"""Signed-HTTP transport for the Ribosome neurons (bittensor v11+).

v11 removed the axon/dendrite networking stack: neurons run their own HTTP
layer and authenticate with ``bittensor.http_auth`` ("btauth/1") — hotkey-
signed headers proving sender identity, body integrity and recency. This
module is that layer:

  MetaView          adapts a bittensor Metagraph snapshot (or any object
                    with .neurons) into the .hotkeys/.S/.block.last_update
                    shape consumed by the SDK-free gates
  SignedHttpClient  httpx.AsyncClient that signs every request body with the
                    validator/miner hotkey (http_auth.sign)
  verify_request    server-side counterpart (http_auth.verify + NonceStore)
  guess_public_ip   best-effort public IPv4 for endpoint publication

bittensor is imported lazily so the mechanism tests run SDK-free.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

BT_AVAILABLE = False
try:  # pragma: no cover - depends on environment
    import bittensor as bt

    BT_AVAILABLE = True
except ImportError:
    bt = None  # type: ignore


# --------------------------------------------------------------------------
# Metagraph adapter
# --------------------------------------------------------------------------
def _tao(balance: Any) -> float:
    """Balance (v11) -> float TAO, tolerating plain floats in fakes/tests."""
    if balance is None:
        return 0.0
    for attr in ("tao", "value"):
        v = getattr(balance, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    try:
        return float(balance)
    except (TypeError, ValueError):
        return 0.0


class MetaView:
    """Uniform metagraph view for the admission gates (SDK-free contract):

      .hotkeys              list[str]
      .S                    list[float]  total stake per uid
      .block.last_update    list[int]    last activity block per uid
      .axons                list[Optional[str]]  'ip:port' per uid (v11)
      .validator_permit     list[bool]
    """

    def __init__(self, metagraph: Any) -> None:
        self.hotkeys: list[str] = []
        self.S: list[float] = []
        self.block = None
        self.axons: list[Optional[str]] = []
        self.validator_permit: list[bool] = []
        self._last_update: list[int] = []

        neurons = getattr(metagraph, "neurons", None)
        if neurons is not None:  # v11 Metagraph snapshot
            for n in neurons:
                self.hotkeys.append(n.hotkey)
                self.S.append(_tao(getattr(n, "total_stake", None)))
                self._last_update.append(int(getattr(n, "last_update", 0) or 0))
                self.axons.append(getattr(n, "axon", None))
                self.validator_permit.append(bool(getattr(n, "validator_permit", False)))
        else:  # already a view / fake
            for attr in ("hotkeys", "S", "axons", "validator_permit"):
                v = getattr(metagraph, attr, None)
                if v is not None:
                    setattr(self, attr, list(v))
            self._last_update = list(getattr(metagraph, "_last_update", None) or [])
            if not self._last_update:
                blk = getattr(metagraph, "block", None)
                lu = getattr(blk, "last_update", None)
                if lu is not None:
                    self._last_update = list(lu)
        self.block = type("BlockView", (), {"last_update": self._last_update})()

    def endpoint_of(self, hotkey: str) -> Optional[str]:
        """http://ip:port for a hotkey with a published axon, else None."""
        try:
            axon = self.axons[self.hotkeys.index(hotkey)]
        except (ValueError, IndexError):
            return None
        if not axon:
            return None
        if axon.startswith("http"):
            return axon
        return f"http://{axon}"


# --------------------------------------------------------------------------
# client side
# --------------------------------------------------------------------------
class SignedHttpClient:
    """Async HTTP client that hotkey-signs every JSON body (btauth/1)."""

    def __init__(self, wallet: Any, timeout: float = 12.0) -> None:
        if not BT_AVAILABLE:  # pragma: no cover - guarded at call sites
            raise RuntimeError("bittensor required for SignedHttpClient")
        import httpx

        self.wallet = wallet
        self._http = httpx.AsyncClient(timeout=timeout)

    async def post_json(
        self,
        url: str,
        path: str,
        payload: Dict[str, Any],
        receiver_ss58: Optional[str] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = bt.http_auth.sign(
            self.wallet, method="POST", path=path, body=body,
            receiver_ss58=receiver_ss58,
        )
        headers["content-type"] = "application/json"
        resp = await self._http.post(url + path, content=body, headers=headers)
        try:
            data = resp.json()
        except ValueError:  # pragma: no cover - transport-level failure
            data = {}
        return resp.status_code, data

    async def aclose(self) -> None:  # pragma: no cover - trivial
        await self._http.aclose()


# --------------------------------------------------------------------------
# server side
# --------------------------------------------------------------------------
def make_nonce_store():
    """InMemoryNonceStore (replay protection) or None when SDK is absent."""
    if not BT_AVAILABLE:
        return None
    return bt.http_auth.InMemoryNonceStore()


def verify_request(
    headers: Dict[str, str],
    body: bytes,
    *,
    method: str,
    path: str,
    self_hotkey: str,
    nonce_store: Any,
    max_age: float = 10.0,
):
    """Verify an incoming signed request; returns Caller or raises AuthError."""
    if not BT_AVAILABLE:  # pragma: no cover - guarded at call sites
        raise RuntimeError("bittensor required for verify_request")
    return bt.http_auth.verify(
        headers, body, method=method, path=path,
        self_hotkey_ss58=self_hotkey, nonce_store=nonce_store,
        max_age=max_age, allowed_skew=max_age,
    )


# --------------------------------------------------------------------------
# endpoint publication (v11: ServeAxon intent, chain data only)
# --------------------------------------------------------------------------
def guess_public_ip() -> str:
    """Best-effort public IPv4 (UDP socket trick; no packet leaves the NIC)."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:  # pragma: no cover - offline
        return "127.0.0.1"
    finally:
        s.close()


def publish_endpoint(wallet: Any, network: str, netuid: int, port: int,
                     ip: Optional[str] = None, version: int = 1) -> str:
    """Publish this neuron's ip:port on chain (bt.ServeAxon intent).

    Blocking; uses a shared SyncClient. Returns the published ip:port."""
    if not BT_AVAILABLE:  # pragma: no cover - guarded at call sites
        raise RuntimeError("bittensor required for publish_endpoint")
    ip = ip or guess_public_ip()
    client = bt.SyncClient(network)
    client.execute(bt.ServeAxon(netuid=netuid, ip=ip, port=port, version=version),
                   wallet)
    return f"{ip}:{port}"


def fetch_metagraph(network: str, netuid: int):
    """Blocking metagraph snapshot via a shared SyncClient (v11)."""
    if not BT_AVAILABLE:  # pragma: no cover - guarded at call sites
        raise RuntimeError("bittensor required for fetch_metagraph")
    client = bt.SyncClient(network)
    return client.subnets.metagraph(netuid)


def chain_block(network: str) -> int:  # pragma: no cover - live chain read
    if not BT_AVAILABLE:
        raise RuntimeError("bittensor required for chain_block")
    return int(bt.SyncClient(network).chain.block())
