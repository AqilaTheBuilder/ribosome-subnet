"""Chaperone neuron (validator) - production, bittensor v11.

Two run modes sharing one evaluation core:

  --mode mock      offline evaluation from a JSONL commit ledger (CI/dev).
  --mode testnet   block-driven phase machine against a live subtensor.
                   Miners are discovered from the metagraph's published
                   endpoints (neuron.axon = ip:port) and queried with
                   hotkey-signed HTTP (bittensor.http_auth, btauth/1):

      COMMIT      POST /task to every miner   -> commitments
      EVALUATE    chaperone pipeline on revealed payloads (sealed scores)
      SET_WEIGHTS sealed scores whose B-epoch hold elapsed, EMA-smoothed,
                  bt.set_weights (v11 auto-handles commit-reveal + norm)
      REVEAL      POST /reveal to committed miners, verify hash-match
      ROTATE      target-pool rotation every T_ROT epochs

Validator hardening:
  * MinerGate      - only query registered hotkeys with a published endpoint
  * EMA smoothing  - weights from exponentially-smoothed scores (alpha)
  * delayed reveal - weights come from sealed scores of epoch-B (anti-grind)
  * checkpoints    - EMA + scheduler persisted per epoch to --state-dir
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ribosome.commit import CommitLedger, commitment_hash  # noqa: E402
from ribosome.constants import (  # noqa: E402
    SCORE_REVEAL_DELAY_B,
    Phase,
)
from ribosome.data_targets import load_pool  # noqa: E402
from ribosome.oracle import get_oracle  # noqa: E402
from ribosome.protocol import (  # noqa: E402
    RevealSynapse,
    TaskSynapse,
    from_dict,
    to_dict,
)
from ribosome.validator_logic import Chaperone  # noqa: E402

from neurons import transport  # noqa: E402
from neurons.config import build_parser  # noqa: E402
from neurons.production_logic import (  # noqa: E402
    CommitRevealScheduler,
    EMAScoreStore,
    HotkeyIndex,
    MinerGate,
    epoch_phase,
)

BT_AVAILABLE = False
try:  # pragma: no cover - depends on environment
    import bittensor as bt

    BT_AVAILABLE = True
except ImportError:
    bt = None  # type: ignore

import logging  # noqa: E402


def log(msg: str) -> None:
    logging.getLogger("ribosome.validator").info(msg)


# --------------------------------------------------------------------------
# mock mode (unchanged semantics)
# --------------------------------------------------------------------------
def run_mock(args) -> None:
    logging.basicConfig(level=logging.INFO, format="[validator] %(message)s")
    pool = load_pool()
    ledger = CommitLedger()
    if args.ledger:
        for line in Path(args.ledger).read_text().splitlines():
            event = json.loads(line)
            if event.get("type") == "commit":
                ledger.commit(event["hotkey"], event["epoch"], event["target_id"], event["hash"])
            elif event.get("type") == "reveal":
                try:
                    ledger.reveal(event["hotkey"], event["epoch"], event["seq"], event["salt"], event["epoch"])
                except ValueError as err:
                    print(f"reveal rejected: {err}")
    chaperone = Chaperone(oracle=get_oracle(args.oracle))
    weights_path = Path(args.out)
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        evaluation = chaperone.evaluate_epoch(epoch, pool, ledger)
        accepted = [f"{h}:{s:.3f}" for h, s in evaluation.weights.items()]
        print(f"epoch {epoch:3d} accepted={len(evaluation.weights)} weights={accepted[:8]}")
    weights_path.write_text(json.dumps(
        {"epochs": args.epochs, "oracle": chaperone.oracle.name,
         "weights": evaluation.weights}, indent=2))
    print(f"weights written to {weights_path}")


# --------------------------------------------------------------------------
# shared weight math (used by both modes; unit-testable without bittensor)
# --------------------------------------------------------------------------
def normalize_uid_weights(
    scores: Dict[str, float], index: HotkeyIndex
) -> Tuple[List[int], List[float]]:
    """Map {hotkey: normalized score} -> (sorted uids, weights) for the chain.

    Drops unregistered hotkeys and zero scores FIRST (so they never consume
    normalization mass), sorts by uid ascending (chain requirement). When
    every score is zero the registered miners get a uniform weight.
    """
    hi = max(scores.values(), default=0.0)
    if hi < 1e-12:
        raw = {h: 1.0 for h in scores}  # uniform when everything is zero
    else:
        raw = {h: s / hi for h, s in scores.items()}
    pairs = []
    for hotkey, score in raw.items():
        uid = index.uid_of(hotkey)
        if uid is not None and score > 1e-12:
            pairs.append((uid, score))
    total = sum(w for _, w in pairs) or 1.0
    pairs.sort(key=lambda p: p[0])
    if not pairs:
        return [], []
    uids = [u for u, _ in pairs]
    weights = [w / total for _, w in pairs]
    return uids, weights


# --------------------------------------------------------------------------
# testnet mode (production phase machine)
# --------------------------------------------------------------------------
class ChaperoneNeuron:
    def __init__(self, args: argparse.Namespace) -> None:
        if not BT_AVAILABLE:  # pragma: no cover - guarded by run_testnet
            raise RuntimeError("bittensor required for testnet mode")
        self.args = args
        self.wallet = bt.Wallet(
            name=args.wallet_name or "validator",
            hotkey=args.hotkey_name or "default",
        )
        self.hotkey = self.wallet.hotkey.ss58_address
        self.client = bt.SyncClient(args.network)
        self.http = transport.SignedHttpClient(
            self.wallet, timeout=args.query_timeout
        )
        self.mg = None
        self.meta = None
        self.refresh_metagraph()
        self.index = HotkeyIndex()
        self.index.rebuild(list(self.meta.hotkeys))
        self.pool = load_pool()
        self.ledger = CommitLedger(score_reveal_delay_b=SCORE_REVEAL_DELAY_B)
        self.chaperone = Chaperone(oracle=self._build_oracle())
        self.ema = EMAScoreStore(alpha=args.ema_alpha)
        self.scheduler = CommitRevealScheduler(period=args.commit_reveal_period)
        self.gate = MinerGate()
        self._phase_locks: Dict[Tuple[int, Phase], bool] = {}
        self._commitments: Dict[Tuple[int, str], dict] = {}  # (epoch, hotkey) -> info
        self.state_dir = Path(args.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._load_checkpoint()

    # ------------------------------------------------------------- setup ----
    def _build_oracle(self):
        if self.args.oracle == "rhofold":
            from ribosome.oracle import RhoFoldOracle

            return RhoFoldOracle(
                repo=self.args.rhofold_repo, checkpoint=self.args.rhofold_ckpt
            )
        return get_oracle(self.args.oracle)

    def refresh_metagraph(self) -> None:
        """Fresh metagraph snapshot (block, tempo, neurons, endpoints)."""
        self.mg = self.client.subnets.metagraph(self.args.netuid)
        self.meta = transport.MetaView(self.mg)
        self.index.rebuild(list(self.meta.hotkeys))

    def _block(self) -> int:
        return int(getattr(self.mg, "block", 0) or 0)

    def _tempo(self) -> int:
        return int(getattr(self.mg, "tempo", 0) or 360)

    # ------------------------------------------------------- checkpoints ----
    def _checkpoint_path(self) -> Path:
        return self.state_dir / "validator_state.json"

    def _save_checkpoint(self) -> None:  # pragma: no cover - disk I/O
        self._checkpoint_path().write_text(
            json.dumps(
                {
                    "ema": self.ema.snapshot(),
                    "scheduler": self.scheduler.to_dict(),
                    "saved_at": time.time(),
                },
                indent=2,
            )
        )

    def _load_checkpoint(self) -> None:
        path = self._checkpoint_path()
        if not path.exists():
            return
        try:  # pragma: no cover - disk I/O
            data = json.loads(path.read_text())
            self.ema = EMAScoreStore(alpha=self.args.ema_alpha)
            self.ema.update(0, data.get("ema", {}))
            self.scheduler = CommitRevealScheduler.from_dict(
                data.get("scheduler", {"period": self.args.commit_reveal_period})
            )
            log(f"restored validator checkpoint from {path}")
        except Exception as exc:
            log(f"checkpoint restore failed ({exc}); starting fresh")

    # ------------------------------------------------------- phase guard ----
    def _once(self, epoch: int, phase: Phase) -> bool:
        """True the first time (epoch, phase) is seen this process run."""
        key = (epoch, phase)
        if self._phase_locks.get(key):
            return False
        self._phase_locks[key] = True
        if len(self._phase_locks) > 512:
            for k in [k for k in self._phase_locks if k[0] < epoch - 8][:256]:
                del self._phase_locks[k]
        return True

    # ---------------------------------------------------------- queries ----
    async def _query_task(self, epoch: int) -> None:
        """COMMIT: POST /task to every reachable miner."""
        self._commitments = {
            k: v for k, v in self._commitments.items() if k[0] == epoch
        }
        queried = 0
        for hotkey in self.meta.hotkeys:
            if hotkey == self.hotkey:
                continue
            ok, _ = self.gate.check(hotkey, self.meta)
            endpoint = self.meta.endpoint_of(hotkey)
            if not ok or endpoint is None:
                continue
            target = self.pool.assignment(hotkey, epoch)
            synapse = TaskSynapse(
                epoch=epoch,
                target_id=target.id,
                target_dot_bracket=target.dot_bracket,
                target_length=target.length,
                k_candidates=4,
            )
            try:
                status, data = await self.http.post_json(
                    endpoint, "/task", to_dict(synapse), receiver_ss58=hotkey
                )
            except Exception as exc:
                log(f"task query failed {hotkey[:10]}...: {exc}")
                continue
            if status == 200 and data.get("commitment"):
                self._commitments[(epoch, hotkey)] = {
                    "target_id": target.id,
                    "commitment": data["commitment"],
                }
            queried += 1
        log(
            f"epoch {epoch} COMMIT: {len(self._commitments)} commitments "
            f"from {queried} reachable miners"
        )

    async def _query_reveals(self, epoch: int) -> None:
        """REVEAL: POST /reveal to committed miners and verify hash-match."""
        hotkeys = [
            h for (e, h) in self._commitments
            if e == epoch and self.gate.check(h, self.meta)[0]
        ]
        accepted = 0
        for hotkey in hotkeys:
            info = self._commitments.get((epoch, hotkey))
            if info is None:
                continue
            endpoint = self.meta.endpoint_of(hotkey)
            if endpoint is None:
                continue
            synapse = RevealSynapse(epoch=epoch, nonce=f"reveal-{epoch}")
            try:
                status, data = await self.http.post_json(
                    endpoint, "/reveal", to_dict(synapse), receiver_ss58=hotkey
                )
            except Exception as exc:
                log(f"reveal query failed {hotkey[:10]}...: {exc}")
                continue
            if status != 200 or not data.get("verified"):
                continue
            seq = data.get("sequence", "")
            salt = data.get("salt", "")
            recomputed = commitment_hash(seq, salt, epoch, info["target_id"])
            if recomputed == info["commitment"]:
                self.ledger.commit(
                    hotkey, epoch, info["target_id"], info["commitment"]
                )
                try:
                    self.ledger.reveal(hotkey, epoch, seq, salt, epoch)
                    accepted += 1
                except ValueError as exc:
                    log(f"reveal rejected for {hotkey[:10]}...: {exc}")
            else:
                log(f"hash mismatch from {hotkey[:10]}... - ignored")
        log(f"epoch {epoch} REVEAL: {accepted}/{len(hotkeys)} verified")

    # ----------------------------------------------------- weight setting ----
    def _weights_due(self, epoch: int) -> Dict[str, float]:
        """Sealed scores whose B-epoch hold elapsed, EMA-smoothed."""
        due = self.ledger.due_scores(epoch)
        epoch_scores: Dict[str, Dict[str, float]] = {}
        for (hotkey, scored_epoch), vals in due.items():
            if not vals:
                continue
            mean = sum(s for _, s in vals) / len(vals)
            epoch_scores.setdefault(hotkey, {})[scored_epoch] = mean
        smoothed: Dict[str, float] = dict(self.ema.snapshot())
        flat: Dict[int, Dict[str, float]] = {}
        for hotkey, per_epoch in epoch_scores.items():
            for scored_epoch, score in per_epoch.items():
                flat.setdefault(scored_epoch, {})[hotkey] = score
        for scored_epoch in sorted(flat):
            smoothed = self.ema.update(scored_epoch, flat[scored_epoch])
        return smoothed

    def _set_weights(self, epoch: int, scores: Dict[str, float]) -> None:  # pragma: no cover - chain tx
        uids, weights = normalize_uid_weights(scores, self.index)
        if not uids:
            log("no eligible miners for weights this epoch")
            return
        # v11: bt.set_weights conforms (clip/normalize/quantize), preflights
        # registration + rate limit, and picks plaintext vs timelocked
        # commit-reveal automatically from the subnet hyperparameters.
        if self.scheduler.period > 0:
            salt = __import__("secrets").token_bytes(32)
            self.scheduler.plan(epoch, uids, weights, salt=salt)
        bt.set_weights(
            self.args.netuid,
            dict(zip(uids, weights)),
            wallet=self.wallet,
            network=self.args.network,
        )
        log(f"epoch {epoch} SET_WEIGHTS: {len(uids)} miners via bt.set_weights")

    # ------------------------------------------------------------ main ----
    async def run(self) -> None:  # pragma: no cover - needs live chain
        logging.basicConfig(level=logging.INFO, format="[validator] %(message)s")
        log(
            f"chaperone {self.hotkey[:10]}... on {self.args.network} "
            f"netuid={self.args.netuid}"
        )
        last_epoch_seen = -1
        while True:
            try:
                block = self._block()
                epoch, phase = epoch_phase(block, self._tempo())
                if phase == Phase.COMMIT and self._once(epoch, Phase.COMMIT):
                    self.refresh_metagraph()
                    await self._query_task(epoch)
                elif phase == Phase.EVALUATE and self._once(epoch, Phase.EVALUATE):
                    if self.ledger.committed_hotkeys(epoch):
                        evaluation = self.chaperone.evaluate_epoch(
                            epoch, self.pool, self.ledger
                        )
                        log(
                            f"epoch {epoch} EVALUATE: accepted="
                            f"{len(evaluation.weights)} sealed for "
                            f"epoch {epoch + SCORE_REVEAL_DELAY_B}"
                        )
                elif phase == Phase.SET_WEIGHTS and self._once(epoch, Phase.SET_WEIGHTS):
                    scores = self._weights_due(epoch)
                    self._set_weights(epoch, scores)
                    self._save_checkpoint()
                elif phase == Phase.REVEAL and self._once(epoch, Phase.REVEAL):
                    await self._query_reveals(epoch)
                elif phase == Phase.ROTATE and self._once(epoch, Phase.ROTATE):
                    if self.pool.should_rotate(epoch):
                        incoming = self.pool.rotate(seed=epoch)
                        log(f"epoch {epoch} ROTATE: {len(incoming)} targets swapped")
                if epoch != last_epoch_seen:
                    log(f"== epoch {epoch} {phase.value} (block {block}) ==")
                    last_epoch_seen = epoch
            except Exception as exc:
                log(f"phase {phase.value if 'phase' in dir() else '?'} error: {exc}")
            await asyncio.sleep(6)


def run_testnet(args) -> None:  # pragma: no cover - needs bittensor + chain
    if not BT_AVAILABLE:
        print("bittensor is not installed: pip install bittensor")
        sys.exit(1)
    neuron = ChaperoneNeuron(args)
    try:
        asyncio.run(neuron.run())
    except KeyboardInterrupt:
        log("shut down")


def main() -> None:
    args = build_parser("validator").parse_args()
    if args.mode == "mock":
        run_mock(args)
    else:
        run_testnet(args)


if __name__ == "__main__":
    main()
