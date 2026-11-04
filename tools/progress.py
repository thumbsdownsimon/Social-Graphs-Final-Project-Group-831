#!/usr/bin/env python3
"""Live progress of tools/run_all.py. Only reads the log, so closing it affects nothing.

    python tools/run_all.py > run_all.log 2>&1
    python tools/progress.py run_all.log          # refreshes until Ctrl+C
    python tools/progress.py run_all.log --once   # prints once
"""
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_all import STEPS

REFRESH_SECONDS = 3
# Rough share of a rerun with downloads and embeddings already cached, only for the bar's width.
TYPICAL_MINUTES = {"collect.py": 1, "build_dataset.py": 3, "make_labeling_sheets.py": 1, "analyze_network.py": 8, "analyze_votes.py": 3,
                   "analyze_language.py": 15, "analyze_role.py": 6, "summarize.py": 1, "check_labels.py": 1, "validate.py": 3,
                   "export_site.py": 1, "make_notebook.py": 1}

sys.stdout.reconfigure(encoding="utf-8")
started = {}


def bar(share, width=36):
    filled = int(share * width)
    return f"[{'#' * filled}{'-' * (width - filled)}] {share * 100:5.1f}%"


def minutes(seconds):
    return f"{seconds / 60:.0f} min" if seconds >= 90 else f"{seconds:.0f} s"


def screen(path):
    if not path.exists():
        return "Pipeline: not started"
    log = path.read_text(encoding="utf-8", errors="replace")
    done_steps = re.findall(r"^=== (\S+) ===", log, re.M)
    finished = "Done. Serve" in log
    failed = "Traceback" in log
    current = done_steps[-1] if done_steps else None
    if current and current not in started:
        started[current] = time.time()
    total = sum(TYPICAL_MINUTES.values())
    complete = STEPS if finished else [s for s in STEPS if s in done_steps and s != current]
    share = 1.0 if finished else sum(TYPICAL_MINUTES[s] for s in complete) / total
    lines = [f"PIPELINE  {bar(share)}  step {len(done_steps)} of {len(STEPS)}", ""]
    for step in STEPS:
        mark = "x" if step in complete else ">" if step == current and not finished else " "
        extra = ""
        if step == current and not finished and step in started:
            extra = f"  running, seen for {minutes(time.time() - started[step])}"
        lines.append(f"  [{mark}] {step}{extra}")
    embedded = re.findall(r"^embedded (\d+) of (\d+)", log, re.M)
    if embedded and current == "analyze_language.py":
        lines += ["", f"  embedded {int(embedded[-1][0]):,} of {int(embedded[-1][1]):,} chunks"]
    lines += ["", f"Log last changed {minutes(time.time() - path.stat().st_mtime)} ago (steps print little until they end)."]
    if finished:
        lines.append("FINISHED")
    if failed:
        lines += ["FAILED:", "  " + log.strip().splitlines()[-1][:110]]
    return "\n".join(lines)


def main():
    path = Path(next(a for a in sys.argv[1:] if not a.startswith("--")))
    while True:
        text = screen(path)
        if "--once" in sys.argv:
            print(text)
            return
        os.system("cls" if os.name == "nt" else "clear")
        print(f"{datetime.now():%H:%M:%S}  (read-only; closing this window does not affect the run)\n\n{text}")
        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
