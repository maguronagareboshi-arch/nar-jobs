# -*- coding: utf-8 -*-
"""南関 買い方 決め 4 の段 2(組 6 券種の買い目・研究 nankan-ai-v3 src/f5_scripts/buy4_judge.py select_race・決め書 out/buy4_plan.md・
ユーザー 2026-11-11「このまま固める」)。

段 1(単勝)は今の本番の買い(v29_gap.decide_buy)のまま。この部品は段 2 だけを作る:
  率   = 本番の直前版の行(nar_ai_marks v3-9 last の meta.runners の p1・p3)から、勝率 + 3 着内率の式で 3連単の表 → 6 券種を足し上げ、
         その券種の 10 分前の板の率と単勝の板からの率と混ぜる(重みは券種ごと・研究 ticket_prob_1105g_fit.json の mix)。
  軸   = 混ぜた勝つ率 ≥ AX_P かつ 混ぜた勝つ率 × 単勝 ≥ AX_EV の馬(いなければ段 2 は買わない)。
  買う = 軸を含む組で 混ぜた率 × 期待値用オッズ ≥ LINE(複勝・ワイドは下限)。複勝・ワイド・馬連・馬単・3連複・3連単。枠連・枠単は買わない。
板 = 便が 10 分前に読んだ単勝・複勝・組の最新の 1 本(締め前)。出走する馬 = 単勝の板のある馬(直前版の行に無い馬がいれば作らない)。
数(重み・式の指数・線)は暗号化したリリース v3-consts の consts.json の buy4(公開のコードに数を置かない)。
"""
import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed

# 券種(この部品の名前 → 研究の名前・板の券種)
KINDS = {'fuku': '複勝', 'wide': 'ワイド', 'umaren': '馬連', 'umatan': '馬単', 'sanrenpuku': '3連複', 'sanrentan': '3連単'}
BOARD_KINDS = ('wide', 'umaren', 'umatan', 'sanrenpuku', 'sanrentan')
N17 = 17
_C = None


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('buy4')
    return _C


def tag():
    return consts()['TAG']


# ---------- 3連単の表から券種の率(研究 ticket_prob_build_1105.tensors・all_types と同じ式・枠の券種は作らない) ----------
def _tensors(w, u, v):
    n = len(w)
    I = np.eye(n, dtype=bool)
    P12 = w[:, None] * u[None, :] / np.clip(u.sum() - u[:, None], 1e-12, None)
    P12[I] = 0.0
    d = np.clip(v.sum() - v[:, None] - v[None, :], 1e-12, None)
    T3 = P12[:, :, None] * v[None, None, :] / d[:, :, None]
    T3[I[:, :, None] | I[:, None, :] | I[None, :, :]] = 0.0
    return P12, T3


def _types(w, u, v, place_k):
    P12, T3 = _tensors(w, u, v)
    S3 = T3 + T3.transpose(1, 0, 2) + T3.transpose(0, 2, 1) + T3.transpose(1, 2, 0) + T3.transpose(2, 0, 1) + T3.transpose(2, 1, 0)
    top2 = w + P12.sum(0)
    top3 = top2 + T3.sum((0, 1))
    return {'単勝': w, '複勝': top3 if place_k == 3 else top2, '馬連': P12 + P12.T, 'ワイド': S3.sum(2),
            '馬単': P12, '3連複': S3, '3連単': T3}


_I = np.arange(N17)
_G2a, _G2b = np.meshgrid(_I, _I, indexing='ij')
_G3a, _G3b, _G3c = np.meshgrid(_I, _I, _I, indexing='ij')


def _mask(name, v):
    """買える組(出走する馬だけ・順序なしは 小 < 大 の 1 通り)。研究 combo_mask と同じ。"""
    if name in ('単勝', '複勝'):
        return v.copy()
    if name in ('馬連', 'ワイド'):
        return (_G2a < _G2b) & v[_G2a] & v[_G2b]
    if name == '馬単':
        return (_G2a != _G2b) & v[_G2a] & v[_G2b]
    if name == '3連複':
        return (_G3a < _G3b) & (_G3b < _G3c) & v[_G3a] & v[_G3b] & v[_G3c]
    return (_G3a != _G3b) & (_G3a != _G3c) & (_G3b != _G3c) & v[_G3a] & v[_G3b] & v[_G3c]


def _mix(c, lp, lm, lh, K):
    a, b, cc = consts()['MIX'][c][:3]
    s = a * lp + b * lm + cc * lh
    e = np.exp(s - s.max())
    return np.clip(K * e / e.sum(), 1e-12, 0.995)


def select_arrays(p1, p3, ow, pl, ph, od):
    """研究 buy4_judge.select_race と同じ計算(17 個の配列・馬番で引く・無い馬は 0・od = {研究の券種名: 表(ワイドは [..., 2])})。
    → (軸の馬番の一覧, [(研究の券種名, 組, 混ぜた率, 期待値用オッズ, 市場の率)]) か (None, 理由)。"""
    C = consts()
    A2, B2, A3, B3 = C['A2'], C['B2'], C['A3'], C['B3']
    AX_P, AX_EV, LINE = C['AX_P'], C['AX_EV'], C['LINE']
    v = p1 > 0
    n = int(v.sum())
    if n < 5:
        return None, '5 頭未満'
    if np.any(ow[v] <= 0):
        return None, '単勝オッズ欠け'
    if any(not (od[c] > 0).any() for c in ('馬連', 'ワイド', '馬単', '3連複', '3連単')):
        return None, '組のオッズ欠け'
    place_k = 3 if n >= 8 else 2
    w = p1 / p1.sum()
    t = np.clip(p3, 1e-4, 0.995) * v
    t = t / t.sum() * min(3, n)
    t = np.clip(t, 1e-4, 0.995) * v
    u_ = np.where(v, (w + 1e-12) ** A2 * t ** B2, 0.0)
    v_ = np.where(v, (w + 1e-12) ** A3 * t ** B3, 0.0)
    AI = _types(w, u_, v_, place_k)
    mw = np.where(v, 1.0 / np.where(ow > 0, ow, 1.0), 0.0)
    mw = mw / mw.sum()
    MH = _types(mw, mw, mw, place_k)
    MK, OE = {'単勝': mw}, {'単勝': np.where(v, ow, 0.0)}
    pm = np.where(v & (pl > 0), 2.0 / np.clip(pl + ph, 1e-9, None), 0.0)
    MK['複勝'] = pm / max(pm.sum(), 1e-12) * place_k
    OE['複勝'] = np.where(v, pl, 0.0)
    for c in ('馬連', '馬単', '3連複', '3連単'):
        o = od[c].astype(float)
        if c == '馬連':
            o = np.maximum(o, o.T)
        if c == '3連複':
            o = np.maximum.reduce([o.transpose(p) for p in [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]])
        m = np.where(o > 0, 1.0 / np.where(o > 0, o, 1.0), 0.0)
        m = m / (m.sum() / (2 if c == '馬連' else 6 if c == '3連複' else 1))
        MK[c], OE[c] = m, o
    o2 = od['ワイド'].astype(float)
    lo = np.maximum(o2[..., 0], o2[..., 0].T)
    hi = np.maximum(o2[..., 1], o2[..., 1].T)
    m = np.where(lo > 0, 2.0 / np.where(lo > 0, lo + hi, 1.0), 0.0)
    MK['ワイド'], OE['ワイド'] = m / (m.sum() / 2) * 3, lo
    out, axis = [], []
    for c in ['単勝'] + list(KINDS.values()):
        K = place_k if c == '複勝' else 3 if c == 'ワイド' else 1
        msk = _mask(c, v) & (MK[c] > 0) & (AI[c] > 0) & (OE[c] > 0)
        X = np.where(msk)
        if not len(X[0]):
            continue
        p = _mix(c, np.log(AI[c][X]), np.log(MK[c][X]), np.log(np.clip(MH[c][X], 1e-12, None)), K)
        oe, mk = OE[c][X], MK[c][X]
        if c == '単勝':
            axis = [int(h) for h in X[0][(p >= AX_P) & (p * oe >= AX_EV)]]
            if not axis:
                return [], []
            continue
        inc = np.zeros(len(p), bool)
        for h in axis:
            for x in X:
                inc |= x == h
        for i in np.where(inc & (p * oe >= LINE))[0]:
            out.append((c, '-'.join(str(int(x[i])) for x in X), float(p[i]), float(oe[i]), float(mk[i])))
    return axis, out


# ---------- 本番の読み口(便の値 → 配列) ----------
def _odds(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 else 0.0


def board_arrays(boards):
    """板 {券種: nar_odds_full_ticks.combos} → 研究の形の表(17 の 2・3 次元・ワイドは [..., 2] = 下限・上限)。
    並びは b53.BOARD と同じ([a, b, 倍率, …]・ワイドは [a, b, 下限, 人気, 上限]・3 連は [a, b, c, 倍率, …])。"""
    od = {}
    for k in BOARD_KINDS:
        c = KINDS[k]
        nn = 3 if k.startswith('sanren') else 2
        A = np.zeros((N17,) * nn + ((2,) if k == 'wide' else ()))
        for e in (boards or {}).get(k) or []:
            try:
                hs = tuple(int(x) for x in e[:nn])
            except (TypeError, ValueError):
                continue
            if any(h < 1 or h > N17 - 1 for h in hs) or len(e) <= nn:
                continue
            lo = _odds(e[nn])
            if k == 'wide':
                hi = _odds(e[4]) if len(e) > 4 else 0.0
                if lo > 0 and hi > 0:
                    A[hs + (0,)], A[hs + (1,)] = lo, hi
            elif lo > 0:
                A[hs] = lo
        od[c] = A
    return od


def race(p, win, place, boards):
    """1 レースの段 2。p = {馬番: (p1, p3)}(直前版の行)・win = {馬番: 単勝}・place = {馬番: [下限, 上限]}・boards = {券種: combos}。
    → 書く値 {'tag', 'axis': [馬番], 'n', 'cols', 券種: [[組, オッズ, 混ぜた率, 市場の率, 期待値], …]}(軸なし = axis 空・券種なし)
       か {'tag', 'why'}(作れない)。"""
    out = {'tag': tag()}
    nums = sorted(int(u) for u, o in (win or {}).items() if _odds(o) > 0)
    if any(u < 1 or u > N17 - 1 for u in nums):
        out['why'] = '馬番が 16 より大きい'
        return out
    miss = [u for u in nums if u not in p]
    if miss:
        out['why'] = f'直前版の行に無い馬 {len(miss)} 頭'
        return out
    a = {c: np.zeros(N17) for c in ('p1', 'p3', 'ow', 'pl', 'ph')}
    for u in nums:
        a['p1'][u], a['p3'][u] = float(p[u][0] or 0.0), float(p[u][1] or 0.0)
        a['ow'][u] = _odds(win[u])
        pv = (place or {}).get(u)
        if isinstance(pv, (list, tuple)) and pv:
            lo = _odds(pv[0])
            hi = _odds(pv[1]) if len(pv) > 1 else lo
            if lo > 0:
                a['pl'][u], a['ph'][u] = lo, (hi if hi > 0 else lo)
    ax, tk = select_arrays(a['p1'], a['p3'], a['ow'], a['pl'], a['ph'], board_arrays(boards))
    if ax is None:
        out['why'] = tk
        return out
    out['axis'] = ax
    out['n'] = len(nums)
    out['cols'] = ['組', 'オッズ', '混ぜた率', '市場の率', '期待値']
    inv = {v: k for k, v in KINDS.items()}
    for c, key, pr, oe, mk in tk:
        out.setdefault(inv[c], []).append([key, round(oe, 1), round(pr, 5), round(mk, 5), round(pr * oe, 3)])
    for k in KINDS:
        if k in out:
            out[k].sort(key=lambda r: -r[4])
    return out


def count(v):
    """ログ用の点数(券種の中身は出さない)"""
    if not isinstance(v, dict):
        return 0
    return sum(len(v.get(k) or []) for k in KINDS)
