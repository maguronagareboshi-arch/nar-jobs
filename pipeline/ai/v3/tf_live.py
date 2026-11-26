# -*- coding: utf-8 -*-
"""南関 移籍馬の専用の木(研究 nankan-ai-v3 src/f5_scripts/tf_feat_1126.py・tf_model_1126.py・tf_prod_1126.py・判定 2026-11-26 合格・ユーザー承認 11/26)。

対象 = 南関所属の馬の 中央から(他地区の地方の出走 0・南関の出走 0〜2・中央の出走あり)/他場から(南関の出走 0〜2・他地区の地方の出走あり)の 1〜3 戦目。
材料 = 前の場・中央での様子 68 列 + 頭数(公式の表 runs・races・jra・jrah と その日の調教 t8.cy_feats)= 走る前に分かる値だけ。
木 = 移籍馬の行だけで学んだ 3 着内の LightGBM(土台を使わない・種 3 本の平均)の logit v。
混ぜ = 移籍馬だけ 3 着内の logit を z3 + A × (v − z3)(前日版 A_PRE・直前版 A_DAY)→ 勝つ率は動かさない → 3 着内を合計 3・勝つ率以上に直す(t6_base.p3prime)。
  前日の便: 第34版 前日版の最後の率の上で混ぜる(表を直す)。当日の便の土台には混ぜる前の率を渡し、v を 'TF:v' の列で渡す。
  当日の便: 第34版 直前版の最後の率の上で 'TF:v' を A_DAY で混ぜる。
定数(ON・A_PRE・A_DAY・TAG・模型のファイル名)と模型は暗号化したリリース v3-consts の consts.json の tf と tf_s*.txt(無ければ動かない = 第34版のまま)。
"""
import numpy as np
import pandas as pd

K = ['track', 'race_date', 'race_no', 'umaban']
NK = ['大井', '船橋', '川崎', '浦和']
TRACKS = ['佐賀', '名古屋', '園田', '大井', '姫路', '川崎', '水沢', '浦和', '盛岡', '笠松', '船橋', '金沢', '門別', '高知']   # 研究の sorted(R.track.unique())
CYC = ['cy_day_pct', 'cy_self', 'cy_stable', 'cy_int', 'cy_n14', 'cy_gap', 'cy_awase']
_C = None
_M = None


def log0(*a):
    print(*a, flush=True)


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('tf')
        for k in ('ON', 'A_PRE', 'A_DAY', 'TAG', 'files', 'cols'):
            if k not in _C:
                raise KeyError(f'tf に {k} が無い')
    return _C


def is_on(day):
    return str(day) >= str(consts().get('ON') or '9999-12-31')


def tag():
    return consts()['TAG']


def load():
    """模型(種ごとの Booster)。"""
    global _M
    if _M is None:
        import lightgbm as lgb
        import sealed
        C = consts()
        _M = [lgb.Booster(model_file=str(sealed.path(f))) for f in C['files']]
    return _M


def _num(d):
    d['race_date'] = pd.to_datetime(d.race_date).dt.strftime('%Y-%m-%d')
    d['race_no'] = d.race_no.astype(int)
    if 'umaban' in d:
        d['umaban'] = d.umaban.astype(int)
    return d


def jcls(s):
    s = str(s)
    if '新馬' in s or '未勝利' in s:
        return 0
    if '1勝' in s or '500万' in s:
        return 1
    if '2勝' in s or '1000万' in s:
        return 2
    if '3勝' in s or '1600万' in s:
        return 3
    return 4


def official(OF):
    """公式の表(k0_dl が落とした runs・races・jra・jrah)を研究と同じ形に読む。"""
    OF = str(OF).rstrip('/\\') + '/'
    RA = _num(pd.read_parquet(OF + 'races.parquet', columns=['track', 'race_date', 'race_no', 'surface', 'distance_m', 'field_size', 'prize_yen', 'cancelled']))
    RA = RA.drop_duplicates(['track', 'race_date', 'race_no'])
    RA['prize_yen'] = pd.to_numeric(RA.prize_yen, errors='coerce')
    RA['distance_m'] = pd.to_numeric(RA.distance_m, errors='coerce')
    R0 = pd.read_parquet(OF + 'runs.parquet', columns=['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'birth_date', 'age', 'sex',
                                                       'trainer_area', 'finish', 'time_sec', 'last3f'])
    R0 = R0[R0.track != '帯広ば'].rename(columns={'runner_number': 'umaban'})
    R0 = _num(R0).drop_duplicates(K)
    JH = pd.read_parquet(OF + 'jrah.parquet', columns=['kb_horse_id', 'horse_name', 'birth_date', 'jra_career_runs', 'last_jra_date'])
    J = pd.read_parquet(OF + 'jra.parquet', columns=['kb_horse_id', 'race_date', 'race_name', 'surface', 'distance', 'field_size', 'finish', 'last3f',
                                                     'race_last3f', 'passing'])
    return {'RA': RA, 'R0': R0, 'JH': JH, 'J': J}


def card(O, day):
    """その日の南関の出走表(公式の表の行 = 研究の db_runs と同じ列)。"""
    R0 = O['R0']
    C = R0[(R0.race_date == str(day)[:10]) & R0.track.isin(NK)]
    return C[K + ['horse_name', 'birth_date', 'age', 'sex', 'trainer_area']].copy()


def feats(X, O, CY=None):
    """X = 予想する行(K + horse_name・birth_date・age・sex・trainer_area)。→ X と同じ並びの grp・n_senme(何戦目・全部の行)と 68 列(研究の f_ を外した名前)。
    研究 tf_feat_1126.py と同じ計算(行の並び・欠けの扱いまで)。"""
    X = _num(X.copy()).reset_index(drop=True)
    RA = O['RA']
    X = X.merge(RA[['track', 'race_date', 'race_no', 'distance_m', 'field_size', 'prize_yen']], on=['track', 'race_date', 'race_no'], how='left')
    X['d'] = pd.to_datetime(X.race_date)
    X['row'] = np.arange(len(X))
    X['age'] = pd.to_numeric(X.age, errors='coerce')
    R = O['R0'][['track', 'race_date', 'race_no', 'umaban', 'horse_name', 'age', 'trainer_area', 'finish', 'time_sec', 'last3f']].copy()
    R = R.merge(RA, on=['track', 'race_date', 'race_no'], how='left')
    R['fin'] = pd.to_numeric(R.finish, errors='coerce')
    for c in ('time_sec', 'last3f', 'age'):
        R[c] = pd.to_numeric(R[c], errors='coerce')
    R['rid'] = R.track + R.race_date + R.race_no.astype(str)
    R['nst'] = R.groupby('rid').umaban.transform('size')
    R['rel'] = (R.fin / R.nst).fillna(1.0)
    R['uprk'] = R.groupby('rid').last3f.rank(pct=True)
    R['tb'] = R.time_sec - R.groupby('rid').time_sec.transform('min')
    R['lpz'] = np.log1p(R.prize_yen.fillna(0))
    R['nkt'] = R.track.isin(NK)
    R['d'] = pd.to_datetime(R.race_date)
    H = X[['row', 'horse_name', 'd', 'age']].merge(R[['horse_name', 'd', 'age', 'track', 'nkt', 'fin', 'rel', 'uprk', 'tb', 'lpz', 'distance_m']],
                                                     on='horse_name', suffixes=('', '_r'))
    H = H[(H.d_r < H.d) & (H.d_r >= H.d - pd.to_timedelta((H.age.astype(float) - 1) * 365 + 200, unit='D'))].sort_values(['row', 'd_r'])
    g = H.groupby('row')
    X['nar_prev'] = g.size().reindex(X.row).fillna(0).to_numpy()
    X['nk_prev'] = H[H.nkt].groupby('row').size().reindex(X.row).fillna(0).to_numpy()
    X['oth_prev'] = X.nar_prev - X.nk_prev
    JH = O['JH'].copy()
    JH['birth_date'] = pd.to_datetime(JH.birth_date, errors='coerce').dt.strftime('%Y-%m-%d')
    X['bd'] = pd.to_datetime(X.birth_date, errors='coerce').dt.strftime('%Y-%m-%d')
    JH = JH.dropna(subset=['birth_date']).drop_duplicates(['horse_name', 'birth_date'])
    X = X.merge(JH.rename(columns={'birth_date': 'bd'}), on=['horse_name', 'bd'], how='left')
    J = O['J'].drop_duplicates(['kb_horse_id', 'race_date']).copy()
    J['d'] = pd.to_datetime(J.race_date)
    J = J[J.surface.isin(['芝', 'ダ', 'ダート'])].copy()
    J['dirt'] = J.surface.str.startswith('ダ')
    J['cls'] = J.race_name.map(jcls)
    J['fin'] = pd.to_numeric(J.finish, errors='coerce')
    for c in ('field_size', 'last3f', 'race_last3f', 'distance'):
        J[c] = pd.to_numeric(J[c], errors='coerce')
    J['rel'] = (J.fin / J.field_size).fillna(1.0)
    J['ud'] = J.last3f - J.race_last3f
    J['pos1'] = J.passing.astype(str).str.extract(r'^(\d+)')[0].astype(float) / J.field_size
    JJ = X[['row', 'kb_horse_id', 'd', 'distance_m']].dropna(subset=['kb_horse_id']).merge(J.drop(columns=['race_date']), on='kb_horse_id', suffixes=('', '_j'))
    JJ = JJ[JJ.d_j < JJ.d].sort_values(['row', 'd_j'])
    X['jn'] = JJ.groupby('row').size().reindex(X.row).fillna(0).to_numpy()
    lj = pd.to_datetime(X.last_jra_date, errors='coerce')
    fa = g.age_r.first().reindex(X.row).to_numpy()
    X['age1'] = np.where(np.isnan(fa), X.age.astype(float), fa)
    X['jra_any'] = (X.jn > 0) | ((X.jra_career_runs.fillna(0) > 0) & (lj < X.d)) | (X.age1 >= 3)
    X['j_hole'] = (X.jn == 0) & X.jra_any
    nka = X.trainer_area.isin(NK)
    X['grp'] = np.select([nka & (X.oth_prev == 0) & (X.nk_prev <= 2) & X.jra_any, nka & (X.oth_prev >= 1) & (X.nk_prev <= 2)], ['A', 'B'], '')
    X['senme'] = X.nk_prev + 1
    T = X.row[X.grp != ''].to_numpy()
    F = pd.DataFrame(index=X.row)
    jj = JJ[JJ.row.isin(T)]
    gj = jj.groupby('row')
    xi = X.set_index('row')
    F['j_n'] = xi.jn
    F['j_w'] = gj.fin.apply(lambda s: (s == 1).sum())
    F['j_t3'] = gj.fin.apply(lambda s: (s <= 3).sum())
    F['j_maxcls'] = gj.cls.max()
    F['j_t3cls'] = jj[jj.fin <= 3].groupby('row').cls.max()
    F['j_t3w'] = jj[jj.fin <= 3].groupby('row').cls.apply(lambda s: (s + 1).sum())
    mc = jj.merge(F.j_maxcls.rename('mc'), left_on='row', right_index=True)
    mc = mc[mc.cls == mc.mc].groupby('row')
    F['j_n_maxcls'] = mc.size()
    F['j_rel_maxcls'] = mc.rel.mean()
    F['j_best_maxcls'] = mc.fin.min()
    F['j_last_cls'] = gj.cls.last()
    F['j_last_rel'] = gj.rel.last()
    F['j_l3_rel'] = gj.rel.apply(lambda s: s.iloc[-3:].mean())
    F['j_trend'] = gj.rel.apply(lambda s: s.iloc[-1] - s.iloc[:-1].mean() if len(s) > 1 else np.nan)
    F['j_days'] = (xi.d - gj.d_j.last()).dt.days
    for nm, msk in (('dirt', jj.dirt), ('turf', ~jj.dirt)):
        q = jj[msk].groupby('row')
        F[f'j_{nm}_n'] = q.size()
        F[f'j_{nm}_best'] = q.rel.min()
        F[f'j_{nm}_l3'] = q.rel.apply(lambda s: s.iloc[-3:].mean())
        F[f'j_{nm}_udbest'] = q.ud.min()
        F[f'j_{nm}_udl3'] = q.ud.apply(lambda s: s.iloc[-3:].mean())
    sb = jj[jj.dirt & ((jj.distance - jj.distance_m).abs() <= 200)].groupby('row')
    F['j_sb_n'] = sb.size()
    F['j_sb_best'] = sb.rel.min()
    F['j_sb_udbest'] = sb.ud.min()
    F['j_pos1_dirt'] = jj[jj.dirt].groupby('row').pos1.mean()
    F['j_career'] = xi.jra_career_runs
    F['j_hole'] = xi.j_hole.astype(float)
    hh = H[H.row.isin(T)]
    for nm, msk in (('o', ~hh.nkt), ('k', hh.nkt)):
        q = hh[msk].groupby('row')
        F[f'{nm}_n'] = q.size()
        F[f'{nm}_l3_rel'] = q.rel.apply(lambda s: s.iloc[-3:].mean())
        F[f'{nm}_best'] = q.fin.min()
        F[f'{nm}_w'] = q.fin.apply(lambda s: (s == 1).sum())
        F[f'{nm}_t3r'] = q.fin.apply(lambda s: (s <= 3).mean())
        F[f'{nm}_up_l3'] = q.uprk.apply(lambda s: s.iloc[-3:].mean())
        F[f'{nm}_tb_l3'] = q.tb.apply(lambda s: s.iloc[-3:].mean())
        F[f'{nm}_lpz_l3'] = q.lpz.apply(lambda s: s.iloc[-3:].mean())
        F[f'{nm}_days'] = (xi.d - q.d_r.last()).dt.days
    F['o_pz_gap'] = np.log1p(xi.prize_yen.fillna(0)) - F.o_lpz_l3
    F['k_pz_gap'] = np.log1p(xi.prize_yen.fillna(0)) - F.k_lpz_l3
    lastoth = hh[~hh.nkt].groupby('row').track.last()
    F['o_track'] = lastoth.map({t: i for i, t in enumerate(sorted(TRACKS))})
    oo = hh[~hh.nkt]
    F['o_rel_top'] = oo.groupby('row').apply(lambda d: d.rel[d.lpz >= d.lpz.max() - 0.01].mean()) if len(oo) else np.nan
    F['rest'] = (xi.d - g.d_r.last()).dt.days.fillna(F.j_days)
    C2 = X[K + ['row']].copy()
    if CY is not None and len(CY):
        CY = _num(CY.copy()).drop_duplicates(K)
        C2 = C2.merge(CY[K + [c for c in CYC if c in CY.columns]], on=K, how='left')
    for c in CYC:
        if c not in C2:
            C2[c] = np.nan
    C2['rid'] = C2.track + C2.race_date + C2.race_no.astype(str)
    C2['cy_rk'] = C2.groupby('rid').cy_day_pct.rank(pct=True, ascending=False)
    for c in CYC + ['cy_rk']:
        F[c] = C2.set_index('row')[c]
    F['grpB'] = (xi.grp == 'B').astype(float)
    F['senme'] = xi.senme
    F['age'] = xi.age
    F['dist'] = xi.distance_m
    F['lpz'] = np.log1p(xi.prize_yen.fillna(0))
    F['trk'] = xi.track.map({t: i for i, t in enumerate(NK)})
    F['female'] = xi.sex.isin(['牝']).astype(float)
    F.loc[~F.index.isin(T)] = np.nan
    out = X[K + ['grp', 'horse_name']].assign(n_senme=X.senme.to_numpy()).reset_index(drop=True).join(F.reset_index(drop=True))
    return out


def predict(Fe, nfield):
    """移籍馬の行の木の logit v(ほかは NaN)。Fe = feats の戻り・nfield = 行ごとのレースの頭数。"""
    cols = consts()['cols']
    A = np.column_stack([Fe[c].to_numpy(float) for c in cols[:-1]] + [np.asarray(nfield, float)])
    v = np.full(len(Fe), np.nan)
    m = (Fe.grp.fillna('') != '').to_numpy()
    if m.any():
        M = load()
        v[m] = np.mean([b.predict(A[m], raw_score=True) for b in M], axis=0)
    return v


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def mix(p1, p3, v, a):
    """1 レースの (p1, p3) に移籍馬の木 v(NaN = 移籍馬でない)を a で混ぜる。→ (p1′, p3′)。研究 tf_model_1126.apply(c = 0)と同じ式。"""
    import t6_base
    p1, p3, v = np.asarray(p1, float), np.asarray(p3, float), np.asarray(v, float)
    z3 = lg(np.clip(p3, 1e-9, 1 - 1e-9))
    du = np.where(np.isfinite(v), a * (np.nan_to_num(v) - z3), 0.0)
    lp = np.log(np.clip(p1, 1e-12, 1))
    w = np.exp(lp - lp.max())
    p1n = w / w.sum()
    s = 1 / (1 + np.exp(-(z3 + du)))
    q = t6_base.p3prime(pd.DataFrame({'rid': np.zeros(len(p3), int), 'p3': np.maximum(s, np.minimum(p1n, 0.999))}), 'p3', key=['rid'])[0]
    return p1n, q


# ------------------------------------------------------------------ 前日の便(v3_daily)
def run_pre(day, csv_path, base_csv, OF, CY, PT74, log=log0):
    """前日の表(第34版 前日版の最後)を直し、v を土台へ 'TF:v' で書く。→ (混ぜる前の表の写しの path か None, {(場, R): meta})。
    混ぜるのは ON の日から・前日版が第34版(meta.pt74.s34)のレースだけ。v は全部のレースで土台に書く(当日の便は第34版の時だけ使う)。"""
    from pathlib import Path
    csv_path, base_csv = Path(csv_path), Path(base_csv)
    C = consts()
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    x['race_date'] = x.race_date.astype(str).str[:10]
    x['race_no'] = pd.to_numeric(x.race_no).astype(int)
    x['umaban'] = pd.to_numeric(x.umaban).astype(int)
    O = official(OF)
    Cd = card(O, day)
    X = x[K].merge(Cd, on=K, how='left')
    if X.horse_name.isna().any():
        log('(前日) 移籍馬の木: 公式の出走表に無い行', int(X.horse_name.isna().sum()), '頭(その馬は移籍馬でない扱い)')
    Xk = X[X.horse_name.notna()].reset_index(drop=True)
    Fe = feats(Xk, O, CY)
    nf = x.groupby(['track', 'race_no']).umaban.transform('size').to_numpy(float)
    Fe = x[K].merge(Fe, on=K, how='left')
    v = predict(Fe, nf)
    Fe['v'] = v
    # 土台へ(当日の便が読む)
    # 前からの列は文字のまま読んで書く(dayonpre77_live.write_base と同じ・当日の便の材料を 1 桁も変えない)
    vb = pd.read_csv(base_csv, encoding='utf-8-sig', dtype=str, keep_default_na=False)
    vb = vb.drop(columns=[c for c in vb.columns if c.startswith('TF:')])
    k = pd.DataFrame({'track': vb.track, 'race_date': vb.race_date.str[:10], 'race_no': pd.to_numeric(vb.race_no).astype(int),
                      'umaban': pd.to_numeric(vb.umaban).astype(int)})
    key = k.merge(Fe[K + ['v', 'grp', 'n_senme']].drop_duplicates(K), on=K, how='left', validate='m:1')
    assert len(key) == len(vb)
    vb['TF:v'] = [repr(float(t)) if np.isfinite(t) else '' for t in key.v.to_numpy(float)]
    vb['TF:grp'] = key.grp.fillna('').to_numpy()
    vb['TF:senme'] = [str(int(t)) if np.isfinite(t) else '' for t in key.n_senme.to_numpy(float)]
    vb.to_csv(base_csv, index=False, encoding='utf-8-sig')
    n_tf = int(np.isfinite(v).sum())
    log('(前日) 移籍馬の木', n_tf, '頭(中央から', int((Fe.grp == 'A').sum()), '・他場から', int((Fe.grp == 'B').sum()), ')・土台へ TF:v')
    out = {}
    if not is_on(day):
        log('(前日) 移籍馬の木 ON の前(混ぜない)', C.get('ON'))
        return None, out
    keep = csv_path.with_name(csv_path.stem + '_notf.csv')
    x0 = pd.read_csv(csv_path, encoding='utf-8-sig')
    x0.to_csv(keep, index=False, encoding='utf-8-sig')
    a = float(C['A_PRE'])
    st = {'on': 0, 'off': 0, 'err': 0}
    for (tr, rno), gi in x.groupby(['track', 'race_no'], sort=False).groups.items():
        m74 = (PT74 or {}).get((tr, int(rno))) or {}
        if not (m74.get('on') and m74.get('s34')):
            st['off'] += 1
            continue
        ix = np.asarray(sorted(gi, key=lambda i: int(x0.umaban[i])))
        try:
            vv = v[ix]
            p1n, p3n = mix(x0.p1.to_numpy(float)[ix], x0.p3p.to_numpy(float)[ix], vv, a)
            if not (np.isfinite(p1n).all() and np.isfinite(p3n).all() and abs(p1n.sum() - 1) < 1e-6 and abs(p3n.sum() - 3) < 1e-6 and (p1n <= p3n + 1e-12).all()):
                raise ValueError('率が数でないか合計が 1・3 でないか勝つ率 > 3 着内')
            x0.loc[ix, 'p1'], x0.loc[ix, 'p3p'] = p1n, p3n
            nm = np.isfinite(vv)
            out[(tr, int(rno))] = {'on': True, 'tag': tag(), 'a': a, 'n': int(nm.sum()),
                                   'v': {str(int(x0.umaban[i])): round(float(t), 5) for i, t, f in zip(ix, vv, nm) if f}}
            st['on'] += 1
        except Exception as e:  # noqa: BLE001  落ちたレースは第34版のまま
            out[(tr, int(rno))] = {'on': False, 'err': f'{type(e).__name__} {str(e)[:80]}'}
            st['err'] += 1
    KEY = ['track', 'race_date', 'race_no']
    MK = ['◎', '○', '▲', '△', '☆']
    o = x0.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x0['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x0.index)
    x0['mark'] = x0['rank'].map(dict(enumerate(MK, 1))).fillna('')
    x0 = x0.sort_values(KEY + ['rank'], kind='mergesort')
    x0.to_csv(csv_path, index=False, encoding='utf-8-sig')
    log('(前日) 移籍馬の木 混ぜた', st)
    return keep, out


# ------------------------------------------------------------------ 当日の便(v29_gap.day_marks・第34版の後)
def apply_day(b, day, p1, p3):
    """1 レースの土台 b('TF:v')と第34版 直前版の最後の (p1, p3)。→ {'on', 'p1', 'p3', 'meta'}。"""
    m = {'tag': None, 'on': False}
    try:
        C = consts()
        m['tag'] = tag()
        if not is_on(day):
            m['why'] = 'ON の前'
            return {'on': False, 'meta': m}
        if 'TF:v' not in b.columns:
            m['why'] = '土台に TF:v なし'
            return {'on': False, 'meta': m}
        v = pd.to_numeric(b['TF:v'], errors='coerce').to_numpy(float)
        a = float(C['A_DAY'])
        p1n, p3n = mix(p1, p3, v, a)
        if not (np.isfinite(p1n).all() and np.isfinite(p3n).all() and abs(p1n.sum() - 1) < 1e-6 and abs(p3n.sum() - 3) < 1e-6 and (p1n <= p3n + 1e-12).all()):
            raise ValueError('率が数でないか合計が 1・3 でないか勝つ率 > 3 着内')
        nm = np.isfinite(v)
        m.update(on=True, a=a, n=int(nm.sum()), v={str(int(n)): round(float(t), 5) for n, t, f in zip(b.umaban, v, nm) if f})
        return {'on': True, 'p1': p1n, 'p3': p3n, 'meta': m}
    except Exception as e:  # noqa: BLE001
        m['err'] = f'{type(e).__name__} {str(e)[:80]}'
        return {'on': False, 'meta': m}
