# -*- coding: utf-8 -*-
"""研究用・1 回きり(やり直し 2026-10-17): 名古屋・笠松で「番組賞金の見直し(25% 控除)の前に、入着(2〜5着)を避けて降級を狙う走り」の痕跡。
便 .github/workflows/yarazu-tokai.yml(workflow_dispatch のみ)から走らせ、docs/yarazu-tokai/result2.md を書く(前回の result.md は残す)。
⛔本番 DB は REST の単純 select だけ(場×年/月・馬名の束ごと・order は一意の列の組)。書き込みなし。馬名・騎手・調教師・馬主は出さない。

前回(a339930・result.md)からの変更:
- 番組賞金 P= nar_class_calc_hist ではなく、この便の中で class_calc.tokai_state(台帳の計算と同じ関数)を、発走の前日までの走りに当てて出す。
  走歴= 台帳(nar_horse_prize.runs)に居る馬は台帳の走(+台帳に無い東海の走を nar_runs から足す)、居ない馬は nar_runs の全場の走
  (馬名+生年月日で 1 頭に絞る。生年の無い走は外して数える)。賞金= nar_races.prize_yen の着順の額。
  印= 台帳に居ない馬で、走歴の頭が 2 歳でない(それより前・中央の走が分からない)か、1〜5着の賞金が分からない走がある馬。
- 見直しの日= 決まりから: 名古屋= 年度の第 7・13・19・26 回の開催の最終日(開催= nar_races の続いた開催日の塊)・
  笠松= 6・9・12・3 月に終わる最後の開催の最終日。nar_meta 'tokai_adj_days' にある日はそれを使う。R の日の走は見直し前。
  tokai_state の調整日(TOKAI_ADJ)もこの日の翌日に置き換える(それ以外の四半期は tokai_adj_dates の既定のまま)。
- 級= 台帳の走の cls の頭の字。台帳に無い走は、同じレースの台帳の馬(2 頭以上)の級がそろっていればその級。
定義(①〜⑤)は前回の台本のまま(式= 再照合2・①で一致率 80% 未満の回は外す・層= 級×前2走×人気×間隔・反証 a b c)。
"""
import bisect
import datetime as dt
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tokai_demotion as td  # noqa: E402  (earn_rows・cls・LINE・RK・NF・ADJ_SET を使う。式は触らない)
import class_calc as cc      # noqa: E402  (tokai_state・tokai_adj_dates・TOKAI_ADJ を使う。式は触らない)

TRACKS = ("名古屋", "笠松")
PFX = {"名古屋": "nagoya", "笠松": "kasamatsu"}
D_FROM, D_TO = dt.date(2024, 1, 1), dt.date(2026, 9, 30)
F_FROM = dt.date(2023, 9, 1)            # 前回の見直し(2023-12)と収得の期間のために前から読む
F_TO = dt.date(2026, 10, 16)            # 見直しの後の級(①)のために後ろまで読む
R_FROM = dt.date(2022, 11, 1)           # 東海のレース表(換算率・開催の塊)
LET = {"Ａ": "A", "Ｂ": "B", "Ｃ": "C", "A": "A", "B": "B", "C": "C"}
LINE = td.LINE
RK = td.RK
BOOT = 1000
MIN_CELL = 30
MIN_REF = 20
OK_RATE = 0.80
RNG = np.random.default_rng(20261017)
OUT = Path(__file__).resolve().parent.parent / "docs" / "yarazu-tokai" / "result2.md"
PAGE = 1000
AGEL = re.compile(r"系(2歳|3歳)(?!以上)")
KEYS = ("t5", "t3", "fin", "mar")
KNAME = {"t5": "5着内 (pt)", "t3": "3着内 (pt)", "fin": "着順", "mar": "秒差"}
BAD_NEG = {"t5": True, "t3": True, "fin": False, "mar": False}
NG_MEET_Q = {7: 6, 13: 9, 19: 12, 26: 3}   # 名古屋の回 → 四半期の月
# 前回(result.md)の見直しの日と主な数(並べる用)
PREV_REVS = {
    "名古屋": ["2024-03-29", "2024-06-28", "2024-12-24", "2025-03-31", "2025-06-27", "2025-10-03", "2025-12-24", "2026-03-27", "2026-07-03"],
    "笠松": ["2023-12-31", "2024-04-01", "2024-06-20", "2024-09-27", "2025-01-07", "2025-03-24", "2025-09-26", "2025-12-31", "2026-03-20",
           "2026-06-26", "2026-09-11"],
}
PREV = {
    "hist": 37628, "used": "4 / 18",
    ("境目", "n"): "38/111", ("境目", "t5"): "-4.5 [-21.3, +15.1]",
    ("安全", "n"): "568/647", ("安全", "t5"): "-1.2 [-6.2, +3.8]",
    ("差の差", "n"): "38/568", ("差の差", "t5"): "-3.3 [-21.7, +15.6]",
    ("勝たないと無理", "n"): "18/44", ("勝たないと無理", "t5"): "+5.9 [-19.6, +28.8]",
    ("C境目", "t5"): "-3.0 [-13.2, +7.3]", ("C差の差", "t5"): "-1.4 [-12.1, +9.6]",
    ("-45", "t5"): "+11.0 [-19.8, +44.6]", ("+45", "t5"): "-2.1 [-26.7, +19.7]",
    ("wh境目", "t5"): "+2.2 [-8.5, +12.8]", ("wh安全", "t5"): "-0.5 [-5.1, +4.2]",
    "verdict": "痕跡なし",
}


def log(s):
    print(s, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- 取得
def get(base, key, path):
    for i in range(4):
        r = urllib.request.Request(base + path, headers={"apikey": key, "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(r, timeout=180) as x:
                return json.loads(x.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code < 500 or i == 3:
                raise
            log("  再試行 %s" % str(e)[:80])
            time.sleep(5 * (i + 1))


def pages(base, key, path):
    """⛔path の order= は一意の列の組。"""
    out, off = [], 0
    while True:
        c = get(base, key, "%s&limit=%d&offset=%d" % (path, PAGE, off))
        out.extend(c)
        if len(c) < PAGE:
            return out
        off += PAGE


def months(a, b):
    y, m = a.year, a.month
    while dt.date(y, m, 1) <= b:
        s = dt.date(y, m, 1)
        e = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
        yield s, min(e, b)
        y, m = y + (m == 12), m % 12 + 1


def pint(v):
    try:
        x = int(str(v).strip())
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def pflt(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pdate(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def rkey(tr, d, no):
    return (tr, str(d)[:10], int(no))


# ---------------------------------------------------------------- 下ごしらえ
def build_nr(runs):
    by = defaultdict(list)
    for r in runs:
        if r.get("race_no") is None:
            continue
        by[rkey(r["track"], r["race_date"], r["race_no"])].append(r)
    nr = {}
    for k, rs in by.items():
        fins = [r for r in rs if pint(r.get("finish"))]
        n = len(fins)
        ts = [pflt(r.get("time_sec")) for r in fins if pflt(r.get("time_sec"))]
        wt = min(ts) if ts else None
        for r in rs:
            f, t = pint(r.get("finish")), pflt(r.get("time_sec"))
            nr[k + (td.NF(r.get("horse_name")),)] = {
                "fin": f, "pop": pint(r.get("popularity")), "n": n, "year": int(k[1][:4]),
                "um": str(pint(r.get("runner_number")) or ""),
                "mar": (t - wt) if (f and t and wt) else None}
    return nr


def build_exp(nr):
    cell = defaultdict(lambda: np.zeros(7))
    for v in nr.values():
        if v["fin"] and v["pop"] and v["n"] and D_FROM.year <= v["year"] <= D_TO.year:
            c = cell[(v["pop"], v["n"], v["year"])]
            c += [1, v["fin"], v["fin"] <= 3, v["fin"] <= 5, v["mar"] or 0.0, v["mar"] is not None, 0]
    tot = defaultdict(lambda: np.zeros(7))
    for (p, n, y), c in cell.items():
        tot[(p, n)] += c
    cache = {}

    def exp(p, n, y):
        kk = (p, n, y)
        if kk not in cache:
            t = tot.get((p, n))
            out = None
            if t is not None:
                d = t - cell.get((p, n, y), np.zeros(7))
                if d[0] >= MIN_CELL:
                    out = {"fin": d[1] / d[0], "t3": d[2] / d[0], "t5": d[3] / d[0],
                           "mar": d[4] / d[5] if d[5] >= MIN_CELL else None}
            cache[kk] = out
        return cache[kk]
    return exp


def metrics(v, exp):
    if not v or not v["fin"] or not v["pop"] or not v["n"]:
        return None
    e = exp(v["pop"], v["n"], v["year"])
    if not e:
        return None
    m = {"fin": v["fin"] - e["fin"], "t3": (v["fin"] <= 3) - e["t3"], "t5": (v["fin"] <= 5) - e["t5"], "et3": e["t3"]}
    if v["mar"] is not None and e["mar"] is not None:
        m["mar"] = v["mar"] - e["mar"]
    return m


def letter(x, races, graded):
    """台帳の走 → 'A'/'B'/'C'(一般格)/None"""
    if x.get("tr") not in TRACKS:
        return None
    d, no = pdate(x.get("d")), pint(x.get("no"))
    if not d or not no:
        return None
    k = rkey(x["tr"], d, no)
    rc = races.get(k) or {}
    if k in graded or td.NF(rc.get("race_kind")) == "重賞" or AGEL.search(td.NF(rc.get("condition"))):
        return None
    c = str(x.get("cls") or "").strip()
    return LET.get(c[:1])



def qin(names):
    return urllib.parse.quote(",".join('"' + n.replace('"', '') + '"' for n in names))


# ---------------------------------------------------------------- 取得(読むだけ)
def fetch(base, key):
    q = urllib.parse.quote
    D = {"runs": [], "races": [], "graded": [], "sched": [], "pays": [], "hist": []}
    for tr in TRACKS:
        for y in range(R_FROM.year, F_TO.year + 1):
            a, b = max(R_FROM, dt.date(y, 1, 1)), min(F_TO, dt.date(y, 12, 31))
            f = "track=eq.%s&race_date=gte.%s&race_date=lte.%s" % (q(tr), a, b)
            D["races"] += pages(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,race_name,race_kind,prize_yen,"
                                "condition&%s&order=race_date.asc,race_no.asc" % f)
            if b < F_FROM:
                continue
            a = max(a, F_FROM)
            f = "track=eq.%s&race_date=gte.%s&race_date=lte.%s" % (q(tr), a, b)
            D["runs"] += pages(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date,"
                               "finish,popularity,time_sec,trainer_area&%s&order=race_date.asc,race_no.asc,runner_number.asc" % f)
            D["graded"] += pages(base, key, "/rest/v1/nar_graded?select=track,race_date,race_no,race_name,race_kind&%s"
                                 "&order=race_date.asc,race_no.asc" % f)
            D["sched"] += pages(base, key, "/rest/v1/nar_graded_schedule?select=race_date,track,race_name,grade&%s"
                                "&order=race_date.asc,race_name.asc" % f)
            D["pays"] += pages(base, key, "/rest/v1/nar_race_payouts?select=track,race_date,race_no,payouts&%s"
                               "&order=race_date.asc,race_no.asc" % f)
            log("%s %d 累計 走 %d・レース %d・払戻 %d" % (tr, y, len(D["runs"]), len(D["races"]), len(D["pays"])))
        for s, e in months(D_FROM, D_TO):
            D["hist"] += pages(base, key, "/rest/v1/nar_class_calc_hist?select=code,prefix,asof,v:calc->>value,lag:calc->>lag"
                               "&prefix=eq.%s&asof=gte.%s&asof=lte.%s&order=code.asc,asof.asc" % (PFX[tr], s, e))
        log("%s 計算の履歴 累計 %d" % (tr, len(D["hist"])))
    names = sorted({r["horse_name"] for r in D["runs"] if r.get("horse_name")})
    D["all"], D["codes"] = [], []
    for i in range(0, len(names), 60):
        D["all"] += pages(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,horse_name,birth_date,finish,trainer_area"
                          "&horse_name=in.(%s)&race_date=lte.%s&order=race_date.asc,track.asc,race_no.asc,runner_number.asc"
                          % (qin(names[i:i + 60]), F_TO))
        if i % 1200 == 0:
            log("全場の走 %d / 馬名 %d・行 %d" % (i, len(names), len(D["all"])))
    for i in range(0, len(names), 80):
        D["codes"] += pages(base, key, "/rest/v1/nar_horse_codes?select=code,horse_name,birth_date&horse_name=in.(%s)&order=code.asc"
                            % qin(names[i:i + 80]))
    cs = sorted({c["code"] for c in D["codes"]}, key=str)
    D["led"] = []
    for i in range(0, len(cs), 100):
        D["led"] += pages(base, key, "/rest/v1/nar_horse_prize?select=code,horse_name,runs&code=in.(%s)&order=code.asc"
                          % ",".join(q(str(c)) for c in cs[i:i + 100]))
    m = pages(base, key, "/rest/v1/nar_meta?select=key,value&key=eq.tokai_adj_days&order=key.asc")
    D["meta"] = m[0]["value"] if m else {}
    log("馬名 %d・全場の走 %d・馬札 %d・台帳 %d" % (len(names), len(D["all"]), len(D["codes"]), len(D["led"])))
    return D


def fetch_other_races(base, key, want):
    """want= {track: {date}} → {(track, date, no): row}(他場の 1〜5着の賞金と名前)"""
    out = {}
    q = urllib.parse.quote
    for tr, ds in sorted(want.items()):
        ds = sorted(ds)
        for i in range(0, len(ds), 40):
            for r in pages(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,race_name,prize_yen&track=eq.%s"
                           "&race_date=in.(%s)&order=race_date.asc,race_no.asc" % (q(tr), ",".join(ds[i:i + 40]))):
                if r.get("race_no") is not None:
                    out[rkey(r["track"], r["race_date"], r["race_no"])] = r
    return out


# ---------------------------------------------------------------- 1 頭に絞る
def bdate(s):
    return str(s)[:10] if s else None


def identify(D):
    """→ horses{hk: {...}}・hk_of(name, birth)・数。hk= 'NF名|生年月日'。"""
    births_by_name = defaultdict(Counter)
    for x in D["all"]:
        if x.get("birth_date"):
            births_by_name[td.NF(x["horse_name"])][bdate(x["birth_date"])] += 1
    st = Counter()
    rows_by_hk = defaultdict(list)
    for x in D["all"]:
        nm, b = td.NF(x["horse_name"]), bdate(x.get("birth_date"))
        if not b:
            bs = births_by_name.get(nm) or {}
            if len(bs) == 1:
                b = next(iter(bs))
                st["生年なしの走を同名 1 頭の生年で補った"] += 1
            else:
                st["生年なしで絞れない走(全場)"] += 1
                continue
        rows_by_hk[nm + "|" + b].append(x)
    codes_by_name = defaultdict(list)
    for c in D["codes"]:
        codes_by_name[td.NF(c["horse_name"])].append(c)
    led = {r["code"]: r for r in D["led"]}
    horses = {}
    for hk, xs in rows_by_hk.items():
        nm, b = hk.split("|")
        allc = codes_by_name.get(nm, [])
        cand = [c for c in allc if bdate(c.get("birth_date")) == b]
        if not cand and len(allc) == 1 and not allc[0].get("birth_date"):
            cand = allc
        if len(cand) > 1:
            st["馬札が絞れない馬(台帳なしで計算)"] += 1
        code = cand[0]["code"] if len(cand) == 1 else None
        horses[hk] = {"hk": hk, "name": nm, "birth": dt.date.fromisoformat(b), "rows": xs, "code": code,
                      "led": led.get(code) if code else None, "ncode": len(codes_by_name.get(nm, []))}
    return horses, st


# ---------------------------------------------------------------- 走歴(台帳の形)
def careers(horses, races, oraces, graded):
    """各馬 h に h['runs'](tokai_state に渡す形)・h['flag']・h['let'](東海の走の級)を付ける。→ 数"""
    st = Counter()
    for h in horses.values():
        ta = {bdate(x["race_date"]): x.get("trainer_area") for x in h["rows"] if x.get("trainer_area")}
        own = []
        for x in h["rows"]:
            d, no, f = bdate(x["race_date"]), pint(x.get("race_no")), pint(x.get("finish"))
            k = rkey(x["track"], d, no) if no else None
            rc = (races.get(k) if x["track"] in TRACKS else oraces.get(k)) if k else None
            pz = (rc or {}).get("prize_yen") or []
            prize = pz[f - 1] if (f and 1 <= f <= 5 and f <= len(pz) and pz[f - 1]) else 0
            miss = bool(f and 1 <= f <= 5 and not prize)
            own.append({"d": d, "tr": x["track"], "no": no, "fin": f, "prize": int(prize or 0),
                        "name": (rc or {}).get("race_name") or "", "ta": x.get("trainer_area"), "_miss": miss})
        if h["led"]:
            runs = [dict(x) for x in (h["led"].get("runs") or [])]
            for x in runs:
                t = ta.get(str(x.get("d"))[:10])
                if t:
                    x["ta"] = t
            have = {(x.get("tr"), str(x.get("d"))[:10]) for x in runs}
            add = [x for x in own if x["tr"] in TRACKS and (x["tr"], x["d"]) not in have]
            st["台帳の馬に nar_runs から足した東海の走"] += len(add)
            runs += add
            h["flag"] = False
        else:
            runs = own
            first = min((x["d"] for x in own), default=None)
            young_start = first and (int(first[:4]) - h["birth"].year) <= 2
            h["flag"] = (not young_start) or any(x["_miss"] for x in own)
        h["runs"] = sorted(runs, key=lambda x: str(x.get("d")), reverse=True)   # 台帳と同じ= 新しい順
        st["台帳あり" if h["led"] else ("台帳なし・印" if h["flag"] else "台帳なし・印なし")] += 1
    return st


def race_letters(horses, races, graded):
    votes = defaultdict(Counter)
    for h in horses.values():
        if not h["led"]:
            continue
        for x in h["led"].get("runs") or []:
            lt = letter(x, races, graded)
            if lt:
                d, no = pdate(x.get("d")), pint(x.get("no"))
                votes[rkey(x["tr"], d, no)][lt] += 1
    out = {}
    for k, c in votes.items():
        if len(c) == 1 and sum(c.values()) >= 2:
            out[k] = next(iter(c))
    return out


def build_seqs(horses, races, graded, nr, rlet):
    seqs, alld, st = {}, {}, Counter()
    for hk, h in horses.items():
        ledlet = {}
        if h["led"]:
            for x in h["led"].get("runs") or []:
                d, no = pdate(x.get("d")), pint(x.get("no"))
                if x.get("tr") in TRACKS and d and no:
                    ledlet[rkey(x["tr"], d, no)] = letter(x, races, graded)
        seq, ds = [], set()
        for x in h["runs"]:
            d = pdate(x.get("d"))
            if not d or d > F_TO:
                continue
            if d <= D_TO:
                ds.add(d)
            no = pint(x.get("no"))
            fin = x.get("fin") if isinstance(x.get("fin"), int) and x.get("fin") > 0 else None
            k = rkey(x.get("tr"), d, no) if (x.get("tr") in TRACKS and no) else None
            lt = None
            if k:
                rc = races.get(k) or {}
                if k in graded or td.NF(rc.get("race_kind")) == "重賞" or AGEL.search(td.NF(rc.get("condition"))):
                    lt = None
                elif k in ledlet and ledlet[k]:
                    lt = ledlet[k]
                    st["級= 台帳"] += 1
                elif k in rlet:
                    lt = rlet[k]
                    st["級= 同じレースの台帳の馬"] += 1
                else:
                    st["級なし(分からない)"] += 1
            seq.append({"d": d, "no": no or 0, "tr": x.get("tr"), "fin": fin, "let": lt, "k": k,
                        "nrv": nr.get(k + (h["name"],)) if k else None})
        seq.sort(key=lambda y: (y["d"], y["no"]))
        seqs[hk] = seq
        alld[hk] = sorted(ds)
    return seqs, alld, st


# ---------------------------------------------------------------- 見直しの日(決まりから)
def blocks_of(ds, g):
    bl = []
    for d in sorted(ds):
        if bl and (d - bl[-1][1]).days <= g:
            bl[-1][1] = d
        else:
            bl.append([d, d])
    return [(a, b) for a, b in bl]


def fy(d):
    return d.year if d.month >= 4 else d.year - 1


def ng_meets(ds, g):
    """→ {(年度, 回): 最終日}・{年度: 回の数}。開催の年度= 最終日の年度。"""
    by = defaultdict(list)
    for a, b in blocks_of(ds, g):
        by[fy(b)].append(b)
    out, cnt = {}, {}
    for y, bs in by.items():
        cnt[y] = len(bs)
        for i, b in enumerate(sorted(bs)):
            out[(y, i + 1)] = b
    return out, cnt


def rule_revs(race_days, meta):
    """→ revs{場: [(R, 出どころ)]}・表の行・名古屋の塊の幅 g と回の数"""
    last = max(max(v) for v in race_days.values())
    known_ng = {(y, k): dt.date.fromisoformat(d) for (y, k), d in td.ADJ_SET["NG"].items()}
    best = None
    for g in (1, 2, 3):
        mt, cnt = ng_meets(race_days["名古屋"], g)
        hit = sum(1 for yk, d in known_ng.items() if mt.get(yk) == d)
        dev = sum(abs(c - 26) for y, c in cnt.items() if fy(R_FROM) < y < fy(last))
        sc = (hit, -dev)
        if best is None or sc > best[0]:
            best = (sc, g, mt, cnt)
    _, g, mt, cnt = best
    meta_ks = (meta or {}).get("KS") or {}
    meta_ng = (meta or {}).get("NG") or {}
    rows, revs, revq = [], {v: [] for v in TRACKS}, {}
    qs = []
    y, m = 2023, 9
    while dt.date(y, m, 1) <= dt.date(2026, 9, 1):
        qs.append((y, m))
        y, m = (y + 1, 3) if m == 12 else (y, m + 3)
    ks_bl = blocks_of(race_days["笠松"], 2)
    for v in TRACKS:
        for (y, m) in qs:
            ym = "%d-%02d" % (y, m)
            if v == "笠松":
                ends = [b for a, b in ks_bl if b.year == y and b.month == m]
                done = last >= dt.date(y + (m == 12), m % 12 + 1, 1)      # その月が終わっている
                rule = max(ends) if (ends and done) else None
                setv = td.ADJ_SET["KS"].get(ym)
                mv = meta_ks.get(ym)
            else:
                k = {6: 7, 9: 13, 12: 19, 3: 26}[m]
                fyy = y if m != 3 else y - 1
                rule = mt.get((fyy, k))
                nxt = mt.get((fyy, k + 1))
                rule = rule if (rule and nxt) else None       # 次の回が見えていなければ確定しない
                setv = td.ADJ_SET["NG"].get((fyy, k))
                mv = meta_ng.get(ym)
            use, src = None, None
            if mv:
                use, src = dt.date.fromisoformat(mv), "nar_meta"
            elif rule:
                use, src = rule, "決まり"
            prev = next((p for p in PREV_REVS[v] if p[:7] == ym or (p[:7] == "%d-%02d" % (y + (m == 12), m % 12 + 1)
                                                                       and int(p[8:]) <= 10)), None)
            rows.append({"v": v, "q": ym, "rule": rule, "meta": mv, "set": setv, "prev": prev, "use": use, "src": src,
                         "add": bool(use and not prev)})
            if use:
                revs[v].append((use, src))
                revq[(v, use)] = (y, m)
    return revs, revq, rows, g, cnt


def set_adj(races, revs, revq):
    """tokai_state の調整日= 既定(tokai_adj_dates)のうち、revs の四半期をその日の翌日へ置き換える。"""
    base = cc.tokai_adj_dates(races)
    out = {}
    for v in TRACKS:
        rq = {revq[(v, R)]: R + dt.timedelta(days=1) for R, _ in revs[v]}
        keep = [e for e in base.get(v, []) if ((e - dt.timedelta(days=1)).year, (e - dt.timedelta(days=1)).month) not in rq]
        out[v] = sorted(keep + list(rq.values()))
    return base, out


# ---------------------------------------------------------------- 番組賞金(この便で計算)
class Prize:
    def __init__(self, horses, races, earn):
        self.h = horses
        self.races = races
        self.earn = earn
        self.cache = {}

    def at(self, hk, venue, t, prevR=None, R=None, incl=False):
        """t の前日まで(incl= t の走も)の番組賞金(千円)。調整は t の日まで(incl でも t+1 の調整は入らない)。"""
        kk = (hk, t, incl)
        if kk not in self.cache:
            ts = t.isoformat()
            h = self.h[hk]
            rs = [x for x in h["runs"] if (str(x.get("d"))[:10] < ts or (incl and str(x.get("d"))[:10] == ts))]
            v = cc.tokai_state(rs, h["birth"], t + dt.timedelta(days=1), 0, self.races)[0]
            self.cache[kk] = math.floor(v / 1000)
        return self.cache[kk]

    def E(self, hk, prevR, t, incl=False):
        ps, ts = prevR.isoformat(), t.isoformat()
        rs = [x for x in self.earn.get(hk, []) if ps < x[0] and (x[0] <= ts if incl else x[0] < ts)]
        return sum(e for d, e, w, ag in rs if not ag), any(w and not ag for d, e, w, ag in rs)


def p1(Pt, E, won):
    return Pt if (won or E > 0.25 * Pt) else math.floor(0.75 * Pt + E)


# ---------------------------------------------------------------- ① 組み立て直し
def rebuild(seqs, revs, PZ):
    rounds, demoted = [], []
    for v in TRACKS:
        rv = [R for R, _ in revs[v]]
        for i in range(1, len(rv)):
            pR, R = rv[i - 1], rv[i]
            nR = rv[i + 1] if i + 1 < len(rv) else R + dt.timedelta(days=100)
            if R < D_FROM:
                continue
            n = pred = act = hit = same = 0
            for code, seq in seqs.items():
                g = [x for x in seq if x["let"]]
                bef = [x for x in g if pR < x["d"] <= R]
                aft = [x for x in g if R < x["d"] < nR]
                if not bef or not aft or bef[-1]["tr"] != v or bef[-1]["let"] not in ("A", "B"):
                    continue
                c0, c1 = bef[-1]["let"], aft[0]["let"]
                Pt = PZ.at(code, v, R, pR, R, incl=True)
                if Pt is None:
                    continue
                E, won = PZ.E(code, pR, R, incl=True)
                pd_ = RK[td.cls(p1(Pt, E, won))] < RK[c0]
                ad = RK[c1] < RK[c0]
                n += 1
                pred += pd_
                act += ad
                hit += pd_ and ad
                same += pd_ == ad
                if ad:
                    demoted.append((v, R, code, aft[0], c1))
            un = pred + act - hit
            rounds.append({"v": v, "pR": pR, "R": R, "n": n, "pred": pred, "act": act, "hit": hit, "same": same,
                           "j": hit / un if un else None})
    return rounds, demoted


# ---------------------------------------------------------------- ② 走ごとの区分
def fbin(t):
    return "2〜6" if t <= 6 else "7〜10" if t <= 10 else "11〜14" if t <= 14 else "15〜18" if t <= 18 else "19以上"


def pbin(p):
    return "1〜3" if p <= 3 else "4〜6" if p <= 6 else "7以上"


def gbin(g):
    if g is None:
        return None
    return "〜14" if g <= 14 else "15〜28" if g <= 28 else "29〜56" if g <= 56 else "57〜"


def base_runs(seqs, alld, PZ, revs, exp, place_e):
    """発走の時点の値(本当の見直しの日で番組賞金を出す)。区分は classify で(本当/偽の日)。"""
    out, drop = [], Counter()
    for code, seq in seqs.items():
        ds = alld[code]
        for j, x in enumerate(seq):
            if not x["let"] or not (D_FROM <= x["d"] <= D_TO):
                continue
            v = x["tr"]
            rv = [R for R, _ in revs[v]]
            i = bisect.bisect_left(rv, x["d"])
            if i == 0 or i >= len(rv):
                drop["見直しの外"] += 1
                continue
            P = PZ.at(code, v, x["d"], rv[i - 1], rv[i])
            if P is None:
                drop["番組賞金なし"] += 1
                continue
            if td.cls(P) != x["let"]:
                drop["級と額が違う"] += 1
                continue
            mm = metrics(x["nrv"], exp)
            if not mm:
                drop["見込みなし(人気・頭数)"] += 1
                continue
            ek = place_e.get(x["k"], {})
            layer = None
            if j >= 2 and seq[j - 1]["fin"] and seq[j - 2]["fin"]:
                layer = (x["let"], fbin(seq[j - 1]["fin"] + seq[j - 2]["fin"]), pbin(x["nrv"]["pop"]))
            k0 = bisect.bisect_left(ds, x["d"])
            gap = (x["d"] - ds[k0 - 1]).days if k0 > 0 else None
            out.append({"code": code, "v": v, "d": x["d"], "year": x["d"].year, "c": x["let"], "P": P,
                        "e1": ek.get(1, 0), "e2": ek.get(2, 0), "e5": ek.get(5, 0), "k": x["k"], "um": x["nrv"]["um"],
                        "fin": x["nrv"]["fin"],
                        "layer": layer + (gbin(gap),) if (layer and gap is not None) else None, "m": mm})
    return out, drop


def classify(recs, revs, PZ, excluded, shift=0):
    """各走に grp(区分)・win(的/対照)・R を付けた写しを返す。shift= 偽の日のずらし(日)。"""
    fake = {v: [R + dt.timedelta(days=shift) for R, _ in revs[v]] for v in TRACKS}
    real = {v: [R for R, _ in revs[v]] for v in TRACKS}
    tmp = []
    for r in recs:
        rv = fake[r["v"]]
        i = bisect.bisect_left(rv, r["d"])
        if i == 0 or i >= len(rv):
            continue
        if (r["v"], real[r["v"]][i]) in excluded:
            continue
        pR, R = rv[i - 1], rv[i]
        dd = (R - r["d"]).days
        win = "的" if dd <= 30 else "対照"
        E, won = PZ.E(r["code"], pR, r["d"])
        f = lambda X, w: p1(r["P"] + X, E + X, won or w)  # noqa: E731
        tmp.append((r, win, R, f(0, False), f(r["e2"], False), f(r["e1"], True), f(r["e5"], False)))
    # Ｃ の見かけの線= Ａ・Ｂの走で X=0 だと下がる割合と同じ割合になる Ｃ の P1 の分位(場ごと)
    fl = {}
    for v in TRACKS:
        ab = [t for t in tmp if t[0]["v"] == v and t[0]["c"] in ("A", "B")]
        fr = np.mean([t[3] < LINE[t[0]["c"]] for t in ab]) if ab else 0.0
        cs = [t[3] for t in tmp if t[0]["v"] == v and t[0]["c"] == "C"]
        fl[v] = (float(np.quantile(cs, fr)) if cs else 0.0, fr)
    out = []
    for r, win, R, b0, b2, b1, b5 in tmp:
        line = LINE[r["c"]] if r["c"] != "C" else fl[r["v"]][0]
        if b0 >= line:
            g = "安全"
        elif b2 >= line:
            g = "境目"
        elif b1 >= line:
            g = "勝たないと無理"
        else:
            g = "見込みなし"
        if r["c"] == "C":
            g = "C" + g
        out.append(dict(r, grp=g, win=win, R=R, keep5=b5 >= line))
    return out, fl


# ---------------------------------------------------------------- ③ 比べ
class Boot:
    def __init__(self, codes):
        self.hs = sorted(codes)
        self.hix = {h: n for n, h in enumerate(self.hs)}
        H = len(self.hs)
        self.W = np.stack([np.bincount(RNG.integers(0, H, H), minlength=H).astype(np.float32) for _ in range(BOOT)])


def compare(BT, tK, rK, lay=lambda r: r["layer"]):
    tK = [r for r in tK if lay(r) is not None]
    rK = [r for r in rK if lay(r) is not None]
    nl = Counter(lay(r) for r in rK)
    keep = {L for L, n in nl.items() if n >= MIN_REF}
    tK2 = [r for r in tK if lay(r) in keep]
    rK2 = [r for r in rK if lay(r) in keep]
    out = {"n": len(tK2), "nR": len(rK2), "nT0": len(tK)}
    if not tK2:
        return out
    layers = sorted(keep & {lay(r) for r in tK2})
    lix = {L: n for n, L in enumerate(layers)}
    H = len(BT.hs)
    for k in KEYS:
        ST = np.zeros((H, len(layers)), dtype=np.float32)
        NT, SR, NR = np.zeros_like(ST), np.zeros_like(ST), np.zeros_like(ST)
        for r in tK2:
            if k in r["m"] and lay(r) in lix:
                ST[BT.hix[r["code"]], lix[lay(r)]] += r["m"][k]
                NT[BT.hix[r["code"]], lix[lay(r)]] += 1
        for r in rK2:
            if k in r["m"] and lay(r) in lix:
                SR[BT.hix[r["code"]], lix[lay(r)]] += r["m"][k]
                NR[BT.hix[r["code"]], lix[lay(r)]] += 1

        def est(a, b, c, d):
            with np.errstate(invalid="ignore", divide="ignore"):
                ok = (b > 0) & (d > 0)
                dd = np.where(ok, a / np.where(b > 0, b, 1) - c / np.where(d > 0, d, 1), 0.0)
                w = np.where(ok, b, 0)
                return (w * dd).sum(-1) / w.sum(-1)

        pt = float(est(ST.sum(0), NT.sum(0), SR.sum(0), NR.sum(0)))
        bs = est(BT.W @ ST, BT.W @ NT, BT.W @ SR, BT.W @ NR)
        lo, hi = np.nanpercentile(bs, [2.5, 97.5])
        yrs = {}
        for y in sorted({r["year"] for r in tK2}):
            acc = defaultdict(lambda: [0.0, 0, 0.0, 0])
            for r in tK2:
                if r["year"] == y and k in r["m"]:
                    acc[lay(r)][0] += r["m"][k]
                    acc[lay(r)][1] += 1
            if sum(v[1] for v in acc.values()) < 20:
                continue
            for r in rK2:
                if r["year"] == y and k in r["m"]:
                    acc[lay(r)][2] += r["m"][k]
                    acc[lay(r)][3] += 1
            nu = de = 0.0
            for v in acc.values():
                if v[1] and v[3]:
                    nu += v[1] * (v[0] / v[1] - v[2] / v[3])
                    de += v[1]
            if de:
                yrs[y] = nu / de
        bad = sum(1 for x in yrs.values() if (x < 0 if BAD_NEG[k] else x > 0))
        out[k] = {"pt": pt, "lo": float(lo), "hi": float(hi), "bs": bs, "bad": bad, "ny": len(yrs)}
    return out


def did(a, b):
    out = {"n": a.get("n", 0), "nR": b.get("n", 0)}
    for k in KEYS:
        if k in a and k in b:
            bs = a[k]["bs"] - b[k]["bs"]
            lo, hi = np.nanpercentile(bs, [2.5, 97.5])
            out[k] = {"pt": a[k]["pt"] - b[k]["pt"], "lo": float(lo), "hi": float(hi), "bs": bs, "bad": None, "ny": None}
    return out


def within_horse(tK, rK):
    out = {}
    for k in KEYS:
        tt, rr = defaultdict(list), defaultdict(list)
        for r in tK:
            if k in r["m"]:
                tt[r["code"]].append(r["m"][k])
        for r in rK:
            if k in r["m"]:
                rr[r["code"]].append(r["m"][k])
        hs = sorted(set(tt) & set(rr))
        if len(hs) < 5:
            continue
        n = np.array([len(tt[h]) for h in hs], dtype=float)
        dv = np.array([np.mean(tt[h]) - np.mean(rr[h]) for h in hs])
        H = len(hs)
        bs = np.array([((w := np.bincount(RNG.integers(0, H, H), minlength=H) * n) * dv).sum() / w.sum()
                       for _ in range(BOOT)])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        out[k] = {"pt": float((n * dv).sum() / n.sum()), "lo": float(lo), "hi": float(hi), "bs": bs,
                  "H": H, "nT": int(n.sum()), "nR": sum(len(rr[h]) for h in hs), "bad": None, "ny": None}
    return out


def fmt(res, k):
    if k not in res:
        return "-"
    x = res[k]
    s = 100 if k in ("t5", "t3") else 1
    f = "%+.1f [%+.1f, %+.1f]" if s == 100 else "%+.3f [%+.3f, %+.3f]"
    return f % (s * x["pt"], s * x["lo"], s * x["hi"])


def yrs(res, k):
    return "%d/%d" % (res[k]["bad"], res[k]["ny"]) if (k in res and res[k].get("ny") is not None) else "-"


def excl0(res, k):
    return k in res and (res[k]["lo"] > 0 or res[k]["hi"] < 0)


# ---------------------------------------------------------------- ④ 払戻
def pay_maps(pays):
    out = {}
    for p in pays:
        if p.get("race_no") is None:
            continue
        w, pl = {}, {}
        for x in p.get("payouts") or []:
            if not isinstance(x, dict):
                continue
            c, y = str(x.get("c") or "").strip(), pflt(x.get("y"))
            if y is None:
                continue
            if x.get("t") == "win":
                w[c] = y
            elif x.get("t") == "place":
                pl[c] = y
        if w or pl:
            out[rkey(p["track"], p["race_date"], p["race_no"])] = (w, pl)
    return out


def ret(runs, PM):
    ok = [r for r in runs if r["k"] in PM and r["um"]]
    if not ok:
        return None, None, 0
    w = sum(PM[r["k"]][0].get(r["um"], 0) for r in ok) / len(ok)
    p = sum(PM[r["k"]][1].get(r["um"], 0) for r in ok) / len(ok)
    return w, p, len(ok)



# ---------------------------------------------------------------- 1. 計算の履歴に無い走の内訳
def missing_breakdown(D, horses, hist):
    hs = {(h["code"], h["prefix"], str(h["asof"])[:10]) for h in hist}
    hk_of = {}
    for hk, h in horses.items():
        for x in h["rows"]:
            hk_of[(x["track"], bdate(x["race_date"]), x.get("race_no"), td.NF(x["horse_name"]))] = hk
    codes_by_name = defaultdict(list)
    for c in D["codes"]:
        codes_by_name[td.NF(c["horse_name"])].append(c)
    led_codes = {r["code"] for r in D["led"]}
    out, yr, attr = Counter(), defaultdict(Counter), Counter()
    for x in D["runs"]:
        d = pdate(x["race_date"])
        if not d or not (D_FROM <= d <= D_TO) or not x.get("horse_name"):
            continue
        nm = td.NF(x["horse_name"])
        hk = hk_of.get((x["track"], bdate(x["race_date"]), x.get("race_no"), nm))
        h = horses.get(hk) if hk else None
        code = h["code"] if h else None
        why = None
        if code and (code, PFX[x["track"]], d.isoformat()) in hs:
            why = "履歴あり"
        elif not h:
            why = "生年月日なしで 1 頭に絞れない"
        elif not codes_by_name.get(nm):
            why = "馬札(nar_horse_codes)に名前が無い"
        elif not code:
            why = "馬札に名前はあるが生年で絞れない"
        elif code not in led_codes:
            why = "馬札にあるが台帳(nar_horse_prize)に無い"
        elif not any(str(y.get("d"))[:10] == d.isoformat() and y.get("tr") == x["track"] for y in (h["led"].get("runs") or [])):
            why = "台帳にあるが その走が台帳の runs に無い"
        else:
            why = "台帳にも走にもあるが履歴の行が無い"
        out[why] += 1
        yr[d.year][why == "履歴あり"] += 1
        if why != "履歴あり" and h:
            ds = sorted(str(y["race_date"])[:10] for y in h["rows"])
            age = d.year - h["birth"].year
            tk = [y for y in sorted(h["rows"], key=lambda y: str(y["race_date"])) if y["track"] in TRACKS]
            first_tk = bdate(tk[0]["race_date"]) if tk else None
            other_before = any(y["track"] not in TRACKS and bdate(y["race_date"]) < first_tk for y in h["rows"]) if first_tk else False
            attr["(属性) 2・3 歳の走"] += age <= 3
            attr["(属性) 4 歳以上の走"] += age >= 4
            attr["(属性) 東海の外から来た馬(最初の東海の走より前に他場の走)"] += other_before
            attr["(属性) 最後の走が 2026-06-30 以前(引退・転出の見込み)"] += ds[-1] < "2026-07-01"
            attr["(属性) 着順なし(取消・除外など)"] += not pint(x.get("finish"))
    return out, yr, attr


# ---------------------------------------------------------------- 本体
def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    os.environ.pop("TOKAI_BLOCKLAG", None)
    D = fetch(base, key)
    races = {rkey(r["track"], r["race_date"], r["race_no"]): r for r in D["races"] if r.get("race_no") is not None}
    graded = {rkey(g["track"], g["race_date"], g["race_no"]) for g in D["graded"] if g.get("race_no") is not None}
    race_days = {v: sorted({pdate(k[1]) for k in races if k[0] == v}) for v in TRACKS}
    horses, st_id = identify(D)
    want = defaultdict(set)
    for h in horses.values():
        if h["led"]:
            continue
        for x in h["rows"]:
            if x["track"] not in TRACKS and pint(x.get("finish")) and pint(x.get("finish")) <= 5:
                want[x["track"]].add(bdate(x["race_date"]))
    oraces = fetch_other_races(base, key, want)
    log("他場のレース %d" % len(oraces))
    st_car = careers(horses, races, oraces, graded)

    # 見直しの日(決まり+nar_meta)と tokai_state の調整日
    revs, revq, revrows, ng_g, ng_cnt = rule_revs(race_days, D["meta"])
    for v in TRACKS:
        log("%s 見直しの日 %s" % (v, [(R.isoformat(), s) for R, s in revs[v]]))
    base_adj, new_adj = set_adj(races, revs, revq)

    # 計算の確かめ= 既定の調整日・lag で台帳の馬の計算の履歴を当て直す(標本 3000 行)
    cc.TOKAI_ADJ.clear()
    cc.TOKAI_ADJ.update(base_adj)
    hk_by_code = {h["code"]: hk for hk, h in horses.items() if h["led"]}
    samp = [x for x in D["hist"] if x["code"] in hk_by_code and pflt(x.get("v")) is not None]
    samp = [samp[i] for i in sorted(RNG.choice(len(samp), size=min(3000, len(samp)), replace=False))] if samp else []
    chk = Counter()
    for x in samp:
        h = horses[hk_by_code[x["code"]]]
        led_runs = [dict(y) for y in (h["led"].get("runs") or [])]
        for y in led_runs:
            t = next((z.get("trainer_area") for z in h["rows"] if bdate(z["race_date"]) == str(y.get("d"))[:10]
                      and z.get("trainer_area")), None)
            if t:
                y["ta"] = t
        trk = {p: t for t, p in PFX.items()}[x["prefix"]]
        v = cc.tokai_state(led_runs, h["birth"], pdate(x["asof"]), int(pflt(x.get("lag")) or 0), races, track=trk)[0]
        dlt = abs(math.floor(v / 1000) - math.floor(pflt(x["v"]) / 1000))
        chk["n"] += 1
        chk["同じ"] += dlt == 0
        chk["差 50 千円以内"] += dlt <= 50
    cc.TOKAI_ADJ.clear()
    cc.TOKAI_ADJ.update(new_adj)
    log("計算の確かめ %s" % dict(chk))

    nr = build_nr(D["runs"])
    exp = build_exp(nr)
    hk_run = {}
    for hk, h in horses.items():
        for x in h["rows"]:
            if x["track"] in TRACKS:
                hk_run[(x["track"], bdate(x["race_date"]), x.get("race_no"), td.NF(x["horse_name"]))] = hk
    erun = []
    for x in D["runs"]:
        hk = hk_run.get((x["track"], bdate(x["race_date"]), x.get("race_no"), td.NF(x.get("horse_name"))))
        if hk:
            erun.append(dict(x, horse_name=hk))
    earn = td.earn_rows(erun, D["races"], D["graded"], D["sched"])
    fake = [{"track": r["track"], "race_date": r["race_date"], "race_no": r["race_no"],
             "horse_name": "%s|%s|%s|%d" % (r["track"], r["race_date"], r["race_no"], k), "finish": k}
            for r in D["races"] if r.get("race_no") is not None and str(r["race_date"])[:10] >= F_FROM.isoformat()
            for k in (1, 2, 5)]
    place_e = defaultdict(dict)
    for nm, xs in td.earn_rows(fake, D["races"], D["graded"], D["sched"]).items():
        tr, d, no, k = nm.split("|")
        place_e[rkey(tr, d, no)][int(k)] = xs[0][1]
    rlet = race_letters(horses, races, graded)
    seqs, alld, st_let = build_seqs(horses, races, graded, nr, rlet)
    PZ = Prize(horses, races, earn)
    flagged = {hk for hk, h in horses.items() if h["flag"]}

    # 1. 履歴に無い走の内訳
    miss, miss_y, miss_attr = missing_breakdown(D, horses, D["hist"])

    # 2. 計算できた走(東海・D の期間)と、履歴との突き合わせ(新しい調整日)
    calc_n = calc_fin = calc_flag = 0
    agree = Counter()
    hist_v = {(x["code"], x["prefix"], str(x["asof"])[:10]): pflt(x.get("v")) for x in D["hist"]}
    for hk, seq in seqs.items():
        h = horses[hk]
        for x in seq:
            if not x["k"] or not (D_FROM <= x["d"] <= D_TO):
                continue
            calc_n += 1
            calc_fin += bool(x["fin"])
            calc_flag += hk in flagged
            if h["code"]:
                hv = hist_v.get((h["code"], PFX[x["tr"]], x["d"].isoformat()))
                if hv is not None:
                    P = PZ.at(hk, x["tr"], x["d"])
                    agree["n"] += 1
                    agree["級が同じ"] += td.cls(P) == td.cls(math.floor(hv / 1000))
    log("計算できた走 %d(着順あり %d・印 %d)" % (calc_n, calc_fin, calc_flag))

    allm = [metrics(v, exp) for v in nr.values() if D_FROM.year <= v["year"] <= D_TO.year]
    allm = [m for m in allm if m]
    calib = {k: (np.mean([m[k] for m in allm if k in m]), sum(1 for m in allm if k in m)) for k in KEYS}

    rounds, demoted = rebuild(seqs, revs, PZ)
    excluded = {(r["v"], r["R"]) for r in rounds if r["j"] is None or r["j"] < OK_RATE}
    used = [r for r in rounds if (r["v"], r["R"]) not in excluded]

    recs, drop = base_runs(seqs, alld, PZ, revs, exp, place_e)
    BT = Boot({r["code"] for r in recs})
    real, fl = classify(recs, revs, PZ, excluded)

    def G(rs, g, w, v=None, nof=False):
        return [r for r in rs if r["grp"] == g and r["win"] == w and (v is None or r["v"] == v)
                and not (nof and r["code"] in flagged)]

    res = {}
    for vv in (None,) + TRACKS:
        for g in ("境目", "安全", "勝たないと無理", "C境目", "C安全"):
            res[(vv, g)] = compare(BT, G(real, g, "的", vv), G(real, g, "対照", vv))
        res[(vv, "差の差")] = did(res[(vv, "境目")], res[(vv, "安全")])
        res[(vv, "C差の差")] = did(res[(vv, "C境目")], res[(vv, "C安全")])
    nof = {}
    for g in ("境目", "安全"):
        nof[g] = compare(BT, G(real, g, "的", nof=True), G(real, g, "対照", nof=True))
    nof["差の差"] = did(nof["境目"], nof["安全"])
    fakes = {}
    for s in (-45, 45):
        fr, _ = classify(recs, revs, PZ, excluded, shift=s)
        a = compare(BT, G(fr, "境目", "的"), G(fr, "境目", "対照"))
        b = compare(BT, G(fr, "安全", "的"), G(fr, "安全", "対照"))
        fakes[s] = (a, did(a, b))
    wh = {g: within_horse(G(real, g, "的"), G(real, g, "対照")) for g in ("境目", "安全")}

    # ④ 降級直後
    PM = pay_maps(D["pays"])
    rec_by = {(r["code"], r["k"]): r for r in recs}
    usedR = {(r["v"], r["R"]) for r in used}
    dem_runs, dem_keys = [], set()
    for v, R, code, x, c1 in demoted:
        if (v, R) not in usedR or (x["d"] - R).days > 45:
            continue
        r = rec_by.get((code, x["k"]))
        if r:
            dem_runs.append(dict(r, R=R))
            dem_keys.add((code, x["k"]))
    stay = []
    for code, seq in seqs.items():
        g = [x for x in seq if x["let"]]
        for a, b in zip(g, g[1:]):
            if a["let"] != b["let"] or (code, b["k"]) in dem_keys:
                continue
            rv = [R for R in sorted(R for (vv, R) in usedR if vv == b["tr"])]
            i = bisect.bisect_left(rv, b["d"])
            if i == 0 or (b["d"] - rv[i - 1]).days > 45 or a["d"] > rv[i - 1]:
                continue
            r = rec_by.get((code, b["k"]))
            if r and r["c"] in ("B", "C"):
                stay.append(r)

    def sumrow(rs):
        if not rs:
            return "0", "-", "-", "-"
        t3 = np.mean([r["m"]["t3"] for r in rs]) * 100
        w, p, n = ret(rs, PM)
        return str(len(rs)), "%+.1f" % t3, "-" if w is None else "%.0f%%" % w, "-" if p is None else "%.0f%%" % p

    # ---------------------------------------------------------------- 書き出し
    L = []
    A = L.append
    A("# 名古屋・笠松 降級前のヤラズ 研究集計(やり直し: 番組賞金を走りから計算・見直しの日を決まりから)\n")
    A("- 台本 cloud/yarazu_tokai.py・便 .github/workflows/yarazu-tokai.yml。出どころ nar_runs / nar_races / nar_graded / "
      "nar_graded_schedule / nar_race_payouts / nar_class_calc_hist / nar_horse_codes / nar_horse_prize / nar_meta(読むだけ)")
    A("- 走 %s〜%s(収得と前回の見直しは %s から・見直し後の級は %s まで)・作成 %s UTC(GitHub Actions)・前回= result.md"
      "・馬名・騎手・調教師・馬主は出さない\n"
      % (D_FROM, D_TO, F_FROM, F_TO, dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")))

    A("## 1. 計算の履歴(nar_class_calc_hist)に無い東海の走の内訳\n")
    tot = sum(miss.values())
    A("| 区分 | 走 | 割合 |\n|---|---|---|")
    for k, n in miss.most_common():
        A("| %s | %d | %.1f%% |" % (k, n, 100 * n / tot if tot else 0))
    A("| 計(%s〜%s の東海の nar_runs) | %d | |" % (D_FROM, D_TO, tot))
    A("\n無い走の属性(重なりあり):\n")
    A("| 属性 | 走 |\n|---|---|")
    for k, n in miss_attr.items():
        A("| %s | %d |" % (k, n))
    A("\n年ごと(履歴あり / 走):\n")
    A("| 年 | 履歴あり | 走 | 割合 |\n|---|---|---|---|")
    for y in sorted(miss_y):
        a, b = miss_y[y][True], miss_y[y][True] + miss_y[y][False]
        A("| %d | %d | %d | %.0f%% |" % (y, a, b, 100 * a / b if b else 0))
    A("\n1 頭に絞る: " + "・".join("%s %d" % kv for kv in sorted(st_id.items())) + "\n")

    A("## 2. 番組賞金の計算し直し\n")
    A("| 項目 | 値 |\n|---|---|")
    A("| 計算の履歴の行(前回の材料) | %d |" % len(D["hist"]))
    A("| 計算できた東海の走(%s〜%s) | %d |" % (D_FROM, D_TO, calc_n))
    A("| うち着順あり | %d |" % calc_fin)
    A("| うち印の馬の走 | %d |" % calc_flag)
    A("| 馬(台帳あり / 台帳なし・印なし / 台帳なし・印) | %d / %d / %d |" % (
        st_car["台帳あり"], st_car["台帳なし・印なし"], st_car["台帳なし・印"]))
    A("| 台帳の馬に nar_runs から足した東海の走 | %d |" % st_car["台帳の馬に nar_runs から足した東海の走"])
    A("| 他場のレース(台帳なしの馬の賞金に使った) | %d |" % len(oraces))
    A("| 確かめ= 台帳の走・既定の調整日・履歴の lag で計算の履歴を当て直す(標本 %d 行)千円まで同じ / 差 50 千円以内 | %s / %s |" % (
        chk["n"], "%.1f%%" % (100 * chk["同じ"] / chk["n"]) if chk["n"] else "-",
        "%.1f%%" % (100 * chk["差 50 千円以内"] / chk["n"]) if chk["n"] else "-"))
    A("| 履歴のある走で 新しい値と履歴の級が同じ | %s(%d 走) |" % (
        "%.1f%%" % (100 * agree["級が同じ"] / agree["n"]) if agree["n"] else "-", agree["n"]))
    for k, n in sorted(st_let.items()):
        A("| 東海の走の %s | %d |" % (k, n))
    A("")
    A("## 3. 見直しの日(決まり+nar_meta)\n")
    A("名古屋の開催の塊= 開催日の空き %d 日以内を 1 開催(設定値の日に合う幅を 1〜3 日から選んだ)。年度ごとの回の数: %s\n" % (
        ng_g, "・".join("%d年度 %d" % (y, c) for y, c in sorted(ng_cnt.items()))))
    A("| 場 | 四半期 | 決まりの日 | nar_meta | 設定値(ADJ_SET) | 前回の日 | 使う日 | 出どころ | 前回から足した |\n|---|---|---|---|---|---|---|---|---|")
    for r in revrows:
        A("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["v"], r["q"], r["rule"] or "-", r["meta"] or "-", r["set"] or "-", r["prev"] or "-", r["use"] or "-",
            r["src"] or "-", "○" if r["add"] else ""))
    A("")

    A("## 0. 材料と見込みの確かめ\n")
    A("| 項目 | 値 |\n|---|---|")
    A("| nar_runs の走(東海) | %d |" % len(D["runs"]))
    for k in KEYS:
        A("| 全走の 実際 − 見込み %s(走 %d) | %+.4f |" % (KNAME[k], calib[k][1], calib[k][0] * (100 if k in ("t5", "t3") else 1)))
    for k, n in sorted(drop.items()):
        A("| 外した走 %s | %d |" % (k, n))
    A("| 区分した走(Ａ・Ｂ・Ｃ) | %d |" % len(recs))
    for v in TRACKS:
        A("| %s Ｃ の見かけの線(千円)/Ａ・Ｂで X=0 だと下がる割合 | %.0f / %.1f%% |" % (v, fl[v][0], 100 * fl[v][1]))
    A("")

    A("## ① 組み立て直し(見直し前の値で下がる予測 と 実際の降級)\n")
    A("| 場 | 見直し | 前回 | 馬(Ａ・Ｂ) | 予測 | 実際 | 両方 | 一致率 | 全馬の当たり | 使う |\n|---|---|---|---|---|---|---|---|---|---|")
    for r in rounds:
        A("| %s | %s | %s | %d | %d | %d | %d | %s | %s | %s |" % (
            r["v"], r["R"], r["pR"], r["n"], r["pred"], r["act"], r["hit"],
            "-" if r["j"] is None else "%.0f%%" % (100 * r["j"]),
            "%.0f%%" % (100 * r["same"] / r["n"]) if r["n"] else "-", "○" if (r["v"], r["R"]) not in excluded else "×"))
    A("\n一致率= 両方 /(予測+実際−両方)。80%% 未満の回(×)は ②〜④ から外す。使う回 %d / %d(前回 %s)。\n"
      % (len(used), len(rounds), PREV["used"]))

    A("## ② 区分ごとの走の数(使う回)\n")
    cnt = Counter((r["v"], r["grp"], r["win"]) for r in real)
    A("| 場 | 区分 | 的(R まで 30 日以内) | 対照(31 日以上前) |\n|---|---|---|---|")
    for v in TRACKS:
        for g in ("安全", "境目", "勝たないと無理", "見込みなし", "C安全", "C境目", "C勝たないと無理", "C見込みなし"):
            A("| %s | %s | %d | %d |" % (v, g, cnt[(v, g, "的")], cnt[(v, g, "対照")]))
    k5 = [r for r in real if r["grp"] == "境目"]
    A("\n境目のうち 5着の収得でも残る走 %d / %d。\n" % (sum(r["keep5"] for r in k5), len(k5)))

    A("## ③ 比べ(的 − 対照・層でそろえる)\n")
    head = "| 場 | 比べ | 走(的/対照) | " + " | ".join(KNAME[k] for k in KEYS) + " | 悪い向きの年(5着内) |"
    A(head)
    A("|" + "---|" * (4 + len(KEYS)))
    for vv in (None,) + TRACKS:
        for g in ("境目", "安全", "差の差", "勝たないと無理"):
            x = res[(vv, g)]
            A("| %s | %s | %s | %s | %s |" % (vv or "両場", g + ("(境目 − 安全)" if g == "差の差" else ""),
                                              "%d/%d" % (x.get("n", 0), x.get("nR", 0)),
                                              " | ".join(fmt(x, k) for k in KEYS), yrs(x, "t5")))
    A("\n5着内・3着内は − が悪い(入着を避けた向き)・着順・秒差は + が悪い。差の差の走の欄= 境目の的 / 安全の的。\n")
    A("### 前回と並べる(両場・5着内 pt)\n")
    A("| 比べ | 前回 走 | 前回 5着内 | 今回 走 | 今回 5着内 |\n|---|---|---|---|---|")
    for g in ("境目", "安全", "差の差", "勝たないと無理"):
        x = res[(None, g)]
        A("| %s | %s | %s | %d/%d | %s |" % (g, PREV[(g, "n")], PREV[(g, "t5")], x.get("n", 0), x.get("nR", 0), fmt(x, "t5")))
    A("\n### 印の馬(台帳なしで走歴が欠けうる馬 %d 頭)を除いた主の比べ(両場)\n" % len(flagged))
    A(head)
    A("|" + "---|" * (4 + len(KEYS)))
    for g in ("境目", "安全", "差の差"):
        x = nof[g]
        A("| 両場 | %s | %s | %s | %s |" % (g + "(印を除く)", "%d/%d" % (x.get("n", 0), x.get("nR", 0)),
                                          " | ".join(fmt(x, k) for k in KEYS), yrs(x, "t5")))
    A("")

    A("## 反証\n")
    A("### (a) 対象外の級 Ｃ(見かけの線で同じ区分)\n")
    A(head)
    A("|" + "---|" * (4 + len(KEYS)))
    for vv in (None,) + TRACKS:
        for g, nm in (("C境目", "Ｃ 境目"), ("C安全", "Ｃ 安全"), ("C差の差", "Ｃ 差の差")):
            x = res[(vv, g)]
            A("| %s | %s | %s | %s | %s |" % (vv or "両場", nm, "%d/%d" % (x.get("n", 0), x.get("nR", 0)),
                                              " | ".join(fmt(x, k) for k in KEYS), yrs(x, "t5")))
    A("\n前回(両場・5着内): Ｃ 境目 %s・Ｃ 差の差 %s\n" % (PREV[("C境目", "t5")], PREV[("C差の差", "t5")]))
    A("### (b) 偽の見直しの日(本当の日 ±45 日・番組賞金は本当の値・区分と時期は偽の日で作る)\n")
    A("| ずらし | 比べ | 走(的/対照) | " + " | ".join(KNAME[k] for k in KEYS) + " | 悪い向きの年(5着内) |")
    A("|" + "---|" * (4 + len(KEYS)))
    x = res[(None, "境目")]
    A("| 0 日(本当) | 境目 | %d/%d | %s | %s |" % (x.get("n", 0), x.get("nR", 0), " | ".join(fmt(x, k) for k in KEYS), yrs(x, "t5")))
    x = res[(None, "差の差")]
    A("| 0 日(本当) | 差の差 | - | %s | - |" % " | ".join(fmt(x, k) for k in KEYS))
    for s, (a, b) in fakes.items():
        A("| %+d 日 | 境目 | %d/%d | %s | %s |" % (s, a.get("n", 0), a.get("nR", 0), " | ".join(fmt(a, k) for k in KEYS), yrs(a, "t5")))
        A("| %+d 日 | 差の差 | - | %s | - |" % (s, " | ".join(fmt(b, k) for k in KEYS)))
    A("\n前回(境目・5着内): −45 日 %s・+45 日 %s\n" % (PREV[("-45", "t5")], PREV[("+45", "t5")]))
    A("### (c) 同じ馬の中(その馬の 的 の走の平均 − その馬の 対照 の走の平均・層なし・的の走の数で重み付け)\n")
    A("| 区分 | 馬 | 走(的/対照) | " + " | ".join(KNAME[k] for k in KEYS) + " |")
    A("|" + "---|" * (3 + len(KEYS)))
    for g in ("境目", "安全"):
        x = wh[g]
        h = x.get("t5", {})
        A("| %s | %s | %s | %s |" % (g, h.get("H", 0), "%s/%s" % (h.get("nT", 0), h.get("nR", 0)), " | ".join(fmt(x, k) for k in KEYS)))
    A("\n前回(5着内): 境目 %s・安全 %s\n" % (PREV[("wh境目", "t5")], PREV[("wh安全", "t5")]))

    A("## ④ 降級の直後(見直し後 45 日以内・使う回)\n")
    A("| 群 | 走 | 3着内 − 見込み (pt) | 単勝の回収 | 複勝の回収 |\n|---|---|---|---|---|")
    A("| 下がった馬の初戦 | %s | %s | %s | %s |" % sumrow(dem_runs))
    for c in ("B", "C"):
        A("| 下がった馬の初戦(%s級へ) | %s | %s | %s | %s |" % ((c,) + sumrow([r for r in dem_runs if r["c"] == c])))
        A("| %s級に前から居る馬(同じ期間) | %s | %s | %s | %s |" % ((c,) + sumrow([r for r in stay if r["c"] == c])))
    A("")

    # ⑤ 判定(前回と同じ決め方)
    main_ = res[(None, "境目")]
    dd = res[(None, "差の差")]
    real_hit = "t5" in main_ and main_["t5"]["hi"] < 0
    did_hit = "t5" in dd and dd["t5"]["hi"] < 0
    safe_out = not excl0(res[(None, "安全")], "t5")
    c_out = not excl0(res[(None, "C境目")], "t5")
    fake_out = all(not excl0(a, "t5") for a, _ in fakes.values())
    if real_hit and did_hit and safe_out and c_out and fake_out:
        verdict = "痕跡あり: 境目×的の時期の 5着内率の差が本物だけに出て、安全・Ｃ・偽の日では出ない。"
    elif real_hit:
        verdict = ("言えない: 境目×的の時期の 5着内率は下がるが、%s。" % "・".join(
            s for s, ok in (("差の差が 0 を含む", not did_hit), ("安全でも出る", not safe_out), ("Ｃでも出る", not c_out),
                            ("偽の日でも出る", not fake_out)) if ok) or "言えない")
    else:
        verdict = "痕跡なし: 境目×的の時期の 5着内率の差は 95% 区間が 0 を含む(または + の向き)。"
    A("## ⑤ 判定\n")
    A(verdict + "(前回= %s)" % PREV["verdict"])
    A("\n(5着内率・両場: 境目 %s・差の差 %s・安全 %s・Ｃ境目 %s・偽 −45 %s・偽 +45 %s・印を除く境目 %s・印を除く差の差 %s)\n" % (
        fmt(main_, "t5"), fmt(dd, "t5"), fmt(res[(None, "安全")], "t5"), fmt(res[(None, "C境目")], "t5"),
        fmt(fakes[-45][0], "t5"), fmt(fakes[45][0], "t5"), fmt(nof["境目"], "t5"), fmt(nof["差の差"], "t5")))
    A("差= 層(級×前2走の着順合計×人気×前走からの間隔)ごとの(的 − 対照)の「実際 − 見込み」を的の走の数で重み付け。"
      "95% は馬ごとのクラスタ bootstrap 1000 回(全部の比べで同じ重み)。対照 20 走未満の層は捨てる。")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    log("書いた %s" % OUT)
    log(verdict)


if __name__ == "__main__":
    main()
