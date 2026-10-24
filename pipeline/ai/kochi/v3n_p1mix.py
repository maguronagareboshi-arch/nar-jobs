# -*- coding: utf-8 -*-
"""他場版 v3n の画面の勝つ率を 3 着内率と混ぜて直す(決め 40・研究 nankan-ai-v3 src/f5_scripts/p1mix_judge.py・2026-10-15)。

  p1′ ∝ exp(a × ln p1 + b × logit q3) を R で合計 1。p1 = 勝つ率の直し(v3n_p1.follow)の後・q3 = E1・能検の後で max(q3, p1) の前の 3 着内率。
  q3 は [1e-4, 1 − 1e-4] で切る。出走 4 頭以下・空の値のある R は混ぜない(p1 のまま)。(a, b) = 朝 mo・直前 di で別(研究の全期間 2024-09〜2026-08)。
  変えるのは画面の勝つ率だけ。印(key の順)・meta.p1c(直す前の c1)は今のまま。行の meta に p1_raw(混ぜる前の p1)と p1mix の字を残す。
確かめ 2025-09〜2026-08: 朝 +0.0038 ± 0.0011・直前 +0.0037 ± 0.0011(1 R あたりの勝ち馬の対数尤度)。
"""
import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed
import sealed  # noqa: E402  定数は暗号化したリリース(公開のコードに置かない)

C = sealed.get('v3n_p1mix')
AB = C['AB']    # {'mo': [a, b], 'di': [a, b]}(決め 40)・'mo3'・'di3' = 決め 54 の木で学び直した値
TAG = C['TAG']  # 行の meta.p1mix の字
CLIP3 = 1e-4
MIN_N = 5


def mix(p1, q3, ver):
    """1 レース: 勝つ率 p1(合計 1)・3 着内率 q3 → 画面の勝つ率(合計 1)。ver = 'mo' / 'di'(決め 54 の行は 'mo3' / 'di3')。混ぜない R は p1 をそのまま返す。"""
    p1 = np.asarray(p1, float)
    q3 = np.asarray(q3, float)
    if len(p1) < MIN_N or len(q3) != len(p1) or not (np.isfinite(p1).all() and np.isfinite(q3).all()) or p1.sum() <= 0:
        return p1
    a, b = AB[ver]
    q = np.clip(q3, CLIP3, 1 - CLIP3)
    z = a * np.log(np.clip(p1 / p1.sum(), 1e-6, 1)) + b * (np.log(q) - np.log(1 - q))
    e = np.exp(z - z.max())
    return e / e.sum()
