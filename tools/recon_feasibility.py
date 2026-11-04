#!/usr/bin/env python3
"""Follow-up to recon_oda.py: can the candidate projects actually be measured?

Uses the cached responses and sampled debate files from recon_oda.py, so run that
first. Writes docs/recon_feasibility.json. Exploratory numbers, not final results.

    python tools/recon_feasibility.py
"""
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oda_client import ROOT, fetch_all
from recon_oda import XML_CACHE, sessions, speeches

OUT = ROOT / "docs" / "recon_feasibility.json"
# Two summary formats exist: "For stemte 96 (S, V)" and, in older votes, "96 stemmer for forslaget (S, V)".
SIDE_NEW = re.compile(r"(hverken for eller imod|for|imod) stemte (\d+)\s*(?:\(([^)]*)\)?)?", re.I)
SIDE_OLD = re.compile(r"(\d+) stemmer (hverken for eller imod|for|imod) forslaget\s*(?:\(([^)]*)\)?)?", re.I)
NO_REMARKS = re.compile(r"(ikke|ingen)[^.]{0,40}bemærkning", re.I)
REMARK = re.compile(r"korte? bemærkning", re.I)
sys.stdout.reconfigure(encoding="utf-8")


def parties_by_side(conclusion):
    """{'for': {'S','V'}, 'imod': {...}, 'hverken': {...}} parsed from a vote's summary text.

    Individually named members such as 'Jeppe Søe (UFG)' are dropped: we want party
    positions only. Returns None if the text has no parseable For/imod clause.
    """
    # Nested parentheses around named members break a simple split, so remove them first.
    text = re.sub(r"[A-ZÆØÅ][\w\-]+(?: [A-ZÆØÅ][\w\-]+)+ \([^)]*\),?", "", conclusion or "")
    sides = {}
    found = [(label, names) for label, _, names in SIDE_NEW.findall(text)]
    found += [(label, names) for _, label, names in SIDE_OLD.findall(text)]
    for label, names in found:
        key = label.lower().split()[0]
        sides[key] = {n.strip() for n in (names or "").split(",") if n.strip()}
    return sides if "for" in sides and "imod" in sides else None


def party_agreement():
    sessions_rows = sessions()
    code = {p["id"]: p["kode"] for p in sessions_rows}
    moeder = {m["id"]: m for m in fetch_all("Møde", filter="typeid eq 1", select="id,periodeid,dato")}
    votes = fetch_all("Afstemning")
    parsed = failed = 0
    together = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    examples = []
    for vote in votes:
        sides = parties_by_side(vote["konklusion"])
        if sides is None:
            failed += 1
            if len(examples) < 5:
                examples.append(vote["konklusion"])
            continue
        parsed += 1
        session = code.get(moeder[vote["mødeid"]]["periodeid"])
        position = {}
        for side, names in sides.items():
            for party in names:
                position[party] = side
        ordered = sorted(position)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                cell = together[session][f"{a}-{b}"]
                cell[0] += position[a] == position[b]
                cell[1] += 1
    pairs = ["S-V", "DF-V", "KF-V", "EL-S", "S-SF", "DF-S", "M-S"]
    table = {
        session: {p: round(c[p][0] / c[p][1], 3) for p in pairs if p in c and c[p][1] >= 10}
        for session, c in sorted(together.items())
    }
    return {"parsed": parsed, "failed": failed, "failed_examples": examples, "agreement": table}


def debate_files():
    names = Counter()
    for path in XML_CACHE.rglob("*.xml"):
        names[re.sub(r"^\d+_M\d+_?", "", path.name)] += 1
    return dict(names.most_common(10))


def exchanges():
    """Pairs (challenger -> speaker holding the floor) from the chair's short-remark calls.

    Rule: in a debate, a member speech followed by a chair turn announcing a short
    remark, followed by a different member, is one challenge. Regex only; to be
    validated by hand in Phase 3.
    """
    rng = random.Random(831)
    table = {}
    shown = []
    minister_parties = defaultdict(Counter)
    for folder in sorted(XML_CACHE.iterdir()):
        n_pairs = cross_party = words = n_files = 0
        kinds = Counter()
        for path in folder.glob("*.xml"):
            n_files += 1
            turns = list(speeches(path))
            for s in turns:
                words += len(s["text"].split())
                if (s["role"] or "") == "minister":
                    minister_parties[folder.name][s["party"] or "(blank)"] += 1
            for floor, chair, challenger in zip(turns, turns[1:], turns[2:]):
                if "formand" not in (chair["role"] or "").lower():
                    continue
                if not REMARK.search(chair["text"]) or NO_REMARKS.search(chair["text"]):
                    continue
                if "formand" in (floor["role"] or "").lower():
                    continue
                if "formand" in (challenger["role"] or "").lower():
                    continue
                if floor["last"] == challenger["last"] and floor["first"] == challenger["first"]:
                    continue
                n_pairs += 1
                cross_party += bool(floor["party"] and challenger["party"]
                                    and floor["party"] != challenger["party"])
                kinds["floor_is_minister"] += floor["role"] == "minister"
                kinds["same_party"] += bool(floor["party"]) and floor["party"] == challenger["party"]
                kinds["s_v_members"] += {floor["party"], challenger["party"]} == {"S", "V"}
                kinds["v_or_s_to_minister"] += (challenger["party"] in {"S", "V"}
                                                and floor["role"] == "minister")
                if rng.random() < 0.012:
                    shown.append({
                        "file": path.name, "floor": f"{floor['first']} {floor['last']} ({floor['party']})",
                        "chair": chair["text"][:160],
                        "challenger": f"{challenger['first']} {challenger['last']} ({challenger['party']})",
                        "challenge": challenger["text"][:200],
                    })
        table[folder.name] = {"files": n_files, "pairs": n_pairs,
                              "cross_party": cross_party, "words": words, **kinds}
    return {
        "by_session": table, "examples": shown,
        "parties_of_speaking_ministers": {k: dict(v.most_common(6))
                                          for k, v in sorted(minister_parties.items())},
    }


def pooled_rates():
    """Vote-weighted rates from recon_numbers.json, leaving out sessions under 14 sampled votes."""
    rows = json.loads((ROOT / "docs" / "recon_numbers.json").read_text(encoding="utf-8"))
    sample = [r for r in rows["party_line_sample"] if r["sampled_votes"] >= 14]
    total = sum(r["sampled_votes"] for r in sample)
    keys = ["share_contested", "share_votes_with_any_rebel", "rebel_share_of_cast", "absent_share"]
    pooled = {k: round(sum(r[k] * r["sampled_votes"] for r in sample) / total, 4) for k in keys}
    xml = rows["debate_xml"]
    sampled_mb = sum(p.stat().st_size for p in XML_CACHE.rglob("*.xml")) / 1e6
    words = sum(r.get("words", 0) for r in xml)
    speech_count = sum(r.get("speeches", 0) for r in xml)
    total_mb = sum(r["mb"] for r in xml)
    corpus = {
        "xml_files": sum(r["files"] for r in xml), "total_mb": round(total_mb, 1),
        "sampled_mb": round(sampled_mb, 1), "sampled_words": words, "sampled_speeches": speech_count,
        "chair_share_of_speeches": round(sum(r.get("chair", 0) for r in xml) / speech_count, 3),
        "chair_share_of_words": round(sum(r.get("chair_words", 0) for r in xml) / words, 3),
        "estimated_total_words": round(words / sampled_mb * total_mb),
        "estimated_total_speeches": round(speech_count / sampled_mb * total_mb),
        "name_match_rate": round(sum(r["name_matches_aktoer"] for r in xml)
                                 / sum(r["with_name"] for r in xml), 3),
        "mention_exact_resolve_rate": round(sum(r.get("mentions_resolved_exact", 0) for r in xml)
                                            / sum(r.get("mentions", 0) for r in xml), 3),
    }
    return {"votes_used": total, **pooled, "corpus": corpus}


def main():
    results = {
        "pooled": pooled_rates(),
        "file_name_suffixes": debate_files(),
        "party_agreement": party_agreement(),
        "exchanges": exchanges(),
    }
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results["file_name_suffixes"], ensure_ascii=False))
    print(json.dumps(results["pooled"], ensure_ascii=False))
    totals = Counter()
    for row in results["exchanges"]["by_session"].values():
        totals.update({k: v for k, v in row.items()})
    print("exchange totals", dict(totals))
    agreement = results["party_agreement"]
    print("konklusion parsed", agreement["parsed"], "failed", agreement["failed"])
    for example in agreement["failed_examples"]:
        print("  failed:", repr(example)[:160])
    for session, row in agreement["agreement"].items():
        print(session, row)
    for session, row in results["exchanges"]["by_session"].items():
        print(session, row, results["exchanges"]["parties_of_speaking_ministers"].get(session))
    for example in results["exchanges"]["examples"]:
        print(json.dumps(example, ensure_ascii=False))


if __name__ == "__main__":
    main()
