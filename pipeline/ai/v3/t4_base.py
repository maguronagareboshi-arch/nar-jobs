# -*- coding: utf-8 -*-
"""第 4 版 2 日目(PREREG4 §3・§10・§11): 土台の部品(格・物差し・その日の速さ・SI/テン/上がり・能力の見込み・
レース水準・相手関係)を 2014〜2021 の南関の走りについて作る。2022-01-01 以降は読まない(load_archive の見張り)。

  py -3.12 -X utf8 src/t4_base.py build   # → v3/t4_base_2014_2021.parquet(出走馬 1 頭 1 行。取消・除外は除く)
  py -3.12 -X utf8 src/t4_base.py check   # §11 の部品の点検 4 つ → out/t4_day2_parts.md
  py -3.12 -X utf8 src/t4_base.py leak    # §10 のリーク検査(20 日・seed 0・うち 4 日は 1 月)→ out/t4_day2_parts.md

■ コードの番号表(当てはめ外を見る前に固定)
  b_g     C3 1・C2 2・C1 3・B3 4・B2 5・B1 6・A2 7・A1 8・混合は平均・重賞/準重賞/OP 9。
          2 歳限定・3 歳限定(condition が「2歳」「3歳」)と読めないレースは欠け。
  b_young 0 = 若馬でない(condition が 2歳/3歳 以外)。若馬は 10×年齢 + 区分:
          1 新馬・2 未格付/未受賞/未出走・3 組・4 賞金条件(○万円)・5 重賞/特別(重賞/OP・選抜・選定・特選・特別・名前付き)・6 その他
          (読む順: 新馬 → 未格付系 → 重賞/OP の語 → 賞金 → 組 → 選抜/特別/名前付き → その他)
  b_age   condition: 一般 0・2歳 2・3歳 3・4歳 4・3歳以上 13・4歳以上 14(ほかは欠け)
  b_kind  0 平場・1 特別(「特別」か、格/年齢の前に名前がある)・2 選抜/選定(特選を含む)・3 重賞/準重賞/OP・4 交流(交流・JRA・Jpn)
          (上の番号が優先)
  l_region・h_mark は 3 日目の段(3・5)の列なので、この台本では作らない(3 日目の台本の頭に書く)。

■ 決め書に無い細部(この台本で決めた。見た後は変えない)
  1. 重賞/OP の語 = 重賞・オープン(直後が「賞」でない)・OP(英字に挟まれない)・(S1〜3)・(G1〜3)・Jpn。
  2. 組の読み: 格/年齢の最初の印(A1〜C3・○歳・○上)より後だけを読む(前はレースの名前)。括弧・○万円・○歳(以上)・○上・格の印を
     消してから空白で区切り、各かたまりで「十 + 一〜九」= 11〜19、ほかの漢数字は 1 字 1 組、数字の並びは 10〜19 の 2 桁を優先して
     前から切る(「1112」= 11・12)。上・下はそのかたまりに番号が無いときだけ 1・2。
  3. 区分 k の 30 R は、その年の窓(y−3〜y−1)で値のあるレースを量(走破・前半・上がり)ごとに数える。「1 つ下とまとめる」は
     まとめ先も足りなければ先へたどる。重賞/OP を A1 とまとめるのも 30 R 未満のとき。若馬の「その他」が足りなければ
     その年齢を全部 1 つ(Y2・Y3)にする。
  4. 当てはめ(b・δ・D)に使うのは、自分のコースが 30 R 以上あり区分 k が読めるレースだけ。D_生 も同じレースだけで作る
     (近い距離の b_c を借りたコースと読めないレースは D_生 に入れない。SI は借りた b_c とその日の D で作る)。
  5. 馬場状態で縮めるときの「その日その場の馬場」= その日その場のレースの馬場で一番多いもの(同数は若い R)。窓に無ければ場の平均、
     それも無ければ 0。
  6. 打ち切り(勝ち馬 + 2.0 秒 × d/1000)は走破 T だけにかける。前半 F = 打ち切り前の T − 上がり 3F。
  7. 勝ち馬の時計 = そのレースの時計の最小。レースの値 = 着順 1〜3 の馬の平均(その量のある馬だけ)。
  8. 事前の値の区分は走破の当てはめの k(まとめた後)。区分が読めないレースは窓の全出走馬の SI の平均。
  9. a_si1 = 前の南関の走り(取消・除外を除く)の SI(中止などで SI が無ければ欠け)。b_lv1 も前の南関の走りの b_lv。
  10. 相手関係: 標準偏差は母標準偏差(ddof 0)。gap = 自分 − 1 位(0 以下)。b_lv は a_ab の上位 5 頭(5 頭未満なら全頭)の平均。
  11. リーク検査で比べるのは、レースの前に決まる部品(格 6 列・b_c 3 つ・δ・事前の値・a_si1・a_siw・a_ab・b_lv・b_lv1・k_* 7 列)。
      その日の D と SI はその日の結果から作るもの(次の走りから使う)なので比べない。
  12. 抜き取り: 2016〜2021 の南関の開催日から seed 0 で、1 月の開催日を違う年から 4 日(年を 4 つ選んでその年の 1 月から 1 日)、
      残り 16 日を 1 月以外から選ぶ。
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_outcomes import load_archive  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
OUT = V3 / 't4_base_2014_2021.parquet'
MD = REPO / 'out/t4_day2_parts.md'
RK = ['track', 'race_date', 'race_no']
NANKAN = ['浦和', '船橋', '大井', '川崎']
OLD = ['C3', 'C2', 'C1', 'B3', 'B2', 'B1', 'A2', 'A1']
GPT = {c: i + 1 for i, c in enumerate(OLD)}
AGE = {'一般': 0, '2歳': 2, '3歳': 3, '4歳': 4, '3歳以上': 13, '4歳以上': 14}
KAN = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
DIV = {'T': lambda d: d / 1000, 'F': lambda d: (d - 600) / 1000, 'L': lambda d: np.full(len(d), 0.6)}
MIN_R = 30
HALF = 90.0
LEAK_COLS = ['b_g', 'b_kumi', 'b_young', 'b_age', 'b_kind', 'b_prize', 'b_unread', 'bc_T', 'bc_F', 'bc_L', 'dl_T',
             'a_prior', 'a_si1', 'a_siw', 'a_ab', 'b_lv', 'b_lv1',
             'k_ab_rank', 'k_ab_z', 'k_ab_gap', 'k_si_rank', 'k_si_z', 'k_si_gap', 'k_ab_sd']
RES_RUN = ['finish', 'time_raw', 'time_sec', 'margin', 'last3f', 'popularity', 'body_weight', 'body_weight_change']
RES_RACE = ['going', 'weather', 'field_size', 'race_last4f', 'race_last3f', 'furlongs', 'corners']

RE_JS = re.compile(r'重賞|オープン(?!賞)|(?<![A-Za-z])OP(?![A-Za-z])|\(S[123]\)|\(G[123]\)|Jpn')
RE_CLS = re.compile(r'(?<![A-Za-z])([ABC])([123])')
RE_ANCHOR = re.compile(r'(?<![A-Za-z])[ABC][123]|\d歳|\d上')


# ---------------------------------------------------------------- 3-1 格
def _nums(tok):
    out, i = [], 0
    while i < len(tok):
        ch = tok[i]
        if ch == '十' and i + 1 < len(tok) and tok[i + 1] in '一二三四五六七八九':
            out.append(10 + KAN[tok[i + 1]]); i += 2
        elif ch in KAN:
            out.append(KAN[ch]); i += 1
        elif ch.isdigit():
            if i + 1 < len(tok) and tok[i + 1].isdigit() and 10 <= int(tok[i:i + 2]) <= 19:
                out.append(int(tok[i:i + 2])); i += 2
            else:
                out.append(int(ch)); i += 1
        else:
            i += 1
    if not out:
        if '上' in tok:
            out = [1]
        elif '下' in tok:
            out = [2]
    return out


def parse_name(name, cond):
    s = unicodedata.normalize('NFKC', str(name))
    ns = re.sub(r'\s+', '', s)
    c = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(cond))).replace('サラブレッド系', '')
    b_age = AGE.get(c, np.nan)
    young = c in ('2歳', '3歳')
    m = RE_ANCHOR.search(s)
    prefix = re.sub(r'\s+', '', s[:m.start()] if m else s)
    kumi = np.nan
    rest = ''
    if m:
        rest = s[m.start():]
        rest = re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', rest)
        rest = re.sub(r'\d+万円?(以下|未満|以上)?', ' ', rest)
        rest = re.sub(r'\d+歳(以上)?|\d上', ' ', rest)
        rest = RE_CLS.sub(' ', rest)
        nums = [n for tok in rest.split() for n in _nums(tok)]
        if nums:
            kumi = float(np.mean(nums))
    js = bool(RE_JS.search(ns))
    sen = bool(re.search(r'選抜|選定|特選', ns))
    toku = ('特別' in ns) or bool(prefix)
    if re.search(r'交流|JRA|Jpn', ns):
        kind = 4
    elif js:
        kind = 3
    elif sen:
        kind = 2
    elif toku:
        kind = 1
    else:
        kind = 0
    cls = RE_CLS.findall(ns)
    b_g, k0, yc = np.nan, None, 0
    if young:
        a = 2 if c == '2歳' else 3
        if '新馬' in ns:
            code = 1
        elif re.search(r'未格付|未受賞|未出走', ns):
            code = 2
        elif js:
            code = 5
        elif '万' in ns:
            code = 4
        elif not np.isnan(kumi):
            code = 3
        elif sen or toku:
            code = 5
        else:
            code = 6
        yc = 10 * a + code
        k0 = f'Y{a}_{code}'
        unread = code == 6
    else:
        if js:
            b_g, k0 = 9.0, 'JS'
        elif cls:
            pts = [GPT[x + y] for x, y in cls]
            b_g = float(np.mean(pts))
            k0 = OLD[max(pts) - 1]
        unread = np.isnan(b_g)
    return b_g, kumi, yc, b_age, kind, k0, int(unread)


def prize(p):
    m = re.search(r'\d+', str(p))
    if not m or int(m.group()) <= 0:
        return np.nan
    return float(np.log10(int(m.group())))


# ---------------------------------------------------------------- 読み込み
def load():
    runs = load_archive('runs')
    runs = runs[runs.track.isin(NANKAN) & (runs.race_date >= '2014-01-01')].copy()
    facts = load_archive('facts')[['track', 'race_date', 'race_no', 'umaban', 'horse_key']]
    facts = facts[facts.track.isin(NANKAN)].rename(columns={'umaban': 'runner_number'})
    runs = runs.merge(facts, on=RK + ['runner_number'], how='left')
    races = load_archive('races')
    races = races[races.track.isin(NANKAN) & (races.race_date >= '2014-01-01')].copy()
    assert races.race_date.max() < '2022-01-01' and runs.race_date.max() < '2022-01-01'
    return runs.reset_index(drop=True), races.reset_index(drop=True)


# ---------------------------------------------------------------- 3-2 物差し
def kmap_make(kc):
    kc = dict(kc)
    m = {}

    def old_final(c, seen=()):
        if kc.get(c, 0) >= MIN_R or c in seen:
            return c
        i = OLD.index(c)
        return old_final(OLD[1] if c == 'C3' else OLD[i - 1], seen + (c,))
    for c in OLD:
        m[c] = old_final(c)
    m['JS'] = 'JS' if kc.get('JS', 0) >= MIN_R else old_final('A1')
    for a in (2, 3):
        codes = [f'Y{a}_{j}' for j in range(1, 7)]
        small = [k for k in codes if kc.get(k, 0) < MIN_R and k != f'Y{a}_6']
        other_n = kc.get(f'Y{a}_6', 0) + sum(kc.get(k, 0) for k in small)
        if other_n >= MIN_R:
            for k in codes:
                m[k] = f'Y{a}_6' if (k in small or k == f'Y{a}_6') else k
        else:
            for k in codes:
                m[k] = f'Y{a}'
    return m


def course_b(courses, own):
    """own: {course: b}。近い距離(±200 m・同じ場・回りは問わない・同じ差なら短い方)から借りる。"""
    by_trk = {}
    for c, b in own.items():
        t, d, _ = c.split('_')
        by_trk.setdefault(t, []).append((int(d), b))
    out = {}
    for c in courses:
        if c in own:
            out[c] = own[c]; continue
        t, d, _ = c.split('_'); d = int(d)
        cand = sorted(((abs(dd - d), dd, b) for dd, b in by_trk.get(t, []) if abs(dd - d) <= 200))
        out[c] = cand[0][2] if cand else np.nan
    return out


def fit_window(W):
    v = W.v.values
    cs, ks, ds = W.course.values, W.k.values, W.dtk.values
    dl = np.zeros(len(W)); D = np.zeros(len(W))
    s = None
    for _ in range(10):
        b = pd.Series(v - dl - D).groupby(cs).transform('median').values
        s = pd.Series(v - b - D).groupby(ks).median()
        s = s - s['C1']
        dl = pd.Series(ks).map(s).values
        D = pd.Series(v - b - dl).groupby(ds).transform('median').values
    own = pd.Series(b, index=cs).groupby(level=0).first().to_dict()
    Dd = pd.Series(D, index=ds).groupby(level=0).first()
    return own, s.to_dict(), Dd


def races_table(races):
    R = races.copy()
    P = [parse_name(n, c) for n, c in zip(R.race_name, R.condition)]
    P = pd.DataFrame(P, columns=['b_g', 'b_kumi', 'b_young', 'b_age', 'b_kind', 'k0', 'b_unread'], index=R.index)
    R = pd.concat([R, P], axis=1)
    R['b_prize'] = R.prize_yen.map(prize)
    R['year'] = R.race_date.str[:4].astype(int)
    dirc = np.where(R.direction.notna(), R.direction.astype(str),
                    np.where(R.track == '大井', '右', '左'))
    R['course'] = R.track + '_' + R.distance_m.astype(int).astype(str) + '_' + dirc
    R['dtk'] = R.race_date + '_' + R.track
    def _mode(x):
        v = list(x.dropna())
        return max(v, key=lambda s: (v.count(s), -v.index(s))) if v else np.nan
    g = R.sort_values('race_no').groupby('dtk').going.agg(_mode)
    R['gmode'] = R.dtk.map(g)
    return R


def build(runs, races, log=print):
    R = races_table(races)
    U = runs[~runs.finish_note.isin(['取消', '除外'])].copy()
    U = U.merge(R[RK + ['distance_m', 'year']], on=RK, how='left')
    U['F'] = U.time_sec - U.last3f
    top = U[U.finish <= 3]
    val = top.groupby(RK).agg(vT=('time_sec', 'mean'), vF=('F', 'mean'), vL=('last3f', 'mean')).reset_index()
    R = R.merge(val, on=RK, how='left')
    d = R.distance_m.values.astype(float)
    for q in 'TFL':
        R['v' + q] = R['v' + q] / DIV[q](d)
    years = sorted(R.year.unique())
    kmaps = {}
    for q in 'TFL':
        for c in ['bc_', 'dl_', 'r_', 'Draw_', 'n_', 'D_']:
            R[c + q] = np.nan
        for y in years:
            win = [2014] if y == 2014 else [x for x in range(y - 3, y) if x >= 2014]
            Wa = R[R.year.isin(win) & R['v' + q].notna()]
            cc = Wa.course.value_counts()
            km = kmap_make(Wa.k0.value_counts())
            if q == 'T':
                kmaps[y] = km
            ownset = set(cc[cc >= MIN_R].index)
            W = Wa[Wa.course.isin(ownset)].assign(k=Wa.k0.map(km), v=Wa['v' + q])
            W = W[W.k.notna()]
            own, delta, Dd = fit_window(W)
            gm = pd.DataFrame({'D': Dd}).join(W.drop_duplicates('dtk').set_index('dtk')[['track', 'gmode']])
            Dm_tg = gm.groupby(['track', 'gmode']).D.mean().to_dict()
            Dm_t = gm.groupby('track').D.mean().to_dict()
            iy = R.index[R.year == y]
            Ry = R.loc[iy]
            bmap = course_b(Ry.course.unique(), own)
            bc = Ry.course.map(bmap).astype(float)
            bown = Ry.course.map(own).astype(float)
            dl = Ry.k0.map(km).map(delta).astype(float)
            r = Ry['v' + q] - bown - dl
            Draw = r.groupby(Ry.dtk).transform('median')
            n = r.notna().groupby(Ry.dtk).transform('sum')
            Dm = pd.Series([Dm_tg.get((t, gg), Dm_t.get(t, 0.0)) for t, gg in zip(Ry.track, Ry.gmode)],
                           index=iy).fillna(0.0)
            D = np.where(n > 0, n / (n + 5) * Draw + 5 / (n + 5) * Dm, Dm)
            R.loc[iy, 'bc_' + q] = bc.values
            R.loc[iy, 'dl_' + q] = dl.values
            R.loc[iy, 'r_' + q] = r.values
            R.loc[iy, 'Draw_' + q] = Draw.values
            R.loc[iy, 'n_' + q] = n.values
            R.loc[iy, 'D_' + q] = D
    R['kT'] = [kmaps[y].get(k) if k is not None else None for y, k in zip(R.year, R.k0)]
    rcols = ['b_g', 'b_kumi', 'b_young', 'b_age', 'b_kind', 'b_prize', 'b_unread', 'k0', 'kT', 'course', 'dtk',
             'gmode'] + [c + q for q in 'TFL' for c in ['bc_', 'dl_', 'r_', 'Draw_', 'n_', 'D_']]
    U = U.merge(R[RK + rcols], on=RK, how='left')
    # SI・テン・上がり
    dd = U.distance_m.values.astype(float)
    win_t = U.groupby(RK).time_sec.transform('min')
    Tt = np.minimum(U.time_sec, win_t + 2.0 * dd / 1000)
    B = U.bc_T * dd / 1000
    U['SI'] = 80 + (1000 / B) * (B - Tt + U.D_T * dd / 1000) + 2 * (U.carried_weight - 55)
    BF = U.bc_F * (dd - 600) / 1000
    U['ten_i'] = 80 + (1000 / BF) * (BF - U.F + U.D_F * (dd - 600) / 1000)
    BL = U.bc_L * 0.6
    U['up_i'] = 80 + (1000 / BL) * (BL - U.last3f + U.D_L * 0.6)
    # 事前の値(区分 k の y−3〜y−1 の全出走馬の SI の平均)
    U['a_prior'] = np.nan
    for y in years:
        win = [2014] if y == 2014 else [x for x in range(y - 3, y) if x >= 2014]
        Wr = U[U.year.isin(win) & U.SI.notna()]
        km = kmaps[y]
        mk = Wr.k0.map(km)
        means = Wr.SI.groupby(mk).mean().to_dict()
        allm = Wr.SI.mean()
        iy = U.index[U.year == y]
        U.loc[iy, 'a_prior'] = [means.get(km.get(k), allm) if k is not None else allm for k in U.loc[iy, 'k0']]
    # 走歴(南関・取消/除外を除く)
    U['hk'] = U.horse_key.fillna(U.horse_name)
    U['dnum'] = (pd.to_datetime(U.race_date) - pd.Timestamp('2000-01-01')).dt.days
    U = U.sort_values(['hk', 'race_date', 'race_no']).reset_index(drop=True)
    hid = pd.factorize(U.hk)[0].astype(np.int64)
    key = hid * 100000 + U.dnum.values
    S = U.SI.notna().values
    Skey, Ssi, Sd = key[S], U.SI.values[S], U.dnum.values[S]
    pos = np.searchsorted(Skey, key, 'left')
    hst = np.searchsorted(Skey, hid * 100000, 'left')
    sw = np.zeros(len(U)); swsi = np.zeros(len(U))
    for j in range(1, 6):
        idx = pos - j
        ok = idx >= hst
        ii = np.where(ok, idx, 0)
        w = np.where(ok, 0.5 ** ((U.dnum.values - Sd[ii]) / HALF), 0.0)
        sw += w; swsi += np.where(ok, w * Ssi[ii], 0.0)
    U['a_siw'] = np.where(sw > 0, swsi / np.where(sw > 0, sw, 1), np.nan)
    U['a_ab'] = (swsi + U.a_prior.values) / (sw + 1)
    same = hid[1:] == hid[:-1]
    prev_si = np.r_[np.nan, np.where(same, U.SI.values[:-1], np.nan)]
    U['a_si1'] = prev_si
    # レース水準・相手関係
    g = U.groupby(RK)
    U['b_lv'] = g.a_ab.transform(lambda x: x.nlargest(5).mean())
    U['b_lv1'] = np.r_[np.nan, np.where(same, U.b_lv.values[:-1], np.nan)]
    for src, nm in [('a_ab', 'ab'), ('a_si1', 'si')]:
        x = U[src]
        cnt = g[src].transform('count')
        U[f'k_{nm}_rank'] = g[src].rank(ascending=False, method='average') / cnt
        mu = g[src].transform('mean')
        sd = g[src].transform(lambda z: z.std(ddof=0))
        U[f'k_{nm}_z'] = (x - mu) / np.maximum(sd, 1.0)
        U[f'k_{nm}_gap'] = x - g[src].transform('max')
        if nm == 'ab':
            U['k_ab_sd'] = sd
    keep = RK + ['runner_number', 'horse_key', 'hk', 'horse_name', 'year', 'distance_m', 'carried_weight', 'finish',
                 'finish_note', 'time_sec', 'last3f'] + rcols + ['SI', 'ten_i', 'up_i'] + LEAK_COLS[11:]
    keep = list(dict.fromkeys(keep))
    return U[keep].sort_values(RK + ['runner_number']).reset_index(drop=True)


# ---------------------------------------------------------------- md
def write_md():
    ck = V3 / 't4_day2_check.json'; lk = V3 / 't4_day2_leak.json'
    L = ['# 第 4 版 2 日目: 土台の部品の点検とリーク検査(PREREG4 §11・§10)', '',
         '台本 src/t4_base.py(build・check・leak)。出力 C:/Users/kouki/nankan_ai/v3/t4_base_2014_2021.parquet。', '']
    if ck.exists():
        c = json.loads(ck.read_text(encoding='utf-8'))
        L += [f"行数 {c['rows']:,}(2014〜2021 の南関の出走・取消/除外を除く)・レース {c['races']:,}", '',
              '## 部品の点検(線は結果を見る前に決めた)', '', '| 点検 | 値 | 線 | 合否 |', '|---|---|---|---|']
        for r in c['checks']:
            L.append(f"| {r['name']} | {r['value']} | {r['line']} | {r['ok']} |")
        L += ['', '古馬の格ごとの SI の中央値(2016〜2021・混合でない格): ' +
              '・'.join(f'{k} {v:.2f}' for k, v in c['class_median'].items()), '',
              f"読めないレースの内訳(2015〜2021): 古馬 {c['unread_old']}・若馬(その他){c['unread_young']}・"
              f"年齢条件の知らない書き方 {c['age_unknown']}", '',
              '## 欠けの割合(列ごと・2015〜2021 の行)', '', '| 列 | 欠け |', '|---|---|']
        for k, v in c['missing'].items():
            L.append(f'| {k} | {v:.4f} |')
        L.append('')
    if lk.exists():
        z = json.loads(lk.read_text(encoding='utf-8'))
        L += ['## リーク検査(§10: 20 日・seed 0・うち 4 日は 1 月)', '',
              f"比べた列 {len(z['cols'])} 個({'・'.join(z['cols'])})", '',
              f"一致 {z['match_days']}/{z['days']} 日・値 {z['match_vals']:,}/{z['vals']:,}・行 {z['rows']:,}", '',
              '| 日 | 行 | 一致しない値 |', '|---|---|---|']
        for r in z['per_day']:
            L.append(f"| {r['date']} | {r['rows']} | {r['bad']} |")
        L.append('')
    MD.write_text('\n'.join(L), encoding='utf-8')


# ---------------------------------------------------------------- 点検
def check():
    U = pd.read_parquet(OUT)
    E = U[U.year >= 2015]
    RR = E.drop_duplicates(RK)
    unread = RR.b_unread.mean()
    unread_old = int(((RR.b_young == 0) & (RR.b_unread == 1)).sum())
    unread_young = int(((RR.b_young > 0) & (RR.b_unread == 1)).sum())
    age_unk = int(RR.b_age.isna().sum())
    # 奇数 R・偶数 R の D_生(走破)
    R6 = U[U.year >= 2016].drop_duplicates(RK)
    R6 = R6[R6.r_T.notna()]
    od = R6[R6.race_no % 2 == 1].groupby('dtk').r_T.median()
    ev = R6[R6.race_no % 2 == 0].groupby('dtk').r_T.median()
    j = pd.concat([od.rename('o'), ev.rename('e')], axis=1).dropna()
    c_oe = float(j.o.corr(j.e))
    # 続けての 2 走
    V = U.sort_values(['hk', 'race_date', 'race_no']).reset_index(drop=True)
    dn = (pd.to_datetime(V.race_date) - pd.Timestamp('2000-01-01')).dt.days.values
    same = (V.hk.values[1:] == V.hk.values[:-1])
    gap = dn[1:] - dn[:-1]
    s0, s1 = V.SI.values[:-1], V.SI.values[1:]
    ok = same & (gap <= 90) & ~np.isnan(s0) & ~np.isnan(s1) & (V.year.values[1:] >= 2015)
    c_si = float(np.corrcoef(s0[ok], s1[ok])[0, 1])
    # 格の順
    C = U[(U.year >= 2016) & U.SI.notna() & U.b_g.isin(range(1, 9))]
    med = C.groupby('b_g').SI.median()
    cm = {OLD[int(k) - 1]: float(v) for k, v in med.items()}
    order_ok = len(med) == 8 and bool(np.all(np.diff(med.sort_index().values) > 0))
    miss_cols = ['b_g', 'b_kumi', 'b_prize', 'b_age', 'bc_T', 'bc_F', 'bc_L', 'D_T', 'SI', 'ten_i', 'up_i', 'a_prior',
                 'a_si1', 'a_siw', 'a_ab', 'b_lv', 'b_lv1', 'k_ab_rank', 'k_si_rank', 'k_ab_sd']
    res = {'rows': int(len(U)), 'races': int(U.drop_duplicates(RK).shape[0]),
           'checks': [
               {'name': '格の読めないレース(2015〜2021)', 'value': f'{unread:.4f}({int(RR.b_unread.sum())}/{len(RR)} R)',
                'line': '≤ 0.01', 'ok': '合' if unread <= 0.01 else '否'},
               {'name': '奇数 R/偶数 R の D_生(走破)の相関(2016〜2021)', 'value': f'{c_oe:.3f}({len(j)} 日×場)',
                'line': '≥ 0.6', 'ok': '合' if c_oe >= 0.6 else '否'},
               {'name': '続けての 2 走(90 日以内)の SI の相関(後の走りが 2015〜2021)', 'value': f'{c_si:.3f}({int(ok.sum())} 組)',
                'line': '≥ 0.5', 'ok': '合' if c_si >= 0.5 else '否'},
               {'name': '古馬の格ごとの SI の中央値の順(2016〜2021)', 'value': '順どおり' if order_ok else '順が崩れる',
                'line': 'C3<C2<C1<B3<B2<B1<A2<A1', 'ok': '合' if order_ok else '否'}],
           'class_median': cm, 'unread_old': unread_old, 'unread_young': unread_young, 'age_unknown': age_unk,
           'missing': {c: float(E[c].isna().mean()) for c in miss_cols}}
    (V3 / 't4_day2_check.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    write_md()
    for r in res['checks']:
        print(r['name'], r['value'], r['ok'])
    print(cm)


# ---------------------------------------------------------------- リーク検査
def pick_days(races):
    ds = sorted(races[(races.race_date >= '2016-01-01')].race_date.unique())
    rng = np.random.default_rng(0)
    jan = [x for x in ds if x[5:7] == '01']
    yrs = rng.choice(sorted({x[:4] for x in jan}), 4, replace=False)
    days = [str(rng.choice(sorted(x for x in jan if x[:4] == y))) for y in yrs]
    rest = sorted(x for x in ds if x[5:7] != '01')
    days += [str(x) for x in rng.choice(rest, 16, replace=False)]
    return sorted(days)


def leak():
    runs, races = load()
    full = pd.read_parquet(OUT)
    days = pick_days(races)
    per, tot_v, tot_m, rows = [], 0, 0, 0
    for X in days:
        r = runs[runs.race_date <= X].copy()
        m = r.race_date == X
        r.loc[m, RES_RUN] = np.nan
        r.loc[m & ~r.finish_note.isin(['取消', '除外']), 'finish_note'] = np.nan
        c = races[races.race_date <= X].copy()
        c.loc[c.race_date == X, RES_RACE] = np.nan
        B = build(r, c)
        a = B[B.race_date == X].set_index(RK + ['runner_number'])[LEAK_COLS].sort_index()
        b = full[full.race_date == X].set_index(RK + ['runner_number'])[LEAK_COLS].sort_index()
        assert a.index.equals(b.index), X
        av, bv = a.values.astype(float), b.values.astype(float)
        eq = (np.isnan(av) & np.isnan(bv)) | (np.abs(av - bv) <= 1e-9)
        bad = int((~eq).sum())
        per.append({'date': X, 'rows': int(len(a)), 'bad': bad})
        tot_v += eq.size; tot_m += int(eq.sum()); rows += len(a)
        print(X, len(a), bad, flush=True)
    z = {'days': len(days), 'match_days': sum(p['bad'] == 0 for p in per), 'vals': tot_v, 'match_vals': tot_m,
         'rows': rows, 'cols': LEAK_COLS, 'per_day': per}
    (V3 / 't4_day2_leak.json').write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding='utf-8')
    write_md()
    print('一致', z['match_days'], '/', z['days'], '日', tot_m, '/', tot_v)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'build'
    if cmd == 'build':
        runs, races = load()
        U = build(runs, races)
        U.to_parquet(OUT, index=False)
        print('rows', len(U), 'races', U.drop_duplicates(RK).shape[0], 'years', U.year.min(), U.year.max())
    elif cmd == 'check':
        check()
    elif cmd == 'leak':
        leak()
