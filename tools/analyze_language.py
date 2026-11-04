#!/usr/bin/env python3
"""Step 5 of the pipeline: do two parties' members sound more alike after joining a government?

    python tools/analyze_language.py

Writes data/results/language.json. Three measurements on backbench speech (no chair, no
ministers), all with names of people and parties removed:

  distinguishability  how well a classifier tells two parties apart on speakers it has not
                      seen. TF-IDF + logistic regression, against shuffled party labels.
  same-debate distance  sentence-embedding similarity of two parties' speakers in the SAME
                      debate, against shuffling party among that debate's speakers. Topic
                      is held fixed, which the classifier does not do.
  distinctive words   log-odds with a Dirichlet prior, to read what a difference consists of.
"""
import json
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_network import DATA, NOT_A_PARTY, RESULTS, ROOT, SEED, load_windows, status_change, window_of

SPEECHES = ROOT / "data-raw" / "derived" / "speeches.parquet"
ENCODER = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MIN_WORDS = 30
TFIDF_CHUNK_WORDS = 300
MAX_CHUNKS_PER_SPEAKER = 20
MIN_SPEAKERS = 8
N_LABEL_SHUFFLES = 20
EMBED_CHUNK_WORDS = 60  # the encoder truncates at 128 word pieces; 90 words truncated 38% of chunks
MAX_CHUNKS_PER_TURN_GROUP = 4
EMBED_LOG_EVERY = 4096
EMBEDDINGS = ROOT / "data-raw" / "derived" / f"embeddings_{EMBED_CHUNK_WORDS}w_{MAX_CHUNKS_PER_TURN_GROUP}c.npz"
MAX_SPEAKER_ITEMS_PER_WINDOW = 6000
N_DEBATE_SHUFFLES = 200
PARTY_NAMES = ["Socialdemokratiet", "Socialdemokraterne", "Socialdemokratiets", "Socialdemokrater", "Venstre", "Venstres",
               "Dansk Folkeparti", "Dansk Folkepartis", "Enhedslisten", "Enhedslistens", "Socialistisk Folkeparti",
               "Radikale", "Konservative", "Liberal Alliance", "Alternativet", "Moderaterne", "Danmarksdemokraterne",
               "Nye Borgerlige", "SF", "DF", "LA", "RV", "EL", "KF", "DD", "ALT", "NB"]

sys.stdout.reconfigure(encoding="utf-8")


def load_speech(windows):
    columns = ["session", "meeting", "item", "date", "person", "party", "text", "words",
               "is_person", "is_chair", "is_minister", "status"]
    frame = pd.read_parquet(SPEECHES, columns=columns)
    frame = frame[frame["is_person"] & ~frame["is_chair"] & ~frame["is_minister"] & frame["person"].notna()
                  & frame["party"].notna() & ~frame["party"].isin(NOT_A_PARTY) & (frame["words"] >= MIN_WORDS)].copy()
    frame["person"] = frame["person"].astype(int)
    frame["window"] = window_of(frame["date"], windows)
    frame = frame[frame["window"].notna()]
    frame["debate"] = frame["session"] + "|" + frame["meeting"].astype(str) + "|" + frame["item"].astype(str)
    return frame


def name_remover():
    """Removes people's and parties' names, which would otherwise identify speakers."""
    names = pd.read_parquet(DATA / "members.parquet")["name"].dropna()
    tokens = {t for n in names for t in re.split(r"[\s\-]+", n) if len(t) > 2 and t[0].isupper()}
    capitalized = re.compile(r"\b[A-ZÆØÅ]\w+\b")
    parties = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(PARTY_NAMES, key=len, reverse=True))) + r")\b")
    title = re.compile(r"\b(?:hr|Hr|fru|Fru)\.?\s")

    def drop_person(match):
        word = match.group()
        return " " if word in tokens or (word.endswith("s") and word[:-1] in tokens) else word

    return lambda text: title.sub(" ", parties.sub(" ", capitalized.sub(drop_person, text)))


def chunks(text, size):
    words = text.split()
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)] or [""]


def speaker_documents(part, rng):
    """(text, person, party) rows: each speaker's speech cut into chunks, capped per speaker."""
    rows = []
    for (person, party), group in part.groupby(["person", "party"]):
        pieces = chunks(" ".join(group["clean"]), TFIDF_CHUNK_WORDS)
        if len(pieces) > MAX_CHUNKS_PER_SPEAKER:
            pieces = [pieces[i] for i in rng.choice(len(pieces), MAX_CHUNKS_PER_SPEAKER, replace=False)]
        rows += [(p, person, party) for p in pieces]
    return pd.DataFrame(rows, columns=["text", "person", "party"])


def cv_balanced_accuracy(docs, labels):
    """Balanced accuracy on speakers held out of training, with chunks weighted equally."""
    predicted = np.empty(len(docs), dtype=object)
    for train, test in GroupKFold(n_splits=5).split(docs, labels, groups=docs["person"]):
        vectorizer = TfidfVectorizer(min_df=3, max_df=0.5, sublinear_tf=True)
        x_train = vectorizer.fit_transform(docs["text"].iloc[train])
        model = LogisticRegression(max_iter=300, class_weight="balanced")
        model.fit(x_train, labels[train])
        predicted[test] = model.predict(vectorizer.transform(docs["text"].iloc[test]))
    return balanced_accuracy_score(labels, list(predicted))


def distinguishability(frame, windows, focal, seed=SEED):
    """Accuracy for each party pair in each window; label shuffles for the focal pairs only."""
    rng = np.random.default_rng(seed)
    rows = []
    for w in windows:
        part = frame[frame["window"] == w["name"]]
        if part.empty:
            continue
        speakers = part.groupby("party")["person"].nunique()
        parties = sorted(speakers[speakers >= MIN_SPEAKERS].index)
        docs = speaker_documents(part[part["party"].isin(parties)], rng)
        pairs = list(combinations(parties, 2))
        rows += Parallel(n_jobs=-1)(
            delayed(score_pair)(docs[docs["party"].isin([a, b])].reset_index(drop=True), a, b, w["name"],
                                speakers, f"{a}-{b}" in focal, seed + i)
            for i, (a, b) in enumerate(pairs))
        print("classified", w["name"], len(pairs), "pairs", flush=True)
    return rows


def score_pair(pair, a, b, window, speakers, with_null, seed):
    rng = np.random.default_rng(seed)
    row = {"window": window, "pair": f"{a}-{b}", "speakers_a": int(speakers[a]), "speakers_b": int(speakers[b]),
           "chunks": len(pair), "accuracy": round(cv_balanced_accuracy(pair, pair["party"].to_numpy()), 3)}
    if with_null:
        people = pair.groupby("person")["party"].first()
        null = []
        for _ in range(N_LABEL_SHUFFLES):
            shuffled = dict(zip(people.index, rng.permutation(people.to_numpy())))
            null.append(cv_balanced_accuracy(pair, pair["person"].map(shuffled).to_numpy()))
        row["null_mean"] = round(float(np.mean(null)), 3)
        row["null_max"] = round(float(np.max(null)), 3)
    return row


def truncation_check(texts, model):
    """Share of chunks longer than the encoder's window, which it would silently cut."""
    lengths = [len(ids) for ids in model.tokenizer(list(texts), add_special_tokens=True)["input_ids"]]
    return {"chunks_checked": len(lengths), "encoder_limit": int(model.max_seq_length),
            "share_truncated": round(float(np.mean(np.array(lengths) > model.max_seq_length)), 4),
            "median_word_pieces": float(np.median(lengths))}


def embed_speakers(frame, seed=SEED):
    """One vector per (debate, speaker): the mean of up to three chunks, cached to disk."""
    from sentence_transformers import SentenceTransformer

    rng = np.random.default_rng(seed)
    grouped = frame.groupby(["window", "debate", "person", "party"], sort=False)["clean"].apply(" ".join).reset_index()
    # Only debates with at least two parties can be compared.
    parties_in_debate = grouped.groupby("debate")["party"].transform("nunique")
    grouped = grouped[parties_in_debate >= 2]
    keep = []
    for _, part in grouped.groupby("window"):
        debates = rng.permutation(part["debate"].unique())
        running = part.groupby("debate").size().reindex(debates).cumsum()
        keep.append(part[part["debate"].isin(running[running <= MAX_SPEAKER_ITEMS_PER_WINDOW].index)])
    grouped = pd.concat(keep).reset_index(drop=True)
    pieces, owner = [], []
    for i, text in enumerate(grouped["clean"]):
        for piece in chunks(text, EMBED_CHUNK_WORDS)[:MAX_CHUNKS_PER_TURN_GROUP]:
            pieces.append(piece)
            owner.append(i)
    owner = np.array(owner)
    model = SentenceTransformer(ENCODER, device="cpu")
    check = truncation_check(rng.choice(pieces, min(3000, len(pieces)), replace=False), model)
    print("truncation", check, "chunks", len(pieces), flush=True)
    if EMBEDDINGS.exists():
        vectors = np.load(EMBEDDINGS)["vectors"]
    else:
        parts = []
        for start in range(0, len(pieces), EMBED_LOG_EVERY):
            parts.append(model.encode(pieces[start:start + EMBED_LOG_EVERY], batch_size=64,
                                      normalize_embeddings=True, show_progress_bar=False))
            print(f"embedded {start + len(parts[-1])} of {len(pieces)}", flush=True)
        chunk_vectors = np.vstack(parts)
        vectors = np.zeros((len(grouped), chunk_vectors.shape[1]), dtype=np.float32)
        np.add.at(vectors, owner, chunk_vectors)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        np.savez_compressed(EMBEDDINGS, vectors=vectors)
    return grouped.drop(columns="clean"), vectors, check


def same_debate_similarity(meta, vectors, seed=SEED):
    """Mean cosine between two parties' speakers in one debate, minus the debate-shuffled mean."""
    rng = np.random.default_rng(seed)
    rows = []
    for window, part in meta.groupby("window"):
        observed, null = {}, {}
        for _, debate in part.groupby("debate"):
            index = debate.index.to_numpy()
            parties = debate["party"].to_numpy()
            matrix = vectors[index] @ vectors[index].T
            for a, b in combinations(sorted(set(parties)), 2):
                observed.setdefault((a, b), []).append(matrix[np.ix_(parties == a, parties == b)].mean())
            for _ in range(N_DEBATE_SHUFFLES // 20):
                shuffled = rng.permutation(parties)
                for a, b in combinations(sorted(set(parties)), 2):
                    null.setdefault((a, b), []).append(matrix[np.ix_(shuffled == a, shuffled == b)].mean())
        for pair, values in observed.items():
            if len(values) < 30:
                continue
            rows.append({"window": window, "pair": "-".join(pair), "debates": len(values),
                         "similarity": round(float(np.mean(values)), 4), "null": round(float(np.mean(null[pair])), 4),
                         "excess": round(float(np.mean(values) - np.mean(null[pair])), 4),
                         "se": round(float(np.std(values) / np.sqrt(len(values))), 4)})
    return rows


def word_counts(texts):
    counts = Counter()
    for text in texts:
        counts.update(re.findall(r"[a-zæøå]{3,}", text.lower()))
    return counts


def distinctive_words(frame, a, b, window, top=20):
    """Monroe et al. log-odds with an informative Dirichlet prior: words typical of a vs b."""
    part = frame[frame["window"] == window]
    ca, cb = word_counts(part.loc[part["party"] == a, "clean"]), word_counts(part.loc[part["party"] == b, "clean"])
    prior = word_counts(part["clean"])
    prior_scale = 500 / sum(prior.values())
    na, nb, rows = sum(ca.values()), sum(cb.values()), []
    alpha0 = 500
    for word, count in prior.items():
        if count < 30:
            continue
        alpha = count * prior_scale
        delta = (np.log((ca[word] + alpha) / (na + alpha0 - ca[word] - alpha))
                 - np.log((cb[word] + alpha) / (nb + alpha0 - cb[word] - alpha)))
        rows.append((word, delta / np.sqrt(1 / (ca[word] + alpha) + 1 / (cb[word] + alpha))))
    rows.sort(key=lambda r: r[1])
    return {b: [(w, round(float(z), 1)) for w, z in rows[:top]],
            a: [(w, round(float(z), 1)) for w, z in rows[::-1][:top]]}


def changes_at_formations(rows, value, windows):
    """Change in a pair's measure across each formation, with same-formation unchanged pairs as placebo."""
    table = pd.DataFrame(rows)
    out = []
    for before, after in zip(windows, windows[1:]):
        t0 = table[table["window"] == before["name"]].set_index("pair")[value]
        t1 = table[table["window"] == after["name"]].set_index("pair")[value]
        both = t0.index.intersection(t1.index)
        for pair in both:
            a, b = pair.split("-")
            out.append({"transition": after["from"], "pair": pair,
                        "relation": status_change(a, b, before["government"], after["government"]),
                        "before": float(t0[pair]), "after": float(t1[pair]),
                        "change": round(float(t1[pair] - t0[pair]), 4)})
    return out


def main():
    windows = load_windows()
    frame = load_speech(windows)
    clean = name_remover()
    print("backbench turns", len(frame), "speakers", frame["person"].nunique(), flush=True)
    frame["clean"] = frame["text"].map(clean)
    print("names removed", flush=True)

    focal = {"S-V", "M-S", "M-V", "DF-S", "DF-V", "EL-S", "S-SF", "KF-V", "LA-V", "RV-S", "RV-SF", "SF-V"}
    accuracy = distinguishability(frame, windows, focal)
    meta, vectors, check = embed_speakers(frame)
    similarity = same_debate_similarity(meta, vectors)
    words = {}
    for a, b, window in [("S", "V", w["name"]) for w in windows if frame.loc[frame["window"] == w["name"], "party"].isin(["S", "V"]).any()]:
        words[window] = distinctive_words(frame, a, b, window)
    results = {
        "corpus": {"backbench_turns": len(frame), "speakers": int(frame["person"].nunique()),
                   "words": int(frame["words"].sum()), "per_window": frame.groupby("window")["words"].sum().to_dict()},
        "encoder": ENCODER, "truncation": check, "speaker_debate_vectors": len(meta),
        "accuracy": accuracy, "accuracy_changes": changes_at_formations(accuracy, "accuracy", windows),
        "same_debate": similarity, "same_debate_changes": changes_at_formations(similarity, "excess", windows),
        "distinctive_words_S_vs_V": words,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "language.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
