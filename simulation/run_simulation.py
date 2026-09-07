"""CLI entry for the offline round simulation."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.harness import SimConfig, Simulation, write_outputs  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Ribosome Network offline simulation")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="data/runs")
    p.add_argument("--k", type=int, default=4, help="candidates per miner")
    args = p.parse_args()

    cfg = SimConfig(epochs=args.epochs, seed=args.seed, k_candidates=args.k)
    sim = Simulation(cfg)
    t0 = time.time()
    sim.run()
    outputs = write_outputs(sim, Path(args.out))
    print(f"simulation complete in {time.time() - t0:.1f}s "
          f"({cfg.epochs} epochs, {cfg.n_miners} miners)")
    print(f"  log:     {outputs['log']}")
    print(f"  summary: {outputs['summary']}")

    import json

    summary = json.loads(Path(outputs["summary"]).read_text())
    print("\nper-strategy results:")
    for name, s in summary["per_strategy"].items():
        print(
            f"  {name:12s} miners={s['n_miners']:2d} mean_TM={s['mean_tm']:.3f} "
            f"accept={s['acceptance_rate']:.2f} dup={s['duplicate_rate']:.2f} "
            f"weight_share={s['mean_weight_share']:.3f}"
        )
    print(f"\nsecurity: {summary['security']}")


if __name__ == "__main__":
    main()
