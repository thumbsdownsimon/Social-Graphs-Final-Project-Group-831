#!/usr/bin/env python3
"""Step 7 of the pipeline: recompute key numbers a second way, and test the measures on toy cases.

    python tools/validate.py

Writes data/results/validation.json and stops with an error if any check fails. These
catch bugs in agent-written code; they do not show that a measure means what we claim.
Those checks are the nulls in the analysis and the group's hand labels.
"""
import json
import re
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_network import DATA, RESULTS, ROOT, assortativity_from_matrix, load_windows, mixing_against_null, status_change
from analyze_votes import ABSENT, member_votes
from build_dataset import parties_by_side

XML_DIR = ROOT / "data-raw" / "oda_referat"
RAW_FORMATION = "2022-12-15"
checks = []

sys.stdout.reconfigure(encoding="utf-8")


def check(name, ok, detail=""):
    checks.append({"check": name, "passed": bool(ok), "detail": str(detail)})
    print("PASS" if ok else "FAIL", name, detail, flush=True)


def toy_mixing():
    """Four people, two parties. Counts worked out on paper: A->X twice, B->X once, X->A once, Y->B once."""
    edges = pd.DataFrame({
        "challenger_party": ["S", "S", "S", "V", "V"], "floor_party": ["V", "V", "V", "S", "S"],
        "challenger_person": [1, 1, 2, 3, 4], "floor_person": [3, 3, 3, 1, 2],
    })
    observed, expected, _, _ = mixing_against_null(edges, ["S", "V"], n=2000)
    check("toy: observed party matrix", observed.tolist() == [[0, 3], [2, 0]], observed.tolist())
    # Marginals: 3 of 5 edges start at S, 3 of 5 end at V. A floor shuffle keeps out and in degrees,
    # so S->V can never drop below 1 and the null's S->S cell must be positive.
    check("toy: null spreads edges across cells", expected[0, 0] > 0 and expected[0, 1] < 3, expected.round(2).tolist())


def toy_assortativity():
    """Our formula against networkx on the same small directed graph."""
    graph = nx.DiGraph()
    labels = {1: "a", 2: "a", 3: "b", 4: "b", 5: "c"}
    graph.add_nodes_from((n, {"party": p}) for n, p in labels.items())
    links = [(1, 2), (2, 1), (1, 3), (3, 4), (4, 5), (5, 1), (2, 4), (3, 1)]
    graph.add_edges_from(links)
    parties = ["a", "b", "c"]
    matrix = np.zeros((3, 3))
    for a, b in links:
        matrix[parties.index(labels[a]), parties.index(labels[b])] += 1
    ours = assortativity_from_matrix(matrix)
    theirs = nx.attribute_assortativity_coefficient(graph, "party")
    check("assortativity matches networkx", abs(ours - theirs) < 1e-9, f"{ours:.4f} vs {theirs:.4f}")


def toy_status():
    check("status: S+V into government together", status_change("S", "V", ["S"], ["M", "S", "V"]) == "joined")
    check("status: pair leaves together", status_change("LA", "V", ["KF", "LA", "V"], ["S"]) == "split")
    check("status: both outside before and after", status_change("DF", "EL", ["S"], ["M", "S", "V"]) == "unchanged")


def toy_vote_parser():
    new = "Vedtaget For stemte 69 (S, SF), imod stemte 44 (V, Jacob Harris (UFG)), hverken for eller imod stemte 0"
    old = "Vedtaget\n\n59 stemmer for forslaget (S, RV)\n\n54 stemmer imod forslaget (V, DF)\n\n0 stemmer hverken for eller imod forslaget\n\n"
    check("vote parser: new format", parties_by_side(new) == {"for": {"S", "SF"}, "imod": {"V"}, "hverken": set()}, parties_by_side(new))
    check("vote parser: old format", parties_by_side(old) == {"for": {"S", "RV"}, "imod": {"V", "DF"}, "hverken": set()}, parties_by_side(old))
    conjunction = parties_by_side("Forslaget blev vedtaget. For stemte 59 (S, V og M), imod stemte 47 (SF, DD), hverken for eller imod stemte 4 (DF).")
    check("vote parser: list ending in og", conjunction == {"for": {"S", "V", "M"}, "imod": {"SF", "DD"}, "hverken": {"DF"}}, conjunction)
    initials = parties_by_side("For stemte 42 (Jan E. Jørgensen (V), SF, LA og NB), imod stemte 57 (S, V og M), hverken for eller imod stemte 8 (DD).")
    check("vote parser: named member with initial", initials == {"for": {"SF", "LA", "NB"}, "imod": {"S", "V", "M"}, "hverken": {"DD"}}, initials)
    check("vote parser: tally format has no parties", parties_by_side("\nVedtaget\n\nFor\t  95\nImod\t  21\n") is None)


def recount_from_xml():
    """Count S<->V short remarks directly in the raw XML with regexes, sharing no code with the pipeline.

    Each Tale is cut out as text. A turn's speaker fields come from its own tags. Only sessions
    around the 2022 formation are scanned, and turns by people without a party tag (ministers)
    are skipped, so the comparison is with backbench S-V edges in challenges.parquet.
    """
    field = lambda tag, text: (re.search(rf"<{tag}>([^<]*)</{tag}>", text) or [None, ""])[1].strip()
    counts = {"before": 0, "after": 0}
    for folder in ["20191", "20201", "20211", "20221", "20222", "20231", "20241", "20251"]:
        for path in sorted((XML_DIR / folder).glob("*.xml")):
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
            date = re.search(r"<DateOfSitting>(\d{4}-\d{2}-\d{2})", raw).group(1)
            turns = []
            for tale in re.findall(r"<Tale>.*?</Tale>", raw, flags=re.S):
                words = " ".join(re.findall(r"<Char[^>]*>([^<]*)</Char>", tale))
                turns.append((field("OratorFirstName", tale) + " " + field("OratorLastName", tale),
                              field("GroupNameShort", tale), field("OratorRole", tale).lower(), words))
            for floor, chair, challenger in zip(turns, turns[1:], turns[2:]):
                if "formand" not in chair[2] or not re.search(r"korte? bemærkning", chair[3], re.I):
                    continue
                if re.search(r"(ikke|ingen)[^.]{0,40}bemærkning", chair[3], re.I):
                    continue
                if {floor[1], challenger[1]} == {"S", "V"} and floor[0] != challenger[0]:
                    counts["after" if date >= RAW_FORMATION else "before"] += 1
    edges = pd.read_parquet(DATA / "challenges.parquet")
    is_pair = edges["floor_party"].isin(["S", "V"]) & edges["challenger_party"].isin(["S", "V"]) & (
        edges["floor_party"] != edges["challenger_party"])
    no_minister = ~edges["floor_is_minister"] & ~edges["challenger_is_minister"]
    in_range = edges["session"].between("20191", "20251")
    part = edges[is_pair & no_minister & in_range]
    pipeline = {"before": int((part["date"] < RAW_FORMATION).sum()), "after": int((part["date"] >= RAW_FORMATION).sum())}
    # The damaged file 20222_M62 fails the regex in part, and mid-session ministers can carry a party tag.
    close = all(abs(counts[k] - pipeline[k]) <= max(3, 0.03 * pipeline[k]) for k in counts)
    check("S-V backbench challenges recounted from raw XML", close, f"raw {counts} vs pipeline {pipeline}")
    return {"raw_xml": counts, "pipeline": pipeline}


def recount_votes():
    """S-V agreement from individual member votes, which share nothing with the vote summaries."""
    windows = load_windows()
    rows = member_votes(windows)
    rows = rows[(rows["window"] == "2022 M+S+V") & (rows["type"] != ABSENT) & rows["party"].isin(["S", "V"])]
    counts = rows.groupby(["vote", "party", "type"]).size().rename("n").reset_index()
    line = counts.sort_values("n").groupby(["vote", "party"]).tail(1).pivot(index="vote", columns="party", values="type").dropna()
    from_members = float((line["S"] == line["V"]).mean())
    network = json.loads((RESULTS / "network.json").read_text(encoding="utf-8"))
    stored = network["vote_agreement"]["2022 M+S+V"]["pairs"]["S-V"]
    check("S-V agreement 2022-26: member votes vs vote summaries", abs(from_members - stored["all"]) < 0.01,
          f"member votes {from_members:.4f} on {len(line)} votes vs summaries {stored['all']} on {stored['n']}")
    return {"from_member_votes": round(from_members, 4), "votes": len(line), "from_summaries": stored["all"], "summaries_n": stored["n"]}


def main():
    toy_mixing()
    toy_assortativity()
    toy_status()
    toy_vote_parser()
    recounts = {"s_v_challenges": recount_from_xml(), "s_v_votes": recount_votes()}
    (RESULTS / "validation.json").write_text(json.dumps({"checks": checks, "recounts": recounts}, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [c["check"] for c in checks if not c["passed"]]
    print(f"{len(checks) - len(failed)} of {len(checks)} passed")
    if failed:
        raise SystemExit(f"Failed: {failed}")


if __name__ == "__main__":
    main()
