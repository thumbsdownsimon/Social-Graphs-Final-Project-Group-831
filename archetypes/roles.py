"""Rule-based archetypes on the member x window table, and the tables built from them.

Every rule ranks members within one window, among members with at least MIN_EDGES
challenges made + received, so a busier parliament does not produce more attack dogs.
A member can hold several roles or none. Thresholds live in config.ROLE.
"""
import numpy as np
import pandas as pd

from .config import MIN_EDGES, ROLE

ROLES = ["attack_dog", "lightning_rod", "minister_rod", "bridge_builder", "friendly_fire", "defector",
         "negative_nancy"]
NEEDS_LANGUAGE = {"negative_nancy"}


def _pct(values, mask):
    """Percentile rank of values among mask rows; NaN outside the mask."""
    out = pd.Series(np.nan, index=values.index)
    out[mask] = values[mask].rank(pct=True)
    return out


def assign_window(t, r=ROLE, min_edges=MIN_EDGES):
    t = t.copy()
    eligible = (t["out_w"] + t["in_w"]) >= min_edges
    t["eligible"] = eligible

    out_pct = _pct(t["out_rate"], eligible)
    t["role_attack_dog"] = (eligible & (out_pct >= r["top"]) & (t["attack_balance"] >= r["attack_balance"])
                            & ((t["z_cross_side"] >= r["z"]) | (t["share_cross_side"] >= r["cross_side_share"])))

    backbench = eligible & (t["in_w_backbench"] > 0)
    in_pct = _pct(t["in_rate_backbench"], backbench)
    div_pct = _pct(t["in_party_diversity"], backbench)
    t["role_lightning_rod"] = backbench & (in_pct >= r["top"]) & (div_pct >= r["upper_half"])

    ministers = t["in_w_minister"] >= r["min_minister_in"]
    min_pct = _pct(t["in_rate_minister"], ministers)
    min_div = _pct(t["in_party_diversity"], ministers)
    t["role_minister_rod"] = ministers & (min_pct >= r["top"]) & (min_div >= r["upper_half"])

    part_pct = _pct(t["participation"], eligible)
    recip_pct = _pct(t["reciprocity"], eligible)
    t["role_bridge_builder"] = (eligible & (part_pct >= r["top"]) & (recip_pct >= r["upper_half"])
                                & (t["attack_balance"].abs() < r["attack_balance"]))

    t["role_friendly_fire"] = (eligible & (t["z_own_side"] >= r["z"]) & (t["share_own_side"] >= r["own_side_share"]))

    t["role_defector"] = t["switches_in_window"] > 0
    t["role_negative_nancy"] = pd.Series(pd.NA, index=t.index, dtype="boolean")  # needs tone (layer 2)

    for col in [f"role_{x}" for x in ROLES if x not in NEEDS_LANGUAGE]:
        t[col] = t[col].fillna(False).astype(bool)
    t["roles"] = [",".join(x for x in ROLES if x not in NEEDS_LANGUAGE and row[f"role_{x}"]) for _, row in t.iterrows()]
    return t


def assign_roles(table):
    return pd.concat([assign_window(part) for _, part in table.groupby("window", sort=False)], ignore_index=True)


def roles_by_party(table, window="all"):
    """For one window: per party, eligible members and how many hold each role."""
    part = table[table["window"] == window]
    rows = []
    for party, g in part.groupby("party", sort=True):
        row = {"party": party, "members": len(g), "eligible": int(g["eligible"].sum())}
        for role in ROLES:
            if role not in NEEDS_LANGUAGE:
                row[role] = int(g[f"role_{role}"].sum())
        rows.append(row)
    return pd.DataFrame(rows)


def transitions(table, window_order):
    """Members eligible in two consecutive windows: did their roles survive a change of office?

    event is what changed for that member between the windows: entered or left government,
    became or stopped being a minister, or nothing. Being a minister takes priority.
    """
    rows = []
    for before, after in zip(window_order, window_order[1:]):
        a = table[(table["window"] == before) & table["eligible"]].set_index("person")
        b = table[(table["window"] == after) & table["eligible"]].set_index("person")
        for person in a.index.intersection(b.index):
            x, y = a.loc[person], b.loc[person]
            if x["was_minister"] != y["was_minister"]:
                event = "became_minister" if y["was_minister"] else "stopped_minister"
            elif x["in_government"] != y["in_government"]:
                event = "entered_government" if y["in_government"] else "left_government"
            else:
                event = "no_change"
            row = {"person": int(person), "from_window": before, "to_window": after, "event": event,
                   "party_before": x["party"], "party_after": y["party"]}
            for role in ROLES:
                if role not in NEEDS_LANGUAGE:
                    row[f"{role}_before"], row[f"{role}_after"] = bool(x[f"role_{role}"]), bool(y[f"role_{role}"])
            rows.append(row)
    return pd.DataFrame(rows)


def transition_summary(trans):
    """Per role and event: how many held the role before, and how many of those kept it."""
    out = {}
    for role in ROLES:
        if role in NEEDS_LANGUAGE or trans.empty:
            continue
        per_event = {}
        for event, g in trans.groupby("event"):
            had = g[g[f"{role}_before"]]
            per_event[event] = {"pairs": len(g), "had_role": len(had), "kept": int(had[f"{role}_after"].sum()),
                                "gained": int((~g[f"{role}_before"] & g[f"{role}_after"]).sum())}
        out[role] = per_event
    return out
