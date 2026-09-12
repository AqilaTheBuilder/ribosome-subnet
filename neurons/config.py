"""Shared neuron configuration.

Bittensor-style CLI (wallet/subtensor/axon/logging flags) that degrades to a
plain argparse namespace when the SDK is absent, so `--help` and mock runs
work in CI. Live neurons additionally merge bt's own sub-configs.

Usage (live):
    python neurons/validator.py --netuid 42 --wallet.name chaperone \
        --wallet.hotkey default --subtensor.network test
"""
from __future__ import annotations

import argparse


def build_parser(neuron_type: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=f"Ribosome Network {neuron_type}")
    p.add_argument("--mode", choices=["mock", "testnet"], default="mock")
    p.add_argument("--netuid", type=int, default=1)
    p.add_argument("--wallet-name", "--wallet.name", dest="wallet_name", default=None)
    p.add_argument("--hotkey-name", "--wallet.hotkey", dest="hotkey_name", default=None)
    p.add_argument("--network", "--subtensor.network", dest="network", default="test",
                   help="finney | test | local | <url>")
    p.add_argument("--axon-port", type=int, default=8091)
    p.add_argument("--public-ip", dest="public_ip", default="",
                   help="public IP for endpoint publication (default: auto-detect)")
    p.add_argument("--epochs", type=int, default=1, help="mock-mode epochs")
    # miner-specific
    if neuron_type == "miner":
        p.add_argument("--generator", choices=["stub", "ga"], default="ga")
        p.add_argument("--beta", type=float, default=2.0)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--rate-capacity", type=float, default=10.0)
        p.add_argument("--rate-refill", type=float, default=0.5)
        p.add_argument("--min-stake", type=float, default=10_000.0)
        p.add_argument("--strict-assignment", action=argparse.BooleanOptionalAction,
                       default=True,
                       help="refuse targets that differ from pool.assignment(hotkey, epoch)")
    # validator-specific
    if neuron_type == "validator":
        p.add_argument("--oracle", choices=["auto", "stub", "viennarna", "pyviennarna", "rhofold"],
                       default="auto")
        p.add_argument("--rhofold-repo", default="", help="path to RhoFold+ checkout")
        p.add_argument("--rhofold-ckpt", default="", help="RhoFold+ checkpoint file")
        p.add_argument("--min-stake", type=float, default=10_000.0)
        p.add_argument("--ema-alpha", type=float, default=0.3)
        p.add_argument("--commit-reveal-period", type=int, default=1,
                       help="0 = plain set_weights")
        p.add_argument("--query-timeout", type=float, default=12.0)
        p.add_argument("--state-dir", default=".ribosome-validator")
        p.add_argument("--ledger", default="", help="JSONL commit ledger (mock)")
        p.add_argument("--out", default="docs/data/weights.json")
    return p


def parser_to_dict(args: argparse.Namespace) -> dict:
    return {
        k: getattr(args, k)
        for k in vars(args)
        if not k.startswith("_")
    }
