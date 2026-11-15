"""Toy cases for layer 1, with answers worked out by hand.

    python tests/test_network.py      (or: pytest tests)
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from archetypes.data import appearances, label_edges, load_windows, party_runs, party_switches  # noqa: E402
from archetypes.graphs import build_graph  # noqa: E402
from archetypes.metrics import member_table  # noqa: E402
from archetypes.nulls import member_nulls, permute_within  # noqa: E402
from archetypes.roles import transitions  # noqa: E402

GOVERNMENTS = [{"from": "2020-01-01", "parties": ["V"]}]
# Person 1, 5: EL (red, opposition). 2: DF (blue, opposition). 3: V minister. 4: V member.


def raw_edge(date, challenger, c_party, floor, f_party, f_minister=False, debate=1, turn=0):
    return {"session": "20191", "meeting": debate, "date": date, "item": "1", "case_number": "1", "turn": turn,
            "floor_person": float(floor), "floor_party": f_party, "floor_is_minister": f_minister,
            "challenger_person": float(challenger), "challenger_party": c_party, "challenger_is_minister": False,
            "challenger_words": 50, "status": "Typeset"}


def toy_raw():
    rows = []
    # Before the window: person 3 speaks as an ordinary V member three times (builds the party run).
    rows += [raw_edge("2019-06-01", 3, "V", 2, "DF", turn=t) for t in (3, 6, 9)]
    # In the window. The minister's tag is wrong ("DD") on purpose: it must be re-labeled V.
    rows += [raw_edge("2020-02-01", 1, "EL", 3, "DD", f_minister=True, turn=t) for t in (3, 6, 9)]
    rows += [raw_edge("2020-02-01", 1, "EL", 2, "DF", turn=12)]
    rows += [raw_edge("2020-02-02", 5, "EL", 1, "EL", turn=3)]
    rows += [raw_edge("2020-02-02", 2, "DF", 3, "DD", f_minister=True, turn=6)]
    rows += [raw_edge("2020-02-02", 4, "V", 1, "EL", turn=9)]
    return pd.DataFrame(rows)


def toy_edges():
    raw = toy_raw()
    runs = party_runs(appearances(raw))
    return raw, runs, label_edges(raw, runs, GOVERNMENTS, load_windows(GOVERNMENTS))


def test_party_runs_drop_noise_and_merge():
    labels = ["A", "A", "A", "B", "A", "A", "C", "C", "C"]
    apps = pd.DataFrame({"person": 7, "party": labels, "is_minister": False,
                         "date": [f"2020-01-{i + 1:02d}" for i in range(len(labels))]})
    runs = party_runs(apps, min_run=3)
    # B (1 turn) and the second A (2 turns) are noise; what is left is A then C.
    assert runs["party"].tolist() == ["A", "C"], runs
    assert runs["n"].tolist() == [3, 3]
    sw = party_switches(runs)
    assert len(sw) == 1 and sw.iloc[0]["from_party"] == "A" and sw.iloc[0]["to_party"] == "C"
    assert sw.iloc[0]["date"] == "2020-01-07"


def test_short_history_keeps_longest_run():
    apps = pd.DataFrame({"person": 8, "party": ["A", "B", "B"], "is_minister": False,
                         "date": ["2020-01-01", "2020-01-02", "2020-01-03"]})
    assert party_runs(apps, min_run=3)["party"].tolist() == ["B"]


def test_minister_relabeled_and_edges_labeled():
    _, _, e = toy_edges()
    assert len(e) == 7  # the three 2019 edges fall before the first window
    assert set(e.loc[e["floor"] == 3, "f_party"]) == {"V"}
    first = e[(e["challenger"] == 1) & (e["floor"] == 3)].iloc[0]
    assert first["cross_side"] and first["at_government"] and first["cross_bloc"] == 1.0 and not first["own_side"]
    el_df = e[(e["challenger"] == 1) & (e["floor"] == 2)].iloc[0]
    # Two opposition parties from opposite blocs: neither cross-side nor allies.
    assert not el_df["cross_side"] and not el_df["own_side"]
    same = e[(e["challenger"] == 5)].iloc[0]
    assert same["same_party"] and same["own_side"]


def test_member_measures_by_hand():
    raw, _, e = toy_edges()
    days = np.array(sorted(raw["date"].unique()))
    t = member_table(e, build_graph(e), days, "w").set_index("person")
    one = t.loc[1]
    assert (one["out_w"], one["in_w"]) == (4, 2)
    assert math.isclose(one["attack_balance"], 1 / 3)
    assert math.isclose(one["share_cross_side"], 0.75)
    assert math.isclose(one["share_at_government"], 0.75)
    assert math.isclose(one["share_cross_bloc"], 1.0)
    assert one["share_own_side"] == 0
    h = -(0.75 * math.log(0.75) + 0.25 * math.log(0.25)) / math.log(2)
    assert math.isclose(one["target_entropy"], h)
    assert math.isclose(one["top_target_share"], 0.75)
    assert math.isclose(one["in_party_diversity"], 0.5)  # challenged once by EL, once by V
    assert one["reciprocity"] == 0  # challenges 2 and 3, challenged by 4 and 5
    assert one["exposure_days"] == 2
    three = t.loc[3]
    assert three["was_minister"] and three["in_w_minister"] == 4 and three["in_w_backbench"] == 0
    assert three["minister_share"] == 1.0 and three["in_government"]


def test_permute_within_stays_in_group():
    rng = np.random.default_rng(0)
    codes = np.array([2, 0, 1, 0, 2, 2, 1, 0])
    for _ in range(20):
        perm = permute_within(codes, rng)
        assert (codes[perm] == codes).all()
        assert sorted(perm) == list(range(len(codes)))


def test_within_debate_null_is_degenerate_with_one_floor_holder():
    # Every debate has a single floor holder, so shuffling floors inside debates changes nothing.
    _, _, e = toy_edges()
    e = e.assign(debate=e["floor"].astype(str))
    null = member_nulls(e, n=30, group="debate").set_index("person")
    assert math.isclose(null.loc[1, "null_cross_side"], 0.75)
    assert np.isnan(null.loc[1, "z_cross_side"])


def test_window_null_flags_a_one_sided_attacker():
    # 20 members challenge evenly; member 99 (opposition) only ever challenges ministers.
    rng = np.random.default_rng(1)
    rows = []
    for i in range(400):
        c = int(rng.integers(1, 20))
        f = int(rng.integers(1, 20))
        if f == c:
            continue
        rows.append((c, f))
    rows += [(99, 100)] * 30
    e = pd.DataFrame(rows, columns=["challenger", "floor"])
    gov = lambda p: p >= 100 or p % 2 == 0  # noqa: E731
    e["c_gov"], e["f_gov"] = e["challenger"].map(gov), e["floor"].map(gov)
    e["c_party"] = np.where(e["c_gov"], "V", "EL")
    e["f_party"] = np.where(e["f_gov"], "V", "EL")
    e["c_bloc"] = np.where(e["c_gov"], "blue", "red")
    e["f_bloc"] = np.where(e["f_gov"], "blue", "red")
    e["debate"] = "d"
    null = member_nulls(e, n=300, group=None, seed=2).set_index("person")
    assert null.loc[99, "z_cross_side"] > 3 and null.loc[99, "p_cross_side"] < 0.01


def test_transition_events():
    base = {"party": "S", "eligible": True, "was_minister": False, "in_government": False}
    roles = {f"role_{r}": False for r in ["attack_dog", "lightning_rod", "minister_rod", "bridge_builder",
                                          "friendly_fire", "defector"]}
    t = pd.DataFrame([
        {**base, **roles, "person": 1, "window": "a", "role_attack_dog": True},
        {**base, **roles, "person": 1, "window": "b", "in_government": True},
        {**base, **roles, "person": 2, "window": "a"},
        {**base, **roles, "person": 2, "window": "b", "was_minister": True, "in_government": True},
    ])
    tr = transitions(t, ["a", "b"]).set_index("person")
    assert tr.loc[1, "event"] == "entered_government" and tr.loc[1, "attack_dog_before"] and not tr.loc[1, "attack_dog_after"]
    assert tr.loc[2, "event"] == "became_minister"


if __name__ == "__main__":
    tests = [(name, f) for name, f in sorted(globals().items()) if name.startswith("test_")]
    for name, f in tests:
        f()
        print("ok", name)
    print(f"{len(tests)} tests passed")
