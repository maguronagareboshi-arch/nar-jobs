# -*- coding: utf-8 -*-
"""南関特化 AI の「ひとこと」= 馬ごとの短い札を前日の便で作る。表示だけで、予想の計算には使わない。

札と出す線(2026-10-02 の数え = nankan-ai-v3 の out/sunpyo_study.md。今の AI の外の予想 2022-01〜2026-08 と比べた
「実際 ÷ 見込み」= 1.00 なら AI が読み切っている):
  勝ち方(公式の成績): 前走が 1 着の馬だけ。差 = 2 着の走破時計 − 1 着の走破時計(秒)。
      0.9 秒以上「前走1.2秒差の圧勝」/ 0.5〜0.8 秒「前走0.6秒差の快勝」/ 2 着の着差がハナ・アタマ・クビ「前走クビ差の1着」/
      1 着が 2 頭「前走同着の1着」。(前走 1 着の次走の勝ち: 差 〜0.1 秒 0.90 倍・0.5〜0.8 秒 1.06 倍・0.9 秒〜 1.17 倍)
  逃げ馬(公式の通過順): f_nige5(過去 5 走で最初の角を 1 番手で回った割合)≥ 0.4 の馬が今日のレースでこの馬だけ
      →「逃げ馬はこの馬だけ」(勝ち 1.09 倍・5,109 頭)。
  ⛔ここから下の 2 つは競馬ブックの会員ページの字から作る = note_kb に分けて入れる(画面に出すかはサイトの旗で別に決める):
  出遅れ(競馬ブックの発走状況 nar_kb_runs.start_note): 今日より前の記録のある直近 5 走で出遅れ 2 回以上 →「近5走で出遅れ3回」
      (3 回以上は勝ち 0.85 倍。今日も出遅れる率 0 回 8%・2 回 25%・3 回以上 39%)。
  不利(競馬ブックの寸評 nar_kb_runs.comment・列があるときだけ): 前走の寸評が不利の組 →「前走 直線で不利」など
      (勝ち 1.09〜1.18 倍)。
出力 = {(track, race_no, umaban): {'note': [...], 'note_kb': [...]}}(札の無い馬は入れない)。
⛔読むだけ(GET)。書かない。鍵は印字しない。失敗は呼ぶ側(v3_daily)で受けて、予想の表と書き込みは止めない。
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

import kb_works
import t4_day3 as d3

KEY = ['track', 'race_date', 'race_no']
SMALL = ('ハナ', 'アタマ', 'クビ')
SLOW = re.compile('出遅|アオ|立ち遅|ダッシュ付かず')
# 寸評 → 札(先に当たった方)。調べの組(src/f5_scripts/sunpyo/cls.py)のうち、字にしてよいものだけ。
EXC = [
    (re.compile(r'^(直線不利|前塞がる|直線挟る|直線包れ|Ｇ前不利|直線前詰|Ｇ前挟る|直線内詰|直線中詰|直線外詰|直線塞る|内包まれ)$'), '前走 直線で不利'),
    (re.compile(r'^(逃争不利|先争い不利|競る不利)$'), '前走 先行争いで厳しい流れ'),
    (re.compile(r'^(スタート後不利|スタート後挟る|スタート後包れ)$'), '前走 スタート直後に不利'),
    (re.compile(r'^(折合欠く|引掛かる)$'), '前走 折り合いを欠く'),
    (re.compile(r'^(外々回る|外を回る)$'), '前走 外を回る'),
    (re.compile(r'不利|挟る|包れ|揉まれ|砂を被'), '前走 道中で不利'),
]
PAGE = 1000
CHUNK = 40


def _fetch_kb(names, lo, hi):
    """nar_kb_runs を馬名で読む(今日より前・lo 以降)。comment の列が無ければ start_note だけで読み直す。"""
    base, key = kb_works.creds()
    if not base:
        return []
    out = []
    for cols in ('track,race_date,race_no,umaban,horse_name,start_note,comment', 'track,race_date,race_no,umaban,horse_name,start_note'):
        try:
            out = []
            for i in range(0, len(names), CHUNK):
                part = names[i:i + CHUNK]
                q = [('select', cols), ('horse_name', 'in.(' + ','.join('"' + n.replace('"', '') + '"' for n in part) + ')'),
                     ('race_date', f'gte.{lo}'), ('race_date', f'lt.{hi}'), ('order', 'race_date,race_no')]
                off = 0
                while True:
                    url = f'{base}/rest/v1/nar_kb_runs?' + urllib.parse.urlencode(q + [('limit', str(PAGE)), ('offset', str(off))])
                    req = urllib.request.Request(url, headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai-v3'})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        got = json.loads(r.read().decode('utf-8'))
                    out += got
                    if len(got) < PAGE:
                        break
                    off += PAGE
            return out
        except urllib.error.HTTPError as e:
            if e.code == 400 and 'comment' in cols:
                continue  # comment の列がまだ無い = 出遅れだけで作る
            raise
    return out


def _norm(s):
    return re.sub(r'\s+', '', str(s)) if isinstance(s, str) else s


def _exc(cm):
    if not isinstance(cm, str) or not cm:
        return None
    for p, txt in EXC:
        if p.search(cm):
            return txt
    return None


def make(day, h, T, kb_rows=None, log=print):
    """day = 'YYYY-MM-DD'・h = 走り(d3.sources_from の形・今日の出走表を含む)・T = 今日の材料(f_nige5・f_nige_n)。
    kb_rows = nar_kb_runs の行(None なら REST で読む・手元の確かめでは渡す)。"""
    day = str(day)[:10]
    today = h[h.race_date.astype(str).str[:10] == day]
    today = today[today.track.isin(d3.NANKAN) & ~today.finish_note.isin(d3.CANCEL)][KEY + ['umaban', 'hid', 'horse_name']]
    notes = {}

    def add(k, field, txt):
        notes.setdefault(k, {'note': [], 'note_kb': []})[field].append(txt)

    # 勝ち方: 前走 = 今日より前の最後の走り(取消・除外を除く)
    past = h[(h.race_date.astype(str).str[:10] < day) & ~h.finish_note.isin(d3.CANCEL)]
    past = past[past.hid.isin(set(today.hid))]
    x = h[h.finish.isin([1, 2])][KEY + ['finish', 'time_sec', 'margin']]
    x = x[x.set_index(KEY).index.isin(past.set_index(KEY).index)]
    a = x[x.finish == 1].groupby(KEY).agg(n1=('finish', 'size'), t1=('time_sec', 'min'))
    b = x[x.finish == 2].sort_values('time_sec').groupby(KEY).agg(t2=('time_sec', 'min'), m2=('margin', 'first'))
    g = a.join(b, how='left').reset_index()
    last = past.sort_values(['race_date', 'race_no'], kind='mergesort').groupby('hid').tail(1)
    last = last[['hid', 'race_date', 'finish'] + [k for k in KEY if k != 'race_date']].merge(g, on=KEY, how='left')
    lw = last.set_index('hid')
    for r in today.itertuples():
        if r.hid not in lw.index:
            continue
        p = lw.loc[r.hid]
        if p.finish != 1:
            continue
        k = (r.track, int(r.race_no), int(r.umaban))
        gap = p.t2 - p.t1 if pd.notna(p.t2) and pd.notna(p.t1) else np.nan
        if p.n1 >= 2:
            add(k, 'note', '前走同着の1着')
        elif isinstance(p.m2, str) and p.m2 in SMALL:
            add(k, 'note', f'前走{p.m2}差の1着')
        elif np.isfinite(gap) and gap >= 0.85:
            add(k, 'note', f'前走{gap:.1f}秒差の圧勝')
        elif np.isfinite(gap) and gap >= 0.45:
            add(k, 'note', f'前走{gap:.1f}秒差の快勝')
    # 逃げ馬
    if T is not None and {'f_nige5', 'f_nige_n'} <= set(T.columns):
        t = T[T.race_date.astype(str).str[:10] == day]
        for r in t[(t.f_nige5 >= 0.4) & (t.f_nige_n == 1)].itertuples():
            k = (r.track, int(r.race_no), int(r.umaban))
            if r.track in d3.NANKAN:
                add(k, 'note', '逃げ馬はこの馬だけ')
    # 競馬ブック: 出遅れ(発走状況)・不利(寸評)
    names = sorted({_norm(n) for n in today.horse_name if isinstance(n, str)})
    if kb_rows is None:
        lo = (pd.Timestamp(day) - pd.Timedelta(days=730)).strftime('%Y-%m-%d')
        kb_rows = _fetch_kb(names, lo, day)
    kb = pd.DataFrame(kb_rows)
    nslow = nkb = 0
    if len(kb):
        kb['nm'] = kb.horse_name.map(_norm)
        kb = kb[kb.race_date.astype(str).str[:10] < day].sort_values(['race_date', 'race_no'], kind='mergesort')
        last_day = last.set_index('hid').race_date.astype(str).str[:10].to_dict()
        for r in today.itertuples():
            m = kb[kb.nm == _norm(r.horse_name)]
            if not len(m):
                continue
            k = (r.track, int(r.race_no), int(r.umaban))
            s5 = m.tail(5).start_note.fillna('').astype(str).str.contains(SLOW).sum()
            if s5 >= 2:
                add(k, 'note_kb', f'近5走で出遅れ{int(s5)}回')
                nslow += 1
            if 'comment' in m.columns:
                p = m.iloc[-1]
                if str(p.race_date)[:10] == last_day.get(r.hid):  # 競馬ブックの最後の走り = 本当の前走のときだけ
                    txt = _exc(p.comment)
                    if txt:
                        add(k, 'note_kb', txt)
                        nkb += 1
    log('ひとこと', len(notes), '頭', '出遅れ', nslow, '不利', nkb, '競馬ブックの行', len(kb))
    return notes


def attach(rows, notes):
    """build_rows の行(track・race_no・meta.runners)に札を足す。札の無い馬は何も足さない。"""
    n = 0
    for row in rows:
        for x in row['meta']['runners']:
            v = notes.get((row['track'], int(row['race_no']), int(x['num'])))
            if not v:
                continue
            if v['note']:
                x['note'] = v['note']
            if v['note_kb']:
                x['note_kb'] = v['note_kb']
            n += 1
    return n
