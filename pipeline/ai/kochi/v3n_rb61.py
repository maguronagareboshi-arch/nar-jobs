# -*- coding: utf-8 -*-
"""他場版 v3n 第 12 版(決め 61・2026-10-30 採用・v3 の out/v3n_rb61_judge.md・研究 src/f5_scripts/v3n_rb61_prod.py)。

1. 2 本目の木 M(今の木と同じ材料・作り・本数 2 値 1700 × 3・順位 760・勝ち 1040・学びは切りの前 2 年だけ)= V3N_RB61/v3n_one_model.json
   (暗号化リリース・年 1 回 9 月に今の木と一緒に学び直す)。当ては v3n_one.predict と同じ。勝ちの帯の表は今の木と同じ表。
2. 混ぜ: 3 着内 = 今の木の p5(γ・曲線の後)と M の p5(M の γ・曲線)を logit で (1 − W) : W。勝つ率 c1 = 対数で (1 − W) : W を R で割り直す。
   並び読み u・E1・能検・勝つ率の直し・混ぜ(決め 40)・決め 41 は今までどおりその後に(勝つ率の直しの k だけ混ぜた形で決めた値)。
3. 最近の内外の有利: 場 × 枠の群(枠番の R の中の位置で 内 ≤ 1/3・中 ≤ 2/3・外)ごとに、その日を含まない前 WIN 日の行の
   r = Σ(実際の 3 着内 − 直す前の表示の率 G)・w = Σ G(1 − G) から a = clip(r ÷ (w + LAM), −1, 1)。
   a を印の率の logit と勝つ率の対数の両方に足し(勝つ率は R で割り直す)、表示の率 = max(両方)・印は直した印の率の順。
   窓の G は「その日に出した版の率」= 行の meta.rb61.g0(第 12 版の行)・無い行(第 11 版)は meta.runners の p3。朝は朝の行・直前は直前の行
   (直前の行が無い R は朝の行)。答えは公式の runs(着順のある馬・取消・中止などの馬を除く・6 頭以上の R)。
定数(W・WIN・LAM・M の γ と曲線・k)は暗号化したリリース v3-consts の consts.json の v3n_rb61(公開のコードに数を置かない)。
"""
import datetime as dt
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed
import sealed  # noqa: E402

C = sealed.get('v3n_rb61')
W, WIN, LAM = float(C['W']), int(C['WIN']), float(C['LAM'])
TAG = C['TAG']                 # 行の meta.rb61.tag
NB = C['nb']
GROUPS = ('内', '中', '外')
MIN_N = 6                      # 窓に数える R の頭数(判定の数える表と同じ)


def load(path=None):
    """2 本目の木(v3n_one と同じ形の JSON)。無ければ FileNotFoundError"""
    import v3n_one
    return v3n_one.load(path or os.environ.get('V3N_RB61', 'v3n_rb61'))


def sharpen(s, n):
    """M の 3 着内の割合 → s^γ ÷ Σ(γ は M の頭数の帯ごと)"""
    g = C['gamma'][next(i for i, k in enumerate(NB) if n <= k)]
    t = np.power(np.clip(np.asarray(s, float), 1e-9, 1), g)
    return t / t.sum()


def p3(c, n):
    """M の割合 → 3 着内の率(M の頭数 3 帯の曲線)"""
    t = C['curve']['〜8 頭' if n <= 8 else ('9〜10' if n <= 10 else '11 頭〜')]
    return np.clip(np.interp(np.log(np.clip(np.asarray(c, float), 1e-6, 1)), t['x'], t['y']), 0.001, 0.999)


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sig(x):
    return 1 / (1 + np.exp(-x))


def lmix(a, b):
    """3 着内の率: 今の木 a と M の b を logit で (1 − W) : W"""
    return sig((1 - W) * lg(a) + W * lg(b))


def cmix(a, b):
    """1 レースの勝つ率: 対数で (1 − W) : W → 合計 1"""
    v = np.exp((1 - W) * np.log(np.clip(np.asarray(a, float), 1e-9, 1)) + W * np.log(np.clip(np.asarray(b, float), 1e-9, 1)))
    return v / v.sum()


def groups(gates):
    """1 レースの枠番 → 内・中・外(枠番の R の中の位置・判定の add_gt と同じ)。読めない枠は None"""
    g = pd.to_numeric(pd.Series(list(gates)), errors='coerce').astype(float)
    rel = (g - 1) / max(float(g.max()) - 1, 1) if g.notna().any() else g
    return [None if pd.isna(r) else ('内' if r <= 1 / 3 else '中' if r <= 2 / 3 else '外') for r in rel]


def shift(fin, q, a):
    """1 レース: 印の率 fin・勝つ率 q(合計 1)・馬ごとの a → (fin', q')。a は logit と対数に足す・q' は合計 1"""
    a = np.nan_to_num(np.asarray(a, float))
    f2 = sig(lg(fin) + a)
    v = np.clip(np.asarray(q, float), 1e-9, 1) * np.exp(a)
    return f2, v / v.sum()


def window_rows(sb_get, day, timing):
    """前 WIN 日の v3n-1 の行 → 馬ごとの G(DataFrame: track・race_date・race_no・umaban・G・src)。
    timing='morning' は朝の行・'last' は直前の行(無い R は朝の行)。通信量を抑えて runners と g0 だけ読む"""
    d0 = (dt.date.fromisoformat(day) - dt.timedelta(days=WIN)).isoformat()
    tm = 'morning' if timing == 'morning' else 'morning,last'
    path = (f'/rest/v1/nar_ai_marks?select=track,race_date,race_no,timing,runners:meta->runners,g0:meta->rb61->g0'
            f'&model=eq.v3n-1&timing=in.({tm})&race_date=gte.{d0}&race_date=lt.{day}&order=race_date,track,race_no,timing')
    out, off = [], 0
    while True:
        r = sb_get(f'{path}&limit=1000&offset={off}')
        out += r
        if len(r) < 1000:
            break
        off += 1000
    best = {}
    for r in out:   # 直前の行があれば直前を使う(並び順には頼らない)
        k = (r['track'], str(r['race_date'])[:10], int(r['race_no']))
        if timing == 'morning' and r['timing'] != 'morning':
            continue
        if k not in best or r['timing'] == 'last':
            best[k] = r
    rows = []
    for (t, d, rn), r in best.items():
        g0 = r.get('g0') or {}
        for x in (r.get('runners') or []):
            n = int(x['num'])
            g = g0.get(str(n), x.get('p3'))
            if g is not None:
                rows.append((t, d, rn, n, float(g), 'g0' if str(n) in g0 else 'p3', r['timing']))
    return pd.DataFrame(rows, columns=['track', 'race_date', 'race_no', 'umaban', 'G', 'src', 'timing'])


def answers(runs):
    """公式の runs → 数える馬(着順のある馬・取消・中止などは除く・6 頭以上の R)と 3 着内・枠の群(数える馬の中の枠番の位置)"""
    ru = runs[['track', 'race_date', 'race_no', 'runner_number', 'gate', 'finish', 'finish_note']].copy()
    ru['race_date'] = ru.race_date.astype(str).str[:10]
    ru['umaban'] = pd.to_numeric(ru.runner_number, errors='coerce')
    ru['fin'] = pd.to_numeric(ru.finish, errors='coerce')
    ru = ru[ru.umaban.notna() & ru.fin.notna() & (ru.finish_note.fillna('').astype(str).str.strip() == '')].copy()
    ru['race_no'], ru['umaban'] = ru.race_no.astype(int), ru.umaban.astype(int)
    ru = ru.drop_duplicates(['track', 'race_date', 'race_no', 'umaban'])
    R = ru.groupby(['track', 'race_date', 'race_no'])
    ru = ru[R.umaban.transform('size') >= MIN_N].copy()
    g = pd.to_numeric(ru.gate, errors='coerce').astype(float)
    mx = g.groupby([ru.track, ru.race_date, ru.race_no]).transform('max')
    rel = (g - 1) / np.maximum(mx - 1, 1)
    ru['gt'] = np.select([rel <= 1 / 3, rel <= 2 / 3], ['内', '中'], '外')
    ru.loc[g.isna(), 'gt'] = None
    ru['Y3'] = (ru.fin <= 3).astype(float)
    return ru[['track', 'race_date', 'race_no', 'umaban', 'gt', 'Y3']]


def table(G, ans, day):
    """馬ごとの G と答え → その日の a(dict (場, 群) → a)と数(判定の shift_tab と同じ式・その日を含まない前 WIN 日)"""
    D = G.merge(ans, on=['track', 'race_date', 'race_no', 'umaban'], how='inner')
    D = D[D['gt'].notna()]
    D = D[D.race_date < day]
    p = np.clip(D.G.to_numpy(float), 1e-6, 1 - 1e-6)
    D = D.assign(r=D.Y3 - p, w=p * (1 - p), dn=pd.to_datetime(D.race_date))
    s = D.groupby(['track', 'gt', 'dn'])[['r', 'w']].sum().reset_index()
    T, today = {}, pd.Timestamp(day)
    for (t, g), x in s.groupby(['track', 'gt']):
        x = pd.concat([x[['dn', 'r', 'w']], pd.DataFrame({'dn': [today], 'r': [0.0], 'w': [0.0]})]).set_index('dn').sort_index()
        c = x.rolling(f'{WIN}D', closed='left').sum().fillna(0).loc[today]
        T[(t, g)] = float(np.clip(c.r / (c.w + LAM), -1, 1))
    st = {'rows': int(len(D)), 'R': int(D.groupby(['track', 'race_date', 'race_no']).ngroups), 'days': int(D.race_date.nunique()),
          'g0': int((D.src == 'g0').sum()), 'p3': int((D.src == 'p3').sum()),
          'no_ans_R': int(G[['track', 'race_date', 'race_no']].drop_duplicates().merge(
              ans[['track', 'race_date', 'race_no']].drop_duplicates(), how='left', indicator=True)._merge.eq('left_only').sum())}
    return T, st


def tables(sb_get, runs, day, log=print):
    """朝の便で 1 回: 朝の a と直前の a を作る(直前の便は朝の行の meta.rb61 から読む = 5 分おきの周で DB を読まない)"""
    ans = answers(runs)
    out = {}
    for tm in ('morning', 'last'):
        G = window_rows(sb_get, day, tm)
        T, st = table(G, ans, day) if len(G) else ({}, {'rows': 0})
        out[tm] = (T, st)
        log('有利の直し', tm, '窓の行', st, '・a', {f'{t}{g}': round(v, 3) for (t, g), v in sorted(T.items())})
    return out
