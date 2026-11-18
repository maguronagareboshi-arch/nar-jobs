# -*- coding: utf-8 -*-
"""tenkai_sim_pace_live: 展開シミュレーターの「流れ」「走破時計」「馬ごとの癖」を、AI と同じ元(公式の成績の表 = DB の nar_runs・nar_races)から読む部品(見せ方だけ)。
便(nar-jobs pipeline/ai/v3/)と手元(nankan-ai-v3 src/f5_scripts/)に同じ写しを置く。式の数は同じ置き場の tenkai_sim_pace_model.json
(手元の台本 tenkai_sim_pace.py fit_db で作る・大井 2025-01〜 のレースで当てはめ)。⛔オッズ・人気は読まない。予想の印・率は変えない。

馬ごと(その日より前の近 5 走・地方の全場・中央は数えない):
  pos1 … 最初の角の位置(0 = 先頭・1 = 最後方)= 前に行く度合い
  fr   … 前半(走破時計 − 上がり 3F)の速さ。コース・距離・馬場の真ん中との差を 1000m あたりに(− = 速い)
  ag   … 上がり 3F − そのレースの先頭のラップの上がり 3F(− = 終いが切れる)
  tm   … 走破時計の真ん中との差 1000m あたり(− = 速い)
  mv   … 最初の角 → 4 角で上げた位置(+ = 捲る)
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

MODELJ = Path(__file__).resolve().with_name('tenkai_sim_pace_model.json')
GO = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
NLAST = 5


def corner_pos(corners):
    """通過順の字 → {馬番: 0〜1 の位置}(最初の角と最後の角)。( ) は並んだ馬 = 同じ位置。"""
    try:
        cs = json.loads(corners) if isinstance(corners, str) else corners
    except Exception:
        return None, None
    if not cs:
        return None, None

    def one(s):
        out, k, toks = {}, 0, re.findall(r'\([^)]*\)|\d+', s or '')
        for t in toks:
            nums = [int(x) for x in re.findall(r'\d+', t)]
            for u in nums:
                out[u] = k + (len(nums) - 1) / 2
            k += len(nums)
        n = max(1, k - 1)
        return {u: v / n for u, v in out.items()}
    return one(cs[0].get('order')), one(cs[-1].get('order'))


def run_metrics(U, R):
    """走り 1 本ごとの pos1・pos4・fr・ag・tm。U = 走り・R = レース(同じ列名の DB の形)。"""
    R = R.copy()
    R['going'] = R['going'].astype(str).where(R['going'].astype(str).isin(GO), '良')
    U = U[U.time_sec.notna() & U.last3f.notna() & (U.time_sec > 30)].copy()
    U = U.merge(R[['track', 'race_date', 'race_no', 'distance_m', 'going', 'race_last3f', 'corners']], on=['track', 'race_date', 'race_no'], how='inner')
    U = U[U.distance_m >= 800]
    cp = {}
    for r in R[['track', 'race_date', 'race_no', 'corners']].itertuples(index=False):
        cp[(r.track, str(r.race_date), int(r.race_no))] = corner_pos(r.corners)
    key = list(zip(U.track, U.race_date.astype(str), U.race_no.astype(int)))
    rn = U.runner_number.astype(int).tolist()
    U['pos1'] = [(cp.get(k) or (None, None))[0].get(u) if (cp.get(k) or (None, None))[0] else np.nan for k, u in zip(key, rn)]
    U['pos4'] = [(cp.get(k) or (None, None))[1].get(u) if (cp.get(k) or (None, None))[1] else np.nan for k, u in zip(key, rn)]
    U['front'] = U.time_sec - U.last3f
    return U


def standards(U):
    """コース・距離ごとの真ん中(前半・走破時計)と、馬場ごとのずれ(1000m あたり)。"""
    g = U.groupby(['track', 'distance_m'])
    st = g.agg(sf=('front', 'median'), stt=('time_sec', 'median'), n=('front', 'size')).reset_index()
    st = st[st.n >= 30]
    X = U.merge(st, on=['track', 'distance_m'])
    X['rf'] = (X.front - X.sf) * 1000 / (X.distance_m - 600).clip(lower=200)
    X['rt'] = (X.time_sec - X.stt) * 1000 / X.distance_m
    gw = X.groupby(['track', 'going']).agg(gaf=('rf', 'median'), gat=('rt', 'median')).reset_index()
    return st, gw


def apply_std(U, st, gw):
    X = U.merge(st[['track', 'distance_m', 'sf', 'stt']], on=['track', 'distance_m'], how='inner').merge(gw, on=['track', 'going'], how='left')
    X[['gaf', 'gat']] = X[['gaf', 'gat']].fillna(0)
    X['fr'] = (X.front - X.sf) * 1000 / (X.distance_m - 600).clip(lower=200) - X['gaf']
    X['tm'] = (X.time_sec - X.stt) * 1000 / X.distance_m - X['gat']
    X['ag'] = X.last3f - X.race_last3f
    X['mv'] = X.pos1 - X.pos4
    X = X[(X.fr.abs() < 8) & (X.tm.abs() < 8) & (X.ag.abs() < 6)]
    return X


def hkey(df):
    return df.horse_name.astype(str) + '|' + df.birth_date.astype(str).str.replace('-', '').str[:8]


def profile(X, day=None):
    """近 5 走の平均(その日より前)。day を渡す = その日の分だけ(本番)。渡さない = 走りごとに、その走りより前の 5 走(学び用)。"""
    X = X.copy()
    X['hk'] = hkey(X)
    X = X.sort_values(['hk', 'race_date', 'race_no'])
    cols = ['pos1', 'fr', 'ag', 'tm', 'mv']
    if day is not None:
        X = X[X.race_date.astype(str) < day]
        P = X.groupby('hk').tail(NLAST).groupby('hk')[cols].mean()
        P['nr'] = X.groupby('hk').tail(NLAST).groupby('hk').size()
        return P
    g = X.groupby('hk')
    for c in cols:
        X['p_' + c] = g[c].transform(lambda s: s.shift(1).rolling(NLAST, min_periods=1).mean())
    X['p_nr'] = g.cumcount().clip(upper=NLAST)
    return X


def race_feats(H):
    """出走馬の近 5 走 → レースの材料。H = 1 レースぶんの馬(列 pos1・fr・ag・tm・mv・nr)。記録の無い馬は真ん中で埋める。"""
    h = H.copy()
    known = h['nr'].fillna(0) > 0
    fill = {'pos1': 0.5, 'fr': 0.4, 'ag': 0.9, 'tm': 0.4, 'mv': 0.0}
    for c, v in fill.items():
        h[c] = h[c].astype(float).fillna(v)
    fr_s = np.sort(h.fr.values)
    tm_s = np.sort(h.tm.values)
    return {
        'n': len(h),
        'nlead': float(((h.pos1 <= 0.12) & known).sum()),          # 逃げたい馬(いつも先頭近く)
        'npre': float(((h.pos1 <= 0.3) & known).sum()),            # 前に行く馬
        'fr2': float(fr_s[:2].mean()),                             # 前半の速い 2 頭の平均
        'frpre': float(h.loc[h.pos1 <= 0.3, 'fr'].mean()) if (h.pos1 <= 0.3).any() else float(fr_s[:2].mean()),
        'ag_m': float(h.ag.mean()),
        'tm5': float(tm_s[:5].mean()),                             # 時計の速い 5 頭の平均
        'unk': float((~known).mean()),
    }


FEATS = ['n', 'nlead', 'npre', 'fr2', 'frpre', 'ag_m', 'tm5', 'unk', 'g1', 'g2', 'g3', 'lp']


def first_prize(v):
    """1 着の賞金(円)。DB は '[800000, 320000, …]' の字。"""
    try:
        a = json.loads(v) if isinstance(v, str) else v
        a = a[0] if isinstance(a, (list, tuple)) else a
        return float(a or 0)
    except Exception:
        return 0.0


def race_targets(R, laps):
    """大井のレース → 流れ z・走破時計の真ん中との差。ラップの区間の数が型と同じ距離だけ。"""
    rows = []
    for r in R.itertuples(index=False):
        L = laps.get(str(int(r.distance_m)))
        if not L:
            continue
        try:
            fl = [float(x) for x in (json.loads(r.furlongs) if isinstance(r.furlongs, str) else r.furlongs)]
        except Exception:
            continue
        if len(fl) != L['laps'] or min(fl) <= 0:
            continue
        tot = sum(fl)
        S = np.array(fl) / tot
        z = float((S - np.array(L['share'])) @ np.array(L['pc'])) / L['pc_sd']
        rows.append({'track': r.track, 'race_date': str(r.race_date), 'race_no': int(r.race_no), 'dist': int(r.distance_m), 'z': z,
                     'dt': tot - L['tot'], 'tot': tot, 'going': str(r.going), 'prize': first_prize(r.prize_yen)})
    return pd.DataFrame(rows)


def design(F):
    F = F.copy()
    for k, g in [('g1', '稍重'), ('g2', '重'), ('g3', '不良')]:
        F[k] = (F.going == g).astype(float)
    F['lp'] = np.log10(F.prize.clip(lower=1e5)) - 6
    return F


def ridge(X, y, lam=1.0):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    A = np.c_[np.ones(len(Z)), Z]
    I = np.eye(A.shape[1]); I[0, 0] = 0
    b = np.linalg.solve(A.T @ A + lam * I, A.T @ y)
    return {'mu': mu.tolist(), 'sd': sd.tolist(), 'b': b.tolist()}


def pred(m, X):
    Z = (np.asarray(X, float) - np.array(m['mu'])) / np.array(m['sd'])
    return m['b'][0] + Z @ np.array(m['b'][1:])


def load_model():
    m = json.loads(MODELJ.read_text(encoding='utf-8'))
    st = pd.DataFrame(m['std'], columns=['track', 'distance_m', 'sf', 'stt'])
    st['distance_m'] = st.distance_m.astype(int)
    gw = pd.DataFrame(m['going_adj'], columns=['track', 'going', 'gaf', 'gat'])
    return m, st, gw


def live_profiles(day, names, rest, rpc, q):
    """その日の出走馬の名前 → 馬ごとの近 5 走(index = 馬名|生年月日)。DB から読むのは馬の過去 2 年の走りと、その走りのレースの行だけ。"""
    m, st, gw = load_model()
    since = str((pd.Timestamp(day) - pd.Timedelta(days=730)).date())
    sel = 'horse_name,birth_date,track,race_date,race_no,runner_number,finish_note,time_sec,last3f'
    rows, names = [], sorted(set(names))
    for i in range(0, len(names), 60):
        off = 0
        while True:
            r = rpc('runs_by_horses', {'p_names': names[i:i + 60]},
                    f'select={sel}&race_date=lt.{day}&race_date=gte.{since}&order=race_date.desc,race_no.desc,track.asc,runner_number.asc&limit=1000&offset={off}')
            rows += r
            if len(r) < 1000:
                break
            off += 1000
    U = pd.DataFrame(rows)
    if U.empty:
        return pd.DataFrame(), m
    U = U[(U.track != '帯広') & ~U.finish_note.isin(['出走取消', '競走除外'])].copy()
    U['race_date'] = U.race_date.astype(str)
    U['hk'] = hkey(U)
    U = U.sort_values(['race_date', 'race_no'], ascending=False).groupby('hk').head(NLAST + 3)
    keys = sorted(set(zip(U.track, U.race_date, U.race_no.astype(int))))
    by = {}
    for t, d, n in keys:
        by.setdefault((t, d), []).append(n)
    conds = [f'and(track.eq.{q(t)},race_date.eq.{d},race_no.in.({",".join(map(str, ns))}))' for (t, d), ns in by.items()]
    R = []
    for i in range(0, len(conds), 40):
        R += rest('nar_races?select=track,race_date,race_no,distance_m,going,race_last3f,corners&or=(' + ','.join(conds[i:i + 40]) + ')')
    R = pd.DataFrame(R)
    R['race_date'] = R.race_date.astype(str)
    R['corners'] = R.corners.apply(lambda v: v if isinstance(v, str) or v is None else json.dumps(v, ensure_ascii=False))
    X = apply_std(run_metrics(U.drop(columns=['hk']), R), st, gw)
    return profile(X, day), m


def live_pace(m, H, dist, going, prize):
    """1 レースの馬(列 pos1・fr・ag・tm・mv・nr)→ 流れ z・走破時計の差 dt(と外れの幅)・材料。"""
    f = race_feats(H)
    f.update({'going': going if going in GO else '良', 'prize': first_prize(prize)})
    F = design(pd.DataFrame([f]))
    x = F[m['feats']].values
    z, dt = float(pred(m['z'], x)[0]), float(pred(m['dt'], x)[0])
    return {'z': round(z, 3), 'zs': round(m['z']['res_sd'], 3), 'dt': round(dt, 2), 'dts': round(m['dt']['res_sd'], 2),
            'nlead': int(f['nlead']), 'npre': int(f['npre']), 'unk': round(f['unk'], 2)}
