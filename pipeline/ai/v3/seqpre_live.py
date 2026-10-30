# -*- coding: utf-8 -*-
"""前日版の並び読み(南関 AI v3 決め 63・2026-10-30・研究 nankan-ai-v3 src/f5_scripts/pre_seq_judge_1030.py・pre_seq_prod_fit.py)。

前日の便(v3_daily.py)の最後の段(併せの相手の層の後)で、並び読みの前日の材料(seq2_live.prep の DAY_seq2.npz)を
前日版の重みで読み、外した分 u を足す。当日に決まる 8 列(馬場 4・頭数・当日の体重・増減・体重なしの印)は
重みの meta の day_cols のとおりに空にする(学んだ時と同じ = 前の晩でも当日でも同じ値)。
  p1′ = レースの中で合計 1 に(sig(logit p1 + k·u))・p3′ = max(sig(logit p3 + u), min(p1′, 0.999)) → 合計 3
  k = 重みの meta の p1_k。重み = 並び読みの固定ファイル(V3_SEQ2)の seqpre_model.npz・seqpre_prod.json。
足せないレース(前日の材料に無い馬がいる・3 頭以下)は何もしない。
"""
import json
from pathlib import Path

import numpy as np

import seq2_live

KEY = ['track', 'race_date', 'race_no']
MK = {1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}  # awase_live.MK と同じ(併せの層の定数に頼らない)


def sum3(p3):
    """合計 3 にそろえる(awase_live.sum3・v29_gap._sum3 と同じ: logit をずらす二分法 [−30, +30]・100 回)。"""
    p = np.clip(np.asarray(p3, float), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    lo, hi = -30.0, 30.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if (1 / (1 + np.exp(-(z + mid)))).sum() < 3 else (lo, mid)
    return 1 / (1 + np.exp(-(z + (lo + hi) / 2)))


def load(mdir, prep_npz):
    """重み(mdir/seqpre_model.npz・seqpre_prod.json)と前日の材料(prep_npz)。どちらか無ければ None(前の段のまま)。"""
    mdir, prep_npz = Path(mdir), Path(prep_npz)
    if not (mdir / 'seqpre_model.npz').exists() or not prep_npz.exists():
        return None
    meta = json.loads((mdir / 'seqpre_prod.json').read_text(encoding='utf-8'))
    P = np.load(prep_npz)
    if P['hist'].shape[1:] != (meta['H'], meta['fh']) or P['ctx'].shape[1] != meta['fc']:
        raise AssertionError('前日版の並び読みの材料の形が模型と合わない')
    Z = np.load(mdir / 'seqpre_model.npz')
    Ws = [{k.split('/', 1)[1]: Z[k].astype(float) for k in Z.files if k.startswith(f's{s}/')} for s in meta['seeds']]
    ix = {(str(a), int(b), int(c)): i for i, (a, b, c) in enumerate(zip(P['track'], P['race_no'], P['umaban']))}
    return {'W': Ws, 'ix': ix, 'hist': P['hist'], 'ctx': P['ctx'], 'meta': meta, 'n': len(ix)}


def resid(S, track, rno, nums):
    """nums = 馬番の並び → その並びの外した分(種の平均)か None(前日の材料に無い馬がいる)。"""
    idx = [S['ix'].get((str(track), int(rno), int(u))) for u in nums]
    if not 2 <= len(idx) <= seq2_live.MAXN or any(i is None for i in idx):
        return None
    idx = np.asarray(idx)
    c = S['ctx'][idx].astype(float)
    dc = S['meta']['day_cols']
    c[:, dc['zero']] = 0.0
    c[:, dc['one']] = 1.0
    h = S['hist'][idx]
    return np.mean([seq2_live.forward(W, h, c) for W in S['W']], axis=0)


def apply(S, track, rno, nums, p1, p3):
    """→ (p1′, p3′ の合計の前, u) か None。"""
    u = resid(S, track, rno, nums)
    if u is None:
        return None
    k = float(S['meta']['p1_k'])
    p1 = np.asarray(p1, float)
    p1 = np.clip(p1 / p1.sum(), 1e-9, 1 - 1e-9)
    r = 1 / (1 + np.exp(-(np.log(p1 / (1 - p1)) + k * u)))
    p1n = r / r.sum()
    p3 = np.clip(np.asarray(p3, float), 1e-9, 1 - 1e-9)
    p3n = np.maximum(1 / (1 + np.exp(-(np.log(p3 / (1 - p3)) + u))), np.minimum(p1n, 0.999))
    return p1n, p3n, u


def apply_csv_pre(S, csv_path, log=print):
    """前日版の表の CSV(併せの相手の層の後)を直す: p1・p3p(元は p1_sq0・p3p_sq0)・rank・mark・sq_u。4 頭以上のレースだけ。→ 直したレース数"""
    import pandas as pd
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p1_sq0' in x.columns:  # 2 度かけない
        log('前日版の並び読み 済み')
        return 0
    x['p1_sq0'], x['p3p_sq0'], x['sq_u'] = x.p1, x.p3p, np.nan
    n, miss = 0, 0
    for (tr, _, rno), g in x.groupby(KEY, sort=False):
        if len(g) <= 3:
            continue
        r = apply(S, tr, rno, g.umaban.astype(int).to_numpy(), g.p1.to_numpy(float), g.p3p.to_numpy(float))
        if r is None:
            miss += 1
            continue
        x.loc[g.index, 'p1'], x.loc[g.index, 'p3p'], x.loc[g.index, 'sq_u'] = r[0], sum3(r[1]), r[2]
        n += 1
    o = x.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map(MK).fillna('')
    x = x.sort_values(KEY + ['rank'], kind='mergesort')
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    top = lambda c: x.loc[x.groupby(KEY, sort=False)[c].idxmax(), KEY + ['umaban']].set_index(KEY).umaban  # noqa: E731
    log('前日版の並び読み 足した', n, 'R・足せない', miss, 'R・本命が替わった', int((top('p3p') != top('p3p_sq0')).sum()), 'R')
    return n
