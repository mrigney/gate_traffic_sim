"""Tier 0 discrete-event simulation.

No road graph: each gate is an independent set of single-server lanes fed by its
own arrival stream. Each open lane is its own server (capacity-1 Resource) so a
single slow vehicle blocks only its lane. Lane 0 of every gate is the
commercial-capable lane: it serves regular traffic too, but commercial vehicles
are restricted to it. Regular vehicles join the shortest eligible lane.
"""

from __future__ import annotations

from typing import List

import numpy as np
import simpy

from .config import GateConfig, SimConfig
from .demand import gate_arrivals
from .metrics import Metrics

COMMERCIAL_LANE = 0  # index of the commercial-capable lane within each gate


def _service_time(vtype: str, sim: SimConfig, rng: np.random.Generator) -> float:
    s = sim.service
    if vtype == "commercial":
        return float(rng.triangular(s.commercial_min, s.commercial_mode, s.commercial_max))
    t = float(rng.triangular(s.regular_min, s.regular_mode, s.regular_max))
    if rng.random() < s.search_prob:  # random search heavy tail
        t += float(rng.uniform(s.search_extra_min, s.search_extra_max))
    return t


def _queue_len(lane: simpy.Resource) -> int:
    return len(lane.queue) + len(lane.users)


def _vehicle(env, gate, lanes, vtype, sim, rng, metrics):
    arrival = env.now
    if vtype == "commercial":
        lane = lanes[COMMERCIAL_LANE]
    else:
        lane = min(lanes, key=_queue_len)  # join shortest eligible lane
    q_on_arrival = _queue_len(lane)

    with lane.request() as req:
        yield req
        start = env.now
        svc = _service_time(vtype, sim, rng)
        yield env.timeout(svc)
    depart = env.now

    metrics.record(
        gate=gate.id,
        vtype=vtype,
        arrival=arrival,
        start=start,
        depart=depart,
        service=svc,
        queue_on_arrival=q_on_arrival,
    )


def _gate_source(env, gate, lanes, arrivals, sim, rng, metrics):
    for t, vtype in arrivals:
        dt = t - env.now
        if dt > 0:
            yield env.timeout(dt)
        env.process(_vehicle(env, gate, lanes, vtype, sim, rng, metrics))


def _queue_monitor(env, gate_lanes, metrics, interval, start_s, max_close_s):
    """Periodically snapshot each gate's queue length. Stops once the gates have
    closed and all queues have drained (so the run can terminate)."""
    if start_s > env.now:
        yield env.timeout(start_s - env.now)
    while True:
        total = 0
        for gid, lanes in gate_lanes.items():
            q = sum(_queue_len(l) for l in lanes)
            metrics.sample_queue(env.now, gid, q)
            total += q
        if env.now > max_close_s and total == 0:
            break
        yield env.timeout(interval)


def run_simulation(sim: SimConfig, sample_interval: float = 60.0) -> Metrics:
    rng = np.random.default_rng(sim.seed)
    env = simpy.Environment()
    metrics = Metrics(sim)

    gate_lanes = {}
    for gate in sim.gates:
        lanes: List[simpy.Resource] = [
            simpy.Resource(env, capacity=1) for _ in range(gate.open_lanes)
        ]
        gate_lanes[gate.id] = lanes
        arrivals = gate_arrivals(gate, sim, rng)
        metrics.note_demand(gate.id, len(arrivals))
        env.process(_gate_source(env, gate, lanes, arrivals, sim, rng, metrics))

    start_s = min(g.open_time_h for g in sim.gates) * 3600.0
    max_close_s = max(g.close_time_h for g in sim.gates) * 3600.0
    env.process(_queue_monitor(env, gate_lanes, metrics, sample_interval, start_s, max_close_s))

    env.run()  # run until the event queue drains (all vehicles cleared)
    return metrics
