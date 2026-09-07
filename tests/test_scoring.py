from ribosome.constants import DELTA_TM
from ribosome.scoring import (
    base_pair_f1,
    best_candidate_scores,
    composite_score,
    contact_map_rmsd,
    exp_term,
    tm_proxy,
)


def test_perfect_match_scores_one():
    db = "((((....))))...."
    assert tm_proxy(db, db) == 1.0
    assert base_pair_f1(db, db) == 1.0
    assert exp_term(db, db) == 1.0


def test_disjoint_structures_score_zero():
    a = "((((....))))...."
    b = "....((((....))))"
    assert base_pair_f1(a, b) == 0.0


def test_f1_symmetry_and_partial_overlap():
    a = "((((....))))"      # 4 pairs: (0,11)(1,10)(2,9)(3,8)
    b = "(((......)))"      # 3 pairs:  (0,11)(1,10)(2,9)
    f1 = base_pair_f1(a, b)
    assert abs(f1 - 2 * 3 / (4 + 3)) < 1e-12
    assert f1 == base_pair_f1(b, a)


def test_contact_map_rmsd_identical_zero():
    db = "((((....))))..((..))"
    assert contact_map_rmsd(db, db) == 0.0


def test_contact_map_rmsd_positive_for_difference():
    a = "((((....))))"
    b = "((........))"
    assert contact_map_rmsd(a, b) > 0.0


def test_composite_score_validity_gate():
    below = composite_score(DELTA_TM - 0.01, 0.9)
    assert below == 0.0
    at_gate = composite_score(DELTA_TM, 0.9)
    assert at_gate > 0.0
    full = composite_score(1.0, 1.0)
    assert abs(full - 0.7 - 0.3) < 1e-12


def test_best_candidate_scores_picks_argmax():
    target = "((((....))))"
    cands = ["...." + "...." + "....", "((((....))))", "(((......)))"[:12]]
    tm, ex, comp, idx = best_candidate_scores(cands, target)
    assert idx == 1
    assert tm == 1.0 and ex == 1.0
    assert abs(comp - 1.0) < 1e-12


def test_best_candidate_scores_skips_invalid_structure():
    target = "((((....))))"
    cands = ["(((((....", "((((....))))"]
    tm, ex, comp, idx = best_candidate_scores(cands, target)
    assert idx == 1 and tm == 1.0
