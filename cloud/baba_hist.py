#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""馬場差の全期間ファイル(持ちタイム表の「馬場差」「補正タイム」用・2026-10-17)。

baba.py(nar_meta baba_diff= 直近 90 日だけ)と**同じ方式**(as-of・前日までの 1 年・1〜5着・場×距離×クラス帯→退避・
going 版の d= 良馬場比 / g= 同じ馬場状態比)で、データのある最初の日から今日までの日×場を組み、
公開バケット cond-stats の v1/baba-hist/<prefix>.json に場ごとに 1 本で上げる。計算は baba.build_days をそのまま呼ぶ。

  形 = {"v":1, "built":"YYYY-MM-DD", "track":"高知", "days": {"2026-02-02": {"d":-0.8, "g":0.1, "d1":-0.45, "g1":0.05, "k":"重"}, …}}
       d1/g1(2026-10-26)= 補正タイム用の 1000m あたりの秒。画面は 時計 − d1×距離/1000×場ごとの倍率。
       ⛔南関 4 場は d1・d を予想 AI の日の値(nar_meta nankan_d5)にそろえ "s":"ai"(baba.overlay_ai・確定済みの日も毎回かぶせ直す)
       当日(まだ終わっていない日)は "p":true(暫定)。翌朝の便で確定して p が消える。

  ⛔確定した日は組み直さない(baba.py の frozen と同じ)。組むのは ファイルに無い日・前回 p の日・当日 だけ。
    --rebuild-all のときだけ全部作り直す(定義を変えたときの作り直し用)。
  毎朝(cond-stats.yml の後ろの手順): 直近 14 日だけ組む(標準の窓ぶん 395 日を遡って読む)。
    その場のファイルがまだ無ければ、その場だけ全期間を組む(自己修復)。
  --full(手動便 workflow_dispatch の baba_full): 全期間(2014-01-01〜)を場ごとに年ずつ読んで組む。
    場ごとに組み終えたら 1 本ずつ上げる(途中で落ちても組み終えた場は残る)= --venue で残りだけ流し直せる。
  ⛔本番 DB は REST の単純 select だけ(場ごと・年ごと・一意の order でページ送り)。DB には書かない。
  ⛔ばんえい(帯広ば)は出さない(baba.py と同じ)。

  py -3.12 -X utf8 cloud/baba_hist.py --dry-run --venue kochi --out out/   # 上げずに手元へ(読み取りだけ・anon キー可)
  python3 cloud/baba_hist.py --apply            # 毎朝
  python3 cloud/baba_hist.py --apply --full     # 全期間(手動便)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(dry-run は SUPABASE_ANON_KEY でも可)
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baba  # noqa: E402
import cond_stats  # noqa: E402

DIR = "baba-hist/"
FIRST_DATE = dt.date(2014, 1, 1)     # nar_races の最古(2026-10-17 実測)
DAILY_DAYS = 14                      # 毎朝 組み直す候補の日数(確定済みは据え置くので実際は p と新しい日だけ)
KEEP = ("d", "g", "d1", "g1", "k", "p", "s")   # d1/g1= 補正タイム用の 1000m あたり・s="ai"= 南関は予想 AI の値(2026-10-26)


def log(msg):
    print(msg, flush=True)


def fetch_track(rest, track, since, until):
    """[since, until] の 1〜5着の時計と、レースの距離・名前・馬場。年ごとに区切って読む(offset を浅く)"""
    wins, races = [], []
    tq = cond_stats.enc(track)
    y = since.year
    while y <= until.year:
        lo = max(since, dt.date(y, 1, 1)).isoformat()
        hi = min(until, dt.date(y, 12, 31)).isoformat()
        rng = f"&track=eq.{tq}&race_date=gte.{lo}&race_date=lte.{hi}"
        wins += rest.paged("nar_runs?select=track,race_date,race_no,finish,runner_number,time_sec"
                           f"&finish=gte.1&finish=lte.{baba.TOP_N}&time_sec=not.is.null&finish_note=is.null" + rng,
                           "race_date.asc,race_no.asc,finish.asc,runner_number.asc")
        races += rest.paged("nar_races?select=track,race_date,race_no,distance_m,race_name,going,race_kind" + rng,
                            "race_date.asc,race_no.asc")
        y += 1
    return wins, races


def to_samples(track, wins, races):
    """baba.py main と同じ並べ方(同着は速い方 1 本・距離の無いレースは捨てる)"""
    meta = {(r["race_date"], r["race_no"]): r for r in races}
    best = {}
    for w in wins:
        kk = (w["race_date"], w["race_no"], int(w["finish"]))
        if kk not in best or float(w["time_sec"]) < float(best[kk]["time_sec"]):
            best[kk] = w
    out = []
    for w in best.values():
        m = meta.get((w["race_date"], w["race_no"]))
        if not m or not m.get("distance_m"):
            continue
        b = baba.band_of(m.get("race_name"), track, m.get("race_kind"))
        out.append((track, w["race_date"], int(m["distance_m"]), b, float(w["time_sec"]),
                    str(m.get("going") or ""), w["race_no"], int(w["finish"])))
    return out


def merge_days(prefix, samples, targets, old_days, today, rebuild_all):
    """baba.build_days を 1 場ぶんで呼び、前回のファイルの確定済みの日と合わせる。戻り= (days, 組み直した日数)"""
    frozen = {d: {prefix: c} for d, c in (old_days or {}).items()}
    built, rebuilt, _ = baba.build_days(samples, targets, baba.DEFAULT_BASELINE, today=today, frozen=frozen,
                                        rebuild_all=rebuild_all)
    days = {} if rebuild_all else {d: dict(c) for d, c in (old_days or {}).items()}
    for d, cells in built.items():
        c = cells.get(prefix)
        if c:
            days[d] = {k: c[k] for k in KEEP if k in c}
    return dict(sorted(days.items())), rebuilt


def read_ai(rest):
    """nar_meta nankan_d5 の days(南関の予想 AI の日の値)。読めなければ {}= 南関もサイトの計算のまま"""
    try:
        rows = rest.get("nar_meta?select=value&key=eq.%s" % baba.AI_META_KEY)
        v = rows[0].get("value") if rows else None
        return (v or {}).get("days") or {}
    except Exception as e:                           # noqa: BLE001
        log("⚠%s を読めない(%s)= 南関もサイトの計算のまま" % (baba.AI_META_KEY, e))
        return {}


def read_old(rest, prefix):
    try:
        raw = rest.req("/storage/v1/object/%s/%s%s%s.json" % (cond_stats.BUCKET, cond_stats.ROOT, DIR, prefix))
        return json.loads(raw.decode("utf-8")).get("days") or {}
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        raise


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="cond-stats/v1/baba-hist/ へ上げる")
    g.add_argument("--dry-run", action="store_true", help="上げずに --out へ書く")
    ap.add_argument("--full", action="store_true", help="全期間(2014-01-01〜)を組む")
    ap.add_argument("--rebuild-all", action="store_true", help="⛔確定済みの日も作り直す(定義を変えたときだけ)")
    ap.add_argument("--venue", default="", help="場の URL 名(カンマ区切り・空= ばんえい以外の 14 場)")
    ap.add_argument("--out", default="baba_hist_out")
    ap.add_argument("--today", default="", help="JST の当日(YYYY-MM-DD・既定= 今日)")
    a = ap.parse_args(argv)
    base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or (os.environ.get("SUPABASE_ANON_KEY", "") if a.dry_run else "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    want = [v.strip() for v in a.venue.split(",") if v.strip()]
    venues = [(p, t) for t, p in baba.TRACK2PREFIX.items() if not want or p in want]
    if want and len(venues) != len(want):
        raise SystemExit("知らない場: %s" % sorted(set(want) - {p for p, _ in venues}))
    today = dt.date.fromisoformat(a.today) if a.today else baba._today_jst()
    rest = cond_stats.Rest(base, key)
    if a.apply:
        cond_stats.ensure_bucket(rest)
    fails = {}
    ai = None
    for prefix, track in venues:
        t0 = time.time()
        try:
            old = None if a.rebuild_all else read_old(rest, prefix)
            full = a.full or a.rebuild_all or old is None
            if full:
                since, lo = FIRST_DATE, FIRST_DATE.isoformat()
            else:
                lo = (today - dt.timedelta(days=DAILY_DAYS)).isoformat()
                since = today - dt.timedelta(days=DAILY_DAYS + baba.fetch_days(baba.DEFAULT_BASELINE))
            wins, races = fetch_track(rest, track, since, today)
            samples = to_samples(track, wins, races)
            targets = {s[1] for s in samples if lo <= s[1] <= today.isoformat()}
            targets |= {d for d in (old or {}) if lo <= d <= today.isoformat()}
            # ⛔標準は前日までの1年= その場の最初のレースから 1 年たつ前の日は標準が欠ける(2014 年・姫路の再開直後)→ 出さない
            fr = rest.get("nar_races?select=race_date&track=eq.%s&order=race_date.asc&limit=1" % cond_stats.enc(track))
            ok_from = (dt.date.fromisoformat(fr[0]["race_date"]) + dt.timedelta(days=365)).isoformat() if fr else lo
            targets = {d for d in targets if d >= ok_from}
            days, rebuilt = merge_days(prefix, samples, targets, old, today, a.rebuild_all)
            days = {d: v for d, v in days.items() if d >= ok_from}
            if track in baba.AI_TRACKS:                  # 南関は予想 AI の日の値にそろえる(確定済みの日も毎回)
                ai = read_ai(rest) if ai is None else ai
                n_ai = baba.overlay_ai({d: {prefix: c} for d, c in days.items()}, samples, ai)
                log("%s 予想 AI の日の値にそろえた %d 日" % (prefix, n_ai))
            doc = {"v": 1, "built": today.isoformat(), "track": track, "days": days}
            data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            first = next(iter(days), None)
            log("%s %s: 時計 %d 行・%d 日(最古 %s・組み直し %d)%d bytes(%.0f 秒)"
                % (prefix, "全期間" if full else "直近", len(wins), len(days), first, rebuilt, len(data),
                   time.time() - t0))
            if a.dry_run:
                os.makedirs(a.out, exist_ok=True)
                with open(os.path.join(a.out, prefix + ".json"), "wb") as f:
                    f.write(data)
            else:
                cond_stats.upload(rest, DIR + prefix + ".json", data)
        except Exception as e:                       # noqa: BLE001
            fails[prefix] = "%s: %s" % (type(e).__name__, str(e)[:200])
            log("⚠%s が作れない: %s" % (prefix, fails[prefix]))
    log("REST %d 回・作れない場 %d" % (rest.nreq, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                            # noqa: BLE001
            pass
    sys.exit(main())
