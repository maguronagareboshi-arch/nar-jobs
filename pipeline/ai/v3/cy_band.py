# -*- coding: utf-8 -*-
"""調教の札(表示だけ・予想の計算には使わない)。2026-11-04 ユーザー承認「この形で進めて」(見本 nar-site/mock/cyeval-20261104.html)。

最終追いの cy_day_pct(v8cy_build = 同じ調教日・同じコース・同じ脚色で、分かった日 ≤ レースの日の追い切りのうち自分より 3F が速い本の割合。
5 本未満は欠け)を 4 段にして meta.runners[].cyb に入れる。
  4 = 好時計(〜0.2)/ 3 = まずまず(〜0.5)/ 2 = 平凡(〜0.8)/ 1 = 遅め / 欠けは入れない。
研究の数え(nankan-ai-v3・南関 4 場 2023-01〜2026-08・13.5 万頭)の 3 着以内: 好時計 37%・まずまず 31%・平凡 25%・遅め 20%(全体 27%)。
⛔時計・脚色・短評そのものは行に入れない(サイトの決まり §11.2・DESIGN #22 = 閲覧者には調教から作った札だけ)。
"""
import math

EDGES = (0.2, 0.5, 0.8)


def band(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    if v <= EDGES[0]:
        return 4
    if v <= EDGES[1]:
        return 3
    if v <= EDGES[2]:
        return 2
    return 1


def make(F):
    """F = t8.cy_feats の戻り(track・race_date・race_no・umaban・cy_day_pct …)。→ {(track, race_no, umaban): 1〜4}"""
    out = {}
    if F is None or 'cy_day_pct' not in getattr(F, 'columns', ()):
        return out
    for t, rn, u, v in zip(F.track, F.race_no, F.umaban, F.cy_day_pct):
        b = band(v)
        if b is not None:
            out[(str(t), int(rn), int(u))] = b
    return out


def attach(rows, bands):
    n = 0
    for row in rows:
        for x in row['meta']['runners']:
            b = bands.get((row['track'], int(row['race_no']), int(x['num'])))
            if b is not None:
                x['cyb'] = b
                n += 1
    return n
