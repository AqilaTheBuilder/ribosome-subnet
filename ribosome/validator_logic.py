"""Chaperone (validator) evaluation pipeline.

Phase-by-phase, faithful to the preprint:

  EVALUATE   for each revealed miner:
      1. refold every revealed candidate with the oracle
      2. score vs the assigned target (best candidate wins)
      3. validity gate delta_tm on the best structural score
      4. duplicate detection on best-candidate sequences (theta_dup)
      5. sealed composite stored; NOT published yet
  SET_WEIGHTS  weights staged from *sealed* scores of epoch-B' whose reveal
               delay has elapsed (delayed score reveals, B=4)
  REVEAL      miners reveal (seq, salt) - chaperones verify hash-match

Weights: final_i = (0.7*TM + 0.3*exp) + 0.1*diversity_i  over accepted
miners (duplicates and gate failures excluded from the accepted set), then
min-max normalized into [0, 1] for Yuma consensus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .commit import CommitLedger, split_candidates
from .constants import (
    DELTA_TM,
    K_CANDIDATES,
    KMER_K,
    SCORE_REVEAL_DELAY_B,
    THETA_DUP,
    W_DIV,
    W_EXP,
    W_STRUCT,
)
from .diversity import apply_diversity_bonus, detect_duplicates
from .oracle import BaseOracle, StubOracle
from .scoring import best_candidate_scores, composite_score
from .targets import TargetPool

ZERO_REASONS = {
    "no_commit": "no commitment published",
    "no_reveal": "commitment never revealed",
    "bad_reveal": "reveal does not hash-match commitment",
    "wrong_target": "committed to a target not in the pool (leak/fault)",
    "all_invalid": "every candidate failed the validity gate",
    "duplicate": "sybil duplicate of an earlier commit",
}


@dataclass
class MinerEvaluation:
    hotkey: str
    target_id: str
    best_tm: float = 0.0
    best_exp: float = 0.0
    base_score: float = 0.0
    final_score: float = 0.0
    diversity: float = 0.0
    accepted: bool = False
    zero_reason: str = ""
    is_duplicate: bool = False
    duplicate_of: str = ""


@dataclass
class EpochEvaluation:
    epoch: int
    per_miner: Dict[str, MinerEvaluation] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)


class Chaperone:
    """Validator-side evaluation engine (oracle-injectable for testing)."""

    def __init__(
        self,
        oracle: Optional[BaseOracle] = None,
        delta_tm: float = DELTA_TM,
        theta_dup: float = THETA_DUP,
        w_div: float = W_DIV,
        w_struct: float = W_STRUCT,
        w_exp: float = W_EXP,
        kmer_k: int = KMER_K,
    ) -> None:
        self.oracle = oracle or StubOracle()
        self.delta_tm = delta_tm
        self.theta_dup = theta_dup
        self.w_div = w_div
        self.w_struct = w_struct
        self.w_exp = w_exp
        self.kmer_k = kmer_k

    # ------------------------------------------------------- evaluate ----
    def evaluate_epoch(
        self,
        epoch: int,
        pool: TargetPool,
        ledger: CommitLedger,
    ) -> EpochEvaluation:
        """Evaluate all revealed commitments of `epoch` (call in REVEAL)."""
        result = EpochEvaluation(epoch=epoch)
        best_seqs: Dict[str, str] = {}
        commit_order: Dict[str, int] = {}

        for hotkey in ledger.committed_hotkeys(epoch):
            commit = ledger.get_commit(hotkey, epoch)
            assert commit is not None
            ev = MinerEvaluation(hotkey=hotkey, target_id=commit.target_id)
            result.per_miner[hotkey] = ev

            if not pool.contains(commit.target_id):
                ev.zero_reason = ZERO_REASONS["wrong_target"]
                continue
            if not commit.revealed:
                ev.zero_reason = ZERO_REASONS["no_reveal"]
                continue

            target = pool.get(commit.target_id)
            assert target is not None
            candidates = split_candidates(commit.seq or "")
            if not candidates:
                ev.zero_reason = ZERO_REASONS["bad_reveal"]
                continue
            cand_dbs = [self.oracle.fold(s) for s in candidates]
            tm, ex, _comp, best_idx = best_candidate_scores(
                cand_dbs, target.dot_bracket
            )
            ev.best_tm, ev.best_exp = tm, ex
            ev.base_score = composite_score(
                tm, ex, self.delta_tm, self.w_struct, self.w_exp
            )
            if tm < self.delta_tm:
                ev.zero_reason = ZERO_REASONS["all_invalid"]
                continue
            ev.accepted = True
            best_seqs[hotkey] = candidates[best_idx if best_idx >= 0 else 0]
            commit_order[hotkey] = commit.order

        # duplicates among accepted miners (first commit kept)
        is_dup, dup_of = detect_duplicates(best_seqs, commit_order, self.theta_dup)
        accepted_seqs = {
            m: s for m, s in best_seqs.items() if not is_dup.get(m, False)
        }
        for miner, ev in result.per_miner.items():
            if ev.accepted and is_dup.get(miner, False):
                ev.is_duplicate = True
                ev.duplicate_of = dup_of.get(miner, "")
                ev.accepted = False
                ev.base_score = 0.0
                ev.zero_reason = ZERO_REASONS["duplicate"]
            elif ev.accepted:
                pass

        # diversity bonus over the surviving accepted set
        base_scores = {
            m: result.per_miner[m].base_score for m in accepted_seqs
        }
        final = apply_diversity_bonus(base_scores, accepted_seqs, self.w_div)
        for miner, seq in accepted_seqs.items():
            ev = result.per_miner[miner]
            ev.final_score = final.get(miner, 0.0)
            ev.diversity = ev.final_score - ev.base_score

        # zero out everyone not accepted
        for hotkey, ev in result.per_miner.items():
            if not ev.accepted:
                ev.final_score = 0.0

        # seal scores with the B-epoch delay (anti-validator-grinding)
        for hotkey, ev in result.per_miner.items():
            ledger.seal_score("chaperone", hotkey, epoch, ev.final_score, epoch)

        result.weights = self._normalize(
            {m: ev.final_score for m, ev in result.per_miner.items() if ev.accepted}
        )
        return result

    # -------------------------------------------------------- helpers ----
    @staticmethod
    def _normalize(scores: Dict[str, float]) -> Dict[str, float]:
        if not scores:
            return {}
        hi = max(scores.values())
        if hi < 1e-12:
            return {m: 1.0 / len(scores) for m in scores}
        raw = {m: s / hi for m, s in scores.items()}
        total = sum(raw.values())
        return {m: v / total for m, v in raw.items()}
