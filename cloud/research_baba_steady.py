#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-11-04)。馬場差 projhalf の②(走った馬の力の見積もり)を「安定して走る馬を物差しにする」形に
変えると次走のテストが良くなるかを測る。半々で混ぜるのは同じ(日の値 = 0.5 × classfirst の d1 + 0.5 × ②)。

  A 今のまま(baba.proj_days と同じ。一致を確かめる)
  B 安定した馬を重く: 馬のずれのばらつき s(近走の「前の走 − その日の②」の重み付き平均 a からの重み付き二乗平均の根)で
    重み 1 / clip(s, 下限, 上限)^2。レースの値= e(その日の走 − a)の重み付き中央値
  C 安定した馬だけ: 直近 365 日に 3 走以上かつ s ≤ 基準の馬だけ。レースに 3 頭・日に 4 R そろわなければ②なし= classfirst だけ
  D 外れた馬を除く: その日(場ごと)のレースに入った馬の e を集め、上下 q を除いた平均(q=0.5 は中央値)を日の値に
  どれも、前の走の補正(前の走 − その日の②)にはその作り方自身の②を使う(積み上げを作り方ごとに別に持つ)。
  B〜D の数はレース(次走)が 2026-06-30 までの組の的中率で決める(倍率 k もその組で決める)。

物差し= cloud/research_baba_retest.py と同じ次走のテスト。南関 4 場は予想 AI で上書きしているので前走が南関の組は外す。
⛔読み取りだけ: 本番 DB は REST の単純 select。DB にも公開バケットにも書かない。本番の baba.py は import して使うだけ。
  python cloud/research_baba_steady.py --out out/RESULT_baba_steady.md
"""
import argparse
import datetime as dt
import math
import multiprocessing as mp
import os
import statistics
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baba  # noqa: E402
import baba_hist as bh  # noqa: E402
import cond_stats  # noqa: E402
import research_baba_retest as rt  # noqa: E402

NB = 1000
K_END = pd.Timestamp("2026-09-30")
TUNE_END = pd.Timestamp("2026-06-30")
NEW0 = pd.Timestamp("2026-10-01")
B_LO = (0.3, 0.6, 1.0)
B_HI = (2.0, 4.0)
C_TAU = (0.6, 0.9, 1.2, 1.5)
D_Q = (0.1, 0.2, 0.3, 0.5)
VARS = ([("A", "A", None)]
        + [(f"B 下限{lo} 上限{hi}", "B", (lo, hi)) for lo in B_LO for hi in B_HI]
        + [(f"C 基準{t}", "C", t) for t in C_TAU]
        + [(f"D 上下{int(q * 100)}%除く" if q < 0.5 else "D 中央値", "D", q) for q in D_Q])
REP = []
T0 = time.time()
XS_BY_DATE = {}
RUNS = []
TARGETS = set()


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


def pct(x):
    return f"{x * 100:.2f}%"


def fd(x):
    return f"{x * 100:+.2f}"


def wmedian(es, ws):
    o = sorted(zip(es, ws))
    half = sum(ws) / 2.0
    c = 0.0
    for e, w in o:
        c += w
        if c >= half - 1e-12:
            return e
    return o[-1][0]


def trim_mean(es, q):
    if q >= 0.5:
        return statistics.median(es)
    s = sorted(es)
    n = len(s)
    c = int(n * q)
    s = s[c:n - c]
    return sum(s) / len(s)


def run_variants(start, end, want):
    """baba.proj_run と同じ積み上げを、作り方ごとに別の day/rv で行う。want= 出したい日(dt.date)の集合"""
    st = {nm: ({}, {}) for nm, _k, _p in VARS}
    hist = {}
    svals = []
    W = baba.PROJ_WT
    dates = sorted(d for d in XS_BY_DATE if start <= d <= end)
    for d in dates:
        rows = XS_BY_DATE[d]
        lo1 = d - dt.timedelta(days=baba.PROJ_WINS[0])
        lo2 = d - dt.timedelta(days=baba.PROJ_WINS[1])
        per = {nm: {} for nm in st}
        for _d, track, rno, h, x in rows:
            hh = hist.get(h) if h is not None else None
            if not hh:
                continue
            last = hh[-5:]
            prev = [(dk, xp) for dp, dk, xp in last if dp >= lo1]
            ok365 = len(prev) >= 3
            if not ok365:
                prev = [(dk, xp) for dp, dk, xp in last if dp >= lo2]
            if len(prev) < 3:
                continue
            rp = list(reversed(prev))
            wt = W[:len(rp)]
            sw = sum(wt)
            for nm, (day, rv) in st.items():
                f = []
                for dk, xp in rp:
                    if dk in day:
                        b = day[dk]
                    elif rv.get(dk):
                        b = statistics.median(list(rv[dk].values()))
                    else:
                        b = 0.0
                    f.append(xp - b)
                a = sum(w * v for w, v in zip(wt, f)) / sw
                s = math.sqrt(sum(w * (v - a) ** 2 for w, v in zip(wt, f)) / sw)
                per[nm].setdefault((track, rno), []).append((x - a, s, ok365))
                if nm == "A" and d in want:
                    svals.append(s)
        tracks = {r[1] for r in rows}
        for nm, kind, p in VARS:
            day, rv = st[nm]
            pooled = {}
            for (track, rno), lst in per[nm].items():
                if kind == "C":
                    lst = [t for t in lst if t[2] and t[1] <= p]
                if len(lst) < baba.PROJ_MIN_H:
                    continue
                es = [t[0] for t in lst]
                if kind == "B":
                    lo_, hi_ = p
                    ws = [1.0 / min(max(t[1], lo_), hi_) ** 2 for t in lst]
                    rv.setdefault((track, d), {})[rno] = wmedian(es, ws)
                else:
                    rv.setdefault((track, d), {})[rno] = statistics.median(es)
                if kind == "D":
                    pooled.setdefault(track, []).extend(es)
            for track in tracks:
                dd = rv.get((track, d))
                if dd and len(dd) >= baba.MIN_RACES:
                    day[(track, d)] = trim_mean(pooled[track], p) if kind == "D" else statistics.median(list(dd.values()))
        for _d, track, _rno, h, x in rows:
            if h is not None:
                hist.setdefault(h, []).append((d, (track, d), x))
    out = {nm: {(d.isoformat(), track): v for (track, d), v in st[nm][0].items() if d in want} for nm in st}
    return out, svals


def job_month(arg):
    ms, ts = arg
    t0 = time.time()
    out, sv = run_variants(ms - dt.timedelta(days=baba.PROJ_ANCHOR), ts[-1], set(ts))
    print(f"  月 {ms} 済み({time.time() - t0:.0f} 秒)", flush=True)
    return out, sv


def job_check(_):
    return baba.proj_days(RUNS, TARGETS)


def prep_xs(runs, targets):
    """baba.proj_days の前半と同じ(x を作る)。戻り= (日ごとの xs, 月ごとの出したい日)"""
    rr = []
    for track, d, rno, h, dist, surf, fin, t in runs:
        if not dist or t is None or track == baba.BANEI:
            continue
        d = d if isinstance(d, dt.date) else dt.date.fromisoformat(d)
        rr.append((track, d, rno, h, int(dist), surf, int(fin), float(t)))
    best = {}
    for r in rr:
        if 1 <= r[6] <= baba.TOP_N:
            k = (r[0], r[1], r[2], r[6])
            if k not in best or r[7] < best[k][7]:
                best[k] = r
    top5 = [(r[0], r[1], r[5], r[4], r[7]) for r in best.values()]
    tds = sorted(targets)
    by_m = {}
    for t in tds:
        by_m.setdefault(baba._ms(t), []).append(t)
    need = set()
    for ms, ts in by_m.items():
        m = baba._ms(ms - dt.timedelta(days=baba.PROJ_ANCHOR))
        while m <= ts[-1]:
            need.add(m)
            m = (m + dt.timedelta(days=32)).replace(day=1)
    par = baba.proj_pars(top5, need)
    xbd = {}
    for track, d, rno, h, dist, surf, _fin, t in rr:
        p = par.get((baba._ms(d), track, surf, dist))
        if p is None:
            continue
        x = max(-baba.PROJ_CLIP, min(baba.PROJ_CLIP, (t - p) / dist * 1000.0))
        xbd.setdefault(d, []).append((d, track, rno, h, x))
    return xbd, by_m


def main():
    global XS_BY_DATE, RUNS, TARGETS
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--today", default="")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else baba._today_jst()
    start = today - dt.timedelta(days=365)
    lo = start - dt.timedelta(days=61)
    base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    rest = cond_stats.Rest(base, key)

    # 1. classfirst の d1(南関以外 10 場)= baba_hist.merge_days と同じ組み方(読む範囲だけ研究の期間に絞る)
    CF = {}
    for track, prefix in baba.TRACK2PREFIX.items():
        if track in baba.AI_TRACKS:
            continue
        since = lo - dt.timedelta(days=baba.fetch_days("classfirst"))
        wins, races, _ = bh.fetch_track(rest, track, since, today)
        samples = bh.to_samples(track, wins, races)
        targets = {s[1] for s in samples if lo.isoformat() <= s[1] <= today.isoformat()}
        fr = rest.get("nar_races?select=race_date&track=eq.%s&order=race_date.asc&limit=1" % cond_stats.enc(track))
        ok_from = (dt.date.fromisoformat(fr[0]["race_date"]) + dt.timedelta(days=365)).isoformat() if fr else lo.isoformat()
        targets = {d for d in targets if d >= ok_from}
        days, _ = bh.merge_days(prefix, samples, targets, None, today, True, "classfirst")
        for d, c in days.items():
            if c.get("p") or c.get("d1") is None:
                continue
            CF[(track, d)] = float(c["d1"])
        log(f"classfirst {track}: {sum(1 for k in CF if k[0] == track)} 日")

    # 2. ②の材料(全場の全着順)= baba_hist.ProjCache と同じ読み方
    since = lo.replace(day=1) - dt.timedelta(days=baba.PROJ_ANCHOR + baba.PROJ_PAR_DAYS + 1)
    allruns, races = bh.fetch_proj_runs(rest, since, today)
    meta = {(r["track"], r["race_date"], r["race_no"]): r for r in races}
    RUNS = baba.proj_runs_of(allruns, meta)
    del allruns
    TARGETS = {lo + dt.timedelta(days=i) for i in range((today - lo).days + 1)}
    XS_BY_DATE, by_m = prep_xs(RUNS, TARGETS)
    log(f"②の材料 全着順 {len(RUNS):,} 行・月 {len(by_m)}")

    # 3. 作り方ごとの②(月ごとに積み直す= 本番と同じ)・A は baba.proj_days と照合
    with mp.get_context("fork").Pool(max(1, os.cpu_count() or 1)) as pool:
        chk = pool.apply_async(job_check, (0,))
        res = pool.map(job_month, sorted(by_m.items()), chunksize=1)
        PROD = chk.get()
    PV = {nm: {} for nm, _k, _p in VARS}
    SV = []
    for out, sv in res:
        for nm in PV:
            PV[nm].update(out[nm])
        SV += sv
    keys = set(PROD) | set(PV["A"])
    nmis = sum(1 for k in keys if (k in PROD) != (k in PV["A"]) or abs(PROD.get(k, 0) - PV["A"].get(k, 0)) > 1e-9)
    log(f"A と本番 proj_days の食い違い {nmis} / {len(keys)}")

    # 4. 日の値(半々)
    D1 = {}
    for nm in PV:
        pv = PV[nm]
        D1[nm] = {}
        for (track, d), c in CF.items():
            v = pv.get((d, track))
            D1[nm][(track, d)] = round(0.5 * c + 0.5 * v, 2) if v is not None else c
    tday = [(t, d) for (t, d) in CF if start.isoformat() <= d <= today.isoformat()]
    miss = {nm: sum(1 for (t, d) in tday if (d, t) not in PV[nm]) for nm in PV}

    # 5. 次走の組(research_baba_retest.py と同じ)
    runs, rcs = rt.fetch(rest, lo, today)
    runs = runs[runs.track != baba.BANEI].copy()
    rcs = rcs.drop_duplicates(["track", "race_date", "race_no"])
    runs = runs.merge(rcs, on=["track", "race_date", "race_no"], how="left")
    runs = runs[runs.horse_name.notna() & runs.birth_date.notna()].copy()
    runs["date"] = pd.to_datetime(runs.race_date)
    runs["ok"] = runs.finish_note.isna() & runs.finish.notna() & (runs.finish.fillna(0) >= 1)
    runs["tok"] = runs.ok & runs.time_sec.notna() & (runs.time_sec.fillna(0) > 0) & (runs.distance_m.fillna(0) > 0)
    runs = runs.sort_values(["horse_name", "birth_date", "date", "race_no"]).reset_index(drop=True)
    g = runs.groupby(["horse_name", "birth_date"], sort=False)
    for c in ("date", "track", "tok", "time_sec", "distance_m", "surface", "race_date"):
        runs["p_" + c] = g[c].shift(1)
    r2 = runs[(runs.date >= pd.Timestamp(start)) & runs.ok].copy()
    gap = (r2.date - r2.p_date).dt.days
    r2 = r2[(gap >= 1) & (gap <= 60) & (r2.p_tok == True) & r2.p_track.isin(list(baba.TRACK2PREFIX))  # noqa: E712
            & ~r2.p_track.isin(list(baba.AI_TRACKS))].copy()
    r2["p_surface"] = r2.p_surface.fillna("")
    n_r2 = len(r2)
    vn = [nm for nm, _k, _p in VARS]
    for i, nm in enumerate(vn):
        r2[f"v{i}"] = [D1[nm].get((t, d), np.nan) for t, d in zip(r2.p_track, r2.p_race_date)]
    r2 = r2.dropna(subset=["v0"])
    log(f"次走 {n_r2:,}・値がそろう {len(r2):,}")
    gk = ["track", "race_date", "race_no", "date", "p_track", "p_surface", "p_distance_m"]
    cols = ["runner_number", "finish", "p_race_date", "p_date", "p_time_sec"] + [f"v{i}" for i in range(len(vn))]
    pr = r2[gk + cols].merge(r2[gk + cols], on=gk, suffixes=("_i", "_j"))
    pr = pr[(pr.runner_number_i < pr.runner_number_j) & (pr.p_race_date_i != pr.p_race_date_j)
            & (pr.finish_i != pr.finish_j)].reset_index(drop=True)
    y = (pr.finish_i < pr.finish_j).values.astype(float)
    dtm = (pr.p_time_sec_i - pr.p_time_sec_j).values.astype(float)
    dist = pr.p_distance_m.values.astype(float) / 1000.0
    DB = {nm: (pr[f"v{i}_i"] - pr[f"v{i}_j"]).values * dist for i, nm in enumerate(vn)}
    pdate = np.minimum(pr.p_date_i.values, pr.p_date_j.values)
    TRAIN = (pr.date <= K_END).values
    TUNE = (pr.date <= TUNE_END).values
    ALL = np.ones(len(pr), bool)
    FRESH = pdate >= np.datetime64(NEW0)
    pj = pr.p_track.values
    ck = pr.track.astype(str) + "_" + pr.race_date.astype(str)
    cl, ci = np.unique(ck.values, return_inverse=True)
    nc = len(cl)
    rng = np.random.default_rng(20261104)
    Wb = np.stack([np.bincount(rng.integers(0, nc, nc), minlength=nc) for _ in range(NB)]).astype(float)
    log(f"組 {len(pr):,}(数を決める {int(TUNE.sum()):,}・k {int(TRAIN.sum()):,}・初見 {int(FRESH.sum()):,})・開催日 {nc:,}")

    def hits(s):
        return np.where(np.abs(s) < 1e-9, 0.5, ((s < 0) == (y == 1)).astype(float))

    def boot(h, mask):
        hc = np.bincount(ci[mask], weights=h[mask], minlength=nc)
        ncm = np.bincount(ci[mask], minlength=nc).astype(float)
        return (Wb @ hc) / np.maximum(Wb @ ncm, 1)

    def diff(h1, h0, mask):
        b = boot(h1, mask) - boot(h0, mask)
        lo_, hi_ = np.percentile(b, [2.5, 97.5])
        return h1[mask].mean() - h0[mask].mean(), lo_, hi_

    def logit(X, yy):
        b = np.zeros(X.shape[1])
        for _ in range(40):
            p = 1 / (1 + np.exp(-(X @ b)))
            stp = np.linalg.solve((X * (p * (1 - p))[:, None]).T @ X, X.T @ (yy - p))
            b += stp
            if np.abs(stp).max() < 1e-9:
                break
        return b

    def kfit(nm, mask):
        b = logit(np.column_stack([dtm[mask], DB[nm][mask]]), y[mask])
        return -b[1] / b[0]

    # 6. 数を決める(6/30 まで)
    tune = {}
    for nm in vn:
        k6 = kfit(nm, TUNE)
        tune[nm] = (k6, hits(dtm - k6 * DB[nm])[TUNE].mean())
    pick = {"A": "A"}
    for fam in ("B", "C", "D"):
        cand = [nm for nm, kd, _p in VARS if kd == fam]
        pick[fam] = max(cand, key=lambda n: (round(tune[n][1], 10), -cand.index(n)))
    K = {nm: kfit(nm, TRAIN) for nm in vn}
    H = {nm: hits(dtm - K[nm] * DB[nm]) for nm in vn}
    H0 = hits(dtm)

    say("# 馬場差の②(走った馬の力の見積もり)を安定して走る馬を物差しにする形へ(2026-11-04)\n")
    say("研究便 research-baba-steady(nar-jobs)・台本 cloud/research_baba_steady.py。本番 DB は読み取りだけ。"
        "日の値= 0.5 × classfirst の d1 + 0.5 × ②(1000m あたりの秒)。変えたのは②だけ。②が出ない日は classfirst だけ(本番と同じ)。"
        "前の走の補正にはその作り方自身の②を使う。南関 4 場は予想 AI で上書きしているので、前走が南関の組は外した(10 場)。\n")
    say("物差し= cloud/research_baba_retest.py と同じ次走のテスト(前走が 60 日以内・同じ場・芝ダ・距離・違う日の 2 頭が次走で同じレース。"
        "補正した前走の時計 = 時計 − k × d1 × 距離/1000 が速い方が先着したか)。区間= 次走の開催日(場×日)単位の復元抽出 1,000 回の 95%。\n")
    table(["項目", "数"], [
        ["期間(次走)", f"{start}〜{today}"],
        ["前走が 60 日以内の次走(南関以外の前走)", f"{n_r2:,}"],
        ["そのうち値がそろう", f"{len(r2):,}"],
        ["組 全期間", f"{len(pr):,}"],
        ["組 数を決めた(次走 6/30 まで)", f"{int(TUNE.sum()):,}"],
        ["組 k を決めた(次走 9/30 まで)", f"{int(TRAIN.sum()):,}"],
        ["組 初見(前走 10/1 以降)", f"{int(FRESH.sum()):,}"],
        ["開催日(次走の場×日)", f"{nc:,}"],
        ["A と本番 baba.proj_days の②の食い違い(場日)", f"{nmis:,} / {len(keys):,}"],
    ])
    qs = np.percentile(SV, [10, 25, 50, 75, 90]) if SV else [np.nan] * 5
    say("馬のばらつき s(1000m あたりの秒・A の②・研究の期間の走)の分布: "
        + "・".join(f"{p}%点 {v:.2f}" for p, v in zip((10, 25, 50, 75, 90), qs)) + f"(走 {len(SV):,})\n")

    say("## 1. 数の決め方(次走 2026-06-30 までの組で k も決めて的中率が最も高いもの)\n")
    rows = []
    for nm, kd, _p in VARS:
        rows.append([nm, f"{tune[nm][0]:.2f}", pct(tune[nm][1]), "← 採用" if pick.get(kd) == nm else "",
                     f"{miss[nm] / max(len(tday), 1) * 100:.1f}%"])
    table(["作り方", "k(6/30 まで)", "的中率(6/30 まで)", "", "②が出ない場日の割合(直近 1 年)"], rows)

    say("## 2. 的中率(k は次走 9/30 までの組で作り方ごとに決めた)\n")
    rows = []
    for fam in ("A", "B", "C", "D"):
        nm = pick[fam]
        r_ = [fam, nm, f"{K[nm]:.2f}"]
        for mk in (ALL, FRESH):
            r_.append(pct(H[nm][mk].mean()))
            if fam == "A":
                r_.append("—")
            else:
                d_ = diff(H[nm], H["A"], mk)
                r_.append(f"{fd(d_[0])} [{fd(d_[1])}, {fd(d_[2])}]")
        rows.append(r_)
    table(["", "作り方(採用した数)", "k", "全期間 的中率", "A との差(点)と 95% 区間", "初見 的中率", "A との差(点)と 95% 区間"], rows)
    say(f"組の数 全期間 {int(ALL.sum()):,}・初見 {int(FRESH.sum()):,}。補正なし 全期間 {pct(H0.mean())}・初見 {pct(H0[FRESH].mean())}。"
        "全期間は k と数を決めた組を含むので甘め。\n")
    nC = pick["C"]
    say(f"C({nC})で②が出ず classfirst だけになった場日: 直近 1 年 {miss[nC]:,} / {len(tday):,}"
        f"({miss[nC] / max(len(tday), 1) * 100:.1f}%)。A は {miss['A']:,}({miss['A'] / max(len(tday), 1) * 100:.1f}%)。\n")

    say("## 3. 場ごと(前走の場)\n")
    for pn, mk1 in (("全期間", ALL), ("初見", FRESH)):
        say(f"### {pn}\n")
        rows = []
        for track in baba.TRACK2PREFIX:
            if track in baba.AI_TRACKS:
                continue
            mk = mk1 & (pj == track)
            n = int(mk.sum())
            if n < 30:
                rows.append([track, f"{n:,}", "—", "—", "—", "—", "—"])
                continue
            r_ = [track, f"{n:,}", pct(H0[mk].mean()), pct(H["A"][mk].mean())]
            for fam in ("B", "C", "D"):
                d_ = diff(H[pick[fam]], H["A"], mk)
                r_.append(f"{fd(d_[0])} [{fd(d_[1])}, {fd(d_[2])}]" if track in ("高知", "園田") else fd(d_[0]))
            rows.append(r_)
        table(["前走の場", "組", "補正なし", "A", "B − A(点)", "C − A(点)", "D − A(点)"], rows)
    say("組が 30 未満の場は —。区間は高知・園田だけ(開催日単位の復元抽出)。\n")
    say(f"実行時間 {time.time() - T0:.0f} 秒・REST {rest.nreq} 回")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(REP) + "\n")
    log(f"書いた {a.out}")


if __name__ == "__main__":
    main()
