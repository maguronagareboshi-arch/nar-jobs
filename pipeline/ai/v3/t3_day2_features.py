# -*- coding: utf-8 -*-
"""第 3 版 2 日目(PREREG3 §2・§3・§9): オッズを見ない予想 AI の材料の表とリーク検査。探索 2014〜2021 だけ。

  py -3.12 -X utf8 src/t3_day2_features.py         # 材料の表 → v3/feat_t3_explore.parquet
  py -3.12 -X utf8 src/t3_day2_features.py leak    # リーク検査(抜き取り 20 日)→ out/t3_day2_leak.md

- 材料は day2_features.py の build をそのまま呼ぶ(直さない)。対象の馬は着順から作る(targets() は使わない)。
- 予想するレース = 南関 4 場・取消と除外を除く出走 5 頭以上・着順が 1 頭でもある。n = そのレースの出走頭数。
- Y1 = 着順 1(同着は両方)、Y3 = 着順 ≤ 3(中止など着順なしは 0)。
- build に渡すオッズの列(q・plc_lo・plc_hi)は空、E_mid = 3/n、K = 3。騎手・調教師の元も同じ作り方(南関の全出走)。
  → s2_jae・s2_tae は「前日まで 365 日の 3 着以内の数 ÷ 頭数だけの見込み」の log になる(名前を s2_jnaive・s2_tnaive に変える)。
- build の出力から q・plc_lo・plc_hi・E_mid・s4_rest_bw を消す。名前の付け替え: s4_cw_chg → s3_cw_chg、s3_going → s4a_going。
  足す列: s3_cw(今回の斤量)・s4b_bw(今回の馬体重)・s4b_bw_chg(今回の増減)。どれも当日の行の出走表の値。
- 比べる相手だけの列: pop(走りの表の popularity)。学習には入れない(FEATS3 に入らないことを assert)。
出力 = C:/Users/kouki/nankan_ai/v3/feat_t3_explore.parquet(2015〜2021 の予想するレースの馬)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from day2_features import ENTRY_COLS, KEY, NANKAN, RACE_COLS, build, load_sources  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
FEATS3 = {
    1: ['s1_c4rel', 's1_l3rank', 's1_tdiff', 's1_front', 's1_dchg', 's1_debut'],
    2: ['s2_jnaive', 's2_tnaive', 's2_jchg'],
    3: ['s3_ti_prev', 's3_ti_mean3', 's3_ti_max5', 's3_l3i_prev', 's3_l3i_mean3', 's3_l3i_max5', 's3_finrel5',
        's3_class', 's3_class_chg', 's3_gate', 's3_track', 's3_dist', 's3_course_top3', 's3_age', 's3_sex',
        's3_rest', 's3_starts', 's3_n', 's3_cw', 's3_cw_chg'],
    '4a': ['s4a_going'],
    '4b': ['s4b_bw', 's4b_bw_chg'],
}
BANNED = {'q', 'plc_lo', 'plc_hi', 'E_mid', 'pop', 'popularity', 'win', 'Y1', 'Y3', 'finish'}
RENAME = {'s2_jae': 's2_jnaive', 's2_tae': 's2_tnaive', 's4_cw_chg': 's3_cw_chg', 's3_going': 's4a_going'}


def targets3(h):
    """南関の予想するレースの出走馬(2014〜2021)。E_mid = 3/n・Y3 は着順から。"""
    r = h[h.track.isin(NANKAN) & ~h.finish_note.isin(['取消', '除外'])].copy()
    g = r.groupby(KEY)
    r['n'] = g.umaban.transform('size')
    has_fin = g.finish.transform(lambda s: s.notna().any()).astype(bool)
    r = r[(r.n >= 5) & has_fin].copy()
    df = r[KEY + ['umaban', 'n', 'finish', 'popularity']].copy()
    df['Y1'] = (df.finish == 1).astype(int)
    df['Y3'] = (df.finish <= 3).astype(int)
    df['K'] = 3
    df['E_mid'] = 3 / df.n
    df['q'] = df['plc_lo'] = df['plc_hi'] = np.nan
    df['year'] = df.race_date.str[:4].astype(int)
    df['meet'] = np.nan
    return df.rename(columns={'popularity': 'pop'}).reset_index(drop=True)


def finish_table(X, h, tg):
    X = X.rename(columns=RENAME).drop(columns=['q', 'plc_lo', 'plc_hi', 'E_mid', 's4_rest_bw'])
    day = h[KEY + ['umaban', 'carried_weight', 'body_weight', 'body_weight_change']].drop_duplicates(KEY + ['umaban'])
    X = X.merge(day, on=KEY + ['umaban'], how='left')
    X['s3_cw'] = X.pop('carried_weight').astype(float)
    X['s4b_bw'] = X.pop('body_weight').astype(float)
    X['s4b_bw_chg'] = X.pop('body_weight_change').astype(float)
    X = X.merge(tg[KEY + ['umaban', 'Y1', 'pop']], on=KEY + ['umaban'], how='left')
    allf = sum(FEATS3.values(), [])
    assert not BANNED & set(allf), 'オッズ・結果の列が材料に入っている'
    miss = [c for c in allf if c not in X.columns]
    assert not miss, miss
    return X


def main():
    h = load_sources()
    tg = targets3(h)
    X, coef = build(h, tg[tg.race_date >= '2015-01-01'].reset_index(drop=True), tg)
    X = finish_table(X, h, tg)
    X.to_parquet(V3 / 'feat_t3_explore.parquet', index=False)
    allf = sum(FEATS3.values(), [])
    print('rows', len(X), 'races', X[KEY].drop_duplicates().shape[0], 'years', sorted(X.year.unique()), 'coef', round(coef, 5))
    print('Y1 平均', round(X.Y1.mean(), 4), 'Y3 平均', round(X.Y3.mean(), 4), '1/n 平均', round((1 / X.n).mean(), 4))
    print('missing', X[allf].isna().mean().round(3).to_dict())


def leak():
    """PREREG3 §9: 抜き取り 20 日(2016〜2021 の開催日・seed 0)。当日以降の行を消し(当日は出走表の列だけ)作り直して比べる。
    比べるのは段 1〜3 の列(段 4 は当日の行から取るので対象外)。"""
    h = load_sources()
    tg = targets3(h)
    full = pd.read_parquet(V3 / 'feat_t3_explore.parquet')
    feats = FEATS3[1] + FEATS3[2] + FEATS3[3]
    days = np.sort(np.random.default_rng(0).choice(np.sort(tg[tg.race_date >= '2016-01-01'].race_date.unique()), 20, replace=False))
    L = ['# 第 3 版 2 日目: リーク検査(PREREG3 §9)', '',
         '抜き取り 20 日: 走歴・騎手調教師の元から race_date ≥ 当日 の行を消し、当日は出走表の列だけを残して作り直す。',
         f'比べる材料 {len(feats)} 列(段 1〜3)。一致 = 両方欠損、または差の絶対値 ≤ 1e-9。', '',
         '| 日 | 頭 | 一致したセル | 全セル | 一致 % |', '|---|---|---|---|---|']
    tot = [0, 0]
    for d in days:
        ent = h.loc[h.race_date == d, KEY + ['umaban', 'hid'] + ENTRY_COLS + RACE_COLS + ['body_weight']]
        Xd, _ = build(h[h.race_date < d], tg[tg.race_date == d].reset_index(drop=True), tg[tg.race_date < d], ent=ent)
        Xd = finish_table(Xd, ent.assign(body_weight=ent.body_weight), tg)
        a = full[full.race_date == d].set_index(KEY + ['umaban'])[feats].sort_index()
        b = Xd.set_index(KEY + ['umaban'])[feats].sort_index()
        assert a.index.equals(b.index), d
        A, Bv = a.to_numpy(float), b.to_numpy(float)
        eq = (np.isnan(A) & np.isnan(Bv)) | (np.abs(A - Bv) <= 1e-9)
        tot[0] += int(eq.sum()); tot[1] += eq.size
        bad = [f for f, k in zip(feats, eq.all(0)) if not k]
        L.append(f'| {d} | {len(a)} | {int(eq.sum()):,} | {eq.size:,} | {100 * eq.mean():.2f}' + (f'(違う列: {"・".join(bad)})' if bad else '') + ' |')
        print(L[-1], flush=True)
    L += ['', f'計: {tot[0]:,} / {tot[1]:,} = {100 * tot[0] / tot[1]:.2f} %']
    (REPO / 'out/t3_day2_leak.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(L[-1])


if __name__ == '__main__':
    leak() if sys.argv[1:] == ['leak'] else main()
