"""Offline round simulation for the Ribosome Network.

Runs the full 5-phase mechanism across many epochs with a mixed miner
population and produces event logs + aggregate metrics:

  ga_strong   GAGenerator(beta=2, oracle-assisted) - honest skilled miner
  stub_honest StubGenerator - honest low-compute miner
  copier      replays the top GA miner's best sequence from epoch t-1
              (Sybil duplicate attack - must be zeroed by theta_dup)
  lazy        honest generator, withholds 10% of reveals
  leaker      commits to target ids absent from the pool (leak/fault)

Weight application follows the preprint's delayed score reveal: chaperones
seal scores at the evaluated epoch t and publish them at t + B (B = 4);
weights set in epoch e consume only scores revealed by then, so the applied
weight vector at epoch e is derived from epoch e - B evaluations.

Usage:
  python -m simulation.run_simulation --epochs 20 --out data/runs
"""
from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ribosome.commit import CommitLedger
from ribosome.constants import (
    DELTA_TM,
    SCORE_REVEAL_DELAY_B,
    THETA_DUP,
    T_ROT,
    W_DIV,
)
from ribosome.data_targets import load_pool
from ribosome.generators import GAGenerator, StubGenerator
from ribosome.miner_logic import Synthetase
from ribosome.validator_logic import Chaperone

STRATEGY_ORDER = ["ga_strong", "stub_honest", "copier", "lazy", "leaker"]


@dataclass
class SimConfig:
    n_ga: int = 12
    n_stub: int = 10
    n_copier: int = 6
    n_lazy: int = 2
    n_leaker: int = 2
    epochs: int = 20
    seed: int = 42
    k_candidates: int = 4
    score_delay_b: int = SCORE_REVEAL_DELAY_B
    theta_dup: float = THETA_DUP
    w_div: float = W_DIV

    @property
    def n_miners(self) -> int:
        return self.n_ga + self.n_stub + self.n_copier + self.n_lazy + self.n_leaker


@dataclass
class EpochRecord:
    epoch: int
    weights: Dict[str, float] = field(default_factory=dict)      # applied (delayed)
    scores: Dict[str, float] = field(default_factory=dict)       # instantaneous final
    tm: Dict[str, float] = field(default_factory=dict)
    accepted: List[str] = field(default_factory=list)
    zeroed: Dict[str, str] = field(default_factory=dict)         # hotkey -> reason
    duplicates: List[str] = field(default_factory=list)
    rotation: List[str] = field(default_factory=list)


class Simulation:
    def __init__(self, config: SimConfig) -> None:
        self.cfg = config
        self.rng = random.Random(config.seed)
        self.pool = load_pool()
        self.ledger = CommitLedger(score_reveal_delay_b=config.score_delay_b)
        self.chaperone = Chaperone(theta_dup=config.theta_dup, w_div=config.w_div)
        self.miners = self._build_miners()
        self.reveal_cache: Dict[int, Dict[str, str]] = {}
        self.top_ga_hotkey: Optional[str] = None
        self.events: List[dict] = []
        self.records: List[EpochRecord] = []

    # ------------------------------------------------------------- setup ----
    def _build_miners(self) -> List[Synthetase]:
        """Build the mixed miner population.

        Copiers are Sybil clones: each one searches for a hotkey whose slot
        collides with a GA miner's slot (exactly what a Sybil operator does
        when registering many keys), then runs the SAME generator with the
        SAME seed as the victim. Result: identical candidates, identical
        payload, later commit -> duplicate detection must zero it.
        """
        miners: List[Synthetase] = []
        hotkey_counter = 0

        def fresh_hotkey() -> str:
            nonlocal hotkey_counter
            hk = f"5F{hotkey_counter:04x}" + "A" * 40
            hotkey_counter += 1
            return hk

        ga_miners: List[Synthetase] = []
        for i in range(self.cfg.n_ga):
            m = Synthetase(
                hotkey=fresh_hotkey(), generator=GAGenerator(),
                strategy="ga_strong", k_candidates=self.cfg.k_candidates,
                seed=self.cfg.seed + 1000 + i,
            )
            miners.append(m)
            ga_miners.append(m)

        for i in range(self.cfg.n_stub):
            miners.append(Synthetase(
                hotkey=fresh_hotkey(), generator=StubGenerator(),
                strategy="stub_honest", k_candidates=self.cfg.k_candidates,
                seed=self.cfg.seed + 2000 + i,
            ))
        for i in range(self.cfg.n_lazy):
            miners.append(Synthetase(
                hotkey=fresh_hotkey(), generator=StubGenerator(),
                strategy="lazy", k_candidates=self.cfg.k_candidates,
                seed=self.cfg.seed + 3000 + i,
            ))
        for _ in range(self.cfg.n_leaker):
            miners.append(Synthetase(
                hotkey=fresh_hotkey(), generator=StubGenerator(),
                strategy="leaker", k_candidates=self.cfg.k_candidates,
                seed=self.cfg.seed + 4000,
            ))

        victim_cycle = [m for m in ga_miners[: max(self.cfg.n_copier, 0)]] or ga_miners
        for j in range(self.cfg.n_copier):
            victim = victim_cycle[j % len(victim_cycle)]
            clone_hotkey = self._find_colliding_hotkey(victim.hotkey)
            miners.append(Synthetase(
                hotkey=clone_hotkey, generator=GAGenerator(),
                strategy="copier", k_candidates=victim.k_candidates,
                seed=victim.seed,   # same trajectory as the victim
            ))
        return miners

    def _find_colliding_hotkey(self, victim_hotkey: str) -> str:
        """Sybil key registration: try suffixes until the slot matches."""
        victim_slot = self.pool.slot_of(victim_hotkey) % len(self.pool.active)
        for attempt in range(100_000):
            candidate = f"5C{attempt:06x}" + "B" * 40
            if self.pool.slot_of(candidate) % len(self.pool.active) == victim_slot:
                return candidate
        raise RuntimeError("no colliding hotkey found")  # pragma: no cover

    # -------------------------------------------------------------- run ----
    def run(self) -> List[EpochRecord]:
        for epoch in range(self.cfg.epochs):
            self._run_epoch(epoch)
        return self.records

    def _run_epoch(self, epoch: int) -> None:
        cfg = self.cfg
        record = EpochRecord(epoch=epoch)

        # ROTATE phase (start of round if due)
        if self.pool.should_rotate(epoch):
            incoming = self.pool.rotate(seed=cfg.seed)
            record.rotation = [t.id for t in incoming]
            self._log({"type": "rotation", "epoch": epoch, "incoming": record.rotation})

        # COMMIT phase
        for m in self.miners:
            m.act(epoch, self.pool, self.ledger)
        self._log({"type": "commit_phase", "epoch": epoch,
                   "commits": len(self.ledger.committed_hotkeys(epoch))})

        # REVEAL phase
        revealed = 0
        for m in self.miners:
            if m.reveal(epoch, self.ledger, epoch):
                revealed += 1
        self._log({"type": "reveal_phase", "epoch": epoch, "revealed": revealed})

        # EVALUATE phase (chaperone refolds + scores; scores sealed)
        evaluation = self.chaperone.evaluate_epoch(epoch, self.pool, self.ledger)
        for hotkey, ev in evaluation.per_miner.items():
            record.tm[hotkey] = ev.best_tm
            record.scores[hotkey] = ev.final_score
            if ev.accepted:
                record.accepted.append(hotkey)
            else:
                record.zeroed[hotkey] = ev.zero_reason
            if ev.is_duplicate:
                record.duplicates.append(hotkey)
            commit = self.ledger.get_commit(hotkey, epoch)
            best_seq = ""
            if commit is not None and commit.revealed and commit.seq:
                from ribosome.commit import split_candidates

                cands = split_candidates(commit.seq)
                best_seq = cands[0] if cands else ""
            self._log({
                "type": "eval", "epoch": epoch, "hotkey": hotkey,
                "strategy": self._strategy_of(hotkey),
                "target_id": ev.target_id,
                "tm": round(ev.best_tm, 4), "final": round(ev.final_score, 4),
                "accepted": ev.accepted, "zero_reason": ev.zero_reason,
                "duplicate_of": ev.duplicate_of,
                "best_seq": best_seq,
            })

        # best GA miner this epoch becomes the copier template
        ga_scores = {
            h: record.scores.get(h, 0.0)
            for h in record.tm if self._strategy_of(h) == "ga_strong"
        }
        if ga_scores:
            self.top_ga_hotkey = max(ga_scores, key=ga_scores.get)  # type: ignore

        # cache best sequences for copiers (what a public chain would show)
        self.reveal_cache[epoch] = {
            h: self.ledger.get_commit(h, epoch).seq or ""
            for h in self.ledger.committed_hotkeys(epoch)
            if self.ledger.get_commit(h, epoch).revealed
        }

        # SET_WEIGHTS phase: apply the scores *revealed* by now (delay B)
        due = self.ledger.due_scores(epoch)
        applied: Dict[str, float] = {}
        for (hotkey, scored_epoch), vals in due.items():
            applied[hotkey] = statistics.fmean(v for _, v in vals)
        if applied:
            hi = max(applied.values())
            if hi > 1e-9:
                raw = {h: s / hi for h, s in applied.items()}
                total = sum(raw.values())
                record.weights = {h: v / total for h, v in raw.items()}
        self._log({
            "type": "weights", "epoch": epoch,
            "n": len(record.weights),
            "from_epochs": sorted({e for (_, e) in due}),
            "weight_sum": round(sum(record.weights.values()), 6),
        })

        self.records.append(record)

    # ----------------------------------------------------------- helpers ----
    _strategy_map: Dict[str, str] = {}

    def _strategy_of(self, hotkey: str) -> str:
        for m in self.miners:
            if m.hotkey == hotkey:
                return m.strategy
        return "unknown"

    def _log(self, event: dict) -> None:
        self.events.append(event)


# ------------------------------------------------------------- summary ----
def summarize(sim: Simulation) -> dict:
    cfg = sim.cfg
    per_strategy: Dict[str, dict] = {}
    for strategy in STRATEGY_ORDER:
        hotkeys = [m.hotkey for m in sim.miners if m.strategy == strategy]
        tms, finals, accepted_n, zeroed_n, dup_n = [], [], 0, 0, 0
        weight_share = 0.0
        for rec in sim.records:
            for hk in hotkeys:
                if hk in rec.tm:
                    tms.append(rec.tm[hk])
                    finals.append(rec.scores.get(hk, 0.0))
                if hk in rec.accepted:
                    accepted_n += 1
                if hk in rec.zeroed:
                    zeroed_n += 1
                if hk in rec.duplicates:
                    dup_n += 1
                weight_share += rec.weights.get(hk, 0.0)
        n_epochs = max(len(sim.records), 1)
        n_miners = max(len(hotkeys), 1)
        per_strategy[strategy] = {
            "n_miners": len(hotkeys),
            "mean_tm": round(statistics.fmean(tms), 4) if tms else 0.0,
            "mean_final_score": round(statistics.fmean(finals), 4) if finals else 0.0,
            "acceptance_rate": round(accepted_n / (n_epochs * n_miners), 4),
            "zeroed_rate": round(zeroed_n / (n_epochs * n_miners), 4),
            "duplicate_rate": round(dup_n / (n_epochs * n_miners), 4),
            "mean_weight_share": round(weight_share / n_epochs, 4),
        }

    dup_events = sum(len(r.duplicates) for r in sim.records)
    from ribosome.validator_logic import ZERO_REASONS

    leaker_zero = sum(
        1 for r in sim.records for h, reason in r.zeroed.items()
        if reason == ZERO_REASONS["wrong_target"]
    )
    late_reveals = sum(
        1 for r in sim.records for h, reason in r.zeroed.items()
        if reason == ZERO_REASONS["no_reveal"]
    )
    gate_failures = sum(
        1 for r in sim.records for h, reason in r.zeroed.items()
        if reason == ZERO_REASONS["all_invalid"]
    )
    rotations = [r.epoch for r in sim.records if r.rotation]

    return {
        "config": {
            "epochs": cfg.epochs, "seed": cfg.seed, "n_miners": cfg.n_miners,
            "n_ga": cfg.n_ga, "n_stub": cfg.n_stub, "n_copier": cfg.n_copier,
            "n_lazy": cfg.n_lazy, "n_leaker": cfg.n_leaker,
            "k_candidates": cfg.k_candidates,
            "theta_dup": cfg.theta_dup, "w_div": cfg.w_div,
            "score_delay_b": cfg.score_delay_b, "t_rot": T_ROT,
            "delta_tm": DELTA_TM,
        },
        "per_strategy": per_strategy,
        "security": {
            "duplicates_zeroed": dup_events,
            "leaker_commits_rejected": leaker_zero,
            "missed_reveals_zeroed": late_reveals,
            "gate_failures": gate_failures,
            "rotations": rotations,
        },
        "mechanism": {
            "oracle": sim.chaperone.oracle.name,
            "epoch_phases": "COMMIT(3m) EVALUATE(6m) SET_WEIGHTS(2m) REVEAL(2m) ROTATE(2m)",
        },
    }


def write_outputs(sim: Simulation, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "sim_log.jsonl"
    with log_path.open("w", encoding="utf-8") as f:
        for event in sim.events:
            f.write(json.dumps(event) + "\n")
    summary = summarize(sim)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"log": str(log_path), "summary": str(summary_path)}
