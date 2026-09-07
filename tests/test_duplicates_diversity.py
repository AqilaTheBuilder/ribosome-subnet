from ribosome.constants import THETA_DUP, W_DIV
from ribosome.diversity import (
    apply_diversity_bonus,
    detect_duplicates,
    diversity_bonus,
    jaccard_similarity,
    kmer_shingles,
)


def test_kmer_shingles_basic():
    s = kmer_shingles("AUGCGC", 3)
    assert s == {"AUG", "UGC", "GCG", "CGC"}


def test_jaccard_identical_one_divergent_low():
    a = "AUGCGCAUGCGCAUGCGC"
    assert jaccard_similarity(a, a) == 1.0
    b = "GGCCGGCCGGCCAAUUGGCC"
    sim = jaccard_similarity(a, b)
    assert sim < 0.3


def test_detect_duplicates_identical_sequences():
    subs = {"m1": "AUGCGCAUGCGC", "m2": "AUGCGCAUGCGC", "m3": "GGCCGGCCAAGG"}
    order = {"m1": 0, "m2": 1, "m3": 2}
    is_dup, dup_of = detect_duplicates(subs, order)
    assert is_dup["m1"] is False
    assert is_dup["m2"] is True and dup_of["m2"] == "m1"
    assert is_dup["m3"] is False


def test_detect_duplicates_keeps_first_commit():
    subs = {"late": "AUGCGCAUGCGC", "early": "AUGCGCAUGCGC"}
    order = {"late": 100, "early": 1}     # early committed first
    is_dup, dup_of = detect_duplicates(subs, order)
    assert is_dup["late"] is True and dup_of["late"] == "early"
    assert is_dup["early"] is False


def test_detect_duplicates_below_threshold_not_flagged():
    a = "AUGCGCAUGCGCAUGCGCAUG"
    b = "AUGCGCAUGCGCAUGCGCGGC"      # one 3-mer changed
    assert jaccard_similarity(a, b) < THETA_DUP
    subs = {"a": a, "b": b}
    is_dup, _ = detect_duplicates(subs, {"a": 0, "b": 1})
    assert not is_dup["b"]


def test_diversity_bonus_single_zero_and_identical_lower():
    assert diversity_bonus(["AUGCGC"]) == [0.0]
    identical = diversity_bonus(["AUGCGCAUG", "AUGCGCAUG", "AUGCGCAUG"])
    divergent = diversity_bonus(["AUGCGCAUG", "GGCCGGCCC", "UUUAUUUAU"])
    assert all(b < 0.05 for b in identical)
    assert all(d > i for d, i in zip(divergent, identical))


def test_apply_diversity_bonus_respects_weight():
    base = {"a": 0.8, "b": 0.4}
    seqs = {"a": "AUGCGCAUGCGC", "b": "GGCCGGCCGGCC"}
    final = apply_diversity_bonus(base, seqs, w_div=W_DIV)
    # both miners gain a non-negative bonus, capped at 1.0 after normalize
    assert final["a"] >= base["a"]
    assert final["b"] >= base["b"]
