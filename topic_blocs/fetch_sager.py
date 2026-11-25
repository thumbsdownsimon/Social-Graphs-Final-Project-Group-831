"""Fetch Sag rows (L, B, F, R) per session 2009-10 onward with SagAktør and Sagstrin dates,
plus names of committees and ministry areas. Sagstrin typeid marks floor-debate stages.
Saves sager.parquet (one row per sag) and actors.parquet."""
import sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data" / "topic_blocs"
sys.path.insert(0, str(ROOT / "tools"))
import oda_client as oda  # noqa: E402
oda.THROTTLE_SECONDS = 1.0

periods = oda.fetch_all("Periode", select="id,kode,type")
sessions = {r["id"]: r["kode"] for r in periods if r["type"] == "samling" and r["kode"] >= "20091"}
PLENARY = {3, 7, 10, 12, 15, 17, 23, 45, 56, 60, 87, 107}  # Sagstrinstype ids of floor debates
rows = []
for typeid in [5, 3, 2, 11]:
    for pid, kode in sorted(sessions.items(), key=lambda x: x[1]):
        sager = oda.fetch_all("Sag", filter=f"typeid eq {typeid} and periodeid eq {pid}", expand="SagAktør,Sagstrin",
                              select="id,nummer,periodeid,titelkort,SagAktør/aktørid,SagAktør/rolleid,Sagstrin/dato,Sagstrin/typeid")
        for s in sager:
            rows.append({"sag": s["id"], "typeid": typeid, "nummer": s["nummer"], "session": int(kode),
                         "title": s["titelkort"],
                         "dates": sorted({t["dato"][:10] for t in s["Sagstrin"] if t["dato"]}),
                         "debate_dates": sorted({t["dato"][:10] for t in s["Sagstrin"]
                                                 if t["dato"] and t["typeid"] in PLENARY}),
                         "committee": [a["aktørid"] for a in s["SagAktør"] if a["rolleid"] == 11],
                         "ministry": [a["aktørid"] for a in s["SagAktør"] if a["rolleid"] == 6],
                         "minister": [a["aktørid"] for a in s["SagAktør"] if a["rolleid"] == 14]})
        print(typeid, kode, len(sager), flush=True)
pd.DataFrame(rows).to_parquet(DATA / "sager.parquet", index=False)
actors = []
for t in [1, 2, 3]:
    actors += oda.fetch_all("Aktør", filter=f"typeid eq {t}", select="id,typeid,navn")
pd.DataFrame(actors).to_parquet(DATA / "actors.parquet", index=False)
print(len(rows), len(actors))
