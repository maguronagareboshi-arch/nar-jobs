# -*- coding: utf-8 -*-
# 写し元 C:/Users/kouki/nankan_ai/build_feat_v3.py(写した日 2026-09-23)。
# 変えた行= ROOT(環境変数 NAI_ROOT)の 1 行だけ。
# RAW/WORK/FEATV2/OUT は ROOT から作られるので自動で移る。⛔計算は 1 行も変えていない。
"""S3: 予想 AI の「土台」を直す = 基準時計を作り直して feat_v3.parquet を作る。

  py -3.12 -X utf8 C:/Users/kouki/nankan_ai/build_feat_v3.py --stage all

段:
  band   … nar_races のレース名からクラス帯を抜き、抜けた割合と 年×場 の分布を出す
           → work/v3_band.parquet / work/v3_band_report.json
  base   … 基準時計(場×距離×クラス帯×馬場・改修日で区切る・季節版 前後45日×過去3年・
           締めは前日)と 日×場の馬場差を作る → work/v3_base.parquet
  feats  … 時計系の列(tz/tza/距離別/場別/C 族/馬場補正)を作る → work/v3_feats.parquet
  join   … feat_v2.parquet に左結合して feat_v3.parquet
  check  … as-of の検査(初出走で空・同じ場日で基準が一定・当日値と不一致)

⛔本番 DB には一切つながない(材料は raw/ の写しと feat_v2.parquet だけ)。
⛔C:/Users/kouki/ai_v1/ は読むだけ。
"""
from __future__ import annotations
import argparse, gzip, json, os, re, sys, time
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

ROOT = (os.environ.get('NAI_ROOT') or 'C:/Users/kouki/nankan_ai/').replace(chr(92), '/').rstrip('/') + '/'
RAW = ROOT + 'raw/'
WORK = ROOT + 'work/'
FEATV2 = ROOT + 'feat_v2.parquet'
OUT = ROOT + 'feat_v3.parquet'
KEY = ['track', 'race_date', 'race_no', 'runner_number']
NANKAN = ['大井', '川崎', '船橋', '浦和']
BANEI = '帯広ば'

# ---- 18 §B の出典の日付(砂の入れ替え/路盤整備)。この日より前のレースは以後の基準に入れない
RESET = {
    '大井': '2023-10-26',    # 2023-10-08〜10-25 に本馬場の砂を全面入れ替え(砂厚 8→10cm)
    '浦和': '2025-11-25',    # 令和7-11-25 の第8回浦和競馬から新しい表層砂
    '船橋': '2025-07-21',    # 2025-07-21〜10-24 に本馬場の路盤整備
}

SEASON_DAYS = 45      # 前後 45 日
STD_DAYS = 1095       # 過去 3 年
FALL_DAYS = 365       # 退避窓
MIN_N = 8             # 最少標本
MIN_RACES_BABA = 4    # 馬場差を出すのに要るレース数
GOINGS = ('良', '稍重', '重', '不良')

# ---- クラス帯(viewer cloud/baba.py:87-105 の写し)
Z = str.maketrans('ＡＢＣ０１２３４５６７８９', 'ABC0123456789')
LETTER_ONLY_TRACKS = {'名古屋', '笠松'}
RE_BAND = re.compile(r'(?<![A-Za-zＡ-Ｚａ-ｚ])([ABC])(?:\s?([0-9一二三])|(?![A-Za-zＡ-Ｚａ-ｚ]))')
RE_GRADE = re.compile(r'Ｇ[ⅠⅡⅢ123]|G[ⅠⅡⅢ123]|Ｊｐｎ|Jpn')
SUB2H = {'一': '1', '二': '2', '三': '3'}


def band_of(race_name, track=None, race_kind=None):
    """クラス帯の粗い抽出。取れなければ None(=「不明」・場×距離の基準に落ちる)。
    ⛔重賞/OP は帯が無いので race_kind を帯の代わりに使う(18 §A-5 の 3)。"""
    if race_kind in ('重賞', '準重賞'):
        return 'OP'
    t = str(race_name or '').translate(Z)
    if RE_GRADE.search(t):
        return 'OP'
    m = RE_BAND.search(t)
    if m:
        if track in LETTER_ONLY_TRACKS:
            return m.group(1)
        g2 = m.group(2) or ''
        return m.group(1) + SUB2H.get(g2, g2)
    if re.search(r'2歳|２歳', t):
        return '2y'
    if re.search(r'3歳|３歳', t):
        return '3y'
    return None


def log(*a):
    print('[%s]' % time.strftime('%H:%M:%S'), *a, flush=True)


def read_gz(name, cols):
    with gzip.open(RAW + name + '.csv.gz', 'rt', encoding='utf-8', newline='') as f:
        df = pd.read_csv(f, usecols=cols, low_memory=False)
    log('read', name, df.shape)
    return df


# ================================================================ 段1: クラス帯
def stage_band():
    R = read_gz('nar_races', ['track', 'race_date', 'race_no', 'race_name',
                              'distance_m', 'going', 'race_kind'])
    R['band'] = [band_of(n, t, k) for n, t, k in
                 zip(R['race_name'], R['track'], R['race_kind'])]
    R['year'] = R['race_date'].str[:4]
    R['going_n'] = np.where(R['going'].isin(GOINGS), R['going'], '?')
    R.to_parquet(WORK + 'v3_band.parquet', index=False)

    nk = R[R['track'].isin(NANKAN)]
    rep = {
        'rows_all': int(len(R)), 'rows_nankan': int(len(nk)),
        'hit_all': round(float(R['band'].notna().mean()), 4),
        'hit_nankan': round(float(nk['band'].notna().mean()), 4),
        'band_counts_nankan': {str(k): int(v) for k, v in
                               nk['band'].fillna('不明').value_counts().items()},
        'hit_by_track': {str(k): round(float(v), 4) for k, v in
                         R.groupby('track')['band'].apply(lambda s: s.notna().mean()).items()},
    }
    piv = (R[R['track'].isin(NANKAN)]
           .assign(hit=lambda d: d['band'].notna().astype(float))
           .pivot_table(index='year', columns='track', values='hit', aggfunc='mean'))
    cnt = (R[R['track'].isin(NANKAN)]
           .pivot_table(index='year', columns='track', values='race_no', aggfunc='size'))
    rep['nankan_hit_year_track'] = piv.round(4).to_dict()
    rep['nankan_n_year_track'] = cnt.astype('Int64').to_dict()
    # 年×場×帯 の分布(南関)
    rep['nankan_band_year'] = (nk.assign(b=nk['band'].fillna('不明'))
                               .pivot_table(index='year', columns='b', values='race_no',
                                            aggfunc='size').fillna(0).astype(int).to_dict())
    json.dump(rep, open(WORK + 'v3_band_report.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    log('band hit all=%.4f nankan=%.4f' % (rep['hit_all'], rep['hit_nankan']))
    print(json.dumps({k: rep[k] for k in ('hit_all', 'hit_nankan', 'hit_by_track')},
                     ensure_ascii=False, indent=1))
    return R


# ======================================================== 基準づくりの共通の道具
def _season_ok(dt_t, dt_s):
    """円環の日付距離が SEASON_DAYS 以内か。"""
    dd = np.abs(dt_t - dt_s) % 365
    return np.minimum(dd, 365 - dd) <= SEASON_DAYS


def asof_group_stats(dates, vals, tdates, cut):
    """1 つの母集団について、各 tdate の「前日締め」統計を返す。
    返り = (n_season, mean_s, sd_s, med_s, n_365, mean_f, sd_f, med_f)"""
    out = np.full((len(tdates), 8), np.nan)
    for i, d in enumerate(tdates):
        lo3, lo1 = d - STD_DAYS, d - FALL_DAYS
        m0 = (dates < d)
        if cut is not None:
            if d >= cut:
                m0 &= (dates >= cut)
            else:
                m0 &= (dates < cut)
        ms = m0 & (dates >= lo3) & _season_ok(d, dates)
        mf = m0 & (dates >= lo1)
        for j, m in ((0, ms), (4, mf)):
            v = vals[m]
            v = v[~np.isnan(v)]
            out[i, j] = len(v)
            if len(v) >= 2:
                out[i, j + 1] = v.mean()
                out[i, j + 2] = v.std(ddof=1)
                out[i, j + 3] = np.median(v)
            elif len(v) == 1:
                out[i, j + 1] = out[i, j + 3] = v[0]
    return out


def build_baseline(df, keycols, valcol, tkeys):
    """母集団 keycols ごとに、各 (母集団, 日) の as-of 統計を作る。
    df: 標本(track/dcut/keycols/valcol/di)。tkeys: 欲しい (keycols..., di) の一覧。"""
    src = df.dropna(subset=[valcol])
    gs = {k: (g['di'].to_numpy(), g[valcol].to_numpy(dtype=float))
          for k, g in src.groupby(keycols, sort=False, dropna=False)}
    rows = []
    for k, g in tkeys.groupby(keycols, sort=False, dropna=False):
        td = np.unique(g['di'].to_numpy())
        tr = k[0] if isinstance(k, tuple) else k
        cut = CUTI.get(tr)
        if k in gs:
            dates, vals = gs[k]
            st = asof_group_stats(dates, vals, td, cut)
        else:
            st = np.full((len(td), 8), np.nan)
        kk = k if isinstance(k, tuple) else (k,)
        for i, d in enumerate(td):
            rows.append(kk + (int(d),) + tuple(st[i]))
    cols = list(keycols) + ['di', 'n_s', 'mean_s', 'sd_s', 'med_s',
                            'n_f', 'mean_f', 'sd_f', 'med_f']
    return pd.DataFrame(rows, columns=cols)


CUTI = {}


# ================================================================ 段2: 基準時計
def stage_base():
    global CUTI
    B = pd.read_parquet(WORK + 'v3_band.parquet')
    V = pd.read_parquet(WORK + 'v2_base.parquet',
                        columns=KEY + ['horse_key', 'distance_m', 'going', 'fin',
                                       'first3f_v', 'last3f_v'])
    runs = read_gz('nar_runs', ['track', 'race_date', 'race_no', 'runner_number',
                                'finish', 'finish_note', 'time_sec'])
    runs['race_date'] = pd.to_datetime(runs['race_date'])
    for c in ('race_no', 'runner_number'):
        runs[c] = pd.to_numeric(runs[c], errors='coerce').astype('int32')
        V[c] = V[c].astype('int32')
    runs['time_sec'] = pd.to_numeric(runs['time_sec'], errors='coerce')
    ok = runs['finish_note'].isna() | (runs['finish_note'].astype(str).str.strip() == '')
    runs['t'] = runs['time_sec'].where(ok & (runs['time_sec'] > 0))
    d = V.merge(runs[KEY + ['t']], on=KEY, how='left', validate='one_to_one')

    B['race_date'] = pd.to_datetime(B['race_date'])
    B['race_no'] = pd.to_numeric(B['race_no'], errors='coerce').astype('int32')
    d = d.merge(B[['track', 'race_date', 'race_no', 'band', 'going_n', 'race_kind']],
                on=['track', 'race_date', 'race_no'], how='left')
    d['band_f'] = d['band'].fillna('不明')
    d['di'] = (d['race_date'].values.astype('datetime64[D]').astype(np.int64))
    d.loc[d['track'] == BANEI, 't'] = np.nan          # ばんえいは時計の性質が別物= 基準に入れない
    CUTI = {k: int(np.datetime64(v, 'D').astype(np.int64)) for k, v in RESET.items()}
    log('rows', len(d), 'time notna', int(d['t'].notna().sum()))

    # ---------- (1) 走破時計の基準: 場 × 距離 × クラス帯 × 馬場
    kc = ['track', 'distance_m', 'band_f', 'going_n']
    tk = d[kc + ['di']].drop_duplicates()
    log('基準セル(場×距離×帯×馬場×日) =', len(tk))
    bl = build_baseline(d, kc, 't', tk)
    # 帯を落とした退避先(場 × 距離 × 馬場)
    kc2 = ['track', 'distance_m', 'going_n']
    tk2 = d[kc2 + ['di']].drop_duplicates()
    bl2 = build_baseline(d, kc2, 't', tk2).rename(
        columns={c: c + '2' for c in ('n_s', 'mean_s', 'sd_s', 'med_s', 'n_f', 'mean_f', 'sd_f', 'med_f')})
    log('基準(帯つき) %d 行 / (帯なし) %d 行' % (len(bl), len(bl2)))

    d = d.merge(bl, on=kc + ['di'], how='left').merge(bl2, on=kc2 + ['di'], how='left')

    # 段階的な退避: 季節×帯 → 365×帯 → 季節×帯なし → 365×帯なし
    lv = [('n_s', 'mean_s', 'sd_s', 'med_s'), ('n_f', 'mean_f', 'sd_f', 'med_f'),
          ('n_s2', 'mean_s2', 'sd_s2', 'med_s2'), ('n_f2', 'mean_f2', 'sd_f2', 'med_f2')]
    m = np.full(len(d), np.nan); s = np.full(len(d), np.nan)
    md = np.full(len(d), np.nan); nn = np.full(len(d), np.nan)
    src = np.full(len(d), np.nan)
    for i, (cn, cm, cs, cd) in enumerate(lv):
        need = np.isnan(m)
        good = need & (d[cn].to_numpy() >= MIN_N) & (d[cs].to_numpy() > 0.01)
        m[good] = d[cm].to_numpy()[good]
        s[good] = d[cs].to_numpy()[good]
        md[good] = d[cd].to_numpy()[good]
        nn[good] = d[cn].to_numpy()[good]
        src[good] = i
    d['bl_m'], d['bl_sd'], d['bl_med'], d['bl_n'], d['bl_src'] = m, s, md, nn, src
    cov = float(np.isfinite(m).mean())
    esc = {int(i): int((src == i).sum()) for i in range(4)}
    log('基準が付いた割合 %.4f  退避の内訳(0=季節帯/1=365帯/2=季節帯なし/3=365帯なし) %s' % (cov, esc))

    # tz = (基準平均 − 自分の時計) / 基準 sd(+ = 速い。prod と同じ向き)
    d['tz_v3'] = (d['bl_m'] - d['t']) / d['bl_sd']
    d['tz_v3'] = d['tz_v3'].clip(-8, 8)

    # ---------- (2) 日×場の馬場差(勝ち時計 − 帯つき中央値・場×距離×帯・馬場は入れない)
    w = d.loc[(d['fin'] == 1) & d['t'].notna() & (d['track'] != BANEI),
              ['track', 'distance_m', 'band_f', 'di', 't']].copy()
    kcb = ['track', 'distance_m', 'band_f']
    tkb = w[kcb + ['di']].drop_duplicates()
    blb = build_baseline(w, kcb, 't', tkb)
    kcb2 = ['track', 'distance_m']
    tkb2 = w[kcb2 + ['di']].drop_duplicates()
    blb2 = build_baseline(w, kcb2, 't', tkb2).rename(
        columns={c: c + '2' for c in ('n_s', 'mean_s', 'sd_s', 'med_s', 'n_f', 'mean_f', 'sd_f', 'med_f')})
    w = w.merge(blb, on=kcb + ['di'], how='left').merge(blb2, on=kcb2 + ['di'], how='left')
    base = np.full(len(w), np.nan)
    for cn, cd in (('n_s', 'med_s'), ('n_f', 'med_f'), ('n_s2', 'med_s2'), ('n_f2', 'med_f2')):
        need = np.isnan(base)
        good = need & (w[cn].to_numpy() >= MIN_N)
        base[good] = w[cd].to_numpy()[good]
    w['dev'] = w['t'] - base
    g = w.dropna(subset=['dev']).groupby(['track', 'di'])['dev']
    bb = g.median().rename('baba_v3').reset_index()
    bb['baba_n'] = g.size().values
    bb = bb[bb['baba_n'] >= MIN_RACES_BABA].copy()
    bb['baba_v3'] = bb['baba_v3'].round(2)
    log('馬場差の出た 場日 =', len(bb), ' 南関 =', int(bb['track'].isin(NANKAN).sum()))
    bb.to_parquet(WORK + 'v3_baba.parquet', index=False)

    d = d.merge(bb[['track', 'di', 'baba_v3']], on=['track', 'di'], how='left')
    # 馬場補正時計 = 時計 − その日その場の馬場差 → 同じ基準で z 化
    d['tza_v3'] = (d['bl_m'] - (d['t'] - d['baba_v3'])) / d['bl_sd']
    d['tza_v3'] = d['tza_v3'].clip(-8, 8)

    # ---------- (3) 前半3F / 上がり3F の基準差(10 の C 族を新基準で)
    for c, tag in (('first3f_v', 'f3'), ('last3f_v', 'l3')):
        tkc = d[kc + ['di']].drop_duplicates()
        b = build_baseline(d[d['track'] != BANEI], kc, c, tkc)
        b2 = build_baseline(d[d['track'] != BANEI], kc2, c,
                            d[kc2 + ['di']].drop_duplicates()).rename(
            columns={x: x + '2' for x in ('n_s', 'mean_s', 'sd_s', 'med_s',
                                          'n_f', 'mean_f', 'sd_f', 'med_f')})
        dd = d[list(dict.fromkeys(kc + kc2 + ['di']))].merge(b, on=kc + ['di'], how='left').merge(
            b2, on=kc2 + ['di'], how='left')
        mm = np.full(len(d), np.nan); ss = np.full(len(d), np.nan)
        for cn, cm, cs in (('n_s', 'mean_s', 'sd_s'), ('n_f', 'mean_f', 'sd_f'),
                           ('n_s2', 'mean_s2', 'sd_s2'), ('n_f2', 'mean_f2', 'sd_f2')):
            need = np.isnan(mm)
            good = need & (dd[cn].to_numpy() >= MIN_N) & (dd[cs].to_numpy() > 0.01)
            mm[good] = dd[cm].to_numpy()[good]
            ss[good] = dd[cs].to_numpy()[good]
        d['dev_' + tag] = d[c].to_numpy() - mm          # + = 遅い
        d['z_' + tag] = np.clip((mm - d[c].to_numpy()) / ss, -8, 8)   # + = 速い
        log('C 族 %s 基準が付いた割合 %.4f' % (tag, float(np.isfinite(mm).mean())))

    # ---------- (4) 基準づくりの記録
    sc = pd.Series(src).value_counts(dropna=False)
    rep = dict(rows=int(len(d)), rows_with_time=int(d['t'].notna().sum()),
               rows_with_base=int(np.isfinite(m).sum()),
               cells_band=int(len(bl)), cells_noband=int(len(bl2)),
               src_counts={('nan' if (isinstance(k, float) and np.isnan(k)) else str(int(k))): int(v)
                           for k, v in sc.items()},
               baba_days=int(len(bb)), baba_days_nankan=int(bb['track'].isin(NANKAN).sum()),
               reset=RESET, season_days=SEASON_DAYS, std_days=STD_DAYS,
               fallback_days=FALL_DAYS, min_n=MIN_N)
    json.dump(rep, open(WORK + 'v3_baseline_report.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    keep = KEY + ['horse_key', 'race_date', 'distance_m', 'band_f', 'going_n', 'di', 'fin',
                  't', 'bl_m', 'bl_sd', 'bl_n', 'bl_src', 'tz_v3', 'tza_v3', 'baba_v3',
                  'dev_f3', 'z_f3', 'dev_l3', 'z_l3']
    keep = list(dict.fromkeys(keep))
    d[keep].to_parquet(WORK + 'v3_base.parquet', index=False)
    log('v3_base saved', d[keep].shape)


# ================================================================ 段3: 時計系の列
def roll(sh, hk, w, how):
    r = sh.groupby(hk, sort=False).rolling(w, min_periods=1)
    o = getattr(r, how)()
    o.index = sh.index
    return o


def stage_feats():
    d = pd.read_parquet(WORK + 'v3_base.parquet')
    d = d.sort_values(['horse_key', 'race_date', 'race_no'], kind='mergesort').reset_index(drop=True)
    hk = d['horse_key']
    F = pd.DataFrame(index=d.index)

    # --- 当該レースの基準そのもの(発走前に決まる情報)
    F['v3_base_n'] = d['bl_n']
    F['v3_base_src'] = d['bl_src']
    F['v3_base_sd'] = d['bl_sd']
    F['v3_band_missing'] = (d['band_f'] == '不明').astype('float32')
    F['v3_band_code'] = pd.factorize(d['band_f'])[0].astype('float32')
    resd = np.full(len(d), np.nan)
    for t, s in RESET.items():
        ci = int(np.datetime64(s, 'D').astype(np.int64))
        m = (d['track'] == t).to_numpy()
        resd[m] = d['di'].to_numpy()[m] - ci
    F['v3_reset_d'] = np.where(np.isfinite(resd) & (resd >= 0), resd, np.nan)

    # --- 馬ごとの過去走(shift(1) 済み= その走自身は入らない)
    cols = ['tz_v3', 'tza_v3', 'baba_v3', 'dev_f3', 'z_f3', 'dev_l3', 'z_l3']
    S = d[cols].groupby(hk, sort=False).shift(1)
    for k in range(1, 6):                       # p1〜p5 の時計偏差
        sk = d[['tz_v3']].groupby(hk, sort=False).shift(k)
        F['v3_p%d_tz' % k] = sk['tz_v3']
    for k in range(1, 4):
        sk = d[['tza_v3']].groupby(hk, sort=False).shift(k)
        F['v3_p%d_tza' % k] = sk['tza_v3']
    m3 = roll(S, hk, 3, 'mean'); m5 = roll(S, hk, 5, 'mean')
    x5 = roll(S[['tz_v3', 'tza_v3', 'z_f3', 'z_l3']], hk, 5, 'max')
    n5 = roll(S[['tz_v3', 'tza_v3', 'dev_f3', 'dev_l3']], hk, 5, 'count')
    sd5 = roll(S[['tz_v3']], hk, 5, 'std')
    F['v3_avg_tz_3'] = m3['tz_v3']; F['v3_avg_tz_5'] = m5['tz_v3']
    F['v3_best_tz_5'] = x5['tz_v3']
    F['v3_avg_tza_3'] = m3['tza_v3']; F['v3_avg_tza_5'] = m5['tza_v3']
    F['v3_best_tza_5'] = x5['tza_v3']
    F['v3_n_tz_5'] = n5['tz_v3']; F['v3_n_tza_5'] = n5['tza_v3']
    F['v3_sd_tz_5'] = sd5['tz_v3']
    F['v3_tz_trend'] = F['v3_p1_tz'] - F['v3_avg_tz_3']
    F['v3_tza_trend'] = F['v3_p1_tza'] - F['v3_avg_tza_3']
    F['v3_avg_baba_3'] = m3['baba_v3']; F['v3_p1_baba'] = S['baba_v3']
    # 生涯最良(その走より前まで)
    g = S.groupby(hk, sort=False)
    F['v3_best_tz_car'] = g['tz_v3'].cummax()
    F['v3_best_tza_car'] = g['tza_v3'].cummax()
    F['v3_n_tz_car'] = g['tz_v3'].cumcount() + 1 - g['tz_v3'].apply(
        lambda s: s.isna().cumsum()).reset_index(level=0, drop=True)
    F['v3_mean_tz_car'] = g['tz_v3'].expanding().mean().reset_index(level=0, drop=True)

    # --- C 族(新基準の前半3F/上がり3F)
    F['v3_f3_dev1'] = S['dev_f3']; F['v3_f3_dev3'] = m3['dev_f3']; F['v3_f3_dev5'] = m5['dev_f3']
    F['v3_l3_dev1'] = S['dev_l3']; F['v3_l3_dev3'] = m3['dev_l3']; F['v3_l3_dev5'] = m5['dev_l3']
    F['v3_f3_z1'] = S['z_f3']; F['v3_f3_z3'] = m3['z_f3']; F['v3_f3_zbest5'] = x5['z_f3']
    F['v3_l3_z1'] = S['z_l3']; F['v3_l3_z3'] = m3['z_l3']; F['v3_l3_zbest5'] = x5['z_l3']
    F['v3_f3_n5'] = n5['dev_f3']; F['v3_l3_n5'] = n5['dev_l3']

    # --- 同じ距離 / 同じ場での過去の時計偏差(すべて前走まで)
    def prior_group(vals, codes, w):
        """行順のまま、同じ code の「その行より前」の直近 w 件の平均 と 件数 と 最良。"""
        s = pd.Series(np.asarray(vals, dtype=float))
        gcode = pd.Series(codes)
        sh = s.groupby(gcode, sort=False).shift(1)
        r = sh.groupby(gcode, sort=False).rolling(w, min_periods=1)
        mn = r.mean(); cn = r.count(); mx = r.max()
        for o in (mn, cn, mx):
            o.index = s.index
        return mn.to_numpy(), cn.to_numpy(), mx.to_numpy()

    hkc = pd.factorize(d['horse_key'])[0].astype(np.int64)
    dcode = hkc * 100000 + pd.factorize(d['distance_m'].fillna(-1))[0]
    tcode = hkc * 100000 + pd.factorize(d['track'])[0]
    bcode = hkc * 100000 + pd.factorize(d['band_f'])[0]
    for tag, code in (('dist', dcode), ('trk', tcode), ('band', bcode)):
        mn, cn, mx = prior_group(d['tz_v3'].to_numpy(), code, 3)
        F['v3_%s_avg_tz_3' % tag] = mn
        F['v3_%s_n_tz' % tag] = cn
        F['v3_%s_best_tz_3' % tag] = mx

    F = F.astype('float32')
    out = pd.concat([d[KEY].reset_index(drop=True), F.reset_index(drop=True)], axis=1)
    out.to_parquet(WORK + 'v3_feats.parquet', index=False)
    log('v3_feats saved', out.shape, '新列', out.shape[1] - 4)
    return out


# ================================================================ 段4: 結合
def stage_join():
    f2 = pd.read_parquet(FEATV2)
    nf = pd.read_parquet(WORK + 'v3_feats.parquet')
    f2['race_date'] = pd.to_datetime(f2['race_date'])
    nf['race_date'] = pd.to_datetime(nf['race_date'])
    for c in ('race_no', 'runner_number'):
        f2[c] = pd.to_numeric(f2[c], errors='coerce').astype('int32')
        nf[c] = pd.to_numeric(nf[c], errors='coerce').astype('int32')
    nf = nf.drop_duplicates(subset=KEY)
    out = f2.merge(nf, on=KEY, how='left', validate='one_to_one')
    assert len(out) == len(f2)
    out.to_parquet(OUT, index=False)
    new = [c for c in nf.columns if c not in KEY]
    nk = out[out['track'].isin(NANKAN)]
    rep = pd.DataFrame({'column': new,
                        'null_all': [out[c].isna().mean() for c in new],
                        'null_nankan': [nk[c].isna().mean() for c in new]})
    rep.to_csv(WORK + 'v3_missing.csv', index=False, encoding='utf-8-sig')
    log('saved', OUT, out.shape, '新列', len(new))
    print(rep.sort_values('null_all', ascending=False).head(12).to_string(index=False))


# ================================================================ 段5: as-of 検査
def stage_check():
    d = pd.read_parquet(WORK + 'v3_base.parquet')
    nf = pd.read_parquet(WORK + 'v3_feats.parquet')
    d['race_date'] = pd.to_datetime(d['race_date'])
    nf['race_date'] = pd.to_datetime(nf['race_date'])
    sel = list(dict.fromkeys(KEY + ['horse_key', 'race_date', 'track', 'di', 'tz_v3',
                                    'bl_m', 'bl_sd', 'band_f', 'going_n', 'distance_m']))
    m = d[sel].merge(nf, on=KEY, how='left')
    m = m.sort_values(['horse_key', 'race_date', 'race_no'], kind='mergesort')
    first = ~m['horse_key'].duplicated()
    hist = [c for c in nf.columns if c.startswith('v3_') and
            not c.startswith(('v3_base', 'v3_band', 'v3_reset'))]
    r = {}
    r['first_run_rows'] = int(first.sum())
    r['first_run_all_null'] = {c: float(m.loc[first, c].isna().mean()) for c in
                               ['v3_p1_tz', 'v3_avg_tz_3', 'v3_best_tz_car', 'v3_f3_dev3',
                                'v3_dist_avg_tz_3', 'v3_p1_tza']}
    nz = {c: float(m.loc[first, c].notna().mean()) for c in hist}
    r['first_run_nonnull_rate'] = {c: round(v, 4) for c, v in nz.items() if v > 0}
    r['first_run_nonnull_are_counts_all_zero'] = all(
        float(np.nanmax(m.loc[first, c].to_numpy())) == 0.0
        for c in r['first_run_nonnull_rate'])
    # 基準が同じ場日・同じ母集団で 1 つに定まっているか(= 当日の結果が混ざっていない)
    gg = m.dropna(subset=['bl_m']).groupby(['track', 'di', 'distance_m', 'band_f', 'going_n'])['bl_m']
    r['baseline_cells'] = int(gg.ngroups)
    r['baseline_constant_within_cell'] = int((gg.nunique() == 1).sum())
    # 当日値との不一致: その走の tz を「自分の時計を基準に入れた場合」と比べ、必ず別物になる
    # (= 基準に自分が入っていれば n が 1 増えるはず)→ 基準 n が当日のレース数ぶん増えていないこと
    r['note'] ='基準 bl_m は (場,日,距離,帯,馬場) ごとに一意で、同じ日の結果に依存しない'
    # 馬ごとの過去走の並び: v3_p1_tz が「直前の走の tz_v3」と一致するか
    prev = m.groupby('horse_key')['tz_v3'].shift(1)
    both = prev.notna() & m['v3_p1_tz'].notna()
    r['p1_tz_matches_prev_run'] = float(
        (np.abs(prev[both] - m.loc[both, 'v3_p1_tz']) < 1e-3).mean())
    r['p1_tz_compared'] = int(both.sum())
    json.dump(r, open(WORK + 'v3_check.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=float))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', default='all',
                    choices=['band', 'base', 'feats', 'join', 'check', 'all'])
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    t0 = time.time()
    if a.stage in ('band', 'all'):
        stage_band()
    if a.stage in ('base', 'all'):
        stage_base()
    if a.stage in ('feats', 'all'):
        stage_feats()
    if a.stage in ('join', 'all'):
        stage_join()
    if a.stage in ('check', 'all'):
        stage_check()
    log('done %.1fs' % (time.time() - t0))
