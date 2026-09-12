"""Wire protocol: synapses passed between neurons.

Bittensor v11 removed the axon/dendrite/Synapse networking stack: neurons
run their own HTTP layer (neurons/transport.py) and authenticate with
``bittensor.http_auth``. Synapses are therefore plain dataclasses on both
sides - serialized to JSON for the wire, SDK-free for tests. Field names
are the contract; mock mode is a strict subset of the transport format.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypeVar


# --------------------------------------------------------------------------
# TaskSynapse - validator (chaperone) -> miner (synthetase), COMMIT phase
# --------------------------------------------------------------------------
@dataclass
class TaskSynapse:
    """Chaperone -> Synthetase: here is your target for this epoch.

    Miner fills `commitment` (sha256 hex) and echoes `miner_hotkey`."""

    epoch: int = 0
    target_id: str = ""
    target_dot_bracket: str = ""
    target_length: int = 0
    k_candidates: int = 4
    # response fields
    commitment: Optional[str] = None
    miner_hotkey: str = ""


# --------------------------------------------------------------------------
# RevealSynapse - validator -> miner, REVEAL phase
# --------------------------------------------------------------------------
@dataclass
class RevealSynapse:
    """Chaperone -> Synthetase (REVEAL): prove your commitment.

    Miner fills `sequence` (joined K-candidate payload) and `salt`."""

    epoch: int = 0
    nonce: str = ""
    # response fields
    sequence: str = ""
    salt: str = ""
    verified: bool = False


# --------------------------------------------------------------------------
# WeightSynapse - internal bookkeeping (never transported)
# --------------------------------------------------------------------------
@dataclass
class WeightSynapse:
    """Internal: staged weights derived from sealed scores (SET_WEIGHTS)."""

    epoch: int = 0
    scored_epoch: int = 0
    hotkeys: List[str] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)


# --------------------------------------------------------------------------
# serialization (works for pydantic v2 models and dataclasses)
# --------------------------------------------------------------------------
S = TypeVar("S")


def to_dict(synapse: Any) -> Dict[str, Any]:
    """Serialize a synapse to a plain dict for the signed-HTTP transport."""
    if dataclasses.is_dataclass(synapse):
        return dataclasses.asdict(synapse)
    return dict(vars(synapse))


def from_dict(cls: TypeVar, data: Dict[str, Any]) -> Any:
    """Rebuild a synapse from its dict form (ignores transport-only fields)."""
    if dataclasses.is_dataclass(cls):
        known = {f.name for f in dataclasses.fields(cls)}
    else:  # pragma: no cover - plain class
        known = set(vars(cls()).keys())
    return cls(**{k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
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


def synapse_hotkey(synapse) -> str:
    """Authenticated sender hotkey from either wire mode.

    In HTTP mode (v11) the miner sets `dendrite_hotkey` from the verified
    Caller before the mechanism handlers run; in SDK mode the transport
    attaches `dendrite.hotkey` itself."""
    hk = getattr(synapse, "dendrite_hotkey", None)
    if hk:
        return hk
    dendrite = getattr(synapse, "dendrite", None)
    return getattr(dendrite, "hotkey", "") or ""
