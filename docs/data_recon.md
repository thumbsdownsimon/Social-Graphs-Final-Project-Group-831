# Data reconnaissance: Folketing open data (oda.ft.dk)

> **Note added after the analysis:** the party-agreement numbers in section 4 come from a first parser that mishandled lists ending in "og" and names with initials. The fixed parser is in `tools/build_dataset.py`, and final numbers are in `data/results/network.json`. This file records the first look at the data.

Probed on 4 November 2026 (1,995 API requests, 09:17 to 09:38 UTC, logged in `data-raw/oda/requests.log`; 68 debate XML files by FTP, not logged there but kept in `data-raw/oda_referat/`).

Numbers come from `tools/recon_oda.py` (`docs/recon_numbers.json`) and `tools/recon_feasibility.py` (`docs/recon_feasibility.json`). Rerun both with:

```
python tools/recon_oda.py
python tools/recon_feasibility.py
```

**Votes, debates and bills are sampled here (seed 831).** Rates and estimates below are for choosing a project and are not results. Nothing here has been hand-checked by the group yet.

## 1. Entities and ids

| Entity | Rows | | Entity | Rows |
|---|---:|---|---|---:|
| Aktør | 18,429 | | Sagstrin | 225,754 |
| AktørAktør | 169,577 | | SagAktør | 426,948 |
| Periode | 163 | | Dokument | 1,021,465 |
| Afstemning | 10,536 | | Fil | 692,193 |
| Stemme | 1,840,932 | | Møde | 14,048 (2,618 plenary) |
| Sag | 99,806 | | Dagsordenspunkt | 34,702 |
| Emneord | 49,252 | | EmneordSag | 276,491 |

**Field names** (non-ASCII is real): `Stemme(id, typeid, afstemningid, aktørid)`, `Afstemning(id, nummer, konklusion, vedtaget, kommentar, mødeid, typeid, sagstrinid)`, `Aktør(id, typeid, gruppenavnkort, navn, fornavn, efternavn, biografi, periodeid, startdato, slutdato)`, `AktørAktør(fraaktørid, tilaktørid, startdato, slutdato, rolleid)`, `SagAktør(aktørid, sagid, rolleid)`, `Møde(id, titel, dato, statusid, typeid, periodeid)`.

**Type and role ids**

- **Aktørtype:** 3 Udvalg, 4 Folketingsgruppe, 5 Person (3,414), 12 Privatperson (4,835; excluded on privacy grounds), 1 Ministerområde, 2 Ministertitel, 8 Ministerium.
- **Stemmetype:** 1 For, 2 Imod, 3 Fravær, 4 Hverken for eller imod.
- **Afstemningstype:** 1 Endelig vedtagelse (6,100), 2 Udvalgsindstilling (14), 3 Forslag til vedtagelse (928), 4 Ændringsforslag (3,494).
- **AktørAktørRolle:** 15 medlem, 16 formand, 10 stedfortræder, 8 Minister, 3 Tidligere minister, 22 minister ej MF.
- **SagAktørRolle:** 16 Forslagsstiller (priv.), 19 Forslagsstiller (reg.), 10 Spørger, 17 Til, 23 Besvaret af, 14 Minister, 1 Taler.
- **Sagstype:** 3 Lovforslag (5,340), 5 Beslutningsforslag (3,928), 10 § 20-spørgsmål (58,599), 9 Forslag til vedtagelse, 2 Forespørgsel.

**Example vote**

```json
{"id": 10612, "nummer": 2, "vedtaget": true, "mødeid": 16186, "typeid": 3, "sagstrinid": 277241,
 "konklusion": "Vedtaget For stemte 69 (S, SF, M, EL, RV, ALT, N, IA), imod stemte 44 (V, DF, LA, KF, DD, BP, Nadja Natalie Isaksen (UFG), Jacob Harris (UFG)), hverken for eller imod stemte 0"}
```

## 2. Time coverage

- **Sessions:** a session is a `Periode` row with `type = 'samling'` (101 rows from 1952). `finans` rows reuse the same `kode`, so always filter on type.
- **Votes:** 30 sessions from 2004-05 to 2026-27, and every vote maps to a plenary meeting. Full sessions have about 300 to 740 votes; 2025-26 (1), cut short, has 192. The shortest sessions (20071, 20102, 20182, 20221) have 1 to 4.
- **Debate XML:** from session 20091 (autumn 2009) on, so there are no debate transcripts for the 2004 to 2008 votes.
- **Open sessions:** 2025-26 (2) has 41 votes and 2026-27 has 1 so far. Debate files there are partly provisional.

## 3. Where the text is

**Debate transcripts (the main text).** Anonymous FTP at `ftp://oda.ft.dk/ODAXML/Referat/samling/<session>/`, one `<session>_M<nn>_helemoedet.xml` per sitting.

- **Size:** 1,889 files and 1,214 MB across 23 sessions.
- **Estimate:** about 86 million words and 820,000 speech turns, scaled up from a sample of 68 files (38.6 MB). This is rough because file sizes vary.
- **Chair turns:** 52% of turns but only 6% of words, so they must be removed or handled separately.
- **Each `Tale` carries:** first and last name, party short name, role (`medlem`, `minister`, `formand`), start and end timestamps, edit status, and through its agenda item a case number and stage.
- **Access:** we reached these by FTP. Linking them through `Fil` and `Møde` was not tested; `Dokument` type 8 (Referat) has 3,245 rows.

**Linking speakers to `Aktør`**

- **Use names, not `tingdokID`.** That attribute is missing before session 20182 and is not a person id: `100643` is not an `Aktør` id, and 14 ids map to more than one name (`525272` covers Kaare Dybvad Bek, Mattias Tesfaye and Morten Bødskov, which looks like a ministerial office).
- **Exact full-name match:** 96.8% of named speeches overall, about 93 to 96% before 2019 and 98 to 99.7% after. The misses have not been inspected.
- **Risk:** this rate measures matching, not correctness, because 54 names are shared by more than one person record.

**Other text**

| Source | Coverage | Notes |
|---|---|---|
| `Sag.resume` | Lovforslag 5,306 of 5,340; Beslutningsforslag 3,890 of 3,928 | Good, clean summaries |
| `Sag.resume` for § 20 questions | 128 of 58,599 | Effectively empty; the question wording is in `Dokument.titel` |
| `Aktør.biografi` | 2,020 of 3,414 persons | XML. Also holds birth date, emails and family details, so we keep only what we need and publish none of that |
| Documents | Links only | `Fil.filurl` points to a PDF even when `format` says DOCX |

## 4. Does the voting data support a question?

Sample: 20 votes per session, 505 votes in total, of which 494 fall in sessions with at least 14 sampled votes and are used for the pooled rates.

| Measure | Pooled rate |
|---|---:|
| Votes with both For and Imod | 77.9% |
| Votes with at least one rebel | 9.1% |
| Rebel votes as a share of votes cast | **0.13%** |
| Rows recorded as Fravær (absent) | 40.4% |

- **Individual votes carry almost no signal.** A rebel is a member voting against their party's majority. A member-level agreement network would mostly recover the parties, so seed A as written fails.
- **The rebel rate is a lower bound.** 5 to 18% of votes cast before session 20222 had no party lookup (0% afterwards), and those votes cannot count as rebellions.
- **Absence looks structural.** It is steady near 40%, roughly 70 of 179 seats per vote. It may reflect a pairing arrangement rather than opinion, which we have not verified, so absence should not count as disagreement.

**Party agreement is where votes move.** `Afstemning.konklusion` names each party's side, so this needs no `Stemme` download. It parsed for 7,629 of 10,536 votes, from about session 20101 on. The other 2,907 use an older tally format without party names.

Share of parsed votes where S and V took the same side:

| 2010-11 | 2015-16 | 2019-20 | 2020-21 | 2021-22 | 2022-23 (2) | 2023-24 | 2024-25 | 2025-26 (1) | 2025-26 (2) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.55 | 0.79 | 0.83 | 0.72 | 0.69 | **1.00** | **1.00** | **1.00** | **1.00** | 0.78 |

This jump is expected, since parties in one government vote together. The change-of-government dates still need to be derived from the data (minister roles in `AktørAktør`). The last column rests on only 41 votes.

## 5. Who challenges whom: a network the data offers directly

In debates, the chair calls members for a short remark (`kort bemærkning`) directed at whoever holds the floor. That gives a directed edge: challenger to floor speaker.

- **Rule:** member speech, then a chair turn that announces a short remark, then a different member.
- **First version failed.** It matched "there are *no* short remarks", and 4 of 6 examples were wrong. The tightened rule excludes those cases.
- **Spot check:** Claude read 14 random pairs from the tightened rule and all 14 looked like real challenges. This is an agent's reading of a small sample, and recall was not measured. It does not replace a hand check by the group.
- **Volume:** 1,473 pairs in 68 sampled files, so very roughly 40,000 to 46,000 since 2009.
- **Adversarial by nature:** among pairs with both parties known, 3 of 1,136 are within one party. Communities of this raw network should not be expected to recover parties.
- **Minister gap:** ministers have a blank party label in every sampled speech (22% of pairs have a minister on the floor). Their party must come from `Aktør` memberships.
- **Thin cells:** S and V members challenged each other 62 times in the sample, but only 8 of those fall in sessions 20171 to 20221 and 0 in the 15 files from 20222 on. Any one party pair may be too sparse to test alone.

**Named mentions** (`hr.`/`fru` plus a name) are also available, but less promising than short remarks. 83.9% resolve exactly; misses include possessives (`Touborgs`) and changed names (`Ammitzbøll` to `Ammitzbøll-Bille`). Their frequency appears to fall over time, from 497 mentions in the 2009-10 sample to 94 in 2025-26 (1), and whether that is real is untested.

## 6. Party switchers and co-sponsorship

- **Switchers:** 56 of 782 members since 2004-05 change party short name between sessions, 28 of them via UFG (outside the party groups). Examples: Lars Løkke Rasmussen V to UFG to M, Pernille Vermund NB to UFG to LA, and a cluster moving DF to DD around 2021-22. Moves within one session are not caught yet.
- **Co-sponsorship** (sample of 30 Beslutningsforslag per session):

| Session | Beslutningsforslag | Mean proposers | Multi-party | Lovforslag | § 20 questions |
|---|---:|---:|---:|---:|---:|
| 2019-20 | 185 | 4.6 | 17% | 251 | 1,880 |
| 2022-23 (2) | 122 | 5.3 | 47% | 146 | 865 |
| 2024-25 | 184 | 5.5 | 20% | 262 | 1,565 |

With 30 bills per session, the multi-party shares are noisy.

## 7. Size

- **Members:** 146 to 210 people per session (above 179 because substitutes count), 782 people since 2004-05.
- **Full vote download:** about 18,400 requests, about 3 hours at the observed rate.
- **Suggested subset:** sessions 20171 to 20252, covering three changes of parliament and well inside the course's node sweet spot. That is 4,391 votes (about 7,900 requests, about 80 minutes), 1,008 debate files (643 MB, roughly 45 million words) and very roughly 18,000 challenges.

## 8. Traps

| Trap | What happens | What to do |
|---|---|---|
| Missing `$` in a query option | `filter=...` without `%24` is **silently ignored and returns every row** | `oda_client.py` always encodes `%24`; sanity-check counts |
| Invalid field in `$filter` | Returns HTTP 400, so the claim that it returns everything is wrong as stated | The missing `$` above is the likely source of that claim |
| `$expand=Stemme` | Silently cut to 100 of 179 rows | Fetch `Stemme` separately with paging |
| `$top` above 100 | Returns 100 rows plus a next link | `fetch_all` pages and verifies the count |
| `resume ne null` | Matches every row, since empty text is `""` | Use `length(field) gt 0` |
| Votes with no `Stemme` rows | Seen in samples from 3 sessions; a few votes have 144, 176, 178 or 180 rows, not 179 | Report coverage per session |
| `Aktør.startdato/slutdato` | Not career dates (Søren Gade: 2026-10-07 to 2026-10-22) | Use memberships per session |
| Membership rows | Stored in both directions; 801 of 5,673 have a null start | Take one direction and date by the group's session |
| Party is per session | Each party has one group `Aktør` per session (`periodeid`); UFG has one per person | Join on session and group by `gruppenavnkort` |
| Dangling and junk actors | 3 of Søren Gade's 84 linked ids do not resolve; one group is named `fejloprettet` | Tolerate and count them |
| Name variants | `Louise Elholm` / `Louise Schack Elholm`, `Lisbeth Bech Poulsen` / `Lisbeth Bech-Nielsen`, suffixes such as `(udpeget af V)` | Build an alias table and hand-check it |
| Party labels in XML | Blank for ministers | Use `Aktør` memberships |
| Chair text | Half of all turns | Filter by role, since the chair's name is otherwise counted as a member speaking |

## 9. Terms of use

The live page (`www.ft.dk/dokumenter/aabne_data`) returns a Cloudflare challenge to scripts, and we did not try to get past it. Simon opened it in a browser on 4 November 2026 and supplied the current text, which covers the same points as a Wayback Machine copy of 20 June 2025.

What the terms say:

- **Use:** free worldwide use, including copying, publishing and combining. Use of the data counts as acceptance.
- **Credit:** Folketinget must be named as the source.
- **Endorsement:** do not imply that Folketinget endorses us, and do not use its logo.
- **Law:** use must comply with Danish law, including data protection rules. Data that Folketinget withdraws must be deleted by us as well.
- **Transcripts:** we must tell readers whether a transcript is provisional or final. Transcripts may not be altered more than the use requires, and speakers keep the sole right to publish collections of their own speeches.
- **Load:** use must not strain the service.

**What this means for us**

- **Provisional or final:** each speech has `EdixiStatus`. All sampled files before 2025-26 say `Typeset`; recent ones also say `Proofed` and `Released`. The mapping to provisional or final is not confirmed, so it must be settled before publishing.
- **Quotes on the site:** keep them short and verbatim, and do not publish one person's speeches as a collection.
- **Withdrawn data:** the deletion table the terms mention was not found under the name `Slettet`.
