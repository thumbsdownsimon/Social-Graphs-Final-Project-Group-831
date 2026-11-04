#!/usr/bin/env python3
"""Phase 1 reconnaissance of the Folketing open data. Writes docs/recon_numbers.json.

Answers, with counts: which sessions have votes and debates, how party-line the
votes are, how many members switch party, whether debate speakers link to Aktør
records, and how much cross-party co-sponsorship exists.

Votes, debates and bills are SAMPLED here (fixed seed); nothing in this script is a
final result. Responses are cached (see oda_client.py), so a rerun costs nothing.

    python tools/recon_oda.py
"""
import ftplib
import json
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oda_client import CACHE, ROOT, build_url, count, fetch_all, get_json

FTP_HOST = "oda.ft.dk"
FTP_DIR = "/ODAXML/Referat/samling"
XML_CACHE = ROOT / "data-raw" / "oda_referat"
OUT = ROOT / "docs" / "recon_numbers.json"
SEED = 831
VOTES_PER_SESSION = 20
XML_PER_SESSION = 3
FIRST_SESSION = "20041"
BILLS_PER_SESSION = 30
BILL_SESSIONS = {"2019-20": 151, "2022-23": 158, "2024-25": 163}

MENTION = re.compile(r"\b(?:hr\.|Hr\.|fru|Fru)\s+((?:[A-ZÆØÅ][\w\-]+\s+){0,3}[A-ZÆØÅ][\w\-]+)")
KORT = re.compile(r"kort bemærkning|korte bemærkning", re.I)

sys.stdout.reconfigure(encoding="utf-8")
results = {}


def save():
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def sessions():
    """Parliamentary sessions (type 'samling'); the same `kode` is reused by 'finans' rows."""
    rows = [p for p in fetch_all("Periode") if p["type"] == "samling"]
    return sorted(rows, key=lambda p: p["startdato"])


def votes_by_session(session_rows):
    moeder = fetch_all("Møde", filter="typeid eq 1", select="id,periodeid,dato")
    meeting = {m["id"]: m for m in moeder}
    votes = fetch_all("Afstemning")
    grouped = defaultdict(list)
    unmapped = 0
    for vote in votes:
        m = meeting.get(vote["mødeid"])
        if m is None:
            unmapped += 1
        else:
            grouped[m["periodeid"]].append(vote)
    code = {p["id"]: p for p in session_rows}
    table = []
    for pid, rows in grouped.items():
        p = code.get(pid)
        table.append({
            "periodeid": pid, "kode": p["kode"] if p else None,
            "titel": p["titel"] if p else None, "votes": len(rows),
            "types": dict(Counter(r["typeid"] for r in rows)),
        })
    table.sort(key=lambda r: r["kode"] or "")
    results["votes_by_session"] = table
    results["votes_unmapped_to_plenary_meeting"] = unmapped
    print("sessions with votes", len(table), "first", table[0]["kode"], "unmapped", unmapped)
    save()
    return grouped


def memberships(session_rows):
    """{periodeid: {person id: group actor}} from party groups (Aktørtype 4, role 15 'medlem').

    Each membership is stored twice (A->B and B->A), so we keep the row where the
    group is the `til` side and de-duplicate. Dates are often null, so the session
    of the group actor is what we use as the time stamp.
    """
    wanted = {p["id"] for p in session_rows if p["kode"] >= FIRST_SESSION}
    groups = fetch_all("Aktør", filter="typeid eq 4",
                       select="id,navn,gruppenavnkort,periodeid,startdato,slutdato")
    groups = [g for g in groups if g["periodeid"] in wanted]
    member_of = defaultdict(dict)
    null_dates = total = 0
    for group in groups:
        rows = fetch_all("AktørAktør", filter=f"tilaktørid eq {group['id']} and rolleid eq 15")
        for row in rows:
            total += 1
            null_dates += row["startdato"] is None
            member_of[group["periodeid"]][row["fraaktørid"]] = group
    results["membership"] = {
        "party_group_actors": len(groups), "rows": total, "rows_with_null_start": null_dates,
        "members_per_session": {str(k): len(v) for k, v in sorted(member_of.items())},
    }
    print("memberships", total, "null start", null_dates)
    save()
    return member_of


def party_switchers(member_of, session_rows):
    """People whose party (short name) changes between sessions, ignoring UFG -> same party."""
    order = {p["id"]: p["kode"] for p in session_rows}
    history = defaultdict(list)
    for pid in sorted(member_of, key=lambda i: order[i]):
        for person, group in member_of[pid].items():
            history[person].append((order[pid], group["gruppenavnkort"]))
    switchers = {}
    for person, seq in history.items():
        parties = [party for _, party in seq if party]
        changes = [(a, b) for a, b in zip(parties, parties[1:]) if a != b]
        if changes:
            switchers[person] = seq
    to_ufg = sum(any(party == "UFG" for _, party in seq) for seq in switchers.values())
    named = {}
    for person in list(switchers)[:400]:
        v = get_json(build_url("Aktør", filter=f"id eq {person}", select="id,navn"))["value"]
        named[v[0]["navn"] if v else str(person)] = [
            f"{code}:{party}" for code, party in switchers[person]
            if code >= "20191"
        ]
    results["party_switchers"] = {
        "people_with_any_membership": len(history), "people_changing_party": len(switchers),
        "of_which_via_UFG": to_ufg, "recent_histories": {k: v for k, v in named.items() if v},
    }
    print("switchers", len(switchers), "of", len(history))
    save()


def sample_party_line(grouped, member_of, session_rows):
    rng = random.Random(SEED)
    table = []
    for p in session_rows:
        votes = grouped.get(p["id"], [])
        if p["kode"] < FIRST_SESSION or not votes:
            continue
        sample = rng.sample(votes, min(VOTES_PER_SESSION, len(votes)))
        n_rebel_votes = n_contested = n_rebels = n_cast = n_absent = no_party = n_rows = 0
        rows_per_vote = []
        for vote in sample:
            rows = fetch_all("Stemme", filter=f"afstemningid eq {vote['id']}")
            rows_per_vote.append(len(rows))
            by_group = defaultdict(list)
            sides = set()
            for r in rows:
                n_rows += 1
                if r["typeid"] == 3:
                    n_absent += 1
                    continue
                n_cast += 1
                sides.add(r["typeid"])
                group = member_of[p["id"]].get(r["aktørid"])
                if group is None:
                    no_party += 1
                else:
                    by_group[group["gruppenavnkort"]].append(r["typeid"])
            rebels = 0
            for party, cast in by_group.items():
                if party == "UFG":
                    continue
                rebels += len(cast) - Counter(cast).most_common(1)[0][1]
            n_rebels += rebels
            n_rebel_votes += rebels > 0
            n_contested += 1 in sides and 2 in sides
        table.append({
            "kode": p["kode"], "titel": p["titel"], "sampled_votes": len(sample),
            "rows_per_vote_min": min(rows_per_vote), "rows_per_vote_max": max(rows_per_vote),
            "share_contested": n_contested / len(sample),
            "share_votes_with_any_rebel": n_rebel_votes / len(sample),
            "rebel_share_of_cast": n_rebels / max(n_cast, 1),
            "absent_share": n_absent / max(n_rows, 1),
            "cast_without_party_lookup": no_party / max(n_cast, 1),
        })
        results["party_line_sample"] = table
        save()
        print(p["kode"], {k: round(v, 3) for k, v in table[-1].items() if isinstance(v, float)})


def persons():
    rows = fetch_all("Aktør", filter="typeid eq 5", select="id,navn,fornavn,efternavn")
    names = Counter(r["navn"].strip().lower() for r in rows if r["navn"])
    results["persons"] = {
        "person_actors": len(rows),
        "duplicate_names": {k: v for k, v in names.items() if v > 1},
        "biografi_nonempty": count("Aktør", "typeid eq 5 and length(biografi) gt 0"),
    }
    print("persons", len(rows), "dup names", sum(v > 1 for v in names.values()))
    save()
    return rows


def ftp_listing():
    ftp = ftplib.FTP(FTP_HOST, timeout=120)
    ftp.login()
    ftp.encoding = "latin-1"
    ftp.cwd(FTP_DIR)
    listing = {}
    for session in sorted(ftp.nlst()):
        lines = []
        ftp.dir(session, lines.append)
        files = [(line.split()[-1], int(line.split()[2])) for line in lines
                 if line.split()[2].isdigit()]
        listing[session] = files
    return ftp, listing


def speeches(path):
    """Yield one dict per Tale in a debate XML file, in document order."""
    root = ET.parse(path).getroot()
    for item in root.iter("DagsordenPunkt"):
        meta = item.find("MetaFTAgendaItem")
        case = meta.findtext("FTCaseNumber") if meta is not None else None
        for tale in item.iter("Tale"):
            speaker = tale.find("Taler/MetaSpeakerMP")
            text = " ".join(c.text or "" for seg in tale.findall("TaleSegment")
                            for c in seg.iter("Char"))
            status = [s.text for s in tale.iter("EdixiStatus")]
            yield {
                "tingdok": speaker.get("tingdokID") if speaker is not None else None,
                "first": (speaker.findtext("OratorFirstName") or "").strip() if speaker is not None else "",
                "last": (speaker.findtext("OratorLastName") or "").strip() if speaker is not None else "",
                "party": speaker.findtext("GroupNameShort") if speaker is not None else None,
                "role": speaker.findtext("OratorRole") if speaker is not None else None,
                "case": case, "text": text, "status": status[0] if status else None,
                "start": tale.findtext("TaleSegment/MetaSpeechSegment/StartDateTime"),
            }


def debate_xml(person_rows):
    rng = random.Random(SEED)
    ftp, listing = ftp_listing()
    known = {(r["navn"] or "").strip().lower(): r["id"] for r in person_rows}
    table = []
    tingdok_names = defaultdict(set)
    examples = []
    for session, files in listing.items():
        xml_files = [f for f in files if f[0].lower().endswith(".xml")]
        row = {
            "session": session, "files": len(xml_files),
            "mb": round(sum(size for _, size in xml_files) / 1e6, 1),
        }
        tally = Counter()
        status = Counter()
        roles = Counter()
        chosen = rng.sample(xml_files, min(XML_PER_SESSION, len(xml_files)))
        for name, _ in chosen:
            path = XML_CACHE / session / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "wb") as handle:
                    ftp.retrbinary(f"RETR {session}/{name}", handle.write)
            previous = None
            for s in speeches(path):
                tally["speeches"] += 1
                tally["words"] += len(s["text"].split())
                status[s["status"]] += 1
                roles[s["role"]] += 1
                full = f"{s['first']} {s['last']}".strip().lower()
                is_chair = (s["role"] or "").lower() in {"formand", "næstformand"} or \
                    "formand" in (s["role"] or "").lower()
                if s["tingdok"]:
                    tally["with_tingdok"] += 1
                    tingdok_names[s["tingdok"]].add(full)
                if full:
                    tally["with_name"] += 1
                    tally["name_matches_aktoer"] += full in known
                tally["with_party"] += bool(s["party"])
                tally["with_case"] += bool(s["case"])
                tally["with_start_time"] += bool(s["start"])
                if is_chair:
                    tally["chair"] += 1
                    tally["chair_words"] += len(s["text"].split())
                    tally["chair_announces_short_remark"] += bool(KORT.search(s["text"]))
                else:
                    for match in MENTION.findall(s["text"]):
                        tally["mentions"] += 1
                        tally["mentions_resolved_exact"] += match.strip().lower() in known
                        if len(examples) < 12 and rng.random() < 0.02:
                            examples.append({"speaker": full, "mention": match, "session": session})
                    if previous and previous != full:
                        tally["speaker_changes_in_debate"] += 1
                    previous = full
        row.update(tally)
        row["status"] = dict(status)
        row["top_roles"] = dict(roles.most_common(5))
        row["sampled_files"] = len(chosen)
        table.append(row)
        results["debate_xml"] = table
        save()
        print(session, row["files"], row["mb"], "sp", tally["speeches"],
              "match", tally["name_matches_aktoer"], "/", tally["with_name"])
    ftp.quit()
    results["tingdok_ids"] = {
        "distinct": len(tingdok_names),
        "with_more_than_one_name": {k: sorted(v) for k, v in tingdok_names.items() if len(v) > 1},
    }
    results["mention_examples"] = examples
    save()


def cosponsorship(member_of):
    rng = random.Random(SEED)
    out = {}
    for label, pid in BILL_SESSIONS.items():
        bills = fetch_all("Sag", filter=f"typeid eq 5 and periodeid eq {pid}", select="id,nummer")
        sample = rng.sample(bills, min(BILLS_PER_SESSION, len(bills)))
        sizes, party_counts = [], []
        for bill in sample:
            rows = fetch_all("SagAktør", filter=f"sagid eq {bill['id']} and rolleid eq 16")
            sizes.append(len(rows))
            party_counts.append(len({
                member_of[pid][r["aktørid"]]["gruppenavnkort"]
                for r in rows if r["aktørid"] in member_of[pid]
            }))
        out[label] = {
            "beslutningsforslag": len(bills), "sampled": len(sample),
            "mean_proposers": sum(sizes) / max(len(sizes), 1),
            "share_with_zero_proposers": sum(s == 0 for s in sizes) / max(len(sizes), 1),
            "share_multi_party": sum(c > 1 for c in party_counts) / max(len(party_counts), 1),
            "lovforslag": count("Sag", f"typeid eq 3 and periodeid eq {pid}"),
            "paragraf20_questions": count("Sag", f"typeid eq 10 and periodeid eq {pid}"),
        }
        print(label, out[label])
    results["cosponsorship_sample"] = out
    save()


def text_fields():
    out = {}
    for label, entity, flt in [
        ("sag_lovforslag", "Sag", "typeid eq 3"),
        ("sag_beslutningsforslag", "Sag", "typeid eq 5"),
        ("sag_par20", "Sag", "typeid eq 10"),
    ]:
        out[label] = {
            "rows": count(entity, flt),
            "resume_nonempty": count(entity, f"{flt} and length(resume) gt 0"),
            "resume_ne_null_matches": count(entity, f"{flt} and resume ne null"),
        }
    results["text_fields"] = out
    print(out)
    save()


def api_behaviour():
    out = {}
    expanded = get_json(build_url("Afstemning", filter="id eq 10612", expand="Stemme"))
    out["expand_stemme_rows_returned"] = len(expanded["value"][0]["Stemme"])
    out["stemme_rows_for_same_vote"] = count("Stemme", "afstemningid eq 10612")
    out["top_1000_rows_returned"] = len(get_json(build_url("Stemme", top=1000))["value"])
    results["api_behaviour"] = out
    print(out)
    save()


def main():
    results["note"] = "Sampled reconnaissance only, seed %d. See docs/data_recon.md." % SEED
    results["totals"] = {e: count(e) for e in [
        "Aktør", "AktørAktør", "Periode", "Afstemning", "Stemme", "Sag", "Sagstrin", "SagAktør",
        "Dokument", "Fil", "Møde", "Dagsordenspunkt", "Emneord", "EmneordSag",
    ]}
    save()
    api_behaviour()
    text_fields()
    session_rows = sessions()
    grouped = votes_by_session(session_rows)
    person_rows = persons()
    debate_xml(person_rows)
    member_of = memberships(session_rows)
    party_switchers(member_of, session_rows)
    cosponsorship(member_of)
    sample_party_line(grouped, member_of, session_rows)
    print("done; cache at", CACHE)


if __name__ == "__main__":
    main()
