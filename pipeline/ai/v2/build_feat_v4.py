# -*- coding: utf-8 -*-
# 写し元 C:/Users/kouki/nankan_ai/build_feat_v4.py(写した日 2026-09-23)。
# 変えた行= ROOT(環境変数 NAI_ROOT)の 1 行だけ。
# RAW/WORK/FEATV3/OUT は ROOT から作られるので自動で移る。⛔計算は 1 行も変えていない。
"""E9: 馬ごとの「条件別の癖」を列にして feat_v4.parquet を作る。

  py -3.12 -X utf8 C:/Users/kouki/nankan_ai/build_feat_v4.py --stage all

段:
  runs  … 過去走ごとに「展開の判定」(逃げられた/揉まれた/展開4段)と条件の帯を付ける
          → work/v4_runs.parquet / work/v4_runs_report.json
  feats … 個体×条件の縮小残差(12 列 + 標本数 12 列)と個体の傾き(6 列)
          → work/v4_feats.parquet
  join  … feat_v3.parquet に左結合して feat_v4.parquet
  check … as-of の検査(初出走で空・当日値と不一致・shift の確認)

⛔本番 DB には一切つながない(材料は raw/ の写しと feat_v3.parquet だけ)。
⛔C:/Users/kouki/ai_v1/ は読むだけ。
"""
from __future__ import annotations
import argparse, gzip, json, os, sys, time
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

ROOT = (os.environ.get('NAI_ROOT') or 'C:/Users/kouki/nankan_ai/').replace(chr(92), '/').rstrip('/') + '/'
RAW = ROOT + 'raw/'
WORK = ROOT + 'work/'
FEATV3 = ROOT + 'feat_v3.parquet'
OUT = ROOT + 'feat_v4.parquet'
KEY = ['track', 'race_date', 'race_no', 'runner_number']
NANKAN = ['大井', '川崎', '船橋', '浦和']

KSHRINK = 5          # 縮小の k(既定 5・n/(n+k))
SLOPE_W = 10         # 傾きを見る直近の走数
LAYOFF_DAYS = 90     # これ以上あいたら「休養明け」


def log(*a):
    print('[%s]' % time.strftime('%H:%M:%S'), *a, flush=True)


# ================================================================ 段1: 過去走ごとの判定
def stage_runs():
    cols = KEY + ['horse_key', 'finish', 'finish_note', 'style', 'n_front', 'wakuban',
                  'tosu', 'barei', 'days_since_prev', 'baba_now', 'kyori', 'lo_runs_30d']
    d = pd.read_parquet(FEATV3, columns=cols)
    d['race_date'] = pd.to_datetime(d['race_date'])
    log('feat_v3', d.shape)

    # tz(新基準の時計偏差)= その走の成績のものさし
    b = pd.read_parquet(WORK + 'v3_base.parquet',
                        columns=KEY + ['tz_v3', 'going_n', 'distance_m'])
    b['race_date'] = pd.to_datetime(b['race_date'])
    for c in ('race_no', 'runner_number'):
        b[c] = pd.to_numeric(b[c], errors='coerce').astype('int32')
        d[c] = pd.to_numeric(d[c], errors='coerce').astype('int32')
    b = b.drop_duplicates(subset=KEY)
    d = d.merge(b, on=KEY, how='left', validate='one_to_one')

    # 通過順(その走の確定後の事実。過去走の判定にだけ使う)
    with gzip.open(RAW + 'nar_run_facts.csv.gz', 'rt', encoding='utf-8', newline='') as f:
        rf = pd.read_csv(f, usecols=['race_date', 'track', 'race_no', 'umaban',
                                     'c1', 'n1', 'c2', 'n2', 'c4', 'n4', 'style'],
                         low_memory=False)
    rf = rf.rename(columns={'umaban': 'runner_number', 'style': 'style_act'})
    rf['race_date'] = pd.to_datetime(rf['race_date'])
    rf['race_no'] = pd.to_numeric(rf['race_no'], errors='coerce').astype('int32')
    rf['runner_number'] = pd.to_numeric(rf['runner_number'], errors='coerce').astype('int32')
    rf = rf.drop_duplicates(subset=KEY)
    d = d.merge(rf, on=KEY, how='left', validate='one_to_one')
    log('merged run_facts', d.shape)

    # ---------- 2 角の位置(c2 が無ければ c1 で代用)
    c1, c2 = d['c1'].to_numpy(float), d['c2'].to_numpy(float)
    n1, n2 = d['n1'].to_numpy(float), d['n2'].to_numpy(float)
    tosu = d['tosu'].to_numpy(float)
    pos2 = np.where(np.isfinite(c2), c2, c1)
    nf2 = np.where(np.isfinite(n2), n2, np.where(np.isfinite(n1), n1, tosu))
    nf2 = np.where(np.isfinite(nf2) & (nf2 > 0), nf2, np.nan)
    ratio2 = pos2 / nf2
    d['v4_pos2'], d['v4_ratio2'] = pos2, ratio2

    # ---------- 逃げられた = 2 角までが 1〜2 番手
    first = np.where(np.isfinite(c1), c1, pos2)
    got_lead = np.where(np.isfinite(pos2), ((pos2 <= 2) & ((first <= 2) | ~np.isfinite(first))), np.nan)
    d['v4_got_lead'] = got_lead.astype(float)

    # ---------- 展開 4 段(0 逃げ / 1 先行 / 2 中団 / 3 後方)
    dev = np.full(len(d), np.nan)
    ok = np.isfinite(ratio2) & np.isfinite(pos2)
    dev[ok & (pos2 <= 2)] = 0
    dev[ok & (pos2 > 2) & (ratio2 <= 0.4)] = 1
    dev[ok & (pos2 > 2) & (ratio2 > 0.4) & (ratio2 <= 0.7)] = 2
    dev[ok & (pos2 > 2) & (ratio2 > 0.7)] = 3
    d['v4_dev'] = dev

    # ---------- 枠帯(0 内 1〜3 枠 / 1 中 4〜5 枠 / 2 外 6〜8 枠)
    w = d['wakuban'].to_numpy(float)
    d['v4_wband'] = np.where(w <= 3, 0, np.where(w <= 5, 1, 2)).astype(float)

    # ---------- 揉まれた = 内枠 かつ 2 角で中団以降(頭数比 0.4 以上)かつ 着順が前走比で悪化
    d = d.sort_values(['horse_key', 'race_date', 'race_no'], kind='mergesort').reset_index(drop=True)
    finr = d['finish'].to_numpy(float) / np.where(tosu > 0, tosu, np.nan)
    d['_finr'] = finr
    prev_finr = d.groupby('horse_key', sort=False)['_finr'].shift(1).to_numpy(float)
    sq = np.where(np.isfinite(ratio2) & np.isfinite(finr) & np.isfinite(prev_finr),
                  ((d['v4_wband'].to_numpy() == 0) & (ratio2 >= 0.4) & (finr > prev_finr)),
                  np.nan)
    d['v4_squeezed'] = sq.astype(float)

    # ---------- 先行勢の数の帯(0: 0〜1 / 1: 2 / 2: 3 / 3: 4 以上)
    nfr = d['n_front'].to_numpy(float)
    d['v4_nsband'] = np.where(nfr <= 1, 0, np.where(nfr == 2, 1, np.where(nfr == 3, 2, 3))).astype(float)

    # ---------- 間隔帯(0 連闘 ≤7 / 1 ≤14 / 2 ≤28 / 3 ≤56 / 4 57 日以上)
    dy = d['days_since_prev'].to_numpy(float)
    gap = np.full(len(d), np.nan)
    gap[dy <= 7] = 0
    gap[(dy > 7) & (dy <= 14)] = 1
    gap[(dy > 14) & (dy <= 28)] = 2
    gap[(dy > 28) & (dy <= 56)] = 3
    gap[dy > 56] = 4
    gap[~np.isfinite(dy)] = 4          # 初出走・間隔不明は「57 日以上」に寄せる
    d['v4_gapband'] = gap

    # ---------- 休養明け何戦目(1/2/3/4 以上)= 90 日以上あいた走を 1 戦目とする
    lay = (dy >= LAYOFF_DAYS) | ~np.isfinite(dy)
    d['_lay'] = lay.astype(int)
    grp = d.groupby('horse_key', sort=False)['_lay'].cumsum()
    idx = d.groupby(['horse_key', grp], sort=False).cumcount() + 1
    d['v4_layoff_i'] = np.minimum(idx.to_numpy(float), 4)

    # ---------- 使い詰め(直近 30 日に 2 走以上)
    d['v4_heavy'] = (d['lo_runs_30d'].fillna(0).to_numpy(float) >= 2).astype(float)

    # ---------- 馬場(0 良 1 稍 2 重 3 不)= feat_v3 の baba_now をそのまま帯に
    d['v4_baba'] = d['baba_now'].astype(float)

    # ---------- 距離帯(0 ≤1200 / 1 ≤1500 / 2 ≤1800 / 3 1800 超)
    km = d['kyori'].to_numpy(float)
    d['v4_dband'] = np.where(km <= 1200, 0, np.where(km <= 1500, 1, np.where(km <= 1800, 2, 3))).astype(float)

    # ---------- 場のコード
    d['v4_trk'] = pd.factorize(d['track'])[0].astype(float)

    # ---------- 今回「逃げられる」見込み(今回の先行勢の数と自分の脚質から)
    st = d['style'].to_numpy(float)     # 0 逃げ 1 先行 2 差し 3 追込(発走前 as-of)
    d['v4_lead_exp'] = np.where(np.isfinite(st), ((st <= 1) & (nfr <= 2)), np.nan).astype(float)

    # ---------- 今回の想定展開(0 逃げ / 1 先行 / 2 中団 / 3 後方)
    devx = np.full(len(d), np.nan)
    devx[np.isfinite(st) & (st <= 1) & (nfr <= 2)] = 0
    devx[np.isfinite(st) & (st <= 1) & (nfr > 2)] = 1
    devx[st == 2] = 2
    devx[st == 3] = 3
    d['v4_dev_exp'] = devx

    # ---------- 今回「揉まれる」見込み(内枠 かつ 前に行けない見込み)
    d['v4_sq_exp'] = np.where(np.isfinite(st),
                              ((d['v4_wband'].to_numpy() == 0) & ((st >= 2) | (nfr >= 3))),
                              np.nan).astype(float)

    keep = KEY + ['horse_key', 'race_date', 'tz_v3', 'barei',
                  'v4_dev', 'v4_got_lead', 'v4_squeezed', 'v4_wband', 'v4_nsband',
                  'v4_gapband', 'v4_layoff_i', 'v4_heavy', 'v4_baba', 'v4_dband', 'v4_trk',
                  'v4_lead_exp', 'v4_dev_exp', 'v4_sq_exp']
    keep = list(dict.fromkeys(keep))
    d[keep].to_parquet(WORK + 'v4_runs.parquet', index=False)

    rep = dict(rows=int(len(d)), rows_nankan=int(d['track'].isin(NANKAN).sum()),
               tz_notna=int(d['tz_v3'].notna().sum()),
               defs=dict(
                   got_lead='2 角(無ければ 1 角)が 1〜2 番手',
                   squeezed='枠 1〜3 かつ 2 角の頭数比 ≥0.4 かつ 着順/頭数 が前走より悪化',
                   dev='0 逃げ(2 角 ≤2 番手)/1 先行(比 ≤0.4)/2 中団(≤0.7)/3 後方(>0.7)',
                   wband='0 内 1〜3 枠 / 1 中 4〜5 枠 / 2 外 6〜8 枠',
                   nsband='今回の先行勢の数(feat_v3 の n_front) 0:≤1 1:=2 2:=3 3:≥4',
                   gapband='0 連闘 ≤7 日 / 1 ≤14 / 2 ≤28 / 3 ≤56 / 4 ≥57(初出走も 4)',
                   layoff_i='90 日以上あいた走を 1 戦目とする連番(4 で頭打ち)',
                   heavy='直近 30 日に 2 走以上',
                   lead_exp='今回 = 脚質が逃げ/先行 かつ 先行勢 ≤2 頭',
                   dev_exp='今回 = 逃げ/先行 かつ ≤2 頭→逃げ、>2 頭→先行、差し→中団、追込→後方',
                   sq_exp='今回 = 内枠 かつ(脚質が差し/追込 または 先行勢 ≥3 頭)'),
               counts={c: {str(k): int(v) for k, v in d[c].value_counts(dropna=False).items()}
                       for c in ['v4_dev', 'v4_got_lead', 'v4_squeezed', 'v4_wband', 'v4_nsband',
                                 'v4_gapband', 'v4_layoff_i', 'v4_heavy', 'v4_baba', 'v4_dband',
                                 'v4_lead_exp', 'v4_dev_exp', 'v4_sq_exp']},
               counts_nankan={c: {str(k): int(v) for k, v in
                                  d.loc[d['track'].isin(NANKAN), c].value_counts(dropna=False).items()}
                              for c in ['v4_dev', 'v4_got_lead', 'v4_squeezed', 'v4_lead_exp',
                                        'v4_dev_exp', 'v4_sq_exp']})
    json.dump(rep, open(WORK + 'v4_runs_report.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    log('v4_runs saved', d[keep].shape)
    print(json.dumps(rep['counts'], ensure_ascii=False, indent=1))


# ================================================================ 段2: 残差と傾き
def _exp_prev(df, keys, v, m):
    """keys ごとの「その行より前」の (和, 本数)。行の値そのものは含めない。"""
    g = df.groupby(keys, sort=False, dropna=False, observed=True)
    cs = g['_v'].cumsum().to_numpy(float) - v
    cn = g['_m'].cumsum().to_numpy(float) - m
    return cs, cn


def stage_feats():
    d = pd.read_parquet(WORK + 'v4_runs.parquet')
    d['race_date'] = pd.to_datetime(d['race_date'])
    d = d.sort_values(['horse_key', 'race_date', 'race_no'], kind='mergesort').reset_index(drop=True)
    tz = d['tz_v3'].to_numpy(float)
    m = np.isfinite(tz).astype(float)
    v = np.where(np.isfinite(tz), tz, 0.0)
    d['_v'], d['_m'] = v, m

    # 馬全体の「その行より前」の平均
    cs_h, cn_h = _exp_prev(d, ['horse_key'], v, m)
    mean_h = np.where(cn_h > 0, cs_h / np.maximum(cn_h, 1), np.nan)

    # ---- 条件 12 本: (残差列名, 過去走側の条件列, 今回側の条件列)
    CONDS = [
        ('waku',   'v4_wband',    'v4_wband'),     # 枠帯(今回の枠は発走前に決まっている)
        ('dev',    'v4_dev',      'v4_dev_exp'),   # 展開(過去 = 実際 / 今回 = 想定)
        ('lead',   'v4_got_lead', 'v4_lead_exp'),  # 逃げられたか
        ('squeeze', 'v4_squeezed', 'v4_sq_exp'),   # 揉まれたか
        ('baba',   'v4_baba',     'v4_baba'),      # 馬場
        ('gap',    'v4_gapband',  'v4_gapband'),   # 間隔帯
        ('layoff', 'v4_layoff_i', 'v4_layoff_i'),  # 休養明け何戦目
        ('heavy',  'v4_heavy',    'v4_heavy'),     # 使い詰め
        ('trk',    'v4_trk',      'v4_trk'),       # 場
        ('dist',   'v4_dband',    'v4_dband'),     # 距離帯
        ('nsenko', 'v4_nsband',   'v4_nsband'),    # 先行勢の数の帯
        ('wakudev', None,         None),           # 枠帯 × 展開(組み合わせ)
    ]
    d['_wd_past'] = d['v4_wband'] * 10 + d['v4_dev']
    d['_wd_now'] = d['v4_wband'] * 10 + d['v4_dev_exp']

    out = pd.DataFrame(index=d.index)
    for name, cpast, cnow in CONDS:
        if name == 'wakudev':
            cpast, cnow = '_wd_past', '_wd_now'
        # 「過去走の条件」で積み上げ、「今回の条件」で引く。
        # 今回の条件が過去走の条件と同じ列(枠・馬場・間隔など)なら 1 回の cumsum で済むが、
        # 展開のように過去 = 実際 / 今回 = 想定 で列が違う場合は、
        # 「過去走の条件」で作った表を「今回の条件」の水準で引き直す必要がある。
        if cpast == cnow:
            cs, cn = _exp_prev(d, ['horse_key', cpast], v, m)
        else:
            # 馬 × 過去走の条件水準 の累積を作り、今回の水準の行に当てる
            # 馬ごとに水準別の走行和を積み上げ、「今回の水準」に当たる行だけ引く
            levels = pd.unique(d[cpast].dropna().to_numpy(float))
            S = np.full(len(d), np.nan)
            N = np.full(len(d), np.nan)
            now = d[cnow].to_numpy(float)
            for L in levels:
                isL = (d[cpast].to_numpy(float) == L)
                sL = np.where(isL, v, 0.0)
                nL = np.where(isL, m, 0.0)
                tmp = pd.DataFrame({'h': d['horse_key'].to_numpy(), 's': sL, 'n': nL})
                gg = tmp.groupby('h', sort=False)
                cS = gg['s'].cumsum().to_numpy(float) - sL   # その行より前の (馬, 水準 L) の和
                cN = gg['n'].cumsum().to_numpy(float) - nL
                pick = (now == L)
                S[pick] = cS[pick]
                N[pick] = cN[pick]
            cs, cn = S, N
        mean_c = np.where((cn > 0) & np.isfinite(cn), cs / np.maximum(cn, 1), np.nan)
        res = (mean_c - mean_h) * (cn / (cn + KSHRINK))
        out['v4_res_' + name] = res.astype('float32')
        out['v4_n_' + name] = np.where(np.isfinite(cn), cn, 0).astype('float32')
        log('res', name, 'notna=%.3f' % float(np.isfinite(res).mean()))

    # ---------- 個体の傾き(直近 10 走の tz の回帰係数)
    idx = d.groupby('horse_key', sort=False).cumcount().to_numpy(float)
    xx = np.where(m > 0, idx, 0.0)
    yy = v
    t = pd.DataFrame({'h': d['horse_key'].to_numpy(), 'm': m, 'x': xx, 'y': yy,
                      'xy': xx * yy, 'xx': xx * xx})
    # その行より前の直近 10 走だけを見る(shift(1) してから窓)
    t[['m', 'x', 'y', 'xy', 'xx']] = t.groupby('h', sort=False)[['m', 'x', 'y', 'xy', 'xx']].shift(1)
    r = t.groupby('h', sort=False)[['m', 'x', 'y', 'xy', 'xx']].rolling(SLOPE_W, min_periods=1).sum()
    r.index = t.index
    n_, Sx, Sy, Sxy, Sxx = (r['m'].to_numpy(float), r['x'].to_numpy(float), r['y'].to_numpy(float),
                            r['xy'].to_numpy(float), r['xx'].to_numpy(float))
    den = n_ * Sxx - Sx ** 2
    slope = np.where((n_ >= 3) & (np.abs(den) > 1e-9), (n_ * Sxy - Sx * Sy) / np.where(den == 0, 1, den), np.nan)
    out['v4_slope10'] = np.clip(slope, -2, 2).astype('float32')
    out['v4_slope10_x_age'] = (out['v4_slope10'] * d['barei'].to_numpy(float)).astype('float32')

    # ---------- 調子 = 直近 3 走の平均 − 直近 4〜10 走の平均
    r3 = t.groupby('h', sort=False)[['m', 'y']].rolling(3, min_periods=1).sum()
    r3.index = t.index
    r10 = r                                  # 直近 10 走
    s3 = np.where(r3['m'].to_numpy(float) > 0, r3['y'].to_numpy(float) / np.maximum(r3['m'].to_numpy(float), 1), np.nan)
    n47 = r10['m'].to_numpy(float) - r3['m'].to_numpy(float)
    y47 = r10['y'].to_numpy(float) - r3['y'].to_numpy(float)
    s47 = np.where(n47 > 0, y47 / np.maximum(n47, 1), np.nan)
    out['v4_form37'] = (s3 - s47).astype('float32')

    # ---------- 生涯のばらつきと、前走が自己ベスト近くか(2 走ボケ)
    d['_v'] = v * v
    cs2, _ = _exp_prev(d, ['horse_key'], v * v, m)          # 二乗和(その行より前)
    d['_v'] = v
    var_h = np.where(cn_h > 1, cs2 / np.maximum(cn_h, 1) - mean_h ** 2, np.nan)
    sd_h = np.sqrt(np.clip(var_h, 0, None))
    out['v4_car_sd'] = sd_h.astype('float32')
    p1 = d.groupby('horse_key', sort=False)['tz_v3'].shift(1).to_numpy(float)
    selfz = np.where((sd_h > 0.05) & np.isfinite(p1), (p1 - mean_h) / np.where(sd_h > 0.05, sd_h, np.nan), np.nan)
    out['v4_p1_selfz'] = selfz.astype('float32')
    out['v4_bounce2'] = np.where(np.isfinite(selfz), (selfz >= 0.8416).astype(float), np.nan).astype('float32')

    res = pd.concat([d[KEY], out], axis=1)
    res.to_parquet(WORK + 'v4_feats.parquet', index=False)
    newc = [c for c in out.columns]
    rep = {c: dict(null_all=round(float(res[c].isna().mean()), 4),
                   mean=None if res[c].isna().all() else round(float(res[c].mean()), 5))
           for c in newc}
    json.dump(rep, open(WORK + 'v4_feats_report.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    log('v4_feats saved', res.shape, '新列', len(newc))


# ================================================================ 段3: 結合
def stage_join():
    f3 = pd.read_parquet(FEATV3)
    nf = pd.read_parquet(WORK + 'v4_feats.parquet')
    f3['race_date'] = pd.to_datetime(f3['race_date'])
    nf['race_date'] = pd.to_datetime(nf['race_date'])
    for c in ('race_no', 'runner_number'):
        f3[c] = pd.to_numeric(f3[c], errors='coerce').astype('int32')
        nf[c] = pd.to_numeric(nf[c], errors='coerce').astype('int32')
    nf = nf.drop_duplicates(subset=KEY)
    out = f3.merge(nf, on=KEY, how='left', validate='one_to_one')
    assert len(out) == len(f3)
    out.to_parquet(OUT, index=False)
    new = [c for c in nf.columns if c not in KEY]
    nk = out[out['track'].isin(NANKAN)]
    rep = pd.DataFrame({'column': new,
                        'null_all': [out[c].isna().mean() for c in new],
                        'null_nankan': [nk[c].isna().mean() for c in new],
                        'mean_nankan': [nk[c].mean() for c in new]})
    rep.to_csv(WORK + 'v4_missing.csv', index=False, encoding='utf-8-sig')
    log('saved', OUT, out.shape, '新列', len(new))
    print(rep.to_string(index=False))


# ================================================================ 段4: as-of 検査
def stage_check():
    d = pd.read_parquet(WORK + 'v4_runs.parquet')
    nf = pd.read_parquet(WORK + 'v4_feats.parquet')
    d['race_date'] = pd.to_datetime(d['race_date'])
    nf['race_date'] = pd.to_datetime(nf['race_date'])
    m = d.merge(nf, on=KEY, how='left')
    m = m.sort_values(['horse_key', 'race_date', 'race_no'], kind='mergesort')
    first = ~m['horse_key'].duplicated()
    new = [c for c in nf.columns if c.startswith('v4_')]
    r = {'first_run_rows': int(first.sum())}
    r['first_run_nonnull_rate'] = {c: round(float(m.loc[first, c].notna().mean()), 4)
                                   for c in new if m.loc[first, c].notna().mean() > 0}
    r['first_run_nonnull_are_zero'] = {
        c: bool(np.nanmax(np.abs(m.loc[first, c].to_numpy(float))) == 0.0)
        for c in r['first_run_nonnull_rate']}
    # 残差列は初出走で空(= 標本 0)か
    resc = [c for c in new if c.startswith('v4_res_')]
    r['res_all_null_on_first_run'] = {c: round(float(m.loc[first, c].isna().mean()), 4) for c in resc}
    # shift の確認: v4_p1_selfz は「直前の走の tz」から作られている
    prev = m.groupby('horse_key')['tz_v3'].shift(1)
    both = prev.notna() & m['v4_p1_selfz'].notna()
    r['p1_selfz_uses_prev_tz'] = int(both.sum())
    r['p1_selfz_null_when_no_prev'] = round(float(m.loc[prev.isna(), 'v4_p1_selfz'].isna().mean()), 4)
    # 当日値と不一致: 残差は当該走の tz を含まない → 当該走の tz との相関が小さいこと
    cor = {}
    for c in resc + ['v4_slope10', 'v4_form37', 'v4_p1_selfz']:
        s = m[[c, 'tz_v3']].dropna()
        cor[c] = round(float(s[c].corr(s['tz_v3'])), 4) if len(s) > 100 else None
    r['corr_with_same_race_tz'] = cor
    # 標本数の分布
    r['n_quantiles'] = {c: [float(x) for x in m[c].quantile([.25, .5, .75, .9]).to_numpy()]
                        for c in new if c.startswith('v4_n_')}
    json.dump(r, open(WORK + 'v4_check.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=float))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', default='all', choices=['runs', 'feats', 'join', 'check', 'all'])
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    t0 = time.time()
    if a.stage in ('runs', 'all'):
        stage_runs()
    if a.stage in ('feats', 'all'):
        stage_feats()
    if a.stage in ('join', 'all'):
        stage_join()
    if a.stage in ('check', 'all'):
        stage_check()
    log('done %.1fs' % (time.time() - t0))
