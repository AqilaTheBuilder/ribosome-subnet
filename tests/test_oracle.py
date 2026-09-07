import pytest

from ribosome.oracle import (
    RhoFoldOracle,
    StubOracle,
    ViennaRNAOracle,
    get_oracle,
    nussinov_fold,
)
from ribosome.rna import parse_dot_bracket


def test_hairpin_folds_correctly():
    seq = "GGGGAAACCCC"       # 4bp stem, 3nt loop
    assert nussinov_fold(seq) == "((((...))))"


def test_fold_is_deterministic_and_cached():
    seq = "GGCCUUAAGGCCAUUAAGGCC"
    a = nussinov_fold(seq)
    b = nussinov_fold(seq)
    assert a == b
    assert a.count("(") == a.count(")")
    parse_dot_bracket(a)     # balanced


def test_fold_output_balanced_for_random_sequences():
    import random

    rng = random.Random(7)
    for _ in range(10):
        seq = "".join(rng.choices("AUGC", k=50))
        db = nussinov_fold(seq)
        parse_dot_bracket(db)   # raises if unbalanced
        assert len(db) == len(seq)


def test_fold_batch():
    oracle = StubOracle()
    outs = oracle.fold_batch(["GGGGAAACCCC", "GGGGAAACCCC"])
    assert outs[0] == outs[1]


def test_viennarna_missing_binary_raises():
    import shutil

    if shutil.which("RNAfold"):
        pytest.skip("RNAfold installed; cannot test the missing-binary path")
    with pytest.raises(FileNotFoundError):
        ViennaRNAOracle()


def test_rhofold_requires_checkpoint():
    with pytest.raises(NotImplementedError):
        RhoFoldOracle()


def test_get_oracle_factory():
    assert get_oracle("stub").name == "stub-nussinov"
    with pytest.raises(ValueError):
        get_oracle("nonexistent")
