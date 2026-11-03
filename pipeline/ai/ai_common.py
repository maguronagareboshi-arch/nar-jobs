# -*- coding: utf-8 -*-
"""予想 AI の共通の部品(2026-11-03 段 1= base_v1.py から写した・中身は同じ)。
他場版 v3n・ばんえい・南関版 v3 は base_v1 を読まずにここを読む(base-v1 は毎日の便から外した)。
write_marks は model を引数で受ける(⛔モジュールの MODEL_ID を書き換える作法はやめた)。
⛔import は標準ライブラリ・numpy・pandas・load_nar_official だけ(v3-gap-live.yml の入れ物に他の道具が無い)。
"""
from __future__ import annotations
import datetime as dt, json, os, sys, time, urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))            # pipeline/
from load_nar_official import load_env, upsert  # noqa: E402,F401

TABLE = 'nar_ai_marks'
CONFLICT = 'model,track,race_date,race_no,timing'
JST = dt.timezone(dt.timedelta(hours=9))
REL = ['avg_rz_3', 'best_rz_5', 'avg_time_z_3', 'avg_time_za_3', 'fukusho_rate_5', 'prize_local_log',
       'kishu_fuku_1y', 'chokyo_fuku_1y', 'dist_fukusho_rate', 'uma_place_fuku', 'avg_l3z_3', 'best_l3z_5',
       'qpts', 'opp_str_now', 'bw_dev', 'futan', 'barei', 'p1_chaku', 'p1_sa', 'avg_chakujun_3',
       'p1_rz', 'p1_tz', 'days_since_prev', 'n_tz_5', 'has_hist', 'prev_best5', 'jc_tier', 'gear_now']
CAL_ID = 'win-v1'
CAL_EDGES = [0.0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.25, 0.40, 0.60, 1.0]   # 10 帯(0-0.5%…60-100%)


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def add_relative(df):
    """レース内の相対値を足して返す(⛔1 列ずつ足すと pandas が断片化するので concat で一度に)"""
    g = df.groupby('rid', sort=False)
    new = {'fld_n': g['runner_number'].transform('size').astype('float32')}
    for c in REL:
        if c not in df.columns:
            continue
        new['rel_' + c] = (df[c] - g[c].transform('mean')).astype('float32')
        new['rk_' + c] = g[c].rank(pct=True, method='average').astype('float32')
    return pd.concat([df, pd.DataFrame(new, index=df.index)], axis=1)


def race_norm(p, rid):
    """レースの中で合計 1 に(⛔合計 0 のレースは頭数で等分)"""
    s = pd.Series(np.asarray(p, dtype='float64'), index=rid.index)
    tot = s.groupby(rid).transform('sum')
    n = s.groupby(rid).transform('size')
    return np.where(tot > 0, s / tot.where(tot > 0, 1.0), 1.0 / n)


def cal_table(p, y):
    """10 帯ごとの 件数・見込みの平均・実際の 1 着率(⛔件数 0 の帯は None)"""
    p = np.asarray(p, dtype='float64')
    y = np.asarray(y, dtype='float64')
    b = np.clip(np.digitize(p, CAL_EDGES[1:-1], right=False), 0, len(CAL_EDGES) - 2)
    n, pred, rate = [], [], []
    for i in range(len(CAL_EDGES) - 1):
        m = b == i
        n.append(int(m.sum()))
        pred.append(round(float(p[m].mean()), 6) if m.any() else None)
        rate.append(round(float(y[m].mean()), 6) if m.any() else None)
    return {'id': CAL_ID, 'edges': CAL_EDGES, 'n': n, 'pred': pred, 'rate': rate}


def win_calibrate(p, cal):
    """帯の実績へ置き換え= (帯の見込みの平均, 帯の実際の率) の点を線で結んで読む(端は端の値)。
    ⛔較正表が無い/点が 2 つ未満なら元のまま"""
    pts = [(x, r) for x, r in zip(cal.get('pred') or [], cal.get('rate') or []) if x is not None and r is not None]
    p = np.asarray(p, dtype='float64')
    if len(pts) < 2:
        return p
    xs, ys = zip(*sorted(pts))
    return np.interp(p, xs, ys)


def sb_get(base, key, path):
    req = urllib.request.Request(f'{base}/rest/v1/{path}',
                                 headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def creds():
    base = os.environ.get('SUPABASE_URL') or os.environ.get('NAR_SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('NAR_SUPABASE_SERVICE_KEY')
    if not (base and key):
        env = load_env(str(HERE.parent / '.env.nar'))
        base, key = env.get('SUPABASE_URL'), env.get('SUPABASE_SERVICE_KEY')
    return base.rstrip('/'), key


def write_marks(rows, day, timing, model):
    """§143 timing='morning'= 既にある行は触らない(凍結)。'last'= 毎回上書き。
    ⛔どちらも書くのは**その timing の行だけ**。⚠発走 15 分前を過ぎた行は DB のトリガーが
    静かに捨てる(ai_marks_guard_20260825.sql)ので、⛔「エラーが出なかった」を採用の証拠にせず読み直す。"""
    base, key = creds()
    now = dt.datetime.now(JST).isoformat(timespec='seconds')
    out = []
    if timing == 'morning':
        have = sb_get(base, key, f'{TABLE}?select=track,race_no,timing&model=eq.{model}'
                                 f'&race_date=eq.{day}&timing=eq.morning&limit=2000')
        have = {(r['track'], r['race_no']) for r in have}
        rows = [r for r in rows if (r['track'], r['race_no']) not in have]
        if len(have):
            log('skip', len(have), 'existing morning rows (凍結)')
    for r in rows:
        out.append(dict(model=model, track=r['track'], race_date=r['race_date'], race_no=r['race_no'],
                        timing=timing, marks=r['marks'], meta=r['meta'], computed_at=now))
    if not out:
        log('nothing to write')
        return 0
    st, err = upsert(base, key, TABLE, CONFLICT, out)
    if st not in (200, 201, 204):
        raise SystemExit(f'upsert failed: {st} {err}')
    log('tried', len(out), timing, 'rows for', day, '=', ' '.join(f"{r['track']}{r['race_no']}R" for r in rows[:12]))
    # 読み直し= 実際に入ったのはどれか(凍結後は静かに捨てられる)
    back = sb_get(base, key, f'{TABLE}?select=track,race_no,computed_at&model=eq.{model}'
                             f'&race_date=eq.{day}&timing=eq.{timing}&limit=2000')
    # ⚠REST は UTC(+00:00)で返し、now は JST(+09:00)= 文字で比べると一致しない(Fable 9/9 実測)→ 時刻として比べる
    def _t(x):
        try:
            return dt.datetime.fromisoformat(str(x).replace('Z', '+00:00')).astimezone(JST).replace(microsecond=0)
        except (TypeError, ValueError):
            return None
    now_t = _t(now)
    took = {(r['track'], r['race_no']) for r in back if _t(r.get('computed_at')) == now_t}
    miss = [f"{r['track']}{r['race_no']}R" for r in rows if (r['track'], r['race_no']) not in took]
    log('took', len(took), '/', len(out), ('(捨てられた= 発走15分前を過ぎている: ' + ' '.join(miss[:12]) + ')') if miss else '')
    return len(took)
