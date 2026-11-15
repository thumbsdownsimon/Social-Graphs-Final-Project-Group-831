"""Loading and labeling the challenge edges, and each member's party history.

The input is data/challenges.parquet from tools/build_dataset.py: one row per short remark,
challenger -> member holding the floor. Party tags there are reliable for members speaking
as members, but ministers have no tag and the builder fills it from the nearest session
(which put Inger Støjberg in DD, founded 2022, as a minister in 2009). So party history is
built from non-minister turns only, and ministers are re-labeled from it.
"""
import json

import numpy as np
import pandas as pd

from .config import BLOC, DATA, INDEPENDENT, MAIN_BLOCS, MIN_RUN, NOT_A_PARTY, RENAMES


def load_raw_edges():
    return pd.read_parquet(DATA / "challenges.parquet")

def load_governments():
    return json.loads((DATA / "governments.json").read_text(encoding="utf-8"))

def load_windows(governments=None):
    """
    Splits time into periods of government: each one starts when a government is formed and ends when the next one takes over

    Windows between consecutive formations, named like '2019 S'.
    """
    governments = governments if governments is not None else load_governments()
    windows = []
    for i, row in enumerate(governments):
        end = governments[i + 1]["from"] if i + 1 < len(governments) else "9999-12-31"
        windows.append({"name": f"{row['from'][:4]} {'+'.join(row['parties'])}", "from": row["from"],
                        "to": end, "government": list(row["parties"])})
    return windows

def window_of(dates, windows):
    labels = pd.Series(pd.NA, index=dates.index, dtype=object)
    for w in windows:
        labels[(dates >= w["from"]) & (dates < w["to"])] = w["name"]
    return labels

def appearances(raw):
    """
    Long table: one row per member per edge end, in transcript order.
    Builds a timeline of each member's appearances, with the party they were in at the time. 
    """
    common = ["session", "meeting", "item", "date", "turn"]
    sides = []
    for side in ["floor", "challenger"]:
        part = raw[common + [f"{side}_person", f"{side}_party", f"{side}_is_minister"]].copy()
        part.columns = common + ["person", "party", "is_minister"]
        part["side"] = side
        # The floor turn comes before the chair's call and the challenger's turn.
        part["order"] = part["turn"] - (2 if side == "floor" else 0)
        sides.append(part)
    out = pd.concat(sides, ignore_index=True)
    out = out[out["person"].notna()].copy()
    out["person"] = out["person"].astype(int)
    out["party"] = out["party"].replace(RENAMES)
    return out.sort_values(["person", "date", "session", "meeting", "order"], kind="stable").reset_index(drop=True)

def _compress(labels):
    """[a, a, b, a] -> [(a, 0, 1), (b, 2, 2), (a, 3, 3)] as (label, first index, last index)."""
    runs = []
    for i, lab in enumerate(labels):
        if runs and runs[-1][0] == lab:
            runs[-1][2] = i
        else:
            runs.append([lab, i, i])
    return runs

def party_runs(apps, min_run=MIN_RUN):
    """
    Each member's consecutive spells in one party, from non-minister turns only.
    For each member of parliment, list the runs of consecutive appearances in the same party.

    Runs shorter than min_run appearances are dropped as noise (a misread tag), unless every
    run of that member is short, in which case the longest is kept. Neighbouring runs with
    the same party are then merged. Columns: person, party, start, end, n.
    """
    usable = apps[~apps["is_minister"] & apps["party"].notna() & ~apps["party"].isin(NOT_A_PARTY)]
    rows = []
    for person, part in usable.groupby("person", sort=True):
        labels = part["party"].tolist()
        dates = part["date"].tolist()
        runs = [(lab, a, b) for lab, a, b in _compress(labels)]
        kept = [r for r in runs if r[2] - r[1] + 1 >= min_run]
        if not kept:
            kept = [max(runs, key=lambda r: r[2] - r[1])]
        merged = []
        for lab, a, b in kept:
            if merged and merged[-1][0] == lab:
                merged[-1][2] = b
                merged[-1][3] += b - a + 1
            else:
                merged.append([lab, a, b, b - a + 1])
        for lab, a, b, n in merged:
            rows.append({"person": person, "party": lab, "start": dates[a], "end": dates[b], "n": n})
    return pd.DataFrame(rows, columns=["person", "party", "start", "end", "n"])

def party_switches(runs):
    """One row per change between consecutive runs. Moves to or from UFG count."""
    rows = []
    for person, part in runs.groupby("person", sort=True):
        part = part.sort_values("start")
        for prev, nxt in zip(part.itertuples(), part.iloc[1:].itertuples()):
            rows.append({"person": person, "from_party": prev.party, "to_party": nxt.party,
                         "last_seen_old": prev.end, "date": nxt.start,
                         "to_independent": nxt.party == INDEPENDENT,
                         "from_independent": prev.party == INDEPENDENT})
    return pd.DataFrame(rows, columns=["person", "from_party", "to_party", "last_seen_old", "date",
                                       "to_independent", "from_independent"])

def party_at(persons, dates, runs):
    """
    Which party was this person in on this date?
    """
    query = pd.DataFrame({"person": np.asarray(persons, dtype=int), "date": pd.to_datetime(dates),
                          "_i": np.arange(len(persons))})
    table = runs.assign(start=pd.to_datetime(runs["start"]))[["person", "start", "party"]].sort_values("start")
    query = query.sort_values("date")
    back = pd.merge_asof(query, table, left_on="date", right_on="start", by="person", direction="backward")
    fwd = pd.merge_asof(query, table, left_on="date", right_on="start", by="person", direction="forward")
    back["party"] = back["party"].fillna(fwd["party"])
    return back.sort_values("_i")["party"].to_numpy()

def government_at(dates, governments):
    """For each date, the set of governing parties (governments.json, sorted by 'from')."""
    starts = [g["from"] for g in governments]
    idx = np.searchsorted(starts, dates.to_numpy(dtype=str), side="right") - 1
    return [frozenset(governments[i]["parties"]) if i >= 0 else frozenset() for i in idx]

def own_side(c_party, f_party, c_gov, f_gov, c_bloc, f_bloc):
    """Allies: same party, both in government, or both in opposition and in the same main bloc.

    Whether the two people in a challenge are on the same side, meaning allies. c_ is the challenger and f_ is the floor speaker who gets challenged
    """
    c_party, f_party = np.asarray(c_party, dtype=object), np.asarray(f_party, dtype=object)
    c_gov, f_gov = np.asarray(c_gov, dtype=bool), np.asarray(f_gov, dtype=bool)
    c_bloc, f_bloc = np.asarray(c_bloc, dtype=object), np.asarray(f_bloc, dtype=object)
    same_main_bloc = np.isin(c_bloc, list(MAIN_BLOCS)) & (c_bloc == f_bloc)
    return (c_party == f_party) | (c_gov & f_gov) | (~c_gov & ~f_gov & same_main_bloc)


def label_edges(raw, runs, governments, windows):
    """Clean challenge edges with party, bloc, side and window labels.

    Ministers, and members without a usable tag, get the party of their run on that date.
    Edges outside every window, or where either party is still unknown, are dropped.
    """
    e = raw[raw["floor_person"].notna() & raw["challenger_person"].notna()].copy()
    for side in ["floor", "challenger"]:
        e[f"{side}_person"] = e[f"{side}_person"].astype(int)
        e[f"{side}_party"] = e[f"{side}_party"].replace(RENAMES)
        fix = e[f"{side}_is_minister"] | e[f"{side}_party"].isna() | e[f"{side}_party"].isin(NOT_A_PARTY)
        if fix.any():
            found = party_at(e.loc[fix, f"{side}_person"], e.loc[fix, "date"], runs)
            original = e.loc[fix, f"{side}_party"].to_numpy(dtype=object)
            # No non-minister history at all (a minister who never spoke as a member): keep the tag.
            e.loc[fix, f"{side}_party"] = np.where(pd.isna(found), original, found)
    e["window"] = window_of(e["date"], windows)
    keep = (e["window"].notna() & e["floor_party"].notna() & e["challenger_party"].notna()
            & ~e["floor_party"].isin(NOT_A_PARTY) & ~e["challenger_party"].isin(NOT_A_PARTY))
    e = e[keep].copy()

    gov = government_at(e["date"], governments)
    out = pd.DataFrame({
        "window": e["window"].to_numpy(),
        "date": e["date"].to_numpy(),
        "debate": (e["session"].astype(str) + "-" + e["meeting"].astype(str) + "-" + e["item"].astype(str)).to_numpy(),
        "challenger": e["challenger_person"].to_numpy(),
        "floor": e["floor_person"].to_numpy(),
        "c_party": e["challenger_party"].to_numpy(),
        "f_party": e["floor_party"].to_numpy(),
        "c_minister": e["challenger_is_minister"].to_numpy(bool),
        "f_minister": e["floor_is_minister"].to_numpy(bool),
    })
    out["c_bloc"] = out["c_party"].map(BLOC)
    out["f_bloc"] = out["f_party"].map(BLOC)
    for side in ["c", "f"]:
        in_gov_party = np.array([p in g for p, g in zip(out[f"{side}_party"], gov)], dtype=bool)
        out[f"{side}_gov"] = in_gov_party | out[f"{side}_minister"].to_numpy(bool)
    out["same_party"] = out["c_party"] == out["f_party"]
    out["cross_side"] = out["c_gov"] != out["f_gov"]
    out["at_government"] = out["f_gov"]
    both_main = out["c_bloc"].isin(MAIN_BLOCS) & out["f_bloc"].isin(MAIN_BLOCS)
    out["own_side"] = own_side(out["c_party"], out["f_party"], out["c_gov"], out["f_gov"], out["c_bloc"], out["f_bloc"])
    out["cross_bloc"] = np.where(both_main, (out["c_bloc"] != out["f_bloc"]).astype(float), np.nan)
    return out.sort_values(["date", "debate", "challenger", "floor"], kind="stable").reset_index(drop=True)


def sitting_days(raw):
    """Every date with at least one challenge: the calendar for exposure."""
    return np.array(sorted(raw["date"].unique()))


def load_all():
    """Everything layer 1 needs: (labeled edges, runs, switches, windows, sitting days)."""
    raw = load_raw_edges()
    governments = load_governments()
    windows = load_windows(governments)
    runs = party_runs(appearances(raw))
    switches = party_switches(runs)
    edges = label_edges(raw, runs, governments, windows)
    return edges, runs, switches, windows, sitting_days(raw)
