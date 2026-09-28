# -*- coding: utf-8 -*-
"""2 日目(PREREG2 §7-2): 確認・封印の DB の写し。行の値は画面にも台帳にも出さない(行数・レース数・sha256 だけ)。

  py -3.12 -X utf8 src/day2_db_copy.py runs      # nar_runs(全 NAR 場)
  py -3.12 -X utf8 src/day2_db_copy.py races     # nar_races(全 NAR 場)
  py -3.12 -X utf8 src/day2_db_copy.py facts     # nar_run_facts(全 NAR 場)
  py -3.12 -X utf8 src/day2_db_copy.py payouts   # nar_race_payouts(南関 4 場・2022-11〜。2022-01〜10 は db_payouts_confirm_2022)
  py -3.12 -X utf8 src/day2_db_copy.py report    # 上の 4 つの結果を out/day2_db_copy.md にまとめる

- 確認用 = 2022-01-01〜2025-08-31、封印用 = 2025-09-01〜2026-08-31。別ファイル。
- 場の一覧 = RAW の 2021 以降に出る NAR 14 場。場で絞らない件数(count=exact・limit=0)と合計が合うかも確かめる。
- 1 回の要求 = 1 表 × 1 場 × 1 か月、1,000 行ずつ offset で送る。並びは主キー順。保存前にも主キー順に並べる。
- 出力 = C:/Users/kouki/nankan_ai/v3/db_{runs,races,facts,payouts}_{confirm,sealed}_*.parquet と v3/day2_copy_{表}.json(件数と sha256)
"""
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
RAW = Path(__import__('os').environ.get('V3_RAW', 'C:/Users/kouki/nankan_ai/raw')) / 'archive'
REPO = Path(__file__).resolve().parent.parent
B = 'https://qgsnsdjvzzeazbazjlwa.supabase.co/rest/v1/'
KEY = 'sb_publishable_dLgCkz1_yt_e9YhAJRAyhQ_oAqAUU1a'
NANKAN = ['浦和', '船橋', '大井', '川崎']
PARTS = {'confirm': ('2022-01', '2025-08'), 'sealed': ('2025-09', '2026-08')}
SPEC = {'runs': ('nar_runs', ['track', 'race_date', 'race_no', 'runner_number']),
        'races': ('nar_races', ['track', 'race_date', 'race_no']),
        'facts': ('nar_run_facts', ['track', 'race_date', 'race_no', 'umaban']),
        'payouts': ('nar_race_payouts', ['track', 'race_date', 'race_no'])}


def req(table, q, count=False):
    url = B + table + '?' + urllib.parse.urlencode(q)
    h = {'apikey': KEY, **({'Prefer': 'count=exact'} if count else {})}
    for k in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=90) as r:
                time.sleep(0.3)
                if count:
                    return int(r.headers['Content-Range'].split('/')[-1])
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            print('retry', table, type(e).__name__, flush=True)
            time.sleep(5 * (k + 1))
    raise SystemExit(f'失敗 {table}')


def sha(fp):
    return hashlib.sha256(fp.read_bytes()).hexdigest()


def tracks():
    r = pd.read_csv(RAW / 'nar_races_archive.csv.gz', usecols=['track', 'race_date'], dtype={'race_date': str})
    return sorted(r[r.race_date >= '2021-01-01'].track.unique())


def copy(kind):
    table, key = SPEC[kind]
    trs = NANKAN if kind == 'payouts' else tracks()
    res = {}
    for part, (a, b) in PARTS.items():
        a = '2022-11' if (kind == 'payouts' and part == 'confirm') else a
        rows, n_all = [], 0
        for m in pd.period_range(a, b, freq='M'):
            lo, hi = m.start_time.strftime('%Y-%m-%d'), (m + 1).start_time.strftime('%Y-%m-%d')
            if kind != 'payouts':
                n_all += req(table, [('select', 'race_date'), ('race_date', f'gte.{lo}'), ('race_date', f'lt.{hi}'),
                                     ('limit', '0')], count=True)
            for t in trs:
                off = 0
                while True:
                    got = req(table, [('select', '*'), ('track', f'eq.{t}'), ('race_date', f'gte.{lo}'),
                                      ('race_date', f'lt.{hi}'), ('order', ','.join(key)),
                                      ('limit', '1000'), ('offset', str(off))])
                    rows += got
                    if len(got) < 1000:
                        break
                    off += 1000
            print(kind, part, m, 'done', flush=True)
        df = pd.DataFrame(rows)
        for c in df.columns:
            if df[c].map(lambda v: isinstance(v, (dict, list))).any():
                df[c] = df[c].map(lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True) if v is not None else None)
        df = df.sort_values(key, kind='mergesort').reset_index(drop=True)
        assert not df.duplicated(key).any(), (kind, part, 'key dup')
        name = f'db_{kind}_{part}_{a}_{b}.parquet'
        df.to_parquet(V3 / name, index=False)
        nk = int((df.track.isin(NANKAN)).sum())
        res[part] = {'file': name, 'rows': len(df), 'races': int(df[['track', 'race_date', 'race_no']].drop_duplicates().shape[0]),
                     'rows_nankan': nk, 'tracks': len(trs), 'db_rows_all_tracks': n_all if kind != 'payouts' else None,
                     'sha256': sha(V3 / name)}
        print(kind, part, 'rows', len(df), flush=True)
    (V3 / f'day2_copy_{kind}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')


def report():
    L = ['# 2 日目: 確認・封印の DB の写し(PREREG2 §7-2)', '',
         '値は受け取った台本の中だけで保存し、表示していない。出すのは行数・レース数・sha256 だけ。', '',
         '| ファイル | 行 | レース | うち南関の行 | DB の全場の行(場で絞らない) | sha256 |', '|---|---|---|---|---|---|']
    for kind in SPEC:
        fp = V3 / f'day2_copy_{kind}.json'
        if not fp.exists():
            L.append(f'| ({kind} 未) | | | | | |')
            continue
        for part, r in json.loads(fp.read_text(encoding='utf-8')).items():
            dbn = '―' if r['db_rows_all_tracks'] is None else f"{r['db_rows_all_tracks']:,}"
            L.append(f"| {r['file']} | {r['rows']:,} | {r['races']:,} | {r['rows_nankan']:,} | {dbn} | {r['sha256']} |")
    (REPO / 'out/day2_db_copy.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    report() if sys.argv[1] == 'report' else copy(sys.argv[1])
