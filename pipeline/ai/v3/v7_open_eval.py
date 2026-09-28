# -*- coding: utf-8 -*-
"""第 7 版 答え合わせの期間の採点(out/v7_open_plan.md の決めどおり)。予想 = v3/v7_open_preds.parquet(前日版)。

  py -3.12 -X utf8 src/v7_open_eval.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
KEY = ['track', 'race_date', 'race_no']


def md(t, index=True):
    d = t.reset_index() if index else t
    return chr(10).join(['| ' + ' | '.join(map(str, d.columns)) + ' |', '|' + '---|' * len(d.columns)]
                        + ['| ' + ' | '.join(map(str, r)) + ' |' for r in d.itertuples(index=False)])


def load():
    p = pd.read_parquet(V3 / 'v7_open_preds.parquet')
    p['race_no'], p['umaban'] = p.race_no.astype(int), p.umaban.astype(int)
    q = pd.concat([pd.read_parquet(V3 / f) for f in ('q_confirm.parquet', 'q_confirm_rakuten2023.parquet', 'q_sealed.parquet')])
    q['race_no'], q['umaban'] = q.race_no.astype(int), q.umaban.astype(int)
    q = q.drop_duplicates(KEY + ['umaban'], keep='first')
    p = p.merge(q[KEY + ['umaban', 'win', 'plc_lo']], on=KEY + ['umaban'], how='left')
    pay = pd.concat([pd.read_parquet(V3 / f) for f in ('db_payouts_confirm_2022.parquet', 'db_payouts_confirm_2022-11_2025-08.parquet',
                                                        'db_payouts_sealed_2025-09_2026-08.parquet')])
    pay['race_no'] = pay.race_no.astype(int)
    pay = pay.drop_duplicates(KEY, keep='last')
    plc = []
    for t, d, no, s in pay[KEY + ['payouts']].itertuples(index=False):
        for x in (json.loads(s) if isinstance(s, str) else s):
            if x['t'] == 'place':
                plc.append((t, d, int(no), int(x['c']), float(x['y'])))
    plc = pd.DataFrame(plc, columns=KEY + ['umaban', 'pay_plc']).groupby(KEY + ['umaban']).pay_plc.sum().reset_index()
    p = p.merge(pay[KEY].assign(has_pay=1), on=KEY, how='left').merge(plc, on=KEY + ['umaban'], how='left')
    p['pay_plc'] = p.pay_plc.fillna(0.0)
    p['pay_win'] = np.where(p.Y1 == 1, p.win * 100, 0.0)
    return p


def top(p, s, s2):
    return p.sort_values(KEY + [s, s2, 'umaban'], ascending=[True] * 3 + [False, False, True],
                         kind='mergesort').groupby(KEY, sort=False).head(1)


def main():
    p = load()
    L = ['# 第 7 版 答え合わせの期間(2022-01〜2026-08・前日版)', '', '決めは out/v7_open_plan.md。', '']
    a = top(p, 'v7pre_p3p', 'v7pre_p1').set_index(KEY)
    b = top(p, 'p3p_v6pre', 'p1_v6pre').set_index(KEY)
    f = p[p['pop'] == 1].drop_duplicates(KEY).set_index(KEY)
    R = pd.DataFrame({'v7': a.Y3, 'v6': b.Y3, 'year': a.year}).join(f.Y3.rename('fav'))
    R['date'] = R.index.get_level_values('race_date')
    rows = []
    for lab, g in [('全体', R)] + [(str(y), g) for y, g in R.groupby('year')]:
        dd = (g.v7 - g.v6).groupby(g.date).agg(['sum', 'size'])
        m = dd['sum'].sum() / dd['size'].sum()
        se = np.sqrt(((dd['sum'] - m * dd['size']) ** 2).sum()) / dd['size'].sum()
        rows.append(dict(期間=lab, レース=len(g), 第7版=round(100 * g.v7.mean(), 1), 第6版=round(100 * g.v6.mean(), 1),
                         差=round(100 * m, 2), 差の幅95=f'±{200 * se:.2f}', 一番人気=round(100 * g.fav.mean(), 1)))
    L += ['## 1. ◎ の 3 着以内率 %(差の幅 = 開催日ごとにまとめた 95% の幅)', '', md(pd.DataFrame(rows), False), '']
    x = p[(p.has_pay == 1) & p.win.notna() & (p.win > 0)].copy()
    x['ev'] = x.v7pre_p1 * x.win
    s = x[(x.v7pre_p1 >= 0.2) & (x.ev >= 1.2)]
    rows = [dict(期間='全体', 頭数=len(s), 回収率=round(s.pay_win.mean(), 1), 的中率=round(100 * s.Y1.mean(), 1))]
    rows += [dict(期間=str(y), 頭数=len(g), 回収率=round(g.pay_win.mean(), 1), 的中率=round(100 * g.Y1.mean(), 1)) for y, g in s.groupby('year')]
    L += ['## 2. 単勝「勝率 ≥ 20%・勝率 × 確定オッズ ≥ 1.2」の回収率 %', '', md(pd.DataFrame(rows), False), '']
    # 参考
    PB = [0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.01]
    EB = [0, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 99]
    lab = lambda B, fm: [fm(a_, b_) for a_, b_ in zip(B, B[1:])]
    x['pb'] = pd.cut(x.v7pre_p1, PB, right=False, labels=lab(PB, lambda a_, b_: f'{int(a_*100)}〜{int(b_*100) if b_ < 1 else 100}%'))
    x['eb'] = pd.cut(x.ev, EB, right=False, labels=lab(EB, lambda a_, b_: f'{a_}〜{b_ if b_ < 99 else ""}'))
    x['ev3'] = x.v7pre_p3p * x.plc_lo
    x['eb3'] = pd.cut(x.ev3, EB, right=False, labels=lab(EB, lambda a_, b_: f'{a_}〜{b_ if b_ < 99 else ""}'))
    def grid(g, eb, pay):
        r = g.pivot_table(index='pb', columns=eb, values=pay, aggfunc='mean', observed=True).round(0)
        n = g.pivot_table(index='pb', columns=eb, values=pay, aggfunc='size', observed=True)
        c = (r.astype('Int64').astype(str) + '(' + n.astype('Int64').astype(str) + ')').where(n.notna(), '—')
        c.index.name = '勝率 / ずれ'
        return c
    band = x.groupby(pd.cut(x.v7pre_p1, [0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 1.01], right=False), observed=True).agg(
        頭数=('Y1', 'size'), 予想勝率=('v7pre_p1', 'mean'), 実際の勝率=('Y1', 'mean'), 単勝回収率=('pay_win', 'mean'),
        実際の3着内=('Y3', 'mean'), 複勝回収率=('pay_plc', 'mean'))
    for c in ('予想勝率', '実際の勝率', '実際の3着内'):
        band[c] = (100 * band[c]).round(1)
    band[['単勝回収率', '複勝回収率']] = band[['単勝回収率', '複勝回収率']].round(1)
    w = x[x.Y1 == 1].copy()
    m = 1 / x.win
    x['m1'] = m / m.groupby([x[k] for k in KEY]).transform('sum')
    w = x[x.Y1 == 1]
    sharp = w.groupby('year').apply(lambda g: pd.Series({'人気': round(100 * np.exp(np.log(g.m1).mean()), 1),
                                                          'AI': round(100 * np.exp(np.log(g.v7pre_p1).mean()), 1)}))
    L += ['## 参考(判断には使わない)', '', '### 勝率の帯', '', md(band), '',
          '### 勝ち馬に付けていた確率(ふつうの値 %)', '', md(sharp), '',
          '### 単勝の回収率 %(頭数)・勝率 × ずれ', '', md(grid(x, 'eb', 'pay_win')), '',
          '### 複勝の回収率 %(頭数)・勝率 × ずれ(3 着内率 × 複勝オッズの下)', '', md(grid(x, 'eb3', 'pay_plc')), '']
    (REPO / 'out' / 'v7_open.md').write_text(chr(10).join(L) + chr(10), encoding='utf-8')
    print(chr(10).join(L))


if __name__ == '__main__':
    main()
