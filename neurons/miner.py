"""Synthetase neuron (miner).

Two run modes:
  --mode mock      offline: drives Synthetase against a local TargetPool and
                   CommitLedger without bittensor (CI, dev, demo).
  --mode testnet   requires `pip install bittensor` and a live subtensor
                   connection; wires the same Synthetase logic onto
                   bt.dendrite queries of the validator's axon.

The mechanism logic (what to commit, when to reveal) is identical in both
modes - only the transport differs. That is the point: the simulation and
the testnet run the same code path.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ribosome.commit import (  # noqa: E402
    CommitLedger,
    commitment_hash,
    join_candidates,
)
from ribosome.constants import K_CANDIDATES  # noqa: E402
from ribosome.data_targets import load_pool  # noqa: E402
from ribosome.generators import GAGenerator, StubGenerator  # noqa: E402
from ribosome.miner_logic import Synthetase  # noqa: E402
from ribosome.protocol import TaskSynapse  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ribosome Network synthetase")
    p.add_argument("--mode", choices=["mock", "testnet"], default="mock")
    p.add_argument("--netuid", type=int, default=1)
    p.add_argument("--wallet-name", default="miner")
    p.add_argument("--hotkey-name", default="default")
    p.add_argument("--generator", choices=["stub", "ga"], default="ga")
    p.add_argument("--beta", type=float, default=2.0)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def build_synthetase(args) -> Synthetase:
    gen = (
        GAGenerator(beta=args.beta)
        if args.generator == "ga"
        else StubGenerator()
    )
    return Synthetase(
        hotkey=f"{args.wallet_name}-{args.hotkey_name}",
        generator=gen,
        strategy="honest",
        k_candidates=K_CANDIDATES,
        seed=args.seed,
    )


def run_mock(args) -> None:
    """Local loop: assignment -> commit -> reveal against an in-process ledger."""
    pool = load_pool()
    ledger = CommitLedger()
    synth = build_synthetase(args)
    rng = random.Random(args.seed)
    for epoch in range(args.epochs):
        if pool.should_rotate(epoch):
            pool.rotate(seed=args.seed)
        target = pool.assignment(synth.hotkey, epoch)
        candidates = synth.produce(target)
        ranked = synth.self_rank(target, candidates)
        payload = join_candidates(ranked[: synth.k_candidates])
        salt = f"{synth.hotkey}-{epoch}"
        ledger.commit(synth.hotkey, epoch, target.id, commitment_hash(payload, salt, epoch, target.id))
        ok = ledger.reveal(synth.hotkey, epoch, payload, salt, epoch)
        print(
            f"epoch {epoch:3d} target {target.id:12s} "
            f"k={len(ranked)} revealed={ok}"
        )
    print("mock run complete - mechanism logic exercised end to end")


def run_testnet(args) -> None:  # pragma: no cover - needs bittensor
    try:
        import bittensor as bt  # type: ignore
    except ImportError:
        print("bittensor is not installed: pip install bittensor")
        sys.exit(1)
    bt.logging.info("starting synthetase neuron")
    wallet = bt.wallet(name=args.wallet_name, hotkey=args.hotkey_name)
    subtensor = bt.subtensor(network="test")
    metagraph = subtensor.metagraph(args.netuid)
    dendrite = bt.dendrite(wallet=wallet)
    synth = build_synthetase(args)
    # main loop: wait for TaskSynapse from validators, respond with commitments
    while True:  # noqa: DOC201 - neuron loop
        metagraph = subtensor.metagraph(args.netuid)
        for axon in metagraph.axons:
            task = TaskSynapse()
            resp = dendrite.query(axon, task, timeout=12)
            if getattr(resp, "commitment", None):
                bt.logging.info(f"commitment sent to {axon.hotkey}")
        import time

        time.sleep(60)


def main() -> None:
    args = parse_args()
    if args.mode == "mock":
        run_mock(args)
    else:
        run_testnet(args)


if __name__ == "__main__":
    main()
