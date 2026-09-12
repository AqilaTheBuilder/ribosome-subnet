"""Live smoke test: signed-HTTP roundtrip miner <-> validator (bittensor v11).

Boots a real SynthetaseNeuron FastAPI endpoint on localhost, publishes
nothing to chain, and drives it with a SignedHttpClient exactly the way the
ChaperoneNeuron does:

  POST /task    signed by a validator wallet  -> commitment
  POST /reveal  signed by the same validator  -> (payload, salt)

Run:  .venv-bt/bin/python scripts/smoke_transport.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import types
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bittensor as bt
import uvicorn

from neurons import transport
from neurons.miner import SynthetaseNeuron, build_synthetase
from neurons.production_logic import (
    PendingRevealStore,
    RateLimiter,
    ValidatorGate,
)
from neurons.transport import MetaView
from ribosome.data_targets import load_pool
from ribosome.protocol import TaskSynapse, RevealSynapse, to_dict


def build_fake_miner(hotkey: str) -> SynthetaseNeuron:
    """SynthetaseNeuron with fake metagraph (no chain), real HTTP app."""
    neuron = SynthetaseNeuron.__new__(SynthetaseNeuron)
    neuron.args = types.SimpleNamespace(
        strict_assignment=True, rate_capacity=50, rate_refill=100.0,
        min_stake=10_000.0, network="test", netuid=1, public_ip="",
    )
    neuron.hotkey = hotkey
    fake_mg = types.SimpleNamespace(
        hotkeys=[VK, hotkey],
        S=[50_000.0, 1.0],
        block=types.SimpleNamespace(last_update=[999, 999]),
    )
    neuron.meta = MetaView(fake_mg)
    neuron.mg = types.SimpleNamespace(block=1000, tempo=360)
    neuron.pool = load_pool()
    neuron.synth = build_synthetase(types.SimpleNamespace(generator="ga", beta=2.0, seed=7))
    neuron.synth.hotkey = hotkey
    neuron.pending = PendingRevealStore()
    neuron.rate = RateLimiter(capacity=50, refill_per_sec=100.0)
    neuron.gate = ValidatorGate(min_stake=10_000.0)
    neuron.nonce_store = transport.make_nonce_store()
    return neuron


VK = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"  # fake validator hotkey


async def main() -> None:
    # two real identities: the miner serves, the validator signs requests
    tmp = tempfile.mkdtemp(prefix="ribo-smoke-")
    miner_wallet = bt.Wallet(name="ci", hotkey="ci", path=tmp)
    miner_wallet.create_new_hotkey(n_words=12, use_password=False, overwrite=True)
    val_wallet = bt.Wallet(name="v", hotkey="v", path=tmp)
    val_wallet.create_new_hotkey(n_words=12, use_password=False, overwrite=True)
    global VK
    VK = val_wallet.hotkey.ss58_address
    miner_hotkey = miner_wallet.hotkey.ss58_address
    print(f"[smoke] miner hotkey: {miner_hotkey[:12]}... validator: {VK[:12]}...")

    neuron = build_fake_miner(miner_hotkey)
    app = neuron.build_app()

    port = 8123
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    print(f"[smoke] uvicorn up on :{port}")

    client = transport.SignedHttpClient(val_wallet, timeout=5.0)
    base = f"http://127.0.0.1:{port}"

    # 1) unauthenticated request must be rejected
    import httpx
    async with httpx.AsyncClient(timeout=5.0) as raw:
        r = await raw.post(f"{base}/task", json={"epoch": 1})
        print(f"[smoke] unsigned /task -> {r.status_code} (expect 401)")
        assert r.status_code == 401

    # 2) signed /task -> commitment
    target = neuron.pool.assignment(miner_hotkey, 1)
    task = TaskSynapse(
        epoch=1, target_id=target.id,
        target_dot_bracket=target.dot_bracket,
        target_length=target.length, k_candidates=4,
    )
    status, data = await client.post_json(
        base, "/task", to_dict(task), receiver_ss58=miner_hotkey
    )
    print(f"[smoke] signed /task -> {status} commitment={str(data.get('commitment'))[:16]}...")
    assert status == 200 and data.get("commitment"), data

    # 3) signed /reveal -> payload + salt (hash-verifiable)
    reveal = RevealSynapse(epoch=1, nonce="n-1")
    status, rdata = await client.post_json(
        base, "/reveal", to_dict(reveal), receiver_ss58=miner_hotkey
    )
    print(f"[smoke] signed /reveal -> {status} verified={rdata.get('verified')}")
    assert status == 200 and rdata.get("verified")

    from ribosome.commit import commitment_hash
    recomputed = commitment_hash(rdata["sequence"], rdata["salt"], 1, target.id)
    assert recomputed == data["commitment"]
    print("[smoke] hash(revealed payload, salt) == commitment  OK")

    # 4) replay protection: same headers/body again must fail
    body = json.dumps(to_dict(task), separators=(",", ":")).encode()
    headers = bt.http_auth.sign(
        val_wallet, method="POST", path="/task", body=body,
        receiver_ss58=miner_hotkey,
    )
    async with httpx.AsyncClient(timeout=5.0) as raw:
        r1 = await raw.post(f"{base}/task", content=body, headers=headers)
        r2 = await raw.post(f"{base}/task", content=body, headers=headers)
        print(f"[smoke] first use -> {r1.status_code}, replay -> {r2.status_code} (expect 401)")
        assert r1.status_code == 200 and r2.status_code == 401

    await client.aclose()
    server.should_exit = True
    thread.join(timeout=5)
    print("[smoke] ALL TRANSPORT CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
