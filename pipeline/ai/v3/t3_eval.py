# -*- coding: utf-8 -*-
"""第 3 版の共通部品(PREREG3 §2・§4・§5・§6): 学習・予想の出し方・当たり方の物差し・旧 AI との比べ方。3 日目に sha256 で固定する。

- 前日版 = 段 1〜3 の 29 列(FEATS_PRE)、当日版 = 29 列 + s4a_going・s4b_bw・s4b_bw_chg(FEATS_DAY)。
- 設定: Y1 = 葉 31・最小 100・木 400、Y3 = 葉 15・最小 100・木 1200(2 日目の格子。v3/t3_grid.json と一致を assert)。
- 初期値 z1 = logit(1/n)、z3 = logit(3/n)。予想 = σ(z + 模型の生の出力)。p1 = レース内で Σ = 1、p3 = max(Y3 の確率, p1)。
- ◎ = p1 最大(同じなら p3 大、次に馬番小)。○▲ = 2・3 位、△ = 4・5 位。
- 対数尤度 = レースあたり(全馬の Bernoulli の和 ÷ レース数、確率は [1e-6, 1−1e-6] に切る。大きいほど良い)。
- 区間 = 開催日(日付 × 場)単位のブートストラップ 2,000 回(seed 0)、95% = 2.5〜97.5% 点。率はレース数で割った比(再標本の中で計算)。
- 1 番人気 = pop = 1 の馬(無いレースは 1 番人気の率から外す)。入力には使わない。
- 旧 AI(§6): rid = 「場|日付|レース番号」、runner_number = 馬番。新 AI の表(取消・除外を除いた出走馬)と内側でつなぎ、
  出走しなかった馬を除いてから ◎ = 旧 AI の勝つ確率(b_*_win)最大(同じなら馬番小)。比べるレース = 新 AI の予想するレースのうち
  旧 AI のファイルにあるレース。差 = 新 − 旧(レースごとの対)。判定: 95% 区間の下限 > 0 →「上回った」、上限 < 0 →「下回った」、
  ほか「差は誤差の範囲」。記録用の旧 AI の対数尤度: p1 = b_*_win をレース内で Σ = 1、p3 = max(b_*_top3, p1)(新 AI と同じ出し方)。
  旧 AI のファイルに無い(または確率が空の)新 AI の出走馬がいるレースの数も書く。対数尤度の差は、その組の確率が全馬にある
  レースだけで出す(◎ の比べ方には全レースを含める)。
"""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from t3_day2_features import FEATS3

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
PRED_OLD = Path('C:/Users/kouki/nankan_ai/pred')
KEY = ['track', 'race_date', 'race_no']
FEATS_PRE = FEATS3[1] + FEATS3[2] + FEATS3[3]
FEATS_DAY = FEATS_PRE + FEATS3['4a'] + FEATS3['4b']
VERSIONS = {'pre': FEATS_PRE, 'day': FEATS_DAY}
VNAME = {'pre': '前日版', 'day': '当日版'}
CFG = {'Y1': (31, 100, 400), 'Y3': (15, 100, 1200)}
BASE = dict(objective='binary', learning_rate=0.03, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
            lambda_l2=10, seed=0, deterministic=True, num_threads=4, verbose=-1)
OLD = ['b_all', 'b_nankan']
BANDS = [(5, 8, '5〜8 頭'), (9, 12, '9〜12 頭'), (13, 99, '13 頭以上')]


def check_grid():
    g = json.loads((V3 / 't3_grid.json').read_text(encoding='utf-8'))
    assert tuple(g['Y1']) == CFG['Y1'] and tuple(g['Y3']) == CFG['Y3'] and g['kept'] == FEATS_PRE, g


def logit(p):
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-z))


def train(df, cols, target):
    assert len(cols) == len(set(cols)) and not {'pop', 'Y1', 'Y3', 'q', 'E_mid'} & set(cols)
    cfg = CFG[target]
    z = logit((1 if target == 'Y1' else 3) / df.n.to_numpy(float))
    prm = dict(BASE, num_leaves=cfg[0], min_data_in_leaf=cfg[1])
    return lgb.train(prm, lgb.Dataset(df[cols].astype(float), label=df[target].to_numpy(float), init_score=z),
                     num_boost_round=cfg[2])


def predict(m1, m3, X, cols):
    """p1・p3 を付けた X の写しを返す(n = そのレースの出走頭数の列)。"""
    n = X.n.to_numpy(float)
    r1 = sig(logit(1 / n) + m1.predict(X[cols].astype(float), raw_score=True))
    r3 = sig(logit(3 / n) + m3.predict(X[cols].astype(float), raw_score=True))
    p1 = r1 / pd.Series(r1, index=X.index).groupby([X[k] for k in KEY]).transform('sum').to_numpy()
    return X.assign(p1=p1, p3=np.maximum(r3, p1))


def marks(te, p1='p1', p3='p3'):
    """予想順位(1 始まり)と印。"""
    o = te.sort_values(KEY + [p1, p3, 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    rank = o.groupby(KEY, sort=False).cumcount() + 1
    te = te.assign(rank=rank.reindex(te.index))
    te['mark'] = te['rank'].map({1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}).fillna('')
    return te


def race_table(te, p1='p1', p3='p3'):
    """レースごと 1 行: ◎ の Y1・Y3、対数尤度、1 番人気の Y1・Y3。"""
    x = te.assign(_p1=np.clip(te[p1], 1e-6, 1 - 1e-6), _p3=np.clip(te[p3], 1e-6, 1 - 1e-6))
    x['ll1'] = x.Y1 * np.log(x._p1) + (1 - x.Y1) * np.log(1 - x._p1)
    x['ll3'] = x.Y3 * np.log(x._p3) + (1 - x.Y3) * np.log(1 - x._p3)
    g = x.groupby(KEY, sort=True)
    R = g[['ll1', 'll3']].sum()
    R['n'] = g.size()
    top = x.sort_values(KEY + [p1, p3, 'umaban'], ascending=[True, True, True, False, False, True],
                        kind='mergesort').groupby(KEY, sort=False).head(1).set_index(KEY)
    R['win'], R['top3'], R['top_uma'] = top.Y1, top.Y3, top.umaban
    f = x[x['pop'] == 1].drop_duplicates(KEY).set_index(KEY)
    R['fav_win'], R['fav_top3'] = f.Y1, f.Y3
    return R.reset_index()


def boot(R, cols, B=2000, seed=0):
    """開催日(日付 × 場)単位。cols ごとに (点, 下限, 上限)。値が NaN のレースはその列の分母から外す。"""
    cl = R.race_date.astype(str) + '|' + R.track
    codes, uniq = pd.factorize(cl)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(B, len(uniq)))
    cnt = np.stack([np.bincount(i, minlength=len(uniq)) for i in idx])  # B × 開催日: 選ばれた回数
    out = {}
    for c in cols:
        v = R[c].to_numpy(float)
        ok = ~np.isnan(v)
        s = np.bincount(codes[ok], weights=v[ok], minlength=len(uniq))
        k = np.bincount(codes[ok], minlength=len(uniq)).astype(float)
        est = cnt @ s / (cnt @ k)
        out[c] = (s.sum() / k.sum(), float(np.quantile(est, 0.025)), float(np.quantile(est, 0.975)))
    return out


def summary(R, B=2000):
    """物差しの一式(点と区間)。LL はレースあたり。"""
    b = boot(R, ['win', 'top3', 'll1', 'll3', 'fav_win', 'fav_top3'], B)
    base1 = (np.log(1 / R.n) + (R.n - 1) * np.log(1 - 1 / R.n)).mean()
    base3 = (3 * np.log(3 / R.n) + (R.n - 3) * np.log(1 - 3 / R.n)).mean()
    return dict(races=len(R), fav_races=int(R.fav_win.notna().sum()), base_ll1=base1, base_ll3=base3, **b)


def breakdown(R):
    """年ごと・場ごと・頭数の帯ごと(記録だけ・点だけ)。"""
    rows = []
    R = R.assign(year=R.race_date.astype(str).str[:4])
    for name, key in (('年', R.year), ('場', R.track)):
        for k, g in R.groupby(key):
            rows.append((name, k, len(g), g.win.mean(), g.top3.mean(), g.fav_top3.mean()))
    for lo, hi, lab in BANDS:
        g = R[(R.n >= lo) & (R.n <= hi)]
        rows.append(('頭数', lab, len(g), g.win.mean(), g.top3.mean(), g.fav_top3.mean()))
    return pd.DataFrame(rows, columns=['区分', '値', 'レース', '◎ 勝率', '◎ 3 着以内率', '1 番人気 3 着以内率'])


def load_old(months):
    """旧 AI の予想ファイル(§11 で固定)。封印を開ける日まで呼ばない。"""
    d = pd.concat([pd.read_parquet(PRED_OLD / f'{m}.parquet') for m in months], ignore_index=True)
    s = d.rid.str.split('|', expand=True)
    d['track'], d['race_date'], d['race_no'] = s[0], s[1], s[2].astype(int)
    d['umaban'] = d.runner_number.astype(int)
    return d


def compare_old(te, old, B=2000):
    """te = 新 AI の予想(p1・p3・Y1・Y3 つき、取消・除外なし)。旧 AI の 2 組それぞれと、レースごとの対で比べる。"""
    races_old = old[KEY].drop_duplicates()
    te = te.merge(races_old, on=KEY, how='inner')
    j = te.merge(old[KEY + ['umaban'] + [f'{o}_{t}' for o in OLD for t in ('win', 'top3')]],
                 on=KEY + ['umaban'], how='left')
    grp = [j[k] for k in KEY]
    oc = [f'{o}_{t}' for o in OLD for t in ('win', 'top3')]
    lack = int(j[j[oc].isna().any(axis=1).groupby(grp).transform('any')][KEY].drop_duplicates().shape[0])
    new = race_table(j)
    res = {'races': len(new), 'races_lacking_old_rows': lack}
    for o in OLD:
        w = j[f'{o}_win'].fillna(-1.0)  # ファイルに無い馬は ◎ にしない
        pw = j[f'{o}_win'].to_numpy(float)
        p1o = pw / pd.Series(pw, index=j.index).groupby([j[k] for k in KEY]).transform('sum').to_numpy()
        p3o = np.maximum(j[f'{o}_top3'].to_numpy(float), p1o)
        jo = j.assign(o_w=w, o_p1=p1o, o_p3=np.where(np.isnan(p3o), np.nan, p3o))
        top = jo.sort_values(KEY + ['o_w', 'umaban'], ascending=[True, True, True, False, True],
                             kind='mergesort').groupby(KEY, sort=False).head(1).set_index(KEY)
        R = new.set_index(KEY).copy()
        R['old_win'], R['old_top3'] = top.Y1, top.Y3
        miss = j[[f'{o}_win', f'{o}_top3']].isna().any(axis=1).groupby(grp).transform('any')
        ok = jo[~miss]  # 対数尤度の差は、その組の確率が全馬にあるレースだけ(足す馬の数をそろえる)
        ro = race_table(ok.assign(p1=ok.o_p1, p3=ok.o_p3)).set_index(KEY)
        R['d_top3'] = R.top3 - R.old_top3
        R['d_win'] = R.win - R.old_win
        R['d_ll1'] = R.ll1 - ro.ll1
        R['d_ll3'] = R.ll3 - ro.ll3
        R['d_fav_top3'] = R.top3 - R.fav_top3
        b = boot(R.reset_index(), ['top3', 'old_top3', 'd_top3', 'd_win', 'd_ll1', 'd_ll3', 'd_fav_top3'], B)
        lo, hi = b['d_top3'][1], b['d_top3'][2]
        b['verdict'] = '上回った' if lo > 0 else ('下回った' if hi < 0 else '差は誤差の範囲')
        res[o] = b
    return res


def fmt(t, d=3, pct=False):
    k = 100 if pct else 1
    return f"{t[0] * k:.{d}f}({t[1] * k:.{d}f}〜{t[2] * k:.{d}f})"
