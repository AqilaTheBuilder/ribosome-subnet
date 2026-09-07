"""Commit-reveal ledger with delayed score reveals.

Miner path (per epoch):
    COMMIT   : sha256(seq || salt || epoch || target_id) published
    REVEAL   : (seq, salt) published; must hash-match the commitment
Validator path:
    EVALUATE : scores computed but kept sealed
    SET_WEIGHTS + B epochs later : score revealed and applied

The B-epoch hold (SCORE_REVEAL_DELAY_B = 4) prevents miners from grinding
validators: by the time a score is public, the weights that consumed it are
already several epochs old, so probing the oracle is not profitable.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def commitment_hash(seq: str, salt: str, epoch: int, target_id: str) -> str:
    payload = f"{seq}|{salt}|{epoch}|{target_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def join_candidates(seqs: List[str]) -> str:
    """Pack the K candidates into one committable payload string."""
    return ";".join(seqs)


def split_candidates(payload: str) -> List[str]:
    return [s for s in payload.split(";") if s]


@dataclass
class Commitment:
    hotkey: str
    epoch: int
    target_id: str
    commit_hash: str
    order: int                      # global arrival order (first-commit kept)
    revealed: bool = False
    seq: Optional[str] = None   # joined candidate payload (see join_candidates)
    salt: Optional[str] = None
    reveal_epoch: Optional[int] = None


@dataclass
class SealedScore:
    validator: str
    hotkey: str
    epoch: int
    score: float
    reveal_epoch: int               # epoch + B


@dataclass
class CommitLedger:
    score_reveal_delay_b: int = 4
    _commits: Dict[Tuple[str, int], Commitment] = field(default_factory=dict)
    _order_counter: int = 0
    _sealed: List[SealedScore] = field(default_factory=list)
    _revealed_scores: Dict[Tuple[str, int], List[Tuple[str, float]]] = field(
        default_factory=dict
    )

    # ---------------------------------------------------------- miners ----
    def commit(self, hotkey: str, epoch: int, target_id: str, commit_hash: str) -> Commitment:
        key = (hotkey, epoch)
        if key in self._commits:
            raise ValueError(f"double commit: {hotkey} epoch {epoch}")
        c = Commitment(
            hotkey=hotkey,
            epoch=epoch,
            target_id=target_id,
            commit_hash=commit_hash,
            order=self._order_counter,
        )
        self._order_counter += 1
        self._commits[key] = c
        return c

    def reveal(self, hotkey: str, epoch: int, seq: str, salt: str, current_epoch: int) -> Commitment:
        c = self._commits.get((hotkey, epoch))
        if c is None:
            raise ValueError(f"reveal without commit: {hotkey} epoch {epoch}")
        expected = commitment_hash(seq, salt, epoch, c.target_id)
        if not hmac.compare_digest(expected, c.commit_hash):
            raise ValueError("commitment mismatch: wrong (seq, salt)")
        if current_epoch > epoch:       # reveal window closed at epoch end
            raise ValueError(f"late reveal: epoch {epoch} reveal in {current_epoch}")
        c.revealed = True
        c.seq = seq
        c.salt = salt
        c.reveal_epoch = current_epoch
        return c

    def get_commit(self, hotkey: str, epoch: int) -> Optional[Commitment]:
        return self._commits.get((hotkey, epoch))

    def committed_hotkeys(self, epoch: int) -> List[str]:
        return [c.hotkey for c in self._commits.values() if c.epoch == epoch]

    def unrevealed(self, epoch: int) -> List[Commitment]:
        return [
            c for (h, e), c in self._commits.items()
            if e == epoch and not c.revealed
        ]

    # ------------------------------------------------------ validators ----
    def seal_score(self, validator: str, hotkey: str, epoch: int, score: float, current_epoch: int) -> SealedScore:
        s = SealedScore(
            validator=validator,
            hotkey=hotkey,
            epoch=epoch,
            score=score,
            reveal_epoch=current_epoch + self.score_reveal_delay_b,
        )
        self._sealed.append(s)
        return s

    def due_scores(self, current_epoch: int) -> Dict[Tuple[str, int], List[Tuple[str, float]]]:
        """Pop sealed scores whose B-epoch hold has elapsed, grouped by
        (hotkey, scored_epoch)."""
        due: Dict[Tuple[str, int], List[Tuple[str, float]]] = {}
        remaining = []
        for s in self._sealed:
            if s.reveal_epoch <= current_epoch:
                due.setdefault((s.hotkey, s.epoch), []).append((s.validator, s.score))
            else:
                remaining.append(s)
        self._sealed = remaining
        for k, v in due.items():
            self._revealed_scores.setdefault(k, []).extend(v)
        return due

    def revealed_scores(self, hotkey: str, epoch: int) -> List[Tuple[str, float]]:
        return self._revealed_scores.get((hotkey, epoch), [])
