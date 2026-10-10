# -*- coding: utf-8 -*-
"""高知版 8 = 南関 t4_base.py の速さの指数を全場の走りに移す(決め書 out/kochi_si_plan.md・2026-10-10)。

  py -3.12 -X utf8 src/kochi/k8_si.py   → C:/Users/kouki/nankan_ai/v3/kochi/si_n.parquet(高知の行・n_ の列)
                                           ・C:/Users/kouki/nankan_ai/v3/kochi/si_all.parquet(全場の走りの SI・全国版で使う)
"""
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import k1_feat as k1  # noqa: E402

V = Path('C:/Users/kouki/nankan_ai/v3/kochi')
RK = ['date', 'jyo', 'race']
MIN_R, HALF, Y0 = 30, 90.0, 2002
DIV = {'T': lambda d: d / 1000, 'F': lambda d: (d - 600) / 1000, 'L': lambda d: np.full(len(d), 0.6)}
log = k1.log


def ra_all():
    """RA の生記録(全場)からクラス名・名前の有無・馬場(芝・ダ)。"""
    L, parts = 1272, []
    with open('C:/KDSCOPE/Data/RA/RA.DAT', 'rb') as f:
        while True:
            buf = f.read(L * 200000)
            if not buf:
                break
            a = np.frombuffer(buf, dtype=np.uint8).reshape(-1, L)
            a = a[(a[:, 0] == 82) & (a[:, 1] == 65)]

            def s(x, y):
                return np.ascontiguousarray(a[:, x:y]).view(f'S{y - x}').ravel()

            def n(x, y):
                sub = a[:, x:y].astype(np.int64) - 48
                ok = ((sub >= 0) & (sub <= 9)).all(1)
                v = (sub * (10 ** np.arange(y - x - 1, -1, -1))).sum(1).astype(float)
                v[~ok] = np.nan
                return v
            parts.append(pd.DataFrame({'make': s(3, 11), 'year': n(11, 15), 'md': n(15, 19), 'jyo': n(19, 21),
                                       'race': n(25, 27), 'clsb': s(637, 673), 'nameb': s(32, 92),
                                       'baba_t': a[:, 888].astype(int) - 48, 'baba_d': a[:, 889].astype(int) - 48}))
    R = pd.concat(parts, ignore_index=True)
    R = R.sort_values('make').drop_duplicates(['year', 'md', 'jyo', 'race'], keep='last')
    R = R.dropna(subset=['year', 'md', 'jyo', 'race'])
    R = R[R.year >= Y0 - 4].copy()
    dec = {b: unicodedata.normalize('NFKC', b.decode('cp932', 'replace')).replace(' ', '') for b in R.clsb.unique()}
    R['cls'] = R.clsb.map(dec)
    R['has_name'] = R.nameb.map(lambda b: b.strip(b' ') not in (b'', ) and b.replace(b'\x81\x40', b'').strip() != b'')
    for c in ['year', 'md', 'jyo', 'race']:
        R[c] = R[c].astype(int)
    log('RA 全場', f'{len(R):,}')
    return R[['year', 'md', 'jyo', 'race', 'cls', 'has_name', 'baba_t', 'baba_d']]


def cls_key(jyo, cls, has_name, ccmin):
    if 1 <= jyo <= 10:
        return f'{jyo}_J{int(ccmin)}' if ccmin == ccmin else None
    if cls.startswith('2歳'):
        return f'{jyo}_Y2'
    if cls.startswith('3歳'):
        return f'{jyo}_Y3'
    m = re.match(r'([A-E])(\d?)', cls)
    if m:
        return f'{jyo}_{m.group(1)}{m.group(2)}'
    return f'{jyo}_JS' if has_name else None


def fit_window(W):
    """南関 t4_base.fit_window と同じ(0 点だけ場ごとの一番多いクラス)。"""
    v = W.v.values
    cs, ks, ds = W.course.values, W.k.values, W.dtk.values
    dl = np.zeros(len(W)); D = np.zeros(len(W))
    ref = W.groupby('jyo').k.agg(lambda x: x.value_counts().index[0])
    s = None
    for _ in range(10):
        b = pd.Series(v - dl - D).groupby(cs).transform('median').values
        s = pd.Series(v - b - D).groupby(ks).median()
        s = s - pd.Series({k: s.get(ref.get(int(k.split('_')[0])), 0.0) for k in s.index})
        dl = pd.Series(ks).map(s).values
        D = pd.Series(v - b - dl).groupby(ds).transform('median').values
    own = pd.Series(b, index=cs).groupby(level=0).first().to_dict()
    Dd = pd.Series(D, index=ds).groupby(level=0).first()
    return own, s.to_dict(), Dd


def course_b(courses, own):
    by = {}
    for c, b in own.items():
        t, d, sf = c.split('_')
        by.setdefault((t, sf), []).append((int(d), b))
    out = {}
    for c in courses:
        if c in own:
            out[c] = own[c]; continue
        t, d, sf = c.split('_'); d = int(d)
        cand = sorted((abs(dd - d), dd, b) for dd, b in by.get((t, sf), []) if abs(dd - d) <= 200)
        out[c] = cand[0][2] if cand else np.nan
    return out


def main():
    se = k1.load_se()
    se = se[(se.year >= Y0 - 3) & (se.surf < 2) & (se.dist > 0)].copy()
    ra = ra_all()
    cc = pd.concat([pd.read_parquet(k1.V + f, columns=['make', 'year', 'md', 'jyo', 'race', 'ccmin'])
                    for f in ['kd_ra.parquet', 'kd_ra_open.parquet']]).dropna(subset=['year', 'jyo', 'race'])
    cc = cc.sort_values('make').drop_duplicates(['year', 'md', 'jyo', 'race'], keep='last').drop(columns='make')
    for c in ['year', 'md', 'jyo', 'race']:
        cc[c] = cc[c].astype(int)
    R = se.groupby(RK + ['year', 'md', 'dist', 'surf']).size().reset_index(name='nn')
    R['jyo'], R['race'], R['md'] = R.jyo.astype(int), R.race.astype(int), R.md.astype(int)
    R = R.merge(ra, on=['year', 'md', 'jyo', 'race'], how='left').merge(cc, on=['year', 'md', 'jyo', 'race'], how='left')
    R['k0'] = [cls_key(j, c if isinstance(c, str) else '', bool(h) if h == h else False, m)
               for j, c, h, m in zip(R.jyo, R.cls, R.has_name, R.ccmin)]
    R['going'] = np.where(R.surf == 1, R.baba_t, R.baba_d)
    R['going'] = R.going.where(R.going.between(1, 4))
    R['course'] = R.jyo.astype(str) + '_' + R.dist.astype(int).astype(str) + '_' + R.surf.astype(str)
    R['dtk'] = R.date.dt.strftime('%Y%m%d') + '_' + R.jyo.astype(str)
    g = R.sort_values('race').groupby('dtk').going.agg(lambda x: x.dropna().mode().iloc[0] if x.notna().any() else np.nan)
    R['gmode'] = R.dtk.map(g)
    log('レース', f'{len(R):,}', 'クラスが読めた', round(R.k0.notna().mean(), 3))
    U = se.copy()
    U['jyo'], U['race'] = U.jyo.astype(int), U.race.astype(int)
    U['F'] = U.time_sec - U.l3f
    top = U[U.fin <= 3]
    val = top.groupby(RK).agg(vT=('time_sec', 'mean'), vF=('F', 'mean'), vL=('l3f', 'mean')).reset_index()
    R = R.merge(val, on=RK, how='left')
    d = R.dist.values.astype(float)
    for q in 'TFL':
        R['v' + q] = R['v' + q] / DIV[q](d)
        if q == 'F':
            R.loc[R.dist <= 600, 'vF'] = np.nan
    years = list(range(Y0, int(R.year.max()) + 1))
    kmaps = {}
    for q in 'TFL':
        for c in ['bc_', 'dl_', 'D_']:
            R[c + q] = np.nan
        for y in years:
            Wa = R[R.year.between(y - 3, y - 1) & R['v' + q].notna() & R.k0.notna()]
            kc = Wa.k0.value_counts()
            km = {k: (k if n >= MIN_R else k.split('_')[0] + '_other') for k, n in kc.items()}
            if q == 'T':
                kmaps[y] = km
            ccn = Wa.course.value_counts()
            W = Wa[Wa.course.isin(set(ccn[ccn >= MIN_R].index))].assign(k=lambda x: x.k0.map(km), v=lambda x: x['v' + q])
            own, delta, Dd = fit_window(W)
            gm = pd.DataFrame({'D': Dd}).join(W.drop_duplicates('dtk').set_index('dtk')[['jyo', 'gmode']])
            Dm_tg = gm.groupby(['jyo', 'gmode']).D.mean().to_dict()
            Dm_t = gm.groupby('jyo').D.mean().to_dict()
            iy = R.index[R.year == y]
            Ry = R.loc[iy]
            bc = Ry.course.map(course_b(Ry.course.unique(), own)).astype(float)
            bown = Ry.course.map(own).astype(float)
            dl = Ry.k0.map(km).map(delta).astype(float)
            r = Ry['v' + q] - bown - dl
            Draw = r.groupby(Ry.dtk).transform('median')
            n = r.notna().groupby(Ry.dtk).transform('sum')
            Dm = pd.Series([Dm_tg.get((t, gg), Dm_t.get(t, 0.0)) for t, gg in zip(Ry.jyo, Ry.gmode)], index=iy).fillna(0.0)
            R.loc[iy, 'bc_' + q] = bc.values
            R.loc[iy, 'dl_' + q] = dl.values
            R.loc[iy, 'D_' + q] = np.where(n > 0, n / (n + 5) * Draw + 5 / (n + 5) * Dm, Dm)
        log('当てはめ', q)
    R['kT'] = [kmaps.get(y, {}).get(k) if k is not None else None for y, k in zip(R.year, R.k0)]
    U = U.merge(R[RK + ['bc_T', 'bc_F', 'bc_L', 'D_T', 'D_F', 'D_L', 'kT']], on=RK, how='left')
    dd = U.dist.values.astype(float)
    win_t = U.groupby(RK).time_sec.transform('min')
    Tt = np.minimum(U.time_sec, win_t + 2.0 * dd / 1000)
    B = U.bc_T * dd / 1000
    U['SI'] = 80 + (1000 / B) * (B - Tt + U.D_T * dd / 1000) + 2 * (U.kinryo - 55)
    BF = U.bc_F * (dd - 600) / 1000
    U['TEN'] = 80 + (1000 / BF) * (BF - U.F + U.D_F * (dd - 600) / 1000)
    BL = U.bc_L * 0.6
    U['UP'] = 80 + (1000 / BL) * (BL - U.l3f + U.D_L * 0.6)
    U.loc[U.year < Y0, ['SI', 'TEN', 'UP']] = np.nan
    # 事前の値(クラスの前 3 年の SI の平均)
    U['prior'] = np.nan
    for y in years:
        Wr = U[U.year.between(y - 3, y - 1) & U.SI.notna()]
        means = Wr.SI.groupby(Wr.kT).mean().to_dict()
        allj = Wr.SI.groupby(Wr.jyo).mean().to_dict()
        iy = U.index[U.year == y]
        U.loc[iy, 'prior'] = [means.get(k, allj.get(j, np.nan)) for k, j in zip(U.loc[iy, 'kT'], U.loc[iy, 'jyo'])]
    U[[*RK, 'umaban', 'ketto', 'SI', 'TEN', 'UP', 'prior']].to_parquet(V / 'si_all.parquet', index=False)
    log('SI', 'SI が付いた割合(高知 2006〜)', round(U.loc[(U.jyo == k1.KOCHI) & (U.year >= 2006), 'SI'].notna().mean(), 4))
    # 馬の過去(全場)
    keys = set(U.loc[U.jyo == k1.KOCHI, 'ketto']) - {0}
    H = U[U.ketto.isin(keys)].sort_values(['ketto', 'date']).reset_index(drop=True)
    hid = pd.factorize(H.ketto)[0].astype(np.int64)
    dnum = (H.date - pd.Timestamp('1980-01-01')).dt.days.values
    key = hid * 100000 + dnum
    S = H.SI.notna().values
    Skey, Ssi, Sd = key[S], H.SI.values[S], dnum[S]
    pos = np.searchsorted(Skey, key, 'left')
    hst = np.searchsorted(Skey, hid * 100000, 'left')
    sw = np.zeros(len(H)); swsi = np.zeros(len(H))
    for j in range(1, 6):
        idx = pos - j
        ok = idx >= hst
        ii = np.where(ok, idx, 0)
        w = np.where(ok, 0.5 ** ((dnum - Sd[ii]) / HALF), 0.0)
        sw += w; swsi += np.where(ok, w * Ssi[ii], 0.0)
    H['n_siw'] = np.where(sw > 0, swsi / np.where(sw > 0, sw, 1), np.nan)
    H['n_ab'] = (swsi + H.prior.fillna(H.prior.mean()).values) / (sw + 1)
    gk = H.groupby('ketto')
    H['n_si1'] = gk.SI.shift(1)
    H['n_ten1'], H['n_up1'] = gk.TEN.shift(1), gk.UP.shift(1)
    H['n_tenw'] = pd.concat([gk.TEN.shift(k) for k in (1, 2, 3)], axis=1).mean(1)
    H['n_upw'] = pd.concat([gk.UP.shift(k) for k in (1, 2, 3)], axis=1).mean(1)
    H['n_prior'] = H.prior
    T = H[H.jyo == k1.KOCHI].copy()
    g = T.groupby(RK)
    T['n_lv'] = g.n_ab.transform(lambda x: x.nlargest(5).mean())
    H = H.merge(T[RK + ['umaban', 'n_lv']], on=RK + ['umaban'], how='left')
    T['n_lv1'] = T[RK + ['umaban']].merge(
        H.assign(n_lv1=H.groupby('ketto').n_lv.shift(1))[RK + ['umaban', 'n_lv1']], on=RK + ['umaban'], how='left').n_lv1.values
    for src, nm in [('n_ab', 'ab'), ('n_si1', 'si')]:
        x = T[src]
        cnt = g[src].transform('count')
        T[f'n_k_{nm}_rank'] = g[src].rank(ascending=False, method='average') / cnt
        mu = g[src].transform('mean')
        sd = g[src].transform(lambda z: z.std(ddof=0))
        T[f'n_k_{nm}_z'] = (x - mu) / np.maximum(sd, 1.0)
        T[f'n_k_{nm}_gap'] = x - g[src].transform('max')
        if nm == 'ab':
            T['n_k_ab_sd'] = sd
    cols = [c for c in T.columns if c.startswith('n_')]
    T = T[T.date >= k1.START][['date', 'race', 'umaban'] + cols]
    T['race'] = T.race.astype('int16')
    T.to_parquet(V / 'si_n.parquet', index=False)
    log('保存', T.shape, T[cols].notna().mean().round(2).to_dict())


if __name__ == '__main__':
    main()
