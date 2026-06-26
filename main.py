"""Simulation runner (Tier 0 and Tier 1).

Usage:
    python main.py --config scenarios/mock.yaml
    python main.py --config scenarios/tier1.yaml --outdir outputs_tier1
    python main.py --config scenarios/tier1.yaml --no-reroute   # A/B baseline
"""

from __future__ import annotations

import argparse

from gate_sim import load_config, run_simulation, output


def main() -> None:
    p = argparse.ArgumentParser(description="Gate traffic simulation")
    p.add_argument("--config", default="scenarios/mock.yaml", help="path to scenario YAML")
    p.add_argument("--volume", type=int, default=None, help="override total daily volume (Tier 0)")
    p.add_argument("--seed", type=int, default=None, help="override random seed")
    p.add_argument("--outdir", default="outputs", help="directory for CSV/PNG output")
    p.add_argument("--bucket-min", type=float, default=15.0, help="time-of-day bucket size (min)")
    p.add_argument("--no-plots", action="store_true", help="skip PNG charts")
    p.add_argument("--no-reroute", action="store_true", help="disable Tier 1 rerouting (baseline)")
    args = p.parse_args()

    sim = load_config(args.config)
    if args.volume is not None:
        sim.total_daily_volume = args.volume
    if args.seed is not None:
        sim.seed = args.seed
    if args.no_reroute:
        sim.reroute.enabled = False

    metrics = run_simulation(sim)

    mode = "Tier 1 (zones + rerouting)" if sim.is_tier1 else "Tier 0 (per-gate)"
    reroute = "on" if (sim.is_tier1 and sim.reroute.enabled) else "off"
    print(f"\nScenario: {args.config}  [{mode}]")
    print(f"Daily volume: {sim.effective_volume:,} | "
          f"commercial: {sim.commercial_fraction:.0%} | "
          f"staffed lanes: {sim.total_open_lanes} | rerouting: {reroute} | seed: {sim.seed}\n")
    print(metrics.format_report())

    if sim.is_tier1:
        rr = metrics.reroute_summary()
        flow = "  ".join(f"{g}:{n:+d}" for g, n in rr["net_flow"].items())
        print(f"\nRerouted: {rr['total_rerouted']:,} vehicles | net habit->final flow:  {flow}")

    peak = metrics.peak_window(args.bucket_min)
    if peak:
        print(f"\nWorst {args.bucket_min:g}-min window (all gates): "
              f"{peak['time_h']:.2f}h - avg wait {peak['avg_wait_s'] / 60:.1f} min, "
              f"{peak['arrivals']} arrivals")

    res = output.write_all(metrics, args.outdir, args.bucket_min, plots=not args.no_plots)
    if args.no_plots:
        plot_note = "(charts skipped)"
    elif res["plots"]:
        plot_note = "with charts"
    else:
        plot_note = "(matplotlib not installed - CSVs only)"
    print(f"\nWrote output to {res['dir']}/ {plot_note}\n")


if __name__ == "__main__":
    main()
