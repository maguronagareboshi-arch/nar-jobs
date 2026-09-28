# -*- coding: utf-8 -*-
"""第 4 版 3 日目(PREREG4 §2・§4・§5・§6・§10): 材料の表(段 1〜6 の 96 列)→ リーク検査 → 段 0〜5 の当てはめ外 → 格子 →
当日版 → 第 3 版の線 → recent(記録だけ)。作る期間 2015〜2021 だけ(2022-01-01 以降は読まない)。

  py -3.12 -X utf8 src/t4_day3.py features   # → v3/feat_t4_explore.parquet
  py -3.12 -X utf8 src/t4_day3.py leak       # 前日版の全列(93)のリーク検査 20 日 → v3/t4_day3_leak.json
  py -3.12 -X utf8 src/t4_day3.py stages     # 段 0〜5(拡張窓 2016〜2021・15/500/800)と採否
  py -3.12 -X utf8 src/t4_day3.py grid       # 最終形の格子 8 通り(Y1 を先に・その p1 で Y3)
  py -3.12 -X utf8 src/t4_day3.py day        # 当日版(最終形 + 段 6 の 3 列・同じ設定)
  py -3.12 -X utf8 src/t4_day3.py v3line     # 第 3 版の前日版 29 列・当日版 32 列(t3_grid.json の設定・同じ拡張窓)
  py -3.12 -X utf8 src/t4_day3.py recent     # 記録だけ: 最終形の前日版を直前 3 年だけで学習(2018〜2021)
  py -3.12 -X utf8 src/t4_day3.py md         # out/t4_day3.md
学習の途中は v3/t4_cache/ にキャッシュ(落ちても続きから)。結果は v3/t4_day3_res.json に足していく。

■ コードの番号表(当てはめ外を見る前に固定)
  h_mark   減量の印: 無し 0・☆ 1・△ 2・▲ 3・★ 4・◇ 4。ほかの印は assert で止まる。
  l_region 南関以外の NAR の最後の走りの地区: 無し 0・北海道(門別)1・岩手(盛岡・水沢)2・金沢 3・東海(笠松・名古屋)4・
           兵庫(園田・姫路)5・高知 6・佐賀 7。ほかの場は assert で止まる。

■ 決め書に無い細部(この台本で決めた・当てはめ外を見る前。見た後は変えない)
  1. 「5 走」= 直前の南関の 5 走(取消・除外を除く)。a_si2 = その中で 2 番目に高い SI(SI が 2 つ以上)、a_simax5 = 最高、
     a_sin = その 5 走のうち SI のある走数(0〜5)、a_sisd = 母標準偏差(SI が 3 つ以上)、a_sislope = SI を日付に最小二乗で
     当てた傾き × 30(SI が 3 つ以上)。
  2. a_tenw・a_upw = その指数のある南関の過去 5 走を a_siw と同じ重み 0.5^(経過日数/90) で平均。a_ten1・a_up1 は前の南関の走りの値。
  3. a_tdiff1 = 前の南関の走りの (min(T − 勝ち馬の T, 2.0 × d/1000)) ÷ (d/1000)。T が無ければ欠け。
  4. 着順 ÷ 頭数(c_fin1・c_bestg・l_nfin・h_plus)の頭数 = そのレースの取消・除外を除く出走数。着順の無い走り(中止など)は 1.0。
     3 着以内・勝ちは着順から(中止は 0)。
  5. c_top3_5・c_win5 は 5 走の中の数(南関の走りが無ければ欠け)。c_top3all・c_out も走りが無ければ欠け。c_out は直前から
     さかのぼって続く 4 着以下(中止を含む)の数(上限なし)。c_bestg は 5 走のうち、その走りの b_g が今回の b_g 以上の走りの
     着順 ÷ 頭数の最小(該当なし・今回の b_g が欠けなら欠け)。
  6. c_stop の「中止」= finish_note が「中止」。取消/除外は [当日 − 90, 当日 − 1] の全 NAR の行。
  7. 最初の角の位置 = c1(無ければ c2 → c3 → c4)、÷ その角の頭数(第 3 版の s1_front と同じ拾い方)。f_nige5 = 5 走のうち
     角の位置のある走りで 1 番手だった割合。f_up5 = 5 走の (c4 − 着順) ÷ 頭数(両方ある走り)の平均。
  8. f_bias・j_gatebias の窓は §3 の物差しと同じ(2015 は 2014 だけ・y は max(2014, y−3)〜y−1)。f_bias は角の位置のある馬だけで
     率を出す。j_gatebias は窓の予想するレース(targets3 の組)の (コース・枠) の ΣY3 ÷ Σ 3/n。コース = t4_base の course。
  9. 騎手・調教師の窓の元 = 予想するレース(targets3 の組・2014〜)。365 日 = [当日 − 365, 当日 − 1]、3 年 = [当日 − 1095, 当日 − 1]。
     i_trest の間隔 = 全 NAR の前の走りからの日数(初出走は入れない)。h_chgdir の前走の騎手の h_j3 は今回の日付で数える
     (前走が無ければ欠け)。h_plus の騎乗 = 南関の走り(t4_base)で k_ab_rank のある騎乗。騎乗が無い騎手は 0。
  10. h_pair = この馬の南関の過去の走りでこの騎手の Σ(3 着以内 − 3/頭数)。d_*・e_trk3・e_trksi・e_first・e_heavy は南関の過去の
      全走(2014〜)。e_heavy の馬場 = そのレースの going。e_night = post_time ≥ 1700(欠けは欠け)。
  11. i_move = 今回の調教師で続けて走った数(今回を含む)。それより前に違う調教師の走りが無ければ(初出走を含む)0。全 NAR の走り。
  12. g_nrest = 直近の「前の走りから 60 日以上」の走り(今回を含む)から数えて何走目(1〜5)。無い・6 走目以降は 0。
  13. l_jra・l_nar・l_nfin・l_region は全 NAR の走り(取消・除外を除く)。l_jra の年齢 = 南関の初戦の age。
  14. 「前の段」= 最後に残した段。段 0 の p1 = 1/n・p3 = 3/n。
  15. recent の学習 = y−3〜y−1 年の行だけ(設定は格子で選んだもの)。
"""
import itertools
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_base  # noqa: E402
from day2_features import ENTRY_COLS, RACE_COLS, build as build3  # noqa: E402
from load_outcomes import load_archive  # noqa: E402
from t3_day2_features import FEATS3, finish_table, targets3  # noqa: E402
import t3_eval  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
CACHE = V3 / 't4_cache'
FEAT = V3 / 'feat_t4_explore.parquet'
RES = V3 / 't4_day3_res.json'
KEY = ['track', 'race_date', 'race_no']
NANKAN = ['浦和', '船橋', '大井', '川崎']
CANCEL = ['取消', '除外']
YEARS = [2016, 2017, 2018, 2019, 2020, 2021]
H_MARK = {'☆': 1, '△': 2, '▲': 3, '★': 4, '◇': 4}
REGION = {'門別': 1, '盛岡': 2, '水沢': 2, '金沢': 3, '笠松': 4, '名古屋': 4, '園田': 5, '姫路': 5, '高知': 6, '佐賀': 7}
V3MAP = {'c_fin5': 's3_finrel5', 'f_c4_1': 's1_c4rel', 'f_front5': 's1_front', 'f_l3rank1': 's1_l3rank',
         'h_j3': 's2_jnaive', 'h_chg': 's2_jchg', 'i_t3': 's2_tnaive', 'd_chg': 's1_dchg', 'e_track': 's3_track',
         'e_dist': 's3_dist', 'e_course3': 's3_course_top3', 'g_rest': 's3_rest', 'g_starts': 's3_starts',
         'g_age': 's3_age', 'g_sex': 's3_sex', 'j_gate': 's3_gate', 'j_n': 's3_n', 'j_cw': 's3_cw',
         'j_cwchg': 's3_cw_chg', 'l_debut': 's1_debut', 'o_going': 's4a_going', 'o_bw': 's4b_bw',
         'o_bwchg': 's4b_bw_chg'}
FEATS4 = {
    1: ['a_si1', 'a_si2', 'a_simax5', 'a_siw', 'a_ab', 'a_sin', 'a_sisd', 'a_sislope', 'a_ten1', 'a_tenw', 'a_up1',
        'a_upw', 'a_tdiff1',
        'b_g', 'b_kumi', 'b_young', 'b_age', 'b_kind', 'b_prize', 'b_g1', 'b_gchg', 'b_prizechg', 'b_lv', 'b_lv1',
        'b_lvchg',
        'k_ab_rank', 'k_ab_z', 'k_ab_gap', 'k_si_rank', 'k_si_z', 'k_si_gap', 'k_ab_sd'],
    2: ['c_fin5', 'c_fin1', 'c_top3_5', 'c_win5', 'c_top3all', 'c_bestg', 'c_out', 'c_stop',
        'f_c4_1', 'f_front5', 'f_l3rank1', 'f_c1_1', 'f_nige5', 'f_up5', 'f_ten_rank', 'f_nige_n', 'f_bias'],
    3: ['h_j3', 'h_j1', 'h_jtrk', 'h_chg', 'h_chgdir', 'h_pair', 'h_mark', 'h_plus', 'h_jrank',
        'i_t3', 'i_t1', 'i_trest', 'i_ttrans', 'i_move'],
    4: ['d_chg', 'd_top3', 'd_simax', 'd_first',
        'e_track', 'e_dist', 'e_course3', 'e_trk3', 'e_trksi', 'e_first', 'e_heavy', 'e_night',
        'g_rest', 'g_starts', 'g_age', 'g_sex', 'g_nrest', 'g_n90',
        'j_gate', 'j_n', 'j_cw', 'j_cwchg', 'j_umaban', 'j_gatebias', 'j_cwrel'],
    5: ['l_debut', 'l_jra', 'l_nar', 'l_nfin', 'l_region'],
    6: ['o_going', 'o_bw', 'o_bwchg'],
}
PRE_ALL = sum((FEATS4[s] for s in (1, 2, 3, 4, 5)), [])
ALL = PRE_ALL + FEATS4[6]
assert [len(FEATS4[s]) for s in range(1, 7)] == [32, 17, 14, 25, 5, 3] and len(set(ALL)) == 96
META = KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop']
BANNED = {'q', 'plc_lo', 'plc_hi', 'E_mid', 'pop', 'popularity', 'win', 'Y1', 'Y3', 'finish', 'win_odds_close',
          'finish_note', 'time_sec', 'last3f', 'margin', 'SI', 'ten_i', 'up_i'}
BASE = dict(objective='binary', learning_rate=0.03, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
            lambda_l2=10, seed=0, deterministic=True, num_threads=4, verbose=-1)
STAGE_CFG = (15, 500, 800)
GRID = list(itertools.product([15, 31], [100, 500], [400, 1200]))
FACT_RES = ['c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4', 'style', 'style_p', 'style_n', 'first3f', 'first3f_src',
            'last3f', 'win_odds_close']


# ================================================================ 読み込み
def sources_from(runs, facts, races):
    """day2_features.load_sources と同じ作り方(渡した表から)。"""
    runs, facts, races = runs.copy(), facts.copy(), races.copy()
    for d in (runs, facts, races):
        d['race_no'] = d.race_no.astype(int)
    runs = runs.rename(columns={'runner_number': 'umaban'})
    runs['umaban'] = runs.umaban.astype(int)
    facts['umaban'] = facts.umaban.astype(int)
    f = facts[KEY + ['umaban', 'horse_key', 'last3f', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']].rename(
        columns={'last3f': 'f_l3'})
    h = runs.merge(f, on=KEY + ['umaban'], how='left').merge(races[KEY + RACE_COLS], on=KEY, how='left')
    h['hid'] = h.horse_key.fillna(h.horse_name)
    return h


def raw():
    runs, facts, races = load_archive('runs'), load_archive('facts'), load_archive('races')
    for d in (runs, facts, races):
        assert d.race_date.max() < '2022-01-01'
        d['race_no'] = d.race_no.astype(int)
    return runs, facts, races


def base_from(runs, facts, races):
    """t4_base.load と同じ絞り方で t4_base.build を呼ぶ。"""
    r = runs[runs.track.isin(NANKAN) & (runs.race_date >= '2014-01-01')].copy()
    f = facts[facts.track.isin(NANKAN)][KEY + ['umaban', 'horse_key']].rename(columns={'umaban': 'runner_number'})
    r = r.merge(f, on=KEY + ['runner_number'], how='left')
    c = races[races.track.isin(NANKAN) & (races.race_date >= '2014-01-01')].copy()
    return t4_base.build(r.reset_index(drop=True), c.reset_index(drop=True), log=lambda *a: None)


def dnum_of(s):
    return pd.to_datetime(s).values.astype('datetime64[D]').astype(np.int64)


# ================================================================ 道具
def lagf(arr, hid, j):
    out = np.full(len(arr), np.nan)
    ok = hid[j:] == hid[:-j]
    out[j:] = np.where(ok, arr[:-j], np.nan)
    return out


def lago(arr, hid, j):
    out = np.full(len(arr), None, dtype=object)
    ok = hid[j:] == hid[:-j]
    out[j:] = np.where(ok, arr[:-j], None)
    return out


def lagm(arr, hid, k=5):
    return np.column_stack([lagf(arr, hid, j) for j in range(1, k + 1)])


def nanagg(M, f, **kw):
    import warnings
    with np.errstate(all='ignore'), warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return f(M, axis=1, **kw)


def lastk(hid, dnum, vals, valid, k, qhid, qdnum):
    """行が (hid, dnum) の順に並んでいるとき、各問い合わせの前(dnum が小さい)の valid な行の最後の k 個の値と dnum。"""
    S = valid
    Skey = hid[S].astype(np.int64) * 100000 + dnum[S]
    Sv, Sd = vals[S], dnum[S]
    qk = qhid.astype(np.int64) * 100000 + qdnum
    pos = np.searchsorted(Skey, qk, 'left')
    hst = np.searchsorted(Skey, qhid.astype(np.int64) * 100000, 'left')
    V = np.full((len(qk), k), np.nan)
    Dd = np.full((len(qk), k), np.nan)
    for j in range(1, k + 1):
        idx = pos - j
        ok = idx >= hst
        ii = np.where(ok, idx, 0)
        if len(Sv):
            V[:, j - 1] = np.where(ok, Sv[ii], np.nan)
            Dd[:, j - 1] = np.where(ok, Sd[ii], np.nan)
    return V, Dd


def _key(d, by):
    k = d[by[0]].astype(str)
    for b in by[1:]:
        k = k + '|' + d[b].astype(str)
    return k.where(d[by].notna().all(axis=1))


def wsum(src, by, cols, q, days):
    """q の各行について、src の同じ by で dnum が [q.dnum − days, q.dnum − 1] の cols の和(numpy・q の順)。by が欠けなら NaN。"""
    out = np.full((len(q), len(cols)), np.nan)
    qk = _key(q, by)
    okq = qk.notna().to_numpy()
    out[okq] = 0.0
    s = src.assign(_k=_key(src, by)).dropna(subset=['_k'])
    if len(s) == 0 or okq.sum() == 0:
        return out
    d = s.groupby(['_k', 'dnum'])[cols].sum().reset_index().sort_values(['_k', 'dnum'])
    d[cols] = d.groupby('_k')[cols].cumsum()
    d = d.rename(columns={'dnum': 't'}).sort_values('t')
    qq = pd.DataFrame({'_k': qk[okq].to_numpy(), 'dnum': q.dnum.to_numpy()[okq], '_i': np.arange(len(q))[okq]})
    res = []
    for shift in (0, days):
        a = qq.assign(t=qq.dnum - shift).sort_values('t')
        r = pd.merge_asof(a, d[['_k', 't'] + cols], on='t', by='_k', allow_exact_matches=False)
        res.append(r.set_index('_i')[cols].fillna(0.0).sort_index().to_numpy())
    out[np.arange(len(q))[okq]] = res[0] - res[1]
    return out


def first_corner(d):
    pos, n = d.c1.astype(float).copy(), d.n1.astype(float).copy()
    for c, nn in (('c2', 'n2'), ('c3', 'n3'), ('c4', 'n4')):
        m = pos.isna()
        pos[m], n[m] = d.loc[m, c].astype(float), d.loc[m, nn].astype(float)
    return pos.to_numpy(), n.to_numpy()


def in_race_rank(T, col):
    g = T.groupby(KEY)[col]
    return (g.rank(ascending=False, method='average') / g.transform('count')).to_numpy()


def win_years(y):
    return [2014] if y == 2015 else [x for x in range(y - 3, y) if x >= 2014]


# ================================================================ 材料(第 4 版の新しい列)
def feat_new(U, h, races, tg_src, tgt):
    """U = t4_base.build の出力(南関の出走)、h = 全 NAR の走り(sources_from)、races = レースの表、
    tg_src = 騎手・調教師・枠の窓の元(targets3 の組)、tgt = 作る行(targets3 の組)。新しい列(〔v3〕以外)を tgt の順で返す。"""
    # ---------- 南関の走り(U)
    U = U.rename(columns={'runner_number': 'umaban'}).copy()
    U['umaban'] = U.umaban.astype(int)
    U['race_no'] = U.race_no.astype(int)
    hh = h[~h.finish_note.isin(CANCEL)][KEY + ['umaban', 'jockey', 'trainer', 'gate', 'weight_mark', 'c1', 'n1', 'c2',
                                              'n2', 'c3', 'n3', 'c4', 'n4']].drop_duplicates(KEY + ['umaban'])
    U = U.merge(hh, on=KEY + ['umaban'], how='left')
    rc = races[KEY + ['post_time', 'going']].copy()
    rc['race_no'] = rc.race_no.astype(int)
    U = U.merge(rc.drop_duplicates(KEY), on=KEY, how='left')
    U['dnum'] = dnum_of(U.race_date)
    U['nstart'] = U.groupby(KEY).umaban.transform('size').astype(float)
    U['finrel'] = np.where(U.finish.notna(), U.finish / U.nstart, 1.0)
    U['top3'] = (U.finish <= 3).astype(float)
    U['win1'] = (U.finish == 1).astype(float)
    fpos, fn = first_corner(U)
    U['fpos'] = fpos
    U['fc'] = fpos / fn
    U['nige'] = np.where(np.isnan(fpos), np.nan, (fpos == 1).astype(float))
    U['upg'] = (U.c4.astype(float) - U.finish) / U.nstart
    d = U.distance_m.astype(float)
    wt = U.time_sec - U.groupby(KEY).time_sec.transform('min')
    U['tdiff'] = np.minimum(wt, 2.0 * d / 1000) / (d / 1000)
    U['E3'] = 3 / U.nstart
    U = U.sort_values(['hk', 'dnum', 'race_no']).reset_index(drop=True)
    hid = pd.factorize(U.hk)[0].astype(np.int64)
    dn = U.dnum.to_numpy()
    F = pd.DataFrame(index=U.index)
    # A 時計
    Lsi = lagm(U.SI.to_numpy(float), hid)
    cnt = (~np.isnan(Lsi)).sum(1)
    srt = -np.sort(-Lsi, axis=1)
    F['a_si1'] = U.a_si1
    F['a_si2'] = np.where(cnt >= 2, srt[:, 1], np.nan)
    F['a_simax5'] = nanagg(Lsi, np.nanmax)
    F['a_siw'] = U.a_siw
    F['a_ab'] = U.a_ab
    F['a_sin'] = cnt.astype(float)
    F['a_sisd'] = np.where(cnt >= 3, nanagg(Lsi, np.nanstd), np.nan)
    Ld = lagm(dn.astype(float), hid)
    Ld = np.where(np.isnan(Lsi), np.nan, Ld)
    xm = nanagg(Ld, np.nanmean)[:, None]
    ym = nanagg(Lsi, np.nanmean)[:, None]
    sxy = np.nansum((Ld - xm) * (Lsi - ym), axis=1)
    sxx = np.nansum((Ld - xm) ** 2, axis=1)
    F['a_sislope'] = np.where((cnt >= 3) & (sxx > 0), sxy / np.where(sxx > 0, sxx, 1) * 30, np.nan)
    for src, n1, nw in (('ten_i', 'a_ten1', 'a_tenw'), ('up_i', 'a_up1', 'a_upw')):
        v = U[src].to_numpy(float)
        F[n1] = lagf(v, hid, 1)
        V, Dd = lastk(hid, dn, v, ~np.isnan(v), 5, hid, dn)
        w = np.where(np.isnan(V), 0.0, 0.5 ** ((dn[:, None] - Dd) / 90.0))
        sw = w.sum(1)
        F[nw] = np.where(sw > 0, np.nansum(w * np.nan_to_num(V), axis=1) / np.where(sw > 0, sw, 1), np.nan)
    F['a_tdiff1'] = lagf(U.tdiff.to_numpy(float), hid, 1)
    # B 格
    for c in ['b_g', 'b_kumi', 'b_young', 'b_age', 'b_kind', 'b_prize', 'b_lv', 'b_lv1']:
        F[c] = U[c].astype(float)
    F['b_g1'] = lagf(U.b_g.to_numpy(float), hid, 1)
    F['b_gchg'] = F.b_g - F.b_g1
    F['b_prizechg'] = F.b_prize - lagf(U.b_prize.to_numpy(float), hid, 1)
    F['b_lvchg'] = F.b_lv - F.b_lv1
    # K 相手関係
    for c in ['k_ab_rank', 'k_ab_z', 'k_ab_gap', 'k_si_rank', 'k_si_z', 'k_si_gap', 'k_ab_sd']:
        F[c] = U[c].astype(float)
    # C 成績
    has1 = ~np.isnan(lagf(dn.astype(float), hid, 1))
    Lfr = lagm(U.finrel.to_numpy(float), hid)
    Lt3 = lagm(U.top3.to_numpy(float), hid)
    Lw = lagm(U.win1.to_numpy(float), hid)
    F['c_fin1'] = Lfr[:, 0]
    F['c_top3_5'] = np.where(has1, np.nansum(Lt3, axis=1), np.nan)
    F['c_win5'] = np.where(has1, np.nansum(Lw, axis=1), np.nan)
    gh = pd.Series(hid)
    k = gh.groupby(hid).cumcount().to_numpy().astype(float)
    cs = pd.Series(U.top3.to_numpy()).groupby(hid).cumsum().to_numpy() - U.top3.to_numpy()
    F['c_top3all'] = np.where(k > 0, cs / np.where(k > 0, k, 1), np.nan)
    Lbg = lagm(U.b_g.to_numpy(float), hid)
    bg = U.b_g.to_numpy(float)[:, None]
    F['c_bestg'] = nanagg(np.where(Lbg >= bg, Lfr, np.nan), np.nanmin)
    o = pd.Series(1.0 - U.top3.to_numpy())
    grp = (o == 0).groupby(hid).cumsum()
    streak = o.groupby([hid, grp.to_numpy()]).cumsum().to_numpy()
    F['c_out'] = lagf(streak.astype(float), hid, 1)
    # F 展開(南関)
    F['f_c1_1'] = lagf(U.fc.to_numpy(float), hid, 1)
    F['f_nige5'] = nanagg(lagm(U.nige.to_numpy(float), hid), np.nanmean)
    F['f_up5'] = nanagg(lagm(U.upg.to_numpy(float), hid), np.nanmean)
    # D・E・h_pair(過去の南関の全走との組)
    hv = U.going.map({'重': 1.0, '不良': 1.0, '良': 0.0, '稍重': 0.0}).to_numpy(float)
    # バグ直し(3 日目・リーク検査で発見・段 4 の当てはめ外を見る前): 並べ替えの前の距離を使っていた → 並べ替えの後の列から取る
    B = pd.DataFrame({'i': np.arange(len(U)), 'hid': hid, 'dnum': dn, 'dist': U.distance_m.to_numpy(float), 'trk': U.track.to_numpy(),
                      'jk': U.jockey.to_numpy(), 'top3': U.top3.to_numpy(), 'SI': U.SI.to_numpy(float), 'hv': hv,
                      'E3': U.E3.to_numpy()})
    agg = {c: np.full(len(U), np.nan) for c in ['d_n', 'd_t3', 'd_si', 't_n', 't_t3', 't_si', 'hvy', 'lgt', 'p_n', 'p_s']}
    uh = np.unique(hid)
    for ch in np.array_split(uh, 40):
        sub = B[np.isin(B.hid.to_numpy(), ch)]
        P = sub[['i', 'hid', 'dnum', 'dist', 'trk', 'jk']].merge(
            sub[['hid', 'dnum', 'dist', 'trk', 'jk', 'top3', 'SI', 'hv', 'E3']], on='hid', suffixes=('', '_p'))
        P = P[P.dnum_p < P.dnum]
        md = (P.dist_p - P.dist).abs() <= 200
        g = P[md].groupby('i')
        r = pd.DataFrame({'d_n': g.size(), 'd_t3': g.top3.sum(), 'd_si': g.SI.max()})
        mt = P.trk_p == P.trk
        g = P[mt].groupby('i')
        r = r.join(pd.DataFrame({'t_n': g.size(), 't_t3': g.top3.sum(), 't_si': g.SI.max()}), how='outer')
        r = r.join(P[(P.hv == 1) & P.SI.notna()].groupby('i').SI.mean().rename('hvy'), how='outer')
        r = r.join(P[(P.hv == 0) & P.SI.notna()].groupby('i').SI.mean().rename('lgt'), how='outer')
        mp = P.jk.notna() & (P.jk_p == P.jk)
        pp = P[mp].assign(v=P.top3 - P.E3).groupby('i')
        r = r.join(pd.DataFrame({'p_n': pp.size(), 'p_s': pp.v.sum()}), how='outer')
        for c in agg:
            if c in r:
                agg[c][r.index.to_numpy()] = r[c].to_numpy(float)
    dn_ = np.nan_to_num(agg['d_n'])
    tn_ = np.nan_to_num(agg['t_n'])
    F['d_top3'] = np.where(dn_ > 0, agg['d_t3'] / np.where(dn_ > 0, dn_, 1), np.nan)
    F['d_simax'] = agg['d_si']
    F['d_first'] = (dn_ == 0).astype(float)
    F['e_trk3'] = np.where(tn_ > 0, agg['t_t3'] / np.where(tn_ > 0, tn_, 1), np.nan)
    F['e_trksi'] = agg['t_si']
    F['e_first'] = (tn_ == 0).astype(float)
    F['e_heavy'] = agg['hvy'] - agg['lgt']
    F['e_night'] = np.where(U.post_time.notna(), (U.post_time.astype(float) >= 1700).astype(float), np.nan)
    F['h_pair'] = np.where(np.nan_to_num(agg['p_n']) > 0, agg['p_s'], np.nan)
    # h_mark
    wm = U.weight_mark
    unk = set(wm.dropna().unique()) - set(H_MARK)
    assert not unk, f'知らない減量の印: {unk}'
    F['h_mark'] = wm.map(H_MARK).fillna(0).astype(float)
    F['j_umaban'] = U.umaban.astype(float)
    # f_bias(コース × 年の窓)
    U['year'] = U.year.astype(int)
    F['f_bias'] = np.nan
    for y in sorted(U.year.unique()):
        if y < 2015:
            continue
        W = U[U.year.isin(win_years(y)) & U.fpos.notna()]
        fr = W[W.fpos <= 3].groupby('course').top3.mean() - W.groupby('course').top3.mean()
        iy = U.index[U.year == y]
        F.loc[iy, 'f_bias'] = U.loc[iy, 'course'].map(fr).astype(float).to_numpy()
    # h_plus(騎手の上積み・365 日)
    U['hp_v'] = U.k_ab_rank - U.finrel
    src_u = U[U.hp_v.notna() & U.jockey.notna()][['jockey', 'dnum', 'hp_v']].assign(one=1.0)
    s = wsum(src_u, ['jockey'], ['hp_v', 'one'], U[['jockey', 'dnum']], 365)
    F['h_plus'] = s[:, 0] / (s[:, 1] + 20)
    F[KEY + ['umaban']] = U[KEY + ['umaban']]
    F['course'] = U.course.to_numpy()
    F['dnum'] = dn
    F['jockey'] = U.jockey.to_numpy()
    F['trainer'] = U.trainer.to_numpy()
    F['gate'] = U.gate.to_numpy()
    F['carried_weight'] = U.carried_weight.to_numpy()
    F['year'] = U.year.to_numpy()

    # ---------- 全 NAR の走り(h)
    H = h[~h.finish_note.isin(CANCEL)].copy()
    H['dnum'] = dnum_of(H.race_date)
    H['nstart'] = H.groupby(KEY).umaban.transform('size').astype(float)
    H['fin_rel'] = np.where(H.finish.notna(), H.finish / H.nstart, 1.0)
    H = H.sort_values(['hid', 'dnum', 'race_no']).reset_index(drop=True)
    hid2 = pd.factorize(H.hid)[0].astype(np.int64)
    dn2 = H.dnum.to_numpy()
    G = H[KEY + ['umaban']].copy()
    prev_d = lagf(dn2.astype(float), hid2, 1)
    G['rest'] = dn2 - prev_d
    G['jockey_prev'] = lago(H.jockey.to_numpy(), hid2, 1)
    pfn = lago(H.finish_note.to_numpy(), hid2, 1)
    a = np.array([x == '中止' for x in pfn])
    H['one'] = 1.0
    C = h[h.finish_note.isin(CANCEL)].copy()
    C['dnum'] = dnum_of(C.race_date)
    C['one'] = 1.0
    b = wsum(C, ['hid'], ['one'], H[['hid', 'dnum']], 90)[:, 0]
    G['c_stop'] = np.where(a, 1.0, np.where(b > 0, 2.0, 0.0))
    G['g_n90'] = wsum(H, ['hid'], ['one'], H[['hid', 'dnum']], 90)[:, 0]
    idx = np.arange(len(H), dtype=float)
    rp = pd.Series(np.where(G.rest.to_numpy() >= 60, idx, np.nan))
    last = rp.groupby(hid2).ffill().to_numpy()
    kk = idx - last + 1
    G['g_nrest'] = np.where(~np.isnan(kk) & (kk <= 5), kk, 0.0)
    tr = H.trainer.fillna('').to_numpy()
    ptr = lago(tr, hid2, 1)
    pos = pd.Series(hid2).groupby(hid2).cumcount().to_numpy()
    chg = pd.Series((pos > 0) & (tr != ptr))
    tgp = chg.groupby(hid2).cumsum().to_numpy()
    stk = pd.Series(np.ones(len(H))).groupby([hid2, tgp]).cumsum().to_numpy()
    G['i_move'] = np.where(tgp == 0, 0.0, stk)
    nk = H.track.isin(NANKAN).to_numpy()
    m = pd.Series(nk.astype(int)).groupby(hid2).cumsum().to_numpy()
    ptrk = lago(H.track.to_numpy(), hid2, 1)
    first_nk = nk & (m == 1)
    jra_h = set(hid2[first_nk & (pos == 0) & (H.age.astype(float).to_numpy() >= 3)])
    nar_h = set(hid2[first_nk & (pos > 0) & np.array([x is not None and x not in NANKAN for x in ptrk])])
    in_j = np.isin(hid2, list(jra_h))
    in_n = np.isin(hid2, list(nar_h))
    G['l_jra'] = np.where(nk & in_j & (m <= 5), m, 0).astype(float)
    G['l_nar'] = np.where(nk & in_n & (m <= 5), m, 0).astype(float)
    unk = set(H.track[~nk].unique()) - set(REGION)
    assert not unk, f'知らない場: {unk}'
    V, _ = lastk(hid2, dn2, H.fin_rel.to_numpy(float), ~nk, 5, hid2, dn2)
    G['l_nfin'] = nanagg(V, np.nanmean)
    rcode = H.track.map(REGION).fillna(0).to_numpy(float)
    V1, _ = lastk(hid2, dn2, rcode, ~nk, 1, hid2, dn2)
    G['l_region'] = np.nan_to_num(V1[:, 0], nan=0.0)
    G['race_no'] = G.race_no.astype(int)

    # ---------- 作る行に集める
    T = tgt[KEY + ['umaban', 'n']].copy()
    T['race_no'] = T.race_no.astype(int)
    T = T.merge(F, on=KEY + ['umaban'], how='left', validate='1:1')
    assert T.dnum.notna().all(), '作る行が t4_base に無い'
    T = T.merge(G[KEY + ['umaban', 'rest', 'jockey_prev', 'c_stop', 'g_n90', 'g_nrest', 'i_move', 'l_jra', 'l_nar',
                     'l_nfin', 'l_region']], on=KEY + ['umaban'], how='left', validate='1:1')
    # 騎手・調教師の窓
    S = tg_src[KEY + ['umaban', 'Y1', 'Y3', 'n']].copy()
    S['race_no'] = S.race_no.astype(int)
    S = S.merge(hh[KEY + ['umaban', 'jockey', 'trainer', 'gate']], on=KEY + ['umaban'], how='left')
    S = S.merge(G[KEY + ['umaban', 'rest', 'l_jra', 'l_nar']], on=KEY + ['umaban'], how='left')
    S['dnum'] = dnum_of(S.race_date)
    S['E1'], S['E3'] = 1 / S.n, 3 / S.n
    q = T[['jockey', 'trainer', 'track', 'dnum']]
    s = wsum(S, ['jockey'], ['Y1', 'E1'], q, 365)
    T['h_j1'] = np.log((s[:, 0] + 10) / (s[:, 1] + 10))
    s = wsum(S, ['jockey'], ['Y3', 'E3'], q, 365)
    T['h_j3_own'] = np.log((s[:, 0] + 30) / (s[:, 1] + 30))
    s = wsum(S, ['jockey', 'track'], ['Y3', 'E3'], q, 365)
    T['h_jtrk'] = np.log((s[:, 0] + 30) / (s[:, 1] + 30))
    qp = pd.DataFrame({'jockey': T.jockey_prev.to_numpy(), 'dnum': T.dnum.to_numpy()})
    s = wsum(S, ['jockey'], ['Y3', 'E3'], qp, 365)
    T['h_chgdir'] = T.h_j3_own - np.log((s[:, 0] + 30) / (s[:, 1] + 30))
    s = wsum(S, ['trainer'], ['Y1', 'E1'], q, 365)
    T['i_t1'] = np.log((s[:, 0] + 10) / (s[:, 1] + 10))
    s = wsum(S[S.rest >= 60], ['trainer'], ['Y3', 'E3'], q, 1095)
    T['i_trest'] = np.log((s[:, 0] + 30) / (s[:, 1] + 30))
    s = wsum(S[(S.l_jra == 1) | (S.l_nar == 1)], ['trainer'], ['Y3', 'E3'], q, 1095)
    T['i_ttrans'] = np.log((s[:, 0] + 30) / (s[:, 1] + 30))
    # j_gatebias(コース × 枠 × 年の窓)
    S = S.merge(F[KEY + ['umaban', 'course']], on=KEY + ['umaban'], how='left')
    S['year'] = S.race_date.str[:4].astype(int)
    T['j_gatebias'] = np.nan
    for y in sorted(T.year.unique()):
        W = S[S.year.isin(win_years(y))]
        gb = W.groupby(['course', 'gate'])
        r = (gb.Y3.sum() / gb.E3.sum()).rename('gb').reset_index()
        iy = T.index[T.year == y]
        T.loc[iy, 'j_gatebias'] = T.loc[iy, ['course', 'gate']].merge(r, on=['course', 'gate'], how='left').gb.to_numpy()
    # レース内
    T['f_ten_rank'] = in_race_rank(T, 'a_tenw')
    T['f_nige_n'] = T.groupby(KEY).f_nige5.transform(lambda x: (x >= 0.4).sum()).astype(float)
    T['j_cwrel'] = T.carried_weight - T.groupby(KEY).carried_weight.transform('mean')
    return T


def assemble(T, X3):
    """T = feat_new の出力、X3 = 第 3 版の材料の表(finish_table の後)。〔v3〕の列を名前だけ変えて足す。"""
    X = X3[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop'] + list(V3MAP.values())].rename(
        columns={v: k for k, v in V3MAP.items()})
    X['race_no'] = X.race_no.astype(int)
    T = T.drop(columns=['n', 'year']).merge(X, on=KEY + ['umaban'], how='inner', validate='1:1')
    assert len(T) == len(X)
    T['h_jrank'] = in_race_rank(T, 'h_j3')
    T['j_cwrel'] = T.j_cw - T.groupby(KEY).j_cw.transform('mean')
    return T


# ================================================================ features
def features():
    runs, facts, races = raw()
    h = sources_from(runs, facts, races)
    tg = targets3(h)
    X3, _ = build3(h, tg[tg.race_date >= '2015-01-01'].reset_index(drop=True), tg)
    X3 = finish_table(X3, h, tg)
    old = pd.read_parquet(V3 / 'feat_t3_explore.parquet')
    a = X3.sort_values(KEY + ['umaban']).reset_index(drop=True)
    b = old.sort_values(KEY + ['umaban']).reset_index(drop=True)
    cols = list(V3MAP.values())
    assert a[KEY + ['umaban']].equals(b[KEY + ['umaban']])
    A, Bv = a[cols].to_numpy(float), b[cols].to_numpy(float)
    assert ((np.isnan(A) & np.isnan(Bv)) | (np.abs(A - Bv) <= 1e-9)).all(), '〔v3〕の列が feat_t3_explore と違う'
    U = pd.read_parquet(V3 / 't4_base_2014_2021.parquet')
    tgt = tg[tg.race_date >= '2015-01-01'].reset_index(drop=True)
    T = feat_new(U, h, races, tg, tgt)
    T = assemble(T, X3)
    d = (T.h_j3 - T.h_j3_own).abs()
    assert (d.fillna(0) <= 1e-9).all() and (T.h_j3.isna() == T.h_j3_own.isna()).all(), 'h_j3 の作り直しが合わない'
    T = T[META + ALL].sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    assert not BANNED & set(ALL), 'オッズ・人気・結果の列が材料に入っている'
    assert set(T.columns) - set(META) == set(ALL)
    T.to_parquet(FEAT, index=False)
    miss = T[ALL].isna().mean()
    print('rows', len(T), 'races', T[KEY].drop_duplicates().shape[0], 'years', T.year.min(), T.year.max())
    print('欠け > 0.3:', miss[miss > 0.3].round(3).to_dict())


# ================================================================ leak
def leak():
    runs, facts, races = raw()
    h = sources_from(runs, facts, races)
    tg = targets3(h)
    full = pd.read_parquet(FEAT)
    days = t4_base.pick_days(races[races.track.isin(NANKAN)])
    RES_RUN, RES_RACE = t4_base.RES_RUN, t4_base.RES_RACE
    per, tot = [], [0, 0]
    for X in days:
        r = runs[runs.race_date <= X].copy()
        mk = r.race_date == X
        r.loc[mk, RES_RUN] = np.nan
        r.loc[mk & ~r.finish_note.isin(CANCEL), 'finish_note'] = np.nan
        f = facts[facts.race_date <= X].copy()
        f.loc[f.race_date == X, FACT_RES] = np.nan
        c = races[races.race_date <= X].copy()
        c.loc[c.race_date == X, RES_RACE] = np.nan
        Um = base_from(r, f, c)
        hm = sources_from(r, f, c)
        tday = tg[tg.race_date == X].reset_index(drop=True)
        Tn = feat_new(Um, hm, c, tg[tg.race_date < X], tday)
        # 〔v3〕の列は第 3 版のリーク検査と同じやり方(前日までの走歴 + 当日の出走表)
        ent = h.loc[h.race_date == X, KEY + ['umaban', 'hid'] + ENTRY_COLS + RACE_COLS + ['body_weight']]
        Xd, _ = build3(h[h.race_date < X], tday, tg[tg.race_date < X], ent=ent)
        Xd = finish_table(Xd, ent, tg)
        T = assemble(Tn, Xd)
        a = full[full.race_date == X].set_index(KEY + ['umaban'])[PRE_ALL].sort_index()
        b = T.set_index(KEY + ['umaban'])[PRE_ALL].sort_index()
        assert a.index.equals(b.index), X
        A, Bv = a.to_numpy(float), b.to_numpy(float)
        eq = (np.isnan(A) & np.isnan(Bv)) | (np.abs(A - Bv) <= 1e-9)
        bad = [cc for cc, ok in zip(PRE_ALL, eq.all(0)) if not ok]
        per.append({'date': X, 'rows': int(len(a)), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad_cols': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        print(X, len(a), int(eq.sum()), eq.size, bad, flush=True)
    z = {'days': len(days), 'jan_days': sum(p['date'][5:7] == '01' for p in per),
         'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0], 'cells': tot[1],
         'cols': len(PRE_ALL), 'per_day': per}
    (V3 / 't4_day3_leak.json').write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding='utf-8')
    print('一致', z['match_days'], '/', z['days'], '日', tot[0], '/', tot[1])
    if tot[0] != tot[1]:
        raise SystemExit('⛔ リーク検査が 100% でない')


# ================================================================ 模型
def logit(p):
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-z))


def load4():
    df = pd.read_parquet(FEAT)
    df = df.sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    assert df.race_date.max() < '2022-01-01'
    df['z1'], df['z3'] = logit(1 / df.n), logit(3 / df.n)
    return df


def test_frame(df, years=YEARS):
    return pd.concat([df[df.year == y] for y in years])


def fit_pred(df, cols, target, cfg, tag, years=YEARS, recent=False):
    CACHE.mkdir(exist_ok=True)
    assert not BANNED & set(cols) and len(cols) == len(set(cols))
    out = []
    for y in years:
        fp = CACHE / f'{tag}_{target}_{cfg[0]}_{cfg[1]}_{cfg[2]}_{y}.npy'
        if fp.exists():
            out.append(np.load(fp)); continue
        tr = df[(df.year < y) & (df.year >= y - 3)] if recent else df[df.year < y]
        te = df[df.year == y]
        z = 'z1' if target == 'Y1' else 'z3'
        prm = dict(BASE, num_leaves=cfg[0], min_data_in_leaf=cfg[1])
        m = lgb.train(prm, lgb.Dataset(tr[cols].astype(float), label=tr[target].to_numpy(float),
                                       init_score=tr[z].to_numpy()), num_boost_round=cfg[2])
        p = sig(te[z].to_numpy() + m.predict(te[cols].astype(float), raw_score=True))
        np.save(fp, p)
        out.append(p)
        print(tag, target, cfg, y, flush=True)
    return np.concatenate(out)


def finish(te, r1, r3):
    p1 = r1 / pd.Series(r1, index=te.index).groupby([te[k] for k in KEY]).transform('sum').to_numpy()
    return p1, np.maximum(r3, p1)


def metrics(te, p1, p3):
    x = te[KEY + ['umaban', 'Y1', 'Y3', 'year']].assign(p1=np.clip(p1, 1e-6, 1 - 1e-6), p3=np.clip(p3, 1e-6, 1 - 1e-6))
    n_r = x[KEY].drop_duplicates().shape[0]
    ll1 = (x.Y1 * np.log(x.p1) + (1 - x.Y1) * np.log(1 - x.p1)).sum() / n_r
    ll3 = (x.Y3 * np.log(x.p3) + (1 - x.Y3) * np.log(1 - x.p3)).sum() / n_r
    top = x.sort_values(KEY + ['p1', 'p3', 'umaban'], ascending=[True, True, True, False, False, True],
                        kind='mergesort').groupby(KEY, sort=False).head(1)
    r = dict(LL1=float(ll1), LL3=float(ll3), win=float(top.Y1.mean()), top3=float(top.Y3.mean()), races=int(n_r))
    r.update({f'top3_{y}': float(g.Y3.mean()) for y, g in top.groupby('year')})
    r.update({f'll3_{y}': float((g.Y3 * np.log(g.p3) + (1 - g.Y3) * np.log(1 - g.p3)).sum() / g[KEY].drop_duplicates().shape[0])
              for y, g in x.groupby('year')})
    r.update({f'll1_{y}': float((g.Y1 * np.log(g.p1) + (1 - g.Y1) * np.log(1 - g.p1)).sum() / g[KEY].drop_duplicates().shape[0])
              for y, g in x.groupby('year')})
    return r


def res_load():
    return json.loads(RES.read_text(encoding='utf-8')) if RES.exists() else {}


def res_save(k, v):
    r = res_load()
    r[k] = v
    RES.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')


def stages():
    df = load4()
    te = test_frame(df)
    rows = [dict(stage=0, cols=0, **metrics(te, 1 / te.n.to_numpy(), 3 / te.n.to_numpy()))]
    kept, prev = [], rows[0]
    for s in (1, 2, 3, 4, 5):
        cols = kept + FEATS4[s]
        r1 = fit_pred(df, cols, 'Y1', STAGE_CFG, f'st{s}')
        r3 = fit_pred(df, cols, 'Y3', STAGE_CFG, f'st{s}')
        m = metrics(te, *finish(te, r1, r3))
        d3, d1 = m['LL3'] - prev['LL3'], m['LL1'] - prev['LL1']
        keep = bool(d3 > 0) if s == 1 else bool(d3 > 0 and m['top3'] >= prev['top3'] - 0.005)
        rows.append(dict(stage=s, cols=len(cols), dLL3=d3, dLL1=d1, dtop3=m['top3'] - prev['top3'], keep=keep, **m))
        print(s, len(cols), round(d3, 5), round(m['top3'], 4), keep, flush=True)
        if keep:
            kept, prev = cols, rows[-1]
    fv = te[te['pop'] == 1].drop_duplicates(KEY)
    res_save('stages', {'rows': rows, 'kept': kept, 'fav': {'win': float(fv.Y1.mean()), 'top3': float(fv.Y3.mean()),
                                                           'races': int(len(fv))}})


def grid():
    df = load4()
    te = test_frame(df)
    kept = res_load()['stages']['kept']
    assert kept, '残した段が無い'
    g1 = []
    for cfg in GRID:
        r1 = fit_pred(df, kept, 'Y1', cfg, 'grid')
        p1, _ = finish(te, r1, r1)
        g1.append((metrics(te, p1, p1)['LL1'], cfg, r1))
    best1 = max(g1, key=lambda t: t[0])
    g3 = []
    for cfg in GRID:
        r3 = fit_pred(df, kept, 'Y3', cfg, 'grid')
        g3.append((metrics(te, *finish(te, best1[2], r3))['LL3'], cfg))
    best3 = max(g3, key=lambda t: t[0])
    r3 = fit_pred(df, kept, 'Y3', best3[1], 'grid')
    m = metrics(te, *finish(te, best1[2], r3))
    res_save('grid', {'Y1': list(best1[1]), 'Y3': list(best3[1]), 'kept': kept,
                      'g1': [[ll, list(c)] for ll, c, _ in g1], 'g3': [[ll, list(c)] for ll, c in g3], 'final': m})
    (V3 / 't4_grid.json').write_text(json.dumps({'Y1': best1[1], 'Y3': best3[1], 'kept': kept}), encoding='utf-8')
    print('Y1', best1[1], 'Y3', best3[1], m['win'], m['top3'])


def final_preds(df, te, which):
    gj = res_load()['grid']
    kept, c1, c3 = gj['kept'], tuple(gj['Y1']), tuple(gj['Y3'])
    if which == 'pre':
        return finish(te, fit_pred(df, kept, 'Y1', c1, 'grid'), fit_pred(df, kept, 'Y3', c3, 'grid'))
    cols = kept + FEATS4[6]
    return finish(te, fit_pred(df, cols, 'Y1', c1, 'day'), fit_pred(df, cols, 'Y3', c3, 'day'))


def day():
    df = load4()
    te = test_frame(df)
    m = metrics(te, *final_preds(df, te, 'day'))
    res_save('day', m)
    print('当日版', m['win'], m['top3'])


def v3_frame():
    X = pd.read_parquet(V3 / 'feat_t3_explore.parquet')
    X = X.sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    assert X.race_date.max() < '2022-01-01'
    X['z1'], X['z3'] = logit(1 / X.n), logit(3 / X.n)
    return X


def v3line():
    df = load4()
    te = test_frame(df)
    X = v3_frame()
    t3_eval.check_grid()
    g = json.loads((V3 / 't3_grid.json').read_text(encoding='utf-8'))
    c1, c3 = tuple(g['Y1']), tuple(g['Y3'])
    tx = test_frame(X)
    k4 = te[KEY + ['umaban', 'n']].reset_index(drop=True)
    k3 = tx[KEY + ['umaban', 'n']].reset_index(drop=True)
    k3['race_no'] = k3.race_no.astype(int)
    assert k4.equals(k3.astype(k4.dtypes.to_dict())), '第 4 版と第 3 版の表で (場・日付・R・馬番) の組か n が一致しない'
    assert (te.Y1.to_numpy() == tx.Y1.to_numpy()).all() and (te.Y3.to_numpy() == tx.Y3.to_numpy()).all()
    out = {}
    tabs = {}
    for v, cols in (('pre', t3_eval.FEATS_PRE), ('day', t3_eval.FEATS_DAY)):
        assert len(cols) == (29 if v == 'pre' else 32)
        p1, p3 = finish(tx, fit_pred(X, cols, 'Y1', c1, f'v3{v}'), fit_pred(X, cols, 'Y3', c3, f'v3{v}'))
        out['v3' + v] = metrics(tx, p1, p3)
        tabs['v3' + v] = t3_eval.race_table(tx.assign(p1=p1, p3=p3))
        q1, q3 = final_preds(df, te, v)
        tabs['v4' + v] = t3_eval.race_table(te.assign(p1=q1, p3=q3))
    B = {}
    for k, R in tabs.items():
        s = t3_eval.summary(R)
        B[k] = {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in s.items()}
    for v in ('pre', 'day'):
        a, b = tabs['v4' + v].set_index(KEY), tabs['v3' + v].set_index(KEY)
        assert a.index.equals(b.index)
        D = a[['win', 'top3', 'll1', 'll3']] - b[['win', 'top3', 'll1', 'll3']]
        D = D.add_prefix('d_').reset_index()
        bb = t3_eval.boot(D, ['d_win', 'd_top3', 'd_ll1', 'd_ll3'])
        B['diff_' + v] = {kk: list(vv) for kk, vv in bb.items()}
    yrs = {}
    for k, R in tabs.items():
        yy = R.assign(year=R.race_date.astype(str).str[:4]).groupby('year')
        yrs[k] = {y: [float(g.win.mean()), float(g.top3.mean())] for y, g in yy}
    fvy = tabs['v4pre'].assign(year=tabs['v4pre'].race_date.astype(str).str[:4]).groupby('year').fav_top3.mean()
    yrs['fav'] = {y: [np.nan, float(v)] for y, v in fvy.items()}
    stop = [v for v in ('pre', 'day') if B['v4' + v]['top3'][0] < B['v3' + v]['top3'][0]]
    res_save('v3line', {'metrics': out, 'boot': B, 'years': yrs, 'stop': stop})
    for k in ('v4pre', 'v3pre', 'v4day', 'v3day'):
        print(k, [round(x, 4) for x in B[k]['top3']])
    print('差 前日版', [round(x, 4) for x in B['diff_pre']['d_top3']], '当日版', [round(x, 4) for x in B['diff_day']['d_top3']])
    if stop:
        print('⛔ 開ける前の止まりどころ: 第 4 版が第 3 版を下回った版 =', stop)


def recent():
    df = load4()
    yrs = [2018, 2019, 2020, 2021]
    te = test_frame(df, yrs)
    gj = res_load()['grid']
    kept, c1, c3 = gj['kept'], tuple(gj['Y1']), tuple(gj['Y3'])
    m_rec = metrics(te, *finish(te, fit_pred(df, kept, 'Y1', c1, 'rec', yrs, True),
                                fit_pred(df, kept, 'Y3', c3, 'rec', yrs, True)))
    te6 = test_frame(df)
    p1, p3 = final_preds(df, te6, 'pre')
    msk = te6.year.isin(yrs).to_numpy()
    m_exp = metrics(te6[msk], p1[msk], p3[msk])
    res_save('recent', {'recent': m_rec, 'expanding': m_exp})
    print('recent', m_rec['top3'], m_rec['LL3'], 'expanding', m_exp['top3'], m_exp['LL3'])


# ================================================================ md
def md():
    r = res_load()
    L = ['# 第 4 版 3 日目: 材料の表・リーク検査・段の採否・格子・当日版・第 3 版の線(2016〜2021 の当てはめ外)', '',
         '台本 src/t4_day3.py。材料 v3/feat_t4_explore.parquet(段 1〜6 の 96 列)。決め書 PREREG4 §4・§5・§6・§10。'
         '決め書に無い細部 15 個と番号表は台本の頭。対数尤度はレースあたり(大きいほど良い)・ΔLL は前の段(最後に残した段)との差。', '']
    lk = V3 / 't4_day3_leak.json'
    if lk.exists():
        z = json.loads(lk.read_text(encoding='utf-8'))
        L += ['## リーク検査(§10・前日版の全 93 列)', '',
              f"抜き取り {z['days']} 日(うち 1 月 {z['jan_days']} 日・seed 0)。一致 {z['match_days']}/{z['days']} 日・"
              f"{z['match']:,}/{z['cells']:,} セル = {100 * z['match'] / z['cells']:.2f} %", '']
    if 'stages' in r:
        S = r['stages']
        L += ['## 段 0〜5(設定 葉 15・最小 500・木 800・拡張窓 2016〜2021)', '',
              '| 段 | 材料の数 | ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y3 | ΔLL(Y3)| ΔLL(Y1)| ◎ 3 着以内率の差 | 年ごとの ◎ 3 着以内率 | 残す |',
              '|---|---|---|---|---|---|---|---|---|---|']
        for x in S['rows']:
            yy = '・'.join(f"{x[f'top3_{y}']:.3f}" for y in YEARS)
            L.append(f"| {x['stage']} | {x['cols']} | {x['win']:.3f} | {x['top3']:.4f} | {x['LL3']:.5f} | "
                     f"{x.get('dLL3', float('nan')):+.5f} | {x.get('dLL1', float('nan')):+.5f} | "
                     f"{x.get('dtop3', float('nan')):+.4f} | {yy} | {('○' if x['keep'] else '×') if 'keep' in x else ''} |")
        L += ['', f"残した材料 {len(S['kept'])} 列。1 番人気(記録): 勝率 {S['fav']['win']:.3f}・3 着以内率 {S['fav']['top3']:.3f}"
              f"({S['fav']['races']:,} R)", '']
    if 'grid' in r:
        g = r['grid']
        L += ['## 最終形の格子(Y1 を先に選び、その p1 で Y3 を選ぶ)', '', '| 目的 | 葉/最小/木 | 対数尤度 | 選択 |', '|---|---|---|---|']
        for ll, c in g['g1']:
            L.append(f"| Y1 | {c[0]}/{c[1]}/{c[2]} | {ll:.5f} | {'○' if c == g['Y1'] else ''} |")
        for ll, c in g['g3']:
            L.append(f"| Y3 | {c[0]}/{c[1]}/{c[2]} | {ll:.5f} | {'○' if c == g['Y3'] else ''} |")
        m = g['final']
        L += ['', f"最終形(前日版): ◎ 勝率 {m['win']:.4f}・◎ 3 着以内率 {m['top3']:.4f}・対数尤度 Y1 {m['LL1']:.5f}・Y3 {m['LL3']:.5f}", '']
    if 'day' in r:
        m = r['day']
        L += [f"当日版(最終形 + o_going・o_bw・o_bwchg・同じ設定): ◎ 勝率 {m['win']:.4f}・◎ 3 着以内率 {m['top3']:.4f}・"
              f"対数尤度 Y1 {m['LL1']:.5f}・Y3 {m['LL3']:.5f}", '']
    if 'v3line' in r:
        v = r['v3line']
        B = v['boot']
        f = lambda t, d=4: f"{t[0]:.{d}f}({t[1]:.{d}f}〜{t[2]:.{d}f})"
        L += ['## 第 3 版の線との比べ(同じレース 2016〜2021・開催日ブートストラップ 2,000 回・95% 区間)', '',
              '| 版 | ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1 | 対数尤度 Y3 | 1 番人気 3 着以内率 |', '|---|---|---|---|---|---|']
        for k, nm in (('v4pre', '第 4 版 前日版'), ('v3pre', '第 3 版 前日版(29 列)'), ('v4day', '第 4 版 当日版'),
                      ('v3day', '第 3 版 当日版(32 列)')):
            L.append(f"| {nm} | {f(B[k]['win'])} | {f(B[k]['top3'])} | {f(B[k]['ll1'])} | {f(B[k]['ll3'])} | {f(B[k]['fav_top3'])} |")
        L += ['', '| 差(第 4 版 − 第 3 版・レースごとの対)| ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1 | 対数尤度 Y3 |', '|---|---|---|---|---|']
        for vv, nm in (('pre', '前日版'), ('day', '当日版')):
            D = B['diff_' + vv]
            L.append(f"| {nm} | {f(D['d_win'])} | {f(D['d_top3'])} | {f(D['d_ll1'])} | {f(D['d_ll3'])} |")
        L += ['', '### 年ごとの ◎ 3 着以内率', '', '| 年 | 第 4 版 前日 | 第 3 版 前日 | 第 4 版 当日 | 第 3 版 当日 | 1 番人気 |',
              '|---|---|---|---|---|---|']
        for y in sorted(v['years']['v4pre']):
            L.append(f"| {y} | " + ' | '.join(f"{v['years'][k][y][1]:.3f}" for k in ('v4pre', 'v3pre', 'v4day', 'v3day', 'fav')) + ' |')
        L += ['', ('**開ける前の止まりどころ(§5)に当たった**: 第 4 版が第 3 版を下回った版 = ' + '・'.join(
            {'pre': '前日版', 'day': '当日版'}[x] for x in v['stop']) + '。4 日目の作業はしない。') if v['stop'] else
              '開ける前の止まりどころ(§5): 前日版・当日版とも第 4 版が第 3 版を下回らなかった(点推定)。', '']
    if 'recent' in r:
        a, b = r['recent']['recent'], r['recent']['expanding']
        L += ['## recent(記録だけ・判定に使わない): 最終形の前日版を直前 3 年だけで学習 vs 拡張窓(2015〜)', '',
              '| 年 | 直前 3 年 ◎ 3 着以内率 | 拡張窓 ◎ 3 着以内率 | 差 | 直前 3 年 対数尤度 Y3 | 拡張窓 対数尤度 Y3 | 直前 3 年 Y1 | 拡張窓 Y1 |',
              '|---|---|---|---|---|---|---|---|']
        for y in (2018, 2019, 2020, 2021):
            L.append(f"| {y} | {a[f'top3_{y}']:.4f} | {b[f'top3_{y}']:.4f} | {a[f'top3_{y}'] - b[f'top3_{y}']:+.4f} | "
                     f"{a[f'll3_{y}']:.5f} | {b[f'll3_{y}']:.5f} | {a[f'll1_{y}']:.5f} | {b[f'll1_{y}']:.5f} |")
        L.append(f"| 計 | {a['top3']:.4f} | {b['top3']:.4f} | {a['top3'] - b['top3']:+.4f} | {a['LL3']:.5f} | {b['LL3']:.5f} | "
                 f"{a['LL1']:.5f} | {b['LL1']:.5f} |")
        L.append('')
    (REPO / 'out/t4_day3.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    {'features': features, 'leak': leak, 'stages': stages, 'grid': grid, 'day': day, 'v3line': v3line,
     'recent': recent, 'md': md}[sys.argv[1]]()
