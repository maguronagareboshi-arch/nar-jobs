# -*- coding: utf-8 -*-
"""南関 直前版の「全 9 券種の組の確率」(AI だけ・オッズは使わない)を、固まった直前の行から作って公開の固定ファイルに置く(2026-11-05)。

研究 nankan-ai-v3 src/f5_scripts/ticket_prob_live_all.py・ticket_prob_build_1105.py をそのまま移した(計算は 1 文字も変えない):
  勝つ率 w と 3 着内率 t から 3連単の表を 1 枚作る(2 着 w^0.270 t^0.846・3 着 w^-0.059 t^1.017)
  → その 1 枚を足し上げて 単勝・複勝・枠連・枠単・馬連・ワイド・馬単・3連複・3連単。
  1 着が 1 頭だけ決まる券種は全部の組の合計が 100%。複勝とワイドは当たりが 3 つ(7 頭以下の複勝は 2 つ)= 合計 300%(200%)。

材料 = nar_ai_marks の model v3-9・timing last の行の meta.runners(p1・p3)と nar_runs の枠番(gate)。
  ⛔発走 15 分前を過ぎた後(DB のトリガーで直前の行が固まった後)にだけ作る = 画面の「直前」の 1着・3着内 と同じ数字から出す。
  ⛔直前の行が無いレースは作らない(前日版から作らない)。
置き場 = 公開バケット cond-stats の ticket/v1/<日>/<場の英字>-<R>.json(1 R 1 本・場の英字はサイトの prefix)。
  中身 {v, date, track, prefix, race_no, model, stamp, computed_at, built, n, place_k, nums, gates, unit, order, kinds}
  kinds[券種の鍵] = {p: [整数(確率 × 1e6)], k: [組の字](枠連・枠単だけ)}。
  ⛔組の並び(order)= 馬の券種は nums(小さい順)から作る辞書順: 単勝・複勝 = nums / 馬連・ワイド a<b / 馬単 a≠b / 3連複 a<b<c / 3連単 全部違う
     (サイト js/data.js の tpCombos と同じ)。確率は研究の CSV と同じ丸め(% で小数 4 桁 = 1e-6)。
"""
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

JST = dt.timezone(dt.timedelta(hours=9))
V = 1
MODEL = 'v3-9'
BUCKET = 'cond-stats'
ROOT = 'ticket/v1/'
CACHE = 'public, max-age=3600'
READY_MIN = 14.5   # 発走 14.5 分前を過ぎたら作る(直前の行は 15 分前で固まる)
PREFIX = {'浦和': 'urawa', '船橋': 'funabashi', '大井': 'ooi', '川崎': 'kawasaki'}  # サイト js/data.js の VENUES と同じ
UA = 'nar-jobs ticket_prob_live (+https://yukochi.com/)'

# ================================================================ 計算(研究 ticket_prob_build_1105.py と同じ)
A2, B2, A3, B3 = 0.270, 0.846, -0.059, 1.017
TYPES = ['単勝', '複勝', '枠連', '枠単', '馬連', 'ワイド', '馬単', '3連複', '3連単']
KEYS = {'単勝': 'tan', '複勝': 'fuku', '枠連': 'wakuren', '枠単': 'wakutan', '馬連': 'umaren', 'ワイド': 'wide',
        '馬単': 'umatan', '3連複': 'trio', '3連単': 'tri'}


def tensors(w, u, v):
    """17 頭分(0 番は空)。P12[a,b] = a が 1 着 b が 2 着、T3[a,b,c] = その上で c が 3 着。"""
    n = len(w)
    I = np.eye(n, dtype=bool)
    P12 = w[:, None] * u[None, :] / np.clip(u.sum() - u[:, None], 1e-12, None)
    P12[I] = 0.0
    d = np.clip(v.sum() - v[:, None] - v[None, :], 1e-12, None)
    T3 = P12[:, :, None] * v[None, None, :] / d[:, :, None]
    T3[I[:, :, None] | I[:, None, :] | I[None, :, :]] = 0.0
    return P12, T3


def all_types(w, u, v, fr, place_k):
    """1 つの 3連単の表から 9 券種の率(dict: 券種 → 配列)。"""
    P12, T3 = tensors(w, u, v)
    S3 = T3 + T3.transpose(1, 0, 2) + T3.transpose(0, 2, 1) + T3.transpose(1, 2, 0) + T3.transpose(2, 0, 1) + T3.transpose(2, 1, 0)
    Q = P12 + P12.T
    WD = S3.sum(2)
    top2 = w + P12.sum(0)
    top3 = top2 + T3.sum((0, 1))
    Fm = (fr[:, None] == np.arange(9)[None, :]).astype(float)
    Fm[:, 0] = 0.0
    FT = Fm.T @ P12 @ Fm  # 枠単
    FQ = FT + FT.T
    FQ[np.diag_indices(9)] = np.diag(FT)  # 同じ枠の組は 1 回だけ
    return {'単勝': w, '複勝': top3 if place_k == 3 else top2, '枠連': FQ, '枠単': FT, '馬連': Q, 'ワイド': WD,
            '馬単': P12, '3連複': S3, '3連単': T3}


I17 = np.arange(17)
G2a, G2b = np.meshgrid(I17, I17, indexing='ij')
G3a, G3b, G3c = np.meshgrid(I17, I17, I17, indexing='ij')
G9a, G9b = np.meshgrid(np.arange(9), np.arange(9), indexing='ij')


def combo_mask(name, v, fr):
    """買える組(出走している馬・枠だけ・順序なしは 小 < 大 の 1 通り)。"""
    if name in ('単勝', '複勝'):
        return v.copy()
    if name in ('馬連', 'ワイド'):
        return (G2a < G2b) & v[G2a] & v[G2b]
    if name == '馬単':
        return (G2a != G2b) & v[G2a] & v[G2b]
    if name == '3連複':
        return (G3a < G3b) & (G3b < G3c) & v[G3a] & v[G3b] & v[G3c]
    if name == '3連単':
        return (G3a != G3b) & (G3a != G3c) & (G3b != G3c) & v[G3a] & v[G3b] & v[G3c]
    cnt = np.bincount(fr[v], minlength=9)
    pres = cnt > 0
    pres[0] = False
    ok = pres[G9a] & pres[G9b] & ((G9a != G9b) | (cnt[G9a] >= 2))
    return ok & (G9a <= G9b) if name == '枠連' else ok


def combo_str(name, X):
    if name in ('単勝', '複勝'):
        return [str(a) for a in X[0]]
    if len(X) == 2:
        return [f'{a}-{b}' for a, b in zip(*X)]
    return [f'{a}-{b}-{c}' for a, b, c in zip(*X)]


def race_probs(nums, p1, p3, gates):
    """研究 ticket_prob_live_all.race_probs と同じ。戻り = ({券種: (組の字の list, 確率の配列)}, 頭数, 複勝の当たりの数)"""
    W, T, FR = np.zeros(17), np.zeros(17), np.zeros(17, int)
    W[nums], T[nums], FR[nums] = p1, p3, gates
    v = W > 0
    n = int(v.sum())
    place_k = 3 if n >= 8 else 2
    w = W / W.sum()
    t = np.clip(T, 1e-4, 0.995) * v
    t = t / t.sum() * min(3, n)
    t = np.clip(t, 1e-4, 0.995) * v
    u_ = np.where(v, (w + 1e-12) ** A2 * t ** B2, 0.0)
    v_ = np.where(v, (w + 1e-12) ** A3 * t ** B3, 0.0)
    AI = all_types(w, u_, v_, FR, place_k)
    out = {}
    for c in TYPES:
        X = np.nonzero(combo_mask(c, v, FR))
        out[c] = (combo_str(c, X), AI[c][X])
    return out, n, place_k


# ================================================================ 1 R の中身
def build_doc(day, track, rno, row, gates):
    """row = 直前の行 {computed_at, runners:[{num,p1,p3}], stamp}・gates = {馬番: 枠番}。率の無い馬・枠の無い馬は None"""
    rs = [x for x in (row.get('runners') or []) if x.get('p1') is not None and float(x['p1']) > 0]
    rs.sort(key=lambda x: int(x['num']))
    nums = [int(x['num']) for x in rs]
    if len(nums) < 2 or any(not (1 <= u <= 16) for u in nums):
        return None
    if any(gates.get(u) is None for u in nums):
        return None  # 枠番が読めない = 枠連・枠単が作れない(研究も枠番が要る)
    P, n, pk = race_probs(np.array(nums), np.array([float(x['p1']) for x in rs]),
                          np.array([float(x['p3']) for x in rs]), np.array([int(gates[u]) for u in nums]))
    kinds = {}
    for c in TYPES:
        k, p = P[c]
        e = {'p': [int(x) for x in np.round(p * 1e6)]}
        if c in ('枠連', '枠単'):
            e['k'] = k
        kinds[KEYS[c]] = e
    return {'v': V, 'date': day, 'track': track, 'prefix': PREFIX.get(track, ''), 'race_no': int(rno), 'model': MODEL,
            'stamp': row.get('stamp') or '', 'computed_at': row.get('computed_at') or '',
            'built': dt.datetime.now(JST).isoformat(timespec='seconds'), 'n': n, 'place_k': pk,
            'nums': nums, 'gates': {str(u): int(gates[u]) for u in nums}, 'unit': 1e-6,
            'order': 'nums の辞書順(単勝・複勝 = nums / 馬連・ワイド a<b / 馬単 a≠b / 3連複 a<b<c / 3連単 全部違う)・枠連・枠単は k',
            'kinds': kinds}


def dump(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def path_of(day, track, rno):
    return f'{ROOT}{day}/{PREFIX[track]}-{int(rno)}.json'


# ================================================================ 読み書き(REST・service_role)
def _req(path, method='GET', body=None, headers=None, timeout=60):
    base, key = os.environ['SUPABASE_URL'].rstrip('/'), os.environ['SUPABASE_SERVICE_KEY']
    h = {'apikey': key, 'Authorization': 'Bearer ' + key, 'User-Agent': UA}
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


def last_row(day, track, rno):
    t = urllib.parse.quote(track)
    r = json.loads(_req(f'/rest/v1/nar_ai_marks?model=eq.{MODEL}&timing=eq.last&track=eq.{t}&race_date=eq.{day}&race_no=eq.{int(rno)}'
                        '&select=computed_at,runners:meta->runners,stamp:meta->>stamp') or b'[]')
    return r[0] if len(r) == 1 else None


def gates_of(day, track, rno):
    t = urllib.parse.quote(track)
    r = json.loads(_req(f'/rest/v1/nar_runs?track=eq.{t}&race_date=eq.{day}&race_no=eq.{int(rno)}&gate=not.is.null'
                        '&select=runner_number,gate') or b'[]')
    return {int(x['runner_number']): int(x['gate']) for x in r if x.get('runner_number') is not None and x.get('gate') is not None}


def done_set(day):
    """もう置いた R(便の回し直しで作り直さない)= {'DAY:場:R'}"""
    body = json.dumps({'prefix': f'{ROOT}{day}/', 'limit': 1000}).encode()
    items = json.loads(_req(f'/storage/v1/object/list/{BUCKET}', 'POST', body, {'Content-Type': 'application/json'}) or b'[]')
    back = {v: k for k, v in PREFIX.items()}
    out = set()
    for x in items:
        nm = str(x.get('name') or '')
        p, _, r = nm[:-5].partition('-') if nm.endswith('.json') else ('', '', '')
        if p in back and r.isdigit():
            out.add(f'{day}:{back[p]}:{int(r)}')
    return out


def upload(path, data):
    _req(f'/storage/v1/object/{BUCKET}/{path}', 'POST', data,
         {'Content-Type': 'application/json; charset=utf-8', 'x-upsert': 'true', 'Cache-Control': CACHE})


def publish(day, track, rno, out_dir=None):
    """固まった直前の行から作って置く。戻り = 'ok …' / 'no-last'(直前の行なし)/ 'no-gate' / 'skip'(南関の外)。例外は呼び手が受ける"""
    if track not in PREFIX:
        return 'skip'
    row = last_row(day, track, rno)
    if not row:
        return 'no-last'
    doc = build_doc(day, track, rno, row, gates_of(day, track, rno))
    if doc is None:
        return 'no-gate'
    data = dump(doc)
    if out_dir:
        p = os.path.join(out_dir, path_of(day, track, rno))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)
    else:
        upload(path_of(day, track, rno), data)
    return f'ok {len(data):,} bytes・{doc["n"]} 頭'
