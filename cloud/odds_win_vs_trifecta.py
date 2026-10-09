# -*- coding: utf-8 -*-
"""研究用・1 回きり: 締め切り 2 分前に、3連単から逆算した 1 着確率が単勝と食い違う馬の勝ちやすさ・単勝回収率。
便 .github/workflows/odds-win-vs-trifecta.yml(workflow_dispatch のみ)から走らせ、docs/odds-win-vs-trifecta/result.md を書く。

⛔本番 DB では REST の単純 select だけ(取得は late_money_preclose.py と同じ)。集計は全部ここ。書き込みなし。
定義:
  fm= 単勝の確定行(f=true の最大 id)の t(分)。発走 ±10 分のレースだけ。
  V= 単勝は asof(無ければ t)が fm-2 分以下の最後の途中行。3連単は observed_at が fm-2 分以下の最後の途中行。
  p_win= V の単勝 1/倍率をレース内で合計 1。p_tri= V の 3連単でその馬が 1 着の組の 1/倍率の和をレース内で合計 1。
  (どちらも 確定/V 単勝に数値がある馬だけで正規化)。r= p_tri / p_win。
  見込み= 確定単勝の正規化確率の和。回収率= 単勝 100 円ずつ・確定単勝倍率。
"""
import datetime as dt
import io
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import hm, ts, num, rkey, first_share, JST, log  # noqa: E402
from late_money_preclose import fetch, get_combos, amin, norm  # noqa: E402

D_FROM, D_TO, D_SPLIT = dt.date(2026, 9, 8), dt.date(2026, 9, 30), dt.date(2026, 9, 20)
BINS = ((0.0, 0.7, "r<0.7"), (0.7, 0.9, "0.7〜0.9"), (0.9, 1.1, "0.9〜1.1"),
        (1.1, 1.3, "1.1〜1.3"), (1.3, 1.6, "1.3〜1.6"), (1.6, 1e18, "1.6 以上"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "odds-win-vs-trifecta", "result.md")
EPS = 1e-6


def cell():
    return {"n": 0, "win": 0, "exp": 0.0, "ptri": 0.0, "ret": 0.0, "races": set()}


def add(c, v, rid):
    c["n"] += 1
    c["win"] += v["won"]
    c["exp"] += v["pf"]
    c["ptri"] += v["pt"]
    c["ret"] += v["won"] * v["fo"] * 100
    c["races"].add(rid)


def pick3_v(rows, fm_dt):
    """3連単の V id(observed_at が fm-2 分以下の最後の途中行)。無ければ None。"""
    v = []
    for r in rows:
        if r.get("f"):
            continue
        t = ts(r["observed_at"])
        if t is not None and t < fm_dt - dt.timedelta(minutes=1):
            v.append((t, r["id"]))
    return max(v)[1] if v else None


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    keys = [b[2] for b in BINS] + ["hi_1_3", "hi_4_6", "hi_7", "hi_all", "hi_first", "hi_second", "all"]
    C = {k: cell() for k in keys}
    ll = {"pw": 0.0, "pt": 0.0, "pf": 0.0, "n": 0}
    ex = {"races_ok": 0, "noV": 0, "no3": 0, "used": 0}
    d = D_FROM
    while d <= D_TO:
        day = d.isoformat()
        races, runs, win, full = fetch(base, key, day, True)
        post_t = {rkey(r): hm(r.get("post_time")) for r in races}
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
        cache, todo = {}, []
        for rk_, rows in sorted(wins.items()):
            fins = [r for r in rows if r.get("f")]
            if not fins or rk_ not in fin_of:
                continue
            fin = max(fins, key=lambda r: r["id"])
            fm, pm = hm(fin.get("t")), post_t.get(rk_)
            if fm is None or pm is None or abs(fm - pm) > 10:
                continue
            ex["races_ok"] += 1
            fw = fin.get("w") or {}
            fo = fin_of[rk_]
            mids = [r for r in rows if not r.get("f") and amin(r) is not None]
            vs = [r for r in mids if amin(r) <= fm - 2]
            if not vs:
                ex["noV"] += 1
                continue
            V = max(vs, key=lambda r: (amin(r), r["id"]))
            vw = V.get("w") or {}
            hs = [h for h in fw if num(fw[h]) and num(vw.get(h)) and h in fo]
            if not hs:
                ex["noV"] += 1
                continue
            fm_dt = dt.datetime(d.year, d.month, d.day, fm // 60, fm % 60, tzinfo=JST)
            v3 = pick3_v(f3.get(rk_, []), fm_dt)
            if v3 is None:
                ex["no3"] += 1
                continue
            todo.append(("%s|%s|%d" % rk_, fw, vw, fo, hs, v3))
        get_combos(base, key, [t[5] for t in todo], cache)
        n0 = ex["used"]
        for rid, fw, vw, fo, hs, v3 in todo:
            if v3 not in cache:
                ex["no3"] += 1
                continue
            sh = first_share(cache[v3])
            st = sum(sh.get(h, 0.0) for h in hs)
            if st <= 0:
                ex["no3"] += 1
                continue
            ex["used"] += 1
            pf, pw = norm(fw, hs), norm(vw, hs)
            vod = {h: num(vw[h]) for h in hs}
            for h in hs:
                pt = sh.get(h, 0.0) / st
                won = 1 if fo[h] == 1 else 0
                v = {"pf": pf[h], "pt": pt, "fo": num(fw[h]), "won": won}
                r = pt / pw[h]
                rk = 1 + sum(1 for x in hs if vod[x] < vod[h])
                add(C["all"], v, rid)
                for lo, hi, lab in BINS:
                    if lo <= r < hi:
                        add(C[lab], v, rid)
                        break
                if r >= 1.3:
                    add(C["hi_all"], v, rid)
                    add(C["hi_1_3" if rk <= 3 else ("hi_4_6" if rk <= 6 else "hi_7")], v, rid)
                    add(C["hi_first" if d < D_SPLIT else "hi_second"], v, rid)
                y = won
                for k, p in (("pw", pw[h]), ("pt", pt), ("pf", pf[h])):
                    p = min(max(p, EPS), 1 - EPS)
                    ll[k] -= y * math.log(p) + (1 - y) * math.log(1 - p)
                ll["n"] += 1
        log("%s 単勝 %d 行・3連単 %d 行・組 %d 件 → %d レース" % (day, len(win), len(full), len(cache), ex["used"] - n0))
        d += dt.timedelta(days=1)
    write(C, ll, ex)


def row(lab, c):
    r = "%.2f" % (c["win"] / c["exp"]) if c["exp"] > 0 else "-"
    rt = "%.2f" % (c["win"] / c["ptri"]) if c["ptri"] > 0 else "-"
    roi = "%.1f%%" % (c["ret"] / c["n"]) if c["n"] else "-"
    return "| %s | %d | %d | %.1f | %s | %s | %s | %d |" % (lab, c["n"], c["win"], c["exp"], r, rt, roi, len(c["races"]))


HEAD = ("| 区分 | 頭数 | 1着数 | 見込み | 実際÷見込み | 実際÷p_tri和 | 単勝回収率 | レース数 |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|")


def write(C, ll, ex):
    L = ["# 締め切り 2 分前 単勝 vs 3連単の 1 着確率(研究・1 回きり)", "",
         "期間 %s〜%s。作成 %s。" % (D_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "- 対象レース(発走 ±10 分)%d・使えた %d・除外 単勝 V なし %d・3連単 V なし %d"
         % (ex["races_ok"], ex["used"], ex["noV"], ex["no3"]), "",
         "## 比 r= p_tri / p_win の区分", "", HEAD]
    for _, _, lab in BINS:
        L.append(row(lab, C[lab]))
    L.append(row("全馬一律", C["all"]))
    L += ["", "## r≥1.3 を V の単勝人気で分ける", "", HEAD,
          row("r≥1.3 全体", C["hi_all"]), row("1〜3 番人気", C["hi_1_3"]),
          row("4〜6 番人気", C["hi_4_6"]), row("7 番人気以下", C["hi_7"]),
          "", "## 偏りの確認(r≥1.3 全体を前半・後半で)", "", HEAD,
          row("前半 9/8〜9/19", C["hi_first"]), row("後半 9/20〜9/30", C["hi_second"]), ""]
    n = ll["n"] or 1
    L += ["## 参考= 1 着の当てはまり(対数損失・小さいほど良い・%d 頭)" % ll["n"], "",
          "| p_win(V 単勝) | p_tri(V 3連単) | 確定単勝 |", "|---:|---:|---:|",
          "| %.5f | %.5f | %.5f |" % (ll["pw"] / n, ll["pt"] / n, ll["pf"] / n), "",
          "> 見込み= 確定単勝の正規化確率の和。回収率= 単勝 100 円ずつ・確定単勝倍率。1 か月弱なので結論にしない。", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
