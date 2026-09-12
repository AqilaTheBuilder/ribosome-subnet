# Kaggle GPU Notebooks

Test the Ribosome Network subnet mechanics on Kaggle with either accelerator:
**GPU T4 x2** (2 × 16 GiB — kernels split across devices) or **GPU RTX Pro 6000**
(single ~96 GiB — kernels share, bigger batches). Every kernel is device-generic
and falls back to CPU so it never hard-fails.

## Setup (once)

1. Zip this repo (`ribosome-network.zip`) and upload it to Kaggle as a
   **Dataset** (kaggle.com/datasets → New Dataset).
2. For each notebook: *File → Add Input → Your Datasets* → select it
   (or set `REPO_URL` in the bootstrap cell to your GitHub fork and let it clone).
3. *Settings → Accelerator*: GPU T4 x2 or RTX Pro 6000 · *Internet*: **ON**.

| notebook | side | what it proves |
|---|---|---|
| `01_miner_synthesase_gpu.ipynb` | miner (synthetase) | 92/92 tests green on Kaggle · oracle throughput (Nussinov vs ViennaRNA wheel) · GPU coupled-objective GA screening (4096 pop, multi-GPU) with oracle-verified uplift · commit artifacts for all 32 targets |
| `02_validator_chaperone_gpu.ipynb` | validator (chaperone) | EVALUATE budget analysis · GPU **exact** k-mer Jaccard duplicate gate (θ_dup = 0.85, clone recall at 1/2/3 mutations) · adversarial epoch (leakers 0%, clones zeroed) · optional RhoFold+ auto-wiring |
| `03_end_to_end_epoch_gpu.ipynb` | miner ⊕ validator | full 5-phase epoch with the production classes, phase timings vs the 900 s budget, 256-miner stress run, weight-share evidence |

## Verification

All three notebooks are validated end-to-end in CI-style fashion by
`scripts/validate_notebooks.py` (simulates the Kaggle filesystem, executes
every code cell, asserts the mechanism outcomes). Run it locally:

```bash
.venv-bt/bin/python scripts/validate_notebooks.py
```

## Why no bittensor in the notebooks

The notebooks exercise the **mechanism core** (`Synthetase`, `Chaperone`,
`CommitLedger`, `TargetPool`) — the identical code path the live neurons run.
The chain-facing shell (signed HTTP, `bt.set_weights`, `ServeAxon`) is a thin
layer on top, covered separately by `scripts/smoke_transport.py`. This split
is deliberate: mechanism proofs belong in reproducible notebooks; transport
proofs belong next to the SDK.
