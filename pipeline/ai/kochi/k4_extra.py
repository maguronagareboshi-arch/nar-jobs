# -*- coding: utf-8 -*-
"""高知版 4 = 南関で効いた上積みの考え方を高知に移した 4 つの束(学習なし・2026-10-10)。

  py -3.12 -X utf8 src/kochi/k4_extra.py   → C:/Users/kouki/nankan_ai/v3/kochi/extra.parquet(feat2 と同じ行・束ごとの列)

■ 束(南関で何に当たるか)
  G1 相手関係(南関の h2h・elo・b7_k10): 今日の相手と前に走った時の勝ち負け(高知のレースだけ)・強さの点数(Elo・高知のレースだけ・K=32)。
  G2 前走のメンバーの強さ(南関の r_ 群・b7_k09_foe): 高知の過去のレースの「出た馬の速さ(a_siw)の平均」を、その馬の前の高知の走りについて。
  G3 血統・馬主・生産者の足し(南関の c7_ の残り): 馬主・生産者・産地の前の 3 着内率、父の初出走の率、父の高知の率、生まれ月。
  G4 中央の足し・休み明け(南関の j7_ の残り・b7_g05/g07/k12): 中央の前走の着順・芝の数・ダートの 3 着内率、休み明けの成績、転厩の回数。
  どれも「その日より前」の走りだけ。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import k1_feat as k1  # noqa: E402

V = Path('C:/Users/kouki/nankan_ai/v3/kochi')
RK = ['date', 'jyo', 'race']
log = k1.log


def g1_rivals(K):
    """K = 高知の全出走(日付・R 順)。前の対戦の勝ち負けと Elo(走る前の値)。"""
    K = K.sort_values(RK + ['umaban'])
    pair, elo, nr = {}, {}, {}
    out = []
    for (d, j, r), x in K.groupby(RK, sort=True):
        ids = x.ketto.to_numpy()
        fin = x.fin.fillna(x.n.iloc[0] + 1).to_numpy(float)
        m = len(ids)
        Rt = np.array([elo.get(i, 1500.0) for i in ids])
        beat = np.zeros(m); lost = np.zeros(m); met = np.zeros(m)
        for a in range(m):
            for b in range(m):
                if a == b or ids[a] == 0 or ids[b] == 0:
                    continue
                w = pair.get((ids[a], ids[b]))
                if w:
                    beat[a] += w[0]; lost[a] += w[1]; met[a] += 1
        for a, i in enumerate(ids):
            out.append((d, r, x.umaban.iat[a], Rt[a], nr.get(i, 0), beat[a], lost[a], met[a]))
        # 更新
        E = 1 / (1 + 10 ** ((Rt[None, :] - Rt[:, None]) / 400))
        S = (fin[:, None] < fin[None, :]).astype(float) + 0.5 * (fin[:, None] == fin[None, :])
        np.fill_diagonal(E, 0); np.fill_diagonal(S, 0)
        dR = 32 / max(m - 1, 1) * (S - E).sum(1)
        for a in range(m):
            i = ids[a]
            if i == 0:
                continue
            elo[i] = Rt[a] + dR[a]
            nr[i] = nr.get(i, 0) + 1
            for b in range(m):
                if a != b and ids[b] != 0:
                    w = pair.setdefault((i, ids[b]), [0, 0])
                    if fin[a] < fin[b]:
                        w[0] += 1
                    elif fin[a] > fin[b]:
                        w[1] += 1
    G = pd.DataFrame(out, columns=['date', 'race', 'umaban', 'x1_elo', 'x1_elon', 'x1_beat', 'x1_lost', 'x1_met'])
    G['x1_h2h'] = (G.x1_beat + 1) / (G.x1_beat + G.x1_lost + 2)
    G['x1_net'] = G.x1_beat - G.x1_lost
    gg = G.groupby(['date', 'race'])
    G['x1_elo_z'] = (G.x1_elo - gg.x1_elo.transform('mean')) / gg.x1_elo.transform('std')
    G['x1_elo_rank'] = gg.x1_elo.rank(ascending=False, method='min')
    G['x1_net_rank'] = gg.x1_net.rank(ascending=False, method='min')
    return G


def main():
    T = pd.read_parquet(V / 'feat2.parquet', columns=['date', 'jyo', 'race', 'umaban', 'ketto', 'n', 'fin', 'Y3', 'a_siw', 'a_si1',
                                                       'g_rest', 'i_move', 'sire_id'])
    se = k1.speed(k1.load_se())
    hz = pd.read_parquet(k1.V + 'kd_horse.parquet', columns=['ketto', 'sire_id', 'owner_cd', 'breeder_cd', 'area', 'birth'])
    hz['ketto'] = pd.to_numeric(hz.ketto, errors='coerce').fillna(0).astype('int64')
    hz = hz[hz.ketto > 0].drop_duplicates('ketto')
    se = se.merge(hz, on='ketto', how='left')
    K = se[se.jyo == k1.KOCHI][['date', 'jyo', 'race', 'umaban', 'ketto', 'n', 'fin']].copy()
    K = K[K.date >= '2005-01-01']
    log('G1 相手関係・Elo', f'{K.groupby(RK).ngroups:,} R')
    G1 = g1_rivals(K)
    log('G1 済み')
    # G2 前の高知の走りのメンバーの強さ
    T = T.sort_values(['ketto', 'date']).reset_index(drop=True)
    lvl = T.groupby(RK).a_siw.agg(['mean', 'max']).rename(columns={'mean': 'lv', 'max': 'lvmax'}).reset_index()
    T = T.merge(lvl, on=RK, how='left')
    g = T.groupby('ketto')
    X = T[['date', 'race', 'umaban']].copy()
    lv = np.column_stack([g.lv.shift(k).to_numpy(float) for k in range(1, 6)])
    fr = np.column_stack([(g.fin.shift(k) / g.n.shift(k)).to_numpy(float) for k in range(1, 6)])
    import warnings
    warnings.simplefilter('ignore', RuntimeWarning)
    X['x2_lv1'] = lv[:, 0]
    X['x2_lvmax5'] = np.nanmax(lv, 1)
    X['x2_lvmean5'] = np.nanmean(lv, 1)
    X['x2_lvchg'] = T.lv - lv[:, 0]  # 今日のメンバー − 前の高知のメンバー(今日の分は走る前の値の平均)
    X['x2_lvfin1'] = lv[:, 0] - 3 * fr[:, 0]  # 強い相手で上の着ほど大きい(目安の合成)
    fk = np.column_stack([g.fin.shift(k).to_numpy(float) for k in range(1, 6)])
    X['x2_t3lv'] = np.nanmax(np.where(fk <= 3, lv, np.nan), 1)  # 3 着内に来たレースの最高のメンバー
    X['x2_lvgap'] = X.x2_t3lv - T.lv
    # G4 休み明け・転厩
    rest = T.g_rest.to_numpy(float)
    fr0 = (T.fin / T.n).to_numpy(float)
    long_ = pd.Series(((rest >= 60) & ~np.isnan(fr0)).astype(float))
    fl = pd.Series(np.where(long_ == 1, fr0, 0.0))
    nlong = long_.groupby(T.ketto).cumsum() - long_
    X['x4_restn'] = nlong
    X['x4_restperf'] = (fl.groupby(T.ketto).cumsum() - fl) / nlong.replace(0, np.nan)
    mv = T.i_move.fillna(0)
    X['x4_ntrans'] = mv.groupby(T.ketto).cumsum()
    # G3 血統・馬主・生産者
    Q = T[['date', 'race', 'umaban', 'ketto']].merge(hz, on='ketto', how='left')
    for key, pf in [('owner_cd', 'x3_own'), ('breeder_cd', 'x3_brd'), ('area', 'x3_area')]:
        r = k1.prior_rate(se, key, Q)
        Q = Q.merge(r.rename(columns={'N': pf + '_n', 'rate': pf + '_t3'}), on=[key, 'date'], how='left')
    deb = se.sort_values('date').drop_duplicates('ketto')  # 初出走
    r = k1.prior_rate(deb, 'sire_id', Q)
    Q = Q.merge(r.rename(columns={'N': 'x3_sdeb_n', 'rate': 'x3_sdeb_t3'}), on=['sire_id', 'date'], how='left')
    r = k1.prior_rate(se[se.jyo == k1.KOCHI], 'sire_id', Q)
    Q = Q.merge(r.rename(columns={'N': 'x3_sk_n', 'rate': 'x3_sk_t3'}), on=['sire_id', 'date'], how='left')
    Q['x3_bmon'] = pd.to_numeric(Q.birth.astype(str).str[4:6], errors='coerce')
    Q = Q.drop(columns=['ketto', 'sire_id', 'owner_cd', 'breeder_cd', 'area', 'birth'])
    log('G3 済み')
    # G4 中央の足し
    J = se[se.jyo.between(1, 10) & se.ketto.isin(set(T.ketto))].sort_values('date')
    J = J.assign(turf=(J.surf == 1).astype(int), dirt=(J.surf == 0).astype(int))
    J['dt3'] = J.dirt * J.Y3
    J[['x4_jturf', 'x4_jdirt', 'x4_jdt3']] = J.groupby('ketto')[['turf', 'dirt', 'dt3']].cumsum()
    J['x4_jlast'] = J.fin / J.n
    J['date'] = J.date + pd.Timedelta(days=1)
    T2 = pd.merge_asof(T[['date', 'race', 'umaban', 'ketto']].sort_values('date'),
                       J[['ketto', 'date', 'x4_jturf', 'x4_jdirt', 'x4_jdt3', 'x4_jlast']], on='date', by='ketto', direction='backward')
    T2['x4_jdirt_t3'] = T2.x4_jdt3 / T2.x4_jdirt.replace(0, np.nan)
    T2 = T2.drop(columns=['ketto', 'x4_jdt3'])
    E = X.merge(G1, on=['date', 'race', 'umaban'], how='left').merge(Q, on=['date', 'race', 'umaban'], how='left') \
        .merge(T2, on=['date', 'race', 'umaban'], how='left')
    E.to_parquet(V / 'extra.parquet', index=False)
    log('保存', E.shape, '付いた割合', E.drop(columns=['date', 'race', 'umaban']).notna().mean().round(2).to_dict())


if __name__ == '__main__':
    main()
