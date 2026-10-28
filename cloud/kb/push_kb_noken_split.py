# -*- coding: utf-8 -*-
"""§117e/f 兵庫の能検レース割り(data/kb_noken/hyogo_split.json)を nar_meta `hyogo_noken_split` へ入れる(PC・service key)。

  py -3 scraper/push_kb_noken_split.py            # 投入(10/28〜 nar_meta の今の値と混ぜる= merge_split)
  py -3 scraper/push_kb_noken_split.py --dry-run  # 日数を見るだけ

鍵= s77-w1\\pipeline\\.env.nar(SUPABASE_URL / SUPABASE_SERVICE_KEY)。⛔鍵は印字しない。
cloud の noken_public.py(hyogo)がこの鍵を読んで公式の行をレース単位に組み直す(DESIGN §10 #502)。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPLIT = (Path(os.environ["KB_DATA_DIR"]) if os.environ.get("KB_DATA_DIR") else HERE.parent / "data") / "kb_noken" / "hyogo_split.json"   # cloud
NAR_ENV = Path(r"C:\Users\kouki\OneDrive\デスクトップ\s77-w1\pipeline\.env.nar")
KEY = "hyogo_noken_split"


def env_vals():
    if os.environ.get("SUPABASE_URL"):   # cloud(2026-09-30): secrets→環境変数(⛔印字しない)
        return os.environ["SUPABASE_URL"].rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    txt = NAR_ENV.read_text(encoding="utf-8")
    url = re.search(r"SUPABASE_URL=(\S+)", txt).group(1).rstrip("/")
    svc = re.search(r"SUPABASE_SERVICE_KEY=(\S+)", txt).group(1)
    return url, svc


def merge_split(current, local):
    """10/28 丸ごと差し替えをやめ、nar_meta の今の値(current)と手元(local)を日ごとに混ぜる。
    ①板つき(unverified なし)の手元の日が勝つ ②unverified の手元の日は、今の値が板つきなら上書きしない
    ③手元に無い日は今の値のまま残す。"""
    cur = dict(((current or {}).get("days") or {}))
    for date, day in (((local or {}).get("days") or {}).items()):
        old = cur.get(date)
        if day.get("unverified") and old and not old.get("unverified"):
            continue
        cur[date] = day
    out = dict(current or {})
    out.update({k: v for k, v in (local or {}).items() if k != "days"})
    out["days"] = dict(sorted(cur.items()))
    return out


def get_current(url, svc):
    req = urllib.request.Request(url + "/rest/v1/nar_meta?select=value&key=eq." + KEY,
                                 headers={"apikey": svc, "Authorization": "Bearer " + svc})
    with urllib.request.urlopen(req, timeout=60) as res:
        got = json.loads(res.read().decode("utf-8"))
    return got[0]["value"] if got and isinstance(got[0].get("value"), dict) else {"days": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not SPLIT.exists():
        print(f"split が無い: {SPLIT}")
        return 2
    data = json.loads(SPLIT.read_text(encoding="utf-8"))
    days = data.get("days") or {}
    print(f"split {len(days)} 日 ({min(days) if days else '-'} .. {max(days) if days else '-'})")
    if not days:
        return 0
    if a.dry_run and not os.environ.get("SUPABASE_URL"):
        return 0
    url, svc = env_vals()
    cur = get_current(url, svc)
    merged = merge_split(cur, data)
    nd = len(merged["days"])
    nu = sum(1 for d in merged["days"].values() if d.get("unverified"))
    print(f"混ぜた結果 {nd} 日(今の値 {len((cur.get('days') or {}))} 日・うち R 未確認 {nu} 日)")
    if a.dry_run:
        return 0
    body = json.dumps([{"key": KEY, "value": merged,
                        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]).encode()
    req = urllib.request.Request(
        url + "/rest/v1/nar_meta?on_conflict=key", data=body, method="POST",
        headers={"apikey": svc, "Authorization": "Bearer " + svc, "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal"})
    st = urllib.request.urlopen(req).status
    print(f"nar_meta/{KEY} upsert {st}")
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main())
