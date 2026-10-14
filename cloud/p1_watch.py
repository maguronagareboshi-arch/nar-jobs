# -*- coding: utf-8 -*-
"""勝つ率の見張り(決め 30・2026-10-14): その日の AI の行(nar_ai_marks・model v3-9 / v3n-1)で勝つ率と 3着内の食い違いを数える。

  python3 cloud/p1_watch.py [日付(既定 = JST の今日)]

赤(exit 1)にするもの:
  1. p1 > p3 + 0.0001 の馬が 1 頭でも
  2. R の p1 の合計が 0.995〜1.005 の外
  3. 勝つ率の直し(決め 29)の印 meta.p1f の無い行: 南関 v3-9(朝・直前)・他場 v3n-1 の朝・他場の直前は朝に p1f がある R だけ
読むだけ(REST の GET)。⛔標準ライブラリだけ。環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))


def get(path):
    url = os.environ['SUPABASE_URL'].rstrip('/') + path
    key = os.environ['SUPABASE_SERVICE_KEY']
    req = urllib.request.Request(url, headers={'apikey': key, 'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(JST).strftime('%Y-%m-%d')
    if day < '2026-10-15':  # 決め 29 の直しは 10/15 の行から(それより前の行は直す前 = 見ない)
        print(f'[p1_watch] {day} は直す前の日 = 見ない', flush=True)
        return 0
    rows = get('/rest/v1/nar_ai_marks?select=model,timing,track,race_no,meta'
               f'&race_date=eq.{day}&model=in.(v3-9,v3n-1)&limit=2000')
    bad, n = [], 0
    mo_p1f = {(r['track'], r['race_no']) for r in rows if r['model'] == 'v3n-1' and r['timing'] == 'morning' and (r['meta'] or {}).get('p1f')}
    for r in rows:
        m = r['meta'] or {}
        run = m.get('runners') or []
        if not run:
            continue
        n += 1
        tag = f"{r['model']} {r['timing']} {r['track']}{r['race_no']}R"
        p1 = [float(x['p1']) for x in run if x.get('p1') is not None]
        over = [x['num'] for x in run if x.get('p1') is not None and x.get('p3') is not None and float(x['p1']) > float(x['p3']) + 1e-4]
        if over:
            bad.append(f'{tag}: p1 > p3 の馬 {over}')
        if p1 and not 0.995 <= sum(p1) <= 1.005:
            bad.append(f'{tag}: p1 の合計 {sum(p1):.4f}')
        need = day >= '2026-10-15' and (r['model'] == 'v3-9' or r['timing'] == 'morning' or (r['track'], r['race_no']) in mo_p1f)
        if need and not m.get('p1f'):
            bad.append(f'{tag}: 勝つ率の直しの印 p1f が無い')
    print(f'[p1_watch] {day} 行 {n}・食い違い {len(bad)}', flush=True)
    for b in bad[:50]:
        print('  ' + b, flush=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
