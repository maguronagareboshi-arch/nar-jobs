# -*- coding: utf-8 -*-
"""第 7 版 d: c7_ の台帳を KDSCOPE(kd_horse.parquet)に入れ替え + 中央での成績の材料 j7_ → 漏れ検査 → judge 3 つ → 採った形で予想。
既存の台本は import して呼ぶだけ(書き換えない)。

  py -3.12 -X utf8 src/v7d_run.py all    # feat → judge → final → open → md(できている段は飛ばす)

■ 決め(この台本で決めた細部)
  1. 台帳 = kd_horse.parquet。同じ血統登録番号が NU と UM の両方にあれば NU(地方)を優先。鍵 = NFKC・空白消しの馬名|生年。
     同じ鍵が 2 頭以上なら外す(v7c と同じ)。c7_ の列の定義・名前は v7c_run.py のまま(build を呼ぶ)。
  2. j7_: 中央の走り(kd_jra_runs・着順 0 = 取消等は除く)のうち、そのレースの日より前(当日を含まない)のものだけ。
     つなぎ = 台帳の 鍵→血統登録番号、台帳に無ければ 中央の走りの 馬名|生年 → 血統登録番号(一意のときだけ)。
     つながった馬で中央の走りが無ければ 数の列 = 0・他は欠け。つながらない馬は全部欠け。
     上がり 0・人気 0 は欠け扱い。人気は中央の過去の走りのものだけ(列名に _pop)。南関の人気・オッズは使わない。
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_base  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t6_base  # noqa: E402
import v7_open as vo  # noqa: E402
import v7_select as vs  # noqa: E402
import v7c_run as vc  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
KEY = d3.KEY
C7 = vc.C7
J7 = ['j7_n', 'j7_w', 'j7_t3', 'j7_days', 'j7_last_fin', 'j7_last_nst', 'j7_best', 'j7_dirt_rel', 'j7_last_pop',
      'j7_turf_n', 'j7_best_l3f']
CEX, COP = V3 / 'feat_c7d_explore.parquet', V3 / 'feat_c7d_open.parquet'
JEX, JOP = V3 / 'feat_j7_explore.parquet', V3 / 'feat_j7_open.parquet'
LEAKJ, RESJ = V3 / 'v7d_leak.json', V3 / 'v7d_res.json'
MD = REPO / 'out' / 'v7_feat_d.md'
CACHE_D = V3 / 'v7d_cache'
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def res_load():
    return json.loads(RESJ.read_text(encoding='utf-8')) if RESJ.exists() else {}


def res_save(k, v):
    R = res_load()
    R[k] = v
    RESJ.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding='utf-8')


# ================================================================ 固定ファイル + 毎日の live(nk_pedjra.py・ユーザー承認 2026-09-29)
def _live_dir():
    """live の置き場 = 環境変数 V3_KD_LIVE(off で使わない)、無ければ V3_KD。どちらも無ければ使わない(手元の学習は固定ファイルのまま)。"""
    import os
    d = os.environ.get('V3_KD_LIVE') or os.environ.get('V3_KD')
    return None if not d or d == 'off' else Path(d)


def _live(name, fixed, key):
    d = _live_dir()
    if d is None:
        return None
    p = d / name
    try:
        if not p.exists():
            log('live 無し・固定ファイルのまま', p); return None
        x = pd.read_parquet(p)
        miss = [c for c in fixed.columns if c not in x.columns]
        if miss or not len(x) or x[key].isna().to_numpy().any():
            log('live 壊れ・固定ファイルのまま', p, miss[:5], len(x)); return None
        x = x[list(fixed.columns)]
        for c in fixed.columns:  # 型を固定ファイルに合わせる
            x[c] = x[c].astype(fixed[c].dtype)
        return x
    except Exception as e:  # noqa: BLE001
        log('live 読めない・固定ファイルのまま', p, repr(e)[:120]); return None


def kd_horse():
    """kd_horse.parquet(書き換えない)+ live(固定に無い ketto だけ足す)。"""
    k = pd.read_parquet(V3 / 'kd_horse.parquet')
    x = _live('kd_live_horse.parquet', k, ['ketto'])
    if x is not None:
        x = x[~x.ketto.isin(set(k.ketto.dropna()))].drop_duplicates('ketto')
        log('live 台帳に足す', len(x))
        k = pd.concat([k, x], ignore_index=True)
    return k


def kd_jra_runs():
    """kd_jra_runs.parquet(書き換えない)+ live を縦に足し (ketto, date, 場, R) で重複を消す(固定ファイルの行を残す)。"""
    J = pd.read_parquet(V3 / 'kd_jra_runs.parquet')
    x = _live('kd_live_jra_runs.parquet', J, ['ketto', 'date', 'jyo', 'race'])
    if x is not None:
        n0 = len(J)
        J = pd.concat([J, x], ignore_index=True).drop_duplicates(['ketto', 'date', 'jyo', 'race'], keep='first')
        log('live 中央の走りを足す', len(J) - n0, '/', len(x))
    return J


# ================================================================ 台帳(kd_horse)
def ledger():
    k = kd_horse()
    n0 = len(k)
    k = k[k.ketto.notna() & k.birth.notna()].copy()
    k['pri'] = (k.src != 'NU').astype(int)
    k = k.sort_values(['ketto', 'pri'], kind='mergesort').drop_duplicates('ketto', keep='first')
    n1 = len(k)
    for c in ('name', 'sire', 'dam', 'bms', 'owner', 'breeder', 'area'):
        k[c] = k[c].map(vc.norm)
    k['lk'] = k['name'] + '|' + (k.birth // 10000).astype(int).astype(str)
    k['bmon'] = ((k.birth // 100) % 100).astype(float)
    k.loc[~k.bmon.between(1, 12), 'bmon'] = np.nan
    k['dam2'] = k['dam'] + '|' + k['bms'].fillna('')
    k.loc[k['dam'].isna(), 'dam2'] = np.nan
    ar = np.where(k['area'].isin(vc.HIDAKA), 1.0, np.where(k['area'].isin(vc.IBURI), 2.0, 3.0))
    k['area_c'] = np.where(k['area'].isna(), np.nan, ar)
    k = k[k.lk.notna()]
    dup = k.lk.duplicated(keep=False)
    K = k[~dup]
    L = K.rename(columns={'dam': 'dam_raw'}).rename(columns={'dam2': 'dam', 'area': 'area_raw', 'area_c': 'area'})
    L = L[['lk', 'sire', 'bms', 'dam', 'owner', 'breeder', 'bmon', 'area']].set_index('lk')
    kmap = dict(zip(K.lk, K.ketto.astype('int64')))
    info = {'kd_rows': n0, 'after_ketto_dedup_NU_first': n1, 'dup_lk_removed': int(dup.sum()), 'ledger': len(L),
            'src': {s: int(v) for s, v in K.src.value_counts().items()}}
    return L, kmap, info


# ================================================================ j7_
def jra_table(J):
    J = J[J.finish.fillna(0) > 0].copy()
    J['ketto'] = J.ketto.astype('int64')
    J = J.sort_values(['ketto', 'date'], kind='mergesort').reset_index(drop=True)
    g = J.ketto
    J['c_n'] = J.groupby('ketto').cumcount() + 1.0
    J['c_w'] = (J.finish == 1).astype(float).groupby(g).cumsum()
    J['c_t3'] = (J.finish <= 3).astype(float).groupby(g).cumsum()
    J['c_best'] = J.finish.groupby(g).cummin()
    J['c_turf'] = (J.surface == '芝').astype(float).groupby(g).cumsum()
    ok = (J.surface == 'ダ') & (J.n_starters > 0)
    J['c_dsum'] = pd.Series(np.where(ok, J.finish / J.n_starters, 0.0)).groupby(g).cumsum()
    J['c_dn'] = ok.astype(float).groupby(g).cumsum()
    l3 = J.l3f.where(J.l3f > 0).fillna(np.inf)
    J['c_l3'] = l3.groupby(g).cummin().replace(np.inf, np.nan)
    J['l_fin'], J['l_nst'] = J.finish.astype(float), J.n_starters.astype(float)
    J['l_pop'] = J['pop'].where(J['pop'] > 0).astype(float)
    J['l_date'] = J.date
    J = J.drop_duplicates(['ketto', 'date'], keep='last')
    return J[['ketto', 'date', 'c_n', 'c_w', 'c_t3', 'c_best', 'c_turf', 'c_dsum', 'c_dn', 'c_l3', 'l_fin', 'l_nst',
              'l_pop', 'l_date']]


def jra_names(J):
    x = J[['ketto', 'name', 'birth_year']].drop_duplicates('ketto').copy()
    x['lk'] = x.name.map(vc.norm) + '|' + x.birth_year.astype('Int64').astype(str)
    x = x[x.lk.notna()]
    x = x[~x.lk.duplicated(keep=False)]
    return dict(zip(x.lk, x.ketto.astype('int64')))


def build_j(h, Q, JT, kmap, nmap):
    hq = h.drop_duplicates(KEY + ['umaban'])[KEY + ['umaban', 'hid']]
    q = Q[KEY + ['umaban']].merge(hq, on=KEY + ['umaban'], how='left', validate='1:1')
    lk = vc.link_key(q.hid)
    k1 = lk.map(kmap)
    k2 = lk.map(nmap)
    q['ketto'] = k1.fillna(k2)
    q['date'] = pd.to_datetime(q.race_date)
    q['_i'] = np.arange(len(q))
    has = q.ketto.notna()
    a = q[has].copy()
    a['ketto'] = a.ketto.astype('int64')
    a = a.sort_values('date', kind='mergesort')
    m = pd.merge_asof(a[['_i', 'ketto', 'date']], JT.sort_values('date', kind='mergesort'), on='date', by='ketto',
                      allow_exact_matches=False, direction='backward')
    m = m.set_index('_i').reindex(np.arange(len(q)))
    out = pd.DataFrame(index=np.arange(len(q)))
    lin = has.to_numpy()
    for c, s in (('j7_n', 'c_n'), ('j7_w', 'c_w'), ('j7_t3', 'c_t3'), ('j7_turf_n', 'c_turf')):
        v = m[s].to_numpy(float)
        out[c] = np.where(lin & np.isnan(v), 0.0, v)
    out['j7_days'] = (q.date - m.l_date).dt.days.to_numpy(float)
    out['j7_last_fin'], out['j7_last_nst'] = m.l_fin.to_numpy(float), m.l_nst.to_numpy(float)
    out['j7_best'] = m.c_best.to_numpy(float)
    with np.errstate(all='ignore'):
        out['j7_dirt_rel'] = np.where(m.c_dn.to_numpy(float) > 0, m.c_dsum.to_numpy(float) / m.c_dn.to_numpy(float), np.nan)
    out['j7_last_pop'] = m.l_pop.to_numpy(float)
    out['j7_best_l3f'] = m.c_l3.to_numpy(float)
    out = out[J7]
    res = pd.concat([Q[KEY + ['umaban']].reset_index(drop=True), out], axis=1)
    aux = pd.DataFrame({'j_link': lin, 'j_by_ledger': k1.notna().to_numpy(), 'j_run': out.j7_n.to_numpy() > 0})
    return res, aux


def leak_j(h, Q, full, J, kmap, nmap, races, part):
    days = t4_base.pick_days(races)
    per, tot = [], [0, 0]
    for X in days:
        ht = h[h.race_date <= X].copy()
        mk = (ht.race_date == X).to_numpy()
        ht.loc[mk, 'finish'] = np.nan
        Jt = J[J.date <= pd.Timestamp(X)].copy()
        Jt.loc[Jt.date == pd.Timestamp(X), ['finish', 'pop', 'l3f', 'time_sec']] = np.nan
        Qd = Q[Q.race_date == X].reset_index(drop=True)
        b, _ = build_j(ht, Qd, jra_table(Jt), kmap, nmap)
        a = full[full.race_date == X].set_index(KEY + ['umaban'])[J7].sort_index()
        b = b.set_index(KEY + ['umaban'])[J7].sort_index()
        assert a.index.equals(b.index), X
        A, B = a.to_numpy(float), b.to_numpy(float)
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        bad = [c for c, ok in zip(J7, eq.all(0)) if not ok]
        per.append({'date': X, 'rows': len(a), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        log('j7', part, X, len(a), int(eq.sum()), eq.size, bad)
    return {'days': len(days), 'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0],
            'cells': tot[1], 'per_day': per}


# ================================================================ feat
def feat():
    if all(p.exists() for p in (CEX, COP, JEX, JOP, LEAKJ)):
        log('feat は済み'); return
    L, kmap, linfo = ledger()
    log('台帳', linfo)
    J = pd.read_parquet(V3 / 'kd_jra_runs.parquet')
    nmap = jra_names(J)
    JT = jra_table(J)
    log('中央の走り', len(J), '表', len(JT), '名前の鍵', len(nmap))
    h, races = vc.sources()
    log('走り', len(h))
    XE = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XO = vo.nk(pd.read_parquet(V3 / 'feat_t6_open.parquet'))
    Q = pd.concat([XE[KEY + ['umaban']], XO[KEY + ['umaban']]], ignore_index=True)
    F, aux = vc.build(h, Q, L)
    G, auxj = build_j(h, Q, JT, kmap, nmap)
    meta = pd.concat([XE[['year', 'Y3']], XO[['year', 'Y3']]], ignore_index=True)
    aux = pd.concat([aux, auxj, meta], axis=1)
    rate = aux.groupby('year').agg(rows=('inled', 'size'), inled=('inled', 'mean'), linked=('linked', 'mean'),
                                   j_link=('j_link', 'mean'), j_run=('j_run', 'mean'))
    log('つながった割合\n', rate.round(4))
    n = len(XE)
    FE, FO = F.iloc[:n].reset_index(drop=True), F.iloc[n:].reset_index(drop=True)
    GE, GO = G.iloc[:n].reset_index(drop=True), G.iloc[n:].reset_index(drop=True)
    for A_, X_ in ((FE, XE), (FO, XO), (GE, XE), (GO, XO)):
        assert A_[KEY + ['umaban']].equals(X_[KEY + ['umaban']])
    ae = aux.iloc[:n].reset_index(drop=True)
    m = ae.year.between(2016, 2019).to_numpy()
    deb = m & (ae.selfn.to_numpy() == 0)
    info = {'ledger': linfo, 'jra_rows': len(J), 'jra_name_keys': len(nmap),
            'rate': {int(y): {k: float(v) for k, v in r.items()} for y, r in rate.iterrows()},
            'n_debut_rows': int(deb.sum()),
            'corr': {c: [float(E_[c].corr(ae.Y3[m], method='spearman')) if E_[c][m].notna().any() else None,
                         float(E_.loc[deb, c].corr(ae.Y3[deb], method='spearman')) if E_[c][deb].notna().any() else None]
                     for E_, cs in ((FE, C7), (GE, J7)) for c in cs},
            'miss': {c: [float(E_[c].isna().mean()), float(O_[c].isna().mean())]
                     for E_, O_, cs in ((FE, FO, C7), (GE, GO, J7)) for c in cs},
            'jra_last_date': str(J.date.max().date())}
    res_save('feat', info)
    FE.to_parquet(CEX, index=False); FO.to_parquet(COP, index=False)
    GE.to_parquet(JEX, index=False); GO.to_parquet(JOP, index=False)
    log('保存', CEX, COP, JEX, JOP)
    nk = races[races.track.isin(d3.NANKAN)]
    ne, no = nk[nk.race_date < '2022-01-01'], nk[nk.race_date >= '2022-01-01']
    z = {'c7_explore': vc.leak_check(h, XE[KEY + ['umaban']], FE, L, ne, 'c7_explore'),
         'c7_open': vc.leak_check(h, XO[KEY + ['umaban']], FO, L, no, 'c7_open'),
         'j7_explore': leak_j(h, XE[KEY + ['umaban']], GE, J, kmap, nmap, ne, 'explore'),
         'j7_open': leak_j(h, XO[KEY + ['umaban']], GO, J, kmap, nmap, no, 'open')}
    LEAKJ.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding='utf-8')
    for k, v in z.items():
        log('漏れ検査', k, v['match_days'], '/', v['days'], v['match'], '/', v['cells'])
    if any(v['match'] != v['cells'] for v in z.values()):
        write_md()
        for p in (CEX, COP, JEX, JOP, LEAKJ):
            p.unlink()
        raise SystemExit('⛔ 漏れ検査が 100% でない')


# ================================================================ judge・final・open
def load_d():
    d = vs.load()
    d['race_no'] = d.race_no.astype(int)
    for f in (CEX, JEX):
        d = d.merge(vo.nk(pd.read_parquet(f)), on=KEY + ['umaban'], how='left', validate='1:1')
    return d


FORMS = {'a': C7, 'b': J7, 'c': C7 + J7}


def judge():
    R = res_load()
    if 'judge' in R:
        log('judge は済み', R['judge']); return
    d = load_d()
    base = vc.base_cols()
    assert len(base) == 138
    ll0 = vs.race_ll(d, vs.fit(d, base))  # 土台は列の値が同じなので既存の cache を使ってよい
    vs.CACHE = CACHE_D  # c7_ は v7c と同じ列名で値が違うので cache を分ける
    out = {}
    for k, add in FORMS.items():
        ll1 = vs.race_ll(d, vs.fit(d, base + add))
        j = vs.judge(ll0, ll1)
        j['sum_base'], j['sum_new'] = round(float(ll0.sum()), 1), round(float(ll1.sum()), 1)
        out[k] = j
        log('judge', k, j)
    if out['c']['ok']:
        pick = 'c'
    else:
        ok = [k for k in ('a', 'b') if out[k]['ok']]
        pick = max(ok, key=lambda k: out[k]['gain']) if ok else 'base'
    out['pick'] = pick
    res_save('judge', out)
    log('採った形', pick)


def pick_cols():
    p = res_load()['judge']['pick']
    return None if p == 'base' else vc.base_cols() + FORMS[p]


def final():
    out_p = V3 / 'v7d_final_preds.parquet'
    cols = pick_cols()
    if cols is None:
        log('土台のまま: final は作らない'); return
    if out_p.exists():
        log('final は済み'); return
    vs.CACHE = CACHE_D
    d = load_d()
    ys = vs.SEL_Y + vs.CHK_Y
    te = d[d.year.isin(ys)].copy()
    out = te[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop']].copy()
    r1 = vs.fit(d, cols, 'Y1', ys, (31, 500, 400))
    r3 = vs.fit(d, cols, 'Y3', ys, (15, 100, 1200))
    p1 = r1 / pd.Series(r1, index=te.index).groupby([te[k] for k in KEY]).transform('sum').to_numpy()
    out['v7dpre_p1'], out['v7dpre_p3'] = p1, np.maximum(r3, p1)
    out['v7dpre_p3p'] = t6_base.p3prime(out, 'v7dpre_p3')[0]
    P7 = vo.nk(pd.read_parquet(V3 / 'v7_final_preds.parquet'))
    P7 = P7[KEY + ['umaban'] + [c for c in P7.columns if c.startswith('v7pre_') or c.startswith('v6re_')]]
    out = vo.nk(out).merge(P7, on=KEY + ['umaban'], how='left', validate='1:1')
    assert out.v7pre_p3p.notna().all() and out.v7dpre_p3p.notna().all()
    out.to_parquet(out_p, index=False)
    log('保存', out_p, out.shape)


def open_():
    out_p = V3 / 'v7d_open_preds.parquet'
    cols = pick_cols()
    if cols is None:
        log('土台のまま: open は作らない'); return
    if out_p.exists():
        log('open は済み'); return
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT))
    assert len(T) == 172738
    for f in (COP, JOP):
        T = T.merge(vo.nk(pd.read_parquet(f)), on=KEY + ['umaban'], how='left', validate='1:1')
    X6 = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XB = vo.nk(pd.read_parquet(V3 / 'feat_v7b_explore.parquet'))
    X = X6.merge(XB[KEY + ['umaban'] + vo.B7], on=KEY + ['umaban'], how='left', validate='1:1')
    for f in (CEX, JEX):
        X = X.merge(vo.nk(pd.read_parquet(f)), on=KEY + ['umaban'], how='left', validate='1:1')
    assert len(X) == len(X6) and X.race_date.max() < '2022-01-01' and set(T.columns) <= set(X.columns)
    ALL = o.sort4(pd.concat([X[list(T.columns)], T], ignore_index=True))
    assert not ALL.duplicated(KEY + ['umaban']).any()
    P = []
    for name, lo, hi in o.SEGS:
        tr = ALL[ALL.race_date < lo]
        te = o.seg_rows(T, lo, hi)
        r = {}
        for t in ('Y1', 'Y3'):
            m = vc.train(tr, t, cols)
            z = d3.logit((1 if t == 'Y1' else 3) / te.n.to_numpy(float))
            r[t] = d3.sig(z + m.predict(te[cols].astype(float), raw_score=True))
        x = te[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop']].copy()
        x['seg'] = name
        p1 = r['Y1'] / pd.Series(r['Y1'], index=x.index).groupby([x[k] for k in KEY]).transform('sum').to_numpy()
        x['v7dpre_p1'], x['v7dpre_p3'] = p1, np.maximum(r['Y3'], p1)
        x['v7dpre_p3p'] = t6_base.p3prime(x, 'v7dpre_p3')[0]
        P.append(x)
        log('区切り', name, '学び', len(tr), '予想', len(x))
    out = pd.concat(P, ignore_index=True).sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    P7 = vo.nk(pd.read_parquet(vo.PRED_OUT))
    P7 = P7[KEY + ['umaban'] + [c for c in P7.columns if c.startswith('v7pre_') or c.endswith('_v6pre')]]
    out = out.merge(P7, on=KEY + ['umaban'], how='left', validate='1:1')
    assert len(out) == 172738 and out.v7pre_p3p.notna().all() and out.v7dpre_p3p.notna().all()
    out.to_parquet(out_p, index=False)
    log('保存', out_p, out.shape)


# ================================================================ md
JDEF = {'j7_n': '中央の出走数', 'j7_w': '中央の 1 着数', 'j7_t3': '中央の 3 着以内数', 'j7_days': '中央の最後の走りからの日数',
        'j7_last_fin': '中央の最後の着順', 'j7_last_nst': '中央の最後の走りの頭数', 'j7_best': '中央での最高着順',
        'j7_dirt_rel': '中央のダートでの平均(着順 ÷ 頭数)', 'j7_last_pop': '中央の最後の走りの人気(中央の過去の結果の一部)',
        'j7_turf_n': '中央の芝の出走数', 'j7_best_l3f': '中央での上がり 3F の最速(秒)'}


def cdef(c):
    p = c.split('_')
    if c == 'c7_bmon':
        return '生まれ月'
    if c == 'c7_monage':
        return '生まれ月 × 年齢(2 歳 = 月・3 歳 = 20 + 月・4 歳以上 40)'
    if c == 'c7_area':
        return '産地 日高 1・胆振 2・その他 3'
    return vc.DEF[p[1]] + ' ' + vc.SUF['_'.join(p[2:])]


def fmt(v):
    return '—' if v is None or (isinstance(v, float) and np.isnan(v)) else f'{v:+.4f}'


def write_md():
    R = res_load()
    f = R['feat']
    li = f['ledger']
    L = ['# 第 7 版 d: 台帳を KDSCOPE に入れ替えた c7_ + 中央での成績 j7_', '',
         f'- 台帳 kd_horse.parquet {li["kd_rows"]} 行 → 血統登録番号で 1 頭 1 行(NU 優先){li["after_ketto_dedup_NU_first"]} 頭'
         f' → 同じ鍵「馬名|生年」が 2 頭以上で外した {li["dup_lk_removed"]} 行 → {li["ledger"]} 頭(内訳 {li["src"]})。'
         '馬主は今の値。c7_ の定義は v7c_run.py と同じ(率はその日より前の全 NAR の走り・自分を除く・縮め 3)。',
         f'- j7_: kd_jra_runs.parquet {f["jra_rows"]} 走(着順 0 = 取消等は除く)。そのレースの日より前(当日を含まない)の中央の走りだけ。'
         '南関のレースの人気・オッズは使わない。つなぎ = 台帳の鍵→血統登録番号、無ければ中央の走りの 馬名|生年(一意のとき)。'
         'つながった馬で中央の走りが無ければ数の列 = 0・他は欠け。つながらない馬は全部欠け。',
         f'- 注意: 中央の走りは {f["jra_last_date"]} まで(それより後の中央の走りは j7_ に入らない)。'
         'kd_se の 2022・2023 年の中央は欠けがある(kd_read.md)。',
         f'- 列 c7_ {len(C7)}・j7_ {len(J7)}', '',
         '## つながった割合(南関の出走・年ごと)', '',
         '| 年 | 行 | 台帳に鍵あり | 父・母・馬主のどれかあり | 血統登録番号とつながった | 前に中央の走りあり |', '|---|---|---|---|---|---|']
    for y, v in f['rate'].items():
        L.append(f'| {y} | {int(v["rows"])} | {100 * v["inled"]:.2f}% | {100 * v["linked"]:.2f}% | '
                 f'{100 * v["j_link"]:.2f}% | {100 * v["j_run"]:.2f}% |')
    L += ['', '## 列の定義・欠け率・順位相関(Y3・2016〜19)', '',
          f'デビュー = 手元で前の走りが無い行({f["n_debut_rows"]} 行)。', '',
          '| 列 | 定義 | 欠け 作る | 欠け 答え合わせ | 相関 全体 | 相関 デビュー |', '|---|---|---|---|---|---|']
    for c in C7 + J7:
        de = JDEF[c] if c in JDEF else cdef(c)
        mi, co = f['miss'][c], f['corr'][c]
        L.append(f'| {c} | {de} | {100 * mi[0]:.1f}% | {100 * mi[1]:.1f}% | {fmt(co[0])} | {fmt(co[1])} |')
    if LEAKJ.exists():
        z = json.loads(LEAKJ.read_text(encoding='utf-8'))
        L += ['', '## 漏れ検査(t4_base.pick_days の 20 日・その日の結果を空にして作り直し。j7_ は中央の走りもその日までに切り、その日の結果を空に)', '']
        for k, v in z.items():
            L.append(f'- {k}: {v["match_days"]} / {v["days"]} 日一致・セル {v["match"]} / {v["cells"]}')
    if 'judge' in R:
        J = R['judge']
        name = {'a': '(a) c7_ だけ', 'b': '(b) j7_ だけ', 'c': '(c) c7_ + j7_'}
        L += ['', '## judge(土台 v7_select.json の 138 列に足す・2016〜19・Y3 15/500/800・線 = 伸び > 2 × 標準誤差 かつ 4 年中 3 年)', '',
              '| 形 | 伸び | 標準誤差 | 年ごと 2016〜19 | 通った | 和 土台 → 足した |', '|---|---|---|---|---|---|']
        for k in ('a', 'b', 'c'):
            j = J[k]
            L.append(f'| {name[k]} | {j["gain"]} | {j["se"]} | {j["years"]} | {j["ok"]} | {j["sum_base"]} → {j["sum_new"]} |')
        L += ['', f'- 採った形: **{name.get(J["pick"], "土台のまま(どれも線を通らない)")}**']
        if J['pick'] != 'base':
            L += ['', '## 予想', '', '- v3/v7d_final_preds.parquet(2016〜21 の当てはめ外・v7_select.final と同じ手順)',
                  '- v3/v7d_open_preds.parquet(2022-01〜2026-08・v7_open と同じ区切りの学び直し・172,738 行)',
                  '- 列 v7dpre_p1・v7dpre_p3・v7dpre_p3p、比べ用に v7pre_…・(open は p1_v6pre…、final は v6re_…)']
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    steps = {'feat': [feat], 'judge': [judge], 'final': [final], 'open': [open_], 'md': [write_md],
             'all': [feat, judge, final, open_, write_md]}[cmd]
    for s in steps:
        s()
