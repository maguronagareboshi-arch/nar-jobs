# -*- coding: utf-8 -*-
"""「南関 展開シミュレーター」のその日のデータ(ページの DATA)を、本番に既にある物だけから作る(2026-11-17)。

11/16 の DATA の元を突き止めた結果(全頭の値が一致):
  勝つ率 p1・3 着内率 p3 = 本番の印の表 nar_ai_marks(model v3-9)の meta.runners(前日版 = timing morning)
  位置の予想 r1・r4・最初の角の名前・距離 = 展開図の公開ファイル cond-stats/tenkai/v1/<日>/<場>-<R>.json(前日の便 tenkai_live.py)
  レース名・発走時刻 = nar_races / 馬名・枠・騎手の短い名前 = 出走馬の読み口 runs_race
⛔オッズ・人気は読まない。予想の印・率は変えない(見せ方だけ)。DB の表は読むだけ。外のサイトは読まない。

絵のコースは大井だけ(外回り・内回り・1400m のポケット・右回り)。
  その日の南関が大井でない → 作らない(戻り None・理由を出す)。大井の 1650m(左回り)は絵が無いのでその R だけ抜く。

  python -X utf8 tenkai_sim_live.py <日> [--timing morning|last] [--write] [--out DIR]
    --write なし = 手元の DIR(既定 out_tksim)に書くだけ。--write = 公開バケット cond-stats/tenkai/sim/v1/<日>/<場の英字>.json へ置く。
    便に入れる版は勝負服を載せない(公式サイトの図の扱いが決まるまで・ページは仮の柄で描く)。
環境変数: SUPABASE_URL・SUPABASE_SERVICE_KEY(読むだけなら公開の鍵 SUPABASE_ANON_KEY でも良い)
"""
import argparse
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

JST = dt.timezone(dt.timedelta(hours=9))
V = 1
MODEL = 'v3-9'
BUCKET = 'cond-stats'
TK_ROOT = 'tenkai/v1/'
SIM_ROOT = 'tenkai/sim/v1/'
CACHE = 'public, max-age=1800'
PREFIX = {'浦和': 'urawa', '船橋': 'funabashi', '大井': 'ooi', '川崎': 'kawasaki'}
NK = ['大井', '川崎', '船橋', '浦和']
DRAWN = {'大井'}            # 絵のコースがある場
NO_DIST = {'大井': {1650}}  # 絵が無い距離(大井の 1650m は左回り)
CHECKED = {'大井': {1200, 1400, 1600, 1800, 2400}}  # 絵を自分で見て確かめた距離(他は同じ式で描くが未確認)
UA = 'nar-jobs tenkai_sim_live'


def _log(*a):
    print('[tksim]', *a, flush=True)


def _env():
    base = os.environ['SUPABASE_URL'].rstrip('/')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ['SUPABASE_ANON_KEY']
    return base, key


def _req(path, method='GET', body=None, headers=None, timeout=60, auth=True):
    base, key = _env()
    h = {'User-Agent': UA}
    if auth:
        h.update({'apikey': key, 'Authorization': 'Bearer ' + key})
    h.update(headers or {})
    for i in range(3):
        try:
            r = urllib.request.Request(base + path, method=method, data=body, headers=h)
            with urllib.request.urlopen(r, timeout=timeout) as x:
                return x.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404) and method == 'GET' and not auth:
                return None                      # 公開ファイルが無い
            if e.code < 500 or i == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == 2:
                raise
        time.sleep(3 * (i + 1))


def _q(s):
    return urllib.parse.quote(str(s))


def rest(query):
    return json.loads(_req('/rest/v1/' + query, headers={'Accept': 'application/json'}))


def rpc(name, args, query=''):
    return json.loads(_req(f'/rest/v1/rpc/{name}' + ('?' + query if query else ''), 'POST', json.dumps(args).encode('utf-8'),
                           {'Content-Type': 'application/json', 'Accept': 'application/json'}))


def tracks_of(day):
    """その日の南関の場 → [場]。"""
    rows = rest(f"nar_races?select=track&track=in.({','.join(_q(t) for t in NK)})&race_date=eq.{day}&race_no=eq.1")
    return sorted({r['track'] for r in rows}, key=NK.index)


def build(day, timing='morning', track=None):
    """→ (DATA または None, 数え)。None のときは 数え['why'] に理由。"""
    info = {'day': day, 'tracks': tracks_of(day), 'skip': [], 'unchecked': []}
    if not info['tracks']:
        info['why'] = '南関の開催が無い(またはレースの表がまだ無い)'
        return None, info
    track = track or next((t for t in info['tracks'] if t in DRAWN), info['tracks'][0])
    info['track'] = track
    if track not in DRAWN:
        info['why'] = f'{track} は絵のコースがまだ無い(作ってあるのは {"・".join(sorted(DRAWN))} だけ)'
        return None, info
    t = _q(track)
    races = rest(f'nar_races?select=race_no,post_time,race_name,distance_m,cancelled&track=eq.{t}&race_date=eq.{day}&order=race_no.asc')
    marks = rest(f'nar_ai_marks?select=race_no,timing,runners:meta->runners&model=eq.{_q(MODEL)}&track=eq.{t}&race_date=eq.{day}')
    by = {}
    for m in marks:
        by.setdefault(int(m['race_no']), {})[m['timing']] = m.get('runners') or []
    out = []
    for rc in races:
        no = int(rc['race_no'])
        dist = int(rc['distance_m'] or 0)
        if rc.get('cancelled'):
            info['skip'].append((no, '取りやめ'))
            continue
        if dist in NO_DIST.get(track, ()):
            info['skip'].append((no, f'{dist}m は絵が無い'))
            continue
        tm = timing if timing in by.get(no, {}) else ('morning' if 'morning' in by.get(no, {}) else None)
        if tm is None:
            info['skip'].append((no, '予想の行がまだ無い'))
            continue
        raw = _req(f'/storage/v1/object/public/{BUCKET}/{TK_ROOT}{day}/{PREFIX[track]}-{no}.json', auth=False)
        tk = json.loads(raw) if raw else None
        if not tk or tk.get('v') != 1:
            info['skip'].append((no, '位置の予想のファイルがまだ無い'))
            continue
        pos = {int(h['num']): h for h in tk['horses']}
        rate = {int(x['num']): x for x in by[no][tm] if x.get('p1') is not None and x.get('p3') is not None}
        runs = rpc('runs_race', {'p_track': track, 'p_date': day, 'p_no': no}, 'select=runner_number,gate,horse_name,jockey&order=runner_number.asc')
        hs = []
        for r in runs:
            u = int(r['runner_number'])
            if u not in pos or u not in rate or not r.get('horse_name'):
                continue                         # 取消・除外(率か位置が無い馬)は走らせない
            h = {'u': u, 'g': int(r['gate'] or pos[u].get('gate') or 0), 'nm': r['horse_name'],
                 'p1': round(float(rate[u]['p1']), 4), 'p3': round(float(rate[u]['p3']), 4),
                 'r1': round(float(pos[u]['r1']), 4), 'r4': round(float(pos[u]['r4']), 4)}
            if r.get('jockey'):
                h['jk'] = r['jockey']
            hs.append(h)
        if len(hs) < 3:
            info['skip'].append((no, f'そろった馬が {len(hs)} 頭'))
            continue
        if dist not in CHECKED.get(track, ()):
            info['unchecked'].append((no, dist))
        out.append({'no': no, 'name': rc.get('race_name') or '', 'dist': dist or int(tk.get('distance_m') or 0), 'post': rc.get('post_time') or '',
                    'c1': tk.get('c1name') or '最初の角', 'timing': tm, 'h': hs})
    if not out:
        info['why'] = f'{track} の予想と位置の予想がまだそろっていない(前日の便の後に回す)'
        return None, info
    info['n_race'], info['n_horse'] = len(out), sum(len(r['h']) for r in out)
    return {'date': day, 'track': track, 'races': out}, info


def path_of(day, track):
    return f'{SIM_ROOT}{day}/{PREFIX[track]}.json'


def upload(path, data):
    _req(f'/storage/v1/object/{BUCKET}/{path}', 'POST', data,
         {'Content-Type': 'application/json; charset=utf-8', 'x-upsert': 'true', 'Cache-Control': CACHE})


def run(day, write=False, out_dir='out_tksim', timing='morning'):
    """入口(便から呼ぶ)。戻り = 置いた R の数(作らない日は 0)。"""
    t0 = time.time()
    data, info = build(day, timing)
    if data is None:
        _log(day, 'ページを作らない:', info['why'])
        return 0
    doc = {'v': V, 'computed_at': dt.datetime.now(JST).isoformat(timespec='seconds'), **data}
    body = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    p = path_of(day, data['track'])
    if write:
        upload(p, body)
    else:
        f = Path(out_dir) / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
    _log(day, data['track'], '置いた', info['n_race'], 'R', info['n_horse'], '頭', len(body), 'バイト', 'バケット' if write else out_dir,
         '・抜いた R', info['skip'], '・絵が未確認の距離', info['unchecked'], f'{time.time() - t0:.0f}s')
    return info['n_race']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('day')
    ap.add_argument('--timing', default='morning', choices=['morning', 'last'])
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--out', default='out_tksim')
    a = ap.parse_args()
    run(a.day, a.write, a.out, a.timing)


if __name__ == '__main__':
    main()
