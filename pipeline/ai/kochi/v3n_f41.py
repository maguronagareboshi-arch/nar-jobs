# -*- coding: utf-8 -*-
"""他場版 v3n の直前版に「決め 41」の材料 29 個を直線のずらしで足す(2026-10-17・v3 の out/v3n_f10k_judge.md・決め書 out/v3n_f10k_plan.md)。

材料の主 = 今日と同じ騎手でこの馬が走った時の過去の成績(着差・速さ・賞金・4 角の位置)。ほかに 調教師 × 距離帯の最近の上振れ・
騎手 × 馬の着差・父/生産者の群の成績・前半の速さのむら・2・3 角の動き。研究は KDSCOPE で作った値で判定し、本番は公式の表
(runs・races・jra・jrah・profiles)から同じ式で作る(研究も本番入れの照合でこの部品を使って学び直した = 研究と本番の値は同じ)。
人気・オッズは使わない。

  prep(off, day, tracks)  直前便の頭で 1 回: 今日の出走馬の 29 個の元の値(順位にする前)→ today/v3n_f41.npz
  shift(F, q3, nums)      周ごと: 残った馬(取消の後)の 3 着内率 q3 に足す logit のずらし(定数は暗号化の consts.json の v3n_f41)

形(研究と同じ): 各材料をレースの中の順位(0〜1)− 0.5 → レースの中で平均を引く → 空は 0 → 土台の logit(レースの中で平均を引いた c)に
直交(X − c β)→ s = X · b。q3′ = 合計 3 にそろえた σ(logit q3 + s)。
"""
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'v3'))
sys.path.insert(0, str(HERE.parent))

NAMES = [  # 研究の名前(out/v3n_f10k_kept.csv の順)。# の後 = raw(そのまま)/ rk(レースの中の順位)。どちらも shift でもう一度順位にする
    'o/g|jh|none|all|ts#raw', 'o/h|jockey|prz|m10#rk', 'o/h|jockey|tkm|m10#rk', 'o/h|jockey|spd|l1#rk', 'o/h|jockey|fin_cls|m3#rk',
    'o/h|jockey|tkm|m2#rk', 'o/h|jockey|prz|n3#raw', 'o/h|jockey|tsec|m3#raw', 'o/h|jockey|spd|m3#rk', 'o/h|jockey|spd|all#rk',
    'o/h|jockey|tkm|n3#rk', 'o/h|jyo_dband|spd|m2#raw', 'o/e|trainer_cd|dband|90|lift#raw', 'o/g|breeder_cd|agec|all|fr-par#raw',
    'o/h|dband|prz|m2#raw', 'o/h|jockey|c4r|all#rk', 'x|o/h|none|c4r|m5*o/h|none|fin_cls|l1#raw', 'o/h|jockey|tsec|x3#rk',
    'o/h|clsb|pre_z|s10#raw', 'o/g|sire|src|all|fr-par#raw', 'x|o/h|none|c4r|m5*o/h|none|prz|l1#rk', 'o/h|jockey|tsec|x10#raw',
    'k/h|jockey|g34|l1#rk', 'x|o/h|none|tsec|l1*k/h|none|c3r|m5#rk', 'o/h|jockey|spd|n3#raw', 'o/h|season|top3|n3#raw',
    'o/h|jyo_dband|spd|x3#rk', 'x|o/h|none|top3|l1*o/h|none|spd_j|l1#raw', 'o/h|dband|tkm|m2#rk']
CANCEL = {'取消', '出走取消', '除外', '競走除外', '枠順発表前取消'}
STOP = {'中止', '競走中止', '落馬'}
LAGS = 10
WIN = {'l1': (1, 'v'), 'm2': (2, 'mean'), 'm3': (3, 'mean'), 'x3': (3, 'max'), 'n3': (3, 'min'), 'm5': (5, 'mean'),
       'm10': (10, 'mean'), 'x10': (10, 'max'), 's10': (10, 'std')}


def _dnum(s):
    return (pd.to_datetime(pd.Series(s).astype(str).str[:10]) - pd.Timestamp('2000-01-01')).dt.days.to_numpy(np.int64)


def _asof_stats(key, day, x, W=365, nmin=20):
    """key の群の、その日より前 W 日の x の平均・標準偏差(その日を含まない・nmin 走未満は空)= 「その日まで」のならし"""
    ok = ~np.isnan(x)
    D = pd.DataFrame({'k': key[ok], 'd': day[ok], 'n': 1.0, 's': x[ok], 'q': x[ok] ** 2}).groupby(['k', 'd'], sort=True).sum().reset_index()
    kc, ku = pd.factorize(D.k, sort=True)
    comb = kc.astype(np.int64) * 1000000 + D.d.to_numpy()
    C = {c: np.r_[0.0, np.cumsum(D[c].to_numpy())] for c in ('n', 's', 'q')}
    qk = pd.Index(ku).get_indexer(key)
    hi = np.searchsorted(comb, qk * 1000000 + day, 'left')
    lo = np.searchsorted(comb, qk * 1000000 + day - W, 'left')
    n, s, q = (C[c][hi] - C[c][lo] for c in ('n', 's', 'q'))
    mu = np.where((qk >= 0) & (n >= nmin), s / np.maximum(n, 1), np.nan)
    sd = np.sqrt(np.maximum(q / np.maximum(n, 1) - mu ** 2, 0) * n / np.maximum(n - 1, 1))
    return mu, np.where(sd > 0, sd, np.nan)


def _seq(a):
    """配列ならそのまま・空(None・NaN = 成績はあるがレースの表にまだ無い R のつなぎ)なら None"""
    return a if isinstance(a, (list, tuple, np.ndarray)) else None


def _ok(o):
    return o is not None and not (isinstance(o, float) and o != o)


def runs_frame(off):
    """公式の表 → 研究 v3n_f10k.build の R と同じ列の表(地方 14 場 + 中央・馬は 名前|生まれ年 でつなぐ)。"""
    import seq2_live as S2
    off = Path(off)
    r = pd.read_parquet(off / 'runs.parquet')
    r = r[(r.track != '帯広ば') & ~r.finish_note.isin(CANCEL)].copy()
    ra = pd.read_parquet(off / 'races.parquet')
    ra = ra[ra.track != '帯広ば'].drop_duplicates(['track', 'race_date', 'race_no'])
    ra['prize1'] = ra.prize_yen.map(lambda a: float(_seq(a)[0]) / 100 if _seq(a) is not None and len(_seq(a)) else np.nan)   # KDS と同じ 100 円単位

    def corner(c, k):   # 後ろから数えた角(k = 1 → 4 角・2 → 3 角・3 → 2 角・4 → 1 角)
        c = _seq(c)
        if c is None or len(c) < k:
            return None
        return c[len(c) - k]['order']
    for k, nm in ((1, 'o4'), (2, 'o3'), (3, 'o2'), (4, 'o1')):
        ra[nm] = ra.corners.map(lambda c, k=k: corner(c, k))
    r['race_date'] = r.race_date.astype(str).str[:10]
    ra['race_date'] = ra.race_date.astype(str).str[:10]
    r = r.merge(ra[['track', 'race_date', 'race_no', 'surface', 'distance_m', 'prize1', 'prize_yen', 'o1', 'o2', 'o3', 'o4']],
                on=['track', 'race_date', 'race_no'], how='left')
    r['hk'] = r.horse_name.str.strip() + '|' + (r.race_date.str[:4].astype(int) - r.age).astype('Int64').astype(str)
    fin = pd.to_numeric(r.finish, errors='coerce')
    okf = fin.notna() & (fin > 0) & ~r.finish_note.isin(STOP | {'失格'})
    r['finish'] = fin.where(okf)
    r['prize'] = [np.nan if (a is None or len(a) == 0 or f != f) else (float(a[int(f) - 1]) / 100 if f <= len(a) else 0.0)
                  for a, f in zip(r.prize_yen.map(_seq), r.finish)]
    for i in (1, 2, 3, 4):
        r[f'c{i}'] = [S2.corner_pos(o, n) if _ok(o) else np.nan for o, n in zip(r[f'o{i}'], r.runner_number)]
    L = pd.DataFrame({'track': r.track, 'race_date': r.race_date, 'race': r.race_no.astype(float), 'umaban': r.runner_number.astype(float),
                      'hk': r.hk, 'src': 0.0, 'rid': r.track + '|' + r.race_date + '|' + r.race_no.astype(str),
                      'jockey': r.jockey.astype(str).str.strip().where(r.jockey.notna()), 'trainer': r.trainer.astype(str).str.strip().where(r.trainer.notna()),
                      'age': pd.to_numeric(r.age, errors='coerce'), 'kinryo': pd.to_numeric(r.carried_weight, errors='coerce'),
                      'dist': pd.to_numeric(r.distance_m, errors='coerce'), 'trk': r.surface.astype(str).str.contains('芝').astype(float),
                      'prize1': r.prize1, 'prize': r.prize, 'finish': r.finish, 'time_sec': pd.to_numeric(r.time_sec, errors='coerce'),
                      'l3f': pd.to_numeric(r.last3f, errors='coerce'), 'c1': r.c1, 'c2': r.c2, 'c3': r.c3, 'c4': r.c4,
                      'horse_name': r.horse_name.str.strip(), 'birth_date': r.birth_date.astype(str).str[:10]})
    j = pd.read_parquet(off / 'jra.parquet')
    j = j[j.surface.isin(['ダ', '芝'])].copy()
    jh = pd.read_parquet(off / 'jrah.parquet')[['kb_horse_id', 'horse_name', 'birth_year']].drop_duplicates('kb_horse_id')
    j = j.merge(jh, on='kb_horse_id', how='left', suffixes=('', '_h'))
    j = j[j.birth_year.notna()].copy()
    nmj = j['horse_name_h'] if 'horse_name_h' in j else j['horse_name']
    j['race_date'] = j.race_date.astype(str).str[:10]
    fj = pd.to_numeric(j.finish, errors='coerce')
    ps = j.passing.astype(str).str.split('-')
    pc = {i: pd.to_numeric(ps.map(lambda a, i=i: a[len(a) - (5 - i)] if len(a) >= 5 - i else None), errors='coerce') for i in (1, 2, 3, 4)}
    J = pd.DataFrame({'track': j.place.astype(str), 'race_date': j.race_date, 'race': pd.to_numeric(j.race_no, errors='coerce').astype(float), 'umaban': -1.0,
                      'hk': nmj.str.strip() + '|' + j.birth_year.astype(int).astype(str), 'src': 1.0, 'rid': 'J|' + j.kb_race_id.astype(str),
                      'jockey': 'J:' + j.jockey.astype(str).str.strip(), 'trainer': None, 'age': np.nan,
                      'kinryo': pd.to_numeric(j.carried_weight, errors='coerce'), 'dist': pd.to_numeric(j.distance, errors='coerce'),
                      'trk': (j.surface == '芝').astype(float), 'prize1': np.nan, 'prize': np.nan, 'finish': fj.where(fj > 0),
                      'time_sec': pd.to_numeric(j.time_sec, errors='coerce'), 'l3f': pd.to_numeric(j.last3f, errors='coerce'),
                      'c1': pc[1], 'c2': pc[2], 'c3': pc[3], 'c4': pc[4], 'fs': pd.to_numeric(j.field_size, errors='coerce'),
                      'horse_name': None, 'birth_date': None})
    R = pd.concat([L, J], ignore_index=True)
    R['day'] = _dnum(R.race_date)
    R['year'] = R.race_date.str[:4].astype(int)
    R['month'] = R.race_date.str[5:7].astype(int)
    # 血統・生産者(profiles・名前 + 生年月日)→ 馬の鍵 hk ごと
    pf = off / 'profiles.parquet'
    if pf.exists():
        P = pd.read_parquet(pf, columns=['horse_name', 'birth_date', 'sire', 'breeder'])
        P['horse_name'], P['birth_date'] = P.horse_name.astype(str).str.strip(), P.birth_date.astype(str).str[:10]
        P = P.drop_duplicates(['horse_name', 'birth_date'])
        M = L[['hk', 'horse_name', 'birth_date']].drop_duplicates('hk').merge(P, on=['horse_name', 'birth_date'], how='left')
        R = R.merge(M[['hk', 'sire', 'breeder']], on='hk', how='left')
    else:
        R['sire'], R['breeder'] = None, None
    return atoms(R)


def atoms(R):
    """研究 v3n_f10k.build の元の値(着順率・着差・速さ・賞金・角の位置・格・前半の速さ)。速さの z と格の帯は「その日まで」のならし。"""
    R = R.sort_values(['hk', 'day', 'src', 'race']).reset_index(drop=True)
    g = R.groupby('rid')
    if 'fs' not in R:
        R['fs'] = np.nan
    R['nfield'] = np.where(R.src == 1, R.fs, g.hk.transform('size')).astype(float)
    n_ok = np.where(R.src == 1, R.fs, g.finish.transform('count'))
    R['fin_r'] = ((R.finish - 1) / np.maximum(n_ok - 1, 1)).clip(0, 1)
    R['top3'] = (R.finish <= 3).astype(float).where(R.finish.notna())
    ts = R.time_sec.where((R.time_sec > 0) & R.finish.notna())
    R['tsec'] = np.where(R.src == 1, np.nan, ts - ts.groupby(R.rid).transform('min'))
    R['tkm'] = R.tsec / R.dist * 1000
    spm = (ts / R.dist).to_numpy(float)
    day = R.day.to_numpy()
    gk = (R.track + '|' + R.dist.astype(str) + '|' + R.trk.astype(str)).to_numpy()
    mu, sd = _asof_stats(gk, day, spm)
    R['spd'] = -(spm - mu) / sd
    t3m = pd.Series(np.where(R.finish <= 3, spm, np.nan)).groupby(R.rid.to_numpy()).transform('mean').to_numpy()
    R['spd_j'] = np.where(R.src == 1, np.nan, -(t3m - mu) / sd)
    for c in ('c1', 'c2', 'c3', 'c4'):
        R[c] = R[c].where(R[c] > 0)
        R[c + 'r'] = R[c] / R.nfield
    R['g34'] = R.c3r - R.c4r
    R['cls'] = np.log1p(R.prize1)
    R['prz'] = np.log1p(R.prize)
    R['fin_cls'] = (1 - R.fin_r) * R.cls
    pre = (ts - R.l3f.where(R.l3f > 0)).to_numpy(float)
    mu2, sd2 = _asof_stats(gk, day, pre)
    R['pre_z'] = -(pre - mu2) / sd2
    R['dband'] = pd.cut(R.dist, [0, 1000, 1200, 1400, 1600, 1800, 2000, 9999], labels=False).astype(float)
    R['season'] = ((R.month % 12) // 3).astype(float)
    # 格の帯 = その場の前の年の 1 着賞金の 5 分位の境で切る(前の年が無い年はその年)
    lp = R[R.src == 0].drop_duplicates('rid')[['track', 'year', 'prize1']].dropna()
    qs = lp.groupby(['track', 'year']).prize1.quantile([0.2, 0.4, 0.6, 0.8]).unstack()
    cl = np.full(len(R), np.nan)
    for (trk, yr), idx in R[(R.src == 0) & R.prize1.notna()].groupby(['track', 'year']).groups.items():
        key = (trk, yr - 1) if (trk, yr - 1) in qs.index else (trk, yr)
        if key in qs.index:
            cl[np.asarray(idx)] = np.searchsorted(qs.loc[key].to_numpy(), R.prize1.to_numpy()[np.asarray(idx)], 'right')
    R['clsb'] = cl
    R['jyo_dband'] = R.track + '#' + R.dband.astype(str)
    R['agec'] = np.clip(R.age, 2, 4)
    R['jh'] = R.jockey.astype(str) + '#' + R.hk.astype(str)
    gt = R.top3.groupby(R.hk)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        R['h5'] = np.nanmean(np.stack([gt.shift(k).to_numpy(float) for k in range(1, 6)]), 0)
    return R


def _hist(R, tidx, filt, want):
    """研究 hist_block と同じ: 馬(+ 絞り)ごとの前の走りの窓の集計。want = [(元, 窓)]"""
    key = R.hk.astype(str) + ('#' + R[filt].astype(str) if filt != 'none' else '')
    bad = R[filt].isna().to_numpy() if filt != 'none' else np.zeros(len(R), bool)
    kc0 = pd.factorize(key)[0]
    order = np.lexsort((R.race.to_numpy(), R.day.to_numpy(), kc0))
    kc = kc0[order]
    n = len(R)
    pos = np.arange(n)
    new = np.r_[True, kc[1:] != kc[:-1]]
    gstart = np.maximum.accumulate(np.where(new, pos, 0))
    inv = np.empty(n, np.int64)
    inv[order] = pos
    tp = inv[tidx]
    gs = gstart[tp]
    tbad = bad[tidx]
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for a in sorted({a for a, _ in want}):
            A = R[a].to_numpy(np.float64)[order]
            L = np.full((LAGS, len(tp)), np.nan)
            for lg in range(1, LAGS + 1):
                ok = ((tp - lg) >= gs) & ~tbad
                L[lg - 1, ok] = A[(tp - lg)[ok]]
            for a2, w in want:
                if a2 != a:
                    continue
                if w == 'all':
                    v = np.nan_to_num(A)
                    cs, cc = np.r_[0, np.cumsum(v)], np.r_[0, np.cumsum(~np.isnan(A))]
                    s_, c_ = cs[tp] - cs[gs], cc[tp] - cc[gs]
                    out[(a, w)] = np.where((c_ > 0) & ~tbad, s_ / np.maximum(c_, 1), np.nan)
                    continue
                k, how = WIN[w]
                S = L[:k]
                out[(a, w)] = {'v': lambda: S[0], 'mean': lambda: np.nanmean(S, 0), 'max': lambda: np.nanmax(S, 0),
                               'min': lambda: np.nanmin(S, 0), 'std': lambda: np.nanstd(S, 0, ddof=1)}[how]()
    return out


def _ent90(R, tidx):
    """研究 ent_block の 調教師 × 距離帯 × 90 日の lift(3 着内 − 馬の前 5 走の 3 着内率)"""
    lift = R.top3 - R.h5
    key = R.trainer.astype(str) + '#' + R.dband.astype(str)
    valid = (R.trainer.notna() & R.dband.notna()).to_numpy()
    D = pd.DataFrame({'key': key[valid], 'day': R.day[valid], 'lf': lift[valid].fillna(0), 'nl': lift[valid].notna().astype(float)})
    D = D.groupby(['key', 'day'], sort=True).sum().reset_index()
    kc, ku = pd.factorize(D.key, sort=True)
    comb = kc.astype(np.int64) * 1000000 + D.day.to_numpy()
    C = {c: np.r_[0.0, np.cumsum(D[c].to_numpy())] for c in ('lf', 'nl')}
    qk = pd.Index(ku).get_indexer(key.iloc[tidx])
    qd = R.day.to_numpy()[tidx]
    hi = np.searchsorted(comb, qk * 1000000 + qd, 'left')
    lo = np.searchsorted(comb, qk * 1000000 + qd - 90, 'left')
    v = (C['lf'][hi] - C['lf'][lo]) / (C['nl'][hi] - C['nl'][lo] + 10)
    return np.where((qk < 0) | ~valid[tidx], np.nan, v)


def _grp(R, tidx, ent, cond, y, m=20, loo=True):
    """研究 grp_block と同じ: 群 ent(× 条件)の、その日より前の他の馬の成績(本人を抜く)。cond = 'none' なら全体の平均へ、
    それ以外は群全体(none)の値へ m 走分で縮める。全期間。→ (値, 群全体の値)"""
    okn = R.top3.notna().to_numpy()
    yv = R[y].to_numpy(float) if y != 'ts' else np.clip(R.tsec.to_numpy(float), 0, 5)
    gm = np.nanmean(yv[okn])
    qd = R.day.to_numpy()[tidx]

    def asof(key, valid):
        D = pd.DataFrame({'key': key[valid], 'day': R.day.to_numpy()[valid], 'n': okn[valid].astype(float), 'v': np.nan_to_num(yv[valid]) * okn[valid]})
        D = D.groupby(['key', 'day'], sort=True).sum().reset_index()
        kc, ku = pd.factorize(D.key, sort=True)
        comb = kc.astype(np.int64) * 1000000 + D.day.to_numpy()
        Cn, Cv = np.r_[0.0, np.cumsum(D.n.to_numpy())], np.r_[0.0, np.cumsum(D.v.to_numpy())]
        qk = pd.Index(ku).get_indexer(key[tidx])
        hi = np.searchsorted(comb, qk * 1000000 + qd, 'left')
        lo = np.searchsorted(comb, qk * 1000000, 'left')   # その群の始まり(全期間)
        return np.where(qk < 0, 0, Cn[hi] - Cn[lo]), np.where(qk < 0, 0, Cv[hi] - Cv[lo])
    base = R[ent].astype(str).to_numpy()
    eok = R[ent].notna().to_numpy()
    hk = R.hk.astype(str).to_numpy()
    res = {}
    for cnd in (['none'] if cond == 'none' else ['none', cond]):
        ck = np.full(len(R), '', object) if cnd == 'none' else R[cnd].astype(str).to_numpy()
        valid = eok & (R[cnd].notna().to_numpy() if cnd != 'none' else True)
        key = (base + '#' + ck).astype(object)
        n, s = asof(key, valid)
        if loo:
            n2, s2 = asof((key + '#' + hk).astype(object), valid)
            n, s = n - n2, s - s2
        p0 = res['none'] if cnd != 'none' else gm
        res[cnd] = np.where(~valid[tidx], np.nan, (s + m * p0) / (n + m))
    return res[cond], res['none']


def raw(R, tidx):
    """予想する行(R の行番号 tidx)の 29 個の元の値。掛け合わせの 4 個は元の 2 つ(_a・_b)で返す(順位は shift でレースの中で取る)。"""
    want = {}
    for nm in NAMES:
        base = nm.rsplit('#', 1)[0]
        for part in (base[2:].split('*') if base.startswith('x|') else [base]):
            f = part.split('|')
            if f[0] in ('o/h', 'k/h'):
                want.setdefault(f[1], set()).add((f[2], f[3]))
    H = {}
    for filt, w in want.items():
        for (a, win), v in _hist(R, tidx, filt, sorted(w)).items():
            H[f'|{filt}|{a}|{win}'] = v
    out = {}
    for nm in NAMES:
        base = nm.rsplit('#', 1)[0]
        if base.startswith('x|'):
            a, b = base[2:].split('*')
            out[nm + '_a'] = H['|' + '|'.join(a.split('|')[1:])]
            out[nm + '_b'] = H['|' + '|'.join(b.split('|')[1:])]
        elif base.startswith(('o/h', 'k/h')):
            out[nm] = H['|' + '|'.join(base.split('|')[1:])]
    out['o/e|trainer_cd|dband|90|lift#raw'] = _ent90(R, tidx)
    out['o/g|jh|none|all|ts#raw'] = _grp(R, tidx, 'jh', 'none', 'ts', m=5, loo=False)[0]
    v, p = _grp(R, tidx, 'breeder', 'agec', 'fin_r')
    out['o/g|breeder_cd|agec|all|fr-par#raw'] = v - p
    v, p = _grp(R, tidx, 'sire', 'src', 'fin_r')
    out['o/g|sire|src|all|fr-par#raw'] = v - p
    return pd.DataFrame({k: np.asarray(v, np.float64) for k, v in out.items()})


def design(F, rcode, names=None):
    """元の値の表 F(raw の列)とレースの番号 → 研究の design(順位 − 0.5・レースの中で平均を引く・空は 0)の列(names の順・既定は 29 個)"""
    def rk(v):
        return pd.Series(v).groupby(rcode).rank(pct=True).to_numpy()
    cols = []
    for nm in (names or NAMES):
        if nm.startswith('x|'):
            v = (rk(F[nm + '_a'].to_numpy()) - 0.5) * (rk(F[nm + '_b'].to_numpy()) - 0.5)
        else:
            v = F[nm].to_numpy()
        cols.append(rk(v) - 0.5)
    M = np.column_stack(cols)
    M = M - pd.DataFrame(M).groupby(rcode).transform('mean').to_numpy()
    return np.nan_to_num(M)


def shift_logit(M, q3, rcode, beta, b):
    """M = design の 29 列・q3 = 土台の 3 着内率 → 足す logit(土台の logit に直交させた材料 × b)"""
    q = np.clip(np.asarray(q3, float), 1e-5, 1 - 1e-5)
    c = np.log(q / (1 - q))
    c = c - pd.Series(c).groupby(rcode).transform('mean').to_numpy()
    return (M - c[:, None] * np.asarray(beta)[None, :]) @ np.asarray(b)


def apply3(q3, s, rcode):
    """σ(logit q3 + s) をレースの中で合計 3 にそろえ [1e-5, 1 − 1e-5] で切る(研究と同じ)"""
    q = np.clip(np.asarray(q3, float), 1e-5, 1 - 1e-5)
    p = 1 / (1 + np.exp(-(np.log(q / (1 - q)) + s)))
    p = p / pd.Series(p).groupby(rcode).transform('sum').to_numpy() * 3
    return np.clip(p, 1e-5, 1 - 1e-5)


# ================================================================ 直前便
def prep(off, day, tracks, out, log=print):
    """直前便の頭: 公式の表から今日の出走馬(tracks)の元の値を out(npz)に。書けたらそのパス・無理なら None"""
    need = [Path(off) / f for f in ('runs.parquet', 'races.parquet', 'jra.parquet', 'jrah.parquet')]
    if not all(p.exists() for p in need):
        log('決め 41 の材料 公式の表が無い = 作らない', [p.name for p in need if not p.exists()])
        return None
    R = runs_frame(off)
    tidx = np.where(R.track.isin(tracks) & (R.race_date == day) & (R.src == 0))[0]
    F = raw(R, tidx)
    # 父・生産者 = 混ぜ作り(KDS から固めた表 + CUT 以後の公式の走り・研究の値との相関 0.97・0.99)
    import sealed
    G = pd.read_parquet(sealed.path('v3n_f41_grp.parquet'))
    H = pd.read_parquet(sealed.path('v3n_f41_horse.parquet'))
    pf = Path(off) / 'profiles.parquet'
    prof = pd.read_parquet(pf, columns=['horse_name', 'birth_date', 'sire', 'breeder']) if pf.exists() else None
    bmap = H.dropna(subset=['breeder']).drop_duplicates('breeder').set_index('breeder').breeder_cd
    R2 = horse_attrs(R, H, prof, bmap)
    for ent, cond, nm in GRP:
        F[nm] = grp_hybrid(R2, tidx, G, ent, cond)
    T = R.iloc[tidx]
    np.savez_compressed(out, track=T.track.to_numpy().astype('U4'), race_no=T.race.to_numpy(int), umaban=T.umaban.to_numpy(int),
                        cols=np.array(list(F.columns)), X=F.to_numpy(np.float64))
    log('決め 41 の材料', out, F.shape, '・空でない割合の最小', round(float(F.notna().mean().min()), 3) if len(F) else '-',
        '・profiles', (Path(off) / 'profiles.parquet').exists())
    return out


def load(path):
    if not path or not Path(path).exists():
        return None
    Z = np.load(path, allow_pickle=False)
    F = pd.DataFrame(Z['X'], columns=[str(c) for c in Z['cols']])
    ix = {(str(a), int(b), int(c)): i for i, (a, b, c) in enumerate(zip(Z['track'], Z['race_no'], Z['umaban']))}
    return {'F': F, 'ix': ix}


def race_shift(S, track, rno, nums, q3):
    """周ごと: 残った馬 nums(取消の後)と土台の q3 → 新しい q3 と足した logit(どちらも nums の順)。材料に無い馬がいれば None"""
    import sealed
    if S is None:
        return None
    idx = [S['ix'].get((str(track), int(rno), int(u))) for u in nums]
    if len(idx) < 2 or any(i is None for i in idx):
        return None
    C = sealed.get('v3n_f41')
    rc = np.zeros(len(idx), int)
    M = design(S['F'].iloc[idx].reset_index(drop=True), rc, list(C['NAMES']))
    s = shift_logit(M, q3, rc, C['BETA'], C['B'])
    return apply3(q3, s, rc), s


# ================================================================ 2026-10-17 混ぜ作り(父・生産者の群の成績)
# 変わらない過去 = KDSCOPE から 1 回だけ取り出して固めた表(暗号化の定数のフォルダの v3n_f41_grp.parquet・v3n_f41_horse.parquet)。
#   CUT(2026-03-01・KDS の中央の走りが止まった日)より前の全場 + 中央の走りの群ごとの合計と、馬ごとの合計(本人を抜く用)。
# 毎日変わる分 = 公式の表の CUT 以後の走り(地方 + 公式の中央 = 地方に来た馬の分)。馬は 名前|生まれ年 で KDS の台帳(固めた表)につなぎ、
#   台帳に無い新しい馬は公式 profiles の父の名前・生産者の名前で引く。
CUT = '2026-03-01'
GRP = [('sire', 'src', 'o/g|sire|src|all|fr-par#raw'), ('breeder_cd', 'agec', 'o/g|breeder_cd|agec|all|fr-par#raw')]


def horse_attrs(R, Hmap, prof=None, bmap=None):
    """公式の表の走り R に ketto・sire・breeder_cd・agec を付ける。Hmap = 固めた台帳(name・birth_year・ketto・sire・breeder_cd)"""
    R = R.copy()
    by = R.hk.str.rsplit('|', n=1).str[1]
    nm = R.hk.str.rsplit('|', n=1).str[0]
    H = Hmap.assign(k=Hmap.name.astype(str).str.strip() + '|' + Hmap.birth_year.astype(int).astype(str)).drop_duplicates('k').set_index('k')
    hit = R.hk.map(H.ketto.astype(str))
    R['ketto'] = hit.fillna('N:' + R.hk).to_numpy()
    R['sire'] = R.hk.map(H.sire)
    R['breeder_cd'] = R.hk.map(H.breeder_cd)
    if prof is not None:   # 台帳に無い馬 = 公式 profiles の名前
        P = prof.assign(k=prof.horse_name.astype(str).str.strip() + '|' + prof.birth_date.astype(str).str[:4]).drop_duplicates('k').set_index('k')
        R['sire'] = R.sire.fillna(R.hk.map(P.sire))
        bn = R.hk.map(P.breeder)
        R['breeder_cd'] = R.breeder_cd.fillna(bn.map(bmap) if bmap is not None else None).fillna('N:' + bn.astype(str)).where(R.breeder_cd.notna() | bn.notna())
    yr = R.year.to_numpy()
    R['agec'] = np.clip(yr - pd.to_numeric(by, errors='coerce').to_numpy(float), 2, 4)
    return R


def grp_hybrid(R, tidx, G, ent, cond, m=20):
    """研究 grp_block(全期間・本人を抜く・群全体へ m 走分で縮める)と同じ式を、固めた表 G(CUT より前の合計)+ R の CUT 以後の走りで。
    R = horse_attrs の後の公式の走り(CUT 以後の分だけ足す)。→ 値 − 群全体の値(fr-par)"""
    gm = float(G.loc[G.kind == 'gm', 'v'].iloc[0])
    okn = R.top3.notna().to_numpy()
    yv = R.fin_r.to_numpy(float)
    after = (R.race_date >= CUT).to_numpy()
    qd = R.day.to_numpy()[tidx]
    hk = R.ketto.astype(str).to_numpy()

    def keyof(cnd):
        ck = np.full(len(R), '', object) if cnd == 'none' else R[cnd].astype(str).to_numpy()
        return (R[ent].astype(str).to_numpy() + '#' + ck).astype(object), (R[ent].notna().to_numpy() & (R[cnd].notna().to_numpy() if cnd != 'none' else True))

    def asof(key, valid, kind):
        D = pd.DataFrame({'key': key[valid & after], 'day': R.day.to_numpy()[valid & after], 'n': okn[valid & after].astype(float),
                          'v': np.nan_to_num(yv[valid & after]) * okn[valid & after]}).groupby(['key', 'day'], sort=True).sum().reset_index()
        kc, ku = pd.factorize(D.key, sort=True)
        comb = kc.astype(np.int64) * 1000000 + D.day.to_numpy()
        Cn, Cv = np.r_[0.0, np.cumsum(D.n.to_numpy())], np.r_[0.0, np.cumsum(D.v.to_numpy())]
        qk = pd.Index(ku).get_indexer(key[tidx])
        hi = np.searchsorted(comb, qk * 1000000 + qd, 'left')
        lo = np.searchsorted(comb, qk * 1000000, 'left')
        n, s = np.where(qk < 0, 0, Cn[hi] - Cn[lo]), np.where(qk < 0, 0, Cv[hi] - Cv[lo])
        T = G[G.kind == kind].set_index('key')
        n0 = pd.Series(key[tidx]).map(T.n).fillna(0).to_numpy()
        s0 = pd.Series(key[tidx]).map(T.v).fillna(0).to_numpy()
        return n + n0, s + s0
    res = {}
    for cnd in ('none', cond):
        key, valid = keyof(cnd)
        n, s = asof(key, valid, f'{ent}|{cnd}')
        lk = (key + '#' + hk).astype(object)
        n2, s2 = asof(lk, valid, f'{ent}|{cnd}|self')
        n, s = n - n2, s - s2
        p0 = res['none'] if cnd != 'none' else gm
        res[cnd] = np.where(~valid[tidx], np.nan, (s + m * p0) / (n + m))
    return res[cond] - res['none']
