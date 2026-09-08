# -*- coding: utf-8 -*-
"""§126 乗り替わり分析の集計表を夜間に作り直す(DB 側の関数 refresh_nar_jc() を 1 回呼ぶだけ)。

  python cloud/jockey_change.py --env pipeline/.env.nar            # 行数を見るだけ(書かない)
  python cloud/jockey_change.py --env pipeline/.env.nar --apply    # 作り直す(truncate + insert・1 トランザクション)
環境変数: SUPABASE_DB_PASSWORD(pg8000 直結・horse_changes.py と同じ)
表と定義= pipeline/sql/jockey_change_20260907.sql。
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import sys
import time

import pg8000.native

HOST = "aws-0-ap-northeast-1.pooler.supabase.com"
USER = "postgres.qgsnsdjvzzeazbazjlwa"
JST = dt.timezone(dt.timedelta(hours=9))


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8-sig").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    pw = os.environ.get("SUPABASE_DB_PASSWORD", "")
    if not pw:
        log("SUPABASE_DB_PASSWORD が要る")
        return 1
    con = pg8000.native.Connection(user=USER, password=pw, host=HOST, port=5432, database="postgres", ssl_context=True)
    try:
        before = con.run("select (select count(*) from nar_jc_runs), (select count(*) from nar_jc_trainer_jockey),"
                         " (select count(*) from nar_jc_pairs), (select count(*) from nar_jc_pop)")[0]
        meta = con.run("select value from nar_jc_meta where key = 'refresh'")
        log(f"いま: runs {before[0]:,} / 調教師×騎手 {before[1]:,} / ペア {before[2]:,} / 人気帯 {before[3]:,}"
            f" / 前回 {meta[0][0] if meta else '無し'}")
        if not a.apply:
            log("ドライラン(--apply で作り直す)")
            return 0
        t0 = time.time()
        con.run("set statement_timeout = '600s'")
        r = con.run("select * from refresh_nar_jc()")[0]
        log(f"作り直し {time.time() - t0:.0f}s: runs {r[0]:,} / 調教師×騎手 {r[1]:,} / ペア {r[2]:,} / 人気帯 {r[3]:,}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
