# Testnet Deployment Guide — Ribosome Network

Production deployment of the synthetase (miner) and chaperone (validator)
neurons on a Bittensor subnet, bittensor **v11+** API.

## 0. Prerequisites

- Python 3.11+ (or Docker)
- A Bittensor wallet: `btcli wallet create` (coldkey) + hotkey, or
  `python -c "import bittensor as bt; bt.Wallet('name','hotkey').create_new_hotkey()"`
- The hotkey registered on the subnet: `btcli subnet register --netuid <N>`
  (miners) / a validator permit for the chaperone if you want weights to count
- Firewall: miners must expose `--axon-port` (default 8091) over public IP

## 1. Install

```bash
git clone <repo> ribosome && cd ribosome
pip install -r requirements.txt
# optional GPU oracle:
#   pip install torch   + RhoFold+ repo/checkpoint (see §4)
```

Or Docker (ViennaRNA baked in):

```bash
cp .env.example .env  # edit wallet names + netuid
docker compose build
```

## 2. Run the synthetase (miner)

```bash
python neurons/miner.py --mode testnet \
    --netuid 1 \
    --wallet-name synthetase --hotkey-name default \
    --network test \
    --generator ga --beta 2.0 \
    --axon-port 8091 --public-ip <your public ip or empty to autodetect>
```

What it does on start: loads the target pool, publishes `ip:port` on chain
(`bt.ServeAxon`), then serves two hotkey-signed endpoints:

| route  | phase   | request                       | response                      |
|--------|---------|-------------------------------|-------------------------------|
| `/task`  | COMMIT  | target id + dot-bracket       | `SHA256(payload‖salt‖epoch‖target)` |
| `/reveal`| REVEAL  | nonce                         | (payload, salt) — verified by the chaperone |

Docker: `docker compose up miner`

## 3. Run the chaperone (validator)

```bash
python neurons/validator.py --mode testnet \
    --netuid 1 \
    --wallet-name chaperone --hotkey-name default \
    --network test \
    --oracle auto \
    --ema-alpha 0.3 \
    --commit-reveal-period 1 \
    --state-dir .ribosome-validator
```

The phase machine runs on chain blocks (`epoch = block // tempo`, phases in the
preprint 3/6/2/2/2 ratio): COMMIT → query every miner; EVALUATE → refold +
score + dedup + diversity (scores sealed); SET_WEIGHTS → apply sealed scores
whose B=4 hold elapsed, EMA-smooth, `bt.set_weights` (v11 auto commit-reveal);
REVEAL → hash-verify payloads; ROTATE → half the pool every 16 epochs.

State (EMA + reveal plan) is checkpointed each epoch — restart-safe.

Docker: `docker compose up validator`

## 4. Oracle selection

| `--oracle`  | what                                    | when |
|-------------|------------------------------------------|------|
| `auto`      | best available: RhoFold+ > pyviennarna > RNAfold > Nussinov | default |
| `stub`      | Nussinov (pure numpy)                    | CI / smoke |
| `viennarna` | RNAfold binary (system package)          | cheap physics |
| `pyviennarna`| `pip install viennarna` wheel           | Kaggle / no conda |
| `rhofold`   | RhoFold+ 3D refold: PDB → C3' contact map (8 Å) → non-crossing dot-bracket | production fidelity, needs GPU |

RhoFold+ setup: clone the official repo, download the checkpoint, then

```bash
export RIBOSOME_RHOFOLD_REPO=/opt/rhofold
export RIBOSOME_RHOFOLD_CKPT=/opt/rhofold/RhoFold.pt
# or pass --rhofold-repo / --rhofold-ckpt
```

On multi-GPU hosts the RhoFold oracle round-robins CUDA devices in
`fold_batch` (verified with 2x T4 and RTX Pro 6000 in `notebooks/`).

## 5. Health & operations

- Miner liveness: `curl http://miner-ip:8091/health` (unauthenticated)
- Validator logs are phase-annotated: `== epoch 42 COMMIT (block 15120) ==`
- Weights can be inspected on chain: `btcli stakes` / taostats
- The transport layer is covered by `scripts/smoke_transport.py`:
  unsigned → 401, signed → 200, replay → 401, hash-reveal roundtrip OK.

## 6. Security model (recap)

- Only registered validators with ≥ 10,000 τ stake pass the miner's gate
- Requests are replay-protected and expire after 10 s (btauth/1 window)
- Miners refuse targets that differ from `pool.assignment(hotkey, epoch)`
- Score sealing (B = 4) + EMA smoothing + v11 timelocked commit-reveal make
  weight grinding and oracle probing unprofitable
