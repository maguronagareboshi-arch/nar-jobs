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
KEY = os.environ.get('SUPABASE_SERVICE_KEY', '') or os.environ.get('SUPABASE_ANON_KEY', '')   # 段3(10/19): nar_runs は管理用の鍵で
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
# 2026-10-31 通信量: 便が毎回 2014〜を丸ごと読んでいた(1 回 約 1 GB × 1 日 5 回 = API の約 4 割)。
# K0_CACHE(便のキャッシュの置き場)があれば、前回の表を控えに使い、直近 DIFF_DAYS 日を含む月からだけ読み直す。
# 控えが FULL_DAYS 日より古い・列が違う・無いときは丸ごと読む(古い月の後からの直しは最長 FULL_DAYS 日で入る)。K0_CACHE が無ければ今まで通り。
CACHE = os.environ.get('K0_CACHE', '')
DIFF_DAYS, FULL_DAYS = 92, 7


def _meta():
    try:
        return json.loads((Path(CACHE) / 'meta.json').read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return {}


def _base(table, sel):
    """(控えの表, 読み直す始めの日) か (None, None)= 丸ごと"""
    if not CACHE:
        return None, None
    m, f = _meta().get(table, {}), Path(CACHE) / f'{table}.parquet'
    today = dt.date.today()
    if not f.exists() or m.get('sel') != sel or not m.get('full') or (today - dt.date.fromisoformat(m['full'])).days >= FULL_DAYS:
        print(table, '控え 無し/古い → 丸ごと', m.get('full'), flush=True)
        return None, None
    since = (today - dt.timedelta(days=DIFF_DAYS)).replace(day=1).isoformat()
    base = pd.read_parquet(f)
    print(table, '控え', len(base), '行(丸ごと', m['full'], ')+', since, '〜を読み直す', flush=True)
    return base, since


def _merge(old, new, sort):
    df = pd.concat([old, new], ignore_index=True) if len(new) else old.reset_index(drop=True)
    key = pd.DataFrame(dict(enumerate(sort(df))))
    return df.iloc[key.sort_values(list(key.columns), kind='mergesort').index].reset_index(drop=True)


def _keep(table, sel, df, full):
    if CACHE:
        Path(CACHE).mkdir(parents=True, exist_ok=True)
        df.to_parquet(Path(CACHE) / f'{table}.parquet', index=False)
        m = _meta()
        m[table] = {'sel': sel, 'full': dt.date.today().isoformat() if full else m.get(table, {}).get('full')}
        (Path(CACHE) / 'meta.json').write_text(json.dumps(m, ensure_ascii=False), encoding='utf-8')
    return df


def months():
    m = pd.period_range('2014-01', (dt.date.today() + dt.timedelta(days=40)).strftime('%Y-%m'), freq='M')
    return [(str(p.start_time.date()), str(p.end_time.date())) for p in m]
def by_track_month(table, sel, order):
    base, since = _base(table, sel)
    jobs = [(t, a, b) for t in TR for a, b in months() if base is None or a >= since]
    def one(j):
        t, a, b = j
        return pages(f'/rest/v1/{table}?select={sel}&track=eq.{q(t)}&race_date=gte.{a}&race_date=lte.{b}&order={order}')
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(6) as ex:
        for i, r in enumerate(ex.map(one, jobs)):
            rows += r
            if i % 300 == 0: print(table, i, len(jobs), len(rows), round(time.time() - t0), flush=True)
    df = pd.DataFrame(rows)
    if base is not None:   # 古い月は控えのまま・新しい月だけ差し替える。並びは丸ごとと同じ(場の順 → 月 → 月の中は読んだ順)
        df = _merge(base[base.race_date < since], df, sort=lambda d: [d.track.map(TR.index), d.race_date.str[:7]])
    return _keep(table, sel, df, base is None)
def whole(table, order, by_date=False):
    base, since = _base(table, '*') if by_date else (None, None)
    flt = f'&race_date=gte.{since}' if base is not None else ''
    rows, off, t0 = [], 0, time.time()
    def one(o): return sb.get(f'/rest/v1/{table}?select=*{flt}&order={order}&limit=1000&offset={o}')
    while True:
        with ThreadPoolExecutor(6) as ex:
            rs = list(ex.map(one, range(off, off + 6000, 1000)))
        for r in rs: rows += r
        off += 6000
        if any(len(r) < 1000 for r in rs): break
    print(table, len(rows), round(time.time() - t0), flush=True)
    df = pd.DataFrame(rows)
    if not by_date:
        return df
    if base is not None:   # 丸ごとの並び = order の列の順(一意)
        df = _merge(base[base.race_date < since], df, sort=lambda d: [d[c] for c in order.split(',')])
    return _keep(table, '*', df, base is None)
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
        whole('nar_jra_runs', 'kb_horse_id,race_date,race_no', by_date=True).to_parquet(D + 'jra.parquet', index=False)
    if 'jrah' in what:
        whole('nar_jra_horses', 'kb_horse_id').to_parquet(D + 'jrah.parquet', index=False)
    print('done')


if __name__ == '__main__':
    main(sys.argv[1:])
