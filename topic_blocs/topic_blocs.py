"""Test (a) and (b) of PLAN.md. Run from the repo root.
(a) per topic x window: modularity Q of gov/opp and red/blue partitions on the undirected
    challenge graph, z against a within-debate floor shuffle; Louvain NMI (descriptive).
(b) per window: S = edge-weighted SD across topics of delta = Q_bloc - Q_gov, against
    whole-debate topic-label permutations within the window.
Usage: topic_blocs.py [--min-edges N] [--strat] [--tag name]"""
import argparse
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import normalized_mutual_info_score as nmi

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data" / "topic_blocs"
sys.path.insert(0, str(ROOT))
from archetypes.config import BLOC, SEED  # noqa: E402
from archetypes.data import load_all  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--min-edges", type=int, default=300)
ap.add_argument("--strat", action="store_true", help="permute topics within (window, Sag type)")
ap.add_argument("--no-ministers", action="store_true", help="drop edges with a minister at either end")
ap.add_argument("--rel", action="store_true", help="delta / (|Q_bloc| + |Q_gov|): which line, not how strong")
ap.add_argument("--sag-level", action="store_true", help="permute topics across whole cases (all readings together)")
ap.add_argument("--no-na", action="store_true", help="drop edges touching North Atlantic or unaffiliated members")
ap.add_argument("--tag", default="main")
ap.add_argument("--n-debate", type=int, default=200)
ap.add_argument("--n-topic", type=int, default=1000)
args = ap.parse_args()
rng = np.random.default_rng(SEED)

POLICY = ["economy", "welfare_health", "environment_energy", "justice", "labour", "immigration",
          "education_culture", "foreign_defence", "infrastructure_local"]

edges, runs, switches, windows, _ = load_all()
dt = pd.read_parquet(DATA / "debate_topics.parquet")
dt["stype"] = dt.nummer.str[0]
dt["case"] = dt.session.astype(str) + "-" + dt.nummer
e = edges.merge(dt[["debate", "topic", "stype", "case"]], on="debate", how="left")
e = e[e.challenger != e.floor]
if args.no_ministers:
    e = e[~e.c_minister & ~e.f_minister]
if args.no_na:
    e = e[e.c_bloc.isin(["red", "blue", "centre"]) & e.f_bloc.isin(["red", "blue", "centre"])]
print("edges", len(e), "with policy topic", e.topic.isin(POLICY).mean().round(3))
e = e[e.topic.isin(POLICY)].reset_index(drop=True)

# Node labels per window: modal party, majority gov flag.
ends = pd.concat([e[["window", "challenger", "c_party", "c_gov"]].set_axis(["window", "person", "party", "gov"], axis=1),
                  e[["window", "floor", "f_party", "f_gov"]].set_axis(["window", "person", "party", "gov"], axis=1)])
lab = ends.groupby(["window", "person"]).agg(party=("party", lambda x: x.mode().iloc[0]), gov=("gov", "mean")).reset_index()
lab["gov"] = (lab.gov >= 0.5).astype(int)
lab["bloc"] = lab.party.map(BLOC).fillna("none")


def q_of(gu, gv, ngroups):
    """Modularity of an undirected multigraph given the group code of each edge end."""
    m = len(gu)
    d = np.bincount(gu, minlength=ngroups) + np.bincount(gv, minlength=ngroups)
    return (gu == gv).mean() - ((d / (2 * m)) ** 2).sum()


def shuffle_within(groups, values):
    """Permute values within groups (groups is an int array)."""
    order = np.lexsort((rng.random(len(groups)), groups))
    out = values.copy()
    base = np.lexsort((np.arange(len(groups)), groups))  # positions sorted by group, original order
    out[base] = values[order]
    return out


rows_a, rows_b, null_store = [], [], {}
for w in [x["name"] for x in windows]:
    ew = e[e.window == w].reset_index(drop=True)
    if ew.empty:
        continue
    lw = lab[lab.window == w].set_index("person")
    codes = {}
    for part in ["gov", "bloc", "party"]:
        cat = pd.Categorical(lw[part].astype(str))
        codes[part] = (dict(zip(lw.index, cat.codes)), len(cat.categories))
    persons_c, persons_f = ew.challenger.to_numpy(), ew.floor.to_numpy()
    deb = pd.factorize(ew.debate)[0]

    def ends_codes(part, pc, pf):
        mp, k = codes[part]
        return np.array([mp[p] for p in pc]), np.array([mp[p] for p in pf]), k

    cu = {p: ends_codes(p, persons_c, persons_f) for p in codes}
    topics = [t for t in POLICY if (ew.topic == t).sum() >= args.min_edges]
    # (a)
    for t in topics:
        idx = np.flatnonzero(ew.topic.to_numpy() == t)
        row = {"window": w, "topic": t, "edges": len(idx), "debates": ew.debate.iloc[idx].nunique()}
        for part in ["gov", "bloc", "party"]:
            gu, gv, k = cu[part]
            row[f"Q_{part}"] = q_of(gu[idx], gv[idx], k)
        nulls = {p: [] for p in codes}
        for _ in range(args.n_debate):
            pf = shuffle_within(deb[idx], persons_f[idx])
            ok = pf != persons_c[idx]
            for part in codes:
                mp, k = codes[part]
                gu = cu[part][0][idx][ok]
                gv = np.array([mp[p] for p in pf[ok]])
                nulls[part].append(q_of(gu, gv, k))
        for part in codes:
            arr = np.array(nulls[part])
            row[f"Qnull_{part}"] = arr.mean()
            row[f"z_{part}"] = (row[f"Q_{part}"] - arr.mean()) / arr.std()
        G = nx.Graph()
        for a, b in zip(persons_c[idx], persons_f[idx]):
            G.add_edge(a, b, weight=G[a][b]["weight"] + 1 if G.has_edge(a, b) else 1)
        comm = nx.community.louvain_communities(G, weight="weight", seed=SEED)
        cl = {n: i for i, c in enumerate(comm) for n in c}
        nodes = list(G.nodes)
        row["Q_louvain"] = nx.community.modularity(G, comm, weight="weight")
        row["n_louvain"] = len(comm)
        for part in ["gov", "bloc", "party"]:
            row[f"nmi_{part}"] = nmi([lw.loc[n, part] for n in nodes], [cl[n] for n in nodes])
        rows_a.append(row)
    if len(topics) < 3:
        continue
    # (b)
    unit = pd.factorize(ew.case)[0] if args.sag_level else deb  # permutation unit
    deb_ids, first = np.unique(unit, return_index=True)
    deb_topic = ew.topic.to_numpy()[first]
    deb_strat = (ew.stype.fillna("?").to_numpy()[first] if args.strat else np.zeros(len(first), dtype=object))
    strat_codes = pd.factorize(deb_strat)[0]

    def stat(topic_of_edge):
        deltas, ws = [], []
        for t in topics:
            idx = topic_of_edge == t
            qb = q_of(cu["bloc"][0][idx], cu["bloc"][1][idx], cu["bloc"][2])
            qg = q_of(cu["gov"][0][idx], cu["gov"][1][idx], cu["gov"][2])
            deltas.append((qb - qg) / (abs(qb) + abs(qg)) if args.rel else qb - qg)
            ws.append(idx.sum())
        deltas, ws = np.array(deltas), np.array(ws, float)
        mu = (deltas * ws).sum() / ws.sum()
        return np.sqrt(((deltas - mu) ** 2 * ws).sum() / ws.sum()), deltas

    s_obs, d_obs = stat(ew.topic.to_numpy())
    null = []
    for _ in range(args.n_topic):
        perm = shuffle_within(strat_codes, deb_topic)
        null.append(stat(perm[unit])[0])
    null = np.array(null)
    null_store[w] = null
    rows_b.append({"window": w, "n_topics": len(topics), "edges": int(ew.topic.isin(topics).sum()),
                   "S_obs": s_obs, "S_null_mean": null.mean(), "S_null_sd": null.std(),
                   "z": (s_obs - null.mean()) / null.std(), "p": ((null >= s_obs).sum() + 1) / (len(null) + 1),
                   **{f"delta_{t}": d for t, d in zip(topics, d_obs)}})
    print(rows_b[-1]["window"], round(rows_b[-1]["z"], 2), flush=True)

A, B = pd.DataFrame(rows_a), pd.DataFrame(rows_b)
A.to_csv(DATA / f"test_a_{args.tag}.csv", index=False)
B.to_csv(DATA / f"test_b_{args.tag}.csv", index=False)
np.savez(DATA / f"null_b_{args.tag}.npz", **null_store)
pd.set_option("display.width", 220)
print(A[["window", "topic", "edges", "Q_gov", "Q_bloc", "z_gov", "z_bloc", "nmi_gov", "nmi_bloc", "nmi_party"]].round(3).to_string())
print(B[["window", "n_topics", "edges", "S_obs", "S_null_mean", "S_null_sd", "z", "p"]].round(4).to_string())
print("windows with z>=2:", (B.z >= 2).sum(), "of", len(B))
