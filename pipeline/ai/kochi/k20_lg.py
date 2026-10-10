# -*- coding: utf-8 -*-
"""他場版 v3n の Glicko など 18 列(2026-10-10・v3 の out/v3n_glicko.md・研究の台本 src/kochi/k20_glicko.py lg)。

南関 v3 の第 11 版の LG 18 列(src/lit_g_feats.py)を、公式の全場の記録(k9 の kd_se・地方の全場 2014〜)で作る。学習はしない(集計だけ)。
  - Glicko 型 2 本(着順・着差)・Elo 6 着・カルマン(公式の SI)。各行の値は**そのレースより前**の走りだけで作る(当日の行は更新前の値)。
  - 定数は南関で 2014〜15 だけで決めた値(c = 50・W = 3・R = 0.5 V0・Qd = 0.002 V0)。V0・平均は SI 表の 2014〜15 で数える。
  - 取消・除外(ijo 1・3)は除く。中止は最下位。中央・ばんえいの走りは数えない。同じ場・日・R・馬番の重なりは 1 行に。
"""
import numpy as np
import pandas as pd

KEY = ['track', 'race_date', 'race_no']
K = KEY + ['umaban']
Q = np.log(10) / 400
PHI0 = 350.0
C_G, W_G, R_K, Q_K = 50.0, 3.0, 0.5, 0.002
JRA_OR_BAN = set(range(1, 11)) | {83}
LGC = ['lg_g_mu', 'lg_g_sd', 'lg_g_rank', 'lg_g_dif', 'lg_g_cons', 'lg_gm_mu', 'lg_gm_sd', 'lg_gm_rank', 'lg_gm_dif', 'lg_gm_cons',
       'lg_k_mu', 'lg_k_sd', 'lg_k_rank', 'lg_k_dif', 'lg_k_cons', 'lg_e6', 'lg_e6_rank', 'lg_e6_dif']


def dnum(s):
    return pd.to_datetime(s).values.astype('datetime64[D]').astype(np.int64)


def prep(st):
    st = st.copy()
    st['dn'] = dnum(st.race_date)
    st = st.sort_values(['dn', 'track', 'race_no', 'umaban'], kind='mergesort').reset_index(drop=True)
    g = st.groupby(KEY, sort=False)
    st['nst'] = g.umaban.transform('size')
    st['fin'] = st.finish.where(st.finish.notna(), st.nst).astype(float)
    tmin = g.time_sec.transform('min')
    st['gap'] = (st.time_sec - tmin).clip(0, 2).fillna(2.0)
    st['tok'] = g.time_sec.transform(lambda x: x.notna().any()).astype(bool)
    return st


def gfun(ph):
    return 1 / np.sqrt(1 + 3 * Q * Q * ph * ph / np.pi ** 2)


def g_update(mu, ph, S, w):
    gj = gfun(ph)
    E = 1 / (1 + 10 ** (-gj[None, :] * (mu[:, None] - mu[None, :]) / 400))
    np.fill_diagonal(E, 0)
    S = S.copy()
    np.fill_diagonal(S, 0)
    vin = Q * Q * w * (gj[None, :] ** 2 * E * (1 - E)).sum(1)
    den = 1 / ph ** 2 + vin
    return mu + Q / den * w * (gj[None, :] * (S - E)).sum(1), np.sqrt(1 / den)


def run_seq(st, c, W):
    """日付の順に回し、各行の「そのレースの前」の Elo 6 着・Glicko 2 本を返す(研究の lit_g_feats.run_seq の採点を抜いたもの)。"""
    hc = pd.factorize(st.hid)[0]
    nh = hc.max() + 1
    dn = st.dn.to_numpy()
    fin = st.fin.to_numpy()
    gap = st.gap.to_numpy()
    tok = st.tok.to_numpy()
    rk = st.groupby(KEY, sort=False).ngroup().to_numpy()
    b = np.flatnonzero(np.r_[True, rk[1:] != rk[:-1], True])
    R = {k: np.full(nh, np.nan) for k in ('e6', 'gmu', 'gph', 'mmu', 'mph')}
    last = np.zeros(nh, np.int64)
    O = {k: np.full(len(st), np.nan) for k in ('e6', 'g_mu', 'g_phi', 'gm_mu', 'gm_phi')}
    for s, e in zip(b[:-1], b[1:]):
        ix = hc[s:e]
        n = e - s
        f = fin[s:e]
        d = dn[s]
        Sf = (f[:, None] < f[None, :]) + 0.5 * (f[:, None] == f[None, :])
        r0 = R['e6'][ix]
        O['e6'][s:e] = r0
        if n >= 2:
            ok = ~((f[:, None] >= 6) & (f[None, :] >= 6))
            kn = ~np.isnan(r0)
            r = np.where(kn, r0, r0[kn].mean() if kn.any() else 1500.0)
            E_ = 1 / (1 + 10 ** ((r[None, :] - r[:, None]) / 400))
            S_ = Sf.astype(float).copy()
            np.fill_diagonal(S_, 0)
            np.fill_diagonal(E_, 0)
            R['e6'][ix] = r + 32.0 / (n - 1) * ((S_ - E_) * ok).sum(1)
        for mk, pk, om, op, Smat in (('gmu', 'gph', 'g_mu', 'g_phi', Sf.astype(float)), ('mmu', 'mph', 'gm_mu', 'gm_phi', None)):
            m0, p0 = R[mk][ix], R[pk][ix]
            kn = ~np.isnan(m0)
            pp = np.where(kn, np.minimum(np.sqrt(np.nan_to_num(p0) ** 2 + c * c * (d - last[ix]) / 30.0), PHI0), np.nan)
            O[om][s:e] = m0
            O[op][s:e] = pp
            if n < 2:
                continue
            mu = np.where(kn, m0, m0[kn].mean() if kn.any() else 1500.0)
            ph = np.where(kn, pp, PHI0)
            if Smat is None:
                if tok[s]:
                    gp = gap[s:e]
                    Smat = 0.5 + 0.5 * np.clip((gp[None, :] - gp[:, None]) / 0.5, -1, 1)
                else:
                    Smat = Sf.astype(float)
            m1, p1 = g_update(mu, ph, Smat, W / (n - 1))
            R[mk][ix], R[pk][ix] = m1, p1
        last[ix] = d
    return O


def run_kalman(S, R_, Qd, m_glob, P0):
    hid = S.hid.to_numpy()
    dn = S.dn.to_numpy()
    si = S.SI.to_numpy(float)
    ap = S.a_prior.to_numpy(float)
    om, osd = np.full(len(S), np.nan), np.full(len(S), np.nan)
    m = P = 0.0
    seen = False
    ld = 0
    for i in range(len(S)):
        if i == 0 or hid[i] != hid[i - 1]:
            seen = False
        if not seen:
            if np.isnan(si[i]):
                continue
            m0 = ap[i] if not np.isnan(ap[i]) else m_glob
            k = P0 / (P0 + R_)
            m, P = m0 + k * (si[i] - m0), (1 - k) * P0
            seen, ld = True, dn[i]
            continue
        Pp = P + Qd * (dn[i] - ld)
        om[i], osd[i] = m, np.sqrt(Pp)
        if not np.isnan(si[i]):
            k = Pp / (Pp + R_)
            m, P = m + k * (si[i] - m), (1 - k) * Pp
        else:
            P = Pp
        ld = dn[i]
    return om, osd


def build(se_path, si_path, log=print):
    """→ DataFrame(track = 場の番号・race_date 'YYYY-MM-DD'・race_no・umaban + 18 列)。地方の全場の行。"""
    se = pd.read_parquet(se_path, columns=['jyo', 'date', 'race', 'umaban', 'ketto', 'ijo', 'finish', 'time_sec'])
    se = se[~se.jyo.isin(JRA_OR_BAN) & ~se.ijo.isin([1, 3]) & se.ketto.notna()]
    se = se.drop_duplicates(['jyo', 'date', 'race', 'umaban'])
    st = pd.DataFrame({'track': se.jyo.astype(int), 'race_date': se.date.dt.strftime('%Y-%m-%d'), 'race_no': se.race.astype(int),
                       'umaban': se.umaban.astype(int), 'hid': se.ketto.astype(np.int64),
                       'finish': se.finish.where(se.finish > 0), 'time_sec': se.time_sec.where(se.time_sec > 0)})
    st = prep(st)
    O = run_seq(st, C_G, W_G)
    S = pd.read_parquet(si_path, columns=['date', 'jyo', 'race', 'umaban', 'ketto', 'SI', 'prior'])
    S = S[~S.jyo.isin(JRA_OR_BAN) & S.ketto.notna()]
    S = pd.DataFrame({'track': S.jyo.astype(int), 'race_date': S.date.dt.strftime('%Y-%m-%d'), 'race_no': S.race.astype(int),
                      'umaban': S.umaban.astype(int), 'hid': S.ketto.astype(np.int64), 'SI': S.SI, 'a_prior': S.prior})
    S['dn'] = dnum(S.race_date)
    S = S.merge(st[K], on=K, how='inner').drop_duplicates(K)
    S = S.sort_values(['hid', 'dn', 'race_no'], kind='mergesort').reset_index(drop=True)
    S_t = S[S.dn < int(dnum(pd.Series(['2016-01-01']))[0])]
    ok = S_t.SI.notna()
    m_glob = float(S_t.SI[ok].mean())
    V0 = float((S_t.SI - S_t.a_prior.fillna(m_glob))[ok].var())
    km, ksd = run_kalman(S, V0 * R_K, V0 * Q_K, m_glob, V0)
    A = st[K].copy()
    for k, v in O.items():
        A[k] = v
    B = S[K].copy()
    B['k_mu'], B['k_sd'] = km, ksd
    A = A.merge(B, on=K, how='left', validate='1:1')
    X = A[K].copy()
    g = A.groupby(KEY, sort=False)
    for pre, mu, sd in (('g', 'g_mu', 'g_phi'), ('gm', 'gm_mu', 'gm_phi'), ('k', 'k_mu', 'k_sd'), ('e6', 'e6', None)):
        X[f'lg_{pre}_mu' if pre != 'e6' else 'lg_e6'] = A[mu]
        if sd:
            X[f'lg_{pre}_sd'] = A[sd]
        X[f'lg_{pre}_rank'] = g[mu].rank(ascending=False, method='min')
        X[f'lg_{pre}_dif'] = A[mu] - g[mu].transform('mean')
        if sd:
            X[f'lg_{pre}_cons'] = A[mu] - 2 * A[sd]
    log('Glicko など 18 列', f'{len(X):,} 行', 'V0', round(V0, 2))
    return X
