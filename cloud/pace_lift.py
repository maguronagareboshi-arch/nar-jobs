# -*- coding: utf-8 -*-
"""本体 cloud: 脚質 × ペースの「3 着内率の倍率」(§224 段 2a)。

過去 12 か月の**実走**を 場 × 距離帯 × 脚質 × ペース で数え、nar_meta `pace_lift:v1` の
1 行に入れる。⛔本番 DB では数えない(REST で月ごとに読み、数えるのはこのプロセスの中)。

  母集団(⛔ユーザー決定 2026-09-22)
    場        = nar_races.track(表に無い場= 帯広ばは対象外)
    距離帯    = round(distance_m / 200) * 200。⛔1200m 未満は前半の意味が変わるので入れない
    脚質      = nar_run_facts.style(発走前 as-of の 逃げ/先行/差し/追込。NULL の走は数えない)
    ペース    = nar_race_pace.pace(速い/平均/遅い)。⛔この行の無いレースは丸ごと数えない
    3 着内    = nar_runs.finish <= 3。分母は「走った」= 着順あり or 競走中止/失格
                (⛔「競走取止め」= 取消はレースが成立していないので分母から外す)
    20 走未満 = rate / lift を null にする(⛔1.0 で埋めない= 画面は「—」)

  値の形    {"months": [from, to], "asof": …, "base": {"場|距離帯": {n, top3, rate}},
             "cells": {"場|距離帯|脚質|ペース": {n, top3, rate, base_rate, lift}}}
    rate      = top3 / n(その枡)
    base_rate = 場 × 距離帯の**全体**(脚質もペースも問わない)の 3 着内率
    lift      = rate / base_rate

  py -3.12 -X utf8 cloud/pace_lift.py --env pipeline/.env.nar --dry
  py -3.12 -X utf8 cloud/pace_lift.py --env pipeline/.env.nar --from 2025-09 --to 2026-09 --dry
  py -3.12 -X utf8 cloud/pace_lift.py --env pipeline/.env.nar --apply
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY  ⛔--env が無ければ環境変数だけで動く
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000行キャップ: 全取得はページング(tenkai.rows_window)。⛔offset の order= は一意に。
⛔updated_at を必ず送る。⛔200KB を超えたら場ごとの鍵に分ける(索引の 1 行を pace_lift:v1 に残す)。
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# ⛔場の表とページングの割り方は cloud/tenkai.py の 1 か所だけ(3 か所目を作らない)
import tenkai                                                      # noqa: E402,F401
from tenkai import TRACK2PREFIX, rows_window, CHIHOU_MIN_DIST      # noqa: E402

UA = "nar-jobs/1.0"
META_KEY = "pace_lift:v1"
JST = dt.timezone(dt.timedelta(hours=9))
MONTHS = 12                # 窓(既定)= 直前の月で終わる 12 か月
CELL_MIN = 20              # この走数未満の枡は rate / lift を出さない(⛔1.0 で埋めない)
BAND = 200                 # 距離帯の刻み
SIZE_MAX = 200000          # これを超えたら場ごとの鍵に分ける
STYLES = ("逃げ", "先行", "差し", "追込")
PACES = ("速い", "平均", "遅い")

# 「走った」= 着順あり or 競走中止/失格。⛔日本語は URL に入る前に符号化する
RAN = "or=(finish.gt.0,finish_note.in.(%s,%s))" % (
    urllib.parse.quote('"競走中止"'), urllib.parse.quote('"失格"'))
PACE_TMPL = ("/rest/v1/nar_race_pace?select=track,race_date,race_no,pace"
             "&race_date=gte.{lo}&race_date=lte.{hi}"
             "&order=race_date.asc,track.asc,race_no.asc")
RACE_TMPL = ("/rest/v1/nar_races?select=track,race_date,race_no,distance_m"
             "&distance_m=gte.%d&race_date=gte.{lo}&race_date=lte.{hi}"
             "&order=race_date.asc,track.asc,race_no.asc" % CHIHOU_MIN_DIST)
FACT_TMPL = ("/rest/v1/nar_run_facts?select=track,race_date,race_no,umaban,style"
             "&style=not.is.null&race_date=gte.{lo}&race_date=lte.{hi}"
             "&order=race_date.asc,track.asc,race_no.asc,umaban.asc")
RUN_TMPL = ("/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,finish"
            "&race_date=gte.{lo}&race_date=lte.{hi}&" + RAN +
            "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc")


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(base, key, path, method="GET", body=None, prefer=None, tries=2):
    """⛔Supabase は一時的に 500 を返す。GET は 1 回だけ待って引き直す(course_stats と同じ)。"""
    last = None
    for i in range(tries):
        r = urllib.request.Request(base + path, method=method, data=body, headers={
            "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
            "Content-Type": "application/json",
            "Prefer": prefer or "resolution=merge-duplicates,return=minimal"})
        try:
            with urllib.request.urlopen(r, timeout=180) as x:
                return x.status, x.headers.get("Content-Range"), x.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last = e
            if method != "GET" or e.code < 500 or i == tries - 1:
                raise
            log("  ⚠ HTTP %d。5 秒待って引き直す" % e.code)
            time.sleep(5)
        except urllib.error.URLError as e:
            last = e
            if i == tries - 1:
                raise
            log("  ⚠ 通信に失敗。5 秒待って引き直す: %s" % str(e)[:80])
            time.sleep(5)
    raise last


def window(base, key, tmpl, lo, hi):
    """30 日の窓に割って集める。⛔窓ごとに 1 回だけ引き直す(読みなので何度でも同じ)"""
    for i in range(2):
        try:
            return rows_window(base, key, tmpl, lo, hi)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if i:
                raise
            log("  ⚠ 取得に失敗(%s)。10 秒待って窓ごと引き直す" % str(e)[:60])
            time.sleep(10)
    return []


# ---------------------------------------------------------------- 月の並び

def month_range(months_from, months_to):
    """YYYY-MM の 2 つ → [(月, 初日, 末日), …]"""
    out = []
    y, m = (int(x) for x in months_from.split("-"))
    ey, em = (int(x) for x in months_to.split("-"))
    while (y, m) <= (ey, em):
        lo = dt.date(y, m, 1)
        hi = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
        out.append(("%04d-%02d" % (y, m), lo.isoformat(), hi.isoformat()))
        y, m = y + (m == 12), m % 12 + 1
    return out


def default_months(today):
    """⛔既定= 直前の月で終わる 12 か月(当月は月半ばなので入れない)"""
    y, m = today.year, today.month
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    ay, am = y, m - (MONTHS - 1)
    while am <= 0:
        ay, am = ay - 1, am + 12
    return "%04d-%02d" % (ay, am), "%04d-%02d" % (y, m)


# ---------------------------------------------------------------- 集計

def band_of(distance_m):
    """距離帯= 200m 刻み。⛔1200m 未満は入れない(前半の意味が別物)。

    ⛔丸めは**半分は上**(1300 → 1400)。Python の round() は偶数丸めで 1300 → 1200 になり、
      画面(JS の Math.round)と食い違うのでここでは使わない。
    """
    d = int(distance_m)
    return None if d < CHIHOU_MIN_DIST else int((d + BAND // 2) // BAND) * BAND


def count(paces, races, facts, runs, acc=None):
    """4 つの行の並び → ({(場, 帯): [n, top3]}, {(場, 帯, 脚質, ペース): [n, top3]})。

    ⛔レースの鍵は (track, race_date, race_no)。ペースの行が無い / 距離帯が出ない /
      脚質が無い / 走っていない のどれかで落ちた走は**どちらの数にも入れない**。
    """
    base, cells = acc if acc else ({}, {})
    pace_of = {(r["track"], r["race_date"], int(r["race_no"])): r.get("pace")
               for r in paces if r.get("pace") in PACES}
    race_of = {}
    for r in races:
        tr = r.get("track")
        if tr not in TRACK2PREFIX or r.get("distance_m") is None:
            continue                                   # ⛔帯広ばなど表に無い場は落とす
        b = band_of(r["distance_m"])
        if b is not None:
            race_of[(tr, r["race_date"], int(r["race_no"]))] = (TRACK2PREFIX[tr], b)
    style_of = {(r["track"], r["race_date"], int(r["race_no"]), int(r["umaban"])): r.get("style")
                for r in facts if r.get("style") in STYLES}
    for r in runs:
        u = r.get("runner_number")
        if u is None:
            continue
        rk = (r["track"], r["race_date"], int(r["race_no"]))
        pace, cell = pace_of.get(rk), race_of.get(rk)
        if not pace or not cell:
            continue
        style = style_of.get(rk + (int(u),))
        if not style:
            continue
        fin = r.get("finish")
        f = int(fin) if isinstance(fin, int) or (isinstance(fin, str) and str(fin).isdigit()) else None
        top3 = 1 if f is not None and f <= 3 else 0
        b = base.setdefault(cell, [0, 0])
        b[0] += 1
        b[1] += top3
        c = cells.setdefault(cell + (style, pace), [0, 0])
        c[0] += 1
        c[1] += top3
    return base, cells


def pack(base, cells, months, asof):
    """数 → nar_meta に入れる形。⛔20 走未満は rate/lift を null(1.0 で埋めない)"""
    out_base, out_cells = {}, {}
    for (prefix, b), (n, t) in sorted(base.items()):
        out_base["%s|%d" % (prefix, b)] = {
            "n": n, "top3": t, "rate": round(t / float(n), 4) if n >= CELL_MIN else None}
    for (prefix, b, style, pace), (n, t) in sorted(cells.items()):
        bn, bt = base.get((prefix, b), [0, 0])
        br = round(bt / float(bn), 4) if bn >= CELL_MIN else None
        rate = round(t / float(n), 4) if n >= CELL_MIN else None
        lift = round(rate / br, 3) if (rate is not None and br) else None
        out_cells["%s|%d|%s|%s" % (prefix, b, style, pace)] = {
            "n": n, "top3": t, "rate": rate, "base_rate": br, "lift": lift}
    return {"months": [months[0][0], months[-1][0]], "asof": asof,
            "min_n": CELL_MIN, "base": out_base, "cells": out_cells}


def split_by_track(value):
    """200KB 超のとき= 場ごとの鍵に分ける。索引の 1 行を pace_lift:v1 に残す"""
    parts = {}
    for name in ("base", "cells"):
        for k, v in value[name].items():
            parts.setdefault(k.split("|", 1)[0], {"base": {}, "cells": {}})[name][k] = v
    out = []
    for prefix in sorted(parts):
        one = {"months": value["months"], "asof": value["asof"], "min_n": value["min_n"]}
        one.update(parts[prefix])
        out.append((META_KEY + ":" + prefix, one))
    out.append((META_KEY, {"months": value["months"], "asof": value["asof"],
                           "min_n": value["min_n"], "split": True, "tracks": sorted(parts)}))
    return out


def size_of(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def upsert(api, key, meta_key, value):
    st, _cr, _b = req(api, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                      json.dumps([{"key": meta_key, "value": value,
                                   "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]
                                 ).encode("utf-8"))
    return st


# ---------------------------------------------------------------- 本体

def build(api, key, months):
    """月ごとに 4 つの表を読み、手元で数える。⛔本番に計算させない"""
    acc = ({}, {})
    for name, lo, hi in months:
        t0 = time.time()
        paces = window(api, key, PACE_TMPL, lo, hi)
        if not paces:
            log("  %s  ペースの行なし= この月は数えない" % name)
            continue
        races = window(api, key, RACE_TMPL, lo, hi)
        facts = window(api, key, FACT_TMPL, lo, hi)
        runs = window(api, key, RUN_TMPL, lo, hi)
        acc = count(paces, races, facts, runs, acc)
        log("  %s  pace %5d / race %5d / facts %6d / run %6d  %.1f 秒"
            % (name, len(paces), len(races), len(facts), len(runs), time.time() - t0))
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ upsert(既定はドライラン)")
    ap.add_argument("--dry", action="store_true", help="ドライラン(明示・既定と同じ)")
    ap.add_argument("--from", dest="m_from", help="始めの月 YYYY-MM")
    ap.add_argument("--to", dest="m_to", help="終わりの月 YYYY-MM")
    ap.add_argument("--out", help="組んだ値を JSON ファイルにも書く(検品・画面のモック用)")
    ap.add_argument("--env")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    api = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not api or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2

    today = dt.datetime.now(JST).date()
    d_from, d_to = default_months(today)
    months = month_range(a.m_from or d_from, a.m_to or d_to)
    log("■ 脚質 × ペースの倍率 %s〜%s(%d か月)" % (months[0][0], months[-1][0], len(months)))
    t0 = time.time()
    base, cells = build(api, key, months)
    if not cells:
        log("⛔数えられた走が 1 つも無い= 書かない")
        return 2
    value = pack(base, cells, months, today.isoformat())
    small = sum(1 for c in value["cells"].values() if c["lift"] is None)
    log("  枡 %d(うち %d 走未満= %d・%.1f%%)・場×距離帯 %d・%d バイト・所要 %.0f 秒"
        % (len(value["cells"]), CELL_MIN, small, 100.0 * small / len(value["cells"]),
           len(value["base"]), size_of(value), time.time() - t0))
    if a.out:
        io.open(a.out, "w", encoding="utf-8").write(json.dumps(value, ensure_ascii=False))
        log("  → %s にも書いた" % a.out)
    rows = [(META_KEY, value)] if size_of(value) <= SIZE_MAX else split_by_track(value)
    if len(rows) > 1:
        log("  200KB 超= 場ごとの鍵 %d 行に分ける" % (len(rows) - 1))
    if not a.apply:
        log("  ← ドライラン(--apply なし)。書く先= " + " / ".join(k for k, _v in rows))
        return 0
    rc = 0
    for meta_key, v in rows:
        st = upsert(api, key, meta_key, v)
        log("  → nar_meta/%s %s(%d バイト)" % (meta_key, st, size_of(v)))
        if st not in (200, 201):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
