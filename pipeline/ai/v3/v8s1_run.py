# -*- coding: utf-8 -*-
"""第 8 版 段 1: FABLE の設計(out/v8_ideas_fable.md §2-D・E・G・H・#30・§3)のうち 2016 年から作れる材料 6 群を作り、
作る期間(2016〜19)で自動の足し引き → 2020〜21 を 1 回だけ → 答え合わせ(2022-01〜2026-08)。
既存の台本は import して呼ぶだけ(書き換えない)。オッズ・人気(南関)は材料にしない。

  py -3.12 -X utf8 src/v8s1_run.py all    # feat → select → final → open → eval → md(できている段は飛ばす)

■ 決め(結果を見る前に書いた。結果を見て変えない)
  共通: 走り = 全 NAR の走り(v7c_run.sources)。取消・除外は走りに数えない(a8_c_ だけが使う)。「前」= レースの日より前
     (当日を含まない)。馬 = hid(v7c と同じ)。馬の鍵 lk = vc.link_key(hid)(NFKC・空白消しの 馬名|生年)。
     「前走」= 取消・除外を除いた一番新しい前の走り。同じ馬・同じ日の走りは最後の 1 つ。
  a8_q_ 隊列(#23・#24): nar_races.corners(角ごとの order)。「,」= 次の塊・「(a,b)」= 並走の塊・「-」「=」= 切れ目。
     位置 = 前の塊の頭数 + 1。1 走ごとに:
       solo = 最初に書かれた角で 先頭の塊が自分 1 頭 かつ すぐ後ろに切れ目(1/0)
       gaps = 最後の角で自分より前にある切れ目の数
       gain = (最後から 2 つ目の角の位置 − 最後の角の位置)÷ 最後の角の頭数(角が 1 つなら欠け)
       gapr = 自分のすぐ前に切れ目がある角の割合(先頭の塊を除く)
       box  = 括弧(2 頭以上)の中で最後でない(= 内側で外に馬がいる)角の割合
     列: a8_q_solo1・a8_q_gaps1・a8_q_gain1・a8_q_box1 = 前走の値/a8_q_solo5・a8_q_gapr5・a8_q_box5 = 直近 5 走の平均(欠けは除く)。
  a8_l_ ラップ(#26・#27): nar_races.furlongs。距離が 200 で割って 100 余るときは最初の区間(100m)を捨てる。区間 6 つ以上のとき
     形 = 後半 3 区間の和 − 前半 3 区間の和(前傾 = +)。形の基準 = 同じ場・同じ距離の前 365 日(当日を含まない)のレースの平均
     (20 レース以上)。shape = 形 − 基準。前寄り = 0.5 −(最初の角の位置 − 1)÷ max(頭数 − 1, 1)(c1/n1、無ければ c2/n2、c3/n3)。
     cons = shape × 前寄り(前傾 × 先行 = + = 消耗)。成績 perf = 1 −(着順 − 1)÷(完走頭数 − 1)。
     列: a8_l_shape1・a8_l_cons1 = 前走/a8_l_cons3 = 直近 3 走の cons の平均/a8_l_fit = 前の走りのうち shape > 0 の perf 平均 −
     shape ≤ 0 の perf 平均(どちらも 1 走以上)。SI の履歴は走りの表に無いので perf で代える。
  a8_s_ セリ(#17〜#19): auction_sales。生年 = birth_date の年、無ければ セリの年 − age。
     1 歳・当歳・2 歳のセリ = source が hba・jrha。照合: 馬名があれば 馬名|生年 = lk、kd_horse(台帳・lk が一意の馬)に父・母が
     あれば 父・母とも一致するときだけ(違えば捨てる。台帳に無い馬は馬名だけで採る)。馬名が無ければ 母|生年|父 が台帳で一意の馬。
     lp = log10(落札価格)(sold かつ価格 > 0)。rk = 同じ source・同じセリの日の落札の中の価格の順位(0〜1)。
     sire_rel = lp − 同じ父の 1 歳等のセリの落札 lp の中央値((そのセリの日 − 365 日, そのセリの日] の同じ日を含む・3 件以上)。
     列: a8_s_lp・a8_s_rk・a8_s_sire_rel = レースの日より前の一番新しい落札/a8_s_unsold = 前に上場して落札が 1 つも無い 1・
     落札あり 0・上場なし 欠け/a8_s_loc_lp・a8_s_loc_days = 楽天・sat の「地方(門別・ホッカイドウ含む)在籍」の落札
     (馬名|生年 = lk)の一番新しい前の lp と、その日からの日数。
  a8_c_ 取消(#30): finish_note が 取消・除外。a8_c_n365 = 前 365 日の回数・a8_c_last = 一番新しい前の出走予定(取消を含む)が
     取消なら 1(前の予定が無ければ欠け)・a8_c_days = 最後の取消からの日数。
  a8_b_ 馬場の持ち越し(#28・#29): 南関の場ごとのレースの日。前のレースの日から 1 日以内なら同じ開催。開催の前の日だけを使う
     (初日は欠け)。front = 前の日の(4 角 3 番手以内・完走)の 3 着以内率 − 同じ場の前 1,095 日の同じ率。
     inner = 前の日の(馬番 ≤ 完走頭数 ÷ 3)の 3 着以内率 − 同じ場の前 1,095 日の同じ率。
     time = 前の日のレースの(勝ち時計 − 基準)÷ 距離 × 1000 の中央値、基準 = 同じ場・同じ距離の前 1,095 日の勝ち時計の平均
     (10 レース以上)。wx・going = 開催の前の日の最後のレースの天候(晴 0・曇 1・小雨 2・雨 3・小雪 4・雪 5)・馬場(良 0・稍重 1・
     重 2・不良 3)。nday = 開催の前の日の数(初日 0)。列: a8_b_front・a8_b_inner・a8_b_time・a8_b_wx・a8_b_going・a8_b_nday。
  a8_j_ 中央(#14〜#16): nar_jra_runs(Supabase)。つなぎ = nar_jra_horses の 馬名|生年(一意のとき)= lk。
     つながらない馬は全部欠け(nar_jra_horses が全部の馬を持つかは分からないので 0 にしない)。着順 > 0 の走りだけ。
     j7_ と同じ 11 列(a8_j_n・w・t3・days・last_fin・last_nst(= field_size)・best・dirt_rel・last_pop(中央の過去の人気・
     j7_last_pop と同じ定義)・turf_n・best_l3f)+
     a8_j_f3rel = 中央ダート 1200〜1800 の first3f − 基準(同じ場・同じ距離のダートの前の年の中央値・10 走以上)の最小/
     a8_j_l3d = 中央ダート 1200〜1800 の last3f の最小/a8_j_c4 = 通過順の最後の数 ÷ 頭数 の平均/
     a8_j_mg3 = 最後 3 走の着差(馬身 × 0.2 秒 ÷ 距離 × 1000、1 着 0・ハナ 0.1・アタマ 0.2・クビ 0.3・大差 10・同着 0 馬身)の平均/
     a8_j_mgmin = 中央ダートでの着差の最小/a8_j_mk_lp・a8_j_mk_rk = 楽天・sat の「中央 登録抹消」の落札(馬名|生年 = lk)の
     一番新しい前の lp と、同じ source・同じ日の落札の中の順位(0〜1)。
  漏れ検査: v7e と同じ 20 日(t4_base.pick_days)× 作る・答え合わせ。その日までに切り(走り・レース・中央の走り・セリ)、
     その日の結果(着順・取消以外の finish_note・時計・通過・corners・furlongs・天候・馬場・中央の着順等・セリの価格)を空にして
     作り直し、一致を見る。
  足し引き: 土台 = 第 7 版 e の 183 列(vc.base_cols + C7 + J7 + nk7_)。線 = vs.judge(伸び > 2 × 標準誤差 かつ 2016〜19 の
     4 年中 3 年)・Y3 15/500/800。
     段 0: §1-3 の 40 列を 1 つの群として抜く → 通れば抜いた形を土台にする。
     群 q・l・s・c・b = 足す形。j = 「j7_(土台に残っているもの)を抜いて a8_j_ を足す」入れ替えの形。
     足す: 通った群のうち伸び最大を足す → 通る群が無くなるまで。抜く: この段で足した群だけを 1 つずつ抜いて同じ線(j を抜くと
     j7_ に戻る)。2020〜21 は final で 1 回だけ(vs.final と同じ設定 Y1 31/500/400・Y3 15/100/1200)。
  答え合わせ: v7e_open.open_ と同じ区切り・学び方。◎ = p3′ → p1 → 馬番。勝率 = ◎ の 1 着率・単勝回収率 = ◎ の pay_win の平均
     (v7_open_eval.load の pay_win・欠けのレースは除く)。場面: 新馬戦 = b_young の 1 の位が 1 のレース・転入初戦 = 新馬戦でなく
     l_debut = 1 の馬がいるレース・接戦 = 第 8 版の p3′ の 1 位 − 2 位 が全レースの下 1/4 のレース。差 ± = 日ごとにまとめた
     2 × 標準誤差(v7e_open と同じ)。
"""
import functools
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_base  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t6_base  # noqa: E402
import v7_open as vo  # noqa: E402
import v7_open_eval as E  # noqa: E402
import v7_select as vs  # noqa: E402
import v7c_run as vc  # noqa: E402
import v7d_run as v7d  # noqa: E402
import v7e_run as e  # noqa: E402
import v7e_open as eo  # noqa: E402

V3 = e.V3
REPO = e.REPO
KEY, Q5 = e.KEY, e.Q5
NANKAN = d3.NANKAN
RESJ = V3 / 'v8s1_res.json'
MD = REPO / 'out' / 'v8_stage1.md'
CACHE = V3 / 'v8s1_cache'
OUT_P = V3 / 'v8s1_open_preds.parquet'
NCOL = e.GROUPS['n']
D40 = ('p_ab p_si1 p_simax5 p_ab_rank r_ab r_fr1 r_frmax5 h_j1 b_lv1 b_g1 j_gate l_debut e_first d_first e_night h_chg '
       'h_mark c_stop c7_s_w c7_s_t3y2 c7_m_n c7_m_w c7_m_t3y2 c7_m_t3deb c7_b_n c7_b_w c7_o_n c7_bmon c7_d_t3_rk '
       'c7_b_t3_rk j7_w j7_turf_n j7_last_nst nk7_last_fin b7_k09_top_t3 b7_k12_ntrans b7_k15_nrest b7_g16_marespring '
       'b7_g17_geldn b7_g18_gdown').split()
G = {
    'q': ['a8_q_solo1', 'a8_q_gaps1', 'a8_q_gain1', 'a8_q_box1', 'a8_q_solo5', 'a8_q_gapr5', 'a8_q_box5'],
    'l': ['a8_l_shape1', 'a8_l_cons1', 'a8_l_cons3', 'a8_l_fit'],
    's': ['a8_s_lp', 'a8_s_rk', 'a8_s_sire_rel', 'a8_s_unsold', 'a8_s_loc_lp', 'a8_s_loc_days'],
    'c': ['a8_c_n365', 'a8_c_last', 'a8_c_days'],
    'b': ['a8_b_front', 'a8_b_inner', 'a8_b_time', 'a8_b_wx', 'a8_b_going', 'a8_b_nday'],
    'j': ['a8_j_n', 'a8_j_w', 'a8_j_t3', 'a8_j_days', 'a8_j_last_fin', 'a8_j_last_nst', 'a8_j_best', 'a8_j_dirt_rel',
          'a8_j_last_pop', 'a8_j_turf_n', 'a8_j_best_l3f', 'a8_j_f3rel', 'a8_j_l3d', 'a8_j_c4', 'a8_j_mg3', 'a8_j_mgmin',
          'a8_j_mk_lp', 'a8_j_mk_rk'],
}
GNAME = {'q': '隊列 a8_q_', 'l': 'ラップ a8_l_', 's': 'セリ a8_s_', 'c': '取消 a8_c_', 'b': '馬場の持ち越し a8_b_',
         'j': '中央の入れ替え(j7_ → a8_j_)', 'drop40': '§1-3 の 40 列を抜く'}
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def res_load():
    return json.loads(RESJ.read_text(encoding='utf-8')) if RESJ.exists() else {}


def res_save(k, v):
    R = res_load()
    R[k] = v
    RESJ.write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def fpath(g, part):
    return V3 / f'feat_v8s1_{g}_{part}.parquet'


def wait_mem():
    """自分以外の python.exe で 1GB を超えるものが動いていれば、終わるまで 60 秒おきに待つ。"""
    me = os.getpid()
    while True:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV', '/NH'],
                             capture_output=True, text=True, errors='ignore').stdout
        big = []
        for line in out.splitlines():
            p = [x.strip().strip('"') for x in line.split('","')]
            if len(p) >= 5 and p[1].isdigit() and int(p[1]) != me:
                kb = int(re.sub(r'[^0-9]', '', p[4]) or 0)
                if kb > 1024 * 1024:
                    big.append((p[1], kb // 1024))
        if not big:
            return
        log('待つ(ほかの python が 1GB 超)', big)
        time.sleep(60)


def nf(s):
    return s.map(vc.norm)


# ================================================================ 元の表
def sources():
    runs, facts, races = vo.raw_all()
    h = d3.sources_from(runs, facts, races)
    h = h[Q5 + ['hid', 'finish', 'finish_note', 'time_sec', 'age', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']].copy()
    del runs, facts
    rc = races[KEY + ['distance_m', 'furlongs', 'corners', 'weather', 'going']].copy()
    rc['race_no'] = rc.race_no.astype(int)
    rc = rc.drop_duplicates(KEY, keep='last').reset_index(drop=True)
    jr = pd.read_parquet(V3 / 'sb_nar_jra_runs.parquet')
    jh = pd.read_parquet(V3 / 'sb_nar_jra_horses.parquet')
    au = pd.read_parquet(V3 / 'sb_auction_sales.parquet')
    kd = pd.read_parquet(V3 / 'kd_horse.parquet', columns=['ketto', 'birth', 'name', 'sire', 'dam', 'src'])
    return {'h': h, 'rc': rc, 'jr': jr, 'jh': jh, 'au': au, 'kd': kd}


def cut(S, X):
    """その日までに切り、その日の結果を空にする(漏れ検査)。"""
    h = S['h'][S['h'].race_date <= X].copy()
    mk = (h.race_date == X).to_numpy()
    h.loc[mk, ['finish', 'time_sec', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']] = np.nan
    h.loc[mk & ~h.finish_note.isin(d3.CANCEL).to_numpy(), 'finish_note'] = np.nan
    rc = S['rc'][S['rc'].race_date <= X].copy()
    rc.loc[rc.race_date == X, ['furlongs', 'corners', 'weather', 'going']] = None
    jr = S['jr'][S['jr'].race_date <= X].copy()
    jr.loc[jr.race_date == X, ['finish', 'finish_note', 'time_sec', 'margin', 'last3f', 'last4f', 'first3f', 'passing',
                               'popularity']] = None
    au = S['au'][S['au'].auction_date <= X].copy()
    au.loc[au.auction_date == X, ['price', 'sold']] = None
    return {'h': h, 'rc': rc, 'jr': jr, 'jh': S['jh'], 'au': au, 'kd': S['kd']}


def qb(S, Q):
    h = S['h']
    q = Q[Q5].reset_index(drop=True).merge(h.drop_duplicates(Q5)[Q5 + ['hid']], on=Q5, how='left', validate='1:1')
    q['lk'] = vc.link_key(q.hid)
    q['date'] = pd.to_datetime(q.race_date)
    q['_i'] = np.arange(len(q))
    return q


def asof(q, P, by, cols, qdate='date'):
    a = q[q[by].notna()][['_i', by, qdate]].rename(columns={qdate: 'date'}).sort_values('date', kind='mergesort')
    P = P[[by, 'date'] + cols].sort_values('date', kind='mergesort')
    m = pd.merge_asof(a, P, on='date', by=by, allow_exact_matches=False, direction='backward')
    return m.set_index('_i').reindex(np.arange(len(q)))


def runs_hist(h):
    r = h[~h.finish_note.isin(d3.CANCEL) & h.hid.notna()].copy()
    r['date'] = pd.to_datetime(r.race_date)
    r = r.sort_values(['hid', 'date', 'race_no'], kind='mergesort').drop_duplicates(['hid', 'date'], keep='last')
    return r.reset_index(drop=True)


def win_mean(df, gcols, dcol, vcol, days, min_n):
    """同じ gcols の [日 − days, 日) の vcol の平均(min_n 件以上)。dcol = 整数の日。"""
    out = np.full(len(df), np.nan)
    df = df.reset_index(drop=True)
    ok = df[vcol].notna()
    for _, g in df.groupby(gcols, sort=False):
        s = g[ok[g.index]].sort_values(dcol, kind='mergesort')
        dd, vv = s[dcol].to_numpy(), s[vcol].to_numpy(float)
        cs = np.concatenate([[0.0], np.cumsum(vv)])
        t = g[dcol].to_numpy()
        lo, hi = np.searchsorted(dd, t - days, 'left'), np.searchsorted(dd, t, 'left')
        n = hi - lo
        with np.errstate(all='ignore'):
            out[g.index] = np.where(n >= min_n, (cs[hi] - cs[lo]) / np.maximum(n, 1), np.nan)
    return out


def dn(s):
    return pd.to_datetime(s).values.astype('datetime64[D]').astype(np.int64)


# ================================================================ a8_q_ 隊列
def parse_order(s):
    groups, gaps, num, par, cur, pend = [], [], '', False, [], False
    for ch in str(s) + ',':
        if ch.isdigit():
            num += ch; continue
        if num:
            if par:
                cur.append(int(num))
            else:
                groups.append([int(num)]); gaps.append(pend); pend = False
            num = ''
        if ch == '(':
            par, cur = True, []
        elif ch == ')':
            par = False
            if cur:
                groups.append(cur); gaps.append(pend); pend = False
        elif ch in '-=' and not par:
            pend = True
    return groups, gaps


@functools.lru_cache(maxsize=None)
def parse_corners(s):
    try:
        L = json.loads(s)
    except Exception:  # noqa: BLE001
        return ()
    orders = [x.get('order') for x in L if isinstance(x, dict) and x.get('order')]
    if not orders:
        return ()
    C = []
    for od in orders:
        groups, gaps = parse_order(od)
        info, cum, ng = {}, 0, 0
        for gi, grp in enumerate(groups):
            if gi > 0 and gaps[gi]:
                ng += 1
            after = gi + 1 < len(groups) and gaps[gi + 1]
            for k, u in enumerate(grp):
                info[u] = dict(pos=cum + 1, gi=gi, size=len(grp), inner=len(grp) >= 2 and k < len(grp) - 1,
                               gb=gi > 0 and gaps[gi], ga=after, nga=ng)
            cum += len(grp)
        C.append((info, cum))
    horses = set().union(*[set(c[0]) for c in C])
    out = []
    f, l = C[0][0], C[-1][0]
    for u in horses:
        solo = float(f[u]['gi'] == 0 and f[u]['size'] == 1 and f[u]['ga']) if u in f else np.nan
        gaps = float(l[u]['nga']) if u in l else np.nan
        gain = np.nan
        if len(C) >= 2 and u in l and u in C[-2][0] and C[-1][1] > 0:
            gain = (C[-2][0][u]['pos'] - l[u]['pos']) / C[-1][1]
        pres = [c[0][u] for c in C if u in c[0]]
        gb = [float(x['gb']) for x in pres]
        box = [float(x['inner']) for x in pres]
        out.append((u, solo, gaps, gain, np.mean(gb) if gb else np.nan, np.mean(box) if box else np.nan))
    return tuple(out)


def build_q(S, Q):
    q = qb(S, Q)
    r = runs_hist(S['h'])
    rc = S['rc'][S['rc'].corners.notna()]
    rows = []
    for t, dd, no, s in rc[KEY + ['corners']].itertuples(index=False):
        for x in parse_corners(s):
            rows.append((t, dd, no) + x)
    Cm = pd.DataFrame(rows, columns=KEY + ['umaban', 'solo', 'gaps', 'gain', 'gapr', 'box'])
    r = r.merge(Cm, on=Q5, how='left')
    g = r.groupby('hid', sort=False)
    for c in ('solo', 'gapr', 'box'):
        r[c + '5'] = g[c].rolling(5, min_periods=1).mean().reset_index(level=0, drop=True)
    cols = ['solo', 'gaps', 'gain', 'box', 'solo5', 'gapr5', 'box5']
    m = asof(q, r, 'hid', cols)
    out = pd.DataFrame(index=np.arange(len(q)))
    for c in cols:
        out['a8_q_' + (c if c.endswith('5') else c + '1')] = m[c].to_numpy(float)
    return out[G['q']], {}


# ================================================================ a8_l_ ラップ
def fl_shape(fl, dist):
    try:
        v = json.loads(fl) if isinstance(fl, str) else list(fl)
        v = [float(x) for x in v]
    except Exception:  # noqa: BLE001
        return np.nan
    if dist == dist and int(dist) % 200 == 100:
        v = v[1:]
    if len(v) < 6:
        return np.nan
    return sum(v[-3:]) - sum(v[:3])


def race_shape(rc):
    x = rc[rc.furlongs.notna()][KEY + ['distance_m', 'furlongs']].copy()
    x['dist'] = pd.to_numeric(x.distance_m, errors='coerce')
    x['raw'] = [fl_shape(f, d) for f, d in zip(x.furlongs, x.dist)]
    x['dn'] = dn(x.race_date)
    x = x[x.raw.notna() & x.dist.notna()].reset_index(drop=True)
    x['shape'] = x.raw - win_mean(x, ['track', 'dist'], 'dn', 'raw', 365, 20)
    return x[KEY + ['shape']]


def build_l(S, Q):
    q = qb(S, Q)
    r = runs_hist(S['h'])
    r = r.merge(race_shape(S['rc']), on=KEY, how='left')
    fin = r.finish.where(r.finish > 0)
    nfin = S['h'][S['h'].finish > 0].groupby(KEY).size().rename('nfin').reset_index()
    r = r.merge(nfin, on=KEY, how='left')
    pos, nn = r.c1.copy(), r.n1.copy()
    for c, n in (('c2', 'n2'), ('c3', 'n3')):
        use = pos.isna()
        pos[use], nn[use] = r.loc[use, c], r.loc[use, n]
    front = 0.5 - (pos - 1) / np.maximum(nn - 1, 1)
    r['cons'] = r['shape'] * front
    with np.errstate(all='ignore'):
        r['perf'] = np.where(r.nfin >= 2, 1 - (fin - 1) / (r.nfin - 1), np.nan)
    g = r.groupby('hid', sort=False)
    r['cons3'] = g['cons'].rolling(3, min_periods=1).mean().reset_index(level=0, drop=True)
    ok = r.perf.notna() & r['shape'].notna()
    for nm, cond in (('p', ok & (r['shape'] > 0)), ('m', ok & (r['shape'] <= 0))):
        r['s_' + nm] = np.where(cond, r.perf, 0.0)
        r['n_' + nm] = cond.astype(float)
        r['s_' + nm] = r.groupby('hid', sort=False)['s_' + nm].cumsum()
        r['n_' + nm] = r.groupby('hid', sort=False)['n_' + nm].cumsum()
    with np.errstate(all='ignore'):
        r['fit'] = np.where((r.n_p > 0) & (r.n_m > 0), r.s_p / r.n_p - r.s_m / r.n_m, np.nan)
    m = asof(q, r, 'hid', ['shape', 'cons', 'cons3', 'fit'])
    out = pd.DataFrame({'a8_l_shape1': m['shape'].to_numpy(float), 'a8_l_cons1': m.cons.to_numpy(float),
                        'a8_l_cons3': m.cons3.to_numpy(float), 'a8_l_fit': m.fit.to_numpy(float)})
    return out[G['l']], {}


# ================================================================ セリの下ごしらえ
def au_prep(au):
    a = au.copy()
    a['date'] = pd.to_datetime(a.auction_date)
    by = pd.to_datetime(a.birth_date, errors='coerce').dt.year
    a['by'] = by.fillna(a.date.dt.year - pd.to_numeric(a.age, errors='coerce'))
    a['byk'] = a.by.astype('Int64').astype(str)
    a['cat'] = a.category.map(lambda s: re.sub(r'\s+', '', unicodedata.normalize('NFKC', s)) if isinstance(s, str) else '')
    ok = (a.sold == True) & (pd.to_numeric(a.price, errors='coerce') > 0)  # noqa: E712
    a['lp'] = np.where(ok, np.log10(pd.to_numeric(a.price, errors='coerce').where(ok)), np.nan)
    a['n_name'], a['n_sire'], a['n_dam'] = nf(a.horse_name), nf(a.sire), nf(a.dam)
    return a


def kd_table(kd):
    k = kd[kd.ketto.notna() & kd.birth.notna()].copy()
    k['pri'] = (k.src != 'NU').astype(int)
    k = k.sort_values(['ketto', 'pri'], kind='mergesort').drop_duplicates('ketto', keep='first')
    k['lk'] = nf(k['name']) + '|' + (k.birth // 10000).astype(int).astype(str)
    k['n_sire'], k['n_dam'] = nf(k.sire), nf(k.dam)
    k = k[k.lk.notna() & ~k.lk.duplicated(keep=False)]
    k['k3'] = k.n_dam + '|' + (k.birth // 10000).astype(int).astype(str) + '|' + k.n_sire
    return k[['lk', 'n_sire', 'n_dam', 'k3']]


def young_match(a, K):
    """1 歳・当歳・2 歳のセリ → lk。route = name(馬名・父母で確かめた)/name_nokd(台帳に無い・馬名だけ)/dam(母|生年|父)。"""
    y = a[a.source.isin(['hba', 'jrha'])].copy()
    kl = K.set_index('lk')
    y['lk_a'] = y.n_name + '|' + y.byk
    has = y.n_name.notna()
    ink = y.lk_a.isin(kl.index)
    ks = y.lk_a.map(kl.n_sire).where(ink)
    kdm = y.lk_a.map(kl.n_dam).where(ink)
    agree = ((ks.isna() | y.n_sire.isna() | (ks == y.n_sire)) & (kdm.isna() | y.n_dam.isna() | (kdm == y.n_dam)))
    k3u = K[~K.k3.duplicated(keep=False) & K.k3.notna()].set_index('k3').lk
    lk_b = (y.n_dam + '|' + y.byk + '|' + y.n_sire).map(k3u)
    y['lk'] = np.where(has & ink & agree, y.lk_a, np.where(has & ~ink, y.lk_a, np.where(~has, lk_b, None)))
    y['route'] = np.where(has & ink & agree, 'name', np.where(has & ink, 'name_ng', np.where(has, 'name_nokd',
                          np.where(lk_b.notna(), 'dam', 'none'))))
    return y


def young_table(a, K):
    y = young_match(a, K)
    y['rk'] = y[y.lp.notna()].groupby(['source', 'auction_date']).lp.rank(pct=True)
    s = y[y.lp.notna() & y.n_sire.notna()].sort_values(['n_sire', 'date'], kind='mergesort')
    y['sire_med'] = np.nan
    for _, g in s.groupby('n_sire', sort=False):
        dd, vv = dn(g.date), g.lp.to_numpy(float)
        lo, hi = np.searchsorted(dd, dd - 365, 'right'), np.searchsorted(dd, dd, 'right')
        y.loc[g.index, 'sire_med'] = [float(np.median(vv[a:b])) if b - a >= 3 else np.nan for a, b in zip(lo, hi)]
    y['sire_rel'] = y.lp - y.sire_med
    return y


def build_s(S, Q):
    q = qb(S, Q)
    a = au_prep(S['au'])
    K = kd_table(S['kd'])
    y = young_table(a, K)
    y = y[y.lk.notna()].sort_values(['lk', 'date', 'lp'], kind='mergesort', na_position='first')
    sold = y.lp.notna().to_numpy()
    lk = y.lk.to_numpy()
    P = pd.DataFrame({'lk': lk, 'date': y.date.to_numpy()})
    # 一番新しい「落札した行」の位置を運ぶ(3 列とも同じ行の値)
    pos = pd.Series(np.where(sold, np.arange(len(y)), np.nan)).groupby(lk).ffill().to_numpy()
    has = ~np.isnan(pos)
    ix = np.where(has, pos, 0).astype(int)
    for c in ('lp', 'rk', 'sire_rel'):
        P[c] = np.where(has, y[c].to_numpy(float)[ix], np.nan)
    P['ever'] = pd.Series(sold.astype(float)).groupby(lk).cummax().to_numpy()
    P = P.drop_duplicates(['lk', 'date'], keep='last')
    m = asof(q, P, 'lk', ['lp', 'rk', 'sire_rel', 'ever'])
    loc = a[a.source.isin(['rakuten', 'sat']) & a.cat.str.contains('在籍') & ~a.cat.str.contains('中央')
            & a.cat.str.contains('地方|門別|ホッカイドウ') & a.lp.notna() & a.n_name.notna()].copy()
    loc['lk'] = loc.n_name + '|' + loc.byk
    loc = loc.sort_values(['lk', 'date'], kind='mergesort').drop_duplicates(['lk', 'date'], keep='last')
    loc['ld'] = loc.date
    ml = asof(q, loc, 'lk', ['lp', 'ld'])
    out = pd.DataFrame(index=np.arange(len(q)))
    out['a8_s_lp'], out['a8_s_rk'] = m.lp.to_numpy(float), m.rk.to_numpy(float)
    out['a8_s_sire_rel'] = m.sire_rel.to_numpy(float)
    out['a8_s_unsold'] = np.where(m.ever.notna(), 1.0 - m.ever.to_numpy(float), np.nan)
    out['a8_s_loc_lp'] = ml.lp.to_numpy(float)
    out['a8_s_loc_days'] = (q.date - ml.ld).dt.days.to_numpy(float)
    aux = {'young': y}
    return out[G['s']], aux


# ================================================================ a8_c_ 取消
def build_c(S, Q):
    q = qb(S, Q)
    h = S['h'][S['h'].hid.notna()]
    c = h[h.finish_note.isin(d3.CANCEL)][['hid', 'race_date']].copy()
    c['date'] = pd.to_datetime(c.race_date)
    c = c.drop_duplicates(['hid', 'date']).sort_values(['hid', 'date'], kind='mergesort')
    c['cn'] = c.groupby('hid').cumcount() + 1.0
    c['ld'] = c.date
    m1 = asof(q, c, 'hid', ['cn', 'ld'])
    q['d365'] = q.date - pd.Timedelta(days=365)
    m2 = asof(q, c, 'hid', ['cn'], qdate='d365')
    en = h[['hid', 'race_date', 'race_no', 'finish_note']].copy()
    en['date'] = pd.to_datetime(en.race_date)
    en['isc'] = en.finish_note.isin(d3.CANCEL).astype(float)
    en = en.sort_values(['hid', 'date', 'race_no'], kind='mergesort').drop_duplicates(['hid', 'date'], keep='last')
    m3 = asof(q, en, 'hid', ['isc'])
    has = q.hid.notna().to_numpy()
    out = pd.DataFrame(index=np.arange(len(q)))
    out['a8_c_n365'] = np.where(has, m1.cn.fillna(0).to_numpy() - m2.cn.fillna(0).to_numpy(), np.nan)
    out['a8_c_last'] = m3.isc.to_numpy(float)
    out['a8_c_days'] = (q.date - m1.ld).dt.days.to_numpy(float)
    return out[G['c']], {}


# ================================================================ a8_b_ 馬場の持ち越し
WX = {'晴': 0, '曇': 1, '小雨': 2, '雨': 3, '小雪': 4, '雪': 5}
GO = {'良': 0, '稍重': 1, '重': 2, '不良': 3}


def build_b(S, Q):
    q = qb(S, Q)
    rc = S['rc'][S['rc'].track.isin(NANKAN)].copy()
    h = S['h'][S['h'].track.isin(NANKAN)]
    f = h[h.finish > 0].copy()
    f['nfin'] = f.groupby(KEY).finish.transform('size')
    f['fr'] = (f.c4 <= 3).astype(float) * f.c4.notna()
    f['t3'] = (f.finish <= 3).astype(float)
    f['inn'] = (f.umaban <= f.nfin / 3).astype(float)
    day = f.assign(tf=f.fr * f.t3, ti=f.inn * f.t3).groupby(['track', 'race_date']).agg(
        nf=('fr', 'sum'), tf=('tf', 'sum'), ni=('inn', 'sum'), ti=('ti', 'sum')).reset_index()
    w = f[f.finish == 1].groupby(KEY).time_sec.min().rename('wt').reset_index()
    w = w.merge(rc[KEY + ['distance_m']], on=KEY, how='left')
    w['dist'] = pd.to_numeric(w.distance_m, errors='coerce')
    w = w[w.wt.notna() & (w.wt > 0) & w.dist.notna()].reset_index(drop=True)
    w['dn'] = dn(w.race_date)
    w['base'] = win_mean(w, ['track', 'dist'], 'dn', 'wt', 1095, 10)
    w['dev'] = (w.wt - w.base) / w.dist * 1000
    last = rc.sort_values(KEY, kind='mergesort').drop_duplicates(['track', 'race_date'], keep='last')
    last = last.set_index(['track', 'race_date'])
    rows = []
    for t in NANKAN:
        ds = sorted(rc[rc.track == t].race_date.unique())
        if not ds:
            continue
        dd = dn(pd.Series(ds))
        dy = day[day.track == t].set_index('race_date').reindex(ds).fillna(0.0)
        cs = {c: np.concatenate([[0.0], np.cumsum(dy[c].to_numpy())]) for c in ('nf', 'tf', 'ni', 'ti')}
        devs = w[w.track == t].groupby('race_date').dev.apply(lambda v: list(v.dropna())).to_dict()
        start = 0
        for i, x in enumerate(ds):
            if i > 0 and dd[i] - dd[i - 1] > 1:
                start = i
            lo = np.searchsorted(dd, dd[i] - 1095, 'left')
            r = {'track': t, 'race_date': x, 'a8_b_nday': float(i - start)}
            if i > start:
                s = lambda c, a, b: cs[c][b] - cs[c][a]  # noqa: E731
                with np.errstate(all='ignore'):
                    bf = s('tf', lo, i) / s('nf', lo, i) if s('nf', lo, i) > 0 else np.nan
                    bi = s('ti', lo, i) / s('ni', lo, i) if s('ni', lo, i) > 0 else np.nan
                    r['a8_b_front'] = s('tf', start, i) / s('nf', start, i) - bf if s('nf', start, i) > 0 else np.nan
                    r['a8_b_inner'] = s('ti', start, i) / s('ni', start, i) - bi if s('ni', start, i) > 0 else np.nan
                v = [z for j in range(start, i) for z in devs.get(ds[j], [])]
                r['a8_b_time'] = float(np.median(v)) if v else np.nan
                pv = last.loc[(t, ds[i - 1])]
                r['a8_b_wx'] = float(WX[pv.weather]) if pv.weather in WX else np.nan
                r['a8_b_going'] = float(GO[pv.going]) if pv.going in GO else np.nan
            rows.append(r)
    B = pd.DataFrame(rows)
    for c in G['b']:
        if c not in B:
            B[c] = np.nan
    m = q[['track', 'race_date']].merge(B, on=['track', 'race_date'], how='left')
    return m[G['b']].astype(float).reset_index(drop=True), {}


# ================================================================ a8_j_ 中央
MG = {'ハナ': 0.1, 'アタマ': 0.2, 'クビ': 0.3, '大差': 10.0, '同着': 0.0}


def mg_len(s):
    if not isinstance(s, str):
        return np.nan
    s = unicodedata.normalize('NFKC', s).strip()
    if s in MG:
        return MG[s]
    m = re.fullmatch(r'(?:(\d+)\s*)?(?:(\d+)/(\d+))?', s)
    if not m or not (m.group(1) or m.group(2)):
        return np.nan
    v = float(m.group(1) or 0)
    if m.group(2):
        v += float(m.group(2)) / float(m.group(3))
    return v


def jra_link(jh):
    x = jh.copy()
    x['lk'] = nf(x.horse_name) + '|' + x.birth_year.astype('Int64').astype(str)
    x = x[x.lk.notna() & ~x.lk.duplicated(keep=False)]
    return dict(zip(x.lk, x.kb_horse_id))


def jra_table8(jr):
    J = jr.copy()
    J['finish'] = pd.to_numeric(J.finish, errors='coerce')
    J = J[J.finish.fillna(0) > 0].copy()
    J['date'] = pd.to_datetime(J.race_date)
    J['dist'] = pd.to_numeric(J.distance, errors='coerce')
    J['nst'] = pd.to_numeric(J.field_size, errors='coerce')
    J['yr'] = J.date.dt.year
    dirt = J.surface == 'ダ'
    J['first3f'] = pd.to_numeric(J.first3f, errors='coerce')
    J['last3f'] = pd.to_numeric(J.last3f, errors='coerce')
    b = J[dirt & J.first3f.notna()].groupby(['place', 'dist', 'yr']).first3f.agg(['median', 'size']).reset_index()
    b = b[b['size'] >= 10].assign(yr=lambda x: x.yr + 1)[['place', 'dist', 'yr', 'median']]
    J = J.merge(b, on=['place', 'dist', 'yr'], how='left')
    dirt = J.surface == 'ダ'
    mid = dirt & J.dist.between(1200, 1800)
    J['f3rel'] = np.where(mid, J.first3f - J['median'], np.nan)
    J['l3d'] = np.where(mid, J.last3f, np.nan)
    pl = J.passing.map(lambda s: float(str(s).split('-')[-1]) if isinstance(s, str) and str(s).split('-')[-1].isdigit()
                       else np.nan)
    J['c4r'] = pl / J.nst.where(J.nst > 0)
    ml = J.margin.map(mg_len)
    ml = np.where(J.finish == 1, 0.0, ml)
    J['mgs'] = ml * 0.2 / J.dist * 1000
    J = J.sort_values(['kb_horse_id', 'date', 'race_no'], kind='mergesort').reset_index(drop=True)
    dirt = J.surface == 'ダ'
    g = J.groupby('kb_horse_id', sort=False)
    k = J.kb_horse_id
    J['c_n'] = g.cumcount() + 1.0
    J['c_w'] = (J.finish == 1).astype(float).groupby(k).cumsum()
    J['c_t3'] = (J.finish <= 3).astype(float).groupby(k).cumsum()
    J['c_best'] = J.finish.groupby(k).cummin()
    J['c_turf'] = (J.surface == '芝').astype(float).groupby(k).cumsum()
    ok = dirt & (J.nst > 0)
    J['c_dsum'] = pd.Series(np.where(ok, J.finish / J.nst, 0.0)).groupby(k).cumsum()
    J['c_dn'] = ok.astype(float).groupby(k).cumsum()
    l3 = J.last3f.where(J.last3f > 0).fillna(np.inf)
    J['c_l3'] = l3.groupby(k).cummin().replace(np.inf, np.nan)
    for c, s in (('c_f3', 'f3rel'), ('c_l3d', 'l3d')):
        J[c] = J[s].fillna(np.inf).groupby(k).cummin().replace(np.inf, np.nan)
    J['c_c4'] = J.c4r.fillna(0).groupby(k).cumsum() / J.c4r.notna().astype(float).groupby(k).cumsum().replace(0, np.nan)
    J['c_mg3'] = J.groupby('kb_horse_id', sort=False).mgs.rolling(3, min_periods=1).mean().reset_index(level=0, drop=True)
    J['c_mgmin'] = pd.Series(np.where(dirt, J.mgs, np.nan)).fillna(np.inf).groupby(k).cummin().replace(np.inf, np.nan)
    J['l_fin'], J['l_nst'] = J.finish.astype(float), J.nst.astype(float)
    pop = pd.to_numeric(J.popularity, errors='coerce')
    J['l_pop'] = pop.where(pop > 0).astype(float)
    J['l_date'] = J.date
    J = J.drop_duplicates(['kb_horse_id', 'date'], keep='last')
    return J


def build_j(S, Q):
    q = qb(S, Q)
    lmap = jra_link(S['jh'])
    q['kb'] = q.lk.map(lmap)
    J = jra_table8(S['jr'])
    cols = ['c_n', 'c_w', 'c_t3', 'c_best', 'c_turf', 'c_dsum', 'c_dn', 'c_l3', 'c_f3', 'c_l3d', 'c_c4', 'c_mg3',
            'c_mgmin', 'l_fin', 'l_nst', 'l_pop', 'l_date']
    m = asof(q, J.rename(columns={'kb_horse_id': 'kb'}), 'kb', cols)
    lin = q.kb.notna().to_numpy()
    out = pd.DataFrame(index=np.arange(len(q)))
    for c, s in (('a8_j_n', 'c_n'), ('a8_j_w', 'c_w'), ('a8_j_t3', 'c_t3'), ('a8_j_turf_n', 'c_turf')):
        v = m[s].to_numpy(float)
        out[c] = np.where(lin & np.isnan(v), 0.0, v)
    out['a8_j_days'] = (q.date - m.l_date).dt.days.to_numpy(float)
    out['a8_j_last_fin'], out['a8_j_last_nst'] = m.l_fin.to_numpy(float), m.l_nst.to_numpy(float)
    out['a8_j_best'] = m.c_best.to_numpy(float)
    with np.errstate(all='ignore'):
        out['a8_j_dirt_rel'] = np.where(m.c_dn.to_numpy(float) > 0, m.c_dsum.to_numpy(float) / m.c_dn.to_numpy(float), np.nan)
    out['a8_j_last_pop'] = m.l_pop.to_numpy(float)
    out['a8_j_best_l3f'] = m.c_l3.to_numpy(float)
    out['a8_j_f3rel'], out['a8_j_l3d'] = m.c_f3.to_numpy(float), m.c_l3d.to_numpy(float)
    out['a8_j_c4'], out['a8_j_mg3'] = m.c_c4.to_numpy(float), m.c_mg3.to_numpy(float)
    out['a8_j_mgmin'] = m.c_mgmin.to_numpy(float)
    a = au_prep(S['au'])
    mk = a[a.source.isin(['rakuten', 'sat']) & a.cat.str.contains('中央') & a.cat.str.contains('登録抹消')
           & ~a.cat.str.contains('未抹消') & a.lp.notna() & a.n_name.notna()].copy()
    mk['rk'] = mk.groupby(['source', 'auction_date']).lp.rank(pct=True)
    mk['lk'] = mk.n_name + '|' + mk.byk
    mk = mk.sort_values(['lk', 'date'], kind='mergesort').drop_duplicates(['lk', 'date'], keep='last')
    mm = asof(q, mk, 'lk', ['lp', 'rk'])
    out['a8_j_mk_lp'], out['a8_j_mk_rk'] = mm.lp.to_numpy(float), mm.rk.to_numpy(float)
    return out[G['j']], {'lin': lin}


BUILD = {'q': build_q, 'l': build_l, 's': build_s, 'c': build_c, 'b': build_b, 'j': build_j}


# ================================================================ feat
def leak(g, S, Q, full, races):
    days = t4_base.pick_days(races)
    cols = G[g]
    per, tot = [], [0, 0]
    for X in days:
        Qd = Q[Q.race_date == X].reset_index(drop=True)
        b, _ = BUILD[g](cut(S, X), Qd)
        b = pd.concat([Qd[Q5], b.reset_index(drop=True)], axis=1)
        a = full[full.race_date == X].set_index(Q5)[cols].sort_index()
        b = b.set_index(Q5)[cols].sort_index()
        assert a.index.equals(b.index), X
        A, B = a.to_numpy(float), b.to_numpy(float)
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        bad = [c for c, ok in zip(cols, eq.all(0)) if not ok]
        per.append({'date': X, 'rows': len(a), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        log('漏れ', g, X, len(a), int(eq.sum()), eq.size, bad)
    return {'days': len(days), 'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0],
            'cells': tot[1], 'per_day': per}


def s_rates(y, F, meta, age):
    """セリの照合率(セリの側・年ごと)と、南関の行の側(年ごと)。"""
    yy = y.assign(yr=y.date.dt.year)
    side = {int(k): {'rows': len(v), 'name': float((v.route == 'name').mean()), 'name_nokd': float((v.route == 'name_nokd').mean()),
                     'dam': float((v.route == 'dam').mean()), 'name_ng': float((v.route == 'name_ng').mean()),
                     'matched': float(v.lk.notna().mean())} for k, v in yy.groupby('yr') if k >= 2010}
    x = pd.DataFrame({'year': meta.year.to_numpy(), 'age': pd.to_numeric(pd.Series(age), errors='coerce').to_numpy(), 'app': F.a8_s_unsold.notna().to_numpy(),
                      'sold': F.a8_s_lp.notna().to_numpy(), 'locx': F.a8_s_loc_lp.notna().to_numpy()})
    rr = {}
    for k, v in x.groupby('year'):
        v2 = v[v.age == 2]
        rr[int(k)] = {'rows': len(v), 'app': float(v.app.mean()), 'sold': float(v.sold.mean()), 'loc': float(v.locx.mean()),
                      'rows2': len(v2), 'app2': float(v2.app.mean()) if len(v2) else None}
    return {'sale_side': side, 'race_side': rr}


def feat():
    R = res_load()
    todo = [g for g in G if not ('leak_' + g in R and fpath(g, 'explore').exists() and fpath(g, 'open').exists())]
    if not todo:
        log('feat は済み'); return
    wait_mem()
    S = sources()
    races = S['h'][['track', 'race_date']].drop_duplicates()
    log('走り', len(S['h']), 'レース', len(S['rc']))
    XE = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet', columns=Q5 + ['year']))
    XO = vo.nk(pd.read_parquet(V3 / 'feat_t6_open.parquet', columns=Q5 + ['year']))
    Q = pd.concat([XE[Q5], XO[Q5]], ignore_index=True)
    meta = pd.concat([XE[['year']], XO[['year']]], ignore_index=True)
    nk = races[races.track.isin(NANKAN)]
    ne, no = nk[nk.race_date < '2022-01-01'], nk[nk.race_date >= '2022-01-01']
    n = len(XE)
    for g in todo:
        wait_mem()
        F, aux = BUILD[g](S, Q)
        info = {}
        if g == 's':
            age = Q.merge(S['h'].drop_duplicates(Q5)[Q5 + ['age']], on=Q5, how='left').age.to_numpy()
            info['rate'] = s_rates(aux['young'], F, meta, age)
        if g == 'j':
            j7 = pd.concat([vo.nk(pd.read_parquet(v7d.JEX, columns=Q5 + ['j7_n'])),
                            vo.nk(pd.read_parquet(v7d.JOP, columns=Q5 + ['j7_n']))], ignore_index=True)
            x = Q.merge(j7, on=Q5, how='left')
            z = pd.DataFrame({'year': meta.year, 'lin': aux['lin'], 'a8': F.a8_j_n.to_numpy() > 0,
                              'j7': x.j7_n.to_numpy() > 0})
            info['rate'] = {int(k): {'rows': len(v), 'link': float(v.lin.mean()), 'a8_run': float(v.a8.mean()),
                                     'j7_run': float(v.j7.mean())} for k, v in z.groupby('year')}
            yr = pd.to_datetime(S['jr'].race_date).dt.year.value_counts().sort_index()
            info['jr_per_year'] = {int(k): int(v) for k, v in yr.items()}
        F = pd.concat([Q[Q5], F.reset_index(drop=True)], axis=1)
        FE, FO = F.iloc[:n].reset_index(drop=True), F.iloc[n:].reset_index(drop=True)
        info['miss'] = {c: [float(FE[c].isna().mean()), float(FO[c].isna().mean())] for c in G[g]}
        info['mean'] = {c: [float(FE[c].mean()), float(FO[c].mean())] for c in G[g]}
        log(g, 'miss', {c: [round(a, 3) for a in v] for c, v in info['miss'].items()})
        z = {'explore': leak(g, S, XE[Q5], FE, ne), 'open': leak(g, S, XO[Q5], FO, no)}
        info['leak'] = {k: {kk: v[kk] for kk in ('days', 'match_days', 'match', 'cells')} for k, v in z.items()}
        res_save('feat_' + g, info)
        if any(v['match'] != v['cells'] for v in z.values()):
            res_save('leakfail_' + g, z)
            write_md()
            raise SystemExit(f'⛔ 漏れ検査が 100% でない: {g}')
        FE.to_parquet(fpath(g, 'explore'), index=False); FO.to_parquet(fpath(g, 'open'), index=False)
        res_save('leak_' + g, info['leak'])
        log('保存', g)


# ================================================================ 足し引き
def base183():
    b = vc.base_cols() + v7d.C7 + v7d.J7 + NCOL
    assert len(b) == 183 and len(set(b)) == 183 and set(D40) <= set(b)
    return b


def load_sel():
    d = v7d.load_d()
    d = d.merge(vo.nk(pd.read_parquet(eo.fpath('explore'))), on=Q5, how='left', validate='1:1')
    for g in G:
        d = d.merge(vo.nk(pd.read_parquet(fpath(g, 'explore'))), on=Q5, how='left', validate='1:1')
    return d


def fitw(d, cols, *a):
    wait_mem()
    return vs.fit(d, cols, *a)


def select():
    R = res_load()
    if 'select' in R:
        log('select は済み'); return
    wait_mem()
    d = load_sel()
    base = base183()
    vs.CACHE = eo.CACHE  # 183 列(同じ列・同じ値)は v7e_open の judge で出した
    ll_b = vs.race_ll(d, fitw(d, base))
    vs.CACHE = CACHE
    cols0 = [c for c in base if c not in D40]
    ll0 = vs.race_ll(d, fitw(d, cols0))
    j0 = vs.judge(ll_b, ll0)
    j0['sum_base'], j0['sum_new'] = round(float(ll_b.sum()), 1), round(float(ll0.sum()), 1)
    log('段 0(40 列を抜く)', j0)
    base0, ll_cur = (cols0, ll0) if j0['ok'] else (base, ll_b)
    S = {'step0': j0, 'drop40': j0['ok'], 'base_n': len(base0), 'sum_base183': round(float(ll_b.sum()), 1),
         'rounds': [], 'drops': []}

    def cols(gs):
        return [c for c in base0 if not ('j' in gs and c in v7d.J7)] + [c for g in gs for c in G[g]]
    cur = []
    while True:
        res = {}
        for g in [g for g in G if g not in cur]:
            ll1 = vs.race_ll(d, fitw(d, cols(cur + [g])))
            res[g] = vs.judge(ll_cur, ll1)
            res[g]['sum_new'] = round(float(ll1.sum()), 1)
            log('足す', cur, '+', g, res[g])
        good = {g: r for g, r in res.items() if r['ok']}
        pick = max(good, key=lambda k: good[k]['gain']) if good else None
        S['rounds'].append({'cur': list(cur), 'sum_cur': round(float(ll_cur.sum()), 1), 'res': res, 'pick': pick})
        if not pick:
            break
        cur.append(pick)
        ll_cur = vs.race_ll(d, fitw(d, cols(cur)))
    while cur:
        res = {}
        for g in cur:
            ll1 = vs.race_ll(d, fitw(d, cols([x for x in cur if x != g])))
            res[g] = vs.judge(ll_cur, ll1)
            log('抜く', g, res[g])
        good = {g: r for g, r in res.items() if r['ok']}
        pick = max(good, key=lambda k: good[k]['gain']) if good else None
        S['drops'].append({'cur': list(cur), 'res': res, 'pick': pick})
        if not pick:
            break
        cur.remove(pick)
        ll_cur = vs.race_ll(d, fitw(d, cols(cur)))
    S['groups'], S['cols'] = cur, cols(cur)
    S['sum_final'] = round(float(ll_cur.sum()), 1)
    res_save('select', S)
    log('決まった形', cur, len(S['cols']))


def final():
    R = res_load()
    if 'final' in R:
        log('final は済み'); return
    wait_mem()
    d = load_sel()
    sel = R['select']['cols']
    ys = vs.SEL_Y + vs.CHK_Y
    vs.CACHE = CACHE
    te = d[d.year.isin(ys)].copy()
    out = te[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop']].copy()
    res = {}
    for tag, cols in (('v7e', base183()), ('v8s1', sel)):
        r1 = fitw(d, cols, 'Y1', ys, (31, 500, 400))
        r3 = fitw(d, cols, 'Y3', ys, (15, 100, 1200))
        p1 = r1 / pd.Series(r1, index=te.index).groupby([te[k] for k in KEY]).transform('sum').to_numpy()
        out[f'{tag}_p1'], out[f'{tag}_p3'] = p1, np.maximum(r3, p1)
        out[f'{tag}_p3p'] = t6_base.p3prime(out, f'{tag}_p3')[0]
        top = out.sort_values(KEY + [f'{tag}_p3p', f'{tag}_p1', 'umaban'], ascending=[True] * 3 + [False, False, True],
                              kind='mergesort').groupby(KEY, sort=False).head(1)
        q = out[f'{tag}_p3p'].clip(1e-6, 1 - 1e-6)
        ll = (out.Y3 * np.log(q) + (1 - out.Y3) * np.log(1 - q)).groupby([out[k] for k in KEY]).sum()
        yr = out.groupby(KEY).year.first()
        res[tag] = {part: dict(top3=round(100 * top[top.year.isin(yy)].Y3.mean(), 2),
                               LL3=round(float(ll[yr.isin(yy)].mean()), 4), races=int(yr.isin(yy).sum()))
                    for part, yy in (('2016〜19', vs.SEL_Y), ('2020〜21', vs.CHK_Y))}
        log('final', tag, res[tag])
    fav = out[out['pop'] == 1].drop_duplicates(KEY)
    res['1番人気'] = {part: dict(top3=round(100 * fav[fav.year.isin(yy)].Y3.mean(), 2))
                     for part, yy in (('2016〜19', vs.SEL_Y), ('2020〜21', vs.CHK_Y))}
    res_save('final', res)


# ================================================================ 答え合わせ
def open_():
    if OUT_P.exists():
        log('open は済み'); return
    R = res_load()
    cols = R['select']['cols']
    if sorted(cols) == sorted(base183()):
        x = pd.read_parquet(eo.OUT_P)
        x = x.rename(columns={'v7epre_p1': 'v8_p1', 'v7epre_p3': 'v8_p3', 'v7epre_p3p': 'v8_p3p'})
        x.to_parquet(OUT_P, index=False)
        log('決まった形 = 第 7 版 e と同じ列: 予想はそのまま写した'); return
    wait_mem()
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT))
    assert len(T) == 172738
    for f in [v7d.COP, v7d.JOP, eo.fpath('open')] + [fpath(g, 'open') for g in G]:
        T = T.merge(vo.nk(pd.read_parquet(f)), on=Q5, how='left', validate='1:1')
    X6 = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XB = vo.nk(pd.read_parquet(V3 / 'feat_v7b_explore.parquet'))
    X = X6.merge(XB[Q5 + vo.B7], on=Q5, how='left', validate='1:1')
    del X6, XB
    for f in [v7d.CEX, v7d.JEX, eo.fpath('explore')] + [fpath(g, 'explore') for g in G]:
        X = X.merge(vo.nk(pd.read_parquet(f)), on=Q5, how='left', validate='1:1')
    assert X.race_date.max() < '2022-01-01' and set(T.columns) <= set(X.columns)
    ALL = o.sort4(pd.concat([X[list(T.columns)], T], ignore_index=True))
    del X
    assert not ALL.duplicated(Q5).any()
    P = []
    for name, lo, hi in o.SEGS:
        wait_mem()
        tr = ALL[ALL.race_date < lo]
        te = o.seg_rows(T, lo, hi)
        r = {}
        for t in ('Y1', 'Y3'):
            m = vc.train(tr, t, cols)
            z = d3.logit((1 if t == 'Y1' else 3) / te.n.to_numpy(float))
            r[t] = d3.sig(z + m.predict(te[cols].astype(float), raw_score=True))
        x = te[Q5 + ['year', 'n', 'Y1', 'Y3', 'pop']].copy()
        x['seg'] = name
        p1 = r['Y1'] / pd.Series(r['Y1'], index=x.index).groupby([x[k] for k in KEY]).transform('sum').to_numpy()
        x['v8_p1'], x['v8_p3'] = p1, np.maximum(r['Y3'], p1)
        x['v8_p3p'] = t6_base.p3prime(x, 'v8_p3')[0]
        P.append(x)
        log('区切り', name, '学び', len(tr), '予想', len(x))
    out = pd.concat(P, ignore_index=True).sort_values(Q5, kind='mergesort').reset_index(drop=True)
    assert len(out) == 172738 and out.v8_p3p.notna().all()
    out.to_parquet(OUT_P, index=False)
    log('保存', OUT_P, out.shape)


def evaluate():
    R = res_load()
    if 'eval' in R:
        log('eval は済み'); return
    p = E.load()
    for f, c in ((eo.OUT_P, 'v7epre'), (OUT_P, 'v8')):
        x = pd.read_parquet(f)
        x['race_no'], x['umaban'] = x.race_no.astype(int), x.umaban.astype(int)
        p = p.merge(x[Q5 + [c + '_p1', c + '_p3p']], on=Q5, how='left', validate='1:1')
    assert p.v7epre_p1.notna().all() and p.v8_p1.notna().all()
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT, columns=Q5 + ['b_young', 'l_debut']))
    sc = T.groupby(KEY).agg(shinba=('b_young', lambda v: float((v.fillna(0) % 10 == 1).any())),
                            debut=('l_debut', lambda v: float((v == 1).any())))
    tops = {'v8': E.top(p, 'v8_p3p', 'v8_p1'), 'v7e': E.top(p, 'v7epre_p3p', 'v7epre_p1')}
    srt = p.sort_values(KEY + ['v8_p3p'], ascending=[True] * 3 + [False], kind='mergesort')
    rk = srt.groupby(KEY, sort=False).cumcount()
    t1 = srt[rk == 0].set_index(KEY).v8_p3p
    t2 = srt[rk == 1].set_index(KEY).v8_p3p
    gap = t1 - t2.reindex(t1.index)
    fav = p[p['pop'] == 1].drop_duplicates(KEY).set_index(KEY)
    Rr = pd.DataFrame({k: v.set_index(KEY).Y3 for k, v in tops.items()})
    for k, v in tops.items():
        v = v.set_index(KEY)
        Rr[k + '_w'], Rr[k + '_pay'] = v.Y1, v.pay_win
    Rr['fav'], Rr['fav_w'], Rr['fav_pay'] = fav.Y3, fav.Y1, fav.pay_win
    Rr['year'] = tops['v8'].set_index(KEY).year
    Rr = Rr.join(sc).join(gap.rename('gap'))
    Rr['close'] = (Rr.gap <= Rr.gap.quantile(0.25)).astype(float)
    Rr['date'] = Rr.index.get_level_values('race_date')

    def dse(g, a, b):
        x = (g[a] - g[b]).dropna()
        dd = x.groupby(g.date[x.index]).agg(['sum', 'size'])
        mm = dd['sum'].sum() / dd['size'].sum()
        se = np.sqrt(((dd['sum'] - mm * dd['size']) ** 2).sum()) / dd['size'].sum()
        return f'{100 * mm:+.2f} ±{200 * se:.2f}'

    def row(lab, g):
        return {'区分': lab, 'レース': len(g), '第8版段1': round(100 * g.v8.mean(), 1), '第7版e': round(100 * g.v7e.mean(), 1),
                '1番人気': round(100 * g.fav.mean(), 1), '差 8−7e': dse(g, 'v8', 'v7e'), '差 8−人気': dse(g, 'v8', 'fav')}

    def row_w(lab, g):
        return {'区分': lab, '勝率 8': round(100 * g.v8_w.mean(), 1), '勝率 7e': round(100 * g.v7e_w.mean(), 1),
                '勝率 人気': round(100 * g.fav_w.mean(), 1), '単回 8': round(g.v8_pay.mean(), 1),
                '単回 7e': round(g.v7e_pay.mean(), 1), '単回 人気': round(g.fav_pay.mean(), 1),
                '単回の欠け': int(g.v8_pay.isna().sum())}
    rows = [row('全体', Rr)] + [row(str(y), g) for y, g in Rr.groupby('year')]
    wrows = [row_w('全体', Rr)] + [row_w(str(y), g) for y, g in Rr.groupby('year')]
    sub = [row('新馬戦', Rr[Rr.shinba == 1]), row('転入初戦(新馬戦でなく走歴の無い馬がいる)', Rr[(Rr.shinba == 0) & (Rr.debut == 1)]),
           row('接戦(第 8 版の 1 位 − 2 位 が下 1/4)', Rr[Rr.close == 1])]
    res_save('eval', {'rows': rows, 'wrows': wrows, 'sub': sub, 'gap_q25': float(Rr.gap.quantile(0.25))})
    log('eval', rows[0], sub)


# ================================================================ md
def pct(v):
    return '—' if v is None else f'{100 * v:.1f}%'


def tab(rows):
    ks = list(rows[0])
    return '\n'.join(['| ' + ' | '.join(ks) + ' |', '|' + '---|' * len(ks)] +
                     ['| ' + ' | '.join(str(r[k]) for k in ks) + ' |' for r in rows])


def jrow(name, j):
    return f'| {name} | {j["gain"]} | {j["se"]} | {j["years"]} | {j["ok"]} |'


def write_md():
    R = res_load()
    L = ['# 第 8 版 段 1: 2016 年から作れる新しい材料 6 群 → 自動の足し引き → 答え合わせ', '',
         '- 台本 src/v8s1_copy.py(Supabase から読むだけ)・src/v8s1_run.py(定義は docstring の「決め」。結果を見て変えていない)。',
         '- 南関のオッズ・人気は材料に使わない(a8_j_last_pop = 中央の過去の人気は j7_last_pop と同じ定義で入れた)。', '']
    cp = V3 / 'v8s1_copy.json'
    if cp.exists():
        C = json.loads(cp.read_text(encoding='utf-8'))
        L += ['## 写した表(Supabase・読むだけ)', '', '| 表 | 行 | DB の件数 | sha256 |', '|---|---|---|---|'] + \
             [f'| {k} | {v["rows"]} | {v["db_count"]} | {v["sha256"][:16]}… |' for k, v in C.items()] + \
             ['', '- corners・furlongs・finish_note は手元の写し(archive + db_*_confirm/sealed)にあるので写していない。', '']
    fj = R.get('feat_j')
    if fj:
        L += ['## 中央 a8_j_ のつながり(南関の行・年ごと)', '',
              '- nar_jra_runs の年ごとの走り: ' + '・'.join(f'{k} {v}' for k, v in fj['jr_per_year'].items()), '',
              '| 年 | 行 | nar_jra_horses とつながった | a8_j_n > 0 | 参考 j7_n > 0(KDSCOPE) |', '|---|---|---|---|---|'] + \
             [f'| {y} | {v["rows"]} | {pct(v["link"])} | {pct(v["a8_run"])} | {pct(v["j7_run"])} |' for y, v in fj['rate'].items()] + ['']
    fs = R.get('feat_s')
    if fs:
        L += ['## セリの照合率', '', '### セリの側(hba・jrha・セリの年ごと)', '',
              '| 年 | 行 | 馬名 + 父母一致 | 馬名だけ(台帳に無い) | 母・生年・父 | 馬名一致で父母が違う(捨てた) | 採った計 |',
              '|---|---|---|---|---|---|---|'] + \
             [f'| {y} | {v["rows"]} | {pct(v["name"])} | {pct(v["name_nokd"])} | {pct(v["dam"])} | {pct(v["name_ng"])} | {pct(v["matched"])} |'
              for y, v in fs['rate']['sale_side'].items()] + \
             ['', '### 南関の行の側(レースの年ごと・レースの日より前のセリ)', '',
              '| 年 | 行 | 1 歳等のセリに上場あり | 落札あり | 地方在籍の落札あり | 2 歳の行 | 2 歳の上場あり |', '|---|---|---|---|---|---|---|'] + \
             [f'| {y} | {v["rows"]} | {pct(v["app"])} | {pct(v["sold"])} | {pct(v["loc"])} | {v["rows2"]} | {pct(v["app2"])} |'
              for y, v in fs['rate']['race_side'].items()] + ['']
    L += ['## 列の欠け率・平均', '', '| 列 | 欠け 作る | 欠け 答え合わせ | 平均 作る |', '|---|---|---|---|']
    for g, cols in G.items():
        f = R.get('feat_' + g)
        for c in cols:
            L.append(f'| {c} | {pct(f["miss"][c][0])} | {pct(f["miss"][c][1])} | {f["mean"][c][0]:.4f} |' if f else f'| {c} | — | — | — |')
    L += ['', '## 漏れ検査(v7e と同じ 20 日・その日までに切り、その日の結果を空にして作り直し)', '']
    for g in G:
        f = R.get('feat_' + g)
        if f and 'leak' in f:
            L.append(f'- {GNAME[g]}: ' + '・'.join(f'{k} {v["match_days"]} / {v["days"]} 日一致・セル {v["match"]} / {v["cells"]}'
                                                  for k, v in f['leak'].items()))
    S = R.get('select')
    if S:
        L += ['', '## 自動の足し引き(2016〜19・Y3 15/500/800・線 = 伸び > 2 × 標準誤差 かつ 4 年中 3 年)', '',
              f'- 土台 183 列の和 {S["sum_base183"]}', '', '### 段 0', '', '| 形 | 伸び | 標準誤差 | 年ごと | 通った |', '|---|---|---|---|---|',
              jrow(GNAME['drop40'], S['step0']), '',
              f'- 40 列を抜いた形を土台に: **{S["drop40"]}**(土台 {S["base_n"]} 列)', '']
        for i, rd in enumerate(S['rounds']):
            L += [f'### 足す {i + 1} 回目(今の形: {rd["cur"] or "土台"}・和 {rd["sum_cur"]})', '',
                  '| 群 | 伸び | 標準誤差 | 年ごと | 通った |', '|---|---|---|---|---|'] + \
                 [jrow(GNAME[g], j) for g, j in rd['res'].items()] + ['', f'- 足した: {rd["pick"] or "なし"}', '']
        for i, rd in enumerate(S['drops']):
            L += [f'### 抜く {i + 1} 回目(今の形: {rd["cur"]})', '', '| 群 | 伸び | 標準誤差 | 年ごと | 通った |', '|---|---|---|---|---|'] + \
                 [jrow(GNAME[g], j) for g, j in rd['res'].items()] + ['', f'- 抜いた: {rd["pick"] or "なし"}', '']
        L += [f'- **決まった形(第 8 版 段 1)**: 群 {S["groups"] or "なし"}・{len(S["cols"])} 列・和 {S["sum_final"]}', '']
    F = R.get('final')
    if F:
        L += ['## 2016〜21 の当てはめ外(2020〜21 はここで 1 回だけ見た・Y1 31/500/400・Y3 15/100/1200)', '',
              '| 版 | 期間 | ◎ 3 着以内 % | 3 着以内の対数尤度/レース | レース |', '|---|---|---|---|---|']
        for tag in ('v7e', 'v8s1'):
            for part, v in F[tag].items():
                L.append(f'| {tag} | {part} | {v["top3"]} | {v["LL3"]} | {v["races"]} |')
        for part, v in F['1番人気'].items():
            L.append(f'| 1 番人気 | {part} | {v["top3"]} | — | — |')
        L.append('')
    if 'eval' in R:
        V = R['eval']
        L += ['## 答え合わせ: ◎ の 3 着以内率 %(2022-01〜2026-08・前日版・差 ± = 日ごとにまとめた 2 × 標準誤差)', '',
              tab(V['rows']), '', '## 勝率 %・単勝回収率 %(◎ に 100 円ずつ・1 番人気も同じ)', '', tab(V['wrows']), '',
              f'## 場面別(接戦 = 第 8 版の p3′ の 1 位 − 2 位 ≤ {V["gap_q25"]:.4f})', '', tab(V['sub']), '']
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')
    log('md', MD)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    steps = {'feat': [feat], 'select': [select], 'final': [final], 'open': [open_], 'eval': [evaluate], 'md': [write_md],
             'all': [feat, select, final, open_, evaluate, write_md]}[cmd]
    for s in steps:
        s()
