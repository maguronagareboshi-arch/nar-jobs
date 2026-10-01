# -*- coding: utf-8 -*-
"""第 10 版 = 第 9 版 + 前に捨てた材料の前日版 51 本(v31_bundle.feats51)の上乗せ。ユーザー承認 2026-10-01。
上乗せは 3 着内(p3)と勝つ率(p1)の 2 つ。段 2 の対数オッズに各乱数の raw_score の平均を足してから、p1 を合計 1・p3p を合計 3 に直す。
模型 = V3_MODELS の t10_up.json・t10_up_{p3,p1}_s{0,1,2}.txt(nankan-ai-v3 src/f5_scripts/t10_check.py final・学び 2016〜2026-08)。
研究の確かめ: nankan-ai-v3 out/t10_check.md・out/t10_prod.md(段 2 の内側に足す形で 2025-07〜2026-08 全馬 3 着内 +9.2 ± 3.0・勝ち馬 +8.6 ± 2.8)。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

Q5 = ['track', 'race_date', 'race_no', 'umaban']


def keys(D):
    D = D.copy()
    D['race_date'] = D.race_date.astype(str).str[:10]
    D['race_no'] = pd.to_numeric(D.race_no).astype(int)
    D['umaban'] = pd.to_numeric(D.umaban).astype(int)
    return D


def load(md):
    import lightgbm as lgb
    md = Path(md)
    meta = json.loads((md / 't10_up.json').read_text(encoding='utf-8'))
    feats = [c.replace(':', '_') for c in meta['feats']]
    # model_str で読む(手元の日本語のパスでも読める)
    B = {t: [lgb.Booster(model_str=(md / Path(f).name).read_text(encoding='utf-8')) for f in fs] for t, fs in meta['targets'].items()}
    return feats, B


def uplift(day, h, races, md, log=print):
    """→ (F51, U)。F51 = Q5 + 51 列(v31 と同じ)・U = Q5 + u_p3・u_p1。失敗は呼び手が受ける。"""
    import v31_bundle
    F = keys(v31_bundle.feats51(day, h, races, log=log))
    feats, B = load(md)
    miss = [c for c in feats if c not in F.columns]
    assert not miss, f'51 本に無い列 {miss}'
    X = F[feats].to_numpy(float)
    U = F[Q5].copy()
    for t, ms in B.items():
        U['u_' + t] = np.mean([m.predict(X, raw_score=True) for m in ms], axis=0)
    return F, U
