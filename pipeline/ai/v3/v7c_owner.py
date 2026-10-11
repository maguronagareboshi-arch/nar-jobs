# -*- coding: utf-8 -*-
"""馬主 = 走った時の馬主(nankan-ai-v3 DESIGN 決め 23・2026-10-11)。v7c_run.build が呼ぶ。

研究 src/f5_scripts/own_rt.py の feat と同じ決まり:
  南関の走り = KDSCOPE SE の写し(v3/kd/kd_se_owner_nankan.parquet・〜その最後の日)の馬主。
  写しより後の南関の走りと作る行 q = DB の馬主(nar_horses の今の馬主から、その日より後の owner_change を戻した値)。
    名前は法人の印((株)(有)…)を外し、写しの名前に前方一致で寄せる(写しは長い名前が途中で切れている)。
  南関の馬主がある馬の他場の走り = 前の一番近い南関の走りの馬主・南関に来る前は数えない(空)・南関を出た後は台帳のまま。
どれも取れない行は台帳の馬主のまま。
"""
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from v7c_run import KEY, V3

OWN_KD = Path(os.environ.get('V3_KD') or V3 / 'kd') / 'kd_se_owner_nankan.parquet'  # 便は V3_KD = v3/kd(V3_DATA = v3/v3_data とは別)
NANKAN4 = ('浦和', '船橋', '大井', '川崎')
RE_CORP = re.compile(r'\((株|有|同|合|資|名|医|財|社|一社|一財|公財|組)\)|^組\)')
K4 = KEY + ['umaban']


def _rest(table, params):
    base = os.environ.get('SUPABASE_URL') or os.environ.get('NAR_SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('NAR_SUPABASE_SERVICE_KEY')
    if not (base and key):
        raise RuntimeError('DB の鍵が無い')
    req = urllib.request.Request(f"{base.rstrip('/')}/rest/v1/{table}?{urllib.parse.urlencode(params)}",
                                 headers={'apikey': key, 'Authorization': f'Bearer {key}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def db_owner_asof(names, lo, days):
    """馬名 → {日付: その日の馬主}。"""
    names = sorted({n for n in names if isinstance(n, str) and n})
    cur = {}
    for i in range(0, len(names), 100):
        q = 'in.(' + ','.join('"' + n.replace('"', '') + '"' for n in names[i:i + 100]) + ')'
        for x in _rest('nar_horses', [('select', 'horse_name,owner'), ('horse_name', q), ('limit', '5000')]):
            cur[x['horse_name']] = x['owner']
    ch = _rest('nar_horse_changes', [('select', 'horse_name,race_date,from_value'), ('kind', 'eq.owner_change'),
                                     ('race_date', f'gt.{lo}'), ('order', 'race_date.desc'), ('limit', '50000')])
    hist = {}
    for c in ch:  # 新しい順
        hist.setdefault(c['horse_name'], []).append(c)
    out = {}
    for n, o0 in cur.items():
        out[n] = {}
        for d in days:
            o = o0
            for c in hist.get(n, []):
                if c['race_date'] > d:
                    o = c['from_value']
            out[n][d] = o
    return out


def owner_rt(r, q, h, norm):
    if not OWN_KD.exists():
        raise RuntimeError(f'写しが無い {OWN_KD}')
    KD = pd.read_parquet(OWN_KD)
    kmax = str(KD.race_date.max())[:10]
    keys = set(KD.owner.dropna())
    pre = sorted((k for k in keys if len(k) >= 4), key=len, reverse=True)

    def fit(s):
        s = norm(s)
        if not isinstance(s, str):
            return None
        s = RE_CORP.sub('', s)
        if s in keys:
            return s
        return next((k for k in pre if s.startswith(k)), s)

    OT = KD.drop_duplicates(K4, keep='last').set_index(K4).owner
    nm = h.drop_duplicates(K4)[K4 + ['horse_name']]
    nm = nm.assign(race_no=nm.race_no.astype(int), umaban=nm.umaban.astype(int))
    st = []
    for X in (r, q):
        k = X[K4].assign(race_no=X.race_no.astype(int), umaban=X.umaban.astype(int))
        t = OT.reindex(pd.MultiIndex.from_frame(k)).to_numpy().astype(object)
        dd = X.race_date.astype(str).str[:10].to_numpy()
        late = X.track.isin(NANKAN4).to_numpy() & pd.isna(t) & (dd > kmax)
        n = k.merge(nm, on=K4, how='left').horse_name.to_numpy()
        st.append((t, dd, late, n))
    names = np.concatenate([n[late] for t, dd, late, n in st])
    days = sorted(set(np.concatenate([dd[late] for t, dd, late, n in st])))
    db = db_owner_asof(names, kmax, days) if len(names) else {}
    info = {}
    for X, lab, (t, dd, late, n) in ((r, 'r', st[0]), (q, 'q', st[1])):
        for i in np.flatnonzero(late):
            o = db.get(n[i], {}).get(dd[i])
            if o:
                t[i] = fit(o)
        m = pd.notna(t)
        X.loc[m, 'owner'] = t[m]
        info[lab] = {'替えた': int(m.sum()), '行': len(X), '写しの後 DB': int((m & late).sum()), '写しの後 取れない': int((~m & late).sum())}
        if X is r:
            oth = ~X.track.isin(NANKAN4).to_numpy()
            last = pd.Series(np.where(m, X.dnum.to_numpy(float), np.nan), index=X.index).groupby(X.hid).transform('max').to_numpy()
            w = oth & (X.dnum.to_numpy(float) < last)
            ff = pd.Series(np.where(m, X.owner.to_numpy(object), None), index=X.index).groupby(X.hid).ffill()  # r は hid・日付の順
            X.loc[w, 'owner'] = ff[w].to_numpy()
            info['他場'] = {'替えた': int(w.sum()), '空(南関に来る前)': int((w & ff.isna().to_numpy()).sum())}
    info['写しの最後の日'] = kmax
    return info
