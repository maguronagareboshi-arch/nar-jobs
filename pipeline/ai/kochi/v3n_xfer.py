# -*- coding: utf-8 -*-
"""他場版の「移籍の目安」= 地区をまたいで移ってきた馬(移籍 1〜5 戦目)に、過去に同じ元から同じクラスへ移った馬の
通用した割合を 1 行で添える。表示だけで、予想の計算には使わない(2026-11-06・研究 nankan-ai-v3 src/f5_scripts/hayami_jisseki.py)。

  表 = v3n_xfer_table.json(研究で作った固定の表・元の場 × 元のクラス × 行き先の場 × 入ったクラス → [頭数, 通用した割合]・8 頭以上の組だけ)。
  通用 = 移って最初に走ったクラスで、同じ地区の最初の 5 走のうちに昇級したか、昇級も降級もせずそのクラスの走りの過半数が 5 着以内。
  元 = 移る前の最後の走りの場とクラス(中央は 未勝利・1勝・2勝・3勝・オープン)。入ったクラス = 移って最初に走ったクラス。
  地区 = 南関 4 場・兵庫 2 場・岩手 2 場・東海 2 場はまとめて 1 つ、他は場ごと。
  遠征の戻り(元の地区の走りが 2 走以下で、その前が今の地区・365 日以内)は移籍と見なさない = 何も付けない。
  出力 = 行の meta.xfer = {馬番: 1 行の字}(付く馬がいなければ meta に何も足さない)。
⛔読むだけ。失敗は呼ぶ側(v3n_daily)で受けて、予想の表と書き込みは止めない。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cls2 import cls3 as cls2  # 11/6 夜 広い読み(交流・混ぜたクラス・2・3 歳)= 表と同じ読み

HERE = Path(__file__).resolve().parent
AREA = {'園田': '兵庫', '姫路': '兵庫', '名古屋': '東海', '笠松': '東海', '水沢': '岩手', '盛岡': '岩手',
        '大井': '南関', '川崎': '南関', '船橋': '南関', '浦和': '南関'}
CANCEL = ('取消', '除外')


def jcls(n):
    """中央のレース名 → 未勝利・1勝・2勝・3勝・オープン(新馬は None)。"""
    n = str(n)
    if '新馬' in n:
        return None
    for k, v in [('未勝利', '未勝利'), ('1勝', '1勝'), ('500万', '1勝'), ('2勝', '2勝'), ('1000万', '2勝'), ('3勝', '3勝'), ('1600万', '3勝')]:
        if k in n:
            return v
    return 'オープン'


def _hid(df):
    return df.horse_name.astype(str) + '|' + df.birth_date.astype(str).str[:10]


def history(off):
    """全部の走り(地方の公式 + 中央)= hid・date・track・cls・area(取消・除外は除く)。"""
    off = Path(off)
    ru = pd.read_parquet(off / 'runs.parquet', columns=['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'birth_date', 'finish_note'])
    ru = ru[~ru.finish_note.astype(str).str.contains('|'.join(CANCEL), na=False)].copy()
    ru['race_date'] = ru.race_date.astype(str).str[:10]
    ru['hid'] = _hid(ru)
    ra = pd.read_parquet(off / 'races.parquet', columns=['track', 'race_date', 'race_no', 'race_name'])
    ra['race_date'] = ra.race_date.astype(str).str[:10]
    ra = ra.drop_duplicates(['track', 'race_date', 'race_no'])
    ra['cls'] = [cls2(n, t) for n, t in zip(ra.race_name, ra.track)]   # 2 桁の番号は名古屋・笠松だけ
    ru = ru.merge(ra[['track', 'race_date', 'race_no', 'cls']], on=['track', 'race_date', 'race_no'], how='left')
    L = ru[['hid', 'race_date', 'race_no', 'track', 'cls', 'runner_number']].copy()
    L['area'] = L.track.map(AREA).fillna(L.track)
    parts = [L]
    try:
        jr = pd.read_parquet(off / 'jra.parquet', columns=['kb_horse_id', 'race_date', 'race_no', 'race_name'])
        jh = pd.read_parquet(off / 'jrah.parquet', columns=['kb_horse_id', 'horse_name', 'birth_date']).dropna()
        jh['hid'] = _hid(jh)
        jr = jr.merge(jh[['kb_horse_id', 'hid']].drop_duplicates('kb_horse_id'), on='kb_horse_id')
        J = pd.DataFrame({'hid': jr.hid, 'race_date': jr.race_date.astype(str).str[:10], 'race_no': jr.race_no,
                          'track': '中央', 'cls': jr.race_name.map(jcls), 'runner_number': np.nan, 'area': '中央'})
        parts.append(J)
    except Exception as e:  # noqa: BLE001  中央が読めなくても地方の分だけで付ける
        print('移籍の目安: 中央の走りが読めない = 地方の元だけ', type(e).__name__, str(e)[:120], flush=True)
    H = pd.concat(parts, ignore_index=True)
    return H.sort_values(['hid', 'race_date', 'race_no']).reset_index(drop=True)


def note_for(seq, track, today_cls, day, T):
    """seq = その馬の今日より前の走り(古い順・date・track・cls・area)。→ 1 行の字か None。"""
    a = AREA.get(track, track)
    ar = seq.area.to_numpy()
    k = 0
    while k < len(ar) and ar[len(ar) - 1 - k] == a:
        k += 1
    if k >= 5 or k == len(ar):          # 移籍 6 戦目以降・ずっと同じ地区
        return None
    i = len(ar) - 1 - k                 # 移る前の最後の走り
    src_area = ar[i]
    j = i
    while j >= 0 and ar[j] == src_area:
        j -= 1
    nsrc = i - j                        # 元の地区での続きの走りの数
    if j >= 0 and ar[j] == a and nsrc <= 2:
        d0 = pd.Timestamp(seq.race_date.iloc[j + 1])
        d1 = pd.Timestamp(seq.race_date.iloc[j])
        if (d0 - d1).days <= 365:       # 遠征の戻り
            return None
    s_trk, s_cls = seq.track.iloc[i], seq.cls.iloc[i]
    e_cls = seq.cls.iloc[i + 1] if k >= 1 else today_cls
    if not isinstance(s_cls, str) or not isinstance(e_cls, str):
        return None
    c = T.get(f'{s_trk}|{s_cls}|{track}|{e_cls}')
    if not c:
        return None
    n, r = c
    src = f'{s_trk}の{s_cls}戦' if s_cls.endswith('歳') else f'{s_trk}{s_cls}'   # 2・3 歳限定は「船橋の3歳戦」
    return f'移籍{k + 1}戦目: {src}から{track}{e_cls}に入った馬は{int(round(r * 100))}%が通用({n}頭)'


def attach(rows, off, day, log=print):
    """v3n_daily の rows(track・race_no・meta.runners)に meta.xfer を足す。→ 付けた頭数。"""
    T = json.loads((HERE / 'v3n_xfer_table.json').read_text(encoding='utf-8'))['cells']
    H = history(off)
    tod = H[H.race_date == day]
    past = H[(H.race_date < day) & H.hid.isin(set(tod.hid))]   # 今日走る馬の分だけ
    g = {h: s for h, s in past.groupby('hid', sort=False)}
    ra = pd.read_parquet(Path(off) / 'races.parquet', columns=['track', 'race_date', 'race_no', 'race_name'])
    ra['race_date'] = ra.race_date.astype(str).str[:10]
    tcls = {(t, int(r)): cls2(nm, t) for t, r, nm in ra.loc[ra.race_date == day, ['track', 'race_no', 'race_name']].itertuples(index=False)}
    hid_of = {(t, int(r), int(u)): h for t, r, u, h in tod.dropna(subset=['runner_number'])[['track', 'race_no', 'runner_number', 'hid']].itertuples(index=False)}
    took = 0
    for row in rows:
        trk, rno = row['track'], int(row['race_no'])
        out = {}
        for x in row['meta'].get('runners') or []:
            h = hid_of.get((trk, rno, int(x['num'])))
            if h is None or h not in g:
                continue
            t = note_for(g[h], trk, tcls.get((trk, rno)), day, T)
            if t:
                out[str(int(x['num']))] = t
        if out:
            row['meta']['xfer'] = out
            took += len(out)
    log('移籍の目安 付けた', took, '頭')
    return took
