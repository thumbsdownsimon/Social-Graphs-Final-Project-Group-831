#!/usr/bin/env python3
"""Do members challenge the people who talk like them?

    python tools/analyze_similarity.py                 # about 10 minutes
    python tools/analyze_similarity.py --shuffles 200  # quicker

Writes data/results/similarity.json. Per government window:

1. A language profile per member, from their backbench speech with names of people and parties
   removed (the same cleaning as tools/analyze_language.py). Two methods:
     tfidf      TF-IDF over each member's words, cosine between members
     embedding  mean of the member's sentence-embedding vectors from analyze_language.py's cache
2. For every pair of members: how alike they talk, and how often they challenged each other,
   against two expectations:
     window  out_i * in_j / N over the whole window: activity alone (a directed configuration model)
     debate  the same, summed debate by debate: who was in the room and who held the floor
   If similar pairs beat the window expectation, conflict follows shared topics ("turf"). If they
   also beat the debate expectation, similar members pick each other out even inside a debate.
   The trend is tested by shuffling similarity among pairs of the same kind (same party or not)
   in the same window.
3. A language network (each member linked to the K most similar members), its Louvain
   communities, and how they line up with party, government side and the challenge network's
   own communities (NMI), against shuffled labels.
4. A map: t-SNE of the embedding profiles, for the site, with each member's closest language
   neighbours and most frequent challenge partners.
"""
import argparse
import json
import sys
from pathlib import Path

import community as louvain
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.manifold import TSNE
from sklearn.metrics import normalized_mutual_info_score as nmi

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_language import embed_speakers, load_speech, name_remover
from analyze_network import DATA, RESULTS, SEED, load_windows, window_of
from analyze_settings import without_nan

MIN_WORDS_MEMBER = 5000    # a member needs this much backbench speech in a window to get a profile
MAX_WORDS_MEMBER = 60000   # longer profiles are sampled down to this, so prolific members do not dominate
K_NEIGHBOURS = 8
N_BINS = 5
N_LOUVAIN_SEEDS = 10
MIN_WINDOW_CHALLENGES = 1000  # windows thinner than this are skipped

sys.stdout.reconfigure(encoding="utf-8")


def profiles(frame, rng):
    """One document per (window, person): their cleaned speech, sampled to MAX_WORDS_MEMBER."""
    rows = []
    for (window, person), group in frame.groupby(["window", "person"]):
        words = group["words"].sum()
        if words < MIN_WORDS_MEMBER:
            continue
        texts = group["clean"].tolist()
        if words > MAX_WORDS_MEMBER:
            order = rng.permutation(len(texts))
            kept, total = [], 0
            for i in order:
                kept.append(texts[i])
                total += group["words"].iloc[i]
                if total >= MAX_WORDS_MEMBER:
                    break
            texts = kept
        rows.append({"window": window, "person": int(person), "party": group["party"].mode().iloc[0],
                     "words": int(words), "text": " ".join(texts)})
    return pd.DataFrame(rows)


def cosine(matrix):
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    unit = matrix / np.where(norms == 0, 1, norms)
    return unit @ unit.T


def tfidf_similarity(docs):
    vectorizer = TfidfVectorizer(min_df=5, max_df=0.5, sublinear_tf=True)
    x = vectorizer.fit_transform(docs["text"])
    return (x @ x.T).toarray()


def challenge_tables(window_edges, people):
    """Observed counts and both expectations, as dense matrices over `people` (directed i -> j)."""
    index = {p: i for i, p in enumerate(people)}
    n = len(people)
    observed = np.zeros((n, n))
    debate = np.zeros((n, n))
    e = window_edges[window_edges["challenger_person"].isin(index) & window_edges["floor_person"].isin(index)]
    for (c, f), count in e.groupby(["challenger_person", "floor_person"]).size().items():
        observed[index[c], index[f]] = count
    out_w = observed.sum(axis=1)
    in_w = observed.sum(axis=0)
    window = np.outer(out_w, in_w) / max(observed.sum(), 1)
    for _, d in e.groupby("debate"):
        o = d["challenger_person"].map(index).value_counts()
        r = d["floor_person"].map(index).value_counts()
        debate[np.ix_(o.index, r.index)] += np.outer(o.values, r.values) / len(d)
    for m in (observed, debate, window):
        np.fill_diagonal(m, 0)
    return observed, debate, window


def pair_frame(window, people, parties, sims, observed, debate, windowexp):
    iu = np.triu_indices(len(people), k=1)
    frame = pd.DataFrame({"window": window, "a": np.array(people)[iu[0]], "b": np.array(people)[iu[1]],
                          "same_party": np.array(parties)[iu[0]] == np.array(parties)[iu[1]],
                          "observed": (observed + observed.T)[iu], "exp_debate": (debate + debate.T)[iu],
                          "exp_window": (windowexp + windowexp.T)[iu]})
    for name, s in sims.items():
        frame[name] = s[iu]
        # Rank within window and kind of pair, so bins mean "among comparable pairs".
        frame[name + "_bin"] = frame.groupby("same_party")[name].transform(
            lambda v: np.minimum((v.rank(pct=True) * N_BINS).astype(int), N_BINS - 1))
    return frame


def binned(pairs, method):
    rows = []
    for (same, b), g in pairs.groupby(["same_party", method + "_bin"]):
        rows.append({"same_party": bool(same), "bin": int(b), "pairs": len(g), "observed": int(g["observed"].sum()),
                     "ratio_window": round(g["observed"].sum() / g["exp_window"].sum(), 3),
                     "ratio_debate": round(g["observed"].sum() / g["exp_debate"].sum(), 3) if g["exp_debate"].sum() > 0 else None,
                     "mean_similarity": round(float(g[method].mean()), 4)})
    return rows


def lift(pairs, method, expectation):
    """Ratio to expectation in the most similar fifth, divided by that in the least similar fifth."""
    top = pairs[pairs[method + "_bin"] == N_BINS - 1]
    bottom = pairs[pairs[method + "_bin"] == 0]
    r_top = top["observed"].sum() / top[expectation].sum()
    r_bottom = bottom["observed"].sum() / bottom[expectation].sum()
    return float(r_top / r_bottom) if r_bottom > 0 else float("nan")


def lift_test(pairs, method, expectation, n, seed):
    """Null: shuffle the similarity bins among pairs of the same window and kind."""
    rng = np.random.default_rng(seed)
    observed = lift(pairs, method, expectation)
    groups = pairs.groupby(["window", "same_party"]).indices
    bins = pairs[method + "_bin"].to_numpy().copy()
    null = []
    shuffled = pairs[[method + "_bin", "observed", expectation]].copy()
    for _ in range(n):
        for idx in groups.values():
            bins[idx] = rng.permutation(bins[idx])
        shuffled[method + "_bin"] = bins
        null.append(lift(shuffled, method, expectation))
        bins = pairs[method + "_bin"].to_numpy().copy()
    null = np.array(null)
    return {"lift": round(observed, 3), "null_mean": round(float(null.mean()), 3), "null_sd": round(float(null.std()), 3),
            "p_one_sided": round(float((null >= observed).mean()), 4)}


def knn_graph(sim, people, k=K_NEIGHBOURS):
    g = nx.Graph()
    g.add_nodes_from(people)
    for i, p in enumerate(people):
        order = np.argsort(-sim[i])
        for j in [j for j in order if j != i][:k]:
            g.add_edge(p, people[j], weight=float(sim[i, j]))
    return g


def best_partition(g, seed):
    parts = [louvain.best_partition(g, weight="weight", random_state=seed + s) for s in range(N_LOUVAIN_SEEDS)]
    q = [louvain.modularity(p, g, weight="weight") for p in parts]
    best = parts[int(np.argmax(q))]
    nodes = list(g.nodes)
    stability = [nmi([parts[a][v] for v in nodes], [parts[b][v] for v in nodes])
                 for a in range(len(parts)) for b in range(a + 1, len(parts))]
    return best, float(max(q)), float(np.mean(stability))


def community_comparison(people, parties, sides, sim, observed, seed):
    rng = np.random.default_rng(seed)
    lang, q_lang, stab_lang = best_partition(knn_graph(sim, people), seed)
    cg = nx.Graph()
    cg.add_nodes_from(people)
    sym = observed + observed.T
    for i, j in zip(*np.nonzero(np.triu(sym, 1))):
        cg.add_edge(people[i], people[j], weight=float(sym[i, j]))
    chal, q_chal, stab_chal = best_partition(cg, seed)
    a = [lang[p] for p in people]
    c = [chal[p] for p in people]
    shuffled_party = [nmi(a, rng.permutation(parties)) for _ in range(200)]
    return {"language_communities": len(set(a)), "language_modularity": round(q_lang, 3), "language_stability_nmi": round(stab_lang, 3),
            "challenge_communities": len(set(c)), "challenge_modularity": round(q_chal, 3), "challenge_stability_nmi": round(stab_chal, 3),
            "nmi_language_party": round(nmi(a, parties), 3), "nmi_language_party_null": round(float(np.mean(shuffled_party)), 3),
            "nmi_language_side": round(nmi(a, sides), 3), "nmi_challenge_party": round(nmi(c, parties), 3),
            "nmi_language_challenge": round(nmi(a, c), 3),
            "nmi_language_challenge_null": round(float(np.mean([nmi(a, rng.permutation(c)) for _ in range(200)])), 3)}, lang


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shuffles", type=int, default=1000)
    args = parser.parse_args()
    rng = np.random.default_rng(SEED)

    windows = load_windows()
    frame = load_speech(windows)
    clean = name_remover()
    frame["clean"] = frame["text"].map(clean)
    print("speech loaded and cleaned", len(frame), flush=True)

    meta, vectors, _ = embed_speakers(frame)
    meta = meta.reset_index(drop=True)
    print("embeddings loaded", vectors.shape, flush=True)

    docs = profiles(frame, rng)
    members = pd.read_parquet(DATA / "members.parquet").set_index("person")["name"].to_dict()
    edges = pd.read_parquet(DATA / "challenges.parquet")
    edges = edges[~edges["floor_is_minister"] & ~edges["challenger_is_minister"]
                  & edges["floor_person"].notna() & edges["challenger_person"].notna()].copy()
    edges["floor_person"] = edges["floor_person"].astype(int)
    edges["challenger_person"] = edges["challenger_person"].astype(int)
    edges["window"] = window_of(edges["date"], windows)
    edges["debate"] = edges["session"] + "|" + edges["meeting"].astype(str) + "|" + edges["item"].astype(str)

    all_pairs, per_window, points, rivals = [], [], [], []
    for w in windows:
        name = w["name"]
        part = docs[docs["window"] == name].reset_index(drop=True)
        window_edges = edges[edges["window"] == name]
        if len(window_edges) < MIN_WINDOW_CHALLENGES or len(part) < 30:
            print("skip", name, len(window_edges), len(part), flush=True)
            continue
        # Embedding profile: mean of the member's debate vectors in this window.
        mw = meta[meta["window"] == name]
        emb = []
        for p in part["person"]:
            idx = mw.index[mw["person"] == p]
            emb.append(vectors[idx].mean(axis=0) if len(idx) else np.full(vectors.shape[1], np.nan))
        emb = np.vstack(emb)
        has_emb = ~np.isnan(emb).any(axis=1)
        part = part[has_emb].reset_index(drop=True)
        emb = emb[has_emb]
        people = part["person"].tolist()
        parties = part["party"].tolist()
        sides = ["government" if p in w["government"] else "opposition" for p in parties]
        sims = {"tfidf": tfidf_similarity(part), "embedding": cosine(emb)}
        observed, debate, windowexp = challenge_tables(window_edges, people)
        pairs = pair_frame(name, people, parties, sims, observed, debate, windowexp)
        all_pairs.append(pairs)
        comparison, lang = community_comparison(people, parties, sides, sims["embedding"], observed, SEED)
        per_window.append({"window": name, "members": len(people), "challenges_among_them": int(observed.sum()),
                           "challenges_in_window": int(len(window_edges)), **comparison})
        coords = TSNE(n_components=2, perplexity=min(30, len(people) // 4), init="pca", metric="cosine",
                      random_state=SEED).fit_transform(emb)
        sym = observed + observed.T
        for i, p in enumerate(people):
            near = [j for j in np.argsort(-sims["embedding"][i]) if j != i][:5]
            partners = [j for j in np.argsort(-sym[i]) if sym[i, j] > 0][:5]
            points.append({"window": name, "person": p, "name": members.get(p, str(p)), "party": parties[i], "side": sides[i],
                           "x": round(float(coords[i, 0]), 2), "y": round(float(coords[i, 1]), 2), "words": int(part["words"][i]),
                           "community": int(lang[p]), "made": int(observed[i].sum()), "received": int(observed[:, i].sum()),
                           "near": [[people[j], round(float(sims["embedding"][i, j]), 3)] for j in near],
                           "partners": [[people[j], int(sym[i, j])] for j in partners]})
        cross = pairs[~pairs["same_party"] & (pairs["observed"] >= 8)].copy()
        cross["ratio"] = cross["observed"] / cross["exp_window"]
        for _, r in cross.sort_values("observed", ascending=False).head(8).iterrows():
            rivals.append({"window": name, "a": members.get(int(r["a"]), str(r["a"])), "b": members.get(int(r["b"]), str(r["b"])),
                           "party_a": parties[people.index(int(r["a"]))], "party_b": parties[people.index(int(r["b"]))],
                           "challenges": int(r["observed"]), "expected_window": round(float(r["exp_window"]), 1),
                           "expected_debate": round(float(r["exp_debate"]), 1),
                           "similarity_percentile": round(float(pairs.loc[~pairs["same_party"], "embedding"].lt(r["embedding"]).mean()), 2)})
        print("window", name, len(people), "members", int(observed.sum()), "challenges", flush=True)

    pairs = pd.concat(all_pairs, ignore_index=True)
    cross = pairs[~pairs["same_party"]]
    results = {"settings": {"min_words_member": MIN_WORDS_MEMBER, "max_words_member": MAX_WORDS_MEMBER, "k_neighbours": K_NEIGHBOURS,
                            "bins": N_BINS, "shuffles": args.shuffles, "ministers": "excluded on both ends"},
               "pairs": len(pairs), "cross_party_pairs": len(cross), "windows": per_window,
               "bins": {m: binned(pairs, m) for m in ["tfidf", "embedding"]},
               "tests": {m: {exp: lift_test(cross, m, exp, args.shuffles, SEED + i)
                             for i, exp in enumerate(["exp_window", "exp_debate"])} for m in ["tfidf", "embedding"]},
               "tests_same_party": {m: {exp: lift_test(pairs[pairs["same_party"]], m, exp, args.shuffles, SEED + 7 + i)
                                        for i, exp in enumerate(["exp_window", "exp_debate"])} for m in ["tfidf", "embedding"]},
               "method_agreement_spearman": round(float(pairs[["tfidf", "embedding"]].corr(method="spearman").iloc[0, 1]), 3),
               "rivals": rivals, "points": points}
    RESULTS.mkdir(parents=True, exist_ok=True)
    # NaN is not valid JSON and would stop the page loading (same guard as analyze_settings.py).
    (RESULTS / "similarity.json").write_text(json.dumps(without_nan(results), ensure_ascii=False, indent=1, default=str, allow_nan=False), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
