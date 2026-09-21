# -*- coding: utf-8 -*-
"""§238a 派生表 nar_run_facts の日次便(2026-09-21)。規則は pipeline/facts.py に 1 つだけ置いてある。

既定= **当日と前日**ぶんを作り直して upsert(前日は結果が確定してから入るので毎日焼き直す)。
`--from YYYY-MM-DD --to YYYY-MM-DD` で遡り(1 か月ずつの窓に割って回す)。何度流しても同じ結果。
§238e: 馬の鍵は birth_date が無い行(楽天 2014〜2022-10)だけ `名前|生年`・脚質の過去走は (名前, 生年) で照合。
ドライラン(--apply 無し)は書かず、本番の行と比べた差(style が違う数・horse_key が埋まる数など)を log に出す。

  py -3.12 -X utf8 cloud/run_facts.py                             # ドライラン(当日+前日)
  py -3.12 -X utf8 cloud/run_facts.py --apply
  py -3.12 -X utf8 cloud/run_facts.py --apply --from 2025-09-01 --to 2026-09-20
  py -3.12 -X utf8 cloud/run_facts.py --selftest                  # 規則だけ(通信なし)

環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(⛔鍵はコードに書かない・ログにも出さない)。
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000 行キャップ: 全取得はページングで回す(order は主キーで一意にする= 深い offset で欠落しない)。
⛔URL 長: in.() は 80 件ずつに割る。⛔本番 DB に重い SQL は流さない(組み立ては全部ここ=便の中)。
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import facts                                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

UA = "nar-jobs/1.0"
JST = dt.timezone(dt.timedelta(hours=9))
PAGE = 1000
CHUNK = 80
WINDOW_DAYS = 31          # 遡りを割る窓。⛔1 年を一息に引くと重い/500 が返る
BATCH = 500               # upsert の 1 回の行数
TABLE = "nar_run_facts"
PK = "race_date,track,race_no,umaban"
KOCHI = "高知"
KOCHI_KIND_KEY = "kochi_3f_kinds:"      # nar_meta の札(§98b)。⛔「実測」の馬だけ own に採る


def log(msg):
    print(msg, flush=True)


def env():
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が要る(⛔鍵はコードに書かない)")
    return base, key


def get(base, key, path):
    req = urllib.request.Request(base + path, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA, "Accept": "application/json"})
    for n in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:                                       # noqa: BLE001
            if n == 2:
                raise SystemExit(2) from e
            time.sleep(2 + n * 3)
    return []


def rows_all(base, key, path):
    """⛔order= 主キーで一意にしてから offset を進める(PostgREST の offset は order が一意でないと欠ける)。"""
    out, off = [], 0
    joiner = "&" if "?" in path else "?"
    while True:
        rows = get(base, key, "%s%slimit=%d&offset=%d" % (path, joiner, PAGE, off))
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        off += PAGE


def q_in(values):
    return urllib.parse.quote(",".join('"%s"' % str(v).replace('"', "") for v in values), safe='(),"')


def chunks(seq, n=CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def upsert(base, key, rows):
    """⛔pipeline/load_nar_official.upsert と同じ作法(merge-duplicates・return=minimal・3 回まで再試行)。"""
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "%s/rest/v1/%s?on_conflict=%s" % (base, TABLE, PK), data=body, method="POST",
        headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal", "User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, ""
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code >= 500 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            return e.code, msg
        except Exception as e:                                       # noqa: BLE001
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            return 0, str(e)
    return 0, "unreachable"


# ---------------------------------------------------------------- 取得

def fetch_races(base, key, lo, hi):
    return rows_all(base, key,
                    "/rest/v1/nar_races?select=track,race_date,race_no,corners,distance_m,going,weather,source"
                    "&race_date=gte.%s&race_date=lte.%s&order=race_date.asc,track.asc,race_no.asc" % (lo, hi))


def fetch_runs(base, key, lo, hi):
    return rows_all(base, key,
                    "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date,age,last3f"
                    "&race_date=gte.%s&race_date=lte.%s"
                    "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc" % (lo, hi))


def fetch_first3f(base, key, lo, hi):
    """{(場,日,R,馬番): {'own'|'paper'|'kb': 値}}。⛔優先順の判定は pipeline/facts.pick_first3f がやる。"""
    out = {}

    def put(track, r, src):
        v = r.get("first3f")
        if v is None or r.get("umaban") is None:
            return
        k = (track, str(r["race_date"])[:10], int(r["race_no"]), int(r["umaban"]))
        out.setdefault(k, {})[src] = float(v)

    # 専門紙(nar_kb_runs)・紙面(nar_paper_runs)
    for table, src in (("nar_kb_runs", "kb"), ("nar_paper_runs", "paper")):
        for r in rows_all(base, key,
                          "/rest/v1/%s?select=track,race_date,race_no,umaban,first3f&first3f=not.is.null"
                          "&race_date=gte.%s&race_date=lte.%s"
                          "&order=race_date.asc,track.asc,race_no.asc,umaban.asc" % (table, lo, hi)):
            put(r.get("track") or "", r, src)
    # 高知(当サイトの計測)。⛔nar_meta の札が「実測」の馬だけ(推定は own に採らない)
    own = rows_all(base, key,
                   "/rest/v1/nar_own_runs?select=track,race_date,race_no,umaban,first3f&first3f=not.is.null"
                   "&race_date=gte.%s&race_date=lte.%s"
                   "&order=race_date.asc,race_no.asc,umaban.asc" % (lo, hi))
    kinds = fetch_kochi_kinds(base, key, {str(r["race_date"])[:10] for r in own})
    for r in own:
        d = str(r["race_date"])[:10]
        if kinds.get((d, "%s-%s" % (r["race_no"], r["umaban"]))) != "実測":
            continue
        put(r.get("track") or KOCHI, r, "own")
    return out


def fetch_kochi_kinds(base, key, days):
    """nar_meta 'kochi_3f_kinds:YYYY-MM-DD' → {(日, 'R-馬番'): '実測'|…}(⛔tenkai.py と同じ読み方)。"""
    out = {}
    for part in chunks(sorted(days)):
        keys = [KOCHI_KIND_KEY + d for d in part]
        for row in rows_all(base, key, "/rest/v1/nar_meta?select=key,value&key=in.(%s)&order=key.asc" % q_in(keys)):
            d = str(row["key"]).split(":", 1)[1]
            v = row.get("value")
            if isinstance(v, dict):
                for k2, kind in v.items():
                    out[(d, str(k2))] = kind
    return out


def fetch_ticks(base, key, lo, hi):
    """{(場,日,R): [tick…]}。⛔引くのは t/f/w/id だけ(p・u1・s1 は要らない= 転送量を増やさない)。"""
    out = {}
    for r in rows_all(base, key,
                      "/rest/v1/nar_odds_ticks?select=id,track,race_date,race_no,t,f,w"
                      "&race_date=gte.%s&race_date=lte.%s&order=id.asc" % (lo, hi)):
        k = (r.get("track"), str(r["race_date"])[:10], int(r["race_no"]))
        out.setdefault(k, []).append(r)
    return out


def match_key(r):
    """過去走の照合の鍵= (名前, 生年)。⛔§238e 決めごと 2: 生年= birth_date の年 or レースの年 − age。

    楽天(2014〜2022-10・birth_date 無し)→ 公式(2022-11〜・birth_date あり)をまたぐ馬がつながる。
    ⛔名前か生年が無ければ None(名前だけでつながない)。名前の正規化はしない。
    """
    name = r.get("horse_name")
    if not name:
        return None
    by = facts.birth_year_of(r.get("birth_date"), r.get("age"), r.get("race_date"))
    return None if by is None else (name, by)


def fetch_past_positions(base, key, lo, hi, keys):
    """脚質の材料= 窓の 365 日前までの走の「1 角の位置 p」。{(名前, 生年): [{track,race_date,race_no,p}]}。

    ⛔as-of の切り方(その日より前だけ)は pipeline/facts.pick_past_runs がやる。ここは材料を集めるだけ。
    ⛔引く馬は**この窓に出る馬だけ**(keys= match_key の集合)= 全馬を舐めない。
    """
    p0 = (dt.date.fromisoformat(lo) - dt.timedelta(days=facts.PAST_DAYS)).isoformat()
    names = sorted({k[0] for k in keys if k})
    runs = []
    for part in chunks(names, 60):
        runs.extend(rows_all(
            base, key,
            "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date,age"
            "&horse_name=in.(%s)&race_date=gte.%s&race_date=lte.%s"
            "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc" % (q_in(part), p0, hi)))
    need = {(r["track"], str(r["race_date"])[:10], int(r["race_no"])) for r in runs}
    corners = fetch_corners(base, key, need)
    out = {}
    for r in runs:
        hk = match_key(r)
        if not hk:
            continue
        d = str(r["race_date"])[:10]
        c = corners.get((r["track"], d, int(r["race_no"])))
        p = facts.position_of(c, r.get("runner_number")) if c else None
        out.setdefault(hk, []).append({"track": r["track"], "race_date": d,
                                       "race_no": int(r["race_no"]), "p": p})
    return out


def fetch_corners(base, key, need):
    """{(場,日,R)} → {(場,日,R): corners}。場ごと・日付 80 個ずつ(⛔tenkai.py fetch_corners と同じ割り方)。"""
    by_track = {}
    for t, d, _no in need:
        by_track.setdefault(t, set()).add(d)
    out = {}
    for t, days in sorted(by_track.items()):
        for part in chunks(sorted(days)):
            for r in rows_all(base, key,
                              "/rest/v1/nar_races?select=track,race_date,race_no,corners"
                              "&track=eq.%s&race_date=in.(%s)&order=race_date.asc,race_no.asc"
                              % (urllib.parse.quote(t), q_in(part))):
                out[(r["track"], str(r["race_date"])[:10], int(r["race_no"]))] = r.get("corners")
    return out


# ---------------------------------------------------------------- 組み立て

def src_of(race):
    """src 列。⛔今は公式だけ(§238b でアーカイブ 'kb_archive' が入る)。"""
    s = str(race.get("source") or "")
    if "kb" in s or "archive" in s:
        return "kb_archive"
    if "kochi" in s and "legacy" in s:
        return "kochi_legacy"
    return "official"


def build_window(base, key, lo, hi):
    """1 窓ぶんの派生行。⛔読むのは REST だけ・組み立ては全部ここ(本番 DB に集計を投げない)。"""
    races = fetch_races(base, key, lo, hi)
    runs = fetch_runs(base, key, lo, hi)
    if not races or not runs:
        return []
    race_of = {(r["track"], str(r["race_date"])[:10], int(r["race_no"])): r for r in races}
    keys = {match_key(r) for r in runs}
    f3 = fetch_first3f(base, key, lo, hi)
    ticks = fetch_ticks(base, key, lo, hi)
    past = fetch_past_positions(base, key, lo, hi, keys)
    now = dt.datetime.now(JST).isoformat(timespec="seconds")
    out = []
    for r in runs:
        d = str(r["race_date"])[:10]
        k = (r["track"], d, int(r["race_no"]))
        race = race_of.get(k)
        if race is None or r.get("runner_number") is None:
            continue                                    # ⛔レースの行が無い走は作らない(推定しない)
        mk = match_key(r)
        out.append(facts.build_row(
            race={"track": k[0], "race_date": d, "race_no": k[2], "corners": race.get("corners")},
            run=r,
            past=past.get(mk, []) if mk else [],
            first3f_cands=f3.get((k[0], d, k[2], int(r["runner_number"]))),
            ticks=ticks.get(k),
            computed_at=now,
            src=src_of(race)))
    return out


def fetch_existing(base, key, lo, hi):
    """本番に既にある派生行 {(日,場,R,馬番): {style, horse_key}}。⛔ドライランの差を数えるためだけ(読むだけ)。"""
    out = {}
    for r in rows_all(base, key,
                      "/rest/v1/%s?select=race_date,track,race_no,umaban,style,horse_key"
                      "&race_date=gte.%s&race_date=lte.%s"
                      "&order=race_date.asc,track.asc,race_no.asc,umaban.asc" % (TABLE, lo, hi)):
        out[(str(r["race_date"])[:10], r["track"], int(r["race_no"]), int(r["umaban"]))] = r
    return out


DIFF_KEYS = ("rows", "old", "new", "gone", "style_diff", "style_fill", "style_drop", "style_change",
             "hk", "hk_fill", "style", "c1")


def diff_counts(rows, old):
    """§238e ドライランの差(⛔数えるだけ・書かない)。rows= 今回焼いた行 / old= fetch_existing の結果。

    old / new / gone= 本番に有る / 無い(新しく入る)/ 本番にだけ有る(今回は焼かない)。
    style_diff= 本番に有る行で style が違う数(うち 空→値 / 値→空 / 別の値)。
    hk= horse_key が埋まる行 / hk_fill= そのうち本番で空だった行。style / c1= 埋まる行。
    """
    c = dict.fromkeys(DIFF_KEYS, 0)
    seen = set()
    for r in rows:
        c["rows"] += 1
        c["hk"] += 1 if r.get("horse_key") else 0
        c["style"] += 1 if r.get("style") else 0
        c["c1"] += 1 if r.get("c1") is not None else 0
        pk = (r["race_date"], r["track"], r["race_no"], r["umaban"])
        o = old.get(pk)
        if o is None:
            c["new"] += 1
            continue
        seen.add(pk)
        c["old"] += 1
        s0, s1 = o.get("style") or None, r.get("style") or None
        if s0 != s1:
            c["style_diff"] += 1
            c["style_fill" if s0 is None else "style_drop" if s1 is None else "style_change"] += 1
        if not o.get("horse_key") and r.get("horse_key"):
            c["hk_fill"] += 1
    c["gone"] = len(set(old) - seen)
    return c


def fmt_diff(c):
    f = lambda n: format(n, ",")                       # noqa: E731
    pct = lambda n: "%.1f%%" % (100.0 * n / c["rows"]) if c["rows"] else "-"   # noqa: E731
    return ("本番に有 %s・無 %s・本番にだけ有 %s / style 違う %s(空→値 %s・値→空 %s・別の値 %s)"
            " / horse_key 埋まる %s(%s・うち本番で空 %s)/ style 埋まる %s(%s)・c1 埋まる %s(%s)"
            % (f(c["old"]), f(c["new"]), f(c["gone"]), f(c["style_diff"]), f(c["style_fill"]),
               f(c["style_drop"]), f(c["style_change"]), f(c["hk"]), pct(c["hk"]), f(c["hk_fill"]),
               f(c["style"]), pct(c["style"]), f(c["c1"]), pct(c["c1"])))


def windows(lo, hi, days=WINDOW_DAYS):
    a = dt.date.fromisoformat(lo)
    end = dt.date.fromisoformat(hi)
    while a <= end:
        b = min(a + dt.timedelta(days=days - 1), end)
        yield a.isoformat(), b.isoformat()
        a = b + dt.timedelta(days=1)


def run(base, key, lo, hi, apply_=False):
    """⛔ドライラン(apply_=False)は書かない。代わりに本番の行と比べた差を窓ごと+合計で log に出す(§238e)。"""
    total, t0 = 0, time.time()
    acc = dict.fromkeys(DIFF_KEYS, 0)
    for a, b in windows(lo, hi):
        tw = time.time()
        rows = build_window(base, key, a, b)
        total += len(rows)
        if apply_:
            for i in range(0, len(rows), BATCH):
                st, err = upsert(base, key, rows[i:i + BATCH])
                if st >= 300 or st == 0:
                    log("  %s〜%s: HTTP%s %s (batch %d)" % (a, b, st, err, i))
                    return 1
            log("  %s〜%s: %s 行 (%.0fs)" % (a, b, format(len(rows), ","), time.time() - tw))
            continue
        c = diff_counts(rows, fetch_existing(base, key, a, b))
        for k in DIFF_KEYS:
            acc[k] += c[k]
        log("  %s〜%s: %s 行 (%.0fs) %s" % (a, b, format(len(rows), ","), time.time() - tw, fmt_diff(c)))
    log("%s 行 %s (%.0f 秒)" % (format(total, ","), "投入" if apply_ else "ドライラン", time.time() - t0))
    if not apply_:
        log("差の合計(⛔書いていない): %s" % fmt_diff(acc))
    return 0


def main():
    ap = argparse.ArgumentParser(description="派生表 nar_run_facts を焼く(§238a)")
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定はドライラン)")
    ap.add_argument("--from", dest="lo", help="YYYY-MM-DD(遡りの始め)")
    ap.add_argument("--to", dest="hi", help="YYYY-MM-DD(遡りの終わり)")
    ap.add_argument("--selftest", action="store_true", help="規則の自己診断だけ(通信なし)")
    a = ap.parse_args()
    if a.selftest:
        return facts.selftest()
    if facts.selftest(quiet=True):                       # ⛔走る前に必ず規則を通す(黙って通る)
        log("⛔規則の自己診断が落ちた= 走らない")
        return 2
    today = dt.datetime.now(JST).date()
    lo = a.lo or (today - dt.timedelta(days=1)).isoformat()
    hi = a.hi or today.isoformat()
    base, key = env()
    log("nar_run_facts %s〜%s %s" % (lo, hi, "(apply)" if a.apply else "(ドライラン)"))
    return run(base, key, lo, hi, a.apply)


if __name__ == "__main__":
    raise SystemExit(main())
