#!/usr/bin/env python3
"""Step 5b of the pipeline: is the language difference about party, or about holding office?

    python tools/analyze_role.py

Writes data/results/role.json.

  opposition words  rate of words addressing the government (minister*, regering*), per party
                    per quarter. Simple and readable, but it counts words, not intent.
  role classifier   train on every window but one to tell government from opposition speakers,
                    test on the window left out. If it works on a government it never saw, then
                    role language is general. The check is shuffled labels, and party accuracy
                    in analyze_language.py is the comparison.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_language import MAX_CHUNKS_PER_SPEAKER, TFIDF_CHUNK_WORDS, chunks, load_speech, name_remover
from analyze_network import RESULTS, SEED, load_windows

ROLE_WORDS = re.compile(r"\b(?:\w*minister\w*|regering\w*)\b", re.I)
MIN_QUARTER_WORDS = 3000
MIN_SPEAKERS_IN_WINDOW = 5
N_SHUFFLES = 20
LAST_FULL_WINDOW = "2022 M+S+V"  # the 2026 government has too little speech to test on

sys.stdout.reconfigure(encoding="utf-8")


def in_government(party, window, windows):
    return party in next(w["government"] for w in windows if w["name"] == window)


def role_word_rates(frame, windows):
    """Role words per 1,000 words, per party per quarter, with the party's status that quarter."""
    frame = frame.assign(role_words=frame["text"].str.count(ROLE_WORDS),
                         quarter=pd.to_datetime(frame["date"]).dt.to_period("Q").astype(str))
    table = frame.groupby(["party", "quarter", "window"]).agg(role_words=("role_words", "sum"), words=("words", "sum")).reset_index()
    table = table[table["words"] >= MIN_QUARTER_WORDS]
    table["rate"] = (1000 * table["role_words"] / table["words"]).round(2)
    table["government"] = [in_government(p, w, windows) for p, w in zip(table["party"], table["window"])]
    return table


def within_party_test(table, seed=SEED):
    """Each party's mean rate in opposition minus in government, against shuffling status within party."""
    rng = np.random.default_rng(seed)
    parties = [p for p, part in table.groupby("party") if part["government"].sum() >= 4 and (~part["government"]).sum() >= 4]
    rows = []
    for party in parties:
        part = table[table["party"] == party]
        rows.append({"party": party, "opposition_rate": round(float(part.loc[~part["government"], "rate"].mean()), 2),
                     "government_rate": round(float(part.loc[part["government"], "rate"].mean()), 2),
                     "quarters": len(part)})
    observed = float(np.mean([r["opposition_rate"] - r["government_rate"] for r in rows]))
    null = []
    for _ in range(5000):
        gaps = []
        for party in parties:
            part = table[table["party"] == party]
            status = rng.permutation(part["government"].to_numpy())
            gaps.append(part["rate"].to_numpy()[~status].mean() - part["rate"].to_numpy()[status].mean())
        null.append(np.mean(gaps))
    return {"parties": rows, "mean_gap": round(observed, 2), "null_sd": round(float(np.std(null)), 2),
            "p": float((np.sum(np.abs(null) >= abs(observed)) + 1) / (len(null) + 1))}


def role_documents(frame, windows, seed=SEED):
    rng = np.random.default_rng(seed)
    rows = []
    for (window, person, party), group in frame.groupby(["window", "person", "party"]):
        pieces = chunks(" ".join(group["clean"]), TFIDF_CHUNK_WORDS)
        if len(pieces) > MAX_CHUNKS_PER_SPEAKER:
            pieces = [pieces[i] for i in rng.choice(len(pieces), MAX_CHUNKS_PER_SPEAKER, replace=False)]
        status = in_government(party, window, windows)
        rows += [{"text": p, "window": window, "person": person, "party": party, "government": status} for p in pieces]
    return pd.DataFrame(rows)


def train_and_test(train_text, train_y, test_text, test_y):
    vectorizer = TfidfVectorizer(min_df=5, max_df=0.5, sublinear_tf=True)
    model = LogisticRegression(max_iter=300, class_weight="balanced")
    model.fit(vectorizer.fit_transform(train_text), train_y)
    return model, vectorizer, balanced_accuracy_score(test_y, model.predict(vectorizer.transform(test_text)))


def one_window(docs, window, seed):
    """Train on other windows, test on this one, leaving this window's speakers out of training."""
    rng = np.random.default_rng(seed)
    test = docs[docs["window"] == window]
    train = docs[(docs["window"] != window) & ~docs["person"].isin(test["person"])]
    model, vectorizer, accuracy = train_and_test(train["text"], train["government"], test["text"], test["government"])
    null = []
    for _ in range(N_SHUFFLES):
        status = train.groupby("person")["government"].first()
        shuffled = dict(zip(status.index, rng.permutation(status.to_numpy())))
        _, _, value = train_and_test(train["text"], train["person"].map(shuffled), test["text"], test["government"])
        null.append(value)
    names = np.array(vectorizer.get_feature_names_out())
    order = np.argsort(model.coef_[0])
    return {"window": window, "test_chunks": len(test), "train_chunks": len(train), "accuracy": round(accuracy, 3),
            "null_mean": round(float(np.mean(null)), 3), "null_max": round(float(np.max(null)), 3),
            "opposition_words": names[order[:15]].tolist(), "government_words": names[order[::-1][:15]].tolist()}


def main():
    windows = load_windows()
    frame = load_speech(windows)
    print("turns", len(frame), flush=True)
    rates = role_word_rates(frame, windows)
    test = within_party_test(rates)
    print(test, flush=True)
    clean = name_remover()
    frame["clean"] = frame["text"].map(clean)
    docs = role_documents(frame[frame["window"] <= LAST_FULL_WINDOW], windows)
    tested = sorted(docs["window"].unique())
    classifier = Parallel(n_jobs=-1)(delayed(one_window)(docs, w, SEED + i) for i, w in enumerate(tested))
    for row in classifier:
        print({k: v for k, v in row.items() if "words" not in k}, row["opposition_words"][:8], flush=True)
    keep = rates[["party", "quarter", "rate", "government", "words"]]
    results = {"role_word_rates": keep.to_dict("records"), "within_party": test, "role_classifier": classifier,
               "pattern": ROLE_WORDS.pattern}
    (RESULTS / "role.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
