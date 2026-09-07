import pytest

from ribosome.commit import (
    CommitLedger,
    commitment_hash,
    join_candidates,
    split_candidates,
)


def test_commitment_hash_deterministic_and_sensitive():
    h1 = commitment_hash("AUGCGC", "salt", 1, "t-1")
    h2 = commitment_hash("AUGCGC", "salt", 1, "t-1")
    assert h1 == h2
    assert commitment_hash("AUGCGU", "salt", 1, "t-1") != h1
    assert commitment_hash("AUGCGC", "salt2", 1, "t-1") != h1
    assert commitment_hash("AUGCGC", "salt", 2, "t-1") != h1
    assert commitment_hash("AUGCGC", "salt", 1, "t-2") != h1


def test_candidates_join_split_roundtrip():
    seqs = ["AUGCGC", "GCAUGU", "UUUAAA"]
    payload = join_candidates(seqs)
    assert split_candidates(payload) == seqs
    assert split_candidates("") == []


def test_commit_and_reveal_happy_path():
    ledger = CommitLedger()
    h = commitment_hash("AUGCGC", "s", 0, "t-1")
    ledger.commit("hk", 0, "t-1", h)
    c = ledger.reveal("hk", 0, "AUGCGC", "s", current_epoch=0)
    assert c.revealed and c.seq == "AUGCGC"


def test_reveal_mismatch_rejected():
    ledger = CommitLedger()
    ledger.commit("hk", 0, "t-1", commitment_hash("AUGCGC", "s", 0, "t-1"))
    with pytest.raises(ValueError):
        ledger.reveal("hk", 0, "AUGCGU", "s", current_epoch=0)
    with pytest.raises(ValueError):
        ledger.reveal("hk", 0, "AUGCGC", "wrong", current_epoch=0)


def test_double_commit_rejected():
    ledger = CommitLedger()
    h = commitment_hash("AUGCGC", "s", 0, "t-1")
    ledger.commit("hk", 0, "t-1", h)
    with pytest.raises(ValueError):
        ledger.commit("hk", 0, "t-1", h)


def test_reveal_without_commit_rejected():
    with pytest.raises(ValueError):
        CommitLedger().reveal("ghost", 0, "AUGCGC", "s", current_epoch=0)


def test_late_reveal_rejected():
    ledger = CommitLedger()
    ledger.commit("hk", 0, "t-1", commitment_hash("AUGCGC", "s", 0, "t-1"))
    with pytest.raises(ValueError):
        ledger.reveal("hk", 0, "AUGCGC", "s", current_epoch=1)


def test_delayed_score_reveal_holds_b_epochs():
    ledger = CommitLedger(score_reveal_delay_b=4)
    ledger.seal_score("val", "hk", epoch=0, score=0.9, current_epoch=0)
    # held at epochs 0..3
    for t in range(4):
        assert ledger.due_scores(t) == {}
    due = ledger.due_scores(4)
    assert ("hk", 0) in due
    assert due[("hk", 0)] == [("val", 0.9)]
    assert ledger.revealed_scores("hk", 0) == [("val", 0.9)]


def test_unrevealed_and_committed_hotkeys():
    ledger = CommitLedger()
    ledger.commit("a", 0, "t", commitment_hash("AUGCGC", "s", 0, "t"))
    ledger.commit("b", 0, "t", commitment_hash("GCAUGC", "s", 0, "t"))
    ledger.reveal("a", 0, "AUGCGC", "s", current_epoch=0)
    assert set(ledger.committed_hotkeys(0)) == {"a", "b"}
    assert [c.hotkey for c in ledger.unrevealed(0)] == ["b"]
