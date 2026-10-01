# -*- coding: utf-8 -*-
"""南関 AI v3 の予想が出ているかの見張り(nar-watchdog から毎時・2026-10-01)。

9/30 の事故: 前日の便(nar-ai-v3)が 0 頭で落ち、10/1 の予想と当日の買い候補が出なかったのに、
誰にも知らせが来なかった(朝に別の作業中にたまたま気付いた)。

赤にする(= 持ち主へ失敗のメール)とき:
  1. JST 10 時以降: 今日の南関のレース(公式の開催一覧 ∪ DB)に、v3-9 の印の無いレースがある
  2. JST 10 時以降: 今日の印はあるのに、当日の便が読む前日の土台(成果物 v3-gap-base-今日)が無い
  3. JST 22 時以降: 明日の南関のレースに、v3-9 の印の無いレースがある
  (前日の便は DB の時計で 14:40・20:40、当日 09:35 に起動。出馬表を待つと最長 40 分かかる)

  python -X utf8 pipeline/ai/v3/v3_watch.py [--now 2026-10-01T22:25]   # --now は手元の試験用
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "cloud"))
NANKAN = ("大井", "川崎", "船橋", "浦和")
JST = dt.timezone(dt.timedelta(hours=9))
SRC = (HERE / "day2_db_copy.py").read_text(encoding="utf-8")      # 公開の読み鍵(前向きの写しと同じ)を pandas なしで読む
B = re.search(r"^B = '([^']+)'", SRC, re.M).group(1)
KEY = re.search(r"^KEY = '([^']+)'", SRC, re.M).group(1)


def rest(path):
    req = urllib.request.Request(B + path, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def db_races(day):
    t = urllib.parse.quote("(" + ",".join(NANKAN) + ")")
    return {(r["track"], int(r["race_no"])) for r in rest(f"nar_races?select=track,race_no&race_date=eq.{day}&track=in.{t}")}


def marks(day):
    return {(r["track"], int(r["race_no"])) for r in rest(f"nar_ai_marks?select=track,race_no&model=eq.v3-9&race_date=eq.{day}")}


def official(day):
    try:
        import time
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
        print(f"公式の開催一覧が取れない({type(e).__name__}: {str(e)[:120]})= DB だけで見る", flush=True)
        return set()


def base_artifact(day):
    repo = os.environ.get("GITHUB_REPOSITORY", "maguronagareboshi-arch/nar-jobs")
    tok = os.environ.get("GH_TOKEN", "")
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/artifacts?name=v3-gap-base-{day}&per_page=10",
                                 headers={"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {tok}"} if tok else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        arts = json.loads(r.read().decode("utf-8")).get("artifacts") or []
    return any(not a.get("expired") for a in arts)


def check(day, label):
    want = db_races(day) | official(day)
    got = marks(day)
    miss = sorted(want - got)
    print(f"{label} {day}: 南関 {len(want)} R・v3-9 の印 {len(got & want)} R", flush=True)
    if miss:
        return [f"{label} {day} の予想が無いレース {len(miss)} R: {miss[:12]}(nar-ai-v3 を確かめる)"], want, got
    return [], want, got


def main():
    a = sys.argv[1:]
    now = dt.datetime.fromisoformat(a[a.index("--now") + 1]).replace(tzinfo=JST) if "--now" in a else dt.datetime.now(JST)
    today = now.date().isoformat()
    tomorrow = (now.date() + dt.timedelta(days=1)).isoformat()
    errs = []
    if now.hour >= 10:
        e, want, got = check(today, "今日")
        errs += e
        if want and got and not base_artifact(today):
            errs.append(f"今日 {today} の印はあるのに前日の土台(v3-gap-base-{today})が無い = 当日の買い候補が出ない")
    if now.hour >= 22:
        e, _, _ = check(tomorrow, "明日")
        errs += e
    for x in errs:
        print("::error::⛔ " + x, flush=True)
    if not errs:
        print("v3 の予想: 問題なし", flush=True)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
