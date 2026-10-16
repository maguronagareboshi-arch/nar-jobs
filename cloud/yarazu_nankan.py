# -*- coding: utf-8 -*-
"""研究用・1 回きり: 南関4場(大井・川崎・船橋・浦和)の格付の切替(1/1・7/1)の前に「入着を避けて降級を狙う走り(ヤラズ)」の痕跡があるか。
便 .github/workflows/yarazu-nankan.yml(workflow_dispatch のみ)から走らせ、docs/yarazu-nankan/result.md を書く。
⛔本番 DB は REST の単純 select だけ(場×年・order は一意の列の組)。書き込みなし。馬名・騎手・調教師・馬主は結果に出さない。

決まり= 公式 Q&A https://www.nankankeiba.com/info/qanda/program.html(線の表は cloud/nankan_demotion.py KAMI/SHIMO)。
  切替 S で「今の点 < 切替後の半期表 × 切替後の馬齢 × 今の級 の線」なら降級。C3 は下が無い・8歳以上(切替前の馬齢)は線が同じ= 対象外。
着内ポイント(1〜5 着で点が増える)= cloud/nankan_hist.run_points(主催者の結果ページの nar_races.nankan.pts を優先・
  無ければレース名 × 公式 Q&A の着内ポイント表)。⇒ 入着= 1〜5 着(公式の表で決めた)。
点= nar_nankan_point_hist の meet_end < レース日 の最後の行 + その後このレースより前の自分の走の着内ポイント(発走前に分かる)。
級(レース時)= レース名の単一の級(nankan_hist.kaku_of_race)・無ければその開催の行の kaku_ran(meet_end − レース日 ≤ 7 日)。

① 組み立て直し: 各切替 S・各場(S の前の最後の走の場)で、S の前の最後の行の点と kaku_ran(無ければ最後の走のレース名の級)で
   「下がる」と予測した馬と、実際に下がった馬(S 後 120 日以内の最初の南関の走のレース名の単一の級が下)の一致。
   一致率= min(予測のうち当たり, 実際のうち拾えた)。80% 未満の回は以後から外す。
② 区分: 次の切替(本当の日)の線 L・このレースの 1 着の点 p1 で 安全 P≥L / 境目 P<L≤P+p1 / 深く圏内 P+p1<L。
   対象外= C3・8歳以上・線が空欄。対象外の見かけの線(反証 a)= 8歳以上は 今の線 + 同じ級の 7 歳が同じ切替で受ける線の上げ幅、
   C3 は 同じ切替・馬齢の C2 の線 ÷ 2。
   時期= 次の切替まで 1〜45 日= 的・46〜135 日= 対照。
③ 見込み= 人気×頭数ごとの率(2024-01〜2026-09 の南関の全走・自分の年を除く・30 走未満は捨てる)。
   層= 級×前2走の着順合計の区分×人気の区分×前走からの間隔の区分。差= 層ごとの(的 − 対照)の「実際 − 見込み」を的の走の数で重み付け
   (対照 10 走未満の層は捨てる)。差の差= 境目の差 − 安全の差。95% は馬ごとのクラスタ bootstrap 1000 回。
   反証 a 対象外の群 / b 切替日を ±60 日ずらした偽の日(区分は本当の次の切替の線のまま・時期だけ偽の日で) / c 同じ馬の中の差。
④ 降級直後: ① で実際に下がった馬の S 後最初の走の 3着内 − 見込み・単複の回収率(nar_race_payouts)と、
   同じ期間に前と同じ級に残った馬の S 後最初の走。
"""
import bisect
import datetime as dt
import json
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
import nankan_demotion as ND  # noqa: E402
import nankan_hist as NH  # noqa: E402

TRACKS = ("大井", "川崎", "船橋", "浦和")
CLASSES = ["A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3"]
D_FROM, D_TO = dt.date(2024, 1, 1), dt.date(2026, 9, 30)
FETCH_FROM = dt.date(2023, 10, 1)            # 前2走・間隔のためだけ
SWITCHES = [dt.date(2024, 7, 1), dt.date(2025, 1, 1), dt.date(2025, 7, 1), dt.date(2026, 1, 1), dt.date(2026, 7, 1)]
ALL_SW = SWITCHES + [dt.date(2027, 1, 1)]
T_WIN, C_WIN = (1, 45), (46, 135)
FIRST_AFTER = 120
MIN_CELL, MIN_CTRL = 30, 10
BOOT = 1000
RNG = np.random.default_rng(20261017)
OUT = HERE.parent / "docs" / "yarazu-nankan" / "result.md"
PAGE = 1000
Z2H = str.maketrans("ＡＢＣ１２３", "ABC123")
q = urllib.parse.quote


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


def fetch(base, key):
    runs, races, pays = [], [], []
    for tr in TRACKS:
        for y in range(FETCH_FROM.year, D_TO.year + 1):
            a = max(dt.date(y, 1, 1), FETCH_FROM)
            b = min(dt.date(y, 12, 31), D_TO)
            f = "track=eq.%s&race_date=gte.%s&race_date=lte.%s" % (q(tr), a, b)
            runs += pages(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,"
                          "finish,finish_note,popularity,time_sec&%s&order=race_date.asc,race_no.asc,runner_number.asc" % f)
            races += pages(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,race_name,race_kind,condition,"
                           "nankan,cancelled&%s&order=race_date.asc,race_no.asc" % f)
            pays += pages(base, key, "/rest/v1/nar_race_payouts?select=track,race_date,race_no,payouts&%s"
                          "&order=race_date.asc,race_no.asc" % f)
            log("%s %d 累計 走 %d・レース %d・払戻 %d" % (tr, y, len(runs), len(races), len(pays)))
    pts = pages(base, key, "/rest/v1/nar_nankan_points?select=code,horse_name,birth_date&order=code.asc")
    hist = pages(base, key, "/rest/v1/nar_nankan_point_hist?select=code,meet_end,points,kaku_ran&order=code.asc,meet_end.asc")
    log("馬 %d・点の履歴 %d" % (len(pts), len(hist)))
    return runs, races, pays, pts, hist


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


def norm_k(k):
    k = str(k or "").strip().translate(Z2H).upper()
    return k if k in CLASSES else None


def line_at(S, k, age):
    if k not in ND.KAMI or age is None or age < 3:
        return None
    return ND.line_of(S, k, age)


def prev_tbl_line(S, k, age_before):
    tbl = ND.SHIMO if S.month == 1 else ND.KAMI
    if k not in tbl or age_before < 3:
        return None
    return tbl[k][min(age_before, 8) - 3]


def rule_line(S, k, by):
    """→ (L, 対象外か, 見かけの線)。L は本当の線(対象外は None)。"""
    if k is None or by is None:
        return None, None, None
    age = S.year - by
    age_b = age if S.month == 7 else age - 1
    if age < 3:
        return None, None, None
    if k == "C3":
        c2 = line_at(S, "C2", age)
        return None, True, (c2 / 2.0 if c2 else None)
    L = line_at(S, k, age)
    if age_b >= 8:
        a7, b7 = line_at(S, k, 7), prev_tbl_line(S, k, 7 if S.month == 7 else 6)
        d7 = (a7 - b7) if (a7 is not None and b7 is not None) else None
        return None, True, (L + d7 if (L is not None and d7 is not None) else None)
    if not L:
        return None, True, None
    return L, False, None


def next_sw(d, sws):
    i = bisect.bisect_right(sws, d)
    return sws[i] if i < len(sws) else None


# ---------------------------------------------------------------- 下ごしらえ
def prep(runs, races, pays, pts, hist):
    race = {(r["track"], str(r["race_date"])[:10], int(r["race_no"])): r for r in races if r.get("race_no") is not None}
    pay = {}
    for p in pays:
        k = (p["track"], str(p["race_date"])[:10], int(p["race_no"]))
        w, pl = {}, {}
        for x in p.get("payouts") or []:
            if x.get("y") is None:
                continue
            if x.get("t") == "win":
                w[str(x.get("c"))] = int(x["y"])
            elif x.get("t") == "place":
                pl[str(x.get("c"))] = int(x["y"])
        pay[k] = (w, pl)
    nm = defaultdict(set)
    birth = {}
    for p in pts:
        if p.get("horse_name"):
            nm[p["horse_name"]].add(str(p["code"]))
        birth[str(p["code"])] = p.get("birth_date")
    code_of = {n: next(iter(c)) for n, c in nm.items() if len(c) == 1}
    H = defaultdict(list)
    for h in hist:
        H[str(h["code"])].append((str(h["meet_end"])[:10], h.get("points"), norm_k(h.get("kaku_ran"))))
    for c in H:
        H[c].sort()
    by_race = defaultdict(list)
    for r in runs:
        if r.get("race_no") is None:
            continue
        by_race[(r["track"], str(r["race_date"])[:10], int(r["race_no"]))].append(r)
    R = []
    for k, rs in by_race.items():
        fins = [pint(r.get("finish")) for r in rs]
        n = sum(1 for f in fins if f)
        fc = Counter(f for f in fins if f)
        ts = [pflt(r.get("time_sec")) for r in rs if pint(r.get("finish")) and pflt(r.get("time_sec"))]
        wt = min(ts) if ts else None
        rc = race.get(k)
        p1, _ = NH.run_points({"fin": 1, "note": ""}, rc, 1) if rc else (None, "")
        kr = NH.kaku_of_race(rc.get("race_name"), rc.get("race_kind")) if rc else None
        for r in rs:
            f, t = pint(r.get("finish")), pflt(r.get("time_sec"))
            pt, _ = NH.run_points({"fin": f, "note": r.get("finish_note") or ""}, rc, fc.get(f, 1)) if rc else (None, "")
            R.append({"tr": k[0], "d": dt.date.fromisoformat(k[1]), "ds": k[1], "no": k[2], "rn": str(r.get("runner_number")),
                      "name": r.get("horse_name"), "fin": f, "pop": pint(r.get("popularity")), "n": n,
                      "mar": (t - wt) if (f and t and wt is not None) else None, "p1": p1, "pt": pt,
                      "kr": norm_k(kr), "rk": k})
    R.sort(key=lambda x: (x["d"], x["no"], x["rn"]))
    return R, code_of, birth, H, pay, race


def birth_year(code, birth):
    return ND.birth_year({"code": code, "birth_date": birth.get(code)})


# ---------------------------------------------------------------- 見込み
def build_exp(R):
    cell = defaultdict(lambda: np.zeros(6))
    for v in R:
        if v["fin"] and v["pop"] and v["n"] and D_FROM <= v["d"] <= D_TO:
            cell[(v["pop"], v["n"], v["d"].year)] += [1, v["fin"] <= 5, v["fin"] <= 3, v["fin"],
                                                      v["mar"] or 0.0, v["mar"] is not None]
    tot = defaultdict(lambda: np.zeros(6))
    for (p, n, y), c in cell.items():
        tot[(p, n)] += c
    cache = {}

    def exp(p, n, y):
        kk = (p, n, y)
        if kk not in cache:
            t = tot.get((p, n))
            out = None
            if t is not None:
                d = t - cell.get(kk, np.zeros(6))
                if d[0] >= MIN_CELL:
                    out = {"in5": d[1] / d[0], "top3": d[2] / d[0], "fin": d[3] / d[0],
                           "mar": d[4] / d[5] if d[5] >= MIN_CELL else None}
            cache[kk] = out
        return cache[kk]
    return exp


MET = [("in5", "入着(1〜5着)率 (pt)", 100), ("top3", "3着内率 (pt)", 100), ("fin", "着順", 1), ("mar", "勝ち馬との秒差", 1)]


def resid(v, exp):
    if not v["fin"] or not v["pop"] or not v["n"]:
        return None
    e = exp(v["pop"], v["n"], v["d"].year)
    if not e:
        return None
    m = {"in5": (v["fin"] <= 5) - e["in5"], "top3": (v["fin"] <= 3) - e["top3"], "fin": v["fin"] - e["fin"],
         "e3": e["top3"]}
    m["mar"] = (v["mar"] - e["mar"]) if (v["mar"] is not None and e["mar"] is not None) else None
    return m


# ---------------------------------------------------------------- ① 組み立て直し
def rebuild(R, code_of, birth, H):
    byh = defaultdict(list)
    for v in R:
        c = code_of.get(v["name"])
        if c:
            byh[c].append(v)
    rows = []
    why = Counter()
    for S in SWITCHES:
        for c, L in H.items():
            ms = [x[0] for x in L]
            i = bisect.bisect_left(ms, S.isoformat()) - 1
            if i < 0 or ms[i] < (S - dt.timedelta(days=183)).isoformat():
                continue
            me, P, kk = L[i]
            rs = byh.get(c, [])
            ds = [x["d"] for x in rs]
            j = bisect.bisect_left(ds, S)
            pre = rs[j - 1] if j > 0 else None
            if kk is None and pre is not None:
                kk = pre["kr"]
            if P is None or kk is None:
                why["点か級なし"] += 1
                continue
            Lr, excl, _ = rule_line(S, kk, birth_year(c, birth))
            if excl is None or excl:
                why["対象外(C3・8歳以上・線空欄・馬齢不明)"] += 1
                continue
            post = rs[j] if j < len(rs) and (rs[j]["d"] - S).days <= FIRST_AFTER else None
            if post is None:
                why["切替後 120 日以内に走なし"] += 1
                continue
            if post["kr"] is None:
                why["切替後最初の走が単一の級でない"] += 1
                continue
            rows.append({"S": S, "tr": pre["tr"] if pre else post["tr"], "code": c, "k": kk, "pred": P < Lr,
                         "down": CLASSES.index(post["kr"]) > CLASSES.index(kk), "same": post["kr"] == kk, "post": post})
    return rows, why


# ---------------------------------------------------------------- ② 区分
def gap_b(g):
    return "無" if g is None else ("~14" if g <= 14 else "15-28" if g <= 28 else "29-56" if g <= 56 else "57~")


def p2_b(s):
    return "無" if s is None else ("~6" if s <= 6 else "7-12" if s <= 12 else "13-18" if s <= 18 else "19~")


def pop_b(p):
    return "1" if p == 1 else "2-3" if p <= 3 else "4-6" if p <= 6 else "7~"


def classify(R, code_of, birth, H, exp):
    """各走 → 区分の材料。区分は発走前の値だけ(点・級・線・時期)。"""
    byname = defaultdict(list)
    for v in R:
        byname[v["name"]].append(v)
    out = []
    why = Counter()
    for name, rs in byname.items():
        c = code_of.get(name)
        prevs = []
        for idx, v in enumerate(rs):
            hist_prev = [x for x in prevs]
            prevs.append(v)
            if not (D_FROM <= v["d"] <= D_TO):
                continue
            if not c or c not in H:
                why["コードか点の履歴なし"] += 1
                continue
            m = resid(v, exp)
            if not m:
                why["見込みなし"] += 1
                continue
            L = H[c]
            ms = [x[0] for x in L]
            i = bisect.bisect_left(ms, v["ds"]) - 1
            if i < 0 or L[i][1] is None:
                why["レース前の点なし"] += 1
                continue
            me = L[i][0]
            P = float(L[i][1])
            bad = False
            for x in hist_prev:
                if x["ds"] > me:
                    if x["pt"] is None:
                        bad = True
                        break
                    P += x["pt"]
            if bad or v["p1"] is None:
                why["点が決まらない走"] += 1
                continue
            k = v["kr"]
            if k is None and i + 1 < len(L) and (dt.date.fromisoformat(L[i + 1][0]) - v["d"]).days <= 7:
                k = L[i + 1][2]
            if k is None:
                why["級なし"] += 1
                continue
            Sn = next_sw(v["d"], ALL_SW)
            by = birth_year(c, birth)
            Lr, excl, Lp = rule_line(Sn, k, by)
            if excl is None:
                why["馬齢不明・3歳未満"] += 1
                continue

            def st(Lx):
                if Lx is None:
                    return None
                return "安全" if P >= Lx else ("境目" if P + v["p1"] >= Lx else "深く圏内")
            fp = [x["fin"] for x in hist_prev[-2:] if x["fin"]]
            p2 = sum(fp) if len(hist_prev) >= 2 and len(fp) == 2 else None
            g = (v["d"] - hist_prev[-1]["d"]).days if hist_prev else None
            out.append({"code": c, "d": v["d"], "Sn": Sn, "excl": excl, "st": st(Lr) if not excl else None,
                        "stp": st(Lp) if excl else None, "m": m,
                        "lay": (k, p2_b(p2), pop_b(v["pop"]), gap_b(g))})
    return out, why


def phase(d, dates):
    s = next_sw(d, dates)
    if s is None:
        return None, None
    dd = (s - d).days
    if T_WIN[0] <= dd <= T_WIN[1]:
        return "的", s
    if C_WIN[0] <= dd <= C_WIN[1]:
        return "対照", s
    return None, s


# ---------------------------------------------------------------- 差・bootstrap
class Cmp:
    """層でそろえた(的 − 対照)。T・C= [(horse_idx, layer, y, year)]"""

    def __init__(self, T, C):
        self.T, self.C = T, C
        cT, cC = Counter(x[1] for x in T), Counter(x[1] for x in C)
        self.ok = {l for l in cT if cC.get(l, 0) >= MIN_CTRL}
        lays = sorted(self.ok)
        li = {l: i for i, l in enumerate(lays)}
        self.nl = len(lays)
        Tk = [x for x in T if x[1] in self.ok]
        Ck = [x for x in C if x[1] in self.ok]
        self.nT, self.nC = len(Tk), len(Ck)
        self.hT = np.array([x[0] for x in Tk], dtype=np.int64)
        self.hC = np.array([x[0] for x in Ck], dtype=np.int64)
        self.lT = np.array([li[x[1]] for x in Tk], dtype=np.int64)
        self.lC = np.array([li[x[1]] for x in Ck], dtype=np.int64)
        self.yT = np.array([x[2] for x in Tk], dtype=float)
        self.yC = np.array([x[2] for x in Ck], dtype=float)
        self.yrT = np.array([x[3] for x in Tk])
        self.yrC = np.array([x[3] for x in Ck])

    def val(self, w=None, yr=None):
        if self.nl == 0:
            return None
        wT = np.ones(self.nT) if w is None else w[self.hT].astype(float)
        wC = np.ones(self.nC) if w is None else w[self.hC].astype(float)
        if yr is not None:
            wT = wT * (self.yrT == yr)
            wC = wC * (self.yrC == yr)
        nT = np.bincount(self.lT, weights=wT, minlength=self.nl)
        nC = np.bincount(self.lC, weights=wC, minlength=self.nl)
        sT = np.bincount(self.lT, weights=wT * self.yT, minlength=self.nl)
        sC = np.bincount(self.lC, weights=wC * self.yC, minlength=self.nl)
        g = (nT > 0) & (nC > 0)
        if not g.any():
            return None
        d = sT[g] / nT[g] - sC[g] / nC[g]
        return float((d * nT[g]).sum() / nT[g].sum())


def boot_draws(nh):
    return [np.bincount(RNG.integers(0, nh, nh), minlength=nh) for _ in range(BOOT)]


def ci(vals):
    v = [x for x in vals if x is not None]
    if len(v) < BOOT * 0.9:
        return None
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def fmt(x, sc, nd=1):
    if x is None:
        return "-"
    return ("%+." + str(nd) + "f") % (x * sc)


def fmt_ci(c, sc, nd=1):
    if c is None:
        return "-"
    return "[%s, %s]" % (fmt(c[0], sc, nd), fmt(c[1], sc, nd))


# ---------------------------------------------------------------- 本体
def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not (base and key):
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    runs, races, pays, pts, hist = fetch(base, key)
    R, code_of, birth, H, pay, race = prep(runs, races, pays, pts, hist)
    exp = build_exp(R)
    L = []                                  # 結果の行

    # 見込みの確かめ
    allr = [resid(v, exp) for v in R if D_FROM <= v["d"] <= D_TO]
    allr = [m for m in allr if m]
    L.append("# 南関4場 降級前のヤラズ(入着を避けて降級を狙う走り)の痕跡")
    L.append("")
    L.append("- 台本 cloud/yarazu_nankan.py・便 yarazu-nankan.yml(手動 1 回)。出どころ nar_runs / nar_races / nar_race_payouts / "
             "nar_nankan_points / nar_nankan_point_hist(読むだけ)・%s〜%s" % (D_FROM, D_TO))
    L.append("- 作成 %s UTC(GitHub Actions)・馬名・騎手・調教師・馬主は出さない" % dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    L.append("- 決まり= 公式 Q&A(線= nankan_demotion.py KAMI/SHIMO)。入着= 1〜5 着= 着内ポイント表(公式 Q&A の表・"
             "主催者の結果ページの値を優先)で決めた")
    L.append("")
    L.append("## 0. 見込みの確かめ(全走の 実際 − 見込み の平均)")
    L.append("")
    L.append("| 指標 | 走 | 平均 |")
    L.append("|---|---|---|")
    for k, lb, sc in MET:
        xs = [m[k] for m in allr if m.get(k) is not None]
        L.append("| %s | %d | %s |" % (lb, len(xs), fmt(float(np.mean(xs)) if xs else None, sc, 3)))
    L.append("")

    # ① 組み立て直し
    rb, why1 = rebuild(R, code_of, birth, H)
    L.append("## 1. 組み立て直し(切替前の点で「下がる」予測 と 実際に下がった馬)")
    L.append("")
    L.append("一致率= min(予測のうち当たり, 実際のうち拾えた)。80% 未満の回は以後から外す。")
    L.append("")
    L.append("| 切替 | 場 | 馬 | 予測 下がる | 実際 下がった | 両方 | 予測の当たり | 実際の拾い | 一致率 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    valid = []
    for S in SWITCHES:
        for tr in TRACKS + ("計",):
            g = [r for r in rb if r["S"] == S and (tr == "計" or r["tr"] == tr)]
            P = sum(r["pred"] for r in g)
            A = sum(r["down"] for r in g)
            B = sum(r["pred"] and r["down"] for r in g)
            pr = B / P if P else None
            rc = B / A if A else None
            mr = min(pr, rc) if (pr is not None and rc is not None) else None
            L.append("| %s | %s | %d | %d | %d | %d | %s | %s | %s |" % (
                S, tr, len(g), P, A, B, "-" if pr is None else "%.1f%%" % (pr * 100),
                "-" if rc is None else "%.1f%%" % (rc * 100), "-" if mr is None else "%.1f%%" % (mr * 100)))
            if tr == "計" and mr is not None and mr >= 0.80:
                valid.append(S)
    L.append("")
    L.append("使う回: %s" % ("・".join(str(s) for s in valid) or "なし"))
    L.append("")
    L.append("除いた数: " + "・".join("%s %d" % kv for kv in why1.most_common()))
    L.append("")
    log("使う回 %s" % valid)

    # ② 区分
    C, why2 = classify(R, code_of, birth, H, exp)
    hidx = {c: i for i, c in enumerate(sorted({x["code"] for x in C}))}
    nh = len(hidx)
    draws = boot_draws(nh)
    vs = sorted(valid)

    def rows_for(stkey, stval, dates, excl, real_ok):
        T, Cc = [], []
        for x in C:
            if x["excl"] != excl or x[stkey] != stval:
                continue
            if real_ok and x["Sn"] not in vs:
                continue
            ph, s = phase(x["d"], dates)
            if ph is None:
                continue
            yield ph, x, s

    def build_cmp(stkey, stval, dates, excl, met, real_ok=True):
        T, Cc = [], []
        for ph, x, s in rows_for(stkey, stval, dates, excl, real_ok):
            y = x["m"].get(met)
            if y is None:
                continue
            t = (hidx[x["code"]], x["lay"], y, s.year)
            (T if ph == "的" else Cc).append(t)
        return Cmp(T, Cc)

    years = sorted({s.year for s in vs})

    def year_dir(cm, sc_sign):
        vals = [cm.val(yr=y) for y in years]
        vals = [v for v in vals if v is not None]
        return "%d/%d" % (sum(1 for v in vals if v * sc_sign > 0), len(vals))

    def one(cm, sc, sign, nd=1):
        v = cm.val()
        b = ci([cm.val(w) for w in draws])
        return v, b, "%d/%d" % (cm.nT, cm.nC), fmt(v, sc, nd), fmt_ci(b, sc, nd), year_dir(cm, sign)

    # 区分の数
    L.append("## 2. 区分の走の数(使う回の次の切替の前)")
    L.append("")
    L.append("| 区分 | 的(1〜45 日前) | 対照(46〜135 日前) |")
    L.append("|---|---|---|")
    for lb, stkey, stval, excl in [("境目", "st", "境目", False), ("深く圏内", "st", "深く圏内", False), ("安全", "st", "安全", False),
                                   ("対象外・見かけの境目", "stp", "境目", True), ("対象外・見かけの安全", "stp", "安全", True)]:
        cnt = Counter(ph for ph, _, _ in rows_for(stkey, stval, vs, excl, True))
        L.append("| %s | %d | %d |" % (lb, cnt.get("的", 0), cnt.get("対照", 0)))
    L.append("")
    L.append("除いた数(走): " + "・".join("%s %d" % kv for kv in why2.most_common()))
    L.append("")

    # ③ 主の比べ・差の差
    SIGN = {"in5": -1, "top3": -1, "fin": 1, "mar": 1}     # ヤラズの向き(入着・3着内は下がる・着順・秒差は増える)
    L.append("## 3. 主の比べ(的 − 対照・層でそろえる)と差の差")
    L.append("")
    L.append("年の向き= 年ごとの差がヤラズの向き(入着・3着内は −、着順・秒差は +)だった年 / 年。")
    L.append("")
    L.append("| 比べ | 指標 | 走(的/対照) | 差 | 95% | 年の向き |")
    L.append("|---|---|---|---|---|---|")
    main_res = {}
    for k, lb, sc in MET:
        nd = 1 if sc == 100 else 3
        cb = build_cmp("st", "境目", vs, False, k)
        cs = build_cmp("st", "安全", vs, False, k)
        cd = build_cmp("st", "深く圏内", vs, False, k)
        for nm, cm in [("境目", cb), ("安全", cs), ("深く圏内", cd)]:
            v, b, n, a1, a2, yd = one(cm, sc, SIGN[k], nd)
            L.append("| %s | %s | %s | %s | %s | %s |" % (nm, lb, n, a1, a2, yd))
            main_res[(nm, k)] = (v, b)
        dv = None if (cb.val() is None or cs.val() is None) else cb.val() - cs.val()
        dd = []
        for w in draws:
            a, c2 = cb.val(w), cs.val(w)
            dd.append(None if (a is None or c2 is None) else a - c2)
        db = ci(dd)
        vals = []
        for y in years:
            a, c2 = cb.val(yr=y), cs.val(yr=y)
            if a is not None and c2 is not None:
                vals.append(a - c2)
        L.append("| 差の差(境目 − 安全) | %s | - | %s | %s | %d/%d |" % (
            lb, fmt(dv, sc, nd), fmt_ci(db, sc, nd), sum(1 for v in vals if v * SIGN[k] > 0), len(vals)))
        main_res[("dd", k)] = (dv, db)
    L.append("")

    # 反証
    L.append("## 4. 反証")
    L.append("")
    L.append("| 反証 | 指標 | 走(的/対照) | 差 | 95% | 年の向き |")
    L.append("|---|---|---|---|---|---|")
    fake = {}
    for k, lb, sc in MET:
        nd = 1 if sc == 100 else 3
        ca = build_cmp("stp", "境目", vs, True, k)
        v, b, n, a1, a2, yd = one(ca, sc, SIGN[k], nd)
        L.append("| a 対象外・見かけの境目 | %s | %s | %s | %s | %s |" % (lb, n, a1, a2, yd))
        fake[("a", k)] = (v, b)
        for sh in (-60, 60):
            fd = sorted(s + dt.timedelta(days=sh) for s in vs)
            cf = build_cmp("st", "境目", fd, False, k, real_ok=False)
            v, b, n, a1, a2, yd = one(cf, sc, SIGN[k], nd)
            L.append("| b 偽の切替 %+d 日・境目 | %s | %s | %s | %s | %s |" % (sh, lb, n, a1, a2, yd))
            fake[("b%+d" % sh, k)] = (v, b)
    # c 同じ馬の中
    for k, lb, sc in MET:
        nd = 1 if sc == 100 else 3
        per = defaultdict(lambda: {"的": [], "対照": []})
        for ph, x, s in rows_for("st", "境目", vs, False, True):
            y = x["m"].get(k)
            if y is not None:
                per[(x["code"], s)][ph].append(y)
        items = [(hidx[c], np.mean(d["的"]) - np.mean(d["対照"]), len(d["的"]), len(d["対照"]))
                 for (c, s), d in per.items() if d["的"] and d["対照"]]
        if items:
            hi = np.array([i[0] for i in items])
            dv = np.array([i[1] for i in items])
            wv = np.array([i[2] for i in items], dtype=float)
            v = float((dv * wv).sum() / wv.sum())
            bs = []
            for w in draws:
                ww = w[hi] * wv
                bs.append(float((dv * ww).sum() / ww.sum()) if ww.sum() > 0 else None)
            b = ci(bs)
            L.append("| c 同じ馬の中(境目の的 − 同じ馬の対照・層なし) | %s | %d/%d(馬×回 %d) | %s | %s | - |" % (
                lb, int(wv.sum()), sum(i[3] for i in items), len(items), fmt(v, sc, nd), fmt_ci(b, sc, nd)))
            fake[("c", k)] = (v, b)
        else:
            L.append("| c 同じ馬の中 | %s | 0 | - | - | - |" % lb)
            fake[("c", k)] = (None, None)
    L.append("")

    # ④ 降級直後
    L.append("## 5. 降級直後(切替後最初の走)")
    L.append("")
    L.append("| 群 | 走 | 3着内率 | 3着内 − 見込み (pt) | 95% | 単勝回収率 | 複勝回収率 |")
    L.append("|---|---|---|---|---|---|---|")
    four = {}
    for nm, f in [("降級した馬", lambda r: r["down"]), ("前と同じ級に残った馬", lambda r: r["same"])]:
        g = [r for r in rb if r["S"] in vs and f(r)]
        ys, hs, top, win, plc, nb = [], [], 0, 0, 0, 0
        for r in g:
            v = r["post"]
            m = resid(v, exp)
            if not m:
                continue
            ys.append(m["top3"])
            hs.append(r["code"])
            top += v["fin"] <= 3
            w, pl = pay.get(v["rk"], ({}, {}))
            if v["rk"] in pay:
                nb += 1
                win += w.get(v["rn"], 0) if v["fin"] == 1 else 0
                plc += pl.get(v["rn"], 0) if v["fin"] <= 3 else 0
        if ys:
            hu = {c: i for i, c in enumerate(sorted(set(hs)))}
            hi = np.array([hu[c] for c in hs])
            ya = np.array(ys)
            bs = []
            for _ in range(BOOT):
                w = np.bincount(RNG.integers(0, len(hu), len(hu)), minlength=len(hu))[hi]
                bs.append(float((ya * w).sum() / w.sum()) if w.sum() else None)
            b = ci(bs)
            mv = float(ya.mean())
            L.append("| %s | %d | %.1f%% | %s | %s | %s | %s |" % (
                nm, len(ys), top / len(ys) * 100, fmt(mv, 100), fmt_ci(b, 100),
                "%.1f%%" % (win / nb) if nb else "-", "%.1f%%" % (plc / nb) if nb else "-"))
            four[nm] = (mv, b, win / nb if nb else None, plc / nb if nb else None, len(ys))
    L.append("")
    L.append("回収率= 払戻(100 円あたり)の合計 ÷ 払戻のあるレースの走の数(%)。")
    L.append("")

    # ⑤ 判定
    def sig(vb, k):
        v, b = vb
        if v is None or b is None:
            return False
        return (b[1] < 0) if SIGN[k] < 0 else (b[0] > 0)
    real = sig(main_res[("境目", "in5")], "in5") or sig(main_res[("境目", "fin")], "fin")
    others = {nm: (sig(fake[(nm, "in5")], "in5") or sig(fake[(nm, "fin")], "fin")) for nm in ("a", "b-60", "b+60")}
    safe = sig(main_res[("安全", "in5")], "in5") or sig(main_res[("安全", "fin")], "fin")
    only = real and not safe and not any(others.values())
    L.append("## 6. 判定")
    L.append("")
    L.append("境目×的の差(入着率か着順でヤラズの向きに 95%% が 0 をまたがない)= %s・安全 %s・対象外 %s・偽の日 −60 %s・+60 %s → %s" % (
        "出た" if real else "出ない", "出た" if safe else "出ない", "出た" if others["a"] else "出ない",
        "出た" if others["b-60"] else "出ない", "出た" if others["b+60"] else "出ない",
        "本物だけに出る= 痕跡あり" if only else ("本物にも出ない= 痕跡は言えない" if not real else "対照の群にも出る= 決まりのせいとは言えない")))
    L.append("")
    L.append("差= 層ごとの(的 − 対照)の「実際 − 見込み」を的の走の数で重み付け。95%% は馬ごとのクラスタ bootstrap %d 回。" % BOOT)
    L.append("層= 級×前2走の着順合計(~6/7-12/13-18/19~/無)×人気(1/2-3/4-6/7~)×前走からの間隔(~14/15-28/29-56/57~/無)。対照 %d 走未満の層は捨てる。" % MIN_CTRL)
    L.append("対象外の見かけの線= 8歳以上は今の線 + 同じ級の 7 歳が同じ切替で受ける線の上げ幅・C3 は同じ切替・馬齢の C2 の線 ÷ 2。線が空欄の欄も対象外。")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
