#!/usr/bin/env python3
"""Step 6 of the pipeline: score everything against the group's hand labels.

    python tools/check_labels.py

Reads labeling/*.csv and writes data/results/label_checks.json. Sheets not yet labeled
are reported as such, and a sheet only counts as "labeled" once every row is filled in
(challenge_stance by both labelers). Nothing here labels anything by itself.

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
DATA = ROOT / "data"
OUT = DATA / "results" / "label_checks.json"
STANCE_SCORE = {"hostile": -1, "neutral": 0, "friendly": 1}
YES_NO = {"yes", "no"}


def wilson(successes, total, z=1.96):
    """95% Wilson interval for a proportion."""
    if total == 0:
        return None
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [round(centre - half, 3), round(centre + half, 3)]


def era(session):
    """The periods make_labeling_sheets.py draws an equal number of rows from."""
    session = str(session)
    return "2009-2014" if session < "20142" else "2014-2019" if session < "20191" else "2019-2026"


def finite(value, digits):
    """A rounded number, or None: NaN would make data/site.json invalid and blank the site."""
    return round(float(value), digits) if math.isfinite(value) else None


def read_sheet(path):
    try:
        with open(path, encoding="utf-8-sig") as file:
            header = file.readline()
        # Excel on a Danish system separates columns with semicolons.
        return pd.read_csv(path, encoding="utf-8-sig", sep=";" if ";" in header else ",")
    except UnicodeDecodeError:
        sys.exit(f"{path.name} is not UTF-8. Save it again as 'CSV UTF-8'.")


def read_labels(name, column, allowed):
    """The labeled rows and the sheet's size. Stops on an unknown label instead of miscounting it."""
    path = SHEETS / f"{name}.csv"
    if not path.exists():
        return None, 0
    sheet = read_sheet(path)
    if column not in sheet:
        sys.exit(f"{path.name} has no column {column}. Keep the header row as it was.")
    sheet[column] = sheet[column].astype("string").str.strip().str.lower()
    labeled = sheet[sheet[column].notna() & (sheet[column] != "")]
    bad = labeled[~labeled[column].isin(allowed)]
    if not bad.empty:
        rows = ", ".join(f"row {i + 2}: {value!r}" for i, value in bad[column].items())
        sys.exit(f"{path.name}: allowed labels are {sorted(allowed)}. Fix {rows}")
    return labeled, len(sheet)


def yes_share(name, column):
    sheet, total = read_labels(name, column, YES_NO)
    if sheet is None or sheet.empty:
        return {"status": "not labeled yet"}
    yes = int((sheet[column] == "yes").sum())
    return {"status": "labeled" if len(sheet) == total else "partial", "n": len(sheet), "of": total, "yes": yes,
            "share": round(yes / len(sheet), 3), "ci95": wilson(yes, len(sheet))}


def precision():
    """The sample has equal rows per period, so also weight by each period's share of all edges."""
    name, column = "challenge_precision", "is_challenge_to_floor_yes_no"
    result = yes_share(name, column)
    if "n" not in result:
        return result
    sheet = read_labels(name, column, YES_NO)[0]
    correct = (sheet[column] == "yes").groupby(sheet["session"].map(era))
    weights = pd.read_parquet(DATA / "challenges.parquet", columns=["session"])["session"].map(era).value_counts()
    weights = weights[correct.mean().index]
    result["by_era"] = {period: {"n": int(group.size), "yes": int(group.sum())} for period, group in correct}
    result["era_weighted_share"] = round(float((correct.mean() * weights).sum() / weights.sum()), 3)
    return result


def names():
    """Most sampled rows repeat a name across sessions, so also score each name and person once."""
    name, column = "name_resolution", "same_person_yes_no"
    result = yes_share(name, column)
    if "n" not in result:
        return result
    sheet = read_labels(name, column, YES_NO)[0]
    pairs = (sheet[column] == "yes").groupby([sheet["name_in_transcript"], sheet["matched_person_id"]]).all()
    result.update(distinct_pairs=len(pairs), distinct_yes=int(pairs.sum()), distinct_ci95=wilson(int(pairs.sum()), len(pairs)))
    return result


def stance():
    column = "stance_hostile_neutral_friendly"
    first, total = read_labels("challenge_stance", column, STANCE_SCORE)
    if first is None or first.empty:
        return {"status": "not labeled yet"}
    afinn = Afinn(language="da")
    first = first.assign(score=first["next_speaker_says"].map(afinn.score))
    human = first[column].map(STANCE_SCORE)
    rho, p = spearmanr(first["score"], human) if first["score"].nunique() > 1 and human.nunique() > 1 else (math.nan, math.nan)
    result = {"status": "partial", "n": len(first), "of": total, "distribution": first[column].value_counts().to_dict(),
              "afinn_spearman_with_labels": finite(rho, 3), "afinn_p": finite(p, 4),
              "note": "AFINN counts positive and negative words; it does not see who the words are aimed at."}
    second = read_labels("challenge_stance_second", column, STANCE_SCORE)[0]
    if second is not None and not second.empty:
        merged = first.merge(second, on=["session", "meeting", "turn"], suffixes=("", "_2"))
        result["second_labeler_n"] = len(merged)
        result["cohen_kappa"] = finite(cohen_kappa_score(merged[column], merged[f"{column}_2"]), 3)
        if len(first) == len(merged) == total:
            result["status"] = "labeled"
    else:
        result["cohen_kappa"] = "no second labeler yet"
    return result


def main():
    results = {
        "challenge_precision": precision(),
        "challenge_missed": yes_share("challenge_missed", "is_challenge_to_floor_yes_no"),
        "name_resolution": names(),
        "challenge_stance": stance(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
