"""Pure production logic for the Bittensor-facing neurons.

Everything here is bittensor-free and I/O-free so it can be unit-tested in
CI without the SDK or a chain connection. The neuron classes
(neurons/miner.py, neurons/validator.py) are thin async shells that call
into these primitives; the mechanism package (ribosome/) stays untouched.

Contents
--------
epoch_phase(block, tempo)            block -> (epoch, phase) state machine
ValidatorGate / MinerGate            blacklist decisions (stake, self, sync)
RateLimiter                          token-bucket per hotkey
EMAScoreStore                        smoothed miner scores across epochs
CommitRevealScheduler                native weight commit-reveal bookkeeping
PendingRevealStore                   miner-side reveals with TTL eviction
HotkeyIndex                          hotkey -> uid mapping with re-sync
"""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ribosome.constants import Phase

# --------------------------------------------------------------------------
# Block -> epoch/phase state machine
# --------------------------------------------------------------------------
# One subnet epoch spans TEMPO blocks; the 5 phases partition it proportion-
# ally to PHASE_DURATIONS_SEC (3/6/2/2/2 min). Bittensor tempos are block
# counts, not seconds, so the phase boundaries are block-fractional.


def epoch_phase(
    block: int, tempo: int, phase_blocks: Optional[List[int]] = None
) -> Tuple[int, Phase]:
    """Map a chain block to (epoch, phase).

    phase_blocks: number of blocks per phase, must sum to tempo. Defaults to
    the preprint 3/6/2/2/2 ratio scaled to the tempo.
    """
    if tempo <= 0:
        raise ValueError("tempo must be positive")
    if phase_blocks is None:
        weights = [180, 360, 120, 120, 120]  # from constants.PHASE_DURATIONS_SEC
        total = sum(weights)
        phase_blocks = [max(1, tempo * w // total) for w in weights]
        # fix rounding drift onto the last phase
        phase_blocks[-1] += tempo - sum(phase_blocks)
    if sum(phase_blocks) != tempo:
        raise ValueError("phase_blocks must sum to tempo")
    order = list(Phase)
    offset = block % tempo
    epoch = block // tempo
    acc = 0
    for ph, span in zip(order, phase_blocks):
        acc += span
        if offset < acc:
            return epoch, ph
    return epoch, order[-1]  # pragma: no cover - unreachable


def phase_deadline_block(block: int, tempo: int) -> int:
    """First block of the NEXT phase (or next epoch) after `block`."""
    epoch, phase = epoch_phase(block, tempo)
    order = list(Phase)
    weights = [180, 360, 120, 120, 120]
    total = sum(weights)
    phase_blocks = [max(1, tempo * w // total) for w in weights]
    phase_blocks[-1] += tempo - sum(phase_blocks)
    start = epoch * tempo
    idx = order.index(phase)
    return start + sum(phase_blocks[: idx + 1])


# --------------------------------------------------------------------------
# Blacklist / admission gates
# --------------------------------------------------------------------------
# Miners only accept queries from validators with real stake; validators only
# query neurons registered on the subnet. Both gates deny during metagraph
# desync so a stale view cannot be spoofed.

MIN_VALIDATOR_STAKE = 10_000.0  # tau, production default; override per subnet


class ValidatorGate:
    """Miner-side admission gate for incoming validator queries."""

    def __init__(
        self,
        min_stake: float = MIN_VALIDATOR_STAKE,
        max_staleness_blocks: int = 100,
    ) -> None:
        self.min_stake = min_stake
        self.max_staleness_blocks = max_staleness_blocks

    def check(
        self,
        synapse: object,
        metagraph: object,
        current_block: int,
        own_hotkey: str,
        stake_attr: str = "S",
    ) -> Tuple[bool, str]:
        """Return (allowed, reason). `metagraph` is any object exposing
        `.hotkeys`, `.S` (stake list) and `.block.last_update` per uid."""
        try:
            from ribosome.protocol import synapse_hotkey
        except ImportError:  # pragma: no cover - path-independent fallback
            def synapse_hotkey(s):
                hk = getattr(s, "dendrite_hotkey", None)
                return hk or getattr(getattr(s, "dendrite", None), "hotkey", "")
        hotkey = synapse_hotkey(synapse)
        if not hotkey:
            return False, "missing dendrite hotkey"
        if hotkey == own_hotkey:
            return False, "self-query denied"
        try:
            uid = metagraph.hotkeys.index(hotkey)
        except ValueError:
            return False, "hotkey not registered on subnet"
        stake = float(metagraph.S[uid]) if hasattr(metagraph, "S") else 0.0
        if stake < self.min_stake:
            return False, f"stake {stake:.0f} < min {self.min_stake:.0f} tau"
        last_update = 0
        if hasattr(metagraph, "block") and hasattr(metagraph.block, "last_update"):
            last_update = int(metagraph.block.last_update[uid])
        if last_update and current_block - last_update > self.max_staleness_blocks:
            return False, "validator metagraph entry stale"
        return True, "allowed"


class MinerGate:
    """Validator-side sanity gate before spending query budget."""

    def __init__(self, max_last_step_lag: int = 10_000) -> None:
        self.max_last_step_lag = max_last_step_lag

    def check(self, hotkey: str, metagraph: object) -> Tuple[bool, str]:
        try:
            uid = metagraph.hotkeys.index(hotkey)
        except ValueError:
            return False, "hotkey not registered"
        if hasattr(metagraph, "block") and hasattr(metagraph.block, "last_update"):
            lag = int(metagraph.block.last_update[uid])
            if lag > self.max_last_step_lag:  # pragma: no cover - heuristic
                return False, f"miner inactive for {lag} blocks"
        return True, "allowed"


# --------------------------------------------------------------------------
# Rate limiting (miner axon)
# --------------------------------------------------------------------------
class RateLimiter:
    """Token bucket per hotkey. burst = capacity, refill = tokens/sec."""

    def __init__(self, capacity: float = 10, refill_per_sec: float = 0.2) -> None:
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._buckets: Dict[str, Tuple[float, float]] = {}

    def allow(self, hotkey: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        tokens, last = self._buckets.get(hotkey, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.refill_per_sec)
        if tokens < 1.0:
            self._buckets[hotkey] = (tokens, now)
            return False
        self._buckets[hotkey] = (tokens - 1.0, now)
        return True


# --------------------------------------------------------------------------
# Validator score smoothing (EMA)
# --------------------------------------------------------------------------
class EMAScoreStore:
    """Exponentially-weighted moving average of per-miner scores.

    Raw epoch scores are noisy (oracle variance, target difficulty). Weights
    are set from the EMA so a single lucky epoch cannot dominate, while a
    consistent miner converges with time constant alpha.
    """

    def __init__(self, alpha: float = 0.3) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha in (0, 1]")
        self.alpha = alpha
        self._ema: Dict[str, float] = {}
        self._last_epoch_seen: Dict[str, int] = {}

    def update(self, epoch: int, scores: Dict[str, float]) -> Dict[str, float]:
        """Blend epoch scores into the store; missing miners decay implicitly
        through renormalization at weight-setting time."""
        for hotkey, score in scores.items():
            prev = self._ema.get(hotkey)
            if prev is None or epoch <= self._last_epoch_seen.get(hotkey, -1):
                self._ema[hotkey] = float(score)
            else:
                self._ema[hotkey] = self.alpha * score + (1 - self.alpha) * prev
            self._last_epoch_seen[hotkey] = epoch
        return dict(self._ema)

    def snapshot(self) -> Dict[str, float]:
        return dict(self._ema)


# --------------------------------------------------------------------------
# Native commit-reveal weight scheduling
# --------------------------------------------------------------------------
@dataclass
class PendingReveal:
    uids: List[int]
    weights: List[float]
    salt: bytes
    commit_epoch: int
    reveal_epoch: int


class CommitRevealScheduler:
    """Plans commit-then-reveal weight transactions.

    Bittensor subnets can enforce a commit-reveal period on weights. The
    validator commits a salted hash of its weight vector at epoch E and
    reveals the plaintext at epoch E + period. This scheduler tracks what is
    due, deduplicates by epoch, and survives restarts via to_dict/from_dict.
    """

    def __init__(self, period: int = 1) -> None:
        if period < 0:
            raise ValueError("period >= 0")
        self.period = period
        self.pending: OrderedDict[int, PendingReveal] = OrderedDict()

    def should_commit(self, epoch: int) -> bool:
        if self.period == 0:
            return True  # plain set_weights
        return epoch not in self.pending

    def plan(self, epoch: int, uids: List[int], weights: List[float], salt: bytes) -> PendingReveal:
        if self.period == 0:
            raise ValueError("commit-reveal disabled (period=0)")
        if epoch in self.pending:
            raise ValueError(f"already committed for epoch {epoch}")
        pr = PendingReveal(
            uids=list(uids),
            weights=list(weights),
            salt=bytes(salt),
            commit_epoch=epoch,
            reveal_epoch=epoch + self.period,
        )
        self.pending[epoch] = pr
        return pr

    def due(self, epoch: int) -> List[PendingReveal]:
        out = [p for p in self.pending.values() if p.reveal_epoch <= epoch]
        for p in out:
            self.pending.pop(p.commit_epoch, None)
        return out

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "pending": [
                {
                    "uids": p.uids,
                    "weights": p.weights,
                    "salt": p.salt.hex(),
                    "commit_epoch": p.commit_epoch,
                    "reveal_epoch": p.reveal_epoch,
                }
                for p in self.pending.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CommitRevealScheduler":
        sched = cls(period=int(data.get("period", 1)))
        for item in data.get("pending", []):
            pr = PendingReveal(
                uids=list(item["uids"]),
                weights=list(item["weights"]),
                salt=bytes.fromhex(item["salt"]),
                commit_epoch=int(item["commit_epoch"]),
                reveal_epoch=int(item["reveal_epoch"]),
            )
            sched.pending[pr.commit_epoch] = pr
        return sched


# --------------------------------------------------------------------------
# Miner-side pending reveal store
# --------------------------------------------------------------------------
@dataclass
class PendingRevealEntry:
    epoch: int
    target_id: str
    payload: str
    salt: str
    created_ts: float = field(default_factory=time.time)


class PendingRevealStore:
    """Holds (payload, salt) between COMMIT and REVEAL phases.

    TTL eviction drops entries older than `ttl_epochs` so a miner restart
    cannot leak stale salts, and memory stays bounded under churn.
    """

    def __init__(self, ttl_epochs: int = 2, now_fn=time.time) -> None:
        self.ttl_epochs = ttl_epochs
        self._now_fn = now_fn
        self._entries: Dict[Tuple[str, int], PendingRevealEntry] = {}

    def put(self, hotkey: str, epoch: int, target_id: str, payload: str, salt: str) -> None:
        self._entries[(hotkey, epoch)] = PendingRevealEntry(
            epoch=epoch, target_id=target_id, payload=payload, salt=salt
        )

    def pop(self, hotkey: str, epoch: int) -> Optional[PendingRevealEntry]:
        return self._entries.pop((hotkey, epoch), None)

    def evict_expired(self, current_epoch: int) -> int:
        stale = [
            k for k, v in self._entries.items()
            if current_epoch - v.epoch > self.ttl_epochs
        ]
        for k in stale:
            del self._entries[k]
        return len(stale)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._entries)


# --------------------------------------------------------------------------
# Hotkey -> uid index
# --------------------------------------------------------------------------
class HotkeyIndex:
    """Fresh mapping built at every metagraph sync; O(1) lookups."""

    def __init__(self) -> None:
        self._by_hotkey: Dict[str, int] = {}
        self.version = 0

    def rebuild(self, hotkeys: List[str]) -> None:
        self._by_hotkey = {h: i for i, h in enumerate(hotkeys)}
        self.version += 1

    def uid_of(self, hotkey: str) -> Optional[int]:
        return self._by_hotkey.get(hotkey)

    def hotkey_of(self, uid: int) -> Optional[str]:
        for h, u in self._by_hotkey.items():  # pragma: no cover - small n
            if u == uid:
                return h
        return None

    def uids_for(self, hotkeys: List[str]) -> Tuple[List[int], List[str]]:
        """Return (uids, known_hotkeys) dropping unregistered hotkeys."""
        uids, known = [], []
        for h in hotkeys:
            u = self._by_hotkey.get(h)
            if u is not None:
                uids.append(u)
                known.append(h)
        return uids, known
