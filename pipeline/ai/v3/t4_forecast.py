# -*- coding: utf-8 -*-
"""第 4 版の毎日の予想表(PREREG4 §1・§2・§9)。4 日目に sha256 で固定する。オッズは見ない。使い方は t3_forecast.py と同じ。

  py -3.12 -X utf8 src/t4_forecast.py fetch DATE        # DB から 2026-09-01〜DATE の写し(t3_forecast.fetch をそのまま呼ぶ)→ v3/db_*_forward_t3.parquet
  py -3.12 -X utf8 src/t4_forecast.py retrain           # 6 日目: 2015〜2026-08 で両版を学び直す(2 回の一致)→ models/t4d6_*.txt
  py -3.12 -X utf8 src/t4_forecast.py table DATE pre    # 前の晩: 前日版 → out/forecast/DATE_第4版_前日版.md・.csv
  py -3.12 -X utf8 src/t4_forecast.py table DATE day    # 当日(馬体重の発表後): 当日版 → out/forecast/DATE_第4版_当日版.md・.csv
  py -3.12 -X utf8 src/t4_forecast.py dry               # 4 日目の通し試験: 探索の写しだけで 2021-12-29〜31 の材料を作り、feat_t4_explore と一致するか

- 読み込みは t4_open.load4('forward')(t3_open.sources の走り + races4)。返す・保存する行は race_date ≥ 2026-09-01 だけ(guard)。
- 予想するレース・n は t3_forecast.frame と同じ(DATE の南関・取消と除外を除く出走予定 5 頭以上。n = 出走予定の数)。
- 材料 = 3 日目のリーク検査と同じ渡し方: DATE より後の行を消し、DATE の結果の列(走り・facts・レース)を消してから t4_base → feat_new。
  〔v3〕の列は t3_forecast.features(DATE より前の走歴 + DATE の出走表の列)。組に掛かる列は前日の出走予定の馬で作る(§3-3)。
- 見張り(§9・届かなければ表を出さずに止まる): DATE の南関の出走予定(取消・除外を除く)の horse_key の埋まり 99% 以上/走歴の無い馬
  (l_debut = 1)の割合が feat_t4_explore の 2016〜2021 の同じ月の割合の最大 + 0.05 以下。
- 鍵の埋め(6 日目のバグ直し): まだ走っていない日の馬は horse_key が無いので「馬名|(開催年 − 年齢)」で埋める(fill_key)。
- 模型 = models/t4d6_*(6 日目に学び直したもの)。無ければ止まる(dry は models/t4_*)。
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
import t4_open as o  # noqa: E402
from t3_day2_features import targets3  # noqa: E402

V3 = o.V3
REPO = o.REPO
MD = o.MD
FWD = t3_forecast.FWD
OUT = REPO / 'out/forecast'
KEY = d3.KEY
NANKAN = d3.NANKAN
guard = t3_forecast.guard
FACT_RES = ['f_l3', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']


def fetch(date):
    t3_forecast.fetch(date)


def features(h, races, date):
    """DATE の予想する行の第 4 版の材料(META + 96 列)。"""
    r = h[h.race_date <= date].copy()
    m = r.race_date == date
    r.loc[m, [c for c in t4_base.RES_RUN if c in r.columns]] = np.nan
    r.loc[m & ~r.finish_note.isin(o.CANCEL), 'finish_note'] = np.nan
    r.loc[m, FACT_RES] = np.nan
    c = races[races.race_date <= date].copy()
    c.loc[c.race_date == date, t4_base.RES_RACE] = np.nan
    tg = targets3(h[h.race_date < date])
    tday = t3_forecast.frame(h, date)
    U = o.base_of(r, c)
    Tn = d3.feat_new(U, r, c, tg, tday)
    X3 = t3_forecast.features(h, date)
    for col in ('Y1', 'Y3', 'pop'):
        if col not in X3.columns:
            X3[col] = np.nan
    T = d3.assemble(Tn, X3)
    return T[d3.META + d3.ALL].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)


def watch(h, T, date):
    e = h[(h.race_date == date) & h.track.isin(NANKAN) & ~h.finish_note.isin(o.CANCEL)]
    fill = float(e.horse_key.notna().mean()) if len(e) else 1.0
    ex = pd.read_parquet(d3.FEAT, columns=['year', 'race_date', 'l_debut'])
    ex = ex[(ex.year >= 2016) & (ex.year <= 2021)]
    base = ex.assign(mm=ex.race_date.str[5:7]).groupby(['year', 'mm']).l_debut.apply(lambda s: (s == 1).mean())
    lim = float(base.xs(date[5:7], level='mm').max()) + 0.05
    share = float((T.l_debut == 1).mean()) if len(T) else 0.0
    if fill < 0.99 or share > lim:
        raise SystemExit(f'⛔ 見張りで止まる(horse_key の埋まり {fill:.3f}・走歴の無い馬 {share:.3f} / 線 {lim:.3f})。表は出さない')
    return fill, share, lim


def fill_key(h, races):
    """バグ直し(6 日目・見張りで発見): 前向きの写しでは、まだ走っていない日の馬に horse_key(facts から作る)が無く、
    全馬が走歴の無い馬になる。鍵の無い行は「馬名|(開催年 − 年齢)」で埋める(地方の年齢は暦年。2022 年以降の 659,604 行で本物の鍵と 100% 一致)。"""
    m = h.horse_key.isna() & h.age.notna()
    h.loc[m, 'horse_key'] = h.loc[m, 'horse_name'] + '|' + (h.loc[m, 'race_date'].str[:4].astype(int) - h.loc[m, 'age'].astype(int)).astype(str)
    h['hid'] = h.horse_key.fillna(h.horse_name)
    return h, races


def table(date, v, h=None, races=None, M=None, write=True):
    if h is None:
        guard(pd.DataFrame({'race_date': [date]}), 'DATE')
        assert (MD / 't4d6_models.json').exists(), '6 日目の学び直しが先'
        h, races = fill_key(*o.load4('forward'))
        M = o.models4('t4d6')
    T = features(h, races, date)
    watch(h, T, date)
    if write:
        guard(T, 'features')
    x = t3_eval.marks(t3_eval.predict(*M[v], T, o.C4[v]))
    names = h.loc[h.race_date == date, KEY + ['umaban', 'horse_name']]
    x = x.merge(names, on=KEY + ['umaban'], how='left').sort_values(KEY + ['rank'], kind='mergesort')
    if not write:
        return T, x
    name = f'{date}_第4版_{o.VN[v]}'
    L = [f'# 予想表 {date}(第 4 版・{o.VN[v]}・オッズは見ない)', '',
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
    print(f"{date} 第 4 版 {o.VN[v]}: {x[KEY].drop_duplicates().shape[0]} R・{len(x)} 頭 → {OUT / (name + '.md')}")


def retrain():
    ex = pd.read_parquet(d3.FEAT)
    df = o.sort4(pd.concat([ex, pd.read_parquet(o.FEAT_OPEN)[ex.columns]], ignore_index=True))
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < FWD and not df.duplicated(KEY + ['umaban']).any()
    meta = {'train': '2015-01-01〜2026-08-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]),
            'cfg': {k: list(v) for k, v in o.CFG4.items()}, 'files': {}}
    for v, cols in o.C4.items():
        for t in ('Y1', 'Y3'):
            s1, s2 = o.train4(df, cols, t).model_to_string(), o.train4(df, cols, t).model_to_string()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {v} {t}')
            fp = MD / f't4d6_{v}_{t}.txt'
            fp.write_text(s1, encoding='utf-8', newline='\n')
            meta['files'][fp.name] = {'cols': cols}
            print(v, t, '一致', flush=True)
    (MD / 't4d6_models.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')


def dry():
    """探索の期間(2021-12-29〜31)で、予想表の材料の作り方が 3 日目の材料の表と一致するか(書き出しはしない)。"""
    h, races = o.load4('dry')
    ref = pd.read_parquet(d3.FEAT)
    M = o.models4('t4')
    cols = d3.ALL + ['n']
    for date in sorted(d for d in ref.race_date.unique() if '2021-12-29' <= d <= '2021-12-31'):
        T, x = table(date, 'pre', h=h, races=races, M=M, write=False)
        a = ref[ref.race_date == date].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
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
