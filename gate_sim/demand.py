"""Arrival generation: a non-homogeneous Poisson process per gate.

The daily demand *shape* is a fixed relative curve (broad AM ramp, sharp peak,
midday bump, low baseline). Each gate's expected count over its open window is
pinned to ``total_daily_volume * volume_share`` by normalising the curve over
that window. Arrivals are drawn by thinning.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from .config import GateConfig, SimConfig

# numpy>=2 renamed trapz -> trapezoid; support both.
_trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))

Arrival = Tuple[float, str]  # (time_seconds_since_midnight, vehicle_type)


def _gauss(x, mu, sigma):
    return np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def demand_weight(t_h):
    """Relative arrival-rate shape as a function of time-of-day (hours).

    Not a probability — just an unnormalised weight. Shapes:
      - broad morning ramp centred ~08:00
      - sharp peak ~07:45 (inside the broad ramp)
      - smaller midday bump ~12:00
      - small all-day baseline
    """
    return (
        1.00                              # steady daytime baseline
        + 1.50 * _gauss(t_h, 8.00, 0.80)  # broad morning ramp ~07:15-08:45
        + 0.80 * _gauss(t_h, 7.75, 0.40)  # sharper peak ~07:30-08:15
        + 0.60 * _gauss(t_h, 12.0, 0.60)  # midday bump (returnees)
    )


def gate_arrivals(gate: GateConfig, sim: SimConfig, rng: np.random.Generator) -> List[Arrival]:
    """Generate the arrival stream for one gate over its open window."""
    open_s = gate.open_time_h * 3600.0
    close_s = gate.close_time_h * 3600.0
    expected = sim.total_daily_volume * gate.volume_share

    # Normalise the weight curve over the gate's open window so that the integral
    # of the rate equals the expected vehicle count.
    grid_h = np.linspace(gate.open_time_h, gate.close_time_h, 2000)
    w = demand_weight(grid_h)
    weight_hours = _trapz(w, grid_h)  # area under weight curve, in weight*hours

    def rate_per_sec(t_s: float) -> float:
        # vehicles per second at time t
        return expected * demand_weight(t_s / 3600.0) / (weight_hours * 3600.0)

    lam_max = expected * w.max() / (weight_hours * 3600.0)
    if lam_max <= 0:
        return []

    arrivals: List[Arrival] = []
    t = open_s
    while True:
        t += rng.exponential(1.0 / lam_max)
        if t >= close_s:
            break
        if rng.random() < rate_per_sec(t) / lam_max:  # thinning accept/reject
            vtype = "commercial" if rng.random() < sim.commercial_fraction else "regular"
            arrivals.append((t, vtype))
    return arrivals
