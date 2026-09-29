# -*- coding: utf-8 -*-
"""第 7 版 d の毎日の予想表(ユーザー承認 2026-09-27: 毎日の表を第 7 版 d で再開)。オッズ・人気は見ない。
既存の台本は import して呼ぶだけ(書き換えない)。使い方は t6_forecast.py と同じ。

  py -3.12 -X utf8 src/t7d_forecast.py fetch DATE        # = t6_forecast.fetch(DB の写し)
  py -3.12 -X utf8 src/t7d_forecast.py retrain           # 2015〜2026-08 で第 7 版 d を学び直す(2 回の一致)→ models/t7d_*.txt
  py -3.12 -X utf8 src/t7d_forecast.py table DATE pre    # 前日版 → out/forecast/DATE_第7版d_前日版.md・.csv
  py -3.12 -X utf8 src/t7d_forecast.py table DATE day    # 当日版 → out/forecast/DATE_第7版d_当日版.md・.csv
  py -3.12 -X utf8 src/t7d_forecast.py dry               # 探索の写しだけで 2021-12-29〜31 の 177 列を作り、v7d の材料と一致するか

■ 177 列 = v7_select.json の 138 列(第 6 版の 118 列 + b7_ 20 列)+ c7_ 28 列 + j7_ 11 列(v7d_run の judge で採った形 c)。
  - 第 6 版の列・見張り = t6_forecast.features / watch(t6_forecast と同じ)。
  - b7_ = v7_feat_b.build(parts=('b',))。生の表 = RAW + DB の写し(v7_open.raw_all と同じそろえ方・前向きは forward も足す)の
    DATE 以前で、DATE の結果の列を v7_feat_b.leak の b と同じ消し方で消したもの。第 6 版の表から読む列 = DATE の第 6 版の行。
  - c7_ = v7c_run.build(台帳 = v7d_run.ledger = 今の kd_horse.parquet)、j7_ = v7d_run.build_j(今の kd_jra_runs.parquet)。
    走り h = t4_day3.sources_from(上の消した生の表)。台帳に無い馬・つながらない馬は欠け(v7d と同じ)。
  - 前向きの写しでは DATE の馬に horse_key が無いので、2026-09-01 以降の鍵の無い行だけ t4_forecast.fill_key と同じ
    「馬名|(開催年 − 年齢)」で埋める(b7_ の中の sources_from にも同じ埋め方を当てる)。2021 以前(dry・学び)は触らない。
  - 模型 = v7d_run.open_ と同じ設定(v7c_run.train・v7_open.CFG・列 = 177)で、feat_t6_explore+feat_v7b_explore+c7d/j7 explore
    と feat_v7_open+c7d/j7 open の全行(2015〜2026-08)を学んだもの。p1 = Y1 をレース内で合計 1・p3 = max(Y3, p1)・
    p3′ = t6_base.p3prime。印 = p3′ → p1 → 馬番(t3_eval.marks)。
  - 第 7 版 d は前日の材料だけの模型(当日の発表値の列は無い)。当日版も同じ列・同じ模型で、馬体重の発表前のレースは出さない(t6 と同じ)。
"""
import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_eval  # noqa: E402
import t3_open  # noqa: E402
import t4_base  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t5_forecast as f5  # noqa: E402
import t5_open as o5  # noqa: E402
import t6_base  # noqa: E402
import t6_forecast as f6  # noqa: E402
import v7_feat_b as vb  # noqa: E402
import v7_open as vo  # noqa: E402
import v7c_run as vc  # noqa: E402
import v7d_run as v7d  # noqa: E402
from day5_forward_features import _align  # noqa: E402
from load_outcomes import load_archive  # noqa: E402

V3 = v7d.V3
MD = o.MD
FWD = f6.FWD
OUT = f6.OUT
KEY = d3.KEY
B7 = vo.B7
COLS = vc.base_cols() + v7d.C7 + v7d.J7
assert len(COLS) == 177 and len(set(COLS)) == 177
PFX = 't7d'
guard = f6.guard
_SRC = d3.sources_from


# ================================================================ 生の表・走り
def raw7(part, date):
    """v7_open.raw_all と同じそろえ方(part = 'dry' は RAW だけ・'forward' は + confirm・sealed・forward)で DATE 以前、
    DATE の結果の列を v7_feat_b.leak の b と同じに消す。"""
    lo, hi, parts = t3_open.SPAN[part]
    out = {}
    for name in ('runs', 'facts', 'races'):
        a = load_archive(name)
        d = pd.concat([a] + [_align(pd.read_parquet(V3 / f'db_{name}_{p}_{t3_open.FILES[p]}.parquet'), a) for p in parts],
                      ignore_index=True)
        d['race_no'] = d.race_no.astype(int)
        assert d.race_date.max() < hi, name
        out[name] = d[d.race_date <= date].copy()
    runs, facts, races = out['runs'], out['facts'], out['races']
    runs['finish_note'] = runs.finish_note.replace(t3_open.NOTE)
    facts['horse_key'] = facts.horse_key.str.replace(r'\|(\d{4})-\d\d-\d\d$', r'|\1', regex=True)
    mk = runs.race_date == date
    runs.loc[mk, t4_base.RES_RUN] = np.nan
    runs.loc[mk & ~runs.finish_note.isin(d3.CANCEL), 'finish_note'] = np.nan
    facts.loc[facts.race_date == date, d3.FACT_RES] = np.nan
    races.loc[races.race_date == date, t4_base.RES_RACE] = np.nan
    return runs, facts, races


def src_fill(runs, facts, races):
    """t4_day3.sources_from + 2026-09-01 以降の鍵の無い行だけ t4_forecast.fill_key と同じ埋め方。"""
    h = _SRC(runs, facts, races)
    m = (h.race_date >= FWD) & h.horse_key.isna() & h.age.notna()
    h.loc[m, 'horse_key'] = h.loc[m, 'horse_name'] + '|' + (
        h.loc[m, 'race_date'].str[:4].astype(int) - h.loc[m, 'age'].astype(int)).astype(str)
    h['hid'] = h.horse_key.fillna(h.horse_name)
    return h


_LED = {}


def led():
    if not _LED:
        L, kmap, info = v7d.ledger()
        J = v7d.kd_jra_runs()  # 固定ファイル + live(nk_pedjra)
        _LED.update(L=L, kmap=kmap, nmap=v7d.jra_names(J), JT=v7d.jra_table(J), jlast=str(J.date.max().date()))
    return _LED


# ================================================================ 材料
def features(h, races, date, part, lap_lo=FWD):
    """DATE の予想する行: 第 6 版の材料(META + 列)+ b7_ + c7_ + j7_。見張りは t6_forecast と同じ。"""
    f5.watch_laps(h, races, date, lap_lo)
    T6, aux = f6.features(h, races, date)
    f6.f4.watch(h, T6, date)
    w4 = f6.watch4(T6, aux)
    T6 = vo.nk(T6)
    Q = T6[KEY + ['umaban']]
    runs, facts, rc = raw7(part, date)
    F = T6[KEY + ['umaban'] + vb.FCOLS].assign(year=T6.race_date.str[:4].astype(int), Y3=np.nan)
    vb.load_F = lambda day: F[KEY + ['umaban', 'year', 'Y3'] + vb.FCOLS].reset_index(drop=True)
    d3.sources_from = src_fill  # v7_feat_b.prep の中の sources_from にも同じ埋め方
    try:
        R = vo.nk(vb.build(runs, facts, rc, parts=('b',)))
    finally:
        d3.sources_from = _SRC
    h7 = src_fill(runs, facts, rc)
    Lg = led()
    C, cx = vc.build(h7, Q, Lg['L'])
    G, gx = v7d.build_j(h7, Q, Lg['JT'], Lg['kmap'], Lg['nmap'])
    T = T6.merge(R[KEY + ['umaban'] + B7], on=KEY + ['umaban'], how='left', validate='1:1')
    for X in (C, G):
        T = T.merge(vo.nk(X), on=KEY + ['umaban'], how='left', validate='1:1')
    assert T[KEY + ['umaban']].equals(Q) and set(COLS) <= set(T.columns)
    info = {'台帳に鍵あり': float(cx.inled.mean()), '中央とつながった': float(gx.j_link.mean()),
            '前に中央の走りあり': float(gx.j_run.mean())}
    return T, w4, info


def booster(t):
    return o.booster(MD / f'{PFX}_{t}.txt')


def predict(T, M):
    x = T[KEY + ['umaban', 'n']].copy()
    r = {}
    for t in ('Y1', 'Y3'):
        z = d3.logit((1 if t == 'Y1' else 3) / x.n.to_numpy(float))
        r[t] = d3.sig(z + M[t].predict(T[COLS].astype(float), raw_score=True))
    x['p1'] = r['Y1'] / pd.Series(r['Y1'], index=x.index).groupby([x[k] for k in KEY]).transform('sum').to_numpy()
    x['p3'] = np.maximum(r['Y3'], x.p1)
    x['p3p'] = t6_base.p3prime(x, 'p3')[0]
    return t3_eval.marks(x, p1='p3p', p3='p1')


def table(date, v):
    guard(pd.DataFrame({'race_date': [date]}), 'DATE')
    assert (MD / f'{PFX}_models.json').exists(), '学び直し(retrain)が先'
    h, races = f6.f4.fill_key(*o5.load5('forward'))
    T, w4, info = features(h, races, date, 'forward')
    guard(T, 'features')
    x = predict(T, {t: booster(t) for t in ('Y1', 'Y3')})
    x = x.assign(o_bw=T.o_bw.to_numpy()) if 'o_bw' in T.columns else x.assign(o_bw=np.nan)
    names = h.loc[h.race_date == date, KEY + ['umaban', 'horse_name']]
    names = names.assign(race_no=names.race_no.astype(int), umaban=names.umaban.astype(int))
    x = x.merge(names, on=KEY + ['umaban'], how='left', validate='1:1').sort_values(KEY + ['rank'], kind='mergesort')
    jl = led()['jlast']
    name = f'{date}_第7版d_{o.VN[v]}'
    L = [f'# 予想表 {date}(第 7 版 d・{o.VN[v]}・オッズ・人気は見ない)', '',
         '第 7 版 d(◎ = 3 着以内に来そうな馬の 1 位)。材料 177 列 = 第 7 版の 138 列 + 血統・生産者・馬主(KDSCOPE の台帳)28 列'
         ' + 中央での成績 11 列。第 7 版 d は前日の材料だけの模型(当日版も同じ模型)。', '',
         f'注記: 中央の成績(kd_jra_runs)は {jl} までしか無い。それより後の中央の走りは材料に入らない。'
         '台帳に無い新しい馬は血統などの列が欠け扱い。', '',
         '印: ◎ = 1 位・○ = 2 位・▲ = 3 位・△ = 4〜5 位(3 着以内の確率 → 勝つ確率 → 馬番の順)。'
         '3 着以内の確率はレース内で合計 3・勝つ確率はレース内で合計 1。']
    for k, g in x.groupby(KEY, sort=False):
        L += ['', f'## {k[0]} {k[2]}R({len(g)} 頭)']
        if v == 'day' and g.o_bw.isna().all():
            L.append('馬体重の発表前のため当日版は出さない(前日版を見る)')
            continue
        L += ['', '| 印 | 馬番 | 馬名 | 3 着以内の確率 | 勝つ確率 |', '|---|---|---|---|---|']
        L += [f'| {r.mark} | {r.umaban} | {r.horse_name} | {r.p3p:.3f} | {r.p1:.3f} |' for r in g.itertuples()]
    OUT.mkdir(parents=True, exist_ok=True)
    x[KEY + ['umaban', 'horse_name', 'n', 'rank', 'mark', 'p3p', 'p1', 'p3']].to_csv(OUT / f'{name}.csv', index=False,
                                                                                    encoding='utf-8-sig')
    (OUT / f'{name}.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(f"{date} 第 7 版 d {o.VN[v]}: {x[KEY].drop_duplicates().shape[0]} R・{len(x)} 頭 → {OUT / (name + '.md')}"
          f" 見張り 4 列 {({k: round(val, 3) for k, val in w4.items()})} つながり {({k: round(val, 3) for k, val in info.items()})}"
          f" 中央の成績の最後 {jl}", flush=True)


# ================================================================ 学び直し
NEED = KEY + ['umaban', 'year', 'n', 'Y1', 'Y3']


def rd(fp, cols):
    """大きい parquet は要る列だけ読む(メモリ対策)。"""
    have = set(pq.read_schema(fp).names)
    return vo.nk(pd.read_parquet(fp, columns=[c for c in dict.fromkeys(cols) if c in have]))


def train_data():
    T = rd(vo.FEAT_OUT, NEED + COLS)
    assert len(T) == 172738
    for f in (v7d.COP, v7d.JOP):
        T = T.merge(rd(f, KEY + ['umaban'] + COLS), on=KEY + ['umaban'], how='left', validate='1:1')
    X = ref_explore()
    assert set(T.columns) <= set(X.columns)
    df = o.sort4(pd.concat([X[list(T.columns)], T], ignore_index=True))
    del X, T
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < FWD and not df.duplicated(KEY + ['umaban']).any()
    return df


def ref_explore(days=None):
    """v7d_run.open_ と同じ作り方の探索の期間の表(feat_t6_explore + b7_ + c7d・j7 explore)。要る列だけ読む。"""
    X6 = rd(V3 / 'feat_t6_explore.parquet', NEED + COLS)
    if days is not None:
        X6 = X6[X6.race_date.isin(days)].reset_index(drop=True)
    X = X6.merge(rd(V3 / 'feat_v7b_explore.parquet', KEY + ['umaban'] + B7), on=KEY + ['umaban'], how='left', validate='1:1')
    for f in (v7d.CEX, v7d.JEX):
        X = X.merge(rd(f, KEY + ['umaban'] + COLS), on=KEY + ['umaban'], how='left', validate='1:1')
    assert len(X) == len(X6)
    return X


def retrain():
    jp = MD / f'{PFX}_models.json'
    if jp.exists():
        print('retrain は済み', jp); return
    df = train_data()
    meta = {'train': '2015-01-01〜2026-08-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]),
            'cfg': {k: list(v) for k, v in vo.CFG.items()}, 'cols': COLS, 'files': {}}
    for t in ('Y1', 'Y3'):
        fp = MD / f'{PFX}_{t}.txt'
        if fp.exists():
            print(t, '済み(2 回の一致を確かめてから書いたもの)', fp, flush=True)
        else:
            s1 = vc.train(df, t, COLS).model_to_string()
            gc.collect()
            s2 = vc.train(df, t, COLS).model_to_string()  # 2 回目は 1 回目が終わってから
            gc.collect()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {t}')
            fp.write_text(s1, encoding='utf-8', newline='\n')
            print(t, '2 回の学習が文字列で一致', len(COLS), '列', flush=True)
            del s1, s2
        meta['files'][fp.name] = {'cols': len(COLS)}
    jp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print('行', meta['rows'], 'レース', meta['races'], flush=True)


# ================================================================ 通し試験
DRY_DAYS = ['2021-12-29', '2021-12-30', '2021-12-31']


def dry(days=None):
    """探索の写しだけ(RAW)で 2021-12-29〜31 の 177 列を作り、v7d の材料(feat_t6_explore + b7_ + c7d・j7 explore)と一致するか。
    メモリ(16 GB)に収めるため 1 回に 1 日: py ... dry 2021-12-29(日を省くと 3 日を順に・同じプロセス)。python は 1 本だけ。"""
    days = days or DRY_DAYS
    h, races = o5.load5('dry')
    ref = ref_explore(days)
    cols = COLS + ['n']
    ok = True
    for date in sorted(d for d in ref.race_date.unique() if '2021-12-29' <= d <= '2021-12-31'):
        T, _, info = features(h, races, date, 'dry', lap_lo='2021-12-01')
        a = ref[ref.race_date == date].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
        b = a[KEY + ['umaban']].merge(T, on=KEY + ['umaban'], how='left')
        A, B = a[cols].to_numpy(float), b[cols].to_numpy(float)
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        part = {g: [int(eq[:, [cols.index(c) for c in cs]].sum()), len(a) * len(cs)]
                for g, cs in (('b7', B7), ('c7', v7d.C7), ('j7', v7d.J7))}
        bad = {c: int((~eq[:, i]).sum()) for i, c in enumerate(cols) if not eq[:, i].all()}
        print(date, 'v7d の馬', len(a), '予想表の馬', len(T), '一致', int(eq.sum()), '/', eq.size, part, '合わない列', bad,
              flush=True)
        ok &= len(a) == len(T) and not bad
    if not ok:
        raise SystemExit('⛔ dry が一致しない')
    print('dry OK')


if __name__ == '__main__':
    a = sys.argv[1:]
    {'fetch': lambda: f6.fetch(a[1]), 'retrain': retrain, 'table': lambda: table(a[1], a[2]), 'dry': lambda: dry(a[1:] or None)}[a[0]]()
