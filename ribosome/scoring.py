"""Scoring metrics for the Ribosome Network chaperone pipeline.

Secondary-structure metrics (offline / Phase-1):
  * base_pair_f1       - precision/recall of predicted vs target pairs
  * contact_map_rmsd   - RMSD over the boolean contact map (0 = identical)
  * tm_proxy           - F1 used as the 2D analog of TM-score

On testnet the RhoFold adapter refolds the sequence into a 3D model and
replaces ``tm_proxy`` with a true TM-score and ``contact_map_rmsd`` with
all-atom RMSD after alignment (see oracle.py). The composite formula and
validity gate are identical in both modes:

  S_i = w_struct * TM + w_exp * exp_term          if best TM >= delta_tm
  S_i = 0                                          otherwise
"""
from __future__ import annotations

import math
from typing import List, Tuple

from .constants import DELTA_TM, W_EXP, W_STRUCT
from .rna import parse_dot_bracket


def _pair_set(dot_bracket: str) -> set:
    return set(parse_dot_bracket(dot_bracket))


def base_pair_f1(pred_db: str, target_db: str) -> float:
    """F1 between predicted and target base-pair sets (2 * |P n Q| / (|P|+|Q|))."""
    p, q = _pair_set(pred_db), _pair_set(target_db)
    if not p and not q:
        return 1.0
    if not p or not q:
        return 0.0
    inter = len(p & q)
    return 2.0 * inter / (len(p) + len(q))


def contact_map_rmsd(pred_db: str, target_db: str) -> float:
    """RMSD between boolean contact maps of predicted vs target structure.

    Both structures are padded to the longer length; the metric is computed
    over the upper triangle (i < j). Identical maps => 0.0.
    """
    n = max(len(pred_db), len(target_db))

    def pad(db: str) -> str:
        return db + "." * (n - len(db))

    p, q = pad(pred_db), pad(target_db)
    try:
        ps, qs = _pair_set(p), _pair_set(q)
    except ValueError:
        return float("inf")
    diffs = 0.0
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = 1.0 if (i, j) in ps else 0.0
            b = 1.0 if (i, j) in qs else 0.0
            diffs += (a - b) ** 2
            count += 1
    return math.sqrt(diffs / count)


def tm_proxy(pred_db: str, target_db: str) -> float:
    """Structural score in [0, 1].

    2D mode: base-pair F1 (symmetric, length-insensitive analog of TM-score).
    3D mode (testnet): replaced by TM-score from RhoFold refolding.
    """
    return base_pair_f1(pred_db, target_db)


def exp_term(pred_db: str, target_db: str) -> float:
    """Expression proxy in [0, 1].

    Uses agreement between the designed structure and the target as a proxy
    for downstream expression fidelity (the preprint's mRNA stability-aware
    selection showed structure-faithful designs transfer better downstream).
    On testnet this slot is filled by the stability forward model
    (XGBoost, MCRMSE 0.356 in the inverse-mRNA preprint).
    """
    return base_pair_f1(pred_db, target_db)


def composite_score(
    structural: float,
    expression: float,
    delta_tm: float = DELTA_TM,
    w_struct: float = W_STRUCT,
    w_exp: float = W_EXP,
) -> float:
    """Validity-gated weighted composite in [0, 1]."""
    if structural < delta_tm:
        return 0.0
    return w_struct * structural + w_exp * expression


def best_candidate_scores(
    candidate_dbs: List[str], target_db: str
) -> Tuple[float, float, float, int]:
    """Evaluate K candidates against a target.

    Returns (best_structural, best_expression, best_composite, argmax_index).
    A submission whose *best* candidate fails the gate scores zero; mining K
    candidates is rewarded only through the best one (plus the diversity
    bonus handled in diversity.py).
    """
    best_tm, best_exp, best_comp, best_idx = 0.0, 0.0, 0.0, -1
    for idx, cand in enumerate(candidate_dbs):
        try:
            tm = tm_proxy(cand, target_db)
            ex = exp_term(cand, target_db)
        except ValueError:
            continue  # invalid structure string -> skip candidate
        comp = composite_score(tm, ex)
        if comp >= best_comp:
            best_tm, best_exp, best_comp, best_idx = tm, ex, comp, idx
    return best_tm, best_exp, best_comp, best_idx
