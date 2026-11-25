"""Link each vote (Afstemning) to its Sag through Sagstrin, and give it the Sag's topic.
Saves vote_topics.parquet (vote, sag, topic). Votes on Sag types we did not fetch get no topic."""
import sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data" / "topic_blocs"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))
import oda_client as oda  # noqa: E402
oda.THROTTLE_SECONDS = 1.0

rows = oda.fetch_all("Afstemning", filter="id ge 1", expand="Sagstrin", select="id,sagstrinid,Sagstrin/sagid")
v = pd.DataFrame([{"vote": r["id"], "sag": (r.get("Sagstrin") or {}).get("sagid")} for r in rows])
s = pd.read_parquet(DATA / "sager.parquet")
import build_topics as bt  # noqa: E402  (re-runs the topic build; cheap, no API calls)
topic = dict(zip(bt.s.sag, bt.s.topic))
v["topic"] = v.sag.map(topic)
v.to_parquet(DATA / "vote_topics.parquet", index=False)
pp = pd.read_parquet(ROOT / "data" / "party_positions.parquet")
print(len(v), "votes in party_positions with topic:", pp.drop_duplicates("vote").vote.map(dict(zip(v.vote, v.topic))).notna().mean())
