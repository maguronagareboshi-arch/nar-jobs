#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用(2026-10-27)。「2026 年の地方競馬」まとめの数字 実装 B(実装 A と照合する独立の再計算)。

約束= nar-site research/year-review-2026/SPEC.md「数え方」。
⛔本番 DB は REST の単純 select だけ(場ごと・月ごと・一意の order でページ送り)。書き込みなし。rpc なし。

  python3 cloud/year_review_b.py [--end YYYY-MM-DD]   # 便→ docs/year_review_b/result.json
  python3 cloud/year_review_b.py --selftest            # 作り物で関数の試験だけ
"""
import datetime as dtm
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "year_review_b", "result.json")
UA = "nar-jobs year_review_b (+https://yukochi.com/)"
VENUES = ["帯広ば", "門別", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢", "笠松", "名古屋", "園田", "姫路",
          "高知", "佐賀"]
KIND = {"win": "単勝", "place": "複勝", "wakuren": "枠複", "wakutan": "枠単", "quinella": "馬複", "exacta": "馬単",
        "wide": "ワイド", "trio": "三連複", "trifecta": "三連単"}
JMARK = re.compile(r"[\s　▲△☆◇★]")

DECISIONS = [
    "期間= 2026-01-01〜end(既定は JST の今日の前日)。場= nar_runs.track の 15 値(帯広ばを含む。門別〜佐賀 14+帯広= SPEC の地方 14 場に帯広を含めた数)。",
    "走= nar_runs の finish が数値の行だけ(取消・除外・中止は finish が空= 数えない)。レース= そういう走が 1 つ以上あるレース。開催日= そういうレースが 1 つ以上ある 場×日。",
    "馬の同定= 馬名+生年月日。騎手= nar_runs.jockey から空白と見習いの印(▲△☆◇★)を除いた文字。",
    "払戻= nar_race_payouts.payouts の t が 単勝/複勝/枠複/枠単/馬複/馬単/ワイド/三連複/三連単 の行(それ以外の券種は入れない)。y= 100 円あたり。"
    "レースに着順のある走が無くても払戻があれば数える(暦は払戻の表だけで作る)。",
    "暦のマス= 場×日の最高額。同額は R の早い方→券種の上の順(単勝が上)→組の文字順。",
    "最高払戻= 払戻の行ごと(同じレースの別券種も別の行)。同額は日→場→R の早い順。別に『最高払戻_レースごと』= 1 レース 1 行(そのレースの最高額)も出す。",
    "上位 5= 5 位と同数は全部出す(馬・騎手とも)。",
    "最年長の勝ち馬= nar_runs.age(空なら 年−生年)。1 着の走で最大の年齢の走を全部。",
    "速い時計= 場×距離で finish が数値・time_sec ありの走の最小。同タイムは日→R の早い順→着順→馬番。距離の並び= 今年の施行数(レース数)の多い順・同数は距離の短い順。"
    "クラス= nar_races の race_kind・condition・race_name をそのまま持つ。",
]


def log(m):
    print(m, flush=True)


class Rest:
    def __init__(self, base, key):
        self.base, self.key, self.n = base.rstrip("/"), key, 0

    def get(self, q):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "User-Agent": UA, "Accept": "application/json"}
        for i in range(4):
            self.n += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(self.base + "/rest/v1/" + q, headers=h),
                                            timeout=180) as x:
                    return json.loads(x.read() or b"[]")
            except urllib.error.HTTPError as e:
                if (e.code < 500 and e.code != 429) or i == 3:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if i == 3:
                    raise
            time.sleep(5 * (i + 1))

    def paged(self, q, order):
        rows, off = [], 0
        while True:
            part = self.get(f"{q}&order={order}&limit=1000&offset={off}")
            rows += part
            if len(part) < 1000:
                return rows
            off += 1000


def enc(v):
    return urllib.parse.quote(str(v), safe="")


def months(lo, hi):
    d = dtm.date(lo.year, lo.month, 1)
    while d <= hi:
        nx = dtm.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        yield max(lo, d).isoformat(), min(hi, nx - dtm.timedelta(days=1)).isoformat()
        d = nx


RUN_COLS = "track,race_date,race_no,runner_number,horse_name,birth_date,age,jockey,finish,finish_note,time_sec,popularity"
RACE_COLS = "track,race_date,race_no,distance_m,race_name,race_kind,condition,going"


def load(rest, lo, hi):
    runs, races, pays = [], [], []
    for v in VENUES:
        t0, n = time.time(), 0
        for a, b in months(lo, hi):
            rng = f"&track=eq.{enc(v)}&race_date=gte.{a}&race_date=lte.{b}"
            p = rest.paged("nar_runs?select=" + RUN_COLS + rng, "race_date.asc,race_no.asc,runner_number.asc")
            n += len(p)
            runs += p
            races += rest.paged("nar_races?select=" + RACE_COLS + rng, "race_date.asc,race_no.asc")
            pays += rest.paged("nar_race_payouts?select=track,race_date,race_no,payouts" + rng, "race_date.asc,race_no.asc")
        log(f"{v} 走 {n:,} {time.time() - t0:.0f}s")
    return runs, races, pays


def num(x):
    try:
        return int(x) if x is not None and str(x).strip() != "" else None
    except (TypeError, ValueError):
        try:
            return int(float(x))
        except (TypeError, ValueError):
            return None


def fnum(x):
    try:
        return float(x) if x is not None and str(x).strip() != "" else None
    except (TypeError, ValueError):
        return None


def topn_ties(cnt, n=5):
    items = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(items) <= n:
        return items
    cut = items[n - 1][1]
    return [kv for kv in items if kv[1] >= cut]


def compute(runs, races, pays, lo, hi):
    KO = list(KIND)
    rinfo = {(r["track"], r["race_date"], int(r["race_no"])): r for r in races}
    ranked = [r for r in runs if num(r.get("finish")) is not None]
    for r in ranked:
        r["_f"] = num(r["finish"])
        r["_k"] = (r["track"], r["race_date"], int(r["race_no"]))
    # 頭の数字
    race_set = {r["_k"] for r in ranked}
    day_set = {(k[0], k[1]) for k in race_set}
    per = {}
    for v in VENUES:
        per[v] = {"開催日数": len({d for d in day_set if d[0] == v}),
                  "レース数": len({k for k in race_set if k[0] == v}),
                  "出走のべ頭数": sum(1 for r in ranked if r["track"] == v)}
    head = {"開催日数": len(day_set), "開催日数_日付の数": len({d[1] for d in day_set}), "レース数": len(race_set),
            "出走のべ頭数": len(ranked), "場別": per}
    # 払戻の行
    prow = []
    for p in pays:
        for x in (p.get("payouts") or []):
            t, y = x.get("t"), num(x.get("y"))
            if t in KIND and y is not None:
                prow.append({"場": p["track"], "日": p["race_date"], "R": int(p["race_no"]), "券種": KIND[t],
                             "組": str(x.get("c")), "金額": y, "人気": num(x.get("p")), "_o": KO.index(t)})
    cal = {}
    for x in prow:
        k = (x["場"], x["日"])
        key = (-x["金額"], x["R"], x["_o"], x["組"])
        if k not in cal or key < cal[k][0]:
            cal[k] = (key, x)
    clean = lambda x: {k: v for k, v in x.items() if not k.startswith("_")}
    cal_rows = [clean(v[1]) for k, v in sorted(cal.items())]
    srt = sorted(prow, key=lambda x: (-x["金額"], x["日"], VENUES.index(x["場"]) if x["場"] in VENUES else 99, x["R"], x["_o"]))
    top_pay = [clean(x) for x in srt[:5]]
    seen, top_pay_race = set(), []
    for x in srt:
        k = (x["場"], x["日"], x["R"])
        if k in seen:
            continue
        seen.add(k)
        top_pay_race.append(clean(x))
        if len(top_pay_race) == 5:
            break
    for lst in (top_pay, top_pay_race):
        for x in lst:
            ri = rinfo.get((x["場"], x["日"], x["R"]), {})
            x["レース名"] = ri.get("race_name")
    # 勝ち
    wins = [r for r in ranked if r["_f"] == 1]
    hc, hv = Counter(), defaultdict(Counter)
    for r in wins:
        h = (r["horse_name"], r.get("birth_date") or "")
        hc[h] += 1
        hv[h][r["track"]] += 1
    top_h = [{"馬": h[0], "生年月日": h[1], "勝ち数": c, "場の内訳": dict(hv[h])} for h, c in topn_ties(hc)]
    jc = Counter()
    jraw = defaultdict(Counter)
    for r in wins:
        j = JMARK.sub("", r.get("jockey") or "")
        if j:
            jc[j] += 1
            jraw[j][r.get("jockey")] += 1
    top_j = [{"騎手": j, "勝ち数": c, "表記": dict(jraw[j])} for j, c in topn_ties(jc)]
    # 最年長
    def age_of(r):
        a = num(r.get("age"))
        if a is None and r.get("birth_date"):
            a = int(r["race_date"][:4]) - int(str(r["birth_date"])[:4])
        return a
    ages = [(age_of(r), r) for r in wins]
    ages = [x for x in ages if x[0] is not None]
    mx = max(a for a, _ in ages) if ages else None
    old = [{"馬": r["horse_name"], "生年月日": r.get("birth_date"), "年齢": a, "表の馬齢": num(r.get("age")),
            "日": r["race_date"], "場": r["track"], "R": int(r["race_no"]),
            "レース名": rinfo.get(r["_k"], {}).get("race_name")}
           for a, r in sorted(ages, key=lambda x: (x[1]["race_date"], x[1]["track"], int(x[1]["race_no"]))) if a == mx]
    # 速い時計
    nrace = defaultdict(Counter)
    for k in race_set:
        d = num(rinfo.get(k, {}).get("distance_m"))
        if d:
            nrace[k[0]][d] += 1
    best = {}
    for r in ranked:
        t = fnum(r.get("time_sec"))
        ri = rinfo.get(r["_k"], {})
        d = num(ri.get("distance_m"))
        if t is None or t <= 0 or not d:
            continue
        key = (t, r["race_date"], int(r["race_no"]), r["_f"], num(r.get("runner_number")) or 99)
        kk = (r["track"], d)
        if kk not in best or key < best[kk][0]:
            best[kk] = (key, r, ri)
    fast = {}
    for v in VENUES:
        lst = []
        for d, n in sorted(nrace[v].items(), key=lambda kv: (-kv[1], kv[0])):
            if (v, d) not in best:
                continue
            key, r, ri = best[(v, d)]
            lst.append({"距離": d, "施行数": n, "タイム秒": key[0], "馬": r["horse_name"], "着順": r["_f"],
                        "日": r["race_date"], "R": int(r["race_no"]), "馬場状態": ri.get("going"),
                        "クラス": ri.get("race_kind"), "条件": ri.get("condition"), "レース名": ri.get("race_name")})
        fast[v] = lst
    return {"期間": [lo.isoformat(), hi.isoformat()], "作り方": DECISIONS, **{"頭の数字": head},
            "暦のマス": cal_rows, "最多勝の馬": top_h, "最多勝の騎手": top_j, "最高払戻": top_pay,
            "最高払戻_レースごと": top_pay_race, "最年長の勝ち馬": old, "各場の速い時計": fast,
            "件数": {"走_読んだ": len(runs), "レース_読んだ": len(races), "払戻_読んだ": len(pays), "払戻の行": len(prow)}}


def selftest():
    runs = [
        {"track": "高知", "race_date": "2026-01-02", "race_no": 1, "runner_number": 1, "horse_name": "A", "birth_date": "2016-04-01",
         "age": 10, "jockey": "▲山田", "finish": 1, "time_sec": 70.1},
        {"track": "高知", "race_date": "2026-01-02", "race_no": 1, "runner_number": 2, "horse_name": "B", "birth_date": "2020-04-01",
         "age": None, "jockey": "佐藤", "finish": 2, "time_sec": 70.5},
        {"track": "高知", "race_date": "2026-01-02", "race_no": 1, "runner_number": 3, "horse_name": "C", "birth_date": None,
         "age": None, "jockey": "鈴木", "finish": None, "finish_note": "出走取消", "time_sec": None},
        {"track": "高知", "race_date": "2026-01-03", "race_no": 2, "runner_number": 1, "horse_name": "A", "birth_date": "2016-04-01",
         "age": 10, "jockey": "山田", "finish": 1, "time_sec": 70.1},
    ]
    races = [{"track": "高知", "race_date": "2026-01-02", "race_no": 1, "distance_m": 1300, "going": "良"},
             {"track": "高知", "race_date": "2026-01-03", "race_no": 2, "distance_m": 1300, "going": "重"}]
    pays = [{"track": "高知", "race_date": "2026-01-02", "race_no": 1,
             "payouts": [{"t": "win", "c": "1", "y": 150, "p": 1}, {"t": "trifecta", "c": "1-2-3", "y": 99999, "p": 50},
                         {"t": "win5", "c": "x", "y": 9999999}]}]
    o = compute(runs, races, pays, dtm.date(2026, 1, 1), dtm.date(2026, 1, 3))
    assert o["頭の数字"]["出走のべ頭数"] == 3 and o["頭の数字"]["レース数"] == 2 and o["頭の数字"]["開催日数"] == 2
    assert o["最多勝の馬"][0]["勝ち数"] == 2 and o["最多勝の騎手"][0] == {"騎手": "山田", "勝ち数": 2, "表記": {"▲山田": 1, "山田": 1}}
    assert o["最高払戻"][0]["金額"] == 99999 and len(o["暦のマス"]) == 1 and o["暦のマス"][0]["券種"] == "三連単"
    assert o["最年長の勝ち馬"][0]["年齢"] == 10 and len(o["最年長の勝ち馬"]) == 2
    f = o["各場の速い時計"]["高知"][0]
    assert f["日"] == "2026-01-02" and f["施行数"] == 2 and f["馬場状態"] == "良"
    log("selftest ok")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    jst = dtm.datetime.utcnow() + dtm.timedelta(hours=9)
    hi = jst.date() - dtm.timedelta(days=1)
    if "--end" in sys.argv:
        hi = dtm.date.fromisoformat(sys.argv[sys.argv.index("--end") + 1])
    lo = dtm.date(hi.year, 1, 1)
    rest = Rest(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    runs, races, pays = load(rest, lo, hi)
    o = compute(runs, races, pays, lo, hi)
    o["要求回数"] = rest.n
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)
    log(json.dumps({k: o[k] for k in ("期間", "件数")}, ensure_ascii=False))
    log(json.dumps(o["頭の数字"], ensure_ascii=False))
    log(json.dumps({"馬": o["最多勝の馬"], "騎手": o["最多勝の騎手"], "払戻": o["最高払戻"], "最年長": o["最年長の勝ち馬"]},
                   ensure_ascii=False))


if __name__ == "__main__":
    main()
