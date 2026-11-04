# Hand labeling

The group fills these in; no model or agent may do it. Label each row without looking at the
other labels, and have a second person label `challenge_stance` so we can report agreement
(save their copy as `challenge_stance_second.csv`). Save as CSV (UTF-8). Then run
`python tools/check_labels.py`.

| Sheet | Label column | What to decide |
|---|---|---|
| `challenge_precision` | `is_challenge_to_floor_yes_no` | The rule called this an edge. Is `next_speaker` really addressing a short remark to `floor`? Answer `no` if they address someone else, even if it is a short remark. |
| `challenge_missed` | same | The rule did NOT call this an edge, and the next turn is short. Is it a short remark to `floor` anyway? Estimates what the rule misses. |
| `challenge_stance` | `stance_hostile_neutral_friendly` | Tone toward the floor speaker. `hostile`: attacks, accuses or ridicules. `friendly`: agrees, praises or offers support. `neutral`: a plain question or information, including polite disagreement on substance. |
| `name_resolution` | `same_person_yes_no` | Is the transcript name the same person as the matched record? Look them up on ft.dk if unsure. |

Transcripts from recent sessions may be provisional and can change.
