# -*- coding: utf-8 -*-
"""直前版の最後の 1 段(決め 49・ユーザー承認 2026-10-22)。

- 前日の便(v3_daily・短評の層の後): 材料を作って v29 の土台へ 'F3:' + 列名 で書く。
- 当日の便(v29_gap.day_marks・状況の印の後): 当日の体重を足して混ぜる。材料がそろわないレースは前の段のまま。
模型・列・重みは暗号化のリリース(V3_F3 = v3-f3-20261022・定数 f3_blend)から読む。
"""
import json
import os
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ASSET = Path(os.environ.get('V3_F3', 'C:/Users/kouki/nankan_ai/v3/f3_prod'))
KEY = ['track', 'race_date', 'race_no']
Q4 = KEY + ['umaban']
PFX = 'F3:'
DAYC = ['body_weight', 'o_bwchg', 'f_bwabs']  # 当日の便が埋める列
# 2026-10-23 馬場の得手 3 列: 前の晩は馬場が分からず 'F3:' の写しは空。当日の便は v31_bundle.pick_going が選んだ v8bl_ の列から取る
#   (研究の表は実際の馬場で 86〜99% 埋まっている・決め 49 の照合は過去の日だけで見落とした)
GOING = {'v8bl:S_g': 'v8bl_S_g', 'v8bl:M_g': 'v8bl_M_g', 'v8bl:D_g': 'v8bl_D_g'}
ATOMS = ['fin_r', 'top3', 'win', 'SI', 'si_rk', 'up_rk', 'ten_rk', 'c1r', 'c4r', 'tdiff_k', 'last3f', 'gain', 'si_gap']
TRK = {'大井': 0, '川崎': 1, '船橋': 2, '浦和': 3}
SEM_FLG = ['light', 'strong', 'much', 'gaik', 'gear', 'rest', 'late', 'jissen', 'partner', 'temper', 'heavy', 'scratch', 'gate']
SEM_KINDS = ['状', '動', '変', '併', '調', '体', '癖', '具', '実', '時', '出', '他']
TAG = '決め49 F3 混ぜ'
WATCH = {'age': 0.95, 'l1_fin_r': 0.6, 'lg_g_mu': 0.6, 'crs_pct3': 0.4, 'h|distance_m|up_i|x5#raw': 0.4}  # 値のある割合の下限(研究の表の 0.9 倍ほど)
LAST = {}  # 前日の便: 部品が作った表(t14・f10k・短評の層・初出走の層)を v3_daily の後で受け取る


def log0(*a):
    print('[f3]', *a, flush=True)


def _q4(x):
    x = x.copy()
    x['race_date'] = x.race_date.astype(str).str[:10]
    x['race_no'] = pd.to_numeric(x.race_no).astype(int)
    x['umaban'] = pd.to_numeric(x.umaban).astype(int)
    return x


def load(d=None):
    """模型(3 着内・1 着 × 種 3 本)と列。無ければ None。"""
    import lightgbm as lgb
    d = Path(d) if d else ASSET
    if not (d / 'f3.json').exists():
        return None
    m = json.loads((d / 'f3.json').read_text(encoding='utf-8'))
    m['M'] = {t: [lgb.Booster(model_file=str(d / f)) for f in fs] for t, fs in m['models'].items()}
    m['dir'] = d
    return m


def load_all(d=None):
    """当日の便: (模型, 混ぜの重み W)。模型が無ければ (None, None)。重みは暗号化の定数(無ければ sealed が止める)。"""
    M = load(d)
    if M is None:
        return None, None
    sys.path.append(str(HERE.parent))  # 末尾に足す = pipeline/ai の sealed
    import sealed
    return M, float(sealed.get('f3_blend')['W'])


def has_cols(M, B):
    """土台に前日の便が書いた F3 の列がそろっているか。"""
    return {PFX + c for c in M['cols'] if c not in DAYC} <= set(B.columns)


# ================================================================ 走り 61 列(研究 ana_label_denoise.build → blend_f3_clean.build_clean と同じ作り)
def runs61(h, U, day):
    """その日の南関の出走馬 1 頭 1 行: Q4 + 走り 61 列。元の走り = f10k_bundle.runs(研究 f10k_gen.load_runs と同じ)+ 通過順(h の c1〜n4)。"""
    import f10k_bundle
    R = f10k_bundle.runs(h, U, day)
    fa = _q4(h[h.track.isin(TRK)][Q4 + ['c1', 'n1', 'c4', 'n4']])
    fa = fa[fa.race_date <= day].drop_duplicates(Q4)
    for c in ('c1', 'n1', 'c4', 'n4'):
        fa[c] = pd.to_numeric(fa[c], errors='coerce')
    R = R.merge(fa, on=Q4, how='left', validate='1:1')
    R.loc[R.race_date == day, ['c1', 'c4']] = np.nan  # その日の結果は使わない
    g = R.groupby('rid')
    R['win'] = (R.finish == 1).astype(float).where(R.finish.notna())
    R['c1r'] = R.c1 / R.n1
    R['c4r'] = R.c4 / R.n4
    R['gain'] = R.c4r - R.fin_r
    R['up_rk'] = g.up_i.rank(pct=True, ascending=False)
    R['ten_rk'] = g.ten_i.rank(pct=True, ascending=False)
    R['si_gap'] = R.SI - g.SI.transform('max')
    R = R[R.nfield >= 5].sort_values(['horse_key', 'day', 'race_no']).reset_index(drop=True)
    Rall = R[R.finish.notna()][['jockey', 'trainer', 'race_date', 'top3']].copy()  # 騎手・調教師の前の年の率は全部の走りで
    R = R[R.horse_key.isin(set(R.horse_key[R.race_date == day]))].reset_index(drop=True)  # 前の走りの列はその日に走る馬の分だけ作る(速さのため・値は同じ)
    fin = R.finish.notna().to_numpy()
    Rf = R[fin].copy().reset_index(drop=True)
    gk = Rf.groupby('horse_key')
    post = Rf[['horse_key', 'day']].copy()
    for a in ATOMS:
        Rf['l1_' + a] = gk[a].shift(1)
        Rf['m3_' + a] = gk[a].transform(lambda x: x.shift(1).rolling(3, min_periods=1).mean())
        Rf['m5_' + a] = gk[a].transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean())
        post['l1_' + a] = Rf[a]
        post['m3_' + a] = gk[a].transform(lambda x: x.rolling(3, min_periods=1).mean())
        post['m5_' + a] = gk[a].transform(lambda x: x.rolling(5, min_periods=1).mean())
    Rf['n_prev'] = gk.cumcount().astype(float)
    Rf['rest'] = Rf.day - gk.day.shift(1)
    Rf['dd'] = Rf.distance_m - gk.distance_m.shift(1)
    Rf['dcls'] = Rf.b_g - gk.b_g.shift(1)
    post['n_post'] = gk.cumcount().astype(float) + 1
    post['p_day'], post['p_dist'], post['p_bg'] = Rf.day, Rf.distance_m, Rf.b_g
    hist = [c for c in post.columns if c[:3] in ('l1_', 'm3_', 'm5_')]
    Rn = R[~fin].copy()
    Rn['_o'] = np.arange(len(Rn))
    Q = pd.merge_asof(Rn.sort_values('day'), post.sort_values('day'), on='day', by='horse_key', allow_exact_matches=False, direction='backward')
    Q = Q.sort_values('_o').reset_index(drop=True)
    Rn = Rn.reset_index(drop=True)
    for c in hist:
        Rn[c] = Q[c].to_numpy()
    Rn['n_prev'] = Q.n_post.fillna(0).to_numpy()
    Rn['rest'] = Rn.day.to_numpy() - Q.p_day.to_numpy()
    Rn['dd'] = Rn.distance_m.to_numpy() - Q.p_dist.to_numpy()
    Rn['dcls'] = Rn.b_g.to_numpy() - Q.p_bg.to_numpy()
    A = pd.concat([Rf, Rn.drop(columns=['_o'])], ignore_index=True)
    A['age'] = (pd.to_datetime(A.race_date) - pd.to_datetime(A.birth_date, errors='coerce')).dt.days / 365.25
    A['sexc'] = A.sex.map({'牡': 0, '牝': 1, 'セ': 2}).astype(float)
    A['trk'] = A.track.map(TRK).astype(float)
    A['yr'] = A.race_date.str[:4].astype(int)
    Rall['yr'] = Rall.race_date.str[:4].astype(int)
    for who in ('jockey', 'trainer'):  # 前の年の 3 着内率(30 走以上・完走した走りで数える)
        s = Rall.groupby([who, 'yr']).top3.agg(['mean', 'size']).reset_index()
        s = s[s['size'] >= 30]
        s['yr'] += 1
        A[who[0] + '_str'] = pd.Series(list(zip(A[who], A.yr))).map(s.set_index([who, 'yr'])['mean']).to_numpy()
    rg = A.groupby('rid')
    for c in ('m3_SI', 'l1_SI', 'm5_fin_r', 'm3_si_rk', 'j_str', 'm3_c4r'):
        A['rk_' + c] = rg[c].rank(pct=True)
    return A[A.race_date == day].reset_index(drop=True)


# ================================================================ 短評の意味の札 23 列(研究 tanpyo_sem_layer.frame と同じ)
def sem(D, d=None):
    """D の tp_h・tp_w(馬・最終追いの短評)→ lvl_・chg_・hedge_・cover_・k_ と札 g_*(g_rest は「休み」の札 = 休みの日数ではない)。"""
    import tanpyo_live
    d = Path(d) if d else ASSET
    T = pd.read_csv(d / 'tags_v2.tsv', sep='\t', keep_default_na=False).set_index('s')
    out = pd.DataFrame(index=D.index)
    for c in ('h', 'w'):
        s = D['tp_' + c].map(lambda x: tanpyo_live.norm(x) if isinstance(x, str) else np.nan)
        for f in ('lvl', 'chg', 'hedge', 'cover'):
            out[f'{f}_{c}'] = pd.to_numeric(s.map(T[f]), errors='coerce').where(s.notna())
        out['k_' + c] = s.map(T['kind']).map({k: i for i, k in enumerate(SEM_KINDS)}).astype(float)
    sh = D.tp_h.map(lambda x: tanpyo_live.norm(x) if isinstance(x, str) else np.nan)
    sw = D.tp_w.map(lambda x: tanpyo_live.norm(x) if isinstance(x, str) else np.nan)
    fl = sh.map(T['flags']).fillna('') + '|' + sw.map(T['flags']).fillna('')
    has = D.tp_h.notna() | D.tp_w.notna()
    for f in SEM_FLG:
        out['g_' + f] = fl.str.split('|').map(lambda v, f=f: float(f in v)).where(has)
    return out


# ================================================================ 前日の便: 284 列を v29 の土台へ
def births(day):
    """その日の南関の出走馬の誕生日(DB nar_runs・読むだけ)。土台の走りの表 h には誕生日が入らない(t3_open.sources が落とす)。"""
    from day2_db_copy import req
    r = req('nar_runs', [('select', 'track,race_date,race_no,runner_number,birth_date'), ('race_date', f'eq.{day}'),
                         ('track', 'in.(' + ','.join(TRK) + ')'), ('limit', '5000')])
    B = pd.DataFrame(r, columns=['track', 'race_date', 'race_no', 'runner_number', 'birth_date']).rename(columns={'runner_number': 'umaban'})
    return _q4(B).drop_duplicates(Q4)


def table(day, h, U, vb, Dt, Dd, F14, F10, cols, bd):
    """部品の表 → Q4 + 'F3:' 列(当日の 3 列を除く)。vb = v29 の土台・Dt = 短評の層の D(add6 の後)・Dd = 初出走の層の D・F14 = 束 t14 の 37 列・F10 = 束 f10k の 60 列・
    bd = その日の誕生日(Q4 + birth_date)。"""
    X = _q4(vb[Q4])
    R = runs61(h, U, day)
    b = R[Q4].merge(_q4(bd)[Q4 + ['birth_date']], on=Q4, how='left')
    R['age'] = ((pd.Timestamp(day) - pd.to_datetime(b.birth_date.astype(str).str[:10], errors='coerce')).dt.days / 365.25).to_numpy()
    X = X.merge(R[Q4 + [c for c in R.columns if c in cols and c not in DAYC]], on=Q4, how='left', validate='1:1')
    for nm, P in (('t14', F14), ('f10k', F10)):
        P = _q4(P)
        X = X.merge(P[Q4 + [c for c in P.columns if c in cols and c not in X.columns]], on=Q4, how='left', validate='1:1')
    B = _q4(vb)
    B = B.rename(columns={c: c.replace('_', ':', 1) for c in B.columns if c.startswith(('f5_', 'v8fa_', 'v8fm_', 'v8bl_'))})
    X = X.merge(B[Q4 + [c for c in B.columns if c in cols and c not in X.columns and c != 'g_rest']], on=Q4, how='left', validate='1:1')
    Dt = _q4(Dt).reset_index(drop=True)
    Dt = pd.concat([Dt.drop(columns=['g_rest'], errors='ignore'), sem(Dt)], axis=1)  # 研究の表の g_rest = 意味の札の「休み」(日数は d_rest)
    tm = ('crs_pct3', 'crs_pct5', 'crs_pcth')  # 短評の層の D の時計の比べは空の列 = 初出走の層の D から取る
    X = X.merge(Dt[Q4 + [c for c in Dt.columns if c in cols and c not in X.columns and c not in tm]], on=Q4, how='left', validate='1:1')
    Dd = _q4(Dd)
    X = X.merge(Dd[Q4 + [c for c in ('crs_pct3', 'crs_pct5', 'crs_pcth') if c in cols and c not in X.columns]], on=Q4, how='left', validate='1:1')
    miss = [c for c in cols if c not in X.columns and c not in DAYC]
    if miss:
        raise KeyError(f'F3 の列が作れない {miss[:12]}(計 {len(miss)})')
    if 'f5:F' in cols:  # 研究の直し(blend_f3_clean.ex60): ちょうど 60 日前に走りのある馬は f5:F を空に
        X['f5:F'] = X['f5:F'].where(~ex60(day, U, X))
    return X[Q4 + [c for c in cols if c not in DAYC]].rename(columns={c: PFX + c for c in cols})


def ex60(day, U, X):
    """その日のちょうど 60 日前に南関の走りのある馬(研究 blend_f3_clean.ex60 と同じ: 土台 U の horse_key と走った日)。"""
    u = U[U.track.isin(TRK)][['track', 'race_date', 'race_no', 'runner_number', 'horse_key']].rename(columns={'runner_number': 'umaban'})
    u = _q4(u)
    d0 = (pd.Timestamp(day) - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
    past = set(u.horse_key[u.race_date == d0])
    hk = X[Q4].merge(u[u.race_date == day][Q4 + ['horse_key']].drop_duplicates(Q4), on=Q4, how='left')
    return hk.horse_key.isin(past).to_numpy()


def run(day, h, base_csv, log=log0):
    """便の入口(v3_daily・短評の層の後): 284 列を作って v29 の土台へ書く。→ 書いた頭数(書かなかったら 0)。"""
    import time
    import t14_bundle
    t0 = time.time()
    M = load()
    if M is None:
        log('模型なし(足さない)')
        return 0
    need = [k for k in ('t14', 'f10k', 'tanpyo', 'debut') if LAST.get(k) is None]
    if need:
        log('部品の表が無い = 書かない(当日は前の段のまま)', need)
        return 0
    U = t14_bundle.CACHE.get('U')
    bp = Path(base_csv)
    vb = _q4(pd.read_csv(bp, encoding='utf-8-sig'))
    X = table(day, h, U, vb, LAST['tanpyo'], LAST['debut'], LAST['t14'], LAST['f10k'], M['cols'], births(day))
    fill = X.drop(columns=Q4).notna().mean()
    bad = {c: round(float(fill[PFX + c]), 3) for c, v in WATCH.items() if fill[PFX + c] < v}
    if bad:
        log('⛔ F3 の材料の見張りで止める(書かない = 当日は前の段のまま)', bad, '/ 線', WATCH)
        return 0
    vb = vb.drop(columns=[c for c in vb.columns if c.startswith(PFX)]).merge(X, on=Q4, how='left', validate='1:1')
    vb.to_csv(bp, index=False, encoding='utf-8-sig')
    log('直前版へ F3 の材料', len(X), '頭', len(fill), '列・値のある割合 平均', round(float(fill.mean()), 3),
        '・全部空の列', [c for c in fill.index if fill[c] == 0][:8], '・秒', round(time.time() - t0))
    return len(X)


# ================================================================ 当日の便: 木を当てて混ぜる
def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def qlogit(M, X):
    """種 3 本の確率の平均の logit(研究 blend_f3_judge.avg_logit と同じ・端は 1e-4)。"""
    out = {}
    for t in ('p3', 'p1'):
        q = np.clip(np.mean([m.predict(X) for m in M['M'][t]], axis=0), 1e-4, 1 - 1e-4)
        out[t] = np.log(q / (1 - q))
    return out


def day_x(M, b):
    """1 レースの土台 b(v29_gap.feats の後: bw・bwd)→ 木の材料 (n, 287)。前日の列が無ければ None。"""
    have = [PFX + c for c in M['cols'] if c not in DAYC]
    if not set(have) <= set(b.columns):
        return None
    X = pd.DataFrame({c: pd.to_numeric(b[PFX + c], errors='coerce').to_numpy(float) for c in M['cols'] if c not in DAYC})
    for c, g in GOING.items():
        if c in X.columns and g in b.columns:
            X[c] = X[c].where(np.isfinite(X[c]), pd.to_numeric(b[g], errors='coerce').to_numpy(float))
    bwd = pd.to_numeric(b['bwd'], errors='coerce').to_numpy(float) if 'bwd' in b.columns else np.full(len(b), np.nan)
    X['body_weight'] = pd.to_numeric(b['bw'], errors='coerce').to_numpy(float) if 'bw' in b.columns else np.nan
    X['o_bwchg'] = bwd
    X['f_bwabs'] = np.abs(bwd)
    for c in M.get('f32', []):  # 研究の表で 32 ビットの列は 32 ビットに丸める(木の境目の近くで研究と同じ側に落ちるように)
        X[c] = X[c].astype(np.float32).astype(float)
    return X[M['cols']].to_numpy(float)


def apply_day(M, b, p1, p3p, u, W):
    """当日の便(v29_gap.day_marks・短評の層の後): → (p1′, p3′ の合計の前, p3′) か None(材料が無い)。"""
    X = day_x(M, b)
    if X is None or u is None:
        return None
    q = qlogit(M, X)
    u = np.asarray(u, float)
    e1 = np.exp(lg(p1) * (1 - W) + W * (q['p1'] + u))
    p1n = (e1 / (1 + e1))
    p1n = p1n / p1n.sum()
    p3 = np.maximum(1 / (1 + np.exp(-((1 - W) * lg(p3p) + W * (q['p3'] + u)))), np.minimum(p1n, 0.999))
    return p1n, p3
