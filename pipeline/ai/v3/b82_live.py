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
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ASSET = Path(os.environ.get('V3_B82', 'C:/Users/kouki/nankan_ai/v3/b82_prod'))   # リリース v3-b82 を開いた所
NKT = ('大井', '船橋', '川崎', '浦和')
WATCH = {'過去走の行に ① が結べた割合 ≥': 0.60, '今回の行がある割合 ≥': 0.30, '出走馬 ≥': 20}

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


_C = None


def log0(*a):
    print('[b82]', *a, flush=True)


def consts():
    """暗号化したリリース v3-consts の consts.json の b82(A1・A3・ON・TAG)。"""
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('b82')
    return _C


def is_on(day):
    """その日(レースの日)が決め 82 の ON 以降か(定数が読めなければ例外)。"""
    return str(day) >= str(consts().get('ON') or '9999-12-31')


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


# ------------------------------------------------------------------ 本番の元(CUT から)の読み口
def _get_all(path):
    """REST を 1000 行ずつ(path に order を必ず入れる・race_date を先に)。"""
    import kb_works
    base, key = kb_works.creds()
    if not base:
        raise RuntimeError('DB の鍵が無い')
    out, off = [], 0
    while True:
        req = urllib.request.Request(f'{base}{path}&limit=1000&offset={off}',
                                     headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai-v3'})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read().decode('utf-8'))
        out += got
        if len(got) < 1000:
            return out
        off += 1000


def official_runs(official=None, cols=('finish', 'time_sec', 'horse_name')):
    """公式の成績表(seq2_live.OFFICIAL/runs.parquet)→ K + cols(race_date は字・馬番は int)。"""
    if official is None:
        import seq2_live
        official = seq2_live.OFFICIAL
    r = pd.read_parquet(Path(official) / 'runs.parquet', columns=['track', 'race_date', 'race_no', 'runner_number'] + list(cols))
    r = r.rename(columns={'runner_number': 'umaban'})
    r['race_date'] = r.race_date.astype(str).str[:10]
    r['race_no'] = pd.to_numeric(r.race_no, errors='coerce')
    r['umaban'] = pd.to_numeric(r.umaban, errors='coerce')
    r = r.dropna(subset=['race_no', 'umaban'])
    r['race_no'], r['umaban'] = r.race_no.astype(int), r.umaban.astype(int)
    return r.drop_duplicates(K).reset_index(drop=True)


def src_margins(R, day):
    """着差 = 公式の成績表の CUT から前の日まで。"""
    return margins(R[(R.race_date >= CUT) & (R.race_date < day)])


def src_talk(day, rows=None):
    """談話 = nar_kb_danwa(CUT から day まで)。rows は照合用(DB のかわり)。"""
    if rows is None:
        rows = _get_all('/rest/v1/nar_kb_danwa?select=track,race_date,race_no,umaban,raw,headline,comment'
                        f'&track=in.({",".join(NKT)})&race_date=gte.{CUT}&race_date=lte.{day}&order=race_date,track,race_no,umaban')
    D = pd.DataFrame(rows, columns=K + ['raw', 'headline', 'comment'])
    if not len(D):
        return pd.DataFrame(columns=K + G2[:6])
    D['race_date'] = D.race_date.astype(str).str[:10]
    D['race_no'], D['umaban'] = D.race_no.astype(int), D.umaban.astype(int)
    D['raw'] = D.raw.fillna('').astype(str).str.strip()
    return talk(D)


def src_tanpyo(parsed, day, M):
    """短評 = nar_kb_works の頁の形(t8_forecast._W['parsed'])の馬の短評・最終追いの短評(研究 debut_tp.build と同じ = debut_live.entries)。"""
    import debut_live
    import tanpyo_live
    C = tanpyo_live._flat(parsed)
    C = C[(C.race_date.astype(str).str[:10] >= CUT) & (C.race_date.astype(str).str[:10] <= day)]
    if not len(C):
        return pd.DataFrame(columns=K + G2[6:])
    R = debut_live.entries(C)
    R = R[R.tp_w.notna() | R.tp_h.notna()]
    return tanpyo(R, M)


def src_ai(day, R, fill=None, rows=None):
    """その時の見込み = 埋めた表(リリースの b82_wf_fill.parquet・K + wf_p3)+ その後は直前版の行の meta.b82.wf({馬番: 見込み})。
    Y3 = 公式の着順 ≤ 3(着順の無い馬 = 中止など は 0)。"""
    F = pd.read_parquet(ASSET / 'b82_wf_fill.parquet') if fill is None else fill
    F = F[K + ['wf_p3']].copy()
    F['race_date'] = F.race_date.astype(str).str[:10]
    lo = max(CUT, str(F.race_date.max()) if len(F) else CUT)
    if rows is None:
        rows = _get_all('/rest/v1/nar_ai_marks?select=track,race_date,race_no,wf:meta->b82->wf'
                        f'&model=eq.v3-9&timing=eq.last&track=in.({",".join(NKT)})&race_date=gt.{lo}&race_date=lt.{day}'
                        '&order=race_date,track,race_no')
    add = [(r['track'], str(r['race_date'])[:10], int(r['race_no']), int(u), float(p))
           for r in rows if isinstance(r.get('wf'), dict) for u, p in r['wf'].items() if p is not None]
    F = pd.concat([F, pd.DataFrame(add, columns=K + ['wf_p3'])], ignore_index=True)
    F['race_no'], F['umaban'] = F.race_no.astype(int), F.umaban.astype(int)
    F = F[(F.race_date >= CUT) & (F.race_date < day)].drop_duplicates(K, keep='last')
    fin = R[K + ['finish']].copy()
    fin['Y3'] = (pd.to_numeric(fin.finish, errors='coerce') <= 3).astype(float)
    return ai(F.merge(fin[K + ['Y3']], on=K, how='inner'))


def src_owner(day, R, Tg, frozen, kd=None, db=None, cd=None):
    """馬主 = 走った時の馬主のコード(研究 kd_se_owner の owner_cd と同じ物差し・000000 = 馬主なし)。
    写しの終わり(kmax = 2026-09-30)までは K ごとのコード(リリースの b82_owner_cd.parquet)・その後は DB の今の馬主と替わりの記録の名前
    (v7c_owner.owner_rt と同じならし)→ 写しの中の同じ名前の最後のコード(写しに無い名前は名前そのものを 1 つのコードとして扱う)。
    CUT より前の 2024〜 の走りも並べて CUT からの行の替わりを数える。替わった回数 = 固めた表の CUT より前の最後の own_n × 4 + CUT からの替わり。"""
    import cy79_live
    import v7c_owner
    KD = (pd.read_parquet(v7c_owner.OWN_KD) if kd is None else kd).copy()
    CD = (pd.read_parquet(ASSET / 'b82_owner_cd.parquet') if cd is None else cd).copy()
    for X in (KD, CD):
        X['race_date'] = X.race_date.astype(str).str[:10]
        X['race_no'], X['umaban'] = X.race_no.astype(int), X.umaban.astype(int)
    kmax = str(KD.race_date.max())
    nc = KD.drop_duplicates(K, keep='last')[K + ['owner']].merge(CD.drop_duplicates(K, keep='last')[K + ['owner_cd']], on=K)
    n2c = nc.sort_values(['race_date', 'race_no']).groupby('owner').owner_cd.last().to_dict()
    S = R[R.track.isin(NKT) & (R.race_date >= '2024-01-01') & (R.race_date < day)][K + ['horse_name']]
    S = pd.concat([S, Tg[K + ['horse_name']]], ignore_index=True).drop_duplicates(K, keep='last')
    S = S.merge(CD.drop_duplicates(K, keep='last')[K + ['owner_cd']].rename(columns={'owner_cd': 'owner'}), on=K, how='left')
    late = (S.owner.isna() & (S.race_date > kmax)).to_numpy()
    keys = set(KD.owner.dropna())
    pre = sorted((k for k in keys if len(k) >= 4), key=len, reverse=True)

    def fit(s):
        s = cy79_live.norm(s)
        if not isinstance(s, str):
            return None
        s = v7c_owner.RE_CORP.sub('', s)
        return s if s in keys else next((k for k in pre if s.startswith(k)), s)
    n_late = int(late.sum())
    if n_late:
        hn_, dd_ = S.horse_name.to_numpy()[late], S.race_date.to_numpy()[late]
        got = v7c_owner.db_owner_asof(list(hn_), kmax, sorted(set(dd_))) if db is None else db
        nm_ = [fit(got.get(n, {}).get(d)) for n, d in zip(hn_, dd_)]
        S.loc[late, 'owner'] = [None if s is None else n2c.get(s, 'N:' + s) for s in nm_]
        log0('馬主 写しの後の名前 → コード', sum(s is not None and s in n2c for s in nm_), '/ 名前あり', sum(s is not None for s in nm_))
    S['hkey'] = S.horse_name.map(cy79_live.norm)
    S = S.dropna(subset=['hkey'])
    S['owner'] = S.owner.where(S.owner.notna(), '')
    O = owner(S, None).merge(S[K + ['hkey']], on=K)
    Fz = frozen[(frozen.race_date < CUT) & frozen.horse_name.notna()].copy()
    Fz['hkey'] = Fz.horse_name.map(cy79_live.norm)
    n0 = Fz.sort_values(['race_date', 'race_no']).groupby('hkey').own_n.last() * 4
    O = O[O.race_date >= CUT].sort_values(['hkey', 'race_date', 'race_no']).copy()
    O['own_n'] = np.minimum(O.hkey.map(n0).fillna(0.0) + O.groupby('hkey').own_chg.cumsum(), 4) / 4
    log0('馬主 CUT からの行', len(O), '・写しの後で DB から', n_late, '・馬主なし', int((O.own_has == 0).sum()), '・替わり', int(O.own_chg.sum()))
    return O[K + G5]


def src_awase(Wt, parsed, bf=None):
    """併せ馬 = 研究の拾い直し(リリースの b82_awase.parquet = 他場/data/backfill/awase の 4 場)+ nar_kb_works の相手の行。
    鍵 = race_id・馬番・調教の日・コース。相手の字の順で最初の 1 本(研究 seqall_1116.awase_rows と同じ)。拾い直しを先に。→ Wt + AWC。"""
    B = pd.read_parquet(ASSET / 'b82_awase.parquet') if bf is None else bf
    rows = []
    for p in parsed or []:
        rid = str(p.get('race_id') or '')
        for h in p.get('horses') or []:
            for w in h.get('works') or []:
                for s in (w.get('partners') or []):
                    if w.get('date') and h.get('umaban') is not None:
                        rows.append((rid, str(int(h['umaban'])), str(w['date'])[:10], str(w.get('course')), s))
    P = pd.DataFrame(rows, columns=['race_id', 'umaban', 'work_date', 'course', 'partner'])
    P = P.sort_values('partner').drop_duplicates(['race_id', 'umaban', 'work_date', 'course'])
    v = [awase_cols(s) for s in P.partner]
    for i, c in enumerate(AWC):
        P[c] = [x[i] for x in v]
    A = pd.concat([B[['race_id', 'umaban', 'work_date', 'course'] + AWC].astype({'umaban': str, 'course': str}), P.drop(columns=['partner'])],
                  ignore_index=True).drop_duplicates(['race_id', 'umaban', 'work_date', 'course'], keep='first')
    k = pd.DataFrame({'race_id': Wt.race_id.astype(str), 'umaban': Wt.umaban.astype(int).astype(str),
                      'work_date': Wt.work_date.astype(str).str[:10], 'course': Wt.course.astype(str)})
    M = k.merge(A, on=['race_id', 'umaban', 'work_date', 'course'], how='left', validate='m:1')
    Wt = Wt.copy()
    for c in AWC:
        Wt[c] = M[c].fillna(0.0).to_numpy(np.float32)
    log0('併せ馬 拾い直し', len(B), '・本番の相手の行', len(P), '・調教の行に結べた', int((Wt.aw_has > 0).sum()), '/', len(Wt))
    return Wt


def prep(day, T, hist, ctx, bwp, out, W=None, parsed=None, log=log0, src=None):
    """前日の便(seq2_live.prep の cy79 の後): その日の南関の出走馬の 3 案まとめの並びを OUT/DAY_b82.npz に。書けたらそのパス・書かなければ None。
    src は照合用(official・frozen・talk_rows・ai_rows・fill・kd・db・bf・M を差し替える)。"""
    import cy79_live
    src = src or {}
    C = cy79_live.consts()
    if W is None or parsed is None:
        import t8_forecast as t8
        W = t8.works()[0] if W is None else W
        parsed = t8._W.get('parsed') if parsed is None else parsed
    Tg = T[K].copy()
    Tg['horse_name'] = T.hk.astype(str).str.split('|').str[0]
    W = W[W.race_date.astype(str).str[:10] <= day]
    R = official_runs(src.get('official'))
    if int(pd.to_numeric(W.umaban, errors='coerce').isna().sum()):
        W, _ = cy79_live.fill_umaban(W, R)
    Wt = src_awase(cy79_live.works_tbl(W, C), parsed, src.get('bf'))
    Fz = pd.read_parquet(ASSET / 'b82_table.parquet') if src.get('frozen') is None else src['frozen']
    Fz = Fz.merge(R[K + ['horse_name']], on=K, how='left')
    if 'M' in src:
        M = src['M']
    else:
        import tanpyo_live
        M = tanpyo_live.load()
    parts = [src_margins(R, day), src_talk(day, src.get('talk_rows')), src_tanpyo(parsed, day, M), src_ai(day, R, src.get('fill'), src.get('ai_rows'))]
    O = src_owner(day, R, Tg, Fz, src.get('kd'), src.get('db'))
    A = table(Fz, parts + [O])
    nm = pd.concat([R[K + ['horse_name']], Tg[K + ['horse_name']]], ignore_index=True).drop_duplicates(K, keep='last')
    A = A.merge(nm, on=K, how='left')
    A = A[A.horse_name.isin(set(Tg.horse_name))]
    cnt = {c: int((A[A.race_date >= CUT][c] > 0).sum()) for c in ('mg_has', 'dw_has', 'tp_has', 'ai_has', 'own_has')}
    log('3 案まとめ CUT からの ① の行', cnt)
    Hn, info = seq_hist(Tg, hist, Wt, A, C)
    v = {'過去走の行に ① が結べた割合 ≥': info['① に結べた'] / max(info['過去走の行'], 1),
         '今回の行がある割合 ≥': info['今回の行あり'] / max(info['頭'], 1), '出走馬 ≥': info['頭']}
    ok = all(v[k] >= w for k, w in WATCH.items())
    info.update(cnt)
    log('3 案まとめ 見張り', {k: round(x, 3) if isinstance(x, float) else x for k, x in info.items()}, '→', '○' if ok else '× = 書かない')
    if not ok:
        return None
    p = Path(out) / f'{day}_b82.npz'
    np.savez_compressed(p, track=T.track.to_numpy().astype('U4'), race_no=T.race_no.to_numpy(int), umaban=T.umaban.to_numpy(int),
                        hist=Hn, ctx=ctx, bw_prev=bwp, info=json.dumps(info, ensure_ascii=False))
    log('3 案まとめ 材料', p.name, Hn.shape)
    return p


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
