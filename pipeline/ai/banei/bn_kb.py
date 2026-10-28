# -*- coding: utf-8 -*-
"""ばんえい 第 3 版の競馬ブック(帯広・場 58)の成績の段(2026-10-28)。

  python -X utf8 pipeline/ai/banei/bn_kb.py fetch 2026-10-31 [--push]   # その日より前の開催日で、DB に無い日の成績を取る
  python -X utf8 pipeline/ai/banei/bn_kb.py table <置き場>              # 固めた表 + DB の nar_kb_banei → <置き場>/banei_kb/kb_runs.parquet

取るのは成績の頁だけ(区間 3 つ = 前半・障害・後半タイム・通過順 3 つ・発走時刻)。読み方は v3 の src/banei/kb_banei_parse.py と同じ。
⛔書くのは nar_kb_banei(race_date, race_no, umaban が鍵)の REST upsert だけ。取れなかった日は書かない(後の便が取り直す)。
⛔その日の R が 1 つでも欠けた・区間の欄が無い日は書かない = 第 3 版はその日の「前の開催日の競馬ブックが無い」で止まる。
ログイン = 環境変数 KEIBABOOK_LOGIN_ID・KEIBABOOK_PASSWORD(cloud/kb/fetch.make_client)。間隔は FETCH_WAIT_SECONDS(既定 2.5 秒)。
"""
import datetime as dt
import json
import os
import sys
import types
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
KB_DIR = Path(os.environ.get('KB_SCRAPER', str(HERE.parents[2] / 'cloud' / 'kb')))
TABLE = 'nar_kb_banei'
COLS = ['race_date', 'race_no', 'umaban', 'horse_name', 'finish', 'finish_note', 'time_sec', 'seg_front', 'seg_obst', 'seg_back',
        'pass1', 'pass2', 'pass3', 'hasso_time', 'kb_race_id']
NEED = ['race_date', 'race_no', 'umaban', 'finish', 'seg_front', 'seg_obst', 'seg_back', 'pass1', 'pass2', 'pass3', 'hasso_time']
SEG = {'前半ﾀｲﾑ': 'seg_front', '障害ﾀｲﾑ': 'seg_obst', '後半ﾀｲﾑ': 'seg_back'}
FROZEN_TO = os.environ.get('BANEI_KB_FROZEN_TO', '2026-10-26')   # 固めた表(リリース)の最後の日


def log(*a):
    print('[bn_kb]', *a, flush=True)


def creds():
    url = os.environ.get('SUPABASE_URL', 'https://qgsnsdjvzzeazbazjlwa.supabase.co').rstrip('/')
    key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    if not key:
        raise SystemExit('SUPABASE_SERVICE_KEY が無い')
    return url, key


def rest(path, body=None, prefer=None):
    url, key = creds()
    h = {'apikey': key, 'Authorization': 'Bearer ' + key}
    data = None
    if body is not None:
        h['Content-Type'] = 'application/json'
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    if prefer:
        h['Prefer'] = prefer
    req = urllib.request.Request(url + path, data=data, headers=h, method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(req, timeout=120) as r:
        t = r.read().decode('utf-8')
        return json.loads(t) if t else None


# ---------------------------------------------------------------- 読み(kb_banei_parse.py と同じ)
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parsers():
    sys.path.insert(0, str(KB_DIR))
    import parsers
    return parsers


def segs(soup, _text):
    """表の行ごとに 前半・障害・後半 を取る(データ行は騎手の前に減量の欄が 1 つ多い = parse_seiseki と同じ揃え方)"""
    t = soup.select_one('table.seiseki')
    if not t:
        return []
    hd = [_text(x) for x in t.find('tr').find_all(['th', 'td'])]
    jk = hd.index('騎手') if '騎手' in hd else None
    out = []
    for tr in t.find_all('tr'):
        c = [_text(td) for td in tr.find_all('td')]
        if len(c) < len(hd):
            continue
        if len(c) == len(hd) + 1 and jk is not None:
            c.pop(jk)
        out.append({v: _num(c[hd.index(k)]) for k, v in SEG.items() if k in hd})
    return out


def parse_one(html, rid):
    from bs4 import BeautifulSoup
    P = _parsers()
    p = P.parse_seiseki(html, rid)
    sg = segs(BeautifulSoup(html, 'lxml'), P._text)
    ok = len(sg) == len(p['results']) and len(sg) > 0
    rows = []
    for i, r in enumerate(p['results']):
        pp = r.get('passing_positions') or []
        rows.append({
            'kb_race_id': rid, 'race_date': p['race'].get('date'), 'race_no': p['race'].get('race_no'),
            'hasso_time': p['race'].get('hasso_time'), 'umaban': r['umaban'], 'horse_name': r['horse_name'],
            'finish': r['finish'], 'finish_note': r['finish_note'], 'time_sec': r['time_sec'],
            'pass1': pp[0] if len(pp) > 0 else None, 'pass2': pp[1] if len(pp) > 1 else None, 'pass3': pp[2] if len(pp) > 2 else None,
            **(sg[i] if ok else {}),
        })
    return rows, ok


# ---------------------------------------------------------------- 取る
def official_days(before, since):
    """公式の帯広の開催日(since 〜 before の前日)と R = nar_races から。取りやめ(cancelled)のレースは数えない(競馬ブックの頁が空)。"""
    t = urllib.parse.quote('帯広ば')
    rs = rest(f'/rest/v1/nar_races?select=race_date,race_no,cancelled&track=eq.{t}&race_date=gte.{since}&race_date=lt.{before}&limit=5000')
    d = {}
    for r in rs:
        if not str(r.get('cancelled') or '').strip():
            d.setdefault(str(r['race_date'])[:10], set()).add(int(r['race_no']))
    return d


def db_days(since):
    rs = rest(f'/rest/v1/{TABLE}?select=race_date,race_no&race_date=gte.{since}&limit=20000')
    d = {}
    for r in rs:
        d.setdefault(str(r['race_date'])[:10], set()).add(int(r['race_no']))
    return d


def fetch_day(client, day):
    """その日の帯広の成績を全 R 取る → (行, 欠けの説明)。欠けがあれば行は返すが書かない。"""
    P = _parsers()
    from keibabook import KeibabookClient as K
    h = client.get(K.nittei_path(day.replace('-', '')), cache=False)
    rids = []
    for m in P.parse_nittei(h):
        if '帯広' not in m['track']:
            continue
        rids += [r['race_id'] for r in m['races'] if f"{r['race_id'][0:4]}-{r['race_id'][12:14]}-{r['race_id'][14:16]}" == day]
    rids = sorted(set(rids))
    if not rids:
        return [], '日程に帯広のレースが無い'
    rows, bad = [], []
    for rid in rids:
        html = client.get(K.seiseki_path(rid), cache=False)
        r, ok = parse_one(html, rid)
        if not r:
            continue            # 頁が空 = 取りやめのレース(公式で取りやめでなければ、下の「公式にある R が無い」で止まる)
        if not ok:
            bad.append(rid[10:12] + 'R')
        rows += r
    return rows, ('区間の欄が無い ' + ' '.join(bad)) if bad else ''


def fetch(day, push):
    since = (dt.date.fromisoformat(FROZEN_TO) + dt.timedelta(days=1)).isoformat()
    want = official_days(day, since)
    have = db_days(since)
    todo = sorted(d for d, rs in want.items() if not rs <= have.get(d, set()))
    log('公式の開催日', len(want), '日・DB に無い日', todo)
    if not todo:
        return 0
    sys.path.insert(0, str(KB_DIR))
    from fetch import make_client
    client, li = make_client(types.SimpleNamespace(no_login=False))
    if not li:
        raise SystemExit('競馬ブックにログインできない')
    bad_days = 0
    for d in todo:
        try:
            rows, why = fetch_day(client, d)
        except Exception as e:  # noqa: BLE001
            rows, why = [], f'取得失敗 {type(e).__name__}: {str(e)[:120]}'
        got = {int(r['race_no']) for r in rows}
        if not why and not want[d] <= got:
            why = '公式にある R が無い ' + ' '.join(f'{x}R' for x in sorted(want[d] - got))
        if why:
            log('書かない', d, why); bad_days += 1
            continue
        out = [{c: (None if pd.isna(r.get(c)) else r.get(c)) for c in COLS} for r in rows]
        log(d, len(rows), '頭', len(got), 'R', '区間の空', sum(r['seg_obst'] is None for r in out))
        if push:
            rest(f'/rest/v1/{TABLE}?on_conflict=race_date,race_no,umaban', out, 'resolution=merge-duplicates,return=minimal')
            back = rest(f'/rest/v1/{TABLE}?select=race_no&race_date=eq.{d}&limit=500')
            log('書いた', d, len(back), '行(読み直し)')
    return bad_days


# ---------------------------------------------------------------- 表
def table(root):
    """固めた表(リリースの kb_runs_frozen.parquet)+ DB の nar_kb_banei(固めた日より後)→ <root>/banei_kb/kb_runs.parquet。"""
    root = Path(root)
    k = pd.read_parquet(root / 'banei_kb' / 'kb_runs_frozen.parquet')
    since = (dt.date.fromisoformat(FROZEN_TO) + dt.timedelta(days=1)).isoformat()
    try:
        rs, off = [], 0
        while True:
            r = rest(f'/rest/v1/{TABLE}?select={",".join(NEED)}&race_date=gte.{since}&order=race_date,race_no,umaban&limit=1000&offset={off}')
            rs += r
            if len(r) < 1000:
                break
            off += 1000
    except Exception as e:  # noqa: BLE001
        log('DB の nar_kb_banei が読めない', type(e).__name__, str(e)[:120]); rs = []
    n = pd.DataFrame(rs, columns=NEED)
    if len(n):
        n['race_date'] = n.race_date.astype(str).str[:10]
        for c in ['race_no', 'umaban']:
            n[c] = n[c].astype('int64')
        for c in ['finish', 'seg_front', 'seg_obst', 'seg_back', 'pass1', 'pass2', 'pass3']:
            n[c] = pd.to_numeric(n[c], errors='coerce').astype(float)
        k = pd.concat([k[NEED], n[NEED]], ignore_index=True)
    k.to_parquet(root / 'banei_kb' / 'kb_runs.parquet', index=False)
    log('競馬ブックの表', len(k), '行・最後の日', k.race_date.max(), '・DB から', len(n), '行')
    return k


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'fetch':
        sys.exit(1 if fetch(a[1], '--push' in a) else 0)
    elif a[0] == 'table':
        table(a[1])
