"""Ribosome Network - mechanism constants.

All values follow the "Ribosome Network" preprint (synthetic-ribosome subnet)
unless marked otherwise. Change them here; every module reads from this file.

Preprint mapping:
  theta_dup=0.85        duplicate similarity threshold (Jaccard on k-mer shingles)
  w_div=0.1             diversity bonus weight
  N_pool=32, T_rot=16   target pool size / rotation period (epochs)
  B=4                   delayed score reveal horizon (epochs)
  delta_tm=0.35         validity gate on structural score
  epoch 900s, phases 3/6/2/2/2 min
"""
from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------- epoch ----
EPOCH_LENGTH_SEC = 900  # 15 minutes


class Phase(str, Enum):
    COMMIT = "COMMIT"        # miners commit sha256(seq || salt || epoch || target)
    EVALUATE = "EVALUATE"    # chaperones refold + score (scores stay sealed)
    SET_WEIGHTS = "SET_WEIGHTS"  # weights staged from sealed scores
    REVEAL = "REVEAL"        # miners reveal (seq, salt); validators reveal scores after B
    ROTATE = "ROTATE"        # target pool bookkeeping


PHASE_DURATIONS_SEC = {
    Phase.COMMIT: 180,
    Phase.EVALUATE: 360,
    Phase.SET_WEIGHTS: 120,
    Phase.REVEAL: 120,
    Phase.ROTATE: 120,
}
assert sum(PHASE_DURATIONS_SEC.values()) == EPOCH_LENGTH_SEC

# ------------------------------------------------------------ targets ----
N_POOL = 32          # target pool size
T_ROT = 16           # rotate half the pool every T_ROT epochs
ROTATE_FRACTION = 0.5

# -------------------------------------------------------------- miners ----
K_CANDIDATES = 4     # sequences per miner per epoch (preprint default K=8; sim uses 4)
MAX_SEQ_LEN_DELTA = 10  # |len(seq) - len(target)| tolerance

# ----------------------------------------------------------- validators ----
DELTA_TM = 0.35      # validity gate: best-candidate structural score below gate -> zero
W_STRUCT = 0.7       # composite score: structural term
W_EXP = 0.3          # composite score: expression/structure-fidelity term
SCORE_REVEAL_DELAY_B = 4   # chaperones hold sealed scores for B epochs

# ------------------------------------------------- duplicates & diversity ----
THETA_DUP = 0.85     # Jaccard similarity above this => duplicate
KMER_K = 3           # shingle width for duplicate detection
W_DIV = 0.1          # diversity bonus weight

# ------------------------------------------------------------ consensus ----
VALIDATOR_QUORUM = 5         # validators required for an epoch score
TRIMMED_MEAN_TRIM = 1        # trim n highest/lowest validator scores

# --------------------------------------------------------- GA generator ----
GA_BETA = 2.0                # coupled-objective weight (paper elbow)
GA_POPULATION = 12           # sim budget (paper used 200; production scales)
GA_GENERATIONS = 4           # sim budget (paper used 60)
GA_ELITE = 2
GA_TOURNAMENT_K = 3
GA_MUTATION_RATE = 0.08
GA_CROSSOVER_RATE = 0.7
GA_ORACLE_ASSISTED = True    # rank candidates by local oracle fold (miners
                             # legitimately replicate the oracle locally)

# ---------------------------------------------------------------- misc ----
SEED = 42
DOT_BRACKET_CHARS = set("().[]{}")
