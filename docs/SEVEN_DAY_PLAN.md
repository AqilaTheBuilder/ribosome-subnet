# 7-Day Preparation Plan — Bittensor Global Subnet Hackathon

Written for this repo's state (mechanism done, tests green, simulation evidence
in `data/runs/`). Checkpoint #1 (Subnet Proposal) is due Sep. 20; final
submission with testnet implementation, GitHub repo, demo video and pitch is
due Oct. 19.

## Day 1 (today) — Submission hygiene
- [x] Mechanism package + 58 tests green (`pytest tests/ -q`)
- [x] Adversarial simulation evidence (`data/runs/summary.json`)
- [x] Charts: flowchart, dashboard, β-Pareto (`docs/charts/`)
- [x] Proposal PDF (`docs/PROPOSAL.pdf`) — submit to Checkpoint #1 form
- [ ] Push repo to public GitHub with this README as the landing page
- [ ] Register for office hours; bring one question: Yuma weight-staking
      interplay with delayed score reveals (B = 4)

## Day 2 — Testnet skeleton
- [ ] `pip install bittensor`; spin up local subtensor (`--local-chain`)
- [ ] Register 1 validator + 3 miner hotkeys on local chain
- [ ] `neurons/validator.py --mode testnet` phase machine ticking end-to-end
      (COMMIT → EVALUATE → SET_WEIGHTS → REVEAL → ROTATE)
- [ ] Confirm weight-setting calls succeed (`subtensor.set_weights`)

## Day 3 — Physics oracle
- [ ] Install ViennaRNA; verify `python -c "from ribosome.oracle import get_oracle; print(get_oracle('auto').name)"`
      prints `viennarna`
- [ ] Re-run simulation with `--oracle viennarna` semantics (Chaperone arg);
      record TM deltas vs Nussinov stub in `data/runs/`
- [ ] Decision gate: if ViennaRNA shifts clone Jaccard > 0.85 in any pair,
      document; otherwise keep θ_dup = 0.85

## Day 4 — Miner quality
- [ ] Plug the XGBoost stability forward model into `Synthetase.self_rank`
      (interface ready; model trained per the companion preprint: MCRMSE 0.356)
- [ ] Re-run GA miner with β = 0.5 (paper's fidelity-preserving operating point);
      target: mean TM ≥ 0.7 on medium targets with better predicted instability
- [ ] Scale GA budget (population 24 × generations 8) if wall-clock allows

## Day 5 — Real target pool
- [ ] Export 32 structures from RNASolo / Das et al. (2010) benchmark to the
      manifest schema (id, name, sequence, dot_bracket, difficulty, source)
- [ ] `python tools/build_pool_manifest.py` regenerates + validates
- [ ] Re-run simulation on the real pool; keep results in `data/runs/`

## Day 6 — Demo + pitch dry run
- [ ] Record demo video per `docs/demo_video_script.md` (≤ 4 min)
- [ ] Pitch deck: problem → mechanism → testnet evidence → roadmap (10 slides)
- [ ] Dry-run in front of someone outside the project; fix the two most
      confusing moments

## Day 7 — Buffer + submission
- [ ] Final `pytest` + fresh 20-epoch simulation on camera
- [ ] Freeze repo, tag `hackathon-final`, attach demo video
- [ ] Submit: updated proposal, GitHub link, testnet evidence, demo, pitch

## Risk register

| Risk | Signal | Mitigation |
|---|---|---|
| Bittensor API churn | neuron import errors on `pip install -U bittensor` | pin the version; mechanism package has zero bittensor imports |
| Validator quorum on testnet | scores disagree | quorum = 5, trimmed mean already in `constants.py`; log per-validator deltas |
| ViennaRNA install pain | RNAfold missing | stub oracle is the default; adapters optional by design |
| Time slip | Days 2–5 slip | Day 7 is buffer; the offline evidence stands alone for Checkpoint #1 |
