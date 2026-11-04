# -*- coding: utf-8 -*-
"""南関 枠の内外の最近の有利の直し(決め 68・研究 nankan-ai-v3 src/f5_scripts/gate68_judge.py・out/gate68_judge.md・ユーザー採用 2026-11-03)。

最後の割り直しの後・勝つ率の守り(決め 67-2)の前に、最終の勝つ率 p1・3 着内の率 p3 に a = a56 + a開催 を足す:
    群    = 場 × 枠(馬番 ÷ 頭数で R の中の位置 (馬番 − 1) ÷ (頭数 − 1)・内 ≤ 1/3・中 ≤ 2/3・外)。頭数 = その R の馬番の最大(取消を除く)
    a56   = 群の前 WIN 日の Σ(実際の 3 着内 − p3) ÷ (Σ p3(1 − p3) + LAM56)、±1 で切る
    a開催 = 同じ開催(同じ場で間 GAP 日以内に続く開催日)の前の日までの同じ量 ÷ (… + LAMM)、±1 で切る。開催の最初の日は 0
    p3′ = sig(logit p3 + a)(合計 3 に割り直さない)・p1′ = p1 × e^a を R で合計 1 に
窓の終わり(含まない): 直前版 = その日・前日版 = 前の日(前日 14:30 に前の日の結果は無い)。直前版の便の時に前の日の結果が DB に
そろっていない場は、その場だけ前日版と同じ窓に落とす(決め書 §9)。
窓の率 = その日に出した行の直しの前の p3(meta.g68.p0・無い行 = 第 22 版までの行は meta.runners の p3)。直前版の窓は直前の行
(直前の行が無い R は朝の行)・前日版の窓は朝の行。DB に行の無い R(2026-09 = 南関の v3-9 の行が 9/30 より前に無い)は、
第22版の前日の便を手元で回し直した前日版の率(暗号化の定数の g68_sept.csv)で埋める(直前版の窓も同じ前日版の率)。答え = 本番 DB の nar_runs(取消・除外を除く・競走中止は着外として残す)。
開催日 = nar_races の取りやめでないレースのある日 + 答えのある日。重み・学びは無い。
定数(WIN・LAM56・LAMM・GAP・TAG)は暗号化したリリース v3-consts の consts.json の g68(公開のコードに数を置かない)。
"""
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed

TRACKS = ('大井', '川崎', '船橋', '浦和')
GT = ('内', '中', '外')
DROP = ('取消', '除外')   # finish_note にこの字があれば窓に入れない(出走取消・競走除外も)
KEEP = ('中止', '失格')   # 着順の無い馬のうち着外で残す馬(競走中止・失格)。着順も字も無い馬(結果がまだ入っていない)は入れない
KEY = ['track', 'race_date', 'race_no']
MIN_N = 5                # 窓に入れる R・直しを足す R の頭数の下限(研究の数える表 = 5 頭以上の R だけ)
MK = {1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}  # seqpre_live.MK と同じ
SEPT = 'g68_sept.csv'    # 窓の元の補い(DB に南関の印の行が無い 2026-09 の第22版の前日版の率・研究 src/f5_scripts/gate68_sept_run.py)
_C = None


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('g68')
    return _C


def tag():
    return consts()['TAG']


# ------------------------------------------------------------------ 式(研究 gate68_judge.gate・shifts・apply と同じ)
def groups(nums):
    """1 レースの馬番 → 内・中・外(頭数 = 馬番の最大)"""
    u = np.asarray(list(nums), float)
    rel = (u - 1) / max(float(u.max()) - 1, 1)
    return list(np.select([rel <= 1 / 3, rel <= 2 / 3], ['内', '中'], '外'))


def meet_start(days, day):
    """場の開催日の並び days(day を含む)→ day の開催の最初の日(間 GAP 日より空いたら別の開催)"""
    gap = int(consts()['GAP'])
    d = sorted(x for x in set(days) if x <= day)
    i = d.index(day)
    while i > 0 and (pd.Timestamp(d[i]) - pd.Timestamp(d[i - 1])).days <= gap:
        i -= 1
    return d[i]


def table(D, days, day, lag):
    """D = 窓の行(track・race_date・gt・Y3・p3)・days = {場: 開催日の並び} → {(場, 群): (a, a56, a開催)}。
    lag = 0(直前版)/1(前日版)・場ごとの lag は dict でも可。"""
    C = consts()
    win, l56, lm = int(C['WIN']), float(C['LAM56']), float(C['LAMM'])
    D = D.assign(r=D.Y3 - D.p3, w=D.p3 * (1 - D.p3))
    s = D.groupby(['track', 'gt', 'race_date'])[['r', 'w']].sum()
    T = {}
    for t in TRACKS:
        if t not in days or day not in days[t]:
            continue
        lg_ = lag.get(t, 1) if isinstance(lag, dict) else lag
        hi = (pd.Timestamp(day) - pd.Timedelta(days=lg_)).strftime('%Y-%m-%d')
        lo = (pd.Timestamp(hi) - pd.Timedelta(days=win)).strftime('%Y-%m-%d')
        ms = meet_start(days[t], day)
        for g in GT:
            try:
                x = s.loc[(t, g)]
            except KeyError:
                x = pd.DataFrame({'r': [], 'w': []}, index=pd.Index([], name='race_date'))
            ix = x.index.to_numpy().astype(str)
            a = x[(ix >= lo) & (ix < hi)].sum()
            m = x[(ix >= ms) & (ix < hi)].sum()
            a56 = float(np.clip(a.r / (a.w + l56), -1, 1))
            am = float(np.clip(m.r / (m.w + lm), -1, 1))
            T[(t, g)] = (a56 + am, a56, am)
    return T


def shift(p1, p3, a):
    """1 レース: 勝つ率 p1・3 着内の率 p3(合計 3 にそろえた後)・馬ごとの a → (p1′, p3′)"""
    a = np.asarray(a, float)
    e = np.log(np.clip(np.asarray(p1, float), 1e-12, 1)) + a
    w = np.exp(e - e.max())
    z = np.clip(np.asarray(p3, float), 1e-9, 1 - 1e-9)
    return w / w.sum(), 1 / (1 + np.exp(-(np.log(z / (1 - z)) + a)))


def race_a(G, track, nums):
    """その日の表 G(load の戻り)→ 馬ごとの a(場が表に無ければ None)"""
    if G is None or len(nums) < MIN_N or not any(k[0] == track for k in G['T']):
        return None
    return np.array([G['T'][(track, g)][0] for g in groups(nums)], float)


# ------------------------------------------------------------------ 本番 DB を読む(読むだけ)
def _creds():
    import os
    base = os.environ.get('SUPABASE_URL') or os.environ.get('NAR_SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('NAR_SUPABASE_SERVICE_KEY')
    if not base or not key:
        raise RuntimeError('DB の鍵が無い')
    return base.rstrip('/'), key


def _get_all(path):
    base, key = _creds()
    out, off = [], 0
    while True:
        req = urllib.request.Request(f'{base}{path}&limit=1000&offset={off}',
                                     headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai-v3'})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read().decode('utf-8'))
        out += got
        if len(got) < 1000:
            return out
        off += 1000


def fetch(d0, day, timing):
    """窓の元 3 つ(DB): 印の行・答え・開催日。d0 ≤ race_date < day(開催日は day まで)"""
    tq = urllib.parse.quote(','.join(TRACKS))
    tm = 'morning' if timing == 'morning' else 'morning,last'
    marks = _get_all(f'/rest/v1/nar_ai_marks?select=track,race_date,race_no,timing,runners:meta->runners,p0:meta->g68->p0'
                     f'&model=eq.v3-9&timing=in.({tm})&track=in.({tq})&race_date=gte.{d0}&race_date=lt.{day}&order=race_date,track,race_no,timing')
    runs = _get_all(f'/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,finish,finish_note'
                    f'&track=in.({tq})&race_date=gte.{d0}&race_date=lt.{day}&order=race_date,track,race_no,runner_number')
    races = _get_all(f'/rest/v1/nar_races?select=track,race_date,race_no,cancelled'
                     f'&track=in.({tq})&race_date=gte.{d0}&race_date=lte.{day}&order=race_date,track,race_no')
    return marks, runs, races


def sept_rows():
    """DB に南関の印の行が無い頃(2026-09)の第22版の前日版の率(手元で作り直した表・暗号化の定数の g68_sept.csv)"""
    import sealed
    x = pd.read_csv(sealed.path(SEPT), dtype={'track': str, 'race_date': str})
    return x.assign(race_no=x.race_no.astype(int), umaban=x.umaban.astype(int), p3=x.p3.astype(float))


def window_rows(marks, timing, sept=None):
    """印の行 → 馬ごとの直しの前の p3(track・race_date・race_no・umaban・p3・src)。直前版は直前の行(無い R は朝の行)。
    DB に行が無い R は 9 月の表(sept = sept_rows())から読む(src = sp・直前版の窓も前日版の率で代わり = sp_mo)"""
    best = {}
    for r in marks:
        if timing == 'morning' and r['timing'] != 'morning':
            continue
        k = (r['track'], str(r['race_date'])[:10], int(r['race_no']))
        if k not in best or r['timing'] == 'last':
            best[k] = r
    rows = []
    for (t, d, rn), r in best.items():
        p0 = r.get('p0') or {}
        for x in (r.get('runners') or []):
            n = int(x['num'])
            g = p0.get(str(n), x.get('p3'))
            if g is not None:
                rows.append((t, d, rn, n, float(g), ('g0' if str(n) in p0 else 'p3') + ('' if r['timing'] == timing else '_mo')))
    W = pd.DataFrame(rows, columns=['track', 'race_date', 'race_no', 'umaban', 'p3', 'src'])
    if sept is not None and len(sept):
        s = sept.merge(W[KEY].drop_duplicates().assign(_db=1), on=KEY, how='left')
        s = s[s._db.isna()][KEY + ['umaban', 'p3']].assign(src='sp' + ('' if timing == 'morning' else '_mo'))
        W = pd.concat([W, s], ignore_index=True)
    return W


def answers(runs, min_n=MIN_N):
    """nar_runs → 数える馬(取消・除外を除く・5 頭以上の R)・3 着内・枠の群(数える馬の馬番の最大で)"""
    ru = pd.DataFrame(runs, columns=['track', 'race_date', 'race_no', 'runner_number', 'finish', 'finish_note'])
    ru['race_date'] = ru.race_date.astype(str).str[:10]
    note = ru.finish_note.fillna('').astype(str)
    fin = pd.to_numeric(ru.finish, errors='coerce')
    ru = ru[~note.str.contains('|'.join(DROP)) & (fin.notna() | note.str.contains('|'.join(KEEP))) & ru.runner_number.notna()].copy()
    ru['umaban'] = pd.to_numeric(ru.runner_number, errors='coerce').astype(int)
    ru['race_no'] = ru.race_no.astype(int)
    ru = ru.drop_duplicates(['track', 'race_date', 'race_no', 'umaban'])
    ru['Y3'] = (pd.to_numeric(ru.finish, errors='coerce') <= 3).astype(float)
    ru = ru[ru.groupby(KEY).umaban.transform('size') >= min_n].copy()
    mx = ru.groupby(KEY).umaban.transform('max').astype(float)
    rel = (ru.umaban - 1) / np.maximum(mx - 1, 1)
    ru['gt'] = np.select([rel <= 1 / 3, rel <= 2 / 3], ['内', '中'], '外')
    return ru[KEY + ['umaban', 'gt', 'Y3']]


def race_days(races, ans, day):
    """{場: 開催日の並び}(取りやめでないレースのある日 + 答えのある日 + その日)"""
    ra = pd.DataFrame(races, columns=['track', 'race_date', 'race_no', 'cancelled'])
    ra['race_date'] = ra.race_date.astype(str).str[:10]
    ok = ra[ra.cancelled.fillna('').astype(str).str.strip() == '']
    out = {}
    for t in TRACKS:
        s = set(ok.race_date[ok.track == t]) | set(ans.race_date[ans.track == t])
        if day in set(ra.race_date[ra.track == t]):
            s.add(day)
        out[t] = sorted(x for x in s if x <= day)
    return out


def build(marks, runs, races, day, timing):
    """DB の 3 つ → その日の表 {'T': {(場, 群): (a, a56, a開催)}, 'lag': {場: 0/1}, 'st': 数}"""
    ans = answers(runs)
    done = answers([r for r in runs if str(r['race_date'])[:10] == (pd.Timestamp(day) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')], 1)  # 前の日の結果の入った R
    days = race_days(races, ans, day)
    W = window_rows(marks, timing, sept_rows())
    D = W.merge(ans, on=KEY + ['umaban'], how='inner')
    lag = {}
    prev = (pd.Timestamp(day) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    ra = pd.DataFrame(races, columns=['track', 'race_date', 'race_no', 'cancelled'])
    ra['race_date'] = ra.race_date.astype(str).str[:10]
    for t in TRACKS:
        if timing == 'morning':
            lag[t] = 1
            continue
        want = ra[(ra.track == t) & (ra.race_date == prev) & (ra.cancelled.fillna('').astype(str).str.strip() == '')].race_no.nunique()
        got = done[(done.track == t) & (done.race_date == prev)].race_no.nunique()
        lag[t] = 0 if got >= want else 1   # 前の日の結果がそろっていない場 = 前日版と同じ窓
    T = table(D, days, day, lag)
    nR = W[KEY].drop_duplicates()
    no_ans = int(len(nR.merge(ans[KEY].drop_duplicates(), how='left', indicator=True).query('_merge == "left_only"')))
    st = {'rows': int(len(D)), 'R': int(D[KEY].drop_duplicates().shape[0]), 'g0': int((D.src.str.startswith('g0')).sum()),
          'sp': int(D.src.str.startswith('sp').sum()), 'd0': (str(D.race_date.min()) if len(D) else None),
          'mo': int(D.src.str.endswith('_mo').sum()), 'no_ans_R': no_ans,
          'lag1': sorted(t for t, v in lag.items() if v and t in {k[0] for k in T})}
    return {'T': T, 'lag': lag, 'st': st, 'timing': timing, 'day': day}


def load(day, timing, log=print):
    """便で 1 回: その日(day)の表。timing = 'last'(直前版)/ 'morning'(前日版)。読めなければ例外(呼ぶ側で直しを足さない)"""
    win = int(consts()['WIN'])
    d0 = (dt.date.fromisoformat(day) - dt.timedelta(days=win + 1)).isoformat()
    G = build(*fetch(d0, day, timing), day, timing)
    log('枠の内外の有利', timing, '窓の行', G['st'], '・a', {f'{t}{g}': round(v[0], 3) for (t, g), v in sorted(G['T'].items())})
    return G


def meta(G, track, nums, a, p1_0, p3_0):
    """行の meta.g68(直しの前の率 p0・q0 は次の日からの窓の元)"""
    return {'tag': tag(), 'lag': int(G['lag'].get(track, 1)), 'a': {str(int(n)): round(float(x), 4) for n, x in zip(nums, a)},
            'p0': {str(int(n)): round(float(x), 6) for n, x in zip(nums, p3_0)},
            'q0': {str(int(n)): round(float(x), 6) for n, x in zip(nums, p1_0)}}


def apply_csv_pre(G, csv_path, log=print):
    """前日版の表の CSV(前日版の並び読みの後・勝つ率の守りの前)を直す: p1・p3p(元は p1_g0・p3p_g0)・g68_a・rank・mark。→ 直したレース数"""
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p1_g0' in x.columns:  # 2 度かけない
        log('枠の内外の有利 済み')
        return int(x.groupby(KEY).g68_a.apply(lambda s: s.notna().all()).sum())
    x['p1_g0'], x['p3p_g0'], x['g68_a'] = x.p1, x.p3p, np.nan
    n = 0
    for (tr, _, _), g in x.groupby(KEY, sort=False):
        a = race_a(G, tr, g.umaban.astype(int).to_numpy())
        if a is None:
            continue
        q, p = shift(g.p1.to_numpy(float), g.p3p.to_numpy(float), a)
        x.loc[g.index, 'p1'], x.loc[g.index, 'p3p'], x.loc[g.index, 'g68_a'] = q, p, a
        n += 1
    o = x.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map(MK).fillna('')
    x = x.sort_values(KEY + ['rank'], kind='mergesort')
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    top = lambda c: x.loc[x.groupby(KEY, sort=False)[c].idxmax(), KEY + ['umaban']].set_index(KEY).umaban  # noqa: E731
    log('枠の内外の有利 足した', n, 'R・本命が替わった', int((top('p3p') != top('p3p_g0')).sum()), 'R')
    return n
