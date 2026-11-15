# -*- coding: utf-8 -*-
"""ばんえい(帯広)の単勝の買い目 = ばんえい 買い方 決め 2(2026-11-15 合格・nankan-ai-v3 の out/banei_buy2_judge.md)。
予想の印は変えない。買い目だけ。

  勝つ率 q = レースの中の割合 exp(a × logit(p) + b × log m)
     p = 本番の行(nar_ai_marks・model banei-3・timing last)の meta.p(第 4 版の 3 着内率・割り直す前)
     m = 発走 10 分前の単勝オッズの 1/o(1 倍未満は 1 倍)をレースの中で割合にしたもの
  買う = q × 10 分前の単勝オッズ ≥ 線 かつ 10 分前の単勝オッズ ≤ 上限。1 頭 100 円。

数(a・b・線・上限・分)は公開のコードに書かない = 暗号化リリースの banei_win2.json(環境変数 BANEI_WIN2 の場所)。
読めない日は買い目を出さない(予想の便は止めない)。

  python -X utf8 pipeline/ai/banei/banei_win2.py tick DAY [--write] [--at HH:MM]
     = 発走の 10 分前を過ぎ、発走前で、まだ決めていないレースを 1 回だけ決め、nar_v3_gap に key 'DAY:帯広ば:R' で書く。
       予想の便(banei-v3.yml の直前の周)が 2 分ごとに呼ぶ。発走が遅れたら新しい発走の 10 分前に決め直す(value.redecided_from)。
       --at は試し(過ぎた日を、その時刻の最後のオッズで決め直す・書かない)。--at each = レースごとに発走の 10 分前で。
  python -X utf8 pipeline/ai/banei/banei_win2.py selftest
     = 部品の検算(手で作った 1 レース)。
⛔公開 repo のログに候補(馬番・オッズ)は出さない。出すのは件数だけ。
"""
import datetime as dt
import json
import math
import os
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
JST = dt.timezone(dt.timedelta(hours=9))
TRACK = '帯広ば'
MODEL_ID = 'banei-3'
TAG = 'banei_win2'
GAP = '/rest/v1/nar_v3_gap'


def log(*a):
    print('[banei_win2]', *a, flush=True)


def consts():
    p = os.environ.get('BANEI_WIN2') or str(Path(os.environ.get('BANEI_V3', 'work')) / 'banei_kb' / 'banei_win2.json')
    C = json.load(open(p, encoding='utf-8'))
    for k in ('a', 'b', 'line', 'cap', 'minutes'):
        float(C[k])
    return C


def decide(p, odds, C):
    """p = {馬番: 3 着内率}・odds = {馬番: 単勝オッズ}。両方ある馬だけで決める。→ (runners, buy)"""
    nums = sorted(n for n in p if n in odds and odds[n] and odds[n] > 0 and p[n] is not None)
    if len(nums) < 2:
        return [], []
    inv = {n: 1.0 / max(float(odds[n]), 1.0) for n in nums}
    s = sum(inv.values())
    a, b = float(C['a']), float(C['b'])
    t = {}
    for n in nums:
        pp = min(max(float(p[n]), 1e-4), 1 - 1e-4)
        t[n] = a * math.log(pp / (1 - pp)) + b * math.log(inv[n] / s)
    mx = max(t.values())
    e = {n: math.exp(t[n] - mx) for n in nums}
    se = sum(e.values())
    runners = []
    for n in nums:
        q = e[n] / se
        o = float(odds[n])
        ev = q * o
        runners.append({'num': n, 'odds': o, 'p': round(float(p[n]), 4), 'q': round(q, 4), 'ev': round(ev, 3),
                        'buy': bool(ev >= float(C['line']) and o <= float(C['cap']))})
    return runners, [r for r in runners if r['buy']]


# ---------------------------------------------------------------- DB
def _rest(path, body=None, prefer=None):
    import bn_kb
    return bn_kb.rest(path, body, prefer)


def races(day):
    return _rest(f'/rest/v1/nar_races?track=eq.{urllib.parse.quote(TRACK)}&race_date=eq.{day}&select=race_no,post_time,cancelled&order=race_no')


def post_at(day, pt):
    s = str(pt or '').replace(':', '').strip()
    if len(s) not in (3, 4) or not s.isdigit():
        return None
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(int(s[:-2]), int(s[-2:])), JST)


def marks_p(day):
    r = _rest(f'/rest/v1/nar_ai_marks?track=eq.{urllib.parse.quote(TRACK)}&race_date=eq.{day}&model=eq.{MODEL_ID}&timing=eq.last'
              '&select=race_no,meta')
    out = {}
    for x in r or []:
        p = (x.get('meta') or {}).get('p') or {}
        out[int(x['race_no'])] = {int(k): float(v) for k, v in p.items() if v is not None}
    return out


def odds_at(day, rno, hhmm=None):
    """確定前の最後の単勝オッズ。hhmm があればその時刻までの最後(試し用)。"""
    q = f'/rest/v1/nar_odds_ticks?track=eq.{urllib.parse.quote(TRACK)}&race_date=eq.{day}&race_no=eq.{rno}&f=eq.false'
    if hhmm:
        q += f'&t=lte.{hhmm}'
    r = _rest(q + '&select=id,t,asof,w&order=id.desc&limit=1')
    if not r:
        return None, None
    w = r[0].get('w') or {}
    return {int(k): float(v) for k, v in w.items() if v not in (None, '') and float(v) > 0}, (r[0].get('asof') or r[0].get('t'))


def stored(day):
    r = _rest(f"{GAP}?race_date=eq.{day}&track=eq.{urllib.parse.quote(TRACK)}&select=key,post:value->>post")
    return {x['key']: (x.get('post') or '') for x in r or []}


def put(key, value, day, rno):
    body = [{'key': key, 'track': TRACK, 'race_date': day, 'race_no': rno, 'value': value,
             'updated_at': dt.datetime.now(dt.timezone.utc).isoformat()}]
    _rest(f'{GAP}?on_conflict=key', body, 'resolution=merge-duplicates,return=minimal')


def tick(day, write=False, at=None):
    try:
        C = consts()
    except Exception as e:  # noqa: BLE001  数が読めない日は買い目を出さない(予想の便は止めない)
        log('数が読めない = 買い目を出さない', type(e).__name__)
        return 0
    each = at == 'each'   # 試し: レースごとに「その発走の 10 分前」で決める
    now = post_at(day, at) if (at and not each) else dt.datetime.now(JST)
    mins = int(C['minutes'])
    have = {} if at else stored(day)
    P = None
    n_w = n_buy = 0
    for r in races(day) or []:
        rno = int(r['race_no'])
        if r.get('cancelled'):
            continue
        pt = post_at(day, r.get('post_time'))
        if pt is not None and each:
            now = pt - dt.timedelta(minutes=mins)
        if pt is None or now < pt - dt.timedelta(minutes=mins) or now >= pt:
            continue
        key = f'{day}:{TRACK}:{rno}'
        prev = have.get(key)
        if prev == pt.strftime('%H:%M'):
            continue
        if P is None:
            P = marks_p(day)
        p = P.get(rno)
        odds, asof = odds_at(day, rno, now.strftime('%H:%M') if at else None)
        if not odds:
            log(f'{rno}R: 締め切り前のオッズが無い(次の回)')
            continue
        val = {'model': TAG, 'rule': C.get('rule'), 'line': C['line'], 'cap': C['cap'], 'post': pt.strftime('%H:%M'),
               'decided_at': now.strftime('%H:%M:%S'), 'odds_asof': asof, 'trained': C.get('trained')}
        if not p:
            val.update(why='no_last', n=0, runners=[], buy=[])   # 直前の印が無い(体重がそろわない等)= 買わない
        else:
            runners, buy = decide(p, odds, C)
            val.update(n=len(runners), runners=runners, buy=[{k: x[k] for k in ('num', 'odds', 'q', 'ev', 'p')} for x in buy])
        if prev:
            val['redecided_from'] = prev
        if write:
            try:
                put(key, val, day, rno)
            except Exception as e:  # noqa: BLE001
                log(f'{rno}R: 書けない {type(e).__name__}(次の回)')
                continue
        n_w += 1
        n_buy += len(val['buy'])
        log(f'{rno}R: 発走 {pt:%H:%M}・{now:%H:%M} に決めた・{val["n"]} 頭・候補 {len(val["buy"])} 頭'
            f'{"・" + val["why"] if val.get("why") else ""}{"・決め直し" if prev else ""}・{"書いた" if write else "書かない(試し)"}')
    log('この回', n_w, 'R・候補', n_buy, '頭')
    return n_w


def selftest():
    C = {'a': 0.7, 'b': 0.4, 'line': 1.2, 'cap': 100, 'minutes': 10}
    p = {1: 0.6, 2: 0.3, 3: 0.3, 4: 0.1}
    o = {1: 2.0, 2: 4.0, 3: 20.0, 4: 150.0}
    runners, buy = decide(p, o, C)
    assert abs(sum(r['q'] for r in runners) - 1) < 1e-3
    lg = lambda x: math.log(x / (1 - x))  # noqa: E731
    inv = {n: 1 / o[n] for n in o}
    s = sum(inv.values())
    t = {n: 0.7 * lg(p[n]) + 0.4 * math.log(inv[n] / s) for n in o}
    z = sum(math.exp(v) for v in t.values())
    for r in runners:
        assert abs(r['q'] - math.exp(t[r['num']]) / z) < 1e-4
        assert r['buy'] == (r['ev'] >= 1.2 and r['odds'] <= 100)
    assert all(r['num'] != 4 for r in buy)  # 上限 100 倍を超える馬は買わない
    log('selftest ok', [(r['num'], r['q'], r['ev'], r['buy']) for r in runners])


def main():
    a = sys.argv[1:]
    if not a or a[0] == 'selftest':
        return selftest()
    if a[0] == 'tick':
        at = a[a.index('--at') + 1] if '--at' in a else None
        tick(a[1], '--write' in a and not at, at)
        return 0
    raise SystemExit(__doc__)


if __name__ == '__main__':
    sys.exit(main() or 0)
