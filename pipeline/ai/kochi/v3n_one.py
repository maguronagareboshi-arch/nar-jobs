# -*- coding: utf-8 -*-
"""他場版 v3n 第 10 版(決め 32・2026-10-15)= 同じ作りの木を材料表 2014〜・学び 2015-01〜切りの前で(B15・v3 の out/v3n_2015_u.md・研究 v3n_2015_prod.py)。
第 9 版 = イ' 全国 1 本の木(決め 31・v3 の out/v3n_one_u.md・研究 src/f5_scripts/v3n_one.py pool・v3n_one_prod.py)。

  土台 = base-v1 の朝の材料(nar_ai_feat_run・当日の馬場・体重の列を抜いた 263 列)+ 場の材料 v_ 148 列(k1・k4・k8 + Glicko 18 + 血統 9・
  当日の馬場・天気を抜く)+ 場の番号 trk。帯広を除く全場の 2022-11〜で学び、対象 10 場の行は重み 2。
  3 着内 g3 = (2 値の木 3 本の平均 + 順位の木の R 内 softmax × 3)÷ 2・勝ち = 勝ちの木を R で合計 1 → 帯の表(1 年前の切りの木の当て)→ 合計 1。
  木は固定ファイル(暗号化リリース・年 1 回 9 月に学び直す = 決め 16)= V3N_ONE/v3n_one_model.json。
  γ と 3 着内の曲線(頭数の帯ごと・選び 2024-09〜25-08 で決めた)= v3n_one_p5.json(暗号化したリリース v3-consts の中・pipeline/ai/sealed.py で読む)。
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FORM = 'v3n-10: one15 (base-v1 + v_ + trk・2015〜) + seq-one15'
KEY = ['track', 'race_date', 'race_no', 'runner_number']
sys.path.append(str(HERE.parent))  # 末尾に足す = pipeline/ai の sealed
import sealed  # noqa: E402  表は暗号化したリリース(公開のコードに置かない)
P5 = json.loads(sealed.path('v3n_one_p5.json').read_text(encoding='utf-8'))
NB = [8, 10, 12, 99]


def load(path=None):
    """固定の木(JSON)→ dict(Booster 入り)。無ければ FileNotFoundError"""
    import lightgbm as lgb
    p = Path(path or os.environ.get('V3N_ONE', 'v3n_one')) / 'v3n_one_model.json'
    m = json.loads(p.read_text(encoding='utf-8'))
    m['_b'] = [lgb.Booster(model_str=s) for s in m['bins']]
    m['_r'] = lgb.Booster(model_str=m['rank'])
    m['_w'] = lgb.Booster(model_str=m['win'])
    return m


def feat_day(path, day, tracks):
    """nar_ai_feat_run(csv / csv.gz)のその日・その場の行 → base_v1.load_feat と同じ形(数値化・float32・rid・R 内の相対値)。
    相対値は R の中だけで計算する = 全期間を読んでから切るのと同じ値"""
    import base_v1 as B
    parts = []
    for c in pd.read_csv(path, low_memory=False, chunksize=200_000, dtype={'race_date': str, 'track': str}):
        parts.append(c[(c.race_date.str[:10] == day) & c.track.isin(tracks)])
    df = pd.concat(parts, ignore_index=True)
    if df.empty:
        return df
    for c in df.columns:
        if df[c].dtype == object and c not in ('track', 'race_date', 'horse_key', 'finish_note', 'updated_at'):
            df[c] = pd.to_numeric(df[c], errors='coerce')
    df['race_date'] = pd.to_datetime(df['race_date'].str[:10])
    num = [c for c in df.columns if df[c].dtype.kind == 'f']
    df[num] = df[num].astype('float32')
    df['rid'] = df['track'] + '|' + df['race_date'].dt.strftime('%Y-%m-%d') + '|' + df['race_no'].astype(str)
    return B.add_relative(df)


def predict(m, F, Vt):
    """F = feat_day の行・Vt = 場の材料(track・race_date(文字)・race_no・runner_number・元の列名)
    → F の鍵 + g3(3 着内の見込み)・pw_raw(R で合計 1)・pwg(帯の表の後 R で合計 1)"""
    import base_v1 as B
    X = F.copy()
    X['race_no'], X['runner_number'] = X.race_no.astype('int64'), X.runner_number.astype('int64')
    v = Vt.rename(columns={c: 'v_' + c for c in m['vcols']})
    v = v.assign(race_date=pd.to_datetime(v.race_date), race_no=v.race_no.astype('int64'), runner_number=v.runner_number.astype('int64'))
    v = v[KEY + [c for c in v.columns if c.startswith('v_')]]
    X = X.merge(v, on=KEY, how='left', validate='1:1')
    for c in m['vcols']:
        X['v_' + c] = X['v_' + c].astype('float32') if 'v_' + c in X.columns else np.full(len(X), np.nan, 'float32')
    X['trk'] = pd.Categorical(X.track, categories=m['trk'])
    assert X.trk.notna().all(), ('学びに無い場', sorted(set(X.track[X.trk.isna()])))
    cols = m['cols']
    miss = [c for c in cols if c not in X.columns]
    assert not miss, ('材料に無い列', miss[:10], len(miss))
    Xc = X[cols]
    pb = np.mean([b.predict(Xc) for b in m['_b']], axis=0)
    raw = pd.Series(m['_r'].predict(Xc), index=X.index)
    e = np.exp(raw - raw.groupby(X['rid']).transform('max'))
    prr = (e / e.groupby(X['rid']).transform('sum') * 3).clip(1e-4, 1 - 1e-4).to_numpy()
    out = X[KEY + ['rid']].copy()
    out['g3'] = (pb + prr) / 2
    out['pw_raw'] = B.race_norm(m['_w'].predict(Xc), X['rid'])
    out['pwg'] = B.race_norm(B.win_calibrate(out.pw_raw.to_numpy(), m['cal']), out['rid'])
    return out


def gamma(n):
    return P5['gamma'][next(i for i, k in enumerate(NB) if n <= k)]


def sharpen(s, n):
    """s = 1 レースの 3 着内の割合(合計 1)→ s^γ ÷ Σ(γ は頭数の帯ごと)"""
    t = np.power(np.clip(np.asarray(s, float), 1e-9, 1), gamma(n))
    return t / t.sum()


def p3(c, n):
    """c = sharpen の後の割合 → 3 着内の率(頭数 3 帯の単調の表・点の間は直線・外は端の値)"""
    t = P5['curve']['〜8 頭' if n <= 8 else ('9〜10' if n <= 10 else '11 頭〜')]
    return np.clip(np.interp(np.log(np.clip(np.asarray(c, float), 1e-6, 1)), t['x'], t['y']), 0.001, 0.999)
