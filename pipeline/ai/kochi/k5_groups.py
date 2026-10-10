# -*- coding: utf-8 -*-
"""高知版 5 = 4 つの束を選んで確かめる(2026-10-10・結果を見る前に決め)。

  py -3.12 -X utf8 src/kochi/k5_groups.py select    # 選び: 2018〜2021 を年ごとに(前の年までで学ぶ)・3 着内だけ・土台と + 束 1 つずつ
  py -3.12 -X utf8 src/kochi/k5_groups.py confirm   # 確かめ: 2022〜2026-09 を 1 回・土台 と 土台 + 選ばれた束(3 着内・勝ち)
  → out/kochi_k5.md(書き足し)

■ 決め
  - 土台 = feat2 の材料(k1 + クラス名・馬場)。束 = k4 の G1〜G4。
  - 選ぶ線 = 3 着内の対数尤度の伸びが 2 標準誤差(レースでまとめる)より大きい束。◎ は見るだけ。
  - 確かめは選ばれた束をまとめて 1 回。結果で選び直さない。
  - 各年の予想は V/k5/{名}_{年}.parquet に置き、落ちても済んだ分から再開する。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import k3_eval as k3  # noqa: E402

V = Path('C:/Users/kouki/nankan_ai/v3/kochi')
W = V / 'k5'
OUTMD = Path(__file__).resolve().parents[2] / 'out' / 'kochi_k5.md'
RK = ['date', 'jyo', 'race']
GROUPS = {'G1': 'x1_', 'G2': 'x2_', 'G3': 'x3_', 'G4': 'x4_', 'G5': 'x5_'}


def load():
    T = pd.read_parquet(V / 'feat2.parquet')
    E = pd.read_parquet(V / 'extra.parquet')
    T = T.merge(E, on=['date', 'race', 'umaban'], how='left', validate='1:1')
    if (V / 'si_n.parquet').exists():
        T = T.merge(pd.read_parquet(V / 'si_n.parquet'), on=['date', 'race', 'umaban'], how='left', validate='1:1')
    if (V / 'pace.parquet').exists():
        T = T.merge(pd.read_parquet(V / 'pace.parquet'), on=['date', 'race', 'umaban'], how='left', validate='1:1')
    base = [c for c in T.columns if c.startswith(k3.PFX) and not c.startswith(('x1_', 'x2_', 'x3_', 'x4_', 'x5_', 'n_'))
            and c not in ('jockey_cd', 'trainer_cd')]
    return T, base


def run(T, name, cols, years, targets=('Y3',)):
    W.mkdir(exist_ok=True)
    out = []
    for Y in years:
        f = W / f'{name}_{Y}.parquet'
        if f.exists():
            out.append(pd.read_parquet(f)); continue
        tr = T[(T.date >= '2008-01-01') & (T.date < f'{Y}-01-01')]
        te = T[(T.date >= f'{Y}-01-01') & (T.date < f'{Y + 1}-01-01')][RK + ['umaban', 'n', 'Y1', 'Y3']].copy()
        X = T.loc[te.index, cols]
        for y in targets:
            m = k3.train(tr, y, cols)
            k = 1 if y == 'Y1' else 3
            z = k3.logit(np.minimum(k / te.n.to_numpy(float), 0.99))
            te['p' + y[1]] = 1 / (1 + np.exp(-(z + m.predict(X.astype(float), raw_score=True))))
        te.to_parquet(f, index=False)
        out.append(te)
        print(name, Y, '済み', flush=True)
    return pd.concat(out)


def diff(P, Q):
    k = RK + ['umaban']
    M = P[k + ['Y3', 'Y1', 'p3']].merge(Q[k + ['p3']], on=k, suffixes=('', '_r'))
    q, r = np.clip(M.p3, 1e-6, 1 - 1e-6), np.clip(M.p3_r, 1e-6, 1 - 1e-6)
    M['d'] = (M.Y3 * np.log(q) + (1 - M.Y3) * np.log(1 - q)) - (M.Y3 * np.log(r) + (1 - M.Y3) * np.log(1 - r))
    g = M.groupby(RK).d.agg(['sum', 'size'])
    m = g['sum'].sum() / g['size'].sum()
    se = np.sqrt(((g['sum'] - m * g['size']) ** 2).sum()) / g['size'].sum()
    a, b = k3.score(M, 'p3'), k3.score(M.assign(p3=M.p3_r), 'p3')
    dh = a.hon - b.hon
    yr = M.groupby(M.date.dt.year).d.mean() * 1e4
    return dict(ll=m * 1e4, se2=2 * se * 1e4, hon0=b.hon.mean() * 100, hon1=a.hon.mean() * 100,
                hse2=2 * dh.std() / np.sqrt(len(dh)) * 100, t50=b.top5.mean() * 100, t51=a.top5.mean() * 100,
                years=' '.join(f'{int(y)}:{v:+.1f}' for y, v in yr.items()))


def select():
    T, base = load()
    years = range(2018, 2022)
    B = run(T, 'base', base, years)
    lines = ['# 高知版 k5: 束を選んで確かめる', '', '## 選び(2018〜2021・3 着内だけ・土台との差)', '',
             f'土台の材料 {len(base)} 個。線 = 対数尤度の伸び > 2 標準誤差。', '',
             '| 束 | 列 | 対数尤度 ×10^-4 | ◎ 3 着内率 | 上位 5 に 3 頭 | 年ごと | 選ぶ |', '|---|---:|---:|---:|---:|---|---|']
    pick = []
    for g, pf in GROUPS.items():
        add = [c for c in T.columns if c.startswith(pf)]
        d = diff(run(T, g, base + add, years), B)
        ok = d['ll'] > d['se2']
        if ok:
            pick.append(g)
        lines.append(f"| {g} | {len(add)} | {d['ll']:+.1f} ± {d['se2']:.1f} | {d['hon0']:.2f}→{d['hon1']:.2f}(± {d['hse2']:.2f}) | "
                     f"{d['t50']:.2f}→{d['t51']:.2f} | {d['years']} | {'○' if ok else '×'} |")
    lines += ['', f'選ばれた束: {", ".join(pick) or "なし"}', '']
    OUTMD.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (W / 'pick.txt').write_text(','.join(pick), encoding='utf-8')
    print('\n'.join(lines))


def confirm():
    T, base = load()
    pick = [g for g in (W / 'pick.txt').read_text(encoding='utf-8').split(',') if g]
    add = [c for c in T.columns if any(c.startswith(GROUPS[g]) for g in pick)]
    years = range(2022, 2027)
    B = run(T, 'cbase', base, years, ('Y3', 'Y1'))
    P = run(T, 'cpick', base + add, years, ('Y3', 'Y1'))
    d = diff(P, B)
    a = k3.score(P, 'p3')
    lines = ['## 確かめ(2022-01〜2026-09・1 回)', '', f'足した束: {", ".join(pick) or "なし"}({len(add)} 列)', '',
             f"- 3 着内の対数尤度/行の差 ×10^-4: {d['ll']:+.1f} ± {d['se2']:.1f}(年ごと {d['years']})",
             f"- ◎ 3 着内率: {d['hon0']:.2f}% → {d['hon1']:.2f}%(± {d['hse2']:.2f})",
             f"- 上位 5 に 3 頭: {d['t50']:.2f}% → {d['t51']:.2f}%",
             f"- ◎ 勝率: {k3.score(B, 'p3').win.mean() * 100:.2f}% → {a.win.mean() * 100:.2f}%", '']
    with open(OUTMD, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


def round2():
    """2 回目(2026-10-10・結果を見る前に決め): 土台 = feat2 + G2(確かめ済み)。展開の束 G5 を同じ線で選び、通れば 2022〜26 で 1 回確かめる。"""
    T, base = load()
    base = base + [c for c in T.columns if c.startswith('x2_')]
    add = [c for c in T.columns if c.startswith('x5_')]
    d = diff(run(T, 'G5', base + add, range(2018, 2022)), run(T, 'b2', base, range(2018, 2022)))
    ok = d['ll'] > d['se2']
    lines = ['', '## 2 回目: 展開の束 G5(土台 = feat2 + G2)', '',
             f"- 選び(2018〜2021): 対数尤度 {d['ll']:+.1f} ± {d['se2']:.1f}・◎ {d['hon0']:.2f}→{d['hon1']:.2f}(± {d['hse2']:.2f})・"
             f"上位 5 に 3 頭 {d['t50']:.2f}→{d['t51']:.2f}・年ごと {d['years']} → {'通る' if ok else '通らない'}"]
    if ok:
        yrs = range(2022, 2027)
        B, P = run(T, 'cpick', base, yrs, ('Y3', 'Y1')), run(T, 'c5', base + add, yrs, ('Y3', 'Y1'))
        d = diff(P, B)
        lines.append(f"- 確かめ(2022〜2026-09・1 回): 対数尤度 {d['ll']:+.1f} ± {d['se2']:.1f}・◎ {d['hon0']:.2f}→{d['hon1']:.2f}"
                     f"(± {d['hse2']:.2f})・上位 5 に 3 頭 {d['t50']:.2f}→{d['t51']:.2f}・◎ 勝率 "
                     f"{k3.score(B, 'p3').win.mean() * 100:.2f}→{k3.score(P, 'p3').win.mean() * 100:.2f}・年ごと {d['years']}")
    with open(OUTMD, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


def round3():
    """3 回目(決め書 out/kochi_si_plan.md): 南関の速さの指数に差し替え(a_・k_・p_ を抜いて n_ を入れる)。"""
    T, base = load()
    base = base + [c for c in T.columns if c.startswith('x2_')]
    new = [c for c in T.columns if c.startswith('n_')]
    rep = [c for c in base if not c.startswith(('a_', 'k_', 'p_'))] + new
    yrs = range(2018, 2022)
    B = run(T, 'b2', base, yrs)
    d = diff(run(T, 'rep', rep, yrs), B)
    da = diff(run(T, 'add', base + new, yrs), B)
    ok = d['ll'] > d['se2']
    f = lambda d: (f"対数尤度 {d['ll']:+.1f} ± {d['se2']:.1f}・◎ {d['hon0']:.2f}→{d['hon1']:.2f}(± {d['hse2']:.2f})・"
                   f"上位 5 に 3 頭 {d['t50']:.2f}→{d['t51']:.2f}・年ごと {d['years']}")
    lines = ['', '## 3 回目: 南関の速さの指数に差し替え(決め書 out/kochi_si_plan.md)', '',
             f'- 選び(2018〜2021)差し替え({len(rep)} 列): ' + f(d) + f" → {'通る' if ok else '通らない'}",
             f'- 見るだけ: 足した版({len(base + new)} 列): ' + f(da)]
    if ok:
        yrs = range(2022, 2027)
        Bc, P = run(T, 'cpick', base, yrs, ('Y3', 'Y1')), run(T, 'crep', rep, yrs, ('Y3', 'Y1'))
        dc = diff(P, Bc)
        lines.append('- 確かめ(2022〜2026-09・1 回): ' + f(dc) + f"・◎ 勝率 {k3.score(Bc, 'p3').win.mean() * 100:.2f}→"
                     f"{k3.score(P, 'p3').win.mean() * 100:.2f}")
    with open(OUTMD, 'a', encoding='utf-8') as fo:
        fo.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


def round3b():
    """3 回目の追記: 足した版(土台 + n_)を 2022〜2026-09 で 1 回確かめる。"""
    T, base = load()
    base = base + [c for c in T.columns if c.startswith('x2_')]
    add = base + [c for c in T.columns if c.startswith('n_')]
    yrs = range(2022, 2027)
    Bc, P = run(T, 'cpick', base, yrs, ('Y3', 'Y1')), run(T, 'cadd', add, yrs, ('Y3', 'Y1'))
    d = diff(P, Bc)
    lines = [f"- 確かめ(足した版・2022〜2026-09・1 回): 対数尤度 {d['ll']:+.1f} ± {d['se2']:.1f}・◎ {d['hon0']:.2f}→{d['hon1']:.2f}"
             f"(± {d['hse2']:.2f})・上位 5 に 3 頭 {d['t50']:.2f}→{d['t51']:.2f}・年ごと {d['years']}・◎ 勝率 "
             f"{k3.score(Bc, 'p3').win.mean() * 100:.2f}→{k3.score(P, 'p3').win.mean() * 100:.2f}"]
    with open(OUTMD, 'a', encoding='utf-8') as fo:
        fo.write(chr(10).join(lines) + chr(10))
    print(chr(10).join(lines))


if __name__ == '__main__':
    {'round3b': round3b, 'select': select, 'confirm': confirm, 'round2': round2, 'round3': round3}[sys.argv[1]]()
