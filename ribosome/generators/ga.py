"""Stability-aware GA generator (coupled objective).

Implements the inverse-mRNA preprint's coupled search as a miner synthetase:

    fitness = structural_TM - beta * instability

beta = 2.0 is the paper's Pareto elbow (structure recovery 92% vs 78% for
the pure-structure GA; predicted instability 1.12 -> 0.92; MFE -33.1 ->
-44.2 kcal/mol). Two fitness modes:

  oracle-assisted (default) - candidates ranked by folding them locally with
      the same oracle class validators use (miners legitimately replicate
      the validation pipeline) and scoring tm_proxy - beta * instability.
  surrogate - the dependency-free cheap proxy (instability_surrogate +
      structure_distance_surrogate), used when no local fold budget exists.

The production miner upgrades the instability term to the XGBoost forward
model (MCRMSE 0.356 in the inverse-mRNA preprint) and the structural term
to a full folding objective; the interface is unchanged.
"""
from __future__ import annotations

import random
from typing import List, Tuple

from ..constants import (
    GA_BETA,
    GA_CROSSOVER_RATE,
    GA_ELITE,
    GA_GENERATIONS,
    GA_MUTATION_RATE,
    GA_POPULATION,
    GA_ORACLE_ASSISTED,
    GA_TOURNAMENT_K,
)
from ..rna import COMPLEMENT, pair_compatible, parse_dot_bracket
from ..targets import Target

_NUC = "AUGC"
_STRONG = {frozenset("GC"), frozenset("CG")}   # GC/CG are the strong pairs


def instability_surrogate(seq: str, target: Target) -> float:
    """Cheap instability proxy in [0, ~1]. Higher = less stable."""
    try:
        pairs = parse_dot_bracket(target.dot_bracket)
    except ValueError:
        pairs = []
    paired = {i for p in pairs for i in p}
    n = len(seq) or 1
    if pairs:
        weak_pairs = sum(
            1 for i, j in pairs if frozenset((seq[i], seq[j])) not in _STRONG
        ) / len(pairs)
    else:
        weak_pairs = 0.0
    unpaired_au = sum(
        1 for i in range(len(seq)) if i not in paired and seq[i] in "AU"
    ) / n
    loop_lens = [sum(1 for x in range(i + 1, j) if x not in paired) for i, j in pairs]
    mean_loop = (sum(loop_lens) / len(loop_lens) / n) if loop_lens else 0.0
    return 0.6 * weak_pairs + 0.25 * unpaired_au + 0.15 * mean_loop


def structure_distance_surrogate(seq: str, target: Target) -> float:
    """Fraction of target pairs the candidate cannot form + stray-pair risk."""
    try:
        pairs = parse_dot_bracket(target.dot_bracket)
    except ValueError:
        pairs = []
    if pairs:
        missed = sum(
            1 for i, j in pairs if not pair_compatible(seq[i], seq[j])
        ) / len(pairs)
    else:
        missed = 0.0
    paired = {i for p in pairs for i in p}
    n = len(seq) or 1
    stray = sum(
        1 for i in range(len(seq)) if i not in paired and seq[i] in "GC"
    ) / n
    return missed + 0.1 * stray


def ga_fitness_surrogate(seq: str, target: Target, beta: float = GA_BETA) -> float:
    """Coupled objective without folding; higher is better."""
    return -structure_distance_surrogate(seq, target) - beta * instability_surrogate(
        seq, target
    )


class GAGenerator:
    """Coupled-objective GA over sequences. Deterministic given the rng."""

    name = f"ga-beta{GA_BETA:g}"

    def __init__(
        self,
        beta: float = GA_BETA,
        oracle_assisted: bool = GA_ORACLE_ASSISTED,
        population: int = GA_POPULATION,
        generations: int = GA_GENERATIONS,
    ) -> None:
        self.beta = beta
        self.oracle_assisted = oracle_assisted
        self.population = population
        self.generations = generations

    # ----------------------------------------------------------- main ----
    def generate(self, target: Target, k: int, rng: random.Random) -> List[str]:
        try:
            pairs = parse_dot_bracket(target.dot_bracket)
        except ValueError:
            pairs = []
        n = target.length

        def rand_seq() -> str:
            return "".join(rng.choice(_NUC) for _ in range(n))

        population: List[str] = [self._informed_seed(target, pairs, rng)]
        population += [rand_seq() for _ in range(self.population - 1)]

        fitness = [self.fitness(s, target) for s in population]

        for _ in range(self.generations):
            order = sorted(range(len(population)), key=lambda i: fitness[i], reverse=True)
            next_pop = [population[i] for i in order[: GA_ELITE]]
            while len(next_pop) < self.population:
                a = self._tournament(population, fitness, rng)
                b = self._tournament(population, fitness, rng)
                child = (
                    self._crossover(a, b, rng)
                    if rng.random() < GA_CROSSOVER_RATE
                    else list(a)
                )
                child = self._mutate(child, pairs, rng)
                next_pop.append("".join(child))
            population = next_pop[: self.population]
            fitness = [self.fitness(s, target) for s in population]

        order = sorted(range(len(population)), key=lambda i: fitness[i], reverse=True)
        return [population[i] for i in order[:k]]

    # -------------------------------------------------------- fitness ----
    def fitness(self, seq: str, target: Target) -> float:
        if not self.oracle_assisted:
            return ga_fitness_surrogate(seq, target, self.beta)
        from ..oracle import nussinov_fold
        from ..scoring import tm_proxy

        fold = nussinov_fold(seq)
        tm = tm_proxy(fold, target.dot_bracket)
        return tm - self.beta * instability_from_fold(fold, seq)

    # ----------------------------------------------------------- ops ----
    def _informed_seed(self, target: Target, pairs, rng) -> str:
        chars: List[str] = [rng.choice(_NUC) for _ in range(target.length)]
        for i, j in pairs:
            if not pair_compatible(chars[i], chars[j]):
                chars[i] = rng.choice("GC")
                chars[j] = COMPLEMENT[chars[i]]
        return "".join(chars)

    def _tournament(self, pop, fit, rng) -> str:
        idx = rng.sample(range(len(pop)), min(GA_TOURNAMENT_K, len(pop)))
        return pop[max(idx, key=lambda i: fit[i])]

    def _crossover(self, a: str, b: str, rng) -> List[str]:
        cut = rng.randint(1, len(a) - 1)
        return list(a[:cut] + b[cut:])

    def _mutate(self, seq_chars: List[str], pairs, rng) -> List[str]:
        out = list(seq_chars)
        for i in range(len(out)):
            if rng.random() < GA_MUTATION_RATE:
                out[i] = rng.choice(_NUC)
        for i, j in pairs:  # Lamarckian repair toward target pairing
            if i < len(out) and j < len(out) and not pair_compatible(out[i], out[j]):
                out[j] = COMPLEMENT[out[i]]
        return out


def instability_from_fold(fold: str, seq: str) -> float:
    """Instability of a candidate given its *actual* fold: weak-pair
    fraction + unpaired AU density + normalized loop bulge."""
    try:
        pairs = parse_dot_bracket(fold)
    except ValueError:
        pairs = []
    n = len(seq) or 1
    if pairs:
        weak = sum(
            1 for i, j in pairs if frozenset((seq[i], seq[j])) not in _STRONG
        ) / len(pairs)
    else:
        weak = 0.0
    paired = {i for p in pairs for i in p}
    unpaired_au = sum(1 for i in range(n) if i not in paired and seq[i] in "AU") / n
    loops = [j - i - 1 for i, j in pairs]
    mean_loop = (sum(loops) / len(loops)) / n if loops else 0.0
    return 0.6 * weak + 0.25 * unpaired_au + 0.15 * mean_loop
