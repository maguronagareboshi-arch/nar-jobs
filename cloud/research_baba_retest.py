#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-11-03)。馬場差の前の出し方(classfirst)と今の出し方(projhalf)を、
本番の便(baba_hist.py --dry-run --rebuild-all)が出した場ごとの json と本番 DB の nar_runs で比べる。

物差し(nar-site tools/research/baba_nextrun_prod.py と同じ考え方):
  組= 次走 R2 が同じ 2 頭で、前走が 60 日以内・異常なし・同じ場・同じ芝ダ・同じ距離・違う日。
  補正した前走の時計(時計 − k × d1 × 距離/1000)が速い方が R2 で先着したか(同じなら 0.5)。
  k= 先着のロジスティック回帰(切片なし)で −馬場差の係数 ÷ 時計の係数。⛔k は R2 が 2026-09-30 までの組だけで決める。
  区間= R2 の開催日(場×日)単位の復元抽出 1,000 回の 95%。
測る組: 全期間= R2 が直近 1 年/初見= 前走が 2026-10-01 以降(R2 も当然それ以降)。

⛔読み取りだけ: 本番 DB は REST の単純 select(月ごと・一意の order でページ送り)。DB にも公開バケットにも書かない。
  python cloud/research_baba_retest.py --old out/classfirst --new out/projhalf --out out/RESULT_baba_retest.md
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(または SUPABASE_ANON_KEY)
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baba  # noqa: E402
import cond_stats  # noqa: E402

NB = 1000
K_END = pd.Timestamp("2026-09-30")
NEW0 = pd.Timestamp("2026-10-01")
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


def pct(x):
    return f"{x * 100:.2f}%"


def fd(x):
    return f"{x * 100:+.2f}"


def load_dir(d):
    out = {}
    for track, pf in baba.TRACK2PREFIX.items():
        p = os.path.join(d, pf + ".json")
        if not os.path.exists(p):
            raise SystemExit(f"{p} が無い")
        js = json.load(open(p, encoding="utf-8"))
        for day, c in js["days"].items():
            if c.get("p") or c.get("d1") is None:
                continue
            out[(track, day)] = float(c["d1"])
    return out


def fetch(rest, since, until):
    runs, races = [], []
    m = since.replace(day=1)
    while m <= until:
        nx = (m + dt.timedelta(days=32)).replace(day=1)
        lo = max(since, m).isoformat()
        hi = min(until, nx - dt.timedelta(days=1)).isoformat()
        rng = f"&race_date=gte.{lo}&race_date=lte.{hi}"
        runs += rest.paged("nar_runs?select=track,race_date,race_no,finish,runner_number,time_sec,horse_name,birth_date,finish_note"
                           + rng, "race_date.asc,track.asc,race_no.asc,runner_number.asc")
        races += rest.paged("nar_races?select=track,race_date,race_no,distance_m,surface" + rng,
                            "race_date.asc,track.asc,race_no.asc")
        log(f"読んだ {lo}〜{hi}: 走 {len(runs):,}・レース {len(races):,}")
        m = nx
    return pd.DataFrame(runs), pd.DataFrame(races)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--today", default="")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else baba._today_jst()
    start = today - dt.timedelta(days=365)
    base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    OLD, NEW = load_dir(a.old), load_dir(a.new)
    log(f"日の値 前 {len(OLD):,}・今 {len(NEW):,}")

    rest = cond_stats.Rest(base, key)
    runs, races = fetch(rest, start - dt.timedelta(days=61), today)
    runs = runs[runs.track != baba.BANEI].copy()
    races = races.drop_duplicates(["track", "race_date", "race_no"])
    runs = runs.merge(races, on=["track", "race_date", "race_no"], how="left")
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
    r2 = r2[(gap >= 1) & (gap <= 60) & (r2.p_tok == True) & r2.p_track.isin(list(baba.TRACK2PREFIX))].copy()  # noqa: E712
    r2["p_surface"] = r2.p_surface.fillna("")
    for nm, src in (("o", OLD), ("n", NEW)):
        r2[nm] = [src.get((t, d), np.nan) for t, d in zip(r2.p_track, r2.p_race_date)]
    n_r2 = len(r2)
    r2 = r2.dropna(subset=["o", "n"])
    log(f"次走 {n_r2:,}・両方の値がそろう {len(r2):,}")

    gk = ["track", "race_date", "race_no", "date", "p_track", "p_surface", "p_distance_m"]
    cols = ["runner_number", "finish", "p_race_date", "p_date", "p_time_sec", "o", "n"]
    pr = r2[gk + cols].merge(r2[gk + cols], on=gk, suffixes=("_i", "_j"))
    pr = pr[(pr.runner_number_i < pr.runner_number_j) & (pr.p_race_date_i != pr.p_race_date_j)
            & (pr.finish_i != pr.finish_j)].reset_index(drop=True)
    y = (pr.finish_i < pr.finish_j).values.astype(float)
    dtm = (pr.p_time_sec_i - pr.p_time_sec_j).values.astype(float)
    dist = pr.p_distance_m.values.astype(float) / 1000.0
    DB = {"o": (pr.o_i - pr.o_j).values * dist, "n": (pr.n_i - pr.n_j).values * dist}
    pdate = np.minimum(pr.p_date_i.values, pr.p_date_j.values)
    TRAIN = (pr.date <= K_END).values
    ALL = np.ones(len(pr), bool)
    FRESH = pdate >= np.datetime64(NEW0)
    pj = pr.p_track.values
    ck = pr.track.astype(str) + "_" + pr.race_date.astype(str)
    cl, ci = np.unique(ck.values, return_inverse=True)
    nc = len(cl)
    rng = np.random.default_rng(20261103)
    Wb = np.stack([np.bincount(rng.integers(0, nc, nc), minlength=nc) for _ in range(NB)]).astype(float)
    log(f"組 {len(pr):,}(k を決める {int(TRAIN.sum()):,}・初見 {int(FRESH.sum()):,})・開催日 {nc:,}")

    def hits(s):
        return np.where(np.abs(s) < 1e-9, 0.5, ((s < 0) == (y == 1)).astype(float))

    def boot(h, mask):
        hc = np.bincount(ci[mask], weights=h[mask], minlength=nc)
        ncm = np.bincount(ci[mask], minlength=nc).astype(float)
        return (Wb @ hc) / np.maximum(Wb @ ncm, 1)

    def diff(h1, h0, mask):
        b = boot(h1, mask) - boot(h0, mask)
        lo, hi = np.percentile(b, [2.5, 97.5])
        return h1[mask].mean() - h0[mask].mean(), lo, hi

    def logit(X, yy, w, b=None):
        b = np.zeros(X.shape[1]) if b is None else b.copy()
        for _ in range(40):
            p = 1 / (1 + np.exp(-(X @ b)))
            st = np.linalg.solve((X * (w * p * (1 - p))[:, None]).T @ X, X.T @ (w * (yy - p)))
            b += st
            if np.abs(st).max() < 1e-9:
                break
        return b

    def kfit(m):
        X = np.column_stack([dtm[TRAIN], DB[m][TRAIN]])
        b = logit(X, y[TRAIN], np.ones(int(TRAIN.sum())))
        ks = []
        for i in range(NB):
            try:
                bb = logit(X, y[TRAIN], Wb[i, ci[TRAIN]], b)
                ks.append(-bb[1] / bb[0])
            except np.linalg.LinAlgError:
                pass
        lo, hi = np.percentile(ks, [2.5, 97.5])
        return -b[1] / b[0], lo, hi

    K = {m: kfit(m) for m in ("o", "n")}
    log("k を決めた")
    H0 = hits(dtm)
    HO = hits(dtm - K["o"][0] * DB["o"])
    HN = hits(dtm - K["n"][0] * DB["n"])
    HO1 = hits(dtm - DB["o"])
    HN1 = hits(dtm - DB["n"])

    say(f"# 馬場差 前の出し方と今の出し方の比べ直し= 本番の便の値+本番 DB(2026-11-03)\n")
    say("値= 研究便 research-baba-retest(nar-jobs)で cloud/baba_hist.py --dry-run --rebuild-all を "
        "前の出し方(classfirst)と今の出し方(projhalf・11/2 から本番)で全 14 場ぶん組んだ日×場の d1(1000m あたりの秒)。"
        "補正は画面と同じ 時計 − 倍率 × d1 × 前走の距離 / 1000。組の材料= 本番 DB の nar_runs・nar_races(読み取りだけ)。"
        "台本 cloud/research_baba_retest.py。\n")
    say("組= 次走が同じ 2 頭で、前走が 60 日以内・異常なし・同じ場・同じ芝ダ・同じ距離・違う日。"
        "補正した前走の時計が速い方が次走で先着したか(同じなら 0.5)。両方の出し方の値がそろう組だけ(同じ組で比べる)。"
        "区間は次走の開催日(場×日)単位の復元抽出 1,000 回の 95%。\n")
    say(f"倍率 k は次走が {K_END:%Y-%m-%d} までの組(直近 1 年の内)で出し方ごとに決め、両方の表に当てた。"
        f"初見= 前走が {NEW0:%Y-%m-%d} 以降の組(作り方を決めるのにも k を決めるのにも使っていない)。"
        "全期間の表は k を決めた組を含むので甘め。\n")
    table(["項目", "数"], [
        ["期間(次走)", f"{start}〜{today}"],
        ["前走が 60 日以内の次走", f"{n_r2:,}"],
        ["そのうち両方の値がそろう", f"{len(r2):,}"],
        ["組 全期間", f"{len(pr):,}"],
        ["組 k を決めた(次走 9/30 まで)", f"{int(TRAIN.sum()):,}"],
        ["組 初見(前走 10/1 以降)", f"{int(FRESH.sum()):,}"],
        ["開催日(次走の場×日)", f"{nc:,}"],
    ])
    table(["出し方", "倍率 k(9/30 まで)と 95% 区間"],
          [["前(classfirst)", f"{K['o'][0]:.2f} [{K['o'][1]:.2f}, {K['o'][2]:.2f}]"],
           ["今(projhalf)", f"{K['n'][0]:.2f} [{K['n'][1]:.2f}, {K['n'][2]:.2f}]"]])

    def block(mask):
        d0o = diff(HO, H0, mask)
        d0n = diff(HN, H0, mask)
        dno = diff(HN, HO, mask)
        d1 = diff(HN1, HO1, mask)
        return d0o, d0n, dno, d1

    say("## 1. 的中率(全期間と初見)\n")
    rows = []
    for nm, mk in (("全期間(直近 1 年)", ALL), ("初見(前走 10/1 以降)", FRESH)):
        d0o, d0n, dno, d1 = block(mk)
        rows.append([nm, f"{int(mk.sum()):,}", pct(H0[mk].mean()), pct(HO[mk].mean()), pct(HN[mk].mean()),
                     f"{fd(dno[0])} [{fd(dno[1])}, {fd(dno[2])}]",
                     f"{fd(d0o[0])} / {fd(d0n[0])}",
                     f"{pct(HO1[mk].mean())} / {pct(HN1[mk].mean())}({fd(d1[0])} [{fd(d1[1])}, {fd(d1[2])}])"])
    table(["組", "組の数", "補正なし", "前", "今", "今 − 前(点)と 95% 区間", "補正なしとの差(点) 前 / 今",
           "参考 倍率 1 の 前 / 今(今 − 前)"], rows)

    say("## 2. 南関 4 場とそれ以外(前走の場で分けた)\n")
    nk = np.isin(pj, list(baba.AI_TRACKS))
    rows = []
    for nm, mk0 in (("南関 4 場", nk), ("それ以外 10 場", ~nk)):
        for pn, mk1 in (("全期間", ALL), ("初見", FRESH)):
            mk = mk0 & mk1
            if mk.sum() == 0:
                rows.append([nm, pn, "0"] + ["—"] * 4)
                continue
            dno = diff(HN, HO, mk)
            rows.append([nm, pn, f"{int(mk.sum()):,}", pct(H0[mk].mean()), pct(HO[mk].mean()), pct(HN[mk].mean()),
                         f"{fd(dno[0])} [{fd(dno[1])}, {fd(dno[2])}]"])
    table(["前走の場", "組", "組の数", "補正なし", "前", "今", "今 − 前(点)と 95% 区間"], rows)
    same = sum(1 for k_, v in OLD.items() if k_[0] in baba.AI_TRACKS and k_ in NEW and abs(NEW[k_] - v) < 1e-9)
    alln = sum(1 for k_ in OLD if k_[0] in baba.AI_TRACKS and k_ in NEW)
    say(f"確かめ: 南関 4 場の日×場で前と今の d1 が同じ {same:,} / {alln:,}(全期間ファイル全体)。"
        "南関の値は両方とも予想 AI の日の値なので、違いは倍率 k の差だけから出る。\n")

    say("## 3. 場ごと(前走の場)\n")
    rows = []
    for track in baba.TRACK2PREFIX:
        r_ = [track + ("(南関)" if track in baba.AI_TRACKS else "")]
        for mk1 in (ALL, FRESH):
            mk = mk1 & (pj == track)
            n = int(mk.sum())
            if n < 30:
                r_ += [f"{n:,}", "—", "—", "—", "—"]
                continue
            dno = diff(HN, HO, mk)
            r_ += [f"{n:,}", pct(H0[mk].mean()), pct(HO[mk].mean()), pct(HN[mk].mean()),
                   f"{fd(dno[0])} [{fd(dno[1])}, {fd(dno[2])}]"]
        rows.append(r_)
    table(["前走の場", "全期間 組", "補正なし", "前", "今", "今 − 前", "初見 組", "補正なし", "前", "今", "今 − 前"], rows)
    say("組が 30 未満の場は —。区間は全体と同じ開催日単位の復元抽出(場の中の開催日だけが効く)。\n")
    say(f"実行時間 {time.time() - T0:.0f} 秒・REST {rest.nreq} 回")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(REP) + "\n")
    log(f"書いた {a.out}")


if __name__ == "__main__":
    main()
