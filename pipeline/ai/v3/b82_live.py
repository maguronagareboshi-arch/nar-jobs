# -*- coding: utf-8 -*-
"""並び読みの 3 案まとめ(南関 AI v3 決め 82・2026-11-16 合格・研究 nankan-ai-v3 src/f5_scripts/seqb82_judge.py・本番の学び seqb82_prod_fit.py)。
南関 第31版 直前版 = 第30版 直前版の「調教入りの並び読みの差 d = u_cy − u_X」を、3 案まとめの並び読みの差 d = u_b − u_X に替える(倍は同じ A1 0.5・A3 0.5)。

並び(研究 seqall_1116.build と同じ式):
  決め 79 の並び(過去走 10 本 + 調教、長さ 20)の調教の行に併せ馬 3 列(aw_has・aw_res・aw_mar)を足し(NT 14 → 17)、
  過去走の行に ① の 21 列(着差の並び 6・談話と短評 9・その時の AI の見込み 3・馬主の替わり 3)+ 今回の行か 1 を足し、
  今回の行(談話・短評・馬主)のある馬は最後に 1 本 → (N, 21, 80 + 22)。
① の元: 2026-08-31 までは固めた表(研究の表・リリース v3-b82 の b82_table.parquet)・2026-09-01 からは本番の元(tail)。
  着差 = 公式の成績表・談話 = nar_kb_danwa(印・見出し・本文)・短評 = 競馬ブックの調教の短評(tanpyo_live の型の表)・
  見込み = 見込みの木(seqai_wf_{年}.txt)を直前の便が当日の材料に当てた値(行の meta.b82.wf・9/1〜11/16 は埋めた表)・馬主 = v7c_owner の走った時の馬主。
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

K = ['track', 'race_date', 'race_no', 'umaban']
G1 = ['mg_has', 'm_to2', 'm_to3', 'm_ahead', 'm_behind', 'm_near']
G2 = ['dw_has', 'dw_mk', 'dw_rel', 'dw_up', 'dw_weak', 'dw_exc', 'tp_has', 'tp_hs', 'tp_ws']
G3 = ['ai_has', 'ai_p3', 'ai_res']
G5 = ['own_has', 'own_chg', 'own_n']
XC = G1 + G2 + G3 + G5
NOWC = G2 + G5
NX = len(XC) + 1
AWC = ['aw_has', 'aw_res', 'aw_mar']
CUT = '2026-09-01'      # 固めた表はこの日より前・この日からは本番の元
W_UP = '前進|上積み|変わり身|良化|上向|復調|進境'
W_WEAK = '壁|厳しい|どうか|結果が出|冴えず|もうひと息|入着'
W_EXC = '前走は.{0,12}(?:不利|出遅|馬場|展開|ロス|外を回|仕方|休み明け|久々)'
PAT = re.compile(r'^(?P<name>.+?)（(?P<cls>[^）]*)）(?P<pash>[^の同先遅]+?)(?:の(?P<side>内|外|中))?'
                 r'(?:を(?P<dist>\d)Ｆ(?P<how>併|付))?(?:(?P<mar>\d+\.\d+)秒)?(?P<res>先着|同入|遅れ|併入)?$')


def log0(*a):
    print('[b82]', *a, flush=True)


# ------------------------------------------------------------------ ① の群(研究 seqall_1116 / seqtalk_1115 と同じ式)
def margins(r):
    """r = 走りの表(K + finish・time_sec)→ K + G1。"""
    r = r[K + ['finish', 'time_sec']].drop_duplicates(K).reset_index(drop=True)
    r['rid'] = r.groupby(['track', 'race_date', 'race_no']).ngroup()
    t = r.time_sec.where(r.finish.notna() & (r.time_sec > 0))
    o = r.assign(t=t).sort_values(['rid', 'finish'])
    o = o[o.t.notna()]
    g = o.groupby('rid').t
    o['m_ahead'] = (o.t - g.shift(1)).clip(0, 5) / 2
    o['m_behind'] = (g.shift(-1) - o.t).clip(0, 5) / 2
    nth = lambda k: g.transform(lambda x: x.iloc[k] if len(x) > k else np.nan)  # noqa: E731
    o['m_to2'] = (o.t - nth(1)).clip(-5, 5) / 2
    o['m_to3'] = (o.t - nth(2)).clip(-5, 5) / 2
    tt, rr = o.t.to_numpy(), o.rid.to_numpy()
    cnt = np.zeros(len(o))
    st = np.r_[0, np.flatnonzero(rr[1:] != rr[:-1]) + 1, len(o)]
    for a, b in zip(st[:-1], st[1:]):
        x = tt[a:b]
        cnt[a:b] = (np.abs(x[:, None] - x[None, :]) <= 0.2).sum(1) - 1
    o['m_near'] = np.minimum(cnt, 6) / 3
    o['mg_has'] = 1.0
    return o[K + G1].fillna(0.0)


def talk(D):
    """D = 談話(K + raw・headline・comment)→ K + 談話 6 列。印 = raw の先頭の字。"""
    D = D.drop_duplicates(K).copy()
    tx = D.headline.fillna('').astype(str) + ' ' + D.comment.fillna('').astype(str)
    D['dw_has'] = 1.0
    D['dw_mk'] = D.raw.fillna('').astype(str).str[:1].map({'◎': 1.0, '○': 0.0, '〇': 0.0, '△': -1.0}).fillna(0.0)
    D['dw_rel'] = D.dw_mk - D.groupby(['track', 'race_date', 'race_no']).dw_mk.transform('mean')
    D['dw_up'] = tx.str.contains(W_UP).astype(float)
    D['dw_weak'] = tx.str.contains(W_WEAK).astype(float)
    D['dw_exc'] = tx.str.contains(W_EXC).astype(float)
    return D[K + G2[:6]]


def tanpyo(T, M):
    """T = 短評(K + tp_h(馬の短評)・tp_w(最終追いの短評))・M = tanpyo_live.load の型の表 → K + 短評 3 列。"""
    import unicodedata
    nm = lambda s: unicodedata.normalize('NFKC', s).strip() if isinstance(s, str) else None  # noqa: E731
    sc = lambda s: s.map(lambda x: M['SC'].get(M['P2G'].get(nm(x)), 0) if isinstance(x, str) else np.nan)  # noqa: E731
    T = T.drop_duplicates(K).copy()
    T['tp_has'] = (T.tp_h.notna() | T.tp_w.notna()).astype(float)
    T['tp_hs'] = sc(T.tp_h).fillna(0.0) / 2
    T['tp_ws'] = sc(T.tp_w).fillna(0.0) / 2
    return T[K + G2[6:]]


def ai(W):
    """W = K + wf_p3(その時の見込み)+ Y3(3 着内)→ K + G3。"""
    W = W[W.wf_p3.notna() & W.Y3.notna()].drop_duplicates(K).copy()
    W['ai_has'] = 1.0
    W['ai_p3'] = W.wf_p3 * 2
    W['ai_res'] = W.Y3 - W.wf_p3
    return W[K + G3]


def owner(S, last=None):
    """S = K + hkey(馬の鍵)+ owner(走った時の馬主・無ければ空)。last = 固めた表の最後の {hkey: (馬主, 替わりの数)}。→ K + G5。"""
    S = S.sort_values(['hkey', 'race_date', 'race_no']).drop_duplicates(K, keep='last').copy()
    oc = S.owner.astype(str).str.strip()
    S['own_has'] = (~oc.isin(['000000', '', 'nan', 'None'])).astype(float)
    S['oc'] = oc.where(S.own_has > 0)
    S['ocf'] = S.groupby('hkey').oc.ffill()
    prev = S.groupby('hkey').ocf.shift(1)
    n0 = pd.Series(0.0, index=S.index)
    if last:
        first = ~S.hkey.duplicated()
        prev = prev.where(~first, S.hkey.map(lambda h: (last.get(h) or (None, 0))[0]))
        n0 = S.hkey.map(lambda h: float((last.get(h) or (None, 0))[1]))
    S['own_chg'] = (S.oc.notna() & prev.notna() & (S.oc != prev)).astype(float)
    S['own_n'] = np.minimum(n0 + S.groupby('hkey').own_chg.cumsum(), 4) / 4
    return S[K + G5]


def table(frozen, parts):
    """固めた表(CUT より前)+ 本番の元の群(CUT から)→ K + XC。"""
    A = frozen[frozen.race_date < CUT][K + XC]
    T = None
    for P in parts:
        P = P[P.race_date >= CUT]
        T = P if T is None else T.merge(P, on=K, how='outer')
    if T is not None:
        A = pd.concat([A, T], ignore_index=True)
    A[XC] = A.reindex(columns=XC).fillna(0.0).astype(np.float32)
    A['race_no'], A['umaban'] = A.race_no.astype(int), A.umaban.astype(int)
    return A.drop_duplicates(K, keep='last')


# ------------------------------------------------------------------ 併せ馬(調教の行へ)
def awase_cols(partner):
    """相手の行の字(1 本)→ (aw_has, aw_res, aw_mar)。研究 seqall_1116.awase_rows と同じ。"""
    if not isinstance(partner, str) or not partner:
        return 0.0, 0.0, 0.0
    m = PAT.match(partner)
    res = {'先着': 1.0, '同入': 0.0, '併入': 0.0, '遅れ': -1.0}.get(m.group('res')) if m else None
    mar = float(m.group('mar')) if m and m.group('mar') else 0.0
    r = 0.0 if res is None else res
    return 1.0, r, float(np.sign(r) * min(max(mar, 0.0), 3.0))


# ------------------------------------------------------------------ 並び
def attach(Hn, Tg, A, F):
    """研究 seqall_1116.build の後半(seqbundle_1116.attach と同じ)。Hn = 決め 79 の並び(併せ馬入り)・Tg = K + horse_name・A = table()。"""
    gcol, vcol = F - 4, F - 1
    N, TL, FF = Hn.shape
    Tg = Tg.reset_index(drop=True)
    tdn = (pd.to_datetime(Tg.race_date) - pd.Timestamp('2014-01-01')).dt.days.to_numpy()
    An = A.dropna(subset=['horse_name']).drop_duplicates(['horse_name', 'race_date'])
    key = pd.Series(np.arange(len(An)), index=pd.MultiIndex.from_frame(An[['horse_name', 'race_date']]))
    TV = An[XC].to_numpy(np.float32)
    out = np.zeros((N, TL + 1, FF + NX), np.float32)
    At = Tg[K].merge(A.drop(columns=['horse_name'], errors='ignore'), on=K, how='left')
    tnow = At[NOWC].fillna(0.0).to_numpy(np.float32)
    has = (At.dw_has.fillna(0) + At.tp_has.fillna(0) + At.own_has.fillna(0)).to_numpy() > 0
    rr, pp = np.nonzero(Hn[:, :, vcol] > 0.5)
    days = np.rint(np.expm1((Hn[rr, pp, gcol].astype(np.float64) + 1.5) * 3)).astype(int)
    dt_ = (pd.Timestamp('2014-01-01') + pd.to_timedelta(tdn[rr] - days, unit='D')).strftime('%Y-%m-%d')
    idx = key.reindex(pd.MultiIndex.from_arrays([Tg.horse_name.to_numpy()[rr], dt_])).to_numpy()
    ok = ~np.isnan(idx)
    sh = np.where(has, 0, 1)
    for i0 in (0, 1):
        m = sh == i0
        out[m, i0:i0 + TL, :FF] = Hn[m]
    pos = pp + sh[rr]
    out[rr[ok], pos[ok], FF:FF + len(XC)] = TV[idx[ok].astype(int)]
    hi = np.flatnonzero(has)
    nidx = [FF + XC.index(c) for c in NOWC]
    out[np.ix_(hi, [TL], nidx)] = tnow[hi][:, None, :]
    out[hi, TL, FF + NX - 1] = 1.0
    out[hi, TL, gcol] = np.log1p(0.0) / 3 - 1.5
    info = {'過去走の行': int(len(rr)), '① に結べた': int(ok.sum()), '今回の行あり': int(has.sum()), '頭': int(N)}
    return out, info


def seq_hist(Tg, hist, Wt, A, C=None):
    """決め 79 の並び(cy79_live.seq_hist)に併せ馬 3 列を足し、① をつける。Wt = cy79_live.works_tbl の表 + AWC の 3 列。"""
    import cy79_live
    C = dict(cy79_live.consts() if C is None else C)
    C['NT'] = int(C['NT']) + len(AWC)
    t0 = cy79_live.tokens
    cy79_live.tokens = lambda W: np.column_stack([t0(W), W[AWC].to_numpy(np.float32)]).astype(np.float32)
    try:
        Hn, info = cy79_live.seq_hist(Tg, hist, Wt, C)
    finally:
        cy79_live.tokens = t0
    out, i2 = attach(Hn, Tg, A, hist.shape[2])
    info.update(i2)
    return out, info


# ------------------------------------------------------------------ 当日の便
def load(mdir, prep_npz):
    """重み(mdir/b82_model.npz・b82_prod.json)と前日の材料(b82.npz)。どちらか無ければ None。"""
    mdir, prep_npz = Path(mdir), Path(prep_npz)
    if not (mdir / 'b82_model.npz').exists() or not prep_npz.exists():
        return None
    P = np.load(prep_npz)
    meta = json.loads((mdir / 'b82_prod.json').read_text(encoding='utf-8'))
    if P['hist'].shape[1:] != (meta['H'], meta['fh']) or P['ctx'].shape[1] != meta['fc']:
        raise AssertionError(f'3 案まとめの並びの材料の形 {P["hist"].shape[1:]}・{P["ctx"].shape[1]} が模型 {meta["H"]}・{meta["fh"]}・{meta["fc"]} と合わない')
    Z = np.load(mdir / 'b82_model.npz')
    Ws = [{k.split('/', 1)[1]: Z[k].astype(float) for k in Z.files if k.startswith(f's{s}/')} for s in meta['seeds']]
    ix = {(str(a), int(b), int(c)): i for i, (a, b, c) in enumerate(zip(P['track'], P['race_no'], P['umaban']))}
    return {'W': Ws, 'ix': ix, 'hist': P['hist'], 'ctx': P['ctx'], 'bw_prev': P['bw_prev'], 'n': len(ix), 'seeds': list(meta['seeds'])}


def resid(S, track, rno, b, going):
    """seq2_live.resid と同じ(模型だけ替える)。→ b の並びの u_b(種の平均)か None。"""
    import seq2_live
    return seq2_live.resid(S, track, rno, b, going)


def wf_load(mdir):
    """見込みの木(seqai_wf.json・seqai_wf_{年}.txt)。無ければ None。"""
    p = Path(mdir) / 'seqai_wf.json'
    if not p.exists():
        return None
    import lightgbm as lgb
    m = json.loads(p.read_text(encoding='utf-8'))
    m['B'] = lgb.Booster(model_str=(Path(mdir) / m['model']).read_text(encoding='utf-8'))
    return m


def wf_pred(M, b, day):
    """当日の材料 b(v29_gap.feats の戻り・66 本)→ 馬ごとの見込み(3 着内)。木の年と日の年が違えば None(年替わりは手で替える)。"""
    if M is None or int(str(day)[:4]) != int(M['year']):
        return None
    X = b.reindex(columns=M['feats']).astype(float).to_numpy()
    return M['B'].predict(X)
