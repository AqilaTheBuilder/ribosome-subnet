"""Build the versioned target pool manifest (data/targets/pool_v1.json).

Every target is validated (seq/db length equality, bracket balance) and
self-consistency under the bundled oracle is recorded. Regenerate after
changing the pool:   python tools/build_pool_manifest.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ribosome.data_targets import builtin_targets, validate_target  # noqa: E402
from ribosome.scoring import tm_proxy  # noqa: E402
from ribosome.oracle import nussinov_fold  # noqa: E402


def main() -> None:
    targets = builtin_targets()
    for t in targets:
        validate_target(t)
    records = []
    difficulty_counts: dict[str, int] = {}
    for t in targets:
        recovery = tm_proxy(nussinov_fold(t.sequence), t.dot_bracket)
        rec = asdict(t)
        rec["oracle_recovery_tm"] = round(recovery, 4)
        records.append(rec)
        difficulty_counts[t.difficulty] = difficulty_counts.get(t.difficulty, 0) + 1

    manifest = {
        "version": "v1",
        "n_pool": 32,
        "t_rot": 16,
        "rotate_fraction": 0.5,
        "oracle": "stub-nussinov",
        "note": (
            "Demo pool: designed motifs + synthetic Nussinov-derived structures. "
            "Production pools swap this manifest for RNASolo / Das et al. (2010) "
            "benchmark structures - the code loads by manifest, not by builder."
        ),
        "difficulty_counts": difficulty_counts,
        "targets": records,
    }
    out = ROOT / "data" / "targets" / "pool_v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(records)} targets)")
    print(f"difficulty: {difficulty_counts}")


if __name__ == "__main__":
    main()
