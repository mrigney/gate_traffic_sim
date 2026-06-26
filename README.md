# Gate Traffic Simulation

An agent-based discrete-event simulation for optimizing traffic flow through the
controlled-access gates of Redstone Arsenal (Huntsville, AL). It models vehicles
arriving, queueing, and being serviced at each gate, so different staffing and
gate-hour scenarios can be played out and compared.

See [DESIGN.md](DESIGN.md) for the full model design, architecture, and roadmap.

## Status

- **Tier 0** (independent per-gate queues, no road graph) — working.
- **Tier 1** (origin zones → OD split → gates, with congestion-based rerouting) — working.
- **Tier 2** (real OpenStreetMap road network) — planned.

## Setup

```bash
pip install -r requirements.txt
```

`matplotlib` is optional — CSV output works without it; charts are skipped if it's absent.

## Run

```bash
python main.py --config scenarios/mock.yaml     # Tier 0
python main.py --config scenarios/tier1.yaml    # Tier 1 (zones + rerouting)
python main.py --config scenarios/tier1.yaml --no-reroute   # Tier 1 baseline (A/B)
```

Useful flags:

- `--volume 60000` — override total daily volume (Tier 0)
- `--seed 7` — change the random seed
- `--outdir outputs` — where CSV/PNG output is written
- `--bucket-min 15` — time-of-day bucket size (minutes)
- `--no-plots` — skip PNG charts
- `--no-reroute` — disable Tier 1 rerouting (compare against rerouting on)

Scenarios are data, not code — edit or copy [scenarios/tier1.yaml](scenarios/tier1.yaml)
(origin zones, OD matrix, travel times, reroute knobs) to define new ones.

## Output

Each run writes to `outputs/`:

| File | Contents |
|------|----------|
| `vehicles.csv` | every vehicle: arrival, wait, service, queue-on-arrival |
| `gate_summary.csv` | per-gate summary metrics |
| `timeofday.csv` | arrivals & waits by 15-min window |
| `queue_by_time.csv` | average queue length by gate and time |
| `arrivals_by_time.png` | arrival profile by gate |
| `wait_by_time.png` | average wait by arrival time |
| `gate_summary.png` | per-gate avg/p95 wait + utilization |
| `queue_heatmap.png` | queue length over time (gate × time-of-day) |
| `vehicles.csv` (Tier 1) | also includes `zone`, `habit_gate`, `rerouted` per vehicle |

See [DESIGN.md](DESIGN.md) for the full model, the Tier 1 demand/network spec, and the roadmap.
