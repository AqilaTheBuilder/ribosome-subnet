import pytest

from ribosome.rna import (
    COMPLEMENT,
    dot_bracket_from_pairs,
    is_valid_sequence,
    pair_compatible,
    parse_dot_bracket,
    pairs_from_sequence_simple,
)


def test_parse_dot_bracket_simple_hairpin():
    db = "((((....))))"
    pairs = parse_dot_bracket(db)
    assert pairs == [(0, 11), (1, 10), (2, 9), (3, 8)]


def test_parse_dot_bracket_pseudoknot():
    # two independent stems, one in (), one in [] (non-crossing within type)
    db = "((((....))))" + "[[[[....]]]]"
    pairs = parse_dot_bracket(db)
    assert len(pairs) == 8
    round_pairs = {(i, j) for i, j in pairs}
    assert (0, 11) in round_pairs and (12, 23) in round_pairs
    # the two stems interleave (pseudoknot geometry)
    assert (0, 11) < (12, 23)


def test_parse_dot_bracket_rejects_imbalance():
    with pytest.raises(ValueError):
        parse_dot_bracket("(((...))) )")
    with pytest.raises(ValueError):
        parse_dot_bracket("(((..)")
    with pytest.raises(ValueError):
        parse_dot_bracket("....x....")


def test_roundtrip_pairs_to_dot_bracket():
    db = "(((...)))..."
    pairs = parse_dot_bracket(db)
    assert dot_bracket_from_pairs(pairs, len(db)) == db


def test_pair_compatibility_wobble():
    assert pair_compatible("G", "C")
    assert pair_compatible("A", "U")
    assert pair_compatible("G", "U")   # wobble
    assert not pair_compatible("A", "G")
    assert not pair_compatible("C", "C")
    assert COMPLEMENT["G"] == "C"


def test_is_valid_sequence():
    assert is_valid_sequence("AUGCGC")
    assert not is_valid_sequence("AUGTXC")
    assert not is_valid_sequence("")
    assert not is_valid_sequence(42)  # type: ignore[arg-type]


def test_pairs_from_sequence_simple_pairs_complementary():
    seq = "GGGGAAAAACCCC"
    pairs = pairs_from_sequence_simple(seq)
    assert all(pair_compatible(seq[i], seq[j]) for i, j in pairs)
    assert len(pairs) >= 4
