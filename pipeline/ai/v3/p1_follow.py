# -*- coding: utf-8 -*-
"""南関 v3 の勝つ率 p1 を 3着内 p3 の上乗せに付いて行かせる(決め 29・研究 nankan-ai-v3 src/f5_scripts/p1_fix.py・2026-10-14)。

10/3 以降の上乗せ(談話の印・束 t14・f10k・並び読み・初出走の層)は p3 だけを動かし、p1 は木のままだった
(並び読みが 3着内を 1.3〜1.6 倍にした馬は表の勝率の 1.67 倍勝つ)。直し:
  p1' ∝ p1^a × exp(k ×(logit F − logit T))を R で合計 1。T = 上乗せの前の 3着内(合計 3)・F = 全部足した後(合計 3)。
  守り: p1' > p3 の馬がいれば p3 = max(p3, p1') で合計 3 に戻す(越えが無くなるまで 20 回)。
  直前版だけ 3着内の極端さの直し E: p3 = 合計 3(max(σ(e_a · logit p3), p1'))→ 守り(並べ順は変わらない)。
定数 = 研究の全期間(2023-01〜2026-08)の学び直し(v3/p1f/prod.json)。確かめ 直前 +134.2 ± 20.8・E +35.9・前日 +52.5 ± 11.0。
"""
import numpy as np
import pandas as pd

FORM = {'pre': (1.0, 0.9868, None), 'day': (0.9429, 0.7916, 0.91)}
TAG = {'pre': 'p1f 決め29 前日 k0.987', 'day': 'p1f 決め29 直前 a0.943 k0.792 E0.91'}
Q4 = ['track', 'race_date', 'race_no', 'umaban']
MK = {1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}


def _lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sig(z):
    return 1 / (1 + np.exp(-z))


def sum3(p3):
    """1 レースの p3 を合計 3 に(logit をずらす二分法 [−30, +30]・100 回 = t6_base.p3prime と同じ)。3 頭以下は 1 で切るだけ。"""
    p3 = np.asarray(p3, float)
    if len(p3) <= 3:
        return np.minimum(p3, 1.0)
    z = _lg(p3)
    lo, hi = -30.0, 30.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _sig(z + mid).sum() < 3 else (lo, mid)
    return _sig(z + (lo + hi) / 2)


def follow(p1, T, F, a, k):
    """1 レース: 木の勝つ率 p1・上乗せ前の 3着内 T・後の F → 直した勝つ率(合計 1)"""
    p1 = np.asarray(p1, float)
    e = a * np.log(np.clip(p1 / p1.sum(), 1e-12, 1)) + k * (_lg(F) - _lg(T))
    e = np.exp(e - e.max())
    return e / e.sum()


def guard(p3, q, n_max=20):
    p3 = np.asarray(p3, float)
    for _ in range(n_max):
        if not (q > p3 + 1e-9).any():
            break
        p3 = sum3(np.maximum(p3, q))
    return p3


def apply(ver, p1, T, F):
    """1 レース → (直した p1, 守り・E の後の p3)"""
    a, k, ea = FORM[ver]
    q = follow(p1, T, F, a, k)
    G = guard(F, q)
    if ea is not None:
        G = guard(sum3(np.maximum(_sig(ea * _lg(G)), q)), q)
    return q, G


def apply_csv(csv_path, log=print):
    """前日の表の CSV(初出走の層まで足した後)を直す: p1(元は p1_t10 に残す)・p3p・rank・mark。T = p3p_t10(談話の前)。→ 直したレース数"""
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p3p_t10' not in x.columns or x.p3p_t10.isna().all():
        log('勝つ率の直し 木の 3着内 p3p_t10 が無い = 直さない')
        return 0
    if 'p1_t10' in x.columns:  # 2 度かけない
        log('勝つ率の直し 済み')
        return 0
    key = ['track', 'race_date', 'race_no']
    x['p1_t10'] = x.p1
    n = 0
    for _, g in x.groupby(key, sort=False):
        if g.p3p_t10.isna().any():
            continue
        q, G = apply('pre', g.p1.to_numpy(float), g.p3p_t10.to_numpy(float), g.p3p.to_numpy(float))
        x.loc[g.index, 'p1'] = q
        x.loc[g.index, 'p3p'] = G
        n += 1
    o = x.sort_values(key + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(key, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map(MK).fillna('')
    x = x.sort_values(key + ['rank'], kind='mergesort')
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    log('勝つ率の直し(決め 29)', n, 'R', '倍率の幅', round(float((x.p1 / x.p1_t10).min()), 2), '〜', round(float((x.p1 / x.p1_t10).max()), 2))
    return n
