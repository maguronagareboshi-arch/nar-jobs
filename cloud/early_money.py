# -*- coding: utf-8 -*-
"""研究用・1 回きり: 発売の早い段階から締め切り 2 分前まで単勝が買われ続けた馬(早めの票)が確定オッズの見込み以上に勝つか。
便 .github/workflows/early-money.yml(workflow_dispatch のみ)から走らせ、docs/early-money/result.md を書く。

⛔本番 DB では REST の単純 select だけ(取得は late_money_preclose.py の fetch を流用)。集計は全部ここ。書き込みなし。
定義(fm・V・正規化・対象レースは late_money_preclose と同じ):
  E= そのレースで最初の途中行。M= E と V の中間時刻に最も近い途中行。pE・pM・pV= 各時点の正規化確率
  (確定/E/M/V の 4 つに数値がある馬だけでレース内合計 1)。
  早め= pV/pE。買われ続けた= pM/pE>=1.1 かつ pV/pM>=1.1。売れ続けなかった= 両方 <=0.91。人気= V の順位。
  見込み= 確定オッズの正規化確率の和。回収率= 単勝 100 円ずつ・確定単勝倍率で。
"""
import datetime as dt
import io
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import num, rkey, JST, log, hm  # noqa: E402
from late_money_preclose import fetch, amin, norm, cell, add, row, HEAD  # noqa: E402
import research_period as rp  # noqa: E402

D_FROM, D_TO, SCHED = rp.period(dt.date(2026, 9, 2), dt.date(2026, 9, 30), data_from=dt.date(2026, 9, 2))
D_HALF = rp.midpoint(D_FROM, D_TO)  # 既定 9/2〜9/30 では 9/16
NANKAN = {"大井", "川崎", "船橋", "浦和", "oi", "kawasaki", "funabashi", "urawa", "OI", "KAWASAKI", "FUNABASHI", "URAWA",
          "Oi", "Kawasaki", "Funabashi", "Urawa", "18", "19", "20", "21"}
BINS = ((None, 0.7, "<0.7"), (0.7, 0.9, "0.7〜0.9"), (0.9, 1.1, "0.9〜1.1"), (1.1, 1.3, "1.1〜1.3"),
        (1.3, 1.6, "1.3〜1.6"), (1.6, None, "1.6 以上"))
POPS = ((1, 3, "1〜3 番人気"), (4, 6, "4〜6 番人気"), (7, 99, "7 番人気以下"))
HALVES = ("前半 %s〜%s" % (rp.md(D_FROM), rp.md(D_HALF - dt.timedelta(days=1))), "後半 %s〜%s" % (rp.md(D_HALF), rp.md(D_TO)))
AREAS = ("南関 4 場", "南関以外")
T3 = {}


def qs(xs):
    if not xs:
        return "-", "-", "-"
    xs = sorted(xs)
    if len(xs) < 2:
        return xs[0], xs[0], xs[0]
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0], statistics.median(xs), q[2]


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    C = {}

    def g(k):
        if k not in C:
            C[k] = cell()
        return C[k]

    ex = {"races_ok": 0, "noV": 0, "noB": 0, "pre_used": 0, "noE": 0, "used": 0}
    e_lead, n_between, tracks = [], [], {}
    d = D_FROM
    while d <= D_TO:
        day = d.isoformat()
        half = HALVES[0] if d < D_HALF else HALVES[1]
        races, runs, win, _ = fetch(base, key, day, False)
        post_t = {rkey(r): hm(r.get("post_time")) for r in races}
        fin_of = {}
        for r in runs:
            try:
                fin_of.setdefault(rkey(r), {})[str(r["runner_number"])] = int(str(r.get("finish")).strip())
            except (TypeError, ValueError):
                continue
        wins = {}
        for r in win:
            wins.setdefault(rkey(r), []).append(r)
        n0 = ex["used"]
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
            rid = "%s|%s|%d" % rk_
            mids = [r for r in rows if not r.get("f") and amin(r) is not None]
            vs = [r for r in mids if amin(r) <= fm - 2]
            if not vs:
                ex["noV"] += 1
                continue
            V = max(vs, key=lambda r: (amin(r), r["id"]))
            va = amin(V)
            vw = V.get("w") or {}
            # ---- 照合= 前回の「単勝信号あり(閾値 1.3)」
            bs = [r for r in mids if va - 5 <= amin(r) <= va - 3]
            if not bs:
                ex["noB"] += 1
            else:
                B = max(bs, key=lambda r: (amin(r), r["id"]))
                bw = B.get("w") or {}
                hs = [h for h in fw if num(fw[h]) and num(vw.get(h)) and num(bw.get(h))]
                if hs:
                    pf, pv, pb = norm(fw, hs), norm(vw, hs), norm(bw, hs)
                    got = False
                    for h in hs:
                        if h not in fo:
                            continue
                        got = True
                        if pv[h] / pb[h] >= 1.3:
                            add(g("chk_sig"), {"pf": pf[h], "fo": num(fw[h]), "won": 1 if fo[h] == 1 else 0}, rid)
                    if got:
                        ex["pre_used"] += 1
            # ---- 早めの票
            E = min(mids, key=lambda r: (amin(r), r["id"]))
            ea = amin(E)
            if ea >= va or E["id"] == V["id"]:
                ex["noE"] += 1
                continue
            mt = (ea + va) / 2.0
            between = [r for r in mids if ea <= amin(r) <= va]
            M = min(between, key=lambda r: (abs(amin(r) - mt), r["id"]))
            ew, mw = E.get("w") or {}, M.get("w") or {}
            hs = [h for h in fw if num(fw[h]) and num(vw.get(h)) and num(ew.get(h)) and num(mw.get(h))]
            if not hs:
                ex["noE"] += 1
                continue
            pf, pv, pe, pmm = norm(fw, hs), norm(vw, hs), norm(ew, hs), norm(mw, hs)
            vod = {h: num(vw[h]) for h in hs}
            used = False
            nk = AREAS[0] if str(rk_[0]) in NANKAN else AREAS[1]
            for h in hs:
                if h not in fo:
                    continue
                used = True
                v = {"pf": pf[h], "fo": num(fw[h]), "won": 1 if fo[h] == 1 else 0}
                rk = 1 + sum(1 for x in hs if vod[x] < vod[h])
                pop = [lab for lo, hi, lab in POPS if lo <= rk <= hi][0]
                r_ve, r_me, r_vm = pv[h] / pe[h], pmm[h] / pe[h], pv[h] / pmm[h]
                add(g("all"), v, rid)
                for lo, hi, lab in BINS:
                    if (lo is None or r_ve >= lo) and (hi is None or r_ve < hi):
                        add(g(("bin", lab)), v, rid)
                if r_me >= 1.1 and r_vm >= 1.1:
                    for k in ("cont", ("cont", pop), ("cont", half), ("cont", nk)):
                        add(g(k), v, rid)
                if r_me <= 0.91 and r_vm <= 0.91:
                    for k in ("notb", ("notb", pop)):
                        add(g(k), v, rid)
                if r_ve >= 1.3:
                    for k in (("big", half), ("big", nk)):
                        add(g(k), v, rid)
                # ---- 追加確認= 4〜6 番人気の「売れ続けなかった」
                if 4 <= rk <= 6:
                    ks = [("x", "4〜6 番人気 全体")]
                    if r_me <= 0.91 and r_vm <= 0.91:
                        ks += [("x", "売れ続けなかった"), ("x", "売れ続けなかった・" + half), ("x", "売れ続けなかった・" + nk)]
                    elif r_me >= 1.1 and r_vm >= 1.1:
                        ks.append(("x", "売れ続けた(買われ続けた)"))
                    else:
                        ks.append(("x", "どちらでもない"))
                    if r_me <= 0.95 and r_vm <= 0.95:
                        ks.append(("x", "売れ続けなかった・閾値 0.95"))
                    if r_me <= 0.85 and r_vm <= 0.85:
                        ks.append(("x", "売れ続けなかった・閾値 0.85"))
                    for k in ks:
                        add(g(k), v, rid)
                        t = T3.setdefault(k, [0, 0])
                        t[0] += 1
                        t[1] += 1 if fo[h] <= 3 else 0
            if used:
                ex["used"] += 1
                e_lead.append(fm - ea)
                n_between.append(sum(1 for r in mids if ea < amin(r) < va))
                tracks.setdefault(nk, set()).add(str(rk_[0]))
        log("%s 単勝 %d 行 → %d レース" % (day, len(win), ex["used"] - n0))
        d += dt.timedelta(days=1)
    write(C, ex, e_lead, n_between, tracks)


def write(C, ex, e_lead, n_between, tracks):
    z = cell()

    def c(k):
        return C.get(k, z)

    q1, md, q3 = qs(e_lead)
    _, nb, _ = qs(n_between)
    L = ["# 早めの票(発売初期→締め切り 2 分前)が見込み以上に勝つか(研究・1 回きり)", "",
         "期間 %s〜%s。作成 %s。" % (D_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "## 照合(前回 late_money_preclose の閾値 1.3「単勝信号あり」= 1147 頭・180 勝)", "", HEAD,
         row("単勝信号あり(再計算)", c("chk_sig")), "",
         "- 対象レース(発走 ±10 分)%d・V なし %d・B なし %d・前回定義で使えた %d"
         % (ex["races_ok"], ex["noV"], ex["noB"], ex["pre_used"]),
         "- 早めの票で使えた %d レース・E が V より前に無い等で除外 %d" % (ex["used"], ex["noE"]),
         "- E の時刻= fm の何分前: 第1四分位 %s / 中央値 %s / 第3四分位 %s 分(%d レース)" % (q1, md, q3, len(e_lead)),
         "- E〜V の間の途中行の本数 中央値 %s" % nb,
         "- 場の分け: " + " / ".join("%s= %s" % (k, ",".join(sorted(v))) for k, v in sorted(tracks.items())), "",
         "## 早め= pV/pE の区分", "", HEAD]
    for _, _, lab in BINS:
        L.append(row(lab, c(("bin", lab))))
    L.append(row("全馬一律", c("all")))
    L += ["", "## 買われ続けた(pM/pE>=1.1 かつ pV/pM>=1.1)・売れ続けなかった(両方 <=0.91)", "", HEAD,
          row("買われ続けた", c("cont"))]
    for _, _, lab in POPS:
        L.append(row("買われ続けた・" + lab, c(("cont", lab))))
    L.append(row("売れ続けなかった", c("notb")))
    for _, _, lab in POPS:
        L.append(row("売れ続けなかった・" + lab, c(("notb", lab))))
    L += ["", "## 主要 2 区分を前半/後半で", "", HEAD]
    for hf in HALVES:
        L.append(row("pV/pE>=1.3・" + hf, c(("big", hf))))
        L.append(row("買われ続けた・" + hf, c(("cont", hf))))
    L += ["", "## 主要 2 区分を南関 4 場/それ以外で", "", HEAD]
    for nk in AREAS:
        L.append(row("pV/pE>=1.3・" + nk, c(("big", nk))))
        L.append(row("買われ続けた・" + nk, c(("cont", nk))))
    X = ("売れ続けなかった", "売れ続けなかった・" + HALVES[0], "売れ続けなかった・" + HALVES[1],
         "売れ続けなかった・" + AREAS[0], "売れ続けなかった・" + AREAS[1],
         "売れ続けなかった・閾値 0.95", "売れ続けなかった・閾値 0.85",
         "売れ続けた(買われ続けた)", "どちらでもない", "4〜6 番人気 全体")
    L += ["", "## 追加確認= 4〜6 番人気(V の順位)の「売れ続けなかった」(閾値は指定なしなら 0.91)", "", HEAD]
    for lab in X:
        L.append(row(lab, c(("x", lab))))
    base_t = T3.get(("x", "4〜6 番人気 全体"), [0, 0])
    br = "%.1f%%" % (100.0 * base_t[1] / base_t[0]) if base_t[0] else "-"
    L += ["", "### 3 着内(見込みとの比較なし)", "",
          "| 区分 | 頭数 | 3着内 | 3着内率 | 4〜6 番人気全体の率 |", "|---|---:|---:|---:|---:|"]
    for lab in X:
        n, t = T3.get(("x", lab), [0, 0])
        L.append("| %s | %d | %d | %s | %s |" % (lab, n, t, "%.1f%%" % (100.0 * t / n) if n else "-", br))
    L += ["", "> 見込み= 確定オッズの正規化確率の和。回収率= 単勝 100 円ずつ・確定単勝倍率。1 か月だけなので結論にしない。", ""]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "early-money", rp.out_name(SCHED, D_TO))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
