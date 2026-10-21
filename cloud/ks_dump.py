"""一時: 東海の照合用に 台帳(走歴)・生年・レース・中央の本賞金(nar_jra_runs+nar_jra_race_prize)を JSON に書き出す(書き込みなし)"""
import datetime as dt
import gzip
import json
import os
import sys
import urllib.parse
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import class_calc as C  # noqa: E402

url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
rows, births, entered, races = C.fetch_tokai(url, key, dt.date(2025, 1, 1))
q = urllib.parse.quote
names = sorted({r["horse_name"] for r in rows})
hs = []
for i in range(0, len(names), 80):
    inq = ",".join('"' + n + '"' for n in names[i:i + 80])
    hs += C.sb_all(url, key, f"nar_jra_horses?select=kb_horse_id,horse_name,birth_date&horse_name=in.({q(inq)})")
ids = sorted({h["kb_horse_id"] for h in hs})
jr = []
for i in range(0, len(ids), 100):
    jr += C.sb_all(url, key, "nar_jra_runs?select=kb_horse_id,race_date,place,race_no,finish,race_name,field_size,kb_race_id"
                             f"&kb_horse_id=in.({','.join(ids[i:i + 100])})")
rids = sorted({r["kb_race_id"] for r in jr if r.get("kb_race_id") and (r.get("finish") or 99) <= 5})
hon = {}
for i in range(0, len(rids), 150):
    for p in C.sb_all(url, key, f"nar_jra_race_prize?select=kb_race_id,honsho&kb_race_id=in.({','.join(rids[i:i + 150])})"):
        hon[p["kb_race_id"]] = p.get("honsho")
by_h = defaultdict(list)
for r in jr:
    by_h[r["kb_horse_id"]].append(dict(r, honsho=hon.get(r.get("kb_race_id"))))
out = {"rows": [{"code": r["code"], "horse_name": r.get("horse_name"), "runs": r.get("runs") or []} for r in rows],
       "births": births, "races": [[k[0], k[1], k[2], v.get("race_name"), v.get("race_kind")] for k, v in races.items()],
       "jra_horses": hs, "jra_runs": by_h}
with gzip.open("tokai_dump.json.gz", "wt", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, default=str)
print("DUMP", len(out["rows"]), len(births), len(out["races"]), "jra", len(hs), len(jr), len(hon))
