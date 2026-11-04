#!/usr/bin/env python3
"""Writes and executes notebooks/analysis.ipynb, which shows the results next to their checks.

    python tools/make_notebook.py

Kept as a script so the notebook's cells can be reviewed as plain text. The hand-validation
cells print real rows to read, so a person can reproduce a number without trusting the pipeline.
"""
import subprocess
import sys
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "analysis.ipynb"

CELLS = [
    ("md", "# Crossing the Aisle: results and checks\n\n**Question:** when a change of government makes parties vote together, do their members' floor challenges and language follow?\n\nThis notebook reads the outputs of `tools/run_all.py`. See `AI_METHODS.md` for what each measure captures and misses. Hand labels may still be pending; the last section says."),
    ("code", """import json
import pandas as pd
from pathlib import Path

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
RESULTS = ROOT / "data" / "results"
read = lambda name: json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))
network, language, role, votes, summary, validation, labels = map(read, ["network", "language", "role", "votes", "summary", "validation", "label_checks"])
pd.set_option("display.width", 180, "display.max_columns", 30, "display.max_rows", 80)
pd.DataFrame(network["windows"])"""),
    ("md", "## 1. Votes set up the question\n\nRebel votes are rare, and vote network communities match party about as well after shuffling members' votes within their party. Member votes add nothing beyond party."),
    ("code", """pd.DataFrame(votes["rebels"])"""),
    ("code", """pd.DataFrame(votes["vote_network"]).T.drop(columns="community_parties")"""),
    ("md", "## 2. The challenge network\n\nEach row is one period between government formations. Compare modularity with the rewired null, and assortativity with the label shuffle."),
    ("code", """rows = []
for name, w in network["by_window"].items():
    rows.append({"window": name, **w["summary"],
                 "party_r": w["party_assortativity"]["observed"], "party_null": w["party_assortativity"]["null_mean"],
                 "side_r": w["side_assortativity"]["observed"], "side_null": w["side_assortativity"]["null_mean"],
                 "Q": w["communities"]["modularity"], "Q_null": w["communities"]["null_modularity_mean"],
                 "seed_nmi": w["communities"]["seed_stability_nmi_mean"], "party_nmi": w["communities"]["nmi_with_party"],
                 "share_committee": w["committee_test"]["share_sharing_a_committee"], "committee_null": w["committee_test"]["null_mean"]})
pd.DataFrame(rows).set_index("window")"""),
    ("md", "## 3. The main test: what changes at a formation\n\n`mean_effect` is in units of the spread of pairs whose relation did not change at that formation. Rows have different raw units, so compare each with its placebo rather than with each other."),
    ("code", """layers = {**summary["layers"], **summary["challenge_variants"]}
pd.DataFrame({k: {x: v[x] for x in ["pairs_tested", "right_direction", "mean_effect_in_placebo_sd", "median_effect", "p_one_sided", "formations_right_on_average"]} for k, v in layers.items()}).T"""),
    ("code", """focal = pd.DataFrame(network["transitions_all"])
focal = focal[focal["relation"].isin(["joined", "both_entered", "split"])]
focal[["transition", "pair", "relation", "observed_before", "expected_before", "observed_after", "expected_after", "log_ratio_change", "placebo_median"]]"""),
    ("md", "## 4. How fast: S and V around December 2022"),
    ("code", """t = network["timelines"]["S-V 2022-12-15"]
pd.DataFrame(t["votes"]).merge(pd.DataFrame(t["challenges"]), on="quarter")"""),
    ("md", "## 5. Language\n\nSame-debate similarity against a within-debate shuffle, the party classifier against shuffled labels, and the role classifier on a government it did not see. S–V similarity had been rising long before 2022."),
    ("code", """pd.DataFrame([r for r in language["same_debate"] if r["pair"] == "S-V"])"""),
    ("code", """pd.DataFrame([r for r in language["accuracy"] if r["pair"] == "S-V"])"""),
    ("code", """print(role["within_party"]["mean_gap"], "+/-", role["within_party"]["null_sd"], "p =", role["within_party"]["p"])
display(pd.DataFrame(role["within_party"]["parties"]))
pd.DataFrame(role["role_classifier"]).drop(columns=["opposition_words", "government_words"])"""),
    ("md", "## 6. Hand validation\n\n**Read these.** First, reproduce the observed S→V count for one sitting by reading the transcript turns printed below. Count the lines yourself and compare with the number from the pipeline."),
    ("code", """speeches = pd.read_parquet(ROOT / "data-raw" / "derived" / "speeches.parquet",
                           columns=["session", "meeting", "turn", "first", "last", "party", "role", "is_chair", "text"])
edges = pd.read_parquet(ROOT / "data" / "challenges.parquet")
pair = edges[edges["floor_party"].isin(["S", "V"]) & edges["challenger_party"].isin(["S", "V"]) & (edges["floor_party"] != edges["challenger_party"])]
session, meeting = pair.groupby(["session", "meeting"]).size().sort_values(ascending=False).index[3]
sitting = speeches[(speeches["session"] == session) & (speeches["meeting"] == meeting)].reset_index(drop=True)
found = pair[(pair["session"] == session) & (pair["meeting"] == meeting)]
print(f"Session {session}, sitting {meeting}: the pipeline finds {len(found)} S-V challenges. Each is shown as floor / chair / challenger:\\n")
for turn in found["turn"]:
    i = sitting.index[sitting["turn"] == turn][0]
    for row in sitting.iloc[i - 2:i + 1].itertuples():
        print(f"  [{row.party}] {row.first} {row.last}: {row.text[:150]}")
    print()"""),
    ("md", "Second, the agent's automated checks. These catch code bugs; they do not show that a measure means what we claim."),
    ("code", """pd.DataFrame(validation["checks"])"""),
    ("code", """validation["recounts"]"""),
    ("md", "## 7. Hand labels\n\nAgreement with the group's labels. `not labeled yet` means the result is still unvalidated, and the site says so."),
    ("code", """labels"""),
]


def main():
    book = nbf.v4.new_notebook()
    book["cells"] = [nbf.v4.new_markdown_cell(text) if kind == "md" else nbf.v4.new_code_cell(text) for kind, text in CELLS]
    OUT.parent.mkdir(exist_ok=True)
    nbf.write(book, OUT)
    subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace", str(OUT)], check=True, cwd=ROOT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
