# -*- coding: utf-8 -*-
"""§117e/f 兵庫の能検レース割り(data/kb_noken/hyogo_split.json)を nar_meta `hyogo_noken_split` へ入れる(PC・service key)。

  py -3 scraper/push_kb_noken_split.py            # 投入(丸ごと差し替え= JSON が正本)
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
    if a.dry_run or not days:
        return 0
    url, svc = env_vals()
    body = json.dumps([{"key": KEY, "value": data,
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
