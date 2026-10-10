# -*- coding: utf-8 -*-
"""他場版 v3n の血統の相性 b9_ 9 列(2026-10-11・確かめ = v3 の out/v3n_next.md・決め書 out/v3n_next_plan.md)。

南関 v8 の S・M の形を他場に移した(自作の移し)。走り = 公式 runs 全 15 場(帯広ばを除く)・取消・除外を除く。
父・母の父 = 公式 profiles(馬名 + 生年月日)。期待 = min(3, 頭数) ÷ 頭数。比 = (3 着内 + 3) ÷ (期待 + 3)。
「前」= その日より前(当日を含まない)・自分の走りは除く。条件の中の前の走りが 0 なら欠け。馬場は朝に分からないので使わない。
まだ走っていない行(今日の出走)も同じ式で値が付く(その行は数に足さない)= 研究の走った行とは全行一致。
"""
from pathlib import Path

import numpy as np
import pandas as pd

B9 = ['b9_s_td', 'b9_s_d', 'b9_s_t', 'b9_s_s', 'b9_s_dgap', 'b9_s_tdn', 'b9_m_td', 'b9_m_d', 'b9_m_dgap']
RIGHT = {'大井', '門別', '水沢', '金沢', '笠松', '名古屋', '園田', '姫路', '高知', '佐賀'}
LEFT = {'川崎', '船橋', '浦和', '盛岡'}
QK = ['track', 'race_date', 'race_no', 'umaban']


def runs(off):
    off = Path(off)
    ru = pd.read_parquet(off / 'runs.parquet', columns=['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'birth_date',
                                                        'finish', 'finish_note'])
    ru = ru[ru.track != '帯広ば'].copy()
    ru['race_date'] = ru.race_date.astype(str).str[:10]
    ru['birth_date'] = ru.birth_date.astype(str).str[:10]
    ru = ru.rename(columns={'runner_number': 'umaban'})
    ru['race_no'] = ru.race_no.astype(int)
    ru['umaban'] = ru.umaban.astype(int)
    ra = pd.read_parquet(off / 'races.parquet', columns=['track', 'race_date', 'race_no', 'distance_m'])
    ra['race_date'] = ra.race_date.astype(str).str[:10]
    ra['race_no'] = ra.race_no.astype(int)
    ru = ru.merge(ra.drop_duplicates(['track', 'race_date', 'race_no']), on=['track', 'race_date', 'race_no'], how='left')
    pr = pd.read_parquet(off / 'profiles.parquet', columns=['horse_name', 'birth_date', 'sire', 'broodmare_sire'])
    pr['birth_date'] = pr.birth_date.astype(str).str[:10]
    ru = ru.merge(pr.drop_duplicates(['horse_name', 'birth_date']), on=['horse_name', 'birth_date'], how='left')
    ru['fin'] = pd.to_numeric(ru.finish, errors='coerce')
    ru['ran'] = ru.fin > 0
    ru['hid'] = ru.horse_name.astype(str) + '|' + ru.birth_date
    return ru


def prior(df, keys, vals):
    """keys の群の、その日より前(当日を含まない)の vals の合計。自分の走りは除く。"""
    a = df.groupby(keys + ['race_date'])[vals].sum()
    c = a.groupby(level=list(range(len(keys)))).cumsum() - a
    o = df.groupby(keys + ['hid', 'race_date'])[vals].sum()
    co = o.groupby(level=list(range(len(keys) + 1))).cumsum() - o
    x = df[keys + ['hid', 'race_date']].merge(c.reset_index(), on=keys + ['race_date'], how='left')
    y = df[keys + ['hid', 'race_date']].merge(co.reset_index(), on=keys + ['hid', 'race_date'], how='left')
    return pd.DataFrame(x[vals].to_numpy() - y[vals].to_numpy(), columns=vals, index=df.index)


def build(off, log=print):
    """→ QK + B9(取消・除外を除く全行・今日の出走を含む)"""
    ru = runs(off)
    R = ru[~ru.finish_note.isin(['出走取消', '競走除外'])].drop_duplicates(QK).copy()
    ran = R.ran.to_numpy()
    fs = R.ran.groupby([R.track, R.race_date, R.race_no]).transform('sum').astype(float)
    R['y'] = ((R.fin <= 3) & R.ran).astype(float)
    R['x'] = np.where(ran, np.minimum(3, fs) / fs.where(fs > 0, 1), 0.0)
    R['yd'] = R.y * R.distance_m
    R['one'] = ran.astype(float)
    d = R.distance_m.astype(float)
    band = np.select([d <= 1250, d <= 1550, d <= 1850], ['1', '2', '3'], '4')
    R['c_d'] = np.where(d.isna(), None, band)
    R['c_td'] = np.where(d.isna(), None, R.track + '_' + pd.Series(band, index=R.index))
    R['c_t'] = R.track.map(lambda t: 'R' if t in RIGHT else ('L' if t in LEFT else None))
    m = pd.to_datetime(R.race_date).dt.month
    R['c_s'] = m.map(lambda v: 'w' if v in (12, 1, 2) else 'p' if v in (3, 4, 5) else 'u' if v in (6, 7, 8) else 'a')
    R['c_all'] = 'a'
    out = R[QK].copy()
    for c in B9:
        out[c] = np.nan
    for g, pf in (('sire', 's'), ('broodmare_sire', 'm')):
        S = R[R[g].notna()]
        base = prior(S, [g, 'c_all'], ['y', 'x', 'yd'])
        rb = (base.y + 3) / (base.x + 3)
        for c in (('td', 'd', 't', 's') if pf == 's' else ('td', 'd')):
            s2 = S[S['c_' + c].notna()]
            p = prior(s2, [g, 'c_' + c], ['y', 'x'])
            r = (p.y + 3) / (p.x + 3)
            r[(p.x <= 0) | p.x.isna()] = np.nan
            out.loc[s2.index, f'b9_{pf}_{c}'] = (r / rb.loc[s2.index]).to_numpy()
            if c == 'td' and pf == 's':
                out.loc[s2.index, 'b9_s_tdn'] = prior(s2, [g, 'c_' + c], ['one']).one.to_numpy()
        gap = R.loc[S.index, 'distance_m'] - base.yd / base.y.replace(0, np.nan)
        gap[base.y < 20] = np.nan
        out.loc[S.index, f'b9_{pf}_dgap'] = gap.to_numpy()
    log('血統の相性 b9_', f'{len(out):,} 行', '父あり', round(float(R.sire.notna().mean()), 3))
    return out
