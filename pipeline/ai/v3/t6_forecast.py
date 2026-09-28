# -*- coding: utf-8 -*-
"""第 6 版の毎日の予想表(PREREG6 §2・§9・§11 の 6 日目)。6 日目に sha256 で固定する。オッズは見ない。使い方は t5_forecast.py と同じ。

  py -3.12 -X utf8 src/t6_forecast.py fetch DATE        # DB から 2026-09-01〜DATE の写し(t4_forecast.fetch)→ v3/db_*_forward_t3.parquet
  py -3.12 -X utf8 src/t6_forecast.py retrain           # 6 日目: 2015〜2026-08 で第 6 版を学び直す(2 回の一致)→ models/t6d6_*.txt
  py -3.12 -X utf8 src/t6_forecast.py table DATE pre    # 前の晩: 前日版 → out/forecast/DATE_第6版_前日版.md・.csv
  py -3.12 -X utf8 src/t6_forecast.py table DATE day    # 当日(馬体重の発表後): 当日版 → out/forecast/DATE_第6版_当日版.md・.csv
  py -3.12 -X utf8 src/t6_forecast.py dry               # 通し試験: 探索の写しだけで 2021-12-29〜31 の材料を作り、feat_t6_explore と一致するか

- 読み込み・第 5 版の 118 列 = t5_forecast と同じ(t5_open.load5('forward') + t4_forecast.fill_key・t5_forecast.features)。
  返す・保存する行は race_date ≥ 2026-09-01 だけ(guard)。
- 4 列(h2h・elo_z・nori・bw_diff)= t6_open.build6(= t6_base.starts → cols4)。元の走り = 同じ h(RAW 2014〜2021 + DB の確かめる期間・
  封印・前向きの写し・全 NAR)のうち DATE 以前で、DATE の結果の列は t5_forecast.features と同じ消し方で消したもの。前日版の騎手 = 出馬表の騎手。
- 模型 = models/t6d6_*(t6_open と同じ設定・並べ方で 2015〜2026-08 を学び直したもの。dry は models/t6_*)。
  予想 = t3_eval.predict の p1・p3 → p3′(t6_day3.p3p = t6_base.p3prime)→ 印 = p3′ → p1 → 馬番の順(t3_eval.marks と同じ印)。
- 見張り(届かなければ表を出さずに止まる): t5_forecast と同じ(ラップ・通過順・horse_key の埋まり・走歴の無い馬の割合)+
  DATE の予想する行の h2h・elo_z の値のある割合・nori_ch = 1・nori_dr = 1 の割合 ≥ 1 日分の線 W_DAY。
- 1 日分の線(ユーザー承認 2026-09-27): はじめ t6_open.W3(答え合わせで 1 年分・区切りの割合に当てた線)を 1 日分に当てていて、
  09-28 の前日版が h2h 0.677 < 0.751 で止まった。作る期間 2016〜2021 の開催日(日付 × 場)1,626 日では、その線を下回る日が
  h2h 20.7%・elo_z 13.5%・nori_ch 14.8%・nori_dr 15.8% あり、ふつうの日でも止まる。→ 1 日分の線 = 作る期間の 1 日ごとの割合の最小
  (h2h 0.44・elo_z 0.52・nori_ch 0.033・nori_dr 0.040)に替えた。馬のつながりが壊れたとき(割合が大きく落ちる)だけ止まる。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_eval  # noqa: E402
import t3_forecast  # noqa: E402
import t4_base  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_forecast as f4  # noqa: E402
import t4_open as o  # noqa: E402
import t5_forecast as f5  # noqa: E402
import t5_open as o5  # noqa: E402
import t6_base  # noqa: E402
import t6_day3  # noqa: E402
import t6_open as o6  # noqa: E402

REPO = o.REPO
MD = o.MD
FWD = t3_forecast.FWD
OUT = REPO / 'out/forecast'
KEY = d3.KEY
NEW4 = t6_base.NEW4
C6 = o6.C6
W3 = o6.W3
W_DAY = {'h2h': 0.44, 'elo_z': 0.52, 'nori_ch1': 0.033, 'nori_dr1': 0.040}  # 1 日分の線(作る期間の 1 日ごとの最小・承認 2026-09-27)
guard = t3_forecast.guard


def fetch(date):
    f4.fetch(date)


def models6(prefix):
    return {v: (o.booster(MD / f'{prefix}_{v}_Y1.txt'), o.booster(MD / f'{prefix}_{v}_Y3.txt')) for v in ('pre', 'day')}


def blank(h, date):
    """t5_forecast.features と同じ: DATE より後を消し、DATE の結果の列を消した走り。"""
    r = h[h.race_date <= date].copy()
    m = r.race_date == date
    r.loc[m, [c for c in t4_base.RES_RUN if c in r.columns]] = np.nan
    r.loc[m & ~r.finish_note.isin(o.CANCEL), 'finish_note'] = np.nan
    r.loc[m, f5.FACT_RES] = np.nan
    # バグ直し(6 日目 dry): body_weight は RES_RUN に入っているが、4 列では出走表の列(当日の発表)として残す
    # (t6_base 細部 8 のリーク検査と同じ・build6 の o_bw との一致の assert。bw_diff だけに効き、最終形の列には入らない)
    r.loc[m, 'body_weight'] = h.loc[r.index[m], 'body_weight']
    return r


def features(h, races, date):
    """DATE の予想する行の第 6 版の材料(META + 第 5 版の列 + 4 列)と見張り用の nori_ch・nori_dr。"""
    T = f5.features(h, races, date)
    T6, aux, _, _ = o6.build6(blank(h, date), T, '9999-12-31')
    assert T6[KEY + ['umaban']].equals(o6.nk(T)[KEY + ['umaban']])
    return T6, aux


def watch4(T6, aux):
    r = {'h2h': float(T6.h2h.notna().mean()), 'elo_z': float(T6.elo_z.notna().mean()),
         'nori_ch1': float((aux.nori_ch == 1).mean()), 'nori_dr1': float((aux.nori_dr == 1).mean())}
    bad = {k: round(v, 3) for k, v in r.items() if v < W_DAY[k]}
    if bad:
        raise SystemExit(f'⛔ 見張りで止まる(4 列の値のある割合 {bad} / 1 日分の線 {W_DAY})。表は出さない')
    return r


def table(date, v, h=None, races=None, M=None, write=True, lap_lo=FWD):
    if h is None:
        guard(pd.DataFrame({'race_date': [date]}), 'DATE')
        assert (MD / 't6d6_models.json').exists(), '6 日目の学び直しが先'
        h, races = f4.fill_key(*o5.load5('forward'))
        M = models6('t6d6')
    f5.watch_laps(h, races, date, lap_lo)
    T, aux = features(h, races, date)
    f4.watch(h, T, date)
    w4 = watch4(T, aux)
    if write:
        guard(T, 'features')
    x = t3_eval.predict(*M[v], T, C6[v])
    q, _ = t6_day3.p3p(x, x.p3.to_numpy())
    x = t3_eval.marks(x.assign(p3p=q), p1='p3p', p3='p1')
    names = h.loc[h.race_date == date, KEY + ['umaban', 'horse_name']]
    names = names.assign(race_no=names.race_no.astype(int), umaban=names.umaban.astype(int))
    x = x.merge(names, on=KEY + ['umaban'], how='left', validate='1:1').sort_values(KEY + ['rank'], kind='mergesort')
    if not write:
        return T, x
    name = f'{date}_第6版_{o.VN[v]}'
    L = [f'# 予想表 {date}(第 6 版・{o.VN[v]}・オッズは見ない)', '',
         '第 6 版(◎ = 3 着以内に来そうな馬の 1 位)', '',
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
    print(f"{date} 第 6 版 {o.VN[v]}: {x[KEY].drop_duplicates().shape[0]} R・{len(x)} 頭 → {OUT / (name + '.md')}"
          f" 見張り 4 列 {({k: round(val, 3) for k, val in w4.items()})}")


def retrain():
    ex = o6.nk(pd.read_parquet(o6.FEAT6X))
    df = o.sort4(pd.concat([ex, o6.nk(pd.read_parquet(o6.FEAT6O))[ex.columns]], ignore_index=True))
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < FWD and not df.duplicated(KEY + ['umaban']).any()
    meta = {'train': '2015-01-01〜2026-08-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]),
            'cfg': {k: list(v) for k, v in o6.CFG6.items()}, 'files': {}}
    for v, cols in C6.items():
        for t in ('Y1', 'Y3'):
            s1, s2 = o6.train6(df, cols, t).model_to_string(), o6.train6(df, cols, t).model_to_string()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {v} {t}')
            fp = MD / f't6d6_{v}_{t}.txt'
            fp.write_text(s1, encoding='utf-8', newline='\n')
            meta['files'][fp.name] = {'cols': cols}
            print(v, t, '2 回の学習が文字列で一致', len(cols), '列', flush=True)
    (MD / 't6d6_models.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print('行', meta['rows'], 'レース', meta['races'], flush=True)


def dry():
    """探索の期間(2021-12-29〜31)で、予想表の材料の作り方が feat_t6_explore と一致するか(書き出しはしない)。"""
    h, races = o5.load5('dry')
    ref = o6.nk(pd.read_parquet(o6.FEAT6X))
    M = models6('t6')
    cols = o5.ALL5 + NEW4 + ['n']
    for date in sorted(d for d in ref.race_date.unique() if '2021-12-29' <= d <= '2021-12-31'):
        T, x = table(date, 'pre', h=h, races=races, M=M, write=False, lap_lo='2021-12-01')
        a = ref[ref.race_date == date].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
        b = a[KEY + ['umaban']].merge(T, on=KEY + ['umaban'], how='left')
        A, B = a[cols].to_numpy(float), b[cols].to_numpy(float)
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        e4 = eq[:, [cols.index(c) for c in NEW4]]
        print(date, '3 日目の馬', len(a), '予想表の馬', len(T), '一致', int(eq.sum()), '/', eq.size,
              '(4 列', int(e4.sum()), '/', e4.size, ')', '◎', int((x['rank'] == 1).sum()), flush=True)
        assert len(a) == len(T) and eq.all(), [c for c, k in zip(cols, eq.all(0)) if not k]
    print('dry OK')


if __name__ == '__main__':
    a = sys.argv[1:]
    {'fetch': lambda: fetch(a[1]), 'retrain': retrain, 'table': lambda: table(a[1], a[2]), 'dry': dry}[a[0]]()
