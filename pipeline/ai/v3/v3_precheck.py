# -*- coding: utf-8 -*-
"""前日の予想の便(nar-ai-v3)を動かす前の確かめ(2026-10-01・9/30 の事故の再発防止)。

  python -X utf8 pipeline/ai/v3/v3_precheck.py DAY [--auto] [--wait-min 40]
  python -X utf8 pipeline/ai/v3/v3_precheck.py DAY --count     # DB の南関のレース数だけ(当日の便が土台を待つかの判断)

9/30 の事故: 便が動いた 20:19 に DB へ翌日(10/1 = 翌月 1 日)の出馬表がまだ無く、0 頭のまま学習の模型に渡して落ちた。
  ・翌日の出馬表の取り込み(nar-refresh)は、月末に翌月の月次ZIPが無いと翌日分を入れられなかった
    → cloud/nextday_card.py で公式の出馬表ページから補う(同じ日に直した)
  ・この便は GitHub の時刻指定(14:30)だけで動き、実際は 6 時間遅れて 20:19 に動いていた
    → DB の時計(pg_cron)から 14:40・20:40・当日 09:35 に起動し、この確かめで「済み」なら何もしない

決め:
  ・南関 4 場の公式の開催一覧(出馬表ページの一覧)のレース数 n_off と、DB の nar_races のレース数 n_db を比べる。
  ・n_off = 0 かつ n_db = 0 → 開催なし(または出馬表の発表前)= 動かさない(緑)。後の回・当日の朝の回が拾う。
  ・--auto(DB の時計・GitHub の時刻指定から動いたとき)で、DB の v3-9 の印が全レース分ある → 済み = 動かさない(緑)。
    手で日付を指定したとき(--auto なし)は済みでも作り直す。
  ・n_db < n_off → 取り込み(20 分おき)を待つ。2 分おきに数え直し、--wait-min 分たっても足りなければ
    足りないまま止めずに作る(n_db > 0)/ 1 R も無ければ赤で止める(= 持ち主へ失敗のメール)。
出力: GITHUB_OUTPUT に run=yes|no。終了コード 0 / 1(出馬表が来ない)。
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "cloud"))
sys.path.insert(0, str(HERE.parents[2] / "pipeline"))
NANKAN = ("大井", "川崎", "船橋", "浦和")


def log(*a):
    print("[precheck]", *a, flush=True)


def rest(path):
    """読むだけ。鍵は前向きの写しと同じ公開の読み鍵(day2_db_copy.B・KEY)。"""
    sys.path.insert(0, str(HERE))
    from day2_db_copy import B, KEY
    url = B + path
    key = KEY
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def db_races(day):
    t = urllib.parse.quote("(" + ",".join(NANKAN) + ")")
    rows = rest(f"nar_races?select=track,race_no&race_date=eq.{day}&track=in.{t}")
    return {(r["track"], int(r["race_no"])) for r in rows}


def db_marks(day):
    rows = rest(f"nar_ai_marks?select=track,race_no&model=eq.v3-9&race_date=eq.{day}")
    return {(r["track"], int(r["race_no"])) for r in rows}


def official(day):
    """公式の開催一覧の南関のレース。取れなければ None。"""
    try:
        import nextday_card as nc
        d = dt.date.fromisoformat(day)
        out = set()
        for c in nc.day_tracks(d):
            t = nc.CODE2TRACK.get(c)
            if t in NANKAN:
                time.sleep(nc.SLEEP)
                out |= {(t, no) for no in nc.race_nos(d, c)}
        return out
    except Exception as e:  # noqa: BLE001
        log(f"公式の開催一覧が取れない({type(e).__name__}: {str(e)[:120]})= DB の数だけで決める")
        return None


def put(run):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"run={run}\n")
    log("run =", run)


def main():
    a = sys.argv[1:]
    day = a[0]
    dt.date.fromisoformat(day)
    if "--count" in a:                      # 当日の便(v3-gap-live)が使う: DB の南関のレース数だけ出す
        print(len(db_races(day)))
        return 0
    auto = "--auto" in a
    wait_min = int(a[a.index("--wait-min") + 1]) if "--wait-min" in a else 40
    off = official(day)
    have = db_races(day)
    marks = db_marks(day)
    log(f"{day}: 公式の開催一覧 {('?' if off is None else len(off))} R・DB の出馬表 {len(have)} R・DB の v3-9 の印 {len(marks)} R・auto={auto}")
    if not have and not off:
        log("開催なし(または出馬表の発表前)= 動かさない"); put("no"); return 0
    if auto and have and marks >= have and (off is None or marks >= off):
        log("全レースの印が済み = 動かさない"); put("no"); return 0
    t0 = time.time()
    while off and not off <= have and time.time() - t0 < wait_min * 60:
        log(f"出馬表が足りない {sorted(off - have)[:6]}… = 取り込みを待つ({(time.time() - t0) / 60:.0f}/{wait_min} 分)")
        time.sleep(120)
        have = db_races(day)
    if off and not off <= have:
        if not have:
            print(f"::error::⛔ {day} は公式に {len(off)} R あるのに DB に出馬表が 1 R も無い({wait_min} 分待った)。"
                  "nar-refresh(翌日の出馬表の取り込み)を確かめる", flush=True)
            put("no"); return 1
        print(f"::warning::{day} の出馬表が {len(off - have)} R 足りないまま作る(足りない分は印なし): {sorted(off - have)[:12]}", flush=True)
    put("yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
