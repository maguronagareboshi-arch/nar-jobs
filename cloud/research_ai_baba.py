#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-11-03)。予想 AI base-v1 の馬場差を「今の作り方(A)」と「サイトの馬場差(B)」で比べる。

  site    : 公開 JSON baba-hist/<prefix>.json(14 場)を TSV(track, race_date, d, d1)に落とす(読むだけ)
  fit     : 特徴量 CSV から base_v1 の PARAMS・ROUNDS_BIN・ROUNDS_WIN・feature_cols(morning)そのままで
            学習= 2025-10-31 まで、試験= 2025-11-01〜最新 の予測を parquet に
  compare : A と B の予測を突き合わせ、B−A をレース単位の対ブートストラップ 1,000 回で 95% 区間
⛔本番 DB にも公開バケットにも書かない。
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'pipeline' / 'ai'))
sys.path.insert(0, str(ROOT / 'cloud'))

BASE = 'https://qgsnsdjvzzeazbazjlwa.supabase.co/storage/v1/object/public/cond-stats/v1/baba-hist/'
TRAIN_TO = pd.Timestamp('2025-10-31')
TEST_FROM = pd.Timestamp('2025-11-01')
FRESH_FROM = pd.Timestamp('2026-10-01')
B_N = 1000
KEYS = ['track', 'race_date', 'race_no', 'runner_number']


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ---------------------------------------------------------------- site
def cmd_site(out):
    from baba import TRACK2PREFIX
    n = 0
    with open(out, 'w', encoding='utf-8') as f:
        for track, prefix in TRACK2PREFIX.items():
            with urllib.request.urlopen(BASE + prefix + '.json', timeout=60) as r:
                days = json.load(r).get('days') or {}
            k = 0
            for d, v in sorted(days.items()):
                if v.get('d') is None:
                    continue
                d1 = v.get('d1')
                f.write('%s\t%s\t%s\t%s\n' % (track, d, v['d'], '\\N' if d1 is None else d1))
                k += 1
            log(track, prefix, k, 'days')
            n += k
    log('site rows', n)


# ---------------------------------------------------------------- fit
def cmd_fit(feat, out):
    import lightgbm as lgb
    import base_v1 as B
    df = B.load_feat(feat)
    df = df[df['finish'].notna() & (df['finish_note'].fillna('') == '')].copy()
    df['y'] = df['y_top3'].astype(int)
    tr = df[df['race_date'] <= TRAIN_TO]
    te = df[df['race_date'] >= TEST_FROM].copy()
    cols = B.feature_cols(tr, 'morning')
    log('train', len(tr), 'test', len(te), 'cols', len(cols), 'test to', te['race_date'].max().date())
    t0 = time.time()
    bst_b = lgb.train(B.PARAMS, lgb.Dataset(tr[cols], tr['y']), num_boost_round=B.ROUNDS_BIN)
    log('binary', round(time.time() - t0), 's')
    t0 = time.time()
    bst_w = lgb.train(B.PARAMS, lgb.Dataset(tr[cols], B.win_label(tr)), num_boost_round=B.ROUNDS_WIN)
    log('win', round(time.time() - t0), 's')
    te['p_b'] = bst_b.predict(te[cols])
    te['p_w'] = B.race_norm(bst_w.predict(te[cols]), te['rid'])
    te['y_w'] = B.win_label(te)
    o = te[KEYS + ['rid', 'finish', 'y', 'y_w', 'p_b', 'p_w']].copy()
    o['race_date'] = o['race_date'].dt.strftime('%Y-%m-%d')
    o.to_parquet(out, index=False)
    log('saved', out, len(o), 'rows', 'n_cols', len(cols))


# ---------------------------------------------------------------- compare
def wauc(o, y, w):
    """行の重み付き AUC(o= 予測の昇順の並び・同点は無視= 連続値なので無視できる)"""
    s_y, s_w = y[o], w[o]
    neg_cum = np.cumsum(s_w * (1 - s_y)) - s_w * (1 - s_y)
    pos = s_y == 1
    wp = s_w[pos].sum()
    wn = (s_w * (1 - s_y)).sum()
    return float((s_w[pos] * neg_cum[pos]).sum() / (wp * wn)) if wp > 0 and wn > 0 else np.nan


def metrics_boot(m):
    """m= A/B 突き合わせ済みの行。戻り= {指標: (A, B, B−A, lo, hi)}"""
    eps = 1e-12
    m = m.copy()
    m['race_i'] = pd.factorize(m['rid'])[0]
    R = int(m['race_i'].max()) + 1
    ri = m['race_i'].values
    y = m['y'].values.astype(float)
    out = {}
    per = {}
    for s in ('a', 'b'):
        p = np.clip(m['p_b_' + s].values, eps, 1 - eps)
        per['ll3_' + s] = np.bincount(ri, -(y * np.log(p) + (1 - y) * np.log(1 - p)), R)
        pw = np.clip(m['p_w_' + s].values, eps, 1)
        per['llw_' + s] = np.bincount(ri, -m['y_w'].values * np.log(pw), R)
        top = m.assign(_p=m['p_b_' + s].values).sort_values(['race_i', '_p'], ascending=[True, False]) \
               .drop_duplicates('race_i')
        t3 = np.zeros(R); tw = np.zeros(R)
        t3[top['race_i'].values] = top['y'].values
        tw[top['race_i'].values] = top['y_w'].values
        per['t3_' + s] = t3
        per['tw_' + s] = tw
    nrun = np.bincount(ri, None, R).astype(float)
    nwin = np.bincount(ri, m['y_w'].values.astype(float), R)
    okw = (nwin == 1).astype(float)   # 1 着がちょうど 1 頭のレースだけ 1 着の損失に使う
    rng = np.random.default_rng(20261103)
    W = np.vstack([np.ones(R)] + [np.bincount(rng.integers(0, R, R), None, R) for _ in range(B_N)])

    def agg(num, den):
        return (W @ num) / (W @ den)

    defs = {
        '3着内の対数損失': (lambda s: agg(per['ll3_' + s], nrun)),
        '1着の対数損失(レース内正規化)': (lambda s: agg(per['llw_' + s] * okw, okw)),
        '最上位の3着内率': (lambda s: agg(per['t3_' + s], np.ones(R))),
        '最上位の勝率': (lambda s: agg(per['tw_' + s], np.ones(R))),
    }
    for name, fn in defs.items():
        va, vb = fn('a'), fn('b')
        d = vb[1:] - va[1:]
        out[name] = (va[0], vb[0], vb[0] - va[0], np.percentile(d, 2.5), np.percentile(d, 97.5))
    # AUC(行の重み= そのレースの抽出回数)
    va, vb = [], []
    oa = np.argsort(m['p_b_a'].values, kind='mergesort')
    ob = np.argsort(m['p_b_b'].values, kind='mergesort')
    for k in range(B_N + 1):
        w = W[k][ri]
        va.append(wauc(oa, y, w))
        vb.append(wauc(ob, y, w))
    va, vb = np.array(va), np.array(vb)
    d = vb[1:] - va[1:]
    out['3着内の AUC'] = (va[0], vb[0], vb[0] - va[0], np.percentile(d, 2.5), np.percentile(d, 97.5))
    return out, R, len(m)


def cmd_compare(a, b, match, out, meta, title=None, lb='サイト'):
    import base_v1 as Bv
    A = pd.read_parquet(a)
    Bp = pd.read_parquet(b)
    m = A.merge(Bp[KEYS + ['p_b', 'p_w']], on=KEYS, suffixes=('_a', '_b'), how='inner')
    log('A', len(A), 'B', len(Bp), 'joined', len(m))
    m['race_date'] = pd.to_datetime(m['race_date'])
    nk = m['track'].isin(Bv.NANKAN)
    bn = m['track'].isin(Bv.BANEI)
    groups = [
        ('試験 1 年全体', '全場', m),
        ('試験 1 年全体', '南関 4 場', m[nk]),
        ('試験 1 年全体', '他場(ばんえい除く)', m[~nk & ~bn]),
        ('試験 1 年全体', 'ばんえい' if title else 'ばんえい(値は A と同じ)', m[bn]),
        ('2026-10-01 以降(初見)', '全場', m[m['race_date'] >= FRESH_FROM]),
        ('2026-10-01 以降(初見)', '南関 4 場', m[(m['race_date'] >= FRESH_FROM) & nk]),
        ('2026-10-01 以降(初見)', '他場(ばんえい除く)', m[(m['race_date'] >= FRESH_FROM) & ~nk & ~bn]),
    ]
    L = ['# ' + (title or '予想 AI base-v1 の馬場差= 今の作り方(A) と サイトの馬場差(B) の比べ(2026-11-03)'), '']
    L += ['- ' + x for x in meta]
    L += ['- 学習= 〜2025-10-31・試験= 2025-11-01〜%s・模型= base_v1 の PARAMS(seed 7)・ROUNDS_BIN %d・ROUNDS_WIN %d・列= morning'
          % (m['race_date'].max().date(), Bv.ROUNDS_BIN, Bv.ROUNDS_WIN),
          '- 区間= レース単位の対ブートストラップ %d 回の 95%%。対数損失は小さいほど良い(B−A が負= B が良い)。'
          '1 着の対数損失= 1 着が 1 頭のレースで −log(その馬の正規化した確率)の平均' % B_N,
          '- 突き合わせ行 A %d・B %d・両方 %d' % (len(A), len(Bp), len(m)), '']
    for per, ven, g in groups:
        if len(g) == 0:
            continue
        res, R, n = metrics_boot(g)
        L += ['## %s・%s(%d レース・%d 頭)' % (per, ven, R, n), '',
              '| 指標 | A 今 | B %s | B−A | 95%% 区間 |' % lb, '|---|---:|---:|---:|---|']
        for k, (va, vb, d, lo, hi) in res.items():
            L.append('| %s | %.5f | %.5f | %+.5f | %+.5f 〜 %+.5f |' % (k, va, vb, d, lo, hi))
        L.append('')
        log('done', per, ven)
    # 場ごと(試験 1 年全体)
    L += ['## 場ごと(試験 1 年全体)', '',
          '| 場 | レース | 3着内の対数損失 B−A | 95% 区間 | 最上位の3着内率 B−A | 95% 区間 |', '|---|---:|---:|---|---:|---|']
    for t in sorted(m['track'].unique()):
        res, R, n = metrics_boot(m[m['track'] == t])
        a1 = res['3着内の対数損失']; a2 = res['最上位の3着内率']
        L.append('| %s | %d | %+.5f | %+.5f 〜 %+.5f | %+.4f | %+.4f 〜 %+.4f |'
                 % (t, R, a1[2], a1[3], a1[4], a2[2], a2[3], a2[4]))
    L.append('')
    if match and os.path.exists(match):
        L += ['## サイト値の付いた割合(14 場・結果のある場日)', '', '| 期間 | 場日 | サイト値あり | 割合 |', '|---|---:|---:|---:|']
        mt = pd.read_csv(match, sep='\t', header=None, names=['per', 'n', 'k'])
        for _, r in mt.iterrows():
            L.append('| %s | %d | %d | %.1f%% |' % (r['per'], r['n'], r['k'], 100.0 * r['k'] / max(r['n'], 1)))
        L.append('')
    Path(out).write_text('\n'.join(L), encoding='utf-8')
    log('wrote', out)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    s = sp.add_parser('site'); s.add_argument('--out', required=True)
    f = sp.add_parser('fit'); f.add_argument('--feat', required=True); f.add_argument('--out', required=True)
    c = sp.add_parser('compare')
    c.add_argument('--a', required=True); c.add_argument('--b', required=True)
    c.add_argument('--match'); c.add_argument('--out', required=True); c.add_argument('--meta', action='append', default=[])
    c.add_argument('--title'); c.add_argument('--lb', default='サイト')
    a = ap.parse_args()
    if a.cmd == 'site':
        cmd_site(a.out)
    elif a.cmd == 'fit':
        cmd_fit(a.feat, a.out)
    else:
        cmd_compare(a.a, a.b, a.match, a.out, a.meta, a.title, a.lb)


if __name__ == '__main__':
    main()
