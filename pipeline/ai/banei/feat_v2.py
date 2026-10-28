# -*- coding: utf-8 -*-
"""ばんえい 第 2 版の材料(区間タイム・通過順・発走時刻)= 第 1 版の表に足す列(ばんえい 決め 1 §5 第 2 版・仮説 3)。

  py -3.12 -X utf8 src/banei/feat_v2.py             # 表を作る(feat_v1.parquet + 新しい列 → feat_v2.parquet)
  py -3.12 -X utf8 src/banei/feat_v2.py --leakcheck  # 切った日で作り直して一致を見る

元: 競馬ブックの成績 v3/banei_kb/kb_runs.parquet(2017-02〜・前半・障害・後半タイム = 整数の秒・通過順 3 つ・発走時刻)。
    公式とは 日付・R・馬番 でつなぐ(100% つながる・out/banei_kb_parse.md)。
通過順の地点(区間タイムの順位との順位相関で確かめた): pass1 = 第 1 障害(0.33)・pass2 = 第 2 障害の手前(前半タイムの順位と 0.986)・
    pass3 = 第 2 障害を越えた所(前半 + 障害の順位と 0.993)。
漏れの決まりは feat_v1 と同じ:
  - 馬の履歴・率は全部「前の日まで」(merge_asof の allow_exact_matches=False)。
  - 区間タイムを重量・水分・組で直す係数は学びの期間(2017-02〜2022-03 の公式 + 競馬ブック)だけで作る(feat_v2_base.json)。
  - 日ごとの馬場差(その日の完走馬の中央値)は前走以前の値の直しにだけ使う。同じ日の前のレースは使わない。
  - 発走時刻は出馬表で前から分かる値(2017 年は欄が空 = 他の年の同じ月・同じ R の中央値で埋める)。
  - 完走していない馬(中止・失格・取消)の区間タイムは壊れている(0 や負)ので使わない。
"""
# 2026-10-28 nar-jobs に写した(v3 の src/banei/feat_v2.py の写し・計算は同じ)。変えたのは置き場(環境変数 BANEI_V3)と、研究だけの関数を外したこと。
import json
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, __file__.rsplit('\\', 1)[0].rsplit('/', 1)[0])
import feat_v1 as f1  # noqa: E402

V3 = f1.V3
OUT = f1.OUT
KB = OUT + 'kb_runs.parquet'
SEG_TRAIN = ('2017-02-01', '2022-04-01')
LEARN2 = ('2017-04-01', '2022-04-01')   # 第 2 版の学び(§A 直す 2)
NL = 10
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)
SEGS = {'f': 'seg_front', 'o': 'seg_obst', 'b': 'seg_back'}


def load_kb(cutoff=None):
    k = pd.read_parquet(KB, columns=['race_date', 'race_no', 'umaban', 'finish', 'seg_front', 'seg_obst', 'seg_back',
                                     'pass1', 'pass2', 'pass3', 'hasso_time'])
    k = k.rename(columns={'umaban': 'runner_number', 'finish': 'kb_finish'})
    if cutoff is not None:
        k = k[k.race_date <= cutoff].copy()
        d = k.race_date == cutoff
        k.loc[d, ['kb_finish', 'seg_front', 'seg_obst', 'seg_back', 'pass1', 'pass2', 'pass3']] = np.nan
    return k.drop_duplicates(['race_date', 'race_no', 'runner_number'])


def start_minutes(k):
    """レースごとの発走時刻(分)。欄の無いレース(2017 年など)は、同じ月・同じ R の他のレースの中央値で埋める。"""
    r = k.drop_duplicates(['race_date', 'race_no'])[['race_date', 'race_no', 'hasso_time']].copy()
    hm = r.hasso_time.str.extract(r'(\d+):(\d+)').astype(float)
    r['st'] = hm[0] * 60 + hm[1]
    r['mon'] = r.race_date.str[5:7]
    med = r.groupby(['mon', 'race_no']).st.median()
    r['st'] = r.st.fillna(pd.Series(list(zip(r.mon, r.race_no)), index=r.index).map(med))
    return r[['race_date', 'race_no', 'st']]


def sunset_min(dates):
    """帯広(北緯 42.92・東経 143.2)の日の入りの時刻(日本時間の分・近似式)。"""
    doy = dates.dt.dayofyear.values.astype(float)
    lat = np.radians(42.92)
    dec = np.radians(23.44) * np.sin(2 * np.pi * (284 + doy) / 365)
    cw = (np.sin(np.radians(-0.833)) - np.sin(lat) * np.sin(dec)) / (np.cos(lat) * np.cos(dec))
    w0 = np.degrees(np.arccos(np.clip(cw, -1, 1)))
    B = 2 * np.pi * (doy - 81) / 364
    eot = 9.87 * np.sin(2 * B) - 7.53 * np.cos(B) - 1.5 * np.sin(B)
    return 12 * 60 + w0 * 4 - (143.2 - 135) * 4 - eot


def fit_seg(H):
    """区間タイムの log を 水分の帯・重量の帯・組 で当てる(学びの期間だけ・feat_v1.fit_base と同じ形)。"""
    t = H[H.seg_ok & (H.race_date >= SEG_TRAIN[0]) & (H.race_date < SEG_TRAIN[1]) & H.going_f.notna()]
    X = pd.get_dummies(pd.DataFrame({'g': f1.gbin(t.going_f).astype(str), 'w': (np.clip(t.carried_weight, 460, 900) // 20 * 20).astype(int).astype(str),
                                     'c': t.cls_key}), drop_first=False).astype(float)
    out = {'n': int(len(t))}
    for s, col in SEGS.items():
        beta, *_ = np.linalg.lstsq(X.values, np.log(t[col].values), rcond=None)
        out[s] = dict(zip(X.columns, beta))
    return out


def seg_pred(H, coef):
    g = 'g_' + f1.gbin(H.going_f).astype(str)
    w = 'w_' + (np.clip(H.carried_weight, 460, 900) // 20 * 20).fillna(0).astype(int).astype(str)
    c = 'c_' + H.cls_key.fillna('')
    mean_c = np.mean([v for k, v in coef.items() if k.startswith('c_')])
    return g.map(coef).astype(float) + w.map(coef).astype(float) + c.map(coef).fillna(mean_c).astype(float)


def cum_mean(H, T, key, val, name, prior, k=20.0, hkey=None):
    """key ごとの val の平均を前の日まで数えて T に付ける(prior へ k 本分寄せる)。"""
    hkey = hkey or key
    h = H[H[val].notna() & H[hkey].notna()]
    g = h.groupby([hkey, 'date'])[val].agg(['sum', 'size']).reset_index()
    g[['cs', 'cn']] = g.groupby(hkey)[['sum', 'size']].cumsum()
    g = g.rename(columns={hkey: key}).sort_values('date')
    g[key] = g[key].astype(str)
    q = T[[key, 'date']].copy(); q[key] = q[key].astype(str); q['_i'] = np.arange(len(q))
    m = pd.merge_asof(q.sort_values('date'), g[[key, 'date', 'cs', 'cn']], on='date', by=key, allow_exact_matches=False).sort_values('_i')
    n = m.cn.fillna(0).values; s = m.cs.fillna(0).values
    ok = T[key].notna().values
    return np.where(ok, (s + k * prior) / (n + k), np.nan), np.where(ok, n, np.nan)


def build(ru, ra, pr, kd, cutoff=None, base=None, sbase=None):
    H, ra, pr = f1.prep(ru, ra, pr, kd, cutoff)
    H = f1.apply_base(H, base)
    kb = load_kb(cutoff)
    st = start_minutes(load_kb(None)[['race_date', 'race_no', 'runner_number', 'hasso_time']])  # 発走時刻は前から分かる値
    H = H.merge(kb.drop(columns=['hasso_time']), on=['race_date', 'race_no', 'runner_number'], how='left')
    H.loc[H.src != 'off', ['kb_finish', 'seg_front', 'seg_obst', 'seg_back', 'pass1', 'pass2', 'pass3']] = np.nan
    H['ran'] = 1 - H.scratch
    H['n_ran'] = H.groupby('rkey').ran.transform('sum')
    fin = H.finish.notna() & H.kb_finish.notna() & (H.dnf == 0)
    H['seg_ok'] = fin & H.seg_obst.notna() & (H.seg_front > 0) & (H.seg_back > 0) & (H.seg_obst > 0)
    for c in SEGS.values():
        H.loc[~H.seg_ok, c] = np.nan
    for c in ['pass1', 'pass2', 'pass3']:
        H.loc[~fin, c] = np.nan
    if sbase is None:
        sbase = fit_seg(H)
    win = H[H.finish == 1].drop_duplicates('rkey').set_index('rkey')
    for s, col in SEGS.items():
        H[s + '_idx'] = np.where(H.seg_ok, (seg_pred(H, sbase[s]) - np.log(H[col])) * 100, np.nan)  # 大きいほど速い
        H[s + '_dc'] = H[s + '_idx'] - H.groupby('race_date')[s + '_idx'].transform('median')     # 前走以前の直しだけに使う
        H[s + '_rel'] = H[s + '_idx'] - H.groupby('rkey')[s + '_idx'].transform('mean')
        H[s + '_rk'] = H.groupby('rkey')[s + '_idx'].rank(ascending=False, pct=True)
        H[s + '_dwin'] = H[col] - H.rkey.map(win[col])
    H['o_bad'] = (H.seg_obst >= 2 * H.groupby('rkey').seg_obst.transform('median')).astype(float).where(H.seg_ok)
    H['b_best'] = (H.seg_back == H.groupby('rkey').seg_back.transform('min')).astype(float).where(H.seg_ok)
    H['fo_bal'] = H.f_rel - H.o_rel
    H['bo_bal'] = H.b_rel - H.o_rel
    H['breath'] = H.f_rk - H.o_rk
    for c in ['pass1', 'pass2', 'pass3']:
        H[c + 'r'] = H[c] / H.n_ran
    H['o_gain'] = (H.pass2 - H.pass3) / H.n_ran          # 障害で上げた順位
    H['late'] = (H.pass3 - H.finish) / H.n_ran            # 障害の後で上げた順位
    H['late_up'] = (H.finish < H.pass3).astype(float).where(H.pass3.notna())
    H['o_first'] = (H.pass3 == 1).astype(float).where(H.pass3.notna())

    T = H[H.src == 'off'].copy()
    # ---- 馬ごとの履歴(走った行だけ・前の日まで)
    # KDSCOPE の走り(2013 年以前)は区間タイムが無く、公式の走りより必ず前なので、直近の走りの並びは変わらない
    R_ = H[(H.ran == 1) & (H.src == 'off')].sort_values(['hk', 'date']).copy()
    gh = R_.groupby('hk')
    lag10 = ['o_idx', 'carried_weight', 'going_f', 'o_bad', 'b_best', 'late_up', 'o_first', 'pass3r']
    lag5 = ['seg_front', 'seg_obst', 'seg_back', 'f_idx', 'b_idx', 'f_dc', 'o_dc', 'b_dc', 'f_rel', 'o_rel', 'b_rel', 'o_rk',
            'f_dwin', 'o_dwin', 'b_dwin', 'fo_bal', 'bo_bal', 'breath', 'pass1r', 'pass2r', 'o_gain', 'late']
    for v in lag10 + lag5:
        for k in range(1, (NL if v in lag10 else 5) + 1):
            R_[f'Q{k}_{v}'] = gh[v].shift(k - 1)
    # 年度ごとの障害の指数(今年度のここまで・前の年度の全部)
    keyfy = [R_.hk, R_.fy]
    R_['q_ofy_s'] = R_.o_idx.fillna(0).groupby(keyfy).cumsum()
    R_['q_ofy_n'] = R_.o_idx.notna().astype(int).groupby(keyfy).cumsum()
    R_['q_fy'] = R_.fy
    keep = ['hk', 'date', 'q_fy', 'q_ofy_s', 'q_ofy_n'] + [c for c in R_.columns if c.startswith('Q')]
    T['_i'] = np.arange(len(T))
    T = pd.merge_asof(T.sort_values('date'), R_[keep].sort_values('date'), on='date', by='hk', allow_exact_matches=False)
    T = T.sort_values('_i').reset_index(drop=True)
    pfy = R_.groupby(['hk', 'fy']).o_idx.mean().rename('pfy').reset_index()
    pfy['fy'] = pfy.fy + 1
    prev_fy = T[['hk', 'fy']].merge(pfy, on=['hk', 'fy'], how='left').pfy.values

    F = pd.DataFrame(index=T.index)
    Q = lambda k, v: T[f'Q{k}_{v}'].astype(float)
    lag = lambda v, n=5: np.column_stack([Q(k, v).values for k in range(1, n + 1)])
    nan = np.nan
    with np.errstate(all='ignore'):
        # D 区間タイム(生の秒)
        F['d59_front_l1'] = Q(1, 'seg_front'); F['d60_obst_l1'] = Q(1, 'seg_obst'); F['d61_back_l1'] = Q(1, 'seg_back')
        for nm, v in [('d62_obst', 'seg_obst'), ('d63_front', 'seg_front'), ('d64_back', 'seg_back')]:
            F[nm + '_mean5'] = np.nanmean(lag(v), 1); F[nm + '_min5'] = np.nanmin(lag(v), 1)
        # 重量・水分・組で直した指数(65 障害の力・66 先行の速さ・67 降りてからの脚)
        for nm, s in [('d65_obst', 'o'), ('d66_front', 'f'), ('d67_back', 'b')]:
            F[nm + '_idx_l1'] = Q(1, s + '_idx')
            F[nm + '_idx_mean5'] = np.nanmean(lag(s + '_idx'), 1)
            F[nm + '_idx_max5'] = np.nanmax(lag(s + '_idx'), 1)
            F[nm + '_dc_l1'] = Q(1, s + '_dc')
            F[nm + '_dc_mean5'] = np.nanmean(lag(s + '_dc'), 1)
            F[nm + '_rel_mean5'] = np.nanmean(lag(s + '_rel'), 1)   # 83 同じレースの相手との差
        F['d68_obst_idx_std5'] = np.nanstd(lag('o_idx'), 1, ddof=1)
        F['d69_obst_bad_n10'] = np.nansum(lag('o_bad', NL), 1)
        F['d70_obst_rk_l1'] = Q(1, 'o_rk'); F['d70_obst_rk_mean5'] = np.nanmean(lag('o_rk'), 1)
        # 71 3 区間の型(先行力型・登坂型・末脚型)
        F['d71_fo_bal_mean5'] = np.nanmean(lag('fo_bal'), 1)
        F['d71_bo_bal_mean5'] = np.nanmean(lag('bo_bal'), 1)
        rel3 = np.column_stack([F.d66_front_rel_mean5, F.d65_obst_rel_mean5, F.d67_back_rel_mean5])
        okr = ~np.isnan(rel3).any(1)
        F['d71_type'] = np.where(okr, np.argmax(np.nan_to_num(rel3, nan=-1e9), 1), nan)
        # 74・75 重量・水分が変わった時の障害の指数の傾き(前 10 走・4 走以上)
        oi = lag('o_idx', NL)
        for nm, v in [('d74_obst_cw_slope10', 'carried_weight'), ('d75_obst_going_slope10', 'going_f')]:
            x = lag(v, NL); m = ~np.isnan(oi) & ~np.isnan(x)
            xm = np.where(m, x, nan); ym = np.where(m, oi, nan)
            cx = xm - np.nanmean(xm, 1, keepdims=True); cy = ym - np.nanmean(ym, 1, keepdims=True)
            vx = np.nansum(cx * cx, 1)
            F[nm] = np.where((m.sum(1) >= 4) & (vx > 0), np.nansum(cx * cy, 1) / vx, nan)
        F['d76_obst_trend3'] = Q(1, 'o_idx') - np.nanmean(np.column_stack([Q(k, 'o_idx') for k in (2, 3, 4)]), 1)
        F['d77_breath_mean5'] = np.nanmean(lag('breath'), 1)
        F['d78_back_best_n10'] = np.nansum(lag('b_best', NL), 1)
        for nm, v in [('d79_obst_dwin', 'o_dwin'), ('d80_front_dwin', 'f_dwin'), ('d81_back_dwin', 'b_dwin')]:
            F[nm + '_l1'] = Q(1, v); F[nm + '_mean5'] = np.nanmean(lag(v), 1)
        # 84 障害の指数の今年度と前の年度の差
        cur = np.where(T.q_fy == T.fy, T.q_ofy_s / T.q_ofy_n.replace(0, nan), nan)
        F['d84_obst_fy_minus_prev'] = cur - prev_fy
        # L 209 障害の力(前 10 走の重み付き平均)・210 今日の水分に近い時の障害の力
        wts = 0.85 ** np.arange(NL)
        mo = ~np.isnan(oi)
        F['l209_obst_ewm10'] = np.where(mo.any(1), np.nansum(np.nan_to_num(oi) * wts, 1) / np.maximum((mo * wts).sum(1), 1e-9), nan)
        gl = lag('going_f', NL)
        near = mo & (np.abs(gl - T.day_going.values[:, None]) <= 0.3)
        F['l210_obst_near_going'] = np.where(near.any(1), np.nansum(np.where(near, oi, 0), 1) / np.maximum(near.sum(1), 1), nan)
        # E 通過順(頭数で割った値・小さいほど前)
        F['e85_p1_l1'] = Q(1, 'pass1r'); F['e85_p2_l1'] = Q(1, 'pass2r'); F['e85_p3_l1'] = Q(1, 'pass3r')
        F['e86_p1_mean5'] = np.nanmean(lag('pass1r'), 1)
        F['e87_p2_mean5'] = np.nanmean(lag('pass2r'), 1)
        F['e87_p3_mean5'] = np.nanmean(lag('pass3r'), 1)
        F['e88_obst_gain_mean5'] = np.nanmean(lag('o_gain'), 1)
        F['e89_late_up_n10'] = np.nansum(lag('late_up', NL), 1)
        F['e93_obst_first_n10'] = np.nansum(lag('o_first', NL), 1)
        F['e95_late_mean5'] = np.nanmean(lag('late'), 1)
        F['e96_p2_std5'] = np.nanstd(lag('pass2r'), 1, ddof=1)
    # 履歴の無い馬の数え上げは空に(0 と区別する)
    has = ~np.isnan(lag('o_idx', NL)).all(1)
    for c in ['d69_obst_bad_n10', 'd78_back_best_n10', 'e89_late_up_n10', 'e93_obst_first_n10']:
        F[c] = F[c].where(has if c.startswith('d') else ~np.isnan(lag('pass3r', NL)).all(1))

    # E 94 先行の残りやすさ(前の 30 日・第 2 障害を先頭で越えた馬の 3 着内率)× 自分の位置
    ld = H[(H.pass3 == 1) & H.finish.notna()].groupby('date').agg(n=('finish', 'size'), t3=('finish', lambda s: (s <= 3).sum())).sort_index()
    ld[['cn', 'c3']] = ld[['n', 't3']].cumsum()
    ld = ld.reset_index()[['date', 'cn', 'c3']]
    q = T[['date']].copy(); q['_i'] = np.arange(len(q))
    a = pd.merge_asof(q.sort_values('date'), ld, on='date', allow_exact_matches=False).sort_values('_i')
    q2 = q.copy(); q2['date'] = q2.date - pd.Timedelta(days=30)
    b = pd.merge_asof(q2.sort_values('date'), ld, on='date', allow_exact_matches=False).sort_values('_i')
    n30 = a.cn.fillna(0).values - b.cn.fillna(0).values
    F['e94_lead_top3_30d'] = np.where(n30 >= 10, (a.c3.fillna(0).values - b.c3.fillna(0).values) / np.maximum(n30, 1), nan)
    F['e94_lead_x_front'] = F.e94_lead_top3_30d * (1 - F.e87_p3_mean5)

    # I 175・176 騎手の乗り方の癖・K 198 父の産駒の障害(前の日まで)
    F['i175_jk_front_rate'], F['i175_jk_n'] = cum_mean(H, T, 'jockey', 'pass2r', 'jk', 0.55)
    F['i176_jk_obst_rel'], _ = cum_mean(H, T, 'jockey', 'o_rel', 'jk', 0.0)
    Hs = H.merge(pr[['hk', 'sire']], on='hk', how='left') if 'sire' not in H.columns else H
    Ts = T.merge(pr[['hk', 'sire']], on='hk', how='left') if 'sire' not in T.columns else T
    F['k198_sire_obst_rel'], F['k198_sire_n'] = cum_mean(Hs, Ts, 'sire', 'o_rel', 'sire', 0.0)

    # B 32・33 発走時刻(分)・日の入りとの差
    T = T.merge(st, on=['race_date', 'race_no'], how='left')
    F['b33_start_min'] = T.st.values
    F['b32_after_sunset'] = T.st.values - sunset_min(T.date)

    # レースの中の値(取消を除いた頭数・§A 注意 6)
    rkx = T.rkey; run_mask = T.scratch.values == 0
    fm = F.d66_front_idx_mean5.where(run_mask); om = F.d65_obst_idx_mean5.where(run_mask)
    F['d72_field_front_mean'] = fm.groupby(rkx).transform('mean')
    F['d73_obst_gap_top'] = F.d65_obst_idx_mean5 - om.groupby(rkx).transform('max')
    F['p242_field_front_std'] = fm.groupby(rkx).transform('std')
    F['p243_n_obst_better'] = om.groupby(rkx).rank(ascending=False, method='min') - 1
    F['p244_n_front_better'] = fm.groupby(rkx).rank(ascending=False, method='min') - 1
    F.loc[F.d65_obst_idx_mean5.isna(), 'p243_n_obst_better'] = nan
    F.loc[F.d66_front_idx_mean5.isna(), 'p244_n_front_better'] = nan
    style = F.e87_p2_mean5.where(run_mask)
    isfront = (style <= 0.25)
    F['e91_field_n_front'] = isfront.astype(float).groupby(rkx).transform('sum')
    F['e92_sole_front'] = np.where(style.notna(), (isfront & (F.e91_field_n_front == 1)).astype(float), nan)
    for c in ['d65_obst_idx_mean5', 'd65_obst_dc_mean5', 'd66_front_idx_mean5', 'd67_back_idx_mean5', 'l209_obst_ewm10',
              'e87_p2_mean5', 'd71_fo_bal_mean5']:
        v = F[c].where(run_mask)
        F['p237_' + c + '_d'] = F[c] - v.groupby(rkx).transform('mean')
        F['p238_' + c + '_rk'] = v.groupby(rkx).rank(ascending=False, pct=True)
    K = T[['race_date', 'race_no', 'runner_number']].copy()
    return K.join(F), sbase
