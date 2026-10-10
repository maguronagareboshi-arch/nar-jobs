# -*- coding: utf-8 -*-
"""高知版 1 = KDSCOPE の高知(場 54)の走りに、南関 v3 の「成績から作れる材料」を作る(学習なし・2026-10-10)。

  py -3.12 -X utf8 src/kochi/k1_feat.py   → C:/Users/kouki/nankan_ai/v3/kochi/feat.parquet(高知の出走 1 頭 1 行・2006〜)

■ 決め(南関の作りを高知に移した所・見た後は変えない)
  - 元: kd_se(全場の走り)・kd_ra + kd_ra_open(距離・コース・1 着賞金)・kd_horse(父・母・母父)。人気・オッズは材料にしない(mk_ に残すだけ)。
  - 調教・談話・能力試験・記者の印は高知に無い(競馬ブックで 2017〜2026-09 を確かめた)ので作らない。馬体重も前日版に合わせて入れない。
  - 速さ(SI)= そのコース(場・距離・芝ダ)の 1〜3 着の平均の速さ(前 3 年・30 R 未満は前 6 年・15 R)からの差 − その日その場の片寄り
    (その日のレースの差の中央値・3 R 未満は 0)。秒/km で、+ が速い。他場・中央の走りも同じ作り。
  - クラス = 1 着賞金(高知の格の名前は KDSCOPE に無い)。
  - 騎手・調教師 = 高知での前 365 日(その日を含まない)の 3 着内率・勝率(全体の率へ 30 騎乗ぶん寄せる)。
  - 血統 = 父・母父・母(兄弟)の産駒の、その日より前の全場の 3 着内率。
  - 馬の過去は、その日より前の走り(取消・除外を除く)だけ。
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd

V = 'C:/Users/kouki/nankan_ai/v3/'
OUT = Path(V) / 'kochi'
KOCHI, NANKAN = 54, (42, 43, 44, 45)
START = pd.Timestamp('2006-01-01')
RK = ['date', 'jyo', 'race']
FEAT = 'feat2.parquet'  # k1 の最初の版は feat.parquet(クラス名・馬場なし)
t0 = time.time()


def log(*a):
    print(f'[{time.time() - t0:6.0f}s]', *a, flush=True)


def load_se():
    cols = ['kubun', 'year', 'md', 'jyo', 'race', 'waku', 'umaban', 'ketto', 'sex', 'age', 'trainer_cd', 'kinryo',
            'jockey_cd', 'ijo', 'finish', 'c1', 'c4', 'l3f', 'time_sec', 'tdiff', 'odds', 'pop', 'date']
    se = pd.read_parquet(V + 'kd_se.parquet', columns=cols)
    se = se[~se.kubun.isin(['0', '9'])].copy()
    se['kb'] = se.kubun.map({'7': 3, '2': 2}).fillna(1)
    se = se.sort_values('kb').drop_duplicates(RK + ['umaban'], keep='last').drop(columns=['kubun', 'kb'])
    for c in ['jyo', 'race', 'umaban', 'ijo']:
        se[c] = se[c].fillna(0).astype('int16')
    se['ketto'] = se.ketto.fillna(0).astype('int64')
    se = se[se.date.notna()].copy()
    se['year'] = se.date.dt.year.astype(int)
    log('SE', f'{len(se):,}')
    ra = pd.concat([pd.read_parquet(V + f, columns=['make', 'year', 'md', 'jyo', 'race', 'grade', 'dist', 'trk', 'prize1'])
                    for f in ['kd_ra.parquet', 'kd_ra_open.parquet']])
    ra = ra.sort_values('make').drop_duplicates(['year', 'md', 'jyo', 'race'], keep='last').drop(columns='make')
    ra = ra[ra.jyo.notna() & ra.race.notna() & ra.year.notna()].copy()
    ra['year'] = ra.year.astype(int)
    ra['jyo'] = ra.jyo.astype('int16')
    ra['race'] = ra.race.astype('int16')
    se = se.merge(ra, on=['year', 'md', 'jyo', 'race'], how='left')
    se['surf'] = np.select([se.trk.between(10, 22), se.trk.between(23, 29)], [1, 0], 2)  # 1 芝・0 ダ・2 障害/不明
    se['run'] = ~se.ijo.isin([1, 2, 3])
    se = se[se.run].copy()
    se['n'] = se.groupby(RK).umaban.transform('size').astype('int16')
    f = se.finish.where(se.finish >= 1)
    se['fin'] = f
    se['Y1'] = (f == 1).astype('int8')
    se['Y3'] = (f <= 3).astype('int8')
    se['l3f'] = se.l3f.where(se.l3f > 0)
    se['time_sec'] = se.time_sec.where(se.time_sec > 0)
    se['c1'] = se.c1.where(se.c1 > 0)
    se['c4'] = se.c4.where(se.c4 > 0)
    td = pd.to_numeric(se.tdiff.astype(str).str.strip().str.replace('+', '', regex=False), errors='coerce') / 10
    se['tdiff'] = td.where(td.abs() < 30)
    log('出走', f'{len(se):,}', '距離が付いた割合', round(se.dist.notna().mean(), 4))
    return se


def ra_text():
    """KDSCOPE の RA.DAT(1 記録 1272 バイト)から高知のクラス名(637〜672)・条件の添え書き(673〜696)・天候(887)・ダートの馬場(889)。
    同じレースは作成日の新しい方。速報(区分 2)で馬場が 0 のものは欠け。"""
    import unicodedata
    L, rows = 1272, []
    with open('C:/KDSCOPE/Data/RA/RA.DAT', 'rb') as f:
        while True:
            buf = f.read(L * 200000)
            if not buf:
                break
            a = np.frombuffer(buf, dtype=np.uint8).reshape(-1, L)
            a = a[(a[:, 0] == 82) & (a[:, 1] == 65) & (a[:, 19] == 53) & (a[:, 20] == 52)]
            for r in a:
                b = bytes(r)
                t = lambda x, y: unicodedata.normalize('NFKC', b[x:y].decode('cp932', 'replace')).replace(' ', '')
                rows.append((b[3:11].decode(), int(b[11:15]), int(b[15:19]), int(b[25:27]), t(637, 673), t(673, 697),
                             t(32, 92), b[887] - 48, b[889] - 48))
    R = pd.DataFrame(rows, columns=['make', 'year', 'md', 'race', 'cls', 'note', 'rname', 'tenko', 'baba'])
    R = R.sort_values('make').drop_duplicates(['year', 'md', 'race'], keep='last').drop(columns='make')
    R['baba'] = R.baba.where(R.baba.between(1, 4))
    R['tenko'] = R.tenko.where(R.tenko.between(1, 6))
    import re
    lv = {'E': 0, 'D': 0.5, 'C3': 1, 'C2': 2, 'C1': 3, 'C': 2, 'B': 4, 'A': 5}  # D・E と数字なしの C は 2011 年ごろまでの古い格

    def parse(c, note, name):
        m = re.match(r'^(C[123]|[ABCDE])', c)
        young = 2 if c.startswith('2歳') else 3 if c.startswith('3歳') else 0
        kumi = re.search(r'-(\d+)', c)
        g = lv[m.group(1)] if m else (6 if (not c and name) else np.nan)
        kind = 3 if any(w in name + note for w in ['重賞', '杯', '賞典', 'カップ', '記念']) and not m else             2 if '選抜' in note or '選抜' in name else 1 if name else 0
        return g, int(kumi.group(1)) if kumi else np.nan, young, kind
    P = [parse(c, n, nm) for c, n, nm in zip(R.cls, R.note, R.rname)]
    R[['b_cls', 'b_kumi', 'b_young', 'b_kind']] = pd.DataFrame(P, index=R.index)
    R['jyo'] = np.int16(KOCHI)
    R['race'] = R.race.astype('int16')
    log('RA の高知', f'{len(R):,}', 'クラスが読めた', round(R.b_cls.notna().mean(), 3), '馬場あり', round(R.baba.notna().mean(), 3))
    print(R.cls.value_counts().head(12).to_dict())
    return R[['year', 'md', 'jyo', 'race', 'b_cls', 'b_kumi', 'b_young', 'b_kind', 'baba', 'tenko']]


def speed(se):
    """コースの物差し・その日の片寄り → 1 頭ごとの SI・上がり・テン。"""
    ok = se.time_sec.notna() & (se.dist > 0) & (se.surf < 2)
    se['v'] = np.where(ok, se.time_sec / se.dist * 1000, np.nan)  # 秒/km
    se['F'] = np.where(ok & (se.dist > 600) & se.l3f.notna(), (se.time_sec - se.l3f) / (se.dist - 600) * 1000, np.nan)
    se['course'] = se.jyo.astype(str) + '_' + se.dist.fillna(0).astype(int).astype(str) + '_' + se.surf.astype(str)
    top = se[(se.fin <= 3) & se.v.notna()]
    R = top.groupby(RK + ['course', 'year']).agg(vT=('v', 'mean'), lT=('l3f', 'mean')).reset_index()
    years = np.arange(int(R.year.min()), int(R.year.max()) + 1)
    S = R.pivot_table(index='course', columns='year', values='vT', aggfunc='sum').reindex(columns=years).fillna(0)
    C = R.pivot_table(index='course', columns='year', values='vT', aggfunc='count').reindex(columns=years).fillna(0)

    def win(k):
        return (S.T.rolling(k, min_periods=1).sum().shift(1).T, C.T.rolling(k, min_periods=1).sum().shift(1).T)
    s3, c3 = win(3)
    s6, c6 = win(6)
    base = (s3 / c3).where(c3 >= 30, (s6 / c6).where(c6 >= 15))
    base.index.name, base.columns.name = 'course', 'year'
    B = base.stack().rename('base').reset_index()
    R = R.merge(B, on=['course', 'year'], how='left')
    R['r'] = R.vT - R.base
    D = R.groupby(['date', 'jyo']).r.agg(['median', 'count']).reset_index()
    D['D'] = np.where(D['count'] >= 3, D['median'], 0.0)
    se = se.merge(B, on=['course', 'year'], how='left').merge(D[['date', 'jyo', 'D']], on=['date', 'jyo'], how='left')
    se['si'] = -(se.v - se.base - se.D.fillna(0))
    se = se.merge(R[RK + ['lT']], on=RK, how='left')
    se['up'] = se.lT - se.l3f
    se['ten'] = se.groupby(RK).F.transform('median') - se.F
    se['l3rank'] = se.groupby(RK).l3f.rank(method='min') / se.n
    se['c4rel'] = se.c4 / se.n
    se['finrel'] = se.fin / se.n
    log('SI が付いた割合(高知)', round(se.loc[se.jyo == KOCHI, 'si'].notna().mean(), 4))
    return se.drop(columns=['v', 'F', 'lT', 'D', 'base'])


def entity_rates(K, key, m=30):
    """高知での前 365 日(その日を含まない)の騎乗数・3 着内率・勝率(全体へ m 騎乗ぶん寄せる)。"""
    d = K.groupby([key, 'date']).agg(n=('Y3', 'size'), t3=('Y3', 'sum'), w=('Y1', 'sum')).reset_index().sort_values([key, 'date'])
    out = []
    for k, g in d.groupby(key, sort=False):
        r = g.set_index('date')[['n', 't3', 'w']].rolling('365D', closed='left').sum()
        r[key] = k
        out.append(r.reset_index())
    r = pd.concat(out).fillna(0)
    p3, p1 = K.Y3.mean(), K.Y1.mean()
    r['n365'] = r.n
    r['r3'] = (r.t3 + m * p3) / (r.n + m)
    r['r1'] = (r.w + m * p1) / (r.n + m)
    return r[[key, 'date', 'n365', 'r3', 'r1']]


def prior_rate(A, key, Q):
    """産駒などの、その日より前(その日を含まない)の全場の走りの数と 3 着内率。"""
    d = A[A[key].notna() & (A[key] != 0)].groupby([key, 'date']).agg(n=('Y3', 'size'), t3=('Y3', 'sum')).reset_index()
    d = d.sort_values([key, 'date'])
    d['N'] = d.groupby(key).n.cumsum()
    d['T'] = d.groupby(key).t3.cumsum()
    q = Q[[key, 'date']].drop_duplicates().dropna()
    q = q[q[key] != 0].sort_values('date')
    m = pd.merge_asof(q, d.sort_values('date')[[key, 'date', 'N', 'T']], on='date', by=key,
                      direction='backward', allow_exact_matches=False)
    m[['N', 'T']] = m[['N', 'T']].fillna(0)
    p = A.Y3.mean()
    m['rate'] = (m['T'] + 20 * p) / (m['N'] + 20)
    return m[[key, 'date', 'N', 'rate']]


def main():
    OUT.mkdir(exist_ok=True)
    se = speed(load_se())
    se = se.merge(ra_text(), on=['year', 'md', 'jyo', 'race'], how='left')
    se['wet'] = (se.baba >= 3).astype(float).where(se.baba.notna())
    hz = pd.read_parquet(V + 'kd_horse.parquet', columns=['ketto', 'sire_id', 'dam_id', 'bms_id'])
    hz['ketto'] = pd.to_numeric(hz.ketto, errors='coerce').fillna(0).astype('int64')
    hz = hz[hz.ketto > 0].drop_duplicates('ketto')
    se = se.merge(hz, on='ketto', how='left')
    keys = set(se.loc[(se.jyo == KOCHI) & (se.date >= START - pd.Timedelta(days=365)), 'ketto']) - {0}
    H = se[se.ketto.isin(keys)].sort_values(['ketto', 'date']).reset_index(drop=True)
    log('高知を走った馬', f'{len(keys):,}', '頭・その馬の全場の走り', f'{len(H):,}')

    g = H.groupby('ketto')
    sh = {k: g[['si', 'up', 'ten', 'tdiff', 'finrel', 'Y3', 'Y1', 'c4rel', 'c1', 'l3rank', 'dist', 'jyo', 'date',
                'prize1', 'jockey_cd', 'trainer_cd', 'kinryo', 'ijo', 'surf', 'n', 'b_cls', 'b_kumi']].shift(k) for k in range(1, 11)}
    X = pd.DataFrame(index=H.index)

    def stack(col, ks=range(1, 6)):
        return np.column_stack([sh[k][col].to_numpy(float) for k in ks])
    import warnings
    warnings.simplefilter('ignore', RuntimeWarning)
    si = stack('si')
    X['a_si1'], X['a_si2'], X['a_si3'] = si[:, 0], si[:, 1], si[:, 2]
    X['a_simax5'] = np.nanmax(si, 1)
    X['a_simean5'] = np.nanmean(si, 1)
    w = np.array([.35, .25, .2, .12, .08])
    msk = ~np.isnan(si)
    X['a_siw'] = np.where(msk.any(1), np.nansum(si * w, 1) / np.maximum((msk * w).sum(1), 1e-9), np.nan)
    X['a_sisd'] = np.nanstd(si, 1)
    X['a_sislope'] = si[:, 0] - np.nanmean(si[:, 1:], 1)
    up, ten = stack('up', range(1, 4)), stack('ten', range(1, 4))
    X['a_up1'], X['a_upw'] = up[:, 0], np.nanmean(up, 1)
    X['a_ten1'], X['a_tenw'] = ten[:, 0], np.nanmean(ten, 1)
    X['a_tdiff1'] = sh[1].tdiff
    fr, t3, w1 = stack('finrel'), stack('Y3'), stack('Y1')
    X['c_fin1'], X['c_fin5'] = fr[:, 0], np.nanmean(fr, 1)
    X['c_top3_5'], X['c_win5'] = np.nanmean(t3, 1), np.nanmean(w1, 1)
    X['c_out'] = (sh[1].ijo == 4).astype(float).where(sh[1].ijo.notna())
    c4 = stack('c4rel')
    X['f_c4_1'], X['f_front5'] = c4[:, 0], np.nanmean(c4, 1)
    X['f_c1_1'] = sh[1].c1 / sh[1].n
    X['f_nige5'] = np.nansum(stack('c1') == 1, 1)
    X['f_l3rank1'] = sh[1].l3rank
    # 経歴
    X['g_starts'] = g.cumcount()
    X['c_top3all'] = (g.Y3.cumsum() - H.Y3) / X.g_starts.replace(0, np.nan)
    X['c_winall'] = (g.Y1.cumsum() - H.Y1) / X.g_starts.replace(0, np.nan)
    isj = H.jyo.between(1, 10).astype(int)
    isk = (H.jyo == KOCHI).astype(int)
    X['l_jra'] = isj.groupby(H.ketto).cumsum() - isj
    X['l_kochi'] = isk.groupby(H.ketto).cumsum() - isk
    X['l_nar'] = X.g_starts - X.l_jra
    X['e_kochi_t3'] = ((H.Y3 * isk).groupby(H.ketto).cumsum() - H.Y3 * isk) / X.l_kochi.replace(0, np.nan)
    j1 = sh[1].jyo
    X['l_region'] = np.select([j1.isna(), j1 == KOCHI, j1.isin(NANKAN), j1.between(1, 10)], [-1, 0, 1, 3], 2)
    X['l_debut'] = (X.g_starts == 0).astype(int)
    X['g_rest'] = (H.date - sh[1].date).dt.days
    dd = np.column_stack([(H.date - sh[k].date).dt.days.to_numpy(float) for k in range(1, 11)])
    X['g_n90'] = (dd <= 90).sum(1)
    X['g_n365'] = (dd <= 365).sum(1)
    X['g_age'], X['g_sex'] = H.age, H.sex
    # 距離
    X['d_chg'] = H.dist - sh[1].dist
    gd = H.groupby(['ketto', 'dist'])
    nd = gd.cumcount()
    X['d_n'] = nd
    X['d_top3'] = (gd.Y3.cumsum() - H.Y3) / nd.replace(0, np.nan)
    X['d_simax'] = gd.si.shift().groupby([H.ketto, H.dist]).cummax()
    # クラス(1 着賞金)
    lp = np.log1p(H.prize1)
    X['b_prize'] = lp
    X['b_prizechg'] = lp - np.log1p(sh[1].prize1)
    pb = np.column_stack([np.where(sh[k].Y3.to_numpy(float) == 1, np.log1p(sh[k].prize1.to_numpy(float)), np.nan) for k in range(1, 11)])
    X['b_best3'] = np.nanmax(pb, 1)
    X['b_grade'] = H.grade.astype(str).str.strip().map({'A': 5, 'B': 4, 'C': 3, 'S': 2, 'L': 1}).fillna(0)
    # 高知のクラス名・馬場(KDSCOPE の RA の生記録)
    for c in ['b_cls', 'b_kumi', 'b_young', 'b_kind']:
        X[c] = H[c]
    X['b_clschg'] = H.b_cls - sh[1].b_cls
    X['b_kumichg'] = H.b_kumi - sh[1].b_kumi
    X['e_baba'], X['e_tenko'] = H.baba, H.tenko
    kw = (isk * H.wet.fillna(0)).astype(float)
    kd = (isk * H.wet.notna()).astype(float) - kw
    fw = (H.finrel.fillna(1) * kw)
    fd = (H.finrel.fillna(1) * kd)
    nw = kw.groupby(H.ketto).cumsum() - kw
    ndr = kd.groupby(H.ketto).cumsum() - kd
    X['e_wet_n'] = nw
    X['e_wetdiff'] = ((fw.groupby(H.ketto).cumsum() - fw) / nw.replace(0, np.nan)
                      - (fd.groupby(H.ketto).cumsum() - fd) / ndr.replace(0, np.nan))
    # 枠・斤量・コース
    X['j_umaban'], X['j_gate'], X['j_n'] = H.umaban, H.waku, H.n
    X['j_cw'] = H.kinryo
    X['j_cwchg'] = H.kinryo - sh[1].kinryo
    X['e_dist'] = H.dist
    X['e_month'] = H.date.dt.month
    X['e_race'] = H.race
    # 乗り替わり・転厩
    X['h_chg'] = (H.jockey_cd != sh[1].jockey_cd).astype(int).where(sh[1].jockey_cd.notna())
    X['i_move'] = (H.trainer_cd != sh[1].trainer_cd).astype(int).where(sh[1].trainer_cd.notna())
    X['h_pair'] = H.groupby(['ketto', 'jockey_cd']).cumcount()
    X['i_trest'] = X.g_rest.where(X.i_move == 1)
    keep = ['date', 'jyo', 'race', 'umaban', 'ketto', 'jockey_cd', 'trainer_cd', 'sire_id', 'dam_id', 'bms_id',
            'n', 'fin', 'Y1', 'Y3', 'odds', 'pop', 'year']
    T = pd.concat([H[keep], X], axis=1)
    T = T[(T.jyo == KOCHI) & (T.date >= START - pd.Timedelta(days=365))].reset_index(drop=True)
    T = T.rename(columns={'odds': 'mk_odds', 'pop': 'mk_pop'})
    log('高知の行', f'{len(T):,}')
    # 高知で ketto 0 の走り(0.2%)は相手として数に入っているが、行には無い
    K = se[se.jyo == KOCHI]
    for key, pf in [('jockey_cd', 'h_j'), ('trainer_cd', 'i_t')]:
        r = entity_rates(K, key)
        T = T.merge(r.rename(columns={'n365': pf + 'n', 'r3': pf + '3', 'r1': pf + '1'}), on=[key, 'date'], how='left')
        log(pf, '済み')
    for key, pf in [('sire_id', 'c7_s'), ('bms_id', 'c7_b'), ('dam_id', 'c7_d')]:
        r = prior_rate(se, key, T)
        T = T.merge(r.rename(columns={'N': pf + '_n', 'rate': pf + '_t3'}), on=[key, 'date'], how='left')
        log(pf, '済み')
    # 中央の成績
    J = se[se.jyo.between(1, 10) & se.ketto.isin(keys)].sort_values('date')
    J = J.assign(jw=J.Y1, jt=J.Y3, jd=J.date)[['ketto', 'date', 'jw', 'jt', 'jd', 'fin']]
    J['jn'] = 1
    J[['jn', 'jw', 'jt']] = J.groupby('ketto')[['jn', 'jw', 'jt']].cumsum()
    J['jbest'] = J.groupby('ketto').fin.cummin()
    J['date_q'] = J.date + pd.Timedelta(days=1)
    T = T.sort_values('date')
    T = pd.merge_asof(T, J[['ketto', 'date_q', 'jn', 'jw', 'jt', 'jd', 'jbest']].rename(columns={'date_q': 'date'}),
                      on='date', by='ketto', direction='backward')
    T['j7_n'] = T.jn.fillna(0)
    T['j7_w'] = T.jw.fillna(0)
    T['j7_t3'] = T.jt / T.jn
    T['j7_best'] = T.jbest
    T['j7_days'] = (T.date - T.jd).dt.days
    T = T.drop(columns=['jn', 'jw', 'jt', 'jd', 'jbest'])
    # レースの中での位置(k・r・p)
    for c, pf in [('a_simax5', 'k_si'), ('a_siw', 'k_ab'), ('a_si1', 'p_si1'), ('c_top3all', 'r_t3'), ('h_j3', 'r_j3')]:
        gg = T.groupby(RK)[c]
        T[pf + '_rank'] = gg.rank(ascending=False, method='min')
        T[pf + '_z'] = (T[c] - gg.transform('mean')) / gg.transform('std')
        T[pf + '_gap'] = gg.transform('max') - T[c]
    T = T[T.date >= START].sort_values(RK + ['umaban']).reset_index(drop=True)
    T.to_parquet(OUT / FEAT, index=False)
    F = [c for c in T.columns if c[:2] in ('a_', 'b_', 'c_', 'd_', 'e_', 'f_', 'g_', 'h_', 'i_', 'j_', 'k_', 'l_', 'p_', 'r_')
         or c.startswith(('c7_', 'j7_', 'h_j', 'i_t'))]
    F = [c for c in F if c not in ('h_j', 'i_t') and c not in ('jockey_cd',)]
    log('保存', OUT / FEAT, T.shape, '材料', len(F))
    na = T[F].isna().mean().sort_values(ascending=False).head(12).round(3)
    print(na.to_string())
    print(T.groupby(T.date.dt.year).size().to_string())


if __name__ == '__main__':
    main()
