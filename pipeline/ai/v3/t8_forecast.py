# -*- coding: utf-8 -*-
"""第 8 版 = 第 7 版 e + 段 2(調教の数字の上乗せ)の毎日の予想表。オッズ・人気は見ない。調教の短評・印・談話は使わない(数字だけ)。
既存の台本は import して呼ぶだけ(書き換えない)。

  py -3.12 -X utf8 src/t8_forecast.py retrain               # 段 2 を 2022-01〜2026-08 で学び直す → models/t8_s2.json
  py -3.12 -X utf8 src/t8_forecast.py table DATE pre [DIR]  # 前日版 → out/forecast/DATE_第8版_前日版.md・.csv(DIR を渡せばそこへ)
  py -3.12 -X utf8 src/t8_forecast.py table DATE day [DIR]  # 当日版(同じ模型)
  py -3.12 -X utf8 src/t8_forecast.py dry                   # 2026-08 の 3 日: t8 の道の p3′・◎ が v3/v8s2_preds.parquet と一致するか

■ 手順(table): t7e_forecast と同じ手順で第 7 版 e の p1・p3(t7d.predict の p1・p3)→ DATE の出走の cy_ 材料を
  v8cy_build.build(= 漏れ検査の道)で作る → models/t8_s2.json で上乗せ(v8s2_run.design・形は v8s2 と同じ)
  → p1 をレースの中で和 1・p3 = max(p3, p1)・p3′ = t6_base.p3prime → 印(t3_eval.marks)。
■ 追い切りの元: 過去分 = 他場/data/backfill/cyokyo_{場}_{2021..2026}.csv。毎日の分 = 他場/data/json/cyokyo/{race_id}.json を
  他場/scraper/backfill_cyokyo.flatten_race で平らにしたもの(日付の無い参考行は入らない)。CSV にある race_id の JSON は使わない。
  DATE の材料は出走表のレースの日 ≤ DATE の行だけ(追い切りの日 < レースの日。v8cy_build の漏れ検査と同じ切り方)。
■ 出走行 R(調教師の 1 年の比べ・騎手・馬名のつなぎ): v8cy_build.runs_rows / make_R の行(〜2026-08)+ 2026-09-01 以降は
  予想の h(南関 4 場・取消を除く)。DATE の行 = 予想する行(T)に h の馬名・騎手・調教師を付けたもの。
■ 調教が無い出走は cy_ が全部欠け(欠けの 0/1 で動く・止めない)。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t7e_forecast as e7  # noqa: E402  (import 時に watch_v2 の差し替えも入る)
import t4_open as o  # noqa: E402
import t5_open as o5  # noqa: E402
import t6_base  # noqa: E402
import v7_open as vo  # noqa: E402
import v7e_open as eo  # noqa: E402
import v8cy_build as cy  # noqa: E402
import v8s1_run as s1  # noqa: E402
import v8s2_run as s2  # noqa: E402

import kb_flatten as bc  # 写し: 他場/scraper/backfill_cyokyo.py の flatten_race と COLUMNS だけ(bs4・競馬ブックの取得部は持ち込まない)  # noqa: E402

t7 = e7.t7
f6 = e7.f6
marks = t7.t3_eval.marks
V3 = e7.V3
MD = e7.MD
OUT = e7.OUT
KEY = e7.KEY
Q5 = KEY + ['umaban']
CY6 = s2.CY6
JP = MD / 't8_s2.json'
JD = Path(__import__('os').environ.get('V3_CYOKYO_JSON', 'C:/Users/kouki/OneDrive/デスクトップ/他場/data/json/cyokyo'))
TRK = {'10': '大井', '11': '川崎', '12': '船橋', '13': '浦和'}
TR_LO, TR_HI = '2022-01-01', '2026-08-31'
DRY_HI = '2025-06-30'  # dry の学び = v8s2_run の「確かめ用」と同じ 2022-01〜2025-06
log = s1.log


# ================================================================ 追い切り
_W = {}


def _s(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    return str(v)


def works():
    """CSV(過去分)+ JSON(CSV に無い race_id)→ v8cy_build.prep_works。"""
    if 'W' in _W:
        return _W['W'], _W['info']
    P = []
    for t in cy.TRACKS:
        for y in cy.YEARS:
            f = cy.SRC / f'cyokyo_{t}_{y}.csv'
            if f.exists():
                P.append(pd.read_csv(f, encoding='utf-8-sig', usecols=cy.USE, dtype=str)[cy.USE])
    C = pd.concat(P, ignore_index=True)
    have = set(C.race_id.dropna().astype(str))
    rows, nj = [], 0
    for p in sorted(JD.glob('*.json')):
        rid = p.stem
        t = TRK.get(rid[6:8])
        if t is None or rid in have:
            continue
        rows += bc.flatten_race(json.loads(p.read_text(encoding='utf-8')), t, source='kb')
        nj += 1
    J = pd.DataFrame(rows, columns=bc.COLUMNS)[cy.USE] if rows else pd.DataFrame(columns=cy.USE)
    J = J.apply(lambda s: s.map(_s)).astype(object)
    W = cy.prep_works(pd.concat([C, J], ignore_index=True))
    info = {'csv_rows': len(C), 'json_races': nj, 'json_rows': len(J),
            'json_rows_kept': int((W.source == 'kb').sum()), 'json_last': str(J.race_date.max()) if len(J) else None}
    _W.update(W=W, info=info)
    return W, info


_R = {}


def hist_R():
    if 'R' not in _R:
        XE, XO, r = cy.runs_rows()
        _R['R'] = cy.make_R(XE, XO, r)
    return _R['R']


def _mkR(x):
    x = x.copy()
    x['hn'] = x.horse_name.map(cy.norm)
    x['jn'] = x.jockey.map(cy.norm)
    x['tn'] = x.trainer.map(cy.norm)
    x['date'] = pd.to_datetime(x.race_date)
    return x


def cy_feats(date, R_day=None, h=None):
    """DATE の出走の cy_ 8 列 + _linked(Q5 付き)。R_day = DATE の出走行(Q5・馬名・騎手・調教師)。
    R_day が None なら make_R の行を使う(dry = 漏れ検査と同じ切り方)。"""
    W, _ = works()
    R = hist_R()
    lo = str((pd.Timestamp(date) - pd.Timedelta(days=370)).date())
    if R_day is None:
        Rc = R[(R.race_date >= lo) & (R.race_date <= date)].reset_index(drop=True)
    else:
        Rh = R[(R.race_date >= lo) & (R.race_date < date)]
        P = [Rh]
        if h is not None:
            g = h[(h.race_date >= '2026-09-01') & (h.race_date < date) & h.track.isin(f6.f4.NANKAN)
                  & ~h.finish_note.isin(o.CANCEL)][Q5 + ['horse_name', 'jockey', 'trainer']].copy()
            g['race_no'], g['umaban'] = g.race_no.astype(int), g.umaban.astype(int)
            g = g[g.race_date > (Rh.race_date.max() if len(Rh) else '')].drop_duplicates(Q5, keep='last')
            P.append(_mkR(g))
        P.append(_mkR(R_day))
        Rc = pd.concat(P, ignore_index=True)[list(R.columns)].reset_index(drop=True)
    b = cy.build(W[W.race_date <= date], Rc)
    mk = (Rc.race_date == date).to_numpy()
    out = pd.concat([Rc.loc[mk, Q5].reset_index(drop=True), b.loc[mk].reset_index(drop=True)], axis=1)
    return out


# ================================================================ 段 2 の当て方
def add_rk(D):
    """v8s2_run.load と同じ shinba・順位列(D は KEY・b_young・CY6 を持つ)。"""
    D = D.sort_values(Q5, kind='mergesort').reset_index(drop=True)
    g = [D[k] for k in KEY]
    D['shinba'] = (D.b_young.fillna(0) % 10 == 1).groupby(g).transform('any').astype(float)
    for c in ('cy_day_pct', 'cy_stable'):
        r = D[c].groupby(g).rank(method='average')
        m = D[c].notna().groupby(g).transform('sum')
        D[c + '_rk'] = np.where(D[c].isna(), 0.0, np.where(m > 1, (r - 1) / (m - 1).clip(lower=1), 0.5))
    return D


def fit_s2(lo, hi):
    D = s2.load()
    tr = D[(D.race_date >= lo) & (D.race_date <= hi)]
    mu, sd = tr[CY6].mean(), tr[CY6].std()
    X, cols = s2.design(tr, mu, sd)
    M = {'train': f'{lo}〜{hi}', 'rows': len(tr), 'cols': cols, 'mu': {c: float(mu[c]) for c in CY6},
         'sd': {c: float(sd[c]) for c in CY6}}
    for t, bc_ in (('Y1', 'v7epre_p1'), ('Y3', 'v7epre_p3')):
        w = s2.fit(X, tr[t].to_numpy(float), s2.lg(tr[bc_].to_numpy(float)))
        M[t] = dict(zip(['切片'] + cols, map(float, w)))
    return M


def apply_s2(x, M):
    """x = KEY・umaban・n・p1・p3(土台)・b_young・CY6。→ p1・p3・p3p・rank・mark(第 8 版)。"""
    D = add_rk(x)
    mu, sd = pd.Series(M['mu']), pd.Series(M['sd'])
    X, cols = s2.design(D, mu, sd)
    assert cols == M['cols']
    r = {}
    for t, bc_ in (('Y1', 'p1'), ('Y3', 'p3')):
        w = np.array([M[t]['切片']] + [M[t][c] for c in cols])
        r[t] = 1 / (1 + np.exp(-(s2.lg(D[bc_].to_numpy(float)) + w[0] + X @ w[1:])))
    y = D[KEY + ['umaban', 'n']].copy()
    y['p1'] = r['Y1'] / pd.Series(r['Y1'], index=y.index).groupby([y[k] for k in KEY]).transform('sum').to_numpy()
    y['p3'] = np.maximum(r['Y3'], y.p1)
    y['p3p'] = t6_base.p3prime(y, 'p3')[0]
    return marks(y, p1='p3p', p3='p1')


def retrain():
    if JP.exists():
        print('retrain は済み', JP); return
    s1.wait_mem()
    M = fit_s2(TR_LO, TR_HI)
    M['base'] = str(eo.OUT_P)
    M['feat'] = str(V3 / 'feat_v8cy_open.parquet')
    JP.write_text(json.dumps(M, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    for t in ('Y1', 'Y3'):
        k = sorted(M['cols'], key=lambda c: -abs(M[t][c]))[:3]
        log(t, '切片', round(M[t]['切片'], 3), '大きい 3 つ', {c: round(M[t][c], 3) for c in k})
    log('保存', JP, '行', M['rows'])


# ================================================================ 表
def table(date, v, out=None):
    out = Path(out) if out else OUT
    e7.guard(pd.DataFrame({'race_date': [date]}), 'DATE')
    assert (MD / f'{e7.PFX}_models.json').exists() and JP.exists(), '学び直し(t7e・t8)が先'
    M = json.loads(JP.read_text(encoding='utf-8'))
    s1.wait_mem()
    h, races = f6.f4.fill_key(*o5.load5('forward'))
    T, w4, info = e7.features(h, races, date, 'forward')
    e7.watch_nk(info)
    e7.guard(T, 'features')
    x7 = e7.predict(T)
    base = x7[KEY + ['umaban', 'n', 'p1', 'p3']].merge(vo.nk(T[Q5 + ['b_young']]), on=Q5, how='left', validate='1:1')
    hd = h.loc[(h.race_date == date) & h.track.isin(f6.f4.NANKAN), Q5 + ['horse_name', 'jockey', 'trainer']].copy()
    hd['race_no'], hd['umaban'] = hd.race_no.astype(int), hd.umaban.astype(int)
    Rd = base[Q5].merge(hd.drop_duplicates(Q5, keep='last'), on=Q5, how='left', validate='1:1')
    F = cy_feats(date, Rd, h)
    base = base.merge(F[Q5 + CY6 + ['_linked']], on=Q5, how='left', validate='1:1')
    x = apply_s2(base, M)
    x = x.merge(base[Q5 + ['_linked']], on=Q5, how='left', validate='1:1')
    x = x.merge(x7[Q5 + ['mark']].rename(columns={'mark': 'mark7e'}), on=Q5, how='left', validate='1:1')
    x = x.merge(vo.nk(T[Q5 + ['o_bw']]), on=Q5, how='left', validate='1:1') if 'o_bw' in T.columns \
        else x.assign(o_bw=np.nan)
    names = h.loc[h.race_date == date, Q5 + ['horse_name']]
    names = names.assign(race_no=names.race_no.astype(int), umaban=names.umaban.astype(int))
    x = x.merge(names, on=Q5, how='left', validate='1:1').sort_values(KEY + ['rank'], kind='mergesort')
    share = x.groupby('track', sort=False)._linked.mean()
    _, wi = works()
    jl = t7.led()['jlast']
    name = f'{date}_第8版_{o.VN[v]}'
    L = [f'# 予想表 {date}(第 8 版・{o.VN[v]}・オッズ・人気は見ない)', '',
         '第 8 版 = 第 7 版 e + 調教の数字の上乗せ(段 2・学び 2022-01〜2026-08)。調教の短評・印・談話は使わない。'
         '前日の材料だけの模型(当日版も同じ模型)。', '',
         '調教の付いた割合(場ごと): ' + '・'.join(f'{t} {100 * s:.0f}%' for t, s in share.items())
         + f'(追い切りの元: CSV + 毎日の JSON {wi["json_races"]} レース・JSON の最後 {wi["json_last"]})。調教の無い馬は欠け扱い。', '',
         f'注記: 中央の成績(kd_jra_runs)は {jl} までしか無い。能力試験は公式サイトから {info["試験の最後の日"]} まで。'
         '台帳に無い新しい馬は血統・能力試験などの列が欠け扱い。', '',
         '印: ◎ = 1 位・○ = 2 位・▲ = 3 位・△ = 4〜5 位(3 着以内の確率 → 勝つ確率 → 馬番の順)。'
         '3 着以内の確率はレース内で合計 3・勝つ確率はレース内で合計 1。']
    for k, g in x.groupby(KEY, sort=False):
        L += ['', f'## {k[0]} {k[2]}R({len(g)} 頭)']
        if v == 'day' and g.o_bw.isna().all():
            L.append('馬体重の発表前のため当日版は出さない(前日版を見る)')
            continue
        L += ['', '| 印 | 馬番 | 馬名 | 3 着以内の確率 | 勝つ確率 |', '|---|---|---|---|---|']
        L += [f'| {r.mark} | {r.umaban} | {r.horse_name} | {r.p3p:.3f} | {r.p1:.3f} |' for r in g.itertuples()]
    out.mkdir(parents=True, exist_ok=True)
    x[KEY + ['umaban', 'horse_name', 'n', 'rank', 'mark', 'p3p', 'p1', 'p3', '_linked', 'mark7e']].to_csv(
        out / f'{name}.csv', index=False, encoding='utf-8-sig')
    (out / f'{name}.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    top = x[x['rank'] == 1]
    t7top = x[x.mark7e == '◎']
    same = int(top[Q5].merge(t7top[Q5], on=Q5).shape[0])
    print(f"{date} 第 8 版 {o.VN[v]}: {x[KEY].drop_duplicates().shape[0]} R・{len(x)} 頭 → {out / (name + '.md')}"
          f" 調教の付いた割合 {({t: round(s, 3) for t, s in share.items()})} 全体 {x._linked.mean():.3f}"
          f" ◎ が第 7 版 e と同じ {same}/{len(top)} 追い切り {wi}"
          f" 見張り 4 列 {({k: round(val, 3) for k, val in w4.items()})}", flush=True)


# ================================================================ 通し試験
def dry():
    s1.wait_mem()
    M = fit_s2('2022-01-01', DRY_HI)
    ref = pd.read_parquet(s2.OUT_P)
    ref['race_no'], ref['umaban'] = ref.race_no.astype(int), ref.umaban.astype(int)
    ref = ref[(ref.fit == '確かめ用') & (ref.race_date >= '2026-08-01') & (ref.race_date <= '2026-08-31')]
    ds = sorted(ref.race_date.unique())
    days = [ds[0], ds[len(ds) // 2], ds[-1]]
    B = pd.read_parquet(eo.OUT_P)
    B['race_no'], B['umaban'] = B.race_no.astype(int), B.umaban.astype(int)
    YT = vo.nk(pd.read_parquet(vo.FEAT_OUT, columns=Q5 + ['b_young']))
    FO = vo.nk(pd.read_parquet(cy.FO))
    _, wi = works()
    log('追い切り', wi)
    tot = [0, 0, 0.0, 0, 0]
    for d in days:
        b = B[B.race_date == d][Q5 + ['n', 'v7epre_p1', 'v7epre_p3']].rename(columns={'v7epre_p1': 'p1', 'v7epre_p3': 'p3'})
        b = b.merge(YT, on=Q5, how='left', validate='1:1')
        F = cy_feats(d)
        fo = FO[FO.race_date == d]
        cmp_ = fo[Q5 + cy.CY].merge(F[Q5 + cy.CY], on=Q5, how='left', suffixes=('_a', '_b'))
        A, Bf = cmp_[[c + '_a' for c in cy.CY]].to_numpy(float), cmp_[[c + '_b' for c in cy.CY]].to_numpy(float)
        eqf = (np.isnan(A) & np.isnan(Bf)) | (np.abs(A - Bf) <= 1e-9)
        x = apply_s2(b.merge(F[Q5 + CY6], on=Q5, how='left', validate='1:1'), M)
        r = ref[ref.race_date == d][KEY + ['umaban', 'n', 'v8s2_p1', 'v8s2_p3', 'v8s2_p3p']]
        rm = marks(r.rename(columns={'v8s2_p1': 'p1', 'v8s2_p3': 'p3', 'v8s2_p3p': 'p3p'}), p1='p3p', p3='p1')
        z = x.merge(rm[Q5 + ['p3p', 'rank']], on=Q5, suffixes=('', '_r'), validate='1:1')
        dmax = float(np.abs(z.p3p - z.p3p_r).max())
        t1, t2 = z[z['rank'] == 1], z[z.rank_r == 1]
        same = int(t1[Q5].merge(t2[Q5], on=Q5).shape[0])
        nr = int(t2.shape[0])
        log(d, '馬', len(z), '/', len(r), 'cy_ 材料の一致', int(eqf.sum()), '/', eqf.size, '◎ 一致', same, '/', nr,
            'p3′ の差の最大', f'{dmax:.2e}', '調教の付いた割合', round(float(F._linked.mean()), 3))
        tot[0] += same; tot[1] += nr; tot[2] = max(tot[2], dmax); tot[3] += int(eqf.sum()); tot[4] += eqf.size
    log('dry 合計', days, '◎ 一致', tot[0], '/', tot[1], 'p3′ の差の最大', f'{tot[2]:.2e}', 'cy_ 材料', tot[3], '/', tot[4])


if __name__ == '__main__':
    a = sys.argv[1:]
    {'retrain': retrain, 'table': lambda: table(a[1], a[2], a[3] if len(a) > 3 else None), 'dry': dry}[a[0]]()
