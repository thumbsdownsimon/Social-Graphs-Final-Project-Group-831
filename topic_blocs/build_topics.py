"""Link each debate (session, meeting, item) to one Sag and a topic area.
Match: same session, same number, and a floor-debate Sagstrin on the debate date
(else any Sagstrin on that date). Topic: the committee the
case was referred to, else its ministry area, else the minister title, grouped by keyword rules
(first rule that matches wins). Saves debate_topics.parquet and topic_map.csv."""
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data" / "topic_blocs"

RULES = [  # (area, stems); order matters
    ("procedure", ["forretningsorden", "valgs prøvelse"]),
    ("immigration", ["udlænding", "integration", "indfødsret", "flygtning"]),
    ("justice", ["retsudvalg", "justits"]),
    ("foreign_defence", ["forsvar", "udenrig", "europa", "grønland", "færø", "udvikling", "nordisk"]),
    ("labour", ["beskæftigelse", "arbejdsmarked"]),
    ("economy", ["skat", "finans", "økonomi", "erhverv", "vækst", "digitalisering", "ejendomsvurdering",
                 "afskrivning", "handel", "virksomhed"]),
    ("environment_energy", ["miljø", "fødevare", "landbrug", "fiskeri", "klima", "energi", "forsyning",
                            "nordsø", "grøn"]),
    ("education_culture", ["undervisning", "uddannelse", "kultur", "kirke", "forskning", "videnskab", "børne- og"]),
    ("welfare_health", ["social", "sundhed", "ældre", "ligestilling", "epidemi", "børnetilskud", "frikort",
                        "børn", "forebyggelse"]),
    ("infrastructure_local", ["transport", "trafik", "bolig", "kommunal", "indenrig", "landdistrikt", "by-",
                              "bygning", "økonomi- og indenrig"]),
    ("general", ["statsminist"]),
]


OVERRIDES = {"Ministeriet for Videnskab, Teknologi og Udvikling": "education_culture",
             "Børne- og Socialministeriet": "welfare_health",
             "Ministeriet for Samfundssikkerhed og Beredskab": "foreign_defence",
             "Udvalget til Prøvelse af Valgene": "procedure"}


def area(name):
    if not name:
        return None
    if name in OVERRIDES:
        return OVERRIDES[name]
    low = name.lower()
    for a, stems in RULES:
        if any(s in low for s in stems):
            return a
    return "other"


s = pd.read_parquet(DATA / "sager.parquet")
actors = pd.read_parquet(DATA / "actors.parquet")
nm = dict(zip(actors.id, actors.navn.str.strip()))
s["num"] = s.nummer.str.extract(r"(\d+)")[0]


def source(row):
    for col in ["committee", "ministry", "minister"]:
        for x in row[col]:
            if nm.get(x):
                return col, nm[x]
    return None, None


s[["src", "src_name"]] = s.apply(lambda r: pd.Series(source(r)), axis=1)
s["topic"] = s.src_name.map(area)

c = pd.read_parquet(ROOT / "data" / "challenges.parquet")
c["session"] = c.session.astype(int)
c["date"] = c.date.astype(str).str[:10]
d = c.groupby(["session", "meeting", "item", "case_number", "date"]).size().rename("n").reset_index()
d["num"] = d.case_number.astype(str).str.extract(r"(\d+)")[0]
m = d.merge(s, on=["session", "num"], how="left")
key = ["session", "meeting", "item"]
# Prefer a floor-debate stage on the debate date; fall back to any stage on that date.
m["plen"] = [isinstance(x, np.ndarray) and dt in set(x) for x, dt in zip(m.debate_dates, m.date)]
m["any"] = [isinstance(x, np.ndarray) and dt in set(x) for x, dt in zip(m.dates, m.date)]
has_plen = m.groupby(key).plen.transform("any")
m = m[np.where(has_plen, m.plen, m["any"])]
agg = m.groupby(key).agg(n=("n", "first"), n_cand=("sag", "size"), topics=("topic", lambda x: sorted(set(x.dropna()))),
                         nummer=("nummer", lambda x: "/".join(x)), title=("title", "first"),
                         src=("src", "first")).reset_index()
agg["topic"] = [t[0] if len(t) == 1 else ("ambiguous" if len(t) > 1 else None) for t in agg.topics]
agg["debate"] = agg.session.astype(str) + "-" + agg.meeting.astype(str) + "-" + agg.item.astype(str)
agg.drop(columns="topics").to_parquet(DATA / "debate_topics.parquet", index=False)

tm = s.dropna(subset=["src_name"]).groupby(["src", "src_name", "topic"]).size().rename("n_sager").reset_index()
tm.sort_values(["topic", "n_sager"], ascending=[True, False]).to_csv(DATA / "topic_map.csv", index=False)

tot = d.n.sum()
print("debates", len(d), "matched", len(agg), f"edge share {agg.n.sum() / tot:.4f}")
print("candidates>1:", (agg.n_cand > 1).sum(), "ambiguous topic:", (agg.topic == "ambiguous").sum())
print("topic source:", agg.src.value_counts().to_dict())
print((agg.groupby("topic", dropna=False).n.sum() / tot).round(3).sort_values(ascending=False))
print(tm[tm.topic == "other"].sort_values("n_sager", ascending=False).head(15))
