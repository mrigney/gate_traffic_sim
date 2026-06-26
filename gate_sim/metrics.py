"""Metric collection and summary.

Every run produces the full panel; the optimizer (later tier) just selects which
metric to target. Times are seconds since midnight.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from .config import SimConfig


@dataclass
class GateSummary:
    gate: str
    name: str
    demand: int            # vehicles generated
    served: int            # vehicles cleared
    avg_wait_s: float
    p95_wait_s: float
    max_wait_s: float
    throughput_per_h: float
    delayed_count: int     # vehicles waiting longer than delay_threshold_min
    max_queue_on_arrival: int
    utilization: float     # busy lane-time / available lane-time


class Metrics:
    def __init__(self, sim: SimConfig) -> None:
        self.sim = sim
        self._gate_cfg = {g.id: g for g in sim.gates}
        self.records: List[dict] = []
        self._demand: Dict[str, int] = defaultdict(int)
        self.queue_samples: List[dict] = []  # periodic queue-length snapshots

    def note_demand(self, gate: str, n: int) -> None:
        self._demand[gate] = n

    def sample_queue(self, time_s: float, gate: str, queue: int) -> None:
        self.queue_samples.append(dict(time=time_s, gate=gate, queue=queue))

    def record(self, *, gate, vtype, arrival, start, depart, service, queue_on_arrival,
               zone=None, habit_gate=None, rerouted=False) -> None:
        self.records.append(
            dict(
                gate=gate,
                vtype=vtype,
                arrival=arrival,
                start=start,
                depart=depart,
                service=service,
                wait=start - arrival,
                queue_on_arrival=queue_on_arrival,
                zone=zone,
                habit_gate=habit_gate,
                rerouted=rerouted,
            )
        )

    # -- summaries -----------------------------------------------------------

    def _summarize(self, gate_id: str, recs: List[dict]) -> GateSummary:
        cfg = self._gate_cfg[gate_id]
        waits = np.array([r["wait"] for r in recs]) if recs else np.array([0.0])
        window_s = (cfg.close_time_h - cfg.open_time_h) * 3600.0
        busy = sum(r["service"] for r in recs)
        delay_cut = self.sim.delay_threshold_min * 60.0
        return GateSummary(
            gate=gate_id,
            name=cfg.name,
            demand=self._demand.get(gate_id, len(recs)),
            served=len(recs),
            avg_wait_s=float(waits.mean()),
            p95_wait_s=float(np.percentile(waits, 95)),
            max_wait_s=float(waits.max()),
            throughput_per_h=len(recs) / (window_s / 3600.0) if window_s else 0.0,
            delayed_count=sum(1 for r in recs if r["wait"] > delay_cut),
            max_queue_on_arrival=max((r["queue_on_arrival"] for r in recs), default=0),
            utilization=busy / (cfg.open_lanes * window_s) if window_s else 0.0,
        )

    def by_gate(self) -> List[GateSummary]:
        grouped: Dict[str, List[dict]] = defaultdict(list)
        for r in self.records:
            grouped[r["gate"]].append(r)
        return [self._summarize(g.id, grouped.get(g.id, [])) for g in self.sim.gates]

    def overall(self) -> dict:
        waits = np.array([r["wait"] for r in self.records]) if self.records else np.array([0.0])
        delay_cut = self.sim.delay_threshold_min * 60.0
        return dict(
            served=len(self.records),
            avg_wait_s=float(waits.mean()),
            p95_wait_s=float(np.percentile(waits, 95)),
            max_wait_s=float(waits.max()),
            delayed_count=sum(1 for r in self.records if r["wait"] > delay_cut),
            total_open_lanes=self.sim.total_open_lanes,
        )

    def timeofday(self, bucket_min: float = 15.0) -> List[dict]:
        """Per-time-of-day-bucket breakdown, by gate and overall (gate='ALL').

        Vehicles are bucketed by *arrival* time, so each row answers "if you
        showed up in this window, what did you experience?"
        """
        width = bucket_min * 60.0
        grouped: Dict[str, List[dict]] = defaultdict(list)
        for r in self.records:
            grouped[r["gate"]].append(r)

        def rows_for(label: str, recs: List[dict]) -> List[dict]:
            buckets: Dict[int, List[dict]] = defaultdict(list)
            for r in recs:
                buckets[int(r["arrival"] // width)].append(r)
            out = []
            for b in sorted(buckets):
                rs = buckets[b]
                waits = [x["wait"] for x in rs]
                out.append(
                    dict(
                        time_h=(b * width + width / 2.0) / 3600.0,
                        gate=label,
                        arrivals=len(rs),
                        avg_wait_s=sum(waits) / len(waits),
                        max_wait_s=max(waits),
                        avg_queue_on_arrival=sum(x["queue_on_arrival"] for x in rs) / len(rs),
                    )
                )
            return out

        rows: List[dict] = []
        for g in self.sim.gates:
            rows += rows_for(g.id, grouped.get(g.id, []))
        rows += rows_for("ALL", self.records)
        return rows

    def reroute_summary(self) -> dict:
        """Tier 1 only: how many vehicles diverted, and each gate's net habit ->
        final flow (negative = lost load to neighbours, positive = absorbed it)."""
        rerouted = [r for r in self.records if r.get("rerouted")]
        habit_n = defaultdict(int)
        final_n = defaultdict(int)
        for r in self.records:
            if r.get("habit_gate") is None:
                continue
            habit_n[r["habit_gate"]] += 1
            final_n[r["gate"]] += 1
        gates = [g.id for g in self.sim.gates]
        net = {g: final_n[g] - habit_n[g] for g in gates}
        return dict(total_rerouted=len(rerouted), net_flow=net,
                    habit=dict(habit_n), final=dict(final_n))

    def queue_timeseries(self, bucket_min: float = 15.0):
        """Average queue length per gate per time bucket, from periodic samples.

        Returns (gate_ids, bucket_center_hours, grid) where grid[g][b] is the
        mean number of vehicles queued (waiting + in service) at gate g, bucket b.
        """
        width = bucket_min * 60.0
        gates = [g.id for g in self.sim.gates]
        buckets: Dict[int, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
        for s in self.queue_samples:
            buckets[int(s["time"] // width)][s["gate"]].append(s["queue"])

        bucket_ids = sorted(buckets)
        centers = [(b * width + width / 2.0) / 3600.0 for b in bucket_ids]
        grid = []
        for gid in gates:
            row = []
            for b in bucket_ids:
                vals = buckets[b].get(gid, [])
                row.append(sum(vals) / len(vals) if vals else 0.0)
            grid.append(row)
        return gates, centers, grid

    def peak_window(self, bucket_min: float = 15.0) -> dict:
        """The overall arrival bucket with the worst average wait."""
        overall_rows = [r for r in self.timeofday(bucket_min) if r["gate"] == "ALL"]
        if not overall_rows:
            return {}
        return max(overall_rows, key=lambda r: r["avg_wait_s"])

    # -- pretty print --------------------------------------------------------

    def format_report(self) -> str:
        def mmss(seconds: float) -> str:
            seconds = int(round(seconds))
            return f"{seconds // 60:d}m{seconds % 60:02d}s"

        dly = f"dly>{self.sim.delay_threshold_min:g}m"
        lines = []
        header = (
            f"{'Gate':<26}{'lanes':>6}{'served':>8}{'avg':>8}{'p95':>8}"
            f"{'max':>8}{'tput/h':>8}{dly:>8}{'util':>7}"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for s in self.by_gate():
            lines.append(
                f"{s.name:<26}{self._gate_cfg[s.gate].open_lanes:>6}{s.served:>8}"
                f"{mmss(s.avg_wait_s):>8}{mmss(s.p95_wait_s):>8}{mmss(s.max_wait_s):>8}"
                f"{s.throughput_per_h:>8.0f}{s.delayed_count:>8}{s.utilization:>7.0%}"
            )
        o = self.overall()
        lines.append("-" * len(header))
        lines.append(
            f"{'OVERALL':<26}{o['total_open_lanes']:>6}{o['served']:>8}"
            f"{mmss(o['avg_wait_s']):>8}{mmss(o['p95_wait_s']):>8}{mmss(o['max_wait_s']):>8}"
            f"{'':>8}{o['delayed_count']:>8}{'':>7}"
        )
        return "\n".join(lines)
