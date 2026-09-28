# -*- coding: utf-8 -*-
"""第 7 版 e の毎日の予想表(ユーザー承認 2026-09-28: 毎日の表を第 7 版 e に切り替える)。オッズ・人気は見ない。
既存の台本は import して呼ぶだけ(書き換えない)。形は t7d_forecast.py と同じ。

  py -3.12 -X utf8 src/t7e_forecast.py fetch DATE        # = t6_forecast.fetch(DB の写し)
  py -3.12 -X utf8 src/t7e_forecast.py nk DATE           # 能力試験の追い取り(2026-08-22〜DATE の前日・4 場)→ nk_shiken.parquet に足す
  py -3.12 -X utf8 src/t7e_forecast.py retrain           # 2015〜2026-08 で第 7 版 e を学び直す(2 回の一致)→ models/t7e_*.txt
  py -3.12 -X utf8 src/t7e_forecast.py table DATE pre    # 前日版 → out/forecast/DATE_第7版e_前日版.md・.csv(先に nk DATE を流す)
  py -3.12 -X utf8 src/t7e_forecast.py table DATE day    # 当日版(同じ模型)
  py -3.12 -X utf8 src/t7e_forecast.py dry [DAY]         # 探索の写しだけで 2021-12-29〜31 の 183 列を作り v7e の材料と一致するか(1 日ずつ)

■ 183 列 = 第 7 版 d の 177 列(t7d_forecast.features と同じ)+ nk7_ 6 列(v7e_run.build_n・v7e_open の「決め」のまま)。
  - nk7_ の元 = v7e_open.ns_all()(KDSCOPE NS の最後の日まで + 公式サイト nk_shiken.parquet のそれより後)を DATE 以前に切り、
    DATE の試験の着順・タイムを空にしたもの(v7e_run.leak の n と同じ切り方)→ v7e_run.ns_table。
    走り h = t7d の features の中で作る h7(src_fill = sources_from + 2026-09 以降の鍵埋め)を v7e_run.slim したもの。
    馬のつなぎ = t7d.led() の kmap・nmap(v7d.ledger・jra_names = v7e_open と同じ)。
    ns_end = DATE(試験は DATE の前日まで追い取ってある前提。build_n は当日の試験を使わない。漏れ検査でも ns_end は切った日以上)。
  - 能力試験の追い取り = nk_fetch.fetch を D0 = 2026-08-22・D1 = DATE の前日にして 1 本・0.5 秒おき(nk_skip.json の日は飛ばす)。
    足す行 = nk_shiken.parquet に無い (日付・場) の HTML を nk_fetch.parse_one で読み、nk_fetch.parse と同じ列にしたもの。
  - 模型 = v7e_open.open_ と同じ設定(v7c_run.train・v7_open.CFG・列 = 183)で、探索(feat_t6_explore + feat_v7b_explore
    + c7d/j7 explore + feat_v7e2_n_explore)と答え合わせ(feat_v7_open + c7d/j7 open + feat_v7e2_n_open)の全行(2015〜2026-08)。
    p1・p3・p3′・印は t7d と同じ(t7d_forecast.predict)。
  - 見張り = t7d と同じ(第 6 版の 4 列・ラップ・t4 の見張り)+ nk7_ の「走歴の無い馬(l_debut = 1)のうち試験の記録がある
    (nk7_n > 0)割合」。線 = 作る期間 2016〜19 の 1 日ごとの割合の最小 = W_NK(feat_t6_explore の l_debut と
    feat_v7e2_n_explore の nk7_n で数えた・走歴の無い馬のいる 925 日・5940 頭・平均 0.374・最小 0.0)。
    最小が 0.0 なので、この線では止まらない(値は毎回表示する)。走歴の無い馬のいない日は見ない。
  - t4 の見張りの差し替え(ユーザー承認 2026-09-27「B はい」)= watch_v2。t4_forecast.watch は変えず、import の直後に
    f6.f4.watch = watch_v2 と差し替える(t7d.features は f6.f4.watch を呼ぶ時に引くので、こちらが使われる)。
    horse_key の埋まり ≥ 0.99 はそのまま。走歴の無い馬(l_debut = 1)の割合は新馬戦のレースの馬を除いて数える
    (新馬戦 = そのレースに b_young の 1 の位が 1 の馬がいる = v8s1_run.evaluate と同じ)。線 = W_DEB(月で分けない)。
    旧の線(同じ月の最大 + 0.05)は月の平均を 1 日に当てていて、新馬戦の多い日(2026-09-01・11・18・24)に止まっていた。
"""
import sys
from datetime import date as _date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gc  # noqa: E402
import json  # noqa: E402
import nk_fetch as nf  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t5_open as o5  # noqa: E402
import t6_forecast as f6  # noqa: E402
import t7d_forecast as t7  # noqa: E402
import v7_open as vo  # noqa: E402
import v7c_run as vc  # noqa: E402
import v7d_run as v7d  # noqa: E402
import v7e_open as eo  # noqa: E402
import v7e_run as e  # noqa: E402

# 作る期間 2016〜2021 の「1 日ごとの走歴の無い馬の割合(新馬戦のレースを除く)」の最大。
# 数え方: feat_t4_explore(t4_day3.FEAT)の year・race_date・track・race_no・b_young・l_debut で、
# year 2016〜2021 の行 → (track, race_date, race_no) ごとに (b_young.fillna(0) % 10 == 1).any() のレースを除く
# → race_date ごとに (l_debut == 1).mean() → その最大。
W_DEB = 0.2073170731707317  # 1599 日・最大 = 2019-10-20・平均 0.0251。2022-01〜2026-08(feat_t6_open・1255 日)で越える日 0・最大 0.1319


def _deb_share(T):
    """新馬戦のレースを除いた走歴の無い馬の割合(除いた後に行が無ければ 0.0)。"""
    if not len(T):
        return 0.0
    sh = (T.b_young.fillna(0) % 10 == 1).groupby([T[k] for k in d3.KEY]).transform('any')
    r = T.l_debut[~sh.to_numpy()]
    return float((r == 1).mean()) if len(r) else 0.0


def watch_v2(h, T, date):
    """t4_forecast.watch の差し替え(承認 2026-09-27)。引数と戻り値は同じ (fill, share, lim)。"""
    e_ = h[(h.race_date == date) & h.track.isin(f6.f4.NANKAN) & ~h.finish_note.isin(o.CANCEL)]
    fill = float(e_.horse_key.notna().mean()) if len(e_) else 1.0
    share = _deb_share(T)
    lim = W_DEB
    if fill < 0.99 or share > lim:
        raise SystemExit(f'⛔ 見張りで止まる(horse_key の埋まり {fill:.3f}・走歴の無い馬 {share:.3f} / 線 {lim:.3f})。表は出さない')
    return fill, share, lim


f6.f4.watch = watch_v2
assert t7.f6.f4 is f6.f4 and t7.f6.f4.watch is watch_v2

V3 = t7.V3
MD = t7.MD
OUT = t7.OUT
KEY = t7.KEY
Q5 = KEY + ['umaban']
NCOL = e.GROUPS['n']
COLS = t7.COLS + NCOL
assert len(COLS) == 183 and len(set(COLS)) == 183
PFX = 't7e'
W_NK = 0.0  # 作る期間 2016〜19 の 1 日ごとの最小(925 日・5940 頭・平均 0.374・最小 0.0 = 2016-01-06 ほか・下から 5% も 0.0)
guard = t7.guard

# ================================================================ 能力試験
_H7 = {}
_src7 = t7.src_fill


def _src_cap(runs, facts, races):
    """t7d.features の中の src_fill をそのまま呼び、最後に作った h(= h7)を覚える。"""
    h = _src7(runs, facts, races)
    _H7['h'] = h
    return h


def nk_fetch(date):
    """nk_fetch.fetch を 2026-08-22〜DATE の前日・1 本・0.5 秒おきで。取れた HTML のうち表に無い (日付・場) を足す。"""
    d = _date.fromisoformat(date)
    # 今日以降はまだ載らない日を 404 として記録してしまい再開で飛ばされるので、取るのは昨日まで
    nf.D0, nf.D1 = _date(2026, 8, 22), min(d, _date.today()) - timedelta(days=1)
    nf.fetch(None, 0.5)
    old = pd.read_parquet(nf.OUT)
    have = set(old.date.dt.strftime('%Y%m%d') + old.jyo.astype(str))
    new = [p for p in sorted(nf.HD.glob('*.html')) if p.stem not in have and p.stem[:8] >= '20260822']
    rows = []
    for p in new:
        rows += nf.parse_one(p)
    if not rows:
        print('足す行なし(新しい HTML', len(new), ')', flush=True); return
    x = pd.DataFrame(rows)
    x['date'] = pd.to_datetime(x.key.str[:8], format='%Y%m%d')
    x['jyo'] = x.key.str[8:].astype(int)
    x['R'] = pd.to_numeric(x.R, errors='coerce')
    x['dist'] = pd.to_numeric(x.dist, errors='coerce')
    x['time_sec'] = x.time.map(nf.tsec)
    x = x.drop(columns='key')[list(old.columns)]
    pd.concat([old, x], ignore_index=True).to_parquet(nf.OUT, index=False)
    print(f'能力試験の追い取り: HTML {len(new)} 日×場・{len(x)} 行を足した({x.date.min().date()}〜{x.date.max().date()})',
          flush=True)


_NS = {}


def nk_table(date):
    if 'ns' not in _NS:
        _NS['ns'] = eo.ns_all()[0]
    ns = _NS['ns']
    nt = ns[ns.date <= pd.Timestamp(date)].copy()
    nt.loc[nt.date == pd.Timestamp(date), ['finish', 'time_sec']] = np.nan
    return e.ns_table(nt), str(ns.date.max().date())


def features(h, races, date, part, lap_lo=t7.FWD):
    t7.src_fill = _src_cap
    try:
        T, w4, info = t7.features(h, races, date, part, lap_lo)
    finally:
        t7.src_fill = _src7
    h7 = e.slim(_H7.pop('h'))
    Lg = t7.led()
    NT, ns_last = nk_table(date)
    N, aux = e.build_n(h7, T[Q5], NT, Lg['kmap'], Lg['nmap'], pd.Timestamp(date))
    T = T.reset_index(drop=True)
    for c in NCOL:
        T[c] = N[c].to_numpy()
    deb = (T.l_debut == 1).to_numpy()
    rate = float((T.nk7_n[deb] > 0).mean()) if deb.any() else float('nan')
    info.update({'試験とつながった': float(aux.n_link.mean()), '走歴の無い馬': int(deb.sum()), '走歴の無い馬で試験あり': rate,
                 '試験の最後の日': ns_last})
    return T, w4, info


def watch_nk(info):
    r = info['走歴の無い馬で試験あり']
    if not np.isnan(r) and r < W_NK:
        raise SystemExit(f'⛔ 見張りで止まる(走歴の無い馬で試験の記録がある割合 {r:.3f} < 1 日分の線 {W_NK})。表は出さない')


def table(date, v):
    guard(pd.DataFrame({'race_date': [date]}), 'DATE')
    assert (MD / f'{PFX}_models.json').exists(), '学び直し(retrain)が先'
    h, races = f6.f4.fill_key(*o5.load5('forward'))
    T, w4, info = features(h, races, date, 'forward')
    watch_nk(info)
    guard(T, 'features')
    x = predict(T)
    x = x.assign(o_bw=T.o_bw.to_numpy()) if 'o_bw' in T.columns else x.assign(o_bw=np.nan)
    names = h.loc[h.race_date == date, KEY + ['umaban', 'horse_name']]
    names = names.assign(race_no=names.race_no.astype(int), umaban=names.umaban.astype(int))
    x = x.merge(names, on=KEY + ['umaban'], how='left', validate='1:1').sort_values(KEY + ['rank'], kind='mergesort')
    jl = t7.led()['jlast']
    name = f'{date}_第7版e_{o.VN[v]}'
    L = [f'# 予想表 {date}(第 7 版 e・{o.VN[v]}・オッズ・人気は見ない)', '',
         '第 7 版 e(◎ = 3 着以内に来そうな馬の 1 位)。材料 183 列 = 第 7 版 d の 177 列 + 能力試験 6 列。'
         '第 7 版 e は前日の材料だけの模型(当日版も同じ模型)。', '',
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
    OUT.mkdir(parents=True, exist_ok=True)
    x[KEY + ['umaban', 'horse_name', 'n', 'rank', 'mark', 'p3p', 'p1', 'p3']].to_csv(OUT / f'{name}.csv', index=False,
                                                                                    encoding='utf-8-sig')
    (OUT / f'{name}.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(f"{date} 第 7 版 e {o.VN[v]}: {x[KEY].drop_duplicates().shape[0]} R・{len(x)} 頭 → {OUT / (name + '.md')}"
          f" 見張り 4 列 {({k: round(val, 3) for k, val in w4.items()})}"
          f" つながり {({k: (round(val, 3) if isinstance(val, float) else val) for k, val in info.items()})}"
          f" 線 {W_NK} 中央の成績の最後 {jl}", flush=True)


def booster(t):
    return o.booster(MD / f'{PFX}_{t}.txt')


def predict(T):
    """t7d_forecast.predict と同じ(列だけ 183)。"""
    old = t7.COLS
    t7.COLS = COLS
    try:
        return t7.predict(T, {t: booster(t) for t in ('Y1', 'Y3')})
    finally:
        t7.COLS = old


# ================================================================ 学び直し
def ref_explore(days=None):
    X = t7.ref_explore(days)
    return X.merge(t7.rd(eo.fpath('explore'), Q5 + NCOL), on=Q5, how='left', validate='1:1')


def train_data():
    T = t7.rd(vo.FEAT_OUT, t7.NEED + t7.COLS)
    assert len(T) == 172738
    for f in (v7d.COP, v7d.JOP):
        T = T.merge(t7.rd(f, Q5 + t7.COLS), on=Q5, how='left', validate='1:1')
    T = T.merge(t7.rd(eo.fpath('open'), Q5 + NCOL), on=Q5, how='left', validate='1:1')
    X = ref_explore()
    assert set(T.columns) <= set(X.columns) and set(COLS) <= set(T.columns)
    df = o.sort4(pd.concat([X[list(T.columns)], T], ignore_index=True))
    del X, T
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < t7.FWD and not df.duplicated(Q5).any()
    return df


def retrain():
    jp = MD / f'{PFX}_models.json'
    if jp.exists():
        print('retrain は済み', jp); return
    df = train_data()
    meta = {'train': '2015-01-01〜2026-08-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]),
            'cfg': {k: list(v) for k, v in vo.CFG.items()}, 'cols': COLS, 'files': {}}
    for t in ('Y1', 'Y3'):
        fp = MD / f'{PFX}_{t}.txt'
        if fp.exists():
            print(t, '済み(2 回の一致を確かめてから書いたもの)', fp, flush=True)
        else:
            s1 = vc.train(df, t, COLS).model_to_string()
            gc.collect()
            s2 = vc.train(df, t, COLS).model_to_string()
            gc.collect()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {t}')
            fp.write_text(s1, encoding='utf-8', newline='\n')
            print(t, '2 回の学習が文字列で一致', len(COLS), '列', flush=True)
            del s1, s2
        meta['files'][fp.name] = {'cols': len(COLS)}
    jp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print('行', meta['rows'], 'レース', meta['races'], flush=True)


# ================================================================ 通し試験
def dry(days=None):
    """探索の写しだけ(RAW)で 2021-12-29〜31 の 183 列を作り、v7e の材料(t7d の参照 + feat_v7e2_n_explore)と一致するか。
    1 回に 1 日(py ... dry 2021-12-29)。python は 1 本だけ。"""
    days = days or t7.DRY_DAYS
    h, races = o5.load5('dry')
    ref = ref_explore(days)
    cols = COLS + ['n']
    ok = True
    for date in sorted(d for d in ref.race_date.unique() if '2021-12-29' <= d <= '2021-12-31'):
        T, _, info = features(h, races, date, 'dry', lap_lo='2021-12-01')
        a = ref[ref.race_date == date].sort_values(Q5, kind='mergesort').reset_index(drop=True)
        b = a[Q5].merge(T, on=Q5, how='left')
        A, B = a[cols].to_numpy(float), b[cols].to_numpy(float)
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        part = {g: [int(eq[:, [cols.index(c) for c in cs]].sum()), len(a) * len(cs)]
                for g, cs in (('b7', t7.B7), ('c7', v7d.C7), ('j7', v7d.J7), ('nk7', NCOL))}
        bad = {c: int((~eq[:, i]).sum()) for i, c in enumerate(cols) if not eq[:, i].all()}
        print(date, 'v7e の馬', len(a), '予想表の馬', len(T), '一致', int(eq.sum()), '/', eq.size, part, '合わない列', bad,
              '走歴の無い馬で試験あり', round(info['走歴の無い馬で試験あり'], 3), flush=True)
        ok &= len(a) == len(T) and not bad
        del T, a, b
        gc.collect()
    if not ok:
        raise SystemExit('⛔ dry が一致しない')
    print('dry OK')


if __name__ == '__main__':
    a = sys.argv[1:]
    {'fetch': lambda: f6.fetch(a[1]), 'nk': lambda: nk_fetch(a[1]), 'retrain': retrain,
     'table': lambda: table(a[1], a[2]), 'dry': lambda: dry(a[1:] or None)}[a[0]]()
