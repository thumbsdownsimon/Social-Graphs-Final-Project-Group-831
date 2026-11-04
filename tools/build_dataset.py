#!/usr/bin/env python3
"""Step 2 of the pipeline: turn the raw downloads into clean tables.

    python tools/build_dataset.py

Reads data-raw/ (from collect.py). Writes:
  data-raw/derived/speeches.parquet   every turn with its text (large, not committed)
  data/challenges.parquet             who challenged whom, no text
  data/members.parquet                people who spoke or belong to a party group
  data/party_positions.parquet        each party's side on each vote, from the vote summary
  data/governments.json               which parties held ministers, and when
  docs/dataset_numbers.json           every count quoted in docs/dataset.md
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from lxml import etree as lxml_etree

ROOT = Path(__file__).resolve().parents[1]
RAW_TABLES = ROOT / "data-raw" / "tables"
XML_DIR = ROOT / "data-raw" / "oda_referat"
DERIVED_RAW = ROOT / "data-raw" / "derived"
DATA = ROOT / "data"
ALIASES = ROOT / "data" / "name_aliases.csv"
NUMBERS = ROOT / "docs" / "dataset_numbers.json"
LAST_SESSION = "20252"  # 2026-27 has only just begun; recon_oda.py left sample files for it on disk

REMARK = re.compile(r"korte? bemærkning", re.I)
NO_REMARKS = re.compile(r"(ikke|ingen)[^.]{0,40}bemærkning", re.I)
SUFFIX = re.compile(r"\s*\(.*?\)\s*$")
# Vote summaries come in two formats: "For stemte 96 (S, V)" and "96 stemmer for forslaget (S, V)".
SIDE_NEW = re.compile(r"(hverken for eller imod|for|imod) stemte (\d+)\s*(?:\(([^)]*)\)?)?", re.I)
SIDE_OLD = re.compile(r"(\d+) stemmer (hverken for eller imod|for|imod) forslaget\s*(?:\(([^)]*)\)?)?", re.I)
# Individually named members, including initials and particles: "Jan E. Jørgensen (V)".
NAMED_MEMBER = re.compile(r"[A-ZÆØÅÖÄÜÉ][\w\-.]*(?:\s+(?:[A-ZÆØÅÖÄÜÉ][\w\-.]*|von|van|de|af))+\s*\([^()]*\),?")
PARTY_CODE = re.compile(r"^[A-ZÆØÅa-zæøå]{1,5}$")
MAX_DROPPED_TOKENS = 5  # typos in the source; more than this means the parser has broken

sys.stdout.reconfigure(encoding="utf-8")
numbers = {}
dropped_tokens = []


def load(name):
    return json.loads((RAW_TABLES / f"{name}.json").read_text(encoding="utf-8"))


def clean_name(name):
    return " ".join(SUFFIX.sub("", name or "").lower().split())


def parse_file(path):
    """One dict per speech turn in a debate file, in document order."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        # Source errors, such as garbled tags inside a chair turn in 20222_M62: keep what parses.
        root = lxml_etree.parse(str(path), lxml_etree.XMLParser(recover=True)).getroot()
        numbers.setdefault("files_repaired", []).append(path.name)
    meeting = root.find("MetaMeeting")
    session = meeting.findtext("ParliamentarySession")
    number = meeting.findtext("MeetingNumber")
    date = (meeting.findtext("DateOfSitting") or "")[:10]
    turns = []
    for item in root.iter("DagsordenPunkt"):
        meta = item.find("MetaFTAgendaItem")
        item_no = meta.findtext("ItemNo") if meta is not None else None
        case = meta.findtext("FTCaseNumber") if meta is not None else None
        title = meta.findtext("ShortTitle") if meta is not None else None
        for tale in item.iter("Tale"):
            speaker = tale.find("Taler/MetaSpeakerMP")
            field = (lambda tag: (speaker.findtext(tag) or "").strip()) if speaker is not None else (lambda tag: "")
            segments = tale.findall("TaleSegment")
            text = " ".join((c.text or "").strip() for seg in segments for c in seg.iter("Char"))
            text = " ".join(text.split())
            status = next((s.text for s in tale.iter("EdixiStatus")), None)
            turns.append({
                "session": session, "meeting": int(number), "date": date, "item": item_no,
                "case_number": case or None, "item_title": title, "turn": len(turns),
                "first": field("OratorFirstName"), "last": field("OratorLastName"),
                "xml_party": field("GroupNameShort") or None, "role": field("OratorRole") or None,
                "status": status,
                "start": tale.findtext("TaleSegment/MetaSpeechSegment/StartDateTime"),
                "end": tale.findtext("TaleSegment/MetaSpeechSegment/EndDateTime"),
                "words": len(text.split()), "text": text,
            })
    return turns


def build_speeches():
    rows = []
    for path in sorted(XML_DIR.rglob("*.xml")):
        if path.parent.name <= LAST_SESSION:
            rows += parse_file(path)
    frame = pd.DataFrame(rows)
    frame["is_chair"] = frame["role"].fillna("").str.lower().str.contains("formand")
    frame["is_minister"] = frame["role"].fillna("").str.lower().str.contains("minister")
    frame["is_person"] = (frame["role"].fillna("").str.lower() == "medlem") | frame["is_minister"] | frame["is_chair"]
    numbers["roles_in_xml"] = frame["role"].fillna("(blank)").value_counts().to_dict()
    numbers["debate_files_parsed"] = int(frame.groupby(["session", "meeting"]).ngroups)
    print("turns", len(frame), "files", numbers["debate_files_parsed"], flush=True)
    return frame


class Resolver:
    """Maps a name in the transcript to an Aktør person id.

    In order: a hand-checked alias, an exact full name, then the same last name with
    all shared first-name tokens among people who sat in that session. Several people
    with one name are told apart by who held a seat in that session. Every speech
    records which method resolved it.
    """

    def __init__(self, persons, groups, memberships, sessions):
        code = {s["id"]: s["kode"] for s in sessions}
        group_session = {g["id"]: code[g["periodeid"]] for g in groups if g["periodeid"] in code}
        self.session_order = sorted(set(group_session.values()))
        self.seated = defaultdict(set)
        self.member_rows = defaultdict(list)
        group_party = {g["id"]: g["gruppenavnkort"] for g in groups}
        for row in memberships:
            session = group_session.get(row["tilaktørid"])
            if session:
                self.seated[session].add(row["fraaktørid"])
                self.member_rows[(session, row["fraaktørid"])].append(
                    (row["startdato"], row["slutdato"], group_party.get(row["tilaktørid"])))
        self.by_name = defaultdict(set)
        self.names = {}
        for person in persons:
            self.names[person["id"]] = person["navn"]
            for name in {person["navn"], f"{person['fornavn']} {person['efternavn']}"}:
                self.by_name[clean_name(name)].add(person["id"])
        self.aliases = {}
        if ALIASES.exists():
            for row in pd.read_csv(ALIASES, comment="#").itertuples():
                self.aliases[clean_name(row.xml_name)] = int(row.person_id)

    def resolve(self, full, session, xml_party=None):
        name = clean_name(full)
        if not name:
            return None, "blank"
        if name in self.aliases:
            return self.aliases[name], "alias"
        candidates = self.by_name.get(name, set())
        if len(candidates) == 1:
            return next(iter(candidates)), "exact"
        if len(candidates) > 1:
            seated = candidates & self.seated[session]
            if len(seated) == 1:
                return next(iter(seated)), "exact_seated"
            # Two people with one name in one session (Malte Larsen, S and DF): the party decides.
            same_party = [p for p in seated if any(r[2] == xml_party for r in self.member_rows[(session, p)])]
            if xml_party and len(same_party) == 1:
                return same_party[0], "exact_party"
            # Ministers without a seat that session (Dan Jørgensen): the record that ever held one.
            ever_seated = [p for p in candidates if any(p in people for people in self.seated.values())]
            if not seated and len(ever_seated) == 1:
                return ever_seated[0], "exact_ever_seated"
            return None, "ambiguous"
        tokens = set(name.replace("-", " ").split())
        last = name.split()[-1]
        matches = []
        for person in self.seated[session]:
            other = clean_name(self.names.get(person))
            other_tokens = set(other.replace("-", " ").split())
            if other.split()[-1:] == [last] and (tokens <= other_tokens or other_tokens <= tokens):
                matches.append(person)
        if len(matches) == 1:
            return matches[0], "tokens_seated"
        return None, "unresolved"

    def party(self, person, session, date):
        """The party a person belonged to on a date; mid-session moves use the row dates."""
        rows = self.member_rows.get((session, person), [])
        if not rows:
            return None
        dated = [r for r in rows if r[0] and r[0][:10] <= date and (not r[1] or date <= r[1][:10])]
        return (dated or rows)[-1][2]

    def nearest_party(self, person, session):
        """Party from the closest session with a membership; for ministers without a seat."""
        order = self.session_order
        position = order.index(session) if session in order else len(order)
        seated_in = [i for i, code in enumerate(order) if (code, person) in self.member_rows]
        if not seated_in:
            return None
        closest = min(seated_in, key=lambda i: (abs(i - position), -i))
        return self.member_rows[(order[closest], person)][-1][2]


def add_people(frame, resolver):
    unique = frame.loc[frame["is_person"], ["session", "first", "last", "xml_party"]].drop_duplicates()
    found = {}
    for row in unique.itertuples():
        party = row.xml_party if pd.notna(row.xml_party) else None
        found[(row.session, row.first, row.last, party)] = resolver.resolve(
            f"{row.first} {row.last}", row.session, party)
    keys = [(s, f, l, x if pd.notna(x) else None) for s, f, l, x in
            zip(frame["session"], frame["first"], frame["last"], frame["xml_party"])]
    frame["person"] = [found.get(k, (None, None))[0] for k in keys]
    frame["name_method"] = [found.get(k, (None, "not_a_person"))[1] for k in keys]
    frame["member_party"] = [
        resolver.party(int(p), s, d) if pd.notna(p) else None
        for p, s, d in zip(frame["person"], frame["session"], frame["date"])
    ]
    frame["nearest_party"] = [
        resolver.nearest_party(int(p), s) if pd.notna(p) and pd.isna(x) and pd.isna(m) else None
        for p, s, x, m in zip(frame["person"], frame["session"], frame["xml_party"], frame["member_party"])
    ]
    frame["party"] = frame["xml_party"].where(frame["xml_party"].notna(), frame["member_party"])
    frame["party"] = frame["party"].where(frame["party"].notna(), frame["nearest_party"])
    frame["party_source"] = "none"
    frame.loc[frame["nearest_party"].notna(), "party_source"] = "nearest_session"
    frame.loc[frame["member_party"].notna(), "party_source"] = "membership"
    frame.loc[frame["xml_party"].notna(), "party_source"] = "transcript"

    people = frame[frame["is_person"]]
    numbers["name_methods_share_of_turns"] = people["name_method"].value_counts(normalize=True).round(4).to_dict()
    missing = people[people["person"].isna()]
    numbers["unresolved_names_top"] = (
        (missing["first"] + " " + missing["last"]).value_counts().head(60).to_dict())
    both = people[people["xml_party"].notna() & people["member_party"].notna()]
    numbers["party_xml_vs_membership"] = {
        "compared_turns": len(both),
        "agree": round(float((both["xml_party"] == both["member_party"]).mean()), 4),
        "top_disagreements": (both.loc[both["xml_party"] != both["member_party"], ["xml_party", "member_party"]]
                              .value_counts().head(10).rename(lambda v: v).reset_index().to_dict("records")),
    }
    non_chair = people[~people["is_chair"]]
    numbers["party_source_share_of_non_chair_turns"] = non_chair["party_source"].value_counts(normalize=True).round(4).to_dict()
    numbers["party_source_share_of_minister_turns"] = (
        non_chair.loc[non_chair["is_minister"], "party_source"].value_counts(normalize=True).round(4).to_dict())
    return frame


def build_challenges(frame):
    """Challenger -> floor speaker: member turn, chair calls a short remark, different member."""
    rows = []
    seen_calls = 0
    for (session, meeting), turns in frame.groupby(["session", "meeting"], sort=False):
        records = turns.to_dict("records")
        for floor, chair, challenger in zip(records, records[1:], records[2:]):
            if not chair["is_chair"] or floor["is_chair"] or challenger["is_chair"]:
                continue
            if not floor["is_person"] or not challenger["is_person"]:
                continue
            if not REMARK.search(chair["text"]) or NO_REMARKS.search(chair["text"]):
                continue
            seen_calls += 1
            if (floor["first"], floor["last"]) == (challenger["first"], challenger["last"]):
                continue
            rows.append({
                "session": session, "meeting": meeting, "date": challenger["date"],
                "item": challenger["item"], "case_number": challenger["case_number"],
                "turn": challenger["turn"], "floor_person": floor["person"],
                "floor_party": floor["party"], "floor_is_minister": floor["is_minister"],
                "challenger_person": challenger["person"], "challenger_party": challenger["party"],
                "challenger_is_minister": challenger["is_minister"], "challenger_words": challenger["words"],
                "status": challenger["status"],
            })
    table = pd.DataFrame(rows)
    numbers["challenges"] = {
        "chair_calls_matched": seen_calls, "edges": len(table),
        "both_people_resolved": int((table["floor_person"].notna() & table["challenger_person"].notna()).sum()),
        "both_parties_known": int((table["floor_party"].notna() & table["challenger_party"].notna()).sum()),
        "same_party": int((table["floor_party"] == table["challenger_party"]).sum()),
        "floor_is_minister": int(table["floor_is_minister"].sum()),
        "per_session": table.groupby("session").size().to_dict(),
    }
    print(numbers["challenges"], flush=True)
    return table


def parties_by_side(conclusion):
    """{'for': {...}, 'imod': {...}, 'hverken': {...}} from a vote summary, or None if unparseable."""
    text = NAMED_MEMBER.sub("", conclusion or "")
    found = [(label, names) for label, _, names in SIDE_NEW.findall(text)]
    found += [(label, names) for _, label, names in SIDE_OLD.findall(text)]
    sides = {}
    for label, names in found:
        # Lists end either "S, V, M" or "S, V og M".
        tokens = {n.strip() for n in re.split(r",|\bog\b", names or "") if n.strip()}
        sides[label.lower().split()[0]] = {t for t in tokens if PARTY_CODE.match(t)}
        dropped_tokens.extend(t for t in tokens if not PARTY_CODE.match(t))
    return sides if "for" in sides and "imod" in sides else None


def build_party_positions(sessions):
    code = {s["id"]: s["kode"] for s in sessions}
    meetings = {m["id"]: m for m in load("meetings")}
    rows, failed = [], 0
    for vote in load("votes"):
        sides = parties_by_side(vote["konklusion"])
        meeting = meetings.get(vote["mødeid"])
        if sides is None or meeting is None:
            failed += 1
            continue
        for side, parties in sides.items():
            for party in parties:
                rows.append({"vote": vote["id"], "session": code.get(meeting["periodeid"]),
                             "date": meeting["dato"][:10], "vote_type": vote["typeid"],
                             "party": party, "side": side})
    table = pd.DataFrame(rows)
    if len(dropped_tokens) > MAX_DROPPED_TOKENS:
        raise ValueError(f"Vote summaries parsed into impossible party names: {dropped_tokens[:20]}")
    numbers["party_positions"] = {"votes_parsed": int(table["vote"].nunique()), "votes_unparsed": failed,
                                  "first_session": str(table["session"].min()), "tokens_dropped": dropped_tokens,
                                  "party_codes": table["party"].value_counts().to_dict()}
    return table


def build_governments(resolver, sessions):
    """Intervals of which parties held ministers, from minister roles and party memberships."""
    titles = {t["id"] for t in load("minister_titles")}
    spells = set()
    for row in load("minister_roles"):
        a, b = row["fraaktørid"], row["tilaktørid"]
        person = a if b in titles else b if a in titles else None
        if person is not None and row["startdato"]:
            spells.add((person, row["startdato"][:10], (row["slutdato"] or "9999")[:10]))
    # Some finished spells were never closed (Carsten Hansen, 2011 onwards). An open spell
    # only counts if it began at the latest formation: the last day five ministers started.
    starts = Counter(s for _, s, _ in spells)
    latest = max(d for d, n in starts.items() if n >= 5)
    spells = {(p, s, e) for p, s, e in spells if e != "9999" or s >= latest}
    boundaries = sorted({d for (_, s, e) in spells for d in (s, e) if d != "9999" and d >= "2009-10-01"})
    code_on = lambda date: max((x["kode"] for x in sessions if x["type"] == "samling" and x["startdato"][:10] <= date), default=None)
    intervals = []
    for start in boundaries:
        active = {p for (p, s, e) in spells if s <= start < e}
        if not active:
            continue
        code = code_on(start)
        counts = Counter(resolver.party(p, code, start) or resolver.nearest_party(p, code) for p in active)
        unknown = counts.pop(None, 0)
        # One minister from a party is too thin to call it a government party: flag for reading.
        parties = sorted(k for k, n in counts.items() if n >= 2)
        if not intervals or intervals[-1]["parties"] != parties:
            intervals.append({"from": start, "parties": parties, "minister_counts": dict(counts),
                              "single_minister_parties": sorted(k for k, n in counts.items() if n == 1),
                              "ministers_without_party": unknown})
    (DATA / "governments.json").write_text(json.dumps(intervals, ensure_ascii=False, indent=1), encoding="utf-8")
    numbers["governments"] = intervals
    for row in intervals:
        print(row, flush=True)


def main():
    DATA.mkdir(exist_ok=True)
    DERIVED_RAW.mkdir(parents=True, exist_ok=True)
    sessions = [s for s in load("sessions")]
    resolver = Resolver(load("persons"), load("party_groups"), load("memberships"), sessions)
    speeches = add_people(build_speeches(), resolver)
    speeches.to_parquet(DERIVED_RAW / "speeches.parquet")
    build_challenges(speeches).to_parquet(DATA / "challenges.parquet")
    ids = sorted(set(speeches["person"].dropna().astype(int)) | {
        p for (_, p) in resolver.member_rows})
    pd.DataFrame({"person": ids, "name": [resolver.names.get(i) for i in ids]}).to_parquet(
        DATA / "members.parquet")
    if (RAW_TABLES / "meetings.json").exists():
        build_party_positions(sessions).to_parquet(DATA / "party_positions.parquet")
    if (RAW_TABLES / "minister_roles.json").exists():
        build_governments(resolver, sessions)
    NUMBERS.write_text(json.dumps(numbers, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
