# -*- coding: utf-8 -*-
"""決め 67-1(2026-11-03): 取りやめのレース(DB の races.cancelled のあるレース = 開催を取りやめて走っていない)の行を、
走り・レースの表から落とす(走歴に「走って最下位」として残さない)。研究 nankan-ai-v3 src/f5_scripts/correct67_1_run.py の
_cancel_filter と同じ決まり:
  - 鍵 = DB の写し db_races_{confirm・sealed・forward_t3}.parquet の cancelled が空でないレース(track・日付 10 字・R)。
    RAW の archive(〜2021)には取りやめの印が無い = 2022 年からだけ。取りやめのレースは走りの着順が全部空(段階 1 で 0 R の例外)。
  - 落とすのは走りの表(db_runs_*・公式の runs)とレースの表(db_races_*・公式の races)の行だけ。中止・取消・除外は別もの(触らない)。
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd

V3 = Path(os.environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
PARTS = ('confirm_2022-01_2025-08', 'sealed_2025-09_2026-08', 'forward_t3')
KEY = ['track', 'race_date', 'race_no']
_KEYS = {}


def keys(v3=None):
    """取りやめのレースの鍵の集合(置き場ごとに 1 回だけ読む)。確定と封印の写しは必ず要る・前向きの写しは有れば。"""
    v3 = Path(v3 or V3)
    if v3 not in _KEYS:
        import pyarrow.parquet as pq  # 表を読む時だけ(当日の便の入れ物は c67_tag しか使わない・11/3 昼に pyarrow が無く読み込みで落ちた)
        ra = []
        for p in PARTS:
            f = v3 / f'db_races_{p}.parquet'
            if p != 'forward_t3' or f.exists():
                ra.append(pq.read_table(f, columns=KEY + ['cancelled']).to_pandas())  # pyarrow で直接(読み手を包む照合の入口でも印を落とさない)
        ra = pd.concat(ra)
        ra = ra[ra.cancelled.notna()]
        _KEYS[v3] = set(zip(ra.track, ra.race_date.astype(str).str[:10], ra.race_no.astype(int)))
    return _KEYS[v3]


def drop(d, v3=None):
    """d(走りかレースの表)から取りやめのレースの行を落とす。鍵の列が無い表はそのまま。"""
    if not set(KEY) <= set(d.columns) or not len(d):
        return d
    c = keys(v3)
    k = zip(d.track, d.race_date.astype(str).str[:10], pd.to_numeric(d.race_no, errors='coerce').fillna(-1).astype(int))
    m = np.fromiter((x in c for x in k), bool, len(d))
    return d[~m].reset_index(drop=True) if m.any() else d


def c67_tag():
    """決め 67-1 の定数(c67_sand)が入っていればその記録の字(版の名前「南関 第22版」と meta.c67 に使う)・無ければ None。"""
    import sys
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import sealed
        c = sealed.get('c67_sand')
    except (FileNotFoundError, KeyError):
        return None
    return c['TAG'] if c['SPANS'] else None
