# -*- coding: utf-8 -*-
"""§271 風の保存: 開催場の気象庁アメダス 10 分値(風向・風速・気温)を表 nar_wind_obs へ残す。

  python3 cloud/wind_store.py [--date YYYY-MM-DD] [--days N] [--dry-run]

  既定= JST の今日 1 日。--days N は今日から N 日前までを順に(初回の取り込み用・最大 10)。
  --dry-run= REST に書かず行数だけ出す・beat も呼ばない(nar_races は読む)。

窓= 1R の発走 − 30 分 〜 最終 R の発走。掛かる 3 時間ファイル(<stationId>/<yyyymmdd>_<hh>.json)だけ取る(1 場最大 5 本)。
点の規則は viewer の functions/api/wind/[venue].js の pointsOfFile と同じ(品質 0 だけ採用・dir は 1〜16 以外 null)。
⛔標準ライブラリだけ。環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(service_role)。
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

JST = dt.timezone(dt.timedelta(hours=9))
BASE = "https://www.jma.go.jp/bosai/amedas/data/point/"
UA = "nar-jobs wind_store"
JOB = "wind_store"

# viewer の js/weather-venues.js の 15 行(prefix, 場名, stationId)を写したもの
VENUES = [
    ("obihiro", "帯広", "20432"), ("monbetsu", "門別", "22141"), ("morioka", "盛岡", "33431"),
    ("mizusawa", "水沢", "33781"), ("urawa", "浦和", "43241"), ("funabashi", "船橋", "45106"),
    ("ooi", "大井", "44166"), ("kawasaki", "川崎", "44166"), ("kanazawa", "金沢", "56227"),
    ("kasamatsu", "笠松", "52586"), ("nagoya", "名古屋", "53041"), ("sonoda", "園田", "62051"),
    ("himeji", "姫路", "63383"), ("kochi", "高知", "74182"), ("saga", "佐賀", "82306"),
]
BY_KEY = {p: (p, n, s) for p, n, s in VENUES}
BY_KEY.update({n: (p, n, s) for p, n, s in VENUES})
BY_KEY["帯広ば"] = BY_KEY["帯広"]   # nar_races の track は「帯広ば」(ばんえい・9/24 初回取り込みで判明)


def venue_of(track):
    """track → (prefix, name, station)。完全一致 → 場名で始まる(「帯広ば」等)の順"""
    t = str(track or "").strip()
    if t in BY_KEY:
        return BY_KEY[t]
    for p, n, s in VENUES:
        if t.startswith(n):
            return (p, n, s)
    return None


def log(msg):
    print(msg, flush=True)


def _env():
    return os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")


def rest(path, body=None, timeout=60):
    url, key = _env()
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA, "Content-Type": "application/json"}
    if body is not None:
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    req = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, method="GET" if body is None else "POST",
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def _q(row, key):
    v = row.get(key) if isinstance(row, dict) else None
    if isinstance(v, list) and len(v) >= 2 and v[1] == 0 and isinstance(v[0], (int, float)) \
            and not isinstance(v[0], bool) and math.isfinite(v[0]):
        return v[0]
    return None


def points_of_file(rows, ymd):
    """上流 1 本分 → [{t, dir, speed, temp}](その日の分だけ・t は HH:MM)。品質 0 以外は null。"""
    if not isinstance(rows, dict):
        raise ValueError("Invalid observations")
    out = []
    for key in sorted(k for k in rows if re.fullmatch(r"\d{14}", k) and k[:8] == ymd):
        r = rows[key]
        d, sp = _q(r, "windDirection"), _q(r, "wind")
        out.append({
            "t": key[8:10] + ":" + key[10:12],
            "dir": int(d) if d is not None and float(d).is_integer() and 1 <= d <= 16 else None,
            "speed": sp if sp is not None and sp >= 0 else None,
            "temp": _q(r, "temp"),
        })
    return out


def in_window(points, lo, hi):
    """窓(HH:MM の lo〜hi・両端含む)の点だけ。"""
    return [p for p in points if lo <= p["t"] <= hi]


def window_of(post_times):
    """発走 HH:MM の一覧 → (lo, hi)。lo = 最初 − 30 分(0:00 で止める)・hi = 最後。"""
    mins = sorted(int(t[:2]) * 60 + int(t[3:5]) for t in post_times)
    lo = max(0, mins[0] - 30)
    return f"{lo // 60:02d}:{lo % 60:02d}", f"{mins[-1] // 60:02d}:{mins[-1] % 60:02d}"


def hours_of(lo, hi):
    return list(range(int(lo[:2]) // 3 * 3, int(hi[:2]) + 1, 3))


def fetch_file(station, ymd, hh):
    url = f"{BASE}{station}/{ymd}_{hh:02d}.json"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=4) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        return json.loads(r.read())


def races_of(date):
    """nar_races → {track: [post_time HH:MM, ...]}。"""
    got = rest("nar_races?select=track,race_no,post_time"
               f"&race_date=eq.{date}&order=track.asc,race_no.asc&limit=1000") or []
    out = {}
    for r in got:
        raw = str(r.get("post_time") or "").strip()
        # 本番の post_time は 'HHMM'(例 1040)。'HH:MM' でも受ける(9/24 dry-run で判明)
        t = raw[:2] + ":" + raw[2:4] if re.fullmatch(r"\d{4}", raw) else raw[:5]
        if re.fullmatch(r"\d{2}:\d{2}", t):
            out.setdefault(r["track"], []).append(t)
    return out


def run_day(date, now, dry):
    """1 日分。戻り= (場数, 行数, 取れなかった場)。場の表に無い track は要判断で止まる。"""
    ymd = date.replace("-", "")
    races = races_of(date)
    if not races:
        log(f"{date} 開催なし")
        return 0, 0, []
    bad = [t for t in races if t and venue_of(t) is None]
    if bad:
        log(f"要判断: 場の表に無い track {bad}")
        raise SystemExit(2)
    day0 = dt.datetime.fromisoformat(date + "T00:00:00+09:00")
    n_v, n_rows, failed = 0, 0, []
    for track, times in races.items():
        prefix, name, station = venue_of(track)
        lo, hi = window_of(times)
        hours = hours_of(lo, hi)[:5]
        pts, got_files = [], 0
        for h in hours:
            if day0 + dt.timedelta(hours=h) > now:
                continue                                  # まだ始まっていない 3 時間
            try:
                pts += points_of_file(fetch_file(station, ymd, h), ymd)
                got_files += 1
            except Exception as e:                        # noqa: BLE001
                log(f"⚠{name} {ymd}_{h:02d} 取れない: {type(e).__name__}: {str(e)[:80]}")
        pts = in_window(pts, lo, hi)
        rows = [{"venue": prefix, "obs_at": f"{date}T{p['t']}:00+09:00",
                 "dir": p["dir"], "speed": p["speed"], "temp": p["temp"]} for p in pts]
        if rows and not dry:
            for i in range(0, len(rows), 60):
                rest("nar_wind_obs?on_conflict=venue,obs_at", rows[i:i + 60])
        log(f"{date} {name}({prefix}) 窓 {lo}〜{hi} ファイル {got_files}/{len(hours)} 行 {len(rows)}"
            + (" (dry-run)" if dry else ""))
        if rows:
            n_v += 1
            n_rows += len(rows)
        else:
            failed.append(name)
    return n_v, n_rows, failed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    url, key = _env()
    if not url or not key:
        log("要判断: SUPABASE_URL / SUPABASE_SERVICE_KEY が無い(nar_races が読めない)")
        return 2
    now = dt.datetime.now(JST)
    if a.date:
        dates = [a.date]
    else:
        n = max(1, min(10, a.days))
        dates = [(now.date() - dt.timedelta(days=i)).isoformat() for i in range(n)]
    tot_v, tot_rows, failed, err = 0, 0, [], None
    try:
        for d in dates:
            v, r, f = run_day(d, now, a.dry_run)
            tot_v, tot_rows = tot_v + v, tot_rows + r
            failed += [f"{d} {x}" for x in f]
    except SystemExit:
        raise
    except Exception as e:                                # noqa: BLE001
        err = f"{type(e).__name__}: {str(e)[:120]}"
        log(f"⚠失敗: {err}")
    note = f"{tot_v}場 {tot_rows}行"
    ok = err is None and not failed
    if not ok:
        note += " 取れない: " + (err or ", ".join(failed))[:200]
    log(("ok " if ok else "fail ") + note)
    if not a.dry_run:
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "beat.py"), JOB,
                        "ok" if ok else "fail", note], check=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
