# -*- coding: utf-8 -*-
"""第 7 版: 新しい材料の列(分類 G・H・I・J・K・L・O の「作れる」「近い」+ 自作 3 案)。学習はしない。
2022-01-01 以降は読まない(t4_day3.raw の assert + 保存前にも assert)。既存の台本は import して呼ぶだけ。

  py -3.12 -X utf8 src/v7_feat_b.py features  # → v3/feat_v7b_explore.parquet(行の並び = feat_t6_explore)+ out/v7_feat_b.md
  py -3.12 -X utf8 src/v7_feat_b.py leak      # 漏れ検査(t4_base.pick_days の日)→ v3/v7b_leak.json + md 更新

■ 決まり
  - b7_*(前日): その日より前の結果 + 出馬表の列(ENTRY_COLS・RACE_COLS)+ 過去のレースの表の列(post_time・prize_yen は
    過去のレース / 当日の発走予定だけ)。d7_*(当日): その日の発表値(馬場状態・馬体重・天気・取消)まで。
  - 漏れ検査: b7 は t4_day3.leak と同じ空け方(RES_RUN・RES_RACE・FACT_RES を空に・取消/除外だけ残す)。
    d7 は body_weight・body_weight_change・going・weather を残して空ける。
  - 第 6 版の表から読む列(漏れ検査済み): a_ab・b_g1・g_rest・g_starts・c_top3all・l_jra・l_nar・l_debut・b_young。
  - b_g は大きいほど上の格と読む(1 が最多 = 下の格)。降級 = b_g が下がる。昇級 = 上がる。
  - 騎手・調教師の名前は NFKC(第 6 版と同じ)。log 比 = log((Σ3着以内 + k) ÷ (Σ3/頭数 + k))。
  - レース内の数・順位は出走馬(取消・除外を除く = 表の行)で数える(第 4〜6 版と同じ)。
"""
import json
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_base  # noqa: E402
import t4_day3  # noqa: E402
from t4_day3 import KEY, NANKAN, CANCEL, lagf, lago, lagm, lastk, nanagg, first_corner, in_race_rank, dnum_of, \
    win_years, base_from, FACT_RES, BANNED  # noqa: E402
from t6_base import wsum as wsum2  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
FEAT6 = V3 / 'feat_t6_explore.parquet'
OUT = V3 / 'feat_v7b_explore.parquet'
LEAKJ = V3 / 'v7b_leak.json'
MD = REPO / 'out/v7_feat_b.md'
FCOLS = ['a_ab', 'b_g1', 'g_rest', 'g_starts', 'c_top3all', 'l_jra', 'l_nar', 'l_debut', 'b_young']
TCODE = {'浦和': 1, '船橋': 2, '大井': 3, '川崎': 4}
GOING = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
WEATHER = {'晴': 0, '曇': 1, '小雨': 2, '雨': 3, '小雪': 4, '雪': 5}
T0 = time.time()

# 列名 → (番号, 一言の定義, 前日/当日)
DEFS = {
    'b7_g05_restperf': ('G05', '過去の休み明け(前走から 60 日以上)の走りの 3 着以内 − 3/頭数 の平均(全 NAR)', '前日'),
    'b7_g05_restn': ('G05', '過去の休み明けの走りの数', '前日'),
    'b7_g07_n365': ('G07', '過去 365 日の出走数(全 NAR)', '前日'),
    'b7_g16_marespring': ('G16', '牝馬 × 3〜6 月の印', '前日'),
    'b7_g17_geldn': ('G17', '牡 → セン に変わってから何走目(今回を含む・変化なしは 0)', '前日'),
    'b7_g18_gdown': ('G18', '格の見直し(b_g の変化)の直近から続く降級の回数(今回の格を含む)', '前日'),
    'd7_g14_bwtop3': ('G14', '今回の馬体重 − 過去の全期間の 3 着以内時の平均体重(第 6 版 bw_diff は 3 年)', '当日'),
    'd7_g14_bwabs': ('G14', '上の絶対値', '当日'),
    'b7_h04_jcourse': ('H04', '騎手 × コース(場・距離)の 3 年の log 比(k=30・南関)', '前日'),
    'b7_h05_jgrade': ('H05', '騎手 × 格の帯(b_g <2・<3・<4.5・<6.5・以上)の 3 年の log 比(k=30)', '前日'),
    'b7_h07_jdir': ('H07', '今回の騎手の H16 − 前走の騎手の H16(力の差)', '前日'),
    'b7_h09_jt3': ('H09', '騎手 × 調教師の 365 日の log 比(k=30・南関)', '前日'),
    'b7_h09_jtn': ('H09', '騎手 × 調教師の 365 日の騎乗数(南関)', '前日'),
    'b7_h10_jhome': ('H10', '騎手の 365 日の最多騎乗場 = 出走場', '前日'),
    'b7_h12_jaway': ('H12', '騎手の最多騎乗場が南関以外 1・365 日に NAR の騎乗なし 2・ほか 0', '前日'),
    'b7_h13_j30': ('H13', '騎手の 30 日の log 比(k=10・南関)', '前日'),
    'b7_h14_jpick': ('H14', '同じ日・場の同じ騎手の乗り鞍の中の a_ab の順位 ÷ 数(乗り鞍 1 なら 1)', '前日'),
    'b7_h14_jrides': ('H14', '同じ日・場の同じ騎手の乗り鞍の数', '前日'),
    'b7_h15_jfront': ('H15', '騎手の 365 日の騎乗の (最初の角の位置 ÷ 頭数 − 馬の直前 5 走の平均) の和 ÷ (数 + 20)', '前日'),
    'b7_h16_jplus': ('H16', '騎手の力: 3 着以内 − 3/頭数 = 馬 + 騎手 の縮めた回帰(前 3 年・南関・年ごと)の騎手の値', '前日'),
    'b7_h17_jwins': ('H17', '騎手の 365 日の勝ち数(南関)', '前日'),
    'b7_h17_lead': ('H17', 'その日・場に乗る騎手の中の勝ち数の順位(1 = 最多)', '前日'),
    'b7_i05_taway': ('I05', '調教師の所属場(365 日の最多)以外での 3 年の log 比(k=30)', '前日'),
    'b7_i06_thome': ('I06', '調教師の所属場(365 日の最多出走場: 浦和 1・船橋 2・大井 3・川崎 4・他 5)', '前日'),
    'b7_i06_tawayrun': ('I06', '出走場 ≠ 調教師の所属場', '前日'),
    'b7_i08_thorses': ('I08', '調教師の 365 日の出走馬の頭数(重複なし・全 NAR)', '前日'),
    'b7_i11_tup': ('I11', '調教師の昇級戦(b_g が上がった走り)の 3 年の log 比(k=30)', '前日'),
    'b7_i12_t30': ('I12', '調教師の 30 日の log 比(k=10・南関)', '前日'),
    'b7_j03_umabias': ('J03', 'コース(場・距離)× 馬番の前年までの窓の log 比(k=30)', '前日'),
    'b7_j05_fromout': ('J05', '出馬表の頭数(取消を含む)− 馬番', '前日'),
    'd7_j09_cwbw': ('J09', '斤量 ÷ 馬体重', '当日'),
    'd7_j12_nact': ('J12', '取消・除外を除いた頭数', '当日'),
    'b7_k04_gap2': ('K04', 'a_ab の 1 位の馬だけ 1 位 − 2 位(ほかは欠け)', '前日'),
    'b7_k05_jplusrank': ('K05', 'H16 のレース内順位', '前日'),
    'b7_k06_distsi': ('K06', '(D03)±200m の過去の南関の SI の平均', '前日'),
    'b7_k06_distsirank': ('K06', 'D03 のレース内順位', '前日'),
    'b7_k09_foe_t3': ('K09', '前走の相手(自分以外)の、前走の翌日〜前日の 3 着以内率', '前日'),
    'b7_k09_foe_n': ('K09', '上の走りの数', '前日'),
    'b7_k09_top_t3': ('K09', '前走の 3 着以内の相手だけの、その後の 3 着以内率', '前日'),
    'b7_k10_beat': ('K10', '今回の相手のうち、自分の前走で自分が先着した馬の数', '前日'),
    'b7_k10_lost': ('K10', '今回の相手のうち、自分の前走で自分に先着した馬の数', '前日'),
    'b7_k12_ntrans': ('K12', 'レース内の転入初戦(l_jra = 1 か l_nar = 1)の数', '前日'),
    'b7_k14_g1rank': ('K14', '前走の格 b_g1 のレース内順位', '前日'),
    'b7_k15_nrest': ('K15', 'レース内の休み明け(g_rest ≥ 60)の数', '前日'),
    'b7_k16_startsrank': ('K16', '出走数 g_starts のレース内順位', '前日'),
    'b7_k17_t3rank': ('K17', '3 着以内率 c_top3all のレース内順位', '前日'),
    'b7_l03_debutyoung': ('L03', '初出走 × 若馬戦(b_young > 0)', '前日'),
    'b7_l03_ndebut': ('L03', 'レース内の初出走の数', '前日'),
    'b7_l09_othlv_max': ('L09', '直近 5 走の他地区の走りのレースの格(log 1 着賞金 − その場の 365 日平均)の最大', '前日'),
    'b7_l09_othlv_mean': ('L09', '同じく平均', '前日'),
    'b7_l11_othdays': ('L11', '最後の他地区(南関以外)の走りからの日数', '前日'),
    'b7_l12_return': ('L12', '出戻り(南関 → 他地区 → 今回南関)の初戦', '前日'),
    'b7_l13_career': ('L13', '最初の出走(2014〜)からの日数', '前日'),
    'b7_l14_homechg': ('L14', '今回の調教師の所属場 ≠ 前走の調教師の所属場(前走の日で)', '前日'),
    'd7_o03_weather': ('O03', '天気(晴 0・曇 1・小雨 2・雨 3・小雪 4・雪 5)', '当日'),
    'd7_o06_ncxl': ('O06', 'レースの取消・除外の数', '当日'),
    'd7_o06_nigecxl': ('O06', '取消・除外の馬のうち逃げ型(直前 5 走の 1 番手率 ≥ 0.4)の数', '当日'),
    'b7_o07_post': ('O07', '発走時刻(分)', '前日'),
    'b7_o07_last': ('O07', 'その日の最終レース', '前日'),
    'd7_o11_goingchg': ('O11', '今回の馬場状態 − 前の開催日の最終レースの馬場状態(良 0〜不良 3)', '当日'),
    'b7_self_chosen': ('自作 A', '今回の騎手が、同じレースの別の馬の直近 3 走で乗っていた馬の数(選ばれた)', '前日'),
    'b7_self_dropped': ('自作 A', '前走の騎手が今回同じレースの別の馬に乗る(捨てられた)', '前日'),
    'b7_self_trmain': ('自作 F', '今回の騎手 = 調教師の主戦(365 日の組数が最多)', '前日'),
    'b7_self_trday_n': ('自作 F', '同じ日・場の同じ調教師の出馬表の頭数(取消を含む)', '前日'),
    'b7_self_trday_main': ('自作 F', 'そのうち主戦が乗る頭数', '前日'),
    'b7_self_kan_lr': ('自作 G', '冠名(頭 2〜4 文字・前年までに 50 頭以上)の集団の前年までの log 比(k=30)', '前日'),
    'b7_self_kan_n': ('自作 G', '冠名の集団の頭数', '前日'),
}
SKIP = {'O02': '同じ日の先のレースのタイムを使う(決まり: その日のタイムは使わない)',
        'O04': '同じ日の先のレースの着順を使う(決まり: その日の着順は使わない)'}
COLS = list(DEFS)
assert all(c.startswith(('b7_', 'd7_')) for c in COLS)


def log(*a):
    print(f'[{time.time() - T0:7.1f}s]', *a, flush=True)


def lr(s, k):
    return np.log((s[:, 0] + k) / (s[:, 1] + k))


def skey(d, cols):
    return t4_day3._key(d, cols).to_numpy(object)


def W(st, key, mask, vals, lo, hi, qkey=None, qdn=None):
    """st の行(mask)を出来事、key ごとに [qdn − lo, qdn − hi] の vals の和。問いの key が欠けなら NaN。"""
    key = np.asarray(key, dtype=object)
    m = np.asarray(mask, bool) & pd.notna(key)
    V = np.column_stack([np.asarray(v, float) for v in vals])
    qk = key if qkey is None else np.asarray(qkey, dtype=object)
    qd = st.dn.to_numpy() if qdn is None else np.asarray(qdn)
    out = wsum2(key[m], st.dn.to_numpy()[m], V[m], qk, qd, lo, hi).astype(float)
    out[pd.isna(qk)] = np.nan
    return out


# ================================================================ 読み込み
def prep(runs, facts, races):
    h = t4_day3.sources_from(runs, facts, races)
    for c in ('jockey', 'trainer'):
        h[c] = h[c].map(lambda x: unicodedata.normalize('NFKC', x) if isinstance(x, str) else x)
    h = h[h.race_date >= '2014-01-01'].drop_duplicates(KEY + ['umaban']).reset_index(drop=True)
    rc = races[KEY + ['post_time', 'weather']].copy()
    rc['race_no'] = rc.race_no.astype(int)
    h = h.merge(rc.drop_duplicates(KEY), on=KEY, how='left')
    h['dn'] = dnum_of(h.race_date)
    h['cxl'] = h.finish_note.isin(CANCEL)
    h['nent'] = h.groupby(KEY).umaban.transform('size').astype(float)
    st = h[~h.cxl].copy()
    st = st.sort_values(['hid', 'dn', 'race_no'], kind='mergesort').reset_index(drop=True)
    st['hi'] = pd.factorize(st.hid)[0].astype(np.int64)
    st['rid'] = st.groupby(KEY, sort=True).ngroup().astype(float)
    st['nst'] = st.groupby(KEY).umaban.transform('size').astype(float)
    st['top3'] = (st.finish <= 3).astype(float)
    st['win1'] = (st.finish == 1).astype(float)
    st['E3'] = 3 / st.nst
    st['fin'] = st.finish.where(st.finish.notna(), st.nst).astype(float)
    st['nk'] = st.track.isin(NANKAN)
    st['tc'] = st.track.map(TCODE).fillna(5).astype(float)
    st['year'] = st.race_date.str[:4].astype(int)
    return h, st


def load_F(day):
    F = pd.read_parquet(FEAT6, columns=KEY + ['umaban', 'year', 'Y3'] + FCOLS)
    F['race_no'] = F.race_no.astype(int)
    if day is not None:
        F = F[F.race_date == day]
    return F.reset_index(drop=True)


def ubase(runs, facts, races):
    U = base_from(runs, facts, races).rename(columns={'runner_number': 'umaban'})
    U['umaban'] = U.umaban.astype(int)
    U['race_no'] = U.race_no.astype(int)
    U = U[~U.finish_note.isin(CANCEL)][KEY + ['umaban', 'hk', 'b_g', 'SI', 'distance_m']].copy()
    U['dn'] = dnum_of(U.race_date)
    U = U.sort_values(['hk', 'dn', 'race_no'], kind='mergesort').reset_index(drop=True)
    Ub = U[U.b_g.notna()].copy()
    d = Ub.groupby('hk').b_g.diff()
    Ub['bchg'] = d
    nz = (d.notna() & (d != 0)).to_numpy()
    Z = Ub[nz]
    zneg = (d[nz] < 0).astype(int)
    grp = (1 - zneg).groupby(Z.hk.to_numpy()).cumsum()
    streak = zneg.groupby([Z.hk.to_numpy(), grp.to_numpy()]).cumsum()
    Ub['gdown'] = np.nan
    Ub.loc[nz, 'gdown'] = streak.to_numpy().astype(float)
    Ub['gdown'] = Ub.groupby('hk').gdown.ffill().fillna(0.0)
    U = U.merge(Ub[KEY + ['umaban', 'bchg', 'gdown']], on=KEY + ['umaban'], how='left', validate='1:1')
    return U


# ================================================================ 走りの表の列(全行・過去だけ)
def st_cols(st, races, parts, U):
    dn = st.dn.to_numpy()
    hi = st.hi.to_numpy()
    nk = st.nk.to_numpy()
    one = np.ones(len(st))
    top3, E3 = st.top3.to_numpy(), st.E3.to_numpy()
    tc = st.tc.to_numpy()
    st['pdn'] = lagf(dn.astype(float), hi, 1)
    st['prid'] = lagf(st.rid.to_numpy(), hi, 1)
    st['pfin'] = lagf(st.fin.to_numpy(), hi, 1)
    jk = st.jockey.to_numpy(object)
    for j in (1, 2, 3):
        st[f'pj{j}'] = lago(jk, hi, j)
    fpos, fn = first_corner(st)
    st['fc'] = fpos / fn
    st['nige'] = np.where(np.isnan(fpos), np.nan, (fpos == 1).astype(float))
    if 'd' in parts:
        bw = st.body_weight.astype(float).to_numpy()
        v = (top3 == 1) & ~np.isnan(bw)
        cs = pd.Series(np.where(v, bw, 0.0)).groupby(hi).cumsum().to_numpy() - np.where(v, bw, 0.0)
        cn = pd.Series(v.astype(float)).groupby(hi).cumsum().to_numpy() - v
        st['d7_g14_bwtop3'] = bw - np.where(cn > 0, cs / np.where(cn > 0, cn, 1), np.nan)
        st['d7_g14_bwabs'] = np.abs(st.d7_g14_bwtop3)
        st['d7_j09_cwbw'] = st.carried_weight.astype(float) / bw
        st['d7_j12_nact'] = st.nst
    if 'b' not in parts:
        return st
    # G
    rest = dn - st.pdn.to_numpy()
    ev = rest >= 60
    v = np.where(ev, top3 - E3, 0.0)
    cv = pd.Series(v).groupby(hi).cumsum().to_numpy() - v
    cn = pd.Series(ev.astype(float)).groupby(hi).cumsum().to_numpy() - ev
    st['b7_g05_restperf'] = np.where(cn > 0, cv / np.where(cn > 0, cn, 1), np.nan)
    st['b7_g05_restn'] = cn
    st['b7_g07_n365'] = W(st, st.hid, one > 0, [one], 365, 1)[:, 0]
    mon = st.race_date.str[5:7].astype(int)
    st['b7_g16_marespring'] = ((st.sex == '牝') & mon.between(3, 6)).astype(float)
    sx = st.sex.to_numpy(object)
    psx = lago(sx, hi, 1)
    chg = (sx == 'セン') & (psx == '牡')
    grp = pd.Series(chg.astype(int)).groupby(hi).cumsum().to_numpy()
    cnt = pd.Series(one).groupby([hi, grp]).cumsum().to_numpy()
    st['b7_g17_geldn'] = np.where((grp > 0) & (sx == 'セン'), cnt, 0.0)
    # U(南関の格)
    st2 = st[KEY + ['umaban']].merge(U[KEY + ['umaban', 'b_g', 'bchg', 'gdown']], on=KEY + ['umaban'], how='left',
                                     validate='1:1')
    st['bg'] = st2.b_g.to_numpy(float)
    st['bchg'] = st2.bchg.to_numpy(float)
    st['b7_g18_gdown'] = np.where(np.isnan(st.bg), np.nan, st2.gdown.to_numpy(float))
    # H・I の窓
    kj = skey(st, ['jockey'])
    kt = skey(st, ['trainer'])
    st['course'] = skey(st, ['track', 'distance_m'])
    kjc = skey(st, ['jockey', 'course'])
    st['b7_h04_jcourse'] = lr(W(st, kjc, nk, [top3, E3], 1095, 1), 30)
    band = np.digitize(st.bg.to_numpy(), [2, 3, 4.5, 6.5]).astype(float)
    band[np.isnan(st.bg.to_numpy())] = np.nan
    st['band'] = band
    st['b7_h05_jgrade'] = lr(W(st, skey(st, ['jockey', 'band']), nk, [top3, E3], 1095, 1), 30)
    s = W(st, skey(st, ['jockey', 'trainer']), nk, [top3, E3, one], 365, 1)
    st['b7_h09_jt3'] = lr(s, 30)
    st['b7_h09_jtn'] = s[:, 2]
    st['b7_h13_j30'] = lr(W(st, kj, nk, [top3, E3], 30, 1), 10)
    st['b7_i12_t30'] = lr(W(st, kt, nk, [top3, E3], 30, 1), 10)
    st['b7_i11_tup'] = lr(W(st, kt, nk & (st.bchg.to_numpy() > 0), [top3, E3], 1095, 1), 30)
    st['b7_h17_jwins'] = W(st, kj, nk, [st.win1.to_numpy()], 365, 1)[:, 0]
    hm = nanagg(lagm(st.fc.to_numpy(float), hi, 5), np.nanmean)
    fv = st.fc.to_numpy(float) - hm
    s = W(st, kj, ~np.isnan(fv), [np.nan_to_num(fv), one], 365, 1)
    st['b7_h15_jfront'] = s[:, 0] / (s[:, 1] + 20)

    def home(key):
        M = np.column_stack([W(st, key, tc == b, [one], 365, 1)[:, 0] for b in (1, 2, 3, 4, 5)])
        tot = np.nansum(M, 1)
        return np.where(tot > 0, np.nanargmax(np.nan_to_num(M), 1) + 1.0, np.nan)
    jh = home(kj)
    th = home(kt)
    st['b7_h10_jhome'] = np.where(np.isnan(jh), np.nan, (jh == tc).astype(float))
    st['b7_h12_jaway'] = np.where(np.isnan(jh), 2.0, (jh == 5).astype(float))
    st['b7_h12_jaway'] = np.where(pd.isna(kj), np.nan, st.b7_h12_jaway)
    st['b7_i06_thome'] = th
    st['b7_i06_tawayrun'] = np.where(np.isnan(th), np.nan, (th != tc).astype(float))
    st['b7_i05_taway'] = lr(W(st, kt, nk & ~np.isnan(th) & (th != tc), [top3, E3], 1095, 1), 30)
    pth = lagf(th, hi, 1)
    st['b7_l14_homechg'] = np.where(np.isnan(pth) | np.isnan(th), np.nan, (pth != th).astype(float))
    # I08(重複なしの頭数: 組の各走りは (t, min(次の走り, t + 365)] の日に数える)
    P = pd.DataFrame({'pk': skey(st, ['trainer', 'hid']), 'tr': kt, 'dn': dn}).dropna(subset=['pk'])
    P = P.sort_values(['pk', 'dn'], kind='mergesort')
    nxt = P.groupby('pk').dn.shift(-1).to_numpy()
    mend = np.minimum(np.where(np.isnan(nxt), 1e9, nxt), P.dn.to_numpy() + 365).astype(np.int64)
    ek = np.r_[P.tr.to_numpy(object), P.tr.to_numpy(object)]
    ed = np.r_[P.dn.to_numpy(np.int64), mend]
    evv = np.r_[np.ones(len(P)), -np.ones(len(P))]
    s = wsum2(ek, ed, evv, kt, dn, dn, 1)[:, 0].astype(float)
    s[pd.isna(kt)] = np.nan
    st['b7_i08_thorses'] = s
    # L
    V1, _ = lastk(hi, dn, dn.astype(float), ~nk, 1, hi, dn)
    st['b7_l11_othdays'] = dn - V1[:, 0]
    pnk = lagf(nk.astype(float), hi, 1)
    nkc = pd.Series(nk.astype(float)).groupby(hi).cumsum().to_numpy() - nk
    st['b7_l12_return'] = ((pnk == 0) & (nkc > 0) & nk).astype(float)
    st['b7_l13_career'] = dn - st.groupby('hi').dn.transform('min').to_numpy()
    rr = races[KEY + ['prize_yen']].drop_duplicates(KEY).copy()
    rr['race_no'] = rr.race_no.astype(int)
    rr['p1'] = pd.to_numeric(rr.prize_yen.astype(str).str.extract(r'\[\s*(\d+)')[0], errors='coerce')
    rr = rr[rr.p1 > 0].copy()
    rr['lp'] = np.log(rr.p1)
    rr['dn'] = dnum_of(rr.race_date)
    s = wsum2(rr.track.to_numpy(object), rr.dn.to_numpy(), np.c_[rr.lp.to_numpy(), np.ones(len(rr))],
              rr.track.to_numpy(object), rr.dn.to_numpy(), 365, 1)
    rr['rel'] = np.where(s[:, 1] > 0, rr.lp - s[:, 0] / np.maximum(s[:, 1], 1), np.nan)
    rel = st[KEY].merge(rr[KEY + ['rel']], on=KEY, how='left').rel.to_numpy(float)
    V5, _ = lastk(hi, dn, rel, (~nk) & ~np.isnan(rel), 5, hi, dn)
    st['b7_l09_othlv_max'] = nanagg(V5, np.nanmax)
    st['b7_l09_othlv_mean'] = nanagg(V5, np.nanmean)
    return st


# ================================================================ 作る
def als(E, lam_h=5.0, lam_j=20.0, it=30):
    hc = pd.factorize(E.hid)[0]
    jc, ju = pd.factorize(E.jockey)
    y = (E.top3 - E.E3).to_numpy()
    nh, nj = np.bincount(hc), np.bincount(jc)
    a, b = np.zeros(len(nh)), np.zeros(len(nj))
    for _ in range(it):
        a = np.bincount(hc, y - b[jc], len(nh)) / (nh + lam_h)
        b = np.bincount(jc, y - a[hc], len(nj)) / (nj + lam_j)
    return pd.Series(b, index=ju)


def build(runs, facts, races, day=None, parts=('b', 'd')):
    t0 = time.time()
    races = races.copy()
    races['race_no'] = races.race_no.astype(int)
    h, st = prep(runs, facts, races)
    U = ubase(runs, facts, races) if 'b' in parts else None
    st = st_cols(st, races, parts, U)
    F = load_F(day)
    m = F[KEY + ['umaban']].merge(st[KEY + ['umaban']].assign(si=np.arange(len(st))), on=KEY + ['umaban'],
                                  how='left', validate='1:1')
    ok = m.si.notna().to_numpy()
    Q = st.iloc[m.si.fillna(0).astype(int).to_numpy()].reset_index(drop=True)
    Q.loc[~ok] = np.nan
    T = F.copy()
    out = pd.DataFrame(index=T.index)
    for c in COLS:
        if c in Q.columns:
            out[c] = Q[c].to_numpy(float)
    n = len(T)
    ti = np.arange(n)

    if 'd' in parts:
        T['cur_going'] = Q.going.map(GOING).to_numpy(float)
        out['d7_o03_weather'] = Q.weather.map(WEATHER).to_numpy(float)
        # O06
        cx = h[h.cxl & h.track.isin(NANKAN)].copy()
        hmap = pd.Series(st.hi.to_numpy(), index=st.hid.to_numpy())
        hmap = hmap[~hmap.index.duplicated()]
        qh = cx.hid.map(hmap).fillna(st.hi.max() + 1).astype(np.int64).to_numpy()
        ng = st.nige.to_numpy(float)
        V, _ = lastk(st.hi.to_numpy(), st.dn.to_numpy(), ng, st.nk.to_numpy() & ~np.isnan(ng), 5, qh,
                     cx.dn.to_numpy())
        cx['n5'] = nanagg(V, np.nanmean)
        cx['nig'] = (cx.n5 >= 0.4).astype(float)
        g = cx.groupby(KEY).agg(ncxl=('cxl', 'size'), nigecxl=('nig', 'sum')).reset_index()
        r = T[KEY].merge(g, on=KEY, how='left')
        out['d7_o06_ncxl'] = r.ncxl.fillna(0).to_numpy(float)
        out['d7_o06_nigecxl'] = r.nigecxl.fillna(0).to_numpy(float)
        # O11
        rg = races[races.track.isin(NANKAN)][KEY + ['going']].copy()
        rg['gc'] = rg.going.map(GOING)
        rg = rg.dropna(subset=['gc']).sort_values(['track', 'race_date', 'race_no'])
        lastg = rg.groupby(['track', 'race_date']).gc.last().reset_index().sort_values(['track', 'race_date'])
        lastg['prevg'] = lastg.groupby('track').gc.shift(1)
        r = T[['track', 'race_date']].merge(lastg[['track', 'race_date', 'prevg']], on=['track', 'race_date'],
                                            how='left')
        out['d7_o11_goingchg'] = T.cur_going.to_numpy() - r.prevg.to_numpy(float)

    if 'b' in parts:
        for c in ['hid', 'jockey', 'trainer', 'rid', 'prid', 'pdn', 'pfin', 'pj1', 'pj2', 'pj3', 'dn', 'nent',
                  'horse_name']:
            T['q_' + c] = Q[c].to_numpy()
        T['q_dn'] = T.q_dn.astype(float)
        # H16・H07・K05
        jp = np.full(n, np.nan)
        jpp = np.full(n, np.nan)
        E0 = st[st.nk & st.jockey.notna()]
        for y in sorted(T.year.unique()):
            E = E0[E0.year.isin(win_years(int(y)))]
            b = als(E)
            iy = (T.year == y).to_numpy()
            jp[iy] = T.q_jockey[iy].map(b).to_numpy(float)
            jpp[iy] = T.q_pj1[iy].map(b).to_numpy(float)
        out['b7_h16_jplus'] = jp
        out['b7_h07_jdir'] = jp - jpp
        T['jp'] = jp
        out['b7_k05_jplusrank'] = in_race_rank(T, 'jp')
        # H14
        g = T.groupby(['track', 'race_date', 'q_jockey'])
        out['b7_h14_jrides'] = g.a_ab.transform('size').to_numpy(float)
        out['b7_h14_jpick'] = (g.a_ab.rank(ascending=False, method='average') / g.a_ab.transform('count')).to_numpy()
        out.loc[T.q_jockey.isna().to_numpy(), ['b7_h14_jrides', 'b7_h14_jpick']] = np.nan
        # H17 順位
        T['jw'] = out.b7_h17_jwins.to_numpy()
        D = T[['track', 'race_date', 'q_jockey', 'jw']].dropna(subset=['q_jockey']).drop_duplicates(
            ['track', 'race_date', 'q_jockey'])
        D['lead'] = D.groupby(['track', 'race_date']).jw.rank(ascending=False, method='min')
        out['b7_h17_lead'] = T[['track', 'race_date', 'q_jockey']].merge(
            D[['track', 'race_date', 'q_jockey', 'lead']], on=['track', 'race_date', 'q_jockey'], how='left').lead.to_numpy()
        # J03
        T['course_um'] = skey(Q.assign(umaban=T.umaban), ['track', 'distance_m', 'umaban'])
        sk = skey(st, ['track', 'distance_m', 'umaban'])
        jb = np.full(n, np.nan)
        for y in sorted(T.year.unique()):
            mm = st.nk.to_numpy() & st.year.isin(win_years(int(y))).to_numpy()
            gg = pd.DataFrame({'k': sk[mm], 'y3': st.top3.to_numpy()[mm], 'e3': st.E3.to_numpy()[mm]}).groupby('k').sum()
            r = np.log((gg.y3 + 30) / (gg.e3 + 30))
            iy = (T.year == y).to_numpy()
            jb[iy] = pd.Series(T.course_um.to_numpy()[iy]).map(r).to_numpy(float)
        out['b7_j03_umabias'] = jb
        out['b7_j05_fromout'] = T.q_nent.astype(float) - T.umaban
        # K04
        g = T.groupby(KEY).a_ab
        mx = g.transform('max')
        sec = g.transform(lambda s: s.nlargest(2).iloc[-1] if s.notna().sum() >= 2 else np.nan)
        top = g.rank(ascending=False, method='first') == 1
        out['b7_k04_gap2'] = np.where(top, mx - sec, np.nan)
        # K06(D03)
        Tq = pd.DataFrame({'ti': ti}).assign(**{k: T[k] for k in KEY + ['umaban']}).merge(
            U[KEY + ['umaban', 'hk', 'dn', 'distance_m']], on=KEY + ['umaban'], how='left')
        Tq = Tq.dropna(subset=['hk'])
        Up = U[U.SI.notna()][['hk', 'dn', 'distance_m', 'SI']]
        d03 = np.full(n, np.nan)
        for ch in np.array_split(Tq.hk.unique(), 20):
            a = Tq[Tq.hk.isin(ch)].merge(Up[Up.hk.isin(ch)], on='hk', suffixes=('', '_p'))
            a = a[(a.dn_p < a.dn) & ((a.distance_m_p.astype(float) - a.distance_m.astype(float)).abs() <= 200)]
            r = a.groupby('ti').SI.mean()
            d03[r.index.to_numpy()] = r.to_numpy()
        out['b7_k06_distsi'] = d03
        T['d03'] = d03
        out['b7_k06_distsirank'] = in_race_rank(T, 'd03')
        # K09
        Pq = pd.DataFrame({'ti': ti, 'hid': T.q_hid, 'dn': T.q_dn, 'prid': T.q_prid, 'pdn': T.q_pdn}).dropna(
            subset=['prid', 'hid'])
        fo = st[['rid', 'hid', 'finish']].rename(columns={'rid': 'prid', 'hid': 'fh'})
        P = Pq.merge(fo, on='prid')
        P = P[P.fh != P.hid]
        s = wsum2(st.hid.to_numpy(object), st.dn.to_numpy(), np.c_[st.top3.to_numpy(), np.ones(len(st))],
                  P.fh.to_numpy(object), P.dn.to_numpy().astype(np.int64),
                  (P.dn - P.pdn - 1).to_numpy().astype(np.int64), 1)
        P['s0'], P['s1'] = s[:, 0], s[:, 1]
        P['ft'] = (P.finish <= 3)
        ga = P.groupby('ti')[['s0', 's1']].sum()
        gt = P[P.ft].groupby('ti')[['s0', 's1']].sum()
        a0 = np.full(n, np.nan)
        a1 = np.full(n, np.nan)
        a0[ga.index] = ga.s0
        a1[ga.index] = ga.s1
        out['b7_k09_foe_t3'] = np.where(a1 > 0, a0 / np.where(a1 > 0, a1, 1), np.nan)
        out['b7_k09_foe_n'] = a1
        b0 = np.full(n, np.nan)
        b1 = np.full(n, np.nan)
        b0[gt.index] = gt.s0
        b1[gt.index] = gt.s1
        out['b7_k09_top_t3'] = np.where(b1 > 0, b0 / np.where(b1 > 0, b1, 1), np.nan)
        # K10・自作 A(レース内の組)
        R = pd.DataFrame({'ti': ti, 'rid': T.q_rid, 'hid': T.q_hid, 'prid': T.q_prid, 'pfin': T.q_pfin,
                          'jk': T.q_jockey, 'pj1': T.q_pj1, 'pj2': T.q_pj2, 'pj3': T.q_pj3}).dropna(subset=['rid'])
        PR = R.merge(R[['rid', 'hid', 'jk', 'pj1', 'pj2', 'pj3']].rename(
            columns={'hid': 'oh', 'jk': 'ojk', 'pj1': 'o1', 'pj2': 'o2', 'pj3': 'o3'}), on='rid')
        PR = PR[PR.oh != PR.hid]
        X = PR.dropna(subset=['prid']).merge(st[['hid', 'rid', 'fin']].rename(
            columns={'hid': 'oh', 'rid': 'prid', 'fin': 'ofin'}), on=['oh', 'prid'])
        X['beat'] = (X.pfin < X.ofin).astype(float)
        X['lost'] = (X.pfin > X.ofin).astype(float)
        gx = X.groupby('ti')[['beat', 'lost']].sum()
        has = T.q_prid.notna().to_numpy()
        for c in ('beat', 'lost'):
            v = np.where(has, 0.0, np.nan)
            v[gx.index] = gx[c]
            out['b7_k10_' + c] = v
        chs = PR.jk.notna() & ((PR.jk == PR.o1) | (PR.jk == PR.o2) | (PR.jk == PR.o3))
        drp = PR.pj1.notna() & (PR.pj1 == PR.ojk)
        cs_ = PR.assign(c=chs.astype(float), d=drp.astype(float)).groupby('ti')[['c', 'd']].agg({'c': 'sum', 'd': 'max'})
        vc = np.zeros(n)
        vd = np.zeros(n)
        vc[cs_.index] = cs_.c
        vd[cs_.index] = cs_.d
        out['b7_self_chosen'] = np.where(T.q_rid.notna(), vc, np.nan)
        out['b7_self_dropped'] = np.where(T.q_rid.notna(), vd, np.nan)
        # K・L のレース内
        g = T.groupby(KEY)
        out['b7_k12_ntrans'] = ((T.l_jra == 1) | (T.l_nar == 1)).astype(float).groupby(
            [T[k] for k in KEY]).transform('sum').to_numpy()
        out['b7_k14_g1rank'] = in_race_rank(T, 'b_g1')
        out['b7_k15_nrest'] = (T.g_rest >= 60).astype(float).groupby([T[k] for k in KEY]).transform('sum').to_numpy()
        out['b7_k16_startsrank'] = in_race_rank(T, 'g_starts')
        out['b7_k17_t3rank'] = in_race_rank(T, 'c_top3all')
        out['b7_l03_debutyoung'] = (T.l_debut * (T.b_young > 0)).astype(float).to_numpy()
        out['b7_l03_ndebut'] = T.l_debut.groupby([T[k] for k in KEY]).transform('sum').to_numpy(float)
        # O07
        rc = races[races.track.isin(NANKAN)][KEY + ['post_time']].drop_duplicates(KEY).copy()
        pt = pd.to_numeric(rc.post_time, errors='coerce')
        rc['post'] = (pt // 100) * 60 + pt % 100
        rc['last'] = (rc.race_no == rc.groupby(['track', 'race_date']).race_no.transform('max')).astype(float)
        r = T[KEY].merge(rc[KEY + ['post', 'last']], on=KEY, how='left')
        out['b7_o07_post'] = r.post.to_numpy(float)
        out['b7_o07_last'] = r['last'].to_numpy(float)
        # 自作 F(調教師の主戦)
        E = st[st.trainer.notna() & st.jockey.notna()]
        pair = E.groupby(['trainer', 'jockey']).dn.agg(['min', 'max']).reset_index()
        ent = h[h.track.isin(NANKAN) & (h.race_date >= '2015-01-01') & h.trainer.notna()].copy()
        if day is not None:
            ent = ent[ent.race_date == day]
        qs = ent[['trainer', 'dn']].drop_duplicates()
        ekp = skey(E, ['trainer', 'jockey'])
        mxs = []
        for ch in np.array_split(qs.trainer.unique(), 20):
            C = qs[qs.trainer.isin(ch)].merge(pair[pair.trainer.isin(ch)], on='trainer')
            C = C[(C['min'] < C.dn) & (C['max'] >= C.dn - 365)]
            if len(C) == 0:
                continue
            C['c'] = wsum2(ekp, E.dn.to_numpy(), np.ones(len(E)), skey(C, ['trainer', 'jockey']), C.dn.to_numpy(),
                           365, 1)[:, 0]
            mxs.append(C.groupby(['trainer', 'dn']).c.max())
        mx = (pd.concat(mxs).rename('mx').reset_index() if mxs
              else pd.DataFrame({'trainer': pd.Series(dtype=object), 'dn': pd.Series(dtype=np.int64), 'mx': []}))
        ent = ent.merge(mx, on=['trainer', 'dn'], how='left')
        ent['mine'] = wsum2(ekp, E.dn.to_numpy(), np.ones(len(E)), skey(ent, ['trainer', 'jockey']),
                            ent.dn.to_numpy(), 365, 1)[:, 0]
        ent['main'] = ((ent.mx > 0) & (ent.mine == ent.mx)).astype(float)
        gg = ent.groupby(['track', 'race_date', 'trainer'])
        ent['dn_n'] = gg.umaban.transform('size').astype(float)
        ent['dn_main'] = gg.main.transform('sum')
        r = T[KEY + ['umaban']].merge(ent[KEY + ['umaban', 'main', 'dn_n', 'dn_main']], on=KEY + ['umaban'],
                                      how='left', validate='1:1')
        nt = T.q_trainer.isna().to_numpy()
        out['b7_self_trmain'] = np.where(nt, np.nan, r.main.to_numpy(float))
        out['b7_self_trday_n'] = np.where(nt, np.nan, r.dn_n.to_numpy(float))
        out['b7_self_trday_main'] = np.where(nt, np.nan, r.dn_main.to_numpy(float))
        # 自作 G(冠名)
        hs = st.groupby('hid', sort=False).agg(first=('dn', 'min'), name=('horse_name', 'first'))
        klr = np.full(n, np.nan)
        kn = np.full(n, np.nan)
        for y in sorted(T.year.unique()):
            y0 = dnum_of(pd.Series([f'{int(y)}-01-01']))[0]
            names = hs[hs['first'] < y0].name.dropna().astype(str)
            valid = {}
            for L in (4, 3, 2):
                p = names[names.str.len() > L].str[:L]
                vc_ = p.value_counts()
                valid[L] = vc_[vc_ >= 50]

            def grp_of(s):
                s = pd.Series(s).astype(object)
                outg = pd.Series(np.nan, index=s.index, dtype=object)
                ss = s.fillna('').astype(str)
                for L in (4, 3, 2):
                    p = ss.str[:L]
                    mk = outg.isna() & (ss.str.len() > L) & p.isin(valid[L].index)
                    outg[mk] = p[mk]
                return outg
            allv = pd.concat([valid[L] for L in (4, 3, 2)])
            mm = st.nk.to_numpy() & (st.year < y).to_numpy()
            ev_name = st.hid[mm].map(hs.name)
            gser = grp_of(ev_name.to_numpy())
            gs = pd.DataFrame({'g': gser.to_numpy(), 'y3': st.top3.to_numpy()[mm], 'e3': st.E3.to_numpy()[mm]}).dropna(
                subset=['g']).groupby('g').sum()
            rr = np.log((gs.y3 + 30) / (gs.e3 + 30))
            iy = (T.year == y).to_numpy()
            tg = grp_of(T.q_horse_name.to_numpy()[iy])
            klr[iy] = tg.map(rr).to_numpy(float)
            kn[iy] = tg.map(allv).to_numpy(float)
        out['b7_self_kan_lr'] = klr
        out['b7_self_kan_n'] = kn

    want = [c for c in COLS if (c.startswith('b7_') and 'b' in parts) or (c.startswith('d7_') and 'd' in parts)]
    miss = [c for c in want if c not in out.columns]
    assert not miss, miss
    res = pd.concat([T[KEY + ['umaban']], out[want]], axis=1)
    log('build', day, parts, res.shape, f'{time.time() - t0:.0f}s', 'st 無し', int((~ok).sum()))
    return res


# ================================================================ features・leak・md
def features():
    runs, facts, races = t4_day3.raw()
    R = build(runs, facts, races)
    F6 = pd.read_parquet(FEAT6, columns=KEY + ['umaban'])
    F6['race_no'] = F6.race_no.astype(int)
    assert len(R) == len(F6) and R[KEY + ['umaban']].reset_index(drop=True).equals(F6.reset_index(drop=True))
    assert R.race_date.max() < '2022-01-01'
    assert not BANNED & set(R.columns)
    R.to_parquet(OUT, index=False)
    log('保存', OUT, R.shape)
    md()


def leak():
    runs, facts, races = t4_day3.raw()
    full = pd.read_parquet(OUT)
    days = t4_base.pick_days(races[races.track.isin(NANKAN)])
    per, tot = [], [0, 0]
    for X in days:
        for part in ('b', 'd'):
            keep_r = [] if part == 'b' else ['body_weight', 'body_weight_change']
            keep_c = [] if part == 'b' else ['going', 'weather']
            r = runs[runs.race_date <= X].copy()
            mk = r.race_date == X
            r.loc[mk, [c for c in t4_base.RES_RUN if c not in keep_r]] = np.nan
            r.loc[mk & ~r.finish_note.isin(CANCEL), 'finish_note'] = np.nan
            f = facts[facts.race_date <= X].copy()
            f.loc[f.race_date == X, FACT_RES] = np.nan
            c = races[races.race_date <= X].copy()
            c.loc[c.race_date == X, [cc for cc in t4_base.RES_RACE if cc not in keep_c]] = np.nan
            Tn = build(r, f, c, day=X, parts=(part,))
            cols = [cc for cc in Tn.columns if cc.startswith(part + '7_')]
            a = full[full.race_date == X].set_index(KEY + ['umaban'])[cols].sort_index()
            b = Tn.set_index(KEY + ['umaban'])[cols].sort_index()
            assert a.index.equals(b.index), X
            A, B = a.to_numpy(float), b.to_numpy(float)
            eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
            bad = [cc for cc, okc in zip(cols, eq.all(0)) if not okc]
            per.append({'date': X, 'part': part, 'rows': int(len(a)), 'match': int(eq.sum()), 'cells': int(eq.size),
                        'bad_cols': bad})
            tot[0] += int(eq.sum())
            tot[1] += int(eq.size)
            log(X, part, len(a), int(eq.sum()), eq.size, bad)
    bad_all = sorted({c for p in per for c in p['bad_cols']})
    z = {'days': len(days), 'match_days': sum(p['match'] == p['cells'] for p in per) // 1, 'runs': len(per),
         'match': tot[0], 'cells': tot[1], 'bad_cols': bad_all, 'per_day': per}
    LEAKJ.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding='utf-8')
    log('一致', tot[0], '/', tot[1], '合わない列', bad_all)
    md()


def md():
    R = pd.read_parquet(OUT)
    F = pd.read_parquet(FEAT6, columns=['year', 'Y3'])
    lk = json.loads(LEAKJ.read_text(encoding='utf-8')) if LEAKJ.exists() else None
    m = (F.year >= 2016) & (F.year <= 2019)
    lines = ['# 第 7 版の新しい材料 B(分類 G・H・I・J・K・L・O + 自作 A・F・G)', '',
             f'- 表: v3/feat_v7b_explore.parquet({len(R):,} 行 = feat_t6_explore と同じ並び・2015〜2021)。台本: src/v7_feat_b.py',
             f'- 列: 前日 b7_ {sum(c.startswith("b7_") for c in COLS)}・当日 d7_ {sum(c.startswith("d7_") for c in COLS)}',
             ]
    if lk:
        lines.append(f'- 漏れ検査: {lk["days"]} 日 × 前日/当日の 2 回 = {lk["runs"]} 回、一致 {lk["match"]:,} / {lk["cells"]:,} セル'
                     f'・合わない列 {lk["bad_cols"] or "なし"}(v3/v7b_leak.json)')
    else:
        lines.append('- 漏れ検査: 未実施')
    lines += ['- 順位相関 = 2016〜19 の行の、列と 3 着以内(Y3)のスピアマン(符号の確認だけ)', '',
              '| 列名 | 番号 | 一言の定義 | 前日/当日 | 欠け率 | 順位相関 |', '|---|---|---|---|---|---|']
    y = F.Y3[m].reset_index(drop=True)
    for c in COLS:
        num, dsc, kind = DEFS[c]
        x = R[c][m.to_numpy()].reset_index(drop=True)
        ok = x.notna()
        rho = x[ok].rank().corr(y[ok].rank()) if ok.sum() > 100 and x[ok].nunique() > 1 else np.nan
        lines.append(f'| {c} | {num} | {dsc} | {kind} | {R[c].isna().mean():.3f} | {rho:+.3f} |')
    lines += ['', '## 飛ばした番号', '', '| 番号 | 理由 |', '|---|---|']
    lines += [f'| {k} | {v} |' for k, v in SKIP.items()]
    MD.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    log('md', MD)


if __name__ == '__main__':
    {'features': features, 'leak': leak, 'md': md}[sys.argv[1]]()
