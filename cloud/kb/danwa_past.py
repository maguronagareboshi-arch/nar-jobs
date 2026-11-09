# -*- coding: utf-8 -*-
"""厩舎の話(nar_kb_danwa)の過去分の取り直し(2026-11-09)。調教は取らない。

  python cloud/kb/danwa_past.py --track 川崎 --from 2023-01-01 --to 2026-08-17 [--push] [--max-days 1] [--oldest-first]

- 日程は既存の nar_races(その場の 1R がある日)から。
- 済み= nar_kb_danwa にその日の 1R の行がある日。再実行で飛ばす(途中で落ちても続きから)。
- 既定は新しい月から古い月へ。月の開催日が全部「データなし」の月が 2 か月続いたら、そこで止める(掲載終了)。
- --budget-min を超えたら、その日を終えたところで止める(Actions の時間切れの手前)。
- 本番 DB は upsert だけ(supabase_push.push_race)。間隔は fetch.make_client の FETCH_WAIT_SECONDS(既定 2.5 秒)。
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fetch  # noqa: E402
import supabase_push  # noqa: E402
from nar_push import creds  # noqa: E402


def _get_dates(table, track, d0, d1, extra):
    base, key = creds()
    if not base:
        raise SystemExit('本体の鍵(SUPABASE_URL / SUPABASE_SERVICE_KEY)が無い')
    out, off = [], 0
    while True:
        q = [('select', 'race_date'), ('track', 'eq.' + track), ('race_date', 'gte.' + d0),
             ('race_date', 'lte.' + d1), ('race_no', 'eq.1')] + extra + [('order', 'race_date.asc')]
        url = f"{base}/rest/v1/{table}?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
        req = urllib.request.Request(url, headers={'apikey': key, 'Authorization': 'Bearer ' + key,
                                                   'Range': f'{off}-{off + 999}'})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read().decode('utf-8'))
        out += [x['race_date'] for x in rows]
        if len(rows) < 1000:
            break
        off += 1000
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--track', required=True)
    ap.add_argument('--from', dest='d0', required=True)
    ap.add_argument('--to', dest='d1', required=True)
    ap.add_argument('--push', action='store_true')
    ap.add_argument('--max-days', type=int, default=0)
    ap.add_argument('--oldest-first', action='store_true')
    ap.add_argument('--budget-min', type=float, default=330)
    a = ap.parse_args()
    t0 = time.time()

    days = _get_dates('nar_races', a.track, a.d0, a.d1, [])
    done = set(_get_dates('nar_kb_danwa', a.track, a.d0, a.d1, [('umaban', 'eq.1')]))
    todo = [d for d in days if d not in done]
    print(f'{a.track} {a.d0}〜{a.d1}: 開催日 {len(days)}・済み {len(days) - len(todo)}・残り {len(todo)}', flush=True)

    months = OrderedDict()
    for d in (todo if a.oldest_first else list(reversed(todo))):
        months.setdefault(d[:7], []).append(d)

    args = argparse.Namespace(no_login=False, refresh=False, push=a.push, what=['danwa'], track=a.track)
    client, logged_in = fetch.make_client(args)
    n_days, empty_run, summary = 0, 0, []
    stop = ''
    for m, ds in months.items():
        before_m = supabase_push.COUNT['nar_kb_danwa']
        got_m = 0
        for d in ds:
            if a.max_days and n_days >= a.max_days:
                stop = f'--max-days {a.max_days} に達した'
                break
            if (time.time() - t0) / 60 > a.budget_min:
                stop = f'時間の枠 {a.budget_min} 分に達した(再実行で続きから)'
                break
            c0 = supabase_push.COUNT['nar_kb_danwa']
            fetch.cmd_day(client, d.replace('-', ''), args, logged_in=logged_in)
            got = supabase_push.COUNT['nar_kb_danwa'] - c0
            got_m += got
            n_days += 1
            print(f'DAY {a.track} {d} 行 {got}', flush=True)
        rows_m = supabase_push.COUNT['nar_kb_danwa'] - before_m
        summary.append((m, rows_m))
        print(f'MONTH {a.track} {m} 行 {rows_m}', flush=True)
        if stop:
            break
        empty_run = empty_run + 1 if got_m == 0 else 0
        if a.push and empty_run >= 2:
            stop = f'{m} まで 2 か月続けて 0 行= 掲載終了とみて止める'
            break
    print('SUMMARY ' + json.dumps({'track': a.track, 'days': n_days, 'rows': supabase_push.COUNT['nar_kb_danwa'],
                                   'months': summary, 'stop': stop,
                                   'min': round((time.time() - t0) / 60, 1)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
