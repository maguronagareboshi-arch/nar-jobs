# -*- coding: utf-8 -*-
"""研究用・1 回きり: 締め切り 2 分前に 3連単が単勝より低く見ている馬(r= p_tri/p_win が小さい)の
「その馬が 1 着の組」を 3連単で買ったときの実際の払戻を数える。
便 .github/workflows/trifecta-group-return.yml(workflow_dispatch のみ)から走らせ、docs/trifecta-group-return/result.md を書く。

⛔本番 DB では REST の単純 select だけ(取得は odds_win_vs_trifecta.py と同じ)。集計は全部ここ。書き込みなし。
V・p_win・p_tri・r・対象レースの定義と正規化は cloud/odds_win_vs_trifecta.py と完全に同じ。
払戻= 3連単の確定行(f=true の最大 id)の、的中の組の倍率。着順は nar_runs の finish。
  1・2・3 着が 1 頭ずつに決まらない(同着・中止)/確定行が無い/確定行に的中の組が無い レースは除外。
買い方(各馬= その馬が 1 着の組すべてを 1 単位):
  均等= 着順が数値の馬で作れる 馬-x-y の全組に同額。
  票比例= V の 3連単でその馬が 1 着の組だけ、賭け額 ∝ 1/V 倍率(合計 1)。V に倍率が無い組は買わない。
回収= 的中なら 的中組の賭け額×確定倍率、外れなら 0。回収率= 回収の和÷単位数。
"""
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import hm, num, rkey, first_share, JST, log  # noqa: E402
from late_money_preclose import fetch, get_combos, amin, norm  # noqa: E402
from odds_win_vs_trifecta import pick3_v  # noqa: E402

D_FROM, D_TO, D_SPLIT = dt.date(2026, 9, 8), dt.date(2026, 9, 30), dt.date(2026, 9, 20)
BINS = ((0.0, 0.5, "r<0.5"), (0.5, 0.7, "0.5〜0.7"), (0.7, 0.9, "0.7〜0.9"), (0.9, 1.1, "0.9〜1.1"),
        (1.1, 1.3, "1.1〜1.3"), (1.3, 1e18, "1.3 以上"))
# 前回(docs/odds-win-vs-trifecta/result.md・2026-10-10 作成)の区分 → (頭数, 1着数)
PREV = (("r<0.7", 1061, 51), ("0.7〜0.9", 2164, 218), ("0.9〜1.1", 2814, 398),
        ("1.1〜1.3", 1858, 208), ("r≥1.3", 1884, 87), ("全馬一律", 9781, 962))
PREV_RACES = 962
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "trifecta-group-return", "result.md")


def cell():
    return {"n": 0, "win": 0, "eq": 0.0, "pr": 0.0, "races": set()}


def add(c, v, rid):
    c["n"] += 1
    c["win"] += v["won"]
    c["eq"] += v["eq"]
    c["pr"] += v["pr"]
    c["races"].add(rid)


def tri_map(combos):
    """3連単 combos → {(a,b,c): 倍率}。倍率が数値の組だけ。"""
    m = {}
    for c in combos or []:
        if not isinstance(c, (list, tuple)) or len(c) < 5:
            continue
        o = num(c[-2])
        if o is None or o <= 0:
            continue
        m[(str(c[0]), str(c[1]), str(c[2]))] = o
    return m


def pick3_f(rows):
    fs = [r["id"] for r in rows if r.get("f")]
    return max(fs) if fs else None


def prev_bin(r):
    if r < 0.7:
        return "r<0.7"
    if r < 0.9:
        return "0.7〜0.9"
    if r < 1.1:
        return "0.9〜1.1"
    if r < 1.3:
        return "1.1〜1.3"
    return "r≥1.3"


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    keys = [b[2] for b in BINS] + ["all", "lo_all", "lo_1_3", "lo_4_6", "lo_7", "lo_first", "lo_second"]
    C = {k: cell() for k in keys}
    R = {p[0]: [0, 0] for p in PREV}
    allc = {"units": 0, "ret": 0.0}
    ex = {"races_ok": 0, "noV": 0, "no3": 0, "used": 0, "x_fin": 0, "x_nof": 0, "x_hit": 0, "paid": 0}
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
            todo.append(("%s|%s|%d" % rk_, fw, vw, fo, hs, v3, pick3_f(f3.get(rk_, []))))
        get_combos(base, key, [t[5] for t in todo] + [t[6] for t in todo if t[6] is not None], cache)
        n0 = ex["used"]
        for rid, fw, vw, fo, hs, v3, f3id in todo:
            if v3 not in cache:
                ex["no3"] += 1
                continue
            sh = first_share(cache[v3])
            st = sum(sh.get(h, 0.0) for h in hs)
            if st <= 0:
                ex["no3"] += 1
                continue
            ex["used"] += 1
            pw = norm(vw, hs)
            rr = {h: (sh.get(h, 0.0) / st) / pw[h] for h in hs}
            # 前回との照合(全 used レース)
            for h in hs:
                won = 1 if fo[h] == 1 else 0
                for lab in (prev_bin(rr[h]), "全馬一律"):
                    R[lab][0] += 1
                    R[lab][1] += won
            # 着順・確定払戻
            pos = {}
            for h, f in fo.items():
                pos.setdefault(f, []).append(h)
            if any(len(pos.get(k, [])) != 1 for k in (1, 2, 3)):
                ex["x_fin"] += 1
                continue
            if f3id is None or f3id not in cache:
                ex["x_nof"] += 1
                continue
            hit = (pos[1][0], pos[2][0], pos[3][0])
            fodds = tri_map(cache[f3id]).get(hit)
            if fodds is None:
                ex["x_hit"] += 1
                continue
            ex["paid"] += 1
            nu = len(fo)
            npair = (nu - 1) * (nu - 2)
            allc["units"] += 1
            allc["ret"] += fodds / (nu * npair)
            vm = tri_map(cache[v3])
            vod = {h: num(vw[h]) for h in hs}
            for h in hs:
                won = 1 if fo[h] == 1 else 0
                eq = fodds / npair if won else 0.0
                pr = 0.0
                if won and hit in vm:
                    s = sum(1.0 / o for k, o in vm.items() if k[0] == h)
                    pr = (1.0 / vm[hit]) / s * fodds
                v = {"won": won, "eq": eq, "pr": pr}
                r = rr[h]
                add(C["all"], v, rid)
                for lo, hi, lab in BINS:
                    if lo <= r < hi:
                        add(C[lab], v, rid)
                        break
                if r < 0.7:
                    rk = 1 + sum(1 for x in hs if vod[x] < vod[h])
                    add(C["lo_all"], v, rid)
                    add(C["lo_1_3" if rk <= 3 else ("lo_4_6" if rk <= 6 else "lo_7")], v, rid)
                    add(C["lo_first" if d < D_SPLIT else "lo_second"], v, rid)
        log("%s 単勝 %d 行・3連単 %d 行・組 %d 件 → %d レース" % (day, len(win), len(full), len(cache), ex["used"] - n0))
        d += dt.timedelta(days=1)
    write(C, R, allc, ex)


def row(lab, c):
    eq = "%.1f%%" % (c["eq"] / c["n"] * 100) if c["n"] else "-"
    pr = "%.1f%%" % (c["pr"] / c["n"] * 100) if c["n"] else "-"
    return "| %s | %d | %d | %s | %s | %d |" % (lab, c["n"], c["win"], eq, pr, len(c["races"]))


HEAD = ("| 区分 | 頭数 | 1着数 | 均等回収率 | 票比例回収率 | レース数 |\n"
        "|---|---:|---:|---:|---:|---:|")


def write(C, R, allc, ex):
    L = ["# 3連単が単勝より低く見ている馬の「1 着の組」を買うと(研究・1 回きり)", "",
         "期間 %s〜%s。作成 %s。" % (D_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "## 前回(docs/odds-win-vs-trifecta)との照合", "",
         "- 対象レース(発走 ±10 分)%d・使えた %d(前回 %d)・除外 単勝 V なし %d・3連単 V なし %d"
         % (ex["races_ok"], ex["used"], PREV_RACES, ex["noV"], ex["no3"]), "",
         "| 区分 | 頭数(今回) | 頭数(前回) | 1着数(今回) | 1着数(前回) | 一致 |", "|---|---:|---:|---:|---:|---|"]
    for lab, n, w in PREV:
        a, b = R[lab]
        L.append("| %s | %d | %d | %d | %d | %s |" % (lab, a, n, b, w, "○" if (a, b) == (n, w) else "×"))
    L += ["", "## 払戻の対象", "",
          "- 払戻を数えたレース %d・除外 1〜3 着が 1 頭ずつでない(同着・中止)%d・確定行なし %d・確定行に的中の組なし %d"
          % (ex["paid"], ex["x_fin"], ex["x_nof"], ex["x_hit"]), "",
          "## 比 r= p_tri / p_win の区分", "", HEAD]
    for _, _, lab in BINS:
        L.append(row(lab, C[lab]))
    L.append(row("全馬一律", C["all"]))
    L += ["", "## r<0.7 を V の単勝順位で分ける", "", HEAD,
          row("r<0.7 全体", C["lo_all"]), row("1〜3 番人気", C["lo_1_3"]),
          row("4〜6 番人気", C["lo_4_6"]), row("7 番人気以下", C["lo_7"]),
          "", "## 偏りの確認(r<0.7 全体を前半・後半で)", "", HEAD,
          row("前半 9/8〜9/19", C["lo_first"]), row("後半 9/20〜9/30", C["lo_second"]), "",
          "## 参考= 全組を均等に買った回収率(3連単の控除の目安)", "",
          "| レース数 | 回収率 |", "|---:|---:|",
          "| %d | %s |" % (allc["units"], ("%.1f%%" % (allc["ret"] / allc["units"] * 100)) if allc["units"] else "-"), "",
          "> 各馬= その馬が 1 着の組すべてを 1 単位。均等= 着順が数値の馬で作れる全組に同額。"
          "票比例= V の 1/倍率に比例(V に無い組は買わない)。払戻= 確定行の的中組の倍率。1 か月弱なので結論にしない。", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
