"""Tier 0 runner.

Usage:
    python main.py --config scenarios/mock.yaml
    python main.py --config scenarios/mock.yaml --volume 60000 --seed 7
    python main.py --config scenarios/mock.yaml --outdir outputs --no-plots
"""

from __future__ import annotations

import argparse

from gate_sim import load_config, run_simulation, output


def main() -> None:
    p = argparse.ArgumentParser(description="Gate traffic simulation (Tier 0)")
    p.add_argument("--config", default="scenarios/mock.yaml", help="path to scenario YAML")
    p.add_argument("--volume", type=int, default=None, help="override total daily volume")
    p.add_argument("--seed", type=int, default=None, help="override random seed")
    p.add_argument("--outdir", default="outputs", help="directory for CSV/PNG output")
    p.add_argument("--bucket-min", type=float, default=15.0, help="time-of-day bucket size (min)")
    p.add_argument("--no-plots", action="store_true", help="skip PNG charts")
    args = p.parse_args()

    sim = load_config(args.config)
    if args.volume is not None:
        sim.total_daily_volume = args.volume
    if args.seed is not None:
        sim.seed = args.seed

    metrics = run_simulation(sim)

    print(f"\nScenario: {args.config}")
    print(f"Total daily volume: {sim.total_daily_volume:,} | "
          f"commercial: {sim.commercial_fraction:.0%} | "
          f"staffed lanes: {sim.total_open_lanes} | seed: {sim.seed}\n")
    print(metrics.format_report())

    peak = metrics.peak_window(args.bucket_min)
    if peak:
        print(f"\nWorst {args.bucket_min:g}-min window (all gates): "
              f"{peak['time_h']:.2f}h — avg wait {peak['avg_wait_s'] / 60:.1f} min, "
              f"{peak['arrivals']} arrivals")

    res = output.write_all(metrics, args.outdir, args.bucket_min, plots=not args.no_plots)
    plot_note = "with charts" if res["plots"] else "(matplotlib not installed — CSVs only)"
    print(f"\nWrote CSV output to {res['dir']}/ {plot_note}\n")


if __name__ == "__main__":
    main()
