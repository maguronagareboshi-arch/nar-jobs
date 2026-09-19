# -*- coding: utf-8 -*-
"""§224a D・E 単勝の払戻の係数(帯別)と、色付けの判定に使う回収率の表。**既定は読むだけ**(--write のときだけ nar_meta 2 行)。

  py -3.12 -X utf8 pipeline/ai/ev_coef.py --wf <base_v1.py fit --wf-out の parquet> [--flat <flat.parquet>] [--payouts <tsv>] [--write]

材料= base_v1.py の 12 か月ウォークフォワードの p_win(レース内で合計 1・較正前)× 締切 10 分前の単勝(o10)× 確定の単勝払戻。
- 較正= 月ごとに**その月より前の WF の月だけ**で 10 帯の表を作り(base_v1.cal_table)、その月の p_win を置き換えて合計 1 に。
  ⛔最初の月は前が無い= 較正も係数も作れないので**数えない**(表に出す)。⛔市場(人気・オッズ)は較正に使わない。
- D 係数 c= 勝った馬の「払戻 ÷ (o10×100)」の中央値を 10 分前の単勝オッズ帯ごとに。nar_meta 'ev_coef:v1' は全期間で作る。
- E 回収率= 較正後の p_win × その月より前の月の c × o10 ≥ τ の馬を単勝 100 円ずつ買った回収率(オッズ帯ごと)。
  c の無い帯(前の月に勝ち馬の払戻が無い)は買わない。⛔τ は 1 つだけ(後から動かさない)。
- 較正の前後の表= 帯(較正前の p_win)ごとに 件数・見込みの平均(前/後)・実際の 1 着率。
⛔材料のファイルはリポに入れない。⛔表の数字はリポに書かない(標準出力だけ)。
"""
import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import base_v1                                          # noqa: E402
from odds_hist import HOME                              # noqa: E402

TAU = 1.2
ODDS_BANDS = ((0, 3.0, '<3'), (3.0, 10.0, '3-9.9'), (10.0, 30.0, '10-29.9'), (30.0, 100.0, '30-99.9'), (100.0, 1e12, '>=100'))
KEY_COEF, KEY_CHECK = 'ev_coef:v1', 'ev_check:v1'


def odds_band(o):
    return next(lab for lo, hi, lab in ODDS_BANDS if lo <= o < hi)


def load(wf, flat, payouts):
    d = pd.read_parquet(wf)
    d['day'] = pd.to_datetime(d['race_date']).dt.strftime('%Y-%m-%d')
    d['no'] = d['rid'].str.rsplit('|', n=1).str[1].astype(int)
    d['ym'] = d['day'].str[:7]
    fl = pd.read_parquet(flat, columns=['track', 'race_date', 'race_no', 'runner_number', 'o10'])
    fl['day'] = pd.to_datetime(fl['race_date']).dt.strftime('%Y-%m-%d')
    fl = fl.rename(columns={'race_no': 'no'})[['track', 'day', 'no', 'runner_number', 'o10']]
    d = d.merge(fl, on=['track', 'day', 'no', 'runner_number'], how='left')
    pay = {}
    with open(payouts, encoding='utf-8') as f:
        for line in f:
            t, day, no, p = line.rstrip('\n').split('\t')
            for x in json.loads(p):
                if x.get('t') == 'win':
                    pay[(t, day, int(no), int(x['c']))] = float(x['y'])
    d['pay'] = [pay.get((t, day, int(no), int(u)), np.nan) for t, day, no, u in zip(d['track'], d['day'], d['no'], d['runner_number'])]
    return d


def calibrate_prior(d):
    """月ごとに前の月だけの較正表で置き換えて合計 1。⛔最初の月は p_cal= NaN(数えない)"""
    d = d.sort_values(['day', 'rid', 'runner_number']).copy()
    d['p_cal'] = np.nan
    months = sorted(d['ym'].unique())
    for ym in months[1:]:
        prior = d[d['ym'] < ym]
        cal = base_v1.cal_table(prior['p_win'].values, prior['y'].values)
        cur = d['ym'] == ym
        c = pd.Series(base_v1.win_calibrate(d.loc[cur, 'p_win'].values, cal), index=d.index[cur])
        tot = c.groupby(d.loc[cur, 'rid']).transform('sum')
        d.loc[cur, 'p_cal'] = np.where(tot > 0, c / tot.where(tot > 0, 1.0), d.loc[cur, 'p_win'])
    return d, months


def cal_report(d, months):
    """帯(較正前の p_win)ごとの 件数・見込みの平均(前/後)・実際の 1 着率。数えるのは 2 か月目から"""
    e = d[d['ym'] > months[0]]
    edges = base_v1.CAL_EDGES
    b = np.clip(np.digitize(e['p_win'].values, edges[1:-1]), 0, len(edges) - 2)
    rows = []
    for i in range(len(edges) - 1):
        m = b == i
        n = int(m.sum())
        if not n:
            rows.append({'band': '%g-%g%%' % (edges[i] * 100, edges[i + 1] * 100), 'n': 0})
            continue
        pre, post, act = float(e['p_win'].values[m].mean()), float(e['p_cal'].values[m].mean()), float(e['y'].values[m].mean())
        rows.append({'band': '%g-%g%%' % (edges[i] * 100, edges[i + 1] * 100), 'n': n, 'pred_before': round(pre * 100, 3),
                     'pred_after': round(post * 100, 3), 'actual': round(act * 100, 3),
                     'gap_before': round(abs(pre - act) * 100, 3), 'gap_after': round(abs(post - act) * 100, 3)})
    return rows


def coef_by_band(w):
    """勝った馬の 払戻 ÷ (o10×100) の中央値(帯ごと)"""
    w = w[(w['y'] == 1) & w['o10'].notna() & (w['o10'] > 0) & w['pay'].notna()]
    out, n = {}, {}
    for lab in (x[2] for x in ODDS_BANDS):
        r = [p / (o * 100) for p, o in zip(w['pay'], w['o10']) if odds_band(o) == lab]
        n[lab] = len(r)
        out[lab] = round(statistics.median(r), 4) if r else None
    return out, n


def ev_check(d, months):
    """E= 較正後 p_win × 前の月の c × o10 ≥ τ を単勝 100 円ずつ。帯ごとの 点数と回収率(%)"""
    tot = {lab: [0, 0.0] for lab in (x[2] for x in ODDS_BANDS)}
    for ym in months[1:]:
        c, _n = coef_by_band(d[d['ym'] < ym])
        cur = d[(d['ym'] == ym) & d['o10'].notna() & (d['o10'] > 0) & d['p_cal'].notna()]
        for p, o, y, pay in zip(cur['p_cal'], cur['o10'], cur['y'], cur['pay']):
            lab = odds_band(o)
            if c.get(lab) is None or p * c[lab] * o < TAU:
                continue
            tot[lab][0] += 1
            if y == 1 and pay == pay:
                tot[lab][1] += pay
    return {lab: {'n': n, 'ret': round(100.0 * s / (100.0 * n), 1) if n else None} for lab, (n, s) in tot.items()}


def write_meta(rows):
    from load_nar_official import upsert
    base, key = base_v1.creds()
    st, err = upsert(base, key, 'nar_meta', 'key', rows)
    if st not in (200, 201, 204):
        raise SystemExit(f'nar_meta upsert failed: {st} {err}')
    base_v1.log('nar_meta', ' '.join(r['key'] for r in rows), 'written')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wf', required=True)
    ap.add_argument('--flat', default=str(HOME / 'keibaodds' / 'flat.parquet'))
    ap.add_argument('--payouts', default=str(HOME / 'payouts_2024.tsv'))
    ap.add_argument('--write', action='store_true', help='nar_meta に ev_coef:v1 と ev_check:v1 を書く(既定は書かない)')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    d = load(a.wf, a.flat, a.payouts)
    d, months = calibrate_prior(d)
    races = d['rid'].nunique()
    with_odds = d[d['o10'].notna()]['rid'].nunique()
    base_v1.log('WF', months[0], '〜', months[-1], len(d), 'rows', races, 'races・10 分前の単勝があるレース', with_odds,
                '・数えない最初の月', months[0])
    print('CAL', json.dumps(cal_report(d, months), ensure_ascii=False))
    coef, n = coef_by_band(d)
    asof = d['day'].max()
    ev_coef = {'win': coef, 'n': n, 'months': [months[0], months[-1]], 'asof': asof}
    ev_chk = {'win': ev_check(d, months), 'tau': TAU, 'cal': base_v1.CAL_ID, 'months': [months[1], months[-1]], 'asof': asof}
    print('EV_COEF', json.dumps(ev_coef, ensure_ascii=False))
    print('EV_CHECK', json.dumps(ev_chk, ensure_ascii=False))
    if a.write:
        now = dt.datetime.now(base_v1.JST).isoformat(timespec='seconds')
        write_meta([{'key': KEY_COEF, 'value': ev_coef, 'updated_at': now},
                    {'key': KEY_CHECK, 'value': ev_chk, 'updated_at': now}])
    else:
        base_v1.log('write=no(nar_meta は書いていない)')


if __name__ == '__main__':
    main()
