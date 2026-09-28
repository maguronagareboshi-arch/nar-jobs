# -*- coding: utf-8 -*-
"""第 5 版 3 日目(PREREG5 §4-2・§4-3・§4-4・§5・§6・§10・§11): 段 B(流れと道中)・段 C(相手関係の点)。
SI* = SI5(2 日目に段 A を残した)。2022-01-01 以降は読まない(load_archive の見張り)。第 4 版の台本と t5_base.py は直さずに呼ぶ。

  py -3.12 -X utf8 src/t5_day3.py parts    # 段 B・C の部品(2014〜2021)→ 部品の点検 B・C → 材料の表 v3/feat_t5_explore.parquet
  py -3.12 -X utf8 src/t5_day3.py leak     # リーク検査(20 日・seed 0・うち 1 月 4 日・前日版の全列 115)
  py -3.12 -X utf8 src/t5_day3.py stages   # 段 B・段 C の当てはめ外(15/500/800)と採否・§6 追加 4
  py -3.12 -X utf8 src/t5_day3.py grid     # 最終形の格子 8 通り(Y1 → Y3)
  py -3.12 -X utf8 src/t5_day3.py day      # 当日版(最終形 + 段 6 の 3 列)
  py -3.12 -X utf8 src/t5_day3.py line     # 第 4 版の線(0.659/0.665 の再現)・対の差・開ける前の止まりどころ・§6 追加 1・2
  py -3.12 -X utf8 src/t5_day3.py md       # out/t5_day3.md

■ 決め書に無い細部(この台本で決めた・段 B・C の当てはめ外を見る前。見た後は変えない)
  1. 部品は U = v3/t5_base_si5_2014_2021.parquet(SI 列 = SI5 = SI*・南関・取消/除外を除く)の行で作る。続けての 2 走・前走・5 走は
     U を馬(hk)・日付・R の順に並べた隣り合う行(t5_base.pairs_of・t4_day3.lagf と同じ)。
  2. RS の勝ち時計 = そのレースの U の time_sec の最小。レースの上がり 3F = races の race_last3f。d ≤ 600 か どちらか欠けのレースは RS 欠け。
     係数の窓は t5_base.win_of(y)(2014 は 2014・2015 は 2014)。コースごとの最小二乗は np.polyfit(t, f, 1)。借りる先は
     t4_base.course_b(同じ場・±200 m・回りは問わない・同じ差なら短い方)。
  3. pos の fpos・fn は facts の c1〜c4・n1〜n4 を KEY・馬番で U に付けて t4_day3.first_corner に通す。fn ≤ 1 か fpos 欠けは欠け。
  4. γ(y) の組 = 細部 1 の隣り合う 2 行で間隔 ≤ 90 日・後の走りの年が win_of(y)・両方に SI* があり前の走りに RS·pos がある組。
     SI*_後 = a + b·SI*_前 + c·(RS·pos)_前 を lstsq。γ は 2014〜2021 の各年(2014 = 2015 と同じ窓)。SIp は走りの年の γ を使う。
  5. FS の L = U の last3f(t4_base の上がり指数と同じ列)。T' = U の time_sec。基準は窓の勝ち馬(着順 1)の FS の中央値で、
     勝ち馬の FS があるレースが 30 R 以上のコースだけ持つ(足りなければ細部 2 と同じ借り方)。
  6. 通過順: U にあるレースの corners(JSON)の項目名を NFKC にする(名前は知らない記号に数えない。名前の種類と数は記録。
     バグ直し 3 日目: 当初は「N角」以外の名前も数えて 950 で止まった → 決め書 §4-2(e) どおり並びの中だけ数える)。3 角 = 名前に「3角」を含む
     最後の項目・4 角も同じ。並びは NFKC の後 1 文字ずつ読み、数字・「,」「-」「=」「(」「)」以外は知らない記号。
     読めないレース = corners が欠け・JSON が読めない・3 角か 4 角の項目が無い・並びが崩れる(区切りの無い 2 頭・括弧の入れ子・
     括弧の中の「-」「=」・閉じない括弧・同じ馬番が 2 回・末尾が区切り)のどれか。読めないレースは全馬の x の値を欠けにする。
     x_wide(その走り)= 3 角 + 4 角の外を回った数(どちらかの角に載っていなければ欠け)。
  7. 「前走」= 直前の南関の走り(値が欠けなら欠け)。p_simax5・r_frmax5 は直前の南関の 5 走の最高(a_simax5 と同じ)。
     重み付き平均(p_mis5・p_fsw・x_wide5)と p_ab の 5 走は、その値のある直前の南関の 5 走(a_siw・a_tenw と同じ)。
  8. p_ab の事前の値 = 年 y の窓 win_of(y) の SIp の区分 k の平均(区分の対応は t5_base.kmaps_of・読めない区分は窓の全平均。
     rebuild の a_prior と同じ作り方)。p_ab_rank・r_ab_rank・r_ab_z・r_ab_gap は U のレースの全出走馬の中で(k_ab_* と同じ式)。
     g_eps_rank は予想するレースの行(targets3)の中で(f_ten_rank と同じ in_race_rank)。
  9. FR: 物差しの馬 = 直前の南関の 5 走のうち FR のある走りが 3 つ以上(t5_base の a_sin5 と同じ数え方)で今回の SI* がある馬。
     R は FR のある直前の 5 走と事前の値(win_of(y) の FR〔2014 は SI*〕の区分 k の平均)で a_ab と同じ式。全馬に R を作り r_ab にする。
     レース = (日付・場・R)。c_y の窓 = y−3〜y−1 年のうち 2015 年以降の物差しの馬の (R_j − SI*_j)(2014 年は物差しの馬を作らない)。
     SI* が欠けの馬は FR も欠け。
  10. g_eps: 走り = h(全 NAR・取消/除外を除く)。賞金 = races の prize_yen を JSON の数の列として読み、着順 k(1〜5)に k 番目
      (列が k より短ければ 0)。6 着以下・着順の無い走り(中止など)は 0。読めない = JSON の数の列でない・空・1 番目が 0 以下。
      分母の中央値 = 走りの日の [−365, −1] 日の南関のレース(prize_yen が読めるもの)の 1 番目の賞金の中央値。そのレースが無い走り
      (2014 年の初めなど)は読めない賞金と同じく分子・分母から外す。窓 = [当日 − 730, 当日 − 1](t4_day3.wsum)。
  11. 点検「流れの向きの筋」: 2016〜2021 の U のレースで RS の 25%・75% 点(レース単位)。上位 = RS ≥ 75% 点・下位 = RS ≤ 25% 点。
      3 着以内 = 着順 ≤ 3。
  12. 点検「通過順の読みの筋」: 2016〜2021 の読めた走りで、4 角の順位 = 4 角の並びの中の何番目(括弧の中も書いた順)。
      頭数の帯(U のそのレースの出走数 5〜8・9〜12・13 以上)× 4 角の順位 の組のうち 30 頭以上の組ごとに
      (x_gap4 − 1.5 ×(順位 − 1))と着差(time_sec − そのレースの最小)の順位相関を取り、頭数で重み付き平均。
      「-」「=」のある角の割合 = 2016〜2021 の読めたレースの 3 角・4 角のうち「-」か「=」を含む割合。
  13. 点検「FR の続き具合」: 細部 1 の隣り合う 2 行・間隔 ≤ 90 日・後の走りが 2015〜2021・両方に FR。
      「FR の水準」の前年からの動き = 2016〜2021 の各年の中央値 − 前年の中央値。
  14. 点検「賞金の筋」: 材料の表(2016〜2021)の g_eps と b_g の両方がある行の順位相関(pandas spearman)。
  15. 段の当てはめ外は t4_day3.fit_pred(CACHE = v3/t5_cache)。段 A の予想は 2 日目のキャッシュ(t5_A)を読み、
      v3/t5_day2_fit.json の段 A の値と一致することを確かめる。段 C の「前」は段 B を残せば A+B、残さなければ A。
  16. §6 追加 4: 段の列(前の段まで + その段)から群を 1 つ外して Y3 だけ学び直し、p1 は段の全列の Y1 で finish。
      差 = 段の全列の対数尤度 Y3 − 群を外した対数尤度 Y3(正 = その群が効いた)。
  17. 第 4 版の線: feat_t4_explore・t4_grid.json の kept と設定で CACHE = v3/t5_cache に学び直し(tag t5_v4pre・t5_v4day)、
      v3/t4_day3_res.json の grid.final・day の ◎ 勝率・◎ 3 着以内率・対数尤度 Y1・Y3 と |差| ≤ 1e-12 で一致を確かめる。
  18. 確かめる期間での「上回った」の見込み = Φ((差 − 1.11h)/(1.11h/1.96))(本当の差 = 作る期間の点推定・正規の近似)。両版とも
      「上回った」の見込みは 2 つの積(独立とみた近似)も書く。
  19. §6 追加 1 のレースの種類は材料の表の l_debut・l_jra・l_nar(予想するレースの行)。追加 2 の温度 β は
      scipy.optimize.minimize_scalar(区間 0.2〜5)で作る期間 2016〜2021 をまとめた Y1 の対数尤度(p1^β をレースで割り直す)を最大。
"""
import json
import math
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_eval  # noqa: E402
import t4_base  # noqa: E402
import t4_day3  # noqa: E402
import t5_base  # noqa: E402
from day2_features import ENTRY_COLS, RACE_COLS, build as build3  # noqa: E402
from t3_day2_features import finish_table, targets3  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
BASE5 = t5_base.BASE5
FEAT4, FEAT5A = t5_base.FEAT4, t5_base.FEAT5
FEAT = V3 / 'feat_t5_explore.parquet'
PARTS = V3 / 't5_day3_parts.parquet'
PREDS = V3 / 't5_day3_preds.parquet'
RES = V3 / 't5_day3_res.json'
MD = REPO / 'out/t5_day3.md'
LEDGER = REPO / 'LEDGER.md'
KEY, RK = t4_day3.KEY, t4_base.RK
NANKAN, CANCEL, HALF = t4_day3.NANKAN, t4_day3.CANCEL, 90.0
win_of = t5_base.win_of
FB = ['p_si1', 'p_ab', 'p_simax5', 'p_ab_rank', 'p_rs1', 'p_mis1', 'p_mis5', 'p_fs1', 'p_fsw',
      'x_gap3_1', 'x_gap4_1', 'x_wide1', 'x_wide5']
FC = ['r_fr1', 'r_ab', 'r_frmax5', 'r_ab_rank', 'r_ab_z', 'r_ab_gap', 'r_gap1', 'g_eps', 'g_eps_rank']
GROUPS = {'B': {'p_*(流れ)': FB[:9], 'x_*(通過順)': FB[9:]}, 'C': {'r_*(相手関係の点)': FC[:7], 'g_*(賞金)': FC[7:]}}
PRE_A, DAY6 = t4_day3.PRE_ALL, t4_day3.FEATS4[6]
PRE_ALL5 = PRE_A + FB + FC
ALL5 = PRE_ALL5 + DAY6
assert len(FB) == 13 and len(FC) == 9 and len(set(ALL5)) == 118
META = t4_day3.META
SEPV = {',': 1.5, '-': 3.5, '=': 6.0}
YRS = list(range(2015, 2022))
EVAL = t4_day3.YEARS
CFG = t4_day3.STAGE_CFG


def res_load():
    return json.loads(RES.read_text(encoding='utf-8')) if RES.exists() else {}


def res_save(k, v):
    r = res_load()
    r[k] = v
    RES.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding='utf-8')


def ledger(cols):
    with LEDGER.open('a', encoding='utf-8') as f:
        f.write('| ' + ' | '.join(cols) + ' |\n')


def dnum_of(s):
    return (pd.to_datetime(s) - pd.Timestamp('2000-01-01')).dt.days.to_numpy()


# ================================================================ 通過順
class Unknown(Exception):
    pass


def parse_order(s):
    """→ {馬番: (先頭からの差, 外を回った数, 何番目)}。読めなければ None。知らない記号は Unknown。"""
    s = unicodedata.normalize('NFKC', str(s))
    out, last, sep, ing, k, gfirst, expect, i = {}, None, None, False, 0, None, 'num', 0
    if not s:
        return None
    while i < len(s):
        ch = s[i]
        if '0' <= ch <= '9':
            j = i
            while j < len(s) and '0' <= s[j] <= '9':
                j += 1
            u = int(s[i:j]); i = j
            if expect != 'num' or u in out:
                return None
            if ing:
                k += 1
                if k == 1:
                    v = 0.0 if last is None else last + sep
                    gfirst = v
                else:
                    v = gfirst + 0.5 * (k - 1)
                w = k - 1
            else:
                v, w = (0.0 if last is None else last + sep), 0
            out[u] = (v, w, len(out) + 1)
            last, sep, expect = v, None, 'sep'
            continue
        if ch == '(':
            if ing or expect != 'num':
                return None
            ing, k = True, 0
        elif ch == ')':
            if not ing or expect != 'sep':
                return None
            ing = False
        elif ch == ',':
            if expect != 'sep':
                return None
            if not ing:
                sep = 1.5
            expect = 'num'
        elif ch in '-=':
            if expect != 'sep' or ing:
                return None
            sep, expect = SEPV[ch], 'num'
        else:
            raise Unknown(ch)
        i += 1
    if ing or expect != 'sep':
        return None
    return out


def corners_table(races):
    """races(南関)→ 馬ごとの 3 角・4 角の差・外・順位(KEY・umaban)と、レースごとの読めた/読めない・知らない記号の数。"""
    rows, stat, unk, names = [], [], {}, {}
    R = races[races.track.isin(NANKAN)].drop_duplicates(KEY)
    for t, d, rn, cs in zip(R.track, R.race_date, R.race_no.astype(int), R.corners):
        ok, dash, res = True, [], {}
        try:
            items = json.loads(cs) if isinstance(cs, str) else None
        except Exception:
            items = None
        if not isinstance(items, list):
            ok = False
        else:
            c3 = c4 = None
            for it in items:
                if not isinstance(it, dict):
                    ok = False
                    continue
                nm = unicodedata.normalize('NFKC', str(it.get('name', '')))
                names[nm] = names.get(nm, 0) + 1
                if '3角' in nm:
                    c3 = it.get('order')
                if '4角' in nm:
                    c4 = it.get('order')
            if c3 is None or c4 is None:
                ok = False
            else:
                for nm, od in (('3', c3), ('4', c4)):
                    try:
                        p = parse_order(od) if isinstance(od, str) else None
                    except Unknown as e:
                        unk[str(e)] = unk.get(str(e), 0) + 1
                        p = None
                    if p is None:
                        ok = False
                        break
                    res[nm] = p
                    so = unicodedata.normalize('NFKC', str(od))
                    dash.append(('-' in so) or ('=' in so))
        stat.append((t, d, rn, ok, sum(dash) if ok else 0))
        if ok:
            for u in set(res['3']) | set(res['4']):
                a, b = res['3'].get(u), res['4'].get(u)
                rows.append((t, d, rn, u, a[0] if a else np.nan, b[0] if b else np.nan, a[1] if a else np.nan,
                             b[1] if b else np.nan, b[2] if b else np.nan))
    X = pd.DataFrame(rows, columns=KEY + ['umaban', 'gap3', 'gap4', 'wide3', 'wide4', 'rank4'])
    S = pd.DataFrame(stat, columns=KEY + ['ok', 'ndash'])
    return X, S, unk, names


# ================================================================ 段 B・C の部品
def coef_by_course(R, val, fit, years):
    """R = レースの表(course・year・値)。年ごとに窓のレースでコースの係数を作り、借りて返す(レースの順)。"""
    out = [None] * len(R)
    for y in years:
        W = R[R.year.isin(win_of(y))]
        own = {}
        for c, g in W.groupby('course'):
            g = g.dropna(subset=val)
            if len(g) >= 30:
                own[c] = fit(g)
        iy = np.flatnonzero((R.year == y).to_numpy())
        cs = R.course.to_numpy()[iy]
        m = t4_base.course_b([c for c in set(cs) if isinstance(c, str)], own)
        for i, c in zip(iy, cs):
            out[i] = m.get(c)
    return out


def horse_sort(U):
    U = U.copy()
    U['dnum'] = dnum_of(U.race_date)
    U = U.sort_values(['hk', 'dnum', 'race_no'], kind='mergesort').reset_index(drop=True)
    return U, pd.factorize(U.hk)[0].astype(np.int64), U.dnum.to_numpy()


def wavg(hid, dn, v):
    V, Dd = t4_day3.lastk(hid, dn, v, ~np.isnan(v), 5, hid, dn)
    w = np.where(np.isnan(V), 0.0, 0.5 ** ((dn[:, None] - Dd) / HALF))
    sw = w.sum(1)
    sv = np.nansum(w * np.nan_to_num(V), axis=1)
    return np.where(sw > 0, sv / np.where(sw > 0, sw, 1), np.nan), sw, sv


def class_prior(U, v, kmaps):
    """年 y の窓 win_of(y) の v の区分 k の平均(rebuild の a_prior と同じ作り方)。U の行の順。"""
    pr = np.full(len(U), np.nan)
    yr, k0 = U.year.to_numpy(), U.k0.to_numpy()
    for y in sorted(set(yr)):
        m = np.isin(yr, win_of(y)) & ~np.isnan(v)
        km = kmaps[y]
        means = pd.Series(v[m]).groupby(pd.Series(k0[m]).map(km).to_numpy()).mean().to_dict()
        allm = float(np.mean(v[m]))
        iy = np.flatnonzero(yr == y)
        pr[iy] = [means.get(km.get(k), allm) if k is not None else allm for k in k0[iy]]
    return pr


def in_race(U, col):
    g = U.groupby(RK)[col]
    cnt = g.transform('count')
    rank = g.rank(ascending=False, method='average') / cnt
    mu, sd = g.transform('mean'), g.transform(lambda z: z.std(ddof=0))
    return rank.to_numpy(), ((U[col] - mu) / np.maximum(sd, 1.0)).to_numpy(), (U[col] - g.transform('max')).to_numpy()


def make_fr(U):
    """U(t5 の U の形)→ FR・R・物差しの馬の数・(R_j − SI*_j)、c_y。日付の順に作る。"""
    U = U.reset_index(drop=True)
    kmaps = t5_base.kmaps_of(U)
    SI = U.SI.to_numpy(float)
    yr, k0, hk = U.year.to_numpy(), U.k0.to_numpy(), U.hk.to_numpy()
    dnum = dnum_of(U.race_date)
    n = len(U)
    FR, Rab, NK, RJ = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n), np.full(n, np.nan)
    cnt = np.zeros(n)
    allh, nnh, cy = {}, {}, {}
    order = U.sort_values(['race_date', 'track', 'race_no', 'runner_number'], kind='mergesort').index.to_numpy()
    dates = U.race_date.to_numpy()[order]
    cut = np.flatnonzero(np.r_[True, dates[1:] != dates[:-1], True])
    rkey = (U.track.astype(str) + '|' + U.race_no.astype(str)).to_numpy()
    cur_y = None
    for s0, s1 in zip(cut[:-1], cut[1:]):
        idx = order[s0:s1]
        y = int(yr[idx[0]])
        if y != cur_y:
            cur_y = y
            km = kmaps[y]
            P = np.where(yr == 2014, SI, FR)
            m = np.isin(yr, win_of(y)) & ~np.isnan(P)
            means = pd.Series(P[m]).groupby(pd.Series(k0[m]).map(km).to_numpy()).mean().to_dict()
            allm = float(np.mean(P[m]))
            if y >= 2016:
                mm = np.isin(yr, [x for x in range(y - 3, y) if x >= 2015]) & ~np.isnan(RJ)
                cy[y] = float(np.median(RJ[mm])) if mm.any() else 0.0
            else:
                cy[y] = 0.0
        for i in idx:
            k = k0[i]
            pri = means.get(km.get(k), allm) if k is not None else allm
            L = nnh.get(hk[i], [])
            sw = swv = 0.0
            for j in range(1, 6):
                if len(L) >= j:
                    dj, vj = L[-j]
                    w = 0.5 ** ((dnum[i] - dj) / HALF)
                    sw += w; swv += w * vj
            Rab[i] = (swv + pri) / (sw + 1)
            cnt[i] = sum(1 for v in allh.get(hk[i], [])[-5:] if v == v)
        if y == 2014:
            FR[idx] = SI[idx]
        else:
            sc = (cnt[idx] >= 3) & ~np.isnan(SI[idx])
            RJ[idx[sc]] = Rab[idx[sc]] - SI[idx[sc]]
            T = pd.DataFrame({'r': rkey[idx], 'v': RJ[idx]})
            g = T.groupby('r').v
            med, nk = g.transform('median').to_numpy(), g.transform('count').to_numpy(float)
            NK[idx] = nk
            adj = np.where(nk > 0, nk / (nk + 3) * (np.nan_to_num(med) - cy[y]), 0.0)
            FR[idx] = SI[idx] + adj
        for i in idx:
            allh.setdefault(hk[i], []).append(FR[i])
            if FR[i] == FR[i]:
                nnh.setdefault(hk[i], []).append((dnum[i], FR[i]))
    return pd.DataFrame({'FR': FR, 'R': Rab, 'nk': NK, 'rj': RJ}, index=U.index), cy


def prize_list(p):
    try:
        v = json.loads(p) if isinstance(p, str) else None
    except Exception:
        return None
    if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) for x in v) or v[0] <= 0:
        return None
    return [float(x) for x in v]


def g_eps_of(h, races, q):
    """q = KEY・umaban・hid の行。→ g_eps(q の順)と記録。"""
    rc = races[KEY + ['prize_yen']].drop_duplicates(KEY).copy()
    rc['race_no'] = rc.race_no.astype(int)
    rc['pl'] = rc.prize_yen.map(prize_list)
    nk = rc[rc.track.isin(NANKAN) & rc.pl.notna()].copy()
    nk['dnum'] = dnum_of(nk.race_date)
    nk = nk.sort_values('dnum')
    nd, n1 = nk.dnum.to_numpy(), np.array([x[0] for x in nk.pl])
    H = h[~h.finish_note.isin(CANCEL)][KEY + ['umaban', 'hid', 'finish']].copy()
    H['race_no'] = H.race_no.astype(int)
    H = H.merge(rc[KEY + ['pl']], on=KEY, how='left')
    H['dnum'] = dnum_of(H.race_date)
    ud = np.unique(H.dnum.to_numpy())
    lo, hi = np.searchsorted(nd, ud - 365, 'left'), np.searchsorted(nd, ud, 'left')
    den = {d: (float(np.median(n1[a:b])) if b > a else np.nan) for d, a, b in zip(ud, lo, hi)}
    H['den'] = H.dnum.map(den)
    fin = H.finish.to_numpy(float)
    num = [0.0 if (pl is None or not (f == f) or f < 1 or f > 5) else (pl[int(f) - 1] if int(f) <= len(pl) else 0.0)
           for pl, f in zip(H.pl, fin)]
    ok = H.pl.notna().to_numpy() & H.den.notna().to_numpy()
    H['v'] = np.array(num) / H.den.to_numpy()
    H['one'] = 1.0
    Hs = H[ok]
    Q = q[['hid']].assign(dnum=dnum_of(q.race_date))
    s = t4_day3.wsum(Hs, ['hid'], ['v', 'one'], Q, 730)
    info = {'runs': int(len(H)), 'excluded': int((~ok).sum()), 'prize_unread_nankan':
            int(H[H.track.isin(NANKAN)].pl.isna().sum()), 'prize_unread_other': int(H[~H.track.isin(NANKAN)].pl.isna().sum()),
            'no_den': int(H.den.isna().sum())}
    return np.where(s[:, 1] > 0, s[:, 0] / np.where(s[:, 1] > 0, s[:, 1], 1), np.nan), info


def parts_of(U5, fc, races, h, tgt):
    """U5 = rebuild(U, SI5) の形(SI = SI*)、fc = 南関の facts(KEY・umaban・c1〜n4)、races = 全 NAR のレース、h = sources_from、
    tgt = 作る行(targets3)。→ 新しい 22 列(tgt の順・KEY・umaban 付き)、走りごとの部品、記録。"""
    U = U5.rename(columns={'runner_number': 'umaban'}).copy()
    U['umaban'] = U.umaban.astype(int)
    U['race_no'] = U.race_no.astype(int)
    f = fc[KEY + ['umaban', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']].copy()
    f['race_no'], f['umaban'] = f.race_no.astype(int), f.umaban.astype(int)
    U = U.merge(f.drop_duplicates(KEY + ['umaban']), on=KEY + ['umaban'], how='left', validate='1:1')
    rc = races[races.track.isin(NANKAN)][KEY + ['race_last3f', 'corners']].drop_duplicates(KEY).copy()
    rc['race_no'] = rc.race_no.astype(int)
    years = sorted(U.year.unique())
    # (a) RS
    R = U.groupby(KEY, sort=False).agg(tw=('time_sec', 'min'), d=('distance_m', 'first'), course=('course', 'first'),
                                       year=('year', 'first')).reset_index().merge(rc[KEY + ['race_last3f']], on=KEY, how='left')
    d = R.d.astype(float)
    okr = (d > 600) & R.tw.notna() & R.race_last3f.notna()
    R['f'] = np.where(okr, (R.tw - R.race_last3f) / ((d - 600) / 1000), np.nan)
    R['t'] = np.where(okr, R.tw / (d / 1000), np.nan)
    ab = coef_by_course(R, ['f', 't'], lambda g: tuple(np.polyfit(g.t.to_numpy(), g.f.to_numpy(), 1)[::-1]), years)
    al = np.array([x[0] if isinstance(x, tuple) else np.nan for x in ab])
    be = np.array([x[1] if isinstance(x, tuple) else np.nan for x in ab])
    R['RS'] = al + be * R.t.to_numpy() - R.f.to_numpy()
    U = U.merge(R[KEY + ['RS']], on=KEY, how='left')
    # (b) pos
    fpos, fn = t4_day3.first_corner(U)
    U['pos'] = np.where((fn > 1) & ~np.isnan(fpos), 1 - 2 * (fpos - 1) / np.where(fn > 1, fn - 1, 1), np.nan)
    U['mis'] = U.RS * U.pos
    # (c) γ・SIp
    V, dn, okp = t5_base.pairs_of(U)
    s, mis = V.SI.to_numpy(float), V.mis.to_numpy(float)
    yl = V.year.to_numpy()[1:]
    use = okp & ~np.isnan(s[:-1]) & ~np.isnan(s[1:]) & ~np.isnan(mis[:-1])
    gam, gin = {}, {}
    for y in years:
        m = use & np.isin(yl, win_of(y))
        A = np.column_stack([np.ones(m.sum()), s[:-1][m], mis[:-1][m]])
        a, b, c = np.linalg.lstsq(A, s[1:][m], rcond=None)[0]
        gam[int(y)] = float(c / b)
        gin[int(y)] = {'a': float(a), 'b': float(b), 'c': float(c), 'pairs': int(m.sum())}
    g = U.year.map(gam).to_numpy(float)
    U['SIp'] = np.where(np.isnan(U.mis.to_numpy(float)), U.SI, U.SI + g * U.mis)
    # (d) FS
    L = U.last3f.astype(float)
    U['FS'] = 100 * 600 * U.time_sec / (L * U.distance_m.astype(float))
    Wn = U[(U.finish == 1) & U.FS.notna()]
    # 基準 = 窓の勝ち馬の FS の中央値(勝ち馬の行の中央値)。30 R はレースの数で数える
    fsb = {}
    for y in years:
        W = Wn[Wn.year.isin(win_of(y))]
        nr = W.drop_duplicates(KEY).groupby('course').size()
        own = W.groupby('course').FS.median()[nr[nr >= 30].index].to_dict()
        cs = [c for c in set(U.course[U.year == y]) if isinstance(c, str)]
        fsb.update({(y, c): v for c, v in t4_base.course_b(cs, own).items()})
    U['FSd'] = U.FS - np.array([fsb.get((y, c), np.nan) for y, c in zip(U.year, U.course)], float)
    # (e) 通過順
    X, S, unk, names = corners_table(rc.merge(U[KEY].drop_duplicates(), on=KEY, how='inner'))
    U = U.merge(X, on=KEY + ['umaban'], how='left')
    U['xwide'] = U.wide3 + U.wide4
    # 段 C: FR
    Fr, cy = make_fr(U5.reset_index(drop=True))
    key5 = U5[RK + ['runner_number']].rename(columns={'runner_number': 'umaban'}).reset_index(drop=True)
    key5['race_no'], key5['umaban'] = key5.race_no.astype(int), key5.umaban.astype(int)
    U = U.merge(pd.concat([key5, Fr], axis=1), on=KEY + ['umaban'], how='left', validate='1:1')
    # 馬の順の列
    U, hid, dn = horse_sort(U)
    kmaps = t5_base.kmaps_of(U5)
    F = pd.DataFrame(index=U.index)
    lag = lambda c: t4_day3.lagf(U[c].to_numpy(float), hid, 1)  # noqa: E731
    mx5 = lambda c: t4_day3.nanagg(t4_day3.lagm(U[c].to_numpy(float), hid), np.nanmax)  # noqa: E731
    F['p_si1'] = lag('SIp')
    _, sw, sv = wavg(hid, dn, U.SIp.to_numpy(float))
    U['p_ab'] = (sv + class_prior(U, U.SIp.to_numpy(float), kmaps)) / (sw + 1)
    F['p_ab'] = U.p_ab
    F['p_simax5'] = mx5('SIp')
    F['p_ab_rank'] = in_race(U, 'p_ab')[0]
    F['p_rs1'] = lag('RS')
    F['p_mis1'] = lag('mis')
    F['p_mis5'] = wavg(hid, dn, U.mis.to_numpy(float))[0]
    F['p_fs1'] = lag('FSd')
    F['p_fsw'] = wavg(hid, dn, U.FSd.to_numpy(float))[0]
    F['x_gap3_1'] = lag('gap3')
    F['x_gap4_1'] = lag('gap4')
    F['x_wide1'] = lag('xwide')
    F['x_wide5'] = wavg(hid, dn, U.xwide.to_numpy(float))[0]
    F['r_fr1'] = lag('FR')
    F['r_ab'] = U.R
    F['r_frmax5'] = mx5('FR')
    F['r_ab_rank'], F['r_ab_z'], F['r_ab_gap'] = in_race(U, 'R')
    U['frgap'] = U.FR - U.SI
    F['r_gap1'] = lag('frgap')
    F[KEY + ['umaban']] = U[KEY + ['umaban']]
    T = tgt[KEY + ['umaban']].copy()
    T['race_no'], T['umaban'] = T.race_no.astype(int), T.umaban.astype(int)
    T = T.merge(F, on=KEY + ['umaban'], how='left', validate='1:1', indicator=True)
    assert (T.pop('_merge') == 'both').all(), '作る行が U に無い'
    hq = h[~h.finish_note.isin(CANCEL)][KEY + ['umaban', 'hid']].drop_duplicates(KEY + ['umaban']).copy()
    hq['race_no'], hq['umaban'] = hq.race_no.astype(int), hq.umaban.astype(int)
    Q = T[KEY + ['umaban']].merge(hq, on=KEY + ['umaban'], how='left', validate='1:1')
    T['g_eps'], ginfo = g_eps_of(h, races, Q)
    T['g_eps_rank'] = t4_day3.in_race_rank(T, 'g_eps')
    info = {'gamma': gam, 'gamma_fit': gin, 'c_y': {int(k): v for k, v in cy.items()}, 'unknown': unk, 'corner_names': names, 'geps': ginfo}
    return T[KEY + ['umaban'] + FB + FC], U, S, info


# ================================================================ parts(点検 B・C → 材料の表)
def spearman(a, b):
    return float(pd.Series(a).corr(pd.Series(b), method='spearman'))


def parts():
    runs, facts, races = t4_day3.raw()
    h = t4_day3.sources_from(runs, facts, races)
    tg = targets3(h)
    tgt = tg[tg.race_date >= '2015-01-01'].reset_index(drop=True)
    U5 = pd.read_parquet(BASE5)
    U5 = U5[[c for c in pd.read_parquet(t5_base.BASE4).columns]]
    fc = facts[facts.track.isin(NANKAN)]
    N, P, S, info = parts_of(U5, fc, races, h, tgt)
    P.drop(columns=['c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']).to_parquet(PARTS, index=False)
    # ---- 点検 B・C
    gam = info['gamma']
    E = P[P.year >= 2016]
    RR = E.drop_duplicates(KEY)
    q25, q75 = RR.RS.quantile(0.25), RR.RS.quantile(0.75)
    fr = E[E.pos > 0.5]
    t_hi = float((fr[fr.RS >= q75].finish <= 3).mean())
    t_lo = float((fr[fr.RS <= q25].finish <= 3).mean())
    S7 = S[(S.race_date >= '2015-01-01')]
    unr = float((~S7.ok).mean())
    nunk = int(sum(info['unknown'].values()))
    S6 = S[(S.race_date >= '2016-01-01') & S.ok]
    dash_share = float(S6.ndash.sum() / (2 * len(S6)))
    G = E[E.gap4.notna() & E.rank4.notna() & E.time_sec.notna()].copy()
    nst_all = P.groupby(KEY).umaban.transform('size')
    G['nst'] = nst_all.loc[G.index]
    G['band'] = np.where(G.nst <= 8, 0, np.where(G.nst <= 12, 1, 2))
    G['ex'] = G.gap4 - 1.5 * (G.rank4 - 1)
    G['mg'] = G.time_sec - P.groupby(KEY).time_sec.transform('min').loc[G.index]
    cs, ws = [], []
    for _, g in G.groupby(['band', 'rank4']):
        if len(g) >= 30 and g.ex.nunique() > 1 and g.mg.nunique() > 1:
            cs.append(spearman(g.ex, g.mg)); ws.append(len(g))
    c_gap = float(np.average(cs, weights=ws))
    V, dn, okp = t5_base.pairs_of(P)
    fv = V.FR.to_numpy(float)
    okf = okp & (V.year.to_numpy()[1:] >= 2015) & ~np.isnan(fv[:-1]) & ~np.isnan(fv[1:])
    c_fr = float(np.corrcoef(fv[:-1][okf], fv[1:][okf])[0, 1])
    lvl = {y: float((P.FR - P.SI)[P.year == y].median()) for y in YRS}
    mv = {y: lvl[y] - lvl[y - 1] for y in range(2016, 2022)}
    # 材料の表
    F5 = pd.read_parquet(FEAT5A).sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    F5['race_no'] = F5.race_no.astype(int)
    T = F5.merge(N, on=KEY + ['umaban'], how='left', validate='1:1', indicator=True)
    assert (T.pop('_merge') == 'both').all() and len(T) == len(F5) == len(N)
    E6 = T[T.year >= 2016]
    m = E6.g_eps.notna() & E6.b_g.notna()
    c_g = spearman(E6.g_eps[m].to_numpy(), E6.b_g[m].to_numpy())
    checks = [
        {'name': '流れの効き: γ(2015〜2021 の年ごと)', 'value': '・'.join(f'{gam[y]:+.4f}' for y in YRS), 'line': 'すべて > 0',
         'ok': all(gam[y] > 0 for y in YRS)},
        {'name': '流れの向きの筋: pos > 0.5 の馬の 3 着以内率(RS 上位 1/4 対 下位 1/4・2016〜2021)',
         'value': f'上位 {t_hi:.4f}・下位 {t_lo:.4f}', 'line': '上位 < 下位', 'ok': t_hi < t_lo},
        {'name': '通過順の読み取り(2015〜2021 の南関)', 'value': f'知らない記号 {nunk}・読めないレース {unr:.5f}({int((~S7.ok).sum())}/{len(S7)} R)',
         'line': '知らない記号 0・読めない ≤ 0.001', 'ok': nunk == 0 and unr <= 0.001},
        {'name': '通過順の読みの筋: x_gap4 − 1.5(順位 − 1) と着差の順位相関(2016〜2021)',
         'value': f'{c_gap:+.4f}({len(cs)} 組・「-」「=」のある角 {dash_share:.4f})', 'line': '> 0', 'ok': c_gap > 0},
        {'name': 'FR の続き具合: 続けての 2 走の相関', 'value': f'{c_fr:.4f}({int(okf.sum()):,} 組)', 'line': '≥ 0.5', 'ok': c_fr >= 0.5},
        {'name': 'FR の水準: 年ごとの (FR − SI*) の中央値(2015〜2021)・前年からの動き',
         'value': '・'.join(f'{v:+.3f}' for v in lvl.values()) + ' / 動き ' + '・'.join(f'{v:+.3f}' for v in mv.values()),
         'line': '±2 以内・動き ≤ 1', 'ok': all(abs(v) <= 2 for v in lvl.values()) and all(abs(v) <= 1 for v in mv.values())},
        {'name': '賞金の筋: g_eps と b_g の順位相関(2016〜2021)', 'value': f'{c_g:+.4f}({int(m.sum()):,} 行)', 'line': '> 0', 'ok': c_g > 0},
    ]
    allok = all(c['ok'] for c in checks)
    rec = {'checks': checks, 'all_ok': allok, 'info': info, 'level': lvl,
           'share': {'RS': float(E.drop_duplicates(KEY).RS.notna().mean()), 'pos': float(E.pos.notna().mean()),
                     'FSd': float(E.FSd.notna().mean()), 'gap4': float(E.gap4.notna().mean()),
                     'FR_eq_SI': float((E.nk == 0).mean())},
           'miss': {c: float(T[T.year >= 2016][c].isna().mean()) for c in FB + FC}}
    for c in checks:
        print(c['name'], c['value'], '合' if c['ok'] else '否', flush=True)
    print('γ', gam, 'c_y', info['c_y'], 'unknown', info['unknown'], flush=True)
    if not allok:
        res_save('parts', rec)
        md()
        raise SystemExit('⛔ 部品の点検 B・C に届かない')
    # 当日の 3 列が第 4 版と同じ・結果の列が無い
    F4 = pd.read_parquet(FEAT4).sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    b = t5_base.colcmp(T, F4, DAY6 + ['n', 'Y1', 'Y3'])
    assert not any(b.values()), f'当日の 3 列が第 4 版と違う {b}'
    T = T[META + ALL5]
    assert not t4_day3.BANNED & set(ALL5), 'オッズ・人気・結果の列が材料に入っている'
    assert set(T.columns) - set(META) == set(ALL5) and len(ALL5) == 118
    assert T.race_date.max() < '2022-01-01' and T.race_date.min() >= '2015-01-01'
    T.to_parquet(FEAT, index=False)
    rec['rows'] = int(len(T))
    res_save('parts', rec)
    md()


# ================================================================ leak
def leak():
    runs, facts, races = t4_day3.raw()
    h = t4_day3.sources_from(runs, facts, races)
    tg = targets3(h)
    full = pd.read_parquet(FEAT)
    full['race_no'] = full.race_no.astype(int)
    days = t4_base.pick_days(races[races.track.isin(NANKAN)])
    base_cols = list(pd.read_parquet(t5_base.BASE4).columns)
    per, tot = [], [0, 0]
    for X in days:
        r = runs[runs.race_date <= X].copy()
        mk = r.race_date == X
        r.loc[mk, t4_base.RES_RUN] = np.nan
        r.loc[mk & ~r.finish_note.isin(CANCEL), 'finish_note'] = np.nan
        f = facts[facts.race_date <= X].copy()
        f.loc[f.race_date == X, t4_day3.FACT_RES] = np.nan
        c = races[races.race_date <= X].copy()
        c.loc[c.race_date == X, t4_base.RES_RACE] = np.nan
        Ub = t4_day3.base_from(r, f, c)
        Rs, _ = t5_base.make_si5(Ub)
        U5 = t5_base.rebuild(Ub, Rs.SI5.to_numpy())[base_cols]
        hm = t4_day3.sources_from(r, f, c)
        tday = tg[tg.race_date == X].reset_index(drop=True)
        Tn = t4_day3.feat_new(U5, hm, c, tg[tg.race_date < X], tday)
        ent = h.loc[h.race_date == X, KEY + ['umaban', 'hid'] + ENTRY_COLS + RACE_COLS + ['body_weight']]
        Xd, _ = build3(h[h.race_date < X], tday, tg[tg.race_date < X], ent=ent)
        Xd = finish_table(Xd, ent, tg)
        T = t4_day3.assemble(Tn, Xd)
        N, _, _, _ = parts_of(U5, f[f.track.isin(NANKAN)], c, hm, tday)
        T['race_no'] = T.race_no.astype(int)
        T = T.merge(N, on=KEY + ['umaban'], how='left', validate='1:1')
        a = full[full.race_date == X].set_index(KEY + ['umaban'])[PRE_ALL5].sort_index()
        b = T.set_index(KEY + ['umaban'])[PRE_ALL5].sort_index()
        assert a.index.equals(b.index), X
        eq = t5_base.eqmask(a.to_numpy(float), b.to_numpy(float))
        bad = [cc for cc, ok in zip(PRE_ALL5, eq.all(0)) if not ok]
        per.append({'date': X, 'rows': int(len(a)), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad_cols': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        print(X, len(a), int(eq.sum()), eq.size, bad, flush=True)
    z = {'days': len(days), 'jan_days': sum(p['date'][5:7] == '01' for p in per),
         'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0], 'cells': tot[1],
         'cols': len(PRE_ALL5), 'per_day': per}
    res_save('leak', z)
    print('一致', z['match_days'], '/', z['days'], '日', tot[0], '/', tot[1])
    md()
    if tot[0] != tot[1]:
        raise SystemExit('⛔ リーク検査が 100% でない')


# ================================================================ 当てはめ外
def setup():
    t4_day3.CACHE = V3 / 't5_cache'
    d = t5_base.load_feat(FEAT)
    return d, t4_day3.test_frame(d)


def run(d, te, cols, tag, cfg1=CFG, cfg3=CFG, r1=None):
    if r1 is None:
        r1 = t4_day3.fit_pred(d, cols, 'Y1', cfg1, tag)
    r3 = t4_day3.fit_pred(d, cols, 'Y3', cfg3, tag)
    p1, p3 = t4_day3.finish(te, r1, r3)
    return t4_day3.metrics(te, p1, p3), r1, p1, p3


def stages():
    assert res_load().get('leak', {}).get('match', -1) == res_load().get('leak', {}).get('cells', -2), 'リーク検査が済んでいない'
    d, te = setup()
    mA, _, _, _ = run(d, te, PRE_A, 't5_A')
    old = json.loads(t5_base.J_FIT.read_text(encoding='utf-8'))['A']
    dA = {k: mA[k] - old[k] for k in ('win', 'top3', 'LL1', 'LL3')}
    assert all(abs(v) <= 1e-12 for v in dA.values()), f'段 A が 2 日目と合わない {dA}'
    rows = {'A': dict(cols=len(PRE_A), **mA)}
    kept, prev, code = list(PRE_A), mA, 'A'
    add4 = {}
    for s, new in (('B', FB), ('C', FC)):
        cols = kept + new
        tag = f't5_{s}_{code}'
        m, r1, p1, _ = run(d, te, cols, tag)
        d3, d1, dt = m['LL3'] - prev['LL3'], m['LL1'] - prev['LL1'], m['top3'] - prev['top3']
        keep = bool(d3 > 0 and m['top3'] >= prev['top3'] - 0.005)
        rows[s] = dict(cols=len(cols), prev=code, dLL3=d3, dLL1=d1, dtop3=dt, dwin=m['win'] - prev['win'], keep=keep, **m)
        print(s, len(cols), round(d3, 5), round(m['top3'], 4), keep, flush=True)
        ledger([f'3(第 5 版)', f'段 {s} の当てはめ外(拡張窓 2016〜2021・15/500/800・前 = 段 {code})',
                f"ΔLL Y3 {d3:+.3f}({d3:+.5f})・Y1 {d1:+.3f}・◎ 3 着以内率 {m['top3']:.3f}({dt * 100:+.2f} ポイント)・"
                f"◎ 勝率 {m['win']:.3f} → {'残す' if keep else '残さない'}", 'out/t5_day3.md・v3/t5_day3_res.json'])
        g = {}
        for gn, gc in GROUPS[s].items():
            cc = [c for c in cols if c not in gc]
            mg, _, _, _ = run(d, te, cc, f'{tag}_no{gc[0][0]}', r1=r1)
            g[gn] = {'LL3_without': mg['LL3'], 'dLL3': m['LL3'] - mg['LL3'], 'top3_without': mg['top3']}
            print(' 追加 4', s, gn, round(m['LL3'] - mg['LL3'], 5), flush=True)
        add4[s] = g
        if keep:
            kept, prev, code = cols, m, code + s
    res_save('stages', {'rows': rows, 'kept': kept, 'code': code, 'add4': add4})
    md()


def grid():
    d, te = setup()
    st = res_load()['stages']
    kept, code = st['kept'], st['code']
    g1 = []
    for cfg in t4_day3.GRID:
        r1 = t4_day3.fit_pred(d, kept, 'Y1', cfg, f't5_grid_{code}')
        p1, _ = t4_day3.finish(te, r1, r1)
        g1.append((t4_day3.metrics(te, p1, p1)['LL1'], cfg, r1))
    best1 = max(g1, key=lambda t: t[0])
    g3 = []
    for cfg in t4_day3.GRID:
        r3 = t4_day3.fit_pred(d, kept, 'Y3', cfg, f't5_grid_{code}')
        g3.append((t4_day3.metrics(te, *t4_day3.finish(te, best1[2], r3))['LL3'], cfg))
    best3 = max(g3, key=lambda t: t[0])
    m, _, _, _ = run(d, te, kept, f't5_grid_{code}', best1[1], best3[1])
    res_save('grid', {'Y1': list(best1[1]), 'Y3': list(best3[1]), 'kept': kept, 'code': code,
                      'g1': [[ll, list(c)] for ll, c, _ in g1], 'g3': [[ll, list(c)] for ll, c in g3], 'final': m})
    (V3 / 't5_grid.json').write_text(json.dumps({'Y1': best1[1], 'Y3': best3[1], 'kept': kept}), encoding='utf-8')
    ledger(['3(第 5 版)', f'最終形の格子 8 通り(段 {code}・{len(kept)} 列・Y1 → Y3)',
            f"Y1 {'/'.join(map(str, best1[1]))}・Y3 {'/'.join(map(str, best3[1]))}・◎ 勝率 {m['win']:.3f}・◎ 3 着以内率 {m['top3']:.3f}・"
            f"Y1 {m['LL1']:.3f}・Y3 {m['LL3']:.3f}", 'out/t5_day3.md・v3/t5_grid.json'])
    print('Y1', best1[1], 'Y3', best3[1], m['win'], m['top3'])
    md()


def v5_preds(d, te, which):
    g = res_load()['grid']
    kept, c1, c3, code = g['kept'], tuple(g['Y1']), tuple(g['Y3']), g['code']
    if which == 'pre':
        return run(d, te, kept, f't5_grid_{code}', c1, c3)
    return run(d, te, kept + DAY6, f't5_day_{code}', c1, c3)


def day():
    d, te = setup()
    m, _, _, _ = v5_preds(d, te, 'day')
    res_save('day', m)
    ledger(['3(第 5 版)', '当日版(最終形 + o_going・o_bw・o_bwchg・同じ設定)',
            f"◎ 勝率 {m['win']:.3f}・◎ 3 着以内率 {m['top3']:.3f}・Y1 {m['LL1']:.3f}・Y3 {m['LL3']:.3f}", 'out/t5_day3.md'])
    print('当日版', m['win'], m['top3'])
    md()


# ================================================================ 第 4 版の線・記録
def calib(te, p1, p3):
    x = te[['Y1', 'Y3']].assign(p1=p1, p3=p3)
    out = {}
    for nm, p, y, edges in (('p1', 'p1', 'Y1', [0, .05, .1, .2, .3, .5, 1.01]), ('p3', 'p3', 'Y3', [0, .1, .2, .4, .6, .8, 1.01])):
        b = pd.cut(x[p], edges, right=False)
        g = x.groupby(b, observed=False)
        out[nm] = [[str(k), int(len(v)), float(v[p].mean()) if len(v) else np.nan, float(v[y].mean()) if len(v) else np.nan]
                   for k, v in g]
    return out


def beta_of(te, p1):
    from scipy.optimize import minimize_scalar
    grp = te.groupby(KEY, sort=False).ngroup().to_numpy()
    y = te.Y1.to_numpy(float)
    lp = np.log(np.clip(p1, 1e-12, 1))

    def nll(b):
        z = np.exp(b * lp)
        q = np.clip(z / np.bincount(grp, z)[grp], 1e-6, 1 - 1e-6)
        return -(y * np.log(q) + (1 - y) * np.log(1 - q)).sum()
    r = minimize_scalar(nll, bounds=(0.2, 5), method='bounded')
    nr = grp.max() + 1
    return {'beta': float(r.x), 'LL1_before': -nll(1.0) / nr, 'LL1_after': -float(r.fun) / nr}


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def line():
    d5, te5 = setup()
    d4 = t5_base.load_feat(FEAT4)
    te4 = t4_day3.test_frame(d4)
    g4 = json.loads((V3 / 't4_grid.json').read_text(encoding='utf-8'))
    c1, c3, k4 = tuple(g4['Y1']), tuple(g4['Y3']), g4['kept']
    old = json.loads(t4_day3.RES.read_text(encoding='utf-8'))
    P, M, tabs = {}, {}, {}
    for v in ('pre', 'day'):
        cols = k4 if v == 'pre' else k4 + DAY6
        m4, _, p1, p3 = run(d4, te4, cols, f't5_v4{v}', c1, c3)
        ref = old['grid']['final'] if v == 'pre' else old['day']
        dd = {k: m4[k] - ref[k] for k in ('win', 'top3', 'LL1', 'LL3')}
        print('第 4 版', v, round(m4['top3'], 4), '保存値との差', dd, flush=True)
        if not all(abs(x) <= 1e-12 for x in dd.values()):
            res_save('line', {'repro_fail': v, 'diff': dd, 'm4': m4})
            md()
            raise SystemExit(f'⛔ 第 4 版の {v} が再現しない')
        M['v4' + v], P['v4' + v] = m4, (p1, p3)
        m5, _, q1, q3 = v5_preds(d5, te5, v)
        M['v5' + v], P['v5' + v] = m5, (q1, q3)
    k5 = te5[KEY + ['umaban', 'n', 'Y1', 'Y3']].reset_index(drop=True)
    k4_ = te4[KEY + ['umaban', 'n', 'Y1', 'Y3']].reset_index(drop=True)
    k4_['race_no'] = k4_.race_no.astype(int)
    assert k5.astype(str).equals(k4_.astype(str)), '第 5 版と第 4 版の表で (場・日付・R・馬番)・n・Y1・Y3 が一致しない'
    for k, (p1, p3) in P.items():
        tabs[k] = t3_eval.race_table((te5 if k.startswith('v5') else te4).assign(p1=p1, p3=p3))
    B = {k: {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in t3_eval.summary(R).items()} for k, R in tabs.items()}
    stop, pr = [], {}
    for v in ('pre', 'day'):
        a, b = tabs['v5' + v].set_index(KEY), tabs['v4' + v].set_index(KEY)
        assert a.index.equals(b.index)
        D = (a[['win', 'top3', 'll1', 'll3']] - b[['win', 'top3', 'll1', 'll3']]).add_prefix('d_').reset_index()
        bb = t3_eval.boot(D, ['d_win', 'd_top3', 'd_ll1', 'd_ll3'])
        B['diff_' + v] = {kk: list(vv) for kk, vv in bb.items()}
        pt, lo, hi = bb['d_top3']
        hw = (hi - lo) / 2
        pr[v] = {'d': pt, 'lo': lo, 'hi': hi, 'h': hw, 'p_up': phi((pt - 1.11 * hw) / (1.11 * hw / 1.96)),
                 'same_top': float((a.top_uma == b.top_uma).mean())}
        if lo <= 0:
            stop.append(v)
    kept_any = len(res_load()['stages']['code']) > 0
    # §6 追加 1・2
    ty = te5.groupby(KEY).agg(deb=('l_debut', lambda s: (s == 1).any()),
                              tr=('l_jra', lambda s: (s == 1).any())).reset_index()
    ty['tr'] = ty.tr | te5.groupby(KEY).l_nar.apply(lambda s: (s == 1).any()).to_numpy()
    ty['kind'] = np.where(ty.deb, '初出走の馬がいる', np.where(ty.tr, '転入初戦の馬がいる(初出走なし)', 'どちらもいない'))
    kinds = {}
    for k, R in tabs.items():
        Rk = R.merge(ty[KEY + ['kind']], on=KEY, how='left')
        kinds[k] = {kk: {'races': int(len(g)), 'win': float(g.win.mean()), 'top3': float(g.top3.mean()),
                         'fav_win': float(g.fav_win.mean()), 'fav_top3': float(g.fav_top3.mean())}
                    for kk, g in Rk.groupby('kind')}
    cal = {k: calib(te5 if k.startswith('v5') else te4, *P[k]) for k in P}
    beta = {k: beta_of(te5 if k.startswith('v5') else te4, P[k][0]) for k in P}
    yrs = {k: {y: float(g.top3.mean()) for y, g in R.assign(year=R.race_date.astype(str).str[:4]).groupby('year')}
           for k, R in tabs.items()}
    pp = te5[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3']].reset_index(drop=True)
    for k, (p1, p3) in P.items():
        pp[f'{k}_p1'], pp[f'{k}_p3'] = p1, p3
    pp.to_parquet(PREDS, index=False)
    res_save('line', {'metrics': M, 'boot': B, 'probe': pr, 'stop': stop, 'kept_any': kept_any, 'kinds': kinds,
                      'calib': cal, 'beta': beta, 'years': yrs})
    for v, nm in (('pre', '前日版'), ('day', '当日版')):
        q = pr[v]
        ledger(['3(第 5 版)', f'第 4 版の線({nm}・同じレース 2016〜2021・開催日ブートストラップ 2,000 回・seed 0)',
                f"第 4 版 ◎ 3 着以内率 {M['v4' + v]['top3']:.3f}(保存値と差 0)・第 5 版 {M['v5' + v]['top3']:.3f}・"
                f"差 {q['d'] * 100:+.2f} ポイント(95% {q['lo'] * 100:+.2f}〜{q['hi'] * 100:+.2f})・半幅 h {q['h'] * 100:.2f}・"
                f"確かめる期間で「上回った」の見込み {q['p_up']:.2f}", 'out/t5_day3.md・v3/t5_day3_preds.parquet'])
    ledger(['3(第 5 版)', '開ける前の止まりどころ(§5)',
            ('当たった: 区間の下限が 0 以下の版 = ' + '・'.join({'pre': '前日版', 'day': '当日版'}[x] for x in stop)
             + '。確かめる期間を開けずにユーザーに聞く') if stop else '当たらない(両版とも下限 > 0)', 'out/t5_day3.md'])
    print('差', pr, '止まりどころ', stop)
    md()


# ================================================================ md
def md():
    r = res_load()
    f = lambda t, dd=4: f"{t[0]:.{dd}f}({t[1]:.{dd}f}〜{t[2]:.{dd}f})"  # noqa: E731
    L = ['# 第 5 版 3 日目: 段 B(流れと道中)・段 C(相手関係の点)・格子・当日版・第 4 版の線(PREREG5 §4-2〜§6・§10・§11)', '',
         '台本 src/t5_day3.py(決め書に無い細部 19 個は台本の頭)。SI* = SI5。材料 v3/feat_t5_explore.parquet(118 列)。'
         '対数尤度はレースあたり(大きいほど良い)。', '']
    if 'parts' in r:
        p = r['parts']
        L += ['## 部品の点検 B・C(線は結果を見る前に決めた)', '', '| 点検 | 値 | 線 | 合否 |', '|---|---|---|---|']
        L += [f"| {c['name']} | {c['value']} | {c['line']} | {'合' if c['ok'] else '否'} |" for c in p['checks']]
        i = p['info']
        L += ['', '### 年ごとの記録(§6 追加 3)', '', '| 年 | γ | 組の数 | c_y | FR − SI* の中央値 |', '|---|---|---|---|---|']
        for y in range(2014, 2022):
            ys = str(y)
            L.append(f"| {y} | {i['gamma'][ys]:+.4f} | {i['gamma_fit'][ys]['pairs']:,} | {i['c_y'].get(ys, float('nan')):+.4f} | "
                     f"{p['level'].get(ys, float('nan')):+.3f} |")
        L += ['', f"知らない記号・名前: {i['unknown'] or 'なし'}。賞金: {i['geps']}", '',
              '部品のある割合(2016〜2021): ' + '・'.join(f'{k} {v:.3f}' for k, v in p['share'].items()), '',
              '欠けの割合(材料の表 2016〜2021): ' + '・'.join(f'{k} {v:.3f}' for k, v in p['miss'].items()), '']
        if 'rows' in p:
            L += [f"材料の表: {p['rows']:,} 行・118 列(段 A の 93 + 段 B 13 + 段 C 9 + 当日 3)。当日の 3 列は feat_t4_explore と一致(assert)・"
                  'オッズ・人気・結果の列なし(assert)。', '']
    if 'leak' in r:
        z = r['leak']
        L += ['## リーク検査(§10・前日版の全 115 列)', '',
              f"抜き取り {z['days']} 日(うち 1 月 {z['jan_days']} 日・seed 0)。一致 {z['match_days']}/{z['days']} 日・"
              f"{z['match']:,}/{z['cells']:,} セル = {100 * z['match'] / z['cells']:.2f} %", '']
        bad = [x for x in z['per_day'] if x['bad_cols']]
        L += [f"- {x['date']}: {'・'.join(x['bad_cols'])}" for x in bad] + ([''] if bad else [])
    if 'stages' in r:
        s = r['stages']
        L += ['## 段 B・C の当てはめ外(拡張窓 2016〜2021・葉 15・最小 500・木 800)', '',
              '| 段 | 列 | 前 | ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1 | 対数尤度 Y3 | ΔLL Y3 | ΔLL Y1 | ◎ 3 着以内率の差 | 年ごとの ◎ 3 着以内率 | 残す |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for k, x in s['rows'].items():
            yy = '・'.join(f"{x[f'top3_{y}']:.3f}" for y in EVAL)
            L.append(f"| {k} | {x['cols']} | {x.get('prev', '')} | {x['win']:.4f} | {x['top3']:.4f} | {x['LL1']:.5f} | {x['LL3']:.5f} | "
                     f"{x.get('dLL3', float('nan')):+.5f} | {x.get('dLL1', float('nan')):+.5f} | {x.get('dtop3', float('nan')) * 100:+.2f} | "
                     f"{yy} | {('○' if x['keep'] else '×') if 'keep' in x else '(2 日目)'} |")
        L += ['', f"残した形: 段 {s['code']}・{len(s['kept'])} 列。(この決まりは ◎ を最大 0.49 ポイント下げる段を残しうる)", '',
              '§6 追加 4(群を 1 つ外したときの Y3 の対数尤度の差・正 = その群が効いた・採否には使わない):', '',
              '| 段 | 外した群 | ΔLL Y3 | 外したときの ◎ 3 着以内率 |', '|---|---|---|---|']
        for st, g in s['add4'].items():
            for gn, v in g.items():
                L.append(f"| {st} | {gn} | {v['dLL3']:+.5f} | {v['top3_without']:.4f} |")
        L.append('')
    if 'grid' in r:
        g = r['grid']
        L += [f"## 最終形の格子(段 {g['code']}・Y1 を先に選び、その p1 で Y3 を選ぶ)", '', '| 目的 | 葉/最小/木 | 対数尤度 | 選択 |',
              '|---|---|---|---|']
        L += [f"| Y1 | {c[0]}/{c[1]}/{c[2]} | {ll:.5f} | {'○' if c == g['Y1'] else ''} |" for ll, c in g['g1']]
        L += [f"| Y3 | {c[0]}/{c[1]}/{c[2]} | {ll:.5f} | {'○' if c == g['Y3'] else ''} |" for ll, c in g['g3']]
        m = g['final']
        L += ['', f"最終形(前日版): ◎ 勝率 {m['win']:.4f}・◎ 3 着以内率 {m['top3']:.4f}・対数尤度 Y1 {m['LL1']:.5f}・Y3 {m['LL3']:.5f}", '']
    if 'day' in r:
        m = r['day']
        L += [f"当日版(最終形 + 段 6 の 3 列・同じ設定): ◎ 勝率 {m['win']:.4f}・◎ 3 着以内率 {m['top3']:.4f}・"
              f"対数尤度 Y1 {m['LL1']:.5f}・Y3 {m['LL3']:.5f}", '']
    if 'line' in r and 'boot' in r['line']:
        v = r['line']
        B = v['boot']
        L += ['## 第 4 版の線(同じレース 2016〜2021・開催日ブートストラップ 2,000 回・seed 0・95% 区間)', '',
              '第 4 版は t4_grid.json の設定で学び直し、out/t4_day3.md の保存値(前日版 0.6586・当日版 0.6647)と差 0 で一致。', '',
              '| 版 | ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1 | 対数尤度 Y3 | 1 番人気 3 着以内率 |', '|---|---|---|---|---|---|']
        for k, nm in (('v5pre', '第 5 版 前日版'), ('v4pre', '第 4 版 前日版'), ('v5day', '第 5 版 当日版'), ('v4day', '第 4 版 当日版')):
            L.append(f"| {nm} | {f(B[k]['win'])} | {f(B[k]['top3'])} | {f(B[k]['ll1'])} | {f(B[k]['ll3'])} | {f(B[k]['fav_top3'])} |")
        L += ['', '| 差(第 5 版 − 第 4 版・レースごとの対)| ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1 | 対数尤度 Y3 | 半幅 h | ◎ が同じ馬 | 「上回った」の見込み |',
              '|---|---|---|---|---|---|---|---|']
        for vv, nm in (('pre', '前日版'), ('day', '当日版')):
            D, q = B['diff_' + vv], v['probe'][vv]
            L.append(f"| {nm} | {f(D['d_win'])} | {f(D['d_top3'])} | {f(D['d_ll1'])} | {f(D['d_ll3'])} | {q['h']:.4f} | "
                     f"{q['same_top']:.3f} | {q['p_up']:.2f} |")
        pu = v['probe']['pre']['p_up'] * v['probe']['day']['p_up']
        L += ['', f"確かめる期間の半幅 ≈ h × 1.11。両版とも「上回った」の見込み(積・独立とみた近似){pu:.2f}。", '',
              '### 年ごとの ◎ 3 着以内率', '', '| 年 | 第 5 版 前日 | 第 4 版 前日 | 第 5 版 当日 | 第 4 版 当日 |', '|---|---|---|---|---|']
        for y in sorted(v['years']['v5pre']):
            L.append(f'| {y} | ' + ' | '.join(f"{v['years'][k][y]:.3f}" for k in ('v5pre', 'v4pre', 'v5day', 'v4day')) + ' |')
        st = v['stop']
        L += ['', ('**開ける前の止まりどころ(§5 ②)に当たった**: 第 5 版 − 第 4 版の ◎ 3 着以内率の 95% 区間の下限が 0 以下の版 = '
                   + '・'.join({'pre': '前日版', 'day': '当日版'}[x] for x in st) + '。確かめる期間は開けずにユーザーに聞く。')
              if st else '開ける前の止まりどころ(§5): ① 段を残した・② 前日版・当日版とも下限 > 0 → 当たらない。', '']
        L += ['## §6 追加 1: レースの種類ごと(◎ − 1 番人気・3 着以内率)', '',
              '| 版 | 種類 | R | ◎ 勝率 | ◎ 3 着以内率 | 1 番人気 3 着以内率 | 差 |', '|---|---|---|---|---|---|---|']
        for k, nm in (('v5pre', '第 5 版 前日'), ('v4pre', '第 4 版 前日'), ('v5day', '第 5 版 当日'), ('v4day', '第 4 版 当日')):
            for kk, x in v['kinds'][k].items():
                L.append(f"| {nm} | {kk} | {x['races']:,} | {x['win']:.3f} | {x['top3']:.3f} | {x['fav_top3']:.3f} | "
                         f"{(x['top3'] - x['fav_top3']) * 100:+.2f} |")
        L += ['', '## §6 追加 2: 確率の当たり具合(見込みの平均 / 実際・馬の数)と温度 β(記録だけ・予想表には当てない)', '']
        for k, nm in (('v5pre', '第 5 版 前日'), ('v4pre', '第 4 版 前日'), ('v5day', '第 5 版 当日'), ('v4day', '第 4 版 当日')):
            c, b = v['calib'][k], v['beta'][k]
            L.append(f"- {nm} p1: " + '・'.join(f"{a} {m:.3f}/{y:.3f}({n:,})" for a, n, m, y in c['p1']))
            L.append(f"- {nm} p3: " + '・'.join(f"{a} {m:.3f}/{y:.3f}({n:,})" for a, n, m, y in c['p3']))
            L.append(f"- {nm} β {b['beta']:.3f}(Y1 の対数尤度 {b['LL1_before']:.5f} → {b['LL1_after']:.5f})")
        L.append('')
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')


if __name__ == '__main__':
    {'parts': parts, 'leak': leak, 'stages': stages, 'grid': grid, 'day': day, 'line': line, 'md': md}[sys.argv[1]]()
