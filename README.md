# Ribosome Network

**A Bittensor subnet for decentralized RNA inverse folding — miners are synthetases, validators are chaperones.**

Built for the [Bittensor Global Subnet Hackathon](https://hackquest.io) (Aug 22 – Oct 19, 2026).
Status: mechanism complete, **92 tests green** (mechanism + production neuron layer), 20-epoch adversarial
simulation evidence included, **production Bittensor v11 integration verified end-to-end** (signed-HTTP
transport smoke test with real wallets).

![mechanism](docs/charts/chart_mechanism_flowchart.png)

## What works right now (no GPU, no chain)

```bash
pip install -r requirements.txt        # numpy, pytest (bittensor optional)

# 1. run the full test suite (mechanism + attack tests)
python -m pytest tests/ -q

# 2. run the adversarial simulation: 32 miners, 20 epochs, 4 attack types
python -m simulation.run_simulation --epochs 20 --out data/runs

# 3. drive the miner neuron standalone (mock mode, no bittensor needed)
python neurons/miner.py --mode mock --generator ga --epochs 3

# 4. evaluate a commit ledger with the validator neuron (mock mode)
python neurons/validator.py --mode mock --epochs 1 --out /tmp/weights.json
```

Expected simulation result (see `data/runs/summary.json`):

| strategy | mean TM | accepted | weight share |
|---|---|---|---|
| GA miner (honest) | 0.75 | 99% | **47%** |
| Stub miner (honest) | 0.54 | 83% | 28% |
| Sybil clone | 0.76 | **0%** (98% zeroed as duplicates) | **0.0%** |
| Lazy (drops reveals) | 0.49 | 75% | 5% |
| Leaker | 0.00 | **0%** (100% rejected) | 0.0% |

## Mechanism in one paragraph

Every 15 minutes each miner receives a target RNA structure from a rotating pool
(32 active, half replaced every 16 epochs), generates K = 4 candidate sequences,
and commits `SHA256(payload ‖ salt ‖ epoch ‖ target)` before seeing anything it
could exploit. Validators refold the candidates with an oracle (bundled Nussinov →
ViennaRNA → RhoFold+), score the best candidate against the target
(`0.7·TM + 0.3·exp`, validity gate δ_tm = 0.35), zero duplicates
(k-mer Jaccard ≥ 0.85, first commit kept), pay a diversity bonus (0.1 × mean
pairwise distance), seal scores for 4 epochs (no oracle grinding), then set
normalized Yuma weights. Full spec: [SPEC.md](SPEC.md).

## Repository map

```
ribosome/           mechanism package (pure Python, no bittensor import)
neurons/            production neuron layer
  base logic:         production_logic.py (epoch/phase math, gates, rate
                      limiter, EMA store, commit-reveal scheduler, reveal TTL)
  transport.py        signed-HTTP layer for bittensor v11 (btauth/1):
                      MetaView adapter, SignedHttpClient, FastAPI app factory,
                      ServeAxon publication
  miner.py            synthetase neuron (mock + testnet modes)
  validator.py        chaperone neuron (mock + testnet modes)
  config.py           shared CLI (bt-style flags, degrades without SDK)
simulation/         offline adversarial harness + CLI
tests/              92 pytest cases (scoring, commit-reveal, duplicates,
                    rotation, delayed reveals, generators, end-to-end attacks,
                    + production gates/scheduler/transport/endpoint logic)
data/targets/       pool_v1.json — 54 validated targets (32 active + reservoir)
data/paper/         β-ablation + OpenVaccine CSVs from the companion preprint
data/runs/          simulation logs (JSONL) + summary.json
notebooks/          Kaggle GPU notebooks (2x T4 / RTX Pro 6000)
scripts/            transport smoke test + pool manifest builder
docs/               charts, demo video script, 7-day plan, proposal PDF
Dockerfile          production neuron image (ViennaRNA included)
docker-compose.yml  validator + miner services
```

## Bittensor v11 integration (production)

Bittensor **v11 removed the axon/dendrite/Synapse networking stack**. The
production neurons are v11-native:

| Concern | v11 approach (implemented here) |
|---|---|
| Transport | own HTTP layer — FastAPI + uvicorn on the miner, httpx on the validator |
| Authentication | `bittensor.http_auth` ("btauth/1"): hotkey signature over method+path+body, recency window, replay-protected nonce store |
| Endpoint discovery | `bt.ServeAxon` intent publishes `ip:port` on chain; the validator reads endpoints from the metagraph snapshot (`neuron.axon`) |
| Weights | `bt.set_weights(netuid, {uid: w}, wallet=...)` — conforms, preflights, retries, and picks plaintext vs timelocked commit-reveal automatically |
| Timing | phase machine driven by `block // tempo` from the metagraph snapshot (3/6/2/2/2 phase ratio, 15-min epochs) |
| Validator state | EMA-smoothed scores + commit-reveal plan checkpointed to `--state-dir` each epoch |

Hardening on the miner endpoint: stake-gated blacklist (≥ 10,000 τ validator
stake), token-bucket rate limiting per hotkey, strict target-assignment
verification (a rogue validator cannot probe miners with chosen targets), and
2-epoch TTL eviction of pending reveals. Try it locally:

```bash
.venv-bt/bin/python scripts/smoke_transport.py
# unsigned /task -> 401 | signed /task -> commitment | /reveal -> payload+salt
# hash(payload‖salt) == commitment | replayed request -> 401
```

## Testnet deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (Docker, wallets, registration,
oracle selection). Quickstart without Docker:

```bash
pip install "bittensor>=11,<12" fastapi uvicorn httpx
python neurons/miner.py --mode testnet --netuid <N> --wallet-name synthetase
python neurons/validator.py --mode testnet --netuid <N> --wallet-name chaperone --oracle auto
```
The mechanism core is identical in mock and testnet mode by design — the
simulation, the tests and the live neurons share one code path.

## Provenance

Mechanism from *The Ribosome Network* preprint (miners-as-synthetases,
chaperone validation, θ_dup = 0.85, w_div = 0.1, N_pool = 32, T_rot = 16,
B = 4). Miner technology from *Stability-Aware mRNA Inverse Design via Coupled
Forward-Model-Guided Search* (coupled GA, β-Pareto operating point, XGBoost
forward model MCRMSE 0.356).
