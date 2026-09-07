"""Target pool loading and construction.

`load_pool()` prefers the versioned manifest in data/targets/pool_v1.json;
when unavailable (e.g. wheel install) it falls back to the deterministic
built-in pool so the mechanism always runs. Structures are constructed
programmatically (never hand-typed) and every manifest entry is validated
for seq/db length equality and bracket balance at build time.

The production pool loads real structures from RNASolo / the Das et al.
(2010) benchmark set - swap the manifest, not the code.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Tuple

from .rna import COMPLEMENT, parse_dot_bracket
from .targets import Target, TargetPool

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
POOL_JSON = DATA_DIR / "targets" / "pool_v1.json"


# ------------------------------------------------------------- builders ----
def make_hairpin(stem: str, loop: str = "AAUA") -> Tuple[str, str]:
    """Stem-loop with a physically legal loop (>= 3nt enforced)."""
    if len(loop) < 3:
        loop = "AAUA"
    comp = "".join(COMPLEMENT[b] for b in reversed(stem))
    seq = stem + loop + comp
    db = "(" * len(stem) + "." * len(loop) + ")" * len(stem)
    return seq, db


def join_parts(parts: List[Tuple[str, str]], linker: str = "AAAA") -> Tuple[str, str]:
    seq, db = "", ""
    for idx, (s, d) in enumerate(parts):
        seq += s
        db += d
        if idx < len(parts) - 1:
            seq += linker
            db += "." * len(linker)
    return seq, db


def make_pseudoknot(stem: int = 4) -> Tuple[str, str]:
    """H-type pseudoknot: S1 pairs with S1', S2 pairs with S2', crossing."""
    s1 = "GGCA"[:stem]
    s2 = "GCGC"[:stem]
    loop1, loop2 = "UUUA", "CAUC"
    s1c = "".join(COMPLEMENT[b] for b in reversed(s1))
    s2c = "".join(COMPLEMENT[b] for b in reversed(s2))
    seq = s1 + loop1 + s2 + loop2 + s1c + s2c
    db = "(" * stem + "." * len(loop1) + "[" * stem + "." * len(loop2) + ")" * stem + "]" * stem
    return seq, db


# ----------------------------------------------------------- validation ----
def validate_target(t: Target) -> None:
    if len(t.sequence) != len(t.dot_bracket):
        raise ValueError(f"{t.id}: len(seq)={len(t.sequence)} != len(db)={len(t.dot_bracket)}")
    parse_dot_bracket(t.dot_bracket)  # raises on imbalance


# ------------------------------------------------------------ built-ins ----
def builtin_targets() -> List[Target]:
    """Deterministic fallback pool: designed motifs + seeded synthetics.

    Designed targets whose reference fold disagrees with the bundled oracle
    are re-referenced to the oracle's own fold (self-consistent) so honest
    miners can always reach the validity gate.
    """
    from .oracle import nussinov_fold
    from .scoring import tm_proxy

    targets: List[Target] = []

    def add(tid, name, seq, db, diff, src, note=""):
        # self-consistency under the bundled oracle
        refold = nussinov_fold(seq)
        recovery = tm_proxy(refold, db)
        if recovery < 0.55:
            db = refold  # re-reference to the oracle's fold
            note = (note + " " if note else "") + "re-referenced to oracle fold"
        targets.append(
            Target(id=tid, name=name, sequence=seq, dot_bracket=db,
                   difficulty=diff, source=src, note=note)
        )

    h1 = make_hairpin("GGGC", "AAUA")
    add("des-hairpin-01", "tandem stem-loops 28nt", *join_parts([h1, h1]),
        "easy", "designed")
    h2 = make_hairpin("GGGGC", "AAAG")
    add("des-hairpin-02", "GC-rich hairpins 28nt", *join_parts([h2, h2]),
        "easy", "designed")
    clover = join_parts([
        make_hairpin("GGCCA", "UUUA"),
        make_hairpin("UGGCC", "AAAC"),
        make_hairpin("GGUUA", "CCCA"),
        make_hairpin("CCGGA", "AAUA"),
    ], linker="CCCC")
    add("des-clover-01", "cloverleaf-like 4-way", *clover, "medium", "designed",
        "tRNA-like multi-loop approximation")
    hammer = join_parts([
        make_hairpin("GGAGC", "UCUCC"),
        make_hairpin("GACCG", "ACUCG"),
        make_hairpin("GGCCU", "CCUAA"),
    ], linker="AA")
    add("des-hammer-01", "hammerhead-like 3-stem", *hammer, "medium", "designed",
        "hammerhead-motif approximation")
    add("des-lariat-01", "nested long-range pairs 44nt",
        *join_parts([make_hairpin("GGGGGG", "AAUA"), make_hairpin("CCCCCC", "AAUA")]),
        "medium", "designed")
    pk_seq, pk_db = make_pseudoknot()
    add("des-pk-01", "H-type pseudoknot 24nt", pk_seq, pk_db, "pseudoknot",
        "designed", "requires []-aware oracle; ()-only folders cannot match")

    from .oracle import nussinov_fold

    rng = random.Random(2026)
    for idx in range(48):
        length = rng.choice([48, 56, 64, 72, 80, 88])
        if idx % 6 == 5:
            # AU-rich draws -> few pairs -> guaranteed hard targets
            seq = "".join(rng.choices("AUGC", k=length, weights=[0.45, 0.45, 0.05, 0.05]))
        else:
            seq = "".join(
                rng.choices("AUGC", k=length, weights=[0.22, 0.22, 0.28, 0.28])
            )
        db = nussinov_fold(seq)
        n_pairs = db.count("(")
        if idx % 6 == 5:
            diff = "hard"    # AU-rich draws: few strong pairs achievable
        else:
            diff = (
                "easy" if n_pairs >= 0.30 * length
                else "medium" if n_pairs >= 0.15 * length
                else "hard"
            )
        add(
            f"syn-{idx:03d}", f"synthetic fold {length}nt", seq, db, diff,
            "synthetic", "folded by bundled Nussinov (self-consistent)",
        )
    return targets


# ------------------------------------------------------------- loading ----
def pool_from_manifest(path: Path) -> TargetPool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets = [Target(**t) for t in payload["targets"]]
    for t in targets:
        validate_target(t)
    return TargetPool(targets=targets, n_pool=payload.get("n_pool", 32))


def load_pool(path: Path = POOL_JSON) -> TargetPool:
    if path.exists():
        try:
            return pool_from_manifest(path)
        except Exception:
            pass
    pool_targets = builtin_targets()
    for t in pool_targets:
        validate_target(t)
    return TargetPool(targets=pool_targets, n_pool=32)
