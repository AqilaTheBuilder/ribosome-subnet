"""Ribosome Network - a Bittensor subnet for decentralized RNA inverse folding.

Miners (synthetases) design RNA sequences for target structures; validators
(chaperones) refold and score them. This package is the Phase-2 subnet layer:
pure mechanism logic that runs offline (simulation, tests) and behind
bittensor neurons (testnet) unchanged.
"""
from .constants import (
    DELTA_TM,
    EPOCH_LENGTH_SEC,
    N_POOL,
    PHASE_DURATIONS_SEC,
    SCORE_REVEAL_DELAY_B,
    T_ROT,
    THETA_DUP,
    W_DIV,
    Phase,
)
from .targets import Target, TargetPool

__version__ = "0.2.0"

__all__ = [
    "Target",
    "TargetPool",
    "Phase",
    "EPOCH_LENGTH_SEC",
    "PHASE_DURATIONS_SEC",
    "N_POOL",
    "T_ROT",
    "THETA_DUP",
    "W_DIV",
    "DELTA_TM",
    "SCORE_REVEAL_DELAY_B",
]
