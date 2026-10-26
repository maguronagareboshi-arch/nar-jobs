#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-10-26)。馬場差の「距離のずれ」を直す案を本番データで確かめる。

今の馬場差(d・g)は 1 日×場に 1 つの秒を作り、距離によらず同じだけ時計から引く。南関の下調べでは
縮尺 k(引き方の丁度= 1)が 〜1200m 0.28〜0.35・1300〜1600m 0.66・1700m〜 1.34〜1.40 だった。

比べる直し方(3 つまで)=
  (a) 今のまま= 日の値(秒)を距離によらず引く
  (b) レースごとの差を 1000m あたりに直してから日の値(1000m あたりの秒)を作り、走りの距離を掛けて引く
  (c) (b) に、日のレース数 n が少ないときは「場×その日の馬場状態のふだん」へ寄せる縮め n/(n+5)
       ふだん= 同じ場・同じ主な馬場状態の、前日までの直近 365 日の (b) の日の値の中央値(5 日未満なら場の全馬場・それも無ければ 0)
レースごとの差は全部 cloud/baba.py の build_days(今の既定 classfirst・帯なしは外す)の内訳 race_d/race_g をそのまま使う。
物差し= 次走の答え合わせの的中率・距離の帯ごとの縮尺 k・奇数 R/偶数 R の一致。測る年 2025-09-28〜2026-09-27・ばんえい除く。

⛔本番 DB は REST の単純 select だけ。書き込みなし。結果は docs/research-baba-distance/result.md。

  python3 cloud/research_baba_distance.py     # SUPABASE_URL / SUPABASE_SERVICE_KEY(読むだけのキーでよい)
  環境変数 NB= 復元抽出の回数(既定 300)/ CACHE= 読んだ行を場ごとに置くフォルダ(2 回目から DB を読まない)
"""
import datetime as dtm
import json
import os
import urllib.request
import pickle
import statistics
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baba  # noqa: E402
import baba_hist  # noqa: E402
import cond_stats  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "research-baba-distance", "result.md")
T0 = dtm.date(2025, 9, 28)
D1 = dtm.date(2026, 9, 27)
# LOCAL= 本番の表を REST で写した手元の parquet のフォルダ(nankan_ai/v3)。写しは 2026-08-31 までなので測る年をずらす
LOCAL = os.environ.get("LOCAL") or None
if LOCAL:
    T0, D1 = dtm.date(2025, 9, 1), dtm.date(2026, 8, 31)
LOCAL_FILES = (("official/full/nar_runs.parquet", "official/full/nar_races.parquet"),
               ("db_runs_confirm_2022-01_2025-08.parquet", "db_races_confirm_2022-01_2025-08.parquet"),
               ("db_runs_sealed_2025-09_2026-08.parquet", "db_races_sealed_2025-09_2026-08.parquet"))
TQ0 = T0 - dtm.timedelta(days=61)                 # 前走の日(次走の答え合わせ用)
P0 = TQ0 - dtm.timedelta(days=365)                # (c) のふだんに要る (b) の日の値の始まり
H_START = P0 - dtm.timedelta(days=1095 + 30)      # その日の 3 年の段の窓
TRACKS = list(baba.TRACK2PREFIX)                  # ばんえいは入っていない
NANKAN = ("浦和", "船橋", "大井", "川崎")
BASE, NONE_BAND = baba.DEFAULT_BASELINE, "drop"
SHRINK = 5
MIN_PRIOR = 5
DBANDS = (("〜1200m", 0, 1250), ("1300〜1600m", 1251, 1650), ("1700m〜", 1651, 99999))
METH = {"a": "(a) 今のまま", "b": "(b) 1000m あたり×距離", "c": "(c) (b)+少ない日は寄せる"}


def pct(x):
    return f"{x * 100:.2f}%"


def fd(x):
    return f"{x * 100:+.2f}"


def fetch_all_runs(rest, track, since, until):
    """[since, until] の全着順の走(次走の答え合わせ用)。年ごとに区切る"""
    out = []
    tq = cond_stats.enc(track)
    y = since.year
    while y <= until.year:
        lo = max(since, dtm.date(y, 1, 1)).isoformat()
        hi = min(until, dtm.date(y, 12, 31)).isoformat()
        out += rest.paged("nar_runs?select=track,race_date,race_no,runner_number,finish,time_sec,finish_note,"
                          f"horse_name,birth_date&track=eq.{tq}&race_date=gte.{lo}&race_date=lte.{hi}",
                          "race_date.asc,race_no.asc,runner_number.asc,horse_name.asc")
        y += 1
    return out


_LOC = {}


def local_tables():
    """手元の写しを繋ぐ(重なる月は新しい写しを採る)。列は REST で読むものと同じ名前・日付は文字列"""
    if not _LOC:
        rr, ra = [], []
        for i, (fr, fa) in enumerate(LOCAL_FILES):
            for lst, fn in ((rr, fr), (ra, fa)):
                x = pd.read_parquet(os.path.join(LOCAL, fn))
                x["race_date"] = x.race_date.astype(str).str[:10]
                x["_src"] = i
                lst.append(x)
        runs = pd.concat(rr, ignore_index=True)
        races = pd.concat(ra, ignore_index=True)
        for x in (runs, races):
            x["race_no"] = pd.to_numeric(x.race_no, errors="coerce").astype("Int64")
        runs = runs.sort_values("_src").drop_duplicates(["track", "race_date", "race_no", "runner_number", "horse_name"],
                                                         keep="last")
        races = races.sort_values("_src").drop_duplicates(["track", "race_date", "race_no"], keep="last")
        _LOC["runs"], _LOC["races"] = runs, races
    return _LOC["runs"], _LOC["races"]


def _recs(df, cols):
    df = df[cols].astype(object).where(df[cols].notna(), None)
    out = df.to_dict("records")
    for r in out:
        r["race_no"] = int(r["race_no"])
    return out


def load_local(track):
    runs, races = local_tables()
    hs, d1, tq = H_START.isoformat(), D1.isoformat(), TQ0.isoformat()
    ru = runs[(runs.track == track) & (runs.race_date >= hs) & (runs.race_date <= d1)]
    fin = pd.to_numeric(ru.finish, errors="coerce")
    w = ru[(fin >= 1) & (fin <= baba.TOP_N) & ru.time_sec.notna() & ru.finish_note.isna()]
    ra = races[(races.track == track) & (races.race_date >= hs) & (races.race_date <= d1)]
    al = ru[ru.race_date >= tq]
    return (_recs(w, ["track", "race_date", "race_no", "finish", "runner_number", "time_sec"]),
            _recs(ra, ["track", "race_date", "race_no", "distance_m", "race_name", "going", "race_kind"]),
            _recs(al, ["track", "race_date", "race_no", "runner_number", "finish", "time_sec", "finish_note",
                       "horse_name", "birth_date"]))


def load_track(rest, track, cache):
    if LOCAL:
        return load_local(track)
    p = os.path.join(cache, baba.TRACK2PREFIX[track] + ".pkl") if cache else None
    if p and os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    wins, races = baba_hist.fetch_track(rest, track, H_START, D1)
    runs = fetch_all_runs(rest, track, TQ0, D1)
    if p:
        os.makedirs(cache, exist_ok=True)
        with open(p, "wb") as f:
            pickle.dump((wins, races, runs), f)
    return wins, races, runs


def day_values(race_dev, dist_of):
    """race_dev= {R: レースの差(秒)}。戻り= (a の値, b の値, レース数) / 4 R 未満なら None。
    a は build_days の d/g と同じ(小数 1 桁)。b は 1000m あたり(小数 2 桁)"""
    items = [(r, v) for r, v in sorted(race_dev.items(), key=lambda kv: str(kv[0])) if dist_of.get(r)]
    if len(items) < baba.MIN_RACES:
        return None
    a = round(statistics.median([v for _, v in items]), 1)
    b = round(statistics.median([v * 1000.0 / dist_of[r] for r, v in items]), 2)
    return a, b, len(items)


def shrink_all(bday, kday):
    """bday= {日: (b, n)}(1 場ぶん)・kday= {日: 主な馬場状態}。戻り= {日: c の値}(as-of= 前日までの 365 日)"""
    out = {}
    ds = sorted(bday)
    for d in ds:
        b, n = bday[d]
        lo = (dtm.date.fromisoformat(d) - dtm.timedelta(days=365)).isoformat()
        past = [x for x in ds if lo <= x < d]
        same = [bday[x][0] for x in past if kday.get(x) == kday.get(d)]
        if len(same) >= MIN_PRIOR:
            prior = statistics.median(same)
        elif len(past) >= MIN_PRIOR:
            prior = statistics.median([bday[x][0] for x in past])
        else:
            prior = 0.0
        out[d] = round((n * b + SHRINK * prior) / (n + SHRINK), 2)
    return out, None


def logit(X, yy, w, b=None):
    b = np.zeros(X.shape[1]) if b is None else b.copy()
    for _ in range(40):
        p = 1 / (1 + np.exp(-(X @ b)))
        g = X.T @ (w * (yy - p))
        Hm = (X * (w * p * (1 - p))[:, None]).T @ X
        st = np.linalg.solve(Hm, g)
        b += st
        if np.abs(st).max() < 1e-9:
            break
    return b


def run(rest, out_path=OUT, nb=None, cache=None, log=print):
    t_start = time.time()
    nb = nb or int(os.environ.get("NB", "300"))
    cache = cache or os.environ.get("CACHE") or None
    rng = np.random.default_rng(20261026)
    today = D1 + dtm.timedelta(days=1)
    P0s, TQ0s, T0s, D1s = P0.isoformat(), TQ0.isoformat(), T0.isoformat(), D1.isoformat()

    def lap(s):
        log(f"{s} {time.time() - t_start:.0f}s")

    VAL = {}            # (m, mode) -> {(track, date): 値(a は秒・b/c は 1000m あたり)}
    NR = {}             # (mode) -> {(track, date): レース数}
    HALF = []           # (mode, track, date, parity, a, b, n)
    MATCH = {"d": [0, 0], "g": [0, 0]}   # 照合 [日×場, 一致]
    runs_all, race_meta = [], {}
    n_wins = n_races = 0
    for track in TRACKS:
        wins, races, runs = load_track(rest, track, cache)
        n_wins += len(wins)
        n_races += len(races)
        runs_all += runs
        smp = baba_hist.to_samples(track, wins, races)
        dist_of = {}
        for r in races:
            if r.get("distance_m"):
                race_meta[(track, r["race_date"], r["race_no"])] = int(r["distance_m"])
                dist_of[(r["race_date"], r["race_no"])] = int(r["distance_m"])
        gs_of = {}
        for s in smp:
            if s[5] and P0s <= s[1] <= D1s:
                gs_of.setdefault(s[1], []).append(s[5])
        kday = {d: statistics.mode(gs) for d, gs in gs_of.items()}
        targets = {s[1] for s in smp if P0s <= s[1] <= D1s}
        info_of = {}
        days, _, _ = baba.build_days(smp, targets, BASE, today=today, rebuild_all=True,
                                     none_band=NONE_BAND, info_of=info_of)
        pf = baba.TRACK2PREFIX[track]
        bd = {"d": {}, "g": {}}
        for (d, _tr), inf in info_of.items():
            dmap = {r: dist_of.get((d, r)) for r in set(inf["race_d"]) | set(inf["race_g"])}
            for mode in "dg":
                rd = inf["race_" + mode]
                v = day_values(rd, dmap)
                if v:
                    a, b, n = v
                    cell = (days.get(d) or {}).get(pf) or {}
                    assert cell.get(mode) == a, (track, d, mode, cell.get(mode), a)   # build_days と同じ値
                    VAL.setdefault(("a", mode), {})[(track, d)] = a
                    VAL.setdefault(("b", mode), {})[(track, d)] = b
                    NR.setdefault(mode, {})[(track, d)] = n
                    bd[mode][d] = (b, n)
                if T0s <= d <= D1s:
                    for par in (1, 0):
                        sub = {r: x for r, x in rd.items() if int(r) % 2 == par}
                        items = [(r, x) for r, x in sub.items() if dmap.get(r)]
                        if len(items) >= 3:
                            HALF.append((mode, track, d, par, statistics.median([x for _, x in items]),
                                         statistics.median([x * 1000.0 / dmap[r] for r, x in items]), len(items)))
        for mode in "dg":
            cv, _ = shrink_all(bd[mode], kday)
            for d, v in cv.items():
                VAL.setdefault(("c", mode), {})[(track, d)] = v
                if d >= TQ0s:            # 照合= 本番の build_days が付けた d1/g1 と (c) が同じか
                    got = ((days.get(d) or {}).get(pf) or {}).get(mode + "1")
                    MATCH[mode][0] += 1
                    MATCH[mode][1] += int(got is not None and abs(got - v) < 0.005)
        lap(f"{track} 1〜5着 {len(wins)}・レース {len(races)}・全着順 {len(runs)}")

    L = []
    say = L.append

    def table(cols, rows):
        say("| " + " | ".join(cols) + " |")
        say("|" + "---|" * len(cols))
        for r in rows:
            say("| " + " | ".join(str(x) for x in r) + " |")
        say("")

    say("# 馬場差の距離のずれを直す案の確かめ(本番データ・研究)\n")
    src = ("材料= 本番の nar_runs/nar_races を REST の select で写した手元の parquet(2014-01〜2026-08-31・"
           "2026-10 に手元の読むだけのキーでは nar_runs が読めなくなったため)。" if LOCAL else "")
    say(f"{src}本番 DB は読むだけ(REST の単純 select)。台本 cloud/research_baba_distance.py。測る年 {T0s}〜{D1s}・ばんえい除く。"
        f"読んだ行= 1〜5着 {n_wins:,}・レース {n_races:,}・全着順 {len(runs_all):,}。"
        f"日の値の作り方は今の既定({BASE}・帯なしは外す)。\n")
    say("直し方= (a) 今のまま(日の秒を距離によらず引く)/(b) レースの差を 1000m あたりに直して日の値を作り、走りの距離を掛けて引く/"
        f"(c) (b) に、日のレース数 n のとき n/(n+{SHRINK}) だけ日の値を使い、残りを場×その日の主な馬場状態のふだん"
        f"(前日までの 365 日の (b) の中央値)へ寄せる。\n")

    # ---------- 1. 次走の答え合わせ ----------
    ar = pd.DataFrame(runs_all)
    ar = ar[ar.horse_name.notna()].copy()
    ar["horse"] = ar.horse_name.astype(str) + "|" + ar.birth_date.astype(str)
    ar["date"] = pd.to_datetime(ar.race_date)
    ar["fin"] = pd.to_numeric(ar.finish, errors="coerce").fillna(0)
    ar["tsec"] = pd.to_numeric(ar.time_sec, errors="coerce").fillna(0)
    ar["ok"] = ar.finish_note.isna() & (ar.fin > 0)
    ar["dist"] = [race_meta.get((t, d, r), 0) for t, d, r in zip(ar.track, ar.race_date, ar.race_no)]
    ar = ar.sort_values(["horse", "date", "track", "race_no"])
    for c in ["date", "track", "ok", "fin", "tsec", "dist", "race_date"]:
        ar["p_" + c] = ar.groupby("horse")[c].shift(1)
    r2 = ar[(ar.date >= pd.Timestamp(T0)) & ar.ok].copy()
    gap = (r2.date - r2.p_date).dt.days
    r2 = r2[(gap >= 1) & (gap <= 60) & (r2.p_ok == True) & (r2.p_tsec > 0) & (r2.p_dist > 0)].copy()  # noqa: E712
    VC = []
    for m in METH:
        for mode in "dg":
            col = f"{m}{mode}"
            dm = VAL.get((m, mode), {})
            v = np.array([dm.get((t, d), np.nan) for t, d in zip(r2.p_track, r2.p_race_date)], dtype=float)
            r2[col] = v if m == "a" else v * r2.p_dist.values.astype(float) / 1000.0     # 引く秒
            VC.append(col)
    r2["nr"] = [NR.get("d", {}).get((t, d), 0) for t, d in zip(r2.p_track, r2.p_race_date)]
    r2 = r2.dropna(subset=VC)
    cols = ["runner_number", "fin", "p_race_date", "p_tsec", "nr"] + VC
    gk = ["track", "race_date", "race_no", "p_track", "p_dist"]
    pr = r2[gk + cols].merge(r2[gk + cols], on=gk, suffixes=("_i", "_j"))
    pr = pr[(pr.runner_number_i < pr.runner_number_j) & (pr.p_race_date_i != pr.p_race_date_j)
            & (pr.fin_i != pr.fin_j)].reset_index(drop=True)
    y = (pr.fin_i < pr.fin_j).values.astype(float)
    dtv = (pr.p_tsec_i - pr.p_tsec_j).values.astype(float)
    DB = {c: (pr[c + "_i"] - pr[c + "_j"]).values.astype(float) for c in VC}
    DB["Z"] = np.zeros(len(pr))
    cl_key = pr.track.astype(str) + "_" + pr.race_date.astype(str)
    _cl, cl_idx = np.unique(cl_key.values, return_inverse=True)
    nc = len(_cl)
    Wb = np.stack([np.bincount(rng.integers(0, nc, nc), minlength=nc) for _ in range(nb)]).astype(float)

    def hits(s):
        return np.where(s == 0, 0.5, ((s < 0) == (y == 1)).astype(float))

    H = {c: hits(dtv - DB[c]) for c in VC + ["Z"]}

    def boot(h, mask):
        hc = np.bincount(cl_idx[mask], weights=h[mask], minlength=nc)
        ncm = np.bincount(cl_idx[mask], minlength=nc).astype(float)
        return (Wb @ hc) / np.maximum(Wb @ ncm, 1)

    def dif(h, h0, mask):
        bt = boot(h, mask) - boot(h0, mask)
        lo, hi = np.percentile(bt, [2.5, 97.5])
        return f"{fd(h[mask].mean() - h0[mask].mean())} [{fd(lo)}, {fd(hi)}]"

    def kfit(mask, c):
        X = np.column_stack([dtv[mask], DB[c][mask]])
        yy = y[mask]
        ci = cl_idx[mask]
        try:
            b = logit(X, yy, np.ones(len(yy)))
        except np.linalg.LinAlgError:
            return "—"
        ks = []
        for i in range(nb):
            try:
                bb = logit(X, yy, Wb[i, ci], b)
                ks.append(-bb[1] / bb[0])
            except np.linalg.LinAlgError:
                pass
        lo, hi = np.percentile(ks, [2.5, 97.5])
        return f"{-b[1] / b[0]:.2f} [{lo:.2f}, {hi:.2f}]"

    pdist = pr.p_dist.values.astype(int)
    ptrack = pr.p_track.values
    say("## 1. 次走の答え合わせ\n")
    say("組= 次走が同じレースの 2 頭・前走が 60 日以内・前走も次走も注記なし・前走が同じ場・同じ距離・違う日・着順が違う"
        "(cloud/research_baba_classfirst.py と同じ)。3 つの直し方の値がそろう組だけ。距離の帯は前走の距離"
        "(〜1250m/1251〜1650m/1651m〜)。区間は開催日単位の復元抽出 "
        f"{nb:,} 回の 95%。的中= 前走の時計の差から引く秒の差を引いた向きで次走の先着を当てた割合(同値は 0.5)。"
        "縮尺 k= 先着をロジットで 前走の時計の差・引く秒の差 に当てたときの −(引く秒の係数)/(時計の係数)。"
        "k = 1 が引き方の丁度・1 より小さい= 引きすぎ・大きい= 引き足りない。\n")
    groups = [("全場", np.ones(len(pr), bool)), ("南関 4 場", np.isin(ptrack, NANKAN)),
              ("南関以外の 10 場", ~np.isin(ptrack, NANKAN))]
    summ = {}
    for gnm, GM in groups:
        say(f"### {gnm}(組 {int(GM.sum()):,}・開催日 {len(np.unique(cl_idx[GM])):,})\n")
        for mode, mnm in (("d", "良馬場比 d"), ("g", "同じ馬場状態比 g")):
            rows = []
            for bnm, lo, hi in (("全部", 0, 99999),) + DBANDS:
                MK = GM & (pdist >= lo) & (pdist <= hi)
                if MK.sum() < 200:
                    continue
                for m in METH:
                    c = f"{m}{mode}"
                    kk = kfit(MK, c)
                    summ[(gnm, mode, bnm, m)] = (H[c][MK].mean(), kk)
                    rows.append([bnm, f"{int(MK.sum()):,}", pct(H["Z"][MK].mean()), METH[m], pct(H[c][MK].mean()),
                                 dif(H[c], H["Z"], MK), "—" if m == "a" else dif(H[c], H[f"a{mode}"], MK), kk])
            say(f"{mnm}\n")
            table(["距離", "組", "補正なし", "直し方", "的中率", "補正なしとの差(点)", "(a) との差(点)", "縮尺 k"], rows)
        lap("次走 " + gnm)

    # 場ごと(d・全距離)
    say("### 場ごと(良馬場比 d・全距離・的中率)\n")
    rows = []
    for track in TRACKS:
        MK = ptrack == track
        if MK.sum() < 200:
            continue
        rows.append([track, f"{int(MK.sum()):,}", pct(H["Z"][MK].mean())]
                    + [pct(H[f"{m}d"][MK].mean()) for m in METH] + [dif(H["bd"], H["ad"], MK), dif(H["cd"], H["ad"], MK)])
    table(["場", "組", "補正なし"] + [METH[m] for m in METH] + ["(b)−(a)", "(c)−(a)"], rows)

    # 場ごとの倍率と当てになりやすさ((c) の d・nar-site RESULT_baba_nextrun_prod_20261025.md §4 と同じ決め方)
    say("### 場ごとのおすすめ倍率と当てになりやすさ((c) の良馬場比 d)\n")
    say("サイトの持ちタイム表の倍率(js/pages/race.js AN6_BABA_SCALE)を (c) 用に作り直すための表。決め方は nar-site "
        "RESULT_baba_nextrun_prod_20261025.md §4 と同じ= 場ごとの k を全体の k へ縮める(経験ベイズ・τ² = 場ごとの k の分散 − 誤差² の平均)。"
        "誤差= 95% 区間の幅 ÷ 3.92。おすすめ倍率= 縮めた k を 0〜1 に収めて小数 1 桁。"
        "当てになりやすさ: 高い= 縮めた k が 0.8 以上で、補正で的中率が有意に上がる/低い= 縮めた k が 0.4 未満か、補正で有意に下がる/ふつう= それ以外。\n")
    K_ALL = float(summ[("全場", "d", "全部", "c")][1].split(" ")[0])
    kt = []
    for track in TRACKS:
        MK = ptrack == track
        if MK.sum() < 200:
            continue
        ks = kfit(MK, "cd")
        k0 = float(ks.split(" ")[0])
        lo_, hi_ = (float(x) for x in ks.split("[")[1].rstrip("]").split(", "))
        bt = boot(H["cd"], MK) - boot(H["Z"], MK)
        kt.append((track, int(MK.sum()), k0, (hi_ - lo_) / 3.92, H["cd"][MK].mean() - H["Z"][MK].mean(),
                   *np.percentile(bt, [2.5, 97.5])))
    ka = np.array([x[2] for x in kt])
    se = np.array([x[3] for x in kt])
    tau2 = max(float(np.var(ka, ddof=1) - np.mean(se ** 2)), 1e-6)
    rows = []
    for (track, npair, k0, s0, dd, lo_, hi_), in_ in zip(kt, range(len(kt))):
        ksh = (k0 / s0 ** 2 + K_ALL / tau2) / (1 / s0 ** 2 + 1 / tau2)
        rec = min(max(round(ksh, 1), 0.0), 1.0)
        lv = "高い" if ksh >= 0.8 and lo_ > 0 else ("低い" if ksh < 0.4 or hi_ < 0 else "ふつう")
        rows.append([track, f"{npair:,}", f"{k0:.2f}", f"{s0:.2f}", f"{ksh:.2f}", f"{rec:.1f}",
                     f"{fd(dd)} [{fd(lo_)}, {fd(hi_)}]", lv])
    say(f"全体の k = {K_ALL:.2f}・τ² = {tau2:.4f}\n")
    table(["前走の場", "組の数", "場の k", "誤差", "縮めた k", "おすすめ倍率", "補正の差(点)と 95% 区間", "当てになりやすさ"], rows)

    # 日のレース数ごと((c) が効くはずの少ない日)
    say("### 前走の日のレース数ごと(良馬場比 d・全場・全距離・的中率)\n")
    say("レース数= 2 頭の前走の日のうち少ない方の、日の値に使えたレース数。\n")
    nmin = np.minimum(pr.nr_i.values, pr.nr_j.values)
    rows = []
    for nm_, lo, hi in (("4〜6 R", 4, 6), ("7〜9 R", 7, 9), ("10 R〜", 10, 99)):
        MK = (nmin >= lo) & (nmin <= hi)
        if MK.sum() < 200:
            continue
        rows.append([nm_, f"{int(MK.sum()):,}", pct(H["Z"][MK].mean())] + [pct(H[f"{m}d"][MK].mean()) for m in METH]
                    + [dif(H["cd"], H["bd"], MK)])
    table(["レース数", "組", "補正なし"] + [METH[m] for m in METH] + ["(c)−(b)"], rows)

    # ---------- 2. 奇数/偶数 ----------
    say("## 2. 奇数レースだけの日の値と偶数レースだけの日の値の一致(測る年)\n")
    say("日の値= その日×場の奇数(偶数)R のレースの差の中央値。両方 3 R 以上の日×場だけ。(a) は秒・(b)(c) は 1000m あたり。"
        "⛔(c) は両方を同じふだんへ寄せるので、一致は寄せた分だけ見かけ上高く出る(参考)。\n")
    hf = pd.DataFrame(HALF, columns=["mode", "track", "ds", "par", "a", "b", "n"])
    rows = []
    for mode in "dg":
        o = hf[(hf["mode"] == mode) & (hf.par == 1)].set_index(["track", "ds"])
        e = hf[(hf["mode"] == mode) & (hf.par == 0)].set_index(["track", "ds"])
        j = o.join(e, lsuffix="_o", rsuffix="_e", how="inner")
        cmap = VAL.get(("c", mode), {})
        bmap = VAL.get(("b", mode), {})
        # (c) の半分= その日の (c) と同じふだんへ、半分のレース数で寄せる(ふだん = (c·(n+5) − n·b)/5 で戻す)
        nmap = NR.get(mode, {})
        pri = np.array([(cmap[k] * (nmap[k] + SHRINK) - nmap[k] * bmap[k]) / SHRINK if k in cmap and k in nmap
                        else np.nan for k in j.index], dtype=float)
        co = (j.n_o * j.b_o + SHRINK * pri) / (j.n_o + SHRINK)
        ce = (j.n_e * j.b_e + SHRINK * pri) / (j.n_e + SHRINK)
        ok = ~np.isnan(pri)
        for m, xo, xe in (("a", j.a_o, j.a_e), ("b", j.b_o, j.b_e), ("c", co, ce)):
            xo, xe = np.asarray(xo)[ok], np.asarray(xe)[ok]
            rows.append([mode, METH[m], f"{int(ok.sum()):,}", f"{np.corrcoef(xo, xe)[0, 1]:.3f}",
                         f"{np.mean(np.abs(xo - xe)):.3f}"])
        for gnm, trs in (("南関 4 場", NANKAN),):
            sel = np.asarray([k[0] in trs for k in j.index]) & ok
            for m, xo, xe in (("a", j.a_o, j.a_e), ("b", j.b_o, j.b_e)):
                xo, xe = np.asarray(xo)[sel], np.asarray(xe)[sel]
                rows.append([mode, f"{METH[m]}({gnm})", f"{int(sel.sum()):,}", f"{np.corrcoef(xo, xe)[0, 1]:.3f}",
                             f"{np.mean(np.abs(xo - xe)):.3f}"])
    table(["値", "直し方", "日×場", "相関 r", "差の絶対値の平均"], rows)

    # ---------- 照合 ----------
    say("## 照合(本番の cloud/baba.py build_days が付けた d1/g1 と、この台本の (c) の値)\n")
    say("一致= 小数 2 桁の値が同じ。前走の日の範囲(" + TQ0s + "〜" + D1s + ")の日×場。\n")
    table(["値", "日×場", "一致"], [[m_, f"{MATCH[m_][0]:,}", f"{MATCH[m_][1]:,}({MATCH[m_][1] / max(MATCH[m_][0], 1) * 100:.1f}%)"]
                                   for m_ in "dg"])

    # ---------- 3. 値の大きさ ----------
    say("## 3. 値の大きさ(測る年・良馬場比 d)\n")
    rows = []
    for m in METH:
        v = np.array([x for (t, d), x in VAL.get((m, "d"), {}).items() if T0s <= d <= D1s])
        rows.append([METH[m], f"{len(v):,}", f"{np.mean(v):+.3f}", f"{np.std(v):.3f}",
                     f"{np.percentile(v, 5):+.2f}〜{np.percentile(v, 95):+.2f}"])
    table(["直し方", "日×場", "平均", "ばらつき(標準偏差)", "5〜95%"], rows)
    say("(a) は秒・(b)(c) は 1000m あたりの秒。\n")

    # ---------- まとめ ----------
    say("## まとめ(数字だけ・全場)\n")
    for mode in "dg":
        for bnm in ("全部",) + tuple(b[0] for b in DBANDS):
            xs = [f"{METH[m]} {pct(summ[('全場', mode, bnm, m)][0])}・k {summ[('全場', mode, bnm, m)][1].split(' ')[0]}"
                  for m in METH if ("全場", mode, bnm, m) in summ]
            say(f"- {mode} {bnm}: " + "/".join(xs))
    say(f"\n実行時間 {time.time() - t_start:.0f} 秒")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    log(f"書いた {out_path}")
    return 0


def main():
    if LOCAL:
        return run(None, log=lambda s: print(s, flush=True))
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い", flush=True)
        return 2
    rest = cond_stats.Rest(base, key)
    if key.startswith("sb_publishable_"):      # 手元の読むだけのキー= Bearer に載せると 401(apikey だけ送る)
        def get(q):
            r = urllib.request.Request(base + "/rest/v1/" + q, headers={"apikey": key, "Accept": "application/json"})
            for i in range(3):
                try:
                    with urllib.request.urlopen(r, timeout=120) as x:
                        return json.loads(x.read() or b"[]")
                except Exception:              # noqa: BLE001
                    if i == 2:
                        raise
                    time.sleep(3 * (i + 1))
        rest.get = get
    return run(rest, log=lambda s: print(s, flush=True))


if __name__ == "__main__":
    sys.exit(main())
