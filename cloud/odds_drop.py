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
  --date YYYY-MM-DD で実行日(JST)を指定。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--out だけなら SUPABASE_ANON_KEY でも可)
"""
import argparse
import datetime as dt
import json
import os
import sys
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="cond-stats/v1/odds-drop/latest.json へ上げる")
    ap.add_argument("--out", default="", help="手元に書くだけ(上げない)")
    ap.add_argument("--today", action="store_true", help="今日の分だけ(v1/odds-drop/today.json)")
    ap.add_argument("--date", default="", help="実行日 JST(YYYY-MM-DD・既定= 今日)")
    a = ap.parse_args(argv)
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


if __name__ == "__main__":
    sys.exit(main())
