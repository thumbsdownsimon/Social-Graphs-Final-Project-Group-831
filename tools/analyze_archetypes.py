#!/usr/bin/env python3
"""Step 7b of the pipeline: archetypes of members, from network, tone, votes and party history.

    python tools/analyze_archetypes.py

Writes data/results/archetypes.json and caches challenge tone in data-raw/derived/.

This answers the problem statement in README.md:
  1. Profile every member: how much they challenge and get challenged, at whom, in what tone,
     how often they vote against their party, and whether they changed party.
  2. Define archetypes by rules written down in advance (ARCHETYPES below).
  3. Cluster the same profiles without the rules, and compare the clusters with the archetypes.
  4. Ask whether each archetype is set apart by tone or by network position.
  5. Find each archetype's most distinctive words.
  6. Count archetypes per party, and follow members across governments.

DRAFT: the tone measure (AFINN Danish lexicon) is not yet checked against the group's stance
labels, and every threshold below is a first choice for the group to review.
"""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from afinn import Afinn
from joblib import Parallel, delayed
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_language import name_remover
from analyze_network import DATA, RESULTS, ROOT, SEED, load_windows, window_of

SPEECHES = ROOT / "data-raw" / "derived" / "speeches.parquet"
TONE_CACHE_DIR = ROOT / "data-raw" / "derived"
OUT = RESULTS / "archetypes.json"

# Blocs as they are usually described in Danish politics. M calls itself the centre and is kept
# apart. North Atlantic seats and members outside groups (UFG) belong to no bloc.
BLOC = {**{p: "red" for p in ["S", "SF", "RV", "EL", "ALT", "FG"]},
        **{p: "blue" for p in ["V", "KF", "DF", "LA", "NB", "DD", "KD", "BP"]},
        "M": "centre"}
PARTY_ALIAS = {"TF": "T"}  # Tjóðveldi appears under two codes

MIN_MADE = 20          # challenges made, to be profiled at all (tone needs text to score)
MIN_YEARS = 1
TOP = 0.90             # "top 10%" for the rate-based archetypes
MIN_TARGET_SUBSET = 5  # challenges at a target group before its tone is reported
MIN_CAST_VOTES = 300   # for a rebel rate
K_RANGE = range(3, 11)
N_SEEDS = 20
N_WORDS = 15
MIN_WINDOW_MADE = 10   # per government window, for following members over time
MIN_CROSS_BLOC = 20    # cross-bloc challenges before a member can be a bridge builder

# The opening ritual of a short remark. AFINN scores "tak" as positive, so leaving it in makes
# almost every remark look friendly.
# Any short opening sentence that starts with "tak" ("Tak til ordføreren for talen.") is removed.
RITUAL = re.compile(r"^\s*(?:(?:mange )?tak\b[^.!?]{0,80}[.!?]\s*)+", re.IGNORECASE)
QUESTION = re.compile(r"\?")
CONNECTIVES = re.compile(r"\b(?:men|fordi|derfor|hvorfor|altså|jo|dog|alligevel|tværtimod)\b", re.IGNORECASE)

# Which measures belong to which family, for "is this archetype about tone or the network?"
FEATURES = {
    "made_per_year": ("network", "Challenges made per year (log)"),
    "received_per_year": ("network", "Challenges received as a backbencher per year (log)"),
    "cross_bloc_share": ("network", "Share of own challenges aimed at the other bloc"),
    "own_party_share": ("network", "Share of own challenges aimed at own party"),
    "at_government_share": ("network", "Share of own challenges aimed at the government"),
    "target_spread": ("network", "Distinct members challenged per challenge"),
    "betweenness": ("network", "Betweenness in the challenge network (log)"),
    "tone": ("tone", "Mean tone of own challenges (AFINN per 100 words)"),
    "negative_share": ("tone", "Share of own challenges with negative tone"),
    "emotional": ("tone", "Emotional words per 100 words (positive or negative)"),
    "question_rate": ("tone", "Question marks per 100 words"),
    "connective_rate": ("tone", "Argument words per 100 words (men, fordi, derfor, jo ...)"),
    "tone_received": ("tone", "Mean tone of challenges received"),
    "tone_at_other_bloc": ("tone", "Mean tone of own challenges aimed at the other bloc"),
    "minister_share": ("career", "Share of years as minister"),
    "defected": ("career", "Changed party at least once"),
    "rebel_rate": ("career", "Votes against own party (2017 on; 0 before)"),
}
LOG_FEATURES = {"made_per_year", "received_per_year", "betweenness"}

ARCHETYPES = {
    "attack_dog": {"name": "Attack dog", "rule": "Top 10% for challenges made per year, with most of them aimed at the other bloc or the government.",
                   "uses": ["made_per_year", "cross_bloc_share", "at_government_share"]},
    "lightning_rod": {"name": "Lightning rod", "rule": "Top 10% for challenges received per year while not a minister.",
                      "uses": ["received_per_year"]},
    "negative_nancy": {"name": "Negative Nancy", "rule": "Bottom 10% for mean tone of own challenges.",
                       "uses": ["tone", "negative_share"]},
    "bridge_builder": {"name": "Bridge builder", "rule": "Top 10% for the tone of challenges aimed at the other bloc, among members with at least 20 such challenges.",
                       "uses": ["tone_at_other_bloc"]},
    "defector": {"name": "Defector", "rule": "Changed party at least once between sessions (leaving for no group counts).",
                 "uses": ["defected"]},
    "rebel": {"name": "Rebel", "rule": "Top 10% for votes against own party, among members with at least 300 cast votes from 2017 on.",
              "uses": ["rebel_rate"]},
}

sys.stdout.reconfigure(encoding="utf-8")


# ---------- loading ----------

def load_speeches():
    columns = ["session", "meeting", "turn", "date", "text", "words", "person", "party",
               "is_person", "is_chair", "is_minister"]
    frame = pd.read_parquet(SPEECHES, columns=columns)
    frame = frame[frame["is_person"] & ~frame["is_chair"] & frame["person"].notna()].copy()
    frame["person"] = frame["person"].astype(int)
    frame["party"] = frame["party"].replace(PARTY_ALIAS)
    return frame


def load_challenges(speeches, windows):
    edges = pd.read_parquet(DATA / "challenges.parquet")
    edges = edges[edges["floor_person"].notna() & edges["challenger_person"].notna()
                  & (edges["floor_person"] != edges["challenger_person"])].copy()
    for side in ["floor", "challenger"]:
        edges[f"{side}_person"] = edges[f"{side}_person"].astype(int)
        edges[f"{side}_party"] = edges[f"{side}_party"].replace(PARTY_ALIAS)
        edges[f"{side}_bloc"] = edges[f"{side}_party"].map(BLOC)
    edges["window"] = window_of(edges["date"], windows)
    government = {w["name"]: set(w["government"]) for w in windows}
    edges["floor_in_government"] = edges["floor_is_minister"].to_numpy() | np.array([
        party in government.get(w, ()) for party, w in zip(edges["floor_party"], edges["window"])])
    edges["challenger_in_government"] = np.array([party in government.get(w, ()) for party, w in zip(edges["challenger_party"], edges["window"])])
    texts = speeches[["session", "meeting", "turn", "text"]]
    return edges.merge(texts, on=["session", "meeting", "turn"], how="left")


# ---------- tone ----------

def _tone_rows(texts):
    afinn = Afinn(language="da")
    rows = []
    for text in texts:
        body = RITUAL.sub("", text or "")
        words = max(len(body.split()), 1)
        scores = afinn.scores(body)
        rows.append((sum(scores) / words * 100, sum(abs(s) for s in scores) / words * 100,
                     len(QUESTION.findall(body)) / words * 100, len(CONNECTIVES.findall(body)) / words * 100,
                     sum(scores)))
    return rows


def challenge_tone(edges):
    """AFINN tone per challenge, with the opening "tak for det" removed. Cached, as it takes minutes."""
    key = ["session", "meeting", "turn"]
    # The cache name carries the ritual pattern, so changing it can never reuse stale scores.
    TONE_CACHE = TONE_CACHE_DIR / f"challenge_tone_{hashlib.sha1(RITUAL.pattern.encode()).hexdigest()[:8]}.parquet"
    if TONE_CACHE.exists():
        cached = pd.read_parquet(TONE_CACHE)
        if len(cached) == len(edges.drop_duplicates(key)):
            return edges.merge(cached, on=key, how="left")
    unique = edges.drop_duplicates(key)[key + ["text"]].reset_index(drop=True)
    parts = np.array_split(unique["text"].to_numpy(), 64)
    rows = [r for part in Parallel(n_jobs=-1)(delayed(_tone_rows)(list(p)) for p in parts) for r in part]
    tone = pd.DataFrame(rows, columns=["tone", "emotional", "question_rate", "connective_rate", "afinn_raw"])
    cached = pd.concat([unique[key], tone], axis=1)
    cached.to_parquet(TONE_CACHE)
    print("scored tone of", len(cached), "challenges", flush=True)
    return edges.merge(cached, on=key, how="left")


# ---------- member profiles ----------

def party_history(speeches):
    """Each member's party per session (the most common one), and the switches between sessions."""
    members = speeches[speeches["party"].notna() & ~speeches["party"].isin(["Pause", "MødeSlut"])]
    modal = members.groupby(["person", "session"])["party"].agg(lambda s: s.value_counts().index[0]).reset_index()
    history = {}
    for person, group in modal.sort_values("session").groupby("person"):
        sequence = [p for i, p in enumerate(group["party"]) if i == 0 or p != group["party"].iloc[i - 1]]
        history[int(person)] = sequence
    return history


def rebel_rates():
    """Votes against the member's party majority, from 2017 on (analyze_votes.py's definition)."""
    from analyze_votes import member_votes, rebel_table
    _, cast = rebel_table(member_votes(load_windows()))
    table = cast.groupby("person")["rebel"].agg(["mean", "size"])
    return table[table["size"] >= MIN_CAST_VOTES]["mean"].to_dict(), table["size"].to_dict()


def betweenness(edges):
    graph = nx.Graph()
    for (a, b), n in edges.groupby(["challenger_person", "floor_person"]).size().items():
        old = graph.get_edge_data(a, b, {"weight": 0})["weight"]
        graph.add_edge(int(a), int(b), weight=old + int(n))
    for _, _, data in graph.edges(data=True):
        data["distance"] = 1 / data["weight"]
    return nx.betweenness_centrality(graph, weight="distance", normalized=True)


def mean_if(values, n=MIN_TARGET_SUBSET):
    return float(values.mean()) if len(values) >= n else np.nan


def profile(made, received, years, minister_years):
    """One member's measures from the challenges they made and received."""
    known = made[made["floor_bloc"].notna() & made["challenger_bloc"].notna()]
    backbench = received[~received["floor_is_minister"]]
    return {
        "made": len(made), "received": len(received), "received_backbench": len(backbench), "years": years,
        "made_per_year": len(made) / years,
        "received_per_year": len(backbench) / years,
        "cross_bloc_share": float((known["floor_bloc"] != known["challenger_bloc"]).mean()) if len(known) else np.nan,
        "own_party_share": float((made["floor_party"] == made["challenger_party"]).mean()) if len(made) else np.nan,
        "at_government_share": float(made["floor_in_government"].mean()) if len(made) else np.nan,
        "target_spread": made["floor_person"].nunique() / len(made) if len(made) else np.nan,
        "tone": float(made["tone"].mean()) if len(made) else np.nan,
        "negative_share": float((made["afinn_raw"] < 0).mean()) if len(made) else np.nan,
        "emotional": float(made["emotional"].mean()) if len(made) else np.nan,
        "question_rate": float(made["question_rate"].mean()) if len(made) else np.nan,
        "connective_rate": float(made["connective_rate"].mean()) if len(made) else np.nan,
        "tone_received": mean_if(received["tone"]),
        "cross_bloc_made": int((known["floor_bloc"] != known["challenger_bloc"]).sum()),
        "tone_at_other_bloc": mean_if(known.loc[known["floor_bloc"] != known["challenger_bloc"], "tone"]),
        "tone_at_own_bloc": mean_if(known.loc[(known["floor_bloc"] == known["challenger_bloc"])
                                              & (known["floor_party"] != known["challenger_party"]), "tone"]),
        "tone_at_own_party": mean_if(made.loc[made["floor_party"] == made["challenger_party"], "tone"]),
        "tone_at_government": mean_if(made.loc[made["floor_in_government"] & ~made["challenger_in_government"], "tone"]),
        "minister_share": minister_years / years,
    }


def member_table(speeches, edges, names):
    speeches = speeches.assign(year=speeches["session"].str[:4])
    years = speeches.groupby("person")["year"].nunique()
    minister_years = speeches[speeches["is_minister"]].groupby("person")["year"].nunique()
    history = party_history(speeches)
    rebel, cast = rebel_rates()
    between = betweenness(edges)
    made_by, received_by = dict(list(edges.groupby("challenger_person"))), dict(list(edges.groupby("floor_person")))
    empty = edges.iloc[0:0]
    rows = []
    for person in sorted(set(made_by) | set(received_by)):
        if years.get(person, 0) < MIN_YEARS:
            continue
        row = {"person": int(person), "name": names.get(person, str(person))}
        row.update(profile(made_by.get(person, empty), received_by.get(person, empty),
                           int(years[person]), int(minister_years.get(person, 0))))
        parties = history.get(person, [])
        counted = speeches.loc[speeches["person"] == person, "party"].value_counts()
        row.update(party=counted.index[0] if len(counted) else None, parties=parties,
                   defected=int(len(parties) > 1), rebel_rate=rebel.get(person, np.nan),
                   cast_votes=int(cast.get(person, 0)), betweenness=between.get(person, 0.0))
        rows.append(row)
    return pd.DataFrame(rows)


# ---------- archetypes ----------

def assign_archetypes(table):
    """Rule-based flags. A member can hold several; 'primary' is the one they are most extreme on."""
    q = lambda col, p: float(table[col].quantile(p))
    th = {"made_per_year": q("made_per_year", TOP), "received_per_year": q("received_per_year", TOP),
          "tone_low": q("tone", 1 - TOP),
          "tone_at_other_bloc": float(table.loc[table["cross_bloc_made"] >= MIN_CROSS_BLOC, "tone_at_other_bloc"].quantile(TOP)),
          "rebel_rate": float(table["rebel_rate"].dropna().quantile(TOP))}
    opponents = np.fmax(table["cross_bloc_share"].fillna(0), table["at_government_share"].fillna(0))
    flags = pd.DataFrame({
        "attack_dog": (table["made_per_year"] >= th["made_per_year"]) & (opponents >= 0.5),
        "lightning_rod": table["received_per_year"] >= th["received_per_year"],
        "negative_nancy": table["tone"] <= th["tone_low"],
        "bridge_builder": (table["cross_bloc_made"] >= MIN_CROSS_BLOC) & (table["tone_at_other_bloc"] >= th["tone_at_other_bloc"]),
        "defector": table["defected"] == 1,
        "rebel": table["rebel_rate"] >= th["rebel_rate"],
    }, index=table.index)
    rank = pd.DataFrame({
        "attack_dog": table["made_per_year"].rank(pct=True), "lightning_rod": table["received_per_year"].rank(pct=True),
        "negative_nancy": 1 - table["tone"].rank(pct=True) + 1 / len(table), "bridge_builder": table["tone_at_other_bloc"].rank(pct=True).fillna(0),
        "defector": pd.Series(TOP, index=table.index),  # wins only when the member has no stronger flag
        "rebel": table["rebel_rate"].rank(pct=True).fillna(0),
    }).where(flags, -1)
    table = table.copy()
    table["archetypes"] = [[a for a in ARCHETYPES if flags.at[i, a]] for i in table.index]
    table["primary"] = np.where(flags.any(axis=1), rank.idxmax(axis=1), "none")
    return table, flags, {k: round(v, 4) for k, v in th.items()}


def feature_matrix(table):
    x = table[list(FEATURES)].copy()
    for col in LOG_FEATURES:
        x[col] = np.log1p(x[col] * (1e4 if col == "betweenness" else 1))
    x["rebel_rate"] = x["rebel_rate"].fillna(0)
    x = x.fillna(x.median())
    return pd.DataFrame(StandardScaler().fit_transform(x), index=table.index, columns=x.columns)


def cluster(z, columns):
    """K-means for each k, chosen by silhouette; stability is the ARI between seeds."""
    data = z[columns].to_numpy()
    scores = {k: float(silhouette_score(data, KMeans(k, n_init=20, random_state=SEED).fit_predict(data))) for k in K_RANGE}
    best = max(scores, key=scores.get)
    runs = [KMeans(best, n_init=1, random_state=SEED + s).fit_predict(data) for s in range(N_SEEDS)]
    stability = np.mean([adjusted_rand_score(runs[i], runs[j]) for i in range(N_SEEDS) for j in range(i + 1, N_SEEDS)])
    labels = KMeans(best, n_init=50, random_state=SEED).fit_predict(data)
    return labels, {"k": best, "silhouette_by_k": {k: round(v, 3) for k, v in scores.items()},
                    "seed_stability_ari": round(float(stability), 3)}


def describe_clusters(table, z, labels):
    out = []
    for c in sorted(set(labels)):
        inside = labels == c
        centre = z[inside].mean()
        top = centre.abs().sort_values(ascending=False).head(4).index
        families = {f: round(float(centre[[k for k, v in FEATURES.items() if v[0] == f]].abs().mean()), 2)
                    for f in ["network", "tone", "career"]}
        members = table[inside].sort_values("made", ascending=False)
        out.append({"cluster": int(c), "size": int(inside.sum()),
                    "profile": {k: round(float(v), 2) for k, v in centre.items()},
                    "stands_out_on": [{"feature": k, "z": round(float(centre[k]), 2)} for k in top],
                    "mean_abs_z_by_family": families,
                    "parties": members["party"].value_counts().head(6).to_dict(),
                    "archetypes": Counter(members["primary"]).most_common(),
                    "examples": members["name"].head(6).tolist()})
    return out


def compare_with_rules(table, flags, labels):
    """For each archetype: the cluster holding most of its members, and how cleanly."""
    rows = {}
    for a in ARCHETYPES:
        members = flags[a].to_numpy()
        if members.sum() == 0:
            continue
        counts = Counter(labels[members])
        best, n = counts.most_common(1)[0]
        size = int((labels == best).sum())
        rows[a] = {"members": int(members.sum()), "best_cluster": int(best), "share_in_best": round(n / members.sum(), 2),
                   "best_cluster_purity": round(n / size, 2), "lift": round((n / size) / members.mean(), 1)}
    return rows


def archetype_profiles(table, z, flags):
    """Mean z of every measure for each archetype; measures used in the rule are marked, as they are circular."""
    out = {}
    for a, spec in ARCHETYPES.items():
        inside = flags[a]
        if inside.sum() == 0:
            continue
        centre = z[inside].mean()
        not_used = [k for k in FEATURES if k not in spec["uses"]]
        fam = {f: round(float(centre[[k for k in not_used if FEATURES[k][0] == f]].abs().mean()), 2)
               if [k for k in not_used if FEATURES[k][0] == f] else None for f in ["network", "tone", "career"]}
        out[a] = {"n": int(inside.sum()), "profile": {k: round(float(v), 2) for k, v in centre.items()},
                  "uses": spec["uses"], "beyond_rule_mean_abs_z": fam}
    return out


def overlaps(flags):
    """How many members hold both of two archetypes, and the Jaccard index."""
    out = []
    names = list(ARCHETYPES)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both, either = int((flags[a] & flags[b]).sum()), int((flags[a] | flags[b]).sum())
            out.append({"a": a, "b": b, "both": both, "jaccard": round(both / either, 2) if either else 0})
    return out


def tone_by_target(edges):
    """Challenge-level tone by who is targeted: is hostility aimed at the other bloc, own side or the government?"""
    known = edges[edges["floor_bloc"].notna() & edges["challenger_bloc"].notna()]
    groups = {
        "own party": edges["floor_party"] == edges["challenger_party"],
        "own bloc, other party": (known["floor_bloc"] == known["challenger_bloc"]) & (known["floor_party"] != known["challenger_party"]),
        "other bloc": known["floor_bloc"] != known["challenger_bloc"],
        "government, from opposition": edges["floor_in_government"] & ~edges["challenger_in_government"],
        "opposition, from government": ~edges["floor_in_government"] & edges["challenger_in_government"],
    }
    out = []
    for name, mask in groups.items():
        part = edges.loc[mask.reindex(edges.index, fill_value=False)]
        se = part["tone"].std() / np.sqrt(len(part))
        out.append({"target": name, "n": len(part), "mean_tone": round(float(part["tone"].mean()), 2),
                    "ci95": [round(float(part["tone"].mean() - 1.96 * se), 2), round(float(part["tone"].mean() + 1.96 * se), 2)],
                    "negative_share": round(float((part["afinn_raw"] < 0).mean()), 3)})
    return out


# ---------- words ----------

def word_counts(texts):
    counts = Counter()
    for text in texts:
        counts.update(re.findall(r"[a-zæøå]{3,}", text.lower()))
    return counts


def log_odds(focus, rest, prior, top=N_WORDS, min_count=40):
    """Monroe et al. log-odds with an informative Dirichlet prior: words typical of focus vs rest."""
    nf, nr = sum(focus.values()), sum(rest.values())
    scale, alpha0, rows = 500 / sum(prior.values()), 500, []
    for word, count in prior.items():
        if count < min_count:
            continue
        a = count * scale
        delta = (np.log((focus[word] + a) / (nf + alpha0 - focus[word] - a))
                 - np.log((rest[word] + a) / (nr + alpha0 - rest[word] - a)))
        rows.append((word, delta / np.sqrt(1 / (focus[word] + a) + 1 / (rest[word] + a))))
    rows.sort(key=lambda r: -r[1])
    return [(w, round(float(s), 1)) for w, s in rows[:top]]


def distinctive_words(edges, table):
    clean = name_remover()
    text = edges.assign(clean=edges["text"].fillna("").map(lambda t: clean(RITUAL.sub("", t))))
    counts = {p: word_counts(g) for p, g in text.groupby("challenger_person")["clean"]}
    prior = sum(counts.values(), Counter())
    party_of = table.set_index("person")["party"].to_dict()
    out = {}
    for a in ARCHETYPES:
        people = set(table.loc[table["archetypes"].map(lambda xs: a in xs), "person"])
        if not people:
            continue
        focus = sum((counts.get(p, Counter()) for p in people), Counter())
        # Archetypes are concentrated in a few parties, so words versus everyone partly show
        # party topics. Versus colleagues in the same parties isolates the archetype's style.
        parties = {party_of[p] for p in people}
        colleagues = [p for p in table["person"] if party_of[p] in parties and p not in people]
        rest = sum((counts.get(p, Counter()) for p in colleagues), Counter())
        out[a] = {"vs_everyone": log_odds(focus, prior - focus, prior),
                  "vs_same_party": log_odds(focus, rest, focus + rest, min_count=25)}
    return out


# ---------- parties and time ----------

def by_party(table):
    rows = []
    for party, group in table.groupby("party"):
        if len(group) < 3:
            continue
        rows.append({"party": party, "bloc": BLOC.get(party), "members": len(group),
                     **{a: sorted(group.loc[group["archetypes"].map(lambda xs: a in xs), "name"]) for a in ARCHETYPES}})
    return sorted(rows, key=lambda r: -r["members"])


def over_time(edges, speeches, windows):
    """Per government window: member rates and tone, the same top-10% rules, and what happens
    to members whose party enters or leaves government or who become ministers."""
    years = {w["name"]: max((pd.Timestamp(min(w["to"], "2026-11-01")) - pd.Timestamp(w["from"])).days / 365.25, 0.25) for w in windows}
    govt = {w["name"]: set(w["government"]) for w in windows}
    speeches = speeches.assign(window=window_of(speeches["date"], windows))
    minister = speeches[speeches["is_minister"]].groupby(["person", "window"]).size()
    received = edges[~edges["floor_is_minister"]].groupby(["floor_person", "window"]).size()
    rows = []
    for (person, window), made in edges[edges["challenger_party"].notna()].groupby(["challenger_person", "window"]):
        party = made["challenger_party"].mode().iloc[0]
        rows.append({"person": int(person), "window": window, "party": party, "made": len(made),
                     "made_per_year": len(made) / years[window],
                     "received_per_year": received.get((person, window), 0) / years[window],
                     "tone": float(made["tone"].mean()), "in_government": party in govt[window],
                     "minister": (person, window) in minister.index})
    frame = pd.DataFrame(rows)
    frame = frame[frame["made"] >= MIN_WINDOW_MADE].copy()
    for col, flag in [("made_per_year", "attack_dog"), ("received_per_year", "lightning_rod")]:
        frame[flag] = frame[col] >= frame.groupby("window")[col].transform(lambda s: s.quantile(TOP))
    frame["negative_nancy"] = frame["tone"] <= frame.groupby("window")["tone"].transform(lambda s: s.quantile(1 - TOP))
    order = [w["name"] for w in windows]
    frame["i"] = frame["window"].map(order.index)
    nxt = frame.merge(frame, on="person", suffixes=("", "_next"))
    nxt = nxt[nxt["i_next"] == nxt["i"] + 1]
    nxt["event"] = np.select(
        [~nxt["minister"] & nxt["minister_next"], ~nxt["in_government"] & nxt["in_government_next"],
         nxt["in_government"] & ~nxt["in_government_next"], ~nxt["in_government"] & ~nxt["in_government_next"]],
        ["became minister", "party entered government", "party left government", "stayed in opposition"],
        "stayed in government")
    events = []
    for event, g in nxt.groupby("event"):
        events.append({"event": event, "members": len(g),
                       "made_per_year_before": round(float(g["made_per_year"].median()), 1),
                       "made_per_year_after": round(float(g["made_per_year_next"].median()), 1),
                       "tone_before": round(float(g["tone"].mean()), 2), "tone_after": round(float(g["tone_next"].mean()), 2),
                       "attack_dogs_before": int(g["attack_dog"].sum()), "attack_dogs_after": int(g["attack_dog_next"].sum()),
                       "negative_nancies_before": int(g["negative_nancy"].sum()), "negative_nancies_after": int(g["negative_nancy_next"].sum())})
    per_window = frame.groupby("window").agg(members=("person", "size"), attack_dogs=("attack_dog", "sum"),
                                             lightning_rods=("lightning_rod", "sum"), negative_nancies=("negative_nancy", "sum"))
    stay = nxt.groupby("person")["attack_dog"].any()
    return {"events": sorted(events, key=lambda e: e["event"]),
            "per_window": {w: {k: int(v) for k, v in r.items()} for w, r in per_window.reindex(order).dropna().iterrows()},
            "members_followed": int(nxt["person"].nunique()),
            "attack_dog_kept_next_window": round(float(nxt.loc[nxt["attack_dog"], "attack_dog_next"].mean()), 2),
            "attack_dog_ever": int(stay.sum())}


# ---------- main ----------

def clean_json(value):
    if isinstance(value, float):
        return None if not np.isfinite(value) else round(value, 4)
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return clean_json(float(value))
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def main():
    windows = load_windows()
    speeches = load_speeches()
    names = pd.read_parquet(DATA / "members.parquet").set_index("person")["name"].to_dict()
    edges = challenge_tone(load_challenges(speeches, windows))
    print("challenges with tone", len(edges), flush=True)

    everyone = member_table(speeches, edges, names)
    table = everyone[everyone["made"] >= MIN_MADE].reset_index(drop=True)
    print("members profiled", len(table), "of", len(everyone), flush=True)
    table, flags, thresholds = assign_archetypes(table)
    z = feature_matrix(table)

    network_cols = [k for k, v in FEATURES.items() if v[0] == "network"]
    tone_cols = [k for k, v in FEATURES.items() if v[0] == "tone"]
    labels, fit = cluster(z, list(FEATURES))
    net_labels, net_fit = cluster(z, network_cols)
    tone_labels, tone_fit = cluster(z, tone_cols)
    table["cluster"] = labels
    primary_codes = table["primary"].astype("category").cat.codes
    print("clusters", fit, flush=True)

    edges_profiled = edges[edges["challenger_person"].isin(set(table["person"]))]
    result = {
        "status": "draft: tone not yet validated against hand labels; thresholds are first choices",
        "blocs": BLOC,
        "settings": {"min_made": MIN_MADE, "top": TOP, "min_cast_votes": MIN_CAST_VOTES, "ritual_removed": RITUAL.pattern},
        "features": {k: {"family": v[0], "label": v[1]} for k, v in FEATURES.items()},
        "archetypes": ARCHETYPES,
        "thresholds": thresholds,
        "counts": {"members_with_any_challenge": len(everyone), "members_profiled": len(table),
                   "challenges_scored": len(edges), "challenges_by_profiled": len(edges_profiled),
                   **{a: int(flags[a].sum()) for a in ARCHETYPES}, "none": int((~flags.any(axis=1)).sum()),
                   "more_than_one": int((flags.sum(axis=1) > 1).sum())},
        "tone_overall": {"mean": float(edges["tone"].mean()), "negative_share": float((edges["afinn_raw"] < 0).mean()),
                         "zero_share": float((edges["afinn_raw"] == 0).mean())},
        "clusters": {"all_measures": fit, "network_only": net_fit, "tone_only": tone_fit,
                     "ari_with_primary_archetype": {"all_measures": round(adjusted_rand_score(primary_codes, labels), 3),
                                                    "network_only": round(adjusted_rand_score(primary_codes, net_labels), 3),
                                                    "tone_only": round(adjusted_rand_score(primary_codes, tone_labels), 3)},
                     "ari_network_vs_tone": round(adjusted_rand_score(net_labels, tone_labels), 3),
                     "described": describe_clusters(table, z, labels),
                     "archetype_in_clusters": compare_with_rules(table, flags, labels)},
        "archetype_profiles": archetype_profiles(table, z, flags),
        "overlaps": overlaps(flags),
        "tone_by_target": tone_by_target(edges),
        "made_received_spearman": round(float(table["made_per_year"].corr(table["received_per_year"], method="spearman")), 3),
        "words": distinctive_words(edges_profiled, table),
        "by_party": by_party(table),
        "over_time": over_time(edges, speeches, windows),
        "members": table.drop(columns=["parties"]).assign(parties=table["parties"].map(lambda p: "→".join(p))).to_dict("records"),
    }
    OUT.write_text(json.dumps(clean_json(result), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(clean_json({k: result[k] for k in ["counts", "thresholds", "tone_overall"]}), ensure_ascii=False, indent=1))
    print(json.dumps(clean_json(result["clusters"]["archetype_in_clusters"]), indent=1))
    print(json.dumps(clean_json([result["overlaps"], result["tone_by_target"], result["made_received_spearman"]]), ensure_ascii=False))
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
