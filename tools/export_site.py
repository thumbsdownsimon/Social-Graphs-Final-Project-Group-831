#!/usr/bin/env python3
"""Step 8 of the pipeline: gather everything the site draws into data/site.json.

    python tools/export_site.py

The page computes nothing: every number on it comes from this file, and every number
in this file comes from data/results/ or data/*.parquet.
"""
import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_network import DATA, RESULTS, ROOT, SEED, clean_edges, load_windows

OUT = DATA / "site.json"
BACKBONE_ALPHA = 0.05
LAST_WINDOW_DRAWN = "2022 M+S+V"
TOP_NEIGHBOURS = 12

sys.stdout.reconfigure(encoding="utf-8")


def read(name):
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))


def disparity_backbone(graph, alpha=BACKBONE_ALPHA):
    """Serrano et al.'s disparity filter: keep an edge if either end finds it unusually heavy."""
    keep = nx.Graph()
    keep.add_nodes_from(graph)
    for node in graph:
        degree = graph.degree(node)
        if degree < 2:
            continue
        strength = graph.degree(node, weight="weight")
        for other, data in graph[node].items():
            p = (1 - data["weight"] / strength) ** (degree - 1)
            if p < alpha:
                keep.add_edge(node, other, weight=data["weight"])
    return keep


def window_network(part, window, names, by_window):
    """Members, their top opponents, and a backbone layout for one government's time in office."""
    party = {}
    for person, value in zip(part["challenger_person"], part["challenger_party"]):
        party[person] = value
    for person, value in zip(part["floor_person"], part["floor_party"]):
        party[person] = value
    pairs = part[part["challenger_person"] != part["floor_person"]]
    undirected = nx.Graph()
    for (a, b), weight in pairs.groupby(["challenger_person", "floor_person"]).size().items():
        old = undirected.get_edge_data(a, b, {"weight": 0})["weight"]
        undirected.add_edge(int(a), int(b), weight=old + int(weight))
    backbone = disparity_backbone(undirected)
    # Only the largest component is drawn: small fragments would push it into a corner of the
    # layout. Everyone else stays reachable through the member search.
    largest = max(nx.connected_components(backbone), key=len)
    giant = backbone.subgraph(largest)
    layout = nx.spring_layout(giant, seed=SEED, weight=None, k=1.6 / np.sqrt(len(giant)), iterations=300)
    communities = by_window[window]["communities"]["partition"]
    made = pairs.groupby("challenger_person").size()
    received = pairs.groupby("floor_person").size()
    challenged = pairs.groupby(["challenger_person", "floor_person"]).size()
    government = window.split(" ", 1)[1].split("+")
    nodes = []
    for person in sorted(party):
        person = int(person)
        top = [(int(b), int(n)) for b, n in (challenged.loc[person].sort_values(ascending=False).head(TOP_NEIGHBOURS).items()
                                             if person in made.index else [])]
        by = [(int(a), int(n)) for a, n in (challenged.xs(person, level="floor_person").sort_values(ascending=False).head(TOP_NEIGHBOURS).items()
                                            if person in received.index else [])]
        position = layout.get(person)
        nodes.append({"id": person, "name": names.get(person, str(person)), "party": party[person],
                      "side": "government" if party[person] in government else "opposition",
                      "community": communities.get(str(person)), "made": int(made.get(person, 0)),
                      "received": int(received.get(person, 0)), "challenged": top, "challenged_by": by,
                      "x": round(float(position[0]), 3) if position is not None else None,
                      "y": round(float(position[1]), 3) if position is not None else None})
    edges = [[int(a), int(b), int(d["weight"])] for a, b, d in backbone.edges(data=True)]
    return {"nodes": nodes, "edges": edges, "edges_all": undirected.number_of_edges(),
            "backbone_alpha": BACKBONE_ALPHA, "backbone_edges": len(edges), "members_drawn": len(layout)}


def role_rates_per_quarter(rows):
    """One point per party and quarter: a quarter spanning a formation appears once per government."""
    table = pd.DataFrame(rows)
    table = table[table["party"].isin(["S", "V"])]
    table["role_words"] = table["rate"] * table["words"]
    merged = table.groupby(["party", "quarter"]).agg(role_words=("role_words", "sum"), words=("words", "sum"),
                                                     government=("government", "last")).reset_index()
    merged["rate"] = (merged["role_words"] / merged["words"]).round(2)
    return merged[["party", "quarter", "rate", "government", "words"]].to_dict("records")


def effect_rows(layer):
    return [{k: r[k] for k in ("transition", "pair", "relation", "change", "placebo_units")} for r in layer["rows"]]


def layer_summary(layer):
    return {k: layer[k] for k in ("pairs_tested", "right_direction", "mean_effect_in_placebo_sd", "median_effect", "p_one_sided",
                                  "by_formation", "formations_right_on_average", "unchanged_pairs")}


MEMBER_FIELDS = ["person", "name", "party", "parties", "years", "made", "received", "made_per_year", "received_per_year",
                 "cross_bloc_share", "at_government_share", "tone", "negative_share", "tone_at_other_bloc", "tone_received",
                 "rebel_rate", "minister_share", "archetypes", "primary", "cluster"]


def archetype_block():
    """The archetype analysis (tools/analyze_archetypes.py), trimmed to what the page draws."""
    if not (RESULTS / "archetypes.json").exists():
        return None
    a = read("archetypes")
    rnd = lambda v: round(v, 3) if isinstance(v, float) else v
    keep = {k: a[k] for k in ("status", "blocs", "settings", "features", "archetypes", "thresholds", "counts", "tone_overall",
                              "archetype_profiles", "overlaps", "tone_by_target", "made_received_spearman", "words",
                              "by_party", "over_time", "clusters")}
    keep["members"] = [{k: rnd(m.get(k)) for k in MEMBER_FIELDS} for m in a["members"]]
    return keep


def main():
    windows = load_windows()
    network, language, role, votes, summary, validation = (read(n) for n in ("network", "language", "role", "votes", "summary", "validation"))
    labels = read("label_checks") if (RESULTS / "label_checks.json").exists() else {}
    edges = clean_edges(windows)
    names = pd.read_parquet(DATA / "members.parquet").set_index("person")["name"].to_dict()
    numbers = json.loads((ROOT / "docs" / "dataset_numbers.json").read_text(encoding="utf-8"))
    log = json.loads((ROOT / "docs" / "collection_log.json").read_text(encoding="utf-8"))
    speeches = pd.read_parquet(ROOT / "data-raw" / "derived" / "speeches.parquet", columns=["session", "words", "is_chair", "is_person", "status"])

    drawn = [w for w in windows if w["name"] <= LAST_WINDOW_DRAWN and w["name"] in network["by_window"]]
    by_window = network["by_window"]
    mixing = {}
    for w in drawn:
        row = by_window[w["name"]]
        keep = [i for i, p in enumerate(row["parties"]) if sum(row["observed"][i]) + sum(r[i] for r in row["observed"]) >= 100]
        mixing[w["name"]] = {
            "parties": [row["parties"][i] for i in keep], "government": w["government"],
            "observed": [[row["observed"][i][j] for j in keep] for i in keep],
            "expected": [[row["expected_same_debate"][i][j] for j in keep] for i in keep],
            "z": [[row["z_same_debate"][i][j] for j in keep] for i in keep],
        }
    site = {
        "windows": windows,
        "drawn_windows": [w["name"] for w in drawn],
        "layers": {k: {"summary": layer_summary(v), "rows": effect_rows(v)} for k, v in summary["layers"].items()},
        "variants": {k: layer_summary(v) for k, v in summary["challenge_variants"].items()},
        "timelines": network["timelines"],
        "transitionsSV": next(r for r in network["transitions_all"] if r["pair"] == "S-V" and r["transition"] == "2022-12-15"),
        "mixing": mixing,
        "per_window": {w["name"]: {"summary": by_window[w["name"]]["summary"],
                                   "party_assortativity": by_window[w["name"]]["party_assortativity"],
                                   "side_assortativity": by_window[w["name"]]["side_assortativity"],
                                   "communities": {k: v for k, v in by_window[w["name"]]["communities"].items() if k != "partition"},
                                   "committee_test": by_window[w["name"]]["committee_test"],
                                   "community_topics": by_window[w["name"]]["community_topics"]} for w in drawn},
        "networks": {w["name"]: window_network(edges[edges["window"] == w["name"]], w["name"], names, by_window) for w in drawn},
        "role_rates": role_rates_per_quarter(role["role_word_rates"]),
        "within_party": role["within_party"],
        "role_classifier": role["role_classifier"],
        "party_accuracy_S_V": [r for r in language["accuracy"] if r["pair"] == "S-V"],
        "same_debate_S_V": [r for r in language["same_debate"] if r["pair"] == "S-V"],
        "distinctive_words_S_V": language["distinctive_words_S_vs_V"],
        "language_corpus": language["corpus"], "truncation": language["truncation"], "encoder": language["encoder"],
        "votes": votes, "validation": validation, "labels": labels, "collection": log,
        "dataset": {
            "turns": len(speeches), "words": int(speeches["words"].sum()),
            "member_turns": int((speeches["is_person"] & ~speeches["is_chair"]).sum()),
            "chair_turns": int(speeches["is_chair"].sum()),
            "status_by_session": speeches.groupby(["session", "status"]).size().unstack(fill_value=0).to_dict("index"),
            "challenges": numbers["challenges"], "usable_edges": len(edges),
            "name_methods": numbers["name_methods_share_of_turns"], "party_positions": {k: v for k, v in numbers["party_positions"].items() if k != "party_codes"},
            "party_source_ministers": numbers["party_source_share_of_minister_turns"],
            "party_agreement": {k: v for k, v in numbers["party_xml_vs_membership"].items() if k != "top_disagreements"},
            "files_repaired": numbers.get("files_repaired", []),
        },
    }
    site["archetypes"] = archetype_block()
    OUT.write_text(json.dumps(site, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    print("wrote", OUT.name, round(OUT.stat().st_size / 1e6, 2), "MB")


if __name__ == "__main__":
    main()
