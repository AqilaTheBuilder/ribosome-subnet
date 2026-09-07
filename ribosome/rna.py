"""RNA sequence and secondary-structure utilities (pure stdlib)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from .constants import DOT_BRACKET_CHARS

_ALPHABET = set("AUGC")

COMPLEMENT = {"A": "U", "U": "A", "G": "C", "C": "G"}

# Nussinov pair energies (simplified Turner-like ranking)
PAIR_SCORE = {
    frozenset("AU"): 1.0,
    frozenset("UA"): 1.0,
    frozenset("GC"): 2.0,
    frozenset("CG"): 2.0,
    frozenset("GU"): 0.5,
    frozenset("UG"): 0.5,
}

OPEN = "([{" 
CLOSE = ")]}"


def is_valid_sequence(seq: str) -> bool:
    """A sequence is valid when non-empty and composed of A/U/G/C only."""
    return isinstance(seq, str) and len(seq) > 0 and set(seq.upper()) <= _ALPHABET


def random_sequence(rng, length: int) -> str:
    return "".join(rng.choices("AUGC", k=length))


def pair_compatible(a: str, b: str) -> bool:
    return frozenset((a, b)) in PAIR_SCORE


def pair_score(a: str, b: str) -> float:
    return PAIR_SCORE.get(frozenset((a, b)), 0.0)


def parse_dot_bracket(db: str) -> List[Tuple[int, int]]:
    """Parse a dot-bracket string (with (), [], {} nesting) into base-pair
    index tuples (i, j), 0-based, i < j. Raises ValueError on imbalance."""
    stacks: dict[int, List[int]] = {0: [], 1: [], 2: []}
    pairs: List[Tuple[int, int]] = []
    for idx, ch in enumerate(db):
        if ch == ".":
            continue
        if ch in OPEN:
            stacks[OPEN.index(ch)].append(idx)
        elif ch in CLOSE:
            kind = CLOSE.index(ch)
            if not stacks[kind]:
                raise ValueError(f"unbalanced {ch!r} at {idx}")
            i = stacks[kind].pop()
            pairs.append((i, idx))
        elif ch in DOT_BRACKET_CHARS:
            raise ValueError(f"unexpected char {ch!r}")
        else:
            raise ValueError(f"invalid dot-bracket char {ch!r}")
    for kind, stack in stacks.items():
        if stack:
            raise ValueError(f"unclosed {OPEN[kind]!r}")
    return sorted(pairs)


def pairs_to_matrix(pairs: List[Tuple[int, int]], length: int):
    """Upper-triangular boolean contact map as a set of (i, j)."""
    return set(pairs)


def pairs_from_sequence_simple(seq: str):
    """Greedy compatible-pairing used by cheap surrogates (NOT a folder):
    walks the sequence and pairs i, j when complementary and unpaired.
    Deterministic; O(n^2) worst case."""
    n = len(seq)
    paired = [False] * n
    pairs = []
    # scan from longest-range to shortest for stem-like behavior
    for span in range(n - 4, 3, -1):
        for i in range(0, n - span):
            j = i + span
            if paired[i] or paired[j]:
                continue
            if pair_compatible(seq[i], seq[j]):
                paired[i] = paired[j] = True
                pairs.append((i, j))
    return sorted(pairs)


def dot_bracket_from_pairs(pairs: List[Tuple[int, int]], length: int) -> str:
    chars = ["."] * length
    for i, j in pairs:
        chars[i] = "("
        chars[j] = ")"
    return "".join(chars)


def min_hairpin_ok(i: int, j: int, min_loop: int = 3) -> bool:
    return j - i - 1 >= min_loop
