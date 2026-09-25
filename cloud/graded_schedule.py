# -*- coding: utf-8 -*-
"""検索集客 案 2-④(2026-09-26) 地方競馬の年間の重賞日程を表 nar_graded_schedule に残す。

  python cloud/graded_schedule.py --dry-run --out x.csv     # 取って数えて CSV だけ(DB に書かない)
  python cloud/graded_schedule.py --apply --out x.csv       # 便(graded-schedule.yml)。upsert→消えた行を消す→heartbeat
  python cloud/graded_schedule.py --html saved.html --year 2026   # 保存した HTML を読む(通信しない)

取り込み元= 地方競馬全国協会の「重賞競走一覧」https://www.keiba.go.jp/gradedrace/schedule_<年>.html(UTF-8・1/1〜12/31)。
  1 競走= <li class="..."> の中に <p class="date">12/29</p> <p class="name">東京大賞典</p>
  <p class="icon ...">GⅠ</p> <p class="area">大井</p> <p class="course">2000m</p> <div class="mare">。
対象の年= JST の今年。11 月以降は来年の一覧も試す(まだ無ければ飛ばす= 失敗にしない)。
⛔今年の一覧が取れない・100 件未満 = 形が変わった疑い= heartbeat fail で止める(古い行は消さない)。
環境変数(--apply のとき): SUPABASE_URL / SUPABASE_SERVICE_KEY。
"""
import argparse
import csv
import datetime as dt
import html as htmlmod
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

URL_TMPL = "https://www.keiba.go.jp/gradedrace/schedule_{year}.html"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TABLE = "nar_graded_schedule"
BEAT_JOB = "graded_schedule"
MIN_ROWS = 100            # 2026 年は 345 件。これを割ったら形が変わった疑い
JST = dt.timezone(dt.timedelta(hours=9))
TRACKS = {"帯広", "門別", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢", "笠松", "名古屋",
          "園田", "姫路", "高知", "佐賀"}
COLS = ["sched_year", "race_date", "track", "race_name", "grade", "distance_m", "mare_only", "detail_url", "fetched_at"]


def log(*a):
    print(*a, flush=True)


def fetch(url):
    """本文(str)。404 は None(来年の一覧がまだ無い)。それ以外の失敗は 3 回試して例外。"""
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"取得できない: {type(last).__name__}: {str(last)[:160]}")


def _p(block, cls):
    m = re.search(r'<p class="' + cls + r'">([^<]*)</p>', block)
    return htmlmod.unescape(m.group(1)).strip() if m else ""


def parse(h, year):
    """一覧 HTML → 行の list。日付・名前・場が読めない <li> は数えて捨てる(戻り値の 2 つ目)。"""
    rows, bad = [], 0
    seen = set()
    for cls, block in re.findall(r'<li class="([^"]*)">(.*?)</li>', h, re.S):
        d = _p(block, "date")
        if not d:
            continue                                   # 日付の無い <li> はメニュー等
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", d)
        name = _p(block, "name")
        area = _p(block, "area")
        if not m or not name or area not in TRACKS:
            bad += 1
            continue
        try:
            date = dt.date(int(year), int(m.group(1)), int(m.group(2)))
        except ValueError:
            bad += 1
            continue
        grades = [htmlmod.unescape(g).strip() for g in re.findall(r'<p class="icon[^"]*">([^<]*)</p>', block)]
        grades = [g for g in grades if g]
        dist = re.search(r"(\d+)\s*m", _p(block, "course"))
        link = re.search(r'<a href="([^"]+)"', block)
        key = (date.isoformat(), area, name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "sched_year": int(year), "race_date": date.isoformat(), "track": area, "race_name": name,
            "grade": grades[0] if grades else None,
            "distance_m": int(dist.group(1)) if dist else None,
            "mare_only": bool(re.search(r"(^|\s)mare(\s|$)", cls)),
            "detail_url": link.group(1) if link else None,
        })
    return rows, bad


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in COLS})


def apply_rows(url, key, year, rows):
    from load_nar_official import upsert
    for i in range(0, len(rows), 500):
        st, msg = upsert(url, key, TABLE, "race_date,track,race_name", rows[i:i + 500])
        if st >= 300 or st == 0:
            raise RuntimeError(f"upsert {st} {msg}")
    # 同じ年を取り直したとき、今回の一覧から消えた行(延期・名前の訂正)を消す= 今回の fetched_at より古いもの
    fa = rows[0]["fetched_at"]
    path = f"{TABLE}?sched_year=eq.{int(year)}&fetched_at=lt.{urllib.parse.quote(fa)}"
    req = urllib.request.Request(f"{url}/rest/v1/{path}", method="DELETE", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=60):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="表へ書く(無ければドライラン)")
    ap.add_argument("--dry-run", action="store_true", help="CSV だけ(既定)")
    ap.add_argument("--out", help="CSV の出力先(既定= graded_schedule_<年>.csv)")
    ap.add_argument("--html", help="保存した HTML を読む(通信しない・--year と組で)")
    ap.add_argument("--year", type=int, help="年(既定= JST の今年)")
    a = ap.parse_args()
    apply_ = a.apply and not a.dry_run
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    import beat as B

    def say(ok, note):
        if apply_:
            B.beat(BEAT_JOB, ok, note)
        log(f"heartbeat {BEAT_JOB} {'ok' if ok else 'fail'} {note}" + ("" if apply_ else "(ドライラン= 書かない)"))

    now = dt.datetime.now(JST)
    this_year = a.year or now.year
    years = [this_year] + ([this_year + 1] if (not a.html and not a.year and now.month >= 11) else [])
    fa = now.isoformat(timespec="seconds")
    notes = []
    all_rows = []
    for y in years:
        try:
            h = open(a.html, encoding="utf-8").read() if a.html else fetch(URL_TMPL.format(year=y))
        except Exception as e:
            if y != this_year:
                log(f"::warning::{y} 年の一覧を取れない(来年分なので飛ばす): {e}")
                continue
            log(f"::error::{y} 年の重賞一覧を取得できない: {e}")
            say(False, f"取得失敗 {str(e)[:80]}")
            return 2
        if h is None:
            if y != this_year:
                log(f"{y} 年の一覧はまだ無い(404)= 飛ばす")
                continue
            log(f"::error::{y} 年の重賞一覧が 404")
            say(False, f"{y} 年が 404")
            return 2
        rows, bad = parse(h, y)
        log(f"{y} 年: {len(rows)} 件(読めない行 {bad})")
        if len(rows) < MIN_ROWS:
            if y != this_year:
                log(f"::warning::{y} 年は {len(rows)} 件だけ= 未公開とみなして飛ばす")
                continue
            log(f"::error::{y} 年が {len(rows)} 件(< {MIN_ROWS})= 形が変わった疑い。書かない")
            say(False, f"{y} 年 {len(rows)} 件だけ")
            return 3
        for r in rows:
            r["fetched_at"] = fa
        all_rows.append((y, rows))
        notes.append(f"{y}={len(rows)}")
    out = a.out or f"graded_schedule_{this_year}.csv"
    write_csv(out, [r for _, rs in all_rows for r in rs])
    log(f"CSV= {out}")
    if not apply_:
        return 0
    if not url or not key:
        log("::error::SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 1
    try:
        for y, rows in all_rows:
            apply_rows(url, key, y, rows)
    except Exception as e:
        log(f"::error::投入失敗: {e}")
        say(False, f"投入失敗 {str(e)[:80]}")
        return 1
    say(True, " ".join(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
