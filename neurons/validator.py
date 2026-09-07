"""Chaperone neuron (validator).

Two run modes:
  --mode mock      offline: evaluates miners from the simulation harness /
                   mock ledger through the same Chaperone pipeline.
  --mode testnet   requires bittensor + subtensor; runs the phase state
                   machine (COMMIT -> EVALUATE -> SET_WEIGHTS -> REVEAL ->
                   ROTATE) against the live metagraph, refolds revealed
                   sequences with the configured oracle and sets weights.

Phase timing comes from ribosome.constants (15-min epochs).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ribosome.commit import CommitLedger  # noqa: E402
from ribosome.constants import PHASE_DURATIONS_SEC, Phase  # noqa: E402
from ribosome.data_targets import load_pool  # noqa: E402
from ribosome.oracle import get_oracle  # noqa: E402
from ribosome.validator_logic import Chaperone  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ribosome Network chaperone")
    p.add_argument("--mode", choices=["mock", "testnet"], default="mock")
    p.add_argument("--netuid", type=int, default=1)
    p.add_argument("--wallet-name", default="validator")
    p.add_argument("--hotkey-name", default="default")
    p.add_argument("--oracle", choices=["auto", "stub", "viennarna", "rhofold"], default="auto")
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--ledger", default="", help="path to JSONL commit ledger (mock)")
    p.add_argument("--out", default="docs/data/weights.json")
    return p.parse_args()


def run_mock(args) -> None:
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


def run_testnet(args) -> None:  # pragma: no cover - needs bittensor
    try:
        import bittensor as bt  # type: ignore
    except ImportError:
        print("bittensor is not installed: pip install bittensor")
        sys.exit(1)
    bt.logging.info("starting chaperone neuron")
    wallet = bt.wallet(name=args.wallet_name, hotkey=args.hotkey_name)
    subtensor = bt.subtensor(network="test")
    metagraph = subtensor.metagraph(args.netuid)
    pool = load_pool()
    ledger = CommitLedger()
    chaperone = Chaperone(oracle=get_oracle(args.oracle))
    epoch = 0
    phase_started = time.time()
    current_phase = Phase.COMMIT
    while True:  # noqa: DOC201 - neuron loop
        if time.time() - phase_started >= PHASE_DURATIONS_SEC[current_phase]:
            # advance phase machine
            order = [Phase.COMMIT, Phase.EVALUATE, Phase.SET_WEIGHTS, Phase.REVEAL, Phase.ROTATE]
            nxt = order[(order.index(current_phase) + 1) % len(order)]
            if nxt == Phase.COMMIT:
                epoch += 1
            if nxt == Phase.EVALUATE:
                bt.logging.info("EVALUATE: refolding revealed candidates")
            if nxt == Phase.SET_WEIGHTS:
                evaluation = chaperone.evaluate_epoch(epoch, pool, ledger)
                hotkeys = list(evaluation.weights)
                weights = [evaluation.weights[h] for h in hotkeys]
                uids = [metagraph.hotkeys.index(h) for h in hotkeys if h in metagraph.hotkeys]
                wt = [evaluation.weights[metagraph.hotkeys[u]] for u in uids]
                subtensor.set_weights(
                    wallet=wallet, netuid=args.netuid, uids=uids, weights=wt,
                    wait_for_inclusion=False,
                )
                bt.logging.info(f"weights set for {len(uids)} miners")
            if nxt == Phase.ROTATE and pool.should_rotate(epoch):
                pool.rotate(seed=epoch)
                bt.logging.info("target pool rotated")
            current_phase, phase_started = nxt, time.time()
        time.sleep(5)


def main() -> None:
    args = parse_args()
    if args.mode == "mock":
        run_mock(args)
    else:
        run_testnet(args)


if __name__ == "__main__":
    main()
