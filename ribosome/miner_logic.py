"""Synthetase (miner) logic.

Per-epoch flow, faithful to the preprint's 5-phase round:
  1. receive the assigned target (deterministic in epoch + hotkey)
  2. generate K candidates with the configured generator
  3. COMMIT phase: publish sha256(payload || salt || epoch || target_id)
     where payload packs all K candidates (join_candidates)
  4. REVEAL phase: publish (payload, salt) - must hash-match

Strategies (simulation labels): honest | copier | lazy | leaker.
The copier replays another miner's revealed best sequence (Sybil duplicate);
the leaker commits to a target id that is not in the pool (leak/fault);
the lazy miner occasionally withholds the reveal.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .commit import CommitLedger, commitment_hash, join_candidates
from .constants import K_CANDIDATES
from .generators import GAGenerator, Generator, StubGenerator
from .targets import Target, TargetPool


@dataclass
class Synthetase:
    hotkey: str
    generator: Generator
    strategy: str = "honest"
    k_candidates: int = K_CANDIDATES
    seed: int = 0
    _rng: random.Random = field(default_factory=lambda: random.Random(0))
    _pending_reveal: Optional[tuple] = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    # ------------------------------------------------------------ main ----
    def produce(self, target: Target) -> List[str]:
        return self.generator.generate(target, self.k_candidates, self._rng)

    def self_rank(self, target: Target, candidates: List[str]) -> List[str]:
        """Rank candidates with local compute before committing.

        GAGenerator already returns fitness-ordered candidates (its internal
        fitness is the coupled objective); the stub is re-ranked by the
        cheap surrogate. Production miners plug the XGBoost forward model
        here - same interface.
        """
        if isinstance(self.generator, GAGenerator):
            return candidates  # already ordered by the GA fitness
        from .generators.ga import ga_fitness_surrogate

        return sorted(
            candidates, key=lambda s: ga_fitness_surrogate(s, target), reverse=True
        )

    def act(
        self,
        epoch: int,
        pool: TargetPool,
        ledger: CommitLedger,
        copy_source: Optional[str] = None,
        reveal_cache: Optional[Dict[int, Dict[str, str]]] = None,
    ) -> Optional[str]:
        """Run this miner's COMMIT for the epoch. Returns target_id or None."""
        if self.strategy == "leaker":
            fake = Target(
                id=f"leaked-{epoch}", name="future", sequence="AUGC",
                dot_bracket="....",
            )
            if pool.contains(fake.id):
                return None
            ledger.commit(
                self.hotkey, epoch, fake.id,
                commitment_hash("AUGC", f"salt-{self.hotkey}", epoch, fake.id),
            )
            self._pending_reveal = ("AUGC", f"salt-{self.hotkey}")
            return fake.id

        if self.strategy == "copier" and copy_source and reveal_cache is not None:
            past = reveal_cache.get(epoch - 1, {})
            stolen_best = past.get(copy_source)
            if stolen_best is not None:
                target = pool.assignment(self.hotkey, epoch)
                salt = f"copy-{self.hotkey}-{epoch}"
                ledger.commit(
                    self.hotkey, epoch, target.id,
                    commitment_hash(stolen_best, salt, epoch, target.id),
                )
                self._pending_reveal = (stolen_best, salt)
                return target.id

        target = pool.assignment(self.hotkey, epoch)
        candidates = self.produce(target)
        ranked = self.self_rank(target, candidates)
        payload = join_candidates(ranked[: self.k_candidates])
        salt = f"{self.hotkey}-{epoch}"
        ledger.commit(
            self.hotkey, epoch, target.id,
            commitment_hash(payload, salt, epoch, target.id),
        )
        self._pending_reveal = (payload, salt)
        return target.id

    def reveal(self, epoch: int, ledger: CommitLedger, current_epoch: int) -> bool:
        """REVEAL phase; lazy miners withhold with probability 0.1."""
        if self.strategy == "lazy" and self._rng.random() < 0.1:
            return False
        if self._pending_reveal is None:
            return False
        payload, salt = self._pending_reveal
        try:
            ledger.reveal(self.hotkey, epoch, payload, salt, current_epoch)
            return True
        except ValueError:
            return False
