# Changes to `tools/check_labels.py`

This describes what changed in `tools/check_labels.py` since the initial commit (`9061a0d`), and how the changes were tested. Claude Code made them on 7 November 2026 to prepare for hand labeling.

The purpose of the script has not changed: it scores the group's labels and adds none of its own. All four sheets in `labeling/` are still blank.

## Why it changed

The old script could give a wrong result without any warning. We tested this on temporary copies of the sheets filled with fake labels, so these are not project results:

- Filling `challenge_precision` with `ja` scored 0 of 60, or 0% precision. That is below the 90% abandon line in the main README, even though `ja` means yes.
- One fake label per sheet was enough for the script to mark all four sheets as `labeled`, which is the status that clears the site's "Validation pending" banner.

## What changed

### Fixes

| Problem in the old script | What happens now |
|---|---|
| Any answer other than `yes` counted as `no`, including `ja`, `y` and typos. | The script stops and lists the rows to fix. |
| Stance labels with typos were silently dropped. | The script stops and lists the rows to fix. |
| One filled row marked a sheet `labeled`, so the banner could clear early. | A sheet is `labeled` only when every row is filled. Otherwise it is `partial`. |
| `challenge_stance` counted as finished with one labeler. | It stays `partial` until both labelers have filled every row. |
| If AFINN scores or labels were all the same, the script wrote `NaN`. That makes `data/site.json` invalid in a browser, which would stop the site loading. | These values, and an undefined kappa, are written as `null`. |
| Files saved by Danish Excel, which uses semicolons, crashed the script. | The separator is detected and the file is read normally. |
| A file not saved as UTF-8 crashed with a confusing error. | The script stops and says to save as `CSV UTF-8`. |
| A renamed label column crashed with a `KeyError`. | The script stops and says which column is missing. |
| Importing the script crashed in a notebook, because `sys.stdout.reconfigure` ran on import. | That line now runs only under `if __name__ == "__main__":`. The command line works as before. |

### New results in `label_checks.json`

| Field | Sheet | Meaning |
|---|---|---|
| `of` | All | Rows in the sheet, so `n` of `of` shows progress. |
| `by_era` | `challenge_precision` | `n` and `yes` for each period. |
| `era_weighted_share` | `challenge_precision` | Precision weighted by each period's share of all edges. |
| `distinct_pairs`, `distinct_yes`, `distinct_ci95` | `name_resolution` | The score with each name and person counted once. |

**Why weight by period:** the sheet has about 20 rows per period, but the real edges split 46%, 17% and 37%. If precision differs between periods, the plain share can mislead.

**Why count pairs:** the 57 rows are only 33 distinct name-and-person pairs, and one name appears 11 times, so the interval on 57 rows looks tighter than it is. A pair counts as correct only if all its rows are `yes`.

### Code structure

- **New helpers:** `era`, `finite` and `read_sheet`.
- **New scoring functions:** `precision` and `names`. Each builds on `yes_share`.
- **Changed signature:** `read_labels(name, column)` is now `read_labels(name, column, allowed)`, and it returns the labeled rows plus the sheet's size.
- **New constants:** `DATA` and `YES_NO`.

`wilson` is unchanged, and results are still written to `data/results/label_checks.json`.

## What this means when you run it

- Use exactly `yes`/`no` or `hostile`/`neutral`/`friendly`. Capitals and extra spaces are fine.
- A bad label makes the script exit with an error, so `tools/run_all.py` stops at this step until it is fixed.
- The banner stays on until every row of all four sheets is labeled, including `challenge_stance_second.csv`.

## How it was tested

`check_labels_demo.ipynb` calls every function, using fake labels on temporary copies. The labels are repeating patterns assigned by row position, so **none of its numbers are project results**. At the end it confirms the real sheets and `label_checks.json` are unchanged.

- All 59 checks pass.
- The confidence interval, kappa, Spearman correlation and weighted share match separate calculations.
- Seven bugs planted one at a time in a throwaway copy were all caught.
- `python tools/check_labels.py` runs from the command line and leaves `label_checks.json` unchanged.

To rerun the notebook, install `requirements.txt` and choose Run All.

## Still open

- **Recall is not calculated.** The script's description says the `challenge_missed` share can be scaled up to estimate recall, but that needs the number of short unmatched turns per period, which comes from `data-raw/derived/speeches.parquet`.
- **The site shows only the plain precision.** `era_weighted_share` is in `label_checks.json`, but `assets/site.js` does not display it.
- **The group has not chosen how to apply the 90% line.** It could apply to the plain share, the weighted share, or the lower end of the interval.
- **`era` is defined twice.** `check_labels.py` repeats the periods from `make_labeling_sheets.py`, so a change to one must be copied to the other.
- **Not tested.** The banner logic was copied from `assets/site.js` into the notebook, so it was not run in a browser, and `export_site.py` was not run. Tests used pandas 3.0.6, not the pinned 3.1.0.
