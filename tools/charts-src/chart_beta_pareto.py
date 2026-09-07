"""Beta-ablation Pareto frontier chart from the inverse-mRNA preprint
(data/paper/pareto_beta_sweep.csv, its Table 5)."""
import csv
import os
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

REPO = Path("/home/z/my-project/download/ribosome-network")
CSV = REPO / "data/paper/pareto_beta_sweep.csv"
OUT = REPO / "docs/charts/chart_beta_pareto.png"

C_MFE = "#0077BB"
C_DIST = "#CC3311"
C_INST = "#009988"
G300, G400, G700, G900 = "#D1D5DB", "#9CA3AF", "#374151", "#111827"

plt.rcParams.update({
    "font.sans-serif": ["DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.facecolor": "#FFFFFF",
    "axes.edgecolor": "#E5E7EB",
    "axes.spines.top": False,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "xtick.labelsize": 10,
    "ytick.labelsize": 9,
    "axes.labelsize": 10.5,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "axes.titlepad": 14,
    "legend.frameon": False,
    "legend.fontsize": 9.5,
    "figure.dpi": 200,
    "savefig.dpi": 200,
})


def main():
    with CSV.open() as f:
        rows = list(csv.DictReader(f))
    beta = [float(r["beta"]) for r in rows]
    mfe = [float(r["mfe_kcal_mol_mean"]) for r in rows]
    dist = [float(r["structure_distance_mean"]) for r in rows]
    inst = [float(r["pred_instability_mean"]) for r in rows]

    fig, ax1 = plt.subplots(figsize=(10.5, 6.4), constrained_layout=True)
    ax2 = ax1.twinx()
    ax2.spines["top"].set_visible(False)

    # right axis: fidelity + instability (both live in [0, ~1.2])
    ln3, = ax2.plot(beta, dist, color=C_DIST, linewidth=2.4, marker="^",
                    markersize=6.5, markerfacecolor="white", markeredgewidth=2,
                    markeredgecolor=C_DIST,
                    label="structure distance to target (right)")
    ln2, = ax2.plot(beta, inst, color=C_INST, linewidth=2.0, marker="s",
                    markersize=5.5, markerfacecolor="white", markeredgewidth=1.8,
                    markeredgecolor=C_INST, linestyle="--",
                    label="predicted instability (right)")
    # left axis: MFE (more negative = more stable)
    ln1, = ax1.plot(beta, mfe, color=C_MFE, linewidth=2.4, marker="o",
                    markersize=6, markerfacecolor="white", markeredgewidth=2,
                    markeredgecolor=C_MFE, label="MFE, kcal/mol (left)")

    ax1.set_xlabel("β  (stability weight in the coupled GA objective)")
    ax1.set_ylabel("MFE (kcal/mol)  — lower is more stable", color=C_MFE)
    ax1.tick_params(axis="y", labelcolor=C_MFE)
    ax2.set_ylabel("structure distance  ·  predicted instability", color=G700)
    ax1.set_xticks(beta)
    ax1.set_title("The β-Pareto frontier: stability is bought with fidelity",
                  loc="left")
    ax1.yaxis.grid(True, alpha=0.08, color=G300)
    ax1.set_axisbelow(True)
    ax1.set_ylim(-58, -28)
    ax2.set_ylim(0, 1.25)

    # annotations placed inside the plot body
    ax1.annotate("β = 0.1 sweet spot:\n63% of the MFE gain, fidelity improves",
                 xy=(0.1, -40.12), xytext=(0.28, -50.5),
                 fontsize=9.5, color=G700,
                 arrowprops=dict(arrowstyle="->", color=G400, lw=1.0))
    ax2.annotate("fidelity erodes from β ≥ 1.0",
                 xy=(1.35, 0.155), xytext=(1.18, 0.30),
                 fontsize=9.5, color=C_DIST,
                 arrowprops=dict(arrowstyle="->", color=C_DIST, lw=1.0, alpha=0.7))

    lines = [ln1, ln3, ln2]
    ax1.legend(lines, [l.get_label() for l in lines],
               loc="upper left", bbox_to_anchor=(1.09, 1.0))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=200, facecolor="white")
    plt.close(fig)
    print(f"OK {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
