# -*- coding: utf-8 -*-
"""他場版の朝の材料表(base-v1 の 263 列)を、nar-ai-feat の成果物に頼らず公式の表から自分で作る(2026-11-07・v3 の out/v3n_feat_unify_1107.md §8〜11)。

定義の正 = pipeline/sql/ai_feat_20260908.sql(refresh_nar_ai_feat)・pipeline/facts.py(通過順と脚質)。
v3 の研究の台本 src/f5_scripts/v3n_feat_unify_a_1107.py の build_ab・build17 をそのまま写した(式は同じ)。
照合: 選び 2024-09〜2025-08 の 15.6 万行・11/7 の出走 352 行で、サイトの材料表と 210 列すべて一致(残り 53 列は add_relative)。

使い方(v3n_daily から): make(off, day, out_csv) → 出口は nar_ai_feat_run と同じ列の csv.gz(その日の行だけ)。
  off = k0_dl が落とした公式の表(runs・races)。発走時刻とラップ・競馬ブック・能検・セリ・病気・制裁・売上・馬の表はここで読む。
  ⛔行の範囲はサイトの写しと同じ 2022-11 以降+高知 2014〜(nar-ai-feat.yml §243)。
"""
import datetime as dt
import importlib.util
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

KX = ['track', 'race_date', 'race_no', 'runner_number']

JYO = {'帯広ば': 0, '門別': 1, '盛岡': 2, '水沢': 3, '浦和': 4, '船橋': 5, '大井': 6, '川崎': 7,
       '金沢': 8, '笠松': 9, '名古屋': 10, '園田': 11, '姫路': 12, '高知': 13, '佐賀': 14}
SEX = {'牡': 0, '牝': 1, 'セン': 2}
GO = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
REL_A = ['fukusho_rate_5', 'prize_local_log', 'kishu_fuku_1y', 'chokyo_fuku_1y', 'dist_fukusho_rate', 'uma_place_fuku',
         'qpts', 'opp_str_now', 'futan', 'barei', 'p1_chaku', 'avg_chakujun_3', 'days_since_prev', 'has_hist']
REL_B = ['avg_rz_3', 'best_rz_5', 'avg_time_z_3', 'avg_time_za_3', 'avg_l3z_3', 'best_l3z_5', 'p1_sa', 'p1_rz', 'p1_tz',
         'n_tz_5', 'prev_best5', 'jc_tier']
T0 = time.time()

def log(*a):
    print(f'[{time.time() - T0:6.0f}s]', *a, flush=True)


# ------------------------------------------------------------ 窓の部品
def win(day, keys, vals, q, lo=None, cnt_days=False):
    """day = keys + d_idx + vals(日ごとに束ねた和)。q の各行(keys, d_idx)に、窓 [d-lo, d-1](lo=None は全部)の和を付ける。
    cnt_days=True なら窓に入った日の数 _nd も付ける(SQL の sum over 空の窓 = NULL を作るため)。"""
    day = day.sort_values(keys + ['d_idx']).copy()
    if cnt_days:
        day['_nd'] = 1.0
        vals = vals + ['_nd']
    C = day.groupby(keys, sort=False)[vals].cumsum()
    C[keys] = day[keys]
    C['t'] = day.d_idx.astype('int64')
    C = C.sort_values('t')
    qq = q[keys + ['d_idx']].drop_duplicates().copy()

    def at(off):
        z = qq.assign(t=(qq.d_idx - off).astype('int64')).sort_values('t')
        z = pd.merge_asof(z, C, on='t', by=keys, direction='backward')
        return z.set_index(keys + ['d_idx'])[vals].fillna(0)
    out = at(1)
    if lo is not None:
        out = out - at(lo + 1)
    return q.merge(out.reset_index(), on=keys + ['d_idx'], how='left')


def latest(Z, keys, vals, q, strict=True):
    """q の各行(keys, d_idx)に、Z の同じ鍵で d_idx が q より前(strict)か以下の最後の行の vals を付ける(q の並びのまま返す)"""
    Z = Z.dropna(subset=keys).copy()
    Z['t'] = Z.d_idx.astype('int64')
    qq = q[keys + ['d_idx']].copy()
    qq['_i'] = np.arange(len(qq))
    qq['t'] = (qq.d_idx - (1 if strict else 0)).astype('int64')
    ok = qq[keys].notna().all(axis=1)
    a = qq[ok].sort_values('t')
    z = pd.merge_asof(a, Z[keys + ['t'] + vals].sort_values('t'), on='t', by=keys, direction='backward')
    out = pd.DataFrame(index=np.arange(len(qq)), columns=vals, dtype='float64')
    out.loc[z._i.to_numpy(), vals] = z[vals].to_numpy('float64')
    return out


def mlen(m):
    """nar_margin_len と同じ"""
    import re
    s = str(m).strip() if m is not None else ''
    if s == '' or s == 'None' or s == 'nan':
        return np.nan
    tab = {'ハナ': 0.05, 'アタマ': 0.10, 'クビ': 0.30, '同着': 0.0, '大差': 10.0}
    if s in tab:
        return float(np.float32(tab[s]))
    if re.fullmatch(r'[0-9]+', s):
        return float(s)
    if re.fullmatch(r'[0-9]+/[0-9]+', s):
        a, b = s.split('/')
        return float(np.float32(float(a) / float(b))) if float(b) else np.nan
    if re.fullmatch(r'[0-9]+\.[0-9]+/[0-9]+', s):
        a, rest = s.split('.', 1)
        b, c = rest.split('/')
        return float(np.float32(float(a) + float(b) / float(c))) if float(c) else np.nan
    return np.nan


def lap(fl):
    """furlongs(ハロンの時計の並び)→ (前半の平均 − 後半の平均, 最後 − 最小)。4 本未満は空"""
    try:
        v = [float(x) for x in (list(fl) if fl is not None else [])]
    except (TypeError, ValueError):
        return (np.nan, np.nan)
    n = len(v)
    if n < 4:
        return (np.nan, np.nan)
    h = n // 2
    return (float(np.float32(np.mean(v[:h]) - np.mean(v[h:]))), float(np.float32(v[-1] - min(v))))


def avg5(df, cs):
    return df[cs].mean(axis=1, skipna=True)


def cnt5(df, cs):
    return df[cs].notna().sum(axis=1).astype('float64')


def prank(df, by, col):
    """Postgres percent_rank() over (partition by … order by col)= (rank − 1)/(行数 − 1)・空は最後(最大)"""
    x = df[col].astype('float64').fillna(np.inf)
    r = x.groupby([df[b] for b in by]).rank(method='min')
    n = x.groupby([df[b] for b in by]).transform('size')
    return ((r - 1) / (n - 1)).where(n > 1, 0.0)



def build_ab(F, u, r, pt, hs, out_from, out_to=None):
    """(a)(b) の 246 列。u = 公式の runs・r = races(corners 付き)・pt = 発走時刻とラップ・hs = その日の nar_horses。
    u・r は写しの範囲(2022-11 以降+高知 2014〜)に絞って渡す。返す行は out_from〜out_to の日だけ。"""
    pt = pt.copy()
    d = u.merge(r, on=['track', 'race_date', 'race_no'], how='inner')
    d = d[~d.duplicated(KX, keep=False)].reset_index(drop=True)
    log('t_run', len(d))
    d['rd'] = pd.to_datetime(d.race_date)
    d['d_idx'] = (d.rd - pd.Timestamp('2000-01-01')).dt.days.astype('int64')
    d['horse_key'] = d.horse_name + '|' + d.birth_date.fillna('').astype(str)
    for c in ('jockey', 'trainer'):
        d[c] = d[c].where(d[c].notna() & (d[c].astype(str).str.strip() != '')).astype(object)
        d[c] = d[c].map(lambda s: s.strip() if isinstance(s, str) else None)
    d['is_run'] = d.finish.notna()
    d['hit3'] = np.where(d.is_run, (d.finish <= 3).astype(float), np.nan)
    d['going_ord'] = d.going.map(GO)
    d['dist_band'] = (np.floor(d.distance_m / 200.0 + 0.5) * 200)
    d['yr'] = d.rd.dt.year
    d['scratched'] = (d.finish_note.fillna('').astype(str) != '').astype(float)

    def prz(x, i):
        try:
            v = x[i]
            return float(v) if v not in ('', None) else np.nan
        except (TypeError, ValueError, IndexError):
            return np.nan
    d['prize1'] = d.prize_yen.map(lambda x: prz(x, 0))
    fin = d.finish.fillna(0).astype(int)
    ear = [prz(x, f - 1) if 1 <= f <= 5 else 0.0 for x, f in zip(d.prize_yen, fin)]
    d['earned'] = np.where(d.is_run, np.nan_to_num(np.array(ear, dtype='float64'), nan=0.0), np.nan)
    d['hasso_hour'] = d.post_time.map(lambda s: float(str(s).zfill(4)[:2]) if isinstance(s, str) and s.strip() else np.nan)

    # 通過順(facts.corner_cells と同じ・帯広ばは無し)
    cc = [F.corner_cells(cr, un) if t != '帯広ば' else [(None, None)] * 4
          for cr, un, t in zip(d.corners, d.runner_number, d.track)]
    for i, k in enumerate((1, 2, 3, 4)):
        d[f'pos{k}'] = pd.to_numeric(pd.Series([c[i][0] for c in cc]), errors='coerce').to_numpy()
        d[f'n{k}'] = pd.to_numeric(pd.Series([c[i][1] for c in cc]), errors='coerce').to_numpy()
    nopos = d.pos1.isna() & d.pos4.isna()      # t_corner は c1 か c4 のある行だけ
    for k in (1, 2, 3, 4):
        d.loc[nopos, [f'pos{k}', f'n{k}']] = np.nan
    d['p_pos1'], d['p_pos2'], d['p_pos4'] = d.pos1 / d.n1.replace(0, np.nan), d.pos2 / d.n2.replace(0, np.nan), d.pos4 / d.n4.replace(0, np.nan)
    d['fwd'] = 1 - d.p_pos1
    d['l3gap'] = d.last3f - d.race_last3f
    del cc
    log('通過順 済み')

    # ---------------------------------------------------- t_day_trk → cls_lvl
    d['lnp'] = np.log(d.prize1.where(d.prize1 > 0))
    g = d.groupby(['track', 'd_idx']).agg(s_pz=('lnp', 'sum'), n_pz=('lnp', 'count')).reset_index()
    d = win(g, ['track'], ['s_pz', 'n_pz'], d, lo=365)
    d['cls_lvl'] = d.lnp - d.s_pz / d.n_pz.replace(0, np.nan)

    # ---------------------------------------------------- t_h1(馬の窓)
    d['wet_hit'] = d.hit3.where(d.going_ord >= 1)
    d['one'] = 1.0
    def hw(keys, cols, lo=None):
        nonlocal d
        agg = {}
        for c in cols:
            agg['s_' + c] = (c, 'sum')
            agg['n_' + c] = (c, 'count')
        gg = d.groupby(keys + ['d_idx']).agg(**agg).reset_index()
        d = win(gg, keys, list(agg), d, lo=lo)
        ren = {k: k + '_' + '_'.join(keys) + ('' if lo is None else str(lo)) for k in agg}
        d = d.rename(columns=ren)
        return ren
    hw(['horse_key'], ['hit3', 'wet_hit', 'earned'])
    hw(['horse_key', 'dist_band'], ['hit3'])
    hw(['horse_key', 'track'], ['hit3'])
    hw(['horse_key', 'yr'], ['hit3'])
    hw(['horse_key'], ['scratched'], lo=365)
    nz = lambda s: s.replace(0, np.nan)
    d['hit_car'] = d.s_hit3_horse_key / nz(d.n_hit3_horse_key)
    d['dist_fukusho_rate'] = d['s_hit3_horse_key_dist_band'] / nz(d['n_hit3_horse_key_dist_band'])
    d['dist_n'] = d['n_hit3_horse_key_dist_band']
    d['uma_place_fuku'] = d['s_hit3_horse_key_track'] / nz(d['n_hit3_horse_key_track'])
    d['uma_place_n'] = d['n_hit3_horse_key_track']
    d['wet_fuku'] = d.s_wet_hit_horse_key / nz(d.n_wet_hit_horse_key)
    d['wet_n'] = d.n_wet_hit_horse_key
    d['runs_this_year'] = d['n_hit3_horse_key_yr']
    d['season_debut'] = (d.runs_this_year == 0).astype(float)
    d['prize_local'] = d.s_earned_horse_key.where(d.n_earned_horse_key > 0)
    d['scratch_n_365'] = d['s_scratched_horse_key365']   # count(case when scr then 1) = 取消の和
    d['dist_match'] = d.dist_fukusho_rate - d.hit_car
    # t_fld → fld_loo
    f = d.groupby(['track', 'race_date', 'race_no']).agg(s_fld=('hit_car', 'sum'), n_fld=('hit_car', 'count')).reset_index()
    d = d.merge(f, on=['track', 'race_date', 'race_no'], how='left')
    d['fld_loo'] = (d.s_fld - d.hit_car.fillna(0)) / nz(d.n_fld - d.hit_car.notna().astype(int))
    log('馬の窓 済み')

    # ==================================================== (b) の材料(11/7 続き)
    f32 = lambda s: pd.Series(s, index=d.index).astype('float32').astype('float64')
    d['sa'] = d.margin.map(mlen)
    lp = d.furlongs.map(lap)
    d['lappace'], d['lapfade'] = [x[0] for x in lp], [x[1] for x in lp]
    d['dist_k'] = d.distance_m.fillna(-1)
    d['gord_k'] = d.going_ord.fillna(-1)
    d['t2'], d['l3h2'] = d.time_sec ** 2, d.last3f ** 2
    K3 = ['track', 'dist_k', 'gord_k']
    gg = d.groupby(K3 + ['d_idx']).agg(s_t=('time_sec', 'sum'), q_t=('t2', 'sum'), n_t=('time_sec', 'count'),
                                      s_l3=('race_last3f', 'sum'), n_l3=('race_last3f', 'count'),
                                      s_l3h=('last3f', 'sum'), q_l3h=('l3h2', 'sum'), n_l3h=('last3f', 'count')).reset_index()
    d = win(gg, K3, ['s_t', 'q_t', 'n_t', 's_l3', 'n_l3', 's_l3h', 'q_l3h', 'n_l3h'], d, lo=365)
    d['m_td'] = f32(d.s_t / nz(d.n_t))
    d['sd_td'] = f32(np.sqrt(np.maximum(d.q_t / nz(d.n_t) - (d.s_t / nz(d.n_t)) ** 2, 0)))
    d['m_l3'] = f32(d.s_l3 / nz(d.n_l3))
    d['m_l3h'] = f32(d.s_l3h / nz(d.n_l3h))
    d['sd_l3h'] = f32(np.sqrt(np.maximum(d.q_l3h / nz(d.n_l3h) - (d.s_l3h / nz(d.n_l3h)) ** 2, 0)))
    d = d.drop(columns=['s_t', 'q_t', 'n_t', 's_l3', 'n_l3', 's_l3h', 'q_l3h', 'n_l3h'])
    gg = d.groupby(['track', 'dist_k', 'd_idx']).agg(s_t=('time_sec', 'sum'), n_t=('time_sec', 'count')).reset_index()
    d = win(gg, ['track', 'dist_k'], ['s_t', 'n_t'], d, lo=365)
    d['m_dn'] = f32(d.s_t / nz(d.n_t))
    d = d.drop(columns=['s_t', 'n_t'])
    # t_baba(勝ち馬の時計 − 場×距離の平均 の中央値)・30 日の平均
    w = d[(d.finish == 1) & d.time_sec.notna() & d.m_dn.notna()]
    bb = (w.time_sec - w.m_dn).groupby([w.track, w.race_date]).median().astype('float32').astype('float64').rename('baba_d').reset_index()
    bb['d_idx'] = (pd.to_datetime(bb.race_date) - pd.Timestamp('2000-01-01')).dt.days.astype('int64')
    bb['bs'], bb['bn'] = bb.baba_d, 1.0
    bb = win(bb[['track', 'd_idx', 'bs', 'bn']], ['track'], ['bs', 'bn'], bb.drop(columns=['bs', 'bn']), lo=30)
    bb['baba_d_30'] = bb.bs / nz(bb.bn)
    d = d.merge(bb[['track', 'race_date', 'baba_d']], on=['track', 'race_date'], how='left')
    for c_, src in (('trk_recent_dmz', 'baba_d_30'), ('baba_diff_d', 'baba_d')):   # その日より前で最後の日の値
        z = latest(bb[['track', 'd_idx', src]], ['track'], [src], d[['track', 'd_idx']], strict=True)
        d[c_] = z[src].to_numpy()
    d['tz'] = f32((d.m_td - d.time_sec) / nz(d.sd_td))
    d['tza'] = f32((d.m_td - (d.time_sec - d.baba_d)) / nz(d.sd_td))
    d['rk_k'] = d.race_kind.fillna('?').astype(str)
    d['fs_k'] = d.field_size.fillna(-1)
    gg = d.groupby(['track', 'rk_k', 'fs_k', 'd_idx']).agg(s=('tz', 'sum'), n=('tz', 'count')).reset_index()
    d = win(gg, ['track', 'rk_k', 'fs_k'], ['s', 'n'], d, lo=365)
    d['rz'] = f32(d.tz - d.s / nz(d.n))
    d = d.drop(columns=['s', 'n'])
    gg = d.groupby(['track', 'd_idx']).agg(s=('tz', 'sum'), n=('tz', 'count')).reset_index()
    d = win(gg, ['track'], ['s', 'n'], d, lo=365)
    d['rzin'] = f32(d.tz - d.s / nz(d.n))
    d = d.drop(columns=['s', 'n'])
    d['ra_pace'] = f32(d.race_last3f - d.m_l3)
    d['l3z'] = f32((d.m_l3h - d.last3f) / nz(d.sd_l3h))
    # t_h2(馬の全部の前の日: 湿った馬場と良の tza の差・tz の最大)
    d['tza_w'] = d.tza.where(d.going_ord >= 1)
    d['tza_d'] = d.tza.where(d.going_ord == 0)
    gg = d.groupby(['horse_key', 'd_idx']).agg(sw=('tza_w', 'sum'), nw=('tza_w', 'count'), sd_=('tza_d', 'sum'), nd_=('tza_d', 'count')).reset_index()
    d = win(gg, ['horse_key'], ['sw', 'nw', 'sd_', 'nd_'], d)
    d['wet_tza_gap'] = f32(d.sw / nz(d.nw) - d.sd_ / nz(d.nd_))
    mx = d.groupby(['horse_key', 'd_idx']).tz.max().reset_index().sort_values(['horse_key', 'd_idx'])
    mx['cm'] = mx.groupby('horse_key').tz.cummax()
    mx = mx[mx.cm.notna()]
    z = latest(mx[['horse_key', 'd_idx', 'cm']], ['horse_key'], ['cm'], d[['horse_key', 'd_idx']], strict=True)
    d['best_tz_car'] = z.cm.to_numpy()
    # 前年の tz
    hz = d.groupby(['horse_key', 'yr']).tz.mean().rename('prevyear_timez').reset_index()
    hz['yr'] = hz.yr + 1
    d = d.merge(hz, on=['horse_key', 'yr'], how='left')
    log('時計の物差し 済み')

    # ---------------------------------------------------- t_rn・t_self・t_np・t_lay
    d = d.sort_values(['horse_key', 'race_date', 'track', 'race_no', 'runner_number']).reset_index(drop=True)
    s = d[d.is_run].copy()
    s['rn'] = s.groupby('horse_key').cumcount() + 1
    s['gap'] = s.groupby('horse_key').d_idx.diff()
    s['grp'] = (s.gap > 42).astype(int).groupby(s.horse_key).cumsum()
    s['since_at'] = s.groupby(['horse_key', 'grp']).cumcount().astype(float)
    gr = d.groupby(['horse_key', 'd_idx']).agg(nr=('is_run', 'sum')).reset_index()
    d = win(gr, ['horse_key'], ['nr'], d)
    d['n_prev'] = d.nr.astype(int)
    # p1_scratch = 前の日までの最後の行の取消
    ls = d.groupby(['horse_key', 'd_idx']).scratched.last().reset_index().rename(columns={'d_idx': 'pd_'})
    ls['t'] = ls.pd_ + 1
    q = d[['horse_key', 'd_idx']].reset_index().rename(columns={'d_idx': 't'}).sort_values('t')
    z = pd.merge_asof(q, ls.sort_values('t')[['horse_key', 't', 'scratched']], on='t', by='horse_key', direction='backward')
    d['p1_scratch'] = z.set_index('index').scratched.sort_index()
    SC = ['rn', 'finish', 'd_idx', 'track', 'distance_m', 'jockey', 'cls_lvl', 'p_pos2', 'p_pos4', 'pos3', 'pos4', 'fwd',
          'fld_loo', 'dist_match', 'season_debut', 'l3gap', 'body_weight', 'carried_weight', 'since_at',
          'sa', 'tz', 'rz', 'rzin', 'tza', 'lappace', 'lapfade', 'ra_pace', 'l3z']
    for k in range(1, 6):
        x = s[['horse_key'] + SC].rename(columns={c: f'p{k}_{c}' for c in SC})
        d['_rn'] = d.n_prev - (k - 1)
        d = d.merge(x, left_on=['horse_key', '_rn'], right_on=['horse_key', f'p{k}_rn'], how='left')
    log('前走 5 本 済み')

    # ---------------------------------------------------- 騎手・調教師・組(t_ent → t_asof)
    for kind, keys, lo in (('jk', ['jockey'], 365), ('tr', ['trainer'], 365), ('pr', ['trainer', 'jockey'], 1095), ('jk3', ['jockey'], 1095)):
        m = d[keys].notna().all(axis=1)
        gg = d[m].groupby(keys + ['d_idx']).agg(sh=('hit3', 'sum'), cn=('hit3', 'count')).reset_index()
        z = win(gg, keys, ['sh', 'cn'], d.loc[m, keys + ['d_idx']].drop_duplicates(), lo=lo, cnt_days=True)
        z[kind + '_f'] = z.sh / nz(z.cn)
        z[kind + '_n'] = z.cn.where(z._nd > 0)
        d = d.merge(z[keys + ['d_idx', kind + '_f', kind + '_n']], on=keys + ['d_idx'], how='left')
    d['kishu_fuku_1y'], d['kishu_n_1y'] = d.jk_f, d.jk_n
    d['chokyo_fuku_1y'], d['chokyo_n_1y'] = d.tr_f, d.tr_n
    d['pair_fuku_3y'], d['pair_n_3y'] = d.pr_f, d.pr_n
    d['pair_vs_kishu'] = d.pr_f - d.jk3_f

    # 乗り替わり t_jc・t_jcp・t_jct
    pj = d.p1_jockey
    d['changed'] = np.where(pj.notna() & d.jockey.notna(), (pj != d.jockey).astype(float), np.nan)
    rej = np.full(len(d), np.nan)
    seen = {}
    prev_key, day_buf, cur_day = None, [], None
    for i, (hk, di, jk, ch, p1) in enumerate(zip(d.horse_key, d.d_idx, d.jockey, d.changed, pj)):
        if hk != prev_key:
            seen, prev_key, day_buf, cur_day = set(), hk, [], di
        if di != cur_day:
            seen.update(day_buf)
            day_buf, cur_day = [], di
        if p1 is not None and isinstance(p1, str) and p1 != jk:
            rej[i] = float(jk in seen) if jk is not None else np.nan
        if jk is not None:
            day_buf.append(jk)
    d['jc_rejoin'] = rej
    d['norikae'] = d['jc_changed'] = d.changed
    ch = d[d.changed == 1]
    for nm, keys in (('jp', ['track', 'p1_jockey', 'jockey']), ('jt2', ['track', 'trainer', 'jockey'])):
        c2 = ch[ch[keys].notna().all(axis=1)]
        gg = c2.groupby(keys + ['d_idx']).agg(sh=('hit3', 'sum'), cn=('hit3', 'count')).reset_index()
        z = win(gg, keys, ['sh', 'cn'], c2[keys + ['d_idx']].drop_duplicates(), cnt_days=True)
        z[nm + '_hit'] = z.sh / nz(z.cn)
        z[nm + '_n'] = z.cn.where(z._nd > 0)
        z['_c'] = 1.0
        d = d.merge(z[keys + ['d_idx', nm + '_hit', nm + '_n', '_c']], on=keys + ['d_idx'], how='left')
        d = d.drop(columns='_c')
    d['jc_pair_n'], d['jc_pair_hit'], d['jc_tj_n'], d['jc_tj_hit'] = d.jp_n, d.jp_hit, d.jt2_n, d.jt2_hit

    # 前年 t_hyr
    hy = d.groupby(['horse_key', 'yr']).agg(prevyear_n=('hit3', 'count'), _s=('hit3', 'sum')).reset_index()
    hy['prevyear_fukusho'] = hy._s / nz(hy.prevyear_n.astype(float))
    hy['yr'] = hy.yr + 1
    d = d.merge(hy[['horse_key', 'yr', 'prevyear_n', 'prevyear_fukusho']], on=['horse_key', 'yr'], how='left')
    log('人の数 済み')

    # ---------------------------------------------------- (b) 血統・馬主・前の騎手・場の傾き
    d = d.merge(hs[['horse_name', 'sire', 'broodmare_sire', 'owner', 'breeder']], on='horse_name', how='left')
    d['band_s'] = d.dist_band.map(lambda v: str(int(v)) if pd.notna(v) else None)
    ent = {}

    def asof_ent(nm, keys, lo, rows=None, val='hit3'):
        """t_ent → t_asof: 鍵ごとの日の行と、その日の窓 [e-lo, e-1](lo=None は全部)の率・数(空の窓の数は空)"""
        x = d if rows is None else rows
        m = x[keys].notna().all(axis=1)
        gg = x[m].groupby(keys + ['d_idx']).agg(sh=('hit3', 'sum'), wn=('win1', 'sum'), cn=('hit3', 'count')).reset_index()
        z = win(gg, keys, ['sh', 'wn', 'cn'], gg[keys + ['d_idx']], lo=lo, cnt_days=True)
        z['f'] = z.sh / nz(z.cn)
        z['wr'] = z.wn / nz(z.cn)
        z['n'] = z.cn.where(z._nd > 0)
        ent[nm] = z[keys + ['d_idx', 'f', 'wr', 'n']]
        return ent[nm]
    d['win1'] = np.where(d.is_run, (d.finish == 1).astype(float), np.nan)
    for nm, keys, lo, outc in (('sb', ['sire', 'band_s'], None, 'sire'), ('mb', ['broodmare_sire', 'band_s'], None, 'mf'),
                               ('ow', ['owner'], 365, 'owner'), ('br', ['breeder'], 365, 'breeder')):
        z = asof_ent(nm, keys, lo)
        d = d.merge(z[keys + ['d_idx', 'f', 'n']].rename(columns={'f': outc + '_f', 'n': outc + '_n'}), on=keys + ['d_idx'], how='left')
    # 騎手(場×騎手)の 1 年・前の騎手の「その日より前で最後の」値
    d['tj_k'] = d.track + '|' + d.jockey.fillna('')
    d.loc[d.jockey.isna(), 'tj_k'] = None
    zjt = asof_ent('jt', ['tj_k'], 365)
    d = d.merge(zjt[['tj_k', 'd_idx', 'f', 'n']].rename(columns={'f': 'jt_f', 'n': 'jt_n'}), on=['tj_k', 'd_idx'], how='left')
    zjk = asof_ent('jk', ['jockey'], 365)
    q = d[['p1_jockey', 'd_idx']].rename(columns={'p1_jockey': 'jockey'})
    d['p1_kishu_fuku'] = latest(zjk[['jockey', 'd_idx', 'f']], ['jockey'], ['f'], q, strict=True).f.to_numpy()
    q = pd.DataFrame({'tj_k': np.where(d.p1_jockey.notna(), d.track + '|' + d.p1_jockey.fillna(''), None), 'd_idx': d.d_idx})
    pz = latest(zjt[['tj_k', 'd_idx', 'f', 'n']], ['tj_k'], ['f', 'n'], q, strict=True)
    d['pjt_f'], d['pjt_n'] = pz.f.to_numpy(), pz.n.to_numpy()
    dd = d.jt_f - d.pjt_f
    tier = np.where(dd >= 0.05, 1.0, np.where(dd <= -0.05, -1.0, 0.0))
    d['jc_tier'] = np.where((d.changed == 1) & (d.jt_n >= 20) & (d.pjt_n >= 20), tier, np.nan)
    # 場の傾き(t_bday → t_bias・その日より前で最後の日)
    x = d[d.is_run].copy()
    fs = x.field_size.replace(0, np.nan)
    x['g'], x['f'], x['q'], x['c'] = x.gate / fs, x.finish / fs, x.p_pos1, x.p_pos4
    agg = {}
    for a_, nm in (('g', 'gf'), ('q', 'qf'), ('c', 'cf')):
        both = x[a_].notna() & x.f.notna()
        x['n_' + nm] = both.astype(float)
        x['sa_' + nm] = x[a_].where(both)
        x['sb_' + nm] = x.f.where(both)
        x['sab_' + nm] = (x[a_] * x.f).where(both)
        x['saa_' + nm] = (x[a_] ** 2).where(both)
        x['sbb_' + nm] = (x.f ** 2).where(both)
        for p_ in ('n_', 'sa_', 'sb_', 'sab_', 'saa_', 'sbb_'):
            agg[p_ + nm] = (p_ + nm, 'sum')
    bd = x.groupby(['track', 'd_idx']).agg(**agg).reset_index()
    V_ = list(agg)
    b30 = win(bd, ['track'], V_, bd[['track', 'd_idx']], lo=30)
    b365 = win(bd, ['track'], V_, bd[['track', 'd_idx']], lo=365)

    def corr(b, nm):
        n, sa_, sb_, sab, saa, sbb = (b[p_ + nm] for p_ in ('n_', 'sa_', 'sb_', 'sab_', 'saa_', 'sbb_'))
        den = np.sqrt(np.maximum(n * saa - sa_ ** 2, 0)) * np.sqrt(np.maximum(n * sbb - sb_ ** 2, 0))
        return ((n * sab - sa_ * sb_) / den.replace(0, np.nan)).astype('float32').astype('float64')
    bias = bd[['track', 'd_idx']].copy()
    bias['waku_bias_30'], bias['waku_bias_365'] = corr(b30, 'gf'), corr(b365, 'gf')
    bias['pace_bias_30'], bias['pace_bias_365'] = corr(b30, 'qf'), corr(b365, 'qf')
    bias['baba_io_365'] = corr(b365, 'cf')
    BI = ['waku_bias_30', 'waku_bias_365', 'pace_bias_30', 'pace_bias_365', 'baba_io_365']
    z = latest(bias, ['track'], BI, d[['track', 'd_idx']], strict=True)
    for c_ in BI:
        d[c_] = z[c_].to_numpy()
    d['td_k'] = np.where(d.distance_m.notna(), d.track + '|' + d.distance_m.fillna(0).astype(int).astype(str), None)
    d['gate_s'] = d.gate.map(lambda v: str(int(v)) if pd.notna(v) else None)
    zcw = asof_ent('cw', ['td_k', 'gate_s'], 365)
    d = d.merge(zcw[['td_k', 'gate_s', 'd_idx', 'f']].rename(columns={'f': 'course_waku_hit'}), on=['td_k', 'gate_s', 'd_idx'], how='left')
    zcf = asof_ent('cf', ['td_k'], 365, rows=d[d.pos1 == 1])
    d['course_front_win'] = latest(zcf[['td_k', 'd_idx', 'wr']], ['td_k'], ['wr'], d[['td_k', 'd_idx']], strict=False).wr.to_numpy()
    xq = d[d.p_pos1.notna()].copy()
    xq['qb'] = np.minimum(3, np.floor(xq.p_pos1 * 4)).astype(int).astype(str)
    zcq = asof_ent('cq', ['td_k', 'qb'], 365, rows=xq)
    log('血統・騎手・傾き 済み')

    # ---------------------------------------------------- 当てる行だけに絞ってから最後の列
    d = d[(d.race_date >= out_from) & (d.race_date <= (out_to or '9999'))].reset_index(drop=True)
    o = pd.DataFrame(index=d.index)
    o['barei'], o['seibetsu'], o['tosu'], o['wakuban'] = d.age, d.sex.map(SEX), d.field_size, d.gate
    o['kyori'], o['keibajo'], o['futan'] = d.distance_m, d.track.map(JYO), d.carried_weight
    o['prize1_log'], o['race_month'], o['hasso_hour'] = d.lnp, d.rd.dt.month, d.hasso_hour
    P = lambda c: [f'p{k}_{c}' for k in range(1, 6)]
    for k in range(1, 6):
        o[f'p{k}_chaku'] = d[f'p{k}_finish']
        o[f'p{k}_pos2'] = d[f'p{k}_p_pos2']
        o[f'p{k}_pos4'] = d[f'p{k}_p_pos4']
        o[f'p{k}_dkyori'] = d.distance_m - d[f'p{k}_distance_m']
        o[f'p{k}_cls'] = d[f'p{k}_cls_lvl']
        o[f'p{k}_gap'] = d.d_idx - d[f'p{k}_d_idx']
        o[f'p{k}_same'] = np.where(d[f'p{k}_track'].notna(), (d.track == d[f'p{k}_track']).astype(float), np.nan)
    o['prev_chakujun'], o['prev_corner4'] = d.p1_finish, d.p1_pos4
    o['avg_chakujun_3'] = avg5(o, ['p1_chaku', 'p2_chaku', 'p3_chaku'])
    h3 = sum((o[c] <= 3).astype(float) for c in P('chaku'))
    o['fukusho_rate_5'] = h3 / cnt5(o, P('chaku')).replace(0, np.nan)
    o['days_since_prev'], o['dist_change'] = o.p1_gap, o.p1_dkyori
    o['track_change'] = 1 - o.p1_same
    o['futan_diff'], o['prev_bataiju'] = d.carried_weight - d.p1_carried_weight, d.p1_body_weight
    for c in ('dist_fukusho_rate', 'dist_n', 'kishu_fuku_1y', 'kishu_n_1y', 'chokyo_fuku_1y', 'chokyo_n_1y', 'uma_place_fuku',
              'uma_place_n', 'norikae', 'runs_this_year', 'season_debut', 'prevyear_fukusho', 'prevyear_n', 'wet_n', 'wet_fuku',
              'pair_fuku_3y', 'pair_n_3y', 'pair_vs_kishu', 'dist_match', 'jc_changed', 'jc_rejoin', 'jc_pair_n', 'jc_pair_hit',
              'jc_tj_n', 'jc_tj_hit', 'prize_local', 'scratch_n_365', 'p1_scratch'):
        o[c] = d[c]
    o['prev_pos2_rate'], o['prev_pos4_rate'] = o.p1_pos2, o.p1_pos4
    o['avg_pos2_3'] = avg5(o, ['p1_pos2', 'p2_pos2', 'p3_pos2'])
    o['class_diff'] = d.cls_lvl - d.p1_cls_lvl
    o['best_chaku_5'] = o[P('chaku')].min(axis=1)
    o['opp_str_now'] = d.fld_loo
    for k in (1, 2, 3):
        o[f'p{k}_fld'] = d[f'p{k}_fld_loo']
    o['avg_fld_3'] = avg5(o, ['p1_fld', 'p2_fld', 'p3_fld'])
    o['relief_3'] = o.avg_fld_3 - o.opp_str_now
    o['p1_season_debut'], o['p1_dist_match'] = d.p1_season_debut, d.p1_dist_match
    o['sex_summer'] = np.where(o.seibetsu.notna(), ((o.seibetsu == 1) & o.race_month.between(6, 8)).astype(float), np.nan)
    o['rest_leq3'] = np.where(o.p1_gap.notna(), (o.p1_gap <= 28).astype(float), np.nan)
    o['rest_gt42'] = np.where(o.p1_gap.notna(), (o.p1_gap > 42).astype(float), np.nan)
    c4 = [d[f'p{k}_pos4'] for k in range(1, 6)]
    c3 = [d[f'p{k}_pos3'] for k in range(1, 6)]
    ck = [o[f'p{k}_chaku'] for k in range(1, 6)]
    lead_n = sum((x == 1).astype(float) for x in c4)
    lead_lost = sum(((x == 1) & (y > 1)).astype(float) for x, y in zip(c4, ck))
    o['c4lead_lost_rate'] = lead_lost / lead_n.replace(0, np.nan)
    o['mak_gain_m3'] = pd.concat([c4[i] - ck[i] for i in range(3)], axis=1).mean(axis=1)
    f_n = sum((a.notna() & b.notna()).astype(float) for a, b in zip(c3, c4))
    f_d = sum((b > a).astype(float) for a, b in zip(c3, c4))
    o['fade34_rate5'] = f_d / f_n.replace(0, np.nan)
    o['qpts'] = d[[f'p{k}_fwd' for k in range(1, 6)]].mean(axis=1)
    mk = d.groupby(['track', 'race_date']).weight_mark.transform('count')
    o['minarai_now'] = np.where(mk > 0, d.weight_mark.notna().astype(float), np.nan)
    o['since_layoff'] = np.where(d.p1_d_idx.isna(), np.nan, np.where(o.p1_gap > 42, 0.0, d.p1_since_at + 1))
    o['has_hist'] = (d.n_prev > 0).astype(float)
    o['p1_l3gap'] = d.p1_l3gap
    o['prize_local_log'] = np.log(np.maximum(o.prize_local.fillna(0), 0) + 1)

    # ---- (b) の最後の列
    for k in range(1, 6):
        for c_ in ('sa', 'tz', 'rz'):
            o[f'p{k}_{c_}'] = d[f'p{k}_{c_}']
    for k in (1, 2, 3):
        o[f'p{k}_rzin'] = d[f'p{k}_rzin']
        o[f'p{k}_l3z'] = d[f'p{k}_l3z']
    o['prev_chakusa'] = o.p1_sa
    sa5 = [o[f'p{k}_sa'] for k in range(1, 6)]
    o['oshi_nose2'] = sum(((c_ == 2) & (s_ <= 0.05)).astype(float) for c_, s_ in zip(ck, sa5))
    o['oshi_nose4'] = sum(((c_ <= 4) & (s_ <= 0.30)).astype(float) for c_, s_ in zip(ck, sa5))
    o['oshi_rate'] = o.oshi_nose4 / cnt5(o, P('chaku')).replace(0, np.nan)
    TZ, RZ = P('tz'), P('rz')
    o['prev_time_z'] = o.p1_tz
    o['avg_time_z_3'] = avg5(o, TZ[:3])
    o['best_tz_5'], o['worst_tz_5'] = o[TZ].max(axis=1), o[TZ].min(axis=1)
    std5 = lambda cs: o[cs].std(axis=1, ddof=0).where(o[cs].notna().sum(axis=1) >= 2)
    o['std_tz_5'], o['n_tz_5'] = std5(TZ), cnt5(o, TZ)
    o['prev_time_za'] = d.p1_tza
    o['avg_time_za_3'] = d[['p1_tza', 'p2_tza', 'p3_tza']].mean(axis=1)
    o['prevyear_timez'] = d.prevyear_timez
    o['avg_rz_3'], o['avg_rz_5'], o['best_rz_5'] = avg5(o, RZ[:3]), avg5(o, RZ), o[RZ].max(axis=1)
    o['std_rz_5'], o['n_rz_5'] = std5(RZ), cnt5(o, RZ)
    o['avg_rzin_3'] = avg5(o, ['p1_rzin', 'p2_rzin', 'p3_rzin'])
    o['wet_tza_gap'] = d.wet_tza_gap
    o['prev_best5'] = o.best_tz_5 - d.best_tz_car
    o['bounce_risk'] = o.p1_tz - avg5(o, TZ[1:])
    o['trk_recent_dmz'], o['baba_diff_d'] = d.trk_recent_dmz, d.baba_diff_d
    o['prev_ra_pace'] = d.p1_ra_pace
    o['avg_l3z_3'] = avg5(o, ['p1_l3z', 'p2_l3z', 'p3_l3z'])
    o['best_l3z_5'] = d[[f'p{k}_l3z' for k in range(1, 6)]].max(axis=1)
    o['p1_lappace'], o['p1_lapfade'] = d.p1_lappace, d.p1_lapfade
    xs = np.array([-1.0, -2.0, -3.0, -4.0, -5.0])
    bw = d[[f'p{k}_body_weight' for k in range(1, 6)]].to_numpy('float64')
    mk_ = ~np.isnan(bw)
    n_ = mk_.sum(1)
    sx, sy = (xs * mk_).sum(1), np.nansum(bw, 1)
    sxy, sxx = np.nansum(bw * xs, 1), (xs * xs * mk_).sum(1)
    with np.errstate(invalid='ignore', divide='ignore'):
        sl = (n_ * sxy - sx * sy) / np.where(n_ * sxx - sx ** 2 == 0, np.nan, n_ * sxx - sx ** 2)
    o['bw_slope_5'] = np.where(n_ >= 2, sl, np.nan)
    o['pos2_var5'] = std5(P('pos2'))
    for c_ in ('sire_f', 'sire_n', 'mf_f', 'mf_n', 'owner_f', 'owner_n', 'breeder_f', 'breeder_n'):
        pass
    o['sire_fuku_band'], o['sire_n_band'] = d.sire_f, d.sire_n
    o['mf_fuku_band'], o['mf_n_band'] = d.mf_f, d.mf_n
    o['owner_hit'], o['owner_n'], o['breeder_hit'], o['breeder_n'] = d.owner_f, d.owner_n, d.breeder_f, d.breeder_n
    o['p1_kishu_fuku'] = d.p1_kishu_fuku
    o['kishu_delta'] = d.kishu_fuku_1y - d.p1_kishu_fuku
    o['jc_tier'] = d.jc_tier
    for c_ in ('waku_bias_30', 'waku_bias_365', 'pace_bias_30', 'pace_bias_365', 'baba_io_365', 'course_waku_hit', 'course_front_win'):
        o[c_] = d[c_]
    qb = pd.Series(np.where(o.qpts.notna(), np.minimum(3, np.floor((1 - o.qpts.fillna(0)) * 4)).astype(int).astype(str), '3'))   # Postgres の least(3, NULL) = 3
    o['course_pos_hit'] = latest(zcq[['td_k', 'qb', 'd_idx', 'f']], ['td_k', 'qb'], ['f'],
                                 pd.DataFrame({'td_k': d.td_k, 'qb': qb, 'd_idx': d.d_idx}), strict=False).f.to_numpy()

    # 脚質(facts.style_asof・その日の行だけ)
    log('脚質')
    u2 = u[(u.race_date >= (pd.Timestamp(out_from) - pd.DateOffset(months=13)).strftime('%Y-%m-%d'))][['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'birth_date', 'age']]
    cr = r.set_index(['track', 'race_date', 'race_no']).corners
    past = {}
    for t, rd_, no, un, hn, bd, ag in u2.itertuples(index=False):
        c = cr.get((t, rd_, no))
        p = F.position_of(c, un) if c else None
        hk = (hn, F.birth_year_of(bd, ag, rd_))
        past.setdefault(hk, []).append({'track': t, 'race_date': rd_, 'race_no': int(no), 'p': p})
    sty = []
    for t, rd_, hn, bd, ag in zip(d.track, d.race_date, d.horse_name, d.birth_date, d.age):
        if t == '帯広ば':
            sty.append(np.nan)
            continue
        s_, _, _ = F.style_asof(past.get((hn, F.birth_year_of(bd, ag, rd_)), []), t, rd_)
        sty.append(F.STYLE_CODE.get(s_, np.nan) if s_ else np.nan)
    o['style'] = sty
    o['avg_pos_5'] = 1 - o.qpts

    # レースの中(t_rank)
    o[['track', 'race_date', 'race_no', 'runner_number']] = d[['track', 'race_date', 'race_no', 'runner_number']]
    R = ['track', 'race_date', 'race_no']
    o['r_fuku5_pct'] = prank(o, R, 'fukusho_rate_5').where(o.fukusho_rate_5.notna())
    o['r_prize_pct'] = prank(o, R, 'prize_local').where(o.prize_local.notna())
    for c_, b_ in (('r_timez_pct', 'avg_time_z_3'), ('r_timeza_pct', 'avg_time_za_3'), ('r_rz_pct', 'avg_rz_3'),
                   ('r_bestrz_pct', 'best_rz_5'), ('r_l3z_pct', 'avg_l3z_3'), ('r_pchakusa_pct', 'p1_sa')):
        o[c_] = prank(o, R, b_).where(o[b_].notna())
    gq = o.groupby(R)
    o['race_qsum'] = gq.qpts.transform(lambda x: x.sum() if x.notna().any() else np.nan)
    o['race_qmax'] = gq.qpts.transform('max')
    o['lead_n'] = gq['style'].transform(lambda x: (x == 0).sum()).astype(float)
    o['n_front'] = gq['style'].transform(lambda x: (x <= 1).sum()).astype(float)
    ns = gq['style'].transform('count').astype(float)
    o['front_ratio'] = o.n_front / ns.replace(0, np.nan)
    # add_relative(float32 のまま)
    o['fld_n'] = gq.runner_number.transform('size').astype('float32')
    for c in REL_A + REL_B:
        x = o[c].astype('float32')
        g2 = x.groupby([o[b] for b in R])
        o['rel_' + c] = (x - g2.transform('mean')).astype('float32')
        o['rk_' + c] = g2.rank(pct=True, method='average').astype('float32')
    log('列 済み', o.shape)
    return o



C17 = ['ten_kb', 'ten_kb_dev', 'avg_f', 'ten_rank', 'gear_n', 'gear_hit', 'start_note_n', 'ill_n_365', 'ill_last_days',
       'noken_days', 'noken_time', 'is_noken_debut', 'sale_price', 'sale_year', 'race_sales', 'sales_vs_venue_avg', 'jockey_penalty_90d']


def build17(d, src):
    """ai_feat_20260908.sql の t_run(kb_*)・t_day_dn(s_f3)・t_h1(gear/note)・t_hist(p1_f3 …)・t_rank(ten_rank)・
    t_ill・t_noken・t_sale・t_pen・t_sales と同じ定義で 17 列を作る。
    d = t_run の行(KX・horse_name・horse_key・jockey・distance_m・finish・d_idx・race_date を持つ)。
    src = 元の表 {'kb','ill','noken','sale','pen','sales'}(DataFrame・noken は nar_meta の value の dict)。"""
    nz = lambda s: s.replace(0, np.nan)
    d = d.copy()
    d['rd'] = pd.to_datetime(d.race_date)
    d['is_run'] = d.finish.notna()
    d['hit3'] = np.where(d.is_run, (d.finish <= 3).astype(float), np.nan)
    # t_run の kb_*
    kb = src['kb'].rename(columns={'umaban': 'runner_number'})
    kb = kb.drop_duplicates(KX, keep='last')
    kb['kb_f3'], kb['kb_avgf'] = pd.to_numeric(kb.first3f, errors='coerce'), pd.to_numeric(kb.avg_f, errors='coerce')
    tr = lambda s: s.map(lambda v: v.strip() if isinstance(v, str) and v.strip() != '' else None)
    kb['kb_gear'], kb['kb_note'] = tr(kb.gear), tr(kb.start_note)
    d = d.merge(kb[KX + ['kb_f3', 'kb_avgf', 'kb_gear', 'kb_note']], on=KX, how='left')
    # t_day_dn → ten_dev(場×距離の 365 日の前半 3F の平均 − その走の前半 3F)
    d['dist_k'] = d.distance_m.fillna(-1)
    g = d.groupby(['track', 'dist_k', 'd_idx']).agg(s_f3=('kb_f3', 'sum'), n_f3=('kb_f3', 'count')).reset_index()
    d = win(g, ['track', 'dist_k'], ['s_f3', 'n_f3'], d, lo=365)
    d['ten_dev'] = d.s_f3 / nz(d.n_f3) - d.kb_f3
    # t_h1 の gear_hit・gear_n・start_note_n(馬の全歴・前日まで)
    gy = d.is_run & d.kb_gear.notna()
    d['_gh'], d['_gc'] = d.hit3.where(gy), gy.astype(float)
    d['_nn'] = (d.is_run & d.kb_note.notna()).astype(float)
    g = d.groupby(['horse_key', 'd_idx']).agg(gh=('_gh', 'sum'), gc=('_gc', 'sum'), nn=('_nn', 'sum')).reset_index()
    d = win(g, ['horse_key'], ['gh', 'gc', 'nn'], d)
    d['gear_n'], d['gear_hit'], d['start_note_n'] = d.gc, d.gh / nz(d.gc), d.nn
    # t_np・t_self の p1(前日までの最後の走)
    d = d.sort_values(['horse_key', 'race_date', 'track', 'race_no', 'runner_number']).reset_index(drop=True)
    s = d[d.is_run].copy()
    s['rn'] = s.groupby('horse_key').cumcount() + 1
    gr = d.groupby(['horse_key', 'd_idx']).agg(nr=('is_run', 'sum')).reset_index()
    d = win(gr, ['horse_key'], ['nr'], d)
    d['n_prev'] = d.nr.astype(int)
    x = s[['horse_key', 'rn', 'kb_f3', 'kb_avgf', 'ten_dev']].rename(columns={'rn': 'n_prev', 'kb_f3': 'ten_kb', 'kb_avgf': 'avg_f',
                                                                              'ten_dev': 'ten_kb_dev'})
    d = d.merge(x, on=['horse_key', 'n_prev'], how='left')
    d['ten_rank'] = prank(d, ['track', 'race_date', 'race_no'], 'ten_kb_dev').where(d.ten_kb_dev.notna())
    # t_ill(公表日、無ければ出来事の日・その走の日より前)
    il = src['ill']
    il = il[il.horse_name.notna()].copy()
    il['kd'] = pd.to_datetime(il.reported_date.fillna(il.event_date), errors='coerce')
    il = il[il.kd.notna()]
    il['horse_key'] = il.horse_name + '|' + il.birth_date.fillna('').astype(str)
    q = d[['horse_key', 'rd']].reset_index().merge(il[['horse_key', 'kd']], on='horse_key')
    q = q[q.kd < q.rd]
    q['in365'] = q.kd > q.rd - pd.Timedelta(days=365)
    ag = q.groupby('index').agg(n365=('in365', 'sum'), mx=('kd', 'max'))
    d['ill_n_365'] = ag.n365.reindex(d.index).fillna(0).astype(float)
    d['ill_last_days'] = (d.rd - ag.mx.reindex(d.index)).dt.days.astype(float)
    # t_noken(馬名だけの鍵・その走の日より前の最後の能検)
    import re
    nk = []
    for hn, es in (src['noken'].get('horses') or {}).items():
        for e in es:
            dt, tm = str(e.get('date') or ''), str(e.get('time') if e.get('time') is not None else '')
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', dt):
                continue
            if re.fullmatch(r'[0-9]+:[0-9.]+', tm):
                a_, b_ = tm.split(':', 1)
                ns = float(np.float32(float(a_) * 60 + float(np.float32(b_))))
            elif re.fullmatch(r'[0-9.]+', tm):
                ns = float(np.float32(tm))
            else:
                ns = np.nan
            nk.append((hn, dt, ns))
    nk = pd.DataFrame(nk, columns=['horse_name', 'ndate', 'nsec'])
    nk['d_idx'] = (pd.to_datetime(nk.ndate) - pd.Timestamp('2000-01-01')).dt.days
    nk['nd'] = nk.d_idx.astype(float)
    nk = nk.sort_values(['horse_name', 'd_idx', 'nsec'])
    z = latest(nk, ['horse_name'], ['nd', 'nsec'], d)
    d['noken_days'] = (d.d_idx - z.nd.to_numpy()).astype(float)
    d['noken_time'] = z.nsec.to_numpy()
    d['is_noken_debut'] = (d.n_prev == 0).astype(float).where(d.noken_days.notna())
    # t_sale(その走の日より前の最後のせり)
    sl = src['sale']
    sl = sl[sl.horse_name.notna() & sl.auction_date.notna() & sl.price.notna()].copy()
    sl['horse_key'] = sl.horse_name + '|' + sl.birth_date.fillna('').astype(str)
    sl['d_idx'] = (pd.to_datetime(sl.auction_date) - pd.Timestamp('2000-01-01')).dt.days
    sl['yr_'] = pd.to_datetime(sl.auction_date).dt.year.astype(float)
    z = latest(sl, ['horse_key'], ['price', 'yr_'], d)
    d['sale_price'], d['sale_year'] = z.price.to_numpy(), z.yr_.to_numpy()
    # t_pen(騎手の制裁・その走の日の前 90 日・件数。無ければ 0)
    pn = src['pen']
    pn = pn[(pn.person_kind == 'jockey') & pn.person_name.notna() & pn.race_date.notna()].copy()
    pn['d_idx'] = (pd.to_datetime(pn.race_date) - pd.Timestamp('2000-01-01')).dt.days
    pn = pn.rename(columns={'person_name': 'jockey'}).assign(c=1.0).groupby(['jockey', 'd_idx']).c.sum().reset_index()
    m = d.jockey.notna()
    z = win(pn, ['jockey'], ['c'], d.loc[m, ['jockey', 'd_idx']].drop_duplicates(), lo=90)
    d = d.merge(z.rename(columns={'c': 'jockey_penalty_90d'}), on=['jockey', 'd_idx'], how='left')
    d['jockey_penalty_90d'] = d.jockey_penalty_90d.fillna(0.0)
    # t_sales(nar_sales_daily の場の 1 日 1 レースあたりの売上・前の開催日までの 30 日 / 365 日)
    import json
    sv = src['sales'].copy()

    def net(vj, rj):
        v, r_ = json.loads(vj), json.loads(rj) if isinstance(rj, str) else {}
        return sum(int(v[k] or 0) - int((r_ or {}).get(k) or 0) for k in v)
    sv['net'] = [net(a_, b_) for a_, b_ in zip(sv.votes, sv.refunds)]
    sd = sv.groupby(['track', 'race_date']).agg(v=('net', 'sum'), c=('net', 'size')).reset_index()
    sd['c'] = sd.c.clip(lower=1).astype(float)
    sd['v'] = sd.v.astype(float)
    sd['d_idx'] = (pd.to_datetime(sd.race_date) - pd.Timestamp('2000-01-01')).dt.days
    a30 = win(sd[['track', 'd_idx', 'v', 'c']], ['track'], ['v', 'c'], sd[['track', 'd_idx']], lo=30)
    a365 = win(sd[['track', 'd_idx', 'v', 'c']], ['track'], ['v', 'c'], sd[['track', 'd_idx']], lo=365)
    sd = sd[['track', 'd_idx']].assign(avg30=(a30.v / nz(a30.c)).to_numpy(), avg365=(a365.v / nz(a365.c)).to_numpy())
    z = latest(sd, ['track'], ['avg30', 'avg365'], d)
    d['race_sales'] = z.avg30.to_numpy().astype('float32').astype('float64')
    d['sales_vs_venue_avg'] = (z.avg30 / z.avg365.replace(0, np.nan)).to_numpy()
    return d



OUT_COLS = ['track', 'race_date', 'race_no', 'runner_number', 'barei', 'seibetsu', 'tosu', 'wakuban', 'kyori', 'keibajo', 'futan', 'prize1_log', 'race_month', 'hasso_hour', 'p1_chaku', 'p1_pos2', 'p1_pos4', 'p1_dkyori', 'p1_cls', 'p1_gap', 'p1_same', 'p2_chaku', 'p2_pos2', 'p2_pos4', 'p2_dkyori', 'p2_cls', 'p2_gap', 'p2_same', 'p3_chaku', 'p3_pos2', 'p3_pos4', 'p3_dkyori', 'p3_cls', 'p3_gap', 'p3_same', 'p4_chaku', 'p4_pos2', 'p4_pos4', 'p4_dkyori', 'p4_cls', 'p4_gap', 'p4_same', 'p5_chaku', 'p5_pos2', 'p5_pos4', 'p5_dkyori', 'p5_cls', 'p5_gap', 'p5_same', 'prev_chakujun', 'prev_corner4', 'avg_chakujun_3', 'fukusho_rate_5', 'days_since_prev', 'dist_change', 'track_change', 'futan_diff', 'prev_bataiju', 'dist_fukusho_rate', 'dist_n', 'kishu_fuku_1y', 'kishu_n_1y', 'chokyo_fuku_1y', 'chokyo_n_1y', 'uma_place_fuku', 'uma_place_n', 'norikae', 'runs_this_year', 'season_debut', 'prevyear_fukusho', 'prevyear_n', 'wet_n', 'wet_fuku', 'pair_fuku_3y', 'pair_n_3y', 'pair_vs_kishu', 'dist_match', 'jc_changed', 'jc_rejoin', 'jc_pair_n', 'jc_pair_hit', 'jc_tj_n', 'jc_tj_hit', 'prize_local', 'scratch_n_365', 'p1_scratch', 'prev_pos2_rate', 'prev_pos4_rate', 'avg_pos2_3', 'class_diff', 'best_chaku_5', 'opp_str_now', 'p1_fld', 'p2_fld', 'p3_fld', 'avg_fld_3', 'relief_3', 'p1_season_debut', 'p1_dist_match', 'sex_summer', 'rest_leq3', 'rest_gt42', 'c4lead_lost_rate', 'mak_gain_m3', 'fade34_rate5', 'qpts', 'minarai_now', 'since_layoff', 'has_hist', 'p1_l3gap', 'prize_local_log', 'p1_sa', 'p1_tz', 'p1_rz', 'p2_sa', 'p2_tz', 'p2_rz', 'p3_sa', 'p3_tz', 'p3_rz', 'p4_sa', 'p4_tz', 'p4_rz', 'p5_sa', 'p5_tz', 'p5_rz', 'p1_rzin', 'p1_l3z', 'p2_rzin', 'p2_l3z', 'p3_rzin', 'p3_l3z', 'prev_chakusa', 'oshi_nose2', 'oshi_nose4', 'oshi_rate', 'prev_time_z', 'avg_time_z_3', 'best_tz_5', 'worst_tz_5', 'std_tz_5', 'n_tz_5', 'prev_time_za', 'avg_time_za_3', 'prevyear_timez', 'avg_rz_3', 'avg_rz_5', 'best_rz_5', 'std_rz_5', 'n_rz_5', 'avg_rzin_3', 'wet_tza_gap', 'prev_best5', 'bounce_risk', 'trk_recent_dmz', 'baba_diff_d', 'prev_ra_pace', 'avg_l3z_3', 'best_l3z_5', 'p1_lappace', 'p1_lapfade', 'bw_slope_5', 'pos2_var5', 'sire_fuku_band', 'sire_n_band', 'mf_fuku_band', 'mf_n_band', 'owner_hit', 'owner_n', 'breeder_hit', 'breeder_n', 'p1_kishu_fuku', 'kishu_delta', 'jc_tier', 'waku_bias_30', 'waku_bias_365', 'pace_bias_30', 'pace_bias_365', 'baba_io_365', 'course_waku_hit', 'course_front_win', 'course_pos_hit', 'style', 'avg_pos_5', 'r_fuku5_pct', 'r_prize_pct', 'r_timez_pct', 'r_timeza_pct', 'r_rz_pct', 'r_bestrz_pct', 'r_l3z_pct', 'r_pchakusa_pct', 'race_qsum', 'race_qmax', 'lead_n', 'n_front', 'front_ratio', 'ten_kb', 'ten_kb_dev', 'avg_f', 'ten_rank', 'gear_n', 'gear_hit', 'start_note_n', 'ill_n_365', 'ill_last_days', 'noken_days', 'noken_time', 'is_noken_debut', 'sale_price', 'sale_year', 'race_sales', 'sales_vs_venue_avg', 'jockey_penalty_90d']


# ============================================================ 元を読む(便の中)
def in_copy_range(x, hi):
    """nar-ai-feat.yml の写しの範囲(2022-11 以降+高知 2014〜)・hi まで"""
    rd = x.race_date.astype(str).str[:10]
    return x[(rd <= hi) & ((rd >= '2022-11-01') | (x.track == '高知'))].assign(race_date=rd)


def _pages(K, path):
    out, off = [], 0
    while True:
        r = K.sb.get(f'{path}&limit=1000&offset={off}')
        out += r
        if len(r) < 1000:
            return out
        off += 1000


def fetch_pt(K, day):
    """発走時刻とラップ(nar_races の post_time・furlongs)を写しの範囲だけ。K0_CACHE があれば控えに持ち、直近 92 日を含む月から読み直す(7 日に 1 回は丸ごと)。
    ⛔k0_dl の races の控えとは別の名前(v3nbf_pt)で置く(k0 の races の列は変えない= 他の便に響かない)。"""
    cache = Path(os.environ['K0_CACHE']) if os.environ.get('K0_CACHE') else None
    f, mf = (cache / 'v3nbf_pt.parquet', cache / 'v3nbf_pt.json') if cache else (None, None)
    today = dt.date.fromisoformat(day)
    base = None
    if f is not None and f.exists() and mf.exists():
        m = json.loads(mf.read_text(encoding='utf-8'))
        if (today - dt.date.fromisoformat(m['full'])).days < 7:
            base = pd.read_parquet(f)
    since = (today - dt.timedelta(days=92)).replace(day=1).isoformat() if base is not None else None
    end = (today + dt.timedelta(days=40)).strftime('%Y-%m')
    jobs = []
    for t in K.TR:
        start = '2014-01' if t == '高知' else '2022-11'
        for p in pd.period_range(start, end, freq='M'):
            a, b = str(p.start_time.date()), str(p.end_time.date())
            if since is None or a >= since:
                jobs.append((t, a, b))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as ex:
        parts = list(ex.map(lambda j: _pages(K, f'/rest/v1/nar_races?select=track,race_date,race_no,post_time,furlongs&track=eq.{K.q(j[0])}'
                                                f'&race_date=gte.{j[1]}&race_date=lte.{j[2]}&order=race_date,race_no'), jobs))
    df = pd.DataFrame([x for p in parts for x in p], columns=['track', 'race_date', 'race_no', 'post_time', 'furlongs'])
    if base is not None:
        df = pd.concat([base[base.race_date < since], df], ignore_index=True)
    dup = int(df.duplicated(['track', 'race_date', 'race_no']).sum())
    if dup:
        raise RuntimeError(f'発走時刻の表に同じ行が {dup} 本(取り方の誤り)')
    if f is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(f, index=False)
        if base is None:
            mf.write_text(json.dumps({'full': day}), encoding='utf-8')
            (cache / 'dirty.flag').write_text('v3nbf_pt\n', encoding='utf-8')   # 丸ごと読んだ回だけ控えを保存させる(k0_dl と同じ印)
    log('発走時刻とラップ', len(df), '行', f'(控え+{since}〜)' if since else '(丸ごと)')
    return df


def _all(K, table, sel, order):
    rows, off = [], 0
    while True:
        r = K.sb.get(f'/rest/v1/{table}?select={sel}&order={order}&limit=1000&offset={off}')
        rows += r
        if len(r) < 1000:
            break
        off += 1000
    return pd.DataFrame(rows, columns=sel.split(','))


def fetch_small(K, day):
    """競馬ブックの成績・セリ・病気・制裁・売上・能検の索引・馬の表(その日の値)。V3N_BF_SRC があれば手元の写しを読む(照合用)"""
    loc = os.environ.get('V3N_BF_SRC', '')
    if loc:
        loc = Path(loc)

        def rd(n, **k):
            return pd.read_csv(loc / f'{n}.csv.gz', **k)
        src = {'kb': rd('nar_kb_runs', usecols=['track', 'race_date', 'race_no', 'umaban', 'gear', 'first3f', 'avg_f', 'start_note'],
                        dtype={'race_date': str}),
               'ill': rd('nar_horse_health_events', usecols=['horse_name', 'birth_date', 'event_date', 'reported_date'], dtype=str),
               'sale': rd('auction_sales', usecols=['horse_name', 'birth_date', 'auction_date', 'price'], dtype={'birth_date': str, 'auction_date': str}),
               'pen': rd('nar_penalties', usecols=['race_date', 'person_kind', 'person_name'], dtype=str),
               'sales': rd('nar_sales', usecols=['track', 'race_date', 'race_no', 'votes', 'refunds'], dtype={'race_date': str})}
        mt = rd('nar_meta')
        src['noken'] = json.loads(mt.loc[mt.key == 'noken_index', 'value'].iloc[0])
        hs = pd.read_parquet(loc / 'nar_horses.parquet', columns=['horse_name', 'sire', 'broodmare_sire', 'owner', 'breeder'])
        return src, hs
    src = {'kb': _all(K, 'nar_kb_runs', 'track,race_date,race_no,umaban,gear,first3f,avg_f,start_note', 'track,race_date,race_no,umaban'),
           'ill': _all(K, 'nar_horse_health_events', 'event_id,horse_name,birth_date,event_date,reported_date', 'event_id'),
           'sale': _all(K, 'auction_sales', 'source,item_id,horse_name,birth_date,auction_date,price', 'source,item_id'),
           'pen': _all(K, 'nar_penalties', 'penalty_id,race_date,person_kind,person_name', 'penalty_id'),
           'sales': _all(K, 'nar_sales', 'track,race_date,race_no,votes,refunds', 'track,race_date,race_no')}
    for c in ('votes', 'refunds'):
        src['sales'][c] = src['sales'][c].map(lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v)
    for k_, v_ in (('kb', ['track', 'race_date', 'race_no', 'umaban']), ('sales', ['track', 'race_date', 'race_no']), ('sale', ['source', 'item_id'])):
        dup = int(src[k_].duplicated(v_).sum())
        if dup:
            raise RuntimeError(f'{k_} に同じ行が {dup} 本(取り方の誤り)')
    x = K.sb.get('/rest/v1/nar_meta?select=value&key=eq.noken_index')
    src['noken'] = x[0]['value'] if x else {}
    hs = _all(K, 'nar_horses', 'horse_name,sire,broodmare_sire,owner,breeder', 'horse_name')
    log('小さい表', {k_: len(v_) for k_, v_ in src.items() if isinstance(v_, pd.DataFrame)},
        '能検', len(src['noken'].get('horses') or {}), '頭・馬の表', len(hs))
    return src, hs


def load_facts():
    p = Path(__file__).resolve().parents[2] / 'facts.py'
    spec = importlib.util.spec_from_file_location('facts_bf', p)
    F = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(F)
    return F


def make(off, day, out_csv, K):
    """その日の出走の行の 210 列(+鍵)を out_csv に書いて、行数を返す。off = k0_dl の出口(runs・races)・K = k0_dl(読み口)"""
    off = Path(off)
    t0 = time.time()
    u = in_copy_range(pd.read_parquet(off / 'runs.parquet'), day)
    r = in_copy_range(pd.read_parquet(off / 'races.parquet', columns=['track', 'race_date', 'race_no', 'distance_m', 'field_size', 'going',
                                                                       'prize_yen', 'race_last3f', 'corners', 'race_kind']), day)
    loc = os.environ.get('V3N_BF_SRC', '')
    pt = pd.read_parquet(Path(loc) / 'pt.parquet') if loc else fetch_pt(K, day)
    pt['race_date'] = pt.race_date.astype(str).str[:10]
    pt = pt[pt.race_date <= day].drop_duplicates(['track', 'race_date', 'race_no'], keep='last')
    pt['race_no'] = pd.to_numeric(pt.race_no, errors='coerce').astype('int64')
    u['race_no'] = pd.to_numeric(u.race_no, errors='coerce').astype('int64')
    u['runner_number'] = pd.to_numeric(u.runner_number, errors='coerce').astype('int64')
    r['race_no'] = pd.to_numeric(r.race_no, errors='coerce').astype('int64')
    r = r.merge(pt, on=['track', 'race_date', 'race_no'], how='left')
    r['corners'] = r.corners.map(lambda x: list(x) if x is not None and not isinstance(x, float) else None)
    src, hs = fetch_small(K, day)
    for k_ in ('kb', 'pen', 'sales'):
        src[k_] = src[k_][src[k_].race_date.astype(str).str[:10] <= day]
    F = load_facts()
    o = build_ab(F, u, r, pt, hs, day, day)
    d = u[['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'birth_date', 'jockey', 'finish']].merge(
        r[['track', 'race_date', 'race_no', 'distance_m']], on=['track', 'race_date', 'race_no'], how='inner')
    d = d[~d.duplicated(KX, keep=False)].reset_index(drop=True)
    d['d_idx'] = (pd.to_datetime(d.race_date) - pd.Timestamp('2000-01-01')).dt.days.astype('int64')
    d['horse_key'] = d.horse_name + '|' + d.birth_date.fillna('').astype(str)
    d['jockey'] = d.jockey.map(lambda s: s.strip() if isinstance(s, str) and s.strip() != '' else None)
    e = build17(d, src)
    e = e[e.race_date == day]
    o = o.copy()
    o['race_no'], o['runner_number'] = o.race_no.astype('int64'), o.runner_number.astype('int64')
    o = o.merge(e[KX + C17], on=KX, how='left', validate='1:1')
    miss = [c for c in OUT_COLS if c not in o.columns]
    if miss:
        raise RuntimeError(f'作れなかった列 {miss[:5]}')
    o[OUT_COLS].to_csv(out_csv, index=False)
    log('自分の材料表', day, len(o), '行', f'{time.time() - t0:.0f} 秒')
    return len(o)


def compare(own_csv, site_csv, day, tracks):
    """その日・その場の行で、自分の材料表とサイトの材料表を 210 列すべて比べる → (同じか(比べられなければ None), 説明)"""
    def rd(p):
        return pd.concat([c[(c.race_date.astype(str).str[:10] == day) & c.track.isin(tracks)]
                          for c in pd.read_csv(p, chunksize=200_000, low_memory=False, dtype={'race_date': str, 'track': str})])
    a = rd(own_csv)
    try:
        b = rd(site_csv)
    except Exception as e:  # noqa: BLE001
        return None, f'サイトの表を読めない {type(e).__name__}'
    if b.empty:
        return None, 'サイトの表にその日の行が無い'
    for x in (a, b):
        x['race_date'] = x.race_date.str[:10]
        x['race_no'], x['runner_number'] = x.race_no.astype('int64'), x.runner_number.astype('int64')
    m = a.merge(b, on=KX, how='outer', suffixes=('', '_s'), indicator=True)
    only = int((m._merge != 'both').sum())
    m = m[m._merge == 'both']
    bad = {}
    for c in OUT_COLS[4:]:
        if c + '_s' not in m.columns:
            bad[c] = 'サイトに列が無い'
            continue
        x = pd.to_numeric(m[c], errors='coerce').to_numpy('float64')
        y = pd.to_numeric(m[c + '_s'], errors='coerce').to_numpy('float64')
        ok = (np.isnan(x) & np.isnan(y)) | (np.abs(x - y) <= 1e-3 * np.maximum(1, np.abs(y)))
        if not ok.all():
            bad[c] = int((~ok).sum())
    same = only == 0 and not bad
    msg = f'行 {len(m)}・片方だけの行 {only}・合わない列 {len(bad)}' + (f' {dict(list(bad.items())[:6])}' if bad else '')
    return same, msg
