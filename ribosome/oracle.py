"""Refold oracle abstraction.

The chaperone's core tool: given a designed sequence, refold it and hand the
structure back for comparison against the target. Three implementations:

  StubOracle      pure-Python/numpy Nussinov (deterministic, memoized)
  ViennaRNAOracle shells out to `RNAfold` when installed - physics-grade 2D
  RhoFoldOracle   3D refolding (Phase-4; requires a RhoFold+ checkpoint)

Selection: 'auto' -> ViennaRNA if installed else Stub. All oracles return a
dot-bracket string with () pairs only; pseudoknot targets ([]) therefore
cannot be fully matched, which the target pool encodes as difficulty tag.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from typing import List, Tuple

from .rna import dot_bracket_from_pairs, pair_score

MIN_LOOP = 3


class BaseOracle:
    name = "base"

    def fold(self, sequence: str) -> str:
        raise NotImplementedError

    def fold_batch(self, sequences: List[str]) -> List[str]:
        return [self.fold(s) for s in sequences]


# --------------------------------------------------------------------------
# Nussinov core (module-level, lru-cached by sequence)
# --------------------------------------------------------------------------
def _score_matrix(seq, np):
    n = len(seq)
    s = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            s[i, j] = pair_score(seq[i], seq[j])
    return s


def _nussinov_dp(seq: str, np):
    """dp[i, j] = max pairs (weighted) obtainable in seq[i..j]."""
    n = len(seq)
    s = _score_matrix(seq, np)
    dp = np.zeros((n, n))
    for span in range(1, n):
        i_range = range(0, n - span)
        # term1 = dp[i+1, j] ; term2 = dp[i, j-1] ; term3 = dp[i+1, j-1] + s
        t1 = dp[np.arange(1, n - span + 1), np.arange(span, n)]
        t2 = dp[np.arange(0, n - span), np.arange(span - 1, n - 1)]
        t3 = dp[np.arange(1, n - span + 1), np.arange(span - 1, n - 1)] + s[
            np.arange(0, n - span), np.arange(span, n)
        ]
        # only allow the pair when the hairpin loop is big enough
        # loop size = span - 1 >= MIN_LOOP  ->  span >= MIN_LOOP + 1
        pair_term = t3 if span >= MIN_LOOP + 1 else np.zeros(n - span)
        best = np.maximum(np.maximum(t1, t2), pair_term)
        # split term: max_k dp[i, k] + dp[k+1, j], k in [i+1, j-1]
        if span >= 2 * MIN_LOOP + 2:
            k_span = span - 1  # number of k candidates
            # dp[i, k]: diagonal offset d = k - i, d in [1, span-1]
            # dp[k+1, j]: diagonal offset span - d - 1, row k+1 = i + d + 1
            cand = np.full((k_span, n - span), -1.0)
            for d in range(1, span):
                left = dp[np.arange(0, n - span), np.arange(d, n - span + d)]
                right = dp[np.arange(d + 1, n - span + d + 1), np.arange(span, n)]
                cand[d - 1, : len(left)] = left + right[: n - span]
            best = np.maximum(best, cand.max(axis=0))
        dp[np.arange(0, n - span), np.arange(span, n)] = best
    return dp


def _nussinov_traceback(seq: str, dp, np) -> List[Tuple[int, int]]:
    n = len(seq)
    pairs: List[Tuple[int, int]] = []
    stack: List[Tuple[int, int]] = [(0, n - 1)] if n else []
    while stack:
        i, j = stack.pop()
        if i >= j or j - i < MIN_LOOP + 1:
            continue
        cur = dp[i, j]
        if abs(dp[i + 1, j] - cur) < 1e-9:
            stack.append((i + 1, j))
            continue
        if abs(dp[i, j - 1] - cur) < 1e-9:
            stack.append((i, j - 1))
            continue
        if (j - i - 1) >= MIN_LOOP and pair_score(seq[i], seq[j]) > 0:
            inside = dp[i + 1, j - 1] if j - 1 >= i + 1 else 0.0
            if abs(pair_score(seq[i], seq[j]) + inside - cur) < 1e-9:
                pairs.append((i, j))
                stack.append((i + 1, j - 1))
                continue
        split_found = False
        if j - i >= 2 * MIN_LOOP + 3:
            for k in range(i + 1, j):
                if abs(dp[i, k] + dp[k + 1, j] - cur) < 1e-9:
                    stack.append((i, k))
                    stack.append((k + 1, j))
                    split_found = True
                    break
        if not split_found:  # pragma: no cover - numeric safety
            stack.append((i + 1, j))
    return sorted(pairs)


@lru_cache(maxsize=200_000)
def nussinov_fold(sequence: str) -> str:
    import numpy as np

    seq = sequence.upper().replace("T", "U")
    if not seq:
        return ""
    dp = _nussinov_dp(seq, np)
    pairs = _nussinov_traceback(seq, dp, np)
    return dot_bracket_from_pairs(pairs, len(seq))


class StubOracle(BaseOracle):
    name = "stub-nussinov"

    def fold(self, sequence: str) -> str:
        return nussinov_fold(sequence)


class ViennaRNAOracle(BaseOracle):
    """Physics-grade 2D folding via the RNAfold executable."""

    name = "viennarna"

    def __init__(self, binary: str = "RNAfold") -> None:
        if shutil.which(binary) is None:
            raise FileNotFoundError(
                "RNAfold not found; install ViennaRNA or fall back to StubOracle"
            )
        self.binary = binary

    def fold(self, sequence: str) -> str:
        seq = sequence.upper().replace("T", "U")
        out = subprocess.run(
            [self.binary, "--noPS"],
            input=seq, capture_output=True, text=True, check=True,
        ).stdout
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        return lines[1].split()[0] if len(lines) >= 2 else "." * len(seq)


class RhoFoldOracle(BaseOracle):
    """Phase-4 3D refolding adapter (placeholder).

    Set env RIBOSOME_RHOFOLD_CKPT to a RhoFold+ checkpoint to enable. The
    mechanism code depends only on the BaseOracle interface, so wiring this
    in during Phase 4 changes nothing upstream.
    """

    name = "rhofold"

    def __init__(self, checkpoint: str = "") -> None:
        self.checkpoint = checkpoint or os.environ.get("RIBOSOME_RHOFOLD_CKPT", "")
        if not self.checkpoint:
            raise NotImplementedError(
                "RhoFoldOracle requires a checkpoint path "
                "(env RIBOSOME_RHOFOLD_CKPT). See roadmap Phase 4."
            )

    def fold(self, sequence: str) -> str:  # pragma: no cover - adapter stub
        raise NotImplementedError("wire RhoFold+ inference here in Phase 4")


def get_oracle(name: str = "auto") -> BaseOracle:
    """Factory: 'stub' | 'viennarna' | 'rhofold' | 'auto'."""
    if name == "stub":
        return StubOracle()
    if name == "viennarna":
        return ViennaRNAOracle()
    if name == "rhofold":
        return RhoFoldOracle()
    if name == "auto":
        if shutil.which("RNAfold"):
            return ViennaRNAOracle()
        return StubOracle()
    raise ValueError(f"unknown oracle {name!r}")
