# -*- coding: utf-8 -*-
"""調教(追い切り)の数字を v3 に取り込み、材料 cy_ 8 列(自作)を作る(ユーザー承認 2026-09-27「A はい」「5 年分を入れる」)。

  py -3.12 -X utf8 src/v8cy_build.py          # 取り込み → 材料 → 漏れ検査(20 日)

元: 他場/data/backfill/cyokyo_{大井,船橋,川崎,浦和}_{2021..2026}.csv(読むだけ)。
使う列だけ読む(arrow・horse_tanpyo・work_tanpyo・mark・movie は読まない)。オッズ・人気は使わない。

決め(指示書どおり・結果を見て変えていない):
- 追い切り 1 本 = (馬名・調教日・コース・脚色・5F・半・3F・1F)。複数の出走表に載っていれば 1 本。
  その追い切りが「分かった日」= それが載った出走表のレースの日の最小。
- 出走ごとに、その出走表の追い切り(調教日 < レースの日)から最終追い = kind final の一番新しい日付(無ければ一番新しい日付)。
- 脚色: 馬なり系 0 = 馬なり・楽走・末抑え・直抑え / 強め系 1 = 強め・稍強め・末強め・直強め /
  一杯系 2 = 一杯・末一杯・直一杯・稍一杯・叩一杯 / ほかは欠け。
- cy_day_pct: 同じ調教日・コース・脚色で、分かった日 ≤ レースの日の追い切り(自分を含め n 本)。n < 5 は欠け。
  (自分より 3F が速い本数)/(n − 1)。0 = 一番速い。
- cy_self: 最終追いの 3F − 同じ馬・同じコース・同じ脚色で、調教日が最終追いより前・分かった日 ≤ レースの日の 3F の中央値(2 本未満は欠け)。
- cy_stable: cy_day_pct − 同じ調教師(v3 の出走行)の [レースの日 − 365 日, レースの日) の cy_day_pct の中央値(同じ追い切りは 1 本・10 本未満は欠け)。
- cy_int: 最終追いの脚色 0/1/2。cy_n14: 分かった日 ≤ レースの日・調教日が [レースの日 − 14 日, レースの日) の本数。
  cy_gap: レースの日 − 最終追いの調教日(日)。cy_awase: position に 先着 +1・同入/併入 0・遅れ −1(無ければ欠け)。
- cy_rider_j: 最終追いの rider(空白除く)と騎手名(空白除く)の頭が 2 字以上一致なら 1・違えば 0・rider 空は欠け。
- 出走表がつながらない出走(追い切りが 1 本も無い)は全部欠け。
- 出走行へのつなぎ: umaban があれば (場・日・R・馬番)、無ければ (場・日・R・馬名)。
"""
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v7_open as vo  # noqa: E402
import v8s1_run as s1  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
SRC = Path(__import__('os').environ.get('V3_CYOKYO_CSV', 'C:/Users/kouki/OneDrive/デスクトップ/他場/data/backfill'))
TRACKS = ['大井', '船橋', '川崎', '浦和']
YEARS = range(2021, 2027)
USE = ['race_id', 'race_date', 'track', 'race_no', 'umaban', 'horse_name', 'kind', 'rider', 'work_date', 'course',
       'is_hanro', 'baba', 't_5f', 't_half', 't_3f', 't_1f', 'position', 'ashiiro', 'source']
KEY = ['track', 'race_date', 'race_no']
Q5 = KEY + ['umaban']
CY = ['cy_day_pct', 'cy_self', 'cy_stable', 'cy_int', 'cy_n14', 'cy_gap', 'cy_awase', 'cy_rider_j']
WORKS = V3 / 'cy_works.parquet'
FE, FO = V3 / 'feat_v8cy_explore.parquet', V3 / 'feat_v8cy_open.parquet'
RESJ = V3 / 'v8cy_res.json'
SHOW_HI = '2025-06-30'  # 表に出すのはここまで
CLS = {**{k: 0 for k in ('馬なり', '楽走', '末抑え', '直抑え')}, **{k: 1 for k in ('強め', '稍強め', '末強め', '直強め')},
       **{k: 2 for k in ('一杯', '末一杯', '直一杯', '稍一杯', '叩一杯')}}
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def res_save(k, v):
    R = json.loads(RESJ.read_text(encoding='utf-8')) if RESJ.exists() else {}
    R[k] = v
    RESJ.write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def norm(s):
    if not isinstance(s, str):
        return np.nan
    s = re.sub(r'\s+', '', unicodedata.normalize('NFKC', s))
    return s if s else np.nan


# ================================================================ 取り込み
def ingest():
    if WORKS.exists():
        log('取り込みは済み'); return pd.read_parquet(WORKS)
    P = []
    for t in TRACKS:
        for y in YEARS:
            f = SRC / f'cyokyo_{t}_{y}.csv'
            if not f.exists():
                log('無い', f.name); continue
            d = pd.read_csv(f, encoding='utf-8-sig', usecols=USE, dtype=str)
            P.append(d[USE])
            log('読んだ', f.name, len(d))
    W = pd.concat(P, ignore_index=True)
    W.to_parquet(WORKS, index=False)
    log('保存', WORKS, W.shape)
    return W


def prep_works(W):
    W = W.copy()
    W['race_date'] = W.race_date.astype(str).str[:10]
    W['work_date'] = W.work_date.astype(str).str[:10]
    W['race_no'] = pd.to_numeric(W.race_no, errors='coerce')
    W['umaban'] = pd.to_numeric(W.umaban, errors='coerce')
    W = W[W.race_no.notna() & W.work_date.str.match(r'^\d{4}-\d\d-\d\d$') & (W.work_date < W.race_date)].copy()
    W['race_no'] = W.race_no.astype(int)
    W['hn'] = W.horse_name.map(norm)
    W = W[W.hn.notna()]
    for c in ('t_5f', 't_half', 't_3f', 't_1f'):
        W[c] = pd.to_numeric(W[c], errors='coerce')
    W['cls'] = W.ashiiro.map(lambda s: CLS.get(norm(s), np.nan) if isinstance(s, str) else np.nan)
    wk = ['hn', 'work_date', 'course', 'ashiiro', 't_5f', 't_half', 't_3f', 't_1f']
    W['wid'] = W[wk].astype(str).agg('|'.join, axis=1)
    W = W.drop_duplicates(KEY + ['umaban', 'hn', 'wid', 'kind']).reset_index(drop=True)
    return W


# ================================================================ 出走行
def runs_rows():
    """v3 の南関の出走行(feat_t6 の行)+ 馬名・騎手・調教師。"""
    XE = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet', columns=Q5))
    XO = vo.nk(pd.read_parquet(V3 / 'feat_t6_open.parquet', columns=Q5))
    a = vo.load_archive('runs')
    a = a[a.race_date.astype(str) >= '2020-06-01']
    P = [a]
    for f in ('db_runs_confirm_2022-01_2025-08.parquet', 'db_runs_sealed_2025-09_2026-08.parquet'):
        P.append(pd.read_parquet(V3 / f))
    r = pd.concat([x.rename(columns={'runner_number': 'umaban'}) if 'umaban' not in x.columns else x for x in P],
                  ignore_index=True)
    r = r[['track', 'race_date', 'race_no', 'umaban', 'horse_name', 'jockey', 'trainer']].copy()
    r['race_date'] = r.race_date.astype(str).str[:10]
    r['race_no'] = pd.to_numeric(r.race_no, errors='coerce')
    r['umaban'] = pd.to_numeric(r.umaban, errors='coerce')
    r = r.dropna(subset=['race_no', 'umaban'])
    r['race_no'], r['umaban'] = r.race_no.astype(int), r.umaban.astype(int)
    r = r.drop_duplicates(Q5, keep='last')
    return XE, XO, r


def make_R(XE, XO, r):
    Q = pd.concat([XE[XE.race_date >= '2020-06-01'][Q5], XO[Q5]], ignore_index=True)
    R = Q.merge(r, on=Q5, how='left', validate='1:1')
    R['hn'] = R.horse_name.map(norm)
    R['jn'] = R.jockey.map(norm)
    R['tn'] = R.trainer.map(norm)
    R['date'] = pd.to_datetime(R.race_date)
    return R.reset_index(drop=True)


# ================================================================ 材料
def link(W, R):
    Ri = R[Q5 + ['hn']].assign(_i=np.arange(len(R)))
    a = W[W.umaban.notna()].copy()
    a['umaban'] = a.umaban.astype(int)
    a = a.merge(Ri[Q5 + ['_i']], on=Q5, how='left')
    b = W[W.umaban.isna()].merge(Ri.drop_duplicates(KEY + ['hn'], keep=False)[KEY + ['hn', '_i']], on=KEY + ['hn'], how='left')
    return pd.concat([a, b], ignore_index=True)


def build(W, R):
    """W = prep_works 済みの出走表の行(レースの日 ≤ 切る日のものだけ渡す)。R = 出走行。戻り: R と同じ順の cy_ 8 列。"""
    L = link(W, R)
    # 追い切り 1 本ごと(出走表のつながりに関係なく、載った出走表の日の最小 = 分かった日)
    U = W.groupby('wid').agg(hn=('hn', 'first'), work_date=('work_date', 'first'), course=('course', 'first'),
                             cls=('cls', 'first'), t_3f=('t_3f', 'first'), seen=('race_date', 'min')).reset_index()
    U['wd'] = pd.to_datetime(U.work_date)
    U['sd'] = pd.to_datetime(U.seen)
    E = L[L._i.notna()].copy()
    E['_i'] = E._i.astype(int)
    E['fin'] = (E.kind == 'final').astype(int)
    E = E.sort_values(['_i', 'fin', 'work_date'], kind='mergesort')
    F = E.groupby('_i').tail(1).set_index('_i')
    out = pd.DataFrame(index=np.arange(len(R)), columns=CY, dtype=float)
    if not len(F):
        return out
    f = pd.DataFrame({'_i': F.index.to_numpy(), 'wid': F.wid.to_numpy(), 'hn': F.hn.to_numpy(), 'course': F.course.to_numpy(),
                      'work_date': F.work_date.to_numpy(), 'cls': F.cls.to_numpy(), 't_3f': F.t_3f.to_numpy(),
                      'rider': F.rider.to_numpy(), 'position': F.position.to_numpy()})
    f['wd'] = pd.to_datetime(f.work_date)
    f['rd'] = R.date.to_numpy()[f._i.to_numpy()]
    idx = f._i.to_numpy()
    out.loc[idx, 'cy_int'] = f.cls.to_numpy(float)
    out.loc[idx, 'cy_gap'] = (f.rd - f.wd).dt.days.to_numpy(float)
    pos = f.position.astype(str)
    aw = np.where(pos.str.contains('先着'), 1.0, np.where(pos.str.contains('同入|併入'), 0.0,
                                                        np.where(pos.str.contains('遅れ'), -1.0, np.nan)))
    out.loc[idx, 'cy_awase'] = aw
    rid = f.rider.map(norm).to_numpy(object)
    jn = R.jn.to_numpy(object)[idx]

    def rj(a, b):
        if not isinstance(a, str):
            return np.nan
        if not isinstance(b, str):
            return np.nan
        return 1.0 if len(a) >= 2 and len(b) >= 2 and a[:2] == b[:2] else 0.0
    out.loc[idx, 'cy_rider_j'] = [rj(a, b) for a, b in zip(rid, jn)]
    # n14(その馬の分かっている追い切り)
    h = f[['_i', 'hn', 'rd']].merge(U[['hn', 'wid', 'wd', 'sd']], on='hn', how='inner')
    h = h[(h.sd <= h.rd) & (h.wd < h.rd) & (h.wd >= h.rd - pd.Timedelta(days=14))]
    n14 = h.groupby('_i').wid.nunique()
    out.loc[idx, 'cy_n14'] = n14.reindex(idx).fillna(0).to_numpy(float)
    # day_pct(年ごとに分けてつなぐ)
    g = f[f.cls.notna() & f.t_3f.notna()]
    Ug = U[U.cls.notna() & U.t_3f.notna()]
    dp = []
    for y, gg in g.groupby(g.work_date.str[:4]):
        m = gg[['_i', 'work_date', 'course', 'cls', 't_3f', 'rd']].merge(
            Ug[Ug.work_date.str[:4] == y][['work_date', 'course', 'cls', 't_3f', 'sd']].rename(columns={'t_3f': 'u3'}),
            on=['work_date', 'course', 'cls'], how='inner')
        m = m[m.sd <= m.rd]
        m['fast'] = (m.u3 < m.t_3f).astype(int)
        a = m.groupby('_i').agg(n=('fast', 'size'), fast=('fast', 'sum'))
        dp.append(a)
    dp = pd.concat(dp) if dp else pd.DataFrame(columns=['n', 'fast'])
    pct = (dp.fast / (dp.n - 1)).where(dp.n >= 5)
    out.loc[idx, 'cy_day_pct'] = pct.reindex(idx).to_numpy(float)
    # self
    s = g[['_i', 'hn', 'course', 'cls', 'wd', 't_3f', 'rd']].merge(
        U[U.t_3f.notna()][['hn', 'course', 'cls', 'wd', 'sd', 't_3f']].rename(columns={'wd': 'uwd', 't_3f': 'u3'}),
        on=['hn', 'course', 'cls'], how='inner')
    s = s[(s.uwd < s.wd) & (s.sd <= s.rd)]
    sa = s.groupby('_i').agg(n=('u3', 'size'), med=('u3', 'median'))
    fx = pd.Series(g.t_3f.to_numpy(), index=g._i.to_numpy())
    sv = (fx.reindex(sa.index) - sa.med).where(sa.n >= 2)
    out.loc[idx, 'cy_self'] = sv.reindex(idx).to_numpy(float)
    # stable
    st = pd.DataFrame({'_i': idx, 'tn': R.tn.to_numpy(object)[idx], 'rd': f.rd.to_numpy(), 'wid': f.wid.to_numpy(),
                       'v': out.loc[idx, 'cy_day_pct'].to_numpy(float)})
    st = st[st.tn.notna() & ~np.isnan(st.v)]
    res = pd.Series(np.nan, index=st._i.to_numpy())
    for tn, gt in st.groupby('tn', sort=False):
        hist = gt.sort_values(['rd', '_i'], kind='mergesort').drop_duplicates('wid', keep='first')
        hd = hist.rd.to_numpy('datetime64[D]').astype(np.int64)
        hv = hist.v.to_numpy(float)
        qd = gt.rd.to_numpy('datetime64[D]').astype(np.int64)
        lo = np.searchsorted(hd, qd - 365, 'left')
        hi = np.searchsorted(hd, qd, 'left')
        vals = [np.median(hv[a:b]) if b - a >= 10 else np.nan for a, b in zip(lo, hi)]
        res.loc[gt._i.to_numpy()] = gt.v.to_numpy(float) - np.array(vals, float)
    out.loc[idx, 'cy_stable'] = res.reindex(idx).to_numpy(float)
    out['_linked'] = 0.0
    out.loc[idx, '_linked'] = 1.0
    return out


# ================================================================ 漏れ検査
def leak(W, R, full):
    ds = sorted(R[R.race_date >= '2022-01-01'].race_date.unique())
    days = sorted(str(x) for x in np.random.default_rng(0).choice(ds, 20, replace=False))
    per, tot = [], [0, 0]
    for X in days:
        lo = str((pd.Timestamp(X) - pd.Timedelta(days=370)).date())
        Rc = R[(R.race_date >= lo) & (R.race_date <= X)].reset_index(drop=True)
        b = build(W[W.race_date <= X], Rc)
        mk = (Rc.race_date == X).to_numpy()
        B = b.loc[mk, CY].to_numpy(float)
        ai = R.index[R.race_date == X].to_numpy()
        A = full.loc[ai, CY].to_numpy(float)
        assert (R.loc[ai, Q5].to_numpy() == Rc.loc[mk, Q5].to_numpy()).all()
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        bad = [c for c, ok in zip(CY, eq.all(0)) if not ok]
        per.append({'date': X, 'rows': int(mk.sum()), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        log('漏れ', X, int(mk.sum()), int(eq.sum()), eq.size, bad)
    return {'days': len(days), 'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0], 'cells': tot[1],
            'per_day': per}


def main():
    s1.wait_mem()
    W0 = ingest()
    res_save('ingest', {'rows': len(W0), 'by_file': {f'{t}_{y}': int(((W0.track == t) & (W0.race_date.str[:4] == str(y))).sum())
                                                    for t in TRACKS for y in YEARS}})
    W = prep_works(W0)
    log('使える行', len(W), '追い切り', W.wid.nunique())
    XE, XO, r = runs_rows()
    R = make_R(XE, XO, r)
    log('出走行', len(R), '馬名の欠け', int(R.hn.isna().sum()), '調教師の欠け', int(R.tn.isna().sum()))
    full = build(W, R)
    # 出走表の行の側のつながり(表示は 2025-06-30 まで)
    L = link(W, R)
    L['ym'] = L.race_date.str[:4]
    w_side = {f'{t}|{y}': [int(len(g)), float(g._i.notna().mean())]
              for (t, y), g in L[L.race_date <= SHOW_HI].groupby(['track', 'ym'])}
    R2 = R.join(full)
    R2['ym'] = R2.race_date.str[:4]
    v = R2[(R2.race_date >= '2021-08-01') & (R2.race_date <= SHOW_HI)]
    r_side = {f'{t}|{y}': {'rows': int(len(g)), 'linked': float(g._linked.mean()),
                           **{c: float(g[c].notna().mean()) for c in CY}} for (t, y), g in v.groupby(['track', 'ym'])}
    res_save('link', {'works_rows': int(len(W)), 'works_unique': int(W.wid.nunique()), 'card_side': w_side, 'race_side': r_side})
    log('つながり(出走行の側)', {k: round(x['linked'], 3) for k, x in r_side.items()})
    F = pd.concat([R[Q5], full[CY]], axis=1)
    fe = XE[Q5].merge(F, on=Q5, how='left', validate='1:1')
    fo = XO[Q5].merge(F, on=Q5, how='left', validate='1:1')
    assert fe.race_date.max() < '2022-01-01' and len(fo) == 172738
    z = leak(W, R, full)
    res_save('leak', z)
    if z['match'] != z['cells']:
        raise SystemExit('⛔ 漏れ検査が 100% でない')
    fe.to_parquet(FE, index=False)
    fo.to_parquet(FO, index=False)
    log('保存', FE, fe.shape, FO, fo.shape)


if __name__ == '__main__':
    main()
