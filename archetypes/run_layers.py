"""Two member networks per government window, challenges (C) and committees (E), and DeepMoji
emotion for every challenge, for the site's layer explorer (Figures 5, 5b and 5c).

    python -m archetypes.run_layers            # download what is missing, then build everything
    python -m archetypes.run_layers --no-download   # fail instead of downloading

| Layer         | An edge means                                   | Edge property                     |
|---------------|-------------------------------------------------|-----------------------------------|
| C. Challenges | one member challenges another                   | count, tone: hostile/neutral/friendly |
| E. Committees | members share committee memberships             | shared committees (Jaccard)       |

Data. Everything raw comes from oda.ft.dk through tools/collect.py, which is throttled and
caches every response in data-raw/ (not committed). This script calls it for any step whose
output is missing, so a fresh clone needs only this one command:
    tables      persons, party groups, memberships, meetings, votes   (~10 min)
    committees  committee memberships per session                     (~5 min)
    debates     transcript XML over FTP, 1,878 files, 1.2 GB          (~1 h)
The speech table (data-raw/derived/speeches.parquet) is then built with the same functions as
tools/build_dataset.py, but this script never overwrites the committed data/ tables.

Layers the group built and dropped: A (voting) only redraws the party blocks, since members
almost never vote against their party (data/results/votes.json); B (language) and D (topics)
duplicate Part 3 of the site ("Talk alike", tools/analyze_similarity.py).

Sparsifying. E is a similarity layer: every pair has a value, so each member keeps their
K_NEIGHBOURS most similar members (a k-nearest-neighbour graph). C keeps the disparity
backbone the site already draws (tools/export_site.py), so its picture is unchanged.

Tone (C). DeepMoji (archetypes/deepmoji.py) gives each challenge a distribution over 64 emoji,
from an English translation of the challenger's words. Its sentiment is P(happy + love emoji)
minus P(anger + disapproval emoji): at or below -TONE_CUT the challenge is hostile, at or above
+TONE_CUT friendly, otherwise neutral. It is unvalidated until labeling/challenge_stance.csv is
labeled; this script reports agreement with that sheet, against always guessing the most
common label.

Writes data/layers.json (read by the site) and prints a short summary.
"""
import argparse
import json
import subprocess
import sys
import time

import community as community_louvain
import networkx as nx
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import normalized_mutual_info_score

from .config import DATA, RENAMES, ROOT, SEED

TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
RAW_TABLES = ROOT / "data-raw" / "tables"
XML_DIR = ROOT / "data-raw" / "oda_referat"
SPEECHES = ROOT / "data-raw" / "derived" / "speeches.parquet"
OUT_FILE = DATA / "layers.json"
STANCE_SHEET = ROOT / "labeling" / "challenge_stance.csv"

LAST_WINDOW_DRAWN = "2022 M+S+V"   # as on the site: 2026 is too short to draw
K_NEIGHBOURS = 5                   # edges kept per member in the similarity layers
TOP_LIST = 12                      # neighbours listed in the member panel
TONE_CUT = 0.10                    # C: |DeepMoji sentiment| at or above this is not neutral
NOT_A_PARTY = {"Pause", "MødeSlut", None}

LAYERS = {
    "C": {"name": "Challenges", "edge": "One member challenges another", "property": "Hostility, neutrality, friendliness"},
    "E": {"name": "Committees", "edge": "Members share committee memberships", "property": "Shared membership"},
}

sys.stdout.reconfigure(encoding="utf-8")


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


# ---------------------------------------------------------------- data

def ensure_raw(download):
    """Run tools/collect.py for every step whose output is missing."""
    needed = {
        "tables": RAW_TABLES / "memberships.json",
        "committees": RAW_TABLES / "committee_memberships.json",
        "debates": XML_DIR,
    }
    missing = [step for step, path in needed.items()
               if not path.exists() or (path.is_dir() and not any(path.rglob("*.xml")))]
    if not missing:
        return
    if not download:
        raise SystemExit(f"Missing raw data for: {', '.join(missing)}. Run without --no-download, "
                         f"or: python tools/collect.py {' '.join(missing)}")
    log("downloading", missing, "(throttled and cached; see tools/collect.py)")
    subprocess.run([sys.executable, str(TOOLS / "collect.py"), *missing], check=True, cwd=ROOT)


def load_speeches():
    """Every member turn with its person and party, built like tools/build_dataset.py (cached)."""
    if not SPEECHES.exists():
        from build_dataset import Resolver, add_people, build_speeches, load
        log("building", SPEECHES.name, "from the transcripts (a few minutes)")
        resolver = Resolver(load("persons"), load("party_groups"), load("memberships"), load("sessions"))
        frame = add_people(build_speeches(), resolver)
        SPEECHES.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(SPEECHES)
    frame = pd.read_parquet(SPEECHES, columns=["session", "meeting", "turn", "date", "person", "party",
                                               "is_chair", "is_person"])
    frame = frame[frame["is_person"] & ~frame["is_chair"] & frame["person"].notna()].copy()
    frame["person"] = frame["person"].astype(int)
    frame["party"] = frame["party"].replace(RENAMES)
    return frame.drop(columns=["is_chair", "is_person"])


class Members:
    """Who sat in parliament in a window, their party and their government side."""

    def __init__(self, speeches, windows):
        from build_dataset import Resolver, load
        self.resolver = Resolver(load("persons"), load("party_groups"), load("memberships"), load("sessions"))
        self.windows = {w["name"]: w for w in windows}
        self.sessions = {}
        self.speech_party = {}
        for w in windows:
            part = speeches[(speeches["date"] >= w["from"]) & (speeches["date"] < w["to"])]
            self.sessions[w["name"]] = sorted(part["session"].unique())
            parties = part[~part["party"].isin(NOT_A_PARTY)].groupby("person")["party"].agg(lambda s: s.mode().iloc[0])
            self.speech_party[w["name"]] = parties.to_dict()

    def seated(self, window):
        return set().union(*(self.resolver.seated.get(s, set()) for s in self.sessions[window]))

    def party(self, person, window):
        found = self.speech_party[window].get(person)
        if found is None:
            for session in self.sessions[window]:
                found = self.resolver.party(person, session, self.windows[window]["from"]) \
                    or self.resolver.nearest_party(person, session)
                if found:
                    break
        return RENAMES.get(found, found)

    def side(self, party, window):
        return "government" if party in self.windows[window]["government"] else "opposition"

    def name(self, person):
        return self.resolver.names.get(person, str(person))


# ---------------------------------------------------------------- E: committees

def committee_similarity(seats, window_sessions, seated):
    """E: Jaccard overlap of the committees two members sat on in the window."""
    part = seats[seats["session"].isin(window_sessions) & seats["person"].isin(seated)]
    names = sorted(part["committee"].unique())
    people = np.array(sorted(part["person"].unique()))
    if len(people) < 3:
        return None
    m = pd.crosstab(part["person"], part["committee"]).reindex(index=people, columns=names).clip(upper=1).to_numpy(np.float32)
    shared = m @ m.T
    size = m.sum(axis=1)
    sim = shared / (size[:, None] + size[None, :] - shared)
    return people, sim, {"committees": names, "member_of": {p: np.flatnonzero(row).tolist() for p, row in zip(people.tolist(), m)},
                         "shared": shared}


# ---------------------------------------------------------------- graphs

def knn_graph(people, sim, k=K_NEIGHBOURS, seed=SEED):
    """Each member's k most similar members; ties broken at random."""
    s = np.where(np.isfinite(sim), sim, -np.inf).astype(float)
    np.fill_diagonal(s, -np.inf)
    jitter = np.random.default_rng(seed).uniform(0, 1e-9, s.shape)
    order = np.argsort(-(s + jitter), axis=1)
    g = nx.Graph()
    g.add_nodes_from(people.tolist())
    for i, row in enumerate(order[:, :k]):
        for j in row:
            if np.isfinite(s[i, j]):
                g.add_edge(int(people[i]), int(people[j]), weight=float(s[i, j]))
    return g, order[:, :TOP_LIST], s


def layout(g):
    """Spring layout of the largest connected part; small fragments are left to the search."""
    giant = g.subgraph(max(nx.connected_components(g), key=len)) if g.number_of_edges() else g
    return nx.spring_layout(giant, seed=SEED, weight=None, k=1.6 / np.sqrt(max(len(giant), 2)), iterations=300)


def graph_stats(g, party, side):
    """Louvain communities and how much party and government side explain the graph."""
    h = nx.Graph()
    h.add_nodes_from(g.nodes)
    h.add_edges_from((a, b, {"weight": max(d.get("weight", 1.0), 1e-3)}) for a, b, d in g.edges(data=True))
    h.remove_nodes_from([n for n in list(h) if h.degree(n) == 0])
    partition = community_louvain.best_partition(h, random_state=SEED)
    nodes = list(partition)
    nx.set_node_attributes(h, {n: side.get(n, "?") for n in h}, "side")
    nx.set_node_attributes(h, {n: party.get(n, "?") for n in h}, "party")
    return {"members": h.number_of_nodes(), "edges": h.number_of_edges(),
            "communities": len(set(partition.values())),
            "modularity": round(community_louvain.modularity(partition, h), 3),
            "nmi_party": round(normalized_mutual_info_score([party.get(n, "?") for n in nodes], [partition[n] for n in nodes]), 3),
            "assort_party": round(nx.attribute_assortativity_coefficient(h, "party"), 3),
            "assort_side": round(nx.attribute_assortativity_coefficient(h, "side"), 3)}


def similarity_layer(result, window, members, fmt=3, extra=None):
    """Nodes, kNN edges, layout and stats for one similarity layer in one window."""
    people, sim, info = result
    g, top, s = knn_graph(people, sim)
    pos = layout(g)
    party = {int(p): members.party(int(p), window) for p in people}
    side = {p: members.side(v, window) for p, v in party.items()}
    nodes = []
    for i, p in enumerate(people.tolist()):
        xy = pos.get(p)
        node = {"id": p, "name": members.name(p), "party": party[p], "side": side[p],
                "top": [[int(people[j]), round(float(s[i, j]), fmt)] for j in top[i] if np.isfinite(s[i, j])],
                "x": round(float(xy[0]), 3) if xy is not None else None,
                "y": round(float(xy[1]), 3) if xy is not None else None}
        if extra:
            node.update(extra(p, i))
        nodes.append(node)
    edges = [[a, b, round(d["weight"], fmt)] for a, b, d in g.edges(data=True)]
    return {"nodes": nodes, "edges": edges, "drawn": len(pos), "stats": graph_stats(g, party, side)}


# ---------------------------------------------------------------- C: challenges with tone

def score_tone(edges):
    """DeepMoji emotion of each challenge (archetypes/deepmoji.py), joined on (session, meeting, turn)."""
    from . import deepmoji
    if not deepmoji.OUT_FILE.exists():
        log("C: no DeepMoji scores yet, running archetypes.deepmoji (translation + scoring)")
        deepmoji.main([])
    emoji = pd.read_parquet(deepmoji.OUT_FILE)
    joined = edges.merge(emoji, on=["session", "meeting", "turn"], how="left")
    score = joined["sentiment"]
    joined["tone"] = np.select([score <= -TONE_CUT, score >= TONE_CUT, score.notna()],
                               ["hostile", "friendly", "neutral"], default="unknown")
    check = {"edges": len(joined), "scored": round(float(score.notna().mean()), 4)}
    return joined, check


def emoji_summary(scored, windows):
    """What the site plots: emoji shares, emotion groups, and the sentiment distribution."""
    from .deepmoji import EMOJI_ALIASES, EMOJI_NAMES, GROUPS
    import emoji as emoji_lib
    part = scored[scored["sentiment"].notna() & (scored["challenger_person"] != scored["floor_person"])]
    part = part[part["window"].isin([w["name"] for w in windows])]
    top1 = part[EMOJI_NAMES].to_numpy().argmax(axis=1)
    bins = np.round(np.arange(-0.8, 0.81, 0.04), 2)
    gov = {w["name"]: set(w["government"]) for w in windows}
    at_gov = np.array([f in gov[w] or m for f, w, m in zip(part["floor_party"], part["window"], part["floor_is_minister"])])

    def hist(values):
        return np.histogram(np.clip(values, bins[0], bins[-1] - 1e-9), bins=bins)[0].tolist()

    by_window = {}
    for w in windows:
        sub = part[part["window"] == w["name"]]
        by_window[w["name"]] = {g: round(float(sub[g].mean()), 4) for g in GROUPS} | {"challenges": len(sub)}
    return {
        "emoji": [emoji_lib.emojize(a, language="alias") for a in EMOJI_ALIASES],
        "names": EMOJI_NAMES,
        "groups": {g: [EMOJI_NAMES.index(n) for n in names] for g, names in GROUPS.items()},
        "challenges": len(part),
        "mean_prob": part[EMOJI_NAMES].mean().round(4).tolist(),
        "top1_count": np.bincount(top1, minlength=len(EMOJI_NAMES)).tolist(),
        "bins": bins.tolist(),
        "hist_all": hist(part["sentiment"]),
        "hist_at_government": hist(part.loc[at_gov, "sentiment"]),
        "hist_at_opposition": hist(part.loc[~at_gov, "sentiment"]),
        "mean_at_government": round(float(part.loc[at_gov, "sentiment"].mean()), 4),
        "mean_at_opposition": round(float(part.loc[~at_gov, "sentiment"].mean()), 4),
        "groups_by_window": by_window,
    }


def stance_check(scored):
    """Agreement with the group's hand labels, once labeling/challenge_stance.csv is filled in."""
    if not STANCE_SHEET.exists():
        return {"status": "no sheet"}
    sheet = pd.read_csv(STANCE_SHEET, encoding="utf-8-sig")
    sheet["label"] = sheet["stance_hostile_neutral_friendly"].astype(str).str.strip().str.lower()
    sheet = sheet[sheet["label"].isin(["hostile", "neutral", "friendly"])]
    if sheet.empty:
        return {"status": "not labeled yet"}
    # The sheet's turn is the challenger's turn (tools/make_labeling_sheets.py), as in challenges.parquet.
    sheet["session"] = sheet["session"].astype(str)
    both = sheet.merge(scored, on=["session", "meeting", "turn"])
    both = both[both["tone"] != "unknown"]
    if both.empty:
        return {"status": "labeled", "rows": 0}
    majority = both["label"].value_counts().idxmax()
    tones = ["hostile", "neutral", "friendly"]
    confusion = pd.crosstab(both["label"], both["tone"]).reindex(index=tones, columns=tones, fill_value=0)
    # The categories can fail while the score still ranks remarks sensibly, so check both.
    from sklearn.metrics import roc_auc_score
    hostile = (both["label"] == "hostile").astype(int)
    order = both["label"].map({"hostile": -1, "neutral": 0, "friendly": 1})
    rho = spearmanr(order, both["sentiment"])
    return {"status": "labeled", "rows": len(both),
            "auc_hostile": round(float(roc_auc_score(hostile, -both["sentiment"])), 3) if 0 < hostile.sum() < len(both) else None,
            "spearman": round(float(rho.statistic), 3), "spearman_p": round(float(rho.pvalue), 4),
            "label_means": both.groupby("label")["sentiment"].mean().round(3).to_dict(),
            "accuracy": round(float((both["label"] == both["tone"]).mean()), 3),
            "majority_label": majority, "majority_baseline": round(float((both["label"] == majority).mean()), 3),
            "hostile_recall": round(float((both.loc[both["label"] == "hostile", "tone"] == "hostile").mean()), 3)
            if (both["label"] == "hostile").any() else None,
            "confusion": {"rows_hand_label": tones, "cols_deepmoji": tones, "counts": confusion.to_numpy().tolist()}}


def challenge_layer(scored, window, names, by_window, members):
    from export_site import window_network
    part = scored[scored["window"] == window]
    net = window_network(part, window, names, by_window)
    pairs = part[part["challenger_person"] != part["floor_person"]]
    made = pairs.groupby(["challenger_person", "tone"]).size().unstack(fill_value=0)
    pair_tone = pairs.assign(a=pairs[["challenger_person", "floor_person"]].min(axis=1),
                             b=pairs[["challenger_person", "floor_person"]].max(axis=1)) \
        .groupby(["a", "b", "tone"]).size().unstack(fill_value=0)
    get = lambda table, key, col: int(table.at[key, col]) if key in table.index and col in table.columns else 0
    from .deepmoji import EMOJI_NAMES
    # Each member's most typical emoji: mean DeepMoji probability over their challenges, relative
    # to the window's mean, so 😂 (the model's default answer) does not top every list.
    probs = pairs.dropna(subset=["sentiment"])
    lift = probs.groupby("challenger_person")[EMOJI_NAMES].mean() / probs[EMOJI_NAMES].mean()
    n_scored = probs.groupby("challenger_person").size()
    typical = {p: [int(i) for i in np.argsort(-row.to_numpy())[:3]] for p, row in lift[n_scored.reindex(lift.index) >= 10].iterrows()}
    nodes = []
    for n in net["nodes"]:
        nodes.append({"id": n["id"], "name": n["name"], "party": n["party"], "side": n["side"], "x": n["x"], "y": n["y"],
                      "made": n["made"], "received": n["received"], "out": n["challenged"], "in": n["challenged_by"],
                      "tone": [get(made, n["id"], t) for t in ("hostile", "neutral", "friendly")],
                      "emoji": typical.get(n["id"], [])})
    edges = []
    for a, b, w in net["edges"]:
        key = (min(a, b), max(a, b))
        edges.append([a, b, w, [get(pair_tone, key, t) for t in ("hostile", "neutral", "friendly")]])
    g = nx.Graph()
    g.add_weighted_edges_from((a, b, w) for a, b, w, _ in edges)
    party = {n["id"]: n["party"] for n in nodes}
    side = {n["id"]: n["side"] for n in nodes}
    return {"nodes": nodes, "edges": edges, "drawn": net["members_drawn"], "edges_all": net["edges_all"],
            "stats": graph_stats(g, party, side),
            "tone_counts": {t: int((pairs["tone"] == t).sum()) for t in ("hostile", "neutral", "friendly", "unknown")}}


def challenge_matrix(scored, window, people):
    part = scored[(scored["window"] == window) & (scored["challenger_person"] != scored["floor_person"])]
    index = pd.Series(np.arange(len(people)), index=people)
    part = part[part["challenger_person"].isin(index.index) & part["floor_person"].isin(index.index)]
    m = np.zeros((len(people), len(people)))
    np.add.at(m, (index[part["challenger_person"]].to_numpy(), index[part["floor_person"]].to_numpy()), 1)
    return m + m.T


# ---------------------------------------------------------------- main

def layer_correlations(matrices):
    """Spearman correlation between layers over all pairs of members present in every layer."""
    names = [k for k, v in matrices.items() if v is not None]
    common = sorted(set.intersection(*(set(matrices[k][0].tolist()) for k in names)))
    if len(common) < 10:
        return None
    iu = np.triu_indices(len(common), 1)
    vectors = {}
    for k in names:
        people, sim = matrices[k]
        idx = pd.Series(np.arange(len(people)), index=people)[common].to_numpy()
        vectors[k] = sim[np.ix_(idx, idx)][iu]
    out = [[None] * len(names) for _ in names]
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            ok = np.isfinite(vectors[a]) & np.isfinite(vectors[b])
            out[i][j] = 1.0 if a == b else round(float(spearmanr(vectors[a][ok], vectors[b][ok]).statistic), 3)
    return {"layers": names, "members": len(common), "pairs": int(len(iu[0])), "rho": out}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-download", action="store_true", help="fail instead of downloading missing raw data")
    args = parser.parse_args(argv)

    ensure_raw(not args.no_download)
    from analyze_network import clean_edges, load_windows, window_of

    all_windows = load_windows()
    windows = [w for w in all_windows if w["name"] <= LAST_WINDOW_DRAWN]
    log("loading speeches")
    speeches = load_speeches()
    speeches["window"] = window_of(speeches["date"], all_windows)
    speeches = speeches[speeches["window"].notna()].reset_index(drop=True)
    members = Members(speeches, windows)
    log(f"{len(speeches):,} member turns")

    log("C: DeepMoji tone")
    edges = clean_edges(all_windows)
    scored, tone_info = score_tone(edges)
    tone_info["hand_labels"] = stance_check(scored)
    seats = pd.DataFrame(json.loads((RAW_TABLES / "committee_memberships.json").read_text(encoding="utf-8")))
    names = pd.read_parquet(DATA / "members.parquet").set_index("person")["name"].to_dict()
    by_window = json.loads((DATA / "results" / "network.json").read_text(encoding="utf-8"))["by_window"]

    out = {"layers": LAYERS, "windows": [w["name"] for w in windows],
           "settings": {"k_neighbours": K_NEIGHBOURS, "tone_cut": TONE_CUT},
           "tone": tone_info, "emoji": emoji_summary(scored, windows), "committees": {}, "correlations": {}, "networks": {k: {} for k in LAYERS}}
    for w in windows:
        name = w["name"]
        seated = members.seated(name)
        log("window", name)
        results = {"E": committee_similarity(seats, members.sessions[name], seated)}
        # Restrict each matrix to members seated in the window (ministers without a seat drop out).
        for k, r in list(results.items()):
            if r is None:
                continue
            people, sim, info = r
            mask = np.array([int(p) in seated for p in people])
            results[k] = (people[mask], sim[np.ix_(mask, mask)], info) if mask.sum() >= 3 else None

        if results["E"]:
            info = results["E"][2]
            out["committees"][name] = info["committees"]
            out["networks"]["E"][name] = similarity_layer(results["E"], name, members,
                                                          extra=lambda p, i: {"member_of": info["member_of"][p]})
        out["networks"]["C"][name] = challenge_layer(scored, name, names, by_window, members)

        c_people = np.array(sorted({n["id"] for n in out["networks"]["C"][name]["nodes"]} & seated))
        matrices = {k: (r[0], r[1]) if r else None for k, r in results.items()}
        matrices["C"] = (c_people, challenge_matrix(scored, name, c_people))
        out["correlations"][name] = layer_correlations({k: matrices[k] for k in "CE"})
        for k in "CE":
            if name in out["networks"][k]:
                log(f"  {k}", out["networks"][k][name]["stats"])

    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log("wrote", OUT_FILE.relative_to(ROOT), round(OUT_FILE.stat().st_size / 1e6, 2), "MB")
    log("tone", json.dumps(tone_info))


if __name__ == "__main__":
    main()
