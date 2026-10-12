# -*- coding: utf-8 -*-
"""他場版 v3n の並び読み AI(2026-10-12・確かめ = v3 の out/v3n_seq.md・決め書 out/v3n_seq_plan.md・研究 src/kochi/k29_seq.py)。学習はしない。

地方 14 場 + 中央の過去 10 走を読む小さな模型(南関の決め 24 と同じ形・GRU + レースの中の注意)が、第 5 版の 3 着内の率の「外した分」を出す。
確かめ 2025-09〜26-08・10 場: 全馬 3 着内 +47.5 ± 8.6 ×10^-4 /頭・本命 76.38 → 76.98%。人気・オッズは使わない。
南関の版との違い: 今回の場 14 列・今日の馬場・体重・増減は使わない(朝の版)・南関の SI は使わない(空)・「南関の走りの数」→「同じ場の走りの数」。
材料 = v3n_daily が落とした公式の表(runs・races・jra・jrah)。時計のならし・重み = 固定ファイル(V3N_SEQ の v3n_seq_std.csv・v3n_seq_model.npz・
v3n_seq_prod.json = 暗号化したリリース v3n-seq-20261012)。無ければ None を返す = 第 5 版のまま。計算は numpy(南関の seq2_live.forward)。
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'v3'))
import seq2_live as S2  # noqa: E402  runs_all・forward・corner_pos は南関の本番の部品をそのまま使う

SEQ = Path(os.environ.get('V3N_SEQ', 'v3n_seq'))
K = ['track', 'race_date', 'race_no', 'umaban']
H, MAXN = 10, 16
LOC = ['大井', '川崎', '船橋', '浦和', '門別', '盛岡', '水沢', '金沢', '笠松', '名古屋', '園田', '姫路', '高知', '佐賀']


def build(d, std, day, tracks):
    """研究 k29_seq.build と同じ式(時計のならしは固定の表・SI は空)。予想する行 = day の tracks の行。→ T・hist(n, 10, 48)・ctx(n, 28)"""
    fin = pd.to_numeric(d.finish, errors='coerce')
    stop = fin.isna() | d.finish_note.isin(['中止', '競走中止', '落馬'])
    isj = d.jra.to_numpy() == 1
    d['nh'] = np.where(isj, d.fs.fillna(14), d.groupby('rkey').hk.transform('size')).astype(float)
    d['Y3'] = ((fin <= 3) & ~stop).astype(float)
    d['Y1'] = ((fin == 1) & ~stop).astype(float)
    fr = (fin - 1) / np.maximum(d.nh - 1, 1)
    d['frel'] = np.where(stop, 1.0, np.where(isj, fr.clip(0, 1), fr))
    d['stop'] = stop.astype(float)
    d['go'] = d.going.map(S2.GO).fillna(-1).astype(int)
    d['gab'] = np.where(d.go >= 2, 1, 0)
    grp = ['plc', 'turf', 'distance_m', 'gab']
    st = std[grp + ['mean', 'std']].copy()
    st['plc'], st['turf'], st['distance_m'], st['gab'] = st.plc.astype(str), st.turf.astype(float), st.distance_m.astype(float), st.gab.astype(int)
    d['distance_m'] = d.distance_m.astype(float)
    d = d.merge(st, on=grp, how='left')
    isj = d.jra.to_numpy() == 1
    ts = d.time_sec.where((d.stop == 0) & (d.time_sec > 0))
    d['tz'] = (-(ts - d['mean']) / d['std']).clip(-4, 4)
    win = ts.groupby(d.rkey).transform('min')
    d['behind'] = np.where(isj, np.nan, ((ts - win) / (d.distance_m / 1000)).clip(0, 5))
    l3 = d.last3f.where((d.stop == 0) & (d.last3f > 0))
    d['l3rel'] = np.where(isj, np.nan, (l3 - l3.groupby(d.rkey).transform('min')).clip(0, 5))
    d['l3j'] = np.where(isj, (l3 - d.rl3).clip(-3, 5), 0.0)
    d['dn'] = (pd.to_datetime(d.race_date) - pd.Timestamp('2014-01-01')).dt.days.astype(float)
    d['race_no'], d['umaban'] = d.race_no.astype(int), d.umaban.astype(int)
    d = d.sort_values(['hk', 'dn', 'jra', 'race_no']).reset_index(drop=True)
    bw = d.body_weight.where(d.body_weight > 0)
    d['bw_prev'] = bw.groupby(d.hk).shift(1)
    lp1 = np.log(d.prize1.where(d.prize1 > 0))
    na = np.full(len(d), np.nan)
    run = np.column_stack([
        d.tz.fillna(0), d.tz.isna(), d.behind.fillna(2.5) / 2 - 0.5, d.l3rel.fillna(2) / 2 - 0.5, d.frel, d.Y1, d.Y3, d.stop, (d.nh - 11) / 3,
        (d.distance_m.fillna(1500) - 1500) / 300, d.turf, d.jra, *[(d.ven == i) for i in range(len(S2.VEN))], *[(d.go == i) for i in range(4)],
        (lp1.fillna(14) - 14), lp1.isna(), (d.carried_weight.fillna(55) - 55) / 2, (bw.fillna(470) - 470) / 30,
        (bw - d.bw_prev).clip(-30, 30).fillna(0) / 10,
        (d.p1 / d.nh).fillna(0.5), (d.p4 / d.nh).fillna(0.5), d.p1.isna(),
        np.full(len(d), 0.0), np.full(len(d), 64 / 25 - 2.5), np.full(len(d), 50 / 35 - 1.4), np.isnan(na),  # 南関の SI は空(研究と同じ)
        pd.Series(d.l3j).fillna(0).to_numpy() / 2]).astype(np.float32)
    FR = run.shape[1]
    tgt = np.where(d.track.isin(tracks) & (d.race_date == day))[0]
    hk, dn = d.hk.to_numpy(), d.dn.to_numpy()
    pos = d.groupby('hk').cumcount().to_numpy()
    dist, ven = d.distance_m.to_numpy(float), d.ven.to_numpy()
    hist = np.zeros((len(tgt), H, FR + 4), np.float32)
    for k in range(1, H + 1):
        j = tgt - k
        ok = (pos[tgt] >= k) & (j >= 0)
        jj, ii = j[ok], np.where(ok)[0]
        same = (hk[jj] == hk[tgt[ii]]) & (dn[jj] < dn[tgt[ii]])
        jj, ii = jj[same], ii[same]
        s = H - k
        hist[ii, s, :FR] = run[jj]
        hist[ii, s, FR] = np.log1p(dn[tgt[ii]] - dn[jj]) / 3 - 1.5
        hist[ii, s, FR + 1] = np.nan_to_num((dist[tgt[ii]] - dist[jj]) / 300)
        hist[ii, s, FR + 2] = (ven[tgt[ii]] == ven[jj])
        hist[ii, s, FR + 3] = 1.0
    hist = hist.astype(np.float16).astype(np.float32)  # 研究は float16 で持った = 同じ丸めにそろえる
    T = d.iloc[tgt].reset_index(drop=True)
    nprev = hist[:, :, -1].sum(1)
    gap = np.where(nprev > 0, hist[:, H - 1, FR], 0)
    nsame = (hist[:, :, FR + 2] * hist[:, :, FR + 3]).sum(1)
    mon = pd.to_datetime(T.race_date).dt.month.to_numpy()
    lpt = np.log(T.prize1.where(T.prize1 > 0))
    ctx = np.column_stack([
        (T.distance_m.fillna(1500) - 1500) / 300, *[(T.track == v) for v in LOC],
        lpt.fillna(14) - 14, (T.carried_weight.fillna(55) - 55) / 2, (T.age.fillna(4) - 4) / 2, T.sex.eq('牝'), T.sex.eq('セ'),
        (T.nh - 11) / 3, (T.gate.fillna(4) - 4) / 3,
        gap, nprev == 0, nprev / 10, nsame / 10, np.sin(mon / 6 * np.pi), np.cos(mon / 6 * np.pi)]).astype(np.float32)
    return T, hist, ctx


def prep(off, day, tracks, log=print):
    """→ {'W': 重み 3 本, 'ix': {(場, R, 馬番): 行}, 'hist', 'ctx'} か None(固定ファイル・公式の表が無い = 第 5 版のまま)"""
    need = [SEQ / 'v3n_seq_std.csv', SEQ / 'v3n_seq_model.npz', SEQ / 'v3n_seq_prod.json', Path(off) / 'runs.parquet', Path(off) / 'jra.parquet']
    if not all(p.exists() for p in need):
        log('並び読み 固定ファイルか公式の表が無い = 第 5 版のまま', [p.name for p in need if not p.exists()])
        return None
    meta = json.loads((SEQ / 'v3n_seq_prod.json').read_text(encoding='utf-8'))
    Z = np.load(SEQ / 'v3n_seq_model.npz')
    Ws = [{k.split('/', 1)[1]: Z[k].astype(float) for k in Z.files if k.startswith(f's{s}/')} for s in meta['seeds']]
    std = pd.read_csv(SEQ / 'v3n_seq_std.csv', encoding='utf-8')
    d = S2.runs_all(off)
    T, hist, ctx = build(d, std, day, tracks)
    assert hist.shape[1:] == (meta['H'], meta['fh']) and ctx.shape[1] == meta['fc'], '並び読みの材料の形が模型と合わない'
    ix = {(str(a), int(b), int(c)): i for i, (a, b, c) in enumerate(zip(T.track, T.race_no, T.umaban))}
    nprev = hist[:, :, -1].sum(1)
    log('並び読み 出走', len(T), '・過去 0 走', round(float((nprev == 0).mean()), 3) if len(T) else '-',
        '・10 走そろう', round(float((nprev == H).mean()), 3) if len(T) else '-')
    return {'W': Ws, 'ix': ix, 'hist': hist, 'ctx': ctx}


def resid(S, track, rno, nums):
    """nums = そのレースの馬番(朝の出走馬)→ 馬ごとの外した分(3 本の平均・logit)か None(材料に無い馬がいる)"""
    if S is None:
        return None
    idx = [S['ix'].get((str(track), int(rno), int(u))) for u in nums]
    if not 2 <= len(idx) <= MAXN or any(i is None for i in idx):
        return None
    idx = np.asarray(idx)
    return np.mean([S2.forward(W, S['hist'][idx], S['ctx'][idx]) for W in S['W']], axis=0)
