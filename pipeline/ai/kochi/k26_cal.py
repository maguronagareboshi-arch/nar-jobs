# -*- coding: utf-8 -*-
"""他場版 v3n の 3 着内の率の直し(確かめ = v3 の out/v3n_cal.md・out/v3n_cal2.md)。

2026-10-11 その 2(第 5 版): 頭数の帯(〜8 頭・9〜10・11 頭〜)ごとに、log(混ぜた割合 s) → 3 着内の率 の単調な表
(選ぶ期間 2024-09〜2025-08 で単調回帰・点の間は直線・範囲の外は端の値)= k26_cal_table.json。
確かめ 2025-09〜26-08: 第 4 版の 2 次式の曲線より 全馬 3 着内 +11.2 ± 4.3 ×10^-4・3 × 割合より +20.5 ± 5.9・印と ◎ は変わらない。
(第 4 版の 2 次式は見込み 2% 以下の人気薄の率を逆に上げていた = 10/11 の本番で 1.1% → 1.4%)
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed
import sealed  # noqa: E402  表は暗号化したリリース(公開のコードに置かない)
TAB = json.loads(sealed.path('k26_cal_table.json').read_text(encoding='utf-8'))


def p3(s, n):
    """s = 1 レースの混ぜた割合(合計 1)・n = 頭数 → 3 着内の率"""
    t = TAB['〜8 頭' if n <= 8 else ('9〜10' if n <= 10 else '11 頭〜')]
    z = np.log(np.clip(np.asarray(s, float), 1e-6, 1))
    return np.clip(np.interp(z, t['x'], t['y']), 0.001, 0.999)
