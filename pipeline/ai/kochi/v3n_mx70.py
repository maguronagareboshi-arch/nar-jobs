# -*- coding: utf-8 -*-
"""他場版 v3n 第 13 版(決め 70・2026-11-06 合格・v3 の out/v3n_mix_judge.md・研究 src/f5_scripts/v3n_mx70_prod.py)。
2026-11-19 他場 第 14 版(決め 83・v3 の out/nn83/judge.md): NN 3 本をレース全体を読む NN 3 本(NA11〜13・V3N_NA83)と入れ替えた組 na83。
  配合の割合・γ・曲線の形は同じ(値は組ごと)・勝つ率の直しの k は mo6・di6。模型か定数が無い・読めない・当てが落ちた日は第 13 版の組 mx70 に戻す。
  どちらの組で出したかは meta.mx70.set(直前の便は朝の組で割り直す)。

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

C70 = sealed.get('v3n_mx70')
try:   # 2026-11-19 決め 83(他場 第 14 版): NN 3 本をレース全体を読む NN 3 本(NA11〜13)と入れ替えた組。定数に無ければ第 13 版の組だけ
    C83 = sealed.get('v3n_na83')
except KeyError:
    C83 = None
SETS = {'mx70': C70, **({'na83': C83} if C83 else {})}
VKEY = {'mx70': {'mo': 'mo5', 'di': 'di5'}, 'na83': {'mo': 'mo6', 'di': 'di6'}}   # 勝つ率の直しの k(v3n_p1 の K)


def use(name):
    """混ぜの組を替える(mx70 = 第 13 版・na83 = 決め 83)。W・MODELS・SEED・NB・TAG・SET を差し替える"""
    global C, W, MODELS, SEED, NB, TAG, SET
    C = SETS[name]
    W = {k: float(v) for k, v in C['W'].items()}      # 'T1xF'・'M'・CB・CB12・CB13・(NN・NN12・NN13 か NA11・NA12・NA13)
    MODELS = list(C['models'])                        # 混ぜる模型の名(並びは meta.mx70.sh の並び・meta.mx70.set で組が分かる)
    SEED = {k: int(v) for k, v in C['seed_of'].items()}
    NB = C['nb']
    TAG = C['TAG']
    SET = name


use('mx70')
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
    out['set'] = 'mx70'
    # 決め 83: レース全体を読む NN 3 本(V3N_NA83/na{種}.npz・暗号化リリース)。定数・模型が無い・読めない日は第 13 版の組のまま(止めない)
    na = os.environ.get('V3N_NA83', '')
    if C83 is None or not na or not Path(na).is_dir():
        print('決め 83 の組: 使わない(', '定数なし' if C83 is None else '模型の置き場なし', ')= 第 13 版の組', flush=True)
        return out
    try:
        ni = json.loads((Path(na) / 'v3n_na83_models.json').read_text(encoding='utf-8'))
        for x in C83['models']:
            if x.startswith('NA'):
                z = np.load(Path(na) / f'na{int(C83["seed_of"][x])}.npz')
                out['_m'][x] = ('na', {k: z[k] for k in z.files})
        out['na_cut'] = ni['cut']
        use('na83')
        out['set'] = 'na83'
        print('決め 83 の組: 使う(レース全体を読む NN 3 本・切り', ni['cut'], ')', flush=True)
    except Exception as e:  # noqa: BLE001
        for x in [k for k in out['_m'] if k.startswith('NA')]:
            del out['_m'][x]
        use('mx70')
        print('決め 83 の組: 読めない = 第 13 版の組', type(e).__name__, str(e)[:200], flush=True)
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


def nn_forward(z, Xc, prep_only=False):
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
    if prep_only:
        return h, t
    h = np.concatenate([h, z['w_emb_weight'][t + 1]], 1)
    for a in (0, 3, 6):
        h = h @ z[f'w_body_{a}_weight'].T + z[f'w_body_{a}_bias']
        h = h / (1 + np.exp(-h))           # SiLU
    o = h @ z['w_head_weight'].T + z['w_head_bias']
    return np.clip(1 / (1 + np.exp(-o.astype('float64'))), 1e-6, 1 - 1e-6)


def _gelu(x):
    try:
        from scipy.special import erf
    except ImportError:  # pragma: no cover
        import math
        erf = np.vectorize(math.erf)
    return 0.5 * x * (1 + erf(x / np.sqrt(2)))


def _ln(x, w, b):
    m = x.mean(-1, keepdims=True)
    v = ((x - m) ** 2).mean(-1, keepdims=True)
    return (x - m) / np.sqrt(v + 1e-5) * w + b


def na_forward(z, Xc, rid):
    """レース全体を読む NN(決め 83・学び v3 の src/f5_scripts/v3n_ab_fit_1118.py の A と同じ式)。
    1 頭ずつ 2 層(512・256)で読み、同じ R の全頭(出馬表の馬 = 判定の確かめと同じ顔ぶれ)を注意機構 2 層(4 頭・前に正規化)で見比べ、
    1 頭ずつの読みと見比べた読みをつないで 128 → 3 着内・勝ち"""
    h0, t = nn_forward(z, Xc, prep_only=True)
    g = lambda k: z['w_' + k].astype('float64')   # noqa: E731
    x = np.concatenate([h0.astype('float64'), g('emb_weight')[t + 1]], 1)
    for a in (0, 3):
        x = x @ g(f'enc_{a}_weight').T + g(f'enc_{a}_bias')
        x = x / (1 + np.exp(-x))   # SiLU
    nl = len({k.split('_')[3] for k in z if k.startswith('w_att_layers_')})
    nh, d = 4, x.shape[1]
    hd = d // nh
    r = np.asarray(rid)
    out = np.zeros((len(x), 2))
    for u in pd.unique(r):
        ix = np.where(r == u)[0]
        h = x[ix]
        c = h
        for li in range(nl):
            p = f'att_layers_{li}_'
            y = _ln(c, g(p + 'norm1_weight'), g(p + 'norm1_bias'))
            qkv = y @ g(p + 'self_attn_in_proj_weight').T + g(p + 'self_attn_in_proj_bias')
            q, k, v = (qkv[:, i * d:(i + 1) * d].reshape(len(ix), nh, hd).transpose(1, 0, 2) for i in range(3))
            s_ = q @ k.transpose(0, 2, 1) / np.sqrt(hd)
            s_ = np.exp(s_ - s_.max(-1, keepdims=True))
            s_ = s_ / s_.sum(-1, keepdims=True)
            o = (s_ @ v).transpose(1, 0, 2).reshape(len(ix), d)
            c = c + o @ g(p + 'self_attn_out_proj_weight').T + g(p + 'self_attn_out_proj_bias')
            y = _ln(c, g(p + 'norm2_weight'), g(p + 'norm2_bias'))
            c = c + _gelu(y @ g(p + 'linear1_weight').T + g(p + 'linear1_bias')) @ g(p + 'linear2_weight').T + g(p + 'linear2_bias')
        o = np.concatenate([h, c], 1) @ g('out_0_weight').T + g('out_0_bias')
        o = o / (1 + np.exp(-o))
        out[ix] = o @ g('head_weight').T + g('head_bias')
    return np.clip(1 / (1 + np.exp(-out)), 1e-6, 1 - 1e-6)


def predict(mx, one, F, Vt):
    """→ 鍵 + rid + 模型ごとの g3_x(3 着内の見込み)・pw_x(勝ちの見込みを R で合計 1)"""
    import ai_common as B
    out, A = matrix(one, F, Vt)
    for x, (kind, m) in mx['_m'].items():
        if kind == 'na' and SET != 'na83':
            continue
        if kind == 'cb':
            g3, pw = m['p3'].predict_proba(A)[:, 1], m['pw'].predict_proba(A)[:, 1]
        elif kind == 'na':
            try:
                r = na_forward(m, A, out['rid'].to_numpy())
                assert np.isfinite(r).all(), 'NaN'
            except Exception as e:  # noqa: BLE001  決め 83 の当てが落ちたら第 13 版の組に戻す(NN 3 本は読んである)
                print('決め 83 の当てが落ちた = 第 13 版の組', type(e).__name__, str(e)[:200], flush=True)
                use('mx70')
                mx['set'] = 'mx70'
                out = out[[c for c in out.columns if not c.endswith(tuple(k for k in mx['_m'] if k.startswith('NA')))]].copy()
                continue
            g3, pw = r[:, 0], r[:, 1]
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
