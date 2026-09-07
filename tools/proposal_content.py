"""Checkpoint-1 proposal content: Ribosome Network.

Block types consumed by make_proposal_pdf.py:
  ("body", text)                      paragraph (supports <b> <i> <super> <sub>)
  ("h2", text)                        sub-heading
  ("bullet", [items])                 bullet list
  ("callouts", [(value, label), ...]) stat callout row (max 3)
  ("table", {...})                    headers/rows/ratios/caption
  ("figure", {...})                   path/caption/max_h
  ("quote", text)                     pull quote
"""

DOC_TITLE = "Ribosome Network - A Decentralized RNA Inverse-Folding Subnet"
DOC_AUTHOR = "Ribosome Network Team"
DOC_SUBJECT = "Bittensor Global Subnet Hackathon 2026 - Checkpoint 1 Subnet Proposal"

CHAPTERS = [
    # ---------------------------------------------------------------- 1 --
    {
        "title": "Executive Summary",
        "numbered": True,
        "blocks": [
            ("body",
             "The Ribosome Network is a Bittensor subnet that produces validated "
             "RNA inverse-folding work: given a target RNA structure drawn from a "
             "rotating pool, miners called <b>synthetases</b> return candidate "
             "sequences, and validators called <b>chaperones</b> refold every "
             "candidate with an oracle and score its structural fidelity. The "
             "commodity is expensive to produce, cheap to verify with a folding "
             "oracle, and scored by objective structural metrics - exactly the "
             "shape of work a decentralized network should coordinate. The "
             "mechanism implemented for this hackathon turns the Ribosome Network "
             "preprint's interface stubs into a working subnet layer: a five-phase "
             "commit-reveal round, a duplicate gate, a diversity bonus, delayed "
             "score reveals, and deterministic target-pool rotation."),
            ("body",
             "Everything in this proposal runs. The repository ships a pure-Python "
             "mechanism package with 58 passing tests, an adversarial offline "
             "simulation that pits honest miners against four attack strategies "
             "across 20 epochs, and the charts generated from those runs. The "
             "headline evidence is summarized below: Sybil clones fold as well as "
             "their victims yet earn exactly zero weight, leakers are rejected "
             "every time, and honest quality concentrates network reward."),
            ("callouts", [
                ("98-99%", "Sybil clones zeroed as duplicates"),
                ("0.000", "clone weight share across 20 epochs"),
                ("100%", "leaker commits rejected (40 of 40)"),
            ]),
            ("body",
             "The miner technology comes from our companion work on stability-aware "
             "mRNA inverse design, which measured the Pareto frontier between "
             "structural fidelity and thermodynamic stability for a coupled "
             "genetic algorithm. That measured trade-off - with a sweet spot at "
             "low beta where most of the stability gain comes at essentially zero "
             "fidelity cost - becomes the scoring heart of our production miner. "
             "We are asking the judges for a Bittensor testnet slot and incubation "
             "to take a mechanism that already survives its own attack surface "
             "onto a live network with three validators and ten miners."),
        ],
    },
    # ---------------------------------------------------------------- 2 --
    {
        "title": "Problem and Digital Commodity",
        "numbered": True,
        "blocks": [
            ("body",
             "Designing an RNA sequence that folds into a prescribed structure is "
             "the core operation behind mRNA therapeutics, aptamers, ribozymes and "
             "synthetic switches. Modern mRNA medicine adds a second constraint: "
             "the designed sequence must not only fold correctly but also fold "
             "stably, because degradation rates track structural stability. The "
             "search is genuinely expensive - each candidate must be folded, and "
             "meaningful design explores a space that grows as 4<super>n</super> - "
             "while verification is comparatively cheap once an oracle exists. "
             "Quality is not a matter of taste: base-pair F1, contact-map RMSD and "
             "TM-score are objective, reproducible measures. This asymmetry "
             "between costly production and cheap verification is precisely the "
             "contract a Bittensor subnet is designed to enforce."),
            ("body",
             "The subnet therefore sells a digital commodity: scored, ranked "
             "(sequence to structure) design work for target structures chosen by "
             "the network. Consumers - mRNA therapeutic developers, vaccine "
             "design teams, synthetic biology laboratories - buy the network's "
             "cumulative inverse-folding capability through standard synapses "
             "rather than building in-house folding and search infrastructure. "
             "Each epoch the commodity is produced fresh against a moving target "
             "pool, so the network's capability cannot be bought once and "
             "replayed; it must be earned continuously."),
            ("body",
             "Our companion preprint supplies the miner-side technology with "
             "measured numbers. A forward model trained on 1,589 SN-filter==1 "
             "OpenVaccine sequences (107 nt, 68 scored positions) reaches a "
             "group-aware 5-fold MCRMSE of 0.356 plus or minus 0.004, and a "
             "coupled genetic algorithm trading structure distance against "
             "predicted instability moves MFE from -33.1 to -51.9 kcal/mol across "
             "the measured beta sweep while quantifying exactly how much fidelity "
             "each unit of stability costs. Section 4 uses that measured frontier "
             "as the miner's ranking objective; the subnet mechanism is "
             "agnostic to which generator plugs in."),
        ],
    },
    # ---------------------------------------------------------------- 3 --
    {
        "title": "Subnet Architecture and Round Lifecycle",
        "numbered": True,
        "blocks": [
            ("body",
             "Two roles coordinate every epoch. Synthetases (miners) design "
             "sequences; chaperones (validators) refold, score and weight them. "
             "The design intentionally mirrors molecular biology: a ribosome "
             "synthesizes from a template and chaperone proteins verify the fold, "
             "so the network is a synthetic ribosome whose product is RNA design "
             "itself. Targets live in a pool of 32 active structures; every 16 "
             "epochs half the pool is swapped from a 54-structure reservoir "
             "(manifest in the repository, validated for bracket balance and "
             "oracle self-consistency)."),
            ("figure", {
                "path": "docs/charts/pdf/fig_phase_strip.png",
                "caption": "Figure 1 - The five phases of one 15-minute epoch. "
                           "Full expanded flowchart: docs/charts/chart_mechanism_flowchart.png",
                "max_h": 150,
            }),
            ("table", {
                "caption": "Table 1 - Phase schedule, actors and enforcement",
                "ratios": [0.16, 0.11, 0.22, 0.51],
                "headers": ["Phase", "Clock", "Actor", "What is enforced"],
                "rows": [
                    ["COMMIT", "3 min", "Synthetases",
                     "SHA-256 of the packed K=4 candidate payload, salted and bound "
                     "to (epoch, target_id); nothing to steal, no post-hoc swaps"],
                    ["EVALUATE", "6 min", "Chaperones",
                     "Oracle refold of every candidate; TM + base-pair F1 scoring "
                     "against the target; validity gate at 0.35; duplicate "
                     "detection; composite sealed for B = 4 epochs"],
                    ["SET_WEIGHTS", "2 min", "Chaperones",
                     "Only scores whose B-epoch hold elapsed are consumed; "
                     "weights normalized and set through Yuma consensus"],
                    ["REVEAL", "2 min", "Synthetases",
                     "Public (payload, salt); hash mismatch or missed reveal "
                     "scores zero"],
                    ["ROTATE", "2 min", "Protocol",
                     "Half the target pool swapped every T_rot = 16 epochs; "
                     "commits naming targets absent from the pool are rejected"],
                ],
            }),
            ("body",
             "One mapping between the offline harness and the eventual testnet is "
             "worth stating plainly. In the pure-Python harness the private "
             "evaluation query and the public reveal are collapsed into a single "
             "ledger reveal inside the epoch; on Bittensor these are distinct "
             "phases, with the payload first passing point-to-point from miner to "
             "validator and becoming public only in REVEAL. The enforcement "
             "semantics - commit-first, hash-verified, delayed scores - are "
             "identical in both settings, which is why the simulation is "
             "meaningful evidence for the testnet design."),
        ],
    },
    # ---------------------------------------------------------------- 4 --
    {
        "title": "Miner Responsibilities and Tasks",
        "numbered": True,
        "blocks": [
            ("body",
             "Each epoch a synthetase is assigned one target structure, "
             "deterministically derived from its hotkey and the epoch so that "
             "every miner's history is auditable and every target keeps a stable "
             "population of miners - which is precisely the condition under which "
             "duplicate detection has teeth. The miner generates K = 4 candidate "
             "sequences for the target's dot-bracket, ranks them with local "
             "compute, packs the ranked candidates into one payload, and commits "
             "its hash. Generating several candidates is legitimate compute "
             "spending: only the best candidate earns the structural score, with "
             "diversity rewarded separately, so K is quality insurance rather "
             "than spam."),
            ("h2", "The generator family"),
            ("body",
             "Generators implement one interface - produce k valid sequences for "
             "a target - so the market of miners can range from simple to "
             "state-of-the-art without touching the mechanism. The bundled "
             "<b>StubGenerator</b> fills target-paired positions with "
             "complementary nucleotides and samples the rest: it is the honest "
             "floor. The bundled <b>GAGenerator</b> implements the coupled "
             "objective from our stability-aware design preprint: candidates are "
             "selected by TM-score of their oracle fold minus beta times a "
             "thermodynamic-instability proxy, with tournament selection, "
             "crossover and Lamarckian repair of target-pair positions. Production "
             "miners upgrade the instability term to the trained XGBoost forward "
             "model (MCRMSE 0.356) and the structural term to full folding "
             "physics - the interface is unchanged."),
            ("figure", {
                "path": "docs/charts/pdf/fig_pareto.png",
                "caption": "Figure 2 - The measured beta-Pareto frontier from the "
                           "companion preprint (30 target structures; means over the "
                           "beta sweep). The subnet's operating guidance: beta = 0.1-0.5 "
                           "where fidelity matters.",
                "max_h": 240,
            }),
            ("body",
             "The frontier matters because it converts 'stable designs' from a "
             "vibe into a measured trade-off: at beta = 0.1 the GA captures 63 "
             "percent of the achievable MFE improvement while slightly improving "
             "fold fidelity over a pure-structure search, while beta of 1.0 and "
             "above erodes fidelity to the point where 13 to 19 positions "
             "disagree with the target. A miner that wants network reward must "
             "clear the 0.35 structural gate first; the coupled objective is how "
             "it buys stability with the fidelity it can spare."),
        ],
    },
    # ---------------------------------------------------------------- 5 --
    {
        "title": "Validator Responsibilities and Evaluation",
        "numbered": True,
        "blocks": [
            ("body",
             "The chaperone's evaluation pipeline is the subnet's source of "
             "truth, so it is deliberately mechanical. After the COMMIT phase "
             "closes, the validator walks every committed hotkey in arrival "
             "order: it rejects targets absent from the pool, drops unrevealed "
             "commitments, verifies the reveal's hash, refolds every revealed "
             "candidate with the oracle, scores the best candidate against the "
             "target, applies the validity gate, and only then lets survivors "
             "into duplicate detection and diversity accounting. Sealed scores "
             "are stored with a reveal epoch of B = 4; the weights staged in the "
             "same epoch consume only scores whose hold has elapsed."),
            ("h2", "The oracle chain"),
            ("body",
             "Oracle choice is a configuration, not a code path. The bundled "
             "<b>StubOracle</b> is a memoized Nussinov folder in pure "
             "Python/numpy - about ten milliseconds per fold at length 90 - "
             "which is what the simulation and the tests run on. The "
             "<b>ViennaRNAOracle</b> shells out to RNAfold for physics-grade "
             "secondary-structure folding when the binary is present. The "
             "<b>RhoFoldOracle</b> slot awaits a RhoFold+ checkpoint in Phase 4, "
             "at which point the 2D base-pair F1 proxy upgrades to a 3D TM-score "
             "and contact-map RMSD without any change to the mechanism above it. "
             "Metrics already shipped: base-pair F1, contact-map RMSD, and the "
             "composite gate."),
            ("body",
             "Validators are themselves scored by consensus: each validator's "
             "weights are compared against the quorum and deviations cost the "
             "deviator stake through Yuma. The quorum (5 validators) and trimmed "
             "mean (trim 1) parameters ship in the mechanism constants, and the "
             "harness records per-epoch sealed scores so validator disagreement "
             "is auditable from the logs."),
        ],
    },
    # ---------------------------------------------------------------- 6 --
    {
        "title": "Incentive and Reward Mechanism",
        "numbered": True,
        "blocks": [
            ("body",
             "The reward function is short enough to state completely. For miner "
             "i with best candidate folded to structure p against target t: the "
             "structural term is the base-pair F1 between p and t (upgraded to a "
             "true TM-score when the 3D oracle ships); the expression term is the "
             "fidelity proxy in 2D and the stability forward model in "
             "production; a candidate whose structural term falls below the 0.35 "
             "gate earns nothing. The composite is 0.7 times the structural term "
             "plus 0.3 times the expression term, a diversity bonus of 0.1 times "
             "the miner's mean pairwise 3-mer distance to the other accepted "
             "miners is added, and the result is max-normalized into the weight "
             "vector Yuma consumes."),
            ("callouts", [
                ("S = 0.7·TM + 0.3·exp", "validity-gated composite"),
                ("+ 0.1·diversity", "mean pairwise k-mer distance"),
                ("B = 4 epochs", "score seal before weights consume it"),
            ]),
            ("body",
             "Each defense exists because a specific failure mode pays otherwise. "
             "Commit-first closes sequence theft: there is nothing to copy until "
             "the author is already credited. The duplicate gate closes Sybil "
             "farming: copying a winner's output is free to attempt and earns "
             "exactly zero, because the later commit by arrival order is the one "
             "zeroed. Delayed score reveals close oracle grinding: by the time a "
             "score is public the weights that consumed it are four epochs old, "
             "so probing the validator teaches nothing actionable. Pool rotation "
             "closes memorization: half the target pool is replaced every 16 "
             "epochs, so overfit strategies decay on a schedule. Rejected unknown "
             "target ids close leakage: a miner claiming to know the future pool "
             "is either leaking or faulty, and both cases score zero."),
            ("body",
             "The emission flow follows standard Bittensor economics: the chain "
             "emits TAO to the subnet proportional to its registered stake and "
             "Yuma-normalized weights; validators take their configured cut; the "
             "remainder flows to miners in proportion to their normalized final "
             "scores. Because the diversity bonus re-normalizes only among "
             "accepted miners, the mechanism has no mechanism-level subsidy for "
             "failure - every zero is a zero."),
        ],
    },
    # ---------------------------------------------------------------- 7 --
    {
        "title": "Scoring Methodology and Anti-Gaming",
        "numbered": True,
        "blocks": [
            ("body",
             "The full scoring stack, in evaluation order, is tabulated below. "
             "Every parameter is a named constant in the mechanism package - "
             "there are no magic numbers buried in code paths - and every "
             "enforcement step writes a structured event to the run log, so any "
             "weight a validator sets can be replayed from the ledger alone."),
            ("table", {
                "caption": "Table 2 - The scoring stack",
                "ratios": [0.24, 0.44, 0.32],
                "headers": ["Step", "Definition", "Failure consequence"],
                "rows": [
                    ["Target membership",
                     "commit's target_id must be in the active pool",
                     "zero; logged as leak or fault"],
                    ["Reveal integrity",
                     "SHA-256(payload, salt, epoch, target) matches commitment",
                     "zero on mismatch or missed reveal"],
                    ["Validity gate",
                     "best-candidate TM >= 0.35 (delta_tm)",
                     "zero below gate"],
                    ["Duplicate gate",
                     "3-mer Jaccard vs earlier accepted commits < 0.85 "
                     "(theta_dup), first commit kept",
                     "later duplicates zeroed"],
                    ["Composite",
                     "0.7 x TM + 0.3 x expression term",
                     "score in [0, 1]"],
                    ["Diversity bonus",
                     "+ 0.1 x mean pairwise (1 - Jaccard) over accepted set",
                     "re-normalized to [0, 1]"],
                    ["Delayed reveal",
                     "score sealed until epoch + B (B = 4)",
                     "weights consume only revealed scores"],
                ],
            }),
            ("h2", "Threat model and measured outcomes"),
            ("table", {
                "caption": "Table 3 - Attacks, mitigations, and 20-epoch simulation results",
                "ratios": [0.20, 0.30, 0.28, 0.22],
                "headers": ["Attack", "Mitigation", "Simulated result",
                            "Verdict"],
                "rows": [
                    ["Sybil clone (same generator, same seed, colliding slot)",
                     "theta_dup = 0.85 k-mer gate, first commit kept",
                     "TM 0.76 but 98-99% zeroed; weight share 0.000",
                     "defense holds"],
                    ["Oracle grinding",
                     "delayed score reveals, B = 4",
                     "no score public before its weight is spent",
                     "defense holds"],
                    ["Target leakage",
                     "pool membership check on every commit",
                     "40 of 40 leaker commits rejected",
                     "defense holds"],
                    ["Pool overfitting",
                     "half-pool rotation every 16 epochs",
                     "rotation executed at epoch 16 in-sim",
                     "defense holds"],
                    ["Free-riding (commit, no reveal)",
                     "REVEAL hash check",
                     "missed reveals zeroed",
                     "defense holds"],
                    ["Low-effort spam",
                     "delta_tm = 0.35 gate",
                     "45 gate failures zeroed in 20 epochs",
                     "defense holds"],
                ],
            }),
            ("body",
             "Parameter sensitivity was kept deliberately boring: thresholds sit "
             "far from measured distributions rather than at knife edges. Honest "
             "same-target pairs peak below 0.7 Jaccard in the simulation while "
             "clones sit at 1.0, so the 0.85 threshold has wide margin on both "
             "sides; the 0.35 gate clears 99 percent of honest GA submissions "
             "while cutting the bulk of stub-miner failures; and the B = 4 delay "
             "is long relative to the one-epoch usefulness of a probed score."),
        ],
    },
    # ---------------------------------------------------------------- 8 --
    {
        "title": "Implementation Evidence: Simulation Results",
        "numbered": True,
        "blocks": [
            ("body",
             "The adversarial harness runs the full mechanism over 20 epochs with "
             "32 miners - 12 coupled-GA honest miners, 10 honest stub miners, 6 "
             "Sybil clones, 2 lazy miners, 2 leakers - against the 32-target "
             "pool, with one chaperone scoring and B = 4 delayed weight "
             "application. Clones are built the way a real Sybil operator would "
             "build them: identical generator and seed as a victim, with the "
             "hotkey registered until its slot collides with the victim's target. "
             "Everything below is generated by two commands in the repository "
             "(pytest and run_simulation) from a fixed seed."),
            ("figure", {
                "path": "docs/charts/pdf/fig_tms.png",
                "caption": "Figure 3 - Best-candidate TM-score by strategy. Clones "
                           "match victim quality: TM alone cannot catch them.",
                "max_h": 200,
            }),
            ("figure", {
                "path": "docs/charts/pdf/fig_share.png",
                "caption": "Figure 4 - Instantaneous score share by strategy. "
                           "Reward concentrates on honest quality; clones are invisible.",
                "max_h": 200,
            }),
            ("body",
             "Quality and reward separate exactly as designed. GA miners hold 12 "
             "of 32 slots (37.5 percent of the population) and take roughly 47 "
             "percent of network weight; honest stub miners hold 31 percent of "
             "slots and earn 28 percent; clones - folding as well as their "
             "victims - earn nothing at all because the duplicate gate fires on "
             "their identical payloads before diversity or composite scores are "
             "even computed."),
            ("figure", {
                "path": "docs/charts/pdf/fig_duplicates.png",
                "caption": "Figure 5 - Pairwise 3-mer Jaccard among accepted or "
                           "duplicate-flagged miners sharing a target. The theta_dup "
                           "line sits in a wide empty gap.",
                "max_h": 205,
            }),
            ("figure", {
                "path": "docs/charts/pdf/fig_outcomes.png",
                "caption": "Figure 6 - Outcome decomposition per strategy over "
                           "600 miner-epochs. Every attack path earns zero.",
                "max_h": 205,
            }),
            ("body",
             "The duplicate histogram is the single most important picture in "
             "this proposal. Honest miners sharing a target produce sequences "
             "whose k-mer similarity clusters well below 0.7; Sybil clones and "
             "their victims sit at exactly 1.0. A threshold of 0.85 therefore "
             "does not separate two intertwined populations - it separates two "
             "populations that never touch, which is the robust regime for a "
             "security parameter. Combined with first-commit-kept ordering, the "
             "attack economics are final: cloning costs the operator hardware "
             "and registration, and returns zero emission, every epoch."),
        ],
    },
    # ---------------------------------------------------------------- 9 --
    {
        "title": "Expected Users and Ecosystem Value",
        "numbered": True,
        "blocks": [
            ("body",
             "The commodity has an existing industry on the demand side. mRNA "
             "therapeutic and vaccine developers need sequences that fold "
             "correctly and degrade slowly; the OpenVaccine benchmark this "
             "subnet's forward model is trained on exists precisely because that "
             "pair of properties is the binding constraint. Synthetic biology "
             "teams designing riboswitches, aptamers and ribozymes need the same "
             "operation at smaller scale. These users consume the network "
             "through standard synapses - submit a target structure, receive "
             "ranked candidate sequences with oracle scores - or through periodic "
             "benchmark reports the network publishes from its own evaluation "
             "runs."),
            ("body",
             "For the Bittensor ecosystem the subnet adds three things. First, a "
             "clean verification story: folding oracles are deterministic and "
             "reproducible, which makes validator consensus auditable in a way "
             "subjective commodities are not. Second, a measurable capability "
             "curve: because targets rotate from published benchmarks, the "
             "network's structural scores over time are directly comparable "
             "against academic baselines - the subnet cannot quietly regress. "
             "Third, a bridge to computational biology talent: the generator "
             "interface admits everything from Kaggle-grade models to "
             "state-of-the-art neural inverse folders, so competing on this "
             "subnet is meaningful to researchers who have never touched a "
             "blockchain. The selected-builder opportunities attached to this "
             "hackathon - incubation and accelerator interviews - are the right "
             "next step for exactly this reason."),
        ],
    },
    # --------------------------------------------------------------- 10 --
    {
        "title": "Roadmap to Testnet and Mainnet",
        "numbered": True,
        "blocks": [
            ("body",
             "The project is sequenced so that each phase ends with something "
             "that runs. Phase 1, the pre-pipeline of generators, metrics and "
             "data loaders, was completed in the companion preprint. Phase 2 - "
             "the mechanism layer submitted here - is finished and tested: "
             "commit-reveal ledger, duplicate gate, diversity bonus, delayed "
             "score reveals, pool rotation, both neurons in mock mode, the "
             "adversarial harness, and 58 green tests. Phase 3 is the hackathon "
             "final on October 19: three validators and ten miners on Bittensor "
             "testnet, a demo video recorded from the live network, and ViennaRNA "
             "replacing the stub oracle. Phase 4 is production: RhoFold+ 3D "
             "refolding, the trained stability forward model inside the miner "
             "ranking path, an RNASolo-sourced target pool, and GPU-backed "
             "miners."),
            ("table", {
                "caption": "Table 4 - Phase status and deliverables",
                "ratios": [0.14, 0.44, 0.20, 0.22],
                "headers": ["Phase", "Scope", "Status", "Evidence"],
                "rows": [
                    ["1. Pipeline", "generators, metrics (TM / RMSD / base-pair), "
                     "data loaders", "done (preprint)",
                     "companion paper + repo modules"],
                    ["2. Mechanism", "commit-reveal, duplicate gate, diversity, "
                     "delayed reveals, rotation, harness, tests",
                     "done - this submission",
                     "58 tests, 20-epoch run, charts"],
                    ["3. Testnet", "3 validators / 10 miners on testnet, "
                     "ViennaRNA oracle, demo video",
                     "Oct 19 target", "live network demo"],
                    ["4. Production", "RhoFold+ 3D oracle, XGBoost miner ranking, "
                     "RNASolo pool, GPU miners",
                     "post-hackathon", "incubation plan"],
                ],
            }),
            ("body",
             "The seven-day operational plan through testnet is committed in the "
             "repository (docs/SEVEN_DAY_PLAN.md): testnet skeleton on day 2, "
             "ViennaRNA oracle swap on day 3, forward-model ranking on day 4, "
             "the real RNASolo target pool on day 5, and demo recording with "
             "buffer on days 6 and 7. Each day ends with a runnable artifact, so "
             "slippage costs a day, never the submission."),
        ],
    },
    # --------------------------------------------------------------- ref --
    {
        "title": "References",
        "numbered": False,
        "blocks": [
            ("body",
             "The mechanism and miner technology in this proposal come from two "
             "companion preprints by the team, supplied as hackathon materials; "
             "the remaining citations anchor the oracle, dataset and benchmark "
             "choices."),
            ("bullet", [
                "<b>The Ribosome Network: A Decentralized RNA Inverse-Folding "
                "Subnet as a Synthetic Ribosome.</b> Team preprint, 2026. "
                "Mechanism source: roles, phase schedule, theta_dup = 0.85, "
                "w_div = 0.1, N_pool = 32, T_rot = 16, B = 4.",
                "<b>Stability-Aware mRNA Inverse Design via Coupled "
                "Forward-Model-Guided Search.</b> Team preprint, 2026. Miner "
                "source: coupled GA, beta ablation (Table 5), XGBoost forward "
                "model MCRMSE 0.356 plus or minus 0.004.",
                "<b>Wayment-Steele, H. et al.</b> Probing RNA dynamics via live "
                "NMR and self-supervised machine learning. OpenVaccine dataset, "
                "Stanford COVID-19 mRNA Vaccine Degradation Prediction, 2020.",
                "<b>Das, R. et al.</b> RNA structure prediction: critical "
                "assessment (benchmark set used for the production target pool), "
                "2010; RNASolo structure repository.",
                "<b>Shen, T. et al.</b> RhoFold+: RNA 3D structure prediction. "
                "2022. Phase-4 oracle; <b>Lorenz, R. et al.</b> ViennaRNA Package "
                "2.0. Algorithms for Molecular Biology, 2011. Secondary-structure "
                "oracles.",
            ]),
            ("h2", "Appendix A - Mechanism hyperparameters"),
            ("table", {
                "caption": "Table 5 - Complete mechanism constants (ribosome/constants.py)",
                "ratios": [0.30, 0.18, 0.52],
                "headers": ["Parameter", "Value", "Meaning"],
                "rows": [
                    ["EPOCH_LENGTH_SEC", "900", "one round, 15 minutes"],
                    ["PHASE_DURATIONS", "3/6/2/2/2 min",
                     "COMMIT / EVALUATE / SET_WEIGHTS / REVEAL / ROTATE"],
                    ["N_POOL / T_ROT", "32 / 16",
                     "active targets; half-pool rotation period (epochs)"],
                    ["K_CANDIDATES", "4",
                     "sequences per miner per epoch (paper default 8)"],
                    ["DELTA_TM", "0.35", "validity gate on structural score"],
                    ["W_STRUCT / W_EXP", "0.7 / 0.3", "composite score weights"],
                    ["SCORE_REVEAL_DELAY_B", "4", "epochs a score stays sealed"],
                    ["THETA_DUP / KMER_K", "0.85 / 3",
                     "duplicate Jaccard threshold; shingle width"],
                    ["W_DIV", "0.1", "diversity bonus weight"],
                    ["VALIDATOR_QUORUM / TRIM", "5 / 1",
                     "quorum size; trimmed-mean trim"],
                    ["GA_BETA (sim)", "2.0",
                     "coupled-objective weight; production guidance 0.1-0.5"],
                    ["GA_POP / GENS (sim)", "12 / 4",
                     "sim budget; paper scale 200 x 60"],
                ],
            }),
        ],
    },
]
