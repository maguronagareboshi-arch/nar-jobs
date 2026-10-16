# -*- coding: utf-8 -*-
"""研究用・1 回きり: 名古屋・笠松で「番組賞金の見直し(25% 控除)の前に、入着(2〜5着)を避けて降級を狙う走り」の痕跡を調べる。
便 .github/workflows/yarazu-tokai.yml(workflow_dispatch のみ)から走らせ、docs/yarazu-tokai/result.md を書く。
⛔本番 DB は REST の単純 select だけ(場×年/月ごと・order は一意の列の組)。書き込みなし。馬名・騎手・調教師・馬主は出さない。

定義(指示書どおり・兵庫 check.md の反省を最初から入れる):
- 級= 台帳(nar_horse_prize.runs)の cls の頭の字 Ａ/Ｂ/Ｃ。重賞(race_kind・nar_graded)と 2・3 歳限定戦(競走条件)は級なし。
  線= Ａ 4500 千円・Ｂ 2500 千円(tokai_demotion.LINE)。Ｃ は一番下(下がらない)= 対象外。
- 見直しの日 R= 場ごと、級が下がった続いた 2 走 (a, b](同じ場・60 日以内)を数え、3・6・9・12 月(と翌月 10 日まで)の開催日 c で
  a <= c < b の組が最多の日(同数なら遅い日・8 組未満は捨てる)。R の日の走は見直し前。
- 式= 再照合2: Pt= 見直し前の番組賞金、E= 前回の見直しの翌日から今回までの一般格の収得、期間中に勝つか E > 0.25Pt なら控除なし、
  それ以外 floor(0.75Pt + E)。収得= tokai_demotion.earn_rows(1〜5着・重賞の率・千円切り捨て・2・3 歳限定戦は E と勝ちに数えない)。
- 番組賞金 P= nar_class_calc_hist(prefix nagoya/kasamatsu)の値+その計算の締め(asof − lag)以後の東海の収得。
  計算の中の調整で値が下がった所(下がり)を近い本当の見直しに結び、本当の見直しより前の下がりの後の行は使わない。
  前回の見直しの下がりが走の日より後にある走は数えない(見直し前か後か分からない)。
① 組み立て直し= 見直しごとに、見直し前の値で下がると予測した馬と、実際に下がった馬(見直し後の最初の一般格の級が下)の
  一致率= |両方| / |どちらか|(Ａ・Ｂの馬)。80% 未満の回は以後から外す。
② 走の区分(発走の時点の値だけ)= このレースの収得 X だけが加わり見直しまで他に収得が無いとして:
  安全= X=0 でも残る / 境目= X=0 だと下がるが 2着の収得で残る / 勝たないと無理= 2着でも下がるが 1着(控除なし)で残る /
  見込みなし= 勝っても下がる。Ｃ は見かけの線(場ごと、Ａ・Ｂの走で X=0 だと下がる割合と同じ割合になる Ｃ の P1 の分位)で同じ区分。
  的の時期= R まで 30 日以内・対照の時期= R の 31 日以上前(前回の見直しの後)。cls(P) と走の級が違う走は外す。
③ 見込み= 人気×頭数ごとの率(全走・自分の年を除く)。差= 層(級×前2走の着順合計×人気×前走からの間隔)ごとの
  (的 − 対照)の「実際 − 見込み」を的の走の数で重み付け(対照 20 走未満の層は捨てる)。95% は馬ごとのクラスタ bootstrap 1000 回
  (全部の比べで同じ馬の重み= 差の差も同じ重みで引く)。反証 (a) Ｃ (b) 偽の日 R±45 (c) 同じ馬の中。
④ 降級直後= 実際に下がった馬の見直し後の初戦(45 日以内)と、同じ級に前から居る馬の同じ期間の走の 3着内 − 見込み・単複の回収率。
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

TRACKS = ("名古屋", "笠松")
PFX = {"名古屋": "nagoya", "笠松": "kasamatsu"}
D_FROM, D_TO = dt.date(2024, 1, 1), dt.date(2026, 9, 30)
F_FROM = dt.date(2023, 9, 1)            # 前回の見直し(2023-12)と収得の期間のために前から読む
LET = {"Ａ": "A", "Ｂ": "B", "Ｃ": "C", "A": "A", "B": "B", "C": "C"}
LINE = td.LINE
RK = td.RK
BOOT = 1000
MIN_CELL = 30
MIN_REF = 20
OK_RATE = 0.80
RNG = np.random.default_rng(20261017)
OUT = Path(__file__).resolve().parent.parent / "docs" / "yarazu-tokai" / "result.md"
PAGE = 1000
AGEL = re.compile(r"系(2歳|3歳)(?!以上)")
KEYS = ("t5", "t3", "fin", "mar")
KNAME = {"t5": "5着内 (pt)", "t3": "3着内 (pt)", "fin": "着順", "mar": "秒差"}
BAD_NEG = {"t5": True, "t3": True, "fin": False, "mar": False}


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


def fetch(base, key):
    q = urllib.parse.quote
    D = {"runs": [], "races": [], "graded": [], "sched": [], "pays": [], "hist": []}
    for tr in TRACKS:
        for y in range(F_FROM.year, D_TO.year + 1):
            a, b = max(F_FROM, dt.date(y, 1, 1)), min(D_TO, dt.date(y, 12, 31))
            f = "track=eq.%s&race_date=gte.%s&race_date=lte.%s" % (q(tr), a, b)
            D["runs"] += pages(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,"
                               "finish,popularity,time_sec&%s&order=race_date.asc,race_no.asc,runner_number.asc" % f)
            D["races"] += pages(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,race_name,race_kind,prize_yen,"
                                "condition&%s&order=race_date.asc,race_no.asc" % f)
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
    codes = sorted({h["code"] for h in D["hist"]})
    D["led"] = []
    for i in range(0, len(codes), 50):
        D["led"] += pages(base, key, "/rest/v1/nar_horse_prize?select=code,horse_name,runs&code=in.(%s)&order=code.asc"
                          % ",".join(q(str(c)) for c in codes[i:i + 50]))
    m = pages(base, key, "/rest/v1/nar_meta?select=key,value&key=eq.tokai_adj_days&order=key.asc")
    D["meta"] = m[0]["value"] if m else {}
    log("馬 %d・台帳 %d" % (len(codes), len(D["led"])))
    return D


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


def build_seqs(led, races, graded, nr):
    seqs, alld, names = {}, {}, {}
    for r in led:
        nm = td.NF(r.get("horse_name"))
        names[r["code"]] = nm
        seq, ds = [], set()
        for x in r.get("runs") or []:
            d = pdate(x.get("d"))
            if not d or d > D_TO:
                continue
            ds.add(d)
            fin = x.get("fin") if isinstance(x.get("fin"), int) and x.get("fin") > 0 else None
            no = pint(x.get("no"))
            k = rkey(x.get("tr"), d, no) if (x.get("tr") in TRACKS and no) else None
            seq.append({"d": d, "no": no or 0, "tr": x.get("tr"), "fin": fin, "let": letter(x, races, graded),
                        "k": k, "nrv": nr.get(k + (nm,)) if k else None})
        seq.sort(key=lambda y: (y["d"], y["no"]))
        seqs[r["code"]] = seq
        alld[r["code"]] = sorted(ds)
    return seqs, alld, names


# ---------------------------------------------------------------- 見直しの日
def detect_revs(seqs, race_days):
    out = {}
    for v in TRACKS:
        pairs = []
        for seq in seqs.values():
            g = [x for x in seq if x["let"] and x["tr"] == v]
            for a, b in zip(g, g[1:]):
                if RK[b["let"]] < RK[a["let"]] and 0 < (b["d"] - a["d"]).days <= 60:
                    pairs.append((a["d"], b["d"]))
        best = {}
        for c in sorted(race_days[v]):
            if c.month in (3, 6, 9, 12):
                qk = (c.year, c.month)
            elif c.month in (1, 4, 7, 10) and c.day <= 10:
                qk = (c.year - (c.month == 1), 12 if c.month == 1 else c.month - 1)
            else:
                continue
            k = sum(1 for a, b in pairs if a <= c < b)
            if k and (qk not in best or k >= best[qk][0]):
                best[qk] = (k, c)
        out[v] = [(c, k) for qk, (k, c) in sorted(best.items()) if k >= 8]
    return out


# ---------------------------------------------------------------- 番組賞金(計算の履歴+締め以後の収得)
class Prize:
    def __init__(self, hist, names, earn, revs):
        self.rows = defaultdict(list)
        for h in hist:
            d, v = pdate(h["asof"]), pflt(h.get("v"))
            if d and v is not None:
                self.rows[(h["code"], h["prefix"])].append((d, v, int(pflt(h.get("lag")) or 0)))
        self.drops = {}
        self.revs = revs
        for k, rs in self.rows.items():
            rs.sort()
            venue = {p: t for t, p in PFX.items()}[k[1]]
            rv = [R for R, _ in revs[venue]]
            dl = []
            for i in range(1, len(rs)):
                if rs[i][1] < rs[i - 1][1] - 0.5:
                    near = min(rv, key=lambda R: abs((R - rs[i][0]).days)) if rv else None
                    if near and abs((near - rs[i][0]).days) <= 45:
                        dl.append((i, near))
            self.drops[k] = dl
        self.names = names
        self.earn = earn

    def at(self, code, venue, t, prevR, R, incl=False):
        """t の時点(incl= t の走も数える)の番組賞金(千円)。分からなければ None。"""
        k = (code, PFX[venue])
        rs = self.rows.get(k)
        if not rs:
            return None
        lo, hi = 0, len(rs)
        for i, near in self.drops[k]:
            if near == prevR:
                if rs[i][0] > t:
                    return None
                lo = max(lo, i)
            elif near == R:
                hi = min(hi, i)
        j = None
        for i in range(lo, hi):
            if rs[i][0] <= t:
                j = i
        if j is None:
            return None
        a, v, lag = rs[j]
        cut = (a - dt.timedelta(days=lag)).isoformat()
        ts = t.isoformat()
        add = sum(e for d, e, w, ag in self.earn.get(self.names[code], [])
                  if cut <= d and (d <= ts if incl else d < ts))
        return math.floor(v / 1000) + add

    def E(self, code, prevR, t, incl=False):
        ps, ts = prevR.isoformat(), t.isoformat()
        rs = [x for x in self.earn.get(self.names[code], []) if ps < x[0] and (x[0] <= ts if incl else x[0] < ts)]
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


# ---------------------------------------------------------------- 本体
def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    D = fetch(base, key)
    races = {rkey(r["track"], r["race_date"], r["race_no"]): r for r in D["races"] if r.get("race_no") is not None}
    graded = {rkey(g["track"], g["race_date"], g["race_no"]) for g in D["graded"] if g.get("race_no") is not None}
    race_days = {v: sorted({pdate(k[1]) for k in races if k[0] == v}) for v in TRACKS}
    nr = build_nr(D["runs"])
    exp = build_exp(nr)
    earn = td.earn_rows([x for x in D["runs"] if x.get("horse_name")], D["races"], D["graded"], D["sched"])
    # このレースで k 着なら入る収得(同じ earn_rows で作る= 率も同じ)
    fake = [{"track": r["track"], "race_date": r["race_date"], "race_no": r["race_no"],
             "horse_name": "%s|%s|%s|%d" % (r["track"], r["race_date"], r["race_no"], k), "finish": k}
            for r in D["races"] if r.get("race_no") is not None for k in (1, 2, 5)]
    place_e = defaultdict(dict)
    for nm, xs in td.earn_rows(fake, D["races"], D["graded"], D["sched"]).items():
        tr, d, no, k = nm.split("|")
        place_e[rkey(tr, d, no)][int(k)] = xs[0][1]
    seqs, alld, names = build_seqs(D["led"], races, graded, nr)
    revs = detect_revs(seqs, race_days)
    for v in TRACKS:
        log("%s 見直しの日 %s" % (v, [(R.isoformat(), k) for R, k in revs[v]]))
    PZ = Prize(D["hist"], names, earn, revs)

    # 全走の 実際 − 見込み
    allm = [metrics(v, exp) for v in nr.values() if D_FROM.year <= v["year"] <= D_TO.year]
    allm = [m for m in allm if m]
    calib = {k: (np.mean([m[k] for m in allm if k in m]), sum(1 for m in allm if k in m)) for k in KEYS}

    rounds, demoted = rebuild(seqs, revs, PZ)
    excluded = {(r["v"], r["R"]) for r in rounds if r["j"] is None or r["j"] < OK_RATE}
    used = [r for r in rounds if (r["v"], r["R"]) not in excluded]

    recs, drop = base_runs(seqs, alld, PZ, revs, exp, place_e)
    BT = Boot({r["code"] for r in recs})
    real, fl = classify(recs, revs, PZ, excluded)

    def G(rs, g, w, v=None):
        return [r for r in rs if r["grp"] == g and r["win"] == w and (v is None or r["v"] == v)]

    res = {}
    for vv in (None,) + TRACKS:
        for g in ("境目", "安全", "勝たないと無理", "C境目", "C安全"):
            res[(vv, g)] = compare(BT, G(real, g, "的", vv), G(real, g, "対照", vv))
        res[(vv, "差の差")] = did(res[(vv, "境目")], res[(vv, "安全")])
        res[(vv, "C差の差")] = did(res[(vv, "C境目")], res[(vv, "C安全")])
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
    A("# 名古屋・笠松 降級前のヤラズ 研究集計\n")
    A("- 台本 cloud/yarazu_tokai.py・便 .github/workflows/yarazu-tokai.yml。出どころ nar_runs / nar_races / nar_graded / "
      "nar_graded_schedule / nar_race_payouts / nar_class_calc_hist / nar_horse_prize / nar_meta(読むだけ)")
    A("- 走 %s〜%s(収得と前回の見直しは %s から)・作成 %s UTC(GitHub Actions)・馬名・騎手・調教師・馬主は出さない\n"
      % (D_FROM, D_TO, F_FROM, dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")))
    A("## 0. 材料と見込みの確かめ\n")
    A("| 項目 | 値 |\n|---|---|")
    A("| nar_runs の走 | %d |" % len(D["runs"]))
    A("| 計算の履歴の行 | %d |" % len(D["hist"]))
    A("| 台帳の馬 | %d |" % len(D["led"]))
    for k in KEYS:
        A("| 全走の 実際 − 見込み %s(走 %d) | %+.4f |" % (KNAME[k], calib[k][1], calib[k][0] * (100 if k in ("t5", "t3") else 1)))
    for k, n in sorted(drop.items()):
        A("| 外した走 %s | %d |" % (k, n))
    A("| 区分した走(Ａ・Ｂ・Ｃ) | %d |" % len(recs))
    for v in TRACKS:
        A("| %s Ｃ の見かけの線(千円)/Ａ・Ｂで X=0 だと下がる割合 | %.0f / %.1f%% |" % (v, fl[v][0], 100 * fl[v][1]))
    A("")
    A("### 見直しの日(台帳の級が下がった組から特定)\n")
    A("| 場 | 見直しの日(組の数) |\n|---|---|")
    for v in TRACKS:
        A("| %s | %s |" % (v, "・".join("%s(%d)" % (R.isoformat(), k) for R, k in revs[v])))
    A("\n照合: nar_meta tokai_adj_days(笠松)= %s / tokai_demotion.ADJ_SET= %s\n"
      % (json.dumps((D["meta"] or {}).get("KS") or {}, ensure_ascii=False),
         json.dumps({"KS": td.ADJ_SET["KS"], "NG": {"%d-%d" % k: d for k, d in td.ADJ_SET["NG"].items()}}, ensure_ascii=False)))

    A("## ① 組み立て直し(見直し前の値で下がる予測 と 実際の降級)\n")
    A("| 場 | 見直し | 前回 | 馬(Ａ・Ｂ) | 予測 | 実際 | 両方 | 一致率 | 全馬の当たり | 使う |\n|---|---|---|---|---|---|---|---|---|---|")
    for r in rounds:
        A("| %s | %s | %s | %d | %d | %d | %d | %s | %s | %s |" % (
            r["v"], r["R"], r["pR"], r["n"], r["pred"], r["act"], r["hit"],
            "-" if r["j"] is None else "%.0f%%" % (100 * r["j"]),
            "%.0f%%" % (100 * r["same"] / r["n"]) if r["n"] else "-", "○" if (r["v"], r["R"]) not in excluded else "×"))
    A("\n一致率= 両方 /(予測+実際−両方)。80%% 未満の回(×)は ②〜④ から外す。使う回 %d / %d。\n" % (len(used), len(rounds)))

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

    A("## 反証\n")
    A("### (a) 対象外の級 Ｃ(見かけの線で同じ区分)\n")
    A(head)
    A("|" + "---|" * (4 + len(KEYS)))
    for vv in (None,) + TRACKS:
        for g, nm in (("C境目", "Ｃ 境目"), ("C安全", "Ｃ 安全"), ("C差の差", "Ｃ 差の差")):
            x = res[(vv, g)]
            A("| %s | %s | %s | %s | %s |" % (vv or "両場", nm, "%d/%d" % (x.get("n", 0), x.get("nR", 0)),
                                              " | ".join(fmt(x, k) for k in KEYS), yrs(x, "t5")))
    A("\n### (b) 偽の見直しの日(本当の日 ±45 日・番組賞金は本当の値・区分と時期は偽の日で作る)\n")
    A("| ずらし | 比べ | 走(的/対照) | " + " | ".join(KNAME[k] for k in KEYS) + " | 悪い向きの年(5着内) |")
    A("|" + "---|" * (4 + len(KEYS)))
    x = res[(None, "境目")]
    A("| 0 日(本当) | 境目 | %d/%d | %s | %s |" % (x.get("n", 0), x.get("nR", 0), " | ".join(fmt(x, k) for k in KEYS), yrs(x, "t5")))
    x = res[(None, "差の差")]
    A("| 0 日(本当) | 差の差 | - | %s | - |" % " | ".join(fmt(x, k) for k in KEYS))
    for s, (a, b) in fakes.items():
        A("| %+d 日 | 境目 | %d/%d | %s | %s |" % (s, a.get("n", 0), a.get("nR", 0), " | ".join(fmt(a, k) for k in KEYS), yrs(a, "t5")))
        A("| %+d 日 | 差の差 | - | %s | - |" % (s, " | ".join(fmt(b, k) for k in KEYS)))
    A("\n### (c) 同じ馬の中(その馬の 的 の走の平均 − その馬の 対照 の走の平均・層なし・的の走の数で重み付け)\n")
    A("| 区分 | 馬 | 走(的/対照) | " + " | ".join(KNAME[k] for k in KEYS) + " |")
    A("|" + "---|" * (3 + len(KEYS)))
    for g in ("境目", "安全"):
        x = wh[g]
        h = x.get("t5", {})
        A("| %s | %s | %s | %s |" % (g, h.get("H", 0), "%s/%s" % (h.get("nT", 0), h.get("nR", 0)), " | ".join(fmt(x, k) for k in KEYS)))

    A("\n## ④ 降級の直後(見直し後 45 日以内・使う回)\n")
    A("| 群 | 走 | 3着内 − 見込み (pt) | 単勝の回収 | 複勝の回収 |\n|---|---|---|---|---|")
    A("| 下がった馬の初戦 | %s | %s | %s | %s |" % sumrow(dem_runs))
    for c in ("B", "C"):
        A("| 下がった馬の初戦(%s級へ) | %s | %s | %s | %s |" % ((c,) + sumrow([r for r in dem_runs if r["c"] == c])))
        A("| %s級に前から居る馬(同じ期間) | %s | %s | %s | %s |" % ((c,) + sumrow([r for r in stay if r["c"] == c])))
    A("")

    # ⑤ 判定
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
    A(verdict)
    A("\n(5着内率・両場: 境目 %s・差の差 %s・安全 %s・Ｃ境目 %s・偽 −45 %s・偽 +45 %s)\n" % (
        fmt(main_, "t5"), fmt(dd, "t5"), fmt(res[(None, "安全")], "t5"), fmt(res[(None, "C境目")], "t5"),
        fmt(fakes[-45][0], "t5"), fmt(fakes[45][0], "t5")))
    A("差= 層(級×前2走の着順合計×人気×前走からの間隔)ごとの(的 − 対照)の「実際 − 見込み」を的の走の数で重み付け。"
      "95% は馬ごとのクラスタ bootstrap 1000 回(全部の比べで同じ重み)。対照 20 走未満の層は捨てる。")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    log("書いた %s" % OUT)
    log(verdict)


if __name__ == "__main__":
    main()
