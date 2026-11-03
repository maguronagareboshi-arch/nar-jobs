# -*- coding: utf-8 -*-
"""第12版 = 第11版 + 束 f10k(材料 1 万個のふるいで残った 60 列の木 1 本)の前日版。研究 nankan-ai-v3 の f10k
(判定 通った 2026-10-11・本番入れ ユーザー承認 2026-10-11)。木は研究 src/f5_scripts/f10k_prod_fit.py で 2023-01〜2026-08 に学んだもの。

足し方(研究 f10k_judge と同じ): p3 = p3prime(max(sig(logit(p3′) + 木の値), p1))・p1 は変えない・4 頭以上のレースだけ。
  p3′ = 束 t14 を足した後の前日の表の値(第11版)。束 t14 が足せなかった日は足さない(木は第11版の上で学んだため)。
60 列(どれもその日より前の走りと、その日の出馬表で分かる値だけ。研究 src/f5_scripts/f10k_gen.py・f10k_fable.py と同じ作り):
  h|絞り|元|型 = 馬の過去の走り(絞り = 今日と同じ場・距離・距離帯・コース・騎手・組・季節・枠帯)の 1〜10 走・全走の平均/最高/最低/ばらつき。
     元 = 上がり指数 up_i・前半指数 ten_i・SI・SI のレース内順位・上がり3F・勝ち馬との時計差(1000m あたり)・馬体重・頭数・格 b_lv。
  e|人|絞り|日|率 = 騎手・調教師のその日より前の 365/1095 日の 3 着内率など(縮めた率)。
  x|A*B = A と B のレース内順位(−0.5)の積。f53 = 今日の相手の牡(セン含む)の割合 − 前走のレースの割合。
  #rk = その日のレースの中の順位(0〜1)・#raw = 値そのまま。
元: 土台 U(t4_open.base_of・南関 2014〜)+ 便の走り h(騎手・調教師・馬体重・枠・性・生年月日は研究と同じく 2020-01〜だけ・名前は NFKC)。
⛔DB には書かない(読むだけ)。

  python -X utf8 pipeline/ai/v3/f10k_bundle.py check DAY [DAY ...]   # 手元: 研究の材料(v3/f10k_pass.parquet)と照合
"""
import json
import os
import sys
import unicodedata
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ASSET = Path(os.environ.get('V3_F10K', 'C:/Users/kouki/nankan_ai/v3/f10k_prod'))
NK = ['浦和', '船橋', '大井', '川崎']
KEY = ['track', 'race_date', 'race_no']
Q4 = KEY + ['umaban']
STAMP = '束 f10k(材料 1 万個のふるいの 60 列の木・学び 2023-01〜2026-08)'
LAGS = 10
WIN = {'l1': (1, 'v'), 'm2': (2, 'mean'), 'm3': (3, 'mean'), 'x3': (3, 'max'), 'n3': (3, 'min'), 'm5': (5, 'mean'), 'x5': (5, 'max'),
       'n5': (5, 'min'), 's5': (5, 'std'), 'm10': (10, 'mean'), 'x10': (10, 'max'), 'n10': (10, 'min'), 's10': (10, 'std')}
# 見張りの線(その日の南関の出走馬のうち値のある割合。研究の確かめの期間はどれも 0.66 以上)
WATCH = {'h|distance_m|up_i|x5#raw': 0.40, 'h|none|body_weight|x10#rk': 0.50, 'e|trainer|track|1095|lift#raw': 0.80}
LASTF = {}  # 日 → その日の 60 列(決め 49 の F3 が読む)
DB0 = '2020-01-01'


def log0(*a):
    print('[f10k]', *a, flush=True)


def _dn(s):
    return ((pd.to_datetime(pd.Series(s).astype(str).str[:10]) - pd.Timestamp('2010-01-01')).dt.days).to_numpy(np.int64)


def _nfkc(x):
    return unicodedata.normalize('NFKC', x).replace(' ', '').replace('\u3000', '') if isinstance(x, str) else x


def cols():
    return json.loads((ASSET / 'f10k_bundle.json').read_text(encoding='utf-8'))['cols']


# ================================================================ 元の走り(研究 f10k_gen.load_runs と同じ作り)
def runs(h, U, day):
    b = U[U.track.isin(NK)][['track', 'race_date', 'race_no', 'runner_number', 'horse_key', 'distance_m', 'carried_weight', 'finish',
                              'time_sec', 'last3f', 'b_g', 'b_lv', 'k0', 'course', 'SI', 'ten_i', 'up_i']].rename(columns={'runner_number': 'umaban'})
    b = b.assign(race_date=b.race_date.astype(str).str[:10], race_no=b.race_no.astype(int), umaban=b.umaban.astype(int))
    b = b[b.race_date <= day].copy()
    for c in ('finish', 'time_sec', 'last3f', 'SI', 'ten_i', 'up_i'):  # その日の結果は使わない(出馬表だけの扱い)
        b[c] = pd.to_numeric(b[c], errors='coerce')
        b.loc[b.race_date == day, c] = np.nan
    d = h[h.track.isin(NK)][['track', 'race_date', 'race_no', 'umaban', 'gate', 'jockey', 'trainer', 'body_weight', 'birth_date', 'sex']].copy()
    d = d.assign(race_date=d.race_date.astype(str).str[:10], race_no=d.race_no.astype(int), umaban=d.umaban.astype(int))
    d = d[(d.race_date >= DB0) & (d.race_date <= day)].drop_duplicates(Q4)
    for c in ('jockey', 'trainer'):
        d[c] = d[c].map(_nfkc)
    d.loc[d.race_date == day, 'body_weight'] = np.nan  # 当日の馬体重は前日には無い
    d['body_weight'] = pd.to_numeric(d.body_weight, errors='coerce')
    d['gate'] = pd.to_numeric(d.gate, errors='coerce')
    d['birth_date'] = d.birth_date.astype(str).str[:10].where(d.birth_date.notna())
    R = b.merge(d, on=Q4, how='left', validate='1:1')
    R['rid'] = R.track + '|' + R.race_date + '|' + R.race_no.astype(str)
    R['day'] = _dn(R.race_date)
    g = R.groupby('rid')
    R['nfield'] = g.umaban.transform('size').astype(float)
    R['fin_r'] = (R.finish - 1) / (R.nfield - 1).clip(lower=1)
    R['top3'] = (R.finish <= 3).astype(float).where(R.finish.notna())
    R['tdiff_k'] = (R.time_sec - g.time_sec.transform('min')) / R.distance_m * 1000
    R['si_rk'] = g.SI.rank(pct=True, ascending=False)
    R['dband'] = pd.cut(R.distance_m, [0, 1200, 1500, 1800, 9999], labels=False).astype(float)
    R['season'] = ((pd.to_datetime(R.race_date).dt.month % 12) // 3).astype(float)
    R['gband'] = (R.gate >= 5).astype(float).where(R.gate.notna())
    male = R.sex.isin(['牡', 'セ']).astype(float).where(R.sex.notna())
    R['msh'] = male.groupby(R.rid).transform('mean')
    R = R.sort_values(['horse_key', 'day', 'race_no']).reset_index(drop=True)
    return R


def _gstart(kc, bad):
    n = len(kc)
    pos = np.arange(n)
    new = np.r_[True, kc[1:] != kc[:-1]]
    gs = np.maximum.accumulate(np.where(new, pos, 0))
    return np.where(bad, pos, gs), pos


def hist(R, filt, need):
    """need = {(atom, win)}。→ {f'h|{filt}|{atom}|{win}': R の順の値}(研究 f10k_gen.hist_block と同じ)。"""
    atoms = sorted({a for a, _ in need})
    key = R.horse_key.astype(str) + '#' + (R[filt].astype(str) if filt != 'none' else '')
    bad = R[filt].isna().to_numpy() if filt != 'none' else np.zeros(len(R), bool)
    order = np.lexsort((R.race_no.to_numpy(), R.day.to_numpy(), pd.factorize(key)[0]))
    kc = pd.factorize(key)[0][order]
    gstart, pos = _gstart(kc, bad[order])
    A = R[atoms].to_numpy(np.float32)[order]
    L = np.full((LAGS, len(R), len(atoms)), np.nan, np.float32)
    for l in range(1, LAGS + 1):
        ok = (pos - l) >= gstart
        L[l - 1, ok] = A[(pos - l)[ok]]
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for a, w in need:
            j = atoms.index(a)
            if w == 'all':
                v = np.nan_to_num(A[:, j]).astype(np.float64)
                c = (~np.isnan(A[:, j])).astype(np.float64)
                cs, cc = np.cumsum(v), np.cumsum(c)
                prev, base = pos - 1, gstart - 1
                okp = prev >= gstart
                ts = np.where(okp, cs[np.maximum(prev, 0)] - np.where(base >= 0, cs[np.maximum(base, 0)], 0), np.nan)
                tc = np.where(okp, cc[np.maximum(prev, 0)] - np.where(base >= 0, cc[np.maximum(base, 0)], 0), np.nan)
                M = (ts / np.where(tc > 0, tc, np.nan)).astype(np.float32)
            else:
                k, how = WIN[w]
                S = L[:k, :, j]
                M = {'v': lambda: S[0], 'mean': lambda: np.nanmean(S, 0), 'max': lambda: np.nanmax(S, 0), 'min': lambda: np.nanmin(S, 0),
                     'std': lambda: np.nanstd(S, 0, ddof=1)}[how]()
            inv = np.empty(len(R), np.int64)
            inv[order] = pos
            out[f'h|{filt}|{a}|{w}'] = np.asarray(M, np.float32)[inv]
    return out


def ent(R, need, qmask):
    """need = {(ent, filt, W, stat)}。qmask = 値が要る行(その日の行)。研究 f10k_gen.ent_block と同じ(その日より前の日だけ)。"""
    h5 = hist(R, 'none', {('top3', 'm5')})['h|none|top3|m5']
    R = R.assign(lift=R.top3 - h5, ok=R.finish.notna().astype(float))
    out = {}
    for e, filt, W, stat in sorted(need):
        key = R[e].astype(str) + '#' + (R[filt].astype(str) if filt != 'none' else '')
        valid = R[e].notna() & (R[filt].notna() if filt != 'none' else pd.Series(True, index=R.index))
        D = pd.DataFrame({'key': key[valid], 'day': R.day[valid], 'n': R.ok[valid], 't3': R.top3[valid].fillna(0), 'fr': R.fin_r[valid].fillna(0),
                          'lf': R.lift[valid].fillna(0), 'nl': R.lift[valid].notna().astype(float)})
        D = D.groupby(['key', 'day'], sort=True).sum().reset_index()
        kc, ku = pd.factorize(D.key, sort=True)
        comb = kc.astype(np.int64) * 100000 + D.day.to_numpy()
        C = {c: np.r_[0.0, np.cumsum(D[c].to_numpy())] for c in ('n', 't3', 'fr', 'lf', 'nl')}
        qk = pd.Index(ku).get_indexer(key[qmask])
        qd = R.day.to_numpy()[qmask]
        hi = np.searchsorted(comb, qk * 100000 + qd, 'left')
        lo = np.searchsorted(comb, qk * 100000 + qd - W, 'left')
        s = {c: C[c][hi] - C[c][lo] for c in C}
        n = np.where((qk < 0) | ~valid.to_numpy()[qmask], np.nan, s['n'])
        v = {'t3': (s['t3'] + 2.5) / (n + 10), 'fr': (s['fr'] + 5) / (n + 10), 'lift': s['lf'] / (s['nl'] + 10)}[stat]
        full = np.full(len(R), np.nan)
        full[qmask] = v
        out[f'e|{e}|{filt}|{W}|{stat}'] = full
    return out


def feats(day, h, U, log=log0):
    """→ その日の南関の出走馬 1 頭 1 行: Q4 + 60 列。"""
    C = cols()
    R = runs(h, U, day)
    today = R.race_date.to_numpy() == day
    if not today.any():
        raise RuntimeError('その日の南関の出走馬が土台 U に無い')
    hs = set(R.horse_key[today])
    keep = R.horse_key.isin(hs).to_numpy()
    Rh = R[keep].reset_index(drop=True)  # その日に走る馬の過去だけ(レースの中の値は全頭で作った後)
    base = {}
    hneed, eneed = {}, set()

    def want(nm):
        p = nm.split('|')
        if p[0] == 'h':
            hneed.setdefault(p[1], set()).add((p[2], p[3]))
        elif p[0] == 'e':
            eneed.add((p[1], p[2], int(p[3]), p[4]))
    for c in C:
        nm = c.split('#')[0]
        if nm.startswith('x|'):
            for part in nm[2:].split('*'):
                want(part)
        else:
            want(nm)
    for filt, need in hneed.items():
        for k, v in hist(Rh, filt, need).items():
            base[k] = v
    tmask_h = Rh.race_date.to_numpy() == day
    for k, v in ent(R, eneed, today).items():
        base[k] = v[keep]
    same = Rh.horse_key.eq(Rh.horse_key.shift(1)).to_numpy()
    prev = Rh.trainer.shift(1).where(same)
    base['c|trainer_chg'] = (Rh.trainer != prev).astype(float).where(prev.notna() & Rh.trainer.notna()).to_numpy()
    pm = Rh.msh.shift(1).where(same)
    base['f53_male_share_chg'] = (Rh.msh - pm).to_numpy()
    X = Rh.loc[tmask_h, Q4 + ['rid']].reset_index(drop=True)
    B = pd.DataFrame({k: np.asarray(v, float)[tmask_h] for k, v in base.items()})
    rk = lambda s: s.groupby(X.rid.to_numpy()).rank(pct=True)  # noqa: E731
    for c in C:
        nm, ver = c.split('#') if '#' in c else (c, 'raw')
        if nm.startswith('x|'):
            a, b = nm[2:].split('*')
            X[c] = ((rk(B[a]) - 0.5) * (rk(B[b]) - 0.5)).to_numpy()
        else:
            X[c] = (rk(B[nm]) if ver == 'rk' else B[nm]).to_numpy()
    fill = {k: round(float(X[k].notna().mean()), 3) for k in WATCH}
    return X.drop(columns='rid'), fill


# ================================================================ 前日の表に足す
def boosters():
    import lightgbm as lgb
    meta = json.loads((ASSET / 'f10k_bundle.json').read_text(encoding='utf-8'))
    return [lgb.Booster(model_file=str(ASSET / f'f10k_bundle_s{s}.txt')) for s in meta['seeds']], meta['cols']


def p3prime(z, g):
    R = g.max() + 1
    lo, hi = np.full(R, -30.0), np.full(R, 30.0)
    for _ in range(100):
        mid = (lo + hi) / 2
        up = np.bincount(g, 1 / (1 + np.exp(-(z + mid[g]))), R) < 3
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    return 1 / (1 + np.exp(-(z + ((lo + hi) / 2)[g])))


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _q4(x):
    x = x.copy()
    x['race_date'] = x.race_date.astype(str).str[:10]
    x['race_no'] = x.race_no.astype(int)
    x['umaban'] = x.umaban.astype(int)
    return x


def apply_table(x, F, M, C):
    """x = 第11版の前日の表 → 束を足して p3p・rank・mark を出し直す。元の値は p3p_t14・mark_t14 に残す。"""
    x = _q4(x.drop(columns=[c for c in C + ['b19_u'] if c in x.columns]))
    x = x.merge(F, on=Q4, how='left', validate='1:1')
    A = x[C].astype(float).to_numpy()
    u = np.mean([m.predict(A, raw_score=True) for m in M], axis=0)
    x['p3p_t14'], x['mark_t14'], x['b19_u'] = x.p3p, x['mark'], u
    g = x.groupby(KEY, sort=False).ngroup().to_numpy()
    q0 = np.maximum(1 / (1 + np.exp(-(lg(x.p3p) + u))), x.p1.to_numpy(float))
    q = p3prime(lg(q0), g)
    big = x.groupby(KEY, sort=False).umaban.transform('size').to_numpy() > 3
    x['p3p'] = np.where(big, q, x.p3p)
    o = x.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map({1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}).fillna('')
    return x.drop(columns=C)


def run(day, h, races, csv_path, log=log0):
    """便の入口(v3_daily・束 t14 を足せた日だけ): 60 列を作り、見張りを通れば前日の表の CSV を書き換える。→ 足したか。"""
    import time
    t0 = time.time()
    U = None
    try:
        import t14_bundle
        U = t14_bundle.CACHE.get('U')
    except Exception:  # noqa: BLE001
        pass
    if U is None or U.race_date.astype(str).str[:10].max() < day:
        import t4_open
        log('束 f10k: 土台 U を作り直す')
        U = t4_open.base_of(h[h.race_date.astype(str).str[:10] <= day], races[races.race_date.astype(str).str[:10] <= day])
    F, fill = feats(day, h, U, log=log)
    LASTF[day] = F  # 決め 49: F3 の材料(f3_live が読む)
    log('束 f10k 60 列 値のある割合', fill, '・全列の平均', round(float(F.drop(columns=Q4).notna().mean().mean()), 3), '・秒', round(time.time() - t0))
    bad = {k: fill[k] for k, v in WATCH.items() if fill[k] < v}
    if bad:
        log('⛔ 束 f10k の見張りで止める(第11版のまま)', bad, '/ 線', WATCH)
        return False
    M, C = boosters()
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    y = apply_table(x, F, M, C)
    ch = int((y[y['rank'] == 1].set_index(KEY).umaban != _q4(x)[x['rank'] == 1].set_index(KEY).umaban).sum())
    y = y.sort_values(KEY + ['rank'], kind='mergesort')
    y.to_csv(csv_path, index=False, encoding='utf-8-sig')
    log('束 f10k 足した', y[KEY].drop_duplicates().shape[0], 'R・木の値 平均', round(float(y.b19_u.mean()), 4), '幅',
        round(float(y.b19_u.std()), 4), '・本命が替わった', ch, 'R')
    return True


# ================================================================ 手元の照合
def check(days):
    import t5_open as o5
    import t6_forecast as f6
    import t4_open
    h, races = f6.f4.fill_key(*o5.load5('forward'))
    R0 = pd.read_parquet('C:/Users/kouki/nankan_ai/v3/f10k_pass.parquet')
    C = cols()
    res = []
    for day in days:
        hh = h[h.race_date.astype(str).str[:10] <= day]
        U = t4_open.base_of(hh, races[races.race_date.astype(str).str[:10] <= day])
        X, fill = feats(day, hh, U)
        Y = X.merge(R0[R0.race_date == day], on=Q4, how='inner', suffixes=('', '_r'))
        log0(day, '本番', len(X), '研究', int((R0.race_date == day).sum()), '重なり', len(Y), fill)
        for c in C:
            a, b = Y[c].to_numpy(float), Y[c + '_r'].to_numpy(float)
            same = (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-4 * np.maximum(1, np.abs(b)))
            both = ~np.isnan(a) & ~np.isnan(b)
            res.append({'day': day, '列': c, '行': len(Y), '一致': round(float(same.mean()), 4),
                        '最大の差': round(float(np.abs(a - b)[both].max()) if both.any() else 0.0, 6)})
    R = pd.DataFrame(res)
    S = R.groupby('列', sort=False).agg(行=('行', 'sum'), 一致=('一致', 'min'), 最大の差=('最大の差', 'max'))
    print(S.to_string())
    print('全列の一致の最小', S['一致'].min(), '・一致 1.0 の列', int((S['一致'] == 1).sum()), '/', len(S))
    return R


if __name__ == '__main__':
    if sys.argv[1] == 'check':
        check(sys.argv[2:])
