"""Per-member network measures for one government window -> one row per member.

The network: one directed edge per short remark, from the challenger to the member holding
the floor. "Out" = challenges a member made, "in" = challenges a member received.

All shares are over that member's own edges in the window and are NaN when the member has
no edges of that kind (a member who never challenges has no targeting profile).

Columns, in plain words
-----------------------
Who the member is
    party                   the party they are listed under most often in the window
    in_government           True if most of their edges happened while their party was in government
    was_minister            True if they appeared as a minister at least once
    first_seen, last_seen   first and last date they appear in the window
    exposure_days           sitting days between first_seen and last_seen; the "time present" used for rates
    exposure_days_backbench / _minister   the same, counted over their non-minister / minister appearances

How active they are
    out_w, in_w             number of challenges made / received
    in_w_backbench          received while NOT a minister
    in_w_minister           received while a minister (ministers are challenged by default, so kept apart)
    minister_share          in_w_minister / in_w
    out_rate, in_rate       out_w / exposure_days, in_w / exposure_days: per sitting day, so a member who
                            joined halfway through is not counted as half as active
    in_rate_backbench       in_w_backbench / exposure_days_backbench
    in_rate_minister        in_w_minister / exposure_days_minister
    attack_balance          (out_w - in_w) / (out_w + in_w): +1 = only attacks, -1 = only attacked,
                            0 = attacks and is attacked equally

Who they challenge (share of their OWN challenges, out-edges)
    share_cross_side        aimed at the other side (government vs opposition)
    share_own_side          aimed at allies (same party, both in government, or both in opposition
                            and in the same red/blue bloc; see data.own_side)
    share_own_party         aimed at their own party
    share_at_government     aimed at a minister or a government-party member
    share_cross_bloc        aimed at the other bloc (red vs blue); NaN if every target is outside red/blue
    n_targets               number of different people they challenged
    top_target_share        share aimed at their single most-challenged person (1 = one fixation)
    target_entropy          how EVENLY their challenges spread over the people they challenged:
                            0 = all at one person, 1 = equally many at each (see _entropy)

Who challenges them (in-edges)
    in_share_cross_side     share of received challenges that came from the other side
    n_challengers           number of different people who challenged them
    in_n_parties            number of different parties that challenged them
    in_party_diversity      how spread the received challenges are over parties: the chance that two
                            random received challenges come from different parties (see _simpson)

How mixed their contacts are
    participation           the same "two random ones differ" measure as in_party_diversity, but over
                            everyone they interact with, made AND received, by the partner's party.
                            0 = deals with one party only; higher = deals with many parties evenly.
                            This is the participation coefficient (Guimera & Amaral 2005), with
                            parties as the groups.

Position in the whole network (see structural)
    pagerank_in             "challenged by important people": PageRank on challenger -> floor edges.
                            Being challenged counts more when the challenger is themselves challenged a lot.
    hub                     "a good attacker": challenges the members who are the main targets (HITS)
    authority               "a main target": challenged by the good attackers (HITS)
    betweenness             "sits between groups": share of shortest paths between other members that
                            pass through this member, ignoring direction
    reciprocity             of everyone they have an exchange with, the share where challenges go both ways
"""
import networkx as nx
import numpy as np
import pandas as pd


def _days_between(first, last, days):
    """Number of sitting days in [first, last], inclusive."""
    return int(np.searchsorted(days, last, side="right") - np.searchsorted(days, first, side="left"))


def long_ends(edges):
    """Each edge seen from both ends: one row per (person, edge, direction)."""
    cols = ["date", "c_party", "f_party", "c_gov", "f_gov", "c_minister", "f_minister"]
    out_side = edges[cols].assign(person=edges["challenger"].to_numpy(), partner=edges["floor"].to_numpy(),
                                  direction="out", party=edges["c_party"].to_numpy(),
                                  partner_party=edges["f_party"].to_numpy(), gov=edges["c_gov"].to_numpy(),
                                  minister=edges["c_minister"].to_numpy())
    in_side = edges[cols].assign(person=edges["floor"].to_numpy(), partner=edges["challenger"].to_numpy(),
                                 direction="in", party=edges["f_party"].to_numpy(),
                                 partner_party=edges["c_party"].to_numpy(), gov=edges["f_gov"].to_numpy(),
                                 minister=edges["f_minister"].to_numpy())
    return pd.concat([out_side, in_side], ignore_index=True)


def _entropy(counts):
    """How evenly counts are spread over the categories that occur: 0 = all in one, 1 = all equal.

    Shannon entropy -sum(p * log p), divided by its maximum log(k), k = number of categories.
    Example: [10, 10, 10] -> 1.0, [28, 1, 1] -> about 0.27, [30] -> 0.0.
    k only counts categories that occur, so [5, 5] and fifty 5s both give 1.0: this measures
    evenness, not how many categories there are (use the count itself for that).
    """
    counts = np.asarray(counts, dtype=float)
    if len(counts) <= 1:
        return 0.0
    p = counts / counts.sum()
    return float(-(p * np.log(p)).sum() / np.log(len(p)))


def _simpson(counts):
    """Chance that two random items fall in different categories: 1 - sum(p_i ** 2).

    0 when everything is in one category; grows with more and more evenly used categories,
    up to 1 - 1/k for k equal categories. NaN when there are no items.
    Example (counts per party): [20] -> 0.0, [10, 10] -> 0.5, [5, 5, 5, 5] -> 0.75,
    [17, 1, 1, 1] -> about 0.27.
    This is the Simpson diversity index; with parties as groups it is the participation
    coefficient used in network science (Guimera & Amaral 2005).
    """
    counts = np.asarray(counts, dtype=float)
    if counts.sum() == 0:
        return np.nan
    p = counts / counts.sum()
    return float(1 - (p ** 2).sum())


def activity_and_shares(edges, days):
    """Counts, rates, targeting and receiving shares per member, from the edge table alone.

    Covers every column in the module docstring except "Position in the whole network".
    days: sorted array of sitting days, used to turn counts into per-day rates.
    """
    ends = long_ends(edges)
    rows = []
    out_edges = edges.groupby("challenger")
    in_edges = edges.groupby("floor")
    for person, part in ends.groupby("person", sort=True):
        row = {"person": int(person)}
        row["party"] = part["party"].mode().iloc[0]
        row["in_government"] = bool(part["gov"].mean() > 0.5)
        row["was_minister"] = bool(part["minister"].any())
        row["first_seen"], row["last_seen"] = part["date"].min(), part["date"].max()
        row["exposure_days"] = _days_between(row["first_seen"], row["last_seen"], days)
        back = part[~part["minister"]]
        mini = part[part["minister"]]
        row["exposure_days_backbench"] = _days_between(back["date"].min(), back["date"].max(), days) if len(back) else 0
        row["exposure_days_minister"] = _days_between(mini["date"].min(), mini["date"].max(), days) if len(mini) else 0

        out = out_edges.get_group(person) if person in out_edges.groups else edges.iloc[0:0]
        inc = in_edges.get_group(person) if person in in_edges.groups else edges.iloc[0:0]
        row["out_w"], row["in_w"] = len(out), len(inc)
        row["in_w_backbench"] = int((~inc["f_minister"]).sum())
        row["in_w_minister"] = int(inc["f_minister"].sum())
        row["minister_share"] = row["in_w_minister"] / row["in_w"] if row["in_w"] else np.nan
        row["out_rate"] = row["out_w"] / max(row["exposure_days"], 1)
        row["in_rate"] = row["in_w"] / max(row["exposure_days"], 1)
        row["in_rate_backbench"] = (row["in_w_backbench"] / row["exposure_days_backbench"]
                                    if row["exposure_days_backbench"] else np.nan)
        row["in_rate_minister"] = (row["in_w_minister"] / row["exposure_days_minister"]
                                   if row["exposure_days_minister"] else np.nan)
        total = row["out_w"] + row["in_w"]
        row["attack_balance"] = (row["out_w"] - row["in_w"]) / total if total else np.nan

        if len(out):
            row["share_cross_side"] = float(out["cross_side"].mean())
            row["share_own_side"] = float(out["own_side"].mean())
            row["share_own_party"] = float(out["same_party"].mean())
            row["share_at_government"] = float(out["at_government"].mean())
            row["share_cross_bloc"] = float(out["cross_bloc"].mean()) if out["cross_bloc"].notna().any() else np.nan
            targets = out["floor"].value_counts()
            row["n_targets"] = len(targets)
            row["target_entropy"] = _entropy(targets.to_numpy())
            row["top_target_share"] = float(targets.iloc[0] / len(out))
        if len(inc):
            row["in_share_cross_side"] = float(inc["cross_side"].mean())
            parties_in = inc["c_party"].value_counts()
            row["in_n_parties"] = len(parties_in)
            row["in_party_diversity"] = _simpson(parties_in.to_numpy())
            row["n_challengers"] = int(inc["challenger"].nunique())
        row["participation"] = _simpson(part["partner_party"].value_counts().to_numpy())
        rows.append(row)
    return pd.DataFrame(rows)


def structural(graph):
    """PageRank, HITS, betweenness and reciprocity per node of one window's graph.

    graph: directed, challenger -> floor holder, edge weight = number of challenges.

    pagerank_in  PageRank with edge weights. A random walker follows challenges from challenger
                 to target, so score piles up on members who are challenged a lot, and more so
                 when their challengers are themselves challenged a lot.
    hub          high when the member challenges members with a high authority score.
    authority    high when the member is challenged by members with a high hub score.
                 The two are computed together by repeating those two rules until they settle.
    betweenness  share of shortest paths between pairs of other members that pass through this
                 member. Direction is ignored, and a pair with more challenges is treated as
                 closer (distance = 1 / number of challenges between them).
    reciprocity  (partners challenged in both directions) / (all partners).
    """
    if graph.number_of_nodes() == 0:
        return pd.DataFrame(columns=["person"])
    pagerank = nx.pagerank(graph, weight="weight")
    try:
        hubs, auths = nx.hits(graph, max_iter=2000, normalized=True)
    except (nx.PowerIterationFailedConvergence, ValueError):
        hubs = auths = {n: np.nan for n in graph}
    # Betweenness on the undirected graph, where more challenges = a shorter, stronger tie.
    undirected = nx.Graph()
    for a, b, d in graph.edges(data=True):
        w = d["weight"] + (undirected[a][b]["weight"] if undirected.has_edge(a, b) else 0)
        undirected.add_edge(a, b, weight=w)
    for a, b, d in undirected.edges(data=True):
        d["distance"] = 1.0 / d["weight"]
    betweenness = nx.betweenness_centrality(undirected, weight="distance", normalized=True)
    rows = []
    for node in graph.nodes:
        succ, pred = set(graph.successors(node)), set(graph.predecessors(node))
        partners = succ | pred
        rows.append({"person": int(node), "pagerank_in": pagerank[node], "hub": hubs[node],
                     "authority": auths[node], "betweenness": betweenness.get(node, 0.0),
                     "reciprocity": len(succ & pred) / len(partners) if partners else np.nan})
    return pd.DataFrame(rows)


def member_table(edges, graph, days, window_name):
    """Every layer-1 measure for one window, one row per member."""
    table = activity_and_shares(edges, days).merge(structural(graph), on="person", how="left")
    table.insert(1, "window", window_name)
    return table
