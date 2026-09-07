import random

from ribosome.data_targets import load_pool
from ribosome.generators import GAGenerator, StubGenerator
from ribosome.generators.ga import (
    ga_fitness_surrogate,
    instability_surrogate,
    structure_distance_surrogate,
)
from ribosome.oracle import nussinov_fold
from ribosome.rna import is_valid_sequence, pair_compatible, parse_dot_bracket
from ribosome.scoring import tm_proxy


def _easy_target():
    pool = load_pool()
    for t in pool.targets:
        if t.difficulty == "easy" and t.length <= 40:
            return t
    return pool.targets[0]


def test_stub_generator_valid_output():
    target = _easy_target()
    rng = random.Random(3)
    cands = StubGenerator().generate(target, k=4, rng=rng)
    assert len(cands) == 4
    for c in cands:
        assert is_valid_sequence(c)
        assert len(c) == target.length


def test_stub_generator_respects_target_pair_positions():
    target = _easy_target()
    pairs = parse_dot_bracket(target.dot_bracket)
    rng = random.Random(4)
    cands = StubGenerator().generate(target, k=1, rng=rng)
    for i, j in pairs:
        assert pair_compatible(cands[0][i], cands[0][j])


def test_ga_generator_valid_output_deterministic():
    target = _easy_target()
    c1 = GAGenerator().generate(target, k=4, rng=random.Random(11))
    c2 = GAGenerator().generate(target, k=4, rng=random.Random(11))
    assert c1 == c2
    assert len(c1) == 4
    for c in c1:
        assert is_valid_sequence(c) and len(c) == target.length


def test_ga_beats_stub_on_target_recovery():
    """On a non-trivial target the oracle-assisted GA must strictly beat the
    stub; on easy targets both can saturate."""
    pool = load_pool()
    target = next(t for t in pool.targets if t.difficulty in ("medium", "hard"))
    ga_best = GAGenerator().generate(target, k=1, rng=random.Random(5))[0]
    stub_best = StubGenerator().generate(target, k=1, rng=random.Random(5))[0]
    ga_tm = tm_proxy(nussinov_fold(ga_best), target.dot_bracket)
    stub_tm = tm_proxy(nussinov_fold(stub_best), target.dot_bracket)
    assert ga_tm > stub_tm


def test_ga_beta2_recovers_easy_target():
    target = _easy_target()
    best = GAGenerator().generate(target, k=1, rng=random.Random(1))[0]
    tm = tm_proxy(nussinov_fold(best), target.dot_bracket)
    assert tm >= 0.5    # oracle-assisted GA reliably clears the gate


def test_beta_coupling_prefers_stable_sequences():
    """The coupled objective's core claim: for structure-equivalent fills,
    the GC-strong fill has lower instability and higher fitness than the
    AU-weak fill."""
    from ribosome.data_targets import make_hairpin
    from ribosome.targets import Target

    seq_ref, db_ref = make_hairpin("GGGGGG", "AAUA")
    target = Target(id="t-coupling", name="coupling", sequence=seq_ref,
                    dot_bracket=db_ref)
    from ribosome.rna import parse_dot_bracket

    pairs = parse_dot_bracket(db_ref)
    strong = list("AUGC" * (target.length // 4 + 1))[: target.length]
    weak = list(strong)
    for i, j in pairs:
        strong[i], strong[j] = "G", "C"
        weak[i], weak[j] = "A", "U"
    s, w = "".join(strong), "".join(weak)
    assert instability_surrogate(s, target) < instability_surrogate(w, target)
    assert ga_fitness_surrogate(s, target, beta=2.0) > ga_fitness_surrogate(
        w, target, beta=2.0
    )


def test_surrogate_components_in_range():
    target = _easy_target()
    seq = ("AUGCGCAUGCGC" * (target.length // 12 + 1))[: target.length]
    assert 0.0 <= structure_distance_surrogate(seq, target) <= 1.1
    assert instability_surrogate(seq, target) >= 0.0
    assert ga_fitness_surrogate(seq, target, beta=2.0) <= 0.0
