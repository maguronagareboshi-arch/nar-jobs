# -*- coding: utf-8 -*-
"""第 5 版 2 日目(PREREG5 §3・§4-1・§5・§10・§11): 段 A = 物差しの合わせ直し(SI5)。
2022-01-01 以降は読まない(load_archive の見張り・t4_base.load の assert)。第 4 版の台本は直さずに呼ぶ。

  py -3.12 -X utf8 src/t5_base.py si5    # rebuild の一致 → SI5 を日付の順に作る → 部品の点検 A → v3/t5_base_si5_2014_2021.parquet
  py -3.12 -X utf8 src/t5_base.py table  # 93 列の表の一致 → 置き換わる列を乱数で決める → v3/feat_t5a_explore.parquet
  py -3.12 -X utf8 src/t5_base.py leak   # リーク検査 A(20 日・seed 0・うち 4 日は 1 月)
  py -3.12 -X utf8 src/t5_base.py fit    # 第 4 版の段 5 の再現 → 段 A の当てはめ外(2016〜2021)→ 採否
  py -3.12 -X utf8 src/t5_base.py md     # out/t5_day2_parts.md

■ 決め書に無い細部(この台本で決めた・当てはめ外を見る前。見た後は変えない)
  1. rebuild の区分の対応(kmaps)は U から作り直す: レースの k0 と、着順 1〜3 の馬に時計と距離があるか(= t4_base の vT の有無)で
     窓のレースを数え、t4_base.kmap_make に通す。U の kT と一致することを assert する。
  2. o_s の組 = U(南関・取消/除外を除く)を馬・日付・R の順に並べた隣り合う 2 行。前か後に第 4 版の SI が無い組は使わない
     (飛ばして次の走りと組まない)。間隔 = 日数の差 ≤ 90。
  3. ① の回帰は同じ場の組(4 場まとめて)で 1 本。③ は行 o_B − o_A = θ_AB に √重み を掛けた最小二乗(lstsq の最小ノルム解)から
     平均を引いて 4 場の平均 0。使える組で 4 場がつながらなければ止める。
  4. D_proj の b_c = そのレースの bc_T(近い距離から借りたものも使う)。T = 打ち切り後の走破。力の分かっている馬は a_sin5 ≥ 3 で
     T・bc_T・斤量がある馬。
  5. a_sin5 = 直前の南関の 5 走(取消・除外を除く)のうち SI5 のある数(t4_day3.feat_new の a_sin と同じ数え方)。
     a_ab5 の 5 走 = SI5 のある直前の 5 走(t4_base の a_ab と同じ)。どちらも前日までの走りだけ。2014 年の行も同じ式で作る。
  6. c'_y の「日」= 日×場(dtk)。D = D_T(日×場で一つ)。窓に D_proj_生 のある日が無ければ 0。
  7. 点検の D_proj の奇数/偶数: 同じ a_ab5・同じ力の分かっている馬で作ったレースの値を奇数 R・偶数 R に分け、それぞれ 2 R 以上ある
     日×場(2016〜2021)で中央値 − c'_y の相関。
  8. SI5 の続き具合の組: 細部 2 の隣り合う 2 行で、後の走りが 2015〜2021・90 日以内・両方に SI5 がある組(第 4 版の点検と同じ組)。
  9. 場の組の数の点検は ② の n_AB・n_BA(後の走りが窓の年の組)をそのまま使う。
  10. 置き換わる列を決める乱数: SI のある行に 正規分布(標準偏差 0.1 点・seed 0)を足して rebuild → feat_new・assemble。
      93 列のうち 1 つでも値が変わった列を置き換わる列とする。
  11. 材料の表の〔v3〕の列(assemble の X3)は v3/feat_t3_explore.parquet を使う(t4_day3.features で X3 と 100% 一致を確かめ済み)。
      列が足りなければ t4_day3.features と同じ作り方(build3 → finish_table)に切り替える。
  12. リーク検査 A で比べる列 = a_ab5・a_sin5 と rebuild(U, SI5) の a_prior・a_si1・a_siw・a_ab・b_lv・b_lv1・k_* 7 列。
  13. 一致の判定は |差| ≤ 1e-9(両方欠けも一致)。段 5 の再現の桁 = ◎ 勝率 3 桁・◎ 3 着以内率 4 桁・対数尤度 Y3 5 桁。
  14. 当てはめ外の模型の置き場 = v3/t5_cache(t4_day3.fit_pred の CACHE を差し替えて呼ぶ)。

■ 置き換わる列(table で機械的に決めた。段 A の当てはめ外を見る前に書いた)
  21 列: a_si1・a_si2・a_simax5・a_siw・a_ab・a_sisd・a_sislope・b_lv・b_lv1・b_lvchg・k_ab_rank・k_ab_z・k_ab_gap・k_si_rank・k_si_z・k_si_gap・k_ab_sd・h_plus・d_simax・e_trksi・e_heavy
"""
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_base  # noqa: E402
import t4_day3  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
BASE4 = V3 / 't4_base_2014_2021.parquet'
BASE5 = V3 / 't5_base_si5_2014_2021.parquet'
FEAT4 = V3 / 'feat_t4_explore.parquet'
FEAT5 = V3 / 'feat_t5a_explore.parquet'
J_SI5, J_COLS, J_LEAK, J_FIT = (V3 / f't5_day2_{k}.json' for k in ('si5', 'cols', 'leak', 'fit'))
MD = REPO / 'out/t5_day2_parts.md'
RK = t4_base.RK
KEY = t4_day3.KEY
NANKAN = t4_base.NANKAN
HALF = t4_base.HALF
REB = ['a_prior', 'a_siw', 'a_ab', 'a_si1', 'b_lv', 'b_lv1',
       'k_ab_rank', 'k_ab_z', 'k_ab_gap', 'k_si_rank', 'k_si_z', 'k_si_gap', 'k_ab_sd']
LEAK5 = ['a_ab5', 'a_sin5', 'a_prior', 'a_si1', 'a_siw', 'a_ab', 'b_lv', 'b_lv1',
         'k_ab_rank', 'k_ab_z', 'k_ab_gap', 'k_si_rank', 'k_si_z', 'k_si_gap', 'k_ab_sd']
REPLACED = ['a_si1', 'a_si2', 'a_simax5', 'a_siw', 'a_ab', 'a_sisd', 'a_sislope', 'b_lv', 'b_lv1', 'b_lvchg', 'k_ab_rank', 'k_ab_z', 'k_ab_gap', 'k_si_rank', 'k_si_z', 'k_si_gap', 'k_ab_sd', 'h_plus', 'd_simax', 'e_trksi', 'e_heavy']  # table の後に書いた(当てはめ外の前)
YRS = list(range(2015, 2022))


def win_of(y):
    return [2014] if y in (2014, 2015) else [x for x in range(y - 3, y) if x >= 2014]


def eqmask(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-9)


# ================================================================ rebuild
def kmaps_of(U):
    top = U[(U.finish <= 3) & U.time_sec.notna() & U.distance_m.notna()]
    has = set(map(tuple, top[RK].drop_duplicates().to_numpy()))
    RR = U.drop_duplicates(RK)
    RR = RR[[tuple(x) in has for x in RR[RK].to_numpy()]]
    km = {}
    for y in sorted(U.year.unique()):
        km[y] = t4_base.kmap_make(RR[RR.year.isin(win_of(y))].k0.value_counts())
    return km


def rebuild(U, si):
    """t4_base.build の SI より後(a_prior〜k_*)を同じ式で作り直す。U = build の出力の形。"""
    U = U.copy()
    U['SI'] = np.asarray(si, float)
    kmaps = kmaps_of(U)
    kt = [kmaps[y].get(k) if k is not None else None for y, k in zip(U.year, U.k0)]
    assert all((a == b) or (a is None and (b is None or b != b)) for a, b in zip(kt, U.kT)), 'kmaps が kT と合わない'
    U['a_prior'] = np.nan
    for y in sorted(U.year.unique()):
        Wr = U[U.year.isin(win_of(y)) & U.SI.notna()]
        km = kmaps[y]
        mk = Wr.k0.map(km)
        means = Wr.SI.groupby(mk).mean().to_dict()
        allm = Wr.SI.mean()
        iy = U.index[U.year == y]
        U.loc[iy, 'a_prior'] = [means.get(km.get(k), allm) if k is not None else allm for k in U.loc[iy, 'k0']]
    order = U.columns
    U['dnum'] = (pd.to_datetime(U.race_date) - pd.Timestamp('2000-01-01')).dt.days
    U = U.sort_values(['hk', 'race_date', 'race_no']).reset_index(drop=True)
    hid = pd.factorize(U.hk)[0].astype(np.int64)
    key = hid * 100000 + U.dnum.values
    S = U.SI.notna().values
    Skey, Ssi, Sd = key[S], U.SI.values[S], U.dnum.values[S]
    pos = np.searchsorted(Skey, key, 'left')
    hst = np.searchsorted(Skey, hid * 100000, 'left')
    sw = np.zeros(len(U)); swsi = np.zeros(len(U))
    for j in range(1, 6):
        idx = pos - j
        ok = idx >= hst
        ii = np.where(ok, idx, 0)
        w = np.where(ok, 0.5 ** ((U.dnum.values - Sd[ii]) / HALF), 0.0)
        sw += w; swsi += np.where(ok, w * Ssi[ii], 0.0)
    U['a_siw'] = np.where(sw > 0, swsi / np.where(sw > 0, sw, 1), np.nan)
    U['a_ab'] = (swsi + U.a_prior.values) / (sw + 1)
    same = hid[1:] == hid[:-1]
    U['a_si1'] = np.r_[np.nan, np.where(same, U.SI.values[:-1], np.nan)]
    g = U.groupby(RK)
    U['b_lv'] = g.a_ab.transform(lambda x: x.nlargest(5).mean())
    U['b_lv1'] = np.r_[np.nan, np.where(same, U.b_lv.values[:-1], np.nan)]
    for src, nm in [('a_ab', 'ab'), ('a_si1', 'si')]:
        x = U[src]
        cnt = g[src].transform('count')
        U[f'k_{nm}_rank'] = g[src].rank(ascending=False, method='average') / cnt
        mu = g[src].transform('mean')
        sd = g[src].transform(lambda z: z.std(ddof=0))
        U[f'k_{nm}_z'] = (x - mu) / np.maximum(sd, 1.0)
        U[f'k_{nm}_gap'] = x - g[src].transform('max')
        if nm == 'ab':
            U['k_ab_sd'] = sd
    return U[list(order)].sort_values(RK + ['runner_number']).reset_index(drop=True)


# ================================================================ SI5
def pairs_of(U):
    V = U.sort_values(['hk', 'race_date', 'race_no'], kind='mergesort').reset_index(drop=True)
    dn = (pd.to_datetime(V.race_date) - pd.Timestamp('2000-01-01')).dt.days.to_numpy()
    same = V.hk.to_numpy()[1:] == V.hk.to_numpy()[:-1]
    return V, dn, same & (dn[1:] - dn[:-1] <= 90)


def o_table(U):
    V, dn, ok = pairs_of(U)
    s = V.SI.to_numpy(float)
    P = pd.DataFrame({'s0': s[:-1], 's1': s[1:], 't0': V.track.to_numpy()[:-1], 't1': V.track.to_numpy()[1:],
                      'yl': V.year.to_numpy()[1:]})[ok & ~np.isnan(s[:-1]) & ~np.isnan(s[1:])]
    O, info = {2014: {t: 0.0 for t in NANKAN}}, {}
    for y in [x for x in YRS if x <= U.year.max()]:
        W = P[P.yl.isin(win_of(y))]
        Sm = W[W.t0 == W.t1]
        b, a = np.polyfit(Sm.s0.to_numpy(), Sm.s1.to_numpy(), 1)
        X = W[W.t0 != W.t1]
        e = X.s1 - (a + b * X.s0)
        m = e.groupby([X.t0, X.t1]).median().to_dict()
        n = e.groupby([X.t0, X.t1]).size().to_dict()
        rows, rhs, wts, pr = [], [], [], []
        for A, Bt in itertools.combinations(NANKAN, 2):
            mab, mba = m.get((A, Bt), np.nan), m.get((Bt, A), np.nan)
            nab, nba = int(n.get((A, Bt), 0)), int(n.get((Bt, A), 0))
            use = min(nab, nba) >= 100
            pr.append({'pair': f'{A}-{Bt}', 'n_ab': nab, 'n_ba': nba, 'm_ab': mab, 'm_ba': mba,
                       'm_sum': mab + mba, 'theta': (mba - mab) / 2, 'use': use})
            if use:
                r = np.zeros(4); r[NANKAN.index(Bt)] = 1; r[NANKAN.index(A)] = -1
                rows.append(r); rhs.append((mba - mab) / 2); wts.append(min(nab, nba))
        M = np.array(rows) * np.sqrt(wts)[:, None]
        assert np.linalg.matrix_rank(M) == 3, f'{y}: 使える場の組で 4 場がつながらない'
        sol = np.linalg.lstsq(M, np.array(rhs) * np.sqrt(wts), rcond=None)[0]
        sol = sol - sol.mean()
        O[y] = {t: float(v) for t, v in zip(NANKAN, sol)}
        info[y] = {'a': float(a), 'b': float(b), 'n_same': int(len(Sm)), 'pairs': pr, 'o': O[y]}
    return O, info


def make_si5(U):
    """U = t4_base.build の出力。SI5・a_ab5 などを U の行の順で返す(DataFrame)と記録。"""
    U = U.reset_index(drop=True)
    kmaps = kmaps_of(U)
    O, oinfo = o_table(U)
    dd = U.distance_m.to_numpy(float)
    win_t = U.groupby(RK).time_sec.transform('min').to_numpy(float)
    Tt = np.minimum(U.time_sec.to_numpy(float), win_t + 2.0 * dd / 1000)
    bc = U.bc_T.to_numpy(float)
    B = bc * dd / 1000
    cw = U.carried_weight.to_numpy(float)
    D = U.D_T.to_numpy(float)
    SI = U.SI.to_numpy(float)
    yr = U.year.to_numpy()
    trk = U.track.to_numpy()
    o = np.array([O.get(y, O[2014])[t] if y >= 2015 else 0.0 for y, t in zip(yr, trk)])
    base0 = 80 + (1000 / B) * (B - Tt) + 2 * (cw - 55)
    dnum = (pd.to_datetime(U.race_date) - pd.Timestamp('2000-01-01')).dt.days.to_numpy()
    hk = U.hk.to_numpy()
    k0 = U.k0.to_numpy()
    n = len(U)
    SI5 = np.full(n, np.nan); ab5 = np.full(n, np.nan); sin5 = np.zeros(n)
    rval = np.full(n, np.nan); Dpr = np.full(n, np.nan); Dp = np.full(n, np.nan); D5 = D.copy()
    allh, nnh = {}, {}
    cy = {}
    dtk = U.dtk.to_numpy()
    order = U.sort_values(['race_date', 'track', 'race_no', 'runner_number'], kind='mergesort').index.to_numpy()
    dates = U.race_date.to_numpy()[order]
    cut = np.flatnonzero(np.r_[True, dates[1:] != dates[:-1], True])
    cur_y, prior, allm = None, None, None
    for s0, s1 in zip(cut[:-1], cut[1:]):
        idx = order[s0:s1]
        y = int(yr[idx[0]])
        if y != cur_y:
            cur_y = y
            km = kmaps[y]
            P = np.where(yr == 2014, SI, SI5)
            m = np.isin(yr, win_of(y)) & ~np.isnan(P)
            Wr = pd.DataFrame({'si': P[m], 'k': pd.Series(k0[m]).map(km).to_numpy()})
            means = Wr.si.groupby(Wr.k).mean().to_dict()
            allm = Wr.si.mean()
            prior = (km, means, allm)
            if y >= 2016:
                wy = [x for x in range(y - 3, y) if x >= 2015]
                mm = np.isin(yr, wy) & ~np.isnan(Dpr)
                dd_ = pd.DataFrame({'k': dtk[mm], 'v': Dpr[mm] - D[mm]}).drop_duplicates('k')
                cy[y] = float(dd_.v.median()) if len(dd_) else 0.0
            else:
                cy[y] = 0.0
        km, means, allm = prior
        for i in idx:
            k = k0[i]
            pri = means.get(km.get(k), allm) if k is not None else allm
            L = nnh.get(hk[i], [])
            sw = 0.0; swsi = 0.0
            for j in range(1, 6):
                if len(L) >= j:
                    dj, sj = L[-j]
                    w = 0.5 ** ((dnum[i] - dj) / HALF)
                    sw += w; swsi += w * sj
            ab5[i] = (swsi + pri) / (sw + 1)
            A = allh.get(hk[i], [])
            sin5[i] = sum(1 for v in A[-5:] if v == v)
        if y == 2014:
            SI5[idx] = SI[idx]
        else:
            v = (ab5[idx] - (base0[idx] + o[idx])) * bc[idx] / 1000
            known = (sin5[idx] >= 3) & ~np.isnan(v)
            T = pd.DataFrame({'r': U.race_no.to_numpy()[idx], 'k': dtk[idx], 'v': np.where(known, v, np.nan)})
            g = T.groupby(['k', 'r']).v
            rv = g.transform('median').where(g.transform('count') >= 2)
            rval[idx] = rv.to_numpy()
            R1 = T.assign(rv=rv).drop_duplicates(['k', 'r'])
            h = R1.groupby('k').rv
            dp = (h.median().where(h.count() >= 3)).to_dict()
            dpr = np.array([dp.get(x, np.nan) for x in dtk[idx]])
            Dpr[idx] = dpr
            Dp[idx] = dpr - cy[y]
            D5[idx] = np.where(np.isnan(dpr), D[idx], (D[idx] + Dp[idx]) / 2)
            SI5[idx] = 80 + (1000 / B[idx]) * (B[idx] - Tt[idx] + D5[idx] * dd[idx] / 1000) + 2 * (cw[idx] - 55) + o[idx]
        for i in idx:
            allh.setdefault(hk[i], []).append(SI5[i])
            if SI5[i] == SI5[i]:
                nnh.setdefault(hk[i], []).append((dnum[i], SI5[i]))
    R = pd.DataFrame({'SI5': SI5, 'a_ab5': ab5, 'a_sin5': sin5, 'rval': rval, 'D_proj_raw': Dpr, 'D_proj': Dp,
                      'D5': D5, 'o_s': o}, index=U.index)
    return R, {'o': oinfo, 'c': cy}


def si5():
    U = pd.read_parquet(BASE4)
    R4 = rebuild(U, U.SI)
    bad = {c: int((~eqmask(R4[c], U[c])).sum()) for c in REB}
    same_rows = R4[RK + ['runner_number']].equals(U[RK + ['runner_number']])
    print('rebuild 一致', same_rows, bad, flush=True)
    assert same_rows and not any(bad.values()), '⛔ rebuild(U, 第 4 版の SI) が t4_base と一致しない'
    R, info = make_si5(U)
    U5 = rebuild(U, R.SI5.to_numpy())
    chk_ab = int((~eqmask(U5.a_ab, R.a_ab5)).sum())
    print('a_ab5 と rebuild の a_ab の不一致', chk_ab, flush=True)
    assert chk_ab == 0
    X = U5.copy()
    X['SI4'] = U.SI.to_numpy()
    for c in ['a_ab5', 'a_sin5', 'rval', 'D_proj_raw', 'D_proj', 'D5', 'o_s']:
        X[c] = R[c].to_numpy()
    X.to_parquet(BASE5, index=False)
    # ---- 点検 A
    E = X[X.year >= 2016]
    RR = E[E.rval.notna()].drop_duplicates(RK)
    od = RR[RR.race_no % 2 == 1].groupby('dtk').rval.agg(['median', 'count'])
    ev = RR[RR.race_no % 2 == 0].groupby('dtk').rval.agg(['median', 'count'])
    j = od.join(ev, lsuffix='_o', rsuffix='_e', how='inner')
    j = j[(j.count_o >= 2) & (j.count_e >= 2)]
    cyv = j.index.str[:4].astype(int).map(info['c'])
    c_oe = float(np.corrcoef(j.median_o - cyv, j.median_e - cyv)[0, 1])
    V, dn, ok = pairs_of(X)
    s4, s5 = V.SI4.to_numpy(float), V.SI.to_numpy(float)
    okp = ok & (V.year.to_numpy()[1:] >= 2015) & ~np.isnan(s5[:-1]) & ~np.isnan(s5[1:])
    c5 = float(np.corrcoef(s5[:-1][okp], s5[1:][okp])[0, 1])
    c4 = float(np.corrcoef(s4[:-1][okp], s4[1:][okp])[0, 1])
    lvl = {y: float((X.SI - X.SI4)[X.year == y].median()) for y in YRS}
    nmin = {y: min(min(p['n_ab'], p['n_ba']) for p in info['o'][y]['pairs']) for y in YRS}
    mv = {y: max(abs(info['o'][y]['o'][t] - info['o'][y - 1]['o'][t]) for t in NANKAN) for y in range(2016, 2022)}
    DD = X.drop_duplicates('dtk')
    dshare = {y: float(DD[DD.year == y].D_proj.notna().mean()) for y in YRS}
    checks = [
        {'name': '書き直しの同一性: rebuild(U, 第 4 版の SI) の a_prior〜k_* 13 列', 'value': f'{len(U):,} 行 × 13 列 不一致 0',
         'line': '100% 一致', 'ok': '合'},
        {'name': 'D_proj の再現: 奇数 R/偶数 R の相関(2016〜2021)', 'value': f'{c_oe:.3f}({len(j)} 日×場)', 'line': '≥ 0.6',
         'ok': '合' if c_oe >= 0.6 else '否'},
        {'name': 'SI5 の続き具合: 続けての 2 走(90 日以内・後が 2015〜2021)の相関', 'value': f'SI5 {c5:.4f}・第 4 版の SI {c4:.4f}({int(okp.sum()):,} 組)',
         'line': '≥ 第 4 版 − 0.01', 'ok': '合' if c5 >= c4 - 0.01 else '否'},
        {'name': 'SI5 の水準: 年ごとの (SI5 − SI) の中央値(2015〜2021)', 'value': '・'.join(f'{v:+.3f}' for v in lvl.values()),
         'line': 'すべて ±2 以内', 'ok': '合' if all(abs(v) <= 2 for v in lvl.values()) else '否'},
        {'name': '場のずれの元: 場の組の両向きの組の数の最小(2015〜2021)', 'value': '・'.join(str(v) for v in nmin.values()),
         'line': 'すべて ≥ 100', 'ok': '合' if all(v >= 100 for v in nmin.values()) else '否'},
        {'name': '場のずれの安定: o_s の前年からの動きの最大(2016〜2021)', 'value': '・'.join(f'{v:.3f}' for v in mv.values()),
         'line': 'すべて ≤ 3', 'ok': '合' if all(v <= 3 for v in mv.values()) else '否'},
    ]
    res = {'checks': checks, 'o': {str(k): v for k, v in info['o'].items()}, 'c': {str(k): v for k, v in info['c'].items()},
           'dshare': {str(k): v for k, v in dshare.items()}, 'level': {str(k): v for k, v in lvl.items()},
           'rows': int(len(X))}
    J_SI5.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    for c in checks:
        print(c['name'], c['value'], c['ok'])
    print('c', info['c'], 'dshare', dshare)
    for y in YRS:
        print(y, {t: round(v, 3) for t, v in info['o'][y]['o'].items()},
              [(p['pair'], round(p['m_sum'], 2), p['n_ab'], p['n_ba']) for p in info['o'][y]['pairs']])
    md()


# ================================================================ 材料の表
def load_x3(h, tg):
    X3 = pd.read_parquet(V3 / 'feat_t3_explore.parquet')
    need = set(KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop'] + list(t4_day3.V3MAP.values()))
    if need <= set(X3.columns):
        return X3
    print('X3 を作り直す', flush=True)
    X3, _ = t4_day3.build3(h, tg[tg.race_date >= '2015-01-01'].reset_index(drop=True), tg)
    return t4_day3.finish_table(X3, h, tg)


def feat_table(Ub, h, races, tg, X3):
    tgt = tg[tg.race_date >= '2015-01-01'].reset_index(drop=True)
    T = t4_day3.feat_new(Ub, h, races, tg, tgt)
    T = t4_day3.assemble(T, X3)
    return T[t4_day3.META + t4_day3.ALL].sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)


def colcmp(A, B, cols):
    assert A[KEY + ['umaban']].astype(str).equals(B[KEY + ['umaban']].astype(str))
    return {c: int((~eqmask(A[c], B[c])).sum()) for c in cols}


def table():
    runs, facts, races = t4_day3.raw()
    h = t4_day3.sources_from(runs, facts, races)
    tg = t4_day3.targets3(h)
    X3 = load_x3(h, tg)
    U = pd.read_parquet(BASE4)
    F4 = pd.read_parquet(FEAT4).sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    PRE, ALL = t4_day3.PRE_ALL, t4_day3.ALL
    T0 = feat_table(rebuild(U, U.SI), h, races, tg, X3)
    b0 = colcmp(T0, F4, ALL + ['n', 'Y1', 'Y3'])
    print('93 列の表の一致(不一致の数)', sum(b0.values()), flush=True)
    assert not any(b0.values()), f'⛔ 表が feat_t4_explore と一致しない {b0}'
    si = U.SI.to_numpy(float)
    rng = np.random.default_rng(0)
    Tn = feat_table(rebuild(U, si + rng.normal(0, 0.1, len(si))), h, races, tg, X3)
    bn = colcmp(Tn, F4, PRE)
    rep = [c for c in PRE if bn[c] > 0]
    print('置き換わる列', len(rep), rep, flush=True)
    U5 = pd.read_parquet(BASE5)[U.columns]
    T5 = feat_table(U5, h, races, tg, X3)
    b5 = colcmp(T5, F4, ALL + ['n', 'Y1', 'Y3'])
    rest_bad = {c: v for c, v in b5.items() if c not in rep and v}
    print('残りの列の不一致', rest_bad, flush=True)
    assert not rest_bad, '⛔ 置き換わらない列が feat_t4_explore と一致しない'
    T5.to_parquet(FEAT5, index=False)
    J_COLS.write_text(json.dumps({'replaced': rep, 'noise_changed': {c: bn[c] for c in rep},
                                  'si5_changed': {c: b5[c] for c in rep}, 'rows': int(len(T5))},
                                 ensure_ascii=False, indent=1), encoding='utf-8')
    md()


# ================================================================ leak
def leak():
    runs, races = t4_base.load()
    full = pd.read_parquet(BASE5)
    days = t4_base.pick_days(races)
    per, tot = [], [0, 0]
    for X in days:
        r = runs[runs.race_date <= X].copy()
        m = r.race_date == X
        r.loc[m, t4_base.RES_RUN] = np.nan
        r.loc[m & ~r.finish_note.isin(['取消', '除外']), 'finish_note'] = np.nan
        c = races[races.race_date <= X].copy()
        c.loc[c.race_date == X, t4_base.RES_RACE] = np.nan
        Ub = t4_base.build(r.reset_index(drop=True), c.reset_index(drop=True), log=lambda *a: None)
        R, _ = make_si5(Ub)
        U5 = rebuild(Ub, R.SI5.to_numpy())
        U5['a_ab5'], U5['a_sin5'] = R.a_ab5.to_numpy(), R.a_sin5.to_numpy()
        a = U5[U5.race_date == X].set_index(RK + ['runner_number'])[LEAK5].sort_index()
        b = full[full.race_date == X].set_index(RK + ['runner_number'])[LEAK5].sort_index()
        assert a.index.equals(b.index), X
        eq = eqmask(a.to_numpy(float), b.to_numpy(float))
        bad = [cc for cc, okc in zip(LEAK5, eq.all(0)) if not okc]
        per.append({'date': X, 'rows': int(len(a)), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad_cols': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        print(X, len(a), int(eq.sum()), eq.size, bad, flush=True)
    z = {'days': len(days), 'jan_days': sum(p['date'][5:7] == '01' for p in per),
         'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0], 'cells': tot[1],
         'cols': LEAK5, 'per_day': per}
    J_LEAK.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding='utf-8')
    print('一致', z['match_days'], '/', z['days'], '日', tot[0], '/', tot[1])
    md()


# ================================================================ fit
def load_feat(p):
    df = pd.read_parquet(p).sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    assert df.race_date.max() < '2022-01-01'
    df['z1'], df['z3'] = t4_day3.logit(1 / df.n), t4_day3.logit(3 / df.n)
    return df


def fit():
    rep = json.loads(J_COLS.read_text(encoding='utf-8'))['replaced']
    assert REPLACED is not None and list(REPLACED) == rep, '台本の頭の置き換わる列が table の結果と違う'
    t4_day3.CACHE = V3 / 't5_cache'
    cols, cfg = t4_day3.PRE_ALL, t4_day3.STAGE_CFG
    d4 = load_feat(FEAT4)
    te4 = t4_day3.test_frame(d4)
    m4 = t4_day3.metrics(te4, *t4_day3.finish(te4, t4_day3.fit_pred(d4, cols, 'Y1', cfg, 't5_v4st5'),
                                              t4_day3.fit_pred(d4, cols, 'Y3', cfg, 't5_v4st5')))
    rep_ok = (f"{m4['win']:.3f}" == '0.343' and f"{m4['top3']:.4f}" == '0.6602' and f"{m4['LL3']:.5f}" == '-5.40946')
    old = json.loads(t4_day3.RES.read_text(encoding='utf-8'))['stages']['rows'][5]
    exact = {k: m4[k] - old[k] for k in ('win', 'top3', 'LL1', 'LL3')}
    print('段 5 の再現', rep_ok, m4['win'], m4['top3'], m4['LL3'], '差', exact, flush=True)
    out = {'v4': m4, 'repro': rep_ok, 'repro_diff': exact}
    if not rep_ok:
        J_FIT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
        md()
        raise SystemExit('⛔ 第 4 版の段 5 が再現しない')
    d5 = load_feat(FEAT5)
    te5 = t4_day3.test_frame(d5)
    assert te5[KEY + ['umaban', 'n', 'Y1', 'Y3']].astype(str).equals(te4[KEY + ['umaban', 'n', 'Y1', 'Y3']].astype(str))
    m5 = t4_day3.metrics(te5, *t4_day3.finish(te5, t4_day3.fit_pred(d5, cols, 'Y1', cfg, 't5_A'),
                                              t4_day3.fit_pred(d5, cols, 'Y3', cfg, 't5_A')))
    d3, d1, dt = m5['LL3'] - m4['LL3'], m5['LL1'] - m4['LL1'], m5['top3'] - m4['top3']
    keep = bool(d3 > 0 and m5['top3'] >= m4['top3'] - 0.005)
    out.update({'A': m5, 'dLL3': d3, 'dLL1': d1, 'dtop3': dt, 'dwin': m5['win'] - m4['win'], 'keep': keep,
                'SI_star': 'SI5' if keep else '第 4 版の SI'})
    J_FIT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('段 A ΔLL3', d3, 'ΔLL1', d1, '◎ 3 着以内率', m5['top3'], '差', dt, '◎ 勝率', m5['win'], '残す', keep)
    md()


# ================================================================ md
def md():
    L = ['# 第 5 版 2 日目: 段 A(物差しの合わせ直し SI5)の部品の点検・リーク検査・当てはめ外(PREREG5 §4-1・§5・§10・§11)', '',
         '台本 src/t5_base.py(si5・table・leak・fit)。決め書に無い細部 14 個と置き換わる列は台本の頭。'
         '出力 v3/t5_base_si5_2014_2021.parquet・v3/feat_t5a_explore.parquet。', '']
    if J_SI5.exists():
        s = json.loads(J_SI5.read_text(encoding='utf-8'))
        L += ['## 部品の点検 A(線は結果を見る前に決めた)', '', '| 点検 | 値 | 線 | 合否 |', '|---|---|---|---|']
        L += [f"| {c['name']} | {c['value']} | {c['line']} | {c['ok']} |" for c in s['checks']]
        L += ['', '## 年ごとの記録', '',
              '| 年 | o_s 浦和 | 船橋 | 大井 | 川崎 | c\'_y | D_proj の作れた日×場の割合 | SI5 − SI の中央値 |',
              '|---|---|---|---|---|---|---|---|']
        for y in map(str, YRS):
            o = s['o'][y]['o']
            L.append(f"| {y} | {o['浦和']:+.3f} | {o['船橋']:+.3f} | {o['大井']:+.3f} | {o['川崎']:+.3f} | "
                     f"{s['c'][y]:+.4f} | {s['dshare'][y]:.3f} | {s['level'][y]:+.3f} |")
        L += ['', '場の組ごとの m_AB + m_BA(純粋な物差しのずれなら 0)と組の数 n_AB/n_BA:', '',
              '| 年 | ' + ' | '.join(p['pair'] for p in s['o']['2015']['pairs']) + ' |', '|---' * 7 + '|']
        for y in map(str, YRS):
            L.append(f'| {y} | ' + ' | '.join(f"{p['m_sum']:+.2f}({p['n_ab']}/{p['n_ba']})"
                                              for p in s['o'][y]['pairs']) + ' |')
        L.append('')
    if J_COLS.exists():
        c = json.loads(J_COLS.read_text(encoding='utf-8'))
        L += ['## 置き換えた 93 列の表', '',
              f"rebuild(U, 第 4 版の SI) → feat_new・assemble の表は feat_t4_explore と 96 列すべて一致。"
              f"置き換わる列(乱数で機械的に決めた){len(c['replaced'])} 個: {'・'.join(c['replaced'])}。"
              f"残りの列は feat_t4_explore と 100% 一致(assert)。行 {c['rows']:,}。", '']
    if J_LEAK.exists():
        z = json.loads(J_LEAK.read_text(encoding='utf-8'))
        L += ['## リーク検査 A(§10: 20 日・seed 0・うち 1 月 ' + str(z['jan_days']) + ' 日)', '',
              f"比べた列 {len(z['cols'])} 個({'・'.join(z['cols'])})", '',
              f"一致 {z['match_days']}/{z['days']} 日・値 {z['match']:,}/{z['cells']:,}", '',
              '| 日 | 行 | 一致しない列 |', '|---|---|---|']
        L += [f"| {p['date']} | {p['rows']} | {'・'.join(p['bad_cols']) or 'なし'} |" for p in z['per_day']]
        L.append('')
    if J_FIT.exists():
        f = json.loads(J_FIT.read_text(encoding='utf-8'))
        v4 = f['v4']
        L += ['## 段 A の当てはめ外(拡張窓 2016〜2021・葉 15・最小 500・木 800)', '',
              f"第 4 版の段 5 の再現: ◎ 勝率 {v4['win']:.3f}・◎ 3 着以内率 {v4['top3']:.4f}・対数尤度 Y3 {v4['LL3']:.5f} → "
              f"{'out/t4_day3.md と一致' if f['repro'] else '一致しない(止めた)'}(保存値との差 "
              + '・'.join(f'{k} {v:+.2e}' for k, v in f['repro_diff'].items()) + ')', '']
        if 'A' in f:
            A = f['A']
            L += ['| 形 | ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1 | 対数尤度 Y3 | 年ごとの ◎ 3 着以内率 |', '|---|---|---|---|---|---|']
            for nm, m in (('第 4 版の 93 列(段 A の前)', v4), ('段 A(SI5 の 93 列)', A)):
                L.append(f"| {nm} | {m['win']:.4f} | {m['top3']:.4f} | {m['LL1']:.5f} | {m['LL3']:.5f} | "
                         + '・'.join(f"{m[f'top3_{y}']:.3f}" for y in t4_day3.YEARS) + ' |')
            L += ['', f"ΔLL(Y3){f['dLL3']:+.5f}・ΔLL(Y1){f['dLL1']:+.5f}・◎ 3 着以内率の差 {f['dtop3']*100:+.2f} ポイント・"
                  f"◎ 勝率の差 {f['dwin']*100:+.2f} ポイント", '',
                  f"採否: (i) ΔLL(Y3) > 0 {'○' if f['dLL3'] > 0 else '×'}・(ii) ◎ 3 着以内率が 0.5 ポイント以上下がらない "
                  f"{'○' if f['dtop3'] >= -0.005 else '×'} → 段 A を{'残す' if f['keep'] else '残さない'}。SI* = {f['SI_star']}。"
                  '(この決まりは ◎ を最大 0.49 ポイント下げる段を残しうる。第 4 版の段 5 は ΔLL +0.00043・◎ −0.26 で残った)', '']
    MD.write_text('\n'.join(L), encoding='utf-8')


if __name__ == '__main__':
    {'si5': si5, 'table': table, 'leak': leak, 'fit': fit, 'md': md}[sys.argv[1]]()
