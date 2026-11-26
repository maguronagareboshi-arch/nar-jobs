# -*- coding: utf-8 -*-
"""他場の朝の便の回し直し(研究・2026-11-26・枝 wip/v3n-replay-1126 だけ)。公式の表から「その日より後」を消し、
mask=1 のときはその日のレースの走った後に分かる値(着順・時計・人気・馬体重・馬場・通過順・オッズなど)も空にする
= 本番の朝 7 時台に近い材料。mask=0 は消すのは翌日以降だけ(研究の作りと同じく今の DB の全部)。
  python -X utf8 ops/v3n_replay_mask.py <公式の表のフォルダ> <日付> <0|1>"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

d, day, mask = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == '1'
POST = {'runs': ['body_weight', 'finish', 'finish_note', 'time_sec', 'margin', 'last3f', 'popularity'],
        'races': ['weather', 'going', 'condition', 'race_last3f', 'corners'],
        'facts': ['c1', 'n1', 'c4', 'n4', 'first3f', 'win_odds_close']}
for t in ['runs', 'races', 'facts', 'jra']:
    f = d / f'{t}.parquet'
    if not f.exists():
        print(t, 'なし'); continue
    x = pd.read_parquet(f)
    rd = x.race_date.astype(str).str[:10]
    n0 = len(x)
    x = x[(rd < day) if t == 'jra' else (rd <= day)].copy()   # 中央の表は当日の走りを持たない
    m = 0
    if mask and t in POST:
        on = x.race_date.astype(str).str[:10] == day
        m = int(on.sum())
        for c in POST[t]:
            if c in x.columns:
                x[c] = x[c].astype(object).where(~on, None) if x[c].dtype == object else x[c].where(~on, np.nan)
    x.to_parquet(f, index=False)
    print(t, n0, '→', len(x), '・当日を空にした行', m)
