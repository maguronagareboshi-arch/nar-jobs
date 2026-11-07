# -*- coding: utf-8 -*-
"""走破指数(SI)を南関以外の 10 場へ広げる台本(2026-11-07・枝 si5-all・⛔まだ本番の便には入れない)。

  python -X utf8 cloud/si_all.py run   [--track 高知,佐賀] [--from 2024-01-01] [--to 2024-12-31] [--out x.csv.gz] [--apply]
  python -X utf8 cloud/si_all.py check --out DIR        # 照合の数表(DB に書かない)→ DIR/check.json・check.md

- 対象= 門別・盛岡・水沢・金沢・笠松・名古屋・園田・姫路・高知・佐賀。南関 4 場は pipeline/ai/v3/si5_store.py のまま
  (この台本は南関を書かない= --apply は南関を拒む)。帯広ばは外す。予想 AI の便(nar-ai-v3)には入れない。
- 基準 bc= t4_base.build の旧 SI と同じ作り: 年 y の基準は前の 3 年(y−3〜y−1)のレース値(1〜3 着の走破の平均 ÷ 距離/1000)
  から、コース(場×距離×芝ダ)の基準 b とクラス区分の差 δ と日の差 D を 10 回交互に当てはめ(fit_window)、b を使う。
  クラス区分は baba.band_of(全場で使える帯)。30 R 未満の帯は同じ字の小さい帯をまとめ、まとめても足りなければ当てはめから外す。
  δ の 0 点= C1(無ければ東海の C・まとめた C*・それも無ければ一番多い帯)。場ごとに別々に当てはめる(場の間のずれ o_s= 0)。
  南関 4 場は照合用にだけ 4 場まとめて当てはめる(t4_base と同じ)。
- 日の馬場差 D= cloud/baba.py の日の値 projhalf の d1(1000m あたりの秒・遅い日が正)= classfirst の d1 と
  出走馬の力の見積もり proj_days の半々(力の見積もりが無い日は classfirst のまま= baba.blend_proj と同じ)。
  nar_meta baba_diff は直近 90 日しか無いので、baba の関数で全日を as-of(その日より前の走だけ)で組み直す。
  照合用に t4_base と同じ作りの D(その日のレース残差の中央値を n/(n+5) で場×馬場のふだんへ寄せる)も出す(D_t4)。
- 式= 80 + (1000/B)·(B − T' + D·d/1000) + 2·(斤量 − 55)。B= bc·d/1000・T'= min(走破, 勝ち時計 + 2·d/1000)。
  流れの直し(disp)・D5・o_s は入れない。
- 読み方= nar_runs・nar_races を場×月で、要る列だけ(送信量が枠超えの月= 丸ごと読まない)。
  基準と baba の窓のぶん、--from の 3 年前の 1 月から読む。proj の馬の走歴のため 14 場を読む(書くのは対象の場だけ)。
- 出力の形= nar_si5 と同じ(track, race_date, race_no, runner_number, horse_key= 馬名|生年月日, si5 小数 1 桁)。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import baba  # noqa: E402

TARGETS = ['門別', '盛岡', '水沢', '金沢', '笠松', '名古屋', '園田', '姫路', '高知', '佐賀']
NANKAN = ['浦和', '船橋', '大井', '川崎']
ALL = TARGETS + NANKAN
RK = ['track', 'race_date', 'race_no']
MIN_R = 30
RUN_COLS = ['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'birth_date', 'finish', 'finish_note',
            'time_sec', 'carried_weight', 'si5']
RACE_COLS = ['track', 'race_date', 'race_no', 'distance_m', 'race_name', 'going', 'race_kind', 'surface']
RE_LV = re.compile(r'[ABC][0-9]?')
TABLE = 'nar_si5'


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 読み込み(場×月・要る列だけ)
def months(lo, hi):
    a = dt.date.fromisoformat(lo).replace(day=1)
    end = dt.date.fromisoformat(hi) + dt.timedelta(days=1)
    while a < end:
        b = (a + dt.timedelta(days=32)).replace(day=1)
        yield max(a.isoformat(), lo), min(b, end).isoformat()
        a = b


def _fetch(base, key, table, cols, order, track, m1, m2):
    path = (f"/rest/v1/{table}?select={','.join(cols)}&track=eq.{urllib.parse.quote(track)}"
            f"&race_date=gte.{m1}&race_date=lt.{m2}&order={order}")
    return baba.rows_all(base, key, path)


def load(base, key, tracks, lo, hi, workers=6):
    jobs = [(t, m1, m2) for t in tracks for m1, m2 in months(lo, hi)]
    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        runs = list(ex.map(lambda j: _fetch(base, key, 'nar_runs', RUN_COLS,
                                            'race_date.asc,race_no.asc,runner_number.asc', *j), jobs))
        races = list(ex.map(lambda j: _fetch(base, key, 'nar_races', RACE_COLS, 'race_date.asc,race_no.asc', *j), jobs))
    runs = [r for x in runs for r in x]
    races = [r for x in races for r in x]
    log(f'読んだ: 走 {len(runs):,} 行・レース {len(races):,} 行({len(jobs)} 場月・{time.time() - t0:.0f} 秒)')
    return runs, races


# ---------------------------------------------------------------- 表
def races_frame(races):
    R = pd.DataFrame(races, columns=RACE_COLS)
    R = R[R.track.isin(ALL)].copy()
    R['race_date'] = R.race_date.astype(str).str[:10]
    R['race_no'] = pd.to_numeric(R.race_no).astype(int)
    R['distance_m'] = pd.to_numeric(R.distance_m, errors='coerce')
    R['k0'] = [baba.band_of(n, t, k) for n, t, k in zip(R.race_name, R.track, R.race_kind)]
    R['year'] = R.race_date.str[:4].astype(int)
    R['course'] = (R.track + '_' + R.distance_m.fillna(0).astype(int).astype(str) + '_'
                   + R.surface.fillna('').astype(str))
    R['dtk'] = R.race_date + '_' + R.track

    def _mode(x):
        v = [s for s in x if isinstance(s, str) and s]
        return max(v, key=lambda s: (v.count(s), -v.index(s))) if v else np.nan
    g = R.sort_values('race_no').groupby('dtk').going.agg(_mode)
    R['gmode'] = R.dtk.map(g)
    return R.drop_duplicates(RK).reset_index(drop=True)


def runs_frame(runs):
    U = pd.DataFrame(runs, columns=RUN_COLS)
    U = U[U.track.isin(ALL)].copy()
    U['race_date'] = U.race_date.astype(str).str[:10]
    for c in ['race_no', 'runner_number']:
        U[c] = pd.to_numeric(U[c]).astype(int)
    for c in ['finish', 'time_sec', 'carried_weight', 'si5']:
        U[c] = pd.to_numeric(U[c], errors='coerce')
    U['finish_note'] = U.finish_note.fillna('').astype(str)
    U = U[~U.finish_note.str.contains('取消|除外')]          # t4_base と同じ= 取消・除外は走りに数えない
    U['hk'] = U.horse_name.fillna('').astype(str) + '|' + U.birth_date.fillna('').astype(str).str[:10]
    return U.reset_index(drop=True)


# ---------------------------------------------------------------- 基準(t4_base の作り)
def kmap_make(kc):
    kc = {k: int(v) for k, v in dict(kc).items() if k}
    small = {k: v for k, v in kc.items() if v < MIN_R}
    m = {}
    for k, c in kc.items():
        if c >= MIN_R:
            m[k] = k
        elif RE_LV.fullmatch(k):
            pooled = sum(v for k2, v in small.items() if RE_LV.fullmatch(k2) and k2[0] == k[0])
            m[k] = k[0] + '*' if pooled >= MIN_R else None
        else:
            m[k] = None
    return m


def ref_class(s, counts):
    for c in ('C1', 'C', 'C*'):
        if c in s.index:
            return c
    return max(s.index, key=lambda k: counts.get(k, 0))


def fit_window(W):
    """t4_base.fit_window と同じ(0 点の帯だけ場に合わせて選ぶ)"""
    v = W.v.values
    cs, ks, ds = W.course.values, W.k.values, W.dtk.values
    cnt = pd.Series(ks).value_counts().to_dict()
    dl = np.zeros(len(W)); D = np.zeros(len(W))
    s = None
    for _ in range(10):
        b = pd.Series(v - dl - D).groupby(cs).transform('median').values
        s = pd.Series(v - b - D).groupby(ks).median()
        s = s - s[ref_class(s, cnt)]
        dl = pd.Series(ks).map(s).values
        D = pd.Series(v - b - dl).groupby(ds).transform('median').values
    own = pd.Series(b, index=cs).groupby(level=0).first().to_dict()
    Dd = pd.Series(D, index=ds).groupby(level=0).first()
    return own, s.to_dict(), Dd


def course_b(courses, own):
    """t4_base.course_b と同じ(近い距離 ±200 m から借りる・同じ場・同じ芝ダ・同じ差なら短い方)"""
    by = {}
    for c, b in own.items():
        t, d, sf = c.split('_')
        by.setdefault((t, sf), []).append((int(d), b))
    out = {}
    for c in courses:
        if c in own:
            out[c] = own[c]
            continue
        t, d, sf = c.split('_')
        d = int(d)
        cand = sorted((abs(dd - d), dd, b) for dd, b in by.get((t, sf), []) if abs(dd - d) <= 200)
        out[c] = cand[0][2] if cand else np.nan
    return out


def race_values(U, R):
    top = U[(U.finish <= 3) & U.time_sec.notna()]
    v = top.groupby(RK).time_sec.mean().rename('vT').reset_index()
    R = R.drop(columns=[c for c in ('vT', 'v') if c in R.columns]).merge(v, on=RK, how='left')
    R['v'] = R.vT / (R.distance_m / 1000)
    return R


def build_base(R, groups, years):
    """R(race_values 済み)に bc・dl・r・Draw・n・D_t4 を足す。groups= 一緒に当てはめる場の組の列"""
    R = R.copy()
    for c in ['bc', 'dl', 'r', 'Draw', 'n', 'D_t4']:
        R[c] = np.nan
    for g in groups:
        ing = R.track.isin(g)
        for y in years:
            win = [2014] if y == 2014 else [x for x in range(y - 3, y) if x >= 2014]
            Wa = R[ing & R.year.isin(win) & R.v.notna()]
            iy = R.index[ing & (R.year == y)]
            if not len(Wa) or not len(iy):
                continue
            cc = Wa.course.value_counts()
            km = kmap_make(Wa.k0.value_counts())
            ownset = set(cc[cc >= MIN_R].index)
            W = Wa[Wa.course.isin(ownset)].assign(k=Wa.k0.map(km))
            W = W[W.k.notna()]
            if not len(W):
                continue
            own, delta, Dd = fit_window(W)
            gm = pd.DataFrame({'D': Dd}).join(W.drop_duplicates('dtk').set_index('dtk')[['track', 'gmode']])
            Dm_tg = gm.groupby(['track', 'gmode']).D.mean().to_dict()
            Dm_t = gm.groupby('track').D.mean().to_dict()
            Ry = R.loc[iy]
            bc = Ry.course.map(course_b(Ry.course.unique(), own)).astype(float)
            bown = Ry.course.map(own).astype(float)
            dl = Ry.k0.map(lambda k: delta.get(km.get(k)) if k else None).astype(float)
            r = Ry.v - bown - dl
            Draw = r.groupby(Ry.dtk).transform('median')
            n = r.notna().groupby(Ry.dtk).transform('sum')
            Dm = pd.Series([Dm_tg.get((t, gg), Dm_t.get(t, 0.0)) for t, gg in zip(Ry.track, Ry.gmode)],
                           index=iy).fillna(0.0)
            D = np.where(n > 0, n / (n + 5) * Draw + 5 / (n + 5) * Dm, Dm)
            R.loc[iy, 'bc'] = bc.values
            R.loc[iy, 'dl'] = dl.values
            R.loc[iy, 'r'] = r.values
            R.loc[iy, 'Draw'] = Draw.values
            R.loc[iy, 'n'] = n.values
            R.loc[iy, 'D_t4'] = D
    return R


# ---------------------------------------------------------------- 日の馬場差(baba.py projhalf)
def baba_inputs(U, R):
    meta = R.set_index(RK)[['distance_m', 'k0', 'going', 'surface']].to_dict('index')
    ok = (U.finish_note == '') & U.time_sec.notna() & U.finish.notna() & (U.finish >= 1) & U.track.isin(
        list(baba.TRACK2PREFIX))
    X = U[ok]
    best = {}
    for t, d, rn, fin, ts in zip(X.track, X.race_date, X.race_no, X.finish, X.time_sec):
        if fin > baba.TOP_N:
            continue
        k = (t, d, int(rn), int(fin))
        if k not in best or ts < best[k]:
            best[k] = ts
    samples = []
    for (t, d, rn, fin), ts in best.items():
        m = meta.get((t, d, rn))
        if not m or not m['distance_m'] or m['distance_m'] != m['distance_m']:
            continue
        samples.append((t, d, int(m['distance_m']), m['k0'], float(ts), str(m['going'] or ''), rn, fin))
    pr = []
    for t, d, rn, h, fin, ts in zip(X.track, X.race_date, X.race_no, X.hk, X.finish, X.time_sec):
        m = meta.get((t, d, int(rn)))
        if not m or not m['distance_m'] or m['distance_m'] != m['distance_m'] or h.startswith('|'):
            continue
        pr.append((t, d, int(rn), h, int(m['distance_m']), m['surface'], int(fin), float(ts)))
    return samples, pr


def baba_days(U, R, targets, today):
    """→ ({(日, 場): projhalf の d1}, {(日, 場): classfirst の d1}, {(日, 場): proj})"""
    samples, pr = baba_inputs(U, R)
    t0 = time.time()
    days, _, _ = baba.build_days(samples, set(targets), 'classfirst', today=today, frozen={}, rebuild_all=True)
    log(f'  classfirst {sum(len(v) for v in days.values()):,} 場日({time.time() - t0:.0f} 秒)')
    t0 = time.time()
    pv = baba.proj_days(pr, set(targets))
    log(f'  力の見積もり {len(pv):,} 場日({time.time() - t0:.0f} 秒)')
    p2t = {v: k for k, v in baba.TRACK2PREFIX.items()}
    cf, out = {}, {}
    for d, cells in days.items():
        for pf, c in cells.items():
            if 'd1' not in c:
                continue
            k = (d, p2t[pf])
            cf[k] = float(c['d1'])
            v = pv.get(k)
            out[k] = round(0.5 * cf[k] + 0.5 * v, 2) if v is not None else cf[k]
    return out, cf, pv


# ---------------------------------------------------------------- 指数
def si_table(U, R, Dbaba):
    """U の行に distance・bc・D を付けて SI(baba の D)と SI_t4(t4 の D)と出せない理由を足す"""
    X = U.merge(R[RK + ['distance_m', 'k0', 'year', 'bc', 'D_t4', 'Draw', 'n', 'dtk']], on=RK, how='left')
    X['D'] = [Dbaba.get((d, t), np.nan) for d, t in zip(X.race_date, X.track)]
    dd = X.distance_m.to_numpy(float)
    X['win_t'] = X.groupby(RK).time_sec.transform('min')
    X['Tt'] = np.minimum(X.time_sec, X.win_t + 2.0 * dd / 1000)
    B = X.bc.to_numpy(float) * dd / 1000
    base = 1000 / B * (B - X.Tt.to_numpy(float)) + 2 * (X.carried_weight.to_numpy(float) - 55)
    X['SI'] = 80 + base + 1000 / B * X.D.to_numpy(float) * dd / 1000
    X['SI_t4'] = 80 + base + 1000 / B * X.D_t4.to_numpy(float) * dd / 1000
    why = np.full(len(X), '', dtype=object)
    for m, w in [(X.D.isna(), 'no_day'), (X.carried_weight.isna(), 'no_weight'), (X.bc.isna(), 'no_base'),
                 (X.distance_m.isna(), 'no_dist'), (X.time_sec.isna(), 'no_time')]:
        why[m.to_numpy()] = w                                 # 後ろほど優先(時計なしが一番先の理由)
    X['why'] = why
    return X


def out_frame(X, col='SI'):
    x = pd.DataFrame({'track': X.track, 'race_date': X.race_date, 'race_no': X.race_no.astype(int),
                      'runner_number': X.runner_number.astype(int), 'horse_key': X.hk, 'si5': np.round(X[col], 1)})
    x = x[x.track.isin(TARGETS) & np.isfinite(x.si5)]
    assert not x.duplicated(['track', 'race_date', 'race_no', 'runner_number']).any(), '同じ走が 2 行ある'
    return x.reset_index(drop=True)


def push(x):
    assert not x.track.isin(NANKAN).any(), '南関は si5_store が書く'
    sys.path.insert(0, str(HERE.parent / 'pipeline/ai'))
    import ai_common as B1
    base, key = B1.creds()
    recs = x.to_dict('records')
    for i in range(0, len(recs), 2000):
        st, err = B1.upsert(base, key, TABLE, 'track,race_date,race_no,runner_number', recs[i:i + 2000])
        if st not in (200, 201, 204):
            raise SystemExit(f'nar_si5 upsert failed: {st} {err}')
    log(f'nar_si5 へ {len(recs):,} 行')


def compute(runs, races, lo, hi, nankan_joint=True):
    """lo〜hi の指数。runs/races は lo の 3 年前の 1 月から(REST の行の形)"""
    R = races_frame(races)
    U = runs_frame(runs)
    R = race_values(U, R)
    years = list(range(int(lo[:4]), int(hi[:4]) + 1))
    groups = ([NANKAN] if nankan_joint else [[t] for t in NANKAN]) + [[t] for t in TARGETS]
    R = build_base(R, groups, years)
    targets = sorted({d for d in R.race_date if lo <= d <= hi})
    log(f'基準を組んだ: {years}・日 {len(targets)}')
    Db, cf, pv = baba_days(U, R, targets, dt.date.fromisoformat(hi) + dt.timedelta(days=1))
    X = si_table(U, R, Db)
    X = X[(X.race_date >= lo) & (X.race_date <= hi)].reset_index(drop=True)
    return X, cf, pv


# ---------------------------------------------------------------- 照合
def _corr(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 2 else None


def pair_corr(X, col):
    Y = X[np.isfinite(X[col])].sort_values(['hk', 'race_date', 'race_no'])
    Y = Y[~Y.hk.str.startswith('|')]
    same = Y.hk.to_numpy()[1:] == Y.hk.to_numpy()[:-1]
    v = Y[col].to_numpy()
    return _corr(v[:-1][same], v[1:][same]), int(same.sum())


def rank_corr(X, col):
    Y = X[np.isfinite(X[col]) & X.finish.notna()].copy()
    c = Y.groupby(RK)[col].transform('count')
    Y = Y[c >= 4]
    Y['a'] = Y.groupby(RK)[col].rank(ascending=False)
    Y['b'] = Y.groupby(RK).finish.rank()
    g = Y.groupby(RK)
    ma, mb = g.a.transform('mean'), g.b.transform('mean')
    Y['xy'] = (Y.a - ma) * (Y.b - mb); Y['xx'] = (Y.a - ma) ** 2; Y['yy'] = (Y.b - mb) ** 2
    S = Y.groupby(RK)[['xy', 'xx', 'yy']].sum()
    S = S[(S.xx > 0) & (S.yy > 0)]
    rho = S.xy / np.sqrt(S.xx * S.yy)
    return (float(rho.mean()) if len(rho) else None), int(len(rho))


def r2(v, k=2):
    return None if v is None or v != v else round(float(v), k)


def to_md(res):
    a = res['a']
    L = [f"# 走破指数を全場へ 照合({res['range'][0]}〜{res['range'][1]}・走 {res['runs']:,})", '',
         '## (a) 南関 2024 と本番 si5', '', '| 値 | 件数 | 平均の差 | 差の絶対値 95% 点 | 相関 |', '|---|---|---|---|---|']
    for col, nm in [('SI_t4', '新台本の基準+t4 の作りの D'), ('SI', '新台本の基準+baba の日の値')]:
        x = a[col]
        L.append(f"| {nm} | {x['n']:,} | {x['mean_diff']} | {x['p95_abs']} | {x['corr']} |")
    L += ['', '場ごと(t4 の D): ' + '・'.join(f"{t} 差 {v['mean_diff']} 相関 {v['corr']}" for t, v in a['SI_t4']['by_track'].items()),
          '場ごと(baba の D): ' + '・'.join(f"{t} 差 {v['mean_diff']} 相関 {v['corr']}" for t, v in a['SI']['by_track'].items()),
          f"日の値の相関(南関・baba の D と t4 の D): {a['day_D_corr_baba_vs_t4']}", '',
          '本番 si5 は D5(力の分かった馬からの日の値と半々)・o_s(4 場の物差しのずれ)・disp(流れと大井の砂替え)が入り、'
          'クラス区分も t4 の parse_name(新台本は baba.band_of)・大井の砂替えの D の扱い(sealed の定数)も無いので差は 0 にならない。', '',
          '## (b) 場ごと 2024〜2025(SI= baba の D・SI_t4= t4 の D)', '',
          '| 場 | 走 | 出せない率 | 続く2走の相関 SI / t4 | 着順との順位相関 SI / t4 | 平均 | 理由の内訳 |', '|---|---|---|---|---|---|---|']
    for t, e in res['b'].items():
        s, s4 = e['SI'], e['SI_t4']
        extra = f" / 本番 {e['si5']['pair_corr']}・{e['si5']['rank_corr']}" if 'si5' in e else ''
        L.append(f"| {t} | {e['runs']:,} | {e['null_rate']} | {s['pair_corr']} / {s4['pair_corr']}{extra} | "
                 f"{s['rank_corr']} / {s4['rank_corr']} | {s['mean']} | "
                 + '・'.join(f'{k} {v}' for k, v in e['null_why'].items()) + ' |')
    L += ['', '順位相関= レースの中の指数の順と着順の相関の平均(1 に近いほど着順どおり)。', '', '### クラス帯ごとの平均(50 走以上)', '']
    for t, e in res['b'].items():
        L.append(f'- {t}: ' + '・'.join(f'{k} {v[0]}({v[1]})' for k, v in
                                         sorted(e['class_mean'].items(), key=lambda kv: kv[1][0] or 0)))
    L += ['', '## (c) 手で計算する材料(場ごと 1 走・2025 の最初の勝ち馬)', '',
          '式= 80 + 1000/B·(B − T_cut + D·距離/1000) + 2·(斤量 − 55)・B= bc·距離/1000', '',
          '| 場 | 走 | 帯 | 距離 | 時計 | 勝ち時計 | T_cut | bc | D(classfirst・proj) | 斤量 | SI | 手計算 |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for t, r in res['c'].items():
        L.append(f"| {t} | {r['race']} {r['horse']} | {r['class']} | {r['dist']} | {r['time']} | {r['win_time']} | "
                 f"{r['T_cut']} | {r['bc_per1000']} | {r['D_per1000']}({r['D_classfirst']}・{r['D_proj']}) | "
                 f"{r['weight']} | {r['SI']} | {r['SI_by_hand']} |")
    return '\n'.join(L) + '\n'


def check(out):
    base = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    if not base or not key:
        raise SystemExit('SUPABASE_URL / SUPABASE_SERVICE_KEY が無い')
    lo, hi = '2024-01-01', '2025-12-31'
    runs, races = load(base, key, ALL, '2021-01-01', hi)
    X, cf, pv = compute(runs, races, lo, hi)
    res = {'range': [lo, hi], 'runs': int(len(X))}
    # (a) 南関 2024: 新台本の基準+t4 の作りの D と本番 si5
    A = X[X.track.isin(NANKAN) & (X.race_date <= '2024-12-31') & np.isfinite(X.si5)]
    a = {'n_prod': int(len(A))}
    for col in ['SI_t4', 'SI']:
        d = (A[col] - A.si5).to_numpy()
        m = np.isfinite(d)
        a[col] = {'n': int(m.sum()), 'mean_diff': r2(np.mean(d[m])), 'p95_abs': r2(np.percentile(np.abs(d[m]), 95)),
                  'corr': r2(_corr(A[col].to_numpy(), A.si5.to_numpy()), 4)}
        a[col]['by_track'] = {t: {'n': int(np.isfinite((g[col] - g.si5).to_numpy()).sum()),
                                  'mean_diff': r2(np.nanmean((g[col] - g.si5).to_numpy())),
                                  'corr': r2(_corr(g[col].to_numpy(), g.si5.to_numpy()), 4)}
                              for t, g in A.groupby('track')}
    # 日の値どうし(南関): baba の D と t4 の D
    dd = X[X.track.isin(NANKAN)].drop_duplicates('dtk')
    a['day_D_corr_baba_vs_t4'] = r2(_corr(dd.D.to_numpy(float), dd.D_t4.to_numpy(float)), 4)
    res['a'] = a
    # (b) 場ごと
    b = {}
    for t in TARGETS + NANKAN:
        g = X[X.track == t]
        if not len(g):
            continue
        e = {'runs': int(len(g))}
        cols = ['SI', 'SI_t4'] + (['si5'] if t in NANKAN else [])
        for col in cols:
            pc, npair = pair_corr(g, col)
            rc, nrace = rank_corr(g, col)
            e[col] = {'pair_corr': r2(pc, 3), 'pairs': npair, 'rank_corr': r2(rc, 3), 'races': nrace,
                      'mean': r2(np.nanmean(g[col].to_numpy(float)), 1)}
        cm = g[np.isfinite(g.SI)].groupby(g.k0.fillna('(なし)')).SI.agg(['mean', 'count'])
        e['class_mean'] = {k: [r2(v['mean'], 1), int(v['count'])] for k, v in cm.iterrows() if v['count'] >= 50}
        e['null_rate'] = r2(float(np.mean(~np.isfinite(g.SI))), 4)
        e['null_why'] = {k: int(v) for k, v in g.why[g.why != ''].value_counts().items()}
        e['null_why_t4'] = int((~np.isfinite(g.SI_t4)).sum())
        b[t] = e
    res['b'] = b
    # (c) 場ごとに 1 頭 1 走(2025 の最初の開催日の 1R の勝ち馬・値の出た走)
    c = {}
    for t in TARGETS + NANKAN:
        g = X[(X.track == t) & (X.race_date >= '2025-01-01') & np.isfinite(X.SI) & (X.finish == 1)]
        if not len(g):
            continue
        r = g.sort_values(['race_date', 'race_no']).iloc[0]
        B = r.bc * r.distance_m / 1000
        hand = 80 + 1000 / B * (B - r.Tt + r.D * r.distance_m / 1000) + 2 * (r.carried_weight - 55)
        c[t] = {'race': f'{r.race_date} {int(r.race_no)}R {int(r.runner_number)}番', 'horse': r.horse_name,
                'class': r.k0, 'dist': int(r.distance_m), 'time': float(r.time_sec), 'win_time': float(r.win_t),
                'T_cut': round(float(r.Tt), 2), 'bc_per1000': round(float(r.bc), 4), 'B': round(float(B), 3),
                'D_per1000': float(r.D), 'D_classfirst': cf.get((r.race_date, t)), 'D_proj': r2(pv.get((r.race_date, t)), 3),
                'D_t4': r2(r.D_t4, 3), 'weight': float(r.carried_weight), 'finish': int(r.finish),
                'SI': round(float(r.SI), 2), 'SI_by_hand': round(float(hand), 2),
                'si5_prod': r2(r.si5, 1)}
    res['c'] = c
    os.makedirs(out, exist_ok=True)
    Path(out, 'check.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    md = to_md(res)
    Path(out, 'check.md').write_text(md, encoding='utf-8')
    log(md)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['run', 'check'])
    ap.add_argument('--track', default=','.join(TARGETS))
    ap.add_argument('--from', dest='lo', default=None)
    ap.add_argument('--to', dest='hi', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--apply', action='store_true', help='nar_si5 へ upsert(既定は書かない)')
    a = ap.parse_args()
    if a.cmd == 'check':
        check(a.out or 'si_all_check')
        return 0
    tracks = [t for t in a.track.split(',') if t]
    bad = [t for t in tracks if t not in TARGETS]
    if bad:
        raise SystemExit(f'対象外の場: {bad}(南関は si5_store・帯広ばは外す)')
    hi = a.hi or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    lo = a.lo or (dt.date.fromisoformat(hi) - dt.timedelta(days=21)).isoformat()
    base = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    runs, races = load(base, key, ALL, f'{int(lo[:4]) - 3}-01-01', hi)
    X, _, _ = compute(runs, races, lo, hi)
    x = out_frame(X[X.track.isin(tracks)])
    log(f'指数 {len(x):,} 行({lo}〜{hi}・{",".join(tracks)})')
    if a.out:
        x.to_csv(a.out, index=False)
    if a.apply:
        push(x)
    return 0


if __name__ == '__main__':
    sys.exit(main())
