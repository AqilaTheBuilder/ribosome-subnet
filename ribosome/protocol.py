"""Wire protocol: synapses passed between neurons.

When bittensor is installed these mirror bt.Synapse semantics (request ->
response fields on one object). Without bittensor the same dataclasses run
in the offline simulation, so the mechanism layer never imports bittensor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

BT_AVAILABLE = False
try:  # pragma: no cover - depends on environment
    import bittensor as bt  # type: ignore

    BT_AVAILABLE = True
except ImportError:
    bt = None  # type: ignore


@dataclass
class TaskSynapse:
    """Chaperone -> Synthetase: here is your target for this epoch."""

    epoch: int = 0
    target_id: str = ""
    target_dot_bracket: str = ""
    target_length: int = 0
    k_candidates: int = 4
    # responses
    commitment: Optional[str] = None
    miner_hotkey: str = ""


@dataclass
class RevealSynapse:
    """Chaperone -> Synthetase (REVEAL phase): prove your commitment."""

    epoch: int = 0
    nonce: str = ""
    # responses
    sequence: str = ""
    salt: str = ""
    verified: bool = False


@dataclass
class WeightSynapse:
    """Internal: staged weights derived from sealed scores (SET_WEIGHTS)."""

    epoch: int = 0
    scored_epoch: int = 0
    hotkeys: List[str] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)


def task_for(epoch: int, target, k_candidates: int) -> TaskSynapse:
    return TaskSynapse(
        epoch=epoch,
        target_id=target.id,
        target_dot_bracket=target.dot_bracket,
        target_length=target.length,
        k_candidates=k_candidates,
    )


def verify_reveal(task: TaskSynapse, reveal: RevealSynapse, expected_hash: str) -> bool:
    from .commit import commitment_hash

    recomputed = commitment_hash(
        reveal.sequence, reveal.salt, reveal.epoch, task.target_id
    )
    return reveal.verified and recomputed == expected_hash
