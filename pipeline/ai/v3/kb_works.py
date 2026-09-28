# -*- coding: utf-8 -*-
"""第 8 版の追い切り「毎日の分」を本番 nar_kb_works(REST・読むだけ)から作る読み口。

手元の t8_forecast.works() は 他場/data/json/cyokyo/{race_id}.json を backfill_cyokyo.flatten_race で平らにする。
nar_kb_works の 1 行 = 1 頭(他場/scraper/supabase_push.push_race が書く形):
  track(大井 など)・race_date・race_no・race_id(競馬ブック 16 桁)・umaban・horse_name・tanpyo・arrow・works(JSON の works そのまま)
→ race_id ごとに {race_id, race_date, horses: [{umaban, horse_name, tanpyo, arrow, works}]} に戻し、同じ flatten_race に通す。
  それ以外(CSV の読み・CSV にある race_id を飛ばす・prep_works・info)は t8_forecast.works() と同じ。

鍵(SUPABASE_URL・SUPABASE_SERVICE_KEY)が無いとき・V3_WORKS_SRC=json のときは install しない = 従来の JSON の道。
⛔読むだけ(GET)。書かない。鍵は印字しない。
"""
import json
import os
import urllib.parse
import urllib.request

import pandas as pd

TABLE = 'nar_kb_works'
TRACKS = ['大井', '川崎', '船橋', '浦和']
COLS = 'race_id,track,race_date,race_no,umaban,horse_name,tanpyo,arrow,works'
FROM = os.environ.get('V3_KB_FROM', '2025-09-01')  # これより前は CSV(固定ファイル)にある前提
PAGE = 1000


def creds():
    base = os.environ.get('SUPABASE_URL') or os.environ.get('NAR_SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('NAR_SUPABASE_SERVICE_KEY')
    return (base.rstrip('/'), key) if base and key else (None, None)


def enabled():
    return os.environ.get('V3_WORKS_SRC', 'kb') != 'json' and creds()[0] is not None


def fetch_rows(lo=FROM, hi=None):
    base, key = creds()
    rows, off = [], 0
    q = [('select', COLS), ('track', 'in.(' + ','.join(TRACKS) + ')'), ('race_date', f'gte.{lo}')]
    if hi:
        q.append(('race_date', f'lte.{hi}'))
    q.append(('order', 'race_id,umaban'))
    while True:
        url = f'{base}/rest/v1/{TABLE}?' + urllib.parse.urlencode(q + [('limit', str(PAGE)), ('offset', str(off))])
        req = urllib.request.Request(url, headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai-v3'})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read().decode('utf-8'))
        rows += got
        if len(got) < PAGE:
            return rows
        off += PAGE


def rows_to_parsed(rows):
    """nar_kb_works の行 → race_id ごとの parse_cyokyo の形(flatten_race が読む鍵だけ)。race_id の順。"""
    R = {}
    for r in rows:
        rid = str(r.get('race_id') or '')
        p = R.setdefault(rid, {'race_id': rid, 'race_date': r.get('race_date'), 'horses': []})
        w = r.get('works')
        if isinstance(w, str):
            w = json.loads(w)
        p['horses'].append({'umaban': r.get('umaban'), 'horse_name': r.get('horse_name'), 'horse_id': None,
                            'arrow': r.get('arrow'), 'tanpyo': r.get('tanpyo'), 'works': w or []})
    return [R[k] for k in sorted(R)]


def make_works(t8, parsed_list):
    """t8_forecast.works() と同じ手順で、JSON のかわりに parsed_list(race_id の順)を使う。"""
    cy, bc = t8.cy, t8.bc
    P = []
    for t in cy.TRACKS:
        for y in cy.YEARS:
            f = cy.SRC / f'cyokyo_{t}_{y}.csv'
            if f.exists():
                P.append(pd.read_csv(f, encoding='utf-8-sig', usecols=cy.USE, dtype=str)[cy.USE])
    C = pd.concat(P, ignore_index=True)
    have = set(C.race_id.dropna().astype(str))
    rows, nj = [], 0
    for parsed in parsed_list:
        rid = parsed['race_id']
        t = t8.TRK.get(rid[6:8])
        if t is None or rid in have:
            continue
        rows += bc.flatten_race(parsed, t, source='kb')
        nj += 1
    J = pd.DataFrame(rows, columns=bc.COLUMNS)[cy.USE] if rows else pd.DataFrame(columns=cy.USE)
    J = J.apply(lambda s: s.map(t8._s)).astype(object)
    W = cy.prep_works(pd.concat([C, J], ignore_index=True))
    info = {'csv_rows': len(C), 'json_races': nj, 'json_rows': len(J),
            'json_rows_kept': int((W.source == 'kb').sum()), 'json_last': str(J.race_date.max()) if len(J) else None,
            'daily_src': 'nar_kb_works'}
    return W, info


def install(t8, hi=None):
    """t8_forecast.works を nar_kb_works 版に差し替える(table() は works() を名前で呼ぶので差し替えが効く)。"""
    def works():
        if 'W' in t8._W:
            return t8._W['W'], t8._W['info']
        W, info = make_works(t8, rows_to_parsed(fetch_rows(hi=hi)))
        t8._W.update(W=W, info=info)
        return W, info
    t8.works = works
