# -*- coding: utf-8 -*-
"""決め 67-8(正しさの直し・南関 第33版・研究 nankan-ai-v3 src/f5_scripts/correct67_8.py・判定 2026-11-25 合格・out/correct67_8_judge.md)。

第32版 直前版は、前日の並び読みを決め 87 の重み(種 1954〜1956)に替えたため、直前版の勝つ率に新しい u_P が約 0.5 倍残り、
決め 82 の差と束を二重に数えて勝ちを落としていた。直し = 直前版の勝つ率の前(log)に − K678 × (u_P新 − u_P旧)。
  u_P新 = 前日版の表の sq_u(決め 87 の重み)・u_P旧 = 決め 63 の今の重み(seq2_live.SEQ2 の seqpre_*)で DAY_seq2.npz を読んだ値(= 第31版の u_P)。
  無い値は 0 にしてから引く(研究と同じ)。3 着内の率・前日版の率は変えない。
前日の便(v3_daily): 決め 87 で前日の並び読みを替えたレースに、u_P旧 を表の sq_u_old として残す(前日版の率には使わない)。
  → dayonpre77_live.write_base が土台の D77:upo に写し、そのレースの土台を D77:v = 33 にする。
直前の便(dayonpre77_live.apply_day): D77:v = 33 のレースで決め 82 が動いた時だけ、勝つ率の前に足す(meta.dp77.c678)= 南関 第33版 直前版。
定数(K678・ON678・TAG678)は暗号化したリリース v3-consts の consts.json の dp77(無ければ動かない = 第32版のまま)。
"""
import numpy as np
import pandas as pd

KEY = ['track', 'race_date', 'race_no']


def log0(*a):
    print('[c678]', *a, flush=True)


def consts():
    import dayonpre77_live
    C = dayonpre77_live.consts()
    if 'K678' not in C or 'ON678' not in C:
        raise KeyError('dp77 に K678・ON678 が無い')
    return C


def is_on(day):
    """その日(レースの日)が決め 67-8 の ON 以降か(定数が無ければ例外)。"""
    return str(day) >= str(consts().get('ON678') or '9999-12-31')


def tag():
    return consts().get('TAG678', '決め67-8 第33版')


def add_old(Sold, csv_path, log=log0):
    """前日版の表で sq_u のあるレース(4 頭以上)に u_P旧 = sq_u_old を足す(率・並びには触らない)。
    Sold = seqpre_live.load(seq2_live.SEQ2, DAY_seq2.npz)。前日の材料に無い馬がいるレースは足さない(列は空 = 0 扱い)。→ 足したレース数"""
    import seqpre_live
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'sq_u' not in x.columns:
        log('表に sq_u が無い(足さない)')
        return 0
    x['sq_u_old'] = np.nan
    n, miss = 0, 0
    for (tr, _, rno), g in x.groupby(KEY, sort=False):
        if len(g) <= 3 or not g.sq_u.notna().any():
            continue
        u = seqpre_live.resid(Sold, tr, rno, g.umaban.astype(int).to_numpy())
        if u is None:
            miss += 1
            continue
        x.loc[g.index, 'sq_u_old'] = u
        n += 1
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    log('u_P旧(第31版の前日の並び読み)を残した', n, 'R・足せない', miss, 'R')
    return n

