"""PDF-embed-tuned chart variants for the Checkpoint-1 proposal.

The standalone repo charts are designed for full-screen viewing (large
figsize); embedded at 451pt on A4 their fonts would fall below the 7-8pt
floor. This script re-renders the same data at embed-friendly sizes so the
smallest text stays >= 7.5pt effective at 451pt (~6.26in) display width.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

REPO = Path("/home/z/my-project/download/ribosome-network")
sys.path.insert(0, str(REPO))
LOG = REPO / "data/runs/sim_log.jsonl"
OUT = REPO / "docs/charts/pdf"
OUT.mkdir(parents=True, exist_ok=True)

STRATS = ["ga_strong", "stub_honest", "lazy", "copier", "leaker"]
LABELS = {
    "ga_strong": "GA miner",
    "stub_honest": "Stub miner",
    "lazy": "Lazy",
    "copier": "Sybil clone",
    "leaker": "Leaker",
}
COLORS = {"ga_strong": "#0077BB", "stub_honest": "#33BBEE", "lazy": "#EE7733",
          "copier": "#CC3311", "leaker": "#9CA3AF"}
G300, G400, G700, G900 = "#D1D5DB", "#9CA3AF", "#374151", "#111827"

plt.rcParams.update({
    "font.sans-serif": ["DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.facecolor": "#FFFFFF",
    "axes.edgecolor": "#E5E7EB",
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "xtick.labelsize": 10.5,
    "ytick.labelsize": 10.5,
    "axes.labelsize": 11.5,
    "legend.frameon": False,
    "legend.fontsize": 10.5,
    "figure.dpi": 200,
    "savefig.dpi": 200,
})


def clean_axis(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, alpha=0.08, color=G300)
    ax.set_axisbelow(True)


def load_events():
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()
            and json.loads(l).get("type") == "eval"]


def save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=200, facecolor="white")
    plt.close(fig)
    print(f"OK {p}")


def fig_tms(evals):
    fig, ax = plt.subplots(figsize=(7.6, 3.0), constrained_layout=True)
    data = []
    for s in STRATS:
        tms = [e["tm"] for e in evals if e["strategy"] == s and e["tm"] > 0]
        data.append(tms if tms else [0.0, 0.0])
    bp = ax.boxplot(data, tick_labels=[LABELS[s] for s in STRATS],
                    patch_artist=True, widths=0.55, showfliers=False,
                    medianprops=dict(color="white", linewidth=1.5),
                    whiskerprops=dict(color=G400), capprops=dict(color=G400),
                    boxprops=dict(linewidth=0))
    for patch, s in zip(bp["boxes"], STRATS):
        patch.set_facecolor(COLORS[s])
        patch.set_alpha(0.88)
    ax.set_ylabel("Best-candidate TM-score")
    ax.set_ylim(-0.03, 1.05)
    clean_axis(ax)
    save(fig, "fig_tms.png")


def fig_duplicates(evals):
    from ribosome.diversity import jaccard_similarity

    by = defaultdict(list)
    for e in evals:
        if (e["accepted"] or e["zero_reason"] == "sybil duplicate of an earlier commit") \
                and e.get("best_seq"):
            by[(e["epoch"], e["target_id"])].append(e)
    honest, clone = [], []
    for rows in by.values():
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                sim = jaccard_similarity(rows[i]["best_seq"], rows[j]["best_seq"])
                (clone if "copier" in (rows[i]["strategy"], rows[j]["strategy"])
                 else honest).append(sim)
    fig, ax = plt.subplots(figsize=(7.6, 3.3), constrained_layout=True)
    bins = np.linspace(0, 1, 26)
    ax.hist(honest, bins=bins, color="#33BBEE", alpha=0.9,
            label=f"honest pairs (n={len(honest)})", edgecolor="white")
    if clone:
        ax.hist(clone, bins=bins, color="#CC3311", alpha=0.9,
                label=f"Sybil clone pairs (n={len(clone)})", edgecolor="white")
    ax.axvline(0.85, color=G900, linewidth=1.4, linestyle="--")
    ax.text(0.862, max(len(honest), 1) * 0.5, r"$\theta_{dup}=0.85$",
            fontsize=12, color=G900)
    ax.set_xlabel("Pairwise k-mer Jaccard (same epoch, same target)")
    ax.set_ylabel("Pairs")
    ax.legend(loc="upper left")
    clean_axis(ax)
    save(fig, "fig_duplicates.png")


def fig_outcomes(evals):
    reason_values = ["",
                     "every candidate failed the validity gate",
                     "sybil duplicate of an earlier commit",
                     "commitment never revealed",
                     "committed to a target not in the pool (leak/fault)"]
    reason_labels = ["accepted", "gate failure", "duplicate zeroed",
                     "missed reveal", "leak rejected"]
    colors_r = ["#0077BB", G300, "#CC3311", "#F5C78A", "#E4B7C6"]
    fig, ax = plt.subplots(figsize=(6.8, 3.9), constrained_layout=True)
    y = np.arange(len(STRATS))
    left = np.zeros(len(STRATS))
    for r_idx, (rl, cr) in enumerate(zip(reason_labels, colors_r)):
        vals = []
        for s in STRATS:
            rows = [e for e in evals if e["strategy"] == s]
            n = len(rows) or 1
            share = 100.0 * sum(1 for e in rows
                                if (r_idx == 0 and e["accepted"]) or e["zero_reason"] == reason_values[r_idx]) / n
            vals.append(share)
        vals = np.array(vals)
        ax.barh(y, vals, left=left, height=0.6, color=cr,
                edgecolor="white", linewidth=0.6, label=rl)
        for yi, v in enumerate(vals):
            if v >= 9:
                ax.text(left[yi] + v / 2, yi, f"{v:.0f}%", ha="center",
                        va="center", fontsize=9.5,
                        color="white" if r_idx in (0, 2) else G700,
                        fontweight="bold" if r_idx in (0, 2) else "normal")
        left += vals
    ax.set_yticks(y)
    ax.set_yticklabels([LABELS[s] for s in STRATS])
    ax.invert_yaxis()
    ax.set_xlabel("Share of miner-epoch outcomes (%)")
    ax.set_xlim(0, 100)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3, fontsize=9.5)
    save(fig, "fig_outcomes.png")


def fig_share(evals):
    epochs = sorted({e["epoch"] for e in evals})
    shares = {s: [] for s in STRATS}
    for ep in epochs:
        rows = [e for e in evals if e["epoch"] == ep]
        tot = sum(e["final"] for e in rows)
        for s in STRATS:
            num = sum(e["final"] for e in rows if e["strategy"] == s)
            shares[s].append(100.0 * num / tot if tot > 0 else 0.0)
    fig, ax = plt.subplots(figsize=(7.6, 3.1), constrained_layout=True)
    ax.stackplot(epochs, [shares[s] for s in STRATS],
                 colors=[COLORS[s] for s in STRATS], alpha=0.88)
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Instantaneous score share (%)")
    ax.set_ylim(0, 100)
    ax.set_xlim(epochs[0], epochs[-1])
    ax.text(epochs[-1] / 2, 30, "GA miner (honest)", ha="center",
            fontsize=11, fontweight="bold", color="white")
    ax.text(epochs[-1] / 2, 74, "Stub miner (honest)", ha="center",
            fontsize=11, fontweight="bold", color="#0B3C5D")
    ax.text(epochs[-1] / 2, 96, "Lazy", ha="center", fontsize=9.5, color="#7A3A10")
    ax.text(0.4, 45, "Sybil clones + leaker: 0%", fontsize=9.5, color="#B94A48",
            va="bottom",
            bbox=dict(facecolor="white", alpha=0.85, edgecolor="none",
                      boxstyle="round,pad=0.25"))
    clean_axis(ax)
    save(fig, "fig_share.png")


def fig_pareto():
    import csv

    with (REPO / "data/paper/pareto_beta_sweep.csv").open() as f:
        rows = list(csv.DictReader(f))
    beta = [float(r["beta"]) for r in rows]
    mfe = [float(r["mfe_kcal_mol_mean"]) for r in rows]
    dist = [float(r["structure_distance_mean"]) for r in rows]
    inst = [float(r["pred_instability_mean"]) for r in rows]

    fig, ax1 = plt.subplots(figsize=(7.0, 4.2), constrained_layout=True)
    ax2 = ax1.twinx()
    ax2.spines["top"].set_visible(False)
    ln3, = ax2.plot(beta, dist, color="#CC3311", linewidth=2.2, marker="^",
                    markersize=6, markerfacecolor="white", markeredgewidth=1.8,
                    markeredgecolor="#CC3311", label="structure distance (right)")
    ln2, = ax2.plot(beta, inst, color="#009988", linewidth=1.9, marker="s",
                    markersize=5, markerfacecolor="white", markeredgewidth=1.6,
                    markeredgecolor="#009988", linestyle="--",
                    label="predicted instability (right)")
    ln1, = ax1.plot(beta, mfe, color="#0077BB", linewidth=2.2, marker="o",
                    markersize=5.5, markerfacecolor="white", markeredgewidth=1.8,
                    markeredgecolor="#0077BB", label="MFE, kcal/mol (left)")
    ax1.set_xlabel("β (stability weight in the coupled GA objective)")
    ax1.set_ylabel("MFE (kcal/mol)", color="#0077BB")
    ax1.tick_params(axis="y", labelcolor="#0077BB")
    ax2.set_ylabel("structure distance · predicted instability")
    ax1.set_xticks(beta)
    ax1.set_ylim(-58, -28)
    ax2.set_ylim(0, 1.25)
    ax1.yaxis.grid(True, alpha=0.08, color=G300)
    ax1.set_axisbelow(True)
    ax1.annotate("β = 0.1: 63% of MFE gain,\nfidelity improves",
                 xy=(0.1, -40.12), xytext=(0.32, -51.5), fontsize=10,
                 color=G700, arrowprops=dict(arrowstyle="->", color=G400, lw=1.0))
    lines = [ln1, ln3, ln2]
    ax1.legend(lines, [l.get_label() for l in lines], loc="upper left",
               bbox_to_anchor=(1.12, 1.02), fontsize=9.5)
    save(fig, "fig_pareto.png")


def main():
    evals = load_events()
    fig_tms(evals)
    fig_duplicates(evals)
    fig_outcomes(evals)
    fig_share(evals)
    fig_pareto()


if __name__ == "__main__":
    main()
