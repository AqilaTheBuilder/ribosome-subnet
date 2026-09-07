import pytest

from ribosome.data_targets import builtin_targets, load_pool, validate_target
from ribosome.targets import TargetPool


@pytest.fixture(scope="module")
def pool() -> TargetPool:
    return load_pool()


def test_manifest_loads_and_validates(pool):
    assert pool.n_pool == 32
    assert len(pool.active) == 32
    assert len({t.id for t in pool.active}) == 32
    for t in pool.targets:
        validate_target(t)


def test_pool_has_difficulty_and_pseudoknot_targets(pool):
    diffs = {t.difficulty for t in pool.targets}
    assert {"easy", "medium", "hard"} <= diffs
    assert any(t.difficulty == "pseudoknot" for t in pool.targets)


def test_assignment_deterministic_and_shared(pool):
    t1 = pool.assignment("hotkey-a", 5)
    t2 = pool.assignment("hotkey-a", 5)
    assert t1.id == t2.id
    # two miners share targets sometimes (needed for duplicate detection)
    shared = any(
        pool.assignment(f"hk{i}", 7).id == pool.assignment(f"hk{j}", 7).id
        for i in range(40) for j in range(i + 1, 40)
    )
    assert shared


def test_assignment_walks_pool_across_epochs(pool):
    seen = {pool.assignment("hotkey-a", e).id for e in range(40)}
    assert len(seen) >= 8   # miner visits many targets over time


def test_rotation_every_t_rot(pool):
    assert not pool.should_rotate(0)
    assert not pool.should_rotate(15)
    assert pool.should_rotate(16)
    assert pool.should_rotate(32)
    assert not pool.should_rotate(17)


def test_rotation_swaps_half_deterministically(pool):
    before = [t.id for t in pool.active]
    incoming = pool.rotate(seed=42)
    after = [t.id for t in pool.active]
    assert len(incoming) == 16
    assert len(after) == 32 and len(set(after)) == 32
    kept = set(before) & set(after)
    assert len(kept) == 16
    # determinism
    pool2 = load_pool()
    pool2.rotate(seed=42)
    assert [t.id for t in pool2.active] == after


def test_contains_rejects_unknown_target(pool):
    assert not pool.contains("leaked-999")
    assert pool.contains(pool.active[0].id)


def test_builtin_fallback_self_consistent():
    for t in builtin_targets():
        assert len(t.sequence) == len(t.dot_bracket)
