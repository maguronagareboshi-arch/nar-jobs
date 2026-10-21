"""一時: 東海の照合用に 台帳(走歴)・生年・レースを JSON に書き出す(書き込みなし・手元で照合する)"""
import datetime as dt
import gzip
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import class_calc as C  # noqa: E402

url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
rows, births, entered, races = C.fetch_tokai(url, key, dt.date(2025, 1, 1))
out = {"rows": [{"code": r["code"], "horse_name": r.get("horse_name"), "runs": r.get("runs") or []} for r in rows],
       "births": births, "races": [[k[0], k[1], k[2], v.get("race_name"), v.get("race_kind")] for k, v in races.items()]}
with gzip.open("tokai_dump.json.gz", "wt", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, default=str)
print("DUMP", len(out["rows"]), len(births), len(out["races"]))
