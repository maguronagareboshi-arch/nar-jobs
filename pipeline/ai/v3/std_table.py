# -*- coding: utf-8 -*-
"""毎回の表に並べる数字(ユーザー承認 2026-09-27「ウ」)。判定の指標は変えない。並べるだけ。

足した 3 つ:
  1. ◎ の単勝回収率 = ◎ が勝てば単勝払戻(100 円あたり)の和 ÷(100 × レース数)。オッズの欠けたレースは除く。
  2. 4 番人気以下の ◎ = ◎ の確定の人気が 4 番人気以下のレースだけで、◎ の 3 着以内率と勝率(件数も出す)。
     目安として「同じ人気の馬の平均の 3 着以内率」(全頭の人気ごとの率を ◎ の人気で平均)を並べる。
  3. 接戦の ◎ = AI の p3′ の 1 位 − 2 位 が、比べる期間の全レースの下 1/4 のレースだけの ◎ の 3 着以内率。
人気・オッズは採点にだけ使う(予想には入れない)。1 番人気の列は同じレースでの 1 番人気の馬。

使い方(p = v7_open_eval.load() と同じ形: 1 行 = 1 頭・KEY・umaban・Y1・Y3・pop・pay_win・year と予想の列):
  import std_table as st
  R = st.frame(p, {'第7版e': ('v7epre_p3p', 'v7epre_p1')}, close_by='第7版e')
  print(st.md(st.rows(R, ['第7版e'])))
"""
import numpy as np
import pandas as pd

KEY = ['track', 'race_date', 'race_no']


def _top(p, s, s2):
    return p.sort_values(KEY + [s, s2, 'umaban'], ascending=[True] * 3 + [False, False, True],
                         kind='mergesort').groupby(KEY, sort=False).head(1).set_index(KEY)


def frame(p, ais, close_by):
    """1 行 = 1 レース。ais = {名前: (p3′ の列, p1 の列)}。close_by の AI の 1 位 − 2 位 で接戦を決める。"""
    fav = p[p['pop'] == 1].drop_duplicates(KEY).set_index(KEY)
    first = None
    cols = {}
    for n, (s, s2) in ais.items():
        t = _top(p, s, s2)
        first = t if first is None else first
        cols.update({f'{n}|Y3': t.Y3, f'{n}|Y1': t.Y1, f'{n}|pay': t.pay_win, f'{n}|pop': t['pop']})
    R = pd.DataFrame(cols)
    R['1番人気|Y3'], R['1番人気|Y1'], R['1番人気|pay'] = fav.Y3, fav.Y1, fav.pay_win
    R['year'] = first.year
    b3 = p[p['pop'].notna()].groupby('pop').Y3.mean()
    for n in ais:
        R[f'{n}|base3'] = R[f'{n}|pop'].map(b3)
    s = ais[close_by][0]
    srt = p.sort_values(KEY + [s], ascending=[True] * 3 + [False], kind='mergesort')
    rk = srt.groupby(KEY, sort=False).cumcount()
    gap = srt[rk == 0].set_index(KEY)[s] - srt[rk == 1].set_index(KEY)[s]
    R['gap'] = gap
    R['close'] = (R.gap <= R.gap.quantile(0.25)).astype(int)
    return R


def _pct(v):
    return '—' if v is None or (isinstance(v, float) and np.isnan(v)) else f'{100 * v:.1f}%'


def rows(R, names):
    """AI ごと + 1 番人気 の 1 行。列 = 既存の 3 つ(3 着以内・勝率・レース数)+ 足した 3 つ。"""
    out = []
    for n in list(names) + ['1番人気']:
        pay = R[f'{n}|pay']
        r = {'AI': n, 'レース': len(R), '◎3着以内': _pct(R[f'{n}|Y3'].mean()), '◎勝率': _pct(R[f'{n}|Y1'].mean()),
             '◎単勝回収率': _pct(pay.dropna().mean() / 100) if pay.notna().any() else '—'}
        if n == '1番人気':
            r['4番人気以下の◎(件数・3着以内・勝率)'] = '—'
        else:
            lo = R[R[f'{n}|pop'] >= 4]
            r['4番人気以下の◎(件数・3着以内・勝率)'] = (f'{len(lo):,}・{_pct(lo[f"{n}|Y3"].mean())}'
                                                    f'(同じ人気の平均 {_pct(lo[f"{n}|base3"].mean())})・{_pct(lo[f"{n}|Y1"].mean())}')
        c = R[R.close == 1]
        r[f'接戦の◎3着以内({len(c):,} R)'] = _pct(c[f'{n}|Y3'].mean())
        out.append(r)
    return out


def md(rows_):
    ks = list(rows_[0])
    return '\n'.join(['| ' + ' | '.join(ks) + ' |', '|' + '---|' * len(ks)] +
                     ['| ' + ' | '.join(str(r[k]) for k in ks) + ' |' for r in rows_])
