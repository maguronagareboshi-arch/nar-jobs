# -*- coding: utf-8 -*-
"""研究用・1 回きり: 締め切り間際に「特定の 3連単の組」へ馬単位の動きで説明できない票が入り、その組が当たる形が
偶然以上に起きているかを数える(特定のレースを告発する目的ではない)。
便 .github/workflows/trifecta-anomaly.yml(workflow_dispatch のみ)から走らせ、docs/trifecta-anomaly/result.md を書く。
⛔本番 DB では REST の単純 select だけ(取得は late_money_preclose.py / trifecta_group_return.py と同じ)。書き込みなし。
⛔result.md にレースを特定できる情報(場・日付・R・馬番)を入れない。上位レースは trifecta_anomaly_private.csv(成果物のみ・commit しない)。

3連単:
  F= 確定行(f=true の最大 id)。P= F より前(id<F)で observed_at が F の 2〜15 分前の最後の途中行。
  q= 1/倍率をレース内で合計 1(F と P の両方に倍率がある組で)。g(c)= qF/qP。
  G1(i)= Σ_{1着=i} qF / Σ_{1着=i} qP(G2・G3 も同様)。r(c)= g(c) / (G1(a)G2(b)G3(c3))^(1/3)。
  当たり組の百分位 u= 比べる相手(qP が当たり組の 1/2〜2 倍の外れ組)の中で (r が小さい数 + 同値数/2)/相手数。相手 20 組未満は除外。
  偽の当たり= 比べる相手から 1 組を無作為(乱数種固定)・その組の相手(qP 1/2〜2 倍・当たり組と自身を除く)で同じ u。
案 B(単勝): V= asof(無ければ t)が確定の 2 分前以下の最後の途中行。1 番人気= V の倍率最小。pF/pV(正規化)で区分。
"""
import csv
import datetime as dt
import io
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import hm, num, rkey, ts, JST, log  # noqa: E402
from late_money_preclose import fetch, get_combos, amin, norm  # noqa: E402
from trifecta_group_return import tri_map, pick3_f  # noqa: E402

D_FROM, D_TO, D_SPLIT, DW_FROM = dt.date(2026, 9, 8), dt.date(2026, 9, 30), dt.date(2026, 9, 20), dt.date(2026, 9, 2)
NANKAN = ("浦和", "船橋", "大井", "川崎")
SEED = 20260908
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(BASE, "docs", "trifecta-anomaly", "result.md")
PRIV = os.path.join(BASE, "trifecta_anomaly_private.csv")
WLABS = ("0.8 以下", "0.8〜0.95", "0.95〜1.05", "1.05 以上")


def wbin(x):
    if x <= 0.8:
        return WLABS[0]
    if x <= 0.95:
        return WLABS[1]
    if x < 1.05:
        return WLABS[2]
    return WLABS[3]


def pick_p(rows, fid):
    fr = [r for r in rows if r["id"] == fid]
    if not fr:
        return None, None
    ft = ts(fr[0].get("observed_at"))
    if ft is None:
        return None, None
    c = []
    for r in rows:
        if r.get("f") or r["id"] >= fid:
            continue
        t = ts(r.get("observed_at"))
        if t is not None and ft - dt.timedelta(minutes=15) <= t <= ft - dt.timedelta(minutes=2):
            c.append((t, r["id"]))
    if not c:
        return None, None
    t, pid = max(c)
    return pid, (ft - t).total_seconds() / 60.0


def pct(rc, comp):
    lo = sum(1 for x in comp if x < rc)
    eq = sum(1 for x in comp if x == rc)
    return (lo + 0.5 * eq) / len(comp)


def race_calc(mp, mf, hit, rng):
    keys = sorted(k for k in mf if k in mp)
    if not keys:
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
    r = {k: (qf[k] / qp[k]) / (G[0][k[0]] * G[1][k[1]] * G[2][k[2]]) ** (1.0 / 3) for k in keys}
    if hit not in qp:
        return "x_hit", None
    qh = qp[hit]
    comp = [k for k in keys if k != hit and qh / 2 <= qp[k] <= qh * 2]
    if len(comp) < 20:
        return "x_comp", None
    u = pct(r[hit], [r[k] for k in comp])
    rank = 1 + sum(1 for k in keys if qp[k] > qh)
    fake = rng.choice(comp)
    qz = qp[fake]
    fc = [k for k in keys if k not in (hit, fake) and qz / 2 <= qp[k] <= qz * 2]
    fu = pct(r[fake], [r[k] for k in fc]) if len(fc) >= 20 else None
    return "ok", {"u": u, "r": r[hit], "g": qf[hit] / qp[hit], "qp": qh, "rank": rank, "ncomp": len(comp),
                  "fu": fu, "fr": r[fake], "frank": 1 + sum(1 for k in keys if qp[k] > qz)}


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
    s = sorted(xs)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    rng = random.Random(SEED)
    res = []
    ex = {"races": 0, "x_fin": 0, "x_nof": 0, "x_nop": 0, "x_hit": 0, "x_comp": 0, "x_fake": 0}
    lead = []
    W = {lab: {"n": 0, "win": 0, "exp": 0.0} for lab in WLABS}
    wex = {"races_ok": 0, "noV": 0, "used": 0}
    d = DW_FROM
    while d <= D_TO:
        day = d.isoformat()
        with3 = d >= D_FROM
        races, runs, win, full = fetch(base, key, day, with3)
        post_t = {rkey(r): hm(r.get("post_time")) for r in races}
        fin_of = {}
        for r in runs:
            try:
                fin_of.setdefault(rkey(r), {})[str(r["runner_number"])] = int(str(r.get("finish")).strip())
            except (TypeError, ValueError):
                continue
        # ---- 案 B 単勝
        wins = {}
        for r in win:
            wins.setdefault(rkey(r), []).append(r)
        for rk_, rows in sorted(wins.items()):
            fins = [r for r in rows if r.get("f")]
            if not fins or rk_ not in fin_of:
                continue
            fin = max(fins, key=lambda r: r["id"])
            fm, pm = hm(fin.get("t")), post_t.get(rk_)
            if fm is None or pm is None or abs(fm - pm) > 10:
                continue
            wex["races_ok"] += 1
            fw = fin.get("w") or {}
            fo = fin_of[rk_]
            vs = [r for r in rows if not r.get("f") and amin(r) is not None and amin(r) <= fm - 2]
            if not vs:
                wex["noV"] += 1
                continue
            V = max(vs, key=lambda r: (amin(r), r["id"]))
            vw = V.get("w") or {}
            hs = [h for h in fw if num(fw[h]) and num(vw.get(h))]
            if not hs:
                wex["noV"] += 1
                continue
            pf, pv = norm(fw, hs), norm(vw, hs)
            fav = min(hs, key=lambda h: (num(vw[h]), h))
            if fav not in fo:
                continue
            wex["used"] += 1
            c = W[wbin(pf[fav] / pv[fav])]
            c["n"] += 1
            c["win"] += 1 if fo[fav] == 1 else 0
            c["exp"] += pf[fav]
        # ---- 3連単
        if with3:
            f3 = {}
            for r in full:
                f3.setdefault(rkey(r), []).append(r)
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
                pid, mins = pick_p(rows, fid)
                if pid is None:
                    ex["x_nop"] += 1
                    continue
                todo.append((rk_, fid, pid, mins, (pos[1][0], pos[2][0], pos[3][0])))
            cache = {}
            get_combos(base, key, [t[1] for t in todo] + [t[2] for t in todo], cache)
            n0 = len(res)
            for rk_, fid, pid, mins, hit in todo:
                if fid not in cache or pid not in cache:
                    ex["x_nop"] += 1
                    continue
                st, v = race_calc(tri_map(cache[pid]), tri_map(cache[fid]), hit, rng)
                if st != "ok":
                    ex[st] += 1
                    continue
                if v["fu"] is None:
                    ex["x_fake"] += 1
                lead.append(mins)
                v.update({"track": rk_[0], "date": str(rk_[1]), "race_no": rk_[2], "hit": "-".join(hit),
                          "nankan": rk_[0] in NANKAN, "first": d < D_SPLIT, "lead": mins})
                res.append(v)
            log("%s 3連単 %d 行・使えた %d レース" % (day, len(full), len(res) - n0))
        d += dt.timedelta(days=1)
    write(res, ex, lead, W, wex)
    private(res)


def dec_table(us, fus):
    L = ["| 百分位 | 当たり組 | 偽の当たり |", "|---|---:|---:|"]
    n, m = len(us), len(fus)
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        a = sum(1 for x in us if lo <= x < hi or (i == 9 and x >= 1.0))
        b = sum(1 for x in fus if lo <= x < hi or (i == 9 and x >= 1.0))
        L.append("| %.1f〜%.1f | %d (%.1f%%) | %d (%.1f%%) |"
                 % (lo, hi, a, a / n * 100 if n else 0, b, b / m * 100 if m else 0))
    return L


def top_row(lab, us):
    n = len(us)
    t1 = sum(1 for x in us if x >= 0.99)
    t5 = sum(1 for x in us if x >= 0.95)
    dd, p = ks_p(us)
    return "| %s | %d | %d | %.1f | %d | %.1f | %.3f | %.3g |" % (lab, n, t1, n * 0.01, t5, n * 0.05, dd, p)


TOPH = ["| 区分 | 件数 | 上位1% | 期待 | 上位5% | 期待 | KS の D | KS の p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]


def write(res, ex, lead, W, wex):
    us = [v["u"] for v in res]
    fus = [v["fu"] for v in res if v["fu"] is not None]
    L = ["# 締め切り間際の 3連単の組への集中と的中(研究・1 回きり)", "",
         "期間 %s〜%s(3連単)・%s〜%s(単勝)。作成 %s。レースを特定できる情報は載せない。"
         % (D_FROM, D_TO, DW_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "## 対象", "",
         "- 3連単の行があり着順のあるレース %d・使えた %d" % (ex["races"], len(res)),
         "- 除外: 1〜3 着が 1 頭ずつでない %d・確定行なし %d・P(確定の 2〜15 分前の途中行)なし %d・"
         "当たり組が両方の行に無い %d・比べる相手 20 組未満 %d"
         % (ex["x_fin"], ex["x_nof"], ex["x_nop"], ex["x_hit"], ex["x_comp"]),
         "- 偽の当たりは相手 20 組未満で %d 件除外(偽の件数 %d)" % (ex["x_fake"], len(fus)),
         "- P が F の何分前か: 中央値 %.1f 分" % median(lead), "",
         "## 当たり組の百分位(組だけの伸び r の、比べる相手の中での位置・一様なら各 10%)", ""]
    L += dec_table(us, fus)
    L += ["", "## 上位に入った件数と一様性の検定", ""] + TOPH
    L.append(top_row("当たり組", us))
    L.append(top_row("偽の当たり", fus))
    L += ["", "- r の中央値: 当たり組 %.3f・偽の当たり %.3f"
          % (median([v["r"] for v in res]), median([v["fr"] for v in res if v["fu"] is not None])),
          "- 組の伸び g(=qF/qP)の中央値: 当たり組 %.3f" % median([v["g"] for v in res]), "",
          "## 人気帯(当たり組の P での人気順位)別", ""] + TOPH
    for lab, lo, hi in (("1〜10 番人気", 1, 10), ("11〜50 番人気", 11, 50), ("51 番人気以下", 51, 10 ** 9)):
        L.append(top_row(lab, [v["u"] for v in res if lo <= v["rank"] <= hi]))
        L.append(top_row(lab + "(偽)", [v["fu"] for v in res if v["fu"] is not None and lo <= v["frank"] <= hi]))
    L += ["", "## 南関 4 場/それ以外", ""] + TOPH
    for lab, f in (("南関 4 場", True), ("それ以外", False)):
        L.append(top_row(lab, [v["u"] for v in res if v["nankan"] == f]))
        L.append(top_row(lab + "(偽)", [v["fu"] for v in res if v["nankan"] == f and v["fu"] is not None]))
    L += ["", "## 前半/後半", ""] + TOPH
    for lab, f in (("前半 9/8〜9/19", True), ("後半 9/20〜9/30", False)):
        L.append(top_row(lab, [v["u"] for v in res if v["first"] == f]))
        L.append(top_row(lab + "(偽)", [v["fu"] for v in res if v["first"] == f and v["fu"] is not None]))
    L += ["", "## 案 B: 単勝の 1 番人気(締め切り 2 分前以下の最後の途中行で)が確定で落ちたか", "",
          "- 対象レース(発走 ±10 分)%d・使えた %d・V なし %d" % (wex["races_ok"], wex["used"], wex["noV"]), "",
          "| pF/pV | レース数 | 1着数 | 見込み | 実際÷見込み |", "|---|---:|---:|---:|---:|"]
    for lab in WLABS:
        c = W[lab]
        L.append("| %s | %d | %d | %.1f | %s |"
                 % (lab, c["n"], c["win"], c["exp"], ("%.2f" % (c["win"] / c["exp"])) if c["exp"] else "-"))
    L += ["", "> 百分位= 当たり組の r が、P での売れ方が近い(1/2〜2 倍)外れ組の中でどこにいるか(0〜1・1 に近いほど上)。"
          "偽の当たり= 同じレースの外れ組を 1 つ無作為に選んで同じ計算(比べ物)。1 か月弱なので結論にしない。", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


def private(res):
    top = sorted(res, key=lambda v: (-v["u"], -v["r"]))[:200]
    with io.open(PRIV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["track", "date", "race_no", "hit", "u", "r", "g", "qP", "rank", "ncomp", "lead_min"])
        for v in top:
            w.writerow([v["track"], v["date"], v["race_no"], v["hit"], "%.4f" % v["u"], "%.4f" % v["r"],
                        "%.4f" % v["g"], "%.6f" % v["qp"], v["rank"], v["ncomp"], "%.1f" % v["lead"]])


if __name__ == "__main__":
    main()
