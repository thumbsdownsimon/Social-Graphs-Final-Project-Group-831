#!/usr/bin/env python3
"""Step 4b of the pipeline: member-level votes, 2017-18 to 2025-26.

    python tools/analyze_votes.py

Writes data/results/votes.json. This sets up the question: if members almost never leave
the party line, individual votes cannot tell us much, and the interesting variation has to
be elsewhere.

  rebel rate    share of cast votes against the member's party majority. Misses dissent
                expressed by not voting, because absence is about 40% of rows and appears to
                be structural, so absence is never counted as a position.
  vote network  member agreement on contested votes, Louvain, NMI with party. The check is
                a null that shuffles each member's votes within their party, which keeps
                the party line and destroys any individual pattern.
"""
import json
import sys
from pathlib import Path

import community as community_louvain
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import normalized_mutual_info_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_network import DATA, NOT_A_PARTY, RESULTS, ROOT, SEED, load_windows, window_of
from build_dataset import RAW_TABLES, Resolver, load

ABSENT, FOR, AGAINST, ABSTAIN = 3, 1, 2, 4
MIN_SHARED_VOTES = 30
FIRST_SESSION = "20171"

sys.stdout.reconfigure(encoding="utf-8")


def member_votes(windows):
    rows = pd.DataFrame(json.loads((RAW_TABLES / "member_votes.json").read_text(encoding="utf-8")))
    sessions = load("sessions")
    resolver = Resolver(load("persons"), load("party_groups"), load("memberships"), sessions)
    code = {s["id"]: s["kode"] for s in sessions}
    meetings = {m["id"]: m for m in load("meetings")}
    info = pd.DataFrame([
        {"vote": v["id"], "session": code.get(meetings[v["mødeid"]]["periodeid"]), "date": meetings[v["mødeid"]]["dato"][:10]}
        for v in load("votes") if v["mødeid"] in meetings
    ])
    rows = rows.merge(info, on="vote")
    rows = rows[rows["session"] >= FIRST_SESSION]
    keys = rows[["person", "session", "date"]].drop_duplicates()
    keys["party"] = [resolver.party(p, s, d) or resolver.nearest_party(p, s)
                     for p, s, d in zip(keys["person"], keys["session"], keys["date"])]
    rows = rows.merge(keys, on=["person", "session", "date"])
    rows["window"] = window_of(rows["date"], windows)
    return rows[rows["window"].notna()]


def rebel_table(rows):
    """Rebel rate per window, for party members with at least two colleagues voting."""
    cast = rows[(rows["type"] != ABSENT) & rows["party"].notna() & ~rows["party"].isin(NOT_A_PARTY)].copy()
    counts = cast.groupby(["vote", "party", "type"]).size().rename("n").reset_index()
    majority = counts.sort_values("n").groupby(["vote", "party"]).tail(1).rename(columns={"type": "line"})
    size = cast.groupby(["vote", "party"]).size().rename("voters").reset_index()
    cast = cast.merge(majority[["vote", "party", "line"]], on=["vote", "party"]).merge(size, on=["vote", "party"])
    cast = cast[cast["voters"] >= 3]
    cast["rebel"] = cast["type"] != cast["line"]
    table = []
    for window, part in cast.groupby("window"):
        by_vote = part.groupby("vote")["rebel"].any()
        table.append({"window": window, "cast": len(part), "rebel_votes": int(part["rebel"].sum()),
                      "rebel_rate": round(float(part["rebel"].mean()), 5),
                      "votes": int(by_vote.size), "votes_with_a_rebel": round(float(by_vote.mean()), 3),
                      "absent_share": round(float((rows.loc[rows["window"] == window, "type"] == ABSENT).mean()), 3)})
    return table, cast


def agreement_graph(matrix):
    """Weighted graph: agreement above the chamber's mean, on votes both members cast."""
    values = matrix.to_numpy(dtype=float)
    cast = ~np.isnan(values)
    shared = cast.astype(int) @ cast.astype(int).T
    same = np.zeros_like(shared, dtype=float)
    for side in (FOR, AGAINST, ABSTAIN):
        mask = (values == side).astype(int)
        same += mask @ mask.T
    with np.errstate(invalid="ignore", divide="ignore"):
        agreement = np.where(shared >= MIN_SHARED_VOTES, same / shared, np.nan)
    upper = agreement[np.triu_indices_from(agreement, 1)]
    mean = np.nanmean(upper)
    graph = nx.Graph()
    people = matrix.index.tolist()
    for i in range(len(people)):
        for j in range(i + 1, len(people)):
            if not np.isnan(agreement[i, j]) and agreement[i, j] > mean:
                graph.add_edge(people[i], people[j], weight=float(agreement[i, j] - mean))
    return graph


def vote_network(rows, seed=SEED):
    """Louvain on members' agreement on contested votes, and how far that is from party alone."""
    results = {}
    rng = np.random.default_rng(seed)
    cast = rows[(rows["type"] != ABSENT) & rows["party"].notna()]
    sides = cast.groupby("vote")["type"].agg(lambda t: {FOR, AGAINST} <= set(t))
    contested = cast[cast["vote"].isin(sides[sides].index)]
    for window, part in contested.groupby("window"):
        if part["vote"].nunique() < 100:
            continue
        matrix = part.pivot_table(index="person", columns="vote", values="type", aggfunc="first")
        party = part.groupby("person")["party"].last()
        graph = agreement_graph(matrix)
        nodes = sorted(graph)
        partitions = [community_louvain.best_partition(graph, random_state=seed + i) for i in range(10)]
        best = max(partitions, key=lambda p: community_louvain.modularity(p, graph))
        vectors = [[p[n] for n in nodes] for p in partitions]

        shuffled = matrix.copy()
        for name, members in party.groupby(party).groups.items():
            members = [m for m in members if m in shuffled.index]
            for vote in shuffled.columns:
                column = shuffled.loc[members, vote].to_numpy()
                shuffled.loc[members, vote] = rng.permutation(column)
        null_graph = agreement_graph(shuffled)
        null_nodes = sorted(null_graph)
        null_partition = community_louvain.best_partition(null_graph, random_state=seed)
        results[window] = {
            "members": len(nodes), "contested_votes": int(part["vote"].nunique()), "communities": len(set(best.values())),
            "modularity": round(community_louvain.modularity(best, graph), 3),
            "seed_stability_nmi": round(float(np.mean([normalized_mutual_info_score(vectors[0], v) for v in vectors[1:]])), 3),
            "nmi_with_party": round(float(normalized_mutual_info_score([party[n] for n in nodes], [best[n] for n in nodes])), 3),
            "null_within_party_shuffle_nmi": round(float(normalized_mutual_info_score(
                [party[n] for n in null_nodes], [null_partition[n] for n in null_nodes])), 3),
            "community_parties": {str(c): sorted(party[[n for n in nodes if best[n] == c]].value_counts().head(4).index.tolist())
                                  for c in set(best.values())},
        }
        print(window, {k: v for k, v in results[window].items() if k != "community_parties"}, flush=True)
    return results


def main():
    windows = load_windows()
    rows = member_votes(windows)
    print("rows", len(rows), flush=True)
    rebels, _ = rebel_table(rows)
    for row in rebels:
        print(row, flush=True)
    results = {"rebels": rebels, "vote_network": vote_network(rows),
               "votes_covered": int(rows["vote"].nunique())}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "votes.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
