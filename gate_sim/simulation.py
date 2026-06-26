"""Discrete-event simulation for both tiers.

Each open lane is an independent single-server (capacity-1 Resource) so one slow
vehicle blocks only its lane. Lane 0 of every gate is the commercial-capable
lane: it serves regular traffic too, but commercial vehicles are restricted to
it. Regular vehicles join the shortest eligible lane.

- Tier 0: each gate has its own arrival stream; no routing.
- Tier 1: vehicles originate in zones with a habit gate, travel to the gate, and
  may reroute to a chain-adjacent gate when their habit gate is backed up.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import simpy

from .config import GateConfig, SimConfig
from .demand import gate_arrivals, zone_arrivals
from .metrics import Metrics
from .network import Tier1Network

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


def _serve(env, gate: GateConfig, lanes, vtype, sim, rng, metrics, **extra):
    """Join the gate, wait for a lane, get serviced, record. Shared by both tiers."""
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
        gate=gate.id, vtype=vtype, arrival=arrival, start=start, depart=depart,
        service=svc, queue_on_arrival=q_on_arrival, **extra,
    )


# -- Tier 0 ------------------------------------------------------------------

def _t0_vehicle(env, gate, lanes, vtype, sim, rng, metrics):
    yield from _serve(env, gate, lanes, vtype, sim, rng, metrics)


def _t0_source(env, gate, lanes, arrivals, sim, rng, metrics):
    for t, vtype in arrivals:
        dt = t - env.now
        if dt > 0:
            yield env.timeout(dt)
        env.process(_t0_vehicle(env, gate, lanes, vtype, sim, rng, metrics))


# -- Tier 1 ------------------------------------------------------------------

def _choose_gate(habit, zone_id, now, gate_lanes, gate_cfg, net, sim):
    """Pick the gate minimising estimated (queue wait + travel time) among the
    habit gate and its open chain neighbours. Hysteresis keeps drivers on their
    habit gate unless a neighbour saves more than the switch threshold."""
    avg_svc = sim.service.expected_regular_seconds()

    def cost(g):
        lanes = gate_lanes[g]
        est_wait = (sum(_queue_len(l) for l in lanes) / len(lanes)) * avg_svc
        return est_wait + net.travel_time(zone_id, g)

    habit_cost = cost(habit)
    best, best_cost = habit, habit_cost
    for g in net.chain_neighbors(habit):
        if not net.gate_open(g, now):
            continue
        c = cost(g)
        if c < best_cost:
            best, best_cost = g, c

    if best != habit and (habit_cost - best_cost) < sim.reroute.switch_threshold_min * 60.0:
        best = habit  # improvement too small to bother
    return best


def _t1_vehicle(env, zone_id, habit, vtype, gate_lanes, gate_cfg, net, sim, rng, metrics):
    # Commercial vehicles stick to their habit gate (dedicated commercial lane).
    chosen = habit
    if vtype != "commercial" and sim.reroute.enabled and rng.random() < sim.reroute.check_prob:
        chosen = _choose_gate(habit, zone_id, env.now, gate_lanes, gate_cfg, net, sim)

    rerouted = chosen != habit
    if rerouted:
        # Pay only the *extra* driving for the detour vs. the habit gate.
        extra = net.travel_time(zone_id, chosen) - net.travel_time(zone_id, habit)
        if extra > 0:
            yield env.timeout(extra)

    yield from _serve(
        env, gate_cfg[chosen], gate_lanes[chosen], vtype, sim, rng, metrics,
        zone=zone_id, habit_gate=habit, rerouted=rerouted,
    )


def _t1_source(env, arrivals, gate_lanes, gate_cfg, net, sim, rng, metrics):
    for t, zone_id, habit, vtype in arrivals:
        dt = t - env.now
        if dt > 0:
            yield env.timeout(dt)
        env.process(_t1_vehicle(env, zone_id, habit, vtype, gate_lanes, gate_cfg,
                                net, sim, rng, metrics))


# -- shared: queue monitor + entry point -------------------------------------

def _queue_monitor(env, gate_lanes, metrics, interval, start_s, max_close_s):
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

    gate_cfg = {g.id: g for g in sim.gates}
    gate_lanes: Dict[str, list] = {
        g.id: [simpy.Resource(env, capacity=1) for _ in range(g.open_lanes)]
        for g in sim.gates
    }

    if sim.is_tier1:
        from collections import Counter
        net = Tier1Network(sim)
        arrivals = zone_arrivals(sim, rng)
        habit_demand = Counter(habit for _t, _z, habit, _v in arrivals)  # baseline gate demand
        for gid, n in habit_demand.items():
            metrics.note_demand(gid, n)
        env.process(_t1_source(env, arrivals, gate_lanes, gate_cfg, net, sim, rng, metrics))
    else:
        for gate in sim.gates:
            arrivals = gate_arrivals(gate, sim, rng)
            metrics.note_demand(gate.id, len(arrivals))
            env.process(_t0_source(env, gate, gate_lanes[gate.id], arrivals, sim, rng, metrics))

    start_s = min(g.open_time_h for g in sim.gates) * 3600.0
    max_close_s = max(g.close_time_h for g in sim.gates) * 3600.0
    env.process(_queue_monitor(env, gate_lanes, metrics, sample_interval, start_s, max_close_s))

    env.run()  # run until the event queue drains (all vehicles cleared)
    return metrics
