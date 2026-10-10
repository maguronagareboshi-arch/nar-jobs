# -*- coding: utf-8 -*-
"""高知版 10 = 公式の元だけで作った材料(k9)を、今の高知の土台(cadd = feat2 + G2 + n_)と比べる(決め = out/kochi_official.md)。

  py -3.12 -X utf8 src/kochi/k10_offeval.py feat   → 材料の照らし合わせ(2022〜・同じ行)
  py -3.12 -X utf8 src/kochi/k10_offeval.py pred   → 予想の比べ(2022-01〜2026-09-27・同じレース)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import k3_eval as k3  # noqa: E402
import k5_groups as k5  # noqa: E402

KD = Path('C:/Users/kouki/nankan_ai/v3/kochi')
OF = Path('C:/Users/kouki/nankan_ai/v3/kochi_off/kochi')
OUTMD = Path(__file__).resolve().parents[2] / 'out' / 'kochi_official.md'
K = ['date', 'race', 'umaban']
LAST = '2026-09-28'


def load(d):
    k5.V = d
    T, base = k5.load()
    cols = base + [c for c in T.columns if c.startswith(('x2_', 'n_'))]
    return T, cols


def feat():
    A, cols = load(KD)
    B, _ = load(OF)
    A, B = A[(A.date >= '2022-01-01') & (A.date < LAST)], B[(B.date >= '2022-01-01') & (B.date < LAST)]
    M = A[K + cols].merge(B[K + cols], on=K, suffixes=('_k', '_o'))
    rows = []
    for c in cols:
        a, b = M[c + '_k'].astype(float), M[c + '_o'].astype(float)
        both = a.notna() & b.notna()
        tol = 1e-6 + 1e-3 * a.abs()
        same = ((a - b).abs() <= tol) | (a.isna() & b.isna())
        r = np.corrcoef(a[both], b[both])[0, 1] if both.sum() > 10 and a[both].std() > 0 and b[both].std() > 0 else np.nan
        rows.append((c, same.mean(), r, a.notna().mean(), b.notna().mean()))
    R = pd.DataFrame(rows, columns=['列', '同じ', '相関', 'KD あり', '公式あり']).sort_values('同じ')
    lines = ['', '## 照らし合わせ 2: 材料(2022-01〜2026-09-27・同じ行)', '',
             f'行 KDSCOPE {len(A):,}・公式 {len(B):,}・両方 {len(M):,}。列 {len(cols)}。', '',
             f"同じ値の割合の中央値 {R['同じ'].median():.3f}・相関の中央値 {R['相関'].median():.3f}・同じ 99% 以上の列 {(R['同じ'] >= .99).sum()}", '',
             'ずれの大きい 25 列:', '', '| 列 | 同じ | 相関 | KD あり | 公式あり |', '|---|---:|---:|---:|---:|']
    for _, x in R.head(25).iterrows():
        lines.append(f"| {x['列']} | {x['同じ']:.3f} | {x['相関']:.3f} | {x['KD あり']:.3f} | {x['公式あり']:.3f} |")
    R.to_csv(OF / 'feat_cmp.csv', index=False, encoding='utf-8-sig')
    with open(OUTMD, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


def run_from(T, name, cols, d, start):
    """k5.run と同じ・学ぶ期間の始まりだけ変える。"""
    W = d / 'k5'
    W.mkdir(exist_ok=True)
    out = []
    for Y in range(2022, 2027):
        f = W / f'{name}_{Y}.parquet'
        if f.exists():
            out.append(pd.read_parquet(f)); continue
        tr = T[(T.date >= start) & (T.date < f'{Y}-01-01')]
        te = T[(T.date >= f'{Y}-01-01') & (T.date < f'{Y + 1}-01-01')][k5.RK + ['umaban', 'n', 'Y1', 'Y3']].copy()
        X = T.loc[te.index, cols]
        for y in ('Y3', 'Y1'):
            m = k3.train(tr, y, cols)
            k = 1 if y == 'Y1' else 3
            z = k3.logit(np.minimum(k / te.n.to_numpy(float), 0.99))
            te['p' + y[1]] = 1 / (1 + np.exp(-(z + m.predict(X.astype(float), raw_score=True))))
        te.to_parquet(f, index=False)
        out.append(te)
        print(name, Y, '済み', flush=True)
    return pd.concat(out)


def pred():
    A, cols = load(KD)
    P0 = pd.concat(pd.read_parquet(KD / 'k5' / f'cadd_{y}.parquet') for y in range(2022, 2027))
    P15 = run_from(A, 'cadd15', cols, KD, '2015-01-01')
    B, colsb = load(OF)
    assert cols == colsb, '列が違う'
    PO = run_from(B, 'oadd', cols, OF, '2015-01-01')
    # 同じレース(両方にあって頭数も同じ)だけ
    def races(P):
        P = P[P.date < LAST]
        return P.groupby(k5.RK).size().rename('nn')
    common = races(P0).to_frame().join(races(PO).rename('no'), how='inner')
    common = common[common.nn == common['no']].index
    def cut(P):
        P = P[P.date < LAST].set_index(k5.RK)
        return P[P.index.isin(common)].reset_index()
    P0, P15, PO = cut(P0), cut(P15), cut(PO)
    lines = ['', '## 照らし合わせ 3: 予想(2022-01〜2026-09-27・同じレース ' + f'{len(common):,} R)', '',
             '| 比べ | 対数尤度 ×10^-4 | ◎ 3 着内率 | 上位 5 に 3 頭 | 年ごと |', '|---|---:|---:|---:|---|']
    for lab, P, Q in [('KDSCOPE 2015〜学び − KDSCOPE 2008〜学び(cadd)', P15, P0), ('公式 2015〜 − KDSCOPE 2008〜(cadd)', PO, P0),
                      ('公式 2015〜 − KDSCOPE 2015〜', PO, P15)]:
        d = k5.diff(P, Q)
        lines.append(f"| {lab} | {d['ll']:+.1f} ± {d['se2']:.1f} | {d['hon0']:.2f}→{d['hon1']:.2f}(± {d['hse2']:.2f}) | "
                     f"{d['t50']:.2f}→{d['t51']:.2f} | {d['years']} |")
    for lab, P in [('cadd', P0), ('cadd15', P15), ('公式', PO)]:
        s = k3.score(P, 'p3')
        lines.append(f'- {lab}: ◎ 3 着内 {s.hon.mean() * 100:.2f}%・◎ 勝率 {s.win.mean() * 100:.2f}%・上位 5 に 3 頭 {s.top5.mean() * 100:.2f}%')
    with open(OUTMD, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    {'feat': feat, 'pred': pred}[sys.argv[1]]()
