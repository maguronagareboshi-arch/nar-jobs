# -*- coding: utf-8 -*-
"""併せ馬の相手の層(南関 AI v3 決め 60・2026-10-28・研究 nankan-ai-v3 src/f5_scripts/awase60_judge.py)。

当日の便(v29_gap.day_marks)の最後の段(F3 の混ぜの後)で、最終追いが併せ馬だった馬の
「先着 +1 / 同入・併入 0 / 遅れ −1」(res)と「向き付きの秒差」(mar)を率の対数に線形で足す。
  p1′ = レースの中で合計 1 に(p1 × exp(D·W1))・p3′ = max(sig(logit p3 + D·W3), min(p1′, 0.999))(合計 3 は呼ぶ側)
  D = [res / SD0, mar / SD1]。定数 = 暗号化したリリースの consts.json の awase60。
元 = nar_kb_works.works の partners(cloud/kb/parsers.parse_cyokyo が相手の行を直前の追い切りに残す)。
最終追い = ☆ の付いた追い切り(kb_flatten.work_kind = final)のうち一番遅い日。その日の追い切りの相手の行を
字の並び(Unicode 順)にして最初の 1 本を読む(研究と同じ決まり・3 頭併せ / 同じ日に 2 本の馬)。
相手の行の無い馬は 0(足さない)。相手の行が 1 頭も無いレースは何もしない。
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed
import sealed  # noqa: E402
import kb_flatten  # noqa: E402
import kb_works  # noqa: E402

_S = sealed.get('awase60')
W1, W3, SD = (np.asarray(_S[k], float) for k in ('W1', 'W3', 'SD'))
W = {'day': (W1, W3), 'pre': (np.asarray(_S['W1_PRE'], float), np.asarray(_S['W3_PRE'], float))}   # 前日版は前日版の上で学んだ重み(決め書 10 節)
TAG = _S['TAG']
KEY = ['track', 'race_date', 'race_no']
MK = {1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}
PAT = re.compile(r'^(?P<name>.+?)（(?P<cls>[^）]*)）(?P<pash>[^の同先遅]+?)(?:の(?P<side>内|外|中))?'
                 r'(?:を(?P<dist>\d)Ｆ(?P<how>併|付))?(?:(?P<mar>\d+\.\d+)秒)?(?P<res>先着|同入|遅れ|併入)?$')
RES = {'先着': 1, '同入': 0, '併入': 0, '遅れ': -1}


def horse_x(works):
    """1 頭の works(JSON)→ (res, mar)。最終追いの相手の行が無い・読めない時は (0, 0)。"""
    ws = [w for w in (works or []) if kb_flatten.work_kind(w)]
    fin = [w['date'] for w in ws if kb_flatten.work_kind(w) == 'final']
    if not fin:
        return 0.0, 0.0
    d = max(fin)
    ps = sorted(p for w in ws if w['date'] == d for p in (w.get('partners') or []))
    if not ps:
        return 0.0, 0.0
    m = PAT.match(ps[0])
    r = RES.get(m.group('res')) if m else None
    if r is None:
        return 0.0, 0.0
    mar = float(m.group('mar')) if m.group('mar') and r != 0 else 0.0
    return float(r), r * mar


def load(day):
    """その日の南関の nar_kb_works → {(track, race_no, umaban): (res, mar)}(相手の行のある馬だけ)。読めなければ例外。"""
    base, key = kb_works.creds()
    if not base:
        raise RuntimeError('nar_kb_works の鍵が無い')
    q = [('select', 'track,race_no,umaban,works'), ('track', 'in.(' + ','.join(kb_works.TRACKS) + ')'),
         ('race_date', f'eq.{day}'), ('order', 'race_id,umaban'), ('limit', '5000')]
    req = urllib.request.Request(f'{base}/rest/v1/{kb_works.TABLE}?' + urllib.parse.urlencode(q),
                                 headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai-v3'})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read().decode('utf-8'))
    out = {}
    for r in rows:
        x = horse_x(r.get('works'))
        if x != (0.0, 0.0):
            out[(r['track'], int(r['race_no']), int(r['umaban']))] = x
    return out, len(rows)


def apply(A, track, rno, nums, p1, p3, ver='day'):
    """→ (p1′, p3′ の合計の前, 足した頭数) か None(相手の行のある馬がいない)。nums = 馬番の並び(p1・p3 と同じ順)。ver = day / pre(重み)。"""
    D = np.array([A.get((track, int(rno), int(u)), (0.0, 0.0)) for u in nums], float)
    n = int((D != 0).any(axis=1).sum())
    if n == 0:
        return None
    w1, w3 = W[ver]
    D = D / SD
    p1 = np.clip(np.asarray(p1, float), 1e-12, 1.0)
    e = np.log(p1) + D @ w1
    e1 = np.exp(e - e.max())
    p1n = e1 / e1.sum()
    p3 = np.clip(np.asarray(p3, float), 1e-6, 1 - 1e-6)
    p3n = np.maximum(1 / (1 + np.exp(-(np.log(p3 / (1 - p3)) + D @ w3))), np.minimum(p1n, 0.999))
    return p1n, p3n, n


def sum3(p3):
    """合計 3 にそろえる(v29_gap._sum3・t6_base.p3prime と同じ: logit をずらす二分法 [−30, +30]・100 回)。"""
    p = np.clip(np.asarray(p3, float), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    lo, hi = -30.0, 30.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if (1 / (1 + np.exp(-(z + mid)))).sum() < 3 else (lo, mid)
    return 1 / (1 + np.exp(-(z + (lo + hi) / 2)))


def apply_csv_pre(A, csv_path, log=print):
    """前日版の表の CSV(短評の層の後)を直す: p1・p3p(元は p1_aw0・p3p_aw0)・rank・mark・aw60_n。4 頭以上のレースだけ。→ 直したレース数"""
    import pandas as pd
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p1_aw0' in x.columns:  # 2 度かけない
        log('併せの相手 前日版 済み')
        return 0
    x['p1_aw0'], x['p3p_aw0'], x['aw60_n'] = x.p1, x.p3p, 0
    n = 0
    for (tr, _, rno), g in x.groupby(KEY, sort=False):
        if len(g) <= 3:
            continue
        r = apply(A, tr, rno, g.umaban.astype(int).to_numpy(), g.p1.to_numpy(float), g.p3p.to_numpy(float), 'pre')
        if r is None:
            continue
        x.loc[g.index, 'p1'], x.loc[g.index, 'p3p'], x.loc[g.index, 'aw60_n'] = r[0], sum3(r[1]), r[2]
        n += 1
    o = x.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map(MK).fillna('')
    x = x.sort_values(KEY + ['rank'], kind='mergesort')
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    top = lambda c: x.loc[x.groupby(KEY, sort=False)[c].idxmax(), KEY + ['umaban']].set_index(KEY).umaban  # noqa: E731
    log('併せの相手 前日版に足した', n, 'R・本命が替わった', int((top('p3p') != top('p3p_aw0')).sum()), 'R')
    return n
