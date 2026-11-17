#!/usr/bin/env python3
"""Runs the whole project from raw data to the site's data file.

    python tools/run_all.py

Downloads are throttled and cached, so the first run takes several hours and later runs reuse
the cache. Embedding takes about an hour on a 16-core CPU and is cached too. Steps run in order,
and the run stops at the first failure.

docs/data_recon.md's numbers come from recon_oda.py and recon_feasibility.py, which are not
part of this pipeline.
"""
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
STEPS = [
    "collect.py", "build_dataset.py", "make_labeling_sheets.py", "analyze_network.py", "analyze_votes.py",
    "analyze_language.py", "analyze_role.py", "analyze_archetypes.py", "summarize.py", "check_labels.py", "validate.py", "export_site.py", "make_notebook.py",
]


def main():
    for step in STEPS:
        print(f"\n=== {step} ===", flush=True)
        subprocess.run([sys.executable, str(TOOLS / step)], check=True, cwd=TOOLS.parent)
    print("\nDone. Serve the repo folder with: python -m http.server")


if __name__ == "__main__":
    main()
