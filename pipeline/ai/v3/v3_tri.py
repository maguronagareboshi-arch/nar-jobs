# -*- coding: utf-8 -*-
"""南関 AI v3 の 3 連単・3 連複のずれ模型(記録だけ・買わない・ユーザー 2026-10-02「記録には残してほしい」)。

学習はしない。研究 nankan-ai-v3 で学んだ模型を読むだけ:
  3 連単 = d1b(src/f5_scripts/d1_tri_gap.py late・材料の作りは d3_sept_tri.race と同じ)
  3 連複 = c8 (src/f5_scripts/c8_trio_cross.py・材料の作りは c10_sept.race_feats と同じ)
土台 = その時の市場の率(組のオッズの逆数を合計 1)。模型はずれだけを足す。期待値 = 模型の率 × その時のオッズ。
組の率 gd/g/ai は研究の t10_bets(disc・match3)と同じ式を numpy だけで書き直したもの(scipy を使わない)。
"""
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

TRI_FILE, TRIO_FILE = 'd1b_tri_model.txt', 'c8_trio_model.txt'
A_, B_ = 0.8, 0.65  # 割り引き型(t10_bets と同じ)
EV_MIN = 1.0        # 期待値 1.0 以上の組を全部残す(線 1.1/1.2/1.3・オッズの帯は後で数え直す)
KINDS = ('sanrentan', 'sanrenpuku', 'umatan', 'umaren', 'wide')


def load(mdir):
    """模型 2 本。片方でも無ければ None = 3 連単・3 連複は記録しない(単勝の候補はそのまま)。"""
    p, q = Path(mdir) / TRI_FILE, Path(mdir) / TRIO_FILE
    if not (p.exists() and q.exists()):
        return None
    import lightgbm as lgb
    return lgb.Booster(model_str=p.read_text(encoding='utf-8')), lgb.Booster(model_str=q.read_text(encoding='utf-8'))


# ---------------------------------------------------------------- 組の率(t10_bets と同じ式)
_M = {}


def _mats(n):
    if n not in _M:
        T = np.array(list(itertools.permutations(range(n), 3)))
        trios = list(itertools.combinations(range(n), 3))
        ti = {c: x for x, c in enumerate(trios)}
        to3 = np.array([ti[tuple(sorted(t))] for t in T])
        _M[n] = (T, np.array(trios), to3)
    return _M[n]


def _disc(p, T):
    pa, pb = p ** A_, p ** B_
    sa, sb = pa.sum(), pb.sum()
    i, j, k = T[:, 0], T[:, 1], T[:, 2]
    return p[i] * pa[j] / (sa - pa[i]) * pb[k] / (sb - pb[i] - pb[j])


def _pl(p1, s, T):
    i, j, k = T[:, 0], T[:, 1], T[:, 2]
    return p1[i] * s[j] / (1 - s[i]) * s[k] / (1 - s[i] - s[j])


def _match3(p1, t, T, iters=1500, tol=1e-5):
    n = len(p1)
    g = np.clip(np.asarray(t, float) - p1, 1e-5, None)
    g = g * (2 / g.sum())
    s = g / 2
    for _ in range(iters):
        pr = _pl(p1, s, T)
        h = np.bincount(T[:, 1], pr, n) + np.bincount(T[:, 2], pr, n)
        if np.abs(h - g).max() < tol:
            break
        s = s * (g / np.maximum(h, 1e-15))
        s = s / s.sum()
    return pr


def _rows(rows, m, ordered):
    """REST の combos([a,b,(c,)オッズ,…])→ {'a-b(-c)': オッズ}。ordered=False は馬番を小さい順に。"""
    d = {}
    for c in rows or []:
        try:
            u = [int(v) for v in c[:m]]
            o = float(c[m]) if c[m] not in (None, '') else None
        except (TypeError, ValueError, IndexError):
            continue
        if not ordered:
            u = sorted(u)
        d['-'.join(map(str, u))] = o
    return d


def _mk(d):
    """{組: オッズ} → {組: 市場の率}(オッズ > 0 の組で合計 1)。"""
    x = {k: 1 / v for k, v in d.items() if v is not None and v > 0}
    s = sum(x.values())
    return {k: v / s for k, v in x.items()} if s > 0 else {}


def _logit(p, eps):
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


# ---------------------------------------------------------------- 1 レース
def race(h, combos, models):
    """h = 1 レースの馬(オッズのある馬)の表: umaban・win(単勝)・pg1(v31 の勝つ率)・p1(第10版)・p3p_base(前日の表の 3 着内・そろえ直す前)。
    combos = {券種: REST の combos}。→ {'tri': [...], 'trio': [...]}(期待値 ≥ EV_MIN・期待値の大きい順)か None。"""
    h = h[(h.win > 0) & h.pg1.notna()].sort_values('umaban')
    n = len(h)
    if n < 4:
        return None
    um = h.umaban.to_numpy().astype(int)
    T, TRIOS, to3 = _mats(n)
    w = h.win.to_numpy(float)
    q = (1 / w) / (1 / w).sum()
    pg1 = h.pg1.to_numpy(float)
    pg1 = pg1 / pg1.sum()
    p1 = h.p1.to_numpy(float)
    p1 = p1 / p1.sum()
    p3 = h.p3p_base.to_numpy(float)
    rk = h.p3p_base.rank(ascending=False, method='first').to_numpy()
    gd = _disc(pg1, T)
    ai = _match3(p1, p3, T)
    D = {k: _rows(combos.get(k), 3 if k.startswith('sanren') else 2, k in ('sanrentan', 'umatan')) for k in KINDS}
    m3 = _mk(D['sanrenpuku'])
    mu, mw = _mk(D['umaren']), _mk(D['wide'])
    out = {}
    m_tri, m_trio = models
    if D['sanrentan']:
        out['tri'] = _tri(um, T, q, pg1, p1, p3, rk, gd, _match3(pg1, p3, T), ai, D, m3, mu, mw, m_tri)
    if m3:
        out['trio'] = _trio(um, T, TRIOS, to3, q, pg1, p1, p3, rk, gd, ai, D, mu, mw, m_trio)
    return out or None


def _tri(um, T, q, pg1, p1, p3, rk, gd, g, ai, D, m3, mu, mw, mdl):
    """3 連単(d3_sept_tri.race と同じ材料)。"""
    keys = np.array(['-'.join(map(str, um[t])) for t in T])
    odds = np.array([D['sanrentan'].get(k) or 0.0 for k in keys], float)
    ok = odds > 0
    if not ok.any():
        return []
    I, J, K = T[ok, 0], T[ok, 1], T[ok, 2]
    o, keys = odds[ok], keys[ok]
    m = (1 / o) / (1 / o).sum()
    mex = _mk(D['umatan'])
    mp3 = {}
    for kk, v in m3.items():
        for u in kk.split('-'):
            mp3[int(u)] = mp3.get(int(u), 0) + v
    A, Bh, Ch = um[I], um[J], um[K]

    def s2(a, b):
        return [f'{min(u, v)}-{max(u, v)}' for u, v in zip(a, b)]
    s3 = ['-'.join(map(str, sorted(t))) for t in zip(A, Bh, Ch)]
    X = {'lm': np.log(m), 'n': np.full(len(m), float(len(m)))}
    for nm, v in (('gd', gd), ('g', g), ('ai', ai)):
        X[f'g_{nm}'] = np.log(np.clip(v[ok], 1e-12, None) / m)
    with np.errstate(divide='ignore', invalid='ignore'):
        X['g_tr'] = np.log(np.array([m3.get(s, np.nan) for s in s3]) / m)
        X['l_ex'] = np.log(np.array([mex.get(f'{a}-{b}', np.nan) for a, b in zip(A, Bh)]))
        X['l_u'] = np.log(np.array([mu.get(s, np.nan) for s in s2(A, Bh)]))
        for (P, Q), nm in (((A, Bh), 'w12'), ((A, Ch), 'w13'), ((Bh, Ch), 'w23')):
            X[f'l_{nm}'] = np.log(np.array([mw.get(s, np.nan) for s in s2(P, Q)]))
        for j, ix in enumerate((I, J, K)):
            X[f'lq_{j + 1}'] = np.log(q[ix])
            X[f'gap_{j + 1}'] = np.log(pg1[ix] / q[ix])
            X[f'ai1_{j + 1}'] = np.log(np.clip(p1[ix], 1e-6, None) / q[ix])
            X[f'g3_{j + 1}'] = np.log(np.clip(p3[ix], 1e-6, None) / np.clip(np.array([mp3.get(int(u), np.nan) for u in um[ix]]), 1e-6, None))
            X[f'rk_{j + 1}'] = rk[ix]
    X = pd.DataFrame(X)[mdl.feature_name()].astype(np.float32)
    p = 1 / (1 + np.exp(-(_logit(m, 1e-9) + mdl.predict(X, raw_score=True))))
    p = p / p.sum()
    return _keep(keys, o, p, m)


def _trio(um, T, TRIOS, to3, q, pg1, p1, p3, rk, gd, ai, D, mu, mw, mdl):
    """3 連複(c10_sept.race_feats と同じ材料)。"""
    nt = len(TRIOS)
    gd3 = np.bincount(to3, gd, nt)
    qd3 = np.bincount(to3, _disc(q, T), nt)
    ai3 = np.bincount(to3, ai, nt)
    codes = np.sort(um[TRIOS], 1)
    keys = np.array(['-'.join(map(str, c)) for c in codes])
    odds = np.array([D['sanrenpuku'].get(k) or 0.0 for k in keys], float)
    ok = odds > 0
    if not ok.any():
        return []
    U, o, keys = codes[ok], odds[ok], keys[ok]
    gd3, qd3, ai3 = gd3[ok], qd3[ok], ai3[ok]
    m = (1 / o) / (1 / o).sum()
    mp3 = pd.Series(np.tile(m, 3), index=U.T.ravel()).groupby(level=0).sum()
    hq = pd.DataFrame({'q': q, 'pg1': pg1, 'p3p': p3, 'rk': rk}, index=um)
    hq['mp3'] = mp3.reindex(hq.index)
    X = pd.DataFrame({'lm': np.log(m), 'g_gd': np.log(np.clip(gd3, 1e-9, None) / m),
                      'g_ai': np.log(np.clip(ai3, 1e-9, None) / m), 'n': float(len(m))})
    Q = hq.q.reindex(U.ravel()).to_numpy().reshape(-1, 3)
    US = np.take_along_axis(U, np.argsort(-Q, 1), 1)
    for j, nm in enumerate('abc'):
        r = hq.reindex(US[:, j])
        X[f'lq_{nm}'] = np.log(r.q.to_numpy())
        X[f'gap_{nm}'] = np.log(r.pg1.to_numpy() / r.q.to_numpy())
        X[f'g3_{nm}'] = np.log(np.clip(r.p3p.to_numpy(), 1e-6, None) / np.clip(r.mp3.to_numpy(), 1e-6, None))
        X[f'rk_{nm}'] = r.rk.to_numpy()
    X['g_qd'] = np.log(np.clip(qd3, 1e-9, None) / m)
    with np.errstate(divide='ignore', invalid='ignore'):
        for nm, kind in (('u', mu), ('w', mw)):
            L = np.stack([np.log([kind.get(f'{min(x, y)}-{max(x, y)}', np.nan) for x, y in zip(U[:, i], U[:, j])])
                          for i, j in ((0, 1), (0, 2), (1, 2))], 1)
            s = L.sum(1)
            X[f'ls_{nm}'] = s
            X[f'lmin_{nm}'] = L.min(1)
            e = np.exp(s - np.nanmax(s)) if np.isfinite(s).any() else np.zeros(len(s))
            e = np.where(np.isfinite(e), e, 0)
            X[f'g_p{nm}'] = np.log(np.clip(e / max(e.sum(), 1e-300), 1e-12, None) / m)
    X = X[mdl.feature_name()].astype(np.float32)
    p = 1 / (1 + np.exp(-(_logit(m, 1e-7) + mdl.predict(X, raw_score=True))))
    p = p / p.sum()
    return _keep(keys, o, p, m)


def _keep(keys, odds, p, m):
    """期待値 ≥ EV_MIN の組 → [[組, オッズ, 期待値, 模型の率, 市場の率], …](期待値の大きい順)。"""
    ev = p * odds
    ix = np.flatnonzero(ev >= EV_MIN)
    ix = ix[np.argsort(-ev[ix], kind='mergesort')]
    return [[str(keys[i]), float(odds[i]), round(float(ev[i]), 3), float(f'{p[i]:.4g}'), float(f'{m[i]:.4g}')] for i in ix]
