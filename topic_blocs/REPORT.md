PROMISING (narrow): the kill criterion is passed, but the dividing line mostly changes strength between topics and rarely changes which divide it is.

# 09 Topic-specific blocs

(Text from the agent's hand-back, saved by the coordinating session because the agent's write tool refused report files.)

**Point:** in 6 of 7 government windows, which divide fits the challenge network better (red/blue or government/opposition) differs between policy topics more than a topic shuffle allows. But the government composition sets which divide wins, and the topic mostly sets how strongly it wins. Foreign/defence is the one topic where the red/blue line is weak again and again.

## Data and topic link

- Each debate (session, meeting, item) is linked to an ODA Sag (types L, B, F, R): same session, same number, and a floor-debate Sagstrin (readings, forhandling) on the debate date. We fall back to any Sagstrin on that date. `fetch_sager.py` and `build_topics.py` do this.
- Match rate: 5,702 of 5,703 debates (99.97% of edges). 185 debates had more than one candidate, and 149 of those had candidates with different topics. We dropped those as ambiguous (4.8% of edges).
- Topic = the committee the case was referred to (SagAktør role 11). For F/R cases with no committee we use the ministry area (role 6). Keyword rules plus 4 overrides group about 150 committee and ministry names into 9 areas: economy, welfare/health, labour, education/culture, environment/energy, infrastructure/local, justice, immigration, foreign/defence. The mapping is in `topic_map.csv`. Statsministeriet (5.5%) and Forretningsorden (1.3%) are left out. About 88% of edges keep a policy topic.

## Method and null (PLAN.md was written first)

- Graph per topic × window: undirected, weighted member graph, only if the cell has at least 300 edges. That gives 54 cells in 7 windows; 2026 is too small. Nodes are labelled gov/opp and red/blue (`config.BLOC`; M and North Atlantic are their own groups). Challenges are conflict, so a fitting divide gives Q < 0.
- (a) Q of each partition against a within-debate floor-holder shuffle (200 draws). Louvain communities with NMI against each partition.
- (b) delta_t = Q_bloc − Q_gov per topic. S = edge-weighted SD of delta across topics. Null: permute topic labels across whole debates within the window (1,000 draws). Kill: fewer than half of windows with z ≥ 2.

## Results

**Test (b), main run:** z = 4.2 (2009), −0.3 (2011), 4.9 (2014), 3.1 (2015), 5.6 (2016), 4.0 (2019), 2.4 (2022). That is 6 of 7 windows, permutation p ≤ 0.013 in all six. 2011 is flat: on every topic, red/blue fits only slightly better (delta −0.01 to −0.06).

**Robustness (windows with z ≥ 2):**

| Variant | Windows with z ≥ 2 |
|---|---|
| Permute whole cases | 6/7 |
| Permute within Sag type | 6/7 |
| Drop North Atlantic and unaffiliated members | 6/7 |
| Drop edges with a minister | 5/7 (2022 falls to z = 1.7) |
| Minimum 500 edges per cell | 4/5 |
| Relative delta, (Q_bloc − Q_gov)/(\|Q_bloc\| + \|Q_gov\|) | 5/7 |

**What varies:**

- Which divide wins is decided by the window. Red/blue wins on every topic up to 2019, because support parties sit on their bloc's side. Gov/opp wins on every topic in 2022.
- The winner changes with topic in only 4 of 54 cells: foreign/defence in 2011, 2016 and 2019, and immigration in 2016.
- Justice and labour in 2019 (delta −0.01, −0.02) and foreign/defence sit near zero, while economy, education and environment are strongly bloc-structured.
- So most of the spread is "same line, different strength". The relative-delta run shows that some of it is about which line, too.

**Test (a):**

- Both partitions beat the within-debate null in 89% of cells. Median z_gov is −4.7 and median z_bloc is −7.2.
- In 2022 the bloc line is mostly not beyond the null.
- In 2019, gov/opp is not beyond the null on welfare (z = 0.0) or labour (z = −0.6).
- Louvain communities do not recover any divide. Mean NMI is about 0.02 with gov/opp, 0.02–0.06 with red/blue and 0.09–0.14 with party.

**Votes:**

- 91% of the votes in `party_positions` link to a topic through Afstemning → Sagstrin → Sag.
- The spread of sep_bloc − sep_gov across topics beats a Sag-level shuffle in 4 of 6 windows (z = 1.6, 2.5, 1.4, 2.7, 3.3, 6.4).
- S–DF agreement is lowest on immigration (0.39 in 2019, 0.19 in 2022, against 0.5–0.8 on other topics). This is likely because most immigration votes are on DF's own motions, which S votes down.

## Caveats

- Committee referral is a coarse topic.
- The bloc map is an assumption (RV, M).
- Topics differ in who takes part. The no-North-Atlantic run keeps the result, but other participation effects remain.
- 4 winner flips in 54 cells is thin evidence that the line itself moves.
- Votes cover 2011–2026 only, and most votes are near-consensual.

## How it feeds the archetypes question

- The `cross_side` and `cross_bloc` labels hold on most topics. On foreign/defence (and on justice and labour in 2019) they overstate conflict.
- If an archetype rests on "attacks the other side", check that it is not driven by a member's topic mix.
- Option: add a topic-mix covariate per member, or compute cross-side share within topic.
- No separate topic-bloc layer is needed: there is one divide per government, with topic-dependent strength.

## Files

Code is in `topic_blocs/`, data and outputs in `data/topic_blocs/`. Run from the repo root, in this order (only the first and fourth call the ODA API, throttled and cached in `data-raw/`):

```
python -m topic_blocs.fetch_sager        # sager.parquet, actors.parquet
python -m topic_blocs.build_topics       # debate_topics.parquet, topic_map.csv
python -m topic_blocs.topic_blocs        # test_a_main.csv, test_b_main.csv, null_b_main.npz (--help for the robustness flags)
python -m topic_blocs.fetch_votes        # vote_topics.parquet
python -m topic_blocs.vote_check         # vote_b.csv, vote_pairs.csv
python -m topic_blocs.figures            # figures/fig_topic_divide.png, figures/fig_vote_pairs.png
python -m topic_blocs.export_site_json   # data/results/topic_blocs.json, read by Part 4b of the site
```

- **Plan:** `topic_blocs/PLAN.md`, written before any test was run.
- **Topic data:** `topic_map.csv`, `debate_topics.parquet`, `vote_topics.parquet`, `sager.parquet`, `actors.parquet`
- **Results:** `test_a_*.csv`, `test_b_*.csv`, `null_b_*.npz`, `vote_b.csv`, `vote_pairs.csv`
- **Figures:** `figures/fig_topic_divide.png`, `figures/fig_vote_pairs.png`
- **Site:** Part 4b of `index.html` (Figures 14 and 15), drawn by `topicBlocsPage` in `assets/findings.js`.
