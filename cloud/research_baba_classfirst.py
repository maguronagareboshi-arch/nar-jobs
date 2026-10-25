#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-10-25)。馬場差の基準タイムを「クラス優先」に変える案を本番データで確かめる。

比べる作り方(計算は全部 cloud/baba.py の build_days をそのまま呼ぶ)=
  A 今の本番(going)/B classfirst・帯なしは場×距離へ/C classfirst・帯なしは外す/D going・帯なしは外す
物差しは nar-site RESULT_baba_window_20261025.md(KDSCOPE 版)と同じ定義=
  1 クラスの偏り 2 基準の届き方 3 金沢の月ごと+6か月以上の片寄り 4 奇数/偶数レースの一致 5 次走の答え合わせ
  6 照合(A と本番の nar_meta baba_diff・公開ファイル cond-stats/v1/baba-hist/<場>.json)
測る年 2025-09-28〜2026-09-27・ばんえい除く。

⛔本番 DB は REST の単純 select だけ(場ごと・年ごと・一意の order でページ送り)。書き込みなし。
  結果は docs/research-baba-classfirst/result.md(便が commit する)。

  python3 cloud/research_baba_classfirst.py            # 便(SUPABASE_URL / SUPABASE_SERVICE_KEY)
  環境変数 NB= 復元抽出の回数(既定 1000)
"""
import datetime as dtm
import os
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
OUT = os.path.join(ROOT, "docs", "research-baba-classfirst", "result.md")
T0 = dtm.date(2025, 9, 28)
D1 = dtm.date(2026, 9, 27)
TQ0 = T0 - dtm.timedelta(days=61)                 # 前走の日(次走の答え合わせ用)
H0 = TQ0 - dtm.timedelta(days=1095)               # 3 年の窓の始まり
H_START = H0 - dtm.timedelta(days=30)
KANAZAWA = "金沢"
TRACKS = list(baba.TRACK2PREFIX)                  # ばんえいは入っていない
PF2TR = {v: k for k, v in baba.TRACK2PREFIX.items()}

METH = {
    "A": ("A 今の本番(going)", "going", "dist"),
    "B": ("B クラス優先・帯なしは場×距離へ", "classfirst", "dist"),
    "C": ("C クラス優先・帯なしは外す", "classfirst", "drop"),
    "D": ("D 今の本番・帯なしは外す", "going", "drop"),
}
LVN = {"b": "細かい帯", "c": "字だけの帯", "d": "場×距離"}
BANDS = ["A", "B", "C", "AB混合", "BC混合", "オープン", "2・3歳オープン", "2歳", "3歳", "帯なし"]


def stages_of(m):
    return baba.CLASSFIRST_STAGES if METH[m][1] == "classfirst" else baba.GOING_STAGES


def stage_name(m, i):
    lv, sp = stages_of(m)[i]
    return f"{LVN[lv]}({sp // 365}年)"


def letter(pb):
    if not isinstance(pb, str):
        return "帯なし"
    if pb == "OP":
        return "オープン"
    if pb == "OPy":
        return "2・3歳オープン"
    if pb == "2y":
        return "2歳"
    if pb == "3y":
        return "3歳"
    if pb in ("AB", "BC", "AC"):
        return pb + "混合"
    return pb[0]


def pct(x):
    return f"{x * 100:.2f}%"


def fd(x):
    return f"{x * 100:+.2f}"


class Report:
    def __init__(self):
        self.lines = []

    def say(self, s=""):
        self.lines.append(s)

    def table(self, cols, rows):
        out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for r in rows:
            out.append("| " + " | ".join(str(x) for x in r) + " |")
        self.say("\n".join(out))
        self.say()


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


def run(rest, out_path=OUT, nb=None, today=None, log=print):
    t_start = time.time()
    nb = nb or int(os.environ.get("NB", "1000"))
    rng = np.random.default_rng(20261025)
    today = today or baba._today_jst()
    end = min(today - dtm.timedelta(days=1), dtm.date(2099, 1, 1))
    T0s, D1s, TQ0s, ENDs = T0.isoformat(), D1.isoformat(), TQ0.isoformat(), end.isoformat()

    def lap(s):
        log(f"{s} {time.time() - t_start:.0f}s")

    DAY = {}            # (m, mode) -> {(track, date): 値}
    RACE = []           # (m, mode, track, date, race, v, st, band)
    REACH = {(m, mode): np.zeros(len(stages_of(m)) + 1) for m in METH for mode in "dg"}
    DROP = {m: 0 for m in METH}
    KDAY = {}           # (track, date) -> その日の主な馬場状態(build_days の k と同じ決め方)
    COVER, cov_rows = {}, []
    runs_all, race_meta = [], {}
    n_wins = n_races = 0
    for track in TRACKS:
        wins, races = baba_hist.fetch_track(rest, track, H_START, end)
        n_wins += len(wins)
        n_races += len(races)
        smp = baba_hist.to_samples(track, wins, races)
        pf = baba.TRACK2PREFIX[track]
        band_r = {}
        for r in races:
            band_r[(r["race_date"], r["race_no"])] = baba.band_of(r.get("race_name"), track, r.get("race_kind"))
            if r.get("distance_m"):
                race_meta[(track, r["race_date"], r["race_no"])] = int(r["distance_m"])
        dates = sorted({s[1] for s in smp})
        first = dates[0] if dates else None
        COVER[track] = bool(first) and first <= (H0 + dtm.timedelta(days=31)).isoformat()
        nd = [len({d for d in dates if d.startswith(str(y))}) for y in (2022, 2023, 2024, 2025, 2026)]
        cov_rows.append([track, first or "—", dates[-1] if dates else "—"] + nd
                        + ["足りる" if COVER[track] else "⚠足りない"])
        gs_of = {}
        for s in smp:
            if s[5] and TQ0s <= s[1] <= ENDs:
                gs_of.setdefault(s[1], []).append(s[5])
        for d, gs in gs_of.items():
            KDAY[(track, d)] = statistics.mode(gs)
        targets = {d for d in dates if TQ0s <= d <= ENDs}
        for m, (_nm, base, nbm) in METH.items():
            info_of = {}
            days, _, _ = baba.build_days(smp, targets, base, today=today, rebuild_all=True,
                                         none_band=nbm, info_of=info_of)
            for d, cells in days.items():
                c = cells.get(pf) or {}
                for mode in "dg":
                    if mode in c:
                        DAY.setdefault((m, mode), {})[(track, d)] = c[mode]
            for (d, _tr), inf in info_of.items():
                if not (T0s <= d <= D1s):
                    continue
                DROP[m] += inf.get("drop", 0)
                for mode in "dg":
                    REACH[(m, mode)] += np.array(inf["reach_" + mode], dtype=float)
                    for rno, v in inf["race_" + mode].items():
                        st = int(np.bincount(inf["stage_" + mode][rno]).argmax())
                        RACE.append((m, mode, track, d, rno, float(v), st, letter(band_r.get((d, rno)))))
        runs_all += fetch_all_runs(rest, track, TQ0, D1)
        lap(f"{track} 1〜5着 {len(wins)}・レース {len(races)}・全着順(累計){len(runs_all)}")
    RACE = pd.DataFrame(RACE, columns=["m", "mode", "track", "ds", "race", "v", "st", "band"])

    # 本番の公開ファイル(全期間)と nar_meta
    prod = {}
    for track in TRACKS:
        pf = baba.TRACK2PREFIX[track]
        try:
            hd = baba_hist.read_old(rest, pf) or {}
        except Exception as e:                       # noqa: BLE001
            log(f"⚠ {pf}.json を読めない({e})")
            hd = {}
        for d, cell in hd.items():
            prod[(track, d)] = cell
    meta_days, meta_base = {}, None
    try:
        rows = rest.get(f"nar_meta?select=value&key=eq.{baba.META_KEY}")
        if rows and isinstance(rows[0].get("value"), dict):
            meta_days = rows[0]["value"].get("days") or {}
            meta_base = rows[0]["value"].get("base")
    except Exception as e:                           # noqa: BLE001
        log(f"⚠ nar_meta を読めない({e})")
    for mode in "dg":
        DAY[("PH", mode)] = {k: v[mode] for k, v in prod.items() if mode in v and TQ0s <= k[1] <= D1s}
    ALLM = list(METH) + ["PH"]
    MNAME = {m: METH[m][0] for m in METH}
    MNAME["PH"] = "参考: 本番の全期間ファイル"
    lap("材料")

    R = Report()
    say, table = R.say, R.table
    say("# 馬場差の基準を「クラス優先」に変える案の確かめ(本番データ・研究便)\n")
    say(f"本番 DB は読むだけ(REST の単純 select)。台本 cloud/research_baba_classfirst.py。測る年 {T0s}〜{D1s}・ばんえい除く。"
        f"作った日 {today.isoformat()}。読んだ行= 1〜5着 {n_wins:,}・レース {n_races:,}・全着順 {len(runs_all):,}。\n")
    say("作り方= " + "/".join(MNAME[m] for m in METH) + "。\n")
    say("## 0. 範囲確認\n")
    say(f"3 年の窓には {H0.isoformat()} からの材料が要る(前走の日 {TQ0s} の 3 年前)。読んだのは {H_START.isoformat()} 以降。\n")
    table(["場", "最初の日", "最後の日", "2022 開催日", "2023", "2024", "2025", "2026", "3年の窓"], cov_rows)
    nc_ok = sum(COVER.values())

    # ---------- 6. 照合(先に出す) ----------
    say("## 6. 照合(A= 今の本番の作り方を今のデータで組み直した値 と 本番に載っている値)\n")
    say("一致= 小数 1 桁の値の差が 0.05 未満。暫定(p)の日は除く。⛔本番の値はその日に組んで据え置いたもの"
        "(あとからデータが直っても組み直さない)なので、ずれはデータの直しでも出る。\n")
    rows, ex_rows = [], []
    srcs = [("nar_meta baba_diff(直近 90 日・base=" + str(meta_base) + ")",
             {(PF2TR.get(pf), d): c for d, cs in meta_days.items() for pf, c in (cs or {}).items()
              if not (c or {}).get("p")}),
            ("公開ファイル baba-hist(測る年)",
             {k: v for k, v in prod.items() if T0s <= k[1] <= D1s and not v.get("p")})]
    for nm, src in srcs:
        src = {k: v for k, v in src.items() if k[0] and k[1] <= ENDs}
        lo_d = min((k[1] for k in src), default=None)
        r_ = [nm, f"{lo_d or '—'}〜{max((k[1] for k in src), default='—')}"]
        for mode in "dg":
            mine = {k: v for k, v in DAY.get(("A", mode), {}).items() if lo_d and lo_d <= k[1] <= ENDs
                    and (nm.startswith("nar_meta") or T0s <= k[1] <= D1s)}
            theirs = {k: c[mode] for k, c in src.items() if mode in c}
            both = [k for k in theirs if k in mine]
            ok = sum(1 for k in both if abs(mine[k] - theirs[k]) < 0.05)
            r_ += [f"{ok:,}/{len(both):,}({ok / max(len(both), 1) * 100:.1f}%)",
                   f"{len([k for k in theirs if k not in mine]):,}", f"{len([k for k in mine if k not in theirs]):,}"]
            for k in sorted(both):
                if abs(mine[k] - theirs[k]) >= 0.05 and len(ex_rows) < 15:
                    ex_rows.append([nm.split("(")[0], mode, k[0], k[1], f"{mine[k]:+.1f}", f"{theirs[k]:+.1f}"])
        rows.append(r_)
    table(["相手", "日の範囲", "d 一致", "d 本番だけ", "d A だけ", "g 一致", "g 本番だけ", "g A だけ"], rows)
    if ex_rows:
        say("ずれた例(先頭 15 件)\n")
        table(["相手", "値", "場", "日", "A", "本番"], ex_rows)
    lap("照合")

    # ---------- 5. 次走の答え合わせ ----------
    ar = pd.DataFrame(runs_all)
    say("## 5. 次走の答え合わせ\n")
    if ar.empty:
        say("全着順の走が読めなかった。\n")
        pr = pd.DataFrame()
    else:
        ar["horse"] = ar.horse_name.astype(str) + "|" + ar.birth_date.astype(str)
        ar = ar[ar.horse_name.notna()].copy()
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
        NRM = [m for m in ALLM if DAY.get((m, "d")) and DAY.get((m, "g"))]   # 公開ファイルが読めなければ参考は外す
        for m in NRM:
            for mode in "dg":
                col = f"{m}{mode}"
                dm = DAY.get((m, mode), {})
                r2[col] = [dm.get((t, d), np.nan) for t, d in zip(r2.p_track, r2.p_race_date)]
                VC.append(col)
        r2 = r2.dropna(subset=VC)
        cols = ["runner_number", "fin", "p_race_date", "p_tsec"] + VC
        gk = ["track", "race_date", "race_no", "p_track", "p_dist"]
        pr = r2[gk + cols].merge(r2[gk + cols], on=gk, suffixes=("_i", "_j"))
        pr = pr[(pr.runner_number_i < pr.runner_number_j) & (pr.p_race_date_i != pr.p_race_date_j)
                & (pr.fin_i != pr.fin_j)].reset_index(drop=True)
    if len(pr):
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
            if not ks:
                return f"{-b[1] / b[0]:.2f}"
            lo, hi = np.percentile(ks, [2.5, 97.5])
            return f"{-b[1] / b[0]:.2f} [{lo:.2f}, {hi:.2f}]"

        say("組= 次走が同じレースの 2 頭・前走が 60 日以内・前走も次走も注記なし・前走が同じ場・同じ距離・違う日・着順が違う。"
            f"全部の作り方の値がそろう組だけ(並べた数字は同じ組)。区間は開催日単位の復元抽出 {nb:,} 回の 95%。"
            "的中= 前走の時計の差から前走の日の値の差を引いた向きで次走の先着を当てた割合(同値は 0.5)。"
            "縮尺 k= 先着をロジットで 前走の時計の差・日の値の差 に当てたときの −(日の値の係数)/(時計の係数)。\n")
        masks = [("全場", np.ones(len(pr), bool))]
        if nc_ok < len(TRACKS):
            masks.append(("3年の窓が足りる場だけ", np.isin(pr.p_track.values, [t for t in TRACKS if COVER[t]])))
        for mnm, MK in masks:
            if not MK.any():
                continue
            say(f"### {mnm}(組 {int(MK.sum()):,}・開催日 {len(np.unique(cl_idx[MK])):,}・補正なし {pct(H['Z'][MK].mean())})\n")
            for mode, mnm2 in (("d", "良馬場比 d"), ("g", "同じ馬場状態比 g")):
                rows = []
                for m in NRM:
                    c = f"{m}{mode}"
                    rows.append([MNAME[m], pct(H[c][MK].mean()), dif(H[c], H["Z"], MK),
                                 "—" if m == "A" else dif(H[c], H[f"A{mode}"], MK), kfit(MK, c)])
                say(f"{mnm2}\n")
                table(["作り方", "的中率", "補正なしとの差(点)と 95% 区間", "A との差(点)と 95% 区間", "縮尺 k と 95% 区間"], rows)
            lap("次走 " + mnm)
    else:
        say("組が無かった。\n")

    # ---------- 1. クラスの偏り ----------
    say("## 1. クラスの偏り(同じ日×場の中で レースの差 −そのレースを除いた日の値)\n")
    say("測る年のレースだけ。除いた日の値= 同じ日×場の残りのレースの差の中央値(残り 3 R 以上)。"
        "区間は日×場単位の復元抽出 300 回の 95%。偏りの大きさ= 帯ごとの平均(30 R 以上の帯)の 2 乗平均の平方根(秒)。\n")
    rms_tab = {}
    RB = pd.DataFrame()
    if len(RACE):
        RACE["ex"] = np.nan
        for _k, g in RACE.groupby(["m", "mode", "track", "ds"], sort=False):
            v = g.v.values
            if len(v) < 4:
                continue
            RACE.loc[g.index, "ex"] = [np.median(np.delete(v, i)) for i in range(len(v))]
        RACE["b"] = RACE.v - RACE.ex
        RB = RACE.dropna(subset=["b"]).copy()
        RB["cl"] = RB.track.astype(str) + RB.ds
        for mode, mnm2 in (("d", "良馬場比 d"), ("g", "同じ馬場状態比 g")):
            rows = []
            for m in METH:
                sub = RB[(RB.m == m) & (RB["mode"] == mode)]
                cu, ci = np.unique(sub.cl.values, return_inverse=True)
                W = np.stack([np.bincount(rng.integers(0, len(cu), len(cu)), minlength=len(cu))
                              for _ in range(300)]).astype(float) if len(cu) else None
                r_ = [MNAME[m]]
                means = []
                for b in BANDS:
                    s = sub[sub.band == b]
                    if len(s) < 30:
                        r_.append(f"—({len(s)})")
                        continue
                    ii = ci[sub.band.values == b]
                    num = W @ np.bincount(ii, weights=s.b.values, minlength=len(cu))
                    den = np.maximum(W @ np.bincount(ii, minlength=len(cu)).astype(float), 1)
                    lo, hi = np.percentile(num / den, [2.5, 97.5])
                    mu = s.b.mean()
                    means.append(mu)
                    r_.append(f"{mu:+.2f} [{lo:+.2f}, {hi:+.2f}]({len(s):,})")
                rms = float(np.sqrt(np.mean(np.square(means)))) if means else float("nan")
                rms_tab[(m, mode)] = rms
                r_.append(f"{rms:.3f}")
                rows.append(r_)
            say(f"### {mnm2}(帯ごとの平均・秒・括弧は R 数)\n")
            table(["作り方"] + BANDS + ["偏りの大きさ"], rows)
        say("### 退避の段ごとの偏り(レースの 1〜5着で一番多く使った段で分けた)\n")
        rows = []
        for m in METH:
            for i in range(len(stages_of(m))):
                r_ = [MNAME[m], stage_name(m, i)]
                for mode in "dg":
                    sub = RB[(RB.m == m) & (RB["mode"] == mode) & (RB.st == i)]
                    mm_ = [sub[sub.band == b].b.mean() for b in BANDS if (sub.band == b).sum() >= 30]
                    r_ += [f"{len(sub):,}", f"{sub.b.abs().mean():.2f}" if len(sub) else "—",
                           f"{np.sqrt(np.mean(np.square(mm_))):.3f}" if mm_ else "—"]
                rows.append(r_)
        table(["作り方", "段", "d の R 数", "d のずれの絶対値の平均(秒)", "d 偏りの大きさ", "g の R 数",
               "g のずれの絶対値の平均", "g 偏りの大きさ"], rows)
    lap("偏り")

    # ---------- 2. 基準の届き方 ----------
    say("## 2. 基準の届き方(測る年の 1〜5着の時計 1 本ごとに、どの段の基準を使ったか)\n")
    say("帯なしで外した= 帯が読めない走をその日の値から外した本数(C・D だけ。d と g で同じ)。\n")
    rows = []
    for m in METH:
        for mode in "dg":
            a = REACH[(m, mode)]
            tot = a.sum() + DROP[m]
            if not tot:
                continue
            segs = [f"{stage_name(m, i)} {a[i] / tot * 100:.1f}%" for i in range(len(stages_of(m)))]
            rows.append([MNAME[m], mode, f"{int(tot):,}", "/".join(segs), f"{a[-1] / tot * 100:.1f}%",
                         f"{DROP[m] / tot * 100:.1f}%"])
    table(["作り方", "値", "時計の本数", "段ごとの割合", "基準なし", "帯なしで外した"], rows)
    ndays = len({k for k in KDAY if T0s <= k[1] <= D1s})
    rows = []
    for m in ALLM:
        r_ = [MNAME[m]]
        for mode in "dg":
            n = sum(1 for k in DAY.get((m, mode), {}) if T0s <= k[1] <= D1s)
            r_.append(f"{n:,}/{ndays:,}({n / max(ndays, 1) * 100:.1f}%)")
        rows.append(r_)
    say("日×場に値が出た割合(測る年)\n")
    table(["作り方", "d", "g"], rows)

    # ---------- 3. 変化への追いつき ----------
    say("## 3. 変化への追いつき\n")
    say("### 金沢(2026-03-17 に砂厚を変更)の月ごとの良の日の d 平均(秒・括弧は日数)\n")

    def months_between(a, b):
        out, y, mo = [], a[0], a[1]
        while (y, mo) <= b:
            out.append(f"{y}-{mo:02d}")
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        return out

    def monthly(m, track, mlist):
        out = {}
        for (t, ds), v in DAY.get((m, "d"), {}).items():
            if t != track:
                continue
            k = prod.get((t, ds), {}).get("k") if m == "PH" else KDAY.get((t, ds))
            if k != "良" or ds[:7] not in mlist:
                continue
            out.setdefault(ds[:7], []).append(v)
        return out

    months = months_between((2026, 1), (2026, 9))
    rows = []
    for m in ALLM:
        mo = monthly(m, KANAZAWA, months)
        rows.append([MNAME[m]] + [f"{np.mean(mo[p]):+.2f}({len(mo[p])})" if p in mo else "—" for p in months])
    table(["作り方"] + months, rows)
    say("### 月平均(良の日の d)が 6 か月以上続けて同じ向きに 0.5 秒を超えた場×作り方(2025-10〜2026-09)\n")
    mall = months_between((2025, 10), (2026, 9))
    rows = []
    for track in TRACKS:
        for m in ALLM:
            mo = monthly(m, track, mall)
            best, cur, sg, st0, bst = 0, 0, 0, None, None
            for i, p in enumerate(mall):
                v = np.mean(mo[p]) if p in mo else 0
                s = 1 if v > 0.5 else (-1 if v < -0.5 else 0)
                if s != 0 and s == sg:
                    cur += 1
                else:
                    cur, sg, st0 = (1, s, i) if s != 0 else (0, 0, None)
                if cur > best:
                    best, bst = cur, (st0, i, sg)
            if best >= 6:
                vals = [np.mean(mo[p]) for p in mall[bst[0]:bst[1] + 1]]
                rows.append([track, MNAME[m], f"{mall[bst[0]]}〜{mall[bst[1]]}", f"{best}",
                             "遅い側" if bst[2] > 0 else "速い側", f"{np.mean(vals):+.2f}"])
    if rows:
        table(["場", "作り方", "期間", "月数", "向き", "その間の平均(秒)"], rows)
    else:
        say("該当なし。\n")

    # ---------- 4. 奇数/偶数レース ----------
    say("## 4. 奇数レースだけの日の値と偶数レースだけの日の値の一致(測る年)\n")
    say("日の値= その日×場の奇数(偶数)R のレースの差の中央値。両方 3 R 以上の日×場だけ。\n")
    rows = []
    if len(RACE):
        RACE["rn"] = pd.to_numeric(RACE.race, errors="coerce")
        for m in METH:
            r_ = [MNAME[m]]
            for mode in "dg":
                sub = RACE[(RACE.m == m) & (RACE["mode"] == mode)]
                o = sub[sub.rn % 2 == 1].groupby(["track", "ds"]).v.agg(["median", "size"])
                e = sub[sub.rn % 2 == 0].groupby(["track", "ds"]).v.agg(["median", "size"])
                j = o.join(e, lsuffix="_o", rsuffix="_e", how="inner")
                j = j[(j.size_o >= 3) & (j.size_e >= 3)]
                if len(j) < 3:
                    r_ += [f"{len(j):,}", "—", "—", "—"]
                    continue
                r = np.corrcoef(j.median_o, j.median_e)[0, 1]
                dd = j.median_o - j.median_e
                r_ += [f"{len(j):,}", f"{r:.3f}", f"{dd.mean():+.3f}", f"{dd.abs().mean():.3f}"]
            rows.append(r_)
    table(["作り方", "d 日×場", "d 相関 r", "d 平均差(奇−偶・秒)", "d 差の絶対値の平均", "g 日×場", "g 相関 r",
           "g 平均差", "g 差の絶対値の平均"], rows)

    # ---------- まとめ(数字だけ) ----------
    say("## まとめ(数字だけ)\n")
    if len(pr):
        say("- 次走の的中率 d: " + "・".join(f"{MNAME[m]} {pct(H[f'{m}d'].mean())}" for m in METH)
            + "/g: " + "・".join(f"{MNAME[m]} {pct(H[f'{m}g'].mean())}" for m in METH))
    if rms_tab:
        say("- クラスの偏りの大きさ(秒)d: " + "・".join(f"{MNAME[m]} {rms_tab.get((m, 'd'), float('nan')):.3f}" for m in METH)
            + "/g: " + "・".join(f"{MNAME[m]} {rms_tab.get((m, 'g'), float('nan')):.3f}" for m in METH))
    say("- 細かい帯の基準に届いた割合 d: " + "・".join(
        f"{MNAME[m]} {sum(REACH[(m, 'd')][i] for i, (lv, _) in enumerate(stages_of(m)) if lv == 'b') / max(REACH[(m, 'd')].sum() + DROP[m], 1) * 100:.1f}%"
        for m in METH))
    say("\n## 方法\n")
    say("- 日の値は全部 cloud/baba.py の build_days(as-of・前日まで・1〜5着・同じ着順・各段 8 本以上・d は良/g は同じ馬場状態・"
        "レース差 3 頭以上・日は 4 R 以上・小数 1 桁)で組んだ。材料の読み方は cloud/baba_hist.py と同じ(同着は速い方・距離の無いレースは捨てる)。")
    say("- A・D の段= 細かい帯(1年)→字だけの帯(1年)→場×距離(1年)。B・C の段= 細かい帯(1年)→細かい帯(3年)→字だけの帯(1年)→字だけの帯(3年)→場×距離(1年)。"
        "帯なし(band_of が None)を B は場×距離へ・C と D は外す。")
    say("- KDSCOPE 版との違い= 材料は本番の nar_runs/nar_races(競走名・重賞区分・馬場状態)。芝ダは分けない。"
        "次走の前走は地方(ばんえい除く)の走だけで探す(間に中央の走があっても見えない)。馬は 馬名+生年月日 で数える。")
    say(f"\n実行時間 {time.time() - t_start:.0f} 秒")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(R.lines) + "\n")
    log(f"書いた {out_path}")
    return 0


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い", flush=True)
        return 2
    return run(cond_stats.Rest(base, key), log=lambda s: print(s, flush=True))


if __name__ == "__main__":
    sys.exit(main())
