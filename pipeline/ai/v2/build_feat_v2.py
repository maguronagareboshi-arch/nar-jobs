# -*- coding: utf-8 -*-
# 写し元 C:/Users/kouki/nankan_ai/build_feat_v2.py(写した日 2026-09-23)。
# 変えた行= ROOT(環境変数 NAI_ROOT)と FEAT(環境変数 NAI_LEGACY)の 2 行だけ。
# RAW/WORK/OUT は ROOT から作られるので自動で移る。⛔計算は 1 行も変えていない。
"""E5b: feat.parquet(既存 279 列の素)に as-of の新列を左結合して feat_v2.parquet を作る。

  py -3.12 -X utf8 C:/Users/kouki/nankan_ai/build_feat_v2.py --stage all

段:
  base   … raw/ の gz CSV を 1 頭 1 走の長表にまとめて work/v2_base.parquet へ
  feats  … 長表から as-of 列を作って work/v2_feats.parquet へ
  join   … feat.parquet に左結合して feat_v2.parquet へ + 欠測率 work/v2_missing.csv

⛔本番 DB には一切つながない(材料は C:/Users/kouki/nankan_ai/raw/ の写しだけ)。
⛔C:/Users/kouki/ai_v1/feat.parquet は読むだけ。
⛔as-of の守り: 新列はすべて「その馬のその走より前の走」だけから作る。
   ・馬ごとに (race_date, race_no) で並べ、shift(1) を掛けてから rolling する。
     つまりその走自身の値は窓に入らない。
   ・基準時計(クラス×距離×場の中央値)は「その走の月の初日より前」の走だけで作る。
   ・当日の馬具・当日の通過順・当日の start_note は一切使わない。
   ・欠測は NULL(NaN)のまま。0 で埋めない。
"""
from __future__ import annotations
import argparse, csv, gzip, os, sys, time
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

ROOT = (os.environ.get('NAI_ROOT') or 'C:/Users/kouki/nankan_ai/').replace(chr(92), '/').rstrip('/') + '/'
RAW = ROOT + 'raw/'
WORK = ROOT + 'work/'
FEAT = os.environ.get('NAI_LEGACY', 'C:/Users/kouki/ai_v1/feat.parquet')
OUT = ROOT + 'feat_v2.parquet'
NANKAN = ['大井', '川崎', '船橋', '浦和']
KEY = ['track', 'race_date', 'race_no', 'runner_number']

STYLES = ['逃げ', '先行', '差し', '追込']
STYLE_ORD = {s: i + 1 for i, s in enumerate(STYLES)}
# 出遅れとみなす start_note(前方一致)
LATE_PREFIX = ('出遅れ', '大きく出遅れ', 'ダッシュ付かず', 'アオル', 'スタート直後躓く')


def log(*a):
    print('[%s]' % time.strftime('%H:%M:%S'), *a, flush=True)


def read_gz(name, cols, dtype=None):
    """gz CSV を必要列だけ読む。"""
    with gzip.open(RAW + name + '.csv.gz', 'rt', encoding='utf-8', newline='') as f:
        df = pd.read_csv(f, usecols=cols, dtype=dtype, low_memory=False)
    log('read', name, df.shape)
    return df


# ------------------------------------------------------------------ 段1: 長表
def stage_base():
    runs = read_gz('nar_runs', ['track', 'race_date', 'race_no', 'runner_number',
                                'horse_name', 'birth_date', 'finish', 'finish_note',
                                'last3f', 'popularity'])
    races = read_gz('nar_races', ['track', 'race_date', 'race_no', 'distance_m',
                                  'field_size', 'race_kind', 'going'])
    rf = read_gz('nar_run_facts', ['track', 'race_date', 'race_no', 'umaban',
                                   'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4',
                                   'style', 'first3f', 'first3f_src', 'last3f'])
    kb = read_gz('nar_kb_runs', ['track', 'race_date', 'race_no', 'umaban',
                                 'gear', 'start_note', 'first3f'])
    paper = read_gz('nar_paper_runs', ['track', 'race_date', 'race_no', 'umaban', 'gear'])

    rf = rf.rename(columns={'umaban': 'runner_number', 'last3f': 'rf_last3f'})
    kb = kb.rename(columns={'umaban': 'runner_number', 'gear': 'kb_gear',
                            'first3f': 'kb_first3f'})
    paper = paper.rename(columns={'umaban': 'runner_number', 'gear': 'paper_gear'})

    df = runs.merge(races, on=['track', 'race_date', 'race_no'], how='left')
    df = df.merge(rf, on=KEY, how='left')
    df = df.merge(kb, on=KEY, how='left')
    df = df.merge(paper, on=KEY, how='left')

    df['race_date'] = pd.to_datetime(df['race_date'], errors='coerce')
    df['horse_key'] = df['horse_name'].astype(str) + '|' + df['birth_date'].fillna('').astype(str)

    # 着順・3着内(finish_note の付いた走= 取消/除外/中止 は成績として数えない)
    fin = pd.to_numeric(df['finish'], errors='coerce')
    ok = df['finish_note'].isna() | (df['finish_note'].astype(str).str.strip() == '')
    df['fin'] = fin.where(ok)
    df['hit3'] = np.where(df['fin'].notna(), (df['fin'] <= 3).astype(float), np.nan)

    # 上がり3F は run_facts 優先・無ければ nar_runs
    df['last3f_v'] = pd.to_numeric(df['rf_last3f'], errors='coerce')
    df['last3f_v'] = df['last3f_v'].fillna(pd.to_numeric(df['last3f'], errors='coerce'))
    # 前半3F は run_facts(own>paper>kb>est の優先で既に一本化済み)優先・無ければ kb
    df['first3f_v'] = pd.to_numeric(df['first3f'], errors='coerce')
    df['first3f_v'] = df['first3f_v'].fillna(pd.to_numeric(df['kb_first3f'], errors='coerce'))
    df['f3_src_ok'] = df['first3f_src'].notna().astype(float)

    for c in ('c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4', 'distance_m', 'field_size'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    # 頭数は n{k} > なければ field_size
    for k in (1, 2, 3, 4):
        df['n%d' % k] = df['n%d' % k].where(df['n%d' % k] > 1, df['field_size'])
        df['r%d' % k] = df['c%d' % k] / df['n%d' % k]
    # 4角からの追い上げ幅(＋= 追い上げた)
    df['gain4'] = df['c4'] - df['fin']
    df['lead3'] = np.where(df['c1'].notna(), (df['c1'] <= 3).astype(float), np.nan)
    df['front_r'] = np.where(df['r1'].notna(), (df['r1'] <= 1.0 / 3).astype(float), np.nan)

    # 脚質(run_facts.style はそれ自体が発走前 as-of。さらに前走までしか使わない)
    df['style_ord'] = df['style'].map(STYLE_ORD)
    for s in STYLES:
        df['sty_' + s] = np.where(df['style'].notna(), (df['style'] == s).astype(float), np.nan)

    # 出遅れ(kb がある走だけ判定できる。kb の無い走は NaN= 不明)
    sn = df['start_note'].fillna('')
    has_kb = df['kb_gear'].notna() | df['start_note'].notna() | df['kb_first3f'].notna()
    late = sn.str.startswith(LATE_PREFIX)
    df['late'] = np.where(has_kb, late.astype(float), np.nan)
    df['kb_cov'] = has_kb.astype(float)
    df['fin_rel'] = df['fin'] / df['field_size']
    df['late_fin'] = np.where(df['late'] == 1, df['fin'], np.nan)
    df['late_fin_rel'] = np.where(df['late'] == 1, df['fin_rel'], np.nan)

    # 馬具: kb の日本語表記 > 紙面の B/P/S
    g = df['kb_gear'].fillna('')
    pg = df['paper_gear'].fillna('')
    # ⛔kb_gear が空文字(= NaN で読まれる)でも kb の行が在れば「馬具なし」が確定している。
    #   kb 行の有無をカバレッジにする(紙面は 2026 年の少数のみ)。
    gear_cov = has_kb | df['paper_gear'].notna()
    df['gear_cov'] = gear_cov.astype(float)
    for tag, jp, en in (('b', 'ブリンカー', 'B'), ('s', 'シャドーロール', 'S'), ('p', 'チーク', 'P')):
        v = g.str.contains(jp, regex=False) | pg.str.contains(en, regex=False)
        df['gear_' + tag] = np.where(gear_cov, v.astype(float), np.nan)
    df['gear_cnt'] = df[['gear_b', 'gear_s', 'gear_p']].sum(axis=1, min_count=3)

    df['dist_band'] = (df['distance_m'] // 100) * 100
    df['race_kind'] = df['race_kind'].fillna('不明')

    df = df.sort_values(['horse_key', 'race_date', 'race_no'], kind='mergesort').reset_index(drop=True)
    keep = KEY + ['horse_key', 'distance_m', 'dist_band', 'field_size',
                  'race_kind', 'going', 'fin', 'fin_rel', 'hit3',
                  'c1', 'c2', 'c3', 'c4', 'r1', 'r2', 'r3', 'r4', 'gain4', 'lead3', 'front_r',
                  'style', 'style_ord'] + ['sty_' + s for s in STYLES] + \
           ['first3f_v', 'last3f_v', 'f3_src_ok',
            'late', 'kb_cov', 'late_fin', 'late_fin_rel',
            'gear_b', 'gear_s', 'gear_p', 'gear_cnt', 'gear_cov']
    out = df[keep].copy()
    out.to_parquet(WORK + 'v2_base.parquet', index=False)
    log('base saved', out.shape)
    return out


# ------------------------------------------------------- 基準時計(月単位 as-of)
def asof_baseline(df, col):
    """クラス×距離×場 の中央値を「その走の月の初日より前」の走だけで作る。"""
    d = df[['track', 'race_kind', 'dist_band', 'race_date', col]].copy()
    d['ym'] = d['race_date'].values.astype('datetime64[M]')
    rows = []
    for gkey, g in d.groupby(['track', 'race_kind', 'dist_band'], sort=False, dropna=False):
        g = g.sort_values('ym')
        vals = g[col].to_numpy(dtype=float)
        yms = g['ym'].to_numpy()
        uym, starts = np.unique(yms, return_index=True)
        acc = []
        for i, m in enumerate(uym):
            med = np.nanmedian(acc) if acc else np.nan
            rows.append((gkey[0], gkey[1], gkey[2], m, med))
            e = starts[i + 1] if i + 1 < len(starts) else len(vals)
            chunk = vals[starts[i]:e]
            chunk = chunk[~np.isnan(chunk)]
            if len(chunk):
                acc.extend(chunk.tolist())
    b = pd.DataFrame(rows, columns=['track', 'race_kind', 'dist_band', 'ym', 'base_' + col])
    d2 = df[['track', 'race_kind', 'dist_band', 'race_date']].copy()
    d2['ym'] = d2['race_date'].values.astype('datetime64[M]')
    m = d2.merge(b, on=['track', 'race_kind', 'dist_band', 'ym'], how='left')
    return m['base_' + col].to_numpy()


# ----------------------------------------------- グループごとの「前走まで」累積
def keycodes(*cols):
    """複数列を 1 本の整数コードに畳む(NaN も 1 つの水準として扱う)。"""
    codes = None
    for c in cols:
        cc = pd.factorize(pd.Series(np.asarray(c)), use_na_sentinel=False)[0].astype(np.int64)
        codes = cc if codes is None else codes * (cc.max() + 2) + cc
        codes = pd.factorize(codes, use_na_sentinel=False)[0].astype(np.int64)
    return codes


def prior_cum(vals, codes):
    """行順のまま、同じ code の「その行より前の行」だけの 件数 と 平均 を返す。
    行は既に (horse_key, race_date, race_no) 順に並んでいる前提。"""
    vals = np.asarray(vals, dtype=float)
    order = np.argsort(codes, kind='stable')      # 同じ code をまとめる(グループ内は元の順)
    v = vals[order]
    ok = ~np.isnan(v)
    cs = np.r_[0.0, np.cumsum(np.where(ok, v, 0.0))]
    cn = np.r_[0.0, np.cumsum(ok.astype(float))]
    c = codes[order]
    gstart = np.r_[True, c[1:] != c[:-1]]
    base = np.maximum.accumulate(np.where(gstart, np.arange(len(c)), 0))  # 各グループの開始位置
    n_prior = cn[np.arange(len(c))] - cn[base]
    s_prior = cs[np.arange(len(c))] - cs[base]
    mean = np.where(n_prior > 0, s_prior / np.where(n_prior > 0, n_prior, 1), np.nan)
    out_n = np.empty(len(c)); out_m = np.empty(len(c))
    out_n[order] = n_prior
    out_m[order] = mean
    return out_n, out_m


# --------------------------------------------------------------- 段2: as-of 列
def roll(shifted, hk, w, how='mean'):
    """馬ごとに shift(1) 済みの表を w 走の窓で集計。"""
    gb = shifted.groupby(hk, sort=False)
    r = gb.rolling(w, min_periods=1)
    out = getattr(r, how)()
    out.index = shifted.index
    return out


def stage_feats():
    df = pd.read_parquet(WORK + 'v2_base.parquet')
    log('base loaded', df.shape)
    hk = df['horse_key']

    # 基準時計との差(その走の時点での差。基準は月の初日より前のデータだけ)
    for c in ('first3f_v', 'last3f_v'):
        df['dev_' + c] = df[c] - asof_baseline(df, c)
        log('baseline done', c, 'notna=%.3f' % df['dev_' + c].notna().mean())

    # ---- 窓集計に使う素の列
    mean_cols = ['c1', 'c2', 'c3', 'c4', 'r1', 'r2', 'r3', 'r4', 'gain4', 'lead3', 'front_r',
                 'sty_逃げ', 'sty_先行', 'sty_差し', 'sty_追込',
                 'first3f_v', 'last3f_v', 'dev_first3f_v', 'dev_last3f_v', 'f3_src_ok',
                 'late', 'kb_cov', 'late_fin', 'late_fin_rel']
    S = df[mean_cols].groupby(hk, sort=False).shift(1)

    F = pd.DataFrame(index=df.index)
    # --- A/B/C/D の平均系
    m1 = S  # w=1 = 前走の値そのもの
    m3 = roll(S, hk, 3, 'mean')
    m5 = roll(S, hk, 5, 'mean')
    cnt5 = roll(S, hk, 5, 'count')
    cnt3 = roll(S, hk, 3, 'count')
    mn5 = roll(S[['first3f_v', 'last3f_v', 'dev_first3f_v', 'dev_last3f_v']], hk, 5, 'min')

    # A. 通過順・位置取り
    for k in (1, 2, 3, 4):
        F['pa_c%d_1' % k] = m1['c%d' % k]
        F['pa_c%d_3' % k] = m3['c%d' % k]
        F['pa_c%d_5' % k] = m5['c%d' % k]
        F['pa_r%d_1' % k] = m1['r%d' % k]
        F['pa_r%d_3' % k] = m3['r%d' % k]
        F['pa_r%d_5' % k] = m5['r%d' % k]
    F['pa_gain4_1'] = m1['gain4']
    F['pa_gain4_3'] = m3['gain4']
    F['pa_gain4_5'] = m5['gain4']
    F['pa_lead3_3'] = m3['lead3']
    F['pa_lead3_5'] = m5['lead3']
    F['pa_front_5'] = m5['front_r']
    F['pa_n5'] = cnt5['c4']

    # B. 脚質
    F['st_nige_5'] = m5['sty_逃げ']
    F['st_senko_5'] = m5['sty_先行']
    F['st_sashi_5'] = m5['sty_差し']
    F['st_oikomi_5'] = m5['sty_追込']
    F['st_n5'] = cnt5['sty_逃げ']
    F['st_prev_ord'] = df.groupby(hk, sort=False)['style_ord'].shift(1)

    # C. 前半3F/上がり3F
    F['tf_f3_avg3'] = m3['first3f_v']
    F['tf_f3_avg5'] = m5['first3f_v']
    F['tf_f3_best5'] = mn5['first3f_v']
    F['tf_l3_avg3'] = m3['last3f_v']
    F['tf_l3_avg5'] = m5['last3f_v']
    F['tf_l3_best5'] = mn5['last3f_v']
    F['tf_f3_dev3'] = m3['dev_first3f_v']
    F['tf_f3_dev5'] = m5['dev_first3f_v']
    F['tf_f3_devbest5'] = mn5['dev_first3f_v']
    F['tf_l3_dev3'] = m3['dev_last3f_v']
    F['tf_l3_dev5'] = m5['dev_last3f_v']
    F['tf_l3_devbest5'] = mn5['dev_last3f_v']
    F['tf_f3_n5'] = cnt5['first3f_v']
    F['tf_l3_n5'] = cnt5['last3f_v']
    F['tf_f3_srcmiss5'] = 1.0 - m5['f3_src_ok']

    # D. 出遅れ
    F['sn_late_rate5'] = m5['late']
    F['sn_late_n5'] = (m5['late'] * cnt5['late']).round()
    F['sn_late_cap3'] = F['sn_late_n5'].clip(upper=3)
    F['sn_late_prev'] = m1['late']
    F['sn_late_fin5'] = m5['late_fin']
    F['sn_late_finrel5'] = m5['late_fin_rel']
    F['sn_kb_n5'] = cnt5['late']
    del m1, m3, cnt3, mn5

    # E. 馬具(⛔当日は使わない。前走時点の馬具と、前走−前々走の差だけ)
    g1 = df[['gear_b', 'gear_s', 'gear_p', 'gear_cnt', 'gear_cov']].groupby(hk, sort=False).shift(1)
    g2 = df[['gear_b', 'gear_s', 'gear_p', 'gear_cnt', 'gear_cov']].groupby(hk, sort=False).shift(2)
    F['gr_prev_b'] = g1['gear_b']
    F['gr_prev_s'] = g1['gear_s']
    F['gr_prev_p'] = g1['gear_p']
    F['gr_prev_cnt'] = g1['gear_cnt']
    both = (g1['gear_cov'] == 1) & (g2['gear_cov'] == 1)
    for t in ('b', 's', 'p'):
        on = (g1['gear_' + t] == 1) & (g2['gear_' + t] == 0)
        off = (g1['gear_' + t] == 0) & (g2['gear_' + t] == 1)
        F['gr_first_' + t] = np.where(both, on.astype(float), np.nan)
        F['gr_off_' + t] = np.where(both, off.astype(float), np.nan)
    ch = (F[['gr_first_b', 'gr_off_b', 'gr_first_s', 'gr_off_s',
             'gr_first_p', 'gr_off_p']].sum(axis=1, min_count=6) > 0)
    F['gr_change'] = np.where(both, ch.astype(float), np.nan)
    F['gr_same'] = np.where(both, (~ch).astype(float), np.nan)
    F['gr_cov2'] = both.astype(float)
    del g1, g2

    # F. 使い詰め(既存 days_since_prev / rest_leq3 / rest_gt42 / runs_this_year とは重ねない)
    dd = df['race_date'].values.astype('datetime64[D]').astype(np.int64)
    order = np.arange(len(df))
    starts = np.flatnonzero(np.r_[True, hk.to_numpy()[1:] != hk.to_numpy()[:-1]])
    ends = np.r_[starts[1:], len(df)]
    n30 = np.empty(len(df)); n60 = np.empty(len(df)); n90 = np.empty(len(df))
    d2 = np.full(len(df), np.nan)
    rent = np.full(len(df), np.nan)
    for s, e in zip(starts, ends):
        dv = dd[s:e]
        idx = np.arange(e - s)
        for arr, win in ((n30, 30), (n60, 60), (n90, 90)):
            pos = np.searchsorted(dv, dv - win, side='left')
            arr[s:e] = idx - pos
        if e - s >= 3:
            d2[s + 2:e] = dv[2:] - dv[:-2]
        if e - s >= 2:
            gap = np.r_[np.nan, np.diff(dv).astype(float)]
            rent[s:e] = np.where(np.isnan(gap), np.nan, (gap <= 8).astype(float))
    F['lo_runs_30d'] = n30
    F['lo_runs_60d'] = n60
    F['lo_runs_90d'] = n90
    F['lo_days_prev2'] = d2          # 前々走からの日数
    F['lo_rento_prev'] = rent        # 前走が連闘(中8日以内)だったか
    # 直近 5 走のうち連闘だった回数
    rs = pd.Series(rent, index=df.index)
    F['lo_rento_n5'] = roll(rs.groupby(hk, sort=False).shift(1).to_frame('x'), hk, 5, 'sum')['x']

    # B(続き). 同じ場・同じ距離・同じ脚質の過去成績(すべて前走まで)
    # ⛔「その脚質」= 前走の脚質(当日の run_facts.style は使わない)
    prev_style = F['st_prev_ord'].to_numpy(dtype=float)
    hit = df['hit3'].to_numpy(dtype=float)
    sty = df['style_ord'].to_numpy(dtype=float)
    # 同じ場×同じ距離帯(どちらも発走前に分かる条件)
    n_course, hit_course = prior_cum(hit, keycodes(df['horse_key'], df['track'], df['dist_band']))
    F['st_n_course'] = n_course
    F['st_hit_course'] = hit_course
    # 脚質別: 4 つの脚質それぞれの累積を全行に持たせ、最後に「前走の脚質」で選ぶ。
    # ⛔当該走の style は選択にも集計にも使わない。
    n_by = {}; h_by = {}; nc_by = {}; hc_by = {}
    for s in (1.0, 2.0, 3.0, 4.0):
        m = (sty == s)
        n_by[s], h_by[s] = prior_cum(np.where(m, hit, np.nan), keycodes(df['horse_key']))
        nc_by[s], hc_by[s] = prior_cum(np.where(m, hit, np.nan),
                                       keycodes(df['horse_key'], df['track'], df['dist_band']))
    nan = np.full(len(df), np.nan)
    F['st_n_style'] = nan.copy(); F['st_hit_style'] = nan.copy()
    F['st_n_style_course'] = nan.copy(); F['st_hit_style_course'] = nan.copy()
    for s in (1.0, 2.0, 3.0, 4.0):
        sel = (prev_style == s)
        F.loc[sel, 'st_n_style'] = n_by[s][sel]
        F.loc[sel, 'st_hit_style'] = h_by[s][sel]
        F.loc[sel, 'st_n_style_course'] = nc_by[s][sel]
        F.loc[sel, 'st_hit_style_course'] = hc_by[s][sel]

    F = F.astype('float32')
    out = pd.concat([df[KEY].reset_index(drop=True), F.reset_index(drop=True)], axis=1)
    out.to_parquet(WORK + 'v2_feats.parquet', index=False)
    log('feats saved', out.shape)
    return out


# ------------------------------------------------------------------ 段3: 左結合
def stage_join():
    feat = pd.read_parquet(FEAT)
    log('feat', feat.shape)
    nf = pd.read_parquet(WORK + 'v2_feats.parquet')
    log('newcols', nf.shape)
    feat['race_date'] = pd.to_datetime(feat['race_date'])
    nf['race_date'] = pd.to_datetime(nf['race_date'])
    for c in ('race_no', 'runner_number'):
        feat[c] = pd.to_numeric(feat[c], errors='coerce').astype('int32')
        nf[c] = pd.to_numeric(nf[c], errors='coerce').astype('int32')
    nf = nf.drop_duplicates(subset=KEY)
    out = feat.merge(nf, on=KEY, how='left', validate='one_to_one')
    assert len(out) == len(feat), (len(out), len(feat))
    out.to_parquet(OUT, index=False)
    log('saved', OUT, out.shape)

    new = [c for c in nf.columns if c not in KEY]
    nk = out[out['track'].isin(NANKAN)]
    rep = pd.DataFrame({
        'column': new,
        'null_all': [out[c].isna().mean() for c in new],
        'null_nankan': [nk[c].isna().mean() for c in new],
    })
    rep.to_csv(WORK + 'v2_missing.csv', index=False, encoding='utf-8')
    log('rows all=%d nankan=%d new_cols=%d' % (len(out), len(nk), len(new)))
    print(rep.sort_values('null_all', ascending=False).head(25).to_string(index=False))
    return rep


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', default='all', choices=['base', 'feats', 'join', 'all'])
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    t0 = time.time()
    if a.stage in ('base', 'all'):
        stage_base()
    if a.stage in ('feats', 'all'):
        stage_feats()
    if a.stage in ('join', 'all'):
        stage_join()
    log('done %.1fs' % (time.time() - t0))
