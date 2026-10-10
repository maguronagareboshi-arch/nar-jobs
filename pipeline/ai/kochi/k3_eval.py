# -*- coding: utf-8 -*-
"""高知版 3 = k1 の材料で学び、2022-01〜2026-09 を年ごとに当てる(その年より前の 2008〜で学ぶ)。南関の第9版と同じ設定。

  py -3.12 -X utf8 src/kochi/k3_eval.py   → C:/Users/kouki/nankan_ai/v3/kochi/preds.parquet・out/kochi_k3.md

  - 設定 = 南関の d3.BASE・vo.CFG(3 着内: 葉 15・min_data 100・1200 本/勝ち: 葉 31・min_data 500・400 本)・初期値 logit(k/頭数)。
  - 物差し = ◎(3 着内の見込み 1 位)の 3 着内率・上位 5 頭に 3 頭の率・行ごとの対数尤度。人気・オッズは使わない。
  - 比べる相手 = 「前 5 走の速さの最大」だけの並び(学習なし)。
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

V = Path('C:/Users/kouki/nankan_ai/v3/kochi')
OUTMD = Path(__file__).resolve().parents[2] / 'out' / 'kochi_k3.md'
RK = ['date', 'jyo', 'race']
BASE = {'objective': 'binary', 'learning_rate': 0.03, 'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 1,
        'lambda_l2': 10, 'seed': 0, 'deterministic': True, 'num_threads': 4, 'verbose': -1}
CFG = {'Y1': (31, 500, 400), 'Y3': (15, 100, 1200)}
PFX = ('a_', 'b_', 'c_', 'd_', 'e_', 'f_', 'g_', 'h_', 'i_', 'j_', 'k_', 'l_', 'p_', 'r_', 'c7_', 'j7_')


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def train(tr, y, cols):
    k = 1 if y == 'Y1' else 3
    z = logit(np.minimum(k / tr.n.to_numpy(float), 0.99))
    prm = dict(BASE, num_leaves=CFG[y][0], min_data_in_leaf=CFG[y][1])
    return lgb.train(prm, lgb.Dataset(tr[cols].astype(float), label=tr[y].to_numpy(float), init_score=z),
                     num_boost_round=CFG[y][2])


def score(x, col):
    s = x.sort_values(RK + [col, 'umaban'], ascending=[True, True, True, False, True], kind='mergesort')
    R = s.groupby(RK).agg(hon=('Y3', 'first'), top5=('Y3', lambda v: float(v.iloc[:5].sum() >= 3)),
                          win=('Y1', 'first'))
    return R


def main(feat='feat.parquet', tag='k1', ref=None):
    T = pd.read_parquet(V / feat)
    cols = [c for c in T.columns if c.startswith(PFX) and c not in ('jockey_cd', 'trainer_cd')]
    print('材料', len(cols))
    out, imp = [], None
    for Y in range(2022, 2027):
        tr = T[(T.date >= '2008-01-01') & (T.date < f'{Y}-01-01')]
        te = T[(T.date >= f'{Y}-01-01') & (T.date < f'{Y + 1}-01-01')].copy()
        for y in ['Y3', 'Y1']:
            m = train(tr, y, cols)
            k = 1 if y == 'Y1' else 3
            z = logit(np.minimum(k / te.n.to_numpy(float), 0.99))
            te['p' + y[1]] = 1 / (1 + np.exp(-(z + m.predict(te[cols].astype(float), raw_score=True))))
            if y == 'Y3':
                g = pd.Series(m.feature_importance('gain'), index=cols)
                imp = g if imp is None else imp + g
        out.append(te[RK + ['umaban', 'ketto', 'n', 'fin', 'Y1', 'Y3', 'p3', 'p1', 'a_simax5', 'mk_pop', 'mk_odds']])
        print(Y, '済み', len(tr), len(te), flush=True)
    P = pd.concat(out)
    P.to_parquet(V / f'preds_{tag}.parquet', index=False)
    P['base'] = P.a_simax5.fillna(-99)
    q = np.clip(P.p3.to_numpy(), 1e-6, 1 - 1e-6)
    P['ll'] = P.Y3 * np.log(q) + (1 - P.Y3) * np.log(1 - q)
    lines = ['# 高知版 k3: KDSCOPE の成績だけの材料で当てる(2022-01〜2026-09・年ごとに前の年までで学ぶ)', '',
             f'材料 {len(cols)} 個・行 {len(P):,}・レース {P.groupby(RK).ngroups:,}', '',
             '| 年 | レース | ◎ 3 着内率 | ◎ 勝率 | 上位 5 に 3 頭 | 速さの最大だけ ◎ | 同 上位 5 に 3 頭 |', '|---|---:|---:|---:|---:|---:|---:|']
    tot = []
    for Y, x in list(P.groupby(P.date.dt.year)) + [('全体', P)]:
        a, b = score(x, 'p3'), score(x, 'base')
        lines.append(f'| {Y} | {len(a):,} | {a.hon.mean() * 100:.1f}% | {a.win.mean() * 100:.1f}% | {a.top5.mean() * 100:.1f}% | '
                     f'{b.hon.mean() * 100:.1f}% | {b.top5.mean() * 100:.1f}% |')
    a = score(P, 'p3')
    se = a.hon.std() / np.sqrt(len(a)) * 100
    lines += ['', f'◎ 3 着内率の誤差の目安(1 標準誤差)±{se:.2f}。3 着内の対数尤度/行 {P.ll.mean():.4f}。', '',
              '## 効いている材料(3 着内・木の分かれの得の合計・上位 20)', '', '| 材料 | 割合 |', '|---|---:|']
    imp = imp / imp.sum()
    for c, v in imp.sort_values(ascending=False).head(20).items():
        lines.append(f'| {c} | {v * 100:.1f}% |')
    if ref:
        lines += cmp(P, pd.read_parquet(V / f'preds_{ref}.parquet'), tag, ref)
    OUTMD.with_name(f'kochi_k3_{tag}.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


def cmp(P, Q, tag, ref):
    """同じ行で ◎ の 3 着内率・3 着内の対数尤度の差(レースでまとめた誤差)。"""
    k = RK + ['umaban']
    M = P[k + ['Y3', 'Y1', 'p3']].merge(Q[k + ['p3']], on=k, suffixes=('', '_r'))
    q, r = np.clip(M.p3, 1e-6, 1 - 1e-6), np.clip(M.p3_r, 1e-6, 1 - 1e-6)
    M['d'] = (M.Y3 * np.log(q) + (1 - M.Y3) * np.log(1 - q)) - (M.Y3 * np.log(r) + (1 - M.Y3) * np.log(1 - r))
    g = M.groupby(RK).d.agg(['sum', 'size'])
    m = g['sum'].sum() / g['size'].sum()
    se = np.sqrt(((g['sum'] - m * g['size']) ** 2).sum()) / g['size'].sum()
    a, b = score(M, 'p3'), score(M.assign(p3=M.p3_r), 'p3')
    dh = (a.hon - b.hon)
    out = ['', f'## {ref} との差(同じ {len(M):,} 行・{len(a):,} R)', '',
           f'- 3 着内の対数尤度/行の差 ×10^-4: {m * 1e4:+.1f} ± {2 * se * 1e4:.1f}(2 標準誤差)',
           f'- ◎ 3 着内率: {b.hon.mean() * 100:.2f}% → {a.hon.mean() * 100:.2f}%({dh.mean() * 100:+.2f} ± {2 * dh.std() / np.sqrt(len(dh)) * 100:.2f})',
           f'- 上位 5 に 3 頭: {b.top5.mean() * 100:.2f}% → {a.top5.mean() * 100:.2f}%']
    for Y, x in M.groupby(M.date.dt.year):
        gg = x.groupby(RK).d.sum().sum() / len(x)
        out.append(f'  - {Y}: 対数尤度 {gg * 1e4:+.1f}')
    return out


if __name__ == '__main__':
    import sys
    main(*sys.argv[1:])
