# Demo Video Script — Ribosome Network (target: 3–4 minutes)

Format: screen recording + voiceover. Record at 1080p. Every on-screen moment
maps to a command that already runs in this repo.

---

### 0. Cold open (0:00–0:20) — the problem

**Screen:** the mechanism flowchart (`docs/charts/chart_mechanism_flowchart.png`).

**VO:** "Every mRNA drug starts with the same operation: design an RNA sequence
that folds into the structure you need. It's expensive to produce, cheap to
verify, and objectively scorable. That's a digital commodity — and this is a
Bittensor subnet that produces it. This is the Ribosome Network."

### 1. Roles (0:20–0:50) — who does what

**Screen:** scroll through `SPEC.md` § 2 roles table.

**VO:** "Miners are synthetases: they receive a target structure from a rotating
pool of 32 and return four candidate sequences. Validators are chaperones:
they refold every candidate with an oracle and score structural fidelity.
Quality earns weight; every attack path earns zero."

### 2. The mechanism (0:50–1:40) — commit to rotate

**Screen:** flowchart again, walking phase by phase.

**VO:** "One epoch, fifteen minutes, five phases. Miners commit a SHA-256 of
their candidates before they can be copied. Chaperones refold and score, gate
at 0.35 TM, and zero duplicates — three-mer Jaccard above 0.85 loses everything
unless you committed first. Diversity pays a bonus. Scores stay sealed for four
epochs, so by the time a score is public the weights that consumed it are
already spent — oracle grinding is pointless. And every sixteen epochs half the
target pool rotates, so memorizing targets has no shelf life."

### 3. Live test suite (1:40–2:20) — the mechanism is real

**Screen:** terminal, `python -m pytest tests/ -q`.

**VO:** "Fifty-eight tests cover every rule you just heard. Watch the attack
tests: a Sybil clone with the same generator and the same seed as its victim —
it produces the identical sequence — and it gets zeroed, first-commit-kept.
A leaker that commits to a target outside the pool gets rejected. A missed
reveal gets zeroed."

### 4. Live adversarial simulation (2:20–3:10) — the evidence

**Screen:** run `python -m simulation.run_simulation --epochs 20`, then open
`docs/charts/chart_simulation_dashboard.png`.

**VO:** "Thirty-two miners, twenty epochs, four attack strategies running
alongside honest miners. The clones fold as well as their victims — TM 0.76 —
but they earn exactly zero weight, because the duplicate gate is wide: clones
sit at similarity 1.0, honest pairs below 0.7. The GA miners take home 47
percent of the network's weight with 12 of 32 slots. Reward follows quality;
nothing else survives."

### 5. Why it matters + roadmap (3:10–3:40) — the ask

**Screen:** β-Pareto chart, then roadmap table in `SPEC.md`.

**VO:** "The miner technology comes from our stability-aware inverse design
work: the coupled objective trades fidelity for stability along a measured
Pareto frontier, with a sweet spot at low beta. Phase 2 — the mechanism you
just saw — is done and tested. Next: three validators and ten miners on
Bittensor testnet, then the RhoFold 3D oracle and the trained stability model
in production. We're asking for a testnet slot and incubation to build the
decentralized synthesis layer for RNA medicine."

---

**Recording checklist**
- [ ] `pytest` run is green on camera (58 passed)
- [ ] simulation summary printed on camera matches the chart numbers
- [ ] flowchart PNG is legible at 1080p (zoom into phases 1–2)
- [ ] total runtime ≤ 4:00
