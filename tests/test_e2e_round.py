"""End-to-end round tests: the full mechanism against attacks."""
import json

import pytest

from ribosome.commit import CommitLedger
from ribosome.constants import SCORE_REVEAL_DELAY_B
from ribosome.data_targets import load_pool
from ribosome.generators import GAGenerator, StubGenerator
from ribosome.miner_logic import Synthetase
from ribosome.validator_logic import Chaperone
from simulation.harness import SimConfig, Simulation, summarize


def test_single_honest_round_produces_weights():
    pool = load_pool()
    ledger = CommitLedger()
    miner = Synthetase("hk", GAGenerator(), seed=1)
    target = miner.act(0, pool, ledger)
    assert target == pool.assignment("hk", 0).id
    assert miner.reveal(0, ledger, current_epoch=0)
    ch = Chaperone()
    ev = ch.evaluate_epoch(0, pool, ledger)
    record = ev.per_miner["hk"]
    assert record.accepted
    assert record.best_tm >= 0.35
    assert 0.0 < record.final_score <= 1.0
    assert sum(ev.weights.values()) == pytest.approx(1.0)


def test_wrong_target_commit_rejected():
    pool = load_pool()
    ledger = CommitLedger()
    leaker = Synthetase("lk", StubGenerator(), strategy="leaker", seed=2)
    tid = leaker.act(0, pool, ledger)
    assert tid.startswith("leaked-")
    leaker.reveal(0, ledger, current_epoch=0)
    ev = Chaperone().evaluate_epoch(0, pool, ledger)
    assert not ev.per_miner["lk"].accepted
    assert ev.per_miner["lk"].zero_reason == "committed to a target not in the pool (leak/fault)"


def test_duplicate_clone_zeroed_first_commit_kept():
    """A Sybil clone (same generator, same seed, same target) must be zeroed."""
    pool = load_pool()
    ledger = CommitLedger()
    victim = Synthetase("victim", GAGenerator(), seed=7)
    clone = Synthetase("clone", GAGenerator(), seed=7)     # same trajectory
    # force same target: use the victim's target for both
    victim.act(0, pool, ledger)
    victim_target = pool.assignment("victim", 0)

    # place the clone on the victim's target by overriding assignment
    class SameTargetPool:
        def __init__(self, pool, forced_id):
            self.pool, self.forced_id = pool, forced_id
            self.active = pool.active

        def assignment(self, hotkey, epoch):
            return self.pool.get(self.forced_id)

        def contains(self, tid):
            return self.pool.contains(tid)

        def get(self, tid):
            return self.pool.get(tid)

    same = SameTargetPool(pool, victim_target.id)
    clone.act(0, same, ledger)
    victim.reveal(0, ledger, current_epoch=0)
    clone.reveal(0, ledger, current_epoch=0)

    ev = Chaperone().evaluate_epoch(0, same, ledger)  # type: ignore[arg-type]
    v, c = ev.per_miner["victim"], ev.per_miner["clone"]
    assert v.accepted, f"victim should pass the gate, tm={v.best_tm}"
    assert not c.accepted
    assert c.is_duplicate and c.duplicate_of == "victim"
    assert c.zero_reason == "sybil duplicate of an earlier commit"


def test_missing_reveal_scores_zero():
    pool = load_pool()
    ledger = CommitLedger()
    m = Synthetase("hk", StubGenerator(), seed=3)
    m.act(0, pool, ledger)
    # no reveal call
    ev = Chaperone().evaluate_epoch(0, pool, ledger)
    rec = ev.per_miner["hk"]
    assert not rec.accepted and rec.zero_reason == "commitment never revealed"


def test_full_simulation_security_properties(tmp_path):
    """Small-scale full simulation: all four defenses fire."""
    cfg = SimConfig(
        n_ga=2, n_stub=1, n_copier=1, n_lazy=1, n_leaker=1,
        epochs=6, seed=11,
    )
    sim = Simulation(cfg)
    sim.run()
    summary = summarize(sim)

    sec = summary["security"]
    assert sec["duplicates_zeroed"] >= 1       # Sybil clone zeroed
    assert sec["leaker_commits_rejected"] == cfg.epochs  # every leak rejected

    # delayed reveal: no weights applied before epoch B
    for rec in sim.records[: SCORE_REVEAL_DELAY_B]:
        assert rec.weights == {}
    applied = [r for r in sim.records[SCORE_REVEAL_DELAY_B:] if r.weights]
    assert applied, "weights must start flowing after the B-epoch delay"
    for rec in applied:
        assert sum(rec.weights.values()) == pytest.approx(1.0, abs=1e-6)
        for w in rec.weights.values():
            assert 0.0 <= w <= 1.0

    # GA miners out-earn honest stubs per capita (quality is rewarded)
    per = summary["per_strategy"]
    ga = per["ga_strong"]["mean_weight_share"] / cfg.n_ga
    stub = per["stub_honest"]["mean_weight_share"] / cfg.n_stub
    assert ga > stub
