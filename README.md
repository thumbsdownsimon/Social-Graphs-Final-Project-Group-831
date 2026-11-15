# Archetypes of the Danish Parliament

**Question:** members of parliament do not all play the same role. Some attack, some get attacked, some build bridges and some leave their party. Can we find distinct archetypes of members in Folketinget, 2009–2026, from how they vote, debate and talk?

Final project for DTU 02805 Social Graphs and Interactions, group 831: Christian Colberg (s224343), Yuen Yi Hui (s226465), Simon Jonsson (s224331).

**Data source: Folketinget**, through [oda.ft.dk](https://oda.ft.dk/). Folketinget has not endorsed or reviewed this project.

> The project started from an earlier question ("Crossing the Aisle": do floor challenges follow changes of government?). Its pipeline in `tools/` still runs, and it builds the shared data that this project reads. See [Rebuilding the shared data](#rebuilding-the-shared-data).

**Status:** the network layer (layer 1 below) is being built. The language, voting and clustering layers are planned.

## Problem statement

### Network

Members of parliament do not all play the same role. Some attack, some get attacked, some build bridges and some leave their party. We ask: can we find distinct archetypes of members in the Danish parliament from how they vote, debate and talk? We build a challenge network for 2009–2026. Nodes are members, and a directed edge goes from a member who makes a short remark to the member holding the floor. We combine each member's position in this network with their voting record and party history. We define a set of archetypes from these measures, such as the attack dog, the lightning rod, the defector and the negative Nancy. Then we test whether these roles really exist, or whether clustering the members finds different ones.

### Language processing

We measure the tone of every challenge as hostile, neutral or friendly, using a sentiment score checked against hand labels. This gives each member a profile: how negative their challenges are, how emotional or argumentative their language is, and whether their hostility is aimed at the other bloc, at their own side or at the government. We ask: are some archetypes defined by tone, like the negative Nancy, and others by network position alone, like the lightning rod? We also find the most distinctive words for each archetype, to show how an attack dog talks compared with a bridge builder.

### Conclusion

We conclude whether the Danish parliament can be described by a small set of archetypes, and how they are spread across parties. Does each party have its own attack dog and its own lightning rod, or are some parties made up mostly of one type? We also ask whether members change archetype over time, for example when their party enters government or when they become ministers.

## Contents

- [Problem statement](#problem-statement)
- [The plan in one picture](#the-plan-in-one-picture)
- [The challenge network](#the-challenge-network)
- [Layer 1: network measures](#layer-1-network-measures)
- [Party history and defectors](#party-history-and-defectors)
- [Archetypes defined by rules](#archetypes-defined-by-rules)
- [Nulls: is a role more than chance?](#nulls-is-a-role-more-than-chance)
- [First results of layer 1](#first-results-of-layer-1)
- [Planned layers](#planned-layers)
- [Code layout](#code-layout)
- [How to run it](#how-to-run-it)
- [Known limitations](#known-limitations)

## The plan in one picture

```
 oda.ft.dk ──► tools/collect.py ──► tools/build_dataset.py ──► data/challenges.parquet
 (existing pipeline, unchanged)                               data/party_positions.parquet
                                                              data/governments.json
                                                                       │
 ┌─────────────────────────────── archetypes/ ─────────────────────────┴──────────────┐
 │ data.py      clean edges, party history, switches, windows, blocs, edge labels     │
 │ graphs.py    one weighted directed graph per government window, plus one overall   │
 │ metrics.py   per member × window: activity, targeting, receiving, structure        │  layer 1
 │ nulls.py     degree-preserving shuffles → z-scores for every targeting share       │  (today)
 │ roles.py     rule-based archetypes (attack dog, lightning rod, ...)                │
 │ run_network.py  writes data/archetypes/*.parquet and data/results/archetypes_*.json│
 ├────────────────────────────────────────────────────────────────────────────────────┤
 │ tone.py      hostile / neutral / friendly per challenge, checked on hand labels    │  layer 2
 │ words.py     distinctive words per archetype                                       │  (planned)
 │ votes.py     rebel rate and absence per member × window (2017+)                    │  layer 3
 │ cluster.py   unsupervised clusters on all features; compare with the rule roles    │  layer 4
 └────────────────────────────────────────────────────────────────────────────────────┘
```

Every layer adds columns to one table, **one row per member per government window**. The rule-based roles and the clustering both read that table. That is how we test whether the hand-defined archetypes actually exist.

**Unit of analysis.** A *window* is the time between two government formations (`data/governments.json`, eight windows from Nov 2009 to 2026). Working per window means a member can change archetype when their party enters government or when they become a minister. Every measure is also computed once over the whole period (`window = "all"`).

## The challenge network

After a speech, the chair can give the floor to another member for a *kort bemærkning*, a short remark aimed at whoever holds the floor. `tools/build_dataset.py` reads these from the transcripts. The rule is: a member's turn, then a chair turn announcing a short remark, then a different member.

- **Nodes:** members (Aktør person ids).
- **Edges:** directed, **challenger → member holding the floor**, weighted by the number of challenges.
- **Edge attributes** added in `archetypes/data.py`: the window, both parties, both blocs, whether each side is in government at that date, and whether the floor holder is a minister.
- **Size:** 45,529 challenges among 573 people, Oct 2009 – Sep 2026.

Edges from before the first formation in our data (24 Nov 2009), or with an unresolved party (`UFG` aside), are dropped, as in the earlier project.

### Labels attached to each edge

| Label | Meaning |
|---|---|
| `same_party` | challenger and floor holder in the same party on that date |
| `cross_bloc` | one in red, one in blue (see the bloc map below); undefined if either is centre, North Atlantic or independent |
| `cross_side` | one in government, one in opposition. Ministers count as government. |
| `own_side` | allies: same party, both in government, or both in opposition **and** in the same main bloc. EL challenging DF while both are in opposition is neither `cross_side` nor `own_side`. |
| `at_government` | the floor holder is a minister or in a government party |

**Blocs** (an assumption, set in `archetypes/config.py`): red = S, SF, RV, EL, ALT, FG. Blue = V, KF, DF, LA, NB, DD, BP, KD. Centre = M. North Atlantic = IA, SIU, SP, T, TF, JF, NQ, N. `UFG` (independent) has no bloc. The government/opposition side comes from the data, so `cross_side` is our main "aimed at the other side" measure, with `cross_bloc` as a check.

## Layer 1: network measures

`archetypes/metrics.py` computes each measure per member and window.

| Group | Measure | What it is for |
|---|---|---|
| Activity | `out_w`, `in_w` | challenges made and received |
| | `out_rate`, `in_rate` | the same per sitting day while the member was active (exposure, see limitations) |
| | `in_w_backbench`, `in_rate_backbench` | challenges received while **not** a minister, because ministers are challenged by default |
| | `attack_balance` | (out − in) / (out + in): +1 only attacks, −1 only attacked |
| Targeting (out-edges) | `share_cross_side`, `share_own_side`, `share_cross_bloc`, `share_own_party`, `share_at_government` | who their challenges hit |
| | `target_entropy`, `top_target_share` | many targets, or one fixation |
| Receiving (in-edges) | `in_share_cross_side`, `in_n_parties`, `in_party_diversity` | attacked by one camp or by everyone |
| Structure | `pagerank_in` | challenged by members who are themselves challenged a lot |
| | `hub`, `authority` (HITS) | good attacker vs good target, mutually defined |
| | `betweenness` | sits on paths between otherwise separate groups |
| | `participation` | spread of the member's edges over parties (participation coefficient, 0 = one party, → 1 = all parties equally) |
| | `reciprocity` | share of partners who are challenged in both directions |
| Status | `party`, `in_government`, `was_minister`, `minister_share` | for the conclusion: do roles move with office? |

## Party history and defectors

Party labels in the transcript are reliable for members but not for ministers. The tag is missing and the old builder fills it from the nearest session. That put Inger Støjberg in DD (founded 2022) as a minister in 2009. So `archetypes/data.py`:

1. Builds each member's **party runs** from their own non-minister turns, sorted by date. It drops runs shorter than `MIN_RUN` appearances, which are treated as noise.
2. Records a **switch** wherever two consecutive runs differ, including moves to and from `UFG` (independent). Known renames, such as `TF` → `T`, are not switches.
3. Re-labels ministers' edges with the party run active on that date.

This gives `data/archetypes/party_history.parquet` and `party_switches.parquet`. The first run finds 53 switches by 39 members, for example DF → DD in 2022, V → UFG → M (Løkke) and ALT → FG. A switch is dated by the first appearance in the new party, which can lag the real date by weeks.

## Archetypes defined by rules

`archetypes/roles.py` assigns roles within each window. It only considers members with at least `MIN_EDGES` challenges in either direction, and uses percentiles within the window, so a busy session does not create more attack dogs. A member can hold several roles or none.

| Archetype | Rule (network layer) | Needs language? |
|---|---|---|
| **Attack dog** | top 20% `out_rate`, `attack_balance` ≥ 1/3, and `share_cross_side` above the null (z ≥ 2) or ≥ 0.8 | no, tone sharpens it |
| **Lightning rod** | top 20% `in_rate_backbench`, and top 50% `in_party_diversity`: attacked a lot, by many parties | no |
| **Minister rod** | the same, for challenges received as minister, ranked among ministers | no |
| **Bridge builder** | top 20% `participation`, top 50% `reciprocity`, `|attack_balance|` < 1/3 | **yes**: needs friendly tone to tell bridging from brawling |
| **Friendly fire** | `share_own_side` above the null (z ≥ 2) and ≥ 0.3: challenges their allies | tone tells critic from ally |
| **Defector** | at least one party switch in the window (or in the career, at member level) | no |
| **Negative Nancy** | mostly hostile challenges | **yes**, layer 2; empty until then |

The thresholds are in `archetypes/config.py`, so they are in one place and easy to vary. Part of the analysis is to check that the roles survive moderate changes to them.

## Nulls: is a role more than chance?

A member challenging the opposition might just reflect who speaks in the debates they join. `archetypes/nulls.py` therefore shuffles the floor side of the edges:

- **Within each debate** (default): keeps how often each member challenges, and who held the floor in each debate. Only "who challenged whom inside a debate" is randomized.
- **Within the window** (looser): keeps each member's in- and out-degree, which is a directed configuration model.

For each targeting share it reports the observed count, the null mean and SD, `z`, and a one-sided empirical p (`N_SHUFFLES` = 500). Self-loops the shuffle creates are dropped from both the count and the total. The same is done on the receiving side by shuffling challengers, for `in_share_cross_side`.

## First results of layer 1

These come from the first full run (500 shuffles, null within debates), 11 Nov 2026. The thresholds have not been tuned yet.

- **Data used:** 44,591 labeled challenges among 571 members. 53 party switches by 39 members. Each window has 125–182 members with at least 15 challenges; the Jun–Sep 2026 window has only 6.
- **Roles per window:** lightning rod 14–23, bridge builder 7–16, attack dog 0–9, minister rod 2–3, friendly fire 0–2. Defectors cluster in 2019–22 (the DF exodus to DD, the NB break-up and the ALT/FG split).
- **Attack dog is rare.** Prolific challengers are mostly spokespeople who are also challenged a lot, so few reach `attack_balance` ≥ 1/3. This needs a group decision: loosen the balance condition, or keep "attack dog" for genuinely one-way attackers.
- **Friendly fire barely survives the within-debate null.** 77 member-windows have `share_own_side` ≥ 0.3, but only 6 have z ≥ 2. Most own-side challenges happen in debates where the floor holder is an ally anyway.
- **Roles are not stable across windows.** Of 7 attack dogs whose office did not change, none kept the role in the next window. For lightning rods it was 12 of 52. Either roles really are situational, or the rules sit too close to noise. The sensitivity check and the clustering (layer 4) should tell these apart.

## Planned layers

- **Layer 2, tone** (`tone.py`, `words.py`). Score every challenge as hostile / neutral / friendly with a Danish sentiment score (AFINN-da is already a dependency), checked against `labeling/challenge_stance.csv`. Per member: share hostile, mean intensity, and hostility aimed at the other bloc / own side / government. Distinctive words per archetype (TF-IDF or log-odds). This needs `data-raw/derived/speeches.parquet`, which holds the text.
- **Layer 3, votes** (`votes.py`). Rebel rate and absence per member and window, from member votes (2017–18 onward only), reusing `tools/analyze_votes.py:member_votes`.
- **Layer 4, clustering** (`cluster.py`). Standardize the member × window table, cluster it (Gaussian mixture or k-means, choosing *k* by silhouette/BIC), and compare with the rule roles: contingency table, adjusted Rand index, and which features separate each cluster.
- **Conclusion.** Roles by party (does each party have its own attack dog?), and role transitions between consecutive windows, split by entering/leaving government and becoming a minister. `run_network.py` already writes a first version of both from the network layer.

## Code layout

| Path | What |
|---|---|
| `archetypes/config.py` | paths, seed, blocs, renames, thresholds |
| `archetypes/data.py` | loading, cleaning, party runs, switches, windows, edge labels |
| `archetypes/graphs.py` | building weighted directed graphs per window |
| `archetypes/metrics.py` | node measures → member × window table |
| `archetypes/nulls.py` | shuffles and z-scores |
| `archetypes/roles.py` | rule-based archetypes, role tables by party, transitions |
| `archetypes/run_network.py` | runs layer 1 end to end |
| `tests/test_network.py` | toy graphs with answers worked out by hand |
| `data/archetypes/` | outputs (parquet) |
| `data/results/archetypes_network.json` | summary for the notebook and site |

## How to run it

The network layer only needs the committed `data/` folder, so `data-raw/` is not required.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m archetypes.run_network
.venv\Scripts\python tests\test_network.py
```

`run_network` takes about 75 seconds with 500 shuffles. Use `--shuffles 50` for a quick run, or `--null-group window` for the looser null. The tests also run under `pytest`.

### Rebuilding the shared data

The committed `data/` is built by the pipeline in `tools/`, from these sources:

| Data | Source | Scope | Size |
|---|---|---|---|
| Debate transcripts (XML) | `ftp://oda.ft.dk/ODAXML/Referat/samling/` | Sessions 2009-10 to 2025-26 | 1,878 files, 1,206 MB |
| Votes, including party positions in the summary text | `Afstemning` in the API | All sessions; party names from about 2010 | 10,536 votes, 7,625 with party positions |
| Individual member votes | `Stemme` in the API | Sessions 2017-18 to 2025-26 | 741,402 rows over 4,391 votes |
| People, party groups and memberships | `Aktør`, `AktørAktør` | Party memberships per session | 3,414 people, 4,173 memberships |
| Minister roles | `AktørAktør` | Used to derive governments | 961 rows |
| Committee memberships | `AktørAktør` | Per session | 21,316 rows |

Downloads are throttled to one API request per half second and one FTP file per second, and every response is cached in `data-raw/`, so reruns do not hit the service again. `docs/collection_log.json` records what was collected and when. How the tables are joined, and the known biases, are in `docs/dataset.md`.

```
.venv\Scripts\python tools\run_all.py
```

This runs `collect.py` (downloads), `build_dataset.py` (speeches, people, parties, challenges, governments) and the rest of `tools/` in order, stopping at the first failure. A first run takes several hours; it can be stopped at any time and resumes from what is saved. To rerun one download step: `tools\collect.py tables`, `debates`, `votes` or `committees`. To watch a run, write it to a log (`... run_all.py > run_all.log 2>&1`) and run `tools\progress.py run_all.log` in another window.

Steps 4–12 of `run_all.py` (`analyze_*.py`, `summarize.py`, `export_site.py`, `make_notebook.py`) belong to the earlier question: do floor challenges follow changes of government? They still drive the current site and notebook.

### Hand labels

The sheets in `labeling/` must be labeled by the group, not by a model; instructions are in `labeling/README.md`. A second person labels `challenge_stance` separately, as `challenge_stance_second.csv`, so agreement can be reported.

| Sheet | Rows | What you decide |
|---|---:|---|
| `challenge_precision` | 60 | Is this edge really a challenge to the speaker holding the floor? |
| `challenge_missed` | 60 | Did the rule miss a challenge here? |
| `challenge_stance` | 60 | Is the tone hostile, neutral or friendly? Also the check for the tone layer. |
| `name_resolution` | 57 | Is this the same person? |

Save as UTF-8 CSV under the same names, then run `tools\check_labels.py`. Set in advance: if the challenge rule is under 90% precise, the network is not reliable enough to use.

## Known limitations

- **Exposure.** Without the speech text we only see floor holders who were challenged, not every speech. Rates are therefore per sitting day between a member's first and last appearance in the window. With `data-raw/derived/speeches.parquet`, exposure can become "floor turns", and `in_rate` should then be read per speech.
- **Ministers** receive about 20% of all challenges, but make almost none. That is why the lightning rod uses backbench challenges and minister rods are ranked separately.
- **The challenge rule** is not hand-validated yet (`labeling/challenge_precision.csv`). Below 90% precision, the network layer is unreliable.
- **Blocs** are a fixed map, but RV and M have moved between camps. `cross_side` (government vs opposition, from the data) is the safer measure.
- **Short windows** (Jun–Sep 2026) have few edges. Roles there are mostly empty by construction.
