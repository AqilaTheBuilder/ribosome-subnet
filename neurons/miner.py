"""Synthetase neuron (miner) - production, bittensor v11.

Two run modes sharing one mechanism core:

  --mode mock      offline loop (CI / dev / demo): drives Synthetase against
                   a local TargetPool and CommitLedger without bittensor.
  --mode testnet   serves a signed-HTTP endpoint (FastAPI + uvicorn). The
                   endpoint is published on chain via the ServeAxon intent;
                   chaperone validators POST hotkey-signed requests:

                     POST /task    TaskSynapse  -> commitment (COMMIT phase)
                     POST /reveal  RevealSynapse-> (payload, salt) (REVEAL)

Every request is authenticated with bittensor.http_auth ("btauth/1":
hotkey signature over method+path+body, recency window, replay-protected
nonces). v11 removed axon/dendrite - the HTTP layer is ours, the identity
layer is the SDK's.

Security model on the endpoint:
  * auth       - signature must verify against the miner's own hotkey
  * blacklist  - only registered validators with >= min-stake tau accepted
  * rate-limit - token bucket per hotkey stops oracle-probing floods
  * assignment - announced target must equal pool.assignment(miner, epoch)
  * reveals    - pending (payload, salt) expires after 2 epochs
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

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
from ribosome.protocol import (  # noqa: E402
    RevealSynapse,
    TaskSynapse,
    from_dict,
    to_dict,
    synapse_hotkey,
)

from neurons import transport  # noqa: E402
from neurons.config import build_parser  # noqa: E402
from neurons.production_logic import (  # noqa: E402
    PendingRevealStore,
    RateLimiter,
    ValidatorGate,
)

BT_AVAILABLE = False
try:  # pragma: no cover - depends on environment
    import bittensor as bt

    BT_AVAILABLE = True
except ImportError:
    bt = None  # type: ignore

# fastapi is imported lazily-guarded: needed only for testnet mode. The
# import stays resolvable for FastAPI's string-annotation machinery
# ("fastapi.Request") while keeping the module importable without it.
try:
    import fastapi
    import uvicorn as _uvicorn
except ImportError:  # pragma: no cover - optional transport deps
    fastapi = None
    _uvicorn = None

import logging  # noqa: E402


def log(msg: str) -> None:
    logging.getLogger("ribosome.miner").info(msg)


def log_exc(msg: str) -> None:  # pragma: no cover - trivial
    logging.getLogger("ribosome.miner").warning(msg)


def fresh_salt() -> str:
    return os.urandom(16).hex()


def build_synthetase(args) -> Synthetase:
    gen = (
        GAGenerator(beta=args.beta)
        if args.generator == "ga"
        else StubGenerator()
    )
    return Synthetase(
        hotkey="",  # filled at neuron startup from the wallet
        generator=gen,
        strategy="honest",
        k_candidates=K_CANDIDATES,
        seed=args.seed,
    )


# --------------------------------------------------------------------------
# mock mode (unchanged semantics)
# --------------------------------------------------------------------------
def run_mock(args) -> None:
    logging.basicConfig(level=logging.INFO, format="[miner] %(message)s")
    pool = load_pool()
    ledger = CommitLedger()
    synth = build_synthetase(args)
    synth.hotkey = f"{args.wallet_name or 'miner'}-{args.hotkey_name or 'default'}"
    rng = random.Random(args.seed)
    for epoch in range(args.epochs):
        if pool.should_rotate(epoch):
            pool.rotate(seed=args.seed)
        target = pool.assignment(synth.hotkey, epoch)
        candidates = synth.produce(target)
        ranked = synth.self_rank(target, candidates)
        payload = join_candidates(ranked[: synth.k_candidates])
        salt = f"{synth.hotkey}-{epoch}"
        ledger.commit(
            synth.hotkey, epoch, target.id,
            commitment_hash(payload, salt, epoch, target.id),
        )
        ok = ledger.reveal(synth.hotkey, epoch, payload, salt, epoch)
        print(
            f"epoch {epoch:3d} target {target.id:12s} "
            f"k={len(ranked)} revealed={bool(ok)}"
        )
    print("mock run complete - mechanism logic exercised end to end")


# --------------------------------------------------------------------------
# testnet mode (production signed-HTTP endpoint)
# --------------------------------------------------------------------------
class SynthetaseNeuron:
    """Mechanism core + signed-HTTP serving (bittensor v11 style)."""

    def __init__(self, args: argparse.Namespace) -> None:
        if not BT_AVAILABLE:  # pragma: no cover - guarded by run_testnet
            raise RuntimeError("bittensor required for testnet mode")
        self.args = args
        self.wallet = bt.Wallet(
            name=args.wallet_name or "miner", hotkey=args.hotkey_name or "default"
        )
        self.hotkey = self.wallet.hotkey.ss58_address
        self.synth = build_synthetase(args)
        self.synth.hotkey = self.hotkey
        self.pool = load_pool()
        self.pending = PendingRevealStore(ttl_epochs=2)
        self.rate = RateLimiter(
            capacity=args.rate_capacity, refill_per_sec=args.rate_refill
        )
        self.gate = ValidatorGate(min_stake=args.min_stake)
        self.nonce_store = transport.make_nonce_store()
        self.mg = None
        self.meta = None
        self.refresh_metagraph()

    # ------------------------------------------------------ metagraph ----
    def refresh_metagraph(self) -> None:
        """Pull a fresh metagraph snapshot and wrap it for the gates."""
        self.mg = transport.fetch_metagraph(self.args.network, self.args.netuid)
        self.meta = transport.MetaView(self.mg)

    def _current_block(self) -> int:
        return int(getattr(self.mg, "block", 0) or 0)

    def _current_epoch(self) -> int:
        tempo = int(getattr(self.mg, "tempo", 0) or 360)
        return self._current_block() // max(1, tempo)

    # ------------------------------------------------------- endpoints ----
    async def forward_task(self, synapse: TaskSynapse) -> TaskSynapse:
        """COMMIT phase: generate candidates, answer with the hash."""
        hotkey = synapse_hotkey(synapse)
        if not self.rate.allow(hotkey):
            synapse.commitment = None
            return synapse
        allowed, reason = self.gate.check(
            synapse, self.meta, self._current_block(), own_hotkey=self.hotkey
        )
        if not allowed:
            log(f"denied task from {hotkey[:10]}...: {reason}")
            synapse.commitment = None
            return synapse

        target = self.pool.assignment(self.hotkey, synapse.epoch)
        if self.args.strict_assignment and target.id != synapse.target_id:
            log(
                f"target mismatch from {hotkey[:10]}...: got {synapse.target_id}, "
                f"expected {target.id} - refusing"
            )
            synapse.commitment = None
            return synapse

        candidates = self.synth.produce(target)
        ranked = self.synth.self_rank(target, candidates)
        payload = join_candidates(ranked[: self.synth.k_candidates])
        salt = fresh_salt()
        commitment = commitment_hash(payload, salt, synapse.epoch, target.id)
        self.pending.put(self.hotkey, synapse.epoch, target.id, payload, salt)
        synapse.commitment = commitment
        synapse.miner_hotkey = self.hotkey
        log(f"committed {commitment[:12]}... epoch {synapse.epoch} target {target.id}")
        return synapse

    async def forward_reveal(self, synapse: RevealSynapse) -> RevealSynapse:
        """REVEAL phase: hand back (payload, salt) for this epoch."""
        hotkey = synapse_hotkey(synapse)
        allowed, reason = self.gate.check(
            synapse, self.meta, self._current_block(), own_hotkey=self.hotkey
        )
        if not allowed:
            log(f"denied reveal from {hotkey[:10]}...: {reason}")
            synapse.verified = False
            return synapse
        entry = self.pending.pop(self.hotkey, synapse.epoch)
        if entry is None:
            synapse.verified = False
            log(f"no pending reveal for epoch {synapse.epoch}")
            return synapse
        synapse.sequence = entry.payload
        synapse.salt = entry.salt
        synapse.verified = True
        log(f"revealed epoch {synapse.epoch} target {entry.target_id}")
        return synapse

    # ------------------------------------------------------------ HTTP ----
    def build_app(self):
        """FastAPI app exposing /task and /reveal behind btauth/1."""
        if fastapi is None:  # pragma: no cover - optional dep
            raise RuntimeError(
                "fastapi+uvicorn required for testnet mode: pip install fastapi uvicorn"
            )
        JSONResponse = fastapi.responses.JSONResponse

        app = fastapi.FastAPI(title="Ribosome synthetase neuron", version="1.0")

        async def _handle(request, path: str, cls, handler):
            body = await request.body()
            try:
                caller = transport.verify_request(
                    dict(request.headers), body, method="POST", path=path,
                    self_hotkey=self.hotkey, nonce_store=self.nonce_store,
                )
            except Exception as exc:  # AuthError family
                return JSONResponse(
                    {"error": f"auth failed: {exc}"}, status_code=401
                )
            try:
                data = json.loads(body) if body else {}
            except ValueError:
                return JSONResponse({"error": "bad json"}, status_code=400)
            synapse = from_dict(cls, data)
            # authenticated identity -> the SDK-free gates read this field
            synapse.dendrite_hotkey = caller.hotkey_ss58
            out = await handler(synapse)
            return JSONResponse(to_dict(out))

        @app.get("/health")
        async def health():  # unauthenticated liveness probe
            return {"ok": True, "block": self._current_block()}

        @app.post("/task")
        async def task(request: "fastapi.Request"):
            return await _handle(request, "/task", TaskSynapse, self.forward_task)

        @app.post("/reveal")
        async def reveal(request: "fastapi.Request"):
            return await _handle(
                request, "/reveal", RevealSynapse, self.forward_reveal
            )

        return app

    # ------------------------------------------------------ background ----
    async def housekeeping(self) -> None:
        """Periodic metagraph refresh + pending-reveal eviction."""
        while True:
            await asyncio.sleep(60)
            try:
                self.refresh_metagraph()
                evicted = self.pending.evict_expired(self._current_epoch())
                if evicted:
                    log(f"evicted {evicted} stale pending reveals")
            except Exception as exc:  # pragma: no cover - network errors
                log(f"housekeeping error: {exc}")

    # ---------------------------------------------------------- main ----
    async def serve(self) -> None:  # pragma: no cover - needs live chain
        import uvicorn

        logging.basicConfig(level=logging.INFO, format="[miner] %(message)s")
        app = self.build_app()
        published = transport.publish_endpoint(
            self.wallet, self.args.network, self.args.netuid,
            self.args.axon_port, ip=self.args.public_ip or None,
        )
        log(f"serving synthetase on {published} (netuid {self.args.netuid})")
        keeper = asyncio.create_task(self.housekeeping())
        config = uvicorn.Config(
            app, host="0.0.0.0", port=self.args.axon_port, log_level="info"
        )
        try:
            await uvicorn.Server(config).serve()
        finally:
            keeper.cancel()
            log("endpoint stopped cleanly")


def run_testnet(args) -> None:  # pragma: no cover - needs bittensor + chain
    if not BT_AVAILABLE:
        print("bittensor is not installed: pip install bittensor")
        sys.exit(1)
    neuron = SynthetaseNeuron(args)
    try:
        asyncio.run(neuron.serve())
    except KeyboardInterrupt:
        log("shut down")


def main() -> None:
    args = build_parser("miner").parse_args()
    if args.mode == "mock":
        run_mock(args)
    else:
        run_testnet(args)


if __name__ == "__main__":
    main()
