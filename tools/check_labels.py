#!/usr/bin/env python3
"""Step 6 of the pipeline: score everything against the group's hand labels.

    python tools/check_labels.py

Reads labeling/*.csv and writes data/results/label_checks.json. Sheets not yet labeled
are reported as such. Nothing here labels anything by itself.

  challenge_precision  share of the rule's edges that are real challenges to the floor
  challenge_missed     share of short unmatched turns that are challenges anyway; scaled
                       by how many such turns exist, this estimates the rule's recall
  name_resolution      share of sampled name matches that are the same person
  challenge_stance     agreement between two labelers, and of the AFINN Danish lexicon with them
"""
import json
import math
import sys
from pathlib import Path

import pandas as pd
from afinn import Afinn
from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parents[1]
SHEETS = ROOT / "labeling"
OUT = ROOT / "data" / "results" / "label_checks.json"
STANCE_SCORE = {"hostile": -1, "neutral": 0, "friendly": 1}

sys.stdout.reconfigure(encoding="utf-8")


def wilson(successes, total, z=1.96):
    """95% Wilson interval for a proportion."""
    if total == 0:
        return None
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [round(centre - half, 3), round(centre + half, 3)]


def read_labels(name, column):
    path = SHEETS / f"{name}.csv"
    if not path.exists():
        return None
    sheet = pd.read_csv(path, encoding="utf-8-sig")
    sheet[column] = sheet[column].astype("string").str.strip().str.lower()
    return sheet[sheet[column].notna() & (sheet[column] != "")]


def yes_share(name, column):
    sheet = read_labels(name, column)
    if sheet is None or sheet.empty:
        return {"status": "not labeled yet"}
    yes = int((sheet[column] == "yes").sum())
    return {"status": "labeled", "n": len(sheet), "yes": yes, "share": round(yes / len(sheet), 3),
            "ci95": wilson(yes, len(sheet))}


def stance():
    first = read_labels("challenge_stance", "stance_hostile_neutral_friendly")
    if first is None or first.empty:
        return {"status": "not labeled yet"}
    afinn = Afinn(language="da")
    first = first[first["stance_hostile_neutral_friendly"].isin(STANCE_SCORE)].copy()
    first["score"] = first["next_speaker_says"].map(afinn.score)
    human = first["stance_hostile_neutral_friendly"].map(STANCE_SCORE)
    rho, p = spearmanr(first["score"], human)
    result = {"status": "labeled", "n": len(first), "distribution": first["stance_hostile_neutral_friendly"].value_counts().to_dict(),
              "afinn_spearman_with_labels": round(float(rho), 3), "afinn_p": round(float(p), 4),
              "note": "AFINN counts positive and negative words; it does not see who the words are aimed at."}
    second = read_labels("challenge_stance_second", "stance_hostile_neutral_friendly")
    if second is not None and not second.empty:
        merged = first.merge(second, on=["session", "meeting", "turn"], suffixes=("", "_2"))
        result["second_labeler_n"] = len(merged)
        result["cohen_kappa"] = round(float(cohen_kappa_score(
            merged["stance_hostile_neutral_friendly"], merged["stance_hostile_neutral_friendly_2"])), 3)
    else:
        result["cohen_kappa"] = "no second labeler yet"
    return result


def main():
    results = {
        "challenge_precision": yes_share("challenge_precision", "is_challenge_to_floor_yes_no"),
        "challenge_missed": yes_share("challenge_missed", "is_challenge_to_floor_yes_no"),
        "name_resolution": yes_share("name_resolution", "same_person_yes_no"),
        "challenge_stance": stance(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
