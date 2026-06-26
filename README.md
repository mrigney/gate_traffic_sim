# Gate Traffic Simulation

An agent-based discrete-event simulation for optimizing traffic flow through the
controlled-access gates of Redstone Arsenal (Huntsville, AL). It models vehicles
arriving, queueing, and being serviced at each gate, so different staffing and
gate-hour scenarios can be played out and compared.

See [DESIGN.md](DESIGN.md) for the full model design, architecture, and roadmap.

## Status

**Tier 0** (independent per-gate queues, no road graph) — working. Tier 1 (road
network graph + rerouting) is next.

## Setup

```bash
pip install -r requirements.txt
```

`matplotlib` is optional — CSV output works without it; charts are skipped if it's absent.

## Run

```bash
python main.py --config scenarios/mock.yaml
```

Useful flags:

- `--volume 60000` — override total daily volume
- `--seed 7` — change the random seed
- `--outdir outputs` — where CSV/PNG output is written
- `--bucket-min 15` — time-of-day bucket size (minutes)
- `--no-plots` — skip PNG charts

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

Scenarios are data, not code — edit or copy [scenarios/mock.yaml](scenarios/mock.yaml)
to define new ones.
