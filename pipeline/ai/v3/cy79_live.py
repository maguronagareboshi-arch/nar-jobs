# -*- coding: utf-8 -*-
"""南関 直前版の並び読みに調教を挟む(決め 79・研究 nankan-ai-v3 src/f5_scripts/seqcy_1111.py の works・tokens・build・seqcy79_judge.py・
判定 2026-11-11 合格・out/seqcy79_judge.md)。学習はしない。

今の並び読み u_X(seq2_live・過去 10 走だけ)はそのまま。もう 1 本の並び読み u_cy = 過去 10 走の行と調教 1 本ずつの行を
「今回までの日数」の古い順に右へ寄せた並び(長さ 20・列 63 + 調教の 14 列)を読む模型(形は seq2_live.forward と同じ)。
決め 77 の段(dayonpre77_live.race)で 3 着内の logit に A3 × d・勝つ率の log に A1 × d を足す(d = u_cy − u_X・どちらかが無い馬は 0)。

  1) 前日(v3_daily → seq2_live.prep の最後): prep(day, T, hist, ctx, bwp, out) → OUT/DAY_cy79.npz
     調教の行 = 今回のレースへの調教 最大 NP 本(レースと馬番で結ぶ)+ 直近 NPAST 走それぞれへの調教 最大 NPP 本(馬名とその走の日で結ぶ)。
     元 = 本番の調教の表(t8_forecast.works = 調教の CSV + nar_kb_works の毎日の分)。時計の z の物差し(コース × 馬場 × 強さ・2022 年まで)は定数 cy79.z。
  2) 当日(v29_gap.day_marks): resid(S, track, rno, b, going) → 馬ごとの u_cy(b の並び)か None。当日の項目の入れ方は seq2_live.day_fill と同じ。
人気・オッズは材料にも重みにも使わない。定数(A3・A1・ON・TAG・z・形)は暗号化したリリース v3-consts の consts.json の cy79。
"""
import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

K = ['track', 'race_date', 'race_no', 'umaban']
CLS = {**{k: 0 for k in ('馬なり', '楽走', '末抑え', '直抑え')}, **{k: 1 for k in ('強め', '稍強め', '末強め', '直強め')},
       **{k: 2 for k in ('一杯', '末一杯', '直一杯', '稍一杯', '叩一杯')}}
BABA = {'良': 0, '稍': 1, '重': 2, '不': 3}
ZC = (('t_3f', 'z3'), ('t_half', 'z4'), ('t_5f', 'z5'), ('t_1f', 'z1'))
TCOL = ['t_5f', 't_half', 't_3f', 't_1f']
WATCH = {'今回への調教がある割合 ≥': 0.30, '直近の走に調教が結べた割合 ≥': 0.30, '出走馬 ≥': 20}
_C = None


def log0(*a):
    print('[cy79]', *a, flush=True)


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('cy79')
    return _C


def is_on(day):
    """その日(レースの日)が決め 79 の ON 以降か(定数が読めなければ例外)。"""
    return str(day) >= str(consts().get('ON') or '9999-12-31')


def norm(s):
    if not isinstance(s, str):
        return np.nan
    s = re.sub(r'\s+', '', unicodedata.normalize('NFKC', s))
    return s if s else np.nan


def _zt(rec):
    """定数の物差し(JSON の None = 研究の欠けの群)→ 表。"""
    st = pd.DataFrame(rec, columns=['crs', 'bb', 'cls', 'mean', 'std'])
    st['crs'] = st.crs.astype(object).where(st.crs.notna(), np.nan)
    for c in ('bb', 'cls', 'mean', 'std'):
        st[c] = pd.to_numeric(st[c], errors='coerce').astype(float)
    return st


def works_tbl(W, C=None):
    """調教の行(研究の CSV と同じ列・v8cy_build.prep_works の後でもよい)→ 研究 seqcy_1111.works と同じ表(z・日数・並びの番号 k)。"""
    C = consts() if C is None else C
    W = W.copy()
    for c in ('course', 'baba', 'ashiiro', 'kind', 'is_hanro', 'horse_name') + tuple(TCOL):
        if c not in W.columns:
            W[c] = np.nan
    W['race_date'] = W.race_date.astype(str).str[:10]
    W['work_date'] = W.work_date.astype(str).str[:10]
    W['race_no'] = pd.to_numeric(W.race_no, errors='coerce')
    W['umaban'] = pd.to_numeric(W.umaban, errors='coerce')
    W = W[W.race_no.notna() & W.umaban.notna() & W.work_date.str.match(r'^\d{4}-\d\d-\d\d$') & (W.work_date < W.race_date)].copy()
    W['race_no'] = W.race_no.astype(int)
    W['umaban'] = W.umaban.astype(int)
    for c in TCOL:
        W[c] = pd.to_numeric(W[c], errors='coerce')
    W['cls'] = W.ashiiro.map(lambda s: CLS.get(norm(s), np.nan)).astype(float)
    W['bb'] = W.baba.map(lambda s: BABA.get(norm(s), np.nan)).astype(float)
    W['hanro'] = pd.to_numeric(W.is_hanro, errors='coerce')
    W['fin'] = (W.kind == 'final').astype(float)
    W['crs'] = W.course.map(norm)
    W = W.drop_duplicates(K + ['work_date', 'course', 't_3f', 't_half', 'kind']).reset_index(drop=True)
    g = ['crs', 'bb', 'cls']
    for c, nm in ZC:
        st = _zt(C['z'][nm])
        W = W.merge(st.rename(columns={'mean': '_m', 'std': '_s'}), on=g, how='left')
        W[nm] = ((W[c] - W._m) / W._s).clip(-4, 4)
        W = W.drop(columns=['_m', '_s'])
    W['gap'] = (pd.to_datetime(W.race_date) - pd.to_datetime(W.work_date)).dt.days
    W['lap'] = (W.t_half - W.t_3f).clip(5, 20)
    W = W.sort_values(K + ['gap', 'fin'], ascending=[True] * 4 + [True, False], kind='mergesort')
    W['k'] = W.groupby(K).cumcount()
    return W.reset_index(drop=True)


def fill_umaban(W, runs):
    """本番の調教の CSV(リリースの cyokyo_csv)は川崎・浦和の 2024〜 の行に馬番が無い(研究の CSV にはある・11/11 に見つけた)。
    馬番の無い行に、公式の成績表のそのレース・馬名(空白を除いた形)の馬番を入れる(研究の CSV と同じ値になる)。→ (W, 補った行数)"""
    W = W.copy()
    u = pd.to_numeric(W.umaban, errors='coerce')
    miss = u.isna()
    if not miss.any() or runs is None or not len(runs):
        return W, 0
    r = runs[['track', 'race_date', 'race_no', 'umaban', 'horse_name']].copy()
    r['race_date'] = r.race_date.astype(str).str[:10]
    r['race_no'] = pd.to_numeric(r.race_no, errors='coerce')
    r['hn'] = r.horse_name.map(norm)
    r = r.dropna(subset=['race_no', 'hn']).drop_duplicates(['track', 'race_date', 'race_no', 'hn'], keep=False)
    q = W.loc[miss, ['track', 'race_date', 'race_no', 'horse_name']].copy()
    q['race_date'] = q.race_date.astype(str).str[:10]
    q['race_no'] = pd.to_numeric(q.race_no, errors='coerce')
    q['hn'] = q.horse_name.map(norm)
    m = q.reset_index().merge(r[['track', 'race_date', 'race_no', 'hn', 'umaban']].rename(columns={'umaban': '_u'}),
                              on=['track', 'race_date', 'race_no', 'hn'], how='left').set_index('index')
    got = m._u.notna()
    W.loc[m.index[got], 'umaban'] = m._u[got].astype(int).astype(str).to_numpy()
    return W, int(got.sum())


def tokens(W):
    """調教 1 本の 14 列(日数の列は後で入れる)= 研究 seqcy_1111.tokens。"""
    z = lambda c: np.nan_to_num(W[c].to_numpy(float))  # noqa: E731
    return np.column_stack([np.ones(len(W)), np.zeros(len(W)), W.gap.to_numpy(float) / 14, np.zeros(len(W)), np.nan_to_num(W.hanro.to_numpy(float)),
                            np.nan_to_num(W.bb.to_numpy(float)) / 3, np.nan_to_num(W.cls.to_numpy(float)), W.fin.to_numpy(float),
                            z('z3'), z('z4'), z('z5'), z('z1'), W.z3.isna().to_numpy(float), (np.nan_to_num(W.lap.to_numpy(float), nan=12.5) - 12.5) / 2]).astype(np.float32)


def seq_hist(Tg, hist, Wt, C=None):
    """研究 seqcy_1111.build と同じ式(偽のまぜ無し)。Tg = 予想する行(K + horse_name・hist と同じ並び)・hist(N, 10, 63)・Wt = works_tbl の表。
    → (Hn(N, TL, 63 + NT), 数え dict)"""
    C = consts() if C is None else C
    TL, NT, NP, NPAST, NPP = (int(C[k]) for k in ('TL', 'NT', 'NP', 'NPAST', 'NPP'))
    N, H, F = hist.shape
    Tg = Tg[K + ['horse_name']].reset_index(drop=True).copy()
    Tg['horse_name'] = Tg.horse_name.astype(str).str.strip()
    tdn = (pd.to_datetime(Tg.race_date) - pd.Timestamp('2014-01-01')).dt.days.to_numpy()
    gcol, vcol = F - 4, F - 1
    W = Wt.reset_index(drop=True).copy()
    W['horse_name'] = W.horse_name.astype(str).str.strip()
    W['wdn'] = (pd.to_datetime(W.work_date) - pd.Timestamp('2014-01-01')).dt.days.to_numpy()
    tok = tokens(W)
    Wk = W.assign(w=np.arange(len(W)))
    A = Tg.reset_index().rename(columns={'index': 'i'})[['i'] + K].merge(Wk.loc[Wk.k < NP, K + ['w']], on=K, how='inner')
    ti, tw, tf = [A.i.to_numpy()], [A.w.to_numpy()], [np.ones(len(A))]
    Wp = Wk.loc[Wk.k < NPP, ['horse_name', 'race_date', 'w']]
    n_ok, n_link = 0, 0
    for k in range(1, NPAST + 1):
        s = H - k
        ok = hist[:, s, vcol] > 0.5
        gap = np.rint(np.expm1((hist[:, s, gcol].astype(np.float64) + 1.5) * 3)).astype(int)
        ii = np.flatnonzero(ok)
        pd_ = (pd.Timestamp('2014-01-01') + pd.to_timedelta(tdn[ii] - gap[ii], unit='D')).strftime('%Y-%m-%d')
        Q = pd.DataFrame({'i': ii, 'horse_name': Tg.horse_name.to_numpy()[ii], 'race_date': pd_}).merge(Wp, on=['horse_name', 'race_date'], how='inner')
        ti.append(Q.i.to_numpy())
        tw.append(Q.w.to_numpy())
        tf.append(np.zeros(len(Q)))
        n_ok += len(ii)
        n_link += Q.i.nunique()
    ti, tw, tf = np.concatenate(ti).astype(int), np.concatenate(tw).astype(int), np.concatenate(tf)
    days = tdn[ti] - W.wdn.to_numpy()[tw]
    keep = days > 0
    ti, tw, tf, days = ti[keep], tw[keep], tf[keep], days[keep]
    info = {'頭': int(N), '今回への調教がある割合': float(len(np.unique(ti[tf > 0])) / N) if N else 0.0,
            '直近の走に調教が結べた割合': float(n_link / n_ok) if n_ok else 0.0, '調教の本数': int(len(ti))}
    rv = hist[:, :, vcol] > 0.5
    ri, rs = np.nonzero(rv)
    rdays = np.rint(np.expm1((hist[ri, rs, gcol].astype(np.float64) + 1.5) * 3))
    I = np.concatenate([ri, ti])
    Dd = np.concatenate([rdays, days.astype(float)])
    typ = np.concatenate([np.zeros(len(ri), int), np.ones(len(ti), int)])
    src = np.concatenate([rs, np.arange(len(ti))])
    o = np.lexsort((typ, -Dd, I))
    I, Dd, typ, src = I[o], Dd[o], typ[o], src[o]
    cnt = np.bincount(I, minlength=N)
    over = np.maximum(cnt - TL, 0)
    start = np.r_[0, np.cumsum(cnt)[:-1]]
    rank = np.arange(len(I)) - start[I]
    keepi = rank >= over[I]
    I, Dd, typ, src, rank = I[keepi], Dd[keepi], typ[keepi], src[keepi], rank[keepi] - over[I[keepi]]
    pos = TL - np.minimum(cnt, TL)[I] + rank
    Hn = np.zeros((N, TL, F + NT), np.float32)
    r_ = typ == 0
    Hn[I[r_], pos[r_], :F] = hist[I[r_], src[r_]]
    t_ = ~r_
    tk = tok[tw[src[t_]]].copy()
    tk[:, 1] = np.log1p(Dd[t_]) / 3 - 1.5
    tk[:, 3] = tf[src[t_]]
    Hn[I[t_], pos[t_], F:] = tk
    Hn[I[t_], pos[t_], gcol] = tk[:, 1]
    info['長さを超えた行'] = int((over > 0).sum())
    return Hn, info


def prep(day, T, hist, ctx, bwp, out, W=None, log=log0):
    """前日の便(seq2_live.prep の最後): その日の南関の出走馬の調教入りの並びを OUT/DAY_cy79.npz に。書けたらそのパス・書かなければ None。"""
    try:
        C = consts()
    except Exception as e:  # noqa: BLE001
        log('調教入りの並び 定数なし = 書かない', type(e).__name__, str(e)[:80])
        return None
    if W is None:
        import t8_forecast as t8
        W = t8.works()[0]
    Tg = T[K].copy()
    Tg['horse_name'] = T.hk.astype(str).str.split('|').str[0]
    W = W[W.race_date.astype(str).str[:10] <= day]
    nmiss = int(pd.to_numeric(W.umaban, errors='coerce').isna().sum())
    if nmiss:
        import seq2_live
        ru = pd.read_parquet(seq2_live.OFFICIAL / 'runs.parquet', columns=['track', 'race_date', 'race_no', 'runner_number', 'horse_name'])
        W, nf = fill_umaban(W, ru.rename(columns={'runner_number': 'umaban'}))
        log('調教入りの並び 馬番の無い調教の行', nmiss, '→ 公式の成績表で補った', nf)
    Wt = works_tbl(W, C)
    Hn, info = seq_hist(Tg, hist, Wt, C)
    v = {'今回への調教がある割合 ≥': info['今回への調教がある割合'], '直近の走に調教が結べた割合 ≥': info['直近の走に調教が結べた割合'], '出走馬 ≥': info['頭']}
    ok = all(v[k] >= w for k, w in WATCH.items())
    log('調教入りの並び 見張り', {k: round(x, 3) if isinstance(x, float) else x for k, x in info.items()}, '→', '○' if ok else '× = 書かない')
    if not ok:
        return None
    p = Path(out) / f'{day}_cy79.npz'
    np.savez_compressed(p, track=T.track.to_numpy().astype('U4'), race_no=T.race_no.to_numpy(int), umaban=T.umaban.to_numpy(int),
                        hist=Hn, ctx=ctx, bw_prev=bwp, info=json.dumps(info, ensure_ascii=False))
    log('調教入りの並び 材料', p.name, Hn.shape)
    return p


def load(mdir, prep_npz):
    """当日の便: 重み(mdir/cy79_model.npz・cy79_prod.json)と前日の材料。どちらか無ければ None(決め 79 の足しなし)。"""
    mdir, prep_npz = Path(mdir), Path(prep_npz)
    if not (mdir / 'cy79_model.npz').exists() or not prep_npz.exists():
        return None
    P = np.load(prep_npz)
    meta = json.loads((mdir / 'cy79_prod.json').read_text(encoding='utf-8'))
    if P['hist'].shape[1:] != (meta['H'], meta['fh']) or P['ctx'].shape[1] != meta['fc']:
        raise AssertionError(f'調教入りの並びの材料の形 {P["hist"].shape[1:]}・{P["ctx"].shape[1]} が模型 {meta["H"]}・{meta["fh"]}・{meta["fc"]} と合わない')
    Z = np.load(mdir / 'cy79_model.npz')
    Ws = [{k.split('/', 1)[1]: Z[k].astype(float) for k in Z.files if k.startswith(f's{s}/')} for s in meta['seeds']]
    ix = {(str(a), int(b), int(c)): i for i, (a, b, c) in enumerate(zip(P['track'], P['race_no'], P['umaban']))}
    return {'W': Ws, 'ix': ix, 'hist': P['hist'], 'ctx': P['ctx'], 'bw_prev': P['bw_prev'], 'n': len(ix), 'seeds': list(meta['seeds'])}


def resid(S, track, rno, b, going):
    """seq2_live.resid と同じ(模型だけ替える)。→ b の並びの u_cy(種の平均)か None。"""
    import seq2_live
    return seq2_live.resid(S, track, rno, b, going)
