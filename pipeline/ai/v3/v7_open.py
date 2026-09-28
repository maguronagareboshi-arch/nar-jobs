# -*- coding: utf-8 -*-
"""第 7 版 前日版: 答え合わせの期間(2022-01〜2026-08)の予想(ユーザー承認 2026-09-27)。既存の台本は import して呼ぶだけ。

  py -3.12 -X utf8 src/v7_open.py   # → v3/feat_v7_open.parquet・v3/v7_open_preds.parquet

  1. 材料 = feat_t6_open の全行 + v7_feat_b.build の b7_ 列(生の表 = RAW + DB の confirm・sealed。t3_open.sources のそろえ方:
     _align・finish_note の書き方・馬の鍵「名前|生年」)。第 6 版の表から読む列 = feat_t6_explore の 2021 + feat_t6_open。
  2. 通し試験 = 同じ build の 2021 の行の b7_ 列が feat_v7b_explore と全セル一致(|差| ≤ 1e-9・両方欠けも一致)。
  3. 区切り(t4_open.SEGS)ごとに、feat_t6_explore+feat_v7b_explore と feat_v7_open の区切りの始まりより前で Y1・Y3 を学び直す。
     p1 = Y1 をレース内で合計 1・p3 = max(Y3, p1)・p3′ = t6_base.p3prime。feat_v7_open があれば 1 は飛ばす(途中からの再開)。
"""
import json
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_open  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t6_base  # noqa: E402
import v7_feat_b as vb  # noqa: E402
from day5_forward_features import _align  # noqa: E402
from load_outcomes import load_archive  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
KEY = d3.KEY
END = '2026-09-01'
FEAT_OUT = V3 / 'feat_v7_open.parquet'
PRED_OUT = V3 / 'v7_open_preds.parquet'
CFG = {'Y1': (31, 500, 400), 'Y3': (15, 100, 1200)}
COLS = json.loads((V3 / 'v7_select.json').read_text(encoding='utf-8'))['cols']
B7 = [c for c in COLS if c.startswith('b7_')]
assert len(COLS) == 138 and len(B7) == 20 and all(c[:4] in ('b7_k', 'b7_g') for c in B7)
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def nk(df):
    df = df.copy()
    df['race_date'] = df.race_date.astype(str)
    df['race_no'] = df.race_no.astype(int)
    df['umaban'] = df.umaban.astype(int)
    return df


def raw_all():
    out = {}
    for name in ('runs', 'facts', 'races'):
        a = load_archive(name)
        assert a.race_date.max() < '2022-01-01'
        d = pd.concat([a] + [_align(pd.read_parquet(V3 / f'db_{name}_{p}_{t3_open.FILES[p]}.parquet'), a)
                             for p in ('confirm', 'sealed')], ignore_index=True)
        d['race_no'] = d.race_no.astype(int)
        assert d.race_date.max() < END, name
        out[name] = d
    out['runs']['finish_note'] = out['runs'].finish_note.replace(t3_open.NOTE)
    f = out['facts']
    f['horse_key'] = f.horse_key.str.replace(r'\|(\d{4})-\d\d-\d\d$', r'|\1', regex=True)
    return out['runs'], out['facts'], out['races']


def make_feat():
    X6 = nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    O6 = nk(pd.read_parquet(V3 / 'feat_t6_open.parquet'))
    assert len(O6) == 172738 and O6.race_date.min() >= '2022-01-01' and O6.race_date.max() < END
    fc = KEY + ['umaban', 'year', 'Y3'] + vb.FCOLS
    F = pd.concat([X6[X6.race_date >= '2021-01-01'][fc], O6[fc]], ignore_index=True)
    F = F.sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    vb.load_F = lambda day: F  # 第 6 版の表から読む列 = explore の 2021 + open(v7_feat_b は直さない)
    runs, facts, races = raw_all()
    log('生の表', len(runs), len(facts), len(races))
    R = nk(vb.build(runs, facts, races, parts=('b',)))
    bc = [c for c in R.columns if c.startswith('b7_')]
    # 2. 通し試験(2021)
    E = nk(pd.read_parquet(V3 / 'feat_v7b_explore.parquet'))
    a = E[E.race_date.str[:4] == '2021'].set_index(KEY + ['umaban'])[bc].sort_index()
    b = R[R.race_date.str[:4] == '2021'].set_index(KEY + ['umaban'])[bc].sort_index()
    assert a.index.equals(b.index), '2021 の行が一致しない'
    A, B = a.to_numpy(float), b.to_numpy(float)
    eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
    bad = {c: int((~eq[:, i]).sum()) for i, c in enumerate(bc) if not eq[:, i].all()}
    log('通し試験 一致', int(eq.sum()), '/', eq.size, '列', len(bc), '合わない列', bad)
    assert not bad, f'通し試験で合わない列 {bad}'
    # 3. 保存
    Ro = R[R.race_date >= '2022-01-01']
    T = O6.merge(Ro[KEY + ['umaban'] + B7], on=KEY + ['umaban'], how='left', validate='1:1')
    assert len(T) == 172738
    meta = [c for c in O6.columns if c not in COLS and c not in KEY + ['umaban']]
    T = T[KEY + ['umaban'] + COLS + meta]
    T.to_parquet(FEAT_OUT, index=False)
    log('保存', FEAT_OUT, T.shape, 'meta', meta)
    return T


def train(tr, target):
    cfg = CFG[target]
    z = d3.logit((1 if target == 'Y1' else 3) / tr.n.to_numpy(float))
    prm = dict(d3.BASE, num_leaves=cfg[0], min_data_in_leaf=cfg[1])
    return lgb.train(prm, lgb.Dataset(tr[COLS].astype(float), label=tr[target].to_numpy(float), init_score=z),
                     num_boost_round=cfg[2])


def main():
    T = nk(pd.read_parquet(FEAT_OUT)) if FEAT_OUT.exists() else make_feat()
    assert len(T) == 172738
    X6 = nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XB = nk(pd.read_parquet(V3 / 'feat_v7b_explore.parquet'))
    X = X6.merge(XB[KEY + ['umaban'] + B7], on=KEY + ['umaban'], how='left', validate='1:1')
    assert len(X) == len(X6) and X.race_date.max() < '2022-01-01'
    assert set(T.columns) <= set(X.columns)
    ALL = o.sort4(pd.concat([X[list(T.columns)], T], ignore_index=True))
    assert not ALL.duplicated(KEY + ['umaban']).any()
    P = []
    for name, lo, hi in o.SEGS:
        tr = ALL[ALL.race_date < lo]
        te = o.seg_rows(T, lo, hi)
        r = {}
        for t in ('Y1', 'Y3'):
            m = train(tr, t)
            z = d3.logit((1 if t == 'Y1' else 3) / te.n.to_numpy(float))
            r[t] = d3.sig(z + m.predict(te[COLS].astype(float), raw_score=True))
        x = te[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop']].copy()
        x['seg'] = name
        p1 = r['Y1'] / pd.Series(r['Y1'], index=x.index).groupby([x[k] for k in KEY]).transform('sum').to_numpy()
        x['v7pre_p1'], x['v7pre_p3'] = p1, np.maximum(r['Y3'], p1)
        x['v7pre_p3p'] = t6_base.p3prime(x, 'v7pre_p3')[0]
        P.append(x)
        log('区切り', name, '学び', len(tr), '予想', len(x))
    out = pd.concat(P, ignore_index=True).sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    S6 = nk(pd.read_parquet(V3 / 't6_day5_preds_open.parquet'))[KEY + ['umaban', 'p1_v6pre', 'p3_v6pre', 'p3p_v6pre']]
    out = out.merge(S6, on=KEY + ['umaban'], how='left', validate='1:1')
    assert len(out) == 172738 and out.p1_v6pre.notna().all() and out.v7pre_p3p.notna().all()
    out.to_parquet(PRED_OUT, index=False)
    log('保存', PRED_OUT, out.shape)


if __name__ == '__main__':
    main()
