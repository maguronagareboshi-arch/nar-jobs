# -*- coding: utf-8 -*-
"""南関 AI v3 の並び読み AI(決め 24・2026-10-12・研究 nankan-ai-v3 src/f5_scripts/seq2_day.py・seq2_prod_fit.py)。学習はしない。

全場(地方 14 場 + 中央)の過去 10 走を読む小さな模型(GRU + レースの中の注意)が、直前版(第12版 = t11 + 談話の印 + 束 t14 + 束 f10k)の
3 着以内の見込みの「外した分」を出す。人気・オッズは使わない。
  1) 前日(nar-ai-v3 の便・v3_daily.py から): prep(day, U, out) → OUT/DAY_seq2.npz
     公式の表(V3_OFFICIAL の runs・races・jra・jrah の parquet = pipeline/ai/kochi/k0_dl.py で落とした nar_runs・nar_races・
     nar_jra_runs・nar_jra_horses)と t4 の土台 U(南関の走りの SI・前半・上がり)から、その日の南関の出走馬ごとに
     過去 10 走 × 48 列と今回の 25 列(当日に決まる 馬場・頭数・体重・増減 は空)・前走の体重を作る。式は研究の build と同じ(写し)。
  2) 当日(v3-gap-live の便・v29_gap.day_marks から): resid(S, track, rno, b, going) → 馬ごとの外した分(b の並び)か None
     = 当日の馬場・頭数(オッズのある馬)・体重を入れて 3 本の模型(numpy で計算・torch は要らない)の平均。
     day_marks が第12版の p3′ の logit に足し、p3 = max(·, p1)・合計 3 にそろえる(研究の tj.renorm と同じ)。
固定ファイル(前日の便 = V3_SEQ2・当日の便 = 模型の置き場 gapm): seq2_std.csv(時計のならし)・seq2_model.npz(重み)・seq2_prod.json。
"""
import json
import math
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

SEQ2 = Path(os.environ.get('V3_SEQ2', 'C:/Users/kouki/nankan_ai/v3/seq2_prod'))
OFFICIAL = Path(os.environ.get('V3_OFFICIAL', 'C:/Users/kouki/nankan_ai/v3/official'))
K = ['track', 'race_date', 'race_no', 'umaban']
NK = ['大井', '川崎', '船橋', '浦和']
VEN = NK + ['門別', '盛岡', '水沢', '金沢', '笠松', '名古屋', '園田', '姫路', '高知', '佐賀', '中央']
GO = {'良': 0, '稍重': 1, '稍': 1, '重': 2, '不良': 3, '不': 3}
CANCEL = {'取消', '出走取消', '除外', '競走除外', '枠順発表前取消'}
H, MAXN = 10, 16
# 見張り(その日の南関の出走馬・研究の 2023-01〜2026-08 の開催日ごとの値で決めた線。割ったら材料を書かない = 第12版のまま)
WATCH = {'過去 0 走の割合 ≤': 0.35, '走りの時計がある割合 ≥': 0.80, '南関の走りの SI がある割合 ≥': 0.80, '出走馬 ≥': 20}


def _log(*a):
    print('[seq2]', *a, flush=True)


# ================================================================ 1) 前日: 材料
def corner_pos(order, num):
    toks = [t for t in re.split(r'[^0-9]+', str(order)) if t]
    try:
        return toks.index(str(num)) + 1
    except ValueError:
        return np.nan


def runs_all(off=None):
    """研究 seq2_day.runs_all と同じ(公式の表の置き場だけ引数)。"""
    off = Path(off or OFFICIAL)
    r = pd.read_parquet(off / 'runs.parquet')
    r = r[r.track != '帯広ば'].copy()
    ra = pd.read_parquet(off / 'races.parquet')
    ra = ra[ra.track != '帯広ば'].drop_duplicates(['track', 'race_date', 'race_no'])
    ra['prize1'] = ra.prize_yen.map(lambda a: float(a[0]) if a is not None and len(a) else np.nan)

    def cn(c, last):
        if c is None or len(c) == 0:
            return None
        return c[-1]['order'] if last else c[0]['order']
    ra['c1'] = ra.corners.map(lambda c: cn(c, False))
    ra['c4'] = ra.corners.map(lambda c: cn(c, True))
    r = r.merge(ra[['track', 'race_date', 'race_no', 'surface', 'distance_m', 'going', 'prize1', 'c1', 'c4']],
                on=['track', 'race_date', 'race_no'], how='left')
    r['hk'] = r.horse_name.str.strip() + '|' + (r.race_date.str[:4].astype(int) - r.age).astype('Int64').astype(str)
    r['p1'] = [corner_pos(o, n) if o is not None else np.nan for o, n in zip(r.c1, r.runner_number)]
    r['p4'] = [corner_pos(o, n) if o is not None else np.nan for o, n in zip(r.c4, r.runner_number)]
    r['ven'] = r.track.map({v: i for i, v in enumerate(VEN)}).fillna(-1).astype(int)
    r['turf'] = r.surface.astype(str).str.contains('芝').astype(float)
    r['jra'] = 0.0
    r['plc'] = r.track
    r['rkey'] = r.track + '|' + r.race_date.astype(str).str[:10] + '|' + r.race_no.astype(str)
    r['fs'], r['rl3'] = np.nan, np.nan
    r = r.rename(columns={'runner_number': 'umaban'})
    cols = ['track', 'race_date', 'race_no', 'umaban', 'hk', 'ven', 'turf', 'jra', 'distance_m', 'going', 'prize1', 'carried_weight',
            'body_weight', 'finish', 'finish_note', 'time_sec', 'last3f', 'p1', 'p4', 'age', 'sex', 'gate', 'plc', 'rkey', 'fs', 'rl3']
    j = pd.read_parquet(off / 'jra.parquet')
    j = j[j.surface.isin(['ダ', '芝'])].copy()
    jh = pd.read_parquet(off / 'jrah.parquet')[['kb_horse_id', 'horse_name', 'birth_year']].drop_duplicates('kb_horse_id')
    j = j.merge(jh, on='kb_horse_id', how='left')
    j = j[j.birth_year.notna()].copy()
    j['hk'] = j.horse_name.str.strip() + '|' + j.birth_year.astype(int).astype(str)
    j['track'], j['ven'], j['turf'], j['jra'] = '中央', VEN.index('中央'), (j.surface == '芝').astype(float), 1.0
    j['distance_m'], j['prize1'], j['umaban'] = j.distance, np.nan, -1
    ps = j.passing.astype(str).str.split('-')
    j['p1'] = pd.to_numeric(ps.str[0], errors='coerce')
    j['p4'] = pd.to_numeric(ps.str[-1], errors='coerce')
    j['age'], j['sex'] = np.nan, None
    j['plc'], j['rkey'], j['fs'], j['rl3'] = j.place, 'J|' + j.kb_race_id.astype(str), j.field_size, j.race_last3f
    d = pd.concat([r[cols], j[cols]], ignore_index=True)
    d['race_date'] = d.race_date.astype(str).str[:10]
    d = d[~d.finish_note.isin(CANCEL)].copy()
    return d


def build(d, U, std, days):
    """研究 seq2_day.build と同じ式(時計のならしは固定の表 std・SI は土台 U)。予想する行 = days の南関の行。
    → T(予想する行の鍵と今回の項目)・hist(n, 10, 48)・ctx(n, 25 = 当日の 5:9・14・16・17・18 は 0)・bw_prev(n)"""
    fin = pd.to_numeric(d.finish, errors='coerce')
    stop = fin.isna() | d.finish_note.isin(['中止', '競走中止', '落馬'])
    isj = d.jra.to_numpy() == 1
    d['nh'] = np.where(isj, d.fs.fillna(14), d.groupby('rkey').hk.transform('size')).astype(float)
    d['Y3'] = ((fin <= 3) & ~stop).astype(float)
    d['Y1'] = ((fin == 1) & ~stop).astype(float)
    fr = (fin - 1) / np.maximum(d.nh - 1, 1)
    d['frel'] = np.where(stop, 1.0, np.where(isj, fr.clip(0, 1), fr))
    d['stop'] = stop.astype(float)
    d['go'] = d.going.map(GO).fillna(-1).astype(int)
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
    t = U[['track', 'race_date', 'race_no', 'runner_number', 'SI', 'ten_i', 'up_i']].rename(columns={'runner_number': 'umaban'})
    t = t.assign(race_date=t.race_date.astype(str).str[:10], race_no=t.race_no.astype(int), umaban=t.umaban.astype(int))
    d['race_no'], d['umaban'] = d.race_no.astype(int), d.umaban.astype(int)
    d = d.merge(t.drop_duplicates(K), on=K, how='left')
    for c, lo, hi in (('SI', -20, 140), ('ten_i', -50, 180), ('up_i', -100, 190)):
        d[c] = d[c].clip(lo, hi)
    d = d.sort_values(['hk', 'dn', 'jra', 'race_no']).reset_index(drop=True)
    bw = d.body_weight.where(d.body_weight > 0)
    d['bw_prev'] = bw.groupby(d.hk).shift(1)
    lp1 = np.log(d.prize1.where(d.prize1 > 0))
    run = np.column_stack([
        d.tz.fillna(0), d.tz.isna(), d.behind.fillna(2.5) / 2 - 0.5, d.l3rel.fillna(2) / 2 - 0.5, d.frel, d.Y1, d.Y3, d.stop, (d.nh - 11) / 3,
        (d.distance_m.fillna(1500) - 1500) / 300, d.turf, d.jra, *[(d.ven == i) for i in range(len(VEN))], *[(d.go == i) for i in range(4)],
        (lp1.fillna(14) - 14), lp1.isna(), (d.carried_weight.fillna(55) - 55) / 2, (bw.fillna(470) - 470) / 30,
        (bw - d.bw_prev).clip(-30, 30).fillna(0) / 10,
        (d.p1 / d.nh).fillna(0.5), (d.p4 / d.nh).fillna(0.5), d.p1.isna(),
        d.SI.fillna(60) / 20 - 3, d.ten_i.fillna(64) / 25 - 2.5, d.up_i.fillna(50) / 35 - 1.4, d.SI.isna(),
        pd.Series(d.l3j).fillna(0).to_numpy() / 2]).astype(np.float32)
    FR = run.shape[1]
    tgt = np.where(d.track.isin(NK) & d.race_date.isin(set(days)))[0]
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
    T = d.iloc[tgt].reset_index(drop=True)
    nprev = hist[:, :, -1].sum(1)
    gap = np.where(nprev > 0, hist[:, H - 1, FR], 0)
    nnk = (hist[:, :, FR + 3] * hist[:, :, 12:16].sum(2)).sum(1)
    mon = pd.to_datetime(T.race_date).dt.month.to_numpy()
    lpt = np.log(T.prize1.where(T.prize1 > 0))
    z = np.zeros(len(T))
    ctx = np.column_stack([
        (T.distance_m.fillna(1500) - 1500) / 300, *[(T.ven == i) for i in range(4)], z, z, z, z,
        lpt.fillna(14) - 14, (T.carried_weight.fillna(55) - 55) / 2, (T.age.fillna(4) - 4) / 2, T.sex.eq('牝'), T.sex.eq('セ'),
        z, (T.gate.fillna(4) - 4) / 3, z, z, z,
        gap, nprev == 0, nprev / 10, nnk / 10, np.sin(mon / 6 * np.pi), np.cos(mon / 6 * np.pi)]).astype(np.float32)
    return T, hist, ctx, T.bw_prev.to_numpy(float)


def day_fill(ctx, bw_prev, going, nh, tb):
    """当日に決まる項目を入れる(研究の build の ctx の 5:9 馬場・14 頭数・16 体重・17 増減・18 体重の欠け)。tb = 当日の体重(無ければ nan)。"""
    c = ctx.copy()
    g = GO.get(str(going or '').strip(), -1)
    c[:, 5:9] = 0.0
    if g >= 0:
        c[:, 5 + g] = 1.0
    c[:, 14] = (nh - 11) / 3
    tb = np.where(np.asarray(tb, float) > 0, np.asarray(tb, float), np.nan)
    c[:, 16] = (np.nan_to_num(tb, nan=470.0) - 470) / 30
    c[:, 17] = np.nan_to_num(np.clip(tb - bw_prev, -30, 30), nan=0.0) / 10
    c[:, 18] = np.isnan(tb)
    return c


def watch(T, hist):
    pres = hist[:, :, -1] == 1
    nk = pres & (hist[:, :, 12:16].sum(2) == 1)
    v = {'過去 0 走の割合 ≤': float((pres.sum(1) == 0).mean()) if len(T) else 1.0,
         '走りの時計がある割合 ≥': float((hist[:, :, 1][pres] == 0).mean()) if pres.any() else 0.0,
         '南関の走りの SI がある割合 ≥': float((hist[:, :, 42][nk] == 0).mean()) if nk.any() else 0.0,
         '出走馬 ≥': int(len(T))}
    ok = all((v[k] <= w) if '≤' in k else (v[k] >= w) for k, w in WATCH.items())
    return ok, v


def prep(day, U, out, log=_log):
    """前日の便: その日の南関の出走馬の材料を OUT/DAY_seq2.npz に。書けたらそのパス・書かなければ None(第12版のまま)。"""
    if U is None or not (OFFICIAL / 'runs.parquet').exists() or not (SEQ2 / 'seq2_std.csv').exists():
        log('並び読み 材料なし(土台 U・公式の表・時計のならしのどれかが無い)= 第12版のまま',
            U is not None, (OFFICIAL / 'runs.parquet').exists(), (SEQ2 / 'seq2_std.csv').exists())
        return None
    std = pd.read_csv(SEQ2 / 'seq2_std.csv', encoding='utf-8')
    d = runs_all(OFFICIAL)
    last = d[(d.jra == 0) & d.finish.notna()].race_date.max()
    log('並び読み 公式の表', len(d), '走・中央', int((d.jra == 1).sum()), '・着順のある最後の日', last)
    T, hist, ctx, bwp = build(d, U, std, [day])
    ok, v = watch(T, hist)
    log('並び読み 見張り', {k: round(x, 3) if isinstance(x, float) else x for k, x in v.items()}, '→', '○' if ok else '× = 書かない')
    if not ok:
        return None
    p = Path(out) / f'{day}_seq2.npz'
    np.savez_compressed(p, track=T.track.to_numpy().astype('U4'), race_no=T.race_no.to_numpy(int), umaban=T.umaban.to_numpy(int),
                        hk=T.hk.to_numpy().astype(str), hist=hist, ctx=ctx, bw_prev=bwp)
    log('並び読み 材料', p.name, hist.shape, ctx.shape, 'R', T[['track', 'race_no']].drop_duplicates().shape[0])
    return p


# ================================================================ 2) 当日: 模型
def _erf(x):
    try:
        from scipy.special import erf
        return erf(x)
    except Exception:  # noqa: BLE001
        return np.vectorize(math.erf, otypes=[float])(x)


def _gelu(x):
    return 0.5 * x * (1.0 + _erf(x / math.sqrt(2.0)))


def _ln(x, g, b):
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + 1e-5) * g + b


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def forward(W, hist, ctx, heads=4):
    """研究 seq_day.model の forward(1 レース・全馬が有効・評価の時 = dropout なし)を numpy で。→ 馬ごとの外した分(logit)。"""
    x = _gelu(hist.astype(float) @ W['inp.0.weight'].T + W['inp.0.bias'])
    n, t, d = x.shape
    gi = x @ W['gru.weight_ih_l0'].T + W['gru.bias_ih_l0']
    whh, bhh = W['gru.weight_hh_l0'], W['gru.bias_hh_l0']
    h = np.zeros((n, d))
    for s in range(t):
        gh = h @ whh.T + bhh
        r = _sig(gi[:, s, :d] + gh[:, :d])
        z = _sig(gi[:, s, d:2 * d] + gh[:, d:2 * d])
        nn_ = np.tanh(gi[:, s, 2 * d:] + r * gh[:, 2 * d:])
        h = (1 - z) * nn_ + z * h
    e = _gelu(np.concatenate([ctx.astype(float), h], -1) @ W['ctx.0.weight'].T + W['ctx.0.bias'])
    e = e @ W['ctx.2.weight'].T + W['ctx.2.bias']
    qkv = e @ W['att.self_attn.in_proj_weight'].T + W['att.self_attn.in_proj_bias']
    hd = d // heads
    q, k, v = (qkv[:, i * d:(i + 1) * d].reshape(n, heads, hd).transpose(1, 0, 2) for i in range(3))
    sc = q @ k.transpose(0, 2, 1) / math.sqrt(hd)
    sc = np.exp(sc - sc.max(-1, keepdims=True))
    a = (sc / sc.sum(-1, keepdims=True)) @ v
    a = a.transpose(1, 0, 2).reshape(n, d) @ W['att.self_attn.out_proj.weight'].T + W['att.self_attn.out_proj.bias']
    x1 = _ln(e + a, W['att.norm1.weight'], W['att.norm1.bias'])
    f = np.maximum(x1 @ W['att.linear1.weight'].T + W['att.linear1.bias'], 0.0) @ W['att.linear2.weight'].T + W['att.linear2.bias']
    x2 = _ln(x1 + f, W['att.norm2.weight'], W['att.norm2.bias'])
    return (np.concatenate([e, x2], -1) @ W['out.weight'].T + W['out.bias'])[:, 0]


def load(mdir, prep_npz):
    """当日の便: 重み(mdir/seq2_model.npz・seq2_prod.json)と前日の材料(prep_npz)。どちらか無ければ None(第12版のまま)。"""
    mdir, prep_npz = Path(mdir), Path(prep_npz)
    if not (mdir / 'seq2_model.npz').exists() or not prep_npz.exists():
        return None
    meta = json.loads((mdir / 'seq2_prod.json').read_text(encoding='utf-8'))
    Z = np.load(mdir / 'seq2_model.npz')
    Ws = [{k.split('/', 1)[1]: Z[k].astype(float) for k in Z.files if k.startswith(f's{s}/')} for s in meta['seeds']]
    P = np.load(prep_npz)
    assert P['hist'].shape[1:] == (meta['H'], meta['fh']) and P['ctx'].shape[1] == meta['fc'], '並び読みの材料の形が模型と合わない'
    ix = {(str(a), int(b), int(c)): i for i, (a, b, c) in enumerate(zip(P['track'], P['race_no'], P['umaban']))}
    return {'W': Ws, 'ix': ix, 'hist': P['hist'], 'ctx': P['ctx'], 'bw_prev': P['bw_prev'], 'n': len(ix)}


def resid(S, track, rno, b, going):
    """b = day_marks の材料(オッズのある馬・umaban と当日の体重 bw)。→ b の並びの外した分(3 本の平均)か None(前日の材料に無い馬がいる)。"""
    idx = [S['ix'].get((str(track), int(rno), int(u))) for u in b.umaban]
    if not 2 <= len(idx) <= MAXN or any(i is None for i in idx):
        return None
    idx = np.asarray(idx)
    c = day_fill(S['ctx'][idx], S['bw_prev'][idx], going, len(idx), b.bw.to_numpy(float))
    h = S['hist'][idx]
    return np.mean([forward(W, h, c) for W in S['W']], axis=0)
