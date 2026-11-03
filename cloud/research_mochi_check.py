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
    a = ap.parse_args()
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


if __name__ == "__main__":
    main()
