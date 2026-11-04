#!/usr/bin/env python3
"""Step 3 of the pipeline: draw the samples the group labels by hand.

    python tools/make_labeling_sheets.py

Writes CSVs to labeling/ with an empty label column, plus the columns needed to judge
each row. Existing sheets are never overwritten, so labels cannot be lost: delete a
sheet on purpose to redraw it. tools/check_labels.py scores the filled-in sheets.
Open the CSVs in Excel or Google Sheets and save them as CSV with UTF-8 encoding.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dataset import DATA, DERIVED_RAW, NO_REMARKS, REMARK, ROOT

OUT = ROOT / "labeling"
SEED = 831
SHEET_SIZE = 60
SHORT_TURN_WORDS = 150

sys.stdout.reconfigure(encoding="utf-8")


def era(session):
    return "2009-2014" if session < "20142" else "2014-2019" if session < "20191" else "2019-2026"


def by_era(frame, total):
    """An equal number of rows from each period, so a rule cannot pass on easy years alone."""
    share = total // 3 + 1
    picked = frame.assign(era=frame["session"].map(era)).groupby("era", group_keys=False).apply(
        lambda part: part.sample(min(share, len(part)), random_state=SEED), include_groups=False)
    return picked.sample(frac=1, random_state=SEED).head(total)


def triples(speeches):
    """Every chair turn with the member turns on each side of it, in one frame."""
    keep = ["session", "meeting", "turn", "first", "last", "party", "role", "text", "words",
            "is_chair", "is_person", "date", "item", "status"]
    frame = speeches[keep].sort_values(["session", "meeting", "turn"]).reset_index(drop=True)
    same = frame["session"].eq(frame["session"].shift(-2)) & frame["meeting"].eq(frame["meeting"].shift(-2))
    rows = pd.DataFrame({
        "session": frame["session"], "meeting": frame["meeting"], "date": frame["date"], "status": frame["status"],
        "floor": frame["first"] + " " + frame["last"], "floor_party": frame["party"], "floor_text": frame["text"],
        "floor_is_chair": frame["is_chair"], "floor_is_person": frame["is_person"],
        "chair_is_chair": frame["is_chair"].shift(-1), "chair_text": frame["text"].shift(-1),
        "speaker": (frame["first"] + " " + frame["last"]).shift(-2), "speaker_party": frame["party"].shift(-2),
        "speaker_text": frame["text"].shift(-2), "speaker_words": frame["words"].shift(-2),
        "speaker_is_chair": frame["is_chair"].shift(-2), "speaker_is_person": frame["is_person"].shift(-2),
        "turn": frame["turn"].shift(-2),
    })[same]
    rows = rows[rows["chair_is_chair"].astype(bool) & ~rows["floor_is_chair"] & ~rows["speaker_is_chair"].astype(bool)
                & rows["floor_is_person"] & rows["speaker_is_person"].astype(bool) & (rows["floor"] != rows["speaker"])]
    called = [bool(REMARK.search(t)) and not NO_REMARKS.search(t) for t in rows["chair_text"]]
    return rows.assign(called=called)


def tail(text, words=60):
    parts = str(text).split()
    return ("... " if len(parts) > words else "") + " ".join(parts[-words:])


def head(text, words=90):
    parts = str(text).split()
    return " ".join(parts[:words]) + (" ..." if len(parts) > words else "")


def write_sheet(name, frame):
    path = OUT / f"{name}.csv"
    if path.exists():
        print("kept existing", path.name)
        return
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    print("wrote", path.name, len(frame))


def main():
    OUT.mkdir(exist_ok=True)
    speeches = pd.read_parquet(DERIVED_RAW / "speeches.parquet")
    pairs = triples(speeches)

    def sheet(sample):
        return pd.DataFrame({
            "session": sample["session"], "meeting": sample["meeting"], "turn": sample["turn"].astype(int),
            "date": sample["date"], "floor": sample["floor"] + " (" + sample["floor_party"].fillna("?") + ")",
            "floor_ends": sample["floor_text"].map(tail), "chair_says": sample["chair_text"],
            "next_speaker": sample["speaker"] + " (" + sample["speaker_party"].fillna("?") + ")",
            "next_speaker_says": sample["speaker_text"].map(head),
        })

    precision = sheet(by_era(pairs[pairs["called"]], SHEET_SIZE))
    precision["is_challenge_to_floor_yes_no"] = ""
    write_sheet("challenge_precision", precision)

    missed = pairs[~pairs["called"] & (pairs["speaker_words"] <= SHORT_TURN_WORDS)]
    recall = sheet(by_era(missed, SHEET_SIZE))
    recall["is_challenge_to_floor_yes_no"] = ""
    write_sheet("challenge_missed", recall)

    cross_party = by_era(pairs[pairs["called"] & (pairs["floor_party"] != pairs["speaker_party"])], SHEET_SIZE)
    stance = sheet(cross_party)
    stance["next_speaker_says"] = cross_party["speaker_text"].values
    stance["stance_hostile_neutral_friendly"] = ""
    write_sheet("challenge_stance", stance)

    people = speeches[speeches["is_person"] & speeches["person"].notna()]
    members = pd.read_parquet(DATA / "members.parquet").set_index("person")["name"]
    unique = people[["session", "first", "last", "party", "role", "person", "name_method"]].drop_duplicates(
        ["session", "first", "last", "person"])
    picks = [unique[unique["name_method"] == m].sample(
        min(n, int((unique["name_method"] == m).sum())), random_state=SEED)
        for m, n in [("alias", 13), ("tokens_seated", 15), ("exact_seated", 15), ("exact_party", 5), ("exact", 12)]]
    names = pd.concat(picks)
    names = pd.DataFrame({
        "session": names["session"], "name_in_transcript": names["first"] + " " + names["last"],
        "party_used": names["party"], "role": names["role"], "matched_person_id": names["person"].astype(int),
        "matched_name": names["person"].astype(int).map(members), "method": names["name_method"],
        "same_person_yes_no": "",
    })
    write_sheet("name_resolution", names)

    readme = OUT / "README.md"
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")


README = """# Hand labeling

The group fills these in; no model or agent may do it. Label each row without looking at the
other labels, and have a second person label `challenge_stance` so we can report agreement
(save their copy as `challenge_stance_second.csv`). Save as CSV (UTF-8). Then run
`python tools/check_labels.py`.

| Sheet | Label column | What to decide |
|---|---|---|
| `challenge_precision` | `is_challenge_to_floor_yes_no` | The rule called this an edge. Is `next_speaker` really addressing a short remark to `floor`? Answer `no` if they address someone else, even if it is a short remark. |
| `challenge_missed` | same | The rule did NOT call this an edge, and the next turn is short. Is it a short remark to `floor` anyway? Estimates what the rule misses. |
| `challenge_stance` | `stance_hostile_neutral_friendly` | Tone toward the floor speaker. `hostile`: attacks, accuses or ridicules. `friendly`: agrees, praises or offers support. `neutral`: a plain question or information, including polite disagreement on substance. |
| `name_resolution` | `same_person_yes_no` | Is the transcript name the same person as the matched record? Look them up on ft.dk if unsure. |

Transcripts from recent sessions may be provisional and can change.
"""


if __name__ == "__main__":
    main()
