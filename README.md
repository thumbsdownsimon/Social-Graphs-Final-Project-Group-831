# Crossing the Aisle

**Question:** when a change of government makes parties vote together, do their members' floor challenges and language follow?

**Finding:** when parties enter government together, challenges between their members fall about 3-fold relative to chance within a quarter or two, and come back when they split. Their language shifts far less clearly.

**Status: preliminary.** The group's hand labels are not done, so the challenge rule's accuracy and the tone of challenges are unvalidated. The site shows a "Validation pending" banner until the labels are scored. See [What is left to do](#what-is-left-to-do).

Final project for DTU 02805 Social Graphs and Interactions, group 831: Christian Colberg (s224343), Yuen Yi Hui (s226465), Simon Jonsson (s224331).

**Data source: Folketinget**, through [oda.ft.dk](https://oda.ft.dk/). Folketinget has not endorsed or reviewed this project.

## Contents

- [Results](#results)
- [How the project works](#how-the-project-works)
- [How to run it](#how-to-run-it)
- [What is left to do](#what-is-left-to-do)
- [Project history](#project-history)
- [Where things are](#where-things-are)

## Results

Each row compares party pairs that entered government together or split with pairs whose relation did not change at the same formation, across six formations from 2011 to 2022.

| Measure | Moved as expected | p (one-sided) |
|---|---:|---:|
| Floor challenges | 14 of 14 pairs | < 0.0001 |
| Challenges, backbenchers only | 14 of 14 pairs | < 0.0001 |
| Challenges, same members before and after | 10 of 10 pairs | < 0.0001 |
| Votes on contested items | 13 of 14 pairs | < 0.0001 |
| Language: similarity within the same debate | 13 of 14 pairs | < 0.0001 |
| Language: telling two parties apart by classifier | 3 of 8 pairs | 0.12 |

- **Clearest case:** S and V challenged each other 623 times before governing together (489 expected by chance) and 22 times during (135 expected).
- **Votes set up the question:** only about 0.14% of member votes went against the member's party in 2019–26, and member votes add nothing beyond party.
- **Language is mixed:** the two language methods disagree, and S–V similarity barely moved in 2022 after rising for years beforehand. The clearest signal is the vocabulary of being in opposition: words like `ministeren` and `regeringen`.
- **Communities:** the challenge network has clear communities that barely match party. Their debate topics read like policy areas, but that is our reading of title words with weak quantitative support.

Limitations are listed on the site and in `docs/dataset.md`. The main ones are few events, a rule-based network whose accuracy is not yet hand-checked, and no measure of tone yet.

## How the project works

### The idea

Danish members almost never vote against their party, so a member-level voting network mostly recovers the parties. The floor is different. After a speech, the chair can call a member for a *kort bemærkning*, a short remark aimed at whoever holds the floor. Reading those calls from the transcripts gives a directed network of who challenges whom, which we compare with votes and language across changes of government.

### Where the data comes from

| Data | Source | Scope | Size |
|---|---|---|---|
| Debate transcripts (XML) | `ftp://oda.ft.dk/ODAXML/Referat/samling/` | Sessions 2009-10 to 2025-26 | 1,878 files, 1,206 MB |
| Votes, including party positions in the summary text | `Afstemning` in the API | All sessions; party names from about 2010 | 10,536 votes, 7,625 with party positions |
| Individual member votes | `Stemme` in the API | Sessions 2017-18 to 2025-26 | 741,402 rows over 4,391 votes |
| People, party groups and memberships | `Aktør`, `AktørAktør` | Party memberships per session | 3,414 people, 4,173 memberships |
| Minister roles | `AktørAktør` | Used to derive governments | 961 rows |
| Committee memberships | `AktørAktør` | Per session | 21,316 rows |

Biographies were never downloaded, because they hold birth dates, contact details and family information we do not need.

Downloads are throttled to at most one API request per half second and one FTP file per second. Every API response is cached in `data-raw/`, so reruns do not hit the service again. `docs/collection_log.json` records what was collected, when and how many records.

### What each step does

`tools/run_all.py` runs these in order and stops at the first failure.

| # | Script | What it does | Writes |
|---|---|---|---|
| 1 | `collect.py` | Downloads tables, debate XML, member votes and committees | `data-raw/`, `docs/collection_log.json` |
| 2 | `build_dataset.py` | Parses speeches, resolves names to people, assigns parties, extracts challenges, parses party positions, derives governments | `data-raw/derived/speeches.parquet`, `data/*.parquet`, `data/governments.json`, `docs/dataset_numbers.json` |
| 3 | `make_labeling_sheets.py` | Draws the samples for hand labeling; never overwrites an existing sheet | `labeling/*.csv` |
| 4 | `analyze_network.py` | Party mixing against nulls, assortativity, communities, changes at each formation, quarterly timelines | `data/results/network.json` |
| 5 | `analyze_votes.py` | Rebel rates and the member vote network | `data/results/votes.json` |
| 6 | `analyze_language.py` | Party classifier, sentence embeddings within debates, distinctive words | `data/results/language.json` |
| 7 | `analyze_role.py` | Opposition vocabulary and a government/opposition classifier | `data/results/role.json` |
| 8 | `summarize.py` | Puts all layers on a common placebo scale, with permutation tests | `data/results/summary.json` |
| 9 | `check_labels.py` | Scores the group's hand labels | `data/results/label_checks.json` |
| 10 | `validate.py` | Toy-case tests and independent recounts; stops the run if any check fails | `data/results/validation.json` |
| 11 | `export_site.py` | Gathers everything the site draws | `data/site.json` |
| 12 | `make_notebook.py` | Writes and runs the results notebook | `notebooks/analysis.ipynb` |

Two more scripts are not part of the pipeline: `recon_oda.py` and `recon_feasibility.py` produced the first look at the data in `docs/data_recon.md`, and `progress.py` shows live progress of a run.

### The key modeling decisions

- **A challenge edge:** a member's turn, then a chair turn announcing a short remark (not "no short remarks"), then a different member.
- **Speakers to people:** by name, because `tingdokID` in the XML is not a person id. Name changes are in `data/name_aliases.csv`.
- **Party:** the transcript's tag first, then the session's membership, then the nearest session. Ministers have no tag.
- **Governments:** parties holding at least two ministers on a date. A "window" is the time between two formations.
- **The nulls:** challenges are compared with shuffling the floor speaker, which keeps how many challenges each member made and received. A stricter version shuffles within each debate.
- **The placebo:** at each formation, pairs that joined or split are compared with pairs whose relation did not change. Relation labels are shuffled within formations for the p-values.
- **Language:** backbench speech only, with names of people and parties removed. Text goes through `paraphrase-multilingual-MiniLM-L12-v2` in 60-word chunks, because 90-word chunks were silently truncated.

`AI_METHODS.md` gives what each measure captures, what it misses, how it was checked and the result.

## How to run it

### View the site

```
python -m http.server
```

Run that in the repo folder and open `http://localhost:8000`. The site is `index.html`, `assets/` and `data/site.json`, with no build step.

### Rerun everything

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python tools\run_all.py
```

Commands are for Windows; on macOS or Linux use `.venv/bin/`. A first run downloads everything and takes several hours. A rerun with the downloads and embeddings saved took under an hour on a 16-core CPU. The downloads can be stopped at any time; rerunning skips what is already saved. A run from a completely empty `data-raw/` has not been tested.

To rerun just one download step, use `tools\collect.py tables`, `debates`, `votes` or `committees`.

To watch a run:

```
.venv\Scripts\python tools\run_all.py > run_all.log 2>&1
.venv\Scripts\python tools\progress.py run_all.log
```

Run the second command in another window.

### Score the hand labels

Fill in `labeling/*.csv` following `labeling/README.md`, saving as UTF-8 CSV under the same names. Then:

```
.venv\Scripts\python tools\check_labels.py
.venv\Scripts\python tools\export_site.py
```

The banner clears once all four sheets are scored. To keep the notebook in step, also run `tools\make_notebook.py`.

## What is left to do

1. **Label the four sheets in `labeling/`.** No model may do this. A second person labels `challenge_stance` separately and saves it as `challenge_stance_second.csv`, so we can report agreement.

   | Sheet | Rows | What you decide |
   |---|---:|---|
   | `challenge_precision` | 60 | Is this edge really a challenge to the speaker holding the floor? |
   | `challenge_missed` | 60 | Did the rule miss a challenge here? |
   | `challenge_stance` | 60 | Is the tone hostile, neutral or friendly? |
   | `name_resolution` | 57 | Is this the same person? |

   If the challenge rule scores under 90% precise, that is the abandon condition set in advance. The fallback project is the party-switcher question, which uses the same data.
2. **Read what the agent interpreted.** That means the claim that communities are policy areas, the aliases in `data/name_aliases.csv`, and the 2026 government's parties, which come from the data alone. Update the site and `AI_METHODS.md` if you disagree.
3. **Publish.** Enable GitHub Pages under Settings → Pages → `main`, root folder. The repo may need to be public for that. Then check the site and its links live.
4. **Write the exam hand-in.** The paper, three slides and reflection are due Fri 27 Nov 2026, with presentations on 2 Dec. The reference list needs a proper literature search, in particular on Danish parliamentary debate and voting.
5. **Make sure everyone can explain the code.** The presentation tests this, and any group member can be asked.

## Project history

All of this happened on 4 November 2026 unless noted. An AI agent (Claude Code) did the work below under the group's direction. Times are in UTC.

### 1. Orientation
The agent read the group's go-nuts site (`colberg00.github.io`) for its theme and reusable methods. The project brief named that repo as the place to work, and the first scripts went there. The group pointed out that this repo is the project's home, so everything was moved here and the go-nuts repo was left as it was. Only the theme file and the group's student ids were reused.

### 2. Reconnaissance (09:17–09:38)
The agent probed the API and FTP server, documented in `docs/data_recon.md`. It found:
- Debate XML exists for every sitting since 2009, with speaker, party, role and timestamps.
- Only about 0.13% of cast votes in a sample were rebel votes, so the seed idea of a member voting network would mostly recover parties.
- The API has silent traps. A missing `$` returns every row, `$expand=Stemme` cuts off at 100 rows, and `resume ne null` matches empty text. The brief's claim that an invalid filter returns everything was wrong as stated: it returns HTTP 400.
- `www.ft.dk` blocks scripts, so the terms were first read from an archived copy. The group then confirmed the current text from the live page.

The first version of the challenge rule was wrong on 4 of 6 examples, because it matched "there are no short remarks". It was tightened before moving on.

### 3. Choosing the question
The agent proposed three candidates: this one, predicting party switches from language, and co-sponsorship topics. The group chose this one and decided the site lives in this repo's Pages, with names and student ids. The group makes all commits.

### 4. Building the dataset (09:52–11:49, plus committees later)
Debates were widened from the proposed 2017 start to 2009, which added the 2011 and 2015 formations as comparison events at no API cost. Downloads were paused twice while the group moved between buildings, and resumed from the saved data without losing any. Committee memberships were added later to test what the network communities mean.

Problems found and fixed while building:
- One source file, `20222_M62`, is malformed at the source. It is read with a recovering parser and logged.
- Names needed an alias table, because of name changes such as Mai Henriksen to Mai Mercado.
- Minister records needed cleaning. Some were never closed, and party lookups could go stale. After fixes, the derived formation dates match the actual ones through 2022.
- Labeling sheets were drawn three times from stale data, because a failed build did not stop the next command. Those unlabeled sheets were deleted and redrawn from the full corpus.

### 5. Analysis
The network analysis came first, and the challenge result was strong straight away. Then:
- A cross-check failed and led the agent to read the raw vote text, which exposed **two real parser bugs**: lists ending in "og" created fake parties, and names with initials cut off the parties after them. Headline S–V numbers had looked fine. Both were fixed, and the build now fails if parsing produces many non-party tokens. The cross-check was replaced with a truly independent one using individual member votes.
- A truncation check found **38% of 90-word chunks were cut off silently** by the encoder. Chunks were shortened to 60 words, which gave 0.0% truncated in a sample of 3,000.
- The language run was also slowed by a very large regex for removing names, which was rewritten.
- The agent first told the group language "barely" tracks government changes. A formal test showed that was too strong across formations, because similarity moved the expected way for 13 of 14 pairs. It was corrected. The S–V case in 2022 is the weak one.

### 6. The site
Five figures were built, each with its check beside it, then tested in a browser at desktop and phone widths. Testing caught several things:
- The headline's "5-fold" mixed joins and splits. For parties entering together, the sentence it describes, the median is about 3-fold, so the headline was corrected.
- Small disconnected fragments squashed the network drawing, so only the largest connected part of the backbone is drawn and search finds everyone else.
- Quarters spanning a formation were counted twice in Figure 3, and smoothed lines implied detail that was not there. Both were fixed.
- The page claimed every older transcript was `Typeset`, which the data contradicted. The wording was corrected.

### 7. Reproduction check
The full pipeline ran with the one documented command, using saved downloads. Comparing outputs showed rows in a different order, plus one tiny numeric change it caused (7.26 to 7.25). Rows are now sorted, and two consecutive reruns of the analysis steps gave identical numbers, apart from the order of parties inside three check descriptions.

## Where things are

| Path | What |
|---|---|
| `index.html`, `assets/` | The site |
| `AI_METHODS.md` | Where an agent or model touched a result, and how it was checked |
| `docs/dataset.md` | What is in the data, and known biases |
| `docs/data_recon.md` | First look at the API, with its traps |
| `docs/collection_log.json`, `docs/dataset_numbers.json` | What was collected, and the counts from the build |
| `notebooks/analysis.ipynb` | Results and hand-validation cells |
| `labeling/` | Sheets for the group's hand labels, with instructions |
| `tools/` | The pipeline |
| `data/` | Compact derived data and results (committed) |
| `data-raw/` | Raw downloads and speech text (not committed; rebuilt by `collect.py`) |

## Terms of use

Folketinget's terms allow free use, including publication. They require crediting Folketinget, not implying endorsement, not using its logo, complying with Danish law, deleting withdrawn data, not straining the service, and telling readers whether a transcript is provisional or final. The status field is undocumented, so we treat `Typeset` as final and everything else as provisional, which is our inference. The site shows no transcript text.
