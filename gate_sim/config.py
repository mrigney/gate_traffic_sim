"""Configuration model and YAML loader.

Scenarios are *data* (YAML), not code. The same SimConfig drives both tiers:
- Tier 0: per-gate `volume_share` + `total_daily_volume`, no `zones`.
- Tier 1: `zones` (origin zones with inflows, an OD split matrix, and travel
  times), a `chain` adjacency for rerouting, and `reroute` behaviour.

If `zones` is present the runner uses the Tier 1 path; otherwise Tier 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import yaml


@dataclass
class ServiceConfig:
    """Service-time parameters (seconds). Regular times are triangular; a random
    search adds a uniform extra delay. Commercial vehicles get their own (longer)
    triangular distribution."""

    regular_min: float = 12.0
    regular_mode: float = 22.0
    regular_max: float = 40.0
    search_prob: float = 0.04
    search_extra_min: float = 60.0
    search_extra_max: float = 240.0
    commercial_min: float = 90.0
    commercial_mode: float = 150.0
    commercial_max: float = 360.0

    def expected_regular_seconds(self) -> float:
        """Mean regular service time (triangular mean) — used as drivers' rough
        estimate when comparing gates for rerouting."""
        return (self.regular_min + self.regular_mode + self.regular_max) / 3.0


@dataclass
class GateConfig:
    id: str
    name: str
    lanes: int                 # physical lane count
    open_lanes: int            # staffed/open lanes for this scenario (<= lanes)
    volume_share: float = 0.0  # Tier 0 only: fraction of total daily volume
    open_time_h: float = 5.5   # 05:30
    close_time_h: float = 21.0 # 21:00 (use 13.5 for a 13:30 close)

    def __post_init__(self) -> None:
        if self.open_lanes > self.lanes:
            raise ValueError(
                f"{self.id}: open_lanes ({self.open_lanes}) exceeds physical lanes ({self.lanes})"
            )
        if self.open_lanes < 1:
            raise ValueError(f"{self.id}: needs at least 1 open lane")

    def is_open(self, time_s: float) -> bool:
        return self.open_time_h * 3600.0 <= time_s < self.close_time_h * 3600.0


@dataclass
class ZoneConfig:
    """A directional origin zone (Tier 1)."""
    id: str
    name: str
    inflow: int                       # daily vehicles originating here
    od: Dict[str, float]              # gate_id -> habit (baseline) probability
    travel_time_min: Dict[str, float] # gate_id -> free-flow approach time (minutes)

    def travel_time_s(self, gate_id: str) -> float:
        # Large default so undefined pairs are effectively unreachable.
        return self.travel_time_min.get(gate_id, 600.0) * 60.0


@dataclass
class RerouteConfig:
    """Driver rerouting behaviour (Tier 1)."""
    enabled: bool = True
    check_prob: float = 0.25           # fraction who consult real-time info
    switch_threshold_min: float = 3.0  # must save more than this to divert


@dataclass
class SimConfig:
    total_daily_volume: int = 50_000   # Tier 0 scaling; Tier 1 derives from zones
    commercial_fraction: float = 0.03
    delay_threshold_min: float = 15.0  # vehicles waiting longer than this are "delayed"
    seed: int = 42
    service: ServiceConfig = field(default_factory=ServiceConfig)
    gates: List[GateConfig] = field(default_factory=list)
    # Tier 1 additions
    zones: List[ZoneConfig] = field(default_factory=list)
    chain: List[List[str]] = field(default_factory=list)  # adjacency edges [a, b]
    reroute: RerouteConfig = field(default_factory=RerouteConfig)

    @property
    def is_tier1(self) -> bool:
        return bool(self.zones)

    @property
    def total_open_lanes(self) -> int:
        """Total staffed lanes = guards in use this scenario (Tier 0 proxy for budget)."""
        return sum(g.open_lanes for g in self.gates)

    @property
    def effective_volume(self) -> int:
        return sum(z.inflow for z in self.zones) if self.is_tier1 else self.total_daily_volume


def load_config(path: str) -> SimConfig:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    service = ServiceConfig(**(raw.get("service") or {}))
    gates = [GateConfig(**g) for g in raw.get("gates", [])]
    zones = [ZoneConfig(**z) for z in raw.get("zones", [])]
    chain = [list(edge) for edge in raw.get("chain", [])]
    reroute = RerouteConfig(**(raw.get("reroute") or {}))

    known = {"total_daily_volume", "commercial_fraction", "delay_threshold_min", "seed"}
    top = {k: raw[k] for k in known if k in raw}
    return SimConfig(service=service, gates=gates, zones=zones, chain=chain,
                     reroute=reroute, **top)
