# -*- coding: utf-8 -*-
"""第 5 版の毎日の予想表(PREREG5 §1・§8・§9)。4 日目に sha256 で固定する。オッズは見ない。使い方は t4_forecast.py と同じ。

  py -3.12 -X utf8 src/t5_forecast.py fetch DATE        # DB から 2026-09-01〜DATE の写し(t4_forecast.fetch = t3_forecast.fetch)→ v3/db_*_forward_t3.parquet
  py -3.12 -X utf8 src/t5_forecast.py retrain           # 6 日目: 2015〜2026-08 で第 5 版を学び直す(2 回の一致)→ models/t5d6_*.txt
  py -3.12 -X utf8 src/t5_forecast.py table DATE pre    # 前の晩: 前日版 → out/forecast/DATE_第5版_前日版.md・.csv
  py -3.12 -X utf8 src/t5_forecast.py table DATE day    # 当日(馬体重の発表後): 当日版 → out/forecast/DATE_第5版_当日版.md・.csv
  py -3.12 -X utf8 src/t5_forecast.py dry               # 4 日目の通し試験: 探索の写しだけで 2021-12-29〜31 の材料を作り、feat_t5_explore と一致するか

- 読み込みは t5_open.load5('forward')(= t4_open.load4 + 第 5 版の列の確かめ)と t4_forecast.fill_key(馬の鍵の埋め)。
  返す・保存する行は race_date ≥ 2026-09-01 だけ(guard)。
- 予想するレース・n は t3_forecast.frame と同じ(t4_forecast と同じ)。
- 材料 = t4_forecast.features と同じ渡し方(DATE より後の行を消し、DATE の結果の列を消す)で、t5_open と同じ順
  (base_of → rebuild の一致 → make_si5〔t5_base.YRS を最後の年まで延ばす〕→ rebuild(U, SI5) → feat_new・assemble → parts_of)。
  〔v3〕の列は t3_forecast.features。parts_of の通過順(c1〜n4)は DATE の分を消した走りから取る。
- 見張り(§9・届かなければ表を出さずに止まる): t4_forecast.watch(horse_key の埋まり 99% 以上・走歴の無い馬の割合)+ 前日までの
  南関のレース(前向きの写しの始まり 2026-09-01〜DATE の前日。dry は 2021-12-01〜)のラップ・通過順が読めること
  (t5_open.guard_laps: 知らない記号 0・読めないレース ≤ 0.1%・ラップの外れ ≤ 1%・上がり 3F の外れ ≤ 1%)。
- 模型 = models/t5d6_*(6 日目に学び直したもの)。無ければ止まる(dry は models/t5_*)。
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
import t5_base  # noqa: E402
import t5_day3 as d5  # noqa: E402
import t5_open as o5  # noqa: E402
from t3_day2_features import targets3  # noqa: E402

V3 = o.V3
REPO = o.REPO
MD = o.MD
FWD = t3_forecast.FWD
OUT = REPO / 'out/forecast'
KEY = d3.KEY
NANKAN = d3.NANKAN
guard = t3_forecast.guard
FACT_RES = f4.FACT_RES


def fetch(date):
    f4.fetch(date)


def features(h, races, date):
    """DATE の予想する行の第 5 版の材料(META + 118 列)。"""
    r = h[h.race_date <= date].copy()
    m = r.race_date == date
    r.loc[m, [c for c in t4_base.RES_RUN if c in r.columns]] = np.nan
    r.loc[m & ~r.finish_note.isin(o.CANCEL), 'finish_note'] = np.nan
    r.loc[m, FACT_RES] = np.nan
    c = races[races.race_date <= date].copy()
    c.loc[c.race_date == date, t4_base.RES_RACE] = np.nan
    tg = targets3(h[h.race_date < date])
    tday = t3_forecast.frame(h, date)
    U, U5, _, _ = o5.base5(r, c)
    Tn = d3.feat_new(U5, r, c, tg, tday)
    X3 = t3_forecast.features(h, date)
    for col in ('Y1', 'Y3', 'pop'):
        if col not in X3.columns:
            X3[col] = np.nan
    T = d3.assemble(Tn, X3)
    fc = r[r.track.isin(NANKAN)][KEY + ['umaban'] + o5.CORNER]
    N, _, _, _ = d5.parts_of(U5, fc, c, r, tday)
    T['race_no'], T['umaban'] = T.race_no.astype(int), T.umaban.astype(int)
    T = T.merge(N, on=KEY + ['umaban'], how='left', validate='1:1', indicator=True)
    assert (T.pop('_merge') == 'both').all()
    return T[d3.META + o5.ALL5].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)


def watch_laps(h, races, date, lo):
    """前日までの南関のレース [lo, DATE) のラップ・通過順(勝ち時計 = h の time_sec の最小)。"""
    x = h[h.track.isin(NANKAN) & (h.race_date >= lo) & (h.race_date < date) & ~h.finish_note.isin(o.CANCEL)]
    tw = x.groupby([x.track, x.race_date, x.race_no.astype(int)]).time_sec.min().rename('tw').reset_index()
    o5.guard_laps(races, tw[tw.tw.notna()], lo, date, '前日までの南関のレース')


def table(date, v, h=None, races=None, M=None, write=True, lap_lo=FWD):
    if h is None:
        guard(pd.DataFrame({'race_date': [date]}), 'DATE')
        assert (MD / 't5d6_models.json').exists(), '6 日目の学び直しが先'
        h, races = f4.fill_key(*o5.load5('forward'))
        M = o5.models5('t5d6')
    watch_laps(h, races, date, lap_lo)
    T = features(h, races, date)
    f4.watch(h, T, date)
    if write:
        guard(T, 'features')
    x = t3_eval.marks(t3_eval.predict(*M[v], T, o5.C5[v]))
    names = h.loc[h.race_date == date, KEY + ['umaban', 'horse_name']]
    x = x.merge(names, on=KEY + ['umaban'], how='left').sort_values(KEY + ['rank'], kind='mergesort')
    if not write:
        return T, x
    name = f'{date}_第5版_{o.VN[v]}'
    L = [f'# 予想表 {date}(第 5 版・{o.VN[v]}・オッズは見ない)', '',
         '印: ◎ = 1 位・○ = 2 位・▲ = 3 位・△ = 4〜5 位。勝つ確率はレース内で合計 1。3 着以内の確率はレース内でそろえていない。']
    for k, g in x.groupby(KEY, sort=False):
        L += ['', f'## {k[0]} {k[2]}R({len(g)} 頭)']
        if v == 'day' and g.o_bw.isna().all():
            L.append('馬体重の発表前のため当日版は出さない(前日版を見る)')
            continue
        L += ['', '| 印 | 馬番 | 馬名 | 勝つ確率 | 3 着以内の確率 |', '|---|---|---|---|---|']
        L += [f'| {r.mark} | {r.umaban} | {r.horse_name} | {r.p1:.3f} | {r.p3:.3f} |' for r in g.itertuples()]
    OUT.mkdir(parents=True, exist_ok=True)
    x[KEY + ['umaban', 'horse_name', 'n', 'rank', 'mark', 'p1', 'p3']].to_csv(OUT / f'{name}.csv', index=False, encoding='utf-8-sig')
    (OUT / f'{name}.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(f"{date} 第 5 版 {o.VN[v]}: {x[KEY].drop_duplicates().shape[0]} R・{len(x)} 頭 → {OUT / (name + '.md')}")


def retrain():
    ex = pd.read_parquet(o5.FEAT5)
    df = o.sort4(pd.concat([ex, pd.read_parquet(o5.FEAT_OPEN5)[ex.columns]], ignore_index=True))
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < FWD and not df.duplicated(KEY + ['umaban']).any()
    meta = {'train': '2015-01-01〜2026-08-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]),
            'cfg': {k: list(v) for k, v in o5.CFG5.items()}, 'files': {}}
    for v, cols in o5.C5.items():
        for t in ('Y1', 'Y3'):
            s1, s2 = o5.train5(df, cols, t).model_to_string(), o5.train5(df, cols, t).model_to_string()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {v} {t}')
            fp = MD / f't5d6_{v}_{t}.txt'
            fp.write_text(s1, encoding='utf-8', newline='\n')
            meta['files'][fp.name] = {'cols': cols}
            print(v, t, '一致', flush=True)
    (MD / 't5d6_models.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')


def dry():
    """探索の期間(2021-12-29〜31)で、予想表の材料の作り方が 3 日目の材料の表と一致するか(書き出しはしない)。"""
    h, races = o5.load5('dry')
    ref = pd.read_parquet(o5.FEAT5)
    M = o5.models5('t5')
    cols = o5.ALL5 + ['n']
    for date in sorted(d for d in ref.race_date.unique() if '2021-12-29' <= d <= '2021-12-31'):
        T, x = table(date, 'pre', h=h, races=races, M=M, write=False, lap_lo='2021-12-01')
        a = ref[ref.race_date == date].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
        a['race_no'] = a.race_no.astype(int)
        b = a[KEY + ['umaban']].merge(T, on=KEY + ['umaban'], how='left')
        A, B = a[cols].to_numpy(float), b[cols].to_numpy(float)
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        print(date, '3 日目の馬', len(a), '予想表の馬', len(T), '一致', int(eq.sum()), '/', eq.size,
              '◎', int((x['rank'] == 1).sum()), flush=True)
        assert eq.all(), [c for c, k in zip(cols, eq.all(0)) if not k]
    print('dry OK')


if __name__ == '__main__':
    a = sys.argv[1:]
    {'fetch': lambda: fetch(a[1]), 'retrain': retrain, 'table': lambda: table(a[1], a[2]), 'dry': dry}[a[0]]()
