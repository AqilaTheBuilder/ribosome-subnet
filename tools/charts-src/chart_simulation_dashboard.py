"""Simulation evidence dashboard (2x2) from data/runs/sim_log.jsonl.

Panels:
  A. TM-score distribution by miner strategy (box) - quality is real
  B. Instantaneous score share by strategy over epochs - Sybils earn nothing
  C. Pairwise k-mer Jaccard among accepted miners on the same target -
     clones sit at 1.0, theta_dup=0.85 separates them from honest pairs
  D. Outcome breakdown per strategy - every attack path earns zero
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np

REPO = Path("/home/z/my-project/download/ribosome-network")
sys.path.insert(0, str(REPO))
LOG = REPO / "data/runs/sim_log.jsonl"
OUT = REPO / "docs/charts/chart_simulation_dashboard.png"

STRATS = ["ga_strong", "stub_honest", "lazy", "copier", "leaker"]
LABELS = {
    "ga_strong": "GA miner (honest)",
    "stub_honest": "Stub miner (honest)",
    "lazy": "Lazy (drops reveals)",
    "copier": "Sybil clone",
    "leaker": "Leaker",
}
C_GA, C_STUB, C_LAZY, C_COPY, C_LEAK = (
    "#0077BB", "#33BBEE", "#EE7733", "#CC3311", "#9CA3AF",
)
COLORS = {"ga_strong": C_GA, "stub_honest": C_STUB, "lazy": C_LAZY,
          "copier": C_COPY, "leaker": C_LEAK}
G200, G300, G400, G700, G900 = "#E5E7EB", "#D1D5DB", "#9CA3AF", "#374151", "#111827"

plt.rcParams.update({
    "font.sans-serif": ["DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.facecolor": "#FFFFFF",
    "axes.facecolor": "#FFFFFF",
    "axes.edgecolor": "#E5E7EB",
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.labelsize": 10,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.titlepad": 12,
    "legend.frameon": False,
    "legend.fontsize": 9,
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "savefig.facecolor": "#FFFFFF",
})


def clean_axis(ax, grid=True):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if grid:
        ax.yaxis.grid(True, alpha=0.08, color=G300)
        ax.set_axisbelow(True)


def load_events():
    events = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    return [e for e in events if e.get("type") == "eval"]


def panel_a_tms(ax, evals):
    data = []
    for s in STRATS:
        tms = [e["tm"] for e in evals if e["strategy"] == s and e["tm"] > 0.0]
        data.append(tms if tms else [0.0, 0.0, 0.0])
    bp = ax.boxplot(
        data, tick_labels=[LABELS[s].replace(" (", "\n(") for s in STRATS],
        patch_artist=True, widths=0.55, showfliers=False,
        medianprops=dict(color="white", linewidth=1.6),
        whiskerprops=dict(color=G400, linewidth=1.0),
        capprops=dict(color=G400, linewidth=1.0),
        boxprops=dict(linewidth=0),
    )
    for patch, s in zip(bp["boxes"], STRATS):
        patch.set_facecolor(COLORS[s])
        patch.set_alpha(0.85)
    ax.set_title("A · Clones match victim quality - TM alone cannot catch them",
                 loc="left")
    ax.set_ylabel("Best-candidate TM-score (per epoch)")
    ax.set_ylim(-0.03, 1.05)
    ax.annotate("leaker: TM = 0\n(every commit rejected)", xy=(4, 0.02),
                xytext=(3.55, 0.22), fontsize=8.5, color=G700,
                arrowprops=dict(arrowstyle="->", color=G400, lw=0.9))
    clean_axis(ax)


def panel_b_share(ax, evals):
    epochs = sorted({e["epoch"] for e in evals})
    shares = {s: [] for s in STRATS}
    for ep in epochs:
        rows = [e for e in evals if e["epoch"] == ep]
        tot = sum(e["final"] for e in rows)
        for s in STRATS:
            num = sum(e["final"] for e in rows if e["strategy"] == s)
            shares[s].append(100.0 * num / tot if tot > 0 else 0.0)
    ax.stackplot(
        epochs,
        [shares[s] for s in STRATS],
        labels=[LABELS[s] for s in STRATS],
        colors=[COLORS[s] for s in STRATS],
        alpha=0.85,
    )
    ax.set_title("B · Reward flows to quality - Sybil clones earn nothing", loc="left")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Instantaneous score share (%)")
    ax.set_ylim(0, 100)
    ax.set_xlim(epochs[0], epochs[-1])
    # direct band labels (no legend needed; colors match panel A)
    ax.text(epochs[-1] / 2, 30, "GA miner (honest)", ha="center",
            fontsize=10, fontweight="bold", color="white")
    ax.text(epochs[-1] / 2, 74, "Stub miner (honest)", ha="center",
            fontsize=10, fontweight="bold", color="#0B3C5D")
    ax.text(epochs[-1] / 2, 96, "Lazy (drops reveals)", ha="center",
            fontsize=8.5, color="#7A3A10")
    ax.text(0.4, 44, "Sybil clones + leaker:\n0% - invisible band",
            fontsize=8.5, color="#B94A48", va="bottom",
            bbox=dict(facecolor="white", alpha=0.85, edgecolor="none",
                      boxstyle="round,pad=0.25"))
    clean_axis(ax)


def panel_c_duplicates(ax, evals):
    from ribosome.diversity import jaccard_similarity

    by_epoch_target = defaultdict(list)
    for e in evals:
        # include duplicated miners: the pair (victim, zeroed clone) is the point
        if (e["accepted"] or e["zero_reason"] == "sybil duplicate of an earlier commit") and e.get("best_seq"):
            by_epoch_target[(e["epoch"], e["target_id"])].append(e)
    sims_honest, sims_clone = [], []
    for rows in by_epoch_target.values():
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                sim = jaccard_similarity(rows[i]["best_seq"], rows[j]["best_seq"])
                pair = (rows[i]["strategy"], rows[j]["strategy"])
                if "copier" in pair:
                    sims_clone.append(sim)
                else:
                    sims_honest.append(sim)
    bins = np.linspace(0, 1, 26)
    ax.hist(
        sims_honest, bins=bins, color=C_STUB, alpha=0.9,
        label=f"honest pairs (n={len(sims_honest)})", edgecolor="white",
    )
    if sims_clone:
        ax.hist(
            sims_clone, bins=bins, color=C_COPY, alpha=0.9,
            label=f"Sybil clone pairs (n={len(sims_clone)})", edgecolor="white",
        )
    ax.axvline(0.85, color=G900, linewidth=1.4, linestyle="--")
    ymax = max(len(sims_honest), len(sims_clone), 1)
    ax.text(0.858, ymax * 0.55, "$\\theta_{dup}$ = 0.85", fontsize=10, color=G900)
    ax.set_title("C · Clones sit at similarity 1.0 - the gate is wide", loc="left")
    ax.set_xlabel("Pairwise k-mer Jaccard (same epoch, same target)")
    ax.set_ylabel("Pairs")
    ax.legend(loc="upper right")
    clean_axis(ax)


def panel_d_outcomes(ax, evals):
    reason_values = [
        "",
        "every candidate failed the validity gate",
        "sybil duplicate of an earlier commit",
        "commitment never revealed",
        "committed to a target not in the pool (leak/fault)",
    ]
    reason_labels = ["accepted", "gate failure", "duplicate zeroed",
                     "missed reveal", "leak rejected"]
    colors_r = [C_GA, G300, C_COPY, "#F5C78A", "#E4B7C6"]
    counts = {s: [] for s in STRATS}
    for s in STRATS:
        rows = [e for e in evals if e["strategy"] == s]
        n = len(rows) or 1
        counts[s] = [
            100.0 * sum(
                1 for e in rows
                if (r == "" and e["accepted"]) or e["zero_reason"] == r
            ) / n
            for r in reason_values
        ]
    y = np.arange(len(STRATS))
    left = np.zeros(len(STRATS))
    for r_idx, (rl, cr) in enumerate(zip(reason_labels, colors_r)):
        vals = np.array([counts[s][r_idx] for s in STRATS])
        ax.barh(y, vals, left=left, height=0.62, color=cr,
                edgecolor="white", linewidth=0.6, label=rl)
        for yi, v in enumerate(vals):
            if v >= 8:
                ax.text(left[yi] + v / 2, yi, f"{v:.0f}%",
                        ha="center", va="center", fontsize=8.5,
                        color="white" if r_idx in (0, 2) else G700,
                        fontweight="bold" if r_idx in (0, 2) else "normal")
        left += vals
    ax.set_yticks(y)
    ax.set_yticklabels([LABELS[s] for s in STRATS], fontsize=9)
    ax.invert_yaxis()
    ax.set_title("D · Every attack path earns zero", loc="left")
    ax.set_xlabel("Share of miner-epoch outcomes (%)")
    ax.set_xlim(0, 100)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.18), ncol=3, fontsize=8.5)
    ax.spines["right"].set_visible(False)


def main():
    evals = load_events()
    fig = plt.figure(figsize=(15.5, 10.6), constrained_layout=True)
    gs = gridspec.GridSpec(2, 2, figure=fig, wspace=0.22, hspace=0.14)
    ax1 = fig.add_subplot(gs[0, 0])
    panel_a_tms(ax1, evals)
    ax2 = fig.add_subplot(gs[0, 1])
    panel_b_share(ax2, evals)
    ax3 = fig.add_subplot(gs[1, 0])
    panel_c_duplicates(ax3, evals)
    ax4 = fig.add_subplot(gs[1, 1])
    panel_d_outcomes(ax4, evals)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=200, facecolor="white")
    plt.close(fig)
    import os

    print(f"OK {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
