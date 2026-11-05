# -*- coding: utf-8 -*-
"""他場版 v3n 第 13 版(決め 70・2026-11-06 合格・v3 の out/v3n_mix_judge.md・研究 src/f5_scripts/v3n_mx70_prod.py)。

木の段(3 着内の率 p5 と勝つ率 c1)に、学び方の違う模型を混ぜる。重み = 今の木 40%・直近 2 年の木 M 20%・
CatBoost 3 本(種 11・12・13)計 20%・ニューラルネット 3 本(種 11・12・13)計 20%。
  - 各模型の 3 着内の見込みを R の中で割り、模型ごとの γ(頭数の帯)・曲線(頭数 3 帯)で p5 にし、logit の重み平均。
  - 勝つ率 = 各模型の勝ちの見込みを R の中で割り(CatBoost・ニューラルネットは帯の表を当てない = 判定と同じ)、対数の重み平均を R で割り直す。
その後(並び読み・E1・能検・勝つ率の直し〔k は mo5・di5〕・混ぜ〔決め 40〕・内外の有利〔決め 61〕)は第 12 版と同じ。
模型 = V3N_MX70/cb{種}_p3.cbm・cb{種}_pw.cbm・nn{種}.npz(暗号化リリース・年 1 回 9 月に今の木と一緒に学び直す)。
ニューラルネットの当ては numpy だけ(学びの torch と同じ式・研究で差を照合済み)。
定数(重み・γ・曲線・TAG)は暗号化したリリース v3-consts の consts.json の v3n_mx70(公開のコードに数を置かない)。
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed
import sealed  # noqa: E402

C = sealed.get('v3n_mx70')
W = {k: float(v) for k, v in C['W'].items()}      # 'T1xF'・'M'・CB・CB12・CB13・NN・NN12・NN13
MODELS = list(C['models'])                        # 混ぜる模型の名(並びは meta.mx70.sh の並び)
SEED = {k: int(v) for k, v in C['seed_of'].items()}
NB = C['nb']
TAG = C['TAG']
KEY = ['track', 'race_date', 'race_no', 'runner_number']


def load(path=None):
    """模型 9 本(CatBoost 6 + ニューラルネット 3)→ dict。無ければ FileNotFoundError"""
    from catboost import CatBoostClassifier
    d = Path(path or os.environ.get('V3N_MX70', 'v3n_mx70'))
    info = json.loads((d / 'v3n_mx70_models.json').read_text(encoding='utf-8'))
    out = {'cut': info['cut'], 'trained_to': info['trained_to'], '_m': {}}
    for x in MODELS:
        s = SEED[x]
        if x.startswith('CB'):
            mm = {}
            for h in ('p3', 'pw'):
                m = CatBoostClassifier()
                m.load_model(str(d / f'cb{s}_{h}.cbm'))
                mm[h] = m
            out['_m'][x] = ('cb', mm)
        else:
            z = np.load(d / f'nn{s}.npz')
            out['_m'][x] = ('nn', {k: z[k] for k in z.files})
    return out


def matrix(one, F, Vt):
    """v3n_one.predict と同じ材料の行列(列 = 木の cols・場 trk は場の番号)→ (鍵の表, float32 の行列)"""
    X = F.copy()
    X['race_no'], X['runner_number'] = X.race_no.astype('int64'), X.runner_number.astype('int64')
    v = Vt.rename(columns={c: 'v_' + c for c in one['vcols']})
    v = v.assign(race_date=pd.to_datetime(v.race_date), race_no=v.race_no.astype('int64'), runner_number=v.runner_number.astype('int64'))
    v = v[KEY + [c for c in v.columns if c.startswith('v_')]]
    X = X.merge(v, on=KEY, how='left', validate='1:1')
    for c in one['vcols']:
        X['v_' + c] = X['v_' + c].astype('float32') if 'v_' + c in X.columns else np.full(len(X), np.nan, 'float32')
    trk = pd.Categorical(X.track, categories=one['trk'])
    assert (trk.codes >= 0).all(), ('学びに無い場', sorted(set(X.track[trk.codes < 0])))
    cols = one['cols']
    miss = [c for c in cols if c != 'trk' and c not in X.columns]
    assert not miss, ('材料に無い列', miss[:10], len(miss))
    A = np.column_stack([trk.codes.astype('float32') if c == 'trk' else X[c].to_numpy('float32') for c in cols])
    return X[KEY + ['rid']].reset_index(drop=True), A


def nn_forward(z, Xc):
    """ニューラルネット(412 列 → 分位の位置・空欄の印・場の埋め込み → 512・256・128 → 3 着内・勝ち)。学び v3n_nn_fit_1105 と同じ式"""
    Q, flag, ci = z['Q'], z['flag'], int(z['ci'])
    n, p = Xc.shape
    out = np.zeros((n, p - 1 + len(flag)), dtype='float32')
    j = 0
    grid = np.linspace(0, 1, 201)
    for c in range(p):
        if c == ci:
            continue
        x = Xc[:, c].astype('float64')
        q = Q[:, c]
        nan = np.isnan(x)
        if np.isnan(q).all() or q[0] == q[-1]:
            v = np.zeros(n)
        else:
            qq, ix = np.unique(q, return_index=True)
            v = (np.interp(np.where(nan, qq[0], x), qq, grid[ix]) - 0.5) * 4
        v[nan] = 0
        out[:, j] = v
        j += 1
    for k, c in enumerate(flag):
        out[:, j + k] = np.isnan(Xc[:, c])
    h = out.astype('float16').astype('float32')
    t = np.nan_to_num(Xc[:, ci], nan=-1).astype('int64')
    h = np.concatenate([h, z['w_emb_weight'][t + 1]], 1)
    for a in (0, 3, 6):
        h = h @ z[f'w_body_{a}_weight'].T + z[f'w_body_{a}_bias']
        h = h / (1 + np.exp(-h))           # SiLU
    o = h @ z['w_head_weight'].T + z['w_head_bias']
    return np.clip(1 / (1 + np.exp(-o.astype('float64'))), 1e-6, 1 - 1e-6)


def predict(mx, one, F, Vt):
    """→ 鍵 + rid + 模型ごとの g3_x(3 着内の見込み)・pw_x(勝ちの見込みを R で合計 1)"""
    import ai_common as B
    out, A = matrix(one, F, Vt)
    for x, (kind, m) in mx['_m'].items():
        if kind == 'cb':
            g3, pw = m['p3'].predict_proba(A)[:, 1], m['pw'].predict_proba(A)[:, 1]
        else:
            r = nn_forward(m, A)
            g3, pw = r[:, 0], r[:, 1]
        out['g3_' + x] = g3
        out['pw_' + x] = B.race_norm(pw, out['rid'])
    return out


def sharpen(x, s, n):
    """模型 x の 3 着内の割合 → s^γ ÷ Σ(γ は模型 x の頭数の帯ごと)"""
    g = C['gamma'][x][next(i for i, k in enumerate(NB) if n <= k)]
    t = np.power(np.clip(np.asarray(s, float), 1e-9, 1), g)
    return t / t.sum()


def p3(x, c, n):
    """模型 x の割合 → 3 着内の率(模型 x の頭数 3 帯の曲線)"""
    t = C['curve'][x]['〜8 頭' if n <= 8 else ('9〜10' if n <= 10 else '11 頭〜')]
    return np.clip(np.interp(np.log(np.clip(np.asarray(c, float), 1e-6, 1)), t['x'], t['y']), 0.001, 0.999)


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def p5_extra(shares, n):
    """shares = {模型: 1 レースの 3 着内の割合(合計 1)} → {模型: p5}"""
    return {x: p3(x, sharpen(x, shares[x], n), n) for x in MODELS}


def mix_p3(p3t, p3m, p5x):
    """3 着内の率: 今の木・M・6 本を logit の重み平均"""
    z = W['T1xF'] * lg(p3t) + W['M'] * lg(p3m) + sum(W[x] * lg(p5x[x]) for x in MODELS)
    return 1 / (1 + np.exp(-z))


def mix_c1(c1t, c1m, c1x):
    """1 レースの勝つ率: 対数の重み平均 → 合計 1"""
    z = W['T1xF'] * np.log(np.clip(np.asarray(c1t, float), 1e-9, 1)) + W['M'] * np.log(np.clip(np.asarray(c1m, float), 1e-9, 1))
    z = z + sum(W[x] * np.log(np.clip(np.asarray(c1x[x], float), 1e-9, 1)) for x in MODELS)
    v = np.exp(z)
    return v / v.sum()
