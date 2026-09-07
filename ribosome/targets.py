"""Target pool with deterministic rotation.

The pool holds N_pool = 32 RNA targets. Every T_rot = 16 epochs, half the
pool (ROTATE_FRACTION) is replaced by fresh targets drawn deterministically
from the reservoir. Rotation bounds the value of overfitting: a strategy
that memorized current targets decays within T_rot epochs.

Target leakage defense: a commit binds (epoch, target_id); a miner that
commits to a target_id not present in the pool at that epoch is rejected
outright (its claim to know the future pool is either a leak or a fault).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .constants import N_POOL, ROTATE_FRACTION, T_ROT


@dataclass
class Target:
    id: str
    name: str
    sequence: str
    dot_bracket: str
    difficulty: str = "medium"       # easy | medium | hard | pseudoknot
    source: str = "designed"
    note: str = ""

    @property
    def length(self) -> int:
        return len(self.sequence)


@dataclass
class TargetPool:
    targets: List[Target]
    n_pool: int = N_POOL
    t_rot: int = T_ROT
    rotate_fraction: float = ROTATE_FRACTION
    _reservoir: List[Target] = field(default_factory=list)
    _rotation_counter: int = 0

    def __post_init__(self) -> None:
        if len(self.targets) < self.n_pool:
            raise ValueError(
                f"pool needs >= {self.n_pool} targets, got {len(self.targets)}"
            )
        self.active: List[Target] = list(self.targets[: self.n_pool])
        self._reservoir = list(self.targets[self.n_pool :])

    # --------------------------------------------------------- lookup ----
    def get(self, target_id: str) -> Optional[Target]:
        for t in self.active:
            if t.id == target_id:
                return t
        return None

    def contains(self, target_id: str) -> bool:
        return self.get(target_id) is not None

    @staticmethod
    def slot_of(hotkey: str) -> int:
        """Stable slot derived from a hotkey (blake2b, deterministic)."""
        import hashlib

        digest = hashlib.blake2b(hotkey.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big")

    def assignment(self, hotkey: str, epoch: int) -> Target:
        """Deterministic per-epoch miner -> target assignment.

        Miners occupy stable slots; the slot set walks the pool once per
        epoch, so a miner sees different targets across epochs while every
        target keeps a stable population of miners (several miners share a
        target - which is exactly where duplicate detection operates).
        """
        slot = self.slot_of(hotkey) + epoch
        return self.active[slot % len(self.active)]

    # -------------------------------------------------------- rotation ----
    def should_rotate(self, epoch: int) -> bool:
        return epoch > 0 and epoch % self.t_rot == 0

    def rotate(self, seed: int = 0) -> List[Target]:
        """Swap out half the pool for reservoir targets (deterministic)."""
        if not self._reservoir:
            return []
        n_swap = max(1, int(len(self.active) * self.rotate_fraction))
        rng = random.Random(seed + self._rotation_counter)
        out_idx = rng.sample(range(len(self.active)), min(n_swap, len(self.active)))
        outgoing = [self.active[i] for i in out_idx]
        incoming = self._reservoir[: len(out_idx)]
        self._reservoir = self._reservoir[len(out_idx) :] + outgoing
        for i, t in zip(out_idx, incoming):
            self.active[i] = t
        self._rotation_counter += 1
        return incoming

    def snapshot(self) -> Dict[str, List[str]]:
        return {
            "active": [t.id for t in self.active],
            "reservoir": [t.id for t in self._reservoir],
        }
