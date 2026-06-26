"""Tier 1 road network.

Implements the RoadNetwork contract (DESIGN.md §4) for the schematic Huntsville
network: directional origin zones feed gates via arteries/access roads. Tier 1
collapses the full edge path to a per-(zone, gate) travel time lookup; Tier 2
(osmnx) can implement true edge routing behind the same methods.

The reroute "chain" (DESIGN §16.2) is an open path because the river breaks the
ring: Gate 1 -- Gate 9 -- Gate 10 -- Gate 7 -- Gate 3. A driver may only divert
to a chain neighbour of their habit gate.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from .config import SimConfig, ZoneConfig, GateConfig


class Tier1Network:
    def __init__(self, sim: SimConfig) -> None:
        self._zones: Dict[str, ZoneConfig] = {z.id: z for z in sim.zones}
        self._gates: Dict[str, GateConfig] = {g.id: g for g in sim.gates}

        # Build chain adjacency (undirected).
        self._neighbors: Dict[str, List[str]] = defaultdict(list)
        for a, b in sim.chain:
            self._neighbors[a].append(b)
            self._neighbors[b].append(a)

    # -- RoadNetwork contract ------------------------------------------------

    def spawn_points(self) -> List[str]:
        return list(self._zones.keys())

    def gates(self) -> List[str]:
        return list(self._gates.keys())

    def travel_time(self, origin: str, gate: str) -> float:
        """Free-flow approach time (seconds) from a zone to a gate."""
        return self._zones[origin].travel_time_s(gate)

    def reachable_gates(self, origin: str) -> List[str]:
        """Gates a zone would consider: its habit gates plus their chain
        neighbours (so overflow can spill to an adjacent gate)."""
        habit = [g for g, p in self._zones[origin].od.items() if p > 0]
        reach = set(habit)
        for g in habit:
            reach.update(self._neighbors.get(g, []))
        return sorted(reach)

    # -- helpers used by the engine -----------------------------------------

    def chain_neighbors(self, gate: str) -> List[str]:
        return list(self._neighbors.get(gate, []))

    def od(self, origin: str) -> Dict[str, float]:
        return self._zones[origin].od

    def gate_open(self, gate: str, time_s: float) -> bool:
        return self._gates[gate].is_open(time_s)

    def zone(self, origin: str) -> ZoneConfig:
        return self._zones[origin]
