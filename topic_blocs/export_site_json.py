#!/usr/bin/env python3
"""Collect the topic-bloc results into data/results/topic_blocs.json for the site (draft Part 4b).

    python -m topic_blocs.export_site_json

Reads only the outputs of topic_blocs.py in data/topic_blocs/ (test_a_*.csv, test_b_*.csv,
debate_topics.parquet) and data/challenges.parquet for the match rate. Computes nothing new
beyond counts and the sign of delta.
"""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data" / "topic_blocs"
OUT = ROOT / "data" / "results" / "topic_blocs.json"

TOPICS = {
    "economy": "Economy and tax",
    "welfare_health": "Welfare and health",
    "labour": "Labour market",
    "education_culture": "Education and culture",
    "environment_energy": "Environment and energy",
    "infrastructure_local": "Transport and local government",
    "justice": "Justice",
    "immigration": "Immigration",
    "foreign_defence": "Foreign affairs and defence",
}
VARIANTS = {
    "main": "Main test: whole debates shuffled",
    "saglevel": "Whole cases shuffled (all readings together)",
    "strat": "Shuffled within case type",
    "nona": "North Atlantic and unaffiliated left out",
    "nomin": "Challenges with a minister left out",
    "min500": "At least 500 challenges per topic",
    "rel": "Relative measure: which line, not how strong",
}


def main():
    a = pd.read_csv(DATA / "test_a_main.csv")
    a["delta"] = a.Q_bloc - a.Q_gov
    windows = list(dict.fromkeys(a.window))

    # The winning line in a window is the sign most topics share; a flip is a topic against it.
    major = a.groupby("window").delta.apply(lambda d: "bloc" if (d < 0).sum() >= (d > 0).sum() else "gov")
    cells = []
    for r in a.itertuples():
        winner = "bloc" if r.delta < 0 else "gov"
        cells.append({
            "window": r.window, "topic": r.topic, "edges": int(r.edges), "debates": int(r.debates),
            "Q_gov": round(r.Q_gov, 4), "Q_bloc": round(r.Q_bloc, 4),
            "z_gov": round(r.z_gov, 2), "z_bloc": round(r.z_bloc, 2),
            "delta": round(r.delta, 4), "winner": winner, "flip": winner != major[r.window],
        })

    tests = {}
    for tag, label in VARIANTS.items():
        b = pd.read_csv(DATA / f"test_b_{tag}.csv")
        tests[tag] = {"label": label, "rows": [
            {"window": r.window, "n_topics": int(r.n_topics), "edges": int(r.edges),
             "S_obs": round(r.S_obs, 4), "S_null_mean": round(r.S_null_mean, 4), "S_null_sd": round(r.S_null_sd, 4),
             "z": round(r.z, 2), "p": round(r.p, 4)} for r in b.itertuples()]}

    # Match rate: debates with challenges that got a case, and challenges that kept a policy topic.
    ch = pd.read_parquet(ROOT / "data" / "challenges.parquet")
    ch["debate"] = ch.session.astype(str) + "-" + ch.meeting.astype(str) + "-" + ch.item.astype(str)
    dt = pd.read_parquet(DATA / "debate_topics.parquet")
    topic_of = dict(zip(dt.debate, dt.topic))
    ch["topic"] = ch.debate.map(topic_of)
    main_rows = tests["main"]["rows"]
    out = {
        "source": "topic_blocs/ (topic_blocs.py); draft for the group, not part of the main analysis",
        "windows": windows,
        "topics": [{"key": k, "label": v} for k, v in TOPICS.items()],
        "cells": cells,
        "tests": tests,
        "summary": {
            "debates": int(ch.debate.nunique()),
            "debates_matched": int(ch.debate[ch.topic.notna()].nunique()),
            "edge_share_matched": round(float(ch.topic.notna().mean()), 4),
            "edge_share_ambiguous": round(float((ch.topic == "ambiguous").mean()), 4),
            "edge_share_policy": round(float(ch.topic.isin(TOPICS).mean()), 4),
            "cells": len(cells),
            "flips": int(sum(c["flip"] for c in cells)),
            "windows_tested": len(main_rows),
            "windows_pass": int(sum(r["z"] >= 2 for r in main_rows)),
            "min_edges": 300,
            "debate_shuffles": 200,
            "topic_shuffles": 1000,
        },
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(cells)} cells, {out['summary']}")


if __name__ == "__main__":
    main()
