"""Write simulation results to disk: CSV tables always, PNG charts if matplotlib
is available. Nothing here changes the simulation — it only consumes a Metrics.
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import List

from .metrics import Metrics


def _write_csv(path: Path, rows: List[dict], fieldnames: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})


def write_vehicles_csv(metrics: Metrics, path: Path) -> None:
    rows = []
    for r in metrics.records:
        row = dict(r)
        row["arrival_h"] = round(r["arrival"] / 3600.0, 4)
        rows.append(row)
    fields = ["gate", "vtype", "arrival_h", "arrival", "start", "depart",
              "service", "wait", "queue_on_arrival"]
    _write_csv(path, rows, fields)


def write_gate_summary_csv(metrics: Metrics, path: Path) -> None:
    rows = [dataclasses.asdict(s) for s in metrics.by_gate()]
    fields = list(rows[0].keys()) if rows else []
    _write_csv(path, rows, fields)


def write_timeofday_csv(metrics: Metrics, path: Path, bucket_min: float) -> None:
    rows = metrics.timeofday(bucket_min)
    fields = ["time_h", "gate", "arrivals", "avg_wait_s", "max_wait_s",
              "avg_queue_on_arrival"]
    _write_csv(path, rows, fields)


def write_queue_csv(metrics: Metrics, path: Path, bucket_min: float) -> None:
    gates, centers, grid = metrics.queue_timeseries(bucket_min)
    rows = []
    for gi, gid in enumerate(gates):
        for bi, t in enumerate(centers):
            rows.append(dict(time_h=round(t, 4), gate=gid, avg_queue=round(grid[gi][bi], 3)))
    _write_csv(path, rows, ["time_h", "gate", "avg_queue"])


def make_plots(metrics: Metrics, outdir: Path, bucket_min: float) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    tod = metrics.timeofday(bucket_min)
    gates = metrics.sim.gates
    names = {g.id: g.name for g in gates}

    def series(gate_id, key):
        rows = [r for r in tod if r["gate"] == gate_id]
        return [r["time_h"] for r in rows], [r[key] for r in rows]

    # 1) Arrival profile (validates the demand curve shape)
    fig, ax = plt.subplots(figsize=(11, 6))
    for g in gates:
        xs, ys = series(g.id, "arrivals")
        ax.plot(xs, ys, label=names[g.id])
    ax.set(xlabel="Time of day (hour)", ylabel=f"Arrivals per {bucket_min:g} min",
           title="Arrival profile by gate")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "arrivals_by_time.png", dpi=120)
    plt.close(fig)

    # 2) Average wait by time of day (the headline chart)
    fig, ax = plt.subplots(figsize=(11, 6))
    for g in gates:
        xs, ys = series(g.id, "avg_wait_s")
        ax.plot(xs, [y / 60.0 for y in ys], label=names[g.id])
    ax.set(xlabel="Time of day (hour)", ylabel="Average wait (min)",
           title="Average wait by arrival time")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "wait_by_time.png", dpi=120)
    plt.close(fig)

    # 3) Per-gate summary (avg vs p95 wait, with utilization annotated)
    summaries = metrics.by_gate()
    labels = [s.name.split(" - ")[0] for s in summaries]
    avg_m = [s.avg_wait_s / 60.0 for s in summaries]
    p95_m = [s.p95_wait_s / 60.0 for s in summaries]
    x = range(len(summaries))
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar([i - 0.2 for i in x], avg_m, width=0.4, label="avg wait")
    ax.bar([i + 0.2 for i in x], p95_m, width=0.4, label="p95 wait")
    for i, s in zip(x, summaries):
        ax.text(i, max(avg_m[i], p95_m[i]), f"{s.utilization:.0%}",
                ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set(ylabel="Wait (min)", title="Per-gate wait (bar label = utilization)")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outdir / "gate_summary.png", dpi=120)
    plt.close(fig)

    # 4) Queue-length-over-time heatmap (gate x time-of-day)
    gate_ids, centers, grid = metrics.queue_timeseries(bucket_min)
    if centers:
        bw = bucket_min / 60.0
        fig, ax = plt.subplots(figsize=(12, 0.7 * len(gate_ids) + 2))
        im = ax.imshow(
            grid, aspect="auto", origin="lower", cmap="YlOrRd",
            extent=[centers[0] - bw / 2, centers[-1] + bw / 2, 0, len(gate_ids)],
        )
        ax.set_yticks([i + 0.5 for i in range(len(gate_ids))])
        ax.set_yticklabels([names[g].split(" - ")[0] for g in gate_ids])
        ax.set(xlabel="Time of day (hour)",
               title="Queue length over time (avg vehicles waiting + in service)")
        fig.colorbar(im, ax=ax, label="vehicles in queue")
        fig.tight_layout()
        fig.savefig(outdir / "queue_heatmap.png", dpi=120)
        plt.close(fig)
    return True


def write_all(metrics: Metrics, outdir: str, bucket_min: float = 15.0,
              plots: bool = True) -> dict:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    write_vehicles_csv(metrics, out / "vehicles.csv")
    write_gate_summary_csv(metrics, out / "gate_summary.csv")
    write_timeofday_csv(metrics, out / "timeofday.csv", bucket_min)
    write_queue_csv(metrics, out / "queue_by_time.csv", bucket_min)

    plotted = make_plots(metrics, out, bucket_min) if plots else False
    return {"dir": str(out), "plots": plotted}
