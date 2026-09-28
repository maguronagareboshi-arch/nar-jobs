# -*- coding: utf-8 -*-
"""第 3 版の毎日の予想表(PREREG3 §1・§2・§8)。3 日目に sha256 で固定する。オッズは見ない。

  py -3.12 -X utf8 src/t3_forecast.py fetch DATE        # DB から 2026-09-01〜DATE の走り・レース・facts(全 NAR 場)を写す → v3/db_*_forward_t3.parquet
  py -3.12 -X utf8 src/t3_forecast.py retrain           # 5 日目: 2015〜2026-08 で両版を学び直す(2 回の一致)→ models/t3d5_*.txt
  py -3.12 -X utf8 src/t3_forecast.py table DATE pre    # 前の晩: 前日版の予想表 → out/forecast/DATE_前日版.md・.csv
  py -3.12 -X utf8 src/t3_forecast.py table DATE day    # 当日(馬体重の発表後): 当日版の予想表 → out/forecast/DATE_当日版.md・.csv
  py -3.12 -X utf8 src/t3_forecast.py dry               # 3 日目の通し試験: 探索の写しだけで 2021-12 の 3 日の表を作り、2 日目の材料からの予想と一致するか

- 前向きの写し(db_*_forward_t3)を読むのはこの台本だけ。読む・返す・保存する行は race_date ≥ 2026-09-01 だけ(見張り: guard)。
  走歴 = t3_open.sources('forward')(RAW + 確認 + 封印 + 前向きの写し)。途中の表・確認や封印の期間の予想は出さない。
- 予想するレース = 南関 4 場・DATE・取消と除外を除く出走 5 頭以上(着順の有無で絞らない)。n = その時点の出走予定の数
  (前の晩は当日の取消が分からない。PREREG3 §2)。材料は build に「DATE より前の走歴」と「DATE の出走表の列」だけを渡して作る
  (2 日目のリーク検査と同じ渡し方)。騎手・調教師の元 = 着順のある南関のレース(targets3)。
- 当日版は馬場(races.going)・馬体重・増減を使う。馬体重が 1 頭も無いレースは当日版を出さず「馬体重の発表前」と書く。
- 模型 = models/t3d5_*(5 日目に学び直したもの)。無ければ止まる(dry は models/t3_* を使う)。
- 表: レースごとに予想順位の順で 馬番・馬名・印(◎○▲△△)・勝つ確率 p1・3 着以内の確率 p3。
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from day2_db_copy import NANKAN, SPEC, req, tracks  # noqa: E402
from day2_features import ENTRY_COLS, KEY, RACE_COLS, build  # noqa: E402
from t3_day2_features import finish_table, targets3  # noqa: E402
from t3_eval import V3, VERSIONS, VNAME, check_grid, marks, predict, train  # noqa: E402
from t3_open import MD, models, sources  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FWD = '2026-09-01'
OUT = REPO / 'out/forecast'


def guard(df, name, lo=FWD):
    bad = int((df.race_date.astype(str) < lo).sum())
    if bad:
        raise SystemExit(f'⛔{name} に {lo} より前が {bad} 行。前向きの行だけを返す')
    return df


def fetch(date):
    for kind in ('runs', 'races', 'facts'):
        table, key = SPEC[kind]
        rows = []
        for t in tracks():
            off = 0
            while True:
                got = req(table, [('select', '*'), ('track', f'eq.{t}'), ('race_date', f'gte.{FWD}'), ('race_date', f'lte.{date}'),
                                  ('order', ','.join(key)), ('limit', '1000'), ('offset', str(off))])
                rows += got
                if len(got) < 1000:
                    break
                off += 1000
        df = pd.DataFrame(rows)
        for c in df.columns:
            if df[c].map(lambda v: isinstance(v, (dict, list))).any():
                df[c] = df[c].map(lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True) if v is not None else None)
        df = guard(df.sort_values(key, kind='mergesort').reset_index(drop=True), kind)
        assert not df.duplicated(key).any(), (kind, 'key dup')
        df.to_parquet(V3 / f'db_{kind}_forward_t3.parquet', index=False)
        print(kind, 'rows', len(df), 'max', df.race_date.max(), flush=True)


def frame(h, date):
    """DATE の南関の予想するレースの出走予定(取消・除外を除く・5 頭以上)。"""
    r = h[(h.race_date == date) & h.track.isin(NANKAN) & ~h.finish_note.isin(['取消', '除外'])]
    df = r[KEY + ['umaban']].copy()
    df['n'] = df.groupby(KEY).umaban.transform('size')
    df = df[df.n >= 5].reset_index(drop=True)
    df['Y1'] = df['Y3'] = float('nan')
    df['K'], df['E_mid'] = 3, 3 / df.n
    df['q'] = df['plc_lo'] = df['plc_hi'] = float('nan')
    df['year'] = int(date[:4])
    df['meet'] = float('nan')
    return df


def features(h, date):
    tg = targets3(h[h.race_date < date])
    ent = h.loc[h.race_date == date, KEY + ['umaban', 'hid'] + ENTRY_COLS + RACE_COLS + ['body_weight']]
    X, _ = build(h[h.race_date < date], frame(h, date), tg, ent=ent)
    X = finish_table(X.drop(columns=['Y1'], errors='ignore'), ent, tg)  # Y1・pop は着順のある targets3 から(DATE は空)
    return X.sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)


def table(date, v, h=None, M=None, write=True):
    if h is None:
        guard(pd.DataFrame({'race_date': [date]}), 'DATE')
        assert (MD / 't3d5_models.json').exists(), '5 日目の学び直しが先'
        h, M = sources('forward'), models('t3d5')
    X = features(h, date)
    if not write:
        return X
    guard(X, 'features')
    x = marks(predict(*M[v], X, VERSIONS[v]))
    names = h.loc[h.race_date == date, KEY + ['umaban', 'horse_name']]
    x = x.merge(names, on=KEY + ['umaban'], how='left').sort_values(KEY + ['rank'], kind='mergesort')
    L = [f'# 予想表 {date}({VNAME[v]}・オッズは見ない)', '',
         '印: ◎ = 1 位・○ = 2 位・▲ = 3 位・△ = 4〜5 位。勝つ確率はレース内で合計 1。3 着以内の確率はレース内でそろえていない(合計は平均 3 前後で、レースにより 2〜4.5 ほど)。']
    for k, g in x.groupby(KEY, sort=False):
        L += ['', f'## {k[0]} {k[2]}R({len(g)} 頭)']
        if v == 'day' and g.s4b_bw.isna().all():
            L.append('馬体重の発表前のため当日版は出さない(前日版を見る)')
            continue
        L += ['', '| 印 | 馬番 | 馬名 | 勝つ確率 | 3 着以内の確率 |', '|---|---|---|---|---|']
        L += [f'| {r.mark} | {r.umaban} | {r.horse_name} | {r.p1:.3f} | {r.p3:.3f} |' for r in g.itertuples()]
    OUT.mkdir(parents=True, exist_ok=True)
    x[KEY + ['umaban', 'horse_name', 'n', 'rank', 'mark', 'p1', 'p3']].to_csv(OUT / f'{date}_{VNAME[v]}.csv', index=False,
                                                                                encoding='utf-8-sig')
    (OUT / f'{date}_{VNAME[v]}.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(f"{date} {VNAME[v]}: {x[KEY].drop_duplicates().shape[0]} R・{len(x)} 頭 → {OUT / f'{date}_{VNAME[v]}.md'}")


def retrain():
    check_grid()
    parts = [pd.read_parquet(V3 / f'feat_t3_{p}.parquet') for p in ('explore', 'confirm', 'sealed')]
    df = pd.concat([parts[0]] + [p[parts[0].columns] for p in parts[1:]], ignore_index=True)
    df = df.sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)  # 3 日目の fit と同じ並び
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < FWD and not df.duplicated(KEY + ['umaban']).any()
    meta = {'train': '2015-01-01〜2026-08-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]), 'files': {}}
    for v, cols in VERSIONS.items():
        for t in ('Y1', 'Y3'):
            s1, s2 = train(df, cols, t).model_to_string(), train(df, cols, t).model_to_string()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {v} {t}')
            fp = MD / f't3d5_{v}_{t}.txt'
            fp.write_text(s1, encoding='utf-8', newline='\n')
            meta['files'][fp.name] = {'cols': cols}
            print(v, t, '一致', flush=True)
    (MD / 't3d5_models.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')


def dry():
    """探索の期間(2021-12 の 3 日)で、予想表の材料の作り方が 2 日目の材料の表と一致するかを確かめる(書き出しはしない)。"""
    h = sources('dry')
    ref = pd.read_parquet(V3 / 'feat_t3_explore.parquet')
    cols = VERSIONS['day'] + ['n']
    for date in sorted(ref[ref.race_date >= '2021-12-01'].race_date.unique())[-3:]:
        X = table(date, 'pre', h=h, write=False)
        a = ref[ref.race_date == date].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
        # 予想表は着順の有無・当日の取消で絞らない。2 日目の表にある馬だけで比べる
        b = a[KEY + ['umaban']].merge(X, on=KEY + ['umaban'], how='left')
        A, B = a[cols].to_numpy(float), b[cols].to_numpy(float)
        eq = ((pd.isna(A) & pd.isna(B)) | (abs(A - B) <= 1e-9))
        print(date, '2 日目の馬', len(a), '予想表の馬', len(X), '一致', int(eq.sum()), '/', eq.size, flush=True)
        assert eq.all(), [c for c, k in zip(cols, eq.all(0)) if not k]
    print('dry OK')


if __name__ == '__main__':
    a = sys.argv[1:]
    {'fetch': lambda: fetch(a[1]), 'retrain': retrain, 'table': lambda: table(a[1], a[2]), 'dry': dry}[a[0]]()
