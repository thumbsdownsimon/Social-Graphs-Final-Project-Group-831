#!/usr/bin/env python3
"""Step 4 of the pipeline: votes and floor challenges across governments.

    python tools/analyze_network.py

Writes data/results/network.json. Every network measurement here is compared with a
null; see AI_METHODS.md for what each one captures and misses.

A "window" is the time between two government formations (data/governments.json).
"""
import json
import sys
from itertools import combinations
from pathlib import Path

import community as community_louvain
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import normalized_mutual_info_score

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = DATA / "results"
SEED = 831
N_SHUFFLES = 1000
N_LOUVAIN_RUNS = 20
SMOOTH = 0.5  # added to counts so a pair with no edges still has a defined log ratio
MIN_EXPECTED = 5  # below this a party pair's rate is too noisy to read
NOT_A_PARTY = {"UFG", "Pause", "MødeSlut"}

sys.stdout.reconfigure(encoding="utf-8")


def load_windows():
    governments = json.loads((DATA / "governments.json").read_text(encoding="utf-8"))
    windows = []
    for i, row in enumerate(governments):
        end = governments[i + 1]["from"] if i + 1 < len(governments) else "9999-12-31"
        windows.append({"name": f"{row['from'][:4]} {'+'.join(row['parties'])}", "from": row["from"],
                        "to": end, "government": row["parties"]})
    return windows


def window_of(dates, windows):
    labels = pd.Series(index=dates.index, dtype=object)
    for w in windows:
        labels[(dates >= w["from"]) & (dates < w["to"])] = w["name"]
    return labels


def vote_agreement(windows):
    """Share of votes on which two parties took the same side, per window.

    Captures formal alignment. Misses everything negotiated before the vote, and is
    mechanically high inside a government: read it as the setup, not as a finding.
    Comparison: the same pair's rate on contested votes only (at least one party against).
    """
    positions = pd.read_parquet(DATA / "party_positions.parquet")
    positions = positions[~positions["party"].isin(NOT_A_PARTY)]
    positions["window"] = window_of(positions["date"], windows)
    contested = positions.groupby("vote")["side"].transform(lambda s: (s == "for").any() and (s == "imod").any())
    out = {}
    for w in windows:
        part = positions[positions["window"] == w["name"]]
        if part.empty:
            continue
        table = part.pivot_table(index="vote", columns="party", values="side", aggfunc="first")
        is_contested = contested[part.index].groupby(part["vote"]).first()
        pairs = {}
        for a, b in combinations(sorted(table.columns), 2):
            both = table[[a, b]].dropna()
            if len(both) < 10:
                continue
            sub = both[is_contested.reindex(both.index).fillna(False)]
            pairs[f"{a}-{b}"] = {"all": round(float((both[a] == both[b]).mean()), 3), "n": len(both),
                                 "contested": round(float((sub[a] == sub[b]).mean()), 3) if len(sub) else None,
                                 "n_contested": len(sub)}
        out[w["name"]] = {"votes": int(part["vote"].nunique()), "pairs": pairs}
    return out


def clean_edges(windows, backbench_only=False):
    edges = pd.read_parquet(DATA / "challenges.parquet")
    edges["window"] = window_of(edges["date"], windows)
    usable = (edges["floor_person"].notna() & edges["challenger_person"].notna()
              & edges["floor_party"].notna() & edges["challenger_party"].notna()
              & edges["window"].notna() & ~edges["floor_party"].isin(NOT_A_PARTY)
              & ~edges["challenger_party"].isin(NOT_A_PARTY))
    if backbench_only:
        usable &= ~edges["floor_is_minister"] & ~edges["challenger_is_minister"]
    edges = edges[usable].copy()
    edges["floor_person"] = edges["floor_person"].astype(int)
    edges["challenger_person"] = edges["challenger_person"].astype(int)
    return edges


def party_matrix(challenger_party, floor_party, parties):
    index = {p: i for i, p in enumerate(parties)}
    matrix = np.zeros((len(parties), len(parties)))
    np.add.at(matrix, (challenger_party.map(index).to_numpy(), floor_party.map(index).to_numpy()), 1)
    return matrix


def mixing_against_null(edges, parties, group_by=None, n=N_SHUFFLES, seed=SEED):
    """Observed party-to-party challenges against shuffling who is on the floor.

    Shuffling the floor side keeps every member's number of challenges made and received
    (a directed configuration model). With group_by, floors only shuffle within one debate,
    so the null also keeps who was speaking in each debate. Self-loops the shuffle creates
    are dropped from the count.
    """
    rng = np.random.default_rng(seed)
    index = {p: i for i, p in enumerate(parties)}
    size = len(parties)
    a = edges["challenger_party"].map(index).to_numpy()
    b = edges["floor_party"].map(index).to_numpy()
    who_a = edges["challenger_person"].to_numpy()
    who_b = edges["floor_person"].to_numpy()
    observed = np.zeros((size, size))
    np.add.at(observed, (a, b), 1)
    groups = (edges[group_by].astype(str).agg("|".join, axis=1).to_numpy() if group_by
              else np.zeros(len(edges), dtype=int))
    slots = [np.flatnonzero(groups == g) for g in pd.unique(groups)]
    draws = np.zeros((n, size, size))
    for k in range(n):
        order = np.arange(len(edges))
        for slot in slots:
            order[slot] = rng.permutation(slot)
        keep = who_a != who_b[order]
        np.add.at(draws[k], (a[keep], b[order][keep]), 1)
    mean, sd = draws.mean(axis=0), draws.std(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(sd > 0, (observed - mean) / sd, 0.0)
    return observed, mean, z, draws


def assortativity_from_matrix(matrix):
    """Newman's attribute assortativity from a mixing matrix of edge counts."""
    e = matrix / matrix.sum()
    expected = float(e.sum(axis=0) @ e.sum(axis=1))
    return (float(np.trace(e)) - expected) / (1 - expected) if expected < 1 else 0.0


def assortativity_test(edges, label_of, n=N_SHUFFLES, seed=SEED):
    """Assortativity of a member label against shuffling that label across members."""
    rng = np.random.default_rng(seed)
    people = np.array(sorted(label_of))
    labels = np.array([label_of[p] for p in people])
    values = sorted(set(labels))
    index = {v: i for i, v in enumerate(values)}
    position = {p: i for i, p in enumerate(people)}
    a = edges["challenger_person"].map(position).to_numpy()
    b = edges["floor_person"].map(position).to_numpy()
    coded = np.array([index[v] for v in labels])

    def score(code):
        matrix = np.zeros((len(values), len(values)))
        np.add.at(matrix, (code[a], code[b]), 1)
        return assortativity_from_matrix(matrix)

    observed = score(coded)
    null = np.array([score(rng.permutation(coded)) for _ in range(n)])
    p = (np.sum(np.abs(null - null.mean()) >= abs(observed - null.mean())) + 1) / (n + 1)
    return {"observed": round(observed, 4), "null_mean": round(float(null.mean()), 4),
            "null_sd": round(float(null.std()), 4), "p": round(float(p), 4)}


def network_summary(edges):
    graph = nx.DiGraph()
    weights = edges.groupby(["challenger_person", "floor_person"]).size()
    graph.add_weighted_edges_from((a, b, int(w)) for (a, b), w in weights.items())
    out_degree = np.array([d for _, d in graph.out_degree(weight="weight")])
    in_degree = np.array([d for _, d in graph.in_degree(weight="weight")])
    return {"members": graph.number_of_nodes(), "challenges": int(len(edges)),
            "distinct_pairs": graph.number_of_edges(), "density": round(nx.density(graph), 4),
            "giant_weak_component": max(len(c) for c in nx.weakly_connected_components(graph)),
            "made_median": float(np.median(out_degree)), "made_max": int(out_degree.max()),
            "received_median": float(np.median(in_degree)), "received_max": int(in_degree.max())}


def communities(edges, party_of, seed=SEED):
    """Louvain on who challenges whom, against a rewired null and against party.

    Captures clusters of members who keep meeting on the floor. Because challenges rarely
    stay within a party, we do not expect this to recover parties. The check is modularity
    against degree-preserving rewiring, NMI between seeds, and NMI with party.
    """
    weights = edges.groupby(["challenger_person", "floor_person"]).size().reset_index(name="w")
    graph = nx.Graph()
    for row in weights.itertuples():
        if row.challenger_person == row.floor_person:
            continue
        old = graph.get_edge_data(row.challenger_person, row.floor_person, {"weight": 0})["weight"]
        graph.add_edge(row.challenger_person, row.floor_person, weight=old + row.w)
    nodes = sorted(graph)
    runs = [community_louvain.best_partition(graph, random_state=seed + i) for i in range(N_LOUVAIN_RUNS)]
    scores = [community_louvain.modularity(r, graph) for r in runs]
    vectors = [[r[n] for n in nodes] for r in runs]
    stability = [normalized_mutual_info_score(vectors[0], v) for v in vectors[1:]]
    best = runs[int(np.argmax(scores))]
    labels = [party_of[n] for n in nodes]

    rng = np.random.default_rng(seed)
    null_scores = []
    floors = edges["floor_person"].to_numpy()
    challengers = edges["challenger_person"].to_numpy()
    for k in range(50):
        shuffled = rng.permutation(floors)
        keep = challengers != shuffled
        null_graph = nx.Graph()
        for a, b in zip(challengers[keep], shuffled[keep]):
            old = null_graph.get_edge_data(a, b, {"weight": 0})["weight"]
            null_graph.add_edge(a, b, weight=old + 1)
        partition = community_louvain.best_partition(null_graph, random_state=seed + k)
        null_scores.append(community_louvain.modularity(partition, null_graph))
    return {"partition": {int(n): int(best[n]) for n in nodes}, "communities": len(set(best.values())),
            "modularity": round(max(scores), 4), "null_modularity_mean": round(float(np.mean(null_scores)), 4),
            "null_modularity_sd": round(float(np.std(null_scores)), 4),
            "seed_stability_nmi_mean": round(float(np.mean(stability)), 3),
            "nmi_with_party": round(float(normalized_mutual_info_score(labels, [best[n] for n in nodes])), 3)}


def pair_rates(edges, parties, group_by=None):
    """{(a, b): (observed, expected)} for unordered party pairs, both directions added."""
    observed, expected, _, _ = mixing_against_null(edges, parties, group_by=group_by, n=200)
    rates = {}
    for i, j in combinations(range(len(parties)), 2):
        rates[(parties[i], parties[j])] = (observed[i, j] + observed[j, i], expected[i, j] + expected[j, i])
    return rates


def status_change(a, b, before, after):
    """How a party pair's relation changed between two governments."""
    was = (a in before, b in before)
    now = (a in after, b in after)
    together_then, together_now = all(was), all(now)
    if not together_then and together_now:
        return "joined" if any(was) else "both_entered"
    if together_then and not together_now:
        return "split"
    if was == now:
        return "unchanged"
    return "other_change"


def transitions(edges, windows, label):
    """Change in each party pair's challenge rate (against its null) across each formation.

    The placebo is the pairs whose relation did not change at that same formation: if the
    chamber's overall style shifted, they shift too. Rate is observed/expected, on a log scale.
    """
    rows = []
    for before, after in zip(windows, windows[1:]):
        e0 = edges[edges["window"] == before["name"]]
        e1 = edges[edges["window"] == after["name"]]
        if e0.empty or e1.empty:
            continue
        p0 = sorted(set(e0["challenger_party"]) | set(e0["floor_party"]))
        p1 = sorted(set(e1["challenger_party"]) | set(e1["floor_party"]))
        r0 = pair_rates(e0, p0, group_by=["session", "meeting", "item"])
        r1 = pair_rates(e1, p1, group_by=["session", "meeting", "item"])
        for pair in sorted(set(r0) & set(r1)):
            (o0, x0), (o1, x1) = r0[pair], r1[pair]
            if x0 < MIN_EXPECTED or x1 < MIN_EXPECTED:
                continue
            change = np.log((o1 + SMOOTH) / (x1 + SMOOTH)) - np.log((o0 + SMOOTH) / (x0 + SMOOTH))
            rows.append({
                "transition": after["from"], "pair": "-".join(pair),
                "relation": status_change(*pair, before["government"], after["government"]),
                "observed_before": int(o0), "expected_before": round(x0, 1),
                "observed_after": int(o1), "expected_after": round(x1, 1),
                "log_ratio_change": round(float(change), 3),
                "se": round(float(np.sqrt(1 / (o0 + SMOOTH) + 1 / (o1 + SMOOTH))), 3),
                "variant": label,
            })
    table = pd.DataFrame(rows)
    if table.empty:
        return []
    placebo = table[table["relation"] == "unchanged"].groupby("transition")["log_ratio_change"]
    table["placebo_median"] = table["transition"].map(placebo.median()).round(3)
    table["placebo_n"] = table["transition"].map(placebo.size())
    table["placebo_share_as_extreme"] = [
        share_as_extreme(change, placebo.get_group(t)) if t in placebo.groups else None
        for t, change in zip(table["transition"], table["log_ratio_change"])
    ]
    return table.to_dict("records")


def share_as_extreme(value, placebo):
    """Share of placebo changes at least this far from the placebo median."""
    centre = placebo.median()
    return round(float(((placebo - centre).abs() >= abs(value - centre)).mean()), 3)


def event_timeline(edges, party_a, party_b, date, quarters=10):
    """Quarter-by-quarter challenges between two parties around a formation, against the null.

    The null shuffles floors within each debate of that quarter, so it holds the chamber's
    level of activity and each debate's speakers fixed. Answers how fast a change happens.
    """
    event = pd.Timestamp(date)
    days = (pd.to_datetime(edges["date"]) - event).dt.days
    position = np.floor(days / 91.25).astype(int)
    rows = []
    for quarter in range(-quarters, quarters):
        part = edges[position == quarter]
        pair = {party_a, party_b}
        if len(part) < 20 or not pair <= (set(part["challenger_party"]) | set(part["floor_party"])):
            rows.append({"quarter": quarter, "challenges": int(len(part)), "observed": None, "expected": None})
            continue
        parties = sorted(set(part["challenger_party"]) | set(part["floor_party"]))
        rates = pair_rates(part, parties, group_by=["session", "meeting", "item"])
        observed, expected = rates[tuple(sorted(pair))]
        rows.append({"quarter": quarter, "challenges": int(len(part)), "observed": int(observed),
                     "expected": round(float(expected), 1)})
    return rows


def vote_timeline(party_a, party_b, date, quarters=10):
    """Quarter-by-quarter share of votes on which two parties took the same side."""
    positions = pd.read_parquet(DATA / "party_positions.parquet")
    positions = positions[positions["party"].isin([party_a, party_b])]
    table = positions.pivot_table(index=["vote", "date"], columns="party", values="side", aggfunc="first").dropna().reset_index()
    position = np.floor((pd.to_datetime(table["date"]) - pd.Timestamp(date)).dt.days / 91.25).astype(int)
    rows = []
    for quarter in range(-quarters, quarters):
        part = table[position == quarter]
        rows.append({"quarter": quarter, "votes": len(part),
                     "agreement": round(float((part[party_a] == part[party_b]).mean()), 3) if len(part) else None})
    return rows


def committee_test(edges, session_of_window, seed=SEED):
    """Do members who challenge each other sit on the same committee, more than the null says?"""
    rows = json.loads((ROOT / "data-raw" / "tables" / "committee_memberships.json").read_text(encoding="utf-8"))
    memberships = pd.DataFrame(rows)
    seats = memberships[memberships["session"].isin(session_of_window)].groupby("person")["committee"].agg(set).to_dict()
    empty = set()
    rng = np.random.default_rng(seed)
    a = edges["challenger_person"].to_numpy()
    b = edges["floor_person"].to_numpy()

    def share(floors):
        return float(np.mean([bool(seats.get(x, empty) & seats.get(y, empty)) for x, y in zip(a, floors) if x != y]))

    observed = share(b)
    null = [share(rng.permutation(b)) for _ in range(200)]
    return {"share_sharing_a_committee": round(observed, 3), "null_mean": round(float(np.mean(null)), 3),
            "null_sd": round(float(np.std(null)), 4), "members_with_committee_data": int(sum(p in seats for p in set(a) | set(b))),
            "z": round((observed - float(np.mean(null))) / float(np.std(null)), 1)}


def community_topics(edges, partition, titles, top=8):
    """The words that set each community's debates apart, to read what a community is about."""
    edges = edges.assign(community=edges["challenger_person"].map(partition))
    edges = edges[edges["community"].notna()].merge(titles, on=["session", "meeting", "item"], how="left")
    docs = edges.groupby("community")["item_title"].apply(lambda t: " ".join(t.dropna()))
    vectorizer = TfidfVectorizer(sublinear_tf=True, max_df=0.6, token_pattern=r"[a-zæøåA-ZÆØÅ]{4,}")
    matrix = vectorizer.fit_transform(docs)
    vocabulary = np.array(vectorizer.get_feature_names_out())
    sizes = pd.Series(partition).value_counts()
    return {str(int(c)): {"members": int(sizes.get(c, 0)),
                          "words": vocabulary[np.argsort(-matrix[i].toarray()[0])[:top]].tolist()}
            for i, c in enumerate(docs.index)}


def panel_edges(edges, before, after):
    """Edges between backbenchers who appear in both windows, so turnover cannot explain a change."""
    e0, e1 = edges[edges["window"] == before], edges[edges["window"] == after]
    seen0 = set(e0["challenger_person"]) | set(e0["floor_person"])
    seen1 = set(e1["challenger_person"]) | set(e1["floor_person"])
    both = seen0 & seen1
    keep = edges["challenger_person"].isin(both) & edges["floor_person"].isin(both)
    return edges[keep & edges["window"].isin([before, after])], len(both)


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    windows = load_windows()
    edges = clean_edges(windows)
    backbench = clean_edges(windows, backbench_only=True)
    print("usable edges", len(edges), "backbench", len(backbench), flush=True)
    results = {"windows": windows, "vote_agreement": vote_agreement(windows), "by_window": {}}

    for w in windows:
        part = edges[edges["window"] == w["name"]]
        if len(part) < 100:
            continue
        parties = sorted(set(part["challenger_party"]) | set(part["floor_party"]))
        observed, expected, z, _ = mixing_against_null(part, parties)
        observed_d, expected_d, z_d, _ = mixing_against_null(part, parties, group_by=["session", "meeting", "item"])
        party_of = {}
        for person, party in zip(part["challenger_person"], part["challenger_party"]):
            party_of[person] = party
        for person, party in zip(part["floor_person"], part["floor_party"]):
            party_of[person] = party
        side_of = {p: ("government" if party in w["government"] else "opposition") for p, party in party_of.items()}
        results["by_window"][w["name"]] = {
            "summary": network_summary(part), "parties": parties, "observed": observed.astype(int).tolist(),
            "expected_rewired": np.round(expected, 1).tolist(), "z_rewired": np.round(z, 2).tolist(),
            "expected_same_debate": np.round(expected_d, 1).tolist(), "z_same_debate": np.round(z_d, 2).tolist(),
            "party_assortativity": assortativity_test(part, party_of),
            "side_assortativity": assortativity_test(part, side_of),
            "communities": communities(part, party_of),
        }
        row = results["by_window"][w["name"]]
        print(w["name"], row["summary"], "party r", row["party_assortativity"]["observed"],
              "side r", row["side_assortativity"]["observed"],
              "Q", row["communities"]["modularity"], "null", row["communities"]["null_modularity_mean"],
              "nmi", row["communities"]["nmi_with_party"], flush=True)

    titles = pd.read_parquet(ROOT / "data-raw" / "derived" / "speeches.parquet",
                             columns=["session", "meeting", "item", "item_title"]).drop_duplicates(["session", "meeting", "item"])
    for w in windows:
        part = edges[edges["window"] == w["name"]]
        if w["name"] in results["by_window"]:
            row = results["by_window"][w["name"]]
            row["committee_test"] = committee_test(part, set(part["session"]))
            row["community_topics"] = community_topics(part, row["communities"]["partition"], titles)
            print(w["name"], row["committee_test"], flush=True)

    results["timelines"] = {
        f"{a}-{b} {date}": {"challenges": event_timeline(edges, a, b, date), "votes": vote_timeline(a, b, date)}
        for a, b, date in [("S", "V", "2022-12-15"), ("LA", "V", "2016-11-28"), ("S", "SF", "2014-02-03"),
                           ("LA", "V", "2019-06-27"), ("RV", "S", "2011-10-03"), ("RV", "S", "2015-06-28")]
    }
    results["transitions_all"] = transitions(edges, windows, "all")
    results["transitions_backbench"] = transitions(backbench, windows, "backbench")
    panels = {}
    for before, after in zip(windows, windows[1:]):
        panel, count = panel_edges(backbench, before["name"], after["name"])
        rows = transitions(panel, [before, after], "panel")
        panels[after["from"]] = {"members_in_both": count, "rows": rows}
    results["transitions_panel"] = panels
    (RESULTS / "network.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str),
                                          encoding="utf-8")
    table = pd.DataFrame(results["transitions_all"])
    if not table.empty:
        print(table[table["relation"].isin(["joined", "split", "both_entered"])].to_string(index=False))
    print("done", flush=True)


if __name__ == "__main__":
    main()
