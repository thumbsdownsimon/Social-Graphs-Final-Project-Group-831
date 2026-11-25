# 09 Topic-specific blocs: plan (written before running any test)

## Hypothesis
The dividing line in the challenge network moves with the topic. On some topics
(e.g. immigration/justice after 2019) the line that best separates challengers from the
challenged is not the same one as on economy/welfare. If true, "cross-side" and
"cross-bloc" labels in the archetypes should be topic-aware.

## Data
- Topic per debate: the challenge's (session, case_number) is the numeric part of a Sag
  number (L 12, B 12, F 12, R 12 share numbers), so we fetch Sag rows of types L (3),
  B (5), F (2), R (11) per session with SagAktør and Sagstrin dates, and pick the Sag whose
  number matches and which has a Sagstrin on the debate date (fallback: unique number
  match). Topic = the committee the case was referred to (SagAktør rolle 11, "Henvist til"),
  fallback Ministerområde (rolle 6). Committees are grouped into ~8 stable areas
  (mapping written to `topic_map.csv`). Match rate reported.
- Edges: `archetypes.data.load_all()` labelled edges (cleaned parties, windows, gov side).

## Test (a), per topic x window with at least 300 edges
Undirected weighted member graph (weight = challenges between the pair, self-loops dropped).
Node labels: gov/opp (member's party in government in that window, or minister), red/blue
bloc (config.BLOC; centre and North Atlantic as their own groups). Modularity Q of each
partition. Challenges are conflict edges, so a divide that explains them gives Q < 0;
"fit" = -Q. Null: shuffle floor holders within debate (200 shuffles), z per partition.
Louvain on the same graph, NMI with each partition (descriptive).

## Test (b), the decisive one
Per window: delta_t = Q_bloc,t - Q_gov,t for each topic t (which divide fits better).
Statistic S = weighted SD of delta_t across topics (weights = edges). Null: permute topic
labels across whole debates within the window (1000 permutations), recompute S.
z = (S - mean_null) / sd_null.

## Kill criterion (fixed now)
If |z| < 2 in most evaluable windows (fewer than half reach z >= 2), the angle is DEAD.
Only if it passes: robustness (Q of party partition, minimum-edge threshold, drop ministers),
and a vote sanity check (party agreement per topic from party_positions linked
Afstemning -> Sagstrin -> Sag).
