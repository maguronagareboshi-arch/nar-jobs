# -*- coding: utf-8 -*-
"""2 日目(PREREG2 §3・§8): 馬を見る予想 AI の材料の表(段 1〜4 の全部)とリーク検査。探索 2014〜2021 だけ。

  py -3.12 -X utf8 src/day2_features.py          # 材料の表 → v3/feat_explore.parquet
  py -3.12 -X utf8 src/day2_features.py leak     # リーク検査(抜き取り 20 日)→ out/day2_leak.md

どれも前日まで(race_date < 当日)の走り・結果だけから作る。当日の行から使うのは出走表の情報だけ
(馬・騎手・調教師・枠・性齢・斤量・馬体重の増減・距離・馬場・レース名・条件)と市場の E_mid。
当日の通過順・タイム・上がり・着差・確定票数・races.corners・win_odds_close は使わない。

■ 対象(§2): 南関 4 場・複勝の払戻あり・全馬に q と plc_lo・plc_hi(>0)がある。K = 3(8 頭以上)/2。
  E_mid = 1/((plc_lo+plc_hi)/2) をレース内で Σ = K に。Y3 = 複勝の払戻がある馬。
■ 走歴: 全 NAR 場の nar_runs(取消・除外を除く)+ nar_run_facts + nar_races。馬 = horse_key(無ければ horse_name)。
  1 走の頭数 = そのレースで取消・除外でない行の数。中止の着順÷頭数 = 1.0。
■ 細部(段の当てはめ外を見る前に固定。後で変えてよいのは §3 のバグ直しだけ):
  段 1  s1_c4rel   前走の 4 角位置 c4 ÷ n4
        s1_l3rank  前走の上がり 3F の順位(同タイムは小さい方)÷ そのレースで上がりのある頭数
        s1_tdiff   前走の勝ち馬とのタイム差 = time_sec − レース内の最小 time_sec、0〜3.0 で切る
        s1_front   近 5 走で最初の通過順(c1、無ければ c2→c3→c4)≤ その角の頭数/3 だった割合 × 今回の頭数 ÷ 12
        s1_dchg    (今回の距離 − 前走の距離)/100、±10 で切る
        s1_debut   前走なし = 1
  段 2  s2_jae・s2_tae  騎手・調教師の [当日−365, 当日−1] の南関の対象レースの log((ΣY3+30)/(ΣE_mid+30))
        s2_jchg    前走と騎手が違う = 1(前走なしは欠損)
  段 3  s3_ti_{prev,mean3,max5}  タイム指数: 斤量補正タイム = time_sec − c×(斤量−55)×距離/1000、
             基準 = 前日まで 730 日の同じ場×コース(芝・ダ)×距離×馬場の斤量補正タイムの中央値(20 走未満なら馬場を外す、
             0 走なら欠損)、指数 = (基準 − 補正タイム)÷距離×1000(1,000 m あたり秒・大きいほど速い)。
             c = 2014 年の全 NAR の同じ馬の続けての 2 走の差で出した傾き(1 本。weight_coef の説明)。
        s3_l3i_{prev,mean3,max5} 上がり指数 = 同じ基準の上がり 3F の中央値 − 上がり 3F(斤量補正なし)
        s3_finrel5 近 5 走の着順 ÷ 頭数の平均
        s3_class   南関のレース名+条件から: 重賞(Jpn・JpnⅠ〜Ⅲ・G・S1〜S3・重賞)11・OP/オープン/準重賞 10・
                   A1 9・A2 8・B1 7・B2 6・B3 5・C1 4・C2 3・C3 2(複数あれば大きい方)。読めない・南関以外は欠損
        s3_class_chg 今回 − 前走
        s3_gate・s3_track(0 浦和 1 船橋 2 大井 3 川崎)・s3_dist・s3_going(良 0 稍重 1 重 2 不良 3)
        s3_course_top3 同じ場で距離 ±200 m の過去の走りの 3 着内率を縮小 = (3 着内の数 + 0.8)÷(走った数 + 3)
        s3_age・s3_sex(牡 0 牝 1 セ 2)・s3_rest(前走からの日数)・s3_starts(2014 以降の出走数)・s3_n(今回の頭数)
  段 4  s4_rest_bw  間隔 ≥ 90 日 かつ 馬体重の増減 ≥ +10 kg(当日の発表を使う楽観値・診断だけ)
        s4_cw_chg   斤量 − 前走の斤量
出力 = C:/Users/kouki/nankan_ai/v3/feat_explore.parquet(2015〜2021 の対象の馬。2014 は走歴だけ)
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_outcomes import load_archive, load_outcomes  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
KEY = ['track', 'race_date', 'race_no']
NANKAN = ['浦和', '船橋', '大井', '川崎']
GOING = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
SEX = {'牡': 0, '牝': 1, 'セン': 2, 'セ': 2, 'せん': 2, '騸': 2}
ENTRY_COLS = ['horse_name', 'jockey', 'trainer', 'gate', 'sex', 'age', 'carried_weight', 'body_weight_change']
RACE_COLS = ['distance_m', 'going', 'surface', 'race_name', 'condition']


# ---------- 入力 ----------
def targets():
    """§2 の対象の馬(南関 2014〜2021)と E_mid・Y3・K。"""
    _, pay = load_outcomes()
    place = {}
    for t, dt, r, js in pay[KEY + ['payouts']].itertuples(index=False):
        for x in json.loads(js):
            if x['t'] == 'place':
                place.setdefault((t, str(dt), int(r)), set()).add(int(x['c']))
    df = pd.read_parquet(V3 / 'explore_frame.parquet')[KEY + ['umaban', 'q', 'meet', 'year']]
    df = df.assign(race_date=df.race_date.astype(str), race_no=df.race_no.astype(int))
    ql = pd.concat([pd.read_parquet(V3 / 'q_explore.parquet'),
                    pd.read_parquet(V3 / 'q_explore_rakuten2014_2019.parquet')])[KEY + ['umaban', 'plc_lo', 'plc_hi']]
    ql = ql.assign(race_date=ql.race_date.astype(str), race_no=ql.race_no.astype(int))
    ql = ql[ql.race_date < '2022-01-01'].drop_duplicates(KEY + ['umaban'])
    df = df[df.race_date < '2022-01-01'].merge(ql, on=KEY + ['umaban'], how='left')
    g = df.groupby(KEY)
    ok = (g.q.transform(lambda s: s.notna().all()) & g.plc_lo.transform(lambda s: s.notna().all() and (s > 0).all())
          & g.plc_hi.transform(lambda s: s.notna().all()))
    df = df[ok.astype(bool)].copy()
    df = df[[(t, d, r) in place for t, d, r in df[KEY].itertuples(index=False)]].copy()
    df['n'] = df.groupby(KEY).umaban.transform('size')
    df['K'] = np.where(df.n >= 8, 3, 2)
    e = 1 / ((df.plc_lo + df.plc_hi) / 2)
    df['E_mid'] = e / e.groupby([df[k] for k in KEY]).transform('sum') * df.K
    df['Y3'] = [int(u in place[(t, d, r)]) for t, d, r, u in df[KEY + ['umaban']].itertuples(index=False)]
    return df.reset_index(drop=True)


def load_sources():
    runs, facts, races = load_archive('runs'), load_archive('facts'), load_archive('races')
    for d in (runs, facts, races):
        d['race_no'] = d.race_no.astype(int)
    runs = runs.rename(columns={'runner_number': 'umaban'})
    runs['umaban'] = runs.umaban.astype(int)
    facts['umaban'] = facts.umaban.astype(int)
    f = facts[KEY + ['umaban', 'horse_key', 'last3f', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']].rename(columns={'last3f': 'f_l3'})
    h = runs.merge(f, on=KEY + ['umaban'], how='left').merge(races[KEY + RACE_COLS], on=KEY, how='left')
    h['hid'] = h.horse_key.fillna(h.horse_name)
    return h


def entries_of(h, tg):
    """対象の馬に当日の出走表の情報だけを付ける(結果の列は持たない)。"""
    cols = KEY + ['umaban', 'hid'] + ENTRY_COLS + RACE_COLS
    e = tg.merge(h[cols], on=KEY + ['umaban'], how='left')
    return e


# ---------- 走歴の下ごしらえ ----------
def class_num(name, cond, track):
    if track not in NANKAN or not isinstance(name, str):
        return np.nan
    s = unicodedata.normalize('NFKC', name + ' ' + (cond if isinstance(cond, str) else ''))
    if re.search(r'Jpn|JPN|重賞|\bG(?:[1-3]|I{1,3})\b|\bS(?:[1-3]|I{1,3})\b', s):
        return 11.0
    if re.search(r'OP|オープン|準重賞', s):
        return 10.0
    m = [{'A1': 9, 'A2': 8, 'B1': 7, 'B2': 6, 'B3': 5, 'C1': 4, 'C2': 3, 'C3': 2}[x] for x in re.findall(r'(A[12]|B[1-3]|C[1-3])', s)]
    return float(max(m)) if m else np.nan


def weight_coef(h):
    """斤量の補正係数(2014 年だけ・1 本)。同じ馬の続けての 2 走で「1,000 m あたりタイムの残差」の差を斤量の差に回帰
    (残差 = 2014 年の同じ場×コース×距離×馬場の中央値との差。|斤量の差| ≤ 6 kg)。
    レース内の回帰は強い馬ほど重い斤量を背負う交絡で負(−0.065)になるため使わない(当てはめ外を見る前に決めた)。"""
    d = h[(h.race_date < '2015-01-01') & h.time_sec.notna() & h.carried_weight.notna() & h.distance_m.notna()].copy()
    d['pace'] = d.time_sec / d.distance_m * 1000
    d['res'] = d.pace - d.groupby(['track', 'surface', 'distance_m', 'going']).pace.transform('median')
    d = d.sort_values(['hid', 'race_date', 'race_no'])
    g = d.groupby('hid')
    dx, dy = g.carried_weight.diff(), g.res.diff()
    ok = dx.notna() & dy.notna() & (dx.abs() <= 6)
    return float((dx[ok] * dy[ok]).sum() / (dx[ok] ** 2).sum())


def rolling_median(d, col, keys, days=730):
    """行ごとに、同じ keys で [日付−days, 日付−1] の col の中央値と件数。"""
    med = np.full(len(d), np.nan)
    cnt = np.zeros(len(d), int)
    ok = d[col].notna().to_numpy()
    for _, idx in d.groupby(keys, sort=False).indices.items():
        dt = d['dnum'].to_numpy()[idx]
        v = d[col].to_numpy()[idx]
        vv, dv = v[ok[idx]], dt[ok[idx]]
        o = np.argsort(dv, kind='mergesort')
        vv, dv = vv[o], dv[o]
        ud, inv = np.unique(dt, return_inverse=True)
        lo = np.searchsorted(dv, ud - days, 'left')
        hi = np.searchsorted(dv, ud, 'left')
        m = np.array([np.median(vv[a:b]) if b > a else np.nan for a, b in zip(lo, hi)])
        med[idx] = m[inv]
        cnt[idx] = (hi - lo)[inv]
    return med, cnt


def prep_hist(h):
    h = h[~h.finish_note.isin(['取消', '除外'])].copy()
    h['dnum'] = pd.to_datetime(h.race_date).values.astype('datetime64[D]').astype(np.int64)
    g = h.groupby(KEY)
    h['nstart'] = g.umaban.transform('size')
    h['fin_rel'] = np.where(h.finish.notna(), h.finish / h.nstart, 1.0)
    h['c4rel'] = h.c4 / h.n4
    l3 = h.last3f.where(h.last3f.notna(), h.f_l3) if 'f_l3' in h else h.last3f
    h['l3'] = l3
    h['l3rank'] = g.l3.rank(method='min') / g.l3.transform('count')
    h['tdiff'] = (h.time_sec - g.time_sec.transform('min')).clip(0, 3.0)
    first, nfirst = h.c1.copy(), h.n1.copy()
    for c, n in (('c2', 'n2'), ('c3', 'n3'), ('c4', 'n4')):
        miss = first.isna()
        first[miss], nfirst[miss] = h.loc[miss, c], h.loc[miss, n]
    h['front'] = np.where(first.notna() & nfirst.notna(), (first <= nfirst / 3).astype(float), np.nan)
    h['top3'] = (h.finish <= 3).astype(float)
    coef = weight_coef(h)
    h['adj_t'] = h.time_sec - coef * (h.carried_weight - 55) * h.distance_m / 1000
    m1, c1 = rolling_median(h, 'adj_t', ['track', 'surface', 'distance_m', 'going'])
    m0, _ = rolling_median(h, 'adj_t', ['track', 'surface', 'distance_m'])
    h['ti'] = (np.where(c1 >= 20, m1, m0) - h.adj_t) / h.distance_m * 1000
    m1, c1 = rolling_median(h, 'l3', ['track', 'surface', 'distance_m', 'going'])
    m0, _ = rolling_median(h, 'l3', ['track', 'surface', 'distance_m'])
    h['l3i'] = np.where(c1 >= 20, m1, m0) - h.l3
    h['cls'] = [class_num(a, b, t) for a, b, t in h[['race_name', 'condition', 'track']].itertuples(index=False)]
    h = h.sort_values(['hid', 'dnum', 'race_no']).reset_index(drop=True)
    h['pos'] = np.arange(len(h))
    h['nth'] = h.groupby('hid').cumcount().astype(float)
    return h, coef


def window_ae(src, who, e):
    """[当日−365, 当日−1] の log((ΣY3+30)/(ΣE_mid+30))。"""
    d = src.groupby([who, 'dnum'])[['Y3', 'E_mid']].sum().reset_index().sort_values([who, 'dnum'])
    d[['cY', 'cE']] = d.groupby(who)[['Y3', 'E_mid']].cumsum()
    q = e[['rid', who, 'dnum']].dropna(subset=[who])
    out = {}
    for tag, shift in (('a', 0), ('b', 365)):
        qq = q.assign(k=q.dnum - shift).sort_values('k')
        r = pd.merge_asof(qq, d[[who, 'dnum', 'cY', 'cE']].rename(columns={'dnum': 'k'}).sort_values('k'),
                          on='k', by=who, allow_exact_matches=False)
        out[tag] = r.set_index('rid')[['cY', 'cE']].fillna(0)
    s = out['a'] - out['b'].reindex(out['a'].index)
    v = np.log((s.cY + 30) / (s.cE + 30))
    return e.rid.map(v)


# ---------- 材料 ----------
def build(h_raw, tg, ae_src, ent=None):
    """h_raw = 走歴(結果つき)、tg = 対象の馬(E_mid・Y3 つき)、ae_src = 騎手・調教師の A/E 用の対象の馬。"""
    h, coef = prep_hist(h_raw)
    e = entries_of(h_raw if ent is None else ent, tg)
    e['rid'] = np.arange(len(e))
    e['dnum'] = pd.to_datetime(e.race_date).values.astype('datetime64[D]').astype(np.int64)
    # 前走の位置(race_date < 当日)
    a = pd.merge_asof(e[['rid', 'hid', 'dnum']].sort_values('dnum'), h[['hid', 'dnum', 'pos']].sort_values('dnum'),
                      on='dnum', by='hid', allow_exact_matches=False).set_index('rid').pos.reindex(e.rid)
    P = a.to_numpy()
    hid_h = h.hid.to_numpy()
    ehid = e.hid.to_numpy()

    def lag(col, k):
        idx = P - k
        ok = ~np.isnan(P)
        ii = np.where(ok, idx, 0).astype(int)
        ok &= (idx >= 0) & (hid_h[np.clip(ii, 0, len(h) - 1)] == ehid)
        v = h[col].to_numpy(float) if h[col].dtype != object else h[col].to_numpy()
        out = np.full(len(e), np.nan, dtype=float if v.dtype != object else object)
        out[ok] = v[ii[ok]]
        return out

    def lags(col, k):
        return np.column_stack([lag(col, j) for j in range(k)]).astype(float)

    def nanagg(M, f):
        with np.errstate(all='ignore'), __import__('warnings').catch_warnings():
            __import__('warnings').simplefilter('ignore')
            return f(M, axis=1)

    has_prev = ~np.isnan(lag('dnum', 0))
    X = e[KEY + ['umaban', 'year', 'meet', 'n', 'K', 'q', 'plc_lo', 'plc_hi', 'E_mid', 'Y3']].copy()
    n_now = e.groupby(KEY).umaban.transform('size').to_numpy(float)
    # 段 1
    X['s1_c4rel'] = lag('c4rel', 0)
    X['s1_l3rank'] = lag('l3rank', 0)
    X['s1_tdiff'] = lag('tdiff', 0)
    X['s1_front'] = nanagg(lags('front', 5), np.nanmean) * n_now / 12
    X['s1_dchg'] = np.clip((e.distance_m.to_numpy(float) - lag('distance_m', 0)) / 100, -10, 10)
    X['s1_debut'] = (~has_prev).astype(float)
    # 段 2
    src = ae_src.merge((h_raw if ent is None else pd.concat([h_raw, ent]))[KEY + ['umaban', 'jockey', 'trainer']], on=KEY + ['umaban'], how='left')
    src['dnum'] = pd.to_datetime(src.race_date).values.astype('datetime64[D]').astype(np.int64)
    X['s2_jae'] = window_ae(src, 'jockey', e).to_numpy()
    X['s2_tae'] = window_ae(src, 'trainer', e).to_numpy()
    pj = lag('jockey', 0)
    X['s2_jchg'] = np.where(has_prev, (pj != e.jockey.to_numpy()).astype(float), np.nan)
    # 段 3
    ti, l3i = lags('ti', 5), lags('l3i', 5)
    X['s3_ti_prev'], X['s3_ti_mean3'], X['s3_ti_max5'] = ti[:, 0], nanagg(ti[:, :3], np.nanmean), nanagg(ti, np.nanmax)
    X['s3_l3i_prev'], X['s3_l3i_mean3'], X['s3_l3i_max5'] = l3i[:, 0], nanagg(l3i[:, :3], np.nanmean), nanagg(l3i, np.nanmax)
    X['s3_finrel5'] = nanagg(lags('fin_rel', 5), np.nanmean)
    cls = np.array([class_num(a, b, t) for a, b, t in e[['race_name', 'condition', 'track']].itertuples(index=False)], float)
    X['s3_class'] = cls
    X['s3_class_chg'] = cls - lag('cls', 0)
    X['s3_gate'] = e.gate.astype(float).to_numpy()
    X['s3_track'] = e.track.map({t: i for i, t in enumerate(NANKAN)}).astype(float).to_numpy()
    X['s3_dist'] = e.distance_m.astype(float).to_numpy()
    X['s3_going'] = e.going.map(GOING).astype(float).to_numpy()
    m = e[['rid', 'hid', 'track', 'dnum', 'distance_m']].merge(
        h[['hid', 'track', 'dnum', 'distance_m', 'top3']], on=['hid', 'track'], suffixes=('', '_h'))
    m = m[(m.dnum_h < m.dnum) & ((m.distance_m_h - m.distance_m).abs() <= 200)]
    ct = m.groupby('rid').top3.agg(['sum', 'count']).reindex(e.rid).fillna(0)
    X['s3_course_top3'] = ((ct['sum'] + 0.8) / (ct['count'] + 3)).to_numpy()
    X['s3_age'] = e.age.astype(float).to_numpy()
    X['s3_sex'] = e.sex.map(SEX).astype(float).to_numpy()
    X['s3_rest'] = e.dnum.to_numpy(float) - lag('dnum', 0)
    X['s3_starts'] = np.where(has_prev, lag('nth', 0) + 1, 0.0)
    X['s3_n'] = n_now
    # 段 4(診断だけ)
    X['s4_rest_bw'] = ((X.s3_rest >= 90) & (e.body_weight_change.astype(float).to_numpy() >= 10)).astype(float)
    X['s4_cw_chg'] = e.carried_weight.astype(float).to_numpy() - lag('carried_weight', 0)
    return X, coef


def main():
    h = load_sources()
    tg = targets()
    X, coef = build(h, tg[tg.race_date >= '2015-01-01'].reset_index(drop=True), tg)
    X.to_parquet(V3 / 'feat_explore.parquet', index=False)
    feats = [c for c in X.columns if c[:2] in ('s1', 's2', 's3', 's4')]
    miss = X[feats].isna().mean().round(3).to_dict()
    print('rows', len(X), 'races', X[KEY].drop_duplicates().shape[0], 'coef', round(coef, 5))
    print('missing', miss)


def leak():
    """§8: 抜き取り 20 日(2016〜2021 の開催日・seed 0)。当日以降の行を消し(当日は出走表の列だけ残す)作り直して比べる。"""
    h = load_sources()
    tg = targets()
    full = pd.read_parquet(V3 / 'feat_explore.parquet')
    feats = [c for c in full.columns if c[:2] in ('s1', 's2', 's3', 's4')]
    days = np.sort(np.random.default_rng(0).choice(np.sort(tg[tg.race_date >= '2016-01-01'].race_date.unique()), 20, replace=False))
    L = ['# 2 日目: リーク検査(PREREG2 §8)', '',
         '抜き取り 20 日: 走歴・騎手調教師の A/E の元から race_date ≥ 当日 の行を消し、当日は出走表の列だけを残して作り直す。',
         f'比べる材料 {len(feats)} 列(段 1〜4)。一致 = 両方欠損、または差の絶対値 ≤ 1e-9。', '',
         '| 日 | 頭 | 一致したセル | 全セル | 一致 % |', '|---|---|---|---|---|']
    tot = [0, 0]
    for d in days:
        ent = h.loc[h.race_date == d, KEY + ['umaban', 'hid'] + ENTRY_COLS + RACE_COLS]
        Xd, _ = build(h[h.race_date < d], tg[tg.race_date == d].reset_index(drop=True), tg[tg.race_date < d], ent=ent)
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
    (REPO / 'out/day2_leak.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(L[-1])


if __name__ == '__main__':
    leak() if sys.argv[1:] == ['leak'] else main()
