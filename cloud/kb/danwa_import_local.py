# -*- coding: utf-8 -*-
"""手元の厩舎の話(研究側 10/3 取得・{race_id}.json)を nar_kb_danwa へ入れる(2026-11-09)。

  python -I cloud/kb/danwa_import_local.py <dir> [--push] [--state <done.txt>]

- 行の形は supabase_push.push_race の danwa と同じ(track・race_date・race_no は race_id から)。
- 既にある行は上書きしない(Prefer resolution=ignore-duplicates・on_conflict=track,race_date,race_no,umaban)。
- 月ごと・500 行ずつ。済んだ月は --state に書き、再実行で飛ばす。
- 鍵は nar_push.creds()(環境変数 SUPABASE_URL / SUPABASE_SERVICE_KEY か .env.nar)。⛔印字しない。
"""
import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch_kb_all import KB_TRACK  # noqa: E402
from nar_push import creds  # noqa: E402
from parsers import race_id_parts  # noqa: E402

COLS = "track,race_date,race_no,umaban"


def rows_of(d):
    rid = str(d.get("race_id") or "")
    p = race_id_parts(rid)
    track = KB_TRACK.get(rid[6:8])
    dd = str(p.get("date") or "")
    if not track or len(dd) != 8 or not p.get("race_no"):
        return []
    base = {"track": track, "race_date": f"{dd[0:4]}-{dd[4:6]}-{dd[6:8]}", "race_no": int(p["race_no"]), "race_id": rid}
    return [dict(base, umaban=h["umaban"], horse_id=h.get("horse_id"), horse_name=h.get("horse_name"),
                 headline=h.get("headline"), trainer=h.get("trainer"), comment=h.get("comment"), raw=h.get("raw"))
            for h in d.get("horses") or [] if h.get("umaban") not in (None, "")]


def post(rows):
    base, key = creds()
    if not base:
        raise SystemExit("本体の鍵が無い")
    req = urllib.request.Request(f"{base}/rest/v1/nar_kb_danwa?on_conflict={COLS}", method="POST",
                                 data=json.dumps(rows, ensure_ascii=False).encode("utf-8"), headers={
                                     "apikey": key, "Authorization": "Bearer " + key,
                                     "Content-Type": "application/json",
                                     "Prefer": "resolution=ignore-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--state", default="")
    a = ap.parse_args()
    st = Path(a.state) if a.state else None
    done = set(st.read_text(encoding="utf-8").split()) if st and st.exists() else set()
    by_month = defaultdict(list)
    bad = 0
    for f in sorted(Path(a.dir).glob("*.json")):
        try:
            rs = rows_of(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            bad += 1
            continue
        for r in rs:
            by_month[(r["track"], r["race_date"][:7])].append(r)
    tot = defaultdict(int)
    for (t, m), rs in sorted(by_month.items()):
        tot[t] += len(rs)
        k = f"{t}:{m}"
        if not a.push or k in done:
            continue
        seen, uniq = set(), []
        for r in rs:
            kk = (r["track"], r["race_date"], r["race_no"], r["umaban"])
            if kk not in seen:
                seen.add(kk)
                uniq.append(r)
        for i in range(0, len(uniq), 500):
            post(uniq[i:i + 500])
        done.add(k)
        if st:
            with st.open("a", encoding="utf-8") as w:
                w.write(k + "\n")
        print(f"MONTH {k} 送った {len(uniq)}", flush=True)
    print("SUMMARY " + json.dumps({"rows_in_files": dict(tot), "bad_files": bad, "months": len(by_month)},
                                  ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
