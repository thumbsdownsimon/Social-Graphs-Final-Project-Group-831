#!/usr/bin/env python3
"""Step 1 of the pipeline: download everything we use from the Folketing open data.

    python tools/collect.py            # all steps; safe to rerun, cached items are skipped
    python tools/collect.py tables     # or one of: tables, debates, votes, committees

Writes raw data to data-raw/ (not committed) and what we collected, when and how
many records to docs/collection_log.json (committed).

Scope, and why:
  debates  sessions 20091-20252. Debate XML starts in 20091. 20261 has just begun.
  votes    individual Stemme rows for sessions 20171-20252 only: party-level positions
           for all votes come from Afstemning.konklusion, so member votes are only
           needed around the most recent changes of government, and each vote costs
           about two requests.
Biographies are never downloaded: they hold birth dates, contact details and family
information that we do not need.
"""
import ftplib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oda_client import ROOT, fetch_all

TABLES = ROOT / "data-raw" / "tables"
XML_DIR = ROOT / "data-raw" / "oda_referat"
LOG = ROOT / "docs" / "collection_log.json"
FTP_HOST = "oda.ft.dk"
FTP_DIR = "/ODAXML/Referat/samling"
FTP_PAUSE_SECONDS = 1.0
FIRST_DEBATE_SESSION, LAST_SESSION = "20091", "20252"
FIRST_VOTE_SESSION = "20171"
PERSON_FIELDS = "id,typeid,navn,fornavn,efternavn,opdateringsdato"
GROUP_FIELDS = "id,typeid,navn,gruppenavnkort,periodeid,startdato,slutdato"
MEMBER_ROLE, MINISTER_ROLES = 15, (8, 22)

sys.stdout.reconfigure(encoding="utf-8")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_step(step, **facts):
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}
    log[step] = {"finished_utc": now(), **facts}
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(step, facts, flush=True)


def save_table(name, rows):
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def load_table(name):
    return json.loads((TABLES / f"{name}.json").read_text(encoding="utf-8"))


def session_rows():
    """Parliamentary sessions only: 'finans' rows in Periode reuse the same kode."""
    return sorted((p for p in fetch_all("Periode") if p["type"] == "samling"),
                  key=lambda p: p["startdato"])


def collect_tables():
    sessions = session_rows()
    wanted = {p["id"] for p in sessions if FIRST_DEBATE_SESSION <= p["kode"] <= LAST_SESSION}
    save_table("sessions", sessions)

    persons = fetch_all("Aktør", filter="typeid eq 5", select=PERSON_FIELDS)
    save_table("persons", persons)

    groups = [g for g in fetch_all("Aktør", filter="typeid eq 4", select=GROUP_FIELDS)
              if g["periodeid"] in wanted]
    save_table("party_groups", groups)

    # Memberships are stored in both directions; the group on the `til` side gives each once.
    memberships = []
    for group in groups:
        memberships += fetch_all(
            "AktørAktør", filter=f"tilaktørid eq {group['id']} and rolleid eq {MEMBER_ROLE}")
    save_table("memberships", memberships)

    ministers = []
    for role in MINISTER_ROLES:
        ministers += fetch_all("AktørAktør", filter=f"rolleid eq {role}")
    save_table("minister_roles", ministers)
    titles = fetch_all("Aktør", filter="typeid eq 2", select=GROUP_FIELDS)
    save_table("minister_titles", titles)

    meetings = fetch_all("Møde", filter="typeid eq 1", select="id,periodeid,dato,nummer,titel")
    save_table("meetings", meetings)
    votes = fetch_all("Afstemning")
    save_table("votes", votes)
    log_step("tables", sessions_in_scope=len(wanted), persons=len(persons),
             party_groups=len(groups), memberships=len(memberships),
             minister_roles=len(ministers), minister_titles=len(titles),
             plenary_meetings=len(meetings), votes_all_sessions=len(votes))


def ftp_connect():
    ftp = ftplib.FTP(FTP_HOST, timeout=180)
    ftp.login()
    ftp.encoding = "latin-1"
    ftp.cwd(FTP_DIR)
    return ftp


def ftp_listing(ftp):
    """{session: [(file name, size in bytes), ...]} for sessions in scope."""
    listing = {}
    for session in sorted(ftp.nlst()):
        if not FIRST_DEBATE_SESSION <= session <= LAST_SESSION:
            continue
        lines = []
        ftp.dir(session, lines.append)
        listing[session] = [(line.split()[-1], int(line.split()[2])) for line in lines
                            if line.split()[2].isdigit() and line.lower().endswith(".xml")]
    return listing


def collect_debates():
    ftp = ftp_connect()
    listing = ftp_listing(ftp)
    fetched = skipped = 0
    for session, files in listing.items():
        folder = XML_DIR / session
        folder.mkdir(parents=True, exist_ok=True)
        for name, size in files:
            path = folder / name
            if path.exists() and path.stat().st_size == size:
                skipped += 1
                continue
            for attempt in range(5):
                try:
                    partial = path.with_suffix(".part")
                    with open(partial, "wb") as handle:
                        ftp.retrbinary(f"RETR {session}/{name}", handle.write)
                    partial.replace(path)
                    break
                except (ftplib.Error, OSError, EOFError) as error:
                    print("retry", name, repr(error), flush=True)
                    time.sleep(2 ** attempt)
                    ftp = ftp_connect()
            else:
                raise RuntimeError(f"Could not download {name}")
            fetched += 1
            time.sleep(FTP_PAUSE_SECONDS)
        print(session, len(files), "files", flush=True)
    ftp.quit()
    log_step("debates", sessions=len(listing), files=sum(len(f) for f in listing.values()),
             megabytes=round(sum(s for f in listing.values() for _, s in f) / 1e6, 1),
             fetched_this_run=fetched, already_cached=skipped,
             per_session={k: len(v) for k, v in listing.items()})


def collect_votes():
    sessions = load_table("sessions")
    in_scope = {p["id"]: p["kode"] for p in sessions
                if FIRST_VOTE_SESSION <= p["kode"] <= LAST_SESSION}
    meeting_session = {m["id"]: m["periodeid"] for m in load_table("meetings")}
    votes = [v for v in load_table("votes") if meeting_session.get(v["mødeid"]) in in_scope]
    rows, empty = [], 0
    for i, vote in enumerate(votes):
        got = fetch_all("Stemme", filter=f"afstemningid eq {vote['id']}")
        empty += not got
        rows += [{"vote": r["afstemningid"], "person": r["aktørid"], "type": r["typeid"]} for r in got]
        if i % 250 == 0:
            print("votes", i, "of", len(votes), flush=True)
    save_table("member_votes", rows)
    log_step("votes", first_session=FIRST_VOTE_SESSION, last_session=LAST_SESSION,
             votes=len(votes), rows=len(rows), votes_without_rows=empty)


def collect_committees():
    """Who sat on which committee, per session; used to test what network communities mean."""
    sessions = load_table("sessions")
    wanted = {p["id"]: p["kode"] for p in sessions if FIRST_DEBATE_SESSION <= p["kode"] <= LAST_SESSION}
    committees = [c for c in fetch_all("Aktør", filter="typeid eq 3", select=GROUP_FIELDS)
                  if c["periodeid"] in wanted and (c["navn"] or "").endswith("udvalget")]
    rows = []
    for committee in committees:
        members = fetch_all("AktørAktør", filter=f"tilaktørid eq {committee['id']} and "
                                                 f"(rolleid eq 14 or rolleid eq {MEMBER_ROLE} or rolleid eq 16)")
        rows += [{"person": m["fraaktørid"], "committee": committee["navn"],
                  "session": wanted[committee["periodeid"]]} for m in members]
    save_table("committee_memberships", rows)
    log_step("committees", committees=len(committees), memberships=len(rows))


def main():
    steps = {"tables": collect_tables, "debates": collect_debates, "votes": collect_votes,
             "committees": collect_committees}
    for name in sys.argv[1:] or steps:
        steps[name]()


if __name__ == "__main__":
    main()
