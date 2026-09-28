# -*- coding: utf-8 -*-
"""段 2 = 第 7 版 e の当てはめ外の予想(v7e_open.OUT_P)を土台に、調教の数字だけで上乗せする小さなロジスティック回帰。

  py -3.12 -X utf8 src/v8s2_run.py      # → v3/v8s2_preds.parquet(全期間)・out/v8_cyokyo_s2.md(2023-01〜2025-06 だけ)

形(決め打ち 1 つ): logit(p) = logit(土台 p3 / p1)(係数 1 で固定)+ b0 + w·x。L2(λ = 1.0・切片は罰なし)。
x = cy_ 6 列(学びの期間の平均・標準偏差で標準化、欠けは 0)+ 欠けの 0/1 × 6 + レース内順位(0〜1)cy_day_pct・cy_stable
    + 以上 14 列 × 新馬戦の馬(b_young の 1 の位が 1 の馬がいるレースの馬)= 28 列。
直した p1 はレース内で和 1、p3 = max(p3, p1)、p3′ = t6_base.p3prime、◎ = p3′ → p1 → 馬番(std_table)。
表・率・差は 2023-01-01〜2025-06-30 の行だけ(2025-07-01 以降は採点の前に落とす。予想の保存だけ全期間)。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t6_base  # noqa: E402
import v7_open as vo  # noqa: E402
import v7_open_eval as E  # noqa: E402
import v7e_open as eo  # noqa: E402
import v8s1_run as s1  # noqa: E402
import std_table as st  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
KEY = ['track', 'race_date', 'race_no']
Q5 = KEY + ['umaban']
OUT_P = V3 / 'v8s2_preds.parquet'
CYP = V3 / 'v8cy_open_preds.parquet'
MD = REPO / 'out' / 'v8_cyokyo_s2.md'
LO, HI = '2023-01-01', '2025-06-30'
CY6 = ['cy_day_pct', 'cy_self', 'cy_stable', 'cy_int', 'cy_n14', 'cy_gap']
LAM = 1.0
FITS = [('2023', '2023-01-01', '2023-12-31'), ('2024', '2024-01-01', '2024-12-31'),
        ('2025上', '2025-01-01', '2025-06-30'), ('確かめ用', '2025-07-01', '2026-08-31')]
log = s1.log


def load():
    B = pd.read_parquet(eo.OUT_P)
    B['race_no'], B['umaban'] = B.race_no.astype(int), B.umaban.astype(int)
    C = vo.nk(pd.read_parquet(V3 / 'feat_v8cy_open.parquet', columns=Q5 + CY6))
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT, columns=Q5 + ['b_young']))
    D = B.merge(C, on=Q5, how='left', validate='1:1').merge(T, on=Q5, how='left', validate='1:1')
    D = D.sort_values(Q5, kind='mergesort').reset_index(drop=True)
    D['shinba'] = (D.b_young.fillna(0) % 10 == 1).groupby([D[k] for k in KEY]).transform('any').astype(float)
    g = [D[k] for k in KEY]
    for c in ('cy_day_pct', 'cy_stable'):
        r = D[c].groupby(g).rank(method='average')
        m = D[c].notna().groupby(g).transform('sum')
        D[c + '_rk'] = np.where(D[c].isna(), 0.0, np.where(m > 1, (r - 1) / (m - 1).clip(lower=1), 0.5))
    assert len(D) == 172738
    return D


def design(D, mu, sd):
    X = {}
    for c in CY6:
        X[c] = ((D[c] - mu[c]) / sd[c]).fillna(0.0)
        X[c + '_na'] = D[c].isna().astype(float)
    X['cy_day_pct_rk'], X['cy_stable_rk'] = D.cy_day_pct_rk, D.cy_stable_rk
    base = list(X)
    for c in base:
        X[c + '×新馬'] = X[c] * D.shinba
    X = pd.DataFrame(X)
    return X.to_numpy(float), list(X.columns)


def fit(X, y, off):
    Xa = np.column_stack([np.ones(len(X)), X])

    def f(w):
        z = off + Xa @ w
        p = 1 / (1 + np.exp(-z))
        ll = np.sum(np.logaddexp(0, z) - y * z)
        g = Xa.T @ (p - y)
        pen = w.copy(); pen[0] = 0
        return ll + 0.5 * LAM * np.sum(pen ** 2), g + LAM * pen
    r = minimize(f, np.zeros(Xa.shape[1]), jac=True, method='L-BFGS-B', options={'maxiter': 2000})
    assert r.success, r.message
    return r.x


def lg(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def run():
    s1.wait_mem()
    D = load()
    P, COEF = [], {}
    for name, lo, hi in FITS:
        tr = D[(D.race_date >= '2022-01-01') & (D.race_date < lo)]
        te = D[(D.race_date >= lo) & (D.race_date <= hi)]
        mu, sd = tr[CY6].mean(), tr[CY6].std()
        Xtr, cols = design(tr, mu, sd)
        Xte, _ = design(te, mu, sd)
        r = {}
        for t, bc in (('Y1', 'v7epre_p1'), ('Y3', 'v7epre_p3')):
            w = fit(Xtr, tr[t].to_numpy(float), lg(tr[bc].to_numpy(float)))
            COEF[f'{name}|{t}'] = dict(zip(['切片'] + cols, map(float, w)))
            r[t] = 1 / (1 + np.exp(-(lg(te[bc].to_numpy(float)) + w[0] + Xte @ w[1:])))
        x = te[Q5 + ['year', 'n', 'Y1', 'Y3', 'pop']].copy()
        x['fit'] = name
        p1 = r['Y1'] / pd.Series(r['Y1'], index=x.index).groupby([x[k] for k in KEY]).transform('sum').to_numpy()
        x['v8s2_p1'], x['v8s2_p3'] = p1, np.maximum(r['Y3'], p1)
        x['v8s2_p3p'] = t6_base.p3prime(x, 'v8s2_p3')[0]
        P.append(x)
        log('段2', name, '学び', len(tr), '予想', len(x))
    out = pd.concat(P, ignore_index=True).sort_values(Q5, kind='mergesort').reset_index(drop=True)
    assert out.v8s2_p3p.notna().all()
    out.to_parquet(OUT_P, index=False)
    log('保存', OUT_P, out.shape)
    evaluate(COEF)


def evaluate(COEF):
    p = E.load()
    p = p[(p.race_date >= LO) & (p.race_date <= HI)].copy()  # 2025-07-01 以降は採点の前に落とす
    for f, cs in ((eo.OUT_P, ['v7epre_p1', 'v7epre_p3p']), (CYP, ['v8cy_p1', 'v8cy_p3p']), (OUT_P, ['v8s2_p1', 'v8s2_p3p'])):
        x = pd.read_parquet(f)
        x['race_no'], x['umaban'] = x.race_no.astype(int), x.umaban.astype(int)
        x = x[(x.race_date >= LO) & (x.race_date <= HI)]
        p = p.merge(x[Q5 + cs], on=Q5, how='left', validate='1:1')
    assert p[['v7epre_p1', 'v8cy_p1', 'v8s2_p1']].notna().all().all() and p.race_date.max() <= HI
    Yc = 'Y3' if 'Y3' in p.columns else None
    ll = {}
    for c in ('v7epre_p3p', 'v8s2_p3p', 'v8cy_p3p'):
        q = np.clip(p[c].to_numpy(float), 1e-6, 1 - 1e-6)
        y = p[Yc].to_numpy(float)
        ll[c] = float(np.sum(y * np.log(q) + (1 - y) * np.log(1 - q)))
    ais = {'第7版e': ('v7epre_p3p', 'v7epre_p1'), '7e+調教': ('v8cy_p3p', 'v8cy_p1'), '段2': ('v8s2_p3p', 'v8s2_p1')}
    R = st.frame(p, ais, close_by='段2')
    std = st.rows(R, list(ais))
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT, columns=Q5 + ['b_young']))
    T = T[(T.race_date >= LO) & (T.race_date <= HI)]
    sc = T.groupby(KEY).agg(shinba=('b_young', lambda v: float((v.fillna(0) % 10 == 1).any())))
    R = R.join(sc)
    R['date'] = R.index.get_level_values('race_date')
    a, b, m, f = '段2|Y3', '第7版e|Y3', '7e+調教|Y3', '1番人気|Y3'

    def dse(g, x, y):
        d = (g[x] - g[y]).dropna()
        dd = d.groupby(g.date[d.index]).agg(['sum', 'size'])
        mm = dd['sum'].sum() / dd['size'].sum()
        se = np.sqrt(((dd['sum'] - mm * dd['size']) ** 2).sum()) / dd['size'].sum()
        return f'{100 * mm:+.2f} ±{200 * se:.2f}'

    def row(lab, g):
        return {'区分': lab, 'レース': len(g), '段2': round(100 * g[a].mean(), 1), '7e+調教': round(100 * g[m].mean(), 1),
                '第7版e': round(100 * g[b].mean(), 1), '1番人気': round(100 * g[f].mean(), 1),
                '差 段2−7e': dse(g, a, b), '差 7e+調教−7e': dse(g, m, b)}
    rows = [row('全体', R)] + [row(str(y) + ('(1〜6 月)' if y == 2025 else ''), g) for y, g in R.groupby('year')]
    trk = [row(t, g) for t, g in R.groupby(level='track')]
    sub = [row('新馬戦', R[R.shinba == 1]), row('接戦(段2 の p3′ 1 位 − 2 位 が下 1/4)', R[R.close == 1])]
    V = {'std': std, 'rows': rows, 'trk': trk, 'sub': sub, 'gap_q25': float(R.gap.quantile(0.25)), 'll': ll, 'coef': COEF,
         'n_rows': len(p)}
    (V3 / 'v8s2_res.json').write_text(json.dumps(V, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    log('eval', rows[0], sub, ll)
    write_md(V)


def write_md(V):
    ll = V['ll']
    C = V['coef']
    ks = [k for k in C if not k.startswith('確かめ用')]
    names = list(C[ks[0]])
    L = ['# 段 2 = 第 7 版 e の予想 + 調教の数字だけの上乗せ(自作)', '',
         '- 決め: out/v8_cyokyo_check_plan.md(追記 2026-09-27)。台本 src/v8s2_run.py。予想 v3/v8s2_preds.parquet(全期間を保存)。',
         '- 形: logit(p) = logit(第 7 版 e の p3 / p1)(係数 1 固定)+ 切片 + 28 列の一次式。ロジスティック回帰・L2 λ = 1.0(切片は罰なし)。',
         '  列 = cy_day_pct・cy_self・cy_stable・cy_int・cy_n14・cy_gap(学びの期間の平均・標準偏差で標準化・欠けは 0)+ 欠けの 0/1 × 6'
         ' + レース内順位 cy_day_pct・cy_stable(0〜1)+ 以上 14 列 × 新馬戦の馬(b_young の 1 の位が 1 の馬がいるレース)。',
         '- 学び: 2022-01〜2022-12 → 2023、2022-01〜2023-12 → 2024、2022-01〜2024-12 → 2025-01〜06。確かめ用 2022-01〜2025-06 → 2025-07〜2026-08(保存だけ・見ていない)。',
         f'- **この表は {LO}〜{HI} だけ・3 つの AI は同じレース**。予想にオッズ・人気は入れていない(採点だけ)。', '',
         '## 毎回の表(std_table)', '', st.md(V['std']), '',
         '## ◎ の 3 着以内率 %(差 ± = 日ごとにまとめた 2 × 標準誤差)', '', s1.tab(V['rows']), '', '### 場ごと', '', s1.tab(V['trk']), '',
         f'### 場面別(接戦 = 段2 の p3′ 1 位 − 2 位 ≤ {V["gap_q25"]:.4f})', '', s1.tab(V['sub']), '',
         f'## 3 着以内の対数尤度の和(p3′・{V["n_rows"]:,} 行)', '',
         '| AI | 和 | 第 7 版 e との差 |', '|---|---|---|']
    for c, n in (('v7epre_p3p', '第7版e'), ('v8cy_p3p', '7e+調教'), ('v8s2_p3p', '段2')):
        L.append(f'| {n} | {ll[c]:,.1f} | {ll[c] - ll["v7epre_p3p"]:+,.1f} |')
    L += ['', '## 当てはめた係数(見る期間の 3 本・標準化した列の単位)', '',
          '| 列 | ' + ' | '.join(ks) + ' |', '|' + '---|' * (1 + len(ks))]
    for c in names:
        L.append(f'| {c} | ' + ' | '.join(f'{C[k][c]:+.3f}' for k in ks) + ' |')
    L.append('')
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')
    log('md', MD)


if __name__ == '__main__':
    run()
