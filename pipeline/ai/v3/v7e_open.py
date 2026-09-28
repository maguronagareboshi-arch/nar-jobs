# -*- coding: utf-8 -*-
"""第 7 版 e(第 7 版 d の 177 列 + 能力試験 nk7_)を、公式サイトの能力試験で 2020-03 以降の穴を埋めて答え合わせまで通す。
ユーザー承認 2026-09-27。既存の台本は import して呼ぶだけ(書き換えない)。オッズ・人気は材料に使わない。

  py -3.12 -X utf8 src/v7e_open.py all    # verify → feat → judge → open → eval → md(できている段は飛ばす)

■ 決め(結果を見る前に決めた。結果を見て変えない)
  元の表 = src/nk_fetch.py parse の v3/nk_shiken.parquet(2019-07-01〜2026-08-31・4 場)。
  確かめ: 2019-07-01〜KDSCOPE NS の最後の日の重なりで、サイトの行と NS を (日付・場・馬名 NFKC 空白消し) でつなぐ
     (NS の馬名 = kd_horse の血統登録番号 → 馬名)。タイム一致 = |差| < 0.05 秒。並び順一致 = サイトの R 内の並び順 = NS の着順。
     件数の比 = サイトの行 ÷ NS の行。タイム一致 < 95% なら止まる。
  馬のつなぎ: 馬名 + 父 + 母(各 NFKC・空白消し)で kd_horse の血統登録番号へ。そのかぎが 1 つの番号にだけつながるときだけ。
  nk7_: 定義は v7e_run.py の「決め」のまま。元 = KDSCOPE(NS の最後の日まで)+ サイト(それより後の日だけ)。
     サイトの 着順 = R 内の並び順・組 = (日付・場・R)・距離 = サイトの距離・タイム = サイトのタイム(「-」等は欠け)。
     つながらないサイトの行も組の頭数と同じ日・同じ距離の平均に入れる(負の仮の番号・レースの馬とはつながらない)。
     合否・試験内容は足さない。ns_end = 合わせた表の最後の日。漏れ検査・judge は v7e と同じ(judge の cache は別の場所)。
  答え合わせ: v7d.open_() と同じ区切り(t4_open.SEGS)・同じ学び方で 177 + nk7_ の予想を作り、v7d_eval と同じ数え方で
     ◎ 3 着以内率と d との差 ±(日ごとにまとめた 2 × 標準誤差)。場面: 新馬戦 = b_young の 1 の位が 1・
     走歴の無い馬のいるレース = そのレースに l_debut = 1 の馬が 1 頭以上。
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t6_base  # noqa: E402
import v7_open as vo  # noqa: E402
import v7_open_eval as E  # noqa: E402
import v7_select as vs  # noqa: E402
import v7c_run as vc  # noqa: E402
import v7d_run as v7d  # noqa: E402
import v7e_run as e  # noqa: E402
import nk_fetch as nf  # noqa: E402

V3 = e.V3
REPO = e.REPO
KEY, Q5 = e.KEY, e.Q5
RESJ = V3 / 'v7e2_res.json'
MD = REPO / 'out' / 'v7e_open.md'
CACHE = V3 / 'v7e2_cache'
NCOL = e.GROUPS['n']
OUT_P = V3 / 'v7e_open_preds.parquet'
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def res_load():
    return json.loads(RESJ.read_text(encoding='utf-8')) if RESJ.exists() else {}


def res_save(k, v):
    R = res_load()
    R[k] = v
    RESJ.write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def fpath(part):
    return V3 / f'feat_v7e2_n_{part}.parquet'


def site():
    s = pd.read_parquet(nf.OUT)
    s = s[s.date >= '2019-07-01'].copy()  # 範囲の外の試しの 1 ページは使わない
    s['jk'] = s.jyo + 24  # 18 浦和 → 42 …(KDSCOPE の場の番号)
    for c in ('name', 'sire', 'dam'):
        s['n_' + c] = s[c].map(vc.norm)
    return s


def horse_key():
    k = pd.read_parquet(V3 / 'kd_horse.parquet')
    k = k[k.ketto.notna()].copy()
    k['ketto'] = k.ketto.astype('int64')
    k['hk'] = k['name'].map(vc.norm) + '|' + k['sire'].map(vc.norm) + '|' + k['dam'].map(vc.norm)
    u = k[k.hk.notna()].drop_duplicates(['hk', 'ketto'])
    one = u.hk.map(u.hk.value_counts()) == 1
    kname = k.drop_duplicates('ketto').set_index('ketto')['name'].map(vc.norm)
    return dict(zip(u.hk[one], u.ketto[one])), kname


# ================================================================ 2・3 確かめ・つなぎ
def verify():
    R = res_load()
    if 'verify' in R:
        log('verify は済み'); return R['verify']
    s = site()
    ns = e.read_ns()
    ks_end = ns.date.max()
    hmap, kname = horse_key()
    ov_s = s[(s.date >= '2019-07-01') & (s.date <= ks_end)].copy()
    ov_k = ns[ns.date >= '2019-07-01'].copy()
    ov_k['n_name'] = ov_k.ketto.map(kname)
    m = ov_s.merge(ov_k, left_on=['date', 'jk', 'n_name'], right_on=['date', 'jyo', 'n_name'], how='inner',
                   suffixes=('', '_k'))
    tt = m[m.time_sec.notna() & (m.time_sec_k > 0)]
    fo = m[m.finish > 0]
    v = {'ks_end': str(ks_end.date()), 'site_rows': len(ov_s), 'ks_rows': len(ov_k), 'ratio': len(ov_s) / len(ov_k),
         'matched': len(m), 'matched_of_ks': len(m) / len(ov_k), 'time_n': len(tt),
         'time_match': float((np.abs(tt.time_sec - tt.time_sec_k) < 0.05).mean()),
         'ord_n': len(fo), 'ord_match': float((fo.ord == fo.finish).mean()),
         'dist_match': float((m.dist == m.dist_k).mean())}
    s['hk'] = s.n_name + '|' + s.n_sire + '|' + s.n_dam
    s['ketto'] = s.hk.map(hmap)
    s['year'] = s.date.dt.year
    v['link'] = {int(y): {'rows': len(g), 'link': float(g.ketto.notna().mean())} for y, g in s.groupby('year')}
    v['fetch'] = {'html': len(list(nf.HD.glob('*.html'))),
                  'n404': sum(len(f.read_text(encoding='utf-8').split()) for f in nf.HD.glob('_404*.txt')),
                  'rows': len(s), 'days': int(s[['date', 'jyo']].drop_duplicates().shape[0]),
                  'first': str(s.date.min().date()), 'last': str(s.date.max().date()),
                  'per_year': {int(y): [int(g[['date', 'jyo']].drop_duplicates().shape[0]), len(g)] for y, g in s.groupby('year')}}
    res_save('verify', v)
    log('verify', {k: v[k] for k in v if k not in ('link', 'fetch')}, v['link'])
    if v['time_match'] < 0.95:
        write_md()
        raise SystemExit('⛔ タイム一致 < 95%: 止まる')
    return v


def ns_all():
    """KDSCOPE(NS の最後の日まで)+ サイト(それより後)。列は read_ns と同じ。"""
    ns = e.read_ns()
    ks_end = ns.date.max()
    hmap, _ = horse_key()
    s = site()
    s = s[s.date > ks_end].copy()
    s['ketto'] = (s.n_name + '|' + s.n_sire + '|' + s.n_dam).map(hmap)
    nl = s.ketto.isna().to_numpy()
    s.loc[nl, 'ketto'] = -np.arange(1, nl.sum() + 1)
    x = pd.DataFrame({'date': s.date, 'jyo': s.jk.astype(float), 'heat': s.R.astype(float), 'ketto': s.ketto.astype('int64'),
                      'finish': s.ord.astype(float), 'time_sec': s.time_sec.astype(float), 'dist': s.dist.astype(float)})
    out = pd.concat([ns, x], ignore_index=True)
    return out, {'ks_rows': len(ns), 'site_rows': len(x), 'site_unlinked': int(nl.sum())}


# ================================================================ 4 nk7_
def feat():
    R = res_load()
    if 'leak' in R and fpath('explore').exists() and fpath('open').exists():
        log('feat は済み'); return
    h, races = vc.sources()
    h = e.slim(h)
    races = races[['track', 'race_date']].drop_duplicates()
    XE = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XO = vo.nk(pd.read_parquet(V3 / 'feat_t6_open.parquet'))
    Q = pd.concat([XE[Q5], XO[Q5]], ignore_index=True)
    meta = pd.concat([XE[['year']], XO[['year']]], ignore_index=True)
    nk = races[races.track.isin(d3.NANKAN)]
    ne, no = nk[nk.race_date < '2022-01-01'], nk[nk.race_date >= '2022-01-01']
    n = len(XE)
    _, kmap, _ = v7d.ledger()
    nmap = v7d.jra_names(pd.read_parquet(V3 / 'kd_jra_runs.parquet'))
    ns, src = ns_all()
    ns_end = ns.date.max()
    log('能力試験', src, ns.date.min().date(), ns_end.date())
    extra = (kmap, nmap, ns_end)
    F, aux = e.build_n(h, Q, e.ns_table(ns), *extra)
    aux = pd.concat([aux, meta], axis=1)
    rt = aux.groupby('year').agg(rows=('n_link', 'size'), link=('n_link', 'mean'), has=('n_has', 'mean'), inr=('n_in', 'mean'))
    info = {'src': src, 'ns_first': str(ns.date.min().date()), 'ns_last': str(ns_end.date()),
            'rate': {int(y): {k: float(v) for k, v in r.items()} for y, r in rt.iterrows()}}
    log('つながり\n', rt.round(4))
    F = pd.concat([Q[Q5], F.reset_index(drop=True)], axis=1)
    FE, FO = F.iloc[:n].reset_index(drop=True), F.iloc[n:].reset_index(drop=True)
    info['miss'] = {c: [float(FE[c].isna().mean()), float(FO[c].isna().mean())] for c in NCOL}
    res_save('feat', info)
    z = {'explore': e.leak('n', e.build_n, h, XE[Q5], FE, ne, 'explore', ns, extra),
         'open': e.leak('n', e.build_n, h, XO[Q5], FO, no, 'open', ns, extra)}
    lk = {k: {kk: v[kk] for kk in ('days', 'match_days', 'match', 'cells')} for k, v in z.items()}
    if any(v['match'] != v['cells'] for v in z.values()):
        res_save('leakfail', z)
        write_md()
        raise SystemExit('⛔ 漏れ検査が 100% でない')
    FE.to_parquet(fpath('explore'), index=False); FO.to_parquet(fpath('open'), index=False)
    res_save('leak', lk)
    log('保存 feat', lk)


def judge():
    R = res_load()
    if 'judge' in R:
        log('judge は済み', R['judge']); return
    d = v7d.load_d()
    d = d.merge(vo.nk(pd.read_parquet(fpath('explore'))), on=Q5, how='left', validate='1:1')
    base = vc.base_cols() + v7d.C7 + v7d.J7
    assert len(base) == 177 and len(set(base)) == 177
    vs.CACHE = v7d.CACHE_D
    ll0 = vs.race_ll(d, vs.fit(d, base))
    vs.CACHE = CACHE
    ll1 = vs.race_ll(d, vs.fit(d, base + NCOL))
    j = vs.judge(ll0, ll1)
    j['sum_base'], j['sum_new'] = round(float(ll0.sum()), 1), round(float(ll1.sum()), 1)
    res_save('judge', j)
    log('judge', j)


# ================================================================ 5 答え合わせ(v7d.open_ と同じ手順)
def open_():
    if OUT_P.exists():
        log('open は済み'); return
    cols = vc.base_cols() + v7d.C7 + v7d.J7 + NCOL
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT))
    assert len(T) == 172738
    for f in (v7d.COP, v7d.JOP, fpath('open')):
        T = T.merge(vo.nk(pd.read_parquet(f)), on=Q5, how='left', validate='1:1')
    X6 = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XB = vo.nk(pd.read_parquet(V3 / 'feat_v7b_explore.parquet'))
    X = X6.merge(XB[Q5 + vo.B7], on=Q5, how='left', validate='1:1')
    for f in (v7d.CEX, v7d.JEX, fpath('explore')):
        X = X.merge(vo.nk(pd.read_parquet(f)), on=Q5, how='left', validate='1:1')
    assert len(X) == len(X6) and X.race_date.max() < '2022-01-01' and set(T.columns) <= set(X.columns)
    ALL = o.sort4(pd.concat([X[list(T.columns)], T], ignore_index=True))
    assert not ALL.duplicated(Q5).any()
    P = []
    for name, lo, hi in o.SEGS:
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
        x['v7epre_p1'], x['v7epre_p3'] = p1, np.maximum(r['Y3'], p1)
        x['v7epre_p3p'] = t6_base.p3prime(x, 'v7epre_p3')[0]
        P.append(x)
        log('区切り', name, '学び', len(tr), '予想', len(x))
    out = pd.concat(P, ignore_index=True).sort_values(Q5, kind='mergesort').reset_index(drop=True)
    assert len(out) == 172738 and out.v7epre_p3p.notna().all()
    out.to_parquet(OUT_P, index=False)
    log('保存', OUT_P, out.shape)


def evaluate():
    R = res_load()
    if 'eval' in R:
        log('eval は済み'); return
    p = E.load()
    for f, c in ((V3 / 'v7d_open_preds.parquet', 'v7dpre'), (OUT_P, 'v7epre')):
        x = pd.read_parquet(f)
        x['race_no'], x['umaban'] = x.race_no.astype(int), x.umaban.astype(int)
        p = p.merge(x[Q5 + [c + '_p1', c + '_p3p']], on=Q5, how='left', validate='1:1')
    assert p.v7dpre_p1.notna().all() and p.v7epre_p1.notna().all()
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT, columns=Q5 + ['b_young', 'l_debut']))
    T['race_no'], T['umaban'] = T.race_no.astype(int), T.umaban.astype(int)
    sc = T.groupby(KEY).agg(shinba=('b_young', lambda v: float((v.fillna(0) % 10 == 1).any())),
                            debut=('l_debut', lambda v: float((v == 1).any())))
    tops = {'e': E.top(p, 'v7epre_p3p', 'v7epre_p1'), 'd': E.top(p, 'v7dpre_p3p', 'v7dpre_p1')}
    Rr = pd.DataFrame({k: v.set_index(KEY).Y3 for k, v in tops.items()})
    Rr['year'] = tops['e'].set_index(KEY).year
    Rr = Rr.join(sc)
    assert Rr.shinba.notna().all()
    Rr['date'] = Rr.index.get_level_values('race_date')

    def row(lab, g):
        dd = (g.e - g.d).groupby(g.date).agg(['sum', 'size'])
        mm = dd['sum'].sum() / dd['size'].sum()
        se = np.sqrt(((dd['sum'] - mm * dd['size']) ** 2).sum()) / dd['size'].sum()
        return dict(期間=lab, レース=len(g), 第7版e=round(100 * g.e.mean(), 1), 第7版d=round(100 * g.d.mean(), 1),
                    差=f'{100 * mm:+.2f} ±{200 * se:.2f}')
    rows = [row('全体', Rr)] + [row(str(y), g) for y, g in Rr.groupby('year')]
    sub = [row('新馬戦', Rr[Rr.shinba == 1]), row('走歴の無い馬のいるレース', Rr[Rr.debut == 1]),
           row('走歴の無い馬のいないレース', Rr[Rr.debut == 0])]
    res_save('eval', {'rows': rows, 'sub': sub})
    log('eval', rows[0], sub)


# ================================================================ md
def pct(v):
    return f'{100 * v:.1f}%'


def tab(rows):
    ks = list(rows[0])
    return '\n'.join(['| ' + ' | '.join(ks) + ' |', '|' + '---|' * len(ks)] +
                     ['| ' + ' | '.join(str(r[k]) for k in ks) + ' |' for r in rows])


def write_md():
    R = res_load()
    L = ['# 第 7 版 e の答え合わせ(177 列 + 能力試験 nk7_・試験の穴を公式サイトで埋めた)', '',
         '- 台本 src/nk_fetch.py(集める・読む)・src/v7e_open.py(定義は docstring の「決め」。結果を見て変えていない)。',
         '- ユーザー承認 2026-09-27。オッズ・人気は材料に使わない。Supabase は使っていない(2026 分もサイトから)。', '']
    fb = nf.FALLBACK.read_text(encoding='utf-8').strip() if nf.FALLBACK.exists() else ''
    L += ['- 集め方: 場ごとに 4 本並列・各本 0.5 秒おき(ユーザー承認 2026-09-27)。守りで 1 本・2 秒おきに戻したか: '
          + (fb if fb else '戻していない'), '']
    skp = V3 / 'nk_skip.json'
    if skp.exists():
        S = json.loads(skp.read_text(encoding='utf-8'))
        L += [f'## 飛ばした日(ユーザー希望 2026-09-27・src/nk_skip.py・NS {S["ns_from"]}〜{S["ns_to"]} の {S["ns_pages"]} 日×場・'
              f'{S["ns_rows"]} 行で数えた)', '',
              '| その場のレース | 曜日 | 試験の日×場 | 割合 | 行の割合 |', '|---|---|---|---|---|']
        L += [f'| {"あり" if r["race"] else "なし"} | {r["wd"]} | {r["days"]} | {pct(r["day_share"])} | {pct(r["row_share"])} |'
              for r in S['table']]
        L += ['', f'- 0.5% 未満で飛ばした条件: {"・".join(S["skip_cond"])}。全 {S["all_keys"]} 日×場のうち {S["skip_n"]} を飛ばした。', '']
    v = R.get('verify')
    if v:
        f = v['fetch']
        L += ['## 集めた分(nankankeiba.com shiken_list・2019-07-01〜2026-08-31 × 4 場)', '',
              f'- 結果のあったページ {f["html"]}・無かった(404){f["n404"]}・行 {f["rows"]}・日×場 {f["days"]}({f["first"]}〜{f["last"]})', '',
              '| 年 | 日×場 | 行 |', '|---|---|---|'] + [f'| {y} | {a} | {b} |' for y, (a, b) in f['per_year'].items()] + ['']
        L += [f'## 確かめ(2019-07-01〜{v["ks_end"]} の重なり・(日付・場・馬名) でつなぐ)', '',
              f'- サイト {v["site_rows"]} 行・KDSCOPE NS {v["ks_rows"]} 行(比 {v["ratio"]:.3f})・つながった {v["matched"]}'
              f'(NS の {pct(v["matched_of_ks"])})',
              f'- タイム一致(|差| < 0.05 秒){pct(v["time_match"])}({v["time_n"]} 組)・並び順 = NS 着順 {pct(v["ord_match"])}'
              f'({v["ord_n"]} 組)・距離一致 {pct(v["dist_match"])}', '',
              '## 馬のつなぎ(馬名 + 父 + 母 → kd_horse の血統登録番号・一意のときだけ・サイトの行)', '',
              '| 年 | 行 | つながった |', '|---|---|---|'] + \
             [f'| {y} | {a["rows"]} | {pct(a["link"])} |' for y, a in v['link'].items()] + ['']
    fn = R.get('feat')
    if fn:
        L += ['## nk7_ のつながり(南関の出走・年ごと)', '',
              f'- 元: KDSCOPE {fn["src"]["ks_rows"]} 行 + サイト {fn["src"]["site_rows"]} 行(うちつながらない {fn["src"]["site_unlinked"]}・'
              f'組の頭数と平均にだけ入る)・{fn["ns_first"]}〜{fn["ns_last"]}', '',
              '| 年 | 行 | 血統登録番号とつながった | 前に試験あり | 試験の期間内 |', '|---|---|---|---|---|']
        L += [f'| {y} | {int(a["rows"])} | {pct(a["link"])} | {pct(a["has"])} | {pct(a["inr"])} |' for y, a in fn['rate'].items()]
        L += ['', '| 列 | 欠け 作る | 欠け 答え合わせ |', '|---|---|---|'] + \
             [f'| {c} | {pct(a[0])} | {pct(a[1])} |' for c, a in fn['miss'].items()] + ['']
    if 'leak' in R:
        L += ['- 漏れ検査(v7e と同じ 20 日): ' + '・'.join(f'{k} {a["match_days"]} / {a["days"]} 日一致・セル {a["match"]} / {a["cells"]}'
                                              for k, a in R['leak'].items()), '']
    if 'judge' in R:
        j = R['judge']
        L += ['## judge(土台 177 列に nk7_ を足す・2016〜19)', '',
              f'- 伸び {j["gain"]} ±{j["se"]}(標準誤差)・年ごと {j["years"]}・通った {j["ok"]}・和 {j["sum_base"]} → {j["sum_new"]}'
              '(前回 v7e: +102.96 ±24.55)', '']
    if 'eval' in R:
        L += ['## ◎ の 3 着以内率 %(2022-01〜2026-08・前日版・v7d_eval と同じ数え方・差 = e − d ± 2 × 標準誤差)', '',
              tab(R['eval']['rows']), '', '## 場面別', '', tab(R['eval']['sub']), '']
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')
    log('md', MD)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    steps = {'verify': [verify], 'feat': [feat], 'judge': [judge], 'open': [open_], 'eval': [evaluate], 'md': [write_md],
             'all': [verify, feat, judge, open_, evaluate, write_md]}[cmd]
    for s in steps:
        s()
