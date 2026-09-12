"""Tests for the production Bittensor-facing layer (bittensor-free).

Covers neurons/production_logic.py primitives, the bt-optional protocol
module, weight normalization, and the miner's async endpoint logic driven
with fake metagraph/wallet objects (no SDK, no chain).
"""
from __future__ import annotations

import asyncio
import types
from dataclasses import replace

import pytest

from neurons.production_logic import (
    CommitRevealScheduler,
    EMAScoreStore,
    HotkeyIndex,
    MinerGate,
    PendingRevealStore,
    RateLimiter,
    ValidatorGate,
    epoch_phase,
    phase_deadline_block,
)
from ribosome.constants import Phase
from ribosome.data_targets import load_pool
from ribosome.protocol import RevealSynapse, TaskSynapse, synapse_hotkey
from neurons.transport import MetaView


# --------------------------------------------------------------------------
# block -> epoch/phase
# --------------------------------------------------------------------------
class TestEpochPhase:
    def test_default_ratio_mapping(self):
        # tempo 360 -> [72, 144, 48, 48, 48]
        assert epoch_phase(0, 360) == (0, Phase.COMMIT)
        assert epoch_phase(71, 360) == (0, Phase.COMMIT)
        assert epoch_phase(72, 360) == (0, Phase.EVALUATE)
        assert epoch_phase(216, 360) == (0, Phase.SET_WEIGHTS)
        assert epoch_phase(264, 360) == (0, Phase.REVEAL)
        assert epoch_phase(312, 360) == (0, Phase.ROTATE)
        assert epoch_phase(359, 360) == (0, Phase.ROTATE)
        assert epoch_phase(360, 360) == (1, Phase.COMMIT)
        assert epoch_phase(725, 360) == (2, Phase.COMMIT)   # offset 5 < 72
        assert epoch_phase(792, 360) == (2, Phase.EVALUATE)  # 720 + 72

    def test_custom_phase_blocks(self):
        blocks = [10, 10, 10, 10, 10]
        assert epoch_phase(5, 50, blocks) == (0, Phase.COMMIT)
        assert epoch_phase(25, 50, blocks) == (0, Phase.SET_WEIGHTS)
        assert epoch_phase(50, 50, blocks) == (1, Phase.COMMIT)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            epoch_phase(0, 0)
        with pytest.raises(ValueError):
            epoch_phase(0, 100, [10, 10, 10, 10])  # does not sum

    def test_phase_deadline(self):
        assert phase_deadline_block(0, 360) == 72
        assert phase_deadline_block(73, 360) == 216
        assert phase_deadline_block(313, 360) == 360


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------
class FakeMetagraph:
    def __init__(self, hotkeys, stakes, last_updates=None, block=1000):
        self.hotkeys = list(hotkeys)
        self.S = list(stakes)
        self.block = types.SimpleNamespace(
            last_update=list(last_updates or [0] * len(hotkeys))
        )
        self._block = block


class FakeSynapse:
    def __init__(self, hotkey):
        self.dendrite_hotkey = hotkey


VK = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"      # validator
MK = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"      # miner
SELF = "5FLSigC9HGRKVhB9FiEo4Y3koPsNmBmLJbpXg2mp1hXcS59Y"    # this neuron


class TestValidatorGate:
    def test_allows_registered_funded_validator(self):
        gate = ValidatorGate()
        mg = FakeMetagraph([VK, MK], [50_000.0, 0.0], [995, 999])
        ok, reason = gate.check(FakeSynapse(VK), mg, 1000, own_hotkey=SELF)
        assert ok and reason == "allowed"

    def test_denies_unknown_hotkey(self):
        gate = ValidatorGate()
        mg = FakeMetagraph([MK], [0.0])
        ok, reason = gate.check(FakeSynapse(VK), mg, 1000, own_hotkey=SELF)
        assert not ok and "not registered" in reason

    def test_denies_low_stake(self):
        gate = ValidatorGate()
        mg = FakeMetagraph([VK], [9_999.0])
        ok, reason = gate.check(FakeSynapse(VK), mg, 1000, own_hotkey=SELF)
        assert not ok and "stake" in reason

    def test_denies_self_query(self):
        gate = ValidatorGate()
        mg = FakeMetagraph([SELF], [50_000.0])
        ok, reason = gate.check(FakeSynapse(SELF), mg, 1000, own_hotkey=SELF)
        assert not ok and "self" in reason

    def test_denies_stale_validator(self):
        gate = ValidatorGate(max_staleness_blocks=100)
        mg = FakeMetagraph([VK], [50_000.0], [500])
        ok, reason = gate.check(FakeSynapse(VK), mg, 1000, own_hotkey=SELF)
        assert not ok and "stale" in reason

    def test_denies_missing_hotkey(self):
        gate = ValidatorGate()
        mg = FakeMetagraph([VK], [50_000.0])
        ok, reason = gate.check(FakeSynapse(""), mg, 1000, own_hotkey=SELF)
        assert not ok and "missing" in reason


class TestMinerGate:
    def test_registered_ok(self):
        mg = FakeMetagraph([MK], [0.0], [999])
        ok, _ = MinerGate().check(MK, mg)
        assert ok

    def test_unregistered_denied(self):
        mg = FakeMetagraph([VK], [0.0])
        ok, reason = MinerGate().check(MK, mg)
        assert not ok and "not registered" in reason


# --------------------------------------------------------------------------
# rate limiter
# --------------------------------------------------------------------------
class TestRateLimiter:
    def test_burst_then_block(self):
        rl = RateLimiter(capacity=2, refill_per_sec=0.0)
        assert rl.allow("a", now=0.0)
        assert rl.allow("a", now=0.0)
        assert not rl.allow("a", now=0.0)
        assert rl.allow("b", now=0.0)  # separate bucket

    def test_refill_over_time(self):
        rl = RateLimiter(capacity=2, refill_per_sec=1.0)
        assert rl.allow("a", now=0.0)
        assert rl.allow("a", now=0.0)
        assert not rl.allow("a", now=0.0)
        assert rl.allow("a", now=1.5)  # refilled >= 1 token


# --------------------------------------------------------------------------
# EMA store
# --------------------------------------------------------------------------
class TestEMAScoreStore:
    def test_alpha_one_is_raw(self):
        ema = EMAScoreStore(alpha=1.0)
        ema.update(0, {"a": 0.5})
        assert ema.update(1, {"a": 1.0})["a"] == 1.0

    def test_blending(self):
        ema = EMAScoreStore(alpha=0.5)
        ema.update(0, {"a": 0.4})
        out = ema.update(1, {"a": 0.8})
        assert out["a"] == pytest.approx(0.6)

    def test_same_epoch_replaces(self):
        ema = EMAScoreStore(alpha=0.5)
        ema.update(3, {"a": 0.4})
        out = ema.update(3, {"a": 0.2})
        assert out["a"] == pytest.approx(0.2)

    def test_invalid_alpha(self):
        with pytest.raises(ValueError):
            EMAScoreStore(alpha=0.0)


# --------------------------------------------------------------------------
# commit-reveal scheduler
# --------------------------------------------------------------------------
class TestCommitRevealScheduler:
    def test_plan_and_due(self):
        s = CommitRevealScheduler(period=2)
        assert s.should_commit(5)
        s.plan(5, [1, 2], [0.6, 0.4], salt=b"\x01" * 8)
        assert not s.should_commit(5)
        assert s.due(6) == []
        due = s.due(7)
        assert len(due) == 1 and due[0].uids == [1, 2]
        assert s.due(8) == []  # consumed

    def test_double_plan_raises(self):
        s = CommitRevealScheduler(period=1)
        s.plan(0, [1], [1.0], salt=b"0" * 8)
        with pytest.raises(ValueError):
            s.plan(0, [1], [1.0], salt=b"0" * 8)

    def test_disabled_period(self):
        s = CommitRevealScheduler(period=0)
        assert s.should_commit(99)
        with pytest.raises(ValueError):
            s.plan(0, [1], [1.0], salt=b"0" * 8)

    def test_roundtrip(self):
        s = CommitRevealScheduler(period=3)
        s.plan(10, [7, 8], [0.9, 0.1], salt=bytes(range(8)))
        clone = CommitRevealScheduler.from_dict(s.to_dict())
        assert clone.period == 3
        due = clone.due(13)
        assert due[0].salt == bytes(range(8))


# --------------------------------------------------------------------------
# pending reveals
# --------------------------------------------------------------------------
class TestPendingRevealStore:
    def test_put_pop(self):
        store = PendingRevealStore()
        store.put("hk", 3, "t1", "AUGC", "salt")
        entry = store.pop("hk", 3)
        assert entry.payload == "AUGC" and entry.salt == "salt"
        assert store.pop("hk", 3) is None

    def test_ttl_eviction(self):
        store = PendingRevealStore(ttl_epochs=2)
        store.put("hk", 1, "t", "A", "s")
        store.put("hk", 9, "t", "B", "s")
        assert store.evict_expired(10) == 1
        assert store.pop("hk", 1) is None
        assert store.pop("hk", 9) is not None


# --------------------------------------------------------------------------
# hotkey index + weight normalization
# --------------------------------------------------------------------------
class TestHotkeyIndexAndWeights:
    def test_index_basics(self):
        idx = HotkeyIndex()
        idx.rebuild(["a", "b", "c"])
        assert idx.uid_of("b") == 1
        assert idx.uid_of("zz") is None
        uids, known = idx.uids_for(["a", "zz", "c"])
        assert uids == [0, 2] and known == ["a", "c"]

    def test_normalize_sorted_and_dropped(self):
        from neurons.validator import normalize_uid_weights

        idx = HotkeyIndex()
        idx.rebuild(["h2", "h1", "h3"])  # ghost is NOT registered
        scores = {"h1": 1.0, "h2": 3.0, "h3": 0.0, "ghost": 5.0}
        uids, weights = normalize_uid_weights(scores, idx)
        # h3 zero -> excluded; ghost unregistered -> excluded; uid order asc
        assert uids == sorted([0, 1])  # h2 -> uid0, h1 -> uid1
        assert weights == [pytest.approx(0.75), pytest.approx(0.25)]

    def test_normalize_all_zero_uniform(self):
        from neurons.validator import normalize_uid_weights

        idx = HotkeyIndex()
        idx.rebuild(["a", "b"])
        uids, weights = normalize_uid_weights({"a": 0.0, "b": 0.0}, idx)
        assert uids == [0, 1]
        assert weights == [pytest.approx(0.5), pytest.approx(0.5)]


# --------------------------------------------------------------------------
# protocol fallback + hotkey extraction
# --------------------------------------------------------------------------
class TestProtocolFallback:
    def test_dataclass_fields(self):
        s = TaskSynapse(epoch=3, target_id="t")
        assert s.commitment is None and s.k_candidates == 4
        r = RevealSynapse(epoch=3, nonce="n")
        assert r.verified is False

    def test_synapse_hotkey_both_shapes(self):
        s1 = FakeSynapse("hk-1")
        assert synapse_hotkey(s1) == "hk-1"
        s2 = types.SimpleNamespace(dendrite=types.SimpleNamespace(hotkey="hk-2"))
        assert synapse_hotkey(s2) == "hk-2"
        assert synapse_hotkey(types.SimpleNamespace()) == ""


# --------------------------------------------------------------------------
# miner endpoint logic with fakes (no bittensor)
# --------------------------------------------------------------------------
def make_miner():
    from neurons.miner import SynthetaseNeuron

    neuron = SynthetaseNeuron.__new__(SynthetaseNeuron)
    neuron.args = types.SimpleNamespace(
        strict_assignment=True, rate_capacity=5, rate_refill=100.0,
        min_stake=10_000.0, network="test", netuid=1, public_ip="",
    )
    neuron.hotkey = SELF
    fake_mg = FakeMetagraph([VK, SELF], [50_000.0, 1.0], [999, 999])
    fake_mg._block = 1000
    neuron.meta = MetaView(fake_mg)
    neuron.mg = types.SimpleNamespace(block=1000, tempo=360)
    neuron.pool = load_pool()
    neuron.synth = types.SimpleNamespace(
        hotkey=SELF, k_candidates=4,
        produce=lambda target: ["AUGC" * 5, "GGCC" * 5, "UUUA" * 5, "ACGU" * 5],
        self_rank=lambda t, c: c,
    )
    from neurons.production_logic import PendingRevealStore, RateLimiter, ValidatorGate

    neuron.pending = PendingRevealStore()
    neuron.rate = RateLimiter(capacity=5, refill_per_sec=100.0)
    neuron.gate = ValidatorGate(min_stake=10_000.0)
    return neuron


class TestMinerEndpoints:
    def test_forward_task_commits(self):
        neuron = make_miner()
        target = neuron.pool.assignment(SELF, 1)  # miner derives own assignment
        syn = TaskSynapse(
            epoch=1, target_id=target.id,
            target_dot_bracket=target.dot_bracket,
            target_length=target.length, k_candidates=4,
        )
        syn.dendrite_hotkey = VK
        out = asyncio.run(neuron.forward_task(syn))
        assert out.commitment and len(out.commitment) == 64
        assert out.miner_hotkey == SELF
        assert neuron.pending.pop(SELF, 1) is not None

    def test_forward_task_refuses_wrong_target(self):
        neuron = make_miner()
        syn = TaskSynapse(epoch=1, target_id="not-in-pool")
        syn.dendrite_hotkey = VK
        out = asyncio.run(neuron.forward_task(syn))
        assert out.commitment is None

    def test_forward_task_denies_low_stake(self):
        neuron = make_miner()
        neuron.meta = MetaView(FakeMetagraph([VK], [10.0]))
        syn = TaskSynapse(epoch=1, target_id="anything")
        syn.dendrite_hotkey = VK
        out = asyncio.run(neuron.forward_task(syn))
        assert out.commitment is None

    def test_forward_reveal_roundtrip(self):
        neuron = make_miner()
        target = neuron.pool.assignment(SELF, 2)
        syn = TaskSynapse(epoch=2, target_id=target.id,
                          target_dot_bracket=target.dot_bracket,
                          target_length=target.length)
        syn.dendrite_hotkey = VK
        asyncio.run(neuron.forward_task(syn))
        rsyn = RevealSynapse(epoch=2, nonce="abc")
        rsyn.dendrite_hotkey = VK
        out = asyncio.run(neuron.forward_reveal(rsyn))
        assert out.verified and out.sequence and out.salt
        cands = out.sequence.split(";")          # payload packs K candidates
        assert len(cands) == 4
        assert all(c in "AUGC" for c in out.sequence.replace(";", ""))

    def test_forward_reveal_no_pending(self):
        neuron = make_miner()
        rsyn = RevealSynapse(epoch=99, nonce="x")
        rsyn.dendrite_hotkey = VK
        out = asyncio.run(neuron.forward_reveal(rsyn))
        assert not out.verified
