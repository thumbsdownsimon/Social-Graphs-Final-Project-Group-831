"""fig_topic_divide.png: (left) delta = Q_bloc - Q_gov per topic x window; (right) z of the
between-topic spread S against the topic-shuffle null, main run and robustness runs.
fig_vote_pairs.png: party-pair vote agreement by topic (S-DF, S-V), 2016-2026 windows."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "topic_blocs"
A = pd.read_csv(DATA / "test_a_main.csv")
A["delta"] = A.Q_bloc - A.Q_gov
order_w = list(dict.fromkeys(A.window))
order_t = ["economy", "welfare_health", "labour", "education_culture", "environment_energy",
           "infrastructure_local", "justice", "immigration", "foreign_defence"]
M = A.pivot(index="topic", columns="window", values="delta").reindex(index=order_t, columns=order_w)

fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 5), gridspec_kw={"width_ratios": [1.5, 1]})
lim = np.nanmax(np.abs(M.values))
im = ax.imshow(M.values, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
for i in range(M.shape[0]):
    for j in range(M.shape[1]):
        v = M.values[i, j]
        if not np.isnan(v):
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=8)
ax.set_xticks(range(len(order_w)), order_w, rotation=30, ha="right")
ax.set_yticks(range(len(order_t)), [t.replace("_", " ") for t in order_t])
ax.set_title("Q(red/blue) - Q(gov/opp) per topic\nblue: red/blue line fits challenges better; red: gov/opp fits better", fontsize=10)
fig.colorbar(im, ax=ax, shrink=0.8)

runs = {"main": "main", "permute whole cases": "saglevel", "within Sag type": "strat",
        "relative delta": "rel", "no ministers": "nomin", "no North Atlantic": "nona", ">= 500 edges": "min500"}
marks = ["o", "s", "^", "D", "v", "P", "X"]
for k, ((label, tag), mk) in enumerate(zip(runs.items(), marks)):
    B = pd.read_csv(DATA / f"test_b_{tag}.csv").set_index("window").reindex(order_w)
    y = np.arange(len(order_w)) + (k - 3) * 0.09
    bx.scatter(B.z, y, marker=mk, s=28 if tag == "main" else 16, label=label,
               color="black" if tag == "main" else None, zorder=3 if tag == "main" else 2)
bx.axvline(2, color="grey", ls="--", lw=1)
bx.axvline(0, color="grey", lw=0.5)
bx.set_yticks(range(len(order_w)), order_w)
bx.invert_yaxis()
bx.set_xlabel("z of between-topic spread S vs topic-shuffle null")
bx.set_title("Does the best divide differ between topics?", fontsize=10)
bx.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3)
fig.tight_layout()
fig.savefig(DATA / "figures" / "fig_topic_divide.png", dpi=150)

P = pd.read_csv(DATA / "vote_pairs.csv")
P = P[P.window.isin(["2016 KF+LA+V", "2019 S", "2022 M+S+V"])]
fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
for a, (w, d) in zip(axes, P.groupby("window", sort=False)):
    d = d.set_index("topic").reindex([t for t in order_t if t in set(d.topic)])
    x = np.arange(len(d))
    a.bar(x - 0.2, d["S-DF"], 0.4, label="S-DF")
    a.bar(x + 0.2, d["S-V"], 0.4, label="S-V")
    a.set_xticks(x, [t.replace("_", " ") for t in d.index], rotation=45, ha="right", fontsize=8)
    a.set_title(w, fontsize=10)
axes[0].set_ylabel("share of votes on the same side")
axes[0].legend(fontsize=8)
fig.tight_layout()
fig.savefig(DATA / "figures" / "fig_vote_pairs.png", dpi=150)
