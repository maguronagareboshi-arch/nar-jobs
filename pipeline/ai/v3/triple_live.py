# -*- coding: utf-8 -*-
"""南関のトリプル馬単(その日の最終 3 レースの馬単を全部当てる・50 円から)の買い目を毎日作る(2026-11-18 ユーザー依頼・投票はしない)。

  python -X utf8 pipeline/ai/v3/triple_live.py DATE [--write] [--out DIR]     # DATE = YYYY-MM-DD(YYYYMMDD でも良い)

買い方 =「堅さで組数を配る」(研究 nankan-ai-v3 src/triple_picks.py・out/triple_1118/ai_use2.py と同じ計算):
  前日版の印の行(nar_ai_marks・model v3-9・timing morning)の勝つ率 p1・3 着内率 p3 だけを使う(オッズは使わない)。
  馬単の率 = 1 着 p1 × 2 着 (p1^0.27 × p3^0.85)。各レースで率の高い順に並べ、3 レースの組数の掛け算が 100(= 5 千円)以内で
  3 つとも当たる見込みが一番高い配り方を選ぶ。
持ち越し(キャリーオーバー)は場ごと。公式の結果の一覧(nankankeiba.com・国外からは本番 DB 経由 = cloud/jp_fetch.py)から、
  その場の前の開催日の値を読む。前の開催日の結果がまだ一覧に無い(前日の夜の最終レースの前)ときは「結果待ち」と書き、
  後の便(前夜 22:40・当日 8:30・12:00)が書き直す。持ち越しの 1 回目は「見送り」(五分)・なし と 2 回以上続いた日は「買う日」(11/19 ユーザーの決め)。
出力: 公開バケット cond-stats/triple/v1/<日>.json(1 日 1 本)。--write なしは DIR(既定 out_triple)に同じ JSON と、手で回す台本と同じ形の字(.txt)。
  ⛔DB の表は読むだけ(印の行)・書かない。⛔当たる見込み % は JSON に入れない(高く出すぎる = 画面に出さない決め)。
環境変数: SUPABASE_URL・SUPABASE_SERVICE_KEY(読むだけなら公開の鍵 SUPABASE_ANON_KEY でも良い)。NK_VIA_DB=0 で公式を直に読む(国内の PC)。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'cloud'))
import jp_fetch  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
V = 1
BUCKET = 'cond-stats'
ROOT = 'triple/v1/'
CACHE = 'public, max-age=60'   # 2026-11-26 1 本目を直前版で作り直す(締め切りの 10 分ほど前)ので短く
MODEL, TIMING = 'v3-9', 'morning'
JO = {'浦和': '18', '船橋': '19', '大井': '20', '川崎': '21'}
PREFIX = {'浦和': 'urawa', '船橋': 'funabashi', '大井': 'ooi', '川崎': 'kawasaki'}  # サイト js/data.js の VENUES と同じ
MAXN = 100      # 1 日 5 千円 = 50 円 × 100 枚(2026-11-26 期間を分けた検証 nankan-ai-v3 out/triple_1118/tri_judge_plan.md・ユーザー「反証してから準備」)
UA = 'nar-jobs triple_live'


def _log(*a):
    print('[triple]', *a, flush=True)


def _env():
    base = os.environ['SUPABASE_URL'].rstrip('/')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ['SUPABASE_ANON_KEY']
    return base, key


def _req(path, method='GET', body=None, headers=None, timeout=60):
    base, key = _env()
    h = {'User-Agent': UA, 'apikey': key, 'Authorization': 'Bearer ' + key}
    h.update(headers or {})
    for i in range(3):
        try:
            r = urllib.request.Request(base + path, method=method, data=body, headers=h)
            with urllib.request.urlopen(r, timeout=timeout) as x:
                return x.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == 2:
                raise
        time.sleep(3 * (i + 1))


def rest(query):
    return json.loads(_req('/rest/v1/' + query, headers={'Accept': 'application/json'}))


def marks(day, timing=TIMING):
    """{場: {R: [(馬番, p1, p3), …]}}(timing = morning 前日版 / last 直前版)。"""
    q = (f'nar_ai_marks?select=track,race_no,meta&model=eq.{MODEL}&timing=eq.{timing}&race_date=eq.{day}'
         + '&track=in.(' + ','.join(urllib.parse.quote(t) for t in JO) + ')')
    out = {}
    for r in rest(q):
        run = [(int(x['num']), float(x['p1']), float(x['p3'])) for x in (r.get('meta') or {}).get('runners', []) if x.get('p1') and x.get('p3')]
        out.setdefault(r['track'], {})[int(r['race_no'])] = run
    return {t: out[t] for t in JO if t in out}


def prev_day(track, day):
    """その場の前の開催日(印の行がある一番新しい日・YYYY-MM-DD)。無ければ None。"""
    r = rest(f'nar_ai_marks?select=race_date&model=eq.{MODEL}&timing=eq.{TIMING}&track=eq.{urllib.parse.quote(track)}'
             f'&race_date=lt.{day}&order=race_date.desc&limit=1')
    return r[0]['race_date'] if r else None


def result_list(year):
    """公式の結果の一覧(その年)の HTML。"""
    url = f'https://www.nankankeiba.com/jyusyosiki_result/{year}0306.do?month=alltuki&jo=alljo'
    if jp_fetch.via_db(url):
        raw = jp_fetch.fetch(url, timeout=60)
    else:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read()
    return raw.decode('cp932', 'ignore')


def carry_rows(html):
    """一覧の行 → {場の番号: {YYYYMMDD: その日からの持ち越し(円)}}。"""
    out = {}
    i = html.find('施行日')
    for row in re.findall(r'<tr.*?</tr>', html[i if i >= 0 else 0:], flags=re.S):
        m = re.search(r'jyusyosiki/(\d{8})(\d\d)\d+\.do', row)
        cells = [re.sub(r'<[^>]*>', ' ', c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, flags=re.S)]
        if not m or len(cells) < 14:
            continue
        out.setdefault(m.group(2), {})[m.group(1)] = int(re.sub(r'[^\d]', '', cells[13]) or 0)
    return out


def carry_of(track, day, lists):
    """→ {state: none(なし)| yes(あり)| wait(前の開催日の結果待ち)| unknown(読めない), yen, from, times, buy}。lists = 年 → carry_rows の結果(使い回す)。
    times = 持ち越しが何回続いたか(前の開催日から数えて、当たりなしが続いた開催日の数)。
    buy = 買う日か。2026-11-26 から持ち越しに関わらず毎日買う(期間を分けた検証で「全部の日」が選ばれた。11/19 の「1 回目は見送り」は替えた)。
      2 回以上続いた日は、買った人全体への戻りが売上を超える日が多い(南関 2014〜 165 日で中央値 1.09 倍・88% の日で 1 倍超)。"""
    d8 = day.replace('-', '')
    try:
        rows = {}
        for y in (int(d8[:4]), int(d8[:4]) - 1):       # 年の最初の開催日は前の年の一覧も見る
            if y not in lists:
                lists[y] = carry_rows(result_list(y))
            rows.update({k: v for k, v in lists[y].get(JO[track], {}).items() if k < d8})
            if rows:
                break
        if not rows:
            return {'state': 'unknown', 'yen': None, 'from': None, 'times': None, 'buy': True}
        times = 0
        for k in sorted(rows, reverse=True):            # 前の開催日から遡って、持ち越しが続いた日を数える
            if rows[k] <= 0:
                break
            times += 1
        if times and times == len(rows) and int(d8[:4]) - 1 not in lists:   # 年をまたいで続いている = 前の年も見る
            lists[int(d8[:4]) - 1] = carry_rows(result_list(int(d8[:4]) - 1))
            for k in sorted(lists[int(d8[:4]) - 1].get(JO[track], {}), reverse=True):
                if lists[int(d8[:4]) - 1][JO[track]][k] <= 0:
                    break
                times += 1
        last = max(rows)
        frm = f'{last[:4]}-{last[4:6]}-{last[6:]}'
        pd_ = prev_day(track, day)
        if pd_ and pd_ > frm:
            return {'state': 'wait', 'yen': None, 'from': pd_, 'times': None, 'buy': True}
        return {'state': 'yes' if rows[last] > 0 else 'none', 'yen': rows[last], 'from': frm, 'times': times, 'buy': True}
    except Exception as e:  # noqa: BLE001
        _log(track, '持ち越しが読めなかった', type(e).__name__, e)
        return {'state': 'unknown', 'yen': None, 'from': None, 'times': None, 'buy': True}


def exacta(run):
    """1 レースの馬単の率(高い順の [(率, 1 着, 2 着)])・本命の勝つ率・本命の馬番。"""
    hb = np.array([x[0] for x in run]); w = np.array([x[1] for x in run]); t = np.array([x[2] for x in run]); n = len(hb)
    w = w / w.sum(); t = np.clip(t, 1e-4, .995); t = np.clip(t / t.sum() * min(3, n), 1e-4, .995); u = w ** 0.27 * t ** 0.85
    P = w[:, None] * u[None, :] / np.clip(u.sum() - u[:, None], 1e-12, None); P[np.eye(n, dtype=bool)] = 0; P = P / P.sum()
    pr = sorted(((P[i, j], int(hb[i]), int(hb[j])) for i in range(n) for j in range(n) if i != j), reverse=True)
    return pr, float(w.max()), int(hb[int(np.argmax(w))])


def split(cum):
    """組数の配り方(k1, k2, k3)= 掛け算が MAXN 以内で、3 つとも当たる見込みが最大。"""
    best = None
    for k1 in range(1, min(MAXN, len(cum[0])) + 1):
        for k2 in range(1, min(MAXN // k1, len(cum[1])) + 1):
            k3 = min(MAXN // (k1 * k2), len(cum[2]))
            if k3 < 1:
                continue
            c = cum[0][k1 - 1] * cum[1][k2 - 1] * cum[2][k3 - 1]
            if best is None or c > best[0]:
                best = (c, (k1, k2, k3))
    return best[1]


def build(day, leg1=None):
    """→ (公開する doc の tracks, 字の行)。leg1 = {場: [(馬番, p1, p3), …]} = 1 本目を直前版の率で差し替える(当日の便 v29_gap.py から)。
    2026-11-26: 1 本目だけ直前版で作ると期間を分けた検証で一番良かった(2 本目・3 本目は締め切りの時刻にまだ直前版が無い = 前日版)。"""
    M = marks(day)
    leg1 = leg1 or {}
    d8 = day.replace('-', '')
    tracks, lines, lists = [], [], {}
    if not M:
        lines.append(f'{d8}: 南関の前日版の行が無い(開催なしか、前日 15 時の便の前)')
    for track, R in M.items():
        legs = sorted(R)[-3:]
        if len(legs) < 3 or any(len(R[r]) < 5 for r in legs):
            lines.append(f'{d8} {track}: 最終 3 レースの率がそろっていない')
            continue
        l1 = leg1.get(track)
        use_last = bool(l1) and len(l1) >= 5
        E = [exacta(l1 if (use_last and i == 0) else R[r]) for i, r in enumerate(legs)]
        cum = [np.cumsum([p for p, _, _ in e[0]]) for e in E]
        ks = split(cum)
        n = ks[0] * ks[1] * ks[2]
        lp = [float(c[k - 1]) for c, k in zip(cum, ks)]   # 各レースの買った組で当たる見込み
        hp = lp[0] * lp[1] * lp[2]                        # 3 つとも当たる見込み(2023-01〜26-08 の 750 日で 見込み 73.3 本 = 実際 73 本)
        ci = carry_of(track, day, lists)
        frm = (ci['from'] or '').replace('-', '')
        lines.append(f'■ {d8} {track} トリプル馬単({legs[0]}R・{legs[1]}R・{legs[2]}R)・1 本目 ' + ('直前版' if use_last else '前日版(直前版の前)'))
        if ci['state'] == 'unknown':
            lines.append('  持ち越し: 読めなかった(公式の頁で確かめる)')
        elif ci['state'] == 'wait':
            lines.append(f'  持ち越し: 前の開催日({frm})の結果待ち')
        elif ci['state'] == 'yes':
            lines.append(f"  持ち越し: あり {ci['yen']:,} 円({ci['times']} 回続き・{frm} から)→ 買う日(毎日買う)")
        else:
            lines.append(f'  持ち越し: なし(前回 {frm})→ 買う日(毎日買う)')
        lines.append(f'  組数 {ks[0]} × {ks[1]} × {ks[2]} = {n} 枚・{n * 50:,} 円・当たる見込み {100 * hp:.0f}%(この買い方は 2025-01〜26-08 の 456 日で 32 本 = 14 日に 1 本)')
        races = []
        for r, e, k, q in zip(legs, E, ks, lp):
            by = {}
            for _, a, b in e[0][:k]:
                by.setdefault(a, []).append(b)
            lines.append(f'  {r}R  本命 {e[2]} 番(勝つ率 {100 * e[1]:.0f}%)・{k} 組・このレースで当たる見込み {100 * q:.0f}%')
            for a, bs in by.items():
                lines.append(f'      1 着 {a:>2} → 2 着 ' + '・'.join(map(str, bs)))
            races.append({'no': int(r), 'k': int(k), 'p': round(q, 4), 'pairs': [[a, bs] for a, bs in by.items()]})
        lines.append('')
        tracks.append({'track': track, 'prefix': PREFIX[track], 'legs': [int(x) for x in legs], 'carry': ci, 'leg1': 'last' if use_last else 'morning',
                       'ks': [int(x) for x in ks], 'hit': round(hp, 4), 'n': int(n), 'yen': int(n * 50), 'races': races})
    return tracks, lines


def upload(path, data):
    _req(f'/storage/v1/object/{BUCKET}/{path}', 'POST', data,
         {'Content-Type': 'application/json; charset=utf-8', 'x-upsert': 'true', 'Cache-Control': CACHE})


def run(day, write=False, out_dir='out_triple', leg1=None):
    """入口(便から呼ぶ)。戻り = 買い目を作れた場の数(開催なし・率がそろわない日は 0 = 何も置かない)。
    leg1 = 1 本目の直前版の率 {場: [(馬番, p1, p3), …]}(当日の便から)。None のときは DB の直前版の行(timing last)があれば使う
    (前日 15 時・夜 22:40・朝の便では直前版はまだ無い = 前日版のまま。当日の便が書いた後に回し直しても 1 本目は直前版のまま)。"""
    t0 = time.time()
    day = day if '-' in day else f'{day[:4]}-{day[4:6]}-{day[6:]}'
    dt.date.fromisoformat(day)
    if leg1 is None:
        try:
            L = marks(day, 'last'); M0 = marks(day)
            leg1 = {t: L[t][sorted(M0[t])[-3]] for t in M0 if t in L and len(M0[t]) >= 3 and sorted(M0[t])[-3] in L[t]}
        except Exception as e:  # noqa: BLE001  直前版が読めなければ前日版のまま
            _log('直前版の行が読めない(1 本目は前日版)', type(e).__name__, str(e)[:120]); leg1 = {}
    tracks, lines = build(day, leg1)
    for s in lines:
        _log(s)
    if not tracks:
        _log(day, '買い目を作らない(何も置かない)')
        return 0
    doc = {'v': V, 'day': day, 'computed_at': dt.datetime.now(JST).isoformat(timespec='seconds'), 'max': MAXN, 'tracks': tracks}
    body = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    p = f'{ROOT}{day}.json'
    if write:
        upload(p, body)
    else:
        f = Path(out_dir) / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
        f.with_suffix('.txt').write_text('\n'.join(lines), encoding='utf-8')
    _log(day, '置いた', len(tracks), '場', len(body), 'バイト', 'バケット ' + p if write else out_dir,
         '・持ち越し', [t['carry']['state'] for t in tracks], f'{time.time() - t0:.0f}s')
    return len(tracks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('day')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--out', default='out_triple')
    a = ap.parse_args()
    run(a.day, a.write, a.out)


if __name__ == '__main__':
    main()
