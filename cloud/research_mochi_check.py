#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-11-04)。レース画面の「持ちタイム」表(各馬の最速)の並びが実際の着順にどれだけ近いか。

過去のレースごとに、そのレースの前日までの走だけで表を作り直し、並べ方 A〜F を比べる。
  A 補正なしのタイム順 / B 今の補正タイム順(画面 nar-viewer js/pages/race.js と同じ式・同じ倍率)/
  C B+斤量の直し(1kg あたり c 秒 × 距離/1000)/ D B+時計の古さ(期間の窓 or 1 年あたり a 秒 × 距離/1000 の割引)/
  E B で勝ち馬から T 秒 × 距離/1000 より離された走を除く / F C〜E のうち決める期間で効いたものを全部。
  参考 B2= 各馬の「補正タイムが最速の走」で並べる(画面は素の時計が最速の走を選び、その補正タイムで並べる)。
表= 画面の既定と同じ「各馬の最速」。最速の走は素の時計で選ぶ(同タイムは新しい日)。表に載らない馬は最後に同順。
物差し= (1) 表に 2 頭以上が載ったレースで 2 頭ずつの先着(着順が同じ組は除く・値が同じなら 0.5)
  (2) 表の 1 位(同値は割る)が 3 着以内 (3) 表の順と着順の順位の相関(表に 3 頭以上・レースごとの平均)。
区間= レースの開催日(場×日)単位の復元抽出 1,000 回の 95%。⛔数は 2026-06-30 までのレースで決め、2026-07-01 以降で測る。
⛔読み取りだけ: 本番 DB は REST の単純 select(月ごと・一意の order でページ送り)・馬場差は公開バケットの json。書かない。
  python cloud/research_mochi_check.py --out out/RESULT_mochi_time_check.md
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(または SUPABASE_ANON_KEY)
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baba  # noqa: E402
import cond_stats  # noqa: E402

NB = 1000
HIST0 = dt.date(2018, 1, 1)
EVAL0 = pd.Timestamp("2024-07-01")
FIT_END = pd.Timestamp("2026-06-30")
TEST0 = pd.Timestamp("2026-07-01")
# 画面と同じ倍率(nar-viewer js/pages/race.js AN6_BABA_SCALE_1K / AN6_BABA_SCALE / AN6_BABA_AI)
SC1K = {"kochi": 1.0, "sonoda": 1.0, "urawa": 1.0, "funabashi": 0.9, "himeji": 0.9, "mizusawa": 0.9, "monbetsu": 0.9,
        "morioka": 0.9, "saga": 0.9, "kanazawa": 0.8, "kasamatsu": 0.8, "kawasaki": 0.7, "nagoya": 0.7, "ooi": 0.5}
SC = {"kochi": 1.0, "urawa": 1.0, "mizusawa": 0.9, "morioka": 0.9, "saga": 0.9, "sonoda": 0.9, "funabashi": 0.8,
      "himeji": 0.8, "kanazawa": 0.8, "kasamatsu": 0.8, "monbetsu": 0.8, "kawasaki": 0.7, "nagoya": 0.7, "ooi": 0.5}
C_GRID = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4]
WIN_GRID = [None, 730, 365]
A_GRID = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8]
T_GRID = [np.inf, 5.0, 4.0, 3.0, 2.5, 2.0, 1.5, 1.0]
REP = []
T0 = time.time()


def log(s):
    print(f"{s}({time.time() - T0:.0f} 秒)", flush=True)


def say(s=""):
    REP.append(s)


def table(cols, rows):
    say("| " + " | ".join(cols) + " |")
    say("|" + "---|" * len(cols))
    for r in rows:
        say("| " + " | ".join(str(x) for x in r) + " |")
    say()


def jsround(x):
    return np.floor(x + 0.5)


def fetch(rest, since, until):
    runs, races = [], []
    m = since.replace(day=1)
    while m <= until:
        nx = (m + dt.timedelta(days=32)).replace(day=1)
        lo = max(since, m).isoformat()
        hi = min(until, nx - dt.timedelta(days=1)).isoformat()
        rng = f"&race_date=gte.{lo}&race_date=lte.{hi}"
        runs += rest.paged("nar_runs?select=track,race_date,race_no,finish,runner_number,time_sec,horse_name,birth_date,"
                           "finish_note,carried_weight" + rng, "race_date.asc,track.asc,race_no.asc,runner_number.asc")
        races += rest.paged("nar_races?select=track,race_date,race_no,distance_m" + rng,
                            "race_date.asc,track.asc,race_no.asc")
        log(f"読んだ {lo}〜{hi}: 走 {len(runs):,}・レース {len(races):,}")
        m = nx
    return pd.DataFrame(runs), pd.DataFrame(races)


def load_baba(base):
    rows = []
    for track, pf in baba.TRACK2PREFIX.items():
        url = f"{base}/storage/v1/object/public/cond-stats/v1/baba-hist/{pf}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "nar-jobs research"})
        js = json.loads(urllib.request.urlopen(req, timeout=120).read().decode("utf-8"))
        for day, c in (js.get("days") or {}).items():
            if not isinstance(c, dict):
                continue
            rows.append((track, day, c.get("d1"), c.get("s") == "ai", c.get("d")))
    b = pd.DataFrame(rows, columns=["track", "race_date", "bd1", "bai", "bd0"])
    b["bd1"] = pd.to_numeric(b.bd1, errors="coerce")
    b["bd0"] = pd.to_numeric(b.bd0, errors="coerce")
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--today", default="")
    ap.add_argument("--part", type=int, default=1, help="2= 園田の原因と古さの分解(2026-11-04 その 2)")
    ap.add_argument("--cf", default="", help="--part 2 用・前の出し方(classfirst)の baba_hist.py --out の場所")
    a = ap.parse_args()
    if a.part == 2:
        return main2(a)
    today = dt.date.fromisoformat(a.today) if a.today else baba._today_jst()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    bb = load_baba(base)
    log(f"馬場差の日 {len(bb):,}(d1 あり {int(bb.bd1.notna().sum()):,})")

    rest = cond_stats.Rest(base, key)
    runs, races = fetch(rest, HIST0, today - dt.timedelta(days=1))
    runs = runs[runs.track.isin(list(baba.TRACK2PREFIX))].copy()
    races = races.drop_duplicates(["track", "race_date", "race_no"])
    runs = runs.merge(races, on=["track", "race_date", "race_no"], how="left")
    runs = runs[runs.horse_name.notna() & runs.birth_date.notna()].copy()
    runs["key"] = runs.horse_name.astype(str) + "|" + runs.birth_date.astype(str)
    runs["date"] = pd.to_datetime(runs.race_date)
    fin = pd.to_numeric(runs.finish, errors="coerce")
    runs["fin"] = fin
    runs["finok"] = fin.notna() & (fin >= 1) & (fin == np.round(fin))
    runs["sec"] = pd.to_numeric(runs.time_sec, errors="coerce")
    runs["dist"] = pd.to_numeric(runs.distance_m, errors="coerce")
    runs["cw"] = pd.to_numeric(runs.carried_weight, errors="coerce")
    runs["rid"] = runs.track + "_" + runs.race_date.astype(str) + "_" + runs.race_no.astype(str)
    tok = runs.finok & (runs.sec > 0)
    wsec = runs[tok].groupby("rid").sec.min()
    runs["behind"] = runs.sec - runs.rid.map(wsec)

    hist = runs[runs.finok & (runs.sec > 0) & (runs.dist > 0)].copy()
    hist = hist.merge(bb, on=["track", "race_date"], how="left")
    pf = hist.track.map(baba.TRACK2PREFIX)
    has1 = hist.bd1.notna()
    bd = np.where(has1, jsround(hist.bd1 * hist.dist / 100) / 10, hist.bd0)
    k1 = np.where(hist.bai.fillna(False).astype(bool), 1.0, pf.map(SC1K).fillna(0.9))
    k = np.where(has1, k1, pf.map(SC).fillna(0.8))
    adj = jsround((hist.sec.values - bd * k) * 10) / 10
    hist["adj"] = np.where(adj > 0, adj, np.nan)
    log(f"表の材料の走 {len(hist):,}(補正タイムあり {int(hist.adj.notna().sum()):,}・d1 で {int(has1.sum()):,})")

    ent = runs[(runs.date >= EVAL0) & runs.finok & (runs.dist > 0)][["rid", "key", "date", "track", "race_date", "dist",
                                                                       "cw", "fin"]].copy()
    m = ent[["rid", "key", "date", "track", "dist", "cw"]].merge(
        hist[["key", "dist", "date", "track", "sec", "adj", "cw", "behind"]], on=["key", "dist"], suffixes=("", "_h"))
    m = m[m.date_h < m.date].reset_index(drop=True)
    m["d1k"] = m.dist / 1000.0
    m["age"] = (m.date - m.date_h).dt.days
    m["yrs"] = m.age / 365.25
    m["dw"] = (m.cw_h - m.cw).fillna(0.0)
    m["same"] = m.track_h == m.track
    log(f"出走 {len(ent):,}・前日までの同じ距離の走 {len(m):,}")

    ent = ent.set_index(["rid", "key"])
    rng = np.random.default_rng(20261104)

    def build(mm):
        """主の器= 表に載る馬(A の値がある馬)・2 頭以上のレースだけ"""
        have = mm.groupby(["rid", "key"]).size()
        e = ent.loc[ent.index.isin(have.index)].copy()
        n = e.groupby(level=0).size()
        e = e[e.index.get_level_values(0).isin(n[n >= 2].index)].sort_index().reset_index()
        e["ri"] = pd.factorize(e.rid)[0]
        e["ci_s"] = e.track + "_" + e.race_date.astype(str)
        rinfo = e.groupby("ri").agg(date=("date", "first"), track=("track", "first"), ci_s=("ci_s", "first"),
                                    n=("key", "size"))
        cl, ci = np.unique(rinfo.ci_s.values, return_inverse=True)
        idx = np.arange(len(e))
        pr = pd.DataFrame({"ri": e.ri.values, "i": idx})
        pr = pr.merge(pr, on="ri", suffixes=("", "j"))
        pr = pr[pr.i < pr.ij]
        fi, fj = e.fin.values[pr.i.values], e.fin.values[pr.ij.values]
        keep = fi != fj
        P = (pr.i.values[keep], pr.ij.values[keep], pr.ri.values[keep], (fi < fj)[keep])
        Wb = np.stack([np.bincount(rng.integers(0, len(cl), len(cl)), minlength=len(cl))
                       for _ in range(NB)]).astype(float)
        return {"e": e, "rinfo": rinfo, "ci": ci, "nc": len(cl), "P": P, "Wb": Wb, "mm": mm,
                "ekey": pd.MultiIndex.from_frame(e[["rid", "key"]]), "cache": {}}

    def pick(G, win, T):
        ck = (win, T)
        if ck in G["cache"]:
            return G["cache"][ck]
        p = G["mm"]
        if win is not None:
            p = p[p.age <= win]
        if np.isfinite(T):
            p = p[~(p.behind > T * p.d1k)]
        p = p.sort_values(["rid", "key", "sec", "date_h"], ascending=[True, True, True, False])
        p = p.drop_duplicates(["rid", "key"]).set_index(["rid", "key"])
        G["cache"][ck] = p
        return p

    def score(G, cfg):
        kind = cfg.get("kind", "B")
        if kind == "B2":
            p = G["mm"].sort_values(["rid", "key", "adj", "date_h"], ascending=[True, True, True, False],
                                    na_position="last").drop_duplicates(["rid", "key"]).set_index(["rid", "key"])
            v = p.adj
        else:
            p = pick(G, cfg.get("win"), cfg.get("T", np.inf))
            if kind == "A":
                v = p.sec
            else:
                v = p.adj - cfg.get("c", 0.0) * p.dw * p.d1k + cfg.get("a", 0.0) * p.yrs * p.d1k
        s = v.reindex(G["ekey"]).values.astype(float)
        return np.where(np.isfinite(s), s, np.inf)

    def per_race(G, s):
        e = G["e"]
        nr = len(G["rinfo"])
        i, j, ri, yi = G["P"]
        si, sj = s[i], s[j]
        h = np.where(si == sj, 0.5, ((si < sj) == yi).astype(float))
        hs = np.bincount(ri, weights=h, minlength=nr)
        hc = np.bincount(ri, minlength=nr).astype(float)
        sr = pd.Series(s)
        mn = sr.groupby(e.ri.values).transform("min").values
        top = (s == mn).astype(float)
        t3 = top * (e.fin.values <= 3)
        top1 = np.bincount(e.ri.values, weights=t3, minlength=nr) / np.bincount(e.ri.values, weights=top, minlength=nr)
        g = e.ri.values
        rs = sr.groupby(g).rank(method="average").values
        rf = e.fin.groupby(g).rank(method="average").values
        n = np.bincount(g, minlength=nr).astype(float)
        sx, sy = np.bincount(g, rs, nr), np.bincount(g, rf, nr)
        sxx, syy, sxy = np.bincount(g, rs * rs, nr), np.bincount(g, rf * rf, nr), np.bincount(g, rs * rf, nr)
        cov = sxy - sx * sy / n
        vx, vy = sxx - sx * sx / n, syy - sy * sy / n
        with np.errstate(invalid="ignore", divide="ignore"):
            rho = np.where((vx > 1e-12) & (vy > 1e-12), cov / np.sqrt(vx * vy), 0.0)
        rv = (n >= 3).astype(float)
        return hs, hc, top1, rho, rv

    def agg(G, pr_, mask, ci_=True):
        hs, hc, top1, rho, rv = pr_
        m_ = mask.astype(float)
        vals = (np.sum(hs * m_) / max(np.sum(hc * m_), 1), np.sum(top1 * m_) / max(m_.sum(), 1),
                np.sum(rho * rv * m_) / max(np.sum(rv * m_), 1))
        if not ci_:
            return vals, None
        ci, nc, Wb = G["ci"], G["nc"], G["Wb"]
        cb = lambda w: Wb @ np.bincount(ci, weights=w, minlength=nc)  # noqa: E731
        bs = [cb(hs * m_) / np.maximum(cb(hc * m_), 1), cb(top1 * m_) / np.maximum(cb(m_), 1),
              cb(rho * rv * m_) / np.maximum(cb(rv * m_), 1)]
        return vals, [np.percentile(b, [2.5, 97.5]) for b in bs], bs

    def pairrate(G, s, mask):
        hs, hc = per_race(G, s)[:2]
        return np.sum(hs[mask]) / max(np.sum(hc[mask]), 1)

    out = {}
    for ver, nm in (("same", "同じ場・同じ距離"), ("all", "全場の同じ距離")):
        mm = m[m.same] if ver == "same" else m
        G = build(mm)
        rd = G["rinfo"].date.values
        FIT = (rd <= np.datetime64(FIT_END))
        TEST = (rd >= np.datetime64(TEST0))
        log(f"{nm}: レース {len(G['rinfo']):,}(決める {int(FIT.sum()):,}・測る {int(TEST.sum()):,})・組 {len(G['P'][0]):,}")
        sB = score(G, {"kind": "B"})
        fB = pairrate(G, sB, FIT)
        grid = {"C": [], "D": [], "E": []}
        for c in C_GRID:
            grid["C"].append(({"c": c}, pairrate(G, score(G, {"c": c}), FIT)))
        for w in WIN_GRID:
            for a_ in A_GRID:
                grid["D"].append(({"win": w, "a": a_}, pairrate(G, score(G, {"win": w, "a": a_}), FIT)))
        for T in T_GRID:
            grid["E"].append(({"T": T}, pairrate(G, score(G, {"T": T}), FIT)))
        best = {kx: max(v, key=lambda t: t[1]) for kx, v in grid.items()}
        eff = [kx for kx in ("C", "D", "E") if best[kx][1] > fB + 1e-12]
        fcfg = {}
        for kx in eff:
            fcfg.update(best[kx][0])
        log(f"{nm}: 決めた {best}・効いた {eff}")
        cfgs = {"A": {"kind": "A"}, "B": {"kind": "B"}, "C": best["C"][0], "D": best["D"][0], "E": best["E"][0],
                "F": fcfg, "B2": {"kind": "B2"}}
        S = {kx: score(G, v) for kx, v in cfgs.items()}
        PR = {kx: per_race(G, v) for kx, v in S.items()}
        out[ver] = {"nm": nm, "G": G, "FIT": FIT, "TEST": TEST, "best": best, "eff": eff, "fB": fB, "cfgs": cfgs,
                    "S": S, "PR": PR, "grid": grid}

    def fp(x):
        return f"{x * 100:.2f}%"

    def fr(x):
        return f"{x:.3f}"

    def cdesc(kx, c):
        if kx == "A":
            return "補正なしのタイム順"
        if kx == "B":
            return "今の補正タイム順(画面と同じ)"
        if kx == "B2":
            return "参考 補正タイムが最速の走で並べる"
        parts = []
        if c.get("c"):
            parts.append(f"斤量 1kg あたり {c['c']:.2f} 秒 × 距離/1000")
        if c.get("win"):
            parts.append(f"直近 {c['win']} 日の走だけ")
        if c.get("a"):
            parts.append(f"古さ 1 年あたり {c['a']:.2f} 秒 × 距離/1000 を足す")
        if c.get("T") is not None and np.isfinite(c.get("T", np.inf)):
            parts.append(f"勝ち馬から {c['T']:.1f} 秒 × 距離/1000 より離された走を除く")
        return "B+" + "・".join(parts) if parts else "B と同じ(決める期間で効かなかった)"

    say("# 持ちタイム表(各馬の最速)の並びはどれだけ着順に近いか(2026-11-04)\n")
    say("材料= 本番 DB の nar_runs・nar_races(読み取りだけ・2018-01-01 以降)と公開バケット cond-stats の "
        "v1/baba-hist/<場>.json(日ごとの d1・d)。台本 nar-jobs cloud/research_mochi_check.py・便 research-mochi-check。\n")
    say("表の作り直し= 各レースの出走馬(着順のある馬)ごとに、そのレースの前日までの走のうち今回と同じ距離"
        "(同じ場版はさらに同じ場)の走を集め、素の時計が最速の走を 1 本選ぶ(同タイムは新しい日)。"
        "補正タイム= 時計 − 馬場差 × 倍率。馬場差= d1 × 距離/1000(0.1 秒に丸め)・d1 の無い日は d。"
        "倍率は画面の表(d1 用・d 用・南関の予想 AI の日は 1.0)。表に載らない馬は最後に同順。\n")
    say("⚠ 馬場差の日の値は今の作り直し済みの値(後の日の走も使って組んだ値)。画面がそのレースの日に出した値とは違うことがある。"
        "材料の走は 2018-01-01 以降だけ(それより前の走は表に入っていない)。\n")
    say(f"数を決めた期間= レースの日 {EVAL0:%Y-%m-%d}〜{FIT_END:%Y-%m-%d}(2 頭ずつの先着が最も高い値を格子で選んだ)。"
        f"測る期間= {TEST0:%Y-%m-%d}〜{today - dt.timedelta(days=1)}(数を決めるのに使っていない)。"
        "F= C〜E のうち決める期間で B より上がったものを全部合わせる(数は単独で決めた値のまま)。\n")
    say("物差し= (1) 表に 2 頭以上が載ったレースで 2 頭ずつ組んで先着を当てた割合(着順が同じ組は除く・表の値が同じなら 0.5)"
        " (2) 表の 1 位(同値は頭数で割る)が 3 着以内の割合 (3) 表の順と着順の順位の相関(表に 3 頭以上のレースの平均)。"
        "[ ] はレースの開催日(場×日)単位の復元抽出 1,000 回の 95% 区間。\n")

    say("## 0. 決めた数(決める期間 2024-07-01〜2026-06-30)\n")
    rows = []
    for ver in ("same", "all"):
        o = out[ver]
        for kx in ("C", "D", "E", "F"):
            v = o["cfgs"][kx]
            pr_fit = pairrate(o["G"], o["S"][kx], o["FIT"])
            rows.append([o["nm"], kx, cdesc(kx, v), fp(pr_fit), f"{(pr_fit - o['fB']) * 100:+.2f}"])
    table(["版", "並べ方", "決めた形", "決める期間の 2 頭ずつの先着", "B との差(点)"], rows)
    say("格子= 斤量 " + ", ".join(f"{c:.2f}" for c in C_GRID) + " 秒/kg/1000m。古さ= 窓(全期間・730 日・365 日)× 割引 "
        + ", ".join(f"{x:.2f}" for x in A_GRID) + " 秒/年/1000m。大敗= 勝ち馬から "
        + ", ".join("除かない" if not np.isfinite(t) else f"{t:.1f}" for t in T_GRID) + " 秒/1000m。\n")

    def main_table(ver, mask_name):
        o = out[ver]
        G = o["G"]
        mask = o["TEST"] if mask_name == "test" else o["FIT"]
        res = {kx: agg(G, o["PR"][kx], mask) for kx in ("A", "B", "C", "D", "E", "F", "B2")}
        bB = res["B"][2]
        rows = []
        for kx in ("A", "B", "C", "D", "E", "F", "B2"):
            v, c, bs = res[kx]
            d = bs[0] - bB[0]
            dlo, dhi = np.percentile(d, [2.5, 97.5])
            rows.append([kx, cdesc(kx, o["cfgs"][kx]),
                         f"{fp(v[0])} [{fp(c[0][0])}, {fp(c[0][1])}]",
                         f"{fp(v[1])} [{fp(c[1][0])}, {fp(c[1][1])}]",
                         f"{fr(v[2])} [{fr(c[2][0])}, {fr(c[2][1])}]",
                         "—" if kx == "B" else f"{(v[0] - res['B'][0][0]) * 100:+.2f} [{dlo * 100:+.2f}, {dhi * 100:+.2f}]"])
        hc = o["PR"]["A"][1]
        rinfo = G["rinfo"]
        say(f"レース {int(mask.sum()):,}・表に載った馬 {int(rinfo.n.values[mask].sum()):,}・組 {int(hc[mask].sum()):,}・"
            f"開催日 {len(np.unique(G['ci'][mask])):,}\n")
        table(["並べ方", "中身", "(1) 2 頭ずつの先着", "(2) 1 位が 3 着以内", "(3) 順位の相関", "(1) の B との差(点)"], rows)
        return res

    for ver in ("same", "all"):
        say(f"## {1 if ver == 'same' else 2}. 測る期間({TEST0:%Y-%m-%d} 以降)・{out[ver]['nm']}\n")
        main_table(ver, "test")
    say("## 3. 参考 決める期間(2024-07-01〜2026-06-30)・同じ場・同じ距離\n")
    say("数を決めた期間なので C〜F は甘め。\n")
    main_table("same", "fit")

    say("## 4. 場ごと(測る期間・同じ場・同じ距離)\n")
    o = out["same"]
    G = o["G"]
    trk = G["rinfo"].track.values
    for mi, mname in ((0, "(1) 2 頭ずつの先着"), (1, "(2) 1 位が 3 着以内"), (2, "(3) 順位の相関")):
        say(f"### {mname}\n")
        rows = []
        for track in baba.TRACK2PREFIX:
            mk = o["TEST"] & (trk == track)
            if mk.sum() < 30:
                rows.append([track, f"{int(mk.sum()):,}"] + ["—"] * 7)
                continue
            r_ = [track, f"{int(mk.sum()):,}"]
            for kx in ("A", "B", "C", "D", "E", "F", "B2"):
                v = agg(G, o["PR"][kx], mk, ci_=False)[0][mi]
                r_.append(fr(v) if mi == 2 else fp(v))
            rows.append(r_)
        table(["場", "レース", "A", "B", "C", "D", "E", "F", "参考 B2"], rows)
    say("レースが 30 未満の場は —。\n")
    for track in ("高知", "園田"):
        say(f"### {track}(区間付き)\n")
        mk = o["TEST"] & (trk == track)
        res = {kx: agg(G, o["PR"][kx], mk) for kx in ("A", "B", "C", "D", "E", "F", "B2")}
        rows = []
        for kx in ("A", "B", "C", "D", "E", "F", "B2"):
            v, c, bs = res[kx]
            d = bs[0] - res["B"][2][0]
            dlo, dhi = np.percentile(d, [2.5, 97.5])
            rows.append([kx, f"{fp(v[0])} [{fp(c[0][0])}, {fp(c[0][1])}]", f"{fp(v[1])} [{fp(c[1][0])}, {fp(c[1][1])}]",
                         f"{fr(v[2])} [{fr(c[2][0])}, {fr(c[2][1])}]",
                         "—" if kx == "B" else f"{(v[0] - res['B'][0][0]) * 100:+.2f} [{dlo * 100:+.2f}, {dhi * 100:+.2f}]"])
        say(f"レース {int(mk.sum()):,}\n")
        table(["並べ方", "(1) 2 頭ずつの先着", "(2) 1 位が 3 着以内", "(3) 順位の相関", "(1) の B との差(点)"], rows)

    say("## 5. 格子の全部(決める期間の 2 頭ずつの先着)\n")
    for ver in ("same", "all"):
        o = out[ver]
        rows = [[kx, cdesc(kx, c), fp(v)] for kx in ("C", "D", "E") for c, v in o["grid"][kx]]
        say(f"### {o['nm']}(B= {fp(o['fB'])})\n")
        table(["並べ方", "形", "先着"], rows)
    say(f"実行時間 {time.time() - T0:.0f} 秒・REST {rest.nreq} 回")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(REP) + "\n")
    log(f"書いた {a.out}")


# ===== その 2(2026-11-04)= 園田で補正が効かない原因・古さの効き目の分解 =====
V2 = {"園田": "sonoda", "姫路": "himeji"}
KK_GRID = [round(0.1 * i, 1) for i in range(13)]
WIN2 = [180, 365, 730, None]
A2 = [0.0, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 2.5, 3.0]


def fetch2(rest, since, until):
    runs, races = [], []
    m = since.replace(day=1)
    while m <= until:
        nx = (m + dt.timedelta(days=32)).replace(day=1)
        lo = max(since, m).isoformat()
        hi = min(until, nx - dt.timedelta(days=1)).isoformat()
        rng = f"&race_date=gte.{lo}&race_date=lte.{hi}"
        runs += rest.paged("nar_runs?select=track,race_date,race_no,finish,runner_number,time_sec,horse_name,birth_date,"
                           "finish_note,carried_weight" + rng, "race_date.asc,track.asc,race_no.asc,runner_number.asc")
        races += rest.paged("nar_races?select=track,race_date,race_no,distance_m,going" + rng,
                            "race_date.asc,track.asc,race_no.asc")
        log(f"読んだ {lo}〜{hi}: 走 {len(runs):,}・レース {len(races):,}")
        m = nx
    return pd.DataFrame(runs), pd.DataFrame(races)


def load_cf(d):
    rows = []
    for track, pf in V2.items():
        js = json.load(open(os.path.join(d, pf + ".json"), encoding="utf-8"))
        for day, c in (js.get("days") or {}).items():
            if isinstance(c, dict):
                rows.append((track, day, c.get("d1"), c.get("d")))
    b = pd.DataFrame(rows, columns=["track", "race_date", "cd1", "cd0"])
    b["cd1"] = pd.to_numeric(b.cd1, errors="coerce")
    b["cd0"] = pd.to_numeric(b.cd0, errors="coerce")
    return b


def main2(a):
    today = dt.date.fromisoformat(a.today) if a.today else baba._today_jst()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    bb = load_baba(base)
    cf = load_cf(a.cf)
    log(f"馬場差の日 今 {len(bb):,}・前の出し方(園田・姫路){len(cf):,}")
    rest = cond_stats.Rest(base, key)
    runs, races = fetch2(rest, HIST0, today - dt.timedelta(days=1))
    runs = runs[runs.track.isin(list(baba.TRACK2PREFIX))].copy()
    races = races.drop_duplicates(["track", "race_date", "race_no"])
    runs = runs.merge(races, on=["track", "race_date", "race_no"], how="left")
    runs = runs[runs.horse_name.notna() & runs.birth_date.notna()].copy()
    runs["key"] = runs.horse_name.astype(str) + "|" + runs.birth_date.astype(str)
    runs["date"] = pd.to_datetime(runs.race_date)
    fin = pd.to_numeric(runs.finish, errors="coerce")
    runs["fin"] = fin
    runs["finok"] = fin.notna() & (fin >= 1) & (fin == np.round(fin))
    runs["sec"] = pd.to_numeric(runs.time_sec, errors="coerce")
    runs["dist"] = pd.to_numeric(runs.distance_m, errors="coerce")
    runs["cw"] = pd.to_numeric(runs.carried_weight, errors="coerce")
    runs["going"] = runs.going.fillna("").astype(str)
    runs["rid"] = runs.track + "_" + runs.race_date.astype(str) + "_" + runs.race_no.astype(str)
    tok = runs.finok & (runs.sec > 0)
    runs["behind"] = runs.sec - runs.rid.map(runs[tok].groupby("rid").sec.min())

    hist = runs[runs.finok & (runs.sec > 0) & (runs.dist > 0)].copy()
    hist = hist.merge(bb, on=["track", "race_date"], how="left").merge(cf, on=["track", "race_date"], how="left")
    pf = hist.track.map(baba.TRACK2PREFIX)
    has1 = hist.bd1.notna()
    hist["bdn"] = np.where(has1, jsround(hist.bd1 * hist.dist / 100) / 10, hist.bd0)
    k1 = np.where(hist.bai.fillna(False).astype(bool), 1.0, pf.map(SC1K).fillna(0.9))
    k = np.where(has1, k1, pf.map(SC).fillna(0.8))
    adj = jsround((hist.sec.values - hist.bdn.values * k) * 10) / 10
    hist["adj"] = np.where(adj > 0, adj, np.nan)
    hc1 = hist.cd1.notna()
    hist["bdc"] = np.where(hc1, jsround(hist.cd1 * hist.dist / 100) / 10, hist.cd0)
    kc = np.where(hc1, pf.map(SC1K).fillna(0.9), pf.map(SC).fillna(0.8))
    adjc = jsround((hist.sec.values - hist.bdc.values * kc) * 10) / 10
    hist["adjc"] = np.where(adjc > 0, adjc, np.nan)
    log(f"表の材料の走 {len(hist):,}")

    ent = runs[(runs.date >= EVAL0) & runs.finok & (runs.dist > 0)][["rid", "key", "date", "track", "race_date", "dist",
                                                                       "cw", "fin", "going"]].copy()
    m = ent[["rid", "key", "date", "track", "dist"]].merge(
        hist[["key", "dist", "date", "track", "sec", "adj", "adjc", "bdn", "bdc", "behind"]], on=["key", "dist"],
        suffixes=("", "_h"))
    m = m[m.date_h < m.date].reset_index(drop=True)
    m["d1k"] = m.dist / 1000.0
    m["age"] = (m.date - m.date_h).dt.days
    m["yrs"] = m.age / 365.25
    m["same"] = m.track_h == m.track
    log(f"出走 {len(ent):,}・前日までの同じ距離の走 {len(m):,}")
    ent = ent.set_index(["rid", "key"])
    rng = np.random.default_rng(20261104)

    def build(mm):
        have = mm.groupby(["rid", "key"]).age.min()
        e = ent.loc[ent.index.isin(have.index)].copy()
        n = e.groupby(level=0).size()
        e = e[e.index.get_level_values(0).isin(n[n >= 2].index)].sort_index()
        e["rec"] = have.reindex(e.index).values <= 365
        e = e.reset_index()
        e["ri"] = pd.factorize(e.rid)[0]
        e["ci_s"] = e.track + "_" + e.race_date.astype(str)
        rinfo = e.groupby("ri").agg(date=("date", "first"), track=("track", "first"), ci_s=("ci_s", "first"),
                                    dist=("dist", "first"), going=("going", "first"), n=("key", "size"),
                                    allrec=("rec", "all"))
        cl, ci = np.unique(rinfo.ci_s.values, return_inverse=True)
        idx = np.arange(len(e))
        pr = pd.DataFrame({"ri": e.ri.values, "i": idx})
        pr = pr.merge(pr, on="ri", suffixes=("", "j"))
        pr = pr[pr.i < pr.ij]
        fi, fj = e.fin.values[pr.i.values], e.fin.values[pr.ij.values]
        keep = fi != fj
        P = (pr.i.values[keep], pr.ij.values[keep], pr.ri.values[keep], (fi < fj)[keep])
        Wb = np.stack([np.bincount(rng.integers(0, len(cl), len(cl)), minlength=len(cl))
                       for _ in range(NB)]).astype(float)
        return {"e": e, "rinfo": rinfo, "ci": ci, "nc": len(cl), "P": P, "Wb": Wb, "mm": mm,
                "ekey": pd.MultiIndex.from_frame(e[["rid", "key"]]), "cache": {}}

    def pick(G, win):
        if win in G["cache"]:
            return G["cache"][win]
        p = G["mm"]
        if win is not None:
            p = p[p.age <= win]
        p = p.sort_values(["rid", "key", "sec", "date_h"], ascending=[True, True, True, False])
        p = p.drop_duplicates(["rid", "key"]).set_index(["rid", "key"])
        G["cache"][win] = p
        return p

    def score(G, cfg):
        p = pick(G, cfg.get("win"))
        kind = cfg.get("kind", "B")
        if kind == "A":
            v = p.sec
        elif kind == "K":
            vv = jsround((p.sec - p[cfg["bd"]] * cfg["kk"]) * 10) / 10
            v = vv.where(vv > 0)
        elif kind == "C":
            v = p.adjc
        else:
            v = p.adj + cfg.get("a", 0.0) * p.yrs * p.d1k
        s = v.reindex(G["ekey"]).values.astype(float)
        return np.where(np.isfinite(s), s, np.inf)

    def per_race(G, s):
        e = G["e"]
        nr = len(G["rinfo"])
        i, j, ri, yi = G["P"]
        si, sj = s[i], s[j]
        h = np.where(si == sj, 0.5, ((si < sj) == yi).astype(float))
        hs = np.bincount(ri, weights=h, minlength=nr)
        hc = np.bincount(ri, minlength=nr).astype(float)
        sr = pd.Series(s)
        g = e.ri.values
        mn = sr.groupby(g).transform("min").values
        top = (s == mn).astype(float)
        top1 = np.bincount(g, weights=top * (e.fin.values <= 3), minlength=nr) / np.bincount(g, weights=top, minlength=nr)
        rs = sr.groupby(g).rank(method="average").values
        rf = e.fin.groupby(g).rank(method="average").values
        n = np.bincount(g, minlength=nr).astype(float)
        sx, sy = np.bincount(g, rs, nr), np.bincount(g, rf, nr)
        sxx, syy, sxy = np.bincount(g, rs * rs, nr), np.bincount(g, rf * rf, nr), np.bincount(g, rs * rf, nr)
        cov = sxy - sx * sy / n
        vx, vy = sxx - sx * sx / n, syy - sy * sy / n
        with np.errstate(invalid="ignore", divide="ignore"):
            rho = np.where((vx > 1e-12) & (vy > 1e-12), cov / np.sqrt(vx * vy), 0.0)
        return hs, hc, top1, rho, (n >= 3).astype(float)

    def agg(G, pr_, mask):
        hs, hc, top1, rho, rv = pr_
        m_ = mask.astype(float)
        vals = (np.sum(hs * m_) / max(np.sum(hc * m_), 1), np.sum(top1 * m_) / max(m_.sum(), 1),
                np.sum(rho * rv * m_) / max(np.sum(rv * m_), 1))
        ci, nc, Wb = G["ci"], G["nc"], G["Wb"]

        def cb(w):
            return Wb @ np.bincount(ci, weights=w, minlength=nc)
        bs = [cb(hs * m_) / np.maximum(cb(hc * m_), 1), cb(top1 * m_) / np.maximum(cb(m_), 1),
              cb(rho * rv * m_) / np.maximum(cb(rv * m_), 1)]
        return vals, [np.percentile(b, [2.5, 97.5]) for b in bs], bs

    def pairrate(G, pr_, mask):
        return np.sum(pr_[0][mask]) / max(np.sum(pr_[1][mask]), 1)

    def fp(x):
        return f"{x * 100:.2f}%"

    def fci(v, c, r=False):
        f = (lambda x: f"{x:.3f}") if r else fp
        return f"{f(v)} [{f(c[0])}, {f(c[1])}]"

    def dci(res, kx, base_="B"):
        d = res[kx][2][0] - res[base_][2][0]
        lo, hi = np.percentile(d, [2.5, 97.5])
        return f"{(res[kx][0][0] - res[base_][0][0]) * 100:+.2f} [{lo * 100:+.2f}, {hi * 100:+.2f}]"

    def rows3(res, names, base_="B"):
        out = []
        for kx, desc in names:
            v, c, _ = res[kx]
            out.append([kx, desc, fci(v[0], c[0]), fci(v[1], c[1]), fci(v[2], c[2], True),
                        "—" if kx == base_ else dci(res, kx, base_)])
        return out

    H3 = ["並べ方", "中身", "(1) 2 頭ずつの先着", "(2) 1 位が 3 着以内", "(3) 順位の相関", "(1) の B との差(点)"]
    G = {"same": build(m[m.same]), "all": build(m)}
    for ver in G:
        rd = G[ver]["rinfo"].date.values
        G[ver]["FIT"] = rd <= np.datetime64(FIT_END)
        G[ver]["TEST"] = rd >= np.datetime64(TEST0)
        log(f"{ver}: レース {len(rd):,}")

    say("# 持ちタイム表の照合 その 2= 園田で補正が効かない原因・古さの効き目の分解(2026-11-04)\n")
    say("材料・表の作り方・物差し・区間はその 1(RESULT_mochi_time_check_20261104.md)と同じ。"
        "台本 nar-jobs cloud/research_mochi_check.py --part 2・便 research-mochi-check。"
        f"数を決めた期間= レースの日 {EVAL0:%Y-%m-%d}〜{FIT_END:%Y-%m-%d}・測る期間= {TEST0:%Y-%m-%d}〜{today - dt.timedelta(days=1)}。"
        "前の出し方(classfirst)の d1= baba_hist.py --dry-run --full --rebuild-all --baseline classfirst --venue sonoda,himeji。"
        "今の d1= 公開バケットの値(画面と同じ)。\n")

    # ---- 1a 日ごとの馬場差と、その日の補正なしの時計のふだんとの差
    say("## 1a. 日ごとの馬場差 d1 と「その日の補正なしの時計の、ふだんとの差」\n")
    say("ふだんとの差= 走ごとに (時計 − 同じ場・同じ距離・同じ年の中央値) ÷ 距離 × 1000、その日の全走の中央値(1000m あたりの秒)。"
        "⚠ その日のクラスの組み方(上のクラスが多い日は速い)も入る。\n")
    t = runs[tok & (runs.dist > 0) & runs.track.isin(list(V2))].copy()
    t["yr"] = t.date.dt.year
    t["r"] = (t.sec - t.groupby(["track", "dist", "yr"]).sec.transform("median")) / t.dist * 1000
    day = t.groupby(["track", "race_date"]).agg(dr=("r", "median"), n=("r", "size"), date=("date", "first")).reset_index()
    day = day.merge(bb[["track", "race_date", "bd1"]], on=["track", "race_date"], how="left").merge(
        cf[["track", "race_date", "cd1"]], on=["track", "race_date"], how="left")
    rows = []
    for track in V2:
        for pn, lo_, hi_ in (("2018〜", None, None), ("決める期間", EVAL0, FIT_END), ("測る期間", TEST0, None)):
            dd = day[day.track == track]
            if lo_ is not None:
                dd = dd[dd.date >= lo_]
            if hi_ is not None:
                dd = dd[dd.date <= hi_]
            r_ = [track, pn]
            for col in ("bd1", "cd1"):
                x = dd.dropna(subset=[col])
                if len(x) < 10:
                    r_ += [f"{len(x):,}", "—", "—", "—"]
                    continue
                c_ = np.corrcoef(x[col], x.dr)[0, 1]
                sl = np.polyfit(x[col], x.dr, 1)[0]
                r_ += [f"{len(x):,}", f"{c_:.3f}", f"{sl:.2f}", f"{np.median(np.abs(x.dr - x[col])):.2f}"]
            rows.append(r_)
    table(["場", "期間", "今 日数", "今 相関", "今 傾き", "今 ずれの中央値", "前 日数", "前 相関", "前 傾き",
           "前 ずれの中央値"], rows)
    say("傾き= ふだんとの差を d1 で回帰した傾き(1 に近いほど d1 がその日の時計の速さの分だけ動いている)。ずれ= |ふだんとの差 − d1|。\n")
    for track in V2:
        dd = day[(day.track == track) & (day.date >= EVAL0)].dropna(subset=["bd1"]).copy()
        dd["gap"] = dd.dr - dd.bd1
        dd = dd.reindex(dd.gap.abs().sort_values(ascending=False).index).head(15)
        say(f"### {track} ずれの大きい日(2024-07 以降・上位 15)\n")
        table(["日", "走", "今 d1", "前 d1", "ふだんとの差", "差 − 今 d1"],
              [[r.race_date, r.n, f"{r.bd1:+.2f}", "—" if pd.isna(r.cd1) else f"{r.cd1:+.2f}", f"{r.dr:+.2f}",
                f"{r.gap:+.2f}"] for r in dd.itertuples()])

    # ---- 1b 倍率を振る
    say("## 1b. 倍率を 0〜1.2 で振ったとき(同じ場・同じ距離・その場のレース)\n")
    say("補正タイム= 時計 − 馬場差 × 倍率(d1 の無い日の d にも同じ倍率)。倍率 0= 補正なし(A)。"
        "★= 決める期間の (1) が最も高い倍率。今の画面の倍率= 園田 1.0・姫路 0.9。\n")
    Gs = G["same"]
    trk = Gs["rinfo"].track.values
    for track in V2:
        mf = Gs["FIT"] & (trk == track)
        mt = Gs["TEST"] & (trk == track)
        say(f"### {track}(決める {int(mf.sum()):,} レース・測る {int(mt.sum()):,} レース)\n")
        rows = []
        for bdcol, bn in (("bdn", "今の出し方"), ("bdc", "前の出し方")):
            fits = []
            res = []
            for kk in KK_GRID:
                pr_ = per_race(Gs, score(Gs, {"kind": "K", "bd": bdcol, "kk": kk}))
                fits.append(pairrate(Gs, pr_, mf))
                res.append(agg(Gs, pr_, mt))
            bi = int(np.argmax(fits))
            for i_, kk in enumerate(KK_GRID):
                v, c, _ = res[i_]
                rows.append([bn, f"{kk:.1f}" + (" ★" if i_ == bi else ""), fp(fits[i_]), fci(v[0], c[0]),
                             fci(v[1], c[1]), fci(v[2], c[2], True)])
        table(["馬場差", "倍率", "決める期間 (1)", "測る期間 (1)", "測る期間 (2)", "測る期間 (3)"], rows)
    PRs = {"A": per_race(Gs, score(Gs, {"kind": "A"})), "B": per_race(Gs, score(Gs, {"kind": "B"})),
           "Bc": per_race(Gs, score(Gs, {"kind": "C"}))}

    # ---- 1c 距離別・馬場状態別
    say("## 1c. 距離別・馬場状態別(測る期間・同じ場・同じ距離)\n")
    say("B= 今の画面・Bc= 前の出し方の d1 で画面と同じ倍率。差は B − A(点)。\n")
    for track in V2:
        for gn, col in (("距離", "dist"), ("馬場状態", "going")):
            vals = Gs["rinfo"][col].values
            mt0 = Gs["TEST"] & (trk == track)
            keys = pd.Series(vals[mt0]).value_counts()
            rows = []
            for kv in sorted(keys.index, key=lambda x: str(x).zfill(6)):
                mk = mt0 & (vals == kv)
                if mk.sum() < 20:
                    rows.append([f"{kv}", f"{int(mk.sum()):,}", "—", "—", "—", "—", "—"])
                    continue
                res = {kx: agg(Gs, PRs[kx], mk) for kx in PRs}
                rows.append([f"{kv:.0f}m" if col == "dist" else (kv or "不明"), f"{int(mk.sum()):,}",
                             fp(res["A"][0][0]), fp(res["B"][0][0]), fp(res["Bc"][0][0]), dci(res, "B", "A"),
                             f"{fp(res['A'][0][1])} / {fp(res['B'][0][1])}"])
            say(f"### {track} {gn}別\n")
            table([gn, "レース", "A (1)", "B (1)", "Bc (1)", "B − A (1)(点)", "(2) A / B"], rows)
        say("レースが 20 未満の行は —。\n")

    # ---- 2 古さの分解
    say("## 2. 古さの効き目の分解\n")
    say("D1= 直近 365 日の走だけ(割り引きなし・数を決めない)/ D2= 全期間の走で古さだけ割り引く"
        "(1 年あたり a 秒 × 距離/1000 を足す・a は 0〜3.0)/ D3= 窓(180・365・730 日)と割り引きの両方。"
        "最速の走は素の時計で選ぶ(その 1 と同じ)。その 1 の D= 365 日+0.80。\n")
    for ver, nm in (("same", "同じ場・同じ距離"), ("all", "全場の同じ距離")):
        g_ = G[ver]
        grid = {}
        for w in WIN2:
            for a_ in A2:
                grid[(w, a_)] = pairrate(g_, per_race(g_, score(g_, {"win": w, "a": a_})), g_["FIT"])
        fB = grid[(None, 0.0)]
        d2 = max((k_ for k_ in grid if k_[0] is None), key=lambda k_: grid[k_])
        d3 = max((k_ for k_ in grid if k_[0] is not None), key=lambda k_: grid[k_])
        cfgs = {"A": ({"kind": "A"}, "補正なし"), "B": ({}, "今の画面"),
                "D1": ({"win": 365}, "直近 365 日だけ"),
                "D2": ({"a": d2[1]}, f"全期間+古さ 1 年あたり {d2[1]:.2f} 秒"),
                "D3": ({"win": d3[0], "a": d3[1]}, f"直近 {d3[0]} 日+古さ 1 年あたり {d3[1]:.2f} 秒"),
                "D前": ({"win": 365, "a": 0.8}, "その 1 の D(365 日+0.80)")}
        PRd = {kx: per_race(g_, score(g_, c[0])) for kx, c in cfgs.items()}
        say(f"### {nm}・決める期間の (1)(B= {fp(fB)})\n")
        table(["窓"] + [f"{x:.1f}" for x in A2],
              [["全期間" if w is None else f"{w} 日"] + [fp(grid[(w, a_)]) for a_ in A2] for w in WIN2])
        for sub, mk0, sn in (("測る期間", g_["TEST"], ""),
                             ("測る期間・表の全馬が直近 1 年以内に走ったレース", g_["TEST"] & g_["rinfo"].allrec.values,
                              "休み明けの馬がいないレースだけ= 休み明けを下げる効き目を除いた、時計の正しさの差。")):
            res = {kx: agg(g_, PRd[kx], mk0) for kx in PRd}
            say(f"### {nm}・{sub}(レース {int(mk0.sum()):,})\n")
            if sn:
                say(sn + "\n")
            table(H3, rows3(res, [(kx, c[1]) for kx, c in cfgs.items()]))

    say(f"実行時間 {time.time() - T0:.0f} 秒・REST {rest.nreq} 回")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(REP) + "\n")
    log(f"書いた {a.out}")


if __name__ == "__main__":
    main()
