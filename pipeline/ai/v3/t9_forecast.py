# -*- coding: utf-8 -*-
"""第 9 版 = 人気を見ない版(第 8 版の 183 列から j7_last_pop を外した 182 列)の毎日の予想表。ユーザー承認 2026-09-29。
作り方は第 8 版(t8_forecast)と同じで、列だけ 182 列。既存の台本は import して呼ぶだけ(t7e・t8 は書き換えない)。

  py -3.12 -X utf8 src/t9_forecast.py open                 # 段 1 の外の予想(v7e_open.open_ と同じ区切り ①〜⑤・同じ設定・182 列)
                                                           #   → v3/t9_open_preds.parquet(区切りごとに書き足す・落ちても済んだ区切りから再開)
  py -3.12 -X utf8 src/t9_forecast.py retrain              # 段 1 の本番用(2015〜2026-08・2 回の一致)→ models/t9_Y1.txt・t9_Y3.txt・t9_models.json
                                                           # 段 2(t9 の外の予想を土台に 2022-01〜2026-08)→ models/t9_s2.json
  py -3.12 -X utf8 src/t9_forecast.py table DATE pre [DIR] # 前日版 → DATE_第9版_前日版.md・.csv
  py -3.12 -X utf8 src/t9_forecast.py table DATE day [DIR] # 当日版(同じ模型)
  py -3.12 -X utf8 src/t9_forecast.py cmp                  # t9 と t8(v7e_open_preds)の外の予想で本命の 3 着内率を比べる
"""
import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t8_forecast as t8  # noqa: E402
import t4_day3 as d3  # noqa: E402
import v7c_run as vc  # noqa: E402
import v7d_run as v7d  # noqa: E402
import v7e_open as eo7  # noqa: E402

e7, s2, s1, o, o5, vo, t6_base = t8.e7, t8.s2, t8.s1, t8.o, t8.o5, t8.vo, t8.t6_base
f6, t7, marks = t8.f6, t8.t7, t8.marks
V3, MD, OUT, KEY, Q5, CY6 = t8.V3, t8.MD, t8.OUT, t8.KEY, t8.Q5, t8.CY6
log = s1.log

DROP = ['j7_last_pop']
COLS8 = list(e7.COLS)
COLS = [c for c in COLS8 if c not in DROP]
assert len(COLS8) == 183 and len(COLS) == 182
PFX = 't9'
JP = MD / 't9_s2.json'
OUT9 = V3 / 't9_open_preds.parquet'
TR_LO, TR_HI = t8.TR_LO, t8.TR_HI

# t7e の予想・学び直しを 182 列・t9 の名前で使う(t7e_forecast の関数は呼ぶ時に COLS・PFX を読む)
e7.COLS = COLS
e7.PFX = PFX


# ================================================================ 段 1 の外の予想(v7e_open.open_ と同じ手順・列だけ 182)
def open_():
    cols = vc.base_cols() + v7d.C7 + v7d.J7 + eo7.NCOL
    assert set(cols) == set(COLS8) and len(cols) == 183
    cols = [c for c in cols if c not in DROP]
    assert len(cols) == 182
    done = pd.read_parquet(OUT9) if OUT9.exists() else None
    segs_done = set(done.seg) if done is not None else set()
    if segs_done >= {s[0] for s in o.SEGS}:
        log('open は済み', OUT9); return
    s1.wait_mem()
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT))
    assert len(T) == 172738
    for f in (v7d.COP, v7d.JOP, eo7.fpath('open')):
        T = T.merge(vo.nk(pd.read_parquet(f)), on=Q5, how='left', validate='1:1')
    X6 = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XB = vo.nk(pd.read_parquet(V3 / 'feat_v7b_explore.parquet'))
    X = X6.merge(XB[Q5 + vo.B7], on=Q5, how='left', validate='1:1')
    for f in (v7d.CEX, v7d.JEX, eo7.fpath('explore')):
        X = X.merge(vo.nk(pd.read_parquet(f)), on=Q5, how='left', validate='1:1')
    assert len(X) == len(X6) and X.race_date.max() < '2022-01-01' and set(T.columns) <= set(X.columns)
    ALL = o.sort4(pd.concat([X[list(T.columns)], T], ignore_index=True))
    del X, X6, XB
    assert not ALL.duplicated(Q5).any()
    for name, lo, hi in o.SEGS:
        if name in segs_done:
            log('区切り', name, '済み'); continue
        tr = ALL[ALL.race_date < lo]
        te = o.seg_rows(T, lo, hi)
        r = {}
        for t in ('Y1', 'Y3'):
            m = vc.train(tr, t, cols)
            z = d3.logit((1 if t == 'Y1' else 3) / te.n.to_numpy(float))
            r[t] = d3.sig(z + m.predict(te[cols].astype(float), raw_score=True))
            del m; gc.collect()
        x = te[Q5 + ['year', 'n', 'Y1', 'Y3', 'pop']].copy()
        x['seg'] = name
        p1 = r['Y1'] / pd.Series(r['Y1'], index=x.index).groupby([x[k] for k in KEY]).transform('sum').to_numpy()
        x['t9pre_p1'], x['t9pre_p3'] = p1, np.maximum(r['Y3'], p1)
        x['t9pre_p3p'] = t6_base.p3prime(x, 't9pre_p3')[0]
        x.attrs = {}
        done = x if done is None else pd.concat([done, x], ignore_index=True)
        done = done.sort_values(Q5, kind='mergesort').reset_index(drop=True)
        tmp = OUT9.with_suffix('.tmp')
        done.to_parquet(tmp, index=False)
        tmp.replace(OUT9)
        log('区切り', name, '学び', len(tr), '予想', len(x), '保存', OUT9, len(done))
    assert len(done) == 172738 and done.t9pre_p3p.notna().all()
    log('open 完了', OUT9, done.shape)


# ================================================================ 段 2(t8.fit_s2 と同じ・土台だけ t9 の外の予想)
def load9():
    B = pd.read_parquet(OUT9)
    assert len(B) == 172738
    B = B.rename(columns={'t9pre_p1': 'v7epre_p1', 't9pre_p3': 'v7epre_p3', 't9pre_p3p': 'v7epre_p3p'})
    old = eo7.OUT_P
    tmp = V3 / 't9_open_preds_as_v7e.tmp.parquet'
    B.to_parquet(tmp, index=False)
    s2.eo.OUT_P = tmp
    try:
        return s2.load()
    finally:
        s2.eo.OUT_P = old
        tmp.unlink()


def fit_s2(lo, hi):
    D = load9()
    tr = D[(D.race_date >= lo) & (D.race_date <= hi)]
    mu, sd = tr[CY6].mean(), tr[CY6].std()
    X, cols = s2.design(tr, mu, sd)
    M = {'train': f'{lo}〜{hi}', 'rows': len(tr), 'cols': cols, 'mu': {c: float(mu[c]) for c in CY6},
         'sd': {c: float(sd[c]) for c in CY6}}
    for t, bc_ in (('Y1', 'v7epre_p1'), ('Y3', 'v7epre_p3')):
        w = s2.fit(X, tr[t].to_numpy(float), s2.lg(tr[bc_].to_numpy(float)))
        M[t] = dict(zip(['切片'] + cols, map(float, w)))
    return M


def retrain():
    open_()
    e7.retrain()  # 段 1 の本番用(182 列・t9_*)
    if JP.exists():
        print('段 2 は済み', JP); return
    s1.wait_mem()
    M = fit_s2(TR_LO, TR_HI)
    M['base'] = str(OUT9)
    M['feat'] = str(V3 / 'feat_v8cy_open.parquet')
    M['stage1_cols'] = len(COLS)
    M['drop'] = DROP
    JP.write_text(json.dumps(M, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    for t in ('Y1', 'Y3'):
        k = sorted(M['cols'], key=lambda c: -abs(M[t][c]))[:3]
        log(t, '切片', round(M[t]['切片'], 3), '大きい 3 つ', {c: round(M[t][c], 3) for c in k})
    log('保存', JP, '行', M['rows'])


# ================================================================ 表(t8.table と同じ・模型と名前だけ t9)
def table(date, v, out=None):
    out = Path(out) if out else OUT
    e7.guard(pd.DataFrame({'race_date': [date]}), 'DATE')
    assert (MD / f'{PFX}_models.json').exists() and JP.exists(), '学び直し(t9 retrain)が先'
    M = json.loads(JP.read_text(encoding='utf-8'))
    s1.wait_mem()
    h, races = f6.f4.fill_key(*o5.load5('forward'))
    T, w4, info = e7.features(h, races, date, 'forward')
    e7.watch_nk(info)
    e7.guard(T, 'features')
    x7 = e7.predict(T)
    base = x7[KEY + ['umaban', 'n', 'p1', 'p3']].merge(vo.nk(T[Q5 + ['b_young']]), on=Q5, how='left', validate='1:1')
    hd = h.loc[(h.race_date == date) & h.track.isin(f6.f4.NANKAN), Q5 + ['horse_name', 'jockey', 'trainer']].copy()
    hd['race_no'], hd['umaban'] = hd.race_no.astype(int), hd.umaban.astype(int)
    Rd = base[Q5].merge(hd.drop_duplicates(Q5, keep='last'), on=Q5, how='left', validate='1:1')
    F = t8.cy_feats(date, Rd, h)
    base = base.merge(F[Q5 + CY6 + ['_linked']], on=Q5, how='left', validate='1:1')
    x = t8.apply_s2(base, M)
    x = x.merge(base[Q5 + ['_linked']], on=Q5, how='left', validate='1:1')
    x = x.merge(x7[Q5 + ['mark']].rename(columns={'mark': 'mark7e'}), on=Q5, how='left', validate='1:1')
    x = x.merge(vo.nk(T[Q5 + ['o_bw']]), on=Q5, how='left', validate='1:1') if 'o_bw' in T.columns \
        else x.assign(o_bw=np.nan)
    names = h.loc[h.race_date == date, Q5 + ['horse_name']]
    names = names.assign(race_no=names.race_no.astype(int), umaban=names.umaban.astype(int))
    x = x.merge(names, on=Q5, how='left', validate='1:1').sort_values(KEY + ['rank'], kind='mergesort')
    share = x.groupby('track', sort=False)._linked.mean()
    _, wi = t8.works()
    jl = t7.led()['jlast']
    name = f'{date}_第9版_{o.VN[v]}'
    L = [f'# 予想表 {date}(第 9 版・{o.VN[v]}・オッズ・人気は見ない)', '',
         '第 9 版 = 第 8 版から中央の前走の人気(j7_last_pop)を外した 182 列 + 調教の数字の上乗せ(段 2・学び 2022-01〜2026-08)。'
         '調教の短評・印・談話は使わない。前日の材料だけの模型(当日版も同じ模型)。', '',
         '調教の付いた割合(場ごと): ' + '・'.join(f'{t} {100 * s:.0f}%' for t, s in share.items())
         + f'(追い切りの元: CSV + 毎日の JSON {wi["json_races"]} レース・JSON の最後 {wi["json_last"]})。調教の無い馬は欠け扱い。', '',
         f'注記: 中央の成績(kd_jra_runs)は {jl} までしか無い。能力試験は公式サイトから {info["試験の最後の日"]} まで。'
         '台帳に無い新しい馬は血統・能力試験などの列が欠け扱い。', '',
         '印: ◎ = 1 位・○ = 2 位・▲ = 3 位・△ = 4〜5 位(3 着以内の確率 → 勝つ確率 → 馬番の順)。'
         '3 着以内の確率はレース内で合計 3・勝つ確率はレース内で合計 1。']
    for k, g in x.groupby(KEY, sort=False):
        L += ['', f'## {k[0]} {k[2]}R({len(g)} 頭)']
        if v == 'day' and g.o_bw.isna().all():
            L.append('馬体重の発表前のため当日版は出さない(前日版を見る)')
            continue
        L += ['', '| 印 | 馬番 | 馬名 | 3 着以内の確率 | 勝つ確率 |', '|---|---|---|---|---|']
        L += [f'| {r.mark} | {r.umaban} | {r.horse_name} | {r.p3p:.3f} | {r.p1:.3f} |' for r in g.itertuples()]
    out.mkdir(parents=True, exist_ok=True)
    x[KEY + ['umaban', 'horse_name', 'n', 'rank', 'mark', 'p3p', 'p1', 'p3', '_linked', 'mark7e']].to_csv(
        out / f'{name}.csv', index=False, encoding='utf-8-sig')
    (out / f'{name}.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(f"{date} 第 9 版 {o.VN[v]}: {x[KEY].drop_duplicates().shape[0]} R・{len(x)} 頭 → {out / (name + '.md')}"
          f" 全体の調教 {x._linked.mean():.3f} 見張り 4 列 {({k: round(val, 3) for k, val in w4.items()})}", flush=True)


# ================================================================ 外の予想の比べ(本命の 3 着内率)
def cmp():
    a = pd.read_parquet(OUT9)
    b = pd.read_parquet(eo7.OUT_P)
    for d in (a, b):
        d['race_no'], d['umaban'] = d.race_no.astype(int), d.umaban.astype(int)
    p = a[Q5 + ['Y3', 't9pre_p3p', 't9pre_p1']].merge(b[Q5 + ['v7epre_p3p', 'v7epre_p1']], on=Q5, validate='1:1')

    def top(c3, c1):
        q = p.sort_values(KEY + [c3, c1, 'umaban'], ascending=[True] * len(KEY) + [False, False, True], kind='mergesort')
        return q.groupby(KEY, sort=False).head(1).set_index(KEY).Y3
    n, o8 = top('t9pre_p3p', 't9pre_p1'), top('v7epre_p3p', 'v7epre_p1')
    R = pd.DataFrame({'n': n, 'o': o8})
    dd = (R.n - R.o).groupby(R.index.get_level_values('race_date')).agg(['sum', 'size'])
    mm = dd['sum'].sum() / dd['size'].sum()
    se = np.sqrt(((dd['sum'] - mm * dd['size']) ** 2).sum()) / dd['size'].sum()
    res = {'races': len(R), 't8': round(100 * R.o.mean(), 2), 't9': round(100 * R.n.mean(), 2),
           'diff': round(100 * mm, 2), 'se2': round(200 * se, 2)}
    print(json.dumps(res, ensure_ascii=False), flush=True)
    return res


if __name__ == '__main__':
    a = sys.argv[1:]
    {'open': open_, 'retrain': retrain, 'cmp': cmp,
     'table': lambda: table(a[1], a[2], a[3] if len(a) > 3 else None)}[a[0]]()
