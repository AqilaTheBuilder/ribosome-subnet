"""Deterministic stub generator.

Fills target paired positions with complementary nucleotides (preferring GC
on a seeded coin flip, else AU/GU) and samples the rest uniformly. It is
naive on purpose: it defines the floor of honest miner behavior and lets the
GA's value show up in the simulation. Deterministic given (target, rng seed).
"""
from __future__ import annotations

import random
from typing import List

from ..rna import COMPLEMENT, is_valid_sequence, parse_dot_bracket
from ..targets import Target


class StubGenerator:
    name = "stub"

    def generate(self, target: Target, k: int, rng: random.Random) -> List[str]:
        out: List[str] = []
        try:
            pairs = parse_dot_bracket(target.dot_bracket)
        except ValueError:
            pairs = []
        paired_idx = {i for p in pairs for i in p}
        for _ in range(k):
            chars = []
            for pos in range(target.length):
                if pos in paired_idx:
                    chars.append(None)  # fill after, to respect complementarity
                else:
                    chars.append(rng.choice("AUGC"))
            seq = [c if c is not None else "" for c in chars]
            for i, j in pairs:
                if seq[j] == "":
                    # choose partner consistent with what i will be
                    if seq[i] == "":
                        left = rng.choice("AUGC")
                        seq[i] = left
                    comp = COMPLEMENT.get(seq[i], "U")
                    seq[j] = comp if rng.random() < 0.85 else _wobble(seq[i])
                elif seq[i] == "":
                    seq[i] = COMPLEMENT.get(seq[j], "U")
            candidate = "".join(c or rng.choice("AUGC") for c in seq)
            out.append(candidate)
        return [c if is_valid_sequence(c) else "AUGC" * (len(c) // 4 or 1) for c in out]


def _wobble(base: str) -> str:
    return {"G": "U", "U": "G", "A": "U", "C": "U"}.get(base, "U")
