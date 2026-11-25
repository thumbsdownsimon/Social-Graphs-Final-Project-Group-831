"""Vote sanity check: does the vote divide also move with topic?
Per window x topic (>= MIN_VOTES votes): party-pair agreement (same side, for/imod only).
Separation of a partition = mean agreement of same-group pairs - mean of cross-group pairs.
delta = sep_bloc - sep_gov; S = vote-weighted SD of delta across topics; null: permute topic
labels across whole Sager (all votes on one case move together) within window. Also S-DF and S-V agreement per topic."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data" / "topic_blocs"
sys.path.insert(0, str(ROOT))
from archetypes.config import BLOC, SEED  # noqa: E402
from archetypes.data import load_windows  # noqa: E402

MIN_VOTES = 50
POLICY = ["economy", "welfare_health", "environment_energy", "justice", "labour", "immigration",
          "education_culture", "foreign_defence", "infrastructure_local"]
rng = np.random.default_rng(SEED)
pp = pd.read_parquet(ROOT / "data" / "party_positions.parquet")
vt = pd.read_parquet(DATA / "vote_topics.parquet")
pp = pp.merge(vt[["vote", "sag", "topic"]], on="vote", how="left")
pp = pp[pp.side.isin(["for", "imod"]) & pp.topic.isin(POLICY)]
pp["x"] = np.where(pp.side == "for", 1, -1)
windows = load_windows()
pp["window"] = None
for w in windows:
    pp.loc[(pp.date >= w["from"]) & (pp.date < w["to"]), "window"] = w["name"]

rows_b, rows_pair = [], []
for w in windows:
    d = pp[pp.window == w["name"]]
    if d.empty:
        continue
    X = d.pivot_table(index="vote", columns="party", values="x", aggfunc="first")
    X = X.loc[:, X.notna().mean() > 0.5]  # parties present in most votes
    meta = d.drop_duplicates("vote").set_index("vote").reindex(X.index)
    topic = meta.topic.to_numpy()
    sag_code, sag_first = pd.factorize(meta.sag)[0], None
    _, first = np.unique(sag_code, return_index=True)
    sag_topic = topic[first]
    parties = list(X.columns)
    gov = np.array([p in w["government"] for p in parties])
    bloc = np.array([BLOC.get(p, "none") for p in parties])
    P, N = (X.to_numpy() == 1).astype(float), (X.to_numpy() == -1).astype(float)
    off = ~np.eye(len(parties), dtype=bool)

    def agree(mask):
        a = P[mask].T @ P[mask] + N[mask].T @ N[mask]
        n = (P[mask] + N[mask]).T @ (P[mask] + N[mask])
        return a / np.where(n > 0, n, np.nan)

    def sep(A, g):
        same = (g[:, None] == g[None, :]) & off
        return np.nanmean(A[same]) - np.nanmean(A[~same & off])

    topics = [t for t in POLICY if (topic == t).sum() >= MIN_VOTES]
    if len(topics) < 3:
        continue

    def stat(tp):
        ds, ws = [], []
        for t in topics:
            A = agree(tp == t)
            ds.append(sep(A, bloc) - sep(A, gov))
            ws.append((tp == t).sum())
        ds, ws = np.array(ds), np.array(ws, float)
        mu = (ds * ws).sum() / ws.sum()
        return np.sqrt(((ds - mu) ** 2 * ws).sum() / ws.sum()), ds

    s_obs, ds = stat(topic)
    null = np.array([stat(rng.permutation(sag_topic)[sag_code])[0] for _ in range(1000)])
    rows_b.append({"window": w["name"], "votes": int(np.isin(topic, topics).sum()), "n_topics": len(topics),
                   "S_obs": s_obs, "S_null_mean": null.mean(), "z": (s_obs - null.mean()) / null.std(),
                   **{f"delta_{t}": x for t, x in zip(topics, ds)}})
    for t in topics:
        A = pd.DataFrame(agree(topic == t), index=parties, columns=parties)
        r = {"window": w["name"], "topic": t, "votes": int((topic == t).sum())}
        for a, b in [("S", "DF"), ("S", "V"), ("S", "EL"), ("V", "DF"), ("S", "DD")]:
            r[f"{a}-{b}"] = A.loc[a, b] if a in A and b in A else np.nan
        rows_pair.append(r)
B, Pr = pd.DataFrame(rows_b), pd.DataFrame(rows_pair)
B.to_csv(DATA / "vote_b.csv", index=False)
Pr.to_csv(DATA / "vote_pairs.csv", index=False)
pd.set_option("display.width", 250)
print(B.round(3).to_string())
print(Pr.round(2).to_string())
