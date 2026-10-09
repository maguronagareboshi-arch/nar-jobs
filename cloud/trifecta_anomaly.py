# -*- coding: utf-8 -*-
"""研究用・1 回きり: 締め切り間際に「特定の 3連単の組」へ馬単位の動きで説明できない票が入り、その組が当たる形が
偶然以上に起きているかを数える(特定のレースを告発する目的ではない)。
便 .github/workflows/trifecta-anomaly.yml(workflow_dispatch のみ)から走らせ、docs/trifecta-anomaly/result.md を書く。
⛔本番 DB では REST の単純 select だけ(取得は late_money_preclose.py / trifecta_group_return.py と同じ)。書き込みなし。
⛔result.md にレースを特定できる情報(場・日付・R・馬番)を入れない。上位レースは trifecta_anomaly_private.csv(成果物のみ・commit しない)。

3連単(第 2 版・10/10 定義修正):
  F= 確定行(f=true の最大 id)。P= F より前(id<F)で observed_at が F の 2〜15 分前の最後の途中行。
  q= 1/倍率をレース内で合計 1(F・P の両方に倍率があり、3 頭とも単勝 F と単勝 P 時点に倍率がある組で)。
  G1(i)= Σ_{1着=i} qF / Σ_{1着=i} qP(G2・G3 も同様)。
  r2= qF / e2・e2= qP·G1(a)·G2(b)·G3(c3) を全組で合計 1。
  r3= qF / e3・e3= H_F(c)·qP(c)/H_P(c) を全組で合計 1。H= Harville(単勝の正規化確率で 1→2→3 着の積)。
     H_F は単勝の確定行・H_P は P の observed_at 以前で最後の単勝途中行(asof 無ければ t)。
  百分位 u= 比べる相手(qP が当たり組の 1/2〜2 倍の外れ組・20 組未満は除外)の中で (小さい数 + 同値数/2)/相手数。
  偽(i)= 比べる相手から無作為 1 組。偽(ii)= 比べる相手のうち G1·G2·G3 の積も当たり組の 1/1.5〜1.5 倍の組から無作為 1 組。
     偽の百分位は、その組の qP の 1/2〜2 倍の組(当たり組・自身を除く)を相手に同じ計算(20 組未満は除外)。
  P の締め切り前確認= P の observed_at(JST の分)と発走時刻(nar_races.post_time)を比べる。
旧定義(初回の r= g/(G1G2G3)^(1/3))の数字は docs/trifecta-anomaly/old_def.md を末尾に写す。
"""
import csv
import datetime as dt
import io
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import hm, num, rkey, ts, JST, log, rows_offset  # noqa: E402
import json  # noqa: E402
import urllib.parse  # noqa: E402
from late_money_preclose import fetch, get_combos, amin, norm  # noqa: E402
from trifecta_group_return import tri_map, pick3_f  # noqa: E402

D_FROM, D_TO, D_SPLIT = dt.date(2026, 9, 8), dt.date(2026, 9, 30), dt.date(2026, 9, 20)
NANKAN = ("浦和", "船橋", "大井", "川崎")
SEED = 20260908
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(BASE, "docs", "trifecta-anomaly", "result.md")
OLD = os.path.join(BASE, "docs", "trifecta-anomaly", "old_def.md")
PRIV = os.path.join(BASE, "trifecta_anomaly_private.csv")
MS = ("r2", "r3")
KINDS = (("hit", "当たり組"), ("f1", "偽(i) qP が近い"), ("f2", "偽(ii) qP と馬の伸びの積が近い"))


def pick_p(rows, fid):
    fr = [r for r in rows if r["id"] == fid]
    if not fr:
        return None, None, None
    ft = ts(fr[0].get("observed_at"))
    if ft is None:
        return None, None, None
    c = []
    for r in rows:
        if r.get("f") or r["id"] >= fid:
            continue
        t = ts(r.get("observed_at"))
        if t is not None and ft - dt.timedelta(minutes=15) <= t <= ft - dt.timedelta(minutes=2):
            c.append((t, r["id"]))
    if not c:
        return None, None, None
    t, pid = max(c)
    return pid, (ft - t).total_seconds() / 60.0, t


def pct(rc, comp):
    lo = sum(1 for x in comp if x < rc)
    eq = sum(1 for x in comp if x == rc)
    return (lo + 0.5 * eq) / len(comp)


def harville(p, k):
    a, b, c = k
    d1 = 1.0 - p[a]
    d2 = 1.0 - p[a] - p[b]
    if d1 <= 0 or d2 <= 0:
        return 0.0
    return p[a] * p[b] / d1 * p[c] / d2


def race_calc(mp, mf, pwF, pwP, hit, rng):
    keys = sorted(k for k in mf if k in mp and all(h in pwF and h in pwP for h in k))
    if hit not in keys:
        return "x_hit", None
    sp = sum(1.0 / mp[k] for k in keys)
    sf = sum(1.0 / mf[k] for k in keys)
    qp = {k: (1.0 / mp[k]) / sp for k in keys}
    qf = {k: (1.0 / mf[k]) / sf for k in keys}
    G = []
    for j in range(3):
        a, b = {}, {}
        for k in keys:
            a[k[j]] = a.get(k[j], 0.0) + qf[k]
            b[k[j]] = b.get(k[j], 0.0) + qp[k]
        G.append({h: a[h] / b[h] for h in a})
    gp = {k: G[0][k[0]] * G[1][k[1]] * G[2][k[2]] for k in keys}
    e2 = {k: qp[k] * gp[k] for k in keys}
    z2 = sum(e2.values())
    e3 = {}
    for k in keys:
        hp = harville(pwP, k)
        e3[k] = harville(pwF, k) * qp[k] / hp if hp > 0 else 0.0
    z3 = sum(e3.values())
    if z2 <= 0 or z3 <= 0:
        return "x_hit", None
    R = {"r2": {k: qf[k] / (e2[k] / z2) for k in keys},
         "r3": {k: (qf[k] / (e3[k] / z3)) if e3[k] > 0 else float("inf") for k in keys}}
    qh = qp[hit]
    comp = [k for k in keys if k != hit and qh / 2 <= qp[k] <= qh * 2]
    if len(comp) < 20:
        return "x_comp", None
    out = {"qp": qh, "rank": 1 + sum(1 for k in keys if qp[k] > qh), "ncomp": len(comp), "g": qf[hit] / qh}
    out.update(spread(keys, qf, {k: e2[k] / z2 for k in keys}, R["r2"], hit))
    for m in MS:
        out["hit_u_" + m] = pct(R[m][hit], [R[m][k] for k in comp])
        out["hit_r_" + m] = R[m][hit]
    f1 = rng.choice(comp)
    c2 = [k for k in comp if gp[hit] / 1.5 <= gp[k] <= gp[hit] * 1.5]
    f2 = rng.choice(c2) if c2 else None
    for nm, fk in (("f1", f1), ("f2", f2)):
        out[nm + "_rank"] = None
        for m in MS:
            out["%s_u_%s" % (nm, m)] = None
            out["%s_r_%s" % (nm, m)] = None
        if fk is None:
            continue
        qz = qp[fk]
        fc = [k for k in keys if k not in (hit, fk) and qz / 2 <= qp[k] <= qz * 2]
        if len(fc) < 20:
            continue
        out[nm + "_rank"] = 1 + sum(1 for k in keys if qp[k] > qz)
        for m in MS:
            out["%s_u_%s" % (nm, m)] = pct(R[m][fk], [R[m][k] for k in fc])
            out["%s_r_%s" % (nm, m)] = R[m][fk]
    out["f2_none"] = f2 is None
    d3 = {k: qf[k] - e3[k] / z3 for k in keys}
    out["hit_d3"] = d3[hit]
    out["hit_d3_rank"] = 1 + sum(1 for k in keys if d3[k] > d3[hit])
    out["max_d3_other"] = max(d3[k] for k in keys if k != hit)
    out["f2_d3"] = d3[f2] if f2 is not None else None
    out["f2_max_other"] = max(d3[k] for k in keys if k != f2) if f2 is not None else None
    return "ok", out


GROUPS = (("超過の上位 1 組", 0, 1), ("上位 2〜5 組", 1, 5), ("上位 6〜20 組", 5, 20))


def spread(keys, qf, e, r2, hit):
    """広く撒く買いか一点集中か(r2 の期待 e= 合計 1)。"""
    ex = {k: qf[k] - e[k] for k in keys}
    order = sorted(keys, key=lambda k: (-ex[k], k))
    pos = [k for k in order if ex[k] > 0]
    tot = sum(ex[k] for k in pos)
    out = {"k": sum(1 for k in keys if r2[k] >= 2),
           "delta": sum(max(ex[k], 0.0) for k in keys if r2[k] >= 2),
           "h1": ex[pos[0]] / tot if tot > 0 else 0.0,
           "h3": sum(ex[k] for k in pos[:3]) / tot if tot > 0 else 0.0,
           "n1": len(set(k[0] for k in pos)), "n2": len(set(k[1] for k in pos)),
           "ex_rank": 1 + order.index(hit)}
    for i, (_, a, b) in enumerate(GROUPS):
        g = order[a:b]
        out["grp%d_hit" % i] = 1 if hit in g else 0
        out["grp%d_exp" % i] = sum(qf[k] for k in g)
    return out


def quart(xs):
    s = sorted(xs)
    if not s:
        return "-"
    q = lambda p: s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]  # noqa: E731
    fmt = (lambda x: "%g" % x) if all(float(x).is_integer() for x in s) else (lambda x: "%.3f" % x)
    return "%s (%s〜%s)" % (fmt(median(s)), fmt(q(0.25)), fmt(q(0.75)))


def spread_section(res):
    top = [v for v in res if v["hit_u_r2"] >= 0.95]
    oth = [v for v in res if v["hit_u_r2"] < 0.95]
    L = ["", "## 広く撒く買いか一点集中か(r2 の期待で・追加検証)", "",
         "上位 5%%= 当たり組の r2 百分位が 0.95 以上のレース(%d)。それ以外 %d。超過= qF − 期待(正の分)。" % (len(top), len(oth)), "",
         "### (1) 広さと一点度(中央値・四分位)", "",
         "| 指標 | 上位 5% のレース | それ以外 |", "|---|---:|---:|"]
    for lab, f in (("k= r2≥2 の組の数", "k"), ("Δ= r2≥2 の組の超過の合計", "delta"),
                   ("h= 超過のうち上位 1 組の割合", "h1"), ("h= 超過のうち上位 3 組の割合", "h3"),
                   ("超過のある組の 1 着馬の数", "n1"), ("超過のある組の 2 着馬の数", "n2")):
        L.append("| %s | %s | %s |" % (lab, quart([v[f] for v in top]), quart([v[f] for v in oth])))
    a = sum(1 for v in top if v["h1"] >= 0.5)
    b = sum(1 for v in oth if v["h1"] >= 0.5)
    L += ["", "### (2) h(上位 1 組)≥0.5 のレース", "",
          "| 区分 | 件数 | 割合 |", "|---|---:|---:|",
          "| 上位 5%% のレース | %d / %d | %.1f%% |" % (a, len(top), a / len(top) * 100 if top else 0),
          "| それ以外 | %d / %d | %.1f%% |" % (b, len(oth), b / len(oth) * 100 if oth else 0), "",
          "### (3) 上位 5% のレースで当たり組は超過の何番目か", "", "| 順位 | 件数 |", "|---|---:|"]
    for lab, lo, hi in (("1 番目", 1, 1), ("2〜5 番目", 2, 5), ("6〜20 番目", 6, 20), ("21 番目以降", 21, 10 ** 9)):
        L.append("| %s | %d |" % (lab, sum(1 for v in top if lo <= v["ex_rank"] <= hi)))
    L += ["", "### (4) 全レース: 超過の上位の組が当たった数と見込み(確定 qF の和)", "",
          "| 組 | レース数 | 当たり | 見込み | 実際÷見込み |", "|---|---:|---:|---:|---:|"]
    for i, (lab, _, _) in enumerate(GROUPS):
        h = sum(v["grp%d_hit" % i] for v in res)
        e = sum(v["grp%d_exp" % i] for v in res)
        L.append("| %s | %d | %d | %.1f | %s |" % (lab, len(res), h, e, ("%.2f" % (h / e)) if e else "-"))
    L += ["", "### (5) 時刻の偏り(上位 5% のレースと全体)", "", "| 区分 | 上位 5% | 全体 |", "|---|---:|---:|"]

    def cnt(lab, f):
        x = sum(1 for v in top if f(v))
        y = sum(1 for v in res if f(v))
        return "| %s | %d (%.1f%%) | %d (%.1f%%) |" % (lab, x, x / len(top) * 100 if top else 0, y, y / len(res) * 100 if res else 0)
    for i, w in enumerate("月火水木金土日"):
        L.append(cnt(w + "曜", lambda v, i=i: v["wday"] == i))
    L.append(cnt("最終 R", lambda v: v["last"]))
    L.append(cnt("それ以外の R", lambda v: not v["last"]))
    L.append(cnt("南関 4 場", lambda v: v["nankan"]))
    L.append(cnt("それ以外の場", lambda v: not v["nankan"]))
    return L


DWB_FROM = dt.date(2026, 9, 2)
X_MIN = 50000


def caseb(wins, fin_of, post_t, sales, WB):
    """案 B(単勝)を初回と同じ定義で数え直し、売上を付けて WB に積む。"""
    for rk_, rows in sorted(wins.items()):
        fins = [r for r in rows if r.get("f")]
        if not fins or rk_ not in fin_of:
            continue
        fin = max(fins, key=lambda r: r["id"])
        fm, pm = hm(fin.get("t")), post_t.get(rk_)
        if fm is None or pm is None or abs(fm - pm) > 10:
            continue
        fw = fin.get("w") or {}
        fo = fin_of[rk_]
        vs = [r for r in rows if not r.get("f") and amin(r) is not None and amin(r) <= fm - 2]
        if not vs:
            continue
        V = max(vs, key=lambda r: (amin(r), r["id"]))
        vw = V.get("w") or {}
        hs = [h for h in fw if num(fw[h]) and num(vw.get(h))]
        if not hs:
            continue
        pf, pv = norm(fw, hs), norm(vw, hs)
        fav = min(hs, key=lambda h: (num(vw[h]), h))
        if fav not in fo:
            continue
        WB.append({"ratio": pf[fav] / pv[fav], "won": 1 if fo[fav] == 1 else 0, "pf": pf[fav], "sales": sales.get(rk_)})


def xyen(sales, d3):
    return sales * d3 * 100.0


def cand(sales, d3, mx):
    return bool(sales) and d3 is not None and d3 > mx and xyen(sales, d3) >= X_MIN


def qv(s, p):
    s = sorted(s)
    return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))] if s else float("nan")


def sales_section(res, WB):
    rs = [v for v in res if v["sales"]]
    ss = sorted(v["sales"] for v in rs)
    cuts = (qv(ss, 0.25), qv(ss, 0.5), qv(ss, 0.75))

    def qi(x):
        return sum(1 for c in cuts if x > c)
    Q = [[v for v in rs if qi(v["sales"]) == i] for i in range(4)]
    names = ("第 1 区(少)", "第 2 区", "第 3 区", "第 4 区(多)")
    L = ["", "## 売上(3連単の票数)で分ける(追加検証)", "",
         "- 売上のあるレース %d・売上なしで除外 %d。区切り(票数)%.0f / %.0f / %.0f"
         % (len(rs), len(res) - len(rs), cuts[0], cuts[1], cuts[2]), "",
         "### (1) 売上の 4 分位ごとの集中(r2 の百分位)", "",
         "| 区 | レース数 | 票数の範囲 | 当たり 上位5% (期待) | 当たり 上位1% (期待) | 偽(ii) 上位5% (期待) | 偽(ii) 上位1% (期待) | h1 中央値 | k 中央値 | h1≥0.5 |",
         "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for i, g in enumerate(Q):
        hu = [v["hit_u_r2"] for v in g]
        fu = [v["f2_u_r2"] for v in g if v["f2_u_r2"] is not None]
        L.append("| %s | %d | %s | %d (%.1f) | %d (%.1f) | %d (%.1f) | %d (%.1f) | %.3f | %g | %d |" % (
            names[i], len(g), ("%.0f〜%.0f" % (min(v["sales"] for v in g), max(v["sales"] for v in g))) if g else "-",
            sum(1 for x in hu if x >= 0.95), len(hu) * 0.05, sum(1 for x in hu if x >= 0.99), len(hu) * 0.01,
            sum(1 for x in fu if x >= 0.95), len(fu) * 0.05, sum(1 for x in fu if x >= 0.99), len(fu) * 0.01,
            median([v["h1"] for v in g]), median([v["k"] for v in g]), sum(1 for v in g if v["h1"] >= 0.5)))
    L += ["", "### 場ごとの売上(3連単の票数)の中央値", "", "| 場 | レース数 | 中央値 |", "|---|---:|---:|"]
    tr = {}
    for v in rs:
        tr.setdefault(v["track"], []).append(v["sales"])
    for t in sorted(tr, key=lambda t: -median(tr[t])):
        L.append("| %s | %d | %.0f |" % (t, len(tr[t]), median(tr[t])))
    L += ["", "### (2) 金額で見る超過額 X= (確定の票数 − r3 の期待の票数)×100 円", "",
          "| 区 | 当たり X 中央値 | 90% | 99% | 最大 | 当たりが超過 1 番目 | 当たりの超過順位 中央値 | 偽(ii) 件数 | 偽(ii) X 中央値 | 90% | 99% | 最大 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for i, g in enumerate(Q):
        hx = [xyen(v["sales"], v["hit_d3"]) for v in g]
        fx = [xyen(v["sales"], v["f2_d3"]) for v in g if v["f2_d3"] is not None]
        L.append("| %s | %.0f | %.0f | %.0f | %.0f | %d | %g | %d | %.0f | %.0f | %.0f | %.0f |" % (
            names[i], median(hx), qv(hx, 0.9), qv(hx, 0.99), max(hx) if hx else float("nan"),
            sum(1 for v in g if v["hit_d3_rank"] == 1), median([v["hit_d3_rank"] for v in g]),
            len(fx), median(fx), qv(fx, 0.9), qv(fx, 0.99), max(fx) if fx else float("nan")))
    L += ["", "### (3) 一点買いの候補(その組の X が同じレースの他の組の X の最大を上回り、かつ X≥5 万円)", "",
          "| 区 | 当たり組が候補 | レース数 | 偽(ii) が候補 | 偽(ii) のレース数 |", "|---|---:|---:|---:|---:|"]
    for i, g in enumerate(Q):
        g2 = [v for v in g if v["f2_d3"] is not None]
        L.append("| %s | %d | %d | %d | %d |" % (
            names[i], sum(1 for v in g if cand(v["sales"], v["hit_d3"], v["max_d3_other"])), len(g),
            sum(1 for v in g2 if cand(v["sales"], v["f2_d3"], v["f2_max_other"])), len(g2)))
    ws = [w for w in WB if w["sales"]]
    med = median([w["sales"] for w in ws])
    lo = [w for w in WB if w["ratio"] <= 0.8]
    L += ["", "### (4) 案 B: 1 番人気が最後に 2 割以上売れなくなった(pF/pV≤0.8)レースを売上で分ける", "",
          "- 案 B の対象 %d レース・pF/pV≤0.8 は %d。区切り= 売上のある案 B 対象レース全体の 3連単票数の中央値 %.0f。売上なし %d"
          % (len(WB), len(lo), med, sum(1 for w in lo if not w["sales"])), "",
          "| 売上 | レース数 | 1着数 | 見込み | 実際÷見込み |", "|---|---:|---:|---:|---:|"]
    for lab, f in (("下半分", lambda w: w["sales"] and w["sales"] <= med),
                   ("上半分", lambda w: w["sales"] and w["sales"] > med)):
        g = [w for w in lo if f(w)]
        e = sum(w["pf"] for w in g)
        wn = sum(w["won"] for w in g)
        L.append("| %s | %d | %d | %.1f | %s |" % (lab, len(g), wn, e, ("%.2f" % (wn / e)) if e else "-"))
    return L


def ks_p(us):
    n = len(us)
    if n == 0:
        return float("nan"), float("nan")
    s = sorted(us)
    d = max(max((i + 1) / n - x, x - i / n) for i, x in enumerate(s))
    lam = (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n)) * d
    if lam < 0.2:
        return d, 1.0
    p = 2 * sum((-1) ** (k - 1) * math.exp(-2 * k * k * lam * lam) for k in range(1, 101))
    return d, min(max(p, 0.0), 1.0)


def median(xs):
    s = sorted(x for x in xs if x is not None)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def win_probs(row):
    w = (row or {}).get("w") or {}
    hs = [h for h in w if num(w[h])]
    return norm(w, hs) if hs else {}


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    rng = random.Random(SEED)
    res = []
    ex = {"races": 0, "x_fin": 0, "x_nof": 0, "x_nop": 0, "x_win": 0, "x_hit": 0, "x_comp": 0,
          "x_f1": 0, "x_f2none": 0, "x_f2": 0}
    WB = []
    d = DWB_FROM
    while d <= D_TO:
        day = d.isoformat()
        races, runs, win, full = fetch(base, key, day, d >= D_FROM)
        sales = {}
        for r in rows_offset(base, key, "/rest/v1/nar_race_votes?select=track,race_date,race_no,votes"
                             "&race_date=eq.%s&order=track.asc,race_no.asc" % urllib.parse.quote(day)):
            vv = r.get("votes")
            if isinstance(vv, str):
                try:
                    vv = json.loads(vv)
                except ValueError:
                    vv = None
            t3 = num(vv.get("trifecta")) if isinstance(vv, dict) else None
            if t3 and t3 > 0:
                sales[rkey(r)] = t3
        post_t = {rkey(r): hm(r.get("post_time")) for r in races}
        last_r = {}
        for r in races:
            last_r[r["track"]] = max(last_r.get(r["track"], 0), int(r["race_no"]))
        fin_of = {}
        for r in runs:
            try:
                fin_of.setdefault(rkey(r), {})[str(r["runner_number"])] = int(str(r.get("finish")).strip())
            except (TypeError, ValueError):
                continue
        wins, f3 = {}, {}
        for r in win:
            wins.setdefault(rkey(r), []).append(r)
        for r in full:
            f3.setdefault(rkey(r), []).append(r)
        caseb(wins, fin_of, post_t, sales, WB)
        todo = []
        for rk_, rows in sorted(f3.items()):
            if rk_ not in fin_of:
                continue
            ex["races"] += 1
            pos = {}
            for h, f in fin_of[rk_].items():
                pos.setdefault(f, []).append(h)
            if any(len(pos.get(k, [])) != 1 for k in (1, 2, 3)):
                ex["x_fin"] += 1
                continue
            fid = pick3_f(rows)
            if fid is None:
                ex["x_nof"] += 1
                continue
            pid, mins, pt = pick_p(rows, fid)
            if pid is None:
                ex["x_nop"] += 1
                continue
            wr = wins.get(rk_, [])
            wf = [r for r in wr if r.get("f")]
            pj = pt.astimezone(JST)
            pmin = pj.hour * 60 + pj.minute
            wp = [r for r in wr if not r.get("f") and amin(r) is not None and amin(r) <= pmin]
            if not wf or not wp:
                ex["x_win"] += 1
                continue
            pwF = win_probs(max(wf, key=lambda r: r["id"]))
            pwP = win_probs(max(wp, key=lambda r: (amin(r), r["id"])))
            if not pwF or not pwP:
                ex["x_win"] += 1
                continue
            pm = post_t.get(rk_)
            pre = None if pm is None else (pmin < pm)
            todo.append((rk_, fid, pid, mins, (pos[1][0], pos[2][0], pos[3][0]), pwF, pwP, pre))
        cache = {}
        get_combos(base, key, [t[1] for t in todo] + [t[2] for t in todo], cache)
        n0 = len(res)
        for rk_, fid, pid, mins, hit, pwF, pwP, pre in todo:
            if fid not in cache or pid not in cache:
                ex["x_nop"] += 1
                continue
            st, v = race_calc(tri_map(cache[pid]), tri_map(cache[fid]), pwF, pwP, hit, rng)
            if st != "ok":
                ex[st] += 1
                continue
            if v["f1_u_r2"] is None:
                ex["x_f1"] += 1
            if v["f2_none"]:
                ex["x_f2none"] += 1
            elif v["f2_u_r2"] is None:
                ex["x_f2"] += 1
            v.update({"track": rk_[0], "date": str(rk_[1]), "race_no": rk_[2], "hit": "-".join(hit),
                      "nankan": rk_[0] in NANKAN, "first": d < D_SPLIT, "lead": mins, "pre": pre,
                      "wday": d.weekday(), "last": rk_[2] == last_r.get(rk_[0]),
                      "sales": sales.get(rk_)})
            res.append(v)
        log("%s 3連単 %d 行・使えた %d レース" % (day, len(full), len(res) - n0))
        d += dt.timedelta(days=1)
    write(res, ex, WB)
    private(res)


def us_of(res, kind, m, cond=None):
    out = []
    for v in res:
        if cond and not cond(v):
            continue
        u = v["%s_u_%s" % (kind, m)]
        if u is not None:
            out.append(u)
    return out


def rank_of(v, kind):
    return v["rank"] if kind == "hit" else v[kind + "_rank"]


def dec_table(res, m):
    cols = [us_of(res, k, m) for k, _ in KINDS]
    L = ["| 百分位 | " + " | ".join(lab for _, lab in KINDS) + " |", "|---|---:|---:|---:|"]
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        cells = []
        for us in cols:
            a = sum(1 for x in us if lo <= x < hi or (i == 9 and x >= 1.0))
            cells.append("%d (%.1f%%)" % (a, a / len(us) * 100 if us else 0))
        L.append("| %.1f〜%.1f | %s |" % (lo, hi, " | ".join(cells)))
    return L


def top_row(lab, us):
    n = len(us)
    t1 = sum(1 for x in us if x >= 0.99)
    t5 = sum(1 for x in us if x >= 0.95)
    dd, p = ks_p(us)
    return "| %s | %d | %d | %.1f | %d | %.1f | %.3f | %.3g |" % (lab, n, t1, n * 0.01, t5, n * 0.05, dd, p)


TOPH = ["| 区分 | 件数 | 上位1% | 期待 | 上位5% | 期待 | KS の D | KS の p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
T5H = ["| 区分 | 当たり 件数 | 当たり 上位5% | 期待 | 偽(i) 件数 | 偽(i) 上位5% | 期待 | 偽(ii) 件数 | 偽(ii) 上位5% | 期待 |",
       "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]


def t5_row(lab, res, cond):
    cells = []
    for k, _ in KINDS:
        us = [v["%s_u_r2" % k] for v in res if v["%s_u_r2" % k] is not None and cond(v, k)]
        n = len(us)
        cells.append("%d | %d | %.1f" % (n, sum(1 for x in us if x >= 0.95), n * 0.05))
    return "| %s | %s |" % (lab, " | ".join(cells))


def write(res, ex, WB):
    npre = sum(1 for v in res if v["pre"] is True)
    npost = sum(1 for v in res if v["pre"] is False)
    nunk = sum(1 for v in res if v["pre"] is None)
    L = ["# 締め切り間際の 3連単の組への集中と的中(研究・1 回きり・第 2 版= 定義修正)", "",
         "期間 %s〜%s(3連単)。作成 %s。レースを特定できる情報は載せない。案 B(単勝)は旧定義の節を見る(再計算なし)。"
         % (D_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "## 対象(新定義)", "",
         "- 3連単の行があり着順のあるレース %d・使えた %d" % (ex["races"], len(res)),
         "- 除外: 1〜3 着が 1 頭ずつでない %d・確定行なし %d・P なし %d・単勝の確定行か P 時点の単勝行なし %d・"
         "当たり組が使える組に無い %d・比べる相手 20 組未満 %d"
         % (ex["x_fin"], ex["x_nof"], ex["x_nop"], ex["x_win"], ex["x_hit"], ex["x_comp"]),
         "- 偽(i) 除外(自身の相手 20 組未満)%d・偽(ii) 候補なし %d・偽(ii) 自身の相手 20 組未満 %d"
         % (ex["x_f1"], ex["x_f2none"], ex["x_f2"]),
         "- P が F の何分前か: 中央値 %.1f 分" % median([v["lead"] for v in res]),
         "- P の observed_at が発走時刻より前 %d・発走時刻以後 %d・発走時刻不明 %d" % (npre, npost, nunk), ""]
    for m, title in (("r2", "r2= qF ÷ 馬単位の伸びの積で作った期待(合計 1)"),
                     ("r3", "r3= qF ÷ 単勝確定の Harville × P 時点の組の個性(合計 1)")):
        L += ["## %s" % title, "", "### 百分位の 10 区分(一様なら各 10%)", ""] + dec_table(res, m)
        L += ["", "### 上位に入った件数と一様性の検定", ""] + TOPH
        for k, lab in KINDS:
            L.append(top_row(lab, us_of(res, k, m)))
        L += ["", "- %s の中央値: 当たり組 %.3f・偽(i) %.3f・偽(ii) %.3f"
              % (m, median([v["hit_r_" + m] for v in res]), median([v["f1_r_" + m] for v in res if v["f1_u_r2"] is not None]),
                 median([v["f2_r_" + m] for v in res if v["f2_u_r2"] is not None])), "",
              "### P が発走時刻より前のレースだけ", ""] + TOPH
        for k, lab in KINDS:
            L.append(top_row(lab, us_of(res, k, m, lambda v: v["pre"] is True)))
        L.append("")
    L += ["- 組の伸び g(=qF/qP)の中央値: 当たり組 %.3f" % median([v["g"] for v in res]), "",
          "## r2 の上位 5%(区分別)", "", "### 人気帯(P での人気順位)", ""] + T5H
    for lab, lo, hi in (("1〜10 番人気", 1, 10), ("11〜50 番人気", 11, 50), ("51 番人気以下", 51, 10 ** 9)):
        L.append(t5_row(lab, res, lambda v, k, lo=lo, hi=hi: rank_of(v, k) is not None and lo <= rank_of(v, k) <= hi))
    L += ["", "### 南関 4 場/それ以外", ""] + T5H
    L.append(t5_row("南関 4 場", res, lambda v, k: v["nankan"]))
    L.append(t5_row("それ以外", res, lambda v, k: not v["nankan"]))
    L += ["", "### 前半/後半", ""] + T5H
    L.append(t5_row("前半 9/8〜9/19", res, lambda v, k: v["first"]))
    L.append(t5_row("後半 9/20〜9/30", res, lambda v, k: not v["first"]))
    L += spread_section(res)
    L += sales_section(res, WB)
    L += ["", "> 百分位= 当たり組の値が、P での売れ方が近い(1/2〜2 倍)外れ組の中でどこにいるか(0〜1・1 に近いほど上)。"
          "偽= 同じレースの外れ組を無作為に選んで同じ計算(比べ物)。1 か月弱なので結論にしない。", ""]
    if os.path.exists(OLD):
        with io.open(OLD, encoding="utf-8") as f:
            old = f.read().splitlines()
        L += ["---", "", "# 旧定義(初回 2026-10-10・r= g÷(G1·G2·G3)^(1/3)・当たり組の r が上がりやすい偏りあり)", ""]
        L += [("#" + x) if x.startswith("#") else x for x in old[1:]]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))


def private(res):
    top = sorted(res, key=lambda v: (-v["hit_u_r2"], -v["hit_r_r2"]))[:200]
    with io.open(PRIV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["track", "date", "race_no", "hit", "u_r2", "r2", "u_r3", "r3", "g", "qP", "rank", "ncomp",
                    "lead_min", "p_before_post", "k_r2ge2", "delta", "h1", "h3", "hit_ex_rank", "sales_votes", "X_yen", "one_point_cand"])
        for v in top:
            w.writerow([v["track"], v["date"], v["race_no"], v["hit"], "%.4f" % v["hit_u_r2"], "%.4f" % v["hit_r_r2"],
                        "%.4f" % v["hit_u_r3"], "%.4f" % v["hit_r_r3"], "%.4f" % v["g"], "%.6f" % v["qp"],
                        v["rank"], v["ncomp"], "%.1f" % v["lead"], v["pre"], v["k"], "%.4f" % v["delta"],
                        "%.4f" % v["h1"], "%.4f" % v["h3"], v["ex_rank"], v["sales"] if v["sales"] else "",
                        ("%.0f" % xyen(v["sales"], v["hit_d3"])) if v["sales"] else "",
                        1 if cand(v["sales"], v["hit_d3"], v["max_d3_other"]) else 0])


if __name__ == "__main__":
    main()
