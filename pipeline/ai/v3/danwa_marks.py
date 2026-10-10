# -*- coding: utf-8 -*-
"""厩舎談話の印(◎○△)の 3 定数を第10版の 3 着内の率に足す(研究 nankan-ai-v3 v13y・2026-10-03)。

研究: 決め書 out/v13y_plan.md → src/v13y_run.py(1 回だけ・結果 out/v13y.md)。木(9 項目)は通ったが 3 定数をはっきり上回らず = 3 定数。
     9 月の新しい期間(2026-09-01〜09-23・180 R)= src/v13y_sept.py → out/v13y_sept.md(−2 誤差より悪くない)。
足し方: logit(p3′) + 定数 → 合計 3 にそろえ直す(t6_base.p3prime と同じ)。p1(勝つ率)は変えない。p3′ ≥ p1 にする。
       談話が無い馬は 0(足さない)。談話が 1 頭も無いレースは第10版のまま。
談話の元: ① 本番の表 nar_kb_danwa(読むだけ・手元の毎日の取り込みが書く)
         ② ① に無い南関のレースは競馬ブックの厩舎の話の頁を直接読む(KEIBABOOK_LOGIN_ID・PASSWORD があるときだけ・cloud/kb の部品)。
         印 = raw の先頭の字(◎ ○ 〇 △)。研究の k_mk と同じ(船橋 9/28〜10/2 の 671 頭で一致を確かめた)。
⛔DB には書かない。鍵は印字しない。失敗したら呼び手が第10版のまま進める。
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TRACKS = ['大井', '川崎', '船橋', '浦和']
Q4 = ['track', 'race_date', 'race_no', 'umaban']
TX = ['raw', 'headline', 'trainer', 'comment']  # 束 t14 の談話 14 列が本文と話し手を使う(印の 3 定数は raw だけ)
LAST = {}  # load が読んだ日の全列(日付 → 表)。t14_bundle が使い回す(競馬ブックの頁を 2 度読まない)
CONST = {'◎': 0.2006, '○': 0.0219, '〇': 0.0219, '△': -0.2308}  # v13y_res.json の const(学び 2018-05〜19・2022・n/(n+200) で縮めた値)
STAMP = '談話の印 3 定数(v13y)'


def _db(day):
    base = os.environ.get('SUPABASE_URL') or os.environ.get('NAR_SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('NAR_SUPABASE_SERVICE_KEY')
    if not (base and key):
        return pd.DataFrame(columns=Q4 + TX)
    q = urllib.parse.urlencode([('select', ','.join(Q4 + TX)), ('race_date', f'eq.{day}'),
                                ('track', 'in.(' + ','.join(TRACKS) + ')'), ('limit', '2000')])
    req = urllib.request.Request(f"{base.rstrip('/')}/rest/v1/nar_kb_danwa?{q}", headers={'apikey': key, 'Authorization': f'Bearer {key}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return pd.DataFrame(json.loads(r.read().decode('utf-8')), columns=Q4 + TX)


def _kb(day, have, log):
    """競馬ブックの頁から、have(場, R)に無い南関のレースの談話を読む。"""
    if not os.environ.get('KEIBABOOK_LOGIN_ID'):
        return pd.DataFrame(columns=Q4 + TX)
    sys.path.insert(0, str(HERE.parents[2] / 'cloud' / 'kb'))
    from keibabook import KeibabookClient
    from parsers import parse_danwa, parse_nittei
    d = Path(os.environ.get('KB_DATA_DIR', '/tmp/kbdata_v3'))
    c = KeibabookClient(login_id=os.environ.get('KEIBABOOK_LOGIN_ID'), password=os.environ.get('KEIBABOOK_PASSWORD'),
                        data_dir=d, wait_seconds=float(os.environ.get('FETCH_WAIT_SECONDS', '2.5')))
    c.ensure_login()
    ymd = day.replace('-', '')
    meets = parse_nittei(c.get(c.nittei_path(ymd), refresh=True))
    rows = []
    for m in meets:
        tr = next((t for t in TRACKS if t in m['track']), None)
        if tr is None:
            continue
        for r in m['races']:
            if r['race_id'][12:16] != ymd[4:8] or (tr, int(r['race_no'])) in have:
                continue
            try:
                p = parse_danwa(c.get(c.danwa_path(r['race_id']), refresh=True), r['race_id'])
            except Exception as e:  # noqa: BLE001
                log('談話 頁 失敗', tr, r['race_no'], type(e).__name__)
                continue
            rows += [{'track': tr, 'race_date': day, 'race_no': int(r['race_no']), 'umaban': int(h['umaban']), 'raw': h.get('raw') or '',
                      'headline': h.get('headline'), 'trainer': h.get('trainer'), 'comment': h.get('comment')}
                     for h in p['horses'] if h.get('umaban')]
    return pd.DataFrame(rows, columns=Q4 + TX)


def load(day, log=print):
    """→ 1 馬 1 行: Q4・dw_mk(◎○△ か空)・dw_u(足す定数・談話が無ければ欠け)。全列(本文・話し手つき)は LAST[day] に控える。"""
    try:
        a = _db(day)
    except Exception as e:  # noqa: BLE001
        log('談話 表 失敗', type(e).__name__, str(e)[:200])
        a = pd.DataFrame(columns=Q4 + TX)
    have = {(t, int(r)) for t, r in zip(a.track, a.race_no)}
    try:
        b = _kb(day, have, log)
    except Exception as e:  # noqa: BLE001
        log('談話 競馬ブック 失敗', type(e).__name__, str(e)[:200])
        b = pd.DataFrame(columns=Q4 + TX)
    log('談話 表', a[['track', 'race_no']].drop_duplicates().shape[0], 'R', len(a), '頭・頁', b[['track', 'race_no']].drop_duplicates().shape[0], 'R', len(b), '頭')
    x = pd.concat([a, b], ignore_index=True)
    x['race_date'] = day
    x['race_no'], x['umaban'] = x.race_no.astype(int), x.umaban.astype(int)
    x = x.drop_duplicates(Q4, keep='first')
    x['dw_mk'] = x.raw.fillna('').astype(str).str.strip().str[:1].where(lambda s: s.isin(list(CONST)), '')
    x['dw_u'] = x.dw_mk.map(CONST)
    LAST[day] = x.copy()
    return x[Q4 + ['dw_mk', 'dw_u']]


def p3prime(z, g):
    """logit z を レース g ごとに合計 3 にそろえる(t6_base.p3prime と同じ二分法 [−30, +30]・100 回)。"""
    R = g.max() + 1
    lo, hi = np.full(R, -30.0), np.full(R, 30.0)
    for _ in range(100):
        mid = (lo + hi) / 2
        up = np.bincount(g, 1 / (1 + np.exp(-(z + mid[g]))), R) < 3
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    return 1 / (1 + np.exp(-(z + ((lo + hi) / 2)[g])))


def apply_table(x, dw):
    """x = 前日の表(Q4・n・p1・p3p・rank・mark …)→ 3 定数を足して p3p・rank・mark を出し直す。元の値は p3p_t10・mark_t10 に残す。"""
    x = x.drop(columns=['dw_mk', 'dw_u'], errors='ignore').merge(dw, on=Q4, how='left', validate='1:1')
    x['p3p_t10'], x['mark_t10'] = x.p3p, x['mark']
    u = x.dw_u.fillna(0.0).to_numpy(float)
    key = ['track', 'race_date', 'race_no']
    g = x.groupby(key, sort=False).ngroup().to_numpy()
    p = np.clip(x.p3p.to_numpy(float), 1e-6, 1 - 1e-6)
    q = p3prime(np.log(p / (1 - p)) + u, g)
    big = x.groupby(key, sort=False).umaban.transform('size').to_numpy() > 3
    x['p3p'] = np.where(big, np.maximum(q, x.p1.to_numpy(float)), x.p3p)
    o = x.sort_values(key + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(key, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map({1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}).fillna('')
    return x


def apply_csv(csv_path, day, base_csv=None, log=print):
    """前日の表の CSV を書き換え(p3p・rank・mark)・v29 の土台に dw_u を足す(当日版の印が使う)。→ 足したレース数。"""
    dw = load(day, log=log)
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    x['race_date'] = x.race_date.astype(str).str[:10]
    x['race_no'], x['umaban'] = x.race_no.astype(int), x.umaban.astype(int)
    y = apply_table(x, dw)
    key = ['track', 'race_date', 'race_no']
    nr = int(y.groupby(key).dw_u.apply(lambda s: s.notna().any()).sum())
    ch = int((y[y['rank'] == 1].set_index(key).umaban != x[x['rank'] == 1].set_index(key).umaban).sum())
    y = y.sort_values(key + ['rank'], kind='mergesort')
    y.to_csv(csv_path, index=False, encoding='utf-8-sig')
    if base_csv is not None and Path(base_csv).exists():
        vb = pd.read_csv(base_csv, encoding='utf-8-sig')
        vb['race_date'] = vb.race_date.astype(str).str[:10]
        vb['race_no'], vb['umaban'] = vb.race_no.astype(int), vb.umaban.astype(int)
        vb = vb.drop(columns=['dw_u'], errors='ignore').merge(dw[Q4 + ['dw_u']], on=Q4, how='left', validate='1:1')
        vb.to_csv(base_csv, index=False, encoding='utf-8-sig')
    log('談話の印 足した', nr, '/', y[key].drop_duplicates().shape[0], 'R・印 ◎', int((y.dw_mk == '◎').sum()), '○', int(y.dw_mk.isin(['○', '〇']).sum()),
        '△', int((y.dw_mk == '△').sum()), '・本命が替わった', ch, 'R')
    return nr


if __name__ == '__main__':  # 手元の確かめ: python danwa_marks.py DAY [CSV]
    d = load(sys.argv[1])
    print(d.groupby('track').dw_mk.value_counts().to_string())
    if len(sys.argv) > 2:
        apply_csv(sys.argv[2], sys.argv[1])
