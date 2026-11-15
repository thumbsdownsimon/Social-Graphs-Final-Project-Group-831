"""Layer 1: the challenge network, member measures, nulls and rule-based roles.

    python -m archetypes.run_network [--shuffles 500] [--null-group debate|window]

Reads data/challenges.parquet, data/governments.json, data/members.parquet.
Writes:
  data/archetypes/party_history.parquet    party runs per member (non-minister turns)
  data/archetypes/party_switches.parquet   one row per party switch
  data/archetypes/member_window.parquet    one row per member x window (and window 'all')
  data/archetypes/transitions.parquet      members eligible in two consecutive windows
  data/results/archetypes_network.json     summary for the notebook and site
"""
import argparse
import json
import sys
import time

import pandas as pd

from .config import MIN_EDGES, MIN_RUN, N_SHUFFLES, OUT, RESULTS, ROLE, SEED, DATA
from .data import load_all
from .graphs import graph_summary, graphs_by_window
from .metrics import member_table
from .nulls import member_nulls
from .roles import NEEDS_LANGUAGE, ROLES, assign_roles, roles_by_party, transition_summary, transitions

sys.stdout.reconfigure(encoding="utf-8")
TOP_N = 10


def switch_counts(switches, windows):
    """switches_in_window per (person, window), plus the 'all' window = career total."""
    rows = []
    for w in windows:
        part = switches[(switches["date"] >= w["from"]) & (switches["date"] < w["to"])]
        rows += [{"person": p, "window": w["name"], "switches_in_window": n} for p, n in part.groupby("person").size().items()]
    rows += [{"person": p, "window": "all", "switches_in_window": n} for p, n in switches.groupby("person").size().items()]
    return pd.DataFrame(rows, columns=["person", "window", "switches_in_window"])


def top_members(table, role, window, names, key):
    part = table[(table["window"] == window) & table[f"role_{role}"]].sort_values(key, ascending=False)
    return [{"person": int(r.person), "name": names.get(r.person), "party": r.party, key: round(float(getattr(r, key)), 4)}
            for r in part.head(TOP_N).itertuples()]


ROLE_SORT_KEY = {"attack_dog": "out_rate", "lightning_rod": "in_rate_backbench", "minister_rod": "in_rate_minister",
                 "bridge_builder": "participation", "friendly_fire": "z_own_side", "defector": "switches_in_window"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shuffles", type=int, default=N_SHUFFLES)
    parser.add_argument("--null-group", choices=["debate", "window"], default="debate")
    args = parser.parse_args(argv)
    start = time.time()

    edges, runs, switches, windows, days = load_all()
    names = pd.read_parquet(DATA / "members.parquet").set_index("person")["name"].to_dict()
    print(f"{len(edges)} labeled challenges, {edges['challenger'].nunique()} challengers, "
          f"{len(switches)} party switches", flush=True)

    graphs = graphs_by_window(edges, windows)
    tables, summaries = [], {}
    for name, (part, graph) in graphs.items():
        t = member_table(part, graph, days, name)
        null = member_nulls(part, n=args.shuffles, group="debate" if args.null_group == "debate" else None)
        tables.append(t.merge(null, on="person", how="left"))
        summaries[name] = graph_summary(graph, part)
        print(f"  {name:16s} {summaries[name]['nodes']:4d} members {summaries[name]['challenges']:6d} challenges "
              f"({time.time() - start:.0f}s)", flush=True)

    table = pd.concat(tables, ignore_index=True)
    table = table.merge(switch_counts(switches, windows), on=["person", "window"], how="left")
    table["switches_in_window"] = table["switches_in_window"].fillna(0).astype(int)
    table["n_switches_career"] = table["person"].map(switches.groupby("person").size()).fillna(0).astype(int)
    table.insert(1, "name", table["person"].map(names))
    table = assign_roles(table)

    order = [w["name"] for w in windows if w["name"] in graphs]
    trans = transitions(table, order)

    OUT.mkdir(parents=True, exist_ok=True)
    runs.to_parquet(OUT / "party_history.parquet", index=False)
    switches.assign(name=switches["person"].map(names)).to_parquet(OUT / "party_switches.parquet", index=False)
    table.to_parquet(OUT / "member_window.parquet", index=False)
    trans.to_parquet(OUT / "transitions.parquet", index=False)

    live_roles = [r for r in ROLES if r not in NEEDS_LANGUAGE]
    per_window_counts = {w: {r: int(g[f"role_{r}"].sum()) for r in live_roles} | {"eligible": int(g["eligible"].sum())}
                         for w, g in table.groupby("window", sort=False)}
    result = {
        "settings": {"shuffles": args.shuffles, "null_group": args.null_group, "seed": SEED,
                     "min_edges": MIN_EDGES, "min_run": MIN_RUN, "role_thresholds": ROLE},
        "graphs": summaries,
        "role_counts": per_window_counts,
        "roles_by_party_all": roles_by_party(table, "all").to_dict("records"),
        "roles_by_party": {w: roles_by_party(table, w).to_dict("records") for w in order},
        "top_members_all": {r: top_members(table, r, "all", names, ROLE_SORT_KEY[r]) for r in live_roles},
        "transitions": transition_summary(trans),
        "pending_roles": sorted(NEEDS_LANGUAGE),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "archetypes_network.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str),
                                                    encoding="utf-8")

    print("\nRoles over the whole period (window 'all'):")
    for r in live_roles:
        top = ", ".join(f"{m['name']} ({m['party']})" for m in result["top_members_all"][r][:5])
        print(f"  {r:15s} {per_window_counts['all'][r]:3d}  e.g. {top}")
    print(f"\nWrote {OUT.relative_to(DATA.parent)} and data/results/archetypes_network.json "
          f"in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
