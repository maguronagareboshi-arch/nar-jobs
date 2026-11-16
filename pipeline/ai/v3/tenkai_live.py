# -*- coding: utf-8 -*-
"""南関の展開図(各馬の最初の角・4 角の位置の予想)を前日に作り、公開の固定ファイルに置く(2026-11-16)。

研究 nankan-ai-v3 src/f5_scripts/tenkai_1116.py(下見)・tenkai_prod_fit_1116.py(学び)をそのまま移した(材料の式は 1 文字も変えない)。
  材料 = その馬の過去の通過順(最初の角・4 角を 0 = 先頭 〜 1 = 最後方に直した値)・前半の速さ(走破時計 − 上がり 3F のレースの中の z)・
         枠・馬番・頭数・距離・場・騎手の過去 200 走の最初の角の平均・同じレースに前へ行きたい馬が何頭いるか。
  ⛔オッズ・人気・当日の馬場・体重は使わない。予想の当たり(印・率)には一切つながない = 見せ方だけ。
  通過順の括弧 (4,6) は横並び = 同じ位置。「-」「=」は区切り(2026-04 の書き方の変化でも物差しはそろう)。
材料の元 = 前日の便 nar-ai-v3 が v3_daily(k0_dl)で落とした公式の表 V3_OFFICIAL の runs.parquet・races.parquet(DB は読まない)。
  過去の走りは 2022-01-01 から(研究と同じ)。その日の出走表も同じ runs.parquet にある(着順は空)。
模型 = 暗号化したリリース v3-tk-*(V3_TK = 開けた置き場: tk.json・tk_r1.txt・tk_r4.txt)。
置き場 = 公開バケット cond-stats の tenkai/v1/<日>/<場の英字>-<R>.json(1 R 1 本・場の英字はサイトの prefix)。
  中身 {v, date, track, prefix, race_no, model, computed_at, n, c1name, horses: [{num, gate, r1, r4, k1, k4, np}]}
  r1・r4 = 予想の位置(0 = 先頭 〜 1 = 最後方)・k1・k4 = レースの中の予想の番手(1 = 先頭)・np = 過去の走りの数。
  c1name = その場・距離で過去いちばん多い最初の角の名前(「１角」「向正面」など)。

  python -X utf8 pipeline/ai/v3/tenkai_live.py <日> [--write] [--out DIR]
    --write なし = 手元の DIR(既定 out)に書くだけ。--write = 公開バケットへ置く。
"""
import argparse
import datetime as dt
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

JST = dt.timezone(dt.timedelta(hours=9))
V = 1
BUCKET = 'cond-stats'
ROOT = 'tenkai/v1/'
CACHE = 'public, max-age=3600'
PREFIX = {'浦和': 'urawa', '船橋': 'funabashi', '大井': 'ooi', '川崎': 'kawasaki'}  # サイト js/data.js の VENUES と同じ
UA = 'nar-jobs tenkai_live (+https://yukochi.com/)'
KEY = ['track', 'race_date', 'race_no']
NK = ['大井', '川崎', '船橋', '浦和']
FROM = '2022-01-01'
OFFICIAL = Path(os.environ.get('V3_OFFICIAL', 'C:/Users/kouki/nankan_ai/v3/official'))
ASSET = Path(os.environ.get('V3_TK', 'C:/Users/kouki/nankan_ai/v3/tenkai_prod'))


def _log(*a):
    print('[tenkai]', *a, flush=True)


# ================================================================ 材料(研究 tenkai_1116.py と同じ)
def parse(order):
    """'5,(4,6),2-3' → {馬番: 位置(1〜)}。括弧の中は同じ位置。"""
    s = re.sub(r'[^0-9(),]', ',', str(order))
    pos, cnt = {}, 0
    for g in re.finditer(r'\(([^)]*)\)|(\d+)', s):
        hs = [int(x) for x in re.findall(r'\d+', g.group(1))] if g.group(1) is not None else [int(g.group(2))]
        for h in hs:
            pos.setdefault(h, cnt + 1)
        cnt += len(hs)
    return pos


def _corners(c):
    """公式の表の corners(dict の並び・numpy の配列・JSON の字のどれでも)→ [{name, order}]"""
    if c is None:
        return []
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except Exception:
            return []
    try:
        return [dict(x) for x in list(c) if x is not None and x.get('order')]
    except Exception:
        return []


def corner_name(nm):
    s = unicodedata.normalize('NFKC', str(nm or '')).replace('コーナー', '角').strip()
    return unicodedata.normalize('NFKC', s).translate(str.maketrans('1234', '１２３４')) if s else ''


def table(rn, rc):
    """研究 tenkai_1116.load の後半と同じ(元が DB の写しか公式の表かだけ違う)。"""
    rc = rc.copy()
    rn = rn.copy()
    for d in (rc, rn):
        d['race_date'] = d.race_date.astype(str).str[:10]
        d['race_no'] = d.race_no.astype(int)
    rc = rc.drop_duplicates(KEY, keep='last')
    rn = rn.drop_duplicates(KEY + ['runner_number'], keep='last')
    recs = []
    for t, d, n, c in rc[KEY + ['corners']].itertuples(index=False):
        cs = _corners(c)
        if not cs:
            continue
        p1, p4 = parse(cs[0]['order']), parse(cs[-1]['order'])
        n1, n4 = max(len(p1), 2), max(len(p4), 2)
        for h in set(p1) | set(p4):
            recs.append((t, d, n, h, p1.get(h, np.nan), p4.get(h, np.nan),
                         (p1[h] - 1) / (n1 - 1) if h in p1 else np.nan, (p4[h] - 1) / (n4 - 1) if h in p4 else np.nan,
                         corner_name(cs[0].get('name'))))
    cp = pd.DataFrame(recs, columns=KEY + ['runner_number', 'c1', 'c4', 'r1', 'r4', 'c1name'])
    X = rn.merge(rc[KEY + ['distance_m', 'field_size']], on=KEY, how='left').merge(cp, on=KEY + ['runner_number'], how='left')
    X = X[X.horse_name.notna()].copy()
    X['front'] = X.time_sec - X.last3f
    g = X.groupby(KEY).front
    X['front_z'] = (X.front - g.transform('mean')) / g.transform('std').replace(0, np.nan)
    return X.sort_values(['race_date', 'track', 'race_no', 'runner_number']).reset_index(drop=True)


def feats(X):
    X = X.copy()
    X['di'] = pd.to_datetime(X.race_date).map(pd.Timestamp.toordinal)
    hg = X.groupby('horse_name')
    for k in ['r1', 'r4', 'front_z', 'distance_m', 'track']:
        X['prev1_' + k] = hg[k].shift(1)
    X['prev2_r1'] = hg.r1.shift(2)
    for k in ['r1', 'r4', 'front_z']:
        X['m5_' + k] = hg[k].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    X['min5_r1'] = hg.r1.transform(lambda s: s.shift(1).rolling(5, min_periods=1).min())
    X['lead5'] = hg.c1.transform(lambda s: (s == 1).astype(float).where(s.notna()).shift(1).rolling(5, min_periods=1).mean())
    X['n_prev'] = hg.cumcount()
    X['gap_days'] = X.di - hg.di.shift(1)
    X['d_dist'] = X.distance_m - X.prev1_distance_m
    X['same_track'] = (X.track == X.prev1_track).astype(float)
    X['jk_r1'] = X.groupby('jockey').r1.transform(lambda s: s.shift(1).rolling(200, min_periods=20).mean())
    X['ub_rel'] = X.runner_number / X.field_size
    rg = X.groupby(KEY)
    for k in ['m5_r1', 'prev1_r1', 'm5_front_z', 'lead5']:
        X['rk_' + k] = rg[k].rank(pct=True)
    X['n_leaders'] = rg.lead5.transform(lambda s: (s >= 0.4).sum())
    X['trk'] = X.track.map({t: i for i, t in enumerate(NK)}).fillna(-1)
    return X


# ================================================================ 予想
def load_official(day, off=None):
    off = Path(off or OFFICIAL)
    rn = pd.read_parquet(off / 'runs.parquet', columns=KEY + ['runner_number', 'gate', 'horse_name', 'jockey', 'finish', 'time_sec', 'last3f'])
    rc = pd.read_parquet(off / 'races.parquet', columns=KEY + ['distance_m', 'field_size', 'corners'])
    for d in (rn, rc):
        d['race_date'] = d.race_date.astype(str).str[:10]
    rn = rn[(rn.race_date >= FROM) & (rn.race_date <= day)]
    rc = rc[(rc.race_date >= FROM) & (rc.race_date <= day)]
    return rn, rc


def models(asset=None):
    import lightgbm as lgb
    d = Path(asset or ASSET)
    m = json.loads((d / 'tk.json').read_text(encoding='utf-8'))
    m['M'] = {t: lgb.Booster(model_file=str(d / f)) for t, f in m['files'].items()}
    return m


def predict(day, off=None, asset=None, M=None):
    """その日の南関の出走馬ごとの予想の位置(pred_r1・pred_r4)と、場・距離ごとの最初の角の名前。"""
    M = M or models(asset)
    rn, rc = load_official(day, off)
    X = feats(table(rn, rc))
    D = X[(X.race_date == day) & X.track.isin(NK)].copy()
    if not len(D):
        return D, {}
    for t in ['r1', 'r4']:
        D['pred_' + t] = M['M'][t].predict(D[M['FC']].astype(float))
    H = X[(X.race_date < day) & X.track.isin(NK) & X.c1name.notna() & (X.c1name != '')]
    names = H.drop_duplicates(KEY).groupby(['track', 'distance_m']).c1name.agg(lambda s: s.value_counts().index[0]).to_dict()
    return D, names


def build_doc(day, track, rno, g, names, tag):
    g = g.sort_values('runner_number')
    if len(g) < 2 or g.pred_r1.isna().any():
        return None
    k1 = g.pred_r1.rank(method='first').astype(int)
    k4 = g.pred_r4.rank(method='first').astype(int)
    hs = []
    for (_, r), a, b in zip(g.iterrows(), k1, k4):
        hs.append({'num': int(r.runner_number), 'gate': int(r.gate) if pd.notna(r.gate) else None,
                   'r1': round(float(r.pred_r1), 4), 'r4': round(float(r.pred_r4), 4), 'k1': int(a), 'k4': int(b), 'np': int(r.n_prev)})
    dist = g.distance_m.iloc[0]
    return {'v': V, 'date': day, 'track': track, 'prefix': PREFIX[track], 'race_no': int(rno), 'model': tag,
            'computed_at': dt.datetime.now(JST).isoformat(timespec='seconds'), 'n': len(hs),
            'distance_m': int(dist) if pd.notna(dist) else None, 'c1name': names.get((track, dist), '') or '最初の角', 'horses': hs}


def dump(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def path_of(day, track, rno):
    return f'{ROOT}{day}/{PREFIX[track]}-{int(rno)}.json'


# ================================================================ 書き込み(Storage・service_role。DB の表は読まない・書かない)
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


def upload(path, data):
    _req(f'/storage/v1/object/{BUCKET}/{path}', 'POST', data,
         {'Content-Type': 'application/json; charset=utf-8', 'x-upsert': 'true', 'Cache-Control': CACHE})


def run(day, write=False, out_dir='out', off=None, asset=None):
    """入口(便から呼ぶ)。戻り = 置いた R の数。"""
    t0 = time.time()
    M = models(asset)
    D, names = predict(day, off, asset, M)
    _log(day, '出走', len(D), '頭', D.groupby(KEY).ngroups if len(D) else 0, 'R', f'{time.time() - t0:.0f}s')
    n = 0
    for (t, d, rno), g in D.groupby(KEY):
        doc = build_doc(day, t, rno, g, names, M['tag'])
        if doc is None:
            _log(t, rno, 'R 作れない(材料の欠け)')
            continue
        data = dump(doc)
        if write:
            upload(path_of(day, t, rno), data)
        else:
            p = Path(out_dir) / path_of(day, t, rno)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        n += 1
    _log('置いた', n, 'R', 'バケット' if write else out_dir, f'{time.time() - t0:.0f}s')
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('day')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--out', default='out')
    a = ap.parse_args()
    run(a.day, a.write, a.out)


if __name__ == '__main__':
    main()
