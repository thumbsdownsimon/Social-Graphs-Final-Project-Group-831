# Hand labeling

The group fills these in; no model or agent may do it. Label each row without looking at the
other labels, and have a second person label `challenge_stance` so we can report agreement
(save their copy as `challenge_stance_second.csv`). Save as CSV (UTF-8). Then run
`python tools/check_labels.py`. Use exactly `yes`/`no` or `hostile`/`neutral`/`friendly`; anything
else stops the script and names the row.

| Sheet | Label column | What to decide |
|---|---|---|
| `challenge_precision` | `is_challenge_to_floor_yes_no` | The rule called this an edge. Is `next_speaker` really addressing a short remark to `floor`? Answer `no` if they address someone else, even if it is a short remark. |
| `challenge_missed` | same | The rule did NOT call this an edge, and the next turn is short. Is it a short remark to `floor` anyway? Estimates what the rule misses. |
| `challenge_stance` | `stance_hostile_neutral_friendly` | Tone toward the floor speaker. `hostile`: attacks, accuses or ridicules. `friendly`: agrees, praises or offers support. `neutral`: a plain question or information, including polite disagreement on substance. |
| `name_resolution` | `same_person_yes_no` | Is the transcript name the same person as the matched record? Look them up on ft.dk if unsure. |

## How to label each sheet

Every row in the three challenge sheets is three turns in a row: `floor` (who spoke last,
ending with `floor_ends`), then the chair (`chair_says`), then `next_speaker`
(`next_speaker_says`). The question is always the same: **is `next_speaker` making a short
remark (a question or objection) aimed at `floor`?** Read `floor_ends`, then `chair_says`,
then the start of `next_speaker_says`, and look for who is being addressed ("ordføreren",
"ministeren", the floor speaker's name or party).

- **Yes:** `next_speaker` questions, objects to or comments on what `floor` just said, as a
  short remark. This includes a questioner's second remark ("Hr. X." or "Så er det hr. X igen")
  directed back at the speaker holding the floor.
- **No:** `next_speaker` is the one *answering* a short remark. This is common when the chair
  just says "Ordføreren.", "Ministeren." or "Spørgeren.", and `floor` was the person asking.
- **No:** `next_speaker` gives a new speech of their own (as rapporteur, minister and so on),
  addresses someone other than `floor`, or the turn is procedural.
- If the excerpt is too short to tell, look up the meeting on ft.dk using `session`, `meeting`
  and `date`. If you still cannot tell, answer `no` and note the row number for the group.

`challenge_precision`: the rule thought every row here is a challenge. You are checking whether
it is right, so most rows should be `yes`. Each `no` counts against the rule (the agreed
abandon line is under 90% `yes`).

`challenge_missed`: the rule did not count any row here. You are checking whether it should
have, so most rows should be `no` (many are answers). Each `yes` is a challenge the rule
missed, typically a follow-up remark the chair announced without the words "kort bemærkning".

`name_resolution`: each row is one name as written in one session's transcripts (with the
party and role used there), matched to one person record. `yes` means that name in that session
is that person. Judge each row on its own. The same name can appear in several rows for
different sessions; label each one, even if the answer is the same. The script also scores
each name and person pair once, and counts it correct only if all its rows are `yes`.

Transcripts from recent sessions may be provisional and can change.