# Dataset

Collected on 4 November 2026 from Folketinget's open data (`oda.ft.dk`). What was collected, when and how many records is logged in `docs/collection_log.json`. All counts below come from `docs/dataset_numbers.json`, `docs/collection_log.json` or `data/site.json`.

**Source: Folketinget.** Folketinget has not endorsed or reviewed this project.

## What is in it

| Table | Rows | File | Committed? |
|---|---:|---|---|
| Speech turns with text | 824,720 (85.7M words) | `data-raw/derived/speeches.parquet` | No, 275 MB |
| Challenges (who challenged whom), no text | 45,529 | `data/challenges.parquet` | Yes |
| Members (id and name) | see file | `data/members.parquet` | Yes |
| Party positions per vote | 7,625 votes | `data/party_positions.parquet` | Yes |
| Governments, derived from minister roles | 8 periods | `data/governments.json` | Yes |
| Name aliases | 16 | `data/name_aliases.csv` | Yes |
| Individual member votes | 741,402 rows, 4,391 votes | `data-raw/tables/member_votes.json` | No |
| Party memberships | 4,173 | `data-raw/tables/memberships.json` | No |
| Committee memberships | 21,316 | `data-raw/tables/committee_memberships.json` | No |
| Raw debate XML | 1,878 files, 1,206 MB | `data-raw/oda_referat/` | No |

Rerun `tools/collect.py` to get everything in `data-raw/`.

## Filters and scope

- **Debates:** sessions 2009-10 to 2025-26, all plenary sittings. XML starts in 2009-10. Session 2026-27 is left out because it has only just begun.
- **Member votes:** sessions 2017-18 to 2025-26, because each vote costs about two API requests and party positions for all other votes come from the summaries.
- **Party positions:** votes from about 2010 on. 2,907 older votes have a tally with no party names.
- **Backbench speech for language:** role `medlem` only, no chair and no ministers, at least 30 words, party known. That leaves 310,441 turns, 63.3M words and 600 speakers. Names of people and parties are removed first.
- **Usable challenges:** 43,336 of 45,529, with both people and parties known and neither side a non-party label such as UFG (outside the party groups).
- **Never collected:** biographies, because they hold birth dates, contact details and family information. Private persons (`Aktørtype` 12) are also excluded.

## How the tables are joined

- **Speakers to people:** by name, since `tingdokID` in the XML is not a person id. Share of turns by method: exact name 95.9%, exact name plus seated that session 2.6%, hand-listed alias 1.2%, matching name parts among members seated that session 0.2%, others under 0.05%. All turns by people resolve. The group's hand check of 57 sampled matches is pending (`labeling/name_resolution.csv`).
- **Party:** the transcript's party tag first, then the membership for that session and date, then the nearest session with a membership. 78.7% of minister turns use membership, 15.9% the nearest session, and 4.9% have no party. Where both exist, tag and membership agree on nearly all of 702,481 compared turns, with 17 disagreements in an earlier build. Both come from Folketinget's own records, so this is a weak check.
- **Governments:** parties holding at least two ministers on a date, from minister roles and memberships. The list matches our background knowledge of formations through 2022. The 2026 formation is beyond that knowledge, so it rests on the data alone. One 2026 minister is listed as EL, from a 2017 membership, and we treat that party as outside government.
- **Challenges:** a member's turn, then a chair turn announcing a short remark (not "no short remarks"), then a different member. A reading of 14 random pairs by the agent found all 14 to be real challenges. The group's precision and recall sheets are pending.

## Known biases and gaps

- **Missed challenges.** Follow-up remarks the chair announces in other words, and spoken question time, are not edges. `labeling/challenge_missed.csv` estimates how many.
- **Uneven activity.** Challenges per session range from 2 to over 5,000, and they are far denser in 2009-13. All comparisons are against nulls within a period, not raw counts over time.
- **Short sessions.** Those at elections hold very little, and the 2026 government has 204 usable challenges, which is too few for testing.
- **Ministers.** About 20% of challenges have a minister on the floor, so changes in government also change who can be challenged. We rerun every test on backbenchers only.
- **Turnover.** Members change between periods. We rerun tests on members seen in both periods.
- **Absence.** About 40% of member vote rows are absences. We did not verify why, and never treat them as a position.
- **Missing vote rows.** 249 of 4,391 votes since 2017 have no individual rows. A few others have 176 to 180 rows rather than 179.
- **Membership gaps.** Some members who spoke have no membership row in some sessions. This is why the transcript tag comes first for party, and it means the rebel rate is a lower bound.
- **Provisional transcripts.** Folketinget revises these without marking changes. The status field is undocumented. We treat `Typeset` as final, which is an inference. Most `Proofed` turns are in 2025-26, and a few older turns also carry that status. Numbers from recent sessions could change.
- **Damaged source file.** `20222_M62_helemoedet.xml` is malformed at the source. It is read with a recovering parser, so a passage in one chair turn may be garbled.
- **Vote summary typos.** Three tokens in the summaries are not party codes. They are logged in `docs/dataset_numbers.json` and dropped.

## Terms of use

Folketinget's terms (read on 4 November 2026) allow free use including publication. They require crediting Folketinget, not implying endorsement, not using its logo, complying with Danish law including data protection, deleting withdrawn data, not straining the service, and telling readers whether a transcript is provisional or final. Downloads were throttled to at most one API request per half second and one file per second. The site shows no transcript text.
