#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-10-26)。読み物「言い伝えをデータで確かめる」7 本(T1〜T7)の集計・実装 A。
約束の正本= nar-site research/lore-articles/SPEC.md(実装 B と同じ定義で別に作り、数字を照合する)。

⛔本番 DB は REST の単純 select だけ(場ごと・年ごと・一意の order でページ送り)。書き込み・rpc なし。
  結果は out/A/lore.json と out/A/summary.md(便が artifact で上げる)。

  python3 cloud/research_lore_a.py            # 便(SUPABASE_URL / SUPABASE_SERVICE_KEY)
"""
import datetime as dtm
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baba  # noqa: E402
import baba_hist  # noqa: E402
import cond_stats  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "out", "A")
P0, P1 = dtm.date(2024, 10, 1), dtm.date(2026, 9, 30)
Y1_END = dtm.date(2025, 9, 30)
H0 = dtm.date(2021, 10, 1)            # 前走・地区の履歴と馬場差の 3 年の窓のために読む始まり
TRACKS = ["門別", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢", "笠松", "名古屋", "園田", "姫路", "高知", "佐賀"]
AREA = {"門別": "北海道", "盛岡": "岩手", "水沢": "岩手", "浦和": "南関東", "船橋": "南関東", "大井": "南関東",
        "川崎": "南関東", "金沢": "金沢", "笠松": "東海", "名古屋": "東海", "園田": "兵庫", "姫路": "兵庫",
        "高知": "高知", "佐賀": "佐賀"}
JRA_AREA = "中央"
DROP_PAT = ("出走取消", "競走除外")
INT_BINS = [(1, 13), (14, 20), (21, 27), (28, 41), (42, 62), (63, 90), (91, 180), (181, 365), (366, 10 ** 6)]
INT_LBL = ["1〜13", "14〜20", "21〜27", "28〜41", "42〜62", "63〜90", "91〜180", "181〜365", "366以上"]
BW_LBL = ["−10以下", "−9〜−4", "−3〜+3", "+4〜+9", "+10〜+19", "+20以上"]
FS_LBL = ["8頭以下", "9〜10頭", "11頭以上"]
ZONES = ["昼", "夕方", "夜"]
SEED = 20261026

DECISIONS = [
    "外す走= finish_note に「出走取消」か「競走除外」を含む走。1 着(finish=1)の無いレースは全走を外す。競走中止は残す(着順なし= 3 着内ではない)。",
    "頭数= そのレースで外さなかった走の数(出走頭数)。T1 の頭数別・T2 の内中外もこの頭数。内= 馬番 ≤ 頭数/3・外= 馬番 > 頭数×2/3・中= 残り。",
    "馬の同一視= 馬名+生年月日(nar_runs の horse_name・birth_date)。中央の走は nar_jra_horses の 馬名+生年月日 で kb_horse_id に結んだ nar_jra_runs。",
    "前走の履歴は 2021-10-01 から読む(それより前の走は見えない= 3 年以上休んだ馬は初出走扱い)。帯広(ばんえい)の走は読まない(平地との行き来はほぼ無い)。",
    "前の走= そのレース日より前の日の、外さなかった走(地方 14 場+中央。中央は finish_note に取消・除外を含む走を外す)。",
    "人気比の期待値= 対象期間 2 年・14 場の外さなかった走のうち人気のある走で出した 場×人気 の 3 着内率。人気比= 実際の 3 着内数 ÷ 期待値の合計(人気のある走だけ)。",
    "T1 の単勝の倍率= nar_run_facts.win_odds_close(発走直前の単勝の最終の点)。無い走は中央値から外し、取れた割合を書く。",
    "T1 の 2 着内率= 着順 ≤ 2。年ごとの勝率は 1 年目/2 年目。",
    "T2 の距離の 100 レース= 対象 2 年に場×距離で数えた外さなかったレース数(1 着のあるレース)。枠番= nar_runs.gate。",
    "T3 の馬場差= cloud/baba.py の build_days を本番の既定(classfirst= 細かい帯 1 年→細かい帯 3 年→字だけの帯 1 年→字だけの帯 3 年→場×距離 1 年・帯の読めない走は外す)で as-of に組んだ、レースごとの 1〜5 着の差の中央値(3 頭以上)。良馬場比 d を主に、同じ馬場状態比 g も lore.json に。参考に 1 年の窓だけ(going 段・帯なしは外す)の d も lore.json に。",
    "T3 の時間帯= nar_races.post_time の時:分。昼 〜15:59・夕方 16:00〜17:59・夜 18:00〜。季節そろえ= 場×年月(YYYY-MM)で 2 つの時間帯がどちらも 10 レース以上の組だけ、平均の差(後−先)を 2 つのレース数の和で重み付けして平均。馬場状態はレースの going(良/良以外)。",
    "T4 の間隔= レース日 − 前の走の日(日数)。",
    "T5 の地区= 走った場の地区(遠征・交流競走もその場の地区で数える)。地区が前の走と変わったら 1 走目から数え直す。初出走から始まる続きは移籍ではない。比べ相手= 見える範囲で移籍で始まっていない続きの 2 走目以降(前走も同じ地区)。前の地区の中央/地方= その続きが始まる直前の走の地区。",
    "T6 の増減= nar_runs.body_weight_change(発表)。無ければ 前の走(地方)の body_weight との差。前の走が中央で発表の増減も無い走は外す。区分の境は整数 kg。",
    "T7 の騎手= nar_runs.jockey から空白と記号(▲△☆◇★)を除いた文字で比べる。前の走が同じ地区・間隔 62 日以内・両方の騎手名がある走だけ。",
    "率は % を小数 1 位で四捨五入。人気比は小数 2 位。",
]


def log(s):
    print(s, flush=True)


def is_drop(note):
    s = str(note or "")
    return any(p in s for p in DROP_PAT)


def pct(a, b):
    return round(a / b * 100, 1) if b else None


def post_min(v):
    m = re.fullmatch(r"\s*(\d{1,2}):?(\d{2})(?::\d{2})?\s*", str(v or ""))
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def zone_of(mins):
    if mins is None or mins != mins:
        return None
    if mins < 16 * 60:
        return "昼"
    if mins < 18 * 60:
        return "夕方"
    return "夜"


def int_bucket(d):
    for (lo, hi), lb in zip(INT_BINS, INT_LBL):
        if lo <= d <= hi:
            return lb
    return None


def bw_bucket(x):
    if x <= -10:
        return BW_LBL[0]
    if x <= -4:
        return BW_LBL[1]
    if x <= 3:
        return BW_LBL[2]
    if x <= 9:
        return BW_LBL[3]
    if x <= 19:
        return BW_LBL[4]
    return BW_LBL[5]


def fs_bucket(n):
    return FS_LBL[0] if n <= 8 else (FS_LBL[1] if n <= 10 else FS_LBL[2])


def norm_jockey(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    t = re.sub(r"[\s　▲△☆◇★]", "", str(s))
    return t or None


# ---------- 読む ----------
def years(since, until):
    y = since.year
    while y <= until.year:
        yield max(since, dtm.date(y, 1, 1)).isoformat(), min(until, dtm.date(y, 12, 31)).isoformat()
        y += 1


def fetch(rest):
    races, runs, facts = [], [], []
    for track in TRACKS:
        tq = cond_stats.enc(track)
        for lo, hi in years(H0, P1):
            rng = f"&track=eq.{tq}&race_date=gte.{lo}&race_date=lte.{hi}"
            races += rest.paged("nar_races?select=track,race_date,race_no,distance_m,race_name,going,race_kind,post_time"
                                + rng, "race_date.asc,race_no.asc")
            runs += rest.paged("nar_runs?select=track,race_date,race_no,runner_number,gate,horse_name,birth_date,finish,"
                               "finish_note,popularity,jockey,body_weight,body_weight_change,time_sec" + rng,
                               "race_date.asc,race_no.asc,runner_number.asc,horse_name.asc")
        for lo, hi in years(P0, P1):
            rng = f"&track=eq.{tq}&race_date=gte.{lo}&race_date=lte.{hi}"
            try:
                facts += rest.paged("nar_run_facts?select=track,race_date,race_no,umaban,win_odds_close" + rng,
                                    "race_date.asc,race_no.asc,umaban.asc")
            except Exception as e:                   # noqa: BLE001
                log(f"⚠ nar_run_facts {track} {lo} を読めない({e})")
        log(f"{track} 読んだ(累計 レース {len(races):,}・走 {len(runs):,}・facts {len(facts):,})")
    jh, jr, jerr = [], [], None
    try:
        jh = rest.paged("nar_jra_horses?select=kb_horse_id,horse_name,birth_date", "kb_horse_id.asc")
        for lo, hi in years(H0, P1):
            jr += rest.paged("nar_jra_runs?select=kb_horse_id,race_date,race_no,place,finish,finish_note"
                             f"&race_date=gte.{lo}&race_date=lte.{hi}", "race_date.asc,kb_horse_id.asc,race_no.asc")
        log(f"中央 馬 {len(jh):,}・走 {len(jr):,}")
    except Exception as e:                           # noqa: BLE001
        jerr = str(e)
        log(f"⚠ 中央の走を読めない({e})")
    return races, runs, facts, jh, jr, jerr


# ---------- 組み立て ----------
def prepare(races, runs, jh, jr):
    """→ (R= 外さなかった地方の走(全期間)と前走の列, RC= レース表, info)"""
    rc = pd.DataFrame(races)
    ru = pd.DataFrame(runs)
    ru["finish"] = pd.to_numeric(ru["finish"], errors="coerce")
    won = set(map(tuple, ru.loc[ru.finish == 1, ["track", "race_date", "race_no"]].drop_duplicates().values.tolist()))
    key3 = list(zip(ru.track, ru.race_date, ru.race_no))
    ru["has_win"] = [k in won for k in key3]
    ru["drop"] = ru.finish_note.map(is_drop)
    info = {"nar_runs_read": int(len(ru)), "dropped_scratch": int(ru["drop"].sum()),
            "dropped_no_winner_runs": int((~ru.has_win & ~ru["drop"]).sum())}
    R = ru[ru.has_win & ~ru["drop"]].copy()
    R["fs"] = R.groupby(["track", "race_date", "race_no"]).runner_number.transform("size")
    R["horse"] = R.horse_name.astype(str) + "|" + R.birth_date.astype(str)
    R = R[R.horse_name.notna()].copy()
    R["date"] = pd.to_datetime(R.race_date)
    R["area"] = R.track.map(AREA)
    R["src"] = "N"
    R["pop"] = pd.to_numeric(R.popularity, errors="coerce")
    R["bw"] = pd.to_numeric(R.body_weight, errors="coerce")
    R["bwc"] = pd.to_numeric(R.body_weight_change, errors="coerce")
    R["jk"] = R.jockey.map(norm_jockey)
    R["rn"] = pd.to_numeric(R.runner_number, errors="coerce")
    R["gt"] = pd.to_numeric(R.gate, errors="coerce")
    # 中央
    J = pd.DataFrame(columns=["horse", "date", "area", "src"])
    info["jra_horses"] = len(jh)
    info["jra_runs_read"] = len(jr)
    if jh and jr:
        h = pd.DataFrame(jh)
        h["horse"] = h.horse_name.astype(str) + "|" + h.birth_date.astype(str)
        h = h[h.horse_name.notna()].drop_duplicates("kb_horse_id")
        j = pd.DataFrame(jr)
        j = j[~j.finish_note.map(is_drop)]
        j = j[~j.place.astype(str).isin(TRACKS)]
        j = j.merge(h[["kb_horse_id", "horse"]], on="kb_horse_id", how="inner")
        j["date"] = pd.to_datetime(j.race_date)
        j["area"] = JRA_AREA
        j["src"] = "J"
        J = j[["horse", "date", "area", "src"]].drop_duplicates(["horse", "date"])
        nar_horses = set(R.horse)
        info["jra_runs_linked_to_nar_horses"] = int(J.horse.isin(nar_horses).sum())
        J = J[J.horse.isin(nar_horses)]
    R["idx"] = np.arange(len(R))
    A = pd.concat([R[["horse", "date", "area", "src", "idx", "jk", "bw"]],
                   J.assign(idx=-1, jk=None, bw=np.nan)], ignore_index=True)
    A = A.sort_values(["horse", "date", "src"], kind="mergesort").reset_index(drop=True)
    # 同じ日の重なり(地方と中央)は地方を残す
    A = A[~A.duplicated(["horse", "date"], keep="last") | (A.src == "N")]
    A = A.drop_duplicates(["horse", "date", "idx"])
    g = A.groupby("horse", sort=False)
    for c in ["date", "area", "src", "jk", "bw"]:
        A["p_" + c] = g[c].shift(1)
    start = A.p_date.isna() | (A.area != A.p_area)
    A["streak"] = start.cumsum()
    A["n_in_area"] = A.groupby("streak").cumcount() + 1
    A["origin"] = A.p_area.where(start).groupby(A.streak).transform("first")
    A = A[A.idx >= 0].set_index("idx").sort_index()
    for c in ["p_date", "p_area", "p_src", "p_jk", "p_bw", "n_in_area", "origin"]:
        R[c] = A[c].values
    R["gap"] = (R.date - pd.to_datetime(R.p_date)).dt.days
    return R, rc, info


def stat_row(df, key=None):
    n = len(df)
    w = int((df.finish == 1).sum())
    t3 = int((df.finish <= 3).sum())
    out = {} if key is None else dict(key)
    out.update({"runs": n, "win": w, "win_pct": pct(w, n), "top3": t3, "top3_pct": pct(t3, n)})
    if "exp" in df:
        m = df.exp.notna()
        e = float(df.exp[m].sum())
        out["pop_runs"] = int(m.sum())
        out["pop_ratio"] = round(float((df.finish[m] <= 3).sum()) / e, 2) if e else None
    return out


def grouped(df, by, order=None):
    rows = []
    for k, g in df.groupby(by, sort=False):
        k = k if isinstance(k, tuple) else (k,)
        rows.append(stat_row(g, zip(by if isinstance(by, list) else [by], k)))
    if order:
        col = by if isinstance(by, str) else by[-1]
        rk = {v: i for i, v in enumerate(order)}
        tk = {v: i for i, v in enumerate(TRACKS)}
        rows.sort(key=lambda r: tuple(tk.get(r.get("track"), 99) if c == "track" else rk.get(r[c], 99)
                                      for c in (by if isinstance(by, list) else [by])))
    return rows


def compute(R, rc, facts, info, today=None, rest_samples=None, jra_ok=True):
    out = {"decisions": DECISIONS, "period": [P0.isoformat(), P1.isoformat()], "info": info}
    T = R[(R.date >= pd.Timestamp(P0)) & (R.date <= pd.Timestamp(P1))].copy()
    T["fin3"] = T.finish.fillna(99)
    T["finish"] = T.finish.fillna(99)
    T["year"] = np.where(T.date <= pd.Timestamp(Y1_END), "1年目", "2年目")
    # 期待値(場×人気)
    tp = T[T["pop"].notna()]
    expv = tp.groupby(["track", "pop"]).finish.apply(lambda s: float((s <= 3).mean()))
    T["exp"] = [expv.get((t, p), np.nan) if not np.isnan(p) else np.nan for t, p in zip(T.track, T["pop"])]
    out["expected_top3"] = [{"track": t, "pop": int(p), "top3_rate": round(v, 4)} for (t, p), v in expv.items()]
    info["target_runs"] = int(len(T))
    info["target_races"] = int(T.groupby(["track", "race_date", "race_no"]).ngroups)
    info["target_runs_no_pop"] = int(T["pop"].isna().sum())
    info["jra_used"] = bool(jra_ok)

    # ---------- T1 ----------
    races_T = T.drop_duplicates(["track", "race_date", "race_no"])[["track", "race_date", "race_no", "fs"]]
    p1 = T[T["pop"] == 1].copy()
    if facts:
        f = pd.DataFrame(facts)
        f["win_odds_close"] = pd.to_numeric(f.win_odds_close, errors="coerce")
        f = f.rename(columns={"umaban": "rn"})
        f["rn"] = pd.to_numeric(f.rn, errors="coerce")
        p1 = p1.merge(f[["track", "race_date", "race_no", "rn", "win_odds_close"]].drop_duplicates(
            ["track", "race_date", "race_no", "rn"]), on=["track", "race_date", "race_no", "rn"], how="left")
    else:
        p1["win_odds_close"] = np.nan
    cnt = p1.groupby(["track", "race_date", "race_no"]).size()
    ties = cnt[cnt >= 2]
    t1 = []
    for tr in TRACKS:
        g = p1[p1.track == tr]
        if not len(g):
            continue
        n = len(g)
        r = {"track": tr, "runs": n, "win_pct": pct((g.finish == 1).sum(), n),
             "top2_pct": pct((g.finish <= 2).sum(), n), "top3_pct": pct((g.finish <= 3).sum(), n),
             "odds_median": round(float(g.win_odds_close.median()), 1) if g.win_odds_close.notna().any() else None,
             "odds_coverage_pct": pct(g.win_odds_close.notna().sum(), n),
             "avg_field": round(float(races_T[races_T.track == tr].fs.mean()), 2),
             "races": int((races_T.track == tr).sum()), "tie_races": int((ties.reset_index().track == tr).sum())}
        for y in ("1年目", "2年目"):
            gy = g[g.year == y]
            r["win_pct_" + y] = pct((gy.finish == 1).sum(), len(gy))
            r["runs_" + y] = int(len(gy))
        for lb in FS_LBL:
            gb = g[g.fs.map(fs_bucket) == lb]
            r["win_pct_" + lb] = pct((gb.finish == 1).sum(), len(gb))
            r["runs_" + lb] = int(len(gb))
        t1.append(r)
    out["T1"] = {"by_track": t1, "tie_races_total": int(len(ties)), "tie_runs_total": int(ties.sum()),
                 "races_without_pop1": int(len(races_T) - len(cnt))}

    # ---------- T2 ----------
    rcd = rc.copy()
    rcd["distance_m"] = pd.to_numeric(rcd.distance_m, errors="coerce")
    T = T.merge(rcd[["track", "race_date", "race_no", "distance_m", "going", "post_time", "race_name"]],
                on=["track", "race_date", "race_no"], how="left")
    rt = T.drop_duplicates(["track", "race_date", "race_no"])
    dcount = rt.groupby(["track", "distance_m"]).size()
    keep = [k for k, v in dcount.items() if v >= 100]
    T["pos"] = np.where(T.rn <= T.fs / 3, "内", np.where(T.rn > T.fs * 2 / 3, "外", "中"))
    gate_rows, pos_rows = [], []
    for tr, dist in sorted(keep, key=lambda k: (TRACKS.index(k[0]), k[1])):
        g = T[(T.track == tr) & (T.distance_m == dist)]
        for gt in range(1, 9):
            s = g[g.gt == gt]
            gate_rows.append({"track": tr, "distance": int(dist), "gate": gt, "runs": int(len(s)),
                              "top3_pct": pct((s.finish <= 3).sum(), len(s))})
        for p in ("内", "中", "外"):
            s = g[g.pos == p]
            pos_rows.append({"track": tr, "distance": int(dist), "races": int(dcount[(tr, dist)]), "pos": p,
                             "runs": int(len(s)), "top3_pct": pct((s.finish <= 3).sum(), len(s)),
                             "win_pct": pct((s.finish == 1).sum(), len(s))})
    pos_all = []
    for tr in TRACKS:
        g = T[T.track == tr]
        for p in ("内", "中", "外"):
            s = g[g.pos == p]
            pos_all.append({"track": tr, "pos": p, "runs": int(len(s)), "top3_pct": pct((s.finish <= 3).sum(), len(s)),
                            "win_pct": pct((s.finish == 1).sum(), len(s))})
    out["T2"] = {"distances_kept": [{"track": t, "distance": int(d), "races": int(dcount[(t, d)])} for t, d in keep],
                 "gate": gate_rows, "pos_by_distance": pos_rows, "pos_by_track": pos_all}

    # ---------- T3 ----------
    out["T3"] = t3(R, rc, T, today)

    # ---------- T4 ----------
    T["ib"] = T.gap.map(lambda d: int_bucket(int(d)) if pd.notna(d) else None)
    t4 = T[T.ib.notna()]
    out["T4"] = {"first_runs_excluded": int(T.gap.isna().sum()),
                 "all": grouped(t4, "ib", INT_LBL), "by_track": grouped(t4, ["track", "ib"], INT_LBL)}

    # ---------- T5 ----------
    T["tcat"] = None
    tr_m = T.origin.notna()
    T.loc[tr_m, "tcat"] = np.where(T.n_in_area[tr_m] >= 4, "4走目以降", T.n_in_area[tr_m].astype(int).astype(str) + "走目")
    T.loc[~tr_m & (T.n_in_area >= 2), "tcat"] = "比べ相手(移籍なし)"
    T["okind"] = np.where(T.origin == JRA_AREA, "中央から", np.where(tr_m, "地方から", ""))
    t5 = T[T.tcat.notna()]
    cats = ["1走目", "2走目", "3走目", "4走目以降", "比べ相手(移籍なし)"]
    out["T5"] = {"all": grouped(t5, "tcat", cats),
                 "by_origin": grouped(t5[t5.okind != ""], ["okind", "tcat"], cats),
                 "first_runs_excluded": int((T.origin.isna() & (T.n_in_area == 1)).sum())}

    # ---------- T6 ----------
    calc = T.bw - pd.to_numeric(T.p_bw, errors="coerce")
    T["bwd"] = np.where(T.bwc.notna(), T.bwc, calc)
    T["bwsrc"] = np.where(T.bwc.notna(), "発表", np.where(calc.notna(), "前走との差", ""))
    t6 = T[T.p_date.notna() & T.bw.notna() & pd.Series(T.bwd).notna()].copy()
    t6["bb"] = t6.bwd.map(bw_bucket)
    out["T6"] = {"source_counts": {k: int(v) for k, v in t6.bwsrc.value_counts().items()},
                 "excluded_no_prev": int(T.p_date.isna().sum()),
                 "excluded_no_weight": int((T.p_date.notna() & (T.bw.isna() | pd.Series(T.bwd).isna())).sum()),
                 "all": grouped(t6, "bb", BW_LBL), "gap_le41": grouped(t6[t6.gap <= 41], "bb", BW_LBL)}

    # ---------- T7 ----------
    m7 = (T.p_area == T.area) & (T.gap <= 62) & T.jk.notna() & T.p_jk.notna()
    t7 = T[m7].copy()
    t7["jc"] = np.where(t7.jk == t7.p_jk, "同じ騎手", "乗り替わり")
    out["T7"] = {"all": grouped(t7, "jc", ["同じ騎手", "乗り替わり"]),
                 "by_track": grouped(t7, ["track", "jc"], ["同じ騎手", "乗り替わり"]),
                 "excluded_no_jockey": int(((T.p_area == T.area) & (T.gap <= 62) & ~(T.jk.notna() & T.p_jk.notna())).sum())}

    # ---------- 公式照合の見本 ----------
    rng = np.random.default_rng(SEED)
    rk = rt[["track", "race_date", "race_no"]].values.tolist()
    pick = [rk[i] for i in rng.choice(len(rk), 5, replace=False)] if len(rk) >= 5 else rk
    samp = []
    for tr, d, no in pick:
        g = R[(R.track == tr) & (R.race_date == d) & (R.race_no == no)].sort_values("rn")
        pt = rc[(rc.track == tr) & (rc.race_date == d) & (rc.race_no == no)].post_time
        samp.append({"track": tr, "race_date": d, "race_no": int(no),
                     "post_time": str(pt.iloc[0]) if len(pt) else None,
                     "runs": [{"rn": int(x.rn), "gate": None if pd.isna(x["gt"]) else int(x["gt"]),
                               "pop": None if pd.isna(x["pop"]) else int(x["pop"]),
                               "finish": None if pd.isna(x.finish) else int(x.finish),
                               "bw": None if pd.isna(x.bw) else int(x.bw),
                               "bwc": None if pd.isna(x.bwc) else int(x.bwc)} for _, x in g.iterrows()]})
    out["official_check_sample"] = samp
    return out


def t3(R, rc, T, today):
    """レースごとのふだんとの差(秒)を build_days で組んで時間帯に分ける"""
    today = today or dtm.date(2026, 10, 26)
    rcx = rc.copy()
    RV = {}
    for base, nb, tag in (("classfirst", "drop", "main"), ("going", "drop", "going1y")):
        for tr in TRACKS:
            rr = R[(R.track == tr) & (R.finish >= 1) & (R.finish <= baba.TOP_N) & R.time_sec.notna()
                   & R.finish_note.isna()]
            wins = rr[["race_date", "race_no", "finish", "runner_number", "time_sec"]].to_dict("records")
            races = rcx[rcx.track == tr].to_dict("records")
            smp = baba_hist.to_samples(tr, wins, races)
            targets = {s[1] for s in smp if P0.isoformat() <= s[1] <= P1.isoformat()}
            info_of = {}
            baba.build_days(smp, targets, base, today=today, rebuild_all=True, none_band=nb, info_of=info_of)
            for (d, _t), inf in info_of.items():
                for mode in "dg":
                    for rno, v in inf["race_" + mode].items():
                        RV[(tag, mode, tr, d, int(rno))] = float(v)
    rt = T.drop_duplicates(["track", "race_date", "race_no"]).copy()
    rt["pm"] = rt.post_time.map(post_min)
    rt["zone"] = rt.pm.map(zone_of)
    rt["good"] = np.where(rt.going.astype(str) == "良", "良", "良以外")
    rt["ym"] = rt.race_date.str[:7]
    miss = [{"track": tr, "races": int((rt.track == tr).sum()), "no_post_time": int(((rt.track == tr) & rt.zone.isna()).sum())}
            for tr in TRACKS]
    res = {"no_post_time": miss, "no_post_time_total": int(rt.zone.isna().sum())}
    for tag in ("main", "going1y"):
        for mode in "dg":
            rt["v"] = [RV.get((tag, mode, t, d, int(n)), np.nan) for t, d, n in zip(rt.track, rt.race_date, rt.race_no)]
            s = rt[rt.v.notna() & rt.zone.notna()]
            zrows = []
            for tr in TRACKS:
                for z in ZONES:
                    g = s[(s.track == tr) & (s.zone == z)]
                    if len(g):
                        zrows.append({"track": tr, "zone": z, "races": int(len(g)), "mean": round(float(g.v.mean()), 3),
                                      "median": round(float(g.v.median()), 3)})
            pairs = [("夜", "昼"), ("夕方", "昼"), ("夜", "夕方")]
            mrows = []
            for gk, gsub in (("全部", s), ("良", s[s.good == "良"]), ("良以外", s[s.good == "良以外"])):
                for a, b in pairs:
                    tot_w, tot, cells = {}, {}, {}
                    for (tr, ym), g in gsub.groupby(["track", "ym"]):
                        ga, gb = g[g.zone == a], g[g.zone == b]
                        if len(ga) >= 10 and len(gb) >= 10:
                            w = len(ga) + len(gb)
                            dlt = float(ga.v.mean() - gb.v.mean())
                            for key in (tr, "全場"):
                                tot_w[key] = tot_w.get(key, 0) + w
                                tot[key] = tot.get(key, 0) + w * dlt
                                cells[key] = cells.get(key, 0) + 1
                    for key in TRACKS + ["全場"]:
                        if key in tot_w:
                            mrows.append({"going": gk, "pair": f"{a}−{b}", "track": key, "months": cells[key],
                                          "weight_races": tot_w[key], "diff": round(tot[key] / tot_w[key], 3)})
            res[f"{tag}_{mode}"] = {"races_with_value": int(rt.v.notna().sum()), "by_zone": zrows, "season_matched": mrows}
    return res


# ---------- 書く ----------
def md_table(cols, rows):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join("—" if x is None else str(x) for x in r) + " |")
    return "\n".join(out) + "\n"


def summary(o):
    L = ["# 言い伝えをデータで確かめる 集計(実装 A)\n",
         f"期間 {o['period'][0]}〜{o['period'][1]}・地方平地 14 場。台本 nar-jobs cloud/research_lore_a.py。\n",
         "## 決めたこと(約束で決まっていない所)\n"]
    L += [f"{i + 1}. {d}" for i, d in enumerate(o["decisions"])]
    L.append("")
    inf = o["info"]
    L.append("## 読んだ量\n")
    L.append(md_table(["項目", "値"], [[k, v] for k, v in inf.items()]))
    t1 = o["T1"]
    L.append("## T1 1番人気がいちばん勝つ場は\n")
    L.append(f"1 番人気が 2 頭のレース {t1['tie_races_total']} 件({t1['tie_runs_total']} 走)・1 番人気の無いレース {t1['races_without_pop1']} 件。\n")
    L.append(md_table(["場", "走数", "勝率", "2着内率", "3着内率", "単勝中央値", "倍率の取れた割合", "平均頭数", "1年目 勝率(走)", "2年目 勝率(走)",
                       "8頭以下 勝率(走)", "9〜10頭", "11頭以上", "同率2頭"],
                      [[r["track"], r["runs"], r["win_pct"], r["top2_pct"], r["top3_pct"], r["odds_median"], r["odds_coverage_pct"],
                        r["avg_field"], f"{r['win_pct_1年目']}({r['runs_1年目']})", f"{r['win_pct_2年目']}({r['runs_2年目']})"]
                       + [f"{r['win_pct_' + lb]}({r['runs_' + lb]})" for lb in FS_LBL] + [r["tie_races"]] for r in t1["by_track"]]))
    t2 = o["T2"]
    L.append("## T2 内枠は有利か\n")
    L.append("### 場ごと(全距離)内・中・外\n")
    L.append(md_table(["場", "位置", "走数", "3着内率", "勝率"],
                      [[r["track"], r["pos"], r["runs"], r["top3_pct"], r["win_pct"]] for r in t2["pos_by_track"]]))
    L.append("### 場×距離(100 レース以上)内・中・外\n")
    L.append(md_table(["場", "距離", "レース", "位置", "走数", "3着内率", "勝率"],
                      [[r["track"], r["distance"], r["races"], r["pos"], r["runs"], r["top3_pct"], r["win_pct"]] for r in t2["pos_by_distance"]]))
    L.append("### 場×距離 枠番 1〜8(3着内率・括弧は走数)\n")
    gk = {}
    for r in t2["gate"]:
        gk.setdefault((r["track"], r["distance"]), []).append(f"{r['top3_pct']}({r['runs']})")
    L.append(md_table(["場", "距離"] + [f"{i}枠" for i in range(1, 9)], [[k[0], k[1]] + v for k, v in gk.items()]))
    t3 = o["T3"]
    L.append("## T3 ナイターは時計が速いか(良馬場比 d・本番の作り方・+ は遅い)\n")
    L.append(f"発走時刻の無いレース 計 {t3['no_post_time_total']} 件。" + "・".join(
        f"{r['track']} {r['no_post_time']}/{r['races']}" for r in t3["no_post_time"] if r["no_post_time"]) + "\n")
    m = t3["main_d"]
    L.append(f"値の出たレース {m['races_with_value']:,}。\n")
    L.append(md_table(["場", "時間帯", "レース数", "平均(秒)", "中央値(秒)"],
                      [[r["track"], r["zone"], r["races"], r["mean"], r["median"]] for r in m["by_zone"]]))
    L.append("### 季節をそろえた比べ(場×年月で両方 10 レース以上・重み= 2 つのレース数の和)\n")
    L.append(md_table(["馬場", "差", "場", "組(月)", "重みのレース数", "差(秒)"],
                      [[r["going"], r["pair"], r["track"], r["months"], r["weight_races"], r["diff"]] for r in m["season_matched"]]))

    def st_tbl(rows, keys):
        return md_table(keys + ["走数", "勝率", "3着内率", "人気比(人気のある走)"],
                        [[r[k] for k in keys] + [r["runs"], r["win_pct"], r["top3_pct"], f"{r['pop_ratio']}({r['pop_runs']})"]
                         for r in rows])
    L.append("## T4 休み明けはどのくらい走るか\n")
    L.append(f"中央の走を前走に含めたか= {'含めた' if inf.get('jra_used') else '含めていない(地方だけ)'}。初出走で外した {o['T4']['first_runs_excluded']:,} 走。\n")
    L.append(st_tbl(o["T4"]["all"], ["ib"]))
    L.append("### 場ごと\n")
    L.append(st_tbl(o["T4"]["by_track"], ["track", "ib"]))
    L.append("## T5 移籍初戦はどのくらい走るか\n")
    L.append(st_tbl(o["T5"]["all"], ["tcat"]))
    L.append("### 前の地区が中央か地方か\n")
    L.append(st_tbl(o["T5"]["by_origin"], ["okind", "tcat"]))
    t6 = o["T6"]
    L.append("## T6 馬体重が大きく増えたら\n")
    L.append("増減の出どころ= " + "・".join(f"{k} {v:,}" for k, v in t6["source_counts"].items())
             + f"。前の走なしで外した {t6['excluded_no_prev']:,}・馬体重なしで外した {t6['excluded_no_weight']:,}。\n")
    L.append("### 全走\n")
    L.append(st_tbl(t6["all"], ["bb"]))
    L.append("### 間隔 41 日以内\n")
    L.append(st_tbl(t6["gap_le41"], ["bb"]))
    L.append("## T7 乗り替わりはどのくらい響くか\n")
    L.append(f"騎手名が無くて外した {o['T7']['excluded_no_jockey']:,} 走。\n")
    L.append(st_tbl(o["T7"]["all"], ["jc"]))
    L.append("### 場ごと\n")
    L.append(st_tbl(o["T7"]["by_track"], ["track", "jc"]))
    L.append("## 公式との照合(DB の値・無作為 5 レース)\n")
    for s in o["official_check_sample"]:
        L.append(f"### {s['track']} {s['race_date']} {s['race_no']}R 発走 {s['post_time']}\n")
        L.append(md_table(["馬番", "枠", "人気", "着", "体重", "増減"],
                          [[r["rn"], r["gate"], r["pop"], r["finish"], r["bw"], r["bwc"]] for r in s["runs"]]))
    return "\n".join(L) + "\n"


def run(rest, out_dir=OUT_DIR):
    t0 = time.time()
    races, runs, facts, jh, jr, jerr = fetch(rest)
    log(f"読み終わり {time.time() - t0:.0f}s")
    R, rc, info = prepare(races, runs, jh, jr)
    info["jra_error"] = jerr
    o = compute(R, rc, facts, info, jra_ok=bool(jh and jr))
    o["info"]["seconds"] = round(time.time() - t0)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "lore.json"), "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(summary(o))
    log(f"書いた {out_dir} {time.time() - t0:.0f}s")
    return 0


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い", flush=True)
        return 2
    return run(cond_stats.Rest(base, key))


if __name__ == "__main__":
    sys.exit(main())
