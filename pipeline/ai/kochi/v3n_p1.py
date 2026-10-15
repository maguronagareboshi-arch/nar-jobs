# -*- coding: utf-8 -*-
"""他場版 v3n の勝つ率を 3着内の上乗せ(並び読み・能検)に付いて行かせる(決め 29・研究 nankan-ai-v3 src/f5_scripts/v3n_p1_fix.py・2026-10-14)。

  p1' ∝ c1 × exp(k × x)を R で合計 1。c1 = 今までの勝つ率(自分の木と base-v1 の混ぜ)・x = 並び読みの外した分 u + 能検 β·z
  (γ・3着内の曲線・E1 は率の直しなので入れない)。k = 朝と直前(meta.direct)で別の値(選び 2024-09〜25-08 で決めた・版ごと)。
  守り = 印を決めた後に、表示の p3 = max(p3, p1')(印は変えない・合計には戻さない)。
確かめ 2025-09〜26-08: 朝 +415.2 ± 27.4・直前 +478.8 ± 32.0(勝ち馬の対数尤度)。
朝の行の meta.p1c に直す前の c1 を残し、直前(v3n_last)は取消の後の馬で c1 を割り直してから x を掛け直す。
"""
import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed
import sealed  # noqa: E402  定数は暗号化したリリース(公開のコードに置かない)

# 版 → k。mo/di = 決め 29・mo1/di1 = 第 9 版 イ' 全国 1 本(決め 31・v3 の out/v3n_one_u.md)・mo2/di2 = 第 10 版 B15(決め 32・v3 の out/v3n_2015_u.md)
K = sealed.get('v3n_p1')['K']
TAG = sealed.get('v3n_p1')['TAG']  # 行の meta.p1f の字


def follow(c1, x, ver):
    """1 レース: 直す前の勝つ率 c1・持ち上げ x → 直した勝つ率(合計 1)"""
    c1 = np.asarray(c1, float)
    e = np.log(np.clip(c1 / c1.sum(), 1e-12, 1)) + K[ver] * np.nan_to_num(np.asarray(x, float))
    e = np.exp(e - e.max())
    return e / e.sum()
