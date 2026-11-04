# AI methods

Where a model or agent touched a result, and how it was checked. "The model said so" is not a method.

**Status: hand labels are pending.** Everything marked *pending* below needs the group's labels in `labeling/`, followed by `python tools/check_labels.py` and `python tools/export_site.py`.

## Who did what

**Claude (Claude Code, model Opus 5.5)** wrote the scripts, ran the analysis, drafted the docs and built the site. **The group** chose the project, supplied the current terms of use, and is responsible for the hand labels. **Before submitting,** each group member needs to read the code and be able to explain it: the agent's reading is not understanding on your behalf.

**No language model labeled any data.** The only models applied to text are a pretrained sentence encoder and logistic regressions trained on party or government status, with a lexicon pending labels.

## Measurements

Each entry says what the measure captures, what it misses, how it was checked, and the result. Results are from `data/results/`.

### Challenge edges (rule on the transcripts)
- **Captures:** a member called by the chair for a short remark directly after another member spoke.
- **Misses:** follow-ups announced in other words, and spoken question time. It does not show tone or who initiated the disagreement.
- **Check:** group hand labels for precision (`challenge_precision`, 60 rows) and missed edges (`challenge_missed`, 60 rows) are *pending*. S–V backbench counts were recounted from raw XML with separate regex code: 321 and 10 against 321 and 8 from the pipeline.
- **Result so far:** the first version of the rule was wrong on 4 of 6 examples, because it matched "there are no short remarks". The agent read 14 random pairs from the fixed rule and all looked right. That is not a validation.

### Speaker name resolution
- **Captures:** which `Aktør` record a transcript name refers to.
- **Misses:** wrong matches among people with similar names, which an exact match rate cannot show.
- **Check:** group hand labels on 57 sampled matches (`name_resolution`) are *pending*. The agent proposed the 16 aliases using party and session, and the group should read them.

### Party mixing against the null
- **Captures:** whether one party challenges another more or less than expected.
- **Misses:** why, and whether remarks are hostile.
- **Check:** two nulls. One shuffles the floor side across the period, which keeps members' counts made and received. One shuffles within each debate, which also keeps who was speaking there. 1,000 shuffles per period, or 200 for the formation comparisons. Tested against a worked toy case.
- **Result:** challenges rarely stay in a party: 112 of 45,117 with both parties known.

### Assortativity by party and by government side
- **Captures:** the tendency to challenge across a label.
- **Misses:** it is one number for a whole period.
- **Check:** label shuffles across members (1,000). Our formula matches networkx on a toy graph.
- **Result:** negative in all seven periods tested, by party (−0.086 to −0.147) and by side (−0.134 to −0.360). Shuffled means are near −0.01.

### Change at each government formation (votes, challenges, language)
- **Captures:** how far a party pair's change stands from pairs whose relation did not change at the same formation.
- **Misses:** there are only six formations, and pairs within one are not independent. Different layers have different units, so the placebo scale is not a way to rank layers.
- **Check:** permutation of relation labels within each formation (20,000). Challenges are also rerun on backbenchers only and on the same members across a change. 2026 is left out as too thin.
- **Result:**

| Layer | Right direction | Mean effect (placebo SDs) | p (one-sided) |
|---|---:|---:|---:|
| Challenges | 14 of 14 | 8.42 | < 0.0001 |
| Challenges, backbench only | 14 of 14 | 10.24 | < 0.0001 |
| Challenges, same members | 10 of 10 | 9.78 | < 0.0001 |
| Votes (contested) | 13 of 14 | 2.43 | < 0.0001 |
| Same-debate similarity | 13 of 14 | 3.65 | < 0.0001 |
| Party classifier | 3 of 8 | 0.06 | 0.12 |

For S–V in 2022 alone: challenges 623 → 22 (expected 489 → 135), votes on contested items 66% → 100%, similarity excess 0.046 → 0.054 (0.73 placebo SDs).

### Votes
- **Captures:** formal alignment, party by party and member by member.
- **Misses:** everything negotiated beforehand, and it is mechanically high inside a government, so it sets up the question and does not answer it.
- **Check:** S–V agreement in 2022–26 from vote summaries (100% of 1,557) was recomputed from individual member votes, which share no code or source field (100% of 1,467). Vote network communities are compared with a null that shuffles votes within each party.
- **Result:** rebel rate 0.056% to 0.137% in full periods. Community NMI with party is 0.60–0.71, and within-party shuffle gives 0.67–0.75, so member votes add nothing beyond party.
- **Bugs this exposed:** the first parser turned `(S, V og M)` into a fake party and lost parties listed after names with initials, such as `Jan E. Jørgensen (V)`. Headline S–V numbers looked fine. A failed cross-check led us to read the raw text, and the build now fails if parsing yields many non-party tokens.

### Sentence embeddings (`paraphrase-multilingual-MiniLM-L12-v2`)
- **Why this model:** its model card lists Danish, and the group used it in week 7. It is not tuned for parliamentary Danish.
- **Captures:** broad semantic similarity between two parties' speakers in one debate, with topic held roughly fixed.
- **Misses:** stance. Two speakers can disagree in similar words. It may also be picking up role vocabulary, which we did not test.
- **Check:** shuffling party among each debate's speakers. Our truncation test found 38% of 90-word chunks cut off silently, so we moved to 60 words: 0.0% of 3,000 sampled chunks truncated, median 85 word pieces. A second method is the party classifier, and the two disagree. We report that rather than choosing.

### Party classifier (TF-IDF, logistic regression)
- **Captures:** how well word use separates two parties on speakers held out of training, after Peterson and Spirling (2018).
- **Misses:** it picks up role and topic as well as party. Accuracy can differ for reasons unrelated to politics, such as group size. It also has low power with 8 pairs.
- **Check:** shuffled speaker labels for focal pairs (20 shuffles), with accuracy near 0.49. Top words were read: `ministeren` and `regeringen` mark whichever party is in opposition. S–V accuracy was as low in 2015 (0.53, opponents) as in 2022 (0.53, partners), so a low value cannot be credited to coalition alone.

### Opposition vocabulary
- **Captures:** the rate of words addressing the government.
- **Misses:** a word count cannot tell an attack from a question.
- **Check:** shuffling status within party gives 0 ± 0.32, with a real gap of 3.92 per 1,000 words (p = 0.0002, 5,000 shuffles). As a second method, a classifier trained on other governments and speakers reaches 0.64–0.66 on a held-out government, with shuffled labels near 0.50.

### Louvain communities on the challenge network
- **Captures:** groups of members who keep meeting on the floor.
- **Misses:** overlap; every member is in one community.
- **Check:** modularity against a rewired null (0.28–0.45 vs 0.08–0.13), NMI between 20 seeds (0.73–0.92), NMI with party (0.06–0.10). Shared committee membership against the shuffle (for example 83% vs 79% in 2022–26; z-scores above 10). This is a blunt test, because most members sit on several committees.
- **Result:** the claim that communities are policy areas is **the agent's reading of title words**, with weak quantitative support. The group should read `community_topics` before repeating it.

### Tone of challenges (AFINN Danish lexicon)
- **Captures:** positive and negative words in a remark.
- **Misses:** whom the words target. It would count a sentence praising one's own plan as friendly in a hostile remark.
- **Check:** *pending*. `challenge_stance` has 60 rows, needs a second labeler for Cohen's kappa, and `check_labels.py` reports the correlation with AFINN. No tone result is claimed until then.

## Other checks and corrections

`tools/validate.py` runs 13 checks, and all pass: toy cases for the null, assortativity, status labels and vote parser, plus the two independent recounts. These catch code bugs, not whether a measure means what we say.

The agent also made and fixed these errors:
- It wrote the first project files to the wrong repository, and moved them when told.
- It drew labeling sheets three times from stale data, because a failed build did not stop the next step. Those unlabeled sheets were deleted and redrawn.
- It first told the group language "barely" tracks government changes. The formal test showed that was too strong across formations, and it was corrected.

## Sources

References on the site were checked against Crossref or a publisher listing. The terms of use were supplied by the group from the live page, and the agent had compared them with a June 2025 archived copy. Danish model support comes from the model's listed tags, and the lexicon's behaviour was tried on three sentences only.
