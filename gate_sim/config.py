"""Configuration model and YAML loader.

All scenario inputs live here as plain dataclasses so that scenarios are *data*
(YAML files), not code. Tier 0 models a single open window per gate at constant
staffing; intra-day shift structure arrives in a later tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

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


@dataclass
class GateConfig:
    id: str
    name: str
    lanes: int                 # physical lane count
    open_lanes: int            # staffed/open lanes for this scenario (<= lanes)
    volume_share: float        # fraction of total daily volume arriving here
    open_time_h: float = 5.5   # 05:30
    close_time_h: float = 21.0 # 21:00 (use 13.5 for a 13:30 close)

    def __post_init__(self) -> None:
        if self.open_lanes > self.lanes:
            raise ValueError(
                f"{self.id}: open_lanes ({self.open_lanes}) exceeds physical lanes ({self.lanes})"
            )
        if self.open_lanes < 1:
            raise ValueError(f"{self.id}: needs at least 1 open lane")


@dataclass
class SimConfig:
    total_daily_volume: int = 50_000
    commercial_fraction: float = 0.03
    delay_threshold_min: float = 15.0  # vehicles waiting longer than this are "delayed"
    seed: int = 42
    service: ServiceConfig = field(default_factory=ServiceConfig)
    gates: List[GateConfig] = field(default_factory=list)

    @property
    def total_open_lanes(self) -> int:
        """Total staffed lanes = guards in use this scenario (Tier 0 proxy for budget)."""
        return sum(g.open_lanes for g in self.gates)


def load_config(path: str) -> SimConfig:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    service = ServiceConfig(**(raw.get("service") or {}))
    gates = [GateConfig(**g) for g in raw.get("gates", [])]

    known = {"total_daily_volume", "commercial_fraction", "delay_threshold_min", "seed"}
    top = {k: raw[k] for k in known if k in raw}
    return SimConfig(service=service, gates=gates, **top)
