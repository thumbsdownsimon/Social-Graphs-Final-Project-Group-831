#!/usr/bin/env python3
"""Same member, different setting, and the late-night effect.

    python tools/analyze_settings.py                 # full run (about 25 minutes, mostly the sentiment model)
    python tools/analyze_settings.py --shuffles 50   # quicker
    python tools/analyze_settings.py --no-model      # skip the second tone method

Writes data/results/settings.json and caches per-turn scores in data-raw/derived/turn_tone.parquet.

Question 1, settings: does the SAME member sound different in the big televised debates and in
question time than in a routine first reading of a bill? Every member is compared with
themselves, so a difference cannot come from which parties or people speak in a setting.

Question 2, late night: does tone change as a sitting runs into the evening and past midnight?
Each turn is compared with the same member in the same kind of debate, so a late-night
difference cannot come from who speaks late or which debates run late.

Tone measures, all per 100 words of one turn (members only, no chair, no ministers, >= 30 words):
  negativity  sum of |score| of negative words in the Danish AFINN lexicon
  positivity  sum of score of positive words
  tone        positivity - negativity
  questions   question marks
AFINN is a word list made for social media, so words that are formulaic or mean something
else in parliament are dropped first (DROPPED_WORDS, with reasons). Whether this helps is
checked against the group's hand labels in tools/check_labels.py.

Second method: a multilingual sentiment model (MODEL) scores a sample of turns from every
setting, to see whether a contextual model ranks the settings the same way as the word list.

Nulls: the setting (or hour) labels are shuffled among each member's own turns (within member
and kind of debate for the hour), which keeps everything about who speaks and how often.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_network import NOT_A_PARTY, RESULTS, ROOT, SEED, load_windows, window_of

SPEECHES = ROOT / "data-raw" / "derived" / "speeches.parquet"
CACHE = ROOT / "data-raw" / "derived" / "turn_tone.parquet"
MODEL = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
MIN_WORDS = 30
MIN_TURNS_PER_CELL = 3      # a member needs this many turns in a setting to be compared there
MIN_TURNS_CHAMELEON = 10    # and this many in both settings to be ranked as a chameleon
MODEL_SAMPLE_PER_SETTING = 700
REFERENCE = "First reading: government bill"

# Words dropped from AFINN, with the reason. Found by listing the most frequent lexicon hits in a
# random sample of 20,000 turns and reading them in context.
DROPPED_WORDS = {
    "når": "means 'when' almost every time, not 'reach'",
    "tak": "formulaic: nearly every turn opens with 'Tak for det'",
    "ja": "yes/no answers, not tone", "nej": "yes/no answers, not tone",
    "fik": "'got', past tense of a neutral verb",
    "imod": "procedural: 'stemmer imod' (votes against)",
    "aftale": "'agreement' is a political noun here (a deal), not a feeling",
    "betale": "'pay', neutral in budget debates", "krav": "'requirement', neutral in bills",
    "alene": "'alone/only', mostly 'only'", "klar": "'ready/clear', mostly filler", "klart": "filler ('clearly')",
    "præcis": "filler ('exactly')", "bestemt": "filler ('certainly')", "helst": "filler ('preferably')",
    "sikre": "'ensure', a neutral policy verb", "sikrer": "'ensures'", "sikker": "'sure', mostly filler",
    "mulighed": "'option', neutral", "muligheder": "'options', neutral",
    "ønsker": "'wishes', procedural ('ønsker ordet')", "ønske": "'wish', procedural",
    "afgørende": "'decisive', a filler intensifier",
}

# Agenda item title (lower case) -> setting. First match wins, so order matters.
SETTINGS = [
    ("Opening debate", ["åbningsredegørelse", "statsministersens åbningsredegørelse", "åbningsdebat", "grundlovens § 38"]),
    ("Closing debate", ["indenrigs- og udenrigspolitiske situation"]),
    ("Party-leader debate", ["partilederdebat"]),
    ("PM question time", ["spørgetime med statsministeren", "spørgsmål til statsministeren"]),
    # Oral questions to ministers (31 turns of 30+ words) are too few for their own setting.
    ("Minister question time", ["spørgetime", "spørgetid", "oversendte spørgsmål", "besvarelse af spørgsmål"]),
    ("Finance bill", ["finanslov"]),
    ("Interpellation debate", ["forespørgsel", "forhandling af f "]),
    ("First reading: government bill", ["1. behandling af l "]),
    ("First reading: members' motion", ["1. behandling af b "]),
    ("Final readings", ["2. behandling", "3. behandling"]),
]
# The three big set-piece debates. PM question time is televised too, but it is a question format
# and behaves differently, so it is kept as its own setting.
FLAGSHIP = ["Opening debate", "Closing debate", "Party-leader debate"]
HOUR_BINS = [(9, 12, "09-12"), (12, 15, "12-15"), (15, 18, "15-18"), (18, 21, "18-21"), (21, 24, "21-24"), (24, 29, "after midnight")]
MEASURES = ["tone", "negativity", "positivity", "questions"]

sys.stdout.reconfigure(encoding="utf-8")


def setting_of(titles):
    lower = titles.fillna("").str.lower() + " "
    out = pd.Series("Other", index=titles.index)
    assigned = pd.Series(False, index=titles.index)
    for name, keys in SETTINGS:
        hit = lower.str.contains("|".join(k.replace(".", r"\.") for k in keys)) & ~assigned
        out[hit] = name
        assigned |= hit
    return out


def load_turns(windows):
    columns = ["session", "meeting", "item", "item_title", "turn", "date", "start", "person", "party",
               "is_person", "is_chair", "is_minister", "words", "text", "status"]
    frame = pd.read_parquet(SPEECHES, columns=columns)
    frame = frame[frame["is_person"] & ~frame["is_chair"] & ~frame["is_minister"] & frame["person"].notna()
                  & frame["party"].notna() & ~frame["party"].isin(NOT_A_PARTY) & (frame["words"] >= MIN_WORDS)].copy()
    frame["person"] = frame["person"].astype(int)
    frame["window"] = window_of(frame["date"], windows)
    frame = frame[frame["window"].notna()]
    frame["setting"] = setting_of(frame["item_title"])
    government = {w["name"]: set(w["government"]) for w in windows}
    frame["side"] = np.where([p in government[w] for p, w in zip(frame["party"], frame["window"])], "government", "opposition")
    start = pd.to_datetime(frame["start"], errors="coerce")
    # A sitting that runs past midnight keeps its date; hours 0-4 are counted as 24-28.
    hour = start.dt.hour + start.dt.minute / 60
    frame["hour"] = np.where(hour < 5, hour + 24, hour)
    frame["debate"] = frame["session"] + "|" + frame["meeting"].astype(str) + "|" + frame["item"].astype(str)
    return frame.reset_index(drop=True)


def _score_block(texts, words):
    from afinn import Afinn

    afinn = Afinn(language="da")
    lexicon = afinn._dict  # word -> score; the matching pattern is built from it when Afinn loads
    rows = []
    for text, n in zip(texts, words):
        found = (w.lower() for w in afinn.find_all(text))
        scores = [lexicon[w] for w in found if w not in DROPPED_WORDS and w in lexicon]
        pos = sum(s for s in scores if s > 0)
        neg = -sum(s for s in scores if s < 0)
        rows.append((100 * pos / n, 100 * neg / n, 100 * text.count("?") / n))
    return rows


def lexicon_scores(frame):
    """Per-turn AFINN rates, cached by (session, meeting, turn)."""
    key = ["session", "meeting", "turn"]
    if CACHE.exists():
        cached = pd.read_parquet(CACHE)
        merged = frame.merge(cached, on=key, how="left")
        if merged["positivity"].notna().all():
            return merged
    blocks = np.array_split(np.arange(len(frame)), 64)
    parts = Parallel(n_jobs=-1)(delayed(_score_block)(frame["text"].iloc[b].tolist(), frame["words"].iloc[b].tolist()) for b in blocks)
    scores = pd.DataFrame([r for p in parts for r in p], columns=["positivity", "negativity", "questions"])
    scored = pd.concat([frame[key].reset_index(drop=True), scores], axis=1)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(CACHE, index=False)
    return frame.merge(scored, on=key, how="left")


def cell_means(frame, label, measures):
    return frame.groupby(["person", label])[measures].agg(["mean", "size"])


def within_member_effects(frame, label, reference, measures, n_shuffles, seed, min_turns=MIN_TURNS_PER_CELL):
    """Mean over members of (member's mean in a level) - (same member's mean in the reference level).

    Null: the labels are shuffled among each member's own turns, n_shuffles times.
    """
    rng = np.random.default_rng(seed)
    part = frame[["person", label] + measures].copy()

    def effects(labels):
        part["_l"] = labels
        grouped = part.groupby(["person", "_l"])
        means = grouped[measures].mean()
        sizes = grouped.size()
        means = means[sizes >= min_turns]
        ref = means.xs(reference, level="_l") if reference in means.index.get_level_values("_l") else None
        out = {}
        for level in means.index.get_level_values("_l").unique():
            if level == reference:
                continue
            here = means.xs(level, level="_l")
            both = here.index.intersection(ref.index)
            diff = here.loc[both] - ref.loc[both]
            out[level] = (diff.mean(), len(both), diff)
        return out

    observed = effects(part[label].to_numpy())
    # Shuffle within member: permute labels inside each person's block of rows.
    order = np.argsort(part["person"].to_numpy(), kind="stable")
    persons = part["person"].to_numpy()[order]
    bounds = np.flatnonzero(np.diff(persons)) + 1
    labels_sorted = part[label].to_numpy()[order]
    null = {level: [] for level in observed}
    for _ in range(n_shuffles):
        shuffled_sorted = np.concatenate([rng.permutation(block) for block in np.split(labels_sorted, bounds)])
        shuffled = np.empty_like(shuffled_sorted)
        shuffled[order] = shuffled_sorted
        for level, (mean, _, _) in effects(shuffled).items():
            if level in null:
                null[level].append(mean)
    rows = []
    for level, (mean, n_members, diff) in observed.items():
        nulls = pd.DataFrame(null[level])
        boot = [diff.sample(len(diff), replace=True, random_state=int(s)).mean() for s in rng.integers(0, 2**31, 300)]
        boot = pd.DataFrame(boot)
        for m in measures:
            sd = float(nulls[m].std()) if len(nulls) else float("nan")
            z = (float(mean[m]) - float(nulls[m].mean())) / sd if sd > 0 else float("nan")
            p = float((np.abs(nulls[m] - nulls[m].mean()) >= abs(mean[m] - nulls[m].mean())).mean()) if len(nulls) else float("nan")
            rows.append({"level": level, "measure": m, "members": int(n_members), "effect": round(float(mean[m]), 4),
                         "ci_low": round(float(boot[m].quantile(0.025)), 4), "ci_high": round(float(boot[m].quantile(0.975)), 4),
                         "null_sd": round(sd, 4), "z": round(z, 2), "p_two_sided": round(p, 4)})
    return rows


def chameleons(frame, members, n_shuffles, seed):
    """Members whose tone differs most between flagship debates and routine first readings."""
    rng = np.random.default_rng(seed)
    part = frame[frame["setting"].isin(FLAGSHIP + [REFERENCE])].copy()
    part["flag"] = part["setting"].isin(FLAGSHIP)
    counts = part.groupby(["person", "flag"]).size().unstack(fill_value=0)
    eligible = counts[(counts.get(True, 0) >= MIN_TURNS_CHAMELEON) & (counts.get(False, 0) >= MIN_TURNS_CHAMELEON)].index
    rows = []
    for person in eligible:
        own = part[part["person"] == person]
        tone = own["tone"].to_numpy()
        flag = own["flag"].to_numpy()
        observed = tone[flag].mean() - tone[~flag].mean()
        null = np.array([(lambda f: tone[f].mean() - tone[~f].mean())(rng.permutation(flag)) for _ in range(n_shuffles)])
        z = (observed - null.mean()) / null.std() if null.std() > 0 else np.nan
        last = own.sort_values("date").iloc[-1]
        rows.append({"person": int(person), "name": members.get(int(person), str(person)), "party": last["party"],
                     "flagship_turns": int(flag.sum()), "routine_turns": int((~flag).sum()),
                     "flagship_tone": round(float(tone[flag].mean()), 3), "routine_tone": round(float(tone[~flag].mean()), 3),
                     "difference": round(float(observed), 3), "z": round(float(z), 2)})
    table = pd.DataFrame(rows)
    expected_false = 0.05 * len(table)
    return table.sort_values("difference").to_dict("records"), {"members_ranked": len(table),
            "beyond_z2": int((table["z"].abs() >= 2).sum()), "expected_beyond_z2_by_chance": round(expected_false, 1)}


def hour_bin(hours):
    out = pd.Series(pd.NA, index=hours.index, dtype="object")
    for lo, hi, name in HOUR_BINS:
        out[(hours >= lo) & (hours < hi)] = name
    return out


def late_night(frame, n_shuffles, seed):
    """Tone by hour of the day, centred on the same member in the same kind of debate."""
    rng = np.random.default_rng(seed)
    part = frame[frame["hour"].notna()].copy()
    part["bin"] = hour_bin(part["hour"])
    part = part[part["bin"].notna()]
    part["cell"] = part["person"].astype(str) + "|" + part["setting"]
    for m in MEASURES:
        part[m + "_c"] = part[m] - part.groupby("cell")[m].transform("mean")
    centred = [m + "_c" for m in MEASURES]
    order = [b[2] for b in HOUR_BINS]
    observed = part.groupby("bin")[centred].mean().reindex(order)
    raw = part.groupby("bin")[MEASURES].mean().reindex(order)
    counts = part.groupby("bin").size().reindex(order)
    settings_mix = (part.groupby(["bin", "setting"]).size() / part.groupby("bin").size()).unstack(fill_value=0).reindex(order)
    # Null: shuffle hour bins within each member-and-setting cell.
    cells = part["cell"].to_numpy()
    sort = np.argsort(cells, kind="stable")
    bounds = np.flatnonzero(cells[sort][1:] != cells[sort][:-1]) + 1
    bins_sorted = part["bin"].to_numpy()[sort]
    null = []
    values = part[centred].reset_index(drop=True)
    for _ in range(n_shuffles):
        s = np.concatenate([rng.permutation(b) for b in np.split(bins_sorted, bounds)])
        shuffled = np.empty_like(s)
        shuffled[sort] = s
        null.append(values.groupby(shuffled).mean().reindex(order))
    null = pd.concat(null, keys=range(len(null)))
    null_sd = null.groupby(level=1).std().reindex(order)
    rows = []
    for b in order:
        row = {"bin": b, "turns": int(counts[b]), "members": int(part.loc[part["bin"] == b, "person"].nunique())}
        for m in MEASURES:
            row[m] = round(float(observed.loc[b, m + "_c"]), 4)
            row[m + "_null_sd"] = round(float(null_sd.loc[b, m + "_c"]), 4)
            row[m + "_raw"] = round(float(raw.loc[b, m]), 4)
        row["top_settings"] = settings_mix.loc[b].sort_values(ascending=False).head(3).round(3).to_dict()
        rows.append(row)
    # Late sittings only: how many turns after 22:00 and in which settings.
    late = part[part["hour"] >= 22]
    # After midnight comes from a limited number of sittings, and turns in one sitting are not
    # independent. Leave each sitting out in turn and report how far the effect moves, and the
    # effect with every sitting weighted equally.
    night = part[part["bin"] == "after midnight"].copy()
    night["sitting"] = night["session"] + "|" + night["meeting"].astype(str)
    per_sitting = night.groupby("sitting").agg(tone=("tone_c", "mean"), turns=("tone_c", "size"), date=("date", "first"))
    leave_one_out = [night.loc[night["sitting"] != s, "tone_c"].mean() for s in per_sitting.index]
    robustness = {"sittings": int(len(per_sitting)), "largest_sitting_share": round(float(per_sitting["turns"].max() / len(night)), 3),
                  "leave_one_sitting_out_min": round(float(min(leave_one_out)), 4), "leave_one_sitting_out_max": round(float(max(leave_one_out)), 4),
                  "sitting_weighted_mean": round(float(per_sitting["tone"].mean()), 4),
                  "sittings_below_zero": int((per_sitting["tone"] < 0).sum())}
    return {"bins": rows, "turns_after_22": int(len(late)), "after_midnight_robustness": robustness,
            "settings_after_22": late["setting"].value_counts(normalize=True).round(3).head(6).to_dict()}


def model_scores(frame, seed):
    """Second method: a multilingual sentiment model on a sample of turns from each setting."""
    from transformers import pipeline

    # pandas 3 drops the grouping column inside groupby().apply, so sample by index instead.
    picked = [g.sample(min(len(g), MODEL_SAMPLE_PER_SETTING), random_state=seed).index
              for _, g in frame[frame["setting"] != "Other"].groupby("setting")]
    sample = frame.loc[np.concatenate(picked)]
    classifier = pipeline("text-classification", model=MODEL, top_k=None, device=-1)
    texts = sample["text"].tolist()
    out = []
    for start in range(0, len(texts), 256):
        for scores in classifier(texts[start:start + 256], truncation=True, max_length=256, batch_size=16):
            s = {d["label"]: d["score"] for d in scores}
            out.append(s.get("positive", 0) - s.get("negative", 0))
        print(f"model scored {min(start + 256, len(texts))} of {len(texts)}", flush=True)
    sample = sample.assign(model=out)
    by_setting = sample.groupby("setting").agg(model=("model", "mean"), tone=("tone", "mean"), turns=("model", "size"))
    from scipy.stats import spearmanr
    rho_turn, _ = spearmanr(sample["model"], sample["tone"])
    rho_setting, p_setting = spearmanr(by_setting["model"], by_setting["tone"])
    return {"model": MODEL, "turns_scored": len(sample), "max_tokens": 256,
            "spearman_turn_level": round(float(rho_turn), 3),
            "spearman_setting_means": round(float(rho_setting), 3), "p_setting_means": round(float(p_setting), 4),
            "by_setting": by_setting.round(4).reset_index().to_dict("records")}


def without_nan(value):
    """The same structure with NaN and infinities replaced by None, so the JSON stays valid."""
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, dict):
        return {k: without_nan(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [without_nan(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shuffles", type=int, default=200)
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()

    windows = load_windows()
    frame = load_turns(windows)
    print("turns", len(frame), "members", frame["person"].nunique(), flush=True)
    frame = lexicon_scores(frame)
    frame["tone"] = frame["positivity"] - frame["negativity"]
    members = pd.read_parquet(ROOT / "data" / "members.parquet").set_index("person")["name"].to_dict() \
        if "person" in pd.read_parquet(ROOT / "data" / "members.parquet").columns else {}
    print("scored", flush=True)

    used = frame[frame["setting"] != "Other"]
    overview = used.groupby("setting").agg(turns=("tone", "size"), members=("person", "nunique"),
                                           words=("words", "sum"), **{m: (m, "mean") for m in MEASURES})
    overview = overview.reindex([s for s, _ in SETTINGS]).round(4).reset_index().to_dict("records")

    effects = within_member_effects(used, "setting", REFERENCE, MEASURES, args.shuffles, SEED)
    print("setting effects done", flush=True)
    by_side = {}
    for side in ["government", "opposition"]:
        by_side[side] = within_member_effects(used[used["side"] == side], "setting", REFERENCE, ["tone", "negativity"], args.shuffles, SEED + 1)
    print("by side done", flush=True)
    chameleon_rows, chameleon_summary = chameleons(used, members, args.shuffles, SEED + 2)
    night = late_night(used, args.shuffles, SEED + 3)
    print("late night done", flush=True)
    second = None if args.no_model else model_scores(used, SEED)

    results = {
        "corpus": {"turns": len(frame), "turns_in_settings": len(used), "members": int(used["person"].nunique()),
                   "min_words": MIN_WORDS, "other_share": round(float((frame["setting"] == "Other").mean()), 4)},
        "dropped_words": DROPPED_WORDS, "reference": REFERENCE, "flagship": FLAGSHIP,
        "settings": overview, "effects": effects, "effects_by_side": by_side,
        "chameleons": chameleon_rows, "chameleon_summary": chameleon_summary,
        "late_night": night, "second_method": second, "shuffles": args.shuffles,
        "min_turns_per_cell": MIN_TURNS_PER_CELL, "min_turns_chameleon": MIN_TURNS_CHAMELEON,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    # NaN (e.g. a setting where no government member spoke) is not valid JSON and would stop the page loading.
    (RESULTS / "settings.json").write_text(json.dumps(without_nan(results), ensure_ascii=False, indent=1, default=str, allow_nan=False), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
