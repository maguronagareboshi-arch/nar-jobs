# -*- coding: utf-8 -*-
"""締め切り前にオッズが下がった馬(2026-10-17)。今週・先週の 2 週ぶんを 1 枚の JSON にして
公開バケット cond-stats の v1/odds-drop/latest.json へ上書きで上げる毎晩の便。

- 計算の正本= nar-site research/odds-drop/build_mock.mjs(試しページ・照合済み)を Python に移したもの。
- 週= 日曜始まり。今週= 実行日(JST)を含む週の日曜〜実行日・先週= その前の日曜〜土曜。
- 各レース(nar_races の cancelled が null・post_time 'HHMM')について nar_odds_ticks から
  基準 N 分前(30,20,10,5,3)= 発走 N 分前以前で最も新しい非最終の tick・最終= f=true の tick(id が最大)。
  下落率= 1 − 最終÷基準。どれかの基準で 20% 以上の馬を載せる。着順・人気・馬名は nar_runs(nar_runs_2026 は REST に出ていない= 404・親表で引く)。
- ⛔本番 DB は REST の単純 select だけ(日ごと)。書くのは Storage の cond-stats だけ。
- ⛔出力の形を変えない(画面側がこの形で作っている)。

  python3 cloud/odds_drop.py --apply                 … 上げる
  python3 cloud/odds_drop.py --out latest.json       … 手元に書くだけ(上げない)
  python3 cloud/odds_drop.py --today --apply         … 今日の分(最終 tick のあるレースだけ)を v1/odds-drop/today.json へ
  python3 cloud/odds_drop.py --combo --apply         … 組の急落(今週・先週)を v1/odds-drop/combo-latest.json へ
                                                       (日ごとに v1/odds-drop/combo-days/<日付>.json を残す)
  python3 cloud/odds_drop.py --combo --today --apply … 今日の組の急落を v1/odds-drop/combo-today.json へ
  --date YYYY-MM-DD で実行日(JST)を指定。
  --combo は本番 DB の関数 public.combo_drops(ops/combo_drops_fn.sql)を RPC で呼ぶ(組のオッズは引かない)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--out だけなら SUPABASE_ANON_KEY でも可)
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cond_stats  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
NS = (30, 20, 10, 5, 3)
THRESH = 0.2
SPARK_MIN = 40
NAME = "odds-drop/latest.json"
NAME_TODAY = "odds-drop/today.json"

# nar-viewer js/data.js の VENUES の name→prefix と NAR_TRACK_ALIAS(帯広ば→obihiro)と同じ対応
PREFIX = {"帯広": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "浦和": "urawa",
          "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa", "笠松": "kasamatsu",
          "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga",
          "帯広ば": "obihiro"}
DISPLAY = {"帯広ば": "帯広"}


def log(msg):
    print(msg, flush=True)


# ---------- 純関数 ----------
def track_name(track):
    """表示用の場名。DB の公式表記「帯広ば」は「帯広」にする。"""
    t = str(track or "").strip()
    return DISPLAY.get(t, t)


def track_prefix(track):
    return PREFIX.get(str(track or "").strip())


def weeks(today):
    """→ [("this", 日曜, today), ("last", 前の日曜, 前の土曜)]。週は日曜始まり。"""
    sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return [("this", sun, today), ("last", sun - dt.timedelta(days=7), sun - dt.timedelta(days=1))]


def mins(hhmm):
    s = str(hhmm).replace(":", "")
    return int(s[0:2]) * 60 + int(s[2:4])


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if x > 0 else 0.0


def pre_ticks(ticks, post):
    """非最終の tick → [(何分前, w)]。何分前の大きい順・同じ値は id の小さい順(試しページと同じ並び)。"""
    pre = [(post - mins(t["t"]), t.get("id") or 0, t.get("w") or {}) for t in ticks if not t.get("f")]
    pre.sort(key=lambda p: (-p[0], p[1]))
    return [(mb, w) for mb, _, w in pre]


def final_tick(ticks):
    fs = [t for t in ticks if t.get("f")]
    return max(fs, key=lambda t: t.get("id") or 0) if fs else None


def base_tick(pre, n):
    """発走 n 分前以前で最も新しい tick の w(無ければ None)。pre は pre_ticks の並び。"""
    cand = [w for mb, w in pre if mb >= n]
    return cand[-1] if cand else None


def drop(final, base):
    return 1 - final / base


def horse_bases(pre, hn, final):
    """→ (b, 載せるか)。b は取れた基準だけ。"""
    b, any_ = {}, False
    for n in NS:
        w = base_tick(pre, n)
        v = num(w.get(hn)) if w is not None else 0.0
        if v > 0:
            b[str(n)] = v
            if drop(final, v) >= THRESH:
                any_ = True
    return b, any_


def spark(pre, hn, final):
    s = [[mb, num(w.get(hn))] for mb, w in pre if 0 <= mb <= SPARK_MIN and num(w.get(hn)) > 0]
    s.append([0, final])
    return s


def build_day(date, ticks, races, runs):
    """1 日ぶん → (レース数, 頭数, [H])"""
    tk = {}
    for t in ticks:
        tk.setdefault((t["track"], t["race_no"]), []).append(t)
    rn = {(r["track"], r["race_no"], str(r["runner_number"])): r for r in runs}
    n_race, n_head, out = 0, 0, []
    for race in races:
        lst = tk.get((race["track"], race["race_no"]))
        pt = race.get("post_time")
        if not lst or not pt or not (len(str(pt)) == 4 and str(pt).isdigit()):
            continue
        fin = final_tick(lst)
        if not fin:
            continue
        pre = pre_ticks(lst, mins(pt))
        n_race += 1
        for hn, fo in (fin.get("w") or {}).items():
            final = num(fo)
            if not final > 0:
                continue
            n_head += 1
            b, ok = horse_bases(pre, hn, final)
            if not ok:
                continue
            run = rn.get((race["track"], race["race_no"], str(hn))) or {}
            f = run.get("finish")
            sf = race.get("surface")
            out.append({
                "d": date, "tr": track_name(race["track"]), "tp": track_prefix(race["track"]),
                "r": race["race_no"], "pt": str(pt), "rn": race.get("race_name") or "",
                "sf": "芝" if sf == "芝" else ("ダ" if sf else ""), "dm": race.get("distance_m"),
                "u": int(hn), "h": run.get("horse_name") or "",
                "fin": f if isinstance(f, int) and not isinstance(f, bool) else None,
                "pop": run.get("popularity"),
                "b": b, "fo": final, "s": spark(pre, hn, final),
            })
    return n_race, n_head, out


# ---------- 取る ----------
def fetch_day(rest, date):
    d = urllib.parse.quote(date, safe="")
    ticks = rest.paged("nar_odds_ticks?select=id,track,race_no,t,f,w&race_date=eq." + d, "id")
    races = rest.paged("nar_races?select=track,race_no,post_time,race_name,surface,distance_m&race_date=eq." + d
                       + "&cancelled=is.null", "track,race_no")
    runs = rest.paged("nar_runs?select=track,race_no,runner_number,horse_name,finish,popularity&race_date=eq."
                      + d, "track,race_no,runner_number")
    return ticks, races, runs


def build(rest, today, now=None):
    now = now or dt.datetime.now(JST)
    doc = {"built": now.replace(microsecond=0).isoformat(), "weeks": []}
    for key, fr, to in weeks(today):
        nr, nh, hs = 0, 0, []
        d = fr
        while d <= to:
            ds = d.isoformat()
            ticks, races, runs = fetch_day(rest, ds)
            a, b, h = build_day(ds, ticks, races, runs)
            nr, nh = nr + a, nh + b
            hs += h
            log("%s ticks=%d races=%d → %dR %d頭 載せる %d" % (ds, len(ticks), len(races), a, b, len(h)))
            d += dt.timedelta(days=1)
        doc["weeks"].append({"key": key, "from": fr.isoformat(), "to": to.isoformat(),
                             "races": nr, "runners": nh, "horses": hs})
    return doc


def build_today(rest, today, now=None):
    """実行日だけ。build_day は最終 tick(f=true)のあるレースだけ数える。開催が無い日は races 0・horses []。"""
    now = now or dt.datetime.now(JST)
    ds = today.isoformat()
    ticks, races, runs = fetch_day(rest, ds)
    nr, nh, hs = build_day(ds, ticks, races, runs)
    log("%s ticks=%d races=%d → %dR %d頭 載せる %d" % (ds, len(ticks), len(races), nr, nh, len(hs)))
    return {"built": now.replace(microsecond=0).isoformat(),
            "weeks": [{"key": "today", "from": ds, "to": ds, "races": nr, "runners": nh, "horses": hs}]}


def count(week, n, x):
    k = str(n)
    return sum(1 for h in week["horses"] if k in h["b"] and drop(h["fo"], h["b"][k]) >= x - 1e-9)


# ---------- 組の急落(--combo・2026-11-05・仕様 nar-site SPEC_combo_drop_20261105.md) ----------
# 判定は本番 DB の関数 public.combo_drops(p_date)(ops/combo_drops_fn.sql)が中でやり、拾った組の行だけ返す。
# ここでは 組ごとに最も下がった 1 回・t0/t1/left・focus・単勝 tan・結果 res を付けて JSON にする。
NAME_COMBO = "odds-drop/combo-latest.json"
NAME_COMBO_TODAY = "odds-drop/combo-today.json"
COMBO_DAY = "odds-drop/combo-days/%s.json"


def ts(v):
    """PostgREST の timestamptz 文字列 → JST の datetime。"""
    s = str(v).replace("Z", "+00:00").replace(" ", "T")
    return dt.datetime.fromisoformat(s).astimezone(JST)


def nearest_w(wticks, hhmm):
    """非最終の単勝 tick のうち t が hhmm に一番近いものの w(同じ近さなら id の小さい方)。無ければ None。"""
    m = mins(hhmm)
    cand = [t for t in wticks if not t.get("f") and t.get("t")]
    if not cand:
        return None
    return min(cand, key=lambda t: (abs(mins(t["t"]) - m), t.get("id") or 0)).get("w") or {}


def combo_race(date, rows, wticks=(), runs=()):
    """1 レースぶんの関数の行 → 札 1 枚(dict)。rows は同じ track・race_no の行だけ。"""
    best = {}
    for x in rows:
        o0, o1 = float(x["o0"]), float(x["o1"])
        key = (x["kind"], tuple(int(v) for v in x["c"]))
        rank = (o1 / o0, ts(x["t1"]))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, x)
    # t0/t1= 一番多くの組を拾った刻み(数は拾った全行で数える・同数なら後の刻み)
    steps = {}
    for x in rows:
        k = (ts(x["t0"]), ts(x["t1"]))
        steps[k] = steps.get(k, 0) + 1
    (t0, t1), _ = max(steps.items(), key=lambda kv: (kv[1], kv[0][1]))
    fins = [ts(x["fin"]) for x in rows if (ts(x["t0"]), ts(x["t1"])) == (t0, t1) and x.get("fin")]
    fin = max(fins) if fins else None
    items = []
    for (k, c), ((ratio, _t), x) in sorted(best.items(), key=lambda kv: kv[1][0]):
        of = x.get("ofin")
        items.append({"k": k, "c": list(c), "o0": float(x["o0"]), "r0": x.get("r0"), "o1": float(x["o1"]),
                      "r1": x.get("r1"), "of": float(of) if of is not None else None})
    cnt, order = {}, []
    for it in items:
        for u in it["c"]:
            if u not in cnt:
                order.append(u)
            cnt[u] = cnt.get(u, 0) + 1
    ranked = sorted(order, key=lambda u: (-cnt[u], u))
    focus = [u for u in ranked if cnt[u] * 2 >= len(items)] or ranked[:1]
    s0, s1 = t0.strftime("%H:%M"), t1.strftime("%H:%M")
    tan = []
    if wticks:
        w0, w1 = nearest_w(wticks, s0), nearest_w(wticks, s1)
        for u in focus:
            a = num((w0 or {}).get(str(u)))
            b = num((w1 or {}).get(str(u)))
            if a > 0 and b > 0:
                tan.append([u, a, b])
    top = {}
    for r in runs:
        f = r.get("finish")
        if isinstance(f, int) and not isinstance(f, bool) and 1 <= f <= 3 and f not in top:
            top[f] = int(r["runner_number"])
    res = [top[1], top[2], top[3]] if all(k in top for k in (1, 2, 3)) else None
    track = rows[0]["track"]
    return {"d": date, "track": track_name(track), "r": int(rows[0]["race_no"]), "t0": s0, "t1": s1,
            "left": int(round((fin - t1).total_seconds() / 60.0)) if fin else None,
            "focus": focus, "fin": "B" if any(x.get("has_final") for x in rows) else None,
            "tan": tan, "res": res, "items": items}


def combo_day(date, rows, wticks=(), runs=(), races_all=0):
    """1 日ぶんの関数の行 → {"d", "races_all", "races": [札]}。札は場・R の順。"""
    by = {}
    for x in rows:
        by.setdefault((x["track"], int(x["race_no"])), []).append(x)
    wt, rn = {}, {}
    for t in wticks:
        wt.setdefault((t["track"], int(t["race_no"])), []).append(t)
    for r in runs:
        rn.setdefault((r["track"], int(r["race_no"])), []).append(r)
    races = [combo_race(date, lst, wt.get(k, []), rn.get(k, [])) for k, lst in sorted(by.items())]
    return {"d": date, "races_all": races_all, "races": races}


def combo_week(key, fr, to, days):
    races = [r for d in days for r in d["races"]]
    return {"key": key, "from": fr, "to": to, "races_all": sum(d["races_all"] for d in days),
            "n_races": len(races), "n_combos": sum(len(r["items"]) for r in races), "races": races}


def fetch_combo_day(rest, date):
    """関数の行(拾った組だけ)+ そのレースの単勝 tick・着順・その日のレース数。"""
    body = json.dumps({"p_date": date}).encode("utf-8")
    rows = json.loads(rest.req("/rest/v1/rpc/combo_drops", "POST", body,
                               {"Content-Type": "application/json", "Accept": "application/json"}) or b"[]")
    d = urllib.parse.quote(date, safe="")
    races = rest.paged("nar_races?select=track,race_no&race_date=eq." + d + "&cancelled=is.null", "track,race_no")
    wticks, runs = [], []
    for tr in sorted({x["track"] for x in rows}):
        q = "&race_date=eq.%s&track=eq.%s" % (d, urllib.parse.quote(tr, safe=""))
        wticks += rest.paged("nar_odds_ticks?select=id,track,race_no,t,f,w&f=is.false" + q, "id")
        runs += rest.paged("nar_runs?select=track,race_no,runner_number,finish&finish=lte.3" + q,
                           "track,race_no,runner_number")
    return rows, wticks, runs, len(races)


def build_combo_one(rest, ds):
    rows, wticks, runs, n = fetch_combo_day(rest, ds)
    day = combo_day(ds, rows, wticks, runs, n)
    log("組 %s 行=%d → %dR 中 %dR %d 組" % (ds, len(rows), n, len(day["races"]),
                                         sum(len(r["items"]) for r in day["races"])))
    return day


def load_combo_day(rest, ds):
    """バケットに残した日ごとの結果(無ければ None)。"""
    path = cond_stats.ROOT + COMBO_DAY % ds
    try:
        raw = rest.req("/storage/v1/object/authenticated/%s/%s?t=%d" % (cond_stats.BUCKET, path, time.time_ns()))
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        raise
    return json.loads(raw)


def build_combo(rest, today, now=None, save=False):
    """今週・先週。すでに残した日は読むだけ(今日と昨日は毎回計算)。save= 計算した日を combo-days へ残す。"""
    now = now or dt.datetime.now(JST)
    doc = {"built": now.replace(microsecond=0).isoformat(), "weeks": []}
    fresh = {today, today - dt.timedelta(days=1)}
    for key, fr, to in weeks(today):
        days, d = [], fr
        while d <= to:
            ds = d.isoformat()
            day = None if d in fresh else load_combo_day(rest, ds)
            if day is None:
                day = build_combo_one(rest, ds)
                if save:
                    cond_stats.upload(rest, COMBO_DAY % ds,
                                      json.dumps(day, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            days.append(day)
            d += dt.timedelta(days=1)
        doc["weeks"].append(combo_week(key, fr.isoformat(), to.isoformat(), days))
    return doc


def build_combo_today(rest, today, now=None):
    now = now or dt.datetime.now(JST)
    ds = today.isoformat()
    day = build_combo_one(rest, ds)
    return {"built": now.replace(microsecond=0).isoformat(), "weeks": [combo_week("today", ds, ds, [day])]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="cond-stats/v1/odds-drop/latest.json へ上げる")
    ap.add_argument("--out", default="", help="手元に書くだけ(上げない)")
    ap.add_argument("--today", action="store_true", help="今日の分だけ(v1/odds-drop/today.json)")
    ap.add_argument("--date", default="", help="実行日 JST(YYYY-MM-DD・既定= 今日)")
    ap.add_argument("--combo", action="store_true",
                    help="組の急落(v1/odds-drop/combo-latest.json・--today で combo-today.json)")
    a = ap.parse_args(argv)
    if a.combo:
        return main_combo(a)
    if not a.apply and not a.out:
        raise SystemExit("--apply か --out を指定")
    base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or ("" if a.apply else os.environ.get("SUPABASE_ANON_KEY", ""))
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(JST).date()
    rest = cond_stats.Rest(base, key)
    doc = build_today(rest, today) if a.today else build(rest, today)
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    for w in doc["weeks"]:
        log("%s %s〜%s %dR %d頭 載せる %d・10分前で25%%以上 %d" % (w["key"], w["from"], w["to"], w["races"],
                                                         w["runners"], len(w["horses"]), count(w, 10, 0.25)))
    if a.out:
        with open(a.out, "wb") as f:
            f.write(data)
        log("書いた %s(%d bytes)" % (a.out, len(data)))
    if a.apply:
        cond_stats.ensure_bucket(rest)
        cond_stats.upload(rest, NAME_TODAY if a.today else NAME, data)
    return 0


def main_combo(a):
    if not a.apply and not a.out:
        raise SystemExit("--apply か --out を指定")
    base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or ("" if a.apply else os.environ.get("SUPABASE_ANON_KEY", ""))
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(JST).date()
    rest = cond_stats.Rest(base, key)
    if a.apply:
        cond_stats.ensure_bucket(rest)
    doc = build_combo_today(rest, today) if a.today else build_combo(rest, today, save=a.apply)
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    for w in doc["weeks"]:
        log("組 %s %s〜%s %dR 中 %dR %d 組" % (w["key"], w["from"], w["to"], w["races_all"], w["n_races"],
                                          w["n_combos"]))
    if a.out:
        with open(a.out, "wb") as f:
            f.write(data)
        log("書いた %s(%d bytes)" % (a.out, len(data)))
    if a.apply:
        cond_stats.upload(rest, NAME_COMBO_TODAY if a.today else NAME_COMBO, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
