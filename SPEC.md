# Ribosome Network — Subnet Specification

**A Bittensor subnet for decentralized RNA inverse folding — miners are synthetases, validators are chaperones.**

Version 0.2.0 · Bittensor Global Subnet Hackathon 2026 · Checkpoint #1 submission

---

## 1. Problem and digital commodity

Designing an RNA sequence that folds into a prescribed structure is the core operation behind mRNA therapeutics, aptamers, ribozyme engineering and RNA switches. It is computationally expensive (each candidate must be folded and evaluated), verification is cheap relative to search when an oracle exists, and quality is measurable with well-defined structural metrics. That shape — expensive-to-produce, cheap-to-verify, objectively-scorable work — is exactly the shape of a good Bittensor digital commodity.

The subnet sells **validated inverse-folding work**: given a target secondary structure from the pool, a miner returns candidate RNA sequences; a validator refolds them with an oracle and scores structural fidelity. The commodity is the scored, ranked (sequence → structure) mapping capability of the network, consumable by mRNA-medicine and synthetic-biology users through standard Bittensor synapses.

This implementation pairs the **Ribosome Network** preprint (mechanism) with the **stability-aware inverse design** preprint (miner technology): the miner's GA ranks candidates by a coupled objective `TM − β·instability`, with the β-Pareto operating point taken from the ablation (β = 0.1–0.5 where fidelity matters).

## 2. Roles

| Role | Bittensor entity | Job | Reward driver |
|---|---|---|---|
| **Synthetase** | miner | Generate K candidate RNA sequences for the assigned target; commit–reveal them | Structural score of best candidate + diversity bonus |
| **Chaperone** | validator | Refold candidates with the oracle; score, detect duplicates, seal scores, set weights | Registration + honest evaluation (scored by consensus) |

## 3. Round lifecycle (one epoch = 15 min)

Phases follow the preprint exactly (`ribosome/constants.py`):

| Phase | Duration | Actor | What happens |
|---|---|---|---|
| COMMIT | 3 min | miner | `c = SHA256(payload ‖ salt ‖ epoch ‖ target_id)` published; payload packs K=4 candidates |
| EVALUATE | 6 min | validator | Oracle-refold each candidate; score vs target; duplicate detection; composite; seal score for B epochs |
| SET_WEIGHTS | 2 min | validator | Consume only scores whose B-epoch hold has elapsed; normalize; set Yuma weights |
| REVEAL | 2 min | miner | Publish `(payload, salt)`; hash mismatch or missed reveal ⇒ zero |
| ROTATE | 2 min | protocol | Every `T_rot = 16` epochs swap half the target pool; reject unknown target ids |

**Offline-harness mapping.** The pure-Python harness (`simulation/harness.py`) collapses the private EVALUATE query and the public REVEAL into one ledger reveal inside the epoch; on testnet these are distinct phases and the payload reaches the validator point-to-point first, publicly only in REVEAL. The mechanism semantics are unchanged.

## 4. Scoring methodology

For miner *i* with best candidate folded to structure *p* against target *t*:

```
TM_i   = base-pair F1(p, t)          # 2D proxy; 3D TM-score from RhoFold on testnet
exp_i  = base-pair F1(p, t)          # expression proxy slot; XGBoost stability model in prod
gate:  TM_i >= delta_tm = 0.35       # else score 0
S_i    = 0.7 * TM_i + 0.3 * exp_i    # composite in [0, 1]
D_i    = mean_{j in accepted, j≠i} (1 − Jaccard_k3(seq_i, seq_j))
final_i = S_i + 0.1 * D_i            # re-normalized into [0,1] for weight setting
```

Duplicate defense: among accepted miners on the same target, pairwise 3-mer Jaccard `>= θ_dup = 0.85` marks the later commit (by arrival order) as a duplicate ⇒ zero. The diversity bonus then operates on the surviving set only.

## 5. Threat model and mitigations

| Attack | Mechanism | Mitigation | Simulated result |
|---|---|---|---|
| Sybil duplication | Clone a winning miner (same generator, same seed); register keys until the slot collides with the victim's target | θ_dup = 0.85 k-mer Jaccard gate; first commit kept; duplicates zeroed | clones: TM 0.76 but **98–99% zeroed, 0.000 weight share** (20 epochs) |
| Oracle grinding | Probe validators to overfit the scoring | Delayed score reveals, B = 4: weights at epoch e consume epoch e−B scores | weights vector empty for first 4 epochs; no score is public before its weight is spent |
| Target leakage | Commit to a future/unknown target id | Pool membership check at evaluation; unknown id ⇒ zero | leakers: **100% of commits rejected** (40/40) |
| Overfitting the pool | Memorize current targets | Rotation: half the pool replaced every 16 epochs | rotation executed at epoch 16 in-sim; memorized work decays |
| Free-riding | Commit, never reveal | REVEAL phase hash check | missed reveals zeroed (2 in-sim) |
| Low-effort spam | Submit garbage | δ_tm gate at 0.35 | 45 gate failures zeroed in-sim |

## 6. Miner technology (synthetases)

Generators implement one interface (`Generator.generate(target, k, rng)`):

- **StubGenerator** — pair-respecting deterministic fill; the honest floor.
- **GAGenerator** — coupled-objective GA: population 12 × 4 generations in sim budget (paper scale: 200 × 60), tournament selection, crossover, point mutation, Lamarckian pair repair, fitness `tm_proxy(fold(seq)) − β·instability(fold, seq)` with β default 2.0 in-sim and the paper's ablation recommending β = 0.1–0.5 where fidelity matters.
- Production upgrades (interfaces ready): XGBoost stability forward model (MCRMSE 0.356 ± 0.004 on OpenVaccine SN_filter==1), ViennaRNA/RhoFold local oracle, BeeRNA/gRNAde neural generators.

## 7. Validator technology (chaperones)

Oracle chain: `StubOracle` (bundled Nussinov, memoized, ~10 ms/fold at L≈90) → `ViennaRNAOracle` (RNAfold when installed) → `RhoFoldOracle` (3D, Phase 4). One interface (`BaseOracle.fold`); mechanism code never branches on the implementation.

## 8. Target pool

`data/targets/pool_v1.json`: 54 targets (32 active + 22 reservoir) — designed motifs (stem-loops, cloverleaf, hammerhead-like, H-type pseudoknot) plus synthetic Nussinov-self-consistent folds across easy/medium/hard. Every manifest entry validated for length + bracket balance + oracle recovery. Production swaps the manifest for RNASolo / Das et al. (2010) benchmark structures — code loads by manifest, not by builder.

## 9. Implementation map

```
ribosome/
  constants.py        # every mechanism parameter, cited to the preprint
  protocol.py         # TaskSynapse / RevealSynapse / WeightSynapse (bittensor-optional)
  commit.py           # commitment hash, commit-reveal ledger, B-epoch sealed scores
  targets.py          # Target, TargetPool (32 active, rotation at T_rot=16)
  scoring.py          # base-pair F1, contact-map RMSD, TM proxy, composite + gate
  diversity.py        # k-mer shingles, Jaccard, duplicate detection, diversity bonus
  oracle.py           # Nussinov stub + ViennaRNA adapter + RhoFold placeholder
  generators/         # stub + coupled-objective GA
  miner_logic.py      # Synthetase (honest | copier | lazy | leaker sim labels)
  validator_logic.py  # Chaperone evaluation pipeline
  data_targets.py     # manifest loader + built-in fallback pool
neurons/              # miner.py / validator.py (mock + testnet modes)
simulation/           # offline harness + CLI, writes data/runs/*
tests/                # 58 pytest cases incl. attack end-to-end
data/                 # pool manifest, paper-derived CSVs, simulation runs
docs/                 # charts, demo script, 7-day plan, proposal PDF
```

## 10. Testnet deployment (Phase 3)

1. `pip install -r requirements.txt` (bittensor included) and run a local subtensor chain, or use the Bittensor testnet (`network = "test"`).
2. Register hotkeys: `btcli subnet register --netuid <uid>` for one validator + N miners.
3. Start the chaperone: `python neurons/validator.py --mode testnet --netuid <uid> --oracle viennarna`.
4. Start synthetases: `python neurons/miner.py --mode testnet --generator ga --beta 0.5` (one process per hotkey/wallet).
5. Verify: `python -m simulation.run_simulation --epochs 20` on logs mirrored from chain; expect clone zeroing ≥ 95% and weight share concentrated on GA miners (see `docs/charts/`).

## 11. Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1. Pipeline | generators, metrics (TM/RMSD/base-pair), data loaders | done (preprint) |
| 2. Mechanism | commit-reveal, duplicate gate, diversity bonus, delayed reveals, harness + tests | **done (this repo)** |
| 3. Testnet | 3 validators / 10 miners on Bittensor testnet; demo video | hackathon final (Oct 19) |
| 4. Production | RhoFold+ 3D oracle, XGBoost stability model in miner rank, RNASolo pool, GPU miners | post-hackathon |

## 12. References

1. *The Ribosome Network: A Decentralized RNA Inverse-Folding Subnet as a Synthetic Ribosome* (preprint, 2026) — mechanism source.
2. *Stability-Aware mRNA Inverse Design via Coupled Forward-Model-Guided Search* (preprint, 2026) — GA miner, β-ablation, forward model.
3. Bittensor white paper; Yuma consensus; OpenVaccine (Wayment-Steele et al., 2020); Das et al. (2010) RNA structure-prediction benchmark; RNASolo; RhoFold+ (Shen et al., 2022); ViennaRNA (Lorenz et al., 2011).
