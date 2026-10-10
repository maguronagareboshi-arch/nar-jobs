# -*- coding: utf-8 -*-
"""高知版 0 = nar-official の公式の表を手元の parquet に落とす(読むだけ・公開の anon 鍵)。場 × 月ごとに 1000 行ずつ。
  py -3.12 -X utf8 src/kochi/k0_dl.py [出す先] [表…]  → runs・races・facts・profiles・jra・jrah(・ext)の parquet
  鍵 = 環境変数 SUPABASE_URL・SUPABASE_ANON_KEY か SUPABASE_SERVICE_KEY(無ければ src/f5_scripts/week_backfill.py の公開の鍵)。"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
D = 'C:/Users/kouki/nankan_ai/v3/official/'
URL = os.environ.get('SUPABASE_URL', 'https://qgsnsdjvzzeazbazjlwa.supabase.co').rstrip('/')
KEY = os.environ.get('SUPABASE_ANON_KEY', '') or os.environ.get('SUPABASE_SERVICE_KEY', '')
if not KEY:
    _t = (Path(__file__).resolve().parents[1] / 'f5_scripts' / 'week_backfill.py').read_text(encoding='utf-8')
    KEY = ''.join(re.findall(r"'([^']*)'", _t.split('KEY = (')[1].split(')')[0]))


class sb:
    @staticmethod
    def get(path, tries=4):
        for i in range(tries):
            try:
                req = urllib.request.Request(URL + path, headers={'apikey': KEY, 'Authorization': 'Bearer ' + KEY})
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read().decode('utf-8'))
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(3 * (i + 1))
TR = ['園田', '帯広ば', '大井', '名古屋', '高知', '佐賀', '門別', '金沢', '笠松', '川崎', '船橋', '浦和', '盛岡', '水沢', '姫路']
q = urllib.parse.quote
def pages(path):
    out, off = [], 0
    while True:
        r = sb.get(f'{path}&limit=1000&offset={off}')
        out += r
        if len(r) < 1000: return out
        off += 1000
def months():
    m = pd.period_range('2014-01', (dt.date.today() + dt.timedelta(days=40)).strftime('%Y-%m'), freq='M')
    return [(str(p.start_time.date()), str(p.end_time.date())) for p in m]
def by_track_month(table, sel, order):
    jobs = [(t, a, b) for t in TR for a, b in months()]
    def one(j):
        t, a, b = j
        return pages(f'/rest/v1/{table}?select={sel}&track=eq.{q(t)}&race_date=gte.{a}&race_date=lte.{b}&order={order}')
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(6) as ex:
        for i, r in enumerate(ex.map(one, jobs)):
            rows += r
            if i % 300 == 0: print(table, i, len(jobs), len(rows), round(time.time() - t0), flush=True)
    return pd.DataFrame(rows)
def whole(table, order):
    rows, off, t0 = [], 0, time.time()
    def one(o): return sb.get(f'/rest/v1/{table}?select=*&order={order}&limit=1000&offset={o}')
    while True:
        with ThreadPoolExecutor(6) as ex:
            rs = list(ex.map(one, range(off, off + 6000, 1000)))
        for r in rs: rows += r
        off += 6000
        if any(len(r) < 1000 for r in rs): break
    print(table, len(rows), round(time.time() - t0), flush=True)
    return pd.DataFrame(rows)
def main(argv):
    global D
    if argv and ('/' in argv[0] or chr(92) in argv[0]):
        D = argv[0].rstrip('/') + '/'
        argv = argv[1:]
    Path(D).mkdir(parents=True, exist_ok=True)
    what = argv or ['races', 'runs', 'facts', 'profiles', 'jra', 'jrah']
    if 'races' in what:
        by_track_month('nar_races', 'track,race_date,race_no,race_name,race_kind,surface,direction,distance_m,weather,going,field_size,condition,prize_yen,race_last3f,corners,cancelled',
                       'race_no').to_parquet(D + 'races.parquet', index=False)
    if 'runs' in what:
        by_track_month('nar_runs', 'track,race_date,race_no,runner_number,gate,horse_name,birth_date,sex,age,jockey,trainer,trainer_area,carried_weight,weight_mark,body_weight,finish,finish_note,time_sec,margin,last3f,popularity',
                       'race_no,runner_number').to_parquet(D + 'runs.parquet', index=False)
    if 'facts' in what:
        by_track_month('nar_run_facts', 'track,race_date,race_no,umaban,horse_key,c1,n1,c4,n4,first3f,win_odds_close',
                       'race_no,umaban').to_parquet(D + 'facts.parquet', index=False)
    if 'profiles' in what:
        whole('nar_horse_profiles', 'horse_name,birth_date').to_parquet(D + 'profiles.parquet', index=False)
    if 'ext' in what:
        whole('nar_horse_ext_ids', 'source,ext_id').to_parquet(D + 'ext.parquet', index=False)
    if 'jra' in what:
        whole('nar_jra_runs', 'kb_horse_id,race_date,race_no').to_parquet(D + 'jra.parquet', index=False)
    if 'jrah' in what:
        whole('nar_jra_horses', 'kb_horse_id').to_parquet(D + 'jrah.parquet', index=False)
    print('done')


if __name__ == '__main__':
    main(sys.argv[1:])
