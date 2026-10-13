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


def build(d, std, day, tracks, g=False):
    """研究 k29_seq.build と同じ式(時計のならしは固定の表・SI は空)。予想する行 = day の tracks の行。→ T・hist(n, 10, 48)・ctx(n, 28)
    g = True(第 8 版の直前版だけ)= runs_all の騎手・調教師から過去走ごとに 5 列を足す(研究 k44_seq3.build と同じ式)→ hist(n, 10, 53)"""
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
    nn_ = NEW if g else 0
    if nn_:
        G = g_cols(d)
    tgt = np.where(d.track.isin(tracks) & (d.race_date == day))[0]
    hk, dn = d.hk.to_numpy(), d.dn.to_numpy()
    pos = d.groupby('hk').cumcount().to_numpy()
    dist, ven = d.distance_m.to_numpy(float), d.ven.to_numpy()
    hist = np.zeros((len(tgt), H, FR + nn_ + 4), np.float32)
    T_ = FR + nn_
    for k in range(1, H + 1):
        j = tgt - k
        ok = (pos[tgt] >= k) & (j >= 0)
        jj, ii = j[ok], np.where(ok)[0]
        same = (hk[jj] == hk[tgt[ii]]) & (dn[jj] < dn[tgt[ii]])
        jj, ii = jj[same], ii[same]
        s = H - k
        hist[ii, s, :FR] = run[jj]
        if nn_:
            it = tgt[ii]
            hist[ii, s, FR] = (G['jk'][jj] == G['jk'][it])
            hist[ii, s, FR + 1] = G['loc'][jj] & (G['tr'][jj] == G['tr'][it])
            hist[ii, s, FR + 2] = np.nan_to_num(G['jr'][jj] - 0.25) * 4
            hist[ii, s, FR + 3] = np.nan_to_num(G['jr'][it] - G['jr'][jj]) * 4
            hist[ii, s, FR + 4] = np.nan_to_num(G['b3'][jj]) / 2
        hist[ii, s, T_] = np.log1p(dn[tgt[ii]] - dn[jj]) / 3 - 1.5
        hist[ii, s, T_ + 1] = np.nan_to_num((dist[tgt[ii]] - dist[jj]) / 300)
        hist[ii, s, T_ + 2] = (ven[tgt[ii]] == ven[jj])
        hist[ii, s, T_ + 3] = 1.0
    hist = hist.astype(np.float16).astype(np.float32)  # 研究は float16 で持った = 同じ丸めにそろえる
    T = d.iloc[tgt].reset_index(drop=True)
    nprev = hist[:, :, -1].sum(1)
    gap = np.where(nprev > 0, hist[:, H - 1, T_], 0)
    nsame = (hist[:, :, T_ + 2] * hist[:, :, T_ + 3]).sum(1)
    mon = pd.to_datetime(T.race_date).dt.month.to_numpy()
    lpt = np.log(T.prize1.where(T.prize1 > 0))
    ctx = np.column_stack([
        (T.distance_m.fillna(1500) - 1500) / 300, *[(T.track == v) for v in LOC],
        lpt.fillna(14) - 14, (T.carried_weight.fillna(55) - 55) / 2, (T.age.fillna(4) - 4) / 2, T.sex.eq('牝'), T.sex.eq('セ'),
        (T.nh - 11) / 3, (T.gate.fillna(4) - 4) / 3,
        gap, nprev == 0, nprev / 10, nsame / 10, np.sin(mon / 6 * np.pi), np.cos(mon / 6 * np.pi)]).astype(np.float32)
    return T, hist, ctx


NEW = 5  # 第 8 版の過去走ごとの列の数


def g_cols(d):
    """第 8 版(v3 の out/v3n_seq3_judge.md・研究 src/kochi/k44_seq3.py)の 5 列の元: 騎手・調教師・その時点の騎手の 3 着内率・3 着馬との時計差。
    騎手の率 = 地方の走りを騎手 × 日で集め、その日より前の全部(30 走分の 0.25 で縮める)。中央の走りは騎手なし。
    今日の行で騎手・調教師が欠けたら、どの走りとも「同じ」にならない印にする(研究は欠け 0)。"""
    n = len(d)
    loc = d.jra.to_numpy() == 0
    rk = pd.factorize(d.rkey)[0]
    tsv = d.time_sec.where((d.stop == 0) & (d.time_sec > 0)).to_numpy(float)
    o = np.lexsort((np.where(np.isnan(tsv), np.inf, tsv), rk))
    rnk = np.empty(n, np.int64)
    rnk[o] = pd.Series(rk[o]).groupby(rk[o]).cumcount().to_numpy()
    sel3 = (rnk == 2) & ~np.isnan(tsv)
    t3 = pd.Series(rk).map(pd.Series(tsv[sel3], index=rk[sel3])).to_numpy(float)
    b3 = np.where(loc, np.clip((tsv - t3) / (d.distance_m.to_numpy(float) / 1000), -3, 5), np.nan)
    jv, tv = d.jockey.to_numpy(object), d.trainer.to_numpy(object)
    miss_j = pd.isna(jv)
    miss_t = pd.isna(tv)
    idx = np.arange(n).astype(str)
    jk = np.where(loc, np.where(miss_j, np.char.add('?', idx), jv.astype(str)), '?J')
    J_ = pd.DataFrame({'jk': jk, 'dn': d.dn.to_numpy(), 'y': d.Y3.to_numpy(float)})[loc & ~miss_j]
    day = J_.groupby(['jk', 'dn']).y.agg(['sum', 'size']).reset_index().sort_values(['jk', 'dn'])
    day['W'] = day.groupby('jk')['sum'].cumsum() - day['sum']
    day['N'] = day.groupby('jk')['size'].cumsum() - day['size']
    day['jr'] = (day.W + 0.25 * 30) / (day.N + 30)
    jr = pd.DataFrame({'jk': jk, 'dn': d.dn.to_numpy()}).merge(day[['jk', 'dn', 'jr']], on=['jk', 'dn'], how='left').jr.to_numpy()
    jr = np.where(loc & ~miss_j, jr, np.nan)
    tr = np.where(loc, np.where(miss_t, np.char.add('?t', idx), tv.astype(str)), '?J')
    return {'loc': loc, 'b3': b3, 'jk': jk, 'jr': jr, 'tr': tr}


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


# ================================================================ 直前版(2026-10-12・確かめ = v3 の out/v3n_seq_day.md)
# 朝の版に当日の 7 列(今日の馬場 4・体重・前走からの増減・体重の欠け)を足した重み(V3N_SEQ_DAY・暗号化リリース v3n-seq-day-20261012)。
# 対 朝の版 全馬 +16.4 ± 11.8 ×10^-4 /頭・本命 76.98 → 77.18%・本命が替わる 6.9%。直前便(nar-ai-last)の頭で prep_day・周ごとに resid_day。
DAY_SEQ = Path(os.environ.get('V3N_SEQ_DAY', 'v3n_seq_day'))
GOING = {'良': 0, '稍重': 1, '稍': 1, '重': 2, '不良': 3, '不': 3}
NH_COL = 20  # 今回の列の頭数((nh − 11) / 3)= 取消の後の頭数で入れ直す


def prep_day(off, day, tracks, out, log=print):
    """直前便の頭: 公式の表から今日の出走馬の過去 10 走と朝の 28 列・前走の体重を out(npz)に。書けたらそのパス・無理なら None"""
    need = [DAY_SEQ / 'v3n_seq_std.csv', DAY_SEQ / 'v3n_seq_model.npz', DAY_SEQ / 'v3n_seq_prod.json', Path(off) / 'runs.parquet']
    if not all(p.exists() for p in need):
        log('並び読み 直前版 固定ファイルか公式の表が無い = 作らない', [p.name for p in need if not p.exists()])
        return None
    std = pd.read_csv(DAY_SEQ / 'v3n_seq_std.csv', encoding='utf-8')
    meta = json.loads((DAY_SEQ / 'v3n_seq_prod.json').read_text(encoding='utf-8'))
    d = S2.runs_all(off)
    T, hist, ctx = build(d, std, day, tracks, int(meta.get('new', 0)) == NEW)  # 第 8 版 = 騎手・調教師 + 3 着差(runs_all に騎手・調教師の列あり)
    np.savez_compressed(out, track=T.track.to_numpy().astype('U4'), race_no=T.race_no.to_numpy(int), umaban=T.umaban.to_numpy(int),
                        hist=hist.astype(np.float16), ctx=ctx, bw_prev=T.bw_prev.to_numpy(float))
    log('並び読み 直前版の材料', out, hist.shape, 'R', T[['track', 'race_no']].drop_duplicates().shape[0])
    return out


def load_day(prep_npz):
    """周ごと: 重み(DAY_SEQ)と頭で作った材料。どちらか無ければ None(取消の割り直しだけ)"""
    prep_npz = Path(prep_npz)
    if not (DAY_SEQ / 'v3n_seq_model.npz').exists() or not prep_npz.exists():
        return None
    meta = json.loads((DAY_SEQ / 'v3n_seq_prod.json').read_text(encoding='utf-8'))
    Z = np.load(DAY_SEQ / 'v3n_seq_model.npz')
    Ws = [{k.split('/', 1)[1]: Z[k].astype(float) for k in Z.files if k.startswith(f's{s}/')} for s in meta['seeds']]
    P = np.load(prep_npz)
    assert P['ctx'].shape[1] + 7 == meta['fc'] and P['hist'].shape[1:] == (meta['H'], meta['fh']), '直前版の材料の形が模型と合わない'
    ix = {(str(a), int(b), int(c)): i for i, (a, b, c) in enumerate(zip(P['track'], P['race_no'], P['umaban']))}
    return {'W': Ws, 'ix': ix, 'hist': P['hist'].astype(np.float32), 'ctx': P['ctx'], 'bwp': P['bw_prev'],
            'form': str(meta.get('form') or 'v3n-6: seq day')}


def resid_day(S, track, rno, nums, going, bws):
    """nums = 取消を外した後の馬番・going = 今日のそのレースの馬場・bws = 馬番 → 今日の体重。
    → 馬ごとの外した分(3 本の平均)か None(材料に無い馬・馬場が読めない・体重が全頭そろっていない)"""
    if S is None:
        return None
    g = GOING.get(str(going or '').strip(), -1)
    idx = [S['ix'].get((str(track), int(rno), int(u))) for u in nums]
    tb = np.array([float(bws.get(int(u)) or np.nan) for u in nums])
    if g < 0 or not 2 <= len(idx) <= MAXN or any(i is None for i in idx) or not np.all(tb > 0):
        return None
    idx = np.asarray(idx)
    c = S['ctx'][idx].copy()
    c[:, NH_COL] = (len(nums) - 11) / 3
    go = np.zeros((len(nums), 4))
    go[:, g] = 1.0
    bwd = np.nan_to_num(np.clip(tb - S['bwp'][idx], -30, 30), nan=0.0) / 10
    cd = np.column_stack([go, (tb - 470) / 30, bwd, np.zeros(len(nums))]).astype(np.float32)
    c = np.concatenate([c, cd], 1)
    return np.mean([S2.forward(W, S['hist'][idx], c) for W in S['W']], axis=0)
