# -*- coding: utf-8 -*-
"""第11版 = 第10版 + 談話の印 3 定数 + 束 t14(37 列の木 1 本)の前日版。研究 nankan-ai-v3 の t14(判定 通った 2026-10-10・
本番入れ ユーザー承認 2026-10-10)。木は研究 src/f5_scripts/t14_prod_fit.py で 2023-01〜2026-08 に学んだもの(学習はしない)。

足し方(研究 t14_judge と同じ): p3 = p3prime(max(sig(logit(p3′) + 木の値), p1))・p1 は変えない・4 頭以上のレースだけ。
  p3′ = 談話の印を足した後の前日の表の値。木の値 = 種 0/1/2 の 3 本の平均(raw)。
束 37 列(どれもそのレースの前に分かる値だけ):
  ① Glicko ほか 18 列(研究 src/lit_g_feats.py): 便の走り h(全 NAR 2014〜)を日付の順に回す Glicko 2 本・Elo 6 着と、
     土台 U(t4_open.base_of)の SI を観測にしたカルマン。定数は研究で 2014〜15 だけで決めた値。その日の走りは出走表だけ(着順なし)。
  ② 事実 5 列(研究 src/fact4_feats.py・src/v13z_feats.py): 調教欄(固定の CSV 2018〜 + nar_kb_works の毎日の分)から
     fc_gai(外厩)・fc_jra(最終追い切りが栗東/美浦)・fc_n30(30 日の追い切りの数)・n30_diff(その馬の前の走の平均との差)、
     rest60(第9版の g_rest > 60・調教欄の行がある馬だけ)。
     研究との違い: 研究の rest60 は「転厩初戦(KDSCOPE 頼み)」の馬にも付くが本番では付かない(確かめの期間で 0.3%)。
  ③ 談話 14 列(研究 src/danwa_feat.py・src/danwa_lab.py): 本文 → intfloat/multilingual-e5-small → 7 項目の
     ロジスティック回帰(係数 danwa_clf.json)→ 状態の向き・仕上がり・強気など。話し手・馬のいつもとの差・前回からの変化は
     2026-08-31 までの集計(danwa_snap_*.parquet)+ 2026-09-01 からその日の前日までの nar_kb_danwa を毎回読み直して作る。
3 群のどれかが作れない・見張りの線を割ったら束は足さない(第10版 + 談話の印のまま・呼び手が続ける)。

固定ファイル(V3_T14・リリース資産): t14_bundle.json・t14_bundle_s{0,1,2}.txt・danwa_clf.json・danwa_snap.json・
  danwa_snap_tr.parquet・danwa_snap_hs.parquet・cyokyo_old/cyokyo_{場}_{2018..2020}.csv。
⛔DB には書かない(読むだけ)。鍵は印字しない。

  python -X utf8 pipeline/ai/v3/t14_bundle.py check DAY [DAY ...]   # 手元: 研究の材料(v3/feat_lit_g・feat_fact4z・feat_danwa_v2)と照合
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ASSET = Path(os.environ.get('V3_T14', 'C:/Users/kouki/nankan_ai/v3/t14_prod'))
NK = ['浦和', '船橋', '大井', '川崎']
KEY = ['track', 'race_date', 'race_no']
Q4 = KEY + ['umaban']
CANCEL = ['取消', '除外']
LG = ['lg_g_mu', 'lg_g_sd', 'lg_g_rank', 'lg_g_dif', 'lg_g_cons', 'lg_gm_mu', 'lg_gm_sd', 'lg_gm_rank', 'lg_gm_dif', 'lg_gm_cons',
      'lg_k_mu', 'lg_k_sd', 'lg_k_rank', 'lg_k_dif', 'lg_k_cons', 'lg_e6', 'lg_e6_rank', 'lg_e6_dif']
FC = ['fc_gai', 'fc_jra', 'fc_n30', 'n30_diff', 'rest60']
DW = ['dw_dir', 'dw_fit', 'dw_conf', 'dw_conf_tr', 'dw_conf_hs', 'dw_dir_chg', 'dw_exc', 'dw_fix', 'dw_worry', 'dw_cfit',
      'dw_evt_now', 'dw_evt_past', 'k_mk', 'k_mkrel']
COLS = LG + FC + DW
STAMP = '束 t14(Glicko 18・事実 5・談話 14 = 37 列の木・学び 2023-01〜2026-08)'
# ① の定数(研究 out/lit_g_feats.md: 2014 を慣らし 2015 の南関で選んだ)
C_G, W_G, PHI0 = 50.0, 3.0, 350.0
QG = np.log(10) / 400
M_GLOB, V0 = 59.040189686947464, 177.01299085325905  # 2014〜15 の SI の平均・(SI − a_prior) の分散
R_K, QD = V0 * 0.5, V0 * 0.002
# 見張りの線(その日の南関の出走馬のうち値のある割合。研究の確かめの期間の 1 日ごとの最小より低めに置く)
WATCH = {'lg_g_mu': 0.60, 'lg_k_mu': 0.50, 'fc_n30': 0.20, 'dw_dir': 0.50}  # 確かめの期間の 1 日ごとの最低 0.76・0.74・0.25・1.0
CACHE = {}


def log0(*a):
    print('[t14]', *a, flush=True)


def _q4(d):
    d = d.copy()
    d['race_date'] = d.race_date.astype(str).str[:10]
    d['race_no'] = pd.to_numeric(d.race_no, errors='coerce').astype(int)
    d['umaban'] = pd.to_numeric(d.umaban, errors='coerce').astype(int)
    return d


def _dn(s):
    return pd.to_datetime(s).values.astype('datetime64[D]').astype(np.int64)


def _nkey(s):
    return s.astype('string').str.replace(r'\|(\d{4})-\d\d-\d\d$', r'|\1', regex=True)


def _nm(s):
    return s.astype(str).str.replace(r'[\s\u3000]', '', regex=True)


def install():
    """便の中の計算を変えずに部品を控える: 土台 U(t4_open.base_of の最後の戻り)と nar_kb_works の行(kb_works.fetch_rows)。"""
    import t4_open
    import kb_works
    b0, f0 = t4_open.base_of, kb_works.fetch_rows

    def b1(h, races):
        U = b0(h, races)
        CACHE['U'] = U
        return U

    def f1(*a, **k):
        r = f0(*a, **k)
        CACHE['kb_rows'] = r
        return r
    t4_open.base_of, kb_works.fetch_rows = b1, f1


# ================================================================ ① Glicko ほか 18 列
def _gfun(ph):
    return 1 / np.sqrt(1 + 3 * QG * QG * ph * ph / np.pi ** 2)


def _g_update(mu, ph, S, w):
    gj = _gfun(ph)
    E = 1 / (1 + 10 ** (-gj[None, :] * (mu[:, None] - mu[None, :]) / 400))
    np.fill_diagonal(E, 0)
    S = S.copy()
    np.fill_diagonal(S, 0)
    vin = QG * QG * w * (gj[None, :] ** 2 * E * (1 - E)).sum(1)
    den = 1 / ph ** 2 + vin
    return mu + QG / den * w * (gj[None, :] * (S - E)).sum(1), np.sqrt(1 / den)


def _prep(st):
    st = st.copy()
    st['dn'] = _dn(st.race_date)
    st = st.sort_values(['dn', 'track', 'race_no', 'umaban'], kind='mergesort').reset_index(drop=True)
    g = st.groupby(KEY, sort=False)
    st['nst'] = g.umaban.transform('size')
    st['fin'] = st.finish.where(st.finish.notna(), st.nst).astype(float)
    tmin = g.time_sec.transform('min')
    st['gap'] = (st.time_sec - tmin).clip(0, 2).fillna(2.0)
    st['tok'] = g.time_sec.transform(lambda x: x.notna().any()).astype(bool)
    return st


def _run_seq(st):
    """研究 lit_g_feats.run_seq と同じ(元の Elo は使わないので省いた・Elo 6 着と Glicko 2 本)。各行の前の値。"""
    hc = pd.factorize(st.hid)[0]
    nh = hc.max() + 1
    dn, fin, gap, tok = st.dn.to_numpy(), st.fin.to_numpy(), st.gap.to_numpy(), st.tok.to_numpy()
    rk = st.groupby(KEY, sort=False).ngroup().to_numpy()
    b = np.flatnonzero(np.r_[True, rk[1:] != rk[:-1], True])
    R = {k: np.full(nh, np.nan) for k in ('e6', 'gmu', 'gph', 'mmu', 'mph')}
    last = np.zeros(nh, np.int64)
    O = {k: np.full(len(st), np.nan) for k in ('e6', 'g_mu', 'g_phi', 'gm_mu', 'gm_phi')}
    for s, e in zip(b[:-1], b[1:]):
        ix = hc[s:e]
        n = e - s
        f = fin[s:e]
        d = dn[s]
        Sf = (f[:, None] < f[None, :]) + 0.5 * (f[:, None] == f[None, :])
        r0 = R['e6'][ix]
        O['e6'][s:e] = r0
        if n >= 2:
            ok = ~((f[:, None] >= 6) & (f[None, :] >= 6))
            kn = ~np.isnan(r0)
            r = np.where(kn, r0, r0[kn].mean() if kn.any() else 1500.0)
            E_ = 1 / (1 + 10 ** ((r[None, :] - r[:, None]) / 400))
            S_ = Sf.astype(float).copy()
            np.fill_diagonal(S_, 0)
            np.fill_diagonal(E_, 0)
            R['e6'][ix] = r + 32.0 / (n - 1) * (S_ * ok - E_ * ok).sum(1)
        for mk, pk, om, op, Smat in (('gmu', 'gph', 'g_mu', 'g_phi', Sf.astype(float)), ('mmu', 'mph', 'gm_mu', 'gm_phi', None)):
            m0, p0 = R[mk][ix], R[pk][ix]
            kn = ~np.isnan(m0)
            pp = np.where(kn, np.minimum(np.sqrt(np.nan_to_num(p0) ** 2 + C_G * C_G * (d - last[ix]) / 30.0), PHI0), np.nan)
            O[om][s:e] = m0
            O[op][s:e] = pp
            if n < 2:
                continue
            mu = np.where(kn, m0, m0[kn].mean() if kn.any() else 1500.0)
            ph = np.where(kn, pp, PHI0)
            if Smat is None:
                if tok[s]:
                    gp = gap[s:e]
                    Smat = 0.5 + 0.5 * np.clip((gp[None, :] - gp[:, None]) / 0.5, -1, 1)
                else:
                    Smat = Sf.astype(float)
            R[mk][ix], R[pk][ix] = _g_update(mu, ph, Smat, W_G / (n - 1))
        last[ix] = d
    return O


def _run_kalman(S):
    hid, dn = S.hid.to_numpy(), S.dn.to_numpy()
    si, ap = S.SI.to_numpy(float), S.a_prior.to_numpy(float)
    om, osd = np.full(len(S), np.nan), np.full(len(S), np.nan)
    m = P = 0.0
    seen, ld = False, 0
    for i in range(len(S)):
        if i == 0 or hid[i] != hid[i - 1]:
            seen = False
        if not seen:
            if np.isnan(si[i]):
                continue
            m0 = ap[i] if not np.isnan(ap[i]) else M_GLOB
            k = V0 / (V0 + R_K)
            m, P = m0 + k * (si[i] - m0), (1 - k) * V0
            seen, ld = True, dn[i]
            continue
        Pp = P + QD * (dn[i] - ld)
        om[i], osd[i] = m, np.sqrt(Pp)
        if not np.isnan(si[i]):
            k = Pp / (Pp + R_K)
            m, P = m + k * (si[i] - m), (1 - k) * Pp
        else:
            P = Pp
        ld = dn[i]
    return om, osd


def glicko(day, h, U):
    """→ その日の南関の出走馬(取消・除外を除く)1 頭 1 行: Q4 + LG 18 列。"""
    rd = h.race_date.astype(str).str[:10]
    st = h[(rd >= '2014-01-01') & (rd <= day) & ~h.finish_note.isin(CANCEL)]
    st = _q4(st[['track', 'race_date', 'race_no', 'umaban', 'horse_name', 'horse_key', 'finish', 'time_sec']])
    st['finish'] = pd.to_numeric(st.finish, errors='coerce')
    st['time_sec'] = pd.to_numeric(st.time_sec, errors='coerce')
    st.loc[st.race_date == day, ['finish', 'time_sec']] = np.nan  # その日の結果は使わない(出走表だけの扱い)
    st['hid'] = _nkey(st.horse_key).fillna(st.horse_name)
    st = _prep(st)
    O = _run_seq(st)
    S = U[~U.finish_note.isin(CANCEL)][['track', 'race_date', 'race_no', 'runner_number', 'horse_key', 'horse_name', 'SI', 'a_prior']]
    S = _q4(S.rename(columns={'runner_number': 'umaban'}))
    S = S[S.race_date <= day].copy()
    S.loc[S.race_date == day, 'SI'] = np.nan
    S['hid'] = _nkey(S.horse_key).fillna(S.horse_name)
    S['dn'] = _dn(S.race_date)
    S = S.sort_values(['hid', 'dn', 'race_no'], kind='mergesort').reset_index(drop=True)
    km, ksd = _run_kalman(S)
    A = st[Q4 + ['hid']].copy()
    for k, v in O.items():
        A[k] = v
    A = A[A.track.isin(NK)].reset_index(drop=True)
    B = S[Q4].copy()
    B['k_mu'], B['k_sd'] = km, ksd
    A = A.merge(B.drop_duplicates(Q4), on=Q4, how='left', validate='1:1')
    A = A[A.race_date == day].reset_index(drop=True)
    X = A[Q4].copy()
    g = A.groupby(KEY, sort=False)
    for pre, mu, sd in (('g', 'g_mu', 'g_phi'), ('gm', 'gm_mu', 'gm_phi'), ('k', 'k_mu', 'k_sd'), ('e6', 'e6', None)):
        X[f'lg_{pre}_mu' if pre != 'e6' else 'lg_e6'] = A[mu]
        if sd:
            X[f'lg_{pre}_sd'] = A[sd]
        X[f'lg_{pre}_rank'] = g[mu].rank(ascending=False, method='min')
        X[f'lg_{pre}_dif'] = A[mu] - g[mu].transform('mean')
        if sd:
            X[f'lg_{pre}_cons'] = A[mu] - 2 * A[sd]
    return X[Q4 + LG]


# ================================================================ ② 事実 5 列
WCOL = ['race_id', 'track', 'race_date', 'race_no', 'horse_name', 'kind', 'course', 'horse_tanpyo', 'work_tanpyo', 'work_date']


def works_raw(day, log=log0):
    """調教欄の行(研究の他場/data/backfill/cyokyo_*.csv と同じ形)= 固定の CSV(2018〜)+ CSV に無い race_id の毎日の分。"""
    import t8_forecast as t8
    dirs = [Path(os.environ.get('V3_CYOKYO_CSV', 'C:/Users/kouki/OneDrive/デスクトップ/他場/data/backfill')), ASSET / 'cyokyo_old']
    P, seen = [], set()
    for d in dirs:
        for t in NK:
            for y in range(2018, int(day[:4]) + 1):
                f = d / f'cyokyo_{t}_{y}.csv'
                if (t, y) in seen or not f.exists():
                    continue
                seen.add((t, y))
                P.append(pd.read_csv(f, encoding='utf-8-sig', usecols=WCOL, dtype=str)[WCOL])
    C = pd.concat(P, ignore_index=True)
    have = set(C.race_id.dropna().astype(str))
    if 'kb_rows' in CACHE:
        import kb_works
        parsed, src = kb_works.rows_to_parsed(CACHE['kb_rows']), 'nar_kb_works'
    else:
        parsed, src = [], 'json'
        for p in sorted(t8.JD.glob('*.json')):
            parsed.append(json.loads(p.read_text(encoding='utf-8')))
            parsed[-1].setdefault('race_id', p.stem)
    rows = []
    for x in parsed:
        rid = str(x.get('race_id') or '')
        t = t8.TRK.get(rid[6:8])
        if t is None or rid in have:
            continue
        rows += t8.bc.flatten_race(x, t, source='kb')
    J = pd.DataFrame(rows, columns=t8.bc.COLUMNS)[WCOL] if rows else pd.DataFrame(columns=WCOL)
    W = pd.concat([C, J.astype(object).where(J.notna(), None)], ignore_index=True)
    W = W[W.race_date.astype(str).str[:10] <= day]
    log('事実: 調教欄', len(C), '行(CSV)+', len(J), '行(' + src + ')・年', sorted({y for _, y in seen})[:1], '〜')
    return W


def facts(day, W, U, T):
    """→ その日の南関の出走馬: Q4 + FC 5 列。W = works_raw・U = 土台・T = 第9版の材料(g_rest)。"""
    C = W[W.track.isin(NK)].copy()
    C['race_date'] = C.race_date.astype(str).str[:10]
    C['race_no'] = pd.to_numeric(C.race_no, errors='coerce')
    C['hn'] = _nm(C.horse_name)
    C = C.dropna(subset=['race_no']).astype({'race_no': int})
    C['gai'] = ((C.horse_tanpyo == '外厩調整') | (C.work_tanpyo == '外厩調整') | C.course.astype(str).str.startswith('牧場')).astype(int)
    C['jra'] = C.course.astype(str).str[:1].isin(['栗', '美']).astype(int)
    C['in30'] = ((pd.to_datetime(C.race_date) - pd.to_datetime(C.work_date, errors='coerce')).dt.days <= 30).astype(int)
    k4 = ['track', 'race_date', 'race_no', 'hn']
    fin = C[C.kind == 'final'][k4 + ['jra']].drop_duplicates(k4)
    cy = C.groupby(k4).agg(gai=('gai', 'max'), n30=('in30', 'sum')).reset_index().merge(fin, on=k4, how='left')
    B4 = _q4(U[['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'horse_key']].rename(columns={'runner_number': 'umaban'}))
    B4 = B4[(B4.race_date >= '2018-01-01') & (B4.race_date <= day)]
    B4['hn'] = _nm(B4.horse_name)
    cy = cy.merge(B4[Q4 + ['hn']], on=k4)
    X = cy[Q4].copy()
    X['fc_gai'] = cy.gai.astype(float)
    X['fc_jra'] = cy.jra.fillna(0).astype(float)
    X['fc_n30'] = cy.n30.astype(float)
    X = X.drop_duplicates(Q4).sort_values(['race_date', 'track', 'race_no', 'umaban']).reset_index(drop=True)
    X = X.merge(B4[Q4 + ['horse_key']].drop_duplicates(Q4), on=Q4, how='left')
    Wk = X[X.fc_n30.notna() & X.horse_key.notna()]
    gw = Wk.groupby('horse_key').fc_n30
    prev = (gw.cumsum() - Wk.fc_n30) / gw.cumcount().replace(0, np.nan)
    X['n30_diff'] = (X.fc_n30 - prev.reindex(X.index)).clip(-5, 5)
    X = X[X.race_date == day]
    R = _q4(T[T.race_date.astype(str).str[:10] == day][Q4 + ['g_rest']]).drop_duplicates(Q4)
    R = R[R.track.isin(NK)].merge(X[Q4 + ['fc_gai', 'fc_jra', 'fc_n30', 'n30_diff']], on=Q4, how='left')
    R['rest60'] = (R.g_rest > 60).astype(float).where(R.fc_n30.notna())
    return R[Q4 + FC]


# ================================================================ ③ 談話 14 列
EVT = r'骨折|骨瘤|屈腱|球節|裂蹄|蹄葉|ソエ|跛行|捻挫|骨膜|骨片|鼻出血|ノド|喉|喘鳴|心房細動|熱発|発熱|疝痛|去勢|靭帯'
PAST = r'明け|治っ|癒え|以前|前は|当時|完治|回復|手術(?:後|して)|休養|放牧|立て直'
NEG = r'(?:は|も)?(?:な(?:い|く)|心配ない|問題ない|大丈夫)'
E5 = 'intfloat/multilingual-e5-small'
E5_REV = '614241f622f53c4eeff9890bdc4f31cfecc418b3'


def _evt(t):
    now = past = 0.0
    for s in re.split(r'[。!?、]', t):
        m = re.search(EVT, s)
        if not m:
            continue
        if re.match(NEG, s[m.end():m.end() + 8]):
            continue
        if re.search(PAST, s):
            past = 1.0
        else:
            now = 1.0
    return now, past


def danwa_rows(d):
    """nar_kb_danwa の形(Q4・raw・headline・trainer・comment)→ Q4・mk・tr・t(研究 v13w_run.read_danwa + danwa_lab.clean と同じ)。"""
    d = _q4(d)
    tx = d.headline.fillna('').astype(str) + '。' + d.comment.fillna('').astype(str)
    d['t'] = tx.str.strip().str.strip('。').str.strip()
    d['mk'] = d.raw.fillna('').astype(str).str[:1]
    d['tr'] = d.trainer.fillna('').astype(str).str.strip()
    return d[Q4 + ['mk', 'tr', 't']].drop_duplicates(Q4)


def _proba(X, c):
    W, b = np.asarray(c['coef'], np.float64), np.asarray(c['intercept'], np.float64)
    z = X.astype(np.float64) @ W.T + b
    if len(c['classes']) == 2:
        p = 1 / (1 + np.exp(-z[:, 0]))
        return np.c_[1 - p, p]
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def items(D, log=log0):
    """本文 t → 7 項目の確率から作る 8 つの値(dw_dir・dw_fit・dw_conf・dw_fix・dw_worry・dw_cfit・excp)。本文が空なら欠け。"""
    clf = json.loads((ASSET / 'danwa_clf.json').read_text(encoding='utf-8'))['items']
    U = pd.Series(D.t.unique())
    U = U[U.str.len() > 0].reset_index(drop=True)
    out = pd.DataFrame(index=D.index, columns=['dw_dir', 'dw_fit', 'dw_conf', 'dw_fix', 'dw_worry', 'dw_cfit', 'excp'], dtype=float)
    if not len(U):
        return out
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(E5, device='cpu', revision=E5_REV)
    E = m.encode(['query: ' + s for s in U.tolist()], batch_size=64, normalize_embeddings=True).astype(np.float16).astype(np.float32)
    log('談話: 文の数の並び', len(U), '文', round(time.time() - t0), '秒')
    ix = pd.Series(np.arange(len(U)), index=U)
    has = D.t.str.len().to_numpy() > 0
    X = E[ix.reindex(D.t[has]).to_numpy()]
    P = {}
    for c, v in clf.items():
        pr = _proba(X, v)
        for j, k in enumerate(v['classes']):
            P[f'{c}_{k}'] = pr[:, j]
    vals = {'dw_dir': P['dir_up'] - P['dir_down'], 'dw_fit': P['fit_full'] - P['fit_mid'],
            'dw_conf': sum(k * P[f'conf_{k}'] for k in range(1, 6)), 'dw_fix': P['fix_yes'], 'dw_worry': 1 - P['worry_none'],
            'dw_cfit': P['cfit_good'] - P['cfit_bad'], 'excp': 1 - P['exc_none']}
    for c, v in vals.items():
        out.loc[has, c] = v
    return out


def danwa(day, U, today, hist, snap=None, log=log0):
    """→ その日の談話のある馬: Q4 + DW 14 列。today・hist = danwa_rows の形(hist = 集計の締めの翌日〜前日)。
    snap = (consts, tr 表, hs 表)。無ければ固定ファイル。"""
    if snap is None:
        snap = (json.loads((ASSET / 'danwa_snap.json').read_text(encoding='utf-8')),
                pd.read_parquet(ASSET / 'danwa_snap_tr.parquet'), pd.read_parquet(ASSET / 'danwa_snap_hs.parquet'))
    cst, STr, SHs = snap
    D = pd.concat([hist.assign(_h=1), today.assign(_h=0)], ignore_index=True)
    D = D[D.race_date <= day].drop_duplicates(Q4, keep='last').reset_index(drop=True)
    D = D.join(items(D, log=log))
    ev = D.t.map(_evt)
    D['dw_evt_now'], D['dw_evt_past'] = ev.str[0], ev.str[1]
    D['k_mk'] = D.mk.map({'◎': 2.0, '○': 1.0, '〇': 1.0, '△': 0.0})
    D['k_mkrel'] = D.k_mk - D.groupby(KEY).k_mk.transform('mean')
    B = _q4(U[['track', 'race_date', 'race_no', 'runner_number', 'horse_key', 'finish']].rename(columns={'runner_number': 'umaban'}))
    B = B[B.race_date <= day].dropna(subset=['horse_key']).drop_duplicates(Q4).sort_values(['horse_key', 'race_date', 'race_no'])
    B['bad'] = pd.to_numeric(B.finish, errors='coerce') / B.groupby(KEY).umaban.transform('size')
    B.loc[B.race_date == day, 'bad'] = np.nan
    B['last_bad'] = B.groupby('horse_key').bad.shift(1)
    D = D.merge(B[Q4 + ['horse_key', 'last_bad']], on=Q4, how='left')
    D['dw_exc'] = D.excp * D.last_bad
    D['tr2'] = D.tr.fillna('').replace('', np.nan)
    pre = D[D.race_date < day]
    # 話し手・馬の前の分の合計と数(集計の締めまで + 締めの翌日〜前日)
    a = pre[pre.tr2.notna()].groupby('tr2').dw_conf.agg(['sum', 'size'])
    tr = STr.set_index('tr').reindex(a.index.union(STr.tr)).fillna(0)
    tr['s'] = tr['sum'] + a['sum'].reindex(tr.index).fillna(0)
    tr['n'] = tr['size'] + a['size'].reindex(tr.index).fillna(0)
    b = pre[pre.horse_key.notna()].groupby('horse_key').dw_conf.agg(['sum', 'size'])
    hs = SHs.set_index('horse_key')
    hs = hs.reindex(b.index.union(hs.index))
    hs['s'] = hs['sum'].fillna(0) + b['sum'].reindex(hs.index).fillna(0)
    hs['n'] = hs['size'].fillna(0) + b['size'].reindex(hs.index).fillna(0)
    lastd = pre[pre.horse_key.notna()].sort_values(['horse_key', 'race_date', 'race_no']).drop_duplicates('horse_key', keep='last') \
        .set_index('horse_key').dw_dir  # 最後の行そのもの(欠けも含む = 研究の shift(1) と同じ)
    has_new = set(pre[pre.horse_key.notna()].horse_key)
    hs['last_dir'] = [lastd[k] if k in has_new else v for k, v in zip(hs.index, hs.last_dir)]
    X = D[D.race_date == day].copy()
    s_, n_ = X.tr2.map(tr['s']).fillna(0), X.tr2.map(tr['n']).fillna(0)
    X['dw_conf_tr'] = (X.dw_conf - (s_ + 30.0 * cst['mu_tr']) / (n_ + 30.0)).where(X.tr2.notna())
    s_, n_ = X.horse_key.map(hs['s']).fillna(0), X.horse_key.map(hs['n']).fillna(0)
    X['dw_conf_hs'] = (X.dw_conf - (s_ + 3.0 * cst['mu_hs']) / (n_ + 3.0)).where(X.horse_key.notna())
    X['dw_dir_chg'] = (X.dw_dir - X.horse_key.map(hs['last_dir'])).where(X.horse_key.notna())
    return X[Q4 + DW].reset_index(drop=True)


def danwa_db(lo, hi, log=log0):
    """nar_kb_danwa の [lo, hi) の南関の行(読むだけ)。"""
    base = os.environ.get('SUPABASE_URL') or os.environ.get('NAR_SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('NAR_SUPABASE_SERVICE_KEY')
    cols = ['track', 'race_date', 'race_no', 'umaban', 'raw', 'headline', 'trainer', 'comment']
    if not (base and key):
        raise RuntimeError('鍵が無い(nar_kb_danwa を読めない)')
    rows, off = [], 0
    while True:
        q = urllib.parse.urlencode([('select', ','.join(cols)), ('track', 'in.(' + ','.join(NK) + ')'),
                                    ('race_date', f'gte.{lo}'), ('race_date', f'lt.{hi}'),
                                    ('order', 'race_date,track,race_no,umaban'), ('limit', '1000'), ('offset', str(off))])
        req = urllib.request.Request(f"{base.rstrip('/')}/rest/v1/nar_kb_danwa?{q}", headers={'apikey': key, 'Authorization': f'Bearer {key}'})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read().decode('utf-8'))
        rows += got
        if len(got) < 1000:
            break
        off += 1000
    d = pd.DataFrame(rows, columns=cols)
    log('談話: nar_kb_danwa', lo, '〜', hi, len(d), '頭', d.race_date.nunique() if len(d) else 0, '日')
    return d


# ================================================================ 本体
def feats37(day, h, U, T, W, today, hist, snap=None, log=log0):
    """→ その日の南関の出走馬(第9版の材料 T の行)1 頭 1 行: Q4 + 37 列と、見張りの値のある割合。"""
    R = _q4(T[T.race_date.astype(str).str[:10] == day][Q4]).drop_duplicates(Q4)
    R = R[R.track.isin(NK)].reset_index(drop=True)
    t0 = time.time()
    G = glicko(day, h, U)
    log('Glicko 18 列', G.shape, round(time.time() - t0), '秒')
    F = facts(day, W, U, T)
    D = danwa(day, U, today, hist, snap=snap, log=log)
    X = R.merge(G, on=Q4, how='left', validate='1:1').merge(F, on=Q4, how='left', validate='1:1') \
        .merge(D, on=Q4, how='left', validate='1:1')
    fill = {c: round(float(X[c].notna().mean()), 3) for c in ('lg_g_mu', 'lg_k_mu', 'fc_n30', 'dw_dir', 'k_mk')}
    return X[Q4 + COLS], fill


def boosters():
    import lightgbm as lgb
    meta = json.loads((ASSET / 't14_bundle.json').read_text(encoding='utf-8'))
    assert meta['cols'] == COLS, '木の列の順が台本と違う'
    return [lgb.Booster(model_file=str(ASSET / f't14_bundle_s{s}.txt')) for s in meta['seeds']]


def p3prime(z, g):
    R = g.max() + 1
    lo, hi = np.full(R, -30.0), np.full(R, 30.0)
    for _ in range(100):
        mid = (lo + hi) / 2
        up = np.bincount(g, 1 / (1 + np.exp(-(z + mid[g]))), R) < 3
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    return 1 / (1 + np.exp(-(z + ((lo + hi) / 2)[g])))


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def apply_table(x, F, M):
    """x = 前日の表(Q4・p1・p3p・rank・mark …)→ 束を足して p3p・rank・mark を出し直す。元の値は p3p_dw・mark_dw に残す。"""
    x = _q4(x.drop(columns=[c for c in COLS + ['b14_u'] if c in x.columns]))
    x = x.merge(F, on=Q4, how='left', validate='1:1')
    A = x[COLS].astype(float).to_numpy()
    u = np.mean([m.predict(A, raw_score=True) for m in M], axis=0)
    x['p3p_dw'], x['mark_dw'], x['b14_u'] = x.p3p, x['mark'], u
    g = x.groupby(KEY, sort=False).ngroup().to_numpy()
    q0 = np.maximum(1 / (1 + np.exp(-(lg(x.p3p) + u))), x.p1.to_numpy(float))
    q = p3prime(lg(q0), g)
    big = x.groupby(KEY, sort=False).umaban.transform('size').to_numpy() > 3
    x['p3p'] = np.where(big, q, x.p3p)
    o = x.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map({1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}).fillna('')
    return x.drop(columns=COLS)


def run(day, h, races, T, csv_path, log=log0):
    """便の入口(v3_daily): 37 列を作り、見張りを通れば前日の表の CSV を書き換える。→ 足したか(True/False)。"""
    import danwa_marks
    U = CACHE.get('U')
    if U is None or U.race_date.astype(str).str[:10].max() < day:
        import t4_open
        log('束: 土台 U を作り直す')
        U = t4_open.base_of(h[h.race_date.astype(str).str[:10] <= day], races[races.race_date.astype(str).str[:10] <= day])
    W = works_raw(day, log=log)
    tday = danwa_marks.LAST.get(day)
    if tday is None:
        danwa_marks.load(day, log=log)
        tday = danwa_marks.LAST[day]
    cut = json.loads((ASSET / 'danwa_snap.json').read_text(encoding='utf-8'))['cut']
    lo = (pd.Timestamp(cut) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    hist = danwa_rows(danwa_db(lo, day, log=log))
    F, fill = feats37(day, h, U, T, W, danwa_rows(tday), hist, log=log)
    log('束 37 列 値のある割合', fill)
    bad = {k: fill[k] for k, v in WATCH.items() if fill[k] < v}
    if bad:
        log('⛔ 束の見張りで止める(第10版 + 談話の印のまま)', bad, '/ 線', WATCH)
        return False
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    y = apply_table(x, F, boosters())
    ch = int((y[y['rank'] == 1].set_index(KEY).umaban != _q4(x)[x['rank'] == 1].set_index(KEY).umaban).sum())
    y = y.sort_values(KEY + ['rank'], kind='mergesort')
    y.to_csv(csv_path, index=False, encoding='utf-8-sig')
    log('束 足した', y[KEY].drop_duplicates().shape[0], 'R・木の値 平均', round(float(y.b14_u.mean()), 4), '幅',
        round(float(y.b14_u.std()), 4), '・本命が替わった', ch, 'R')
    return True


# ================================================================ 手元の照合
def check(days):
    """研究の材料と照合: h・U は手元の便の読み口、談話は研究の本文(v3/danwa_text)で、集計の締めを 2026-07-31 に置いて作り直す。"""
    import t5_open as o5
    import t6_forecast as f6
    import t4_open
    V = Path('C:/Users/kouki/nankan_ai/v3')
    h, races = f6.f4.fill_key(*o5.load5('forward'))
    G0 = _q4(pd.read_parquet(V / 'feat_lit_g.parquet'))
    F0 = _q4(pd.read_parquet(V / 'feat_fact4z.parquet', columns=Q4 + FC))
    D0 = _q4(pd.read_parquet(V / 'feat_danwa_v2.parquet', columns=Q4 + DW))
    T6 = pd.concat([pd.read_parquet(V / f, columns=Q4 + ['g_rest']) for f in ('feat_t6_explore.parquet', 'feat_t6_open.parquet')])
    TXT = _q4(pd.read_parquet(V / 'danwa_text.parquet', columns=Q4 + ['mk', 'tr', 't']))
    snap = json.loads((ASSET / 'check_snap' / 'danwa_snap.json').read_text(encoding='utf-8'))
    snap = (snap, pd.read_parquet(ASSET / 'check_snap' / 'danwa_snap_tr.parquet'), pd.read_parquet(ASSET / 'check_snap' / 'danwa_snap_hs.parquet'))
    W = works_raw(max(days))
    res = []
    for day in days:
        hh = h[h.race_date.astype(str).str[:10] <= day]
        U = t4_open.base_of(hh, races[races.race_date.astype(str).str[:10] <= day])
        T = _q4(T6[T6.race_date.astype(str).str[:10] == day])
        hist = TXT[(TXT.race_date > snap[0]['cut']) & (TXT.race_date < day)]
        X, fill = feats37(day, hh, U, T, W, TXT[TXT.race_date == day], hist, snap=snap)
        for nm, R0, cols in (('Glicko', G0, LG), ('事実', F0, FC), ('談話', D0, DW)):
            Y = X[Q4 + cols].merge(R0[R0.race_date == day], on=Q4, how='inner', suffixes=('', '_r'))
            for c in cols:
                a, b = Y[c].to_numpy(float), Y[c + '_r'].to_numpy(float)
                same = (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-6)
                res.append({'day': day, '群': nm, '列': c, '行': len(Y), '一致': round(float(same.mean()), 4),
                            '最大の差': round(float(np.nanmax(np.abs(a - b))) if (~np.isnan(a) & ~np.isnan(b)).any() else 0.0, 6)})
        log0(day, '値のある割合', fill)
    R = pd.DataFrame(res)
    print(R.groupby(['群', '列'], sort=False).agg(行=('行', 'sum'), 一致=('一致', 'min'), 最大の差=('最大の差', 'max')).to_string())
    return R


if __name__ == '__main__':
    if sys.argv[1] == 'check':
        check(sys.argv[2:])
