"""Arrival generation: a non-homogeneous Poisson process.

The daily demand *shape* is a fixed relative curve (broad AM ramp, sharp peak,
midday bump, low baseline). Counts are pinned by normalising the curve over the
relevant open window; arrivals are drawn by thinning.

- Tier 0: one stream per gate (expected = total_volume * gate.volume_share).
- Tier 1: one stream per (zone, habit-gate) pair (expected = zone.inflow * od),
  generated over the *gate's* open window so closures are respected by
  construction. Each vehicle remembers its origin zone and habit gate.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from .config import GateConfig, SimConfig, ZoneConfig

# numpy>=2 renamed trapz -> trapezoid; support both.
_trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))

Arrival = Tuple[float, str]  # (time_seconds_since_midnight, vehicle_type)


def _gauss(x, mu, sigma):
    return np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def demand_weight(t_h):
    """Relative arrival-rate shape as a function of time-of-day (hours)."""
    return (
        1.00                              # steady daytime baseline
        + 1.50 * _gauss(t_h, 8.00, 0.80)  # broad morning ramp ~07:15-08:45
        + 0.80 * _gauss(t_h, 7.75, 0.40)  # sharper peak ~07:30-08:15
        + 0.60 * _gauss(t_h, 12.0, 0.60)  # midday bump (returnees)
    )


def nhpp_times(open_h: float, close_h: float, expected: float,
               rng: np.random.Generator) -> List[float]:
    """Draw arrival times (seconds) over [open_h, close_h) whose expected count
    is `expected`, following the daily demand shape, via thinning."""
    if expected <= 0 or close_h <= open_h:
        return []
    open_s, close_s = open_h * 3600.0, close_h * 3600.0

    grid_h = np.linspace(open_h, close_h, 2000)
    w = demand_weight(grid_h)
    weight_hours = _trapz(w, grid_h)

    def rate_per_sec(t_s: float) -> float:
        return expected * demand_weight(t_s / 3600.0) / (weight_hours * 3600.0)

    lam_max = expected * w.max() / (weight_hours * 3600.0)
    if lam_max <= 0:
        return []

    times: List[float] = []
    t = open_s
    while True:
        t += rng.exponential(1.0 / lam_max)
        if t >= close_s:
            break
        if rng.random() < rate_per_sec(t) / lam_max:  # thinning accept/reject
            times.append(t)
    return times


def gate_arrivals(gate: GateConfig, sim: SimConfig, rng: np.random.Generator) -> List[Arrival]:
    """Tier 0: arrival stream for one gate."""
    expected = sim.total_daily_volume * gate.volume_share
    times = nhpp_times(gate.open_time_h, gate.close_time_h, expected, rng)
    out: List[Arrival] = []
    for t in times:
        vtype = "commercial" if rng.random() < sim.commercial_fraction else "regular"
        out.append((t, vtype))
    return out


# Tier 1 vehicle: (gate-arrival-decision time, zone_id, habit_gate_id, vtype)
ZoneArrival = Tuple[float, str, str, str]


def zone_arrivals(sim: SimConfig, rng: np.random.Generator) -> List[ZoneArrival]:
    """Tier 1: arrival stream across all zones, one sub-stream per (zone, gate)
    habit pair. Returns vehicles tagged with origin zone and habit gate, sorted
    by time."""
    gate_by_id = {g.id: g for g in sim.gates}
    out: List[ZoneArrival] = []
    for zone in sim.zones:
        for gate_id, prob in zone.od.items():
            if prob <= 0 or gate_id not in gate_by_id:
                continue
            gate = gate_by_id[gate_id]
            expected = zone.inflow * prob
            for t in nhpp_times(gate.open_time_h, gate.close_time_h, expected, rng):
                vtype = "commercial" if rng.random() < sim.commercial_fraction else "regular"
                out.append((t, zone.id, gate_id, vtype))
    out.sort(key=lambda x: x[0])
    return out
