"""Duplicate detection and diversity bonus.

Sybil defense: all K revealed candidates of a miner are shingled into k-mers
(k=3). Two miners whose *best* candidates share Jaccard similarity above
theta_dup = 0.85 are duplicates; the later commit is zeroed (first-commit
kept). The remaining accepted miners receive a diversity bonus proportional
to their mean pairwise distance (1 - Jaccard) within the accepted set,
scaled by w_div = 0.1.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Set, Tuple

from .constants import KMER_K, THETA_DUP, W_DIV


def kmer_shingles(seq: str, k: int = KMER_K) -> Set[str]:
    seq = seq.upper()
    if len(seq) < k:
        return {seq}
    return {seq[i : i + k] for i in range(len(seq) - k + 1)}


def jaccard_similarity(a: str, b: str, k: int = KMER_K) -> float:
    sa, sb = kmer_shingles(a, k), kmer_shingles(b, k)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def similarity_matrix(sequences: Sequence[str]) -> List[List[float]]:
    n = len(sequences)
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        sim[i][i] = 1.0
        for j in range(i + 1, n):
            s = jaccard_similarity(sequences[i], sequences[j])
            sim[i][j] = sim[j][i] = s
    return sim


def detect_duplicates(
    submissions: Dict[str, str],
    commit_order: Dict[str, int],
    theta_dup: float = THETA_DUP,
) -> Tuple[Dict[str, bool], Dict[str, str]]:
    """Zero-sum Sybil filter.

    Parameters
    ----------
    submissions : miner_hotkey -> best candidate sequence this epoch
    commit_order : miner_hotkey -> monotonically increasing commit sequence no.

    Returns
    -------
    is_duplicate : miner -> True if zeroed as a duplicate
    duplicate_of : miner -> hotkey of the kept original (empty if not dup)
    """
    order = sorted(submissions, key=lambda m: commit_order.get(m, 0))
    kept: List[str] = []
    is_duplicate: Dict[str, bool] = {m: False for m in submissions}
    duplicate_of: Dict[str, str] = {m: "" for m in submissions}
    for miner in order:
        seq = submissions[miner]
        original = ""
        for other in kept:
            if jaccard_similarity(seq, submissions[other]) >= theta_dup:
                original = other
                break
        if original:
            is_duplicate[miner] = True
            duplicate_of[miner] = original
        else:
            kept.append(miner)
    return is_duplicate, duplicate_of


def diversity_bonus(accepted_sequences: Sequence[str]) -> List[float]:
    """Mean pairwise distance (1 - Jaccard) of each accepted miner to the
    rest of the accepted set, in [0, 1]. Single accepted miner gets 0."""
    n = len(accepted_sequences)
    if n <= 1:
        return [0.0] * n
    sim = similarity_matrix(list(accepted_sequences))
    bonuses = []
    for i in range(n):
        total = sum(1.0 - sim[i][j] for j in range(n) if j != i)
        bonuses.append(total / (n - 1))
    return bonuses


def apply_diversity_bonus(
    base_scores: Dict[str, float],
    accepted_sequences: Dict[str, str],
    w_div: float = W_DIV,
) -> Dict[str, float]:
    """final_i = base_i + w_div * diversity_i, then re-normalized to [0, 1]."""
    miners = list(accepted_sequences)
    bonuses = diversity_bonus([accepted_sequences[m] for m in miners])
    final = {
        m: base_scores.get(m, 0.0) + w_div * b for m, b in zip(miners, bonuses)
    }
    max_score = max(final.values(), default=0.0)
    if max_score > 1.0:
        final = {m: s / max_score for m, s in final.items()}
    return final
