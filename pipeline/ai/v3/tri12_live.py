# -*- coding: utf-8 -*-
"""南関 3連単の参考の買い目(買い方 決め 12・2026-11-25 判定で合格・ユーザー 11/25「決め12の形で表示」)。
表示だけ(お金は賭けない・買い目の点数と成績に入れない)。研究 nankan-ai-v3 out/buy12_plan_1125.md・out/buy12_1125_judge.md。

  軸 = 10 分前の買いの模型の期待値(runners の ev)≥ AX_EV かつ 単勝 AX_LO 以上 AX_HI 未満の馬(買い方の形とは別に、この定数で決める)。
  券 = 軸を含む 3 頭の並び(軸は 1・2・3 着のどれでも)のうち、相手 2 頭の期待値がどちらも EV_S 以上 かつ AI の率 ≥ FLOOR の組を、
       割安さ(AI の率 ÷ 単勝だけから作る率)の高い順に N 点。同じ値は研究の並び(軸 1 着 → 2 着 → 3 着・相手は馬番の順)のまま。
       同じレースで同じ組は 1 枚(軸が 2 頭以上でも重ねない・研究の数え方と同じ)。
  AI の率と単勝から作る率の作りは研究 buy8_1121.build(= buyfin_live.combo_probs と同じ材料)。
数(線)は暗号化したリリース v3-consts の consts.json の tri12(公開のコードに数を置かない)。無い = 書かない。
"""
import sys
from itertools import permutations
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed

_C = None


def consts():
    """定数 tri12(無い = KeyError)"""
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('tri12')
    return _C


def tag(C=None):
    return (C or consts())['TAG']


def _tri_probs(ok):
    """ok = [(馬番, 期待値, 3 着内率, 単勝)](馬番の順)→ (AI の 3連単, 単勝から作る 3連単)の 17 × 17 × 17。"""
    import numpy as np
    import buyfin_live as BF
    um = np.array([u for u, *_ in ok]); ev = np.array([e for _, e, _, _ in ok], float)
    p3 = np.array([p for _, _, p, _ in ok], float); o = np.array([x for *_, x in ok], float)
    p = ev / o; nh = len(um)
    v = np.zeros(17, bool); v[um] = True
    w = np.zeros(17); w[um] = p / p.sum()
    t3 = np.zeros(17); t3[um] = np.clip(p3, 1e-4, .995)
    t3 = np.clip(t3 / t3.sum() * min(3, nh), 1e-4, .995) * v
    u = np.where(v, np.clip(w, 1e-9, None) ** 0.27 * np.clip(t3, 1e-9, None) ** 0.85, 0.0)
    vv = np.where(v, np.clip(w, 1e-9, None) ** -0.06 * np.clip(t3, 1e-9, None) ** 1.02, 0.0)
    qx = (1 / o) / (1 / o).sum(); pm = np.zeros(17); pm[um] = qx
    return BF._tensors(w, u, vv)[1], BF._tensors(pm, pm, pm)[1]


def race(rows, C=None):
    """rows = [(馬番, 期待値, 3 着内率, 単勝)](便がいま決めた全頭・丸めない値)→ (軸の馬番, [組の字 '1着-2着-3着'])。5 頭未満・馬番 17 以上は ([], [])。"""
    import numpy as np
    C = C or consts()
    ok = sorted((int(u), e, p, o) for u, e, p, o in rows if e is not None and p is not None and o is not None and o > 0)
    if len(ok) < 5 or any(u > 16 for u, *_ in ok):
        return [], []
    T3, M3 = _tri_probs(ok)
    um = [u for u, *_ in ok]; ev = {u: e for u, e, _, _ in ok}
    axes, out, seen = [], [], set()
    for a, e, _, o in ok:
        if not (e >= C['AX_EV'] and C['AX_LO'] <= o < C['AX_HI']):
            continue
        axes.append(a)
        oth = [x for x in um if x != a]
        od = list(permutations(oth, 2))
        cs = [(a, x, y) for x, y in od] + [(x, a, y) for x, y in od] + [(x, y, a) for x, y in od]
        ix = np.array(cs)
        prob = T3[ix[:, 0], ix[:, 1], ix[:, 2]]; mkt = M3[ix[:, 0], ix[:, 1], ix[:, 2]]
        pe = np.tile(np.array([min(ev[x], ev[y]) for x, y in od]), 3)
        el = (pe >= C['EV_S']) & (prob >= C['FLOOR'])
        sc = np.where(el, prob / np.clip(mkt, 1e-12, None), -np.inf)
        oo = np.argsort(-sc, kind='stable')
        for i in oo[:min(int(C['N']), int(el.sum()))]:
            k = '-'.join(str(int(z)) for z in cs[int(i)])
            if k not in seen:
                seen.add(k); out.append(k)
    return axes, out
