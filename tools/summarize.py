#!/usr/bin/env python3
"""Step 6 of the pipeline: put votes, challenges and language on one scale and test them.

    python tools/summarize.py

Writes data/results/summary.json. For each layer and each formation, a pair's change is
compared with pairs whose relation did not change at that same formation:

  effect     (change - placebo median) / placebo spread, signed so that positive means the
             expected direction: closer after joining a government, further after splitting.
  test       shuffle which pairs are "joined" or "split" within each formation. Pairs within
             one formation are not independent, so we shuffle within formations and report
             a per-formation count too.

Layers measure different things in different units, so the comparison is of how far each
stands out from its own placebo, not of raw size. 2026 is left out: its window is too thin.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_network import RESULTS, SEED, load_windows, status_change

LAST_FORMATION = "2022-12-15"
N_SHUFFLES = 20000
EXPECTED_SIGN = {"votes": {"joined": 1, "both_entered": 1, "split": -1},
                 "challenges": {"joined": -1, "both_entered": -1, "split": 1},
                 "same_debate_similarity": {"joined": 1, "both_entered": 1, "split": -1},
                 "party_classifier": {"joined": -1, "both_entered": -1, "split": 1}}

sys.stdout.reconfigure(encoding="utf-8")


def vote_changes(network, windows):
    rows = []
    agreement = network["vote_agreement"]
    for before, after in zip(windows, windows[1:]):
        if before["name"] not in agreement or after["name"] not in agreement:
            continue
        p0, p1 = agreement[before["name"]]["pairs"], agreement[after["name"]]["pairs"]
        for pair in sorted(set(p0) & set(p1)):
            a, b = pair.split("-")
            rows.append({"transition": after["from"], "pair": pair, "before": p0[pair]["contested"], "after": p1[pair]["contested"],
                         "n_before": p0[pair]["n_contested"], "n_after": p1[pair]["n_contested"],
                         "change": None if p0[pair]["contested"] is None or p1[pair]["contested"] is None
                         else round(p1[pair]["contested"] - p0[pair]["contested"], 4),
                         "relation": status_change(a, b, before["government"], after["government"])})
    return pd.DataFrame(rows).dropna(subset=["change"])


def score_layer(table, layer, seed=SEED):
    """Signed effects per pair, and a within-formation permutation test of their mean."""
    table = table[table["transition"] <= LAST_FORMATION].copy()
    signs = EXPECTED_SIGN[layer]
    changed = table["relation"].isin(signs)
    rows = []
    for transition, part in table.groupby("transition"):
        placebo = part.loc[part["relation"] == "unchanged", "change"]
        if len(placebo) < 3:
            continue
        centre, spread = placebo.median(), max(float(placebo.std()), 1e-9)
        for row in part.itertuples():
            sign = signs.get(row.relation, 0)
            rows.append({"transition": transition, "pair": row.pair, "relation": row.relation, "change": float(row.change),
                         "before": getattr(row, "before", None), "after": getattr(row, "after", None),
                         "effect": round(float(sign * (row.change - centre) / spread), 2) if sign else None,
                         "placebo_units": round(float((row.change - centre) / spread), 2)})
    scored = pd.DataFrame(rows)
    focal = scored[scored["relation"].isin(signs)]
    observed = float(focal["effect"].mean())

    rng = np.random.default_rng(seed)
    groups = []
    for _, part in scored.groupby("transition"):
        groups.append((part["placebo_units"].to_numpy(), part["relation"].map(lambda r: signs.get(r, 0)).to_numpy()))
    null = np.zeros(N_SHUFFLES)
    count = sum(int((sign != 0).sum()) for _, sign in groups)
    for k in range(N_SHUFFLES):
        total = 0.0
        for values, sign in groups:
            total += float((values * rng.permutation(sign)).sum())
        null[k] = total / count
    p = (np.sum(null >= observed) + 1) / (N_SHUFFLES + 1)

    by_formation = {}
    for transition, part in focal.groupby("transition"):
        by_formation[transition] = {"pairs": len(part), "right_direction": int((part["effect"] > 0).sum()),
                                    "mean_effect": round(float(part["effect"].mean()), 2)}
    return {"layer": layer, "pairs_tested": len(focal), "right_direction": int((focal["effect"] > 0).sum()),
            "mean_effect_in_placebo_sd": round(observed, 2), "median_effect": round(float(focal["effect"].median()), 2),
            "p_one_sided": float(p), "by_formation": by_formation,
            "formations_right_on_average": sum(v["mean_effect"] > 0 for v in by_formation.values()),
            "unchanged_pairs": int((scored["relation"] == "unchanged").sum()),
            "rows": scored.to_dict("records")}


def main():
    network = json.loads((RESULTS / "network.json").read_text(encoding="utf-8"))
    language = json.loads((RESULTS / "language.json").read_text(encoding="utf-8"))
    windows = load_windows()

    challenges = pd.DataFrame(network["transitions_all"]).rename(columns={"log_ratio_change": "change"})
    backbench = pd.DataFrame(network["transitions_backbench"]).rename(columns={"log_ratio_change": "change"})
    panel = pd.DataFrame([r for p in network["transitions_panel"].values() for r in p["rows"]]).rename(
        columns={"log_ratio_change": "change"})
    layers = {
        "votes": score_layer(vote_changes(network, windows), "votes"),
        "challenges": score_layer(challenges, "challenges"),
        "same_debate_similarity": score_layer(pd.DataFrame(language["same_debate_changes"]), "same_debate_similarity"),
        "party_classifier": score_layer(pd.DataFrame(language["accuracy_changes"]), "party_classifier"),
    }
    variants = {"challenges_backbench_only": score_layer(backbench, "challenges"),
                "challenges_same_members_panel": score_layer(panel, "challenges")}
    summary = {"layers": layers, "challenge_variants": variants}
    (RESULTS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for name, row in {**layers, **variants}.items():
        print(name, {k: v for k, v in row.items() if k not in ("rows", "layer")}, flush=True)
    focal = [r for r in layers["challenges"]["rows"] if r["pair"] == "S-V" and r["transition"] == LAST_FORMATION]
    print(focal, flush=True)
    for name in ("votes", "same_debate_similarity", "party_classifier"):
        print(name, [r for r in layers[name]["rows"] if r["pair"] == "S-V" and r["transition"] == LAST_FORMATION], flush=True)


if __name__ == "__main__":
    main()
