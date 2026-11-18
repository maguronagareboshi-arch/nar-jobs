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
    TKSIM_SILKS=1 で騎手の本物の勝負服も載せる(tenkai_silks_db.py・2026-11-17 ユーザー「許可はもらっています」)。
      升目は tenkai_silks_seed.json(手元で読み取り済み)+ 公開バケットの tenkai/sim/v1/silks.json にため、新しい騎手の図だけ公式サイトから取る(10 秒あける)。
環境変数: SUPABASE_URL・SUPABASE_SERVICE_KEY(読むだけなら公開の鍵 SUPABASE_ANON_KEY でも良い)
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
KEIRO = {1: '栗毛', 2: '栃栗毛', 3: '鹿毛', 4: '黒鹿毛', 5: '青鹿毛', 6: '青毛', 7: '芦毛', 11: '白毛'}   # 馬の台帳(KDS)の毛色の番号。南関の血統の台帳の字と 4,204/4,208 頭で一致(11/17)


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


def coat_table(paths):
    """馬の台帳(parquet・列 name・birth〔20240207〕・keiro〔番号〕か keiro_name〔字〕)→ {(馬名, 生年月日 8 桁): 毛色}。先に渡した台帳を優先。
    毛色は事実(公式サイトの画像ではない)。台帳が無い・読めないときは空 = ページは名前から決めた仮の色で描く。"""
    out = {}
    for p in paths or []:
        try:
            import pandas as pd
            import pyarrow.parquet as pq
            cols = [c for c in ['name', 'birth', 'keiro', 'keiro_name'] if c in pq.read_schema(str(p)).names]
            d = pd.read_parquet(p, columns=cols).dropna(subset=['name', 'birth'])
            nm = d['keiro_name'] if 'keiro_name' in d else pd.Series(index=d.index, dtype=object)
            if 'keiro' in d:
                nm = nm.where(nm.notna(), d['keiro'].map(lambda v: KEIRO.get(int(v)) if v == v else None))
            for n, b, k in zip(d['name'], d['birth'], nm):
                if isinstance(k, str) and k:
                    out.setdefault((n, str(int(b))), k)
        except Exception as e:  # noqa: BLE001
            _log('毛色の台帳が読めない', p, type(e).__name__, e)
    return out


def coat_paths():
    """便 = 予想の便が開けた固定の台帳 $V3_KD/kd_horse.parquet。ほかは TKSIM_COAT(os.pathsep 区切り)で足す。"""
    ps = [x for x in os.environ.get('TKSIM_COAT', '').split(os.pathsep) if x]
    if os.environ.get('V3_KD'):
        ps.append(str(Path(os.environ['V3_KD']) / 'kd_horse.parquet'))
    return [p for p in ps if Path(p).exists()]


def build(day, timing='morning', track=None, coat=None):
    """→ (DATA または None, 数え)。None のときは 数え['why'] に理由。"""
    info = {'day': day, 'tracks': tracks_of(day), 'skip': [], 'unchecked': [], 'nocoat': []}
    coat = coat_table(coat_paths()) if coat is None else coat
    if not info['tracks']:
        info['why'] = '南関の開催が無い(またはレースの表がまだ無い)'
        return None, info
    track = track or next((t for t in info['tracks'] if t in DRAWN), info['tracks'][0])
    info['track'] = track
    if track not in DRAWN:
        info['why'] = f'{track} は絵のコースがまだ無い(作ってあるのは {"・".join(sorted(DRAWN))} だけ)'
        return None, info
    t = _q(track)
    races = rest(f'nar_races?select=race_no,post_time,race_name,distance_m,cancelled,going,prize_yen&track=eq.{t}&race_date=eq.{day}&order=race_no.asc')
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
        runs = rpc('runs_race', {'p_track': track, 'p_date': day, 'p_no': no}, 'select=runner_number,gate,horse_name,jockey,age,birth_date&order=runner_number.asc')
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
            if r.get('age') is not None:
                h['ag'] = int(r['age'])           # 年齢(芦毛は年を取るほど白い)
            kc = coat.get((r['horse_name'], str(r.get('birth_date') or '').replace('-', '')))
            if kc:
                h['kc'] = kc                      # 本物の毛色(馬の台帳)。無い馬はページが名前から決めた仮の色で描く
            else:
                info['nocoat'].append((no, u, r['horse_name']))
            h['_bd'] = str(r.get('birth_date') or '').replace('-', '')[:8]
            hs.append(h)
        if len(hs) < 3:
            info['skip'].append((no, f'そろった馬が {len(hs)} 頭'))
            continue
        if dist not in CHECKED.get(track, ()):
            info['unchecked'].append((no, dist))
        out.append({'no': no, 'name': rc.get('race_name') or '', 'dist': dist or int(tk.get('distance_m') or 0), 'post': rc.get('post_time') or '',
                    'c1': tk.get('c1name') or '最初の角', 'timing': tm, 'h': hs, '_go': str(rc.get('going') or ''), '_pz': rc.get('prize_yen')})
    if not out:
        info['why'] = f'{track} の予想と位置の予想がまだそろっていない(前日の便の後に回す)'
        return None, info
    pace_into(day, out, info)
    info['n_race'], info['n_horse'] = len(out), sum(len(r['h']) for r in out)
    return {'date': day, 'track': track, 'races': out}, info


def pace_into(day, out, info):
    """出走馬の近 5 走(AI と同じ元 = 公式の成績の表)→ 馬ごとの癖 h.pf と、レースの流れ・時計の読み r.pace(見せ方だけ・tenkai_sim_pace_live.py)。
    pf = [前に行く度合い, 前半の速さ(1000m あたり・− = 速い), 上がり − レースの上がり, 捲り, 走った数]。読めない時はページは作り、絵はくじだけで走る。
    DB から読むのは出走馬の過去 2 年の走り(runs_by_horses)と、その走りのレースの行(通過順・上がり・馬場)だけ。"""
    import pandas as pd
    import tenkai_sim_pace_live as TP
    try:
        P, m = TP.live_profiles(day, [h['nm'] for r in out for h in r['h']], rest, rpc, _q)
    except Exception as e:
        info['pace'] = f'読めず {type(e).__name__}: {e}'
        for r in out:
            r.pop('_go', None); r.pop('_pz', None)
            for h in r['h']:
                h.pop('_bd', None)
        return
    nk = 0
    for r in out:
        rows = []
        for h in r['h']:
            k = f"{h['nm']}|{h.pop('_bd', '')}"
            v = P.loc[k] if len(P) and k in P.index else None
            if v is not None and v['nr'] > 0:
                f = lambda c, d=0.0, n=3: round(float(v[c]), n) if v[c] == v[c] else d
                h['pf'] = [f('pos1', None), f('fr', 0.0, 2), f('ag', 0.9, 2), f('mv'), int(v['nr'])]
                nk += 1
                rows.append({'pos1': v['pos1'], 'fr': v['fr'], 'ag': v['ag'], 'tm': v['tm'], 'mv': v['mv'], 'nr': v['nr']})
            else:
                rows.append({'pos1': None, 'fr': None, 'ag': None, 'tm': None, 'mv': None, 'nr': 0})
        go, pz = r.pop('_go', ''), r.pop('_pz', None)
        r['pace'] = TP.live_pace(m, pd.DataFrame(rows), r['dist'], go, pz)
    info['pace'] = f"近走の記録あり {nk} 頭 / {sum(len(r['h']) for r in out)} 頭"


def path_of(day, track):
    return f'{SIM_ROOT}{day}/{PREFIX[track]}.json'


def upload(path, data):
    _req(f'/storage/v1/object/{BUCKET}/{path}', 'POST', data,
         {'Content-Type': 'application/json; charset=utf-8', 'x-upsert': 'true', 'Cache-Control': CACHE})


def silks_into(data, write):
    """騎手の本物の勝負服を足す。落ちても data はそのまま(仮の柄で描く)。"""
    try:
        import tenkai_silks_db as S
        store = {}
        seed = Path(__file__).resolve().parent / 'tenkai_silks_seed.json'
        if seed.exists():
            store.update(json.loads(seed.read_text(encoding='utf-8')))
        raw = _req(f'/storage/v1/object/public/{BUCKET}/{SIM_ROOT}silks.json', auth=False)
        if raw:
            store.update(json.loads(raw))
        n0 = len(store)
        _log('勝負服', S.attach(data, store), '升目の持ち合わせ', n0, '→', len(store))
        if write and (len(store) > n0 or not raw):
            upload(SIM_ROOT + 'silks.json', json.dumps(store, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    except Exception as e:  # noqa: BLE001
        for r in data['races']:
            for h in r['h']:
                h.pop('sk', None)
        data.pop('silks', None)
        _log('勝負服は載せられなかった(仮の柄で描く)', type(e).__name__, e)


def run(day, write=False, out_dir='out_tksim', timing='morning'):
    """入口(便から呼ぶ)。戻り = 置いた R の数(作らない日は 0)。"""
    t0 = time.time()
    data, info = build(day, timing)
    if data is None:
        _log(day, 'ページを作らない:', info['why'])
        return 0
    if os.environ.get('TKSIM_SILKS') == '1':
        silks_into(data, write)
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
         '・抜いた R', info['skip'], '・絵が未確認の距離', info['unchecked'], '・毛色あり', info['n_horse'] - len(info['nocoat']), '無し', len(info['nocoat']), '・流れ', info.get('pace'), f'{time.time() - t0:.0f}s')
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
