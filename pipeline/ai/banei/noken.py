# -*- coding: utf-8 -*-
"""ばんえい 第 4 版の能力検査(2026-10-29・ばんえい 決め 8・例外採用 = v3 の src/banei/noken_pre.noken と noken_check.base の写し)。

能検の表(DB nar_meta key=banei_noken・手元 BANEI_LOCAL=1 は v3/banei_kb/noken/banei_noken_days.json)を平らにし、
  nk_z = 同じ能検の日の中での時計の速さ(速いほど +・日の中の標準化)・合格 = 合否の欄があればそれ・無ければ時計があり中止等でない
→ ±zclip で切る → レースより前(当日を除く)maxdays 日以内の最後の合格の回を馬名(NFKC・空白なし)で結ぶ
→ 走った数 0(a12_runs == 0)の馬だけ nk を返す(他は 0)。z に b × nk を足すのは banei_v3.score。
b・maxdays・zclip は公開のコードに書かない = 固めた表の banei_kb/banei_noken.json({b, maxdays, zclip})。毎年 9 月に学び直す。
"""
import json
import os
import unicodedata

import numpy as np
import pandas as pd

import feat_v1 as f1


def params():
    return json.load(open(os.environ.get('BANEI_NOKEN', f1.OUT + 'banei_noken.json'), encoding='utf-8'))


def nm(x):
    return unicodedata.normalize('NFKC', str(x or '')).replace(' ', '').replace('　', '').strip()


def secs(x):
    x = str(x or '').strip()
    try:
        p = x.split(':')
        return float(p[0]) * 60 + float(p[1]) if len(p) == 2 else float(p[0])
    except ValueError:
        return np.nan


def days():
    if os.environ.get('BANEI_LOCAL') == '1':
        return json.load(open(f1.OUT + 'noken/banei_noken_days.json', encoding='utf-8'))
    import bn_kb
    r = bn_kb.rest('/rest/v1/nar_meta?select=value&key=eq.banei_noken')
    return (r[0]['value'] or {}).get('days') or [] if r else []


def table(ds):
    """研究の noken_fetch(平らにする)+ noken_pre.noken(合格・日の中の標準化)と同じ。"""
    rows = []
    for d in ds:
        for ri, r in enumerate(d.get('races') or []):
            for x in r.get('rows') or []:
                rows.append({'date': d.get('date'), 'ri': ri, **x})
    t = pd.DataFrame(rows)
    for c in ('name', 'time', 'status', 'ok'):
        if c not in t:
            t[c] = None
    t['name'] = t['name'].map(nm); t['sec'] = t['time'].map(secs)
    t['date'] = pd.to_datetime(t['date']).dt.strftime('%Y-%m-%d')
    st = t['status'].fillna('')
    okc = t['ok']
    t['pass'] = np.where(okc.notna(), okc.fillna('').astype(str).str.contains('[○〇]'), t.sec.notna() & (st == ''))
    g = t[t.sec.notna()].groupby('date').sec
    t['nk_z'] = -(t.sec - g.transform('mean').reindex(t.index)) / g.transform('std').reindex(t.index)
    return t


def nk_of(today, P=None):
    """today = 当日の行(race_date・race_no・runner_number・horse_name・a12_runs)。返り = 同じ順の nk(新馬で能検の値が無い・新馬でない = 0)と結べた頭数。"""
    P = P or params()
    t = table(days())
    t = t[t['pass'] & t.nk_z.notna()].assign(nd=lambda q: pd.to_datetime(q.date)).sort_values('nd')
    x = today[['race_date', 'horse_name', 'a12_runs']].copy()
    x['name'] = x.horse_name.map(nm); x['rd'] = pd.to_datetime(x.race_date)
    m = pd.merge_asof(x.reset_index().sort_values('rd'), t[['name', 'nd', 'nk_z']], left_on='rd', right_on='nd', by='name',
                      direction='backward', allow_exact_matches=False,
                      tolerance=pd.Timedelta(days=int(P['maxdays']))).set_index('index').loc[x.index]
    nk = np.where(x.a12_runs.to_numpy() == 0, m.nk_z.clip(-float(P['zclip']), float(P['zclip'])).to_numpy(), np.nan)
    return np.nan_to_num(nk.astype(float)), int(np.isfinite(nk).sum()), int((x.a12_runs == 0).sum()), len(t)
