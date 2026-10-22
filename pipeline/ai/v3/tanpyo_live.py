# -*- coding: utf-8 -*-
"""全馬の短評の層(決め 30・研究 nankan-ai-v3 src/f5_scripts/tanpyo_layer.py・tanpyo_prod.py・ユーザー承認 2026-10-14)。

競馬ブックの調教の短評(馬の短評・最終追いの短評)を、成績を見ずに意味で分けた型(研究 tanpyo_pat.py の G)と段(SC: −2〜+2)にして、
3 着内と 1 着の小さな木 2 本で、前日版と直前版の率を最後に直す(勝つ率も一緒に直す)。
- 材料 15 列 = 今の調教の 9 列(CY6・cy_day_pct_rk・cy_stable_rk・shinba)+ 土台の 3 着内の logit off3 + 馬・最終追いの段 v_h・v_w
  + 型 c_h・c_w(カテゴリ)+ 前走の馬の短評の段 pv_h。表に無い言葉は段 0・型なし。短評の無い馬は空。
- 前走 = 調教の表に載った一つ前の南関の出走(固定の表 tanpyo_hist.parquet + それより後は nar_kb_works)。今日の出走表の調教に載らない馬は空。
- 初出走の層(決め 28)の馬は触らない(外した分 0・割り直しだけ動く)。4 頭以上のレースだけ。
- 足し方(研究 tanpyo_layer.probs と同じ): p1′ = R で合計 1(σ(logit p1 + u1))・p3′ = 合計 3(max(σ(logit p3 + u3), min(p1′, 0.999)))。
- 土台 = 勝つ率の直し(p1_follow)の後の率(研究もその土台で学んだ)。前日版は前日の表の CSV を直し、直前版は材料を v29 の土台へ
  書いて当日の便(v29_gap.day_marks)が勝つ率の直しの後に足す。
模型 = V3_TANPYO/tanpyo.json・tanpyo_{day8,pre}_{p3,p1}_s{種}.txt・tanpyo_hist.parquet(リリース v3-tanpyo-20261015)。
決め 36(2026-10-15・研究 tanpyo_sitb_judge.py・tanpyo_sitb_prod.py): 直前版だけ、状況の印 8 列(ADD8)を足した模型(meta の feats_day)。
  休み明け初戦・休みの日数・中央/他地区から転入初戦・転厩初戦・初めての場 は前日の便で材料表 T から作って tpl_ に書き、
  体重の増減とその大きさは当日の便の公式の増減(v29_gap.feats の bwd)から作る。前日版は今のまま(feats)。
"""
import json
import os
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ASSET = Path(os.environ.get('V3_TANPYO', 'C:/Users/kouki/nankan_ai/v3/tanpyo_prod'))
KEY = ['track', 'race_date', 'race_no']
Q4 = KEY + ['umaban']
OLD9 = ['cy_day_pct', 'cy_self', 'cy_stable', 'cy_int', 'cy_n14', 'cy_gap', 'cy_day_pct_rk', 'cy_stable_rk', 'shinba']
NEW = ['v_h', 'v_w', 'c_h', 'c_w', 'pv_h']
SRC6 = ['g_rest', 'g_nrest', 'i_move', 'l_jra', 'l_nar', 'e_first']  # 材料表 T の元の列(研究 feat_t4 と同じ名前)
PRE6 = ['f_rest1', 'd_rest', 'f_jra1', 'f_nar1', 'f_move1', 'e_first']  # 前日に作れる 6 列
ADD8 = PRE6 + ['f_bwabs', 'o_bwchg']  # 決め 36 の 8 列(研究 tanpyo_sitb_polish.FLX と同じ並び)
TPL = ['tpl_' + c for c in OLD9 + NEW + PRE6] + ['tpl_lay']  # v29 の土台へ書く列(直前版用)
MK = {1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}
TAG = 'tpl 決め30 短評の層'
TAG8 = '決め36 状況の印'  # 当日の便が 8 列入りの模型を使った時に記録へ足す字
LAST_VER = None  # apply_day が最後に使った模型('day8' = 決め 36・'day' = 決め 30 のまま)
LASTD = {}  # 日 → 前日の便の材料の表 D(決め 49 の F3 が読む)


def log0(*a):
    print('[tanpyo]', *a, flush=True)


def load(d=None):
    """模型(種 3 本 × 直前・前日 × 3 着内・1 着)と型の表。無ければ None。"""
    import lightgbm as lgb
    d = Path(d) if d else ASSET
    if not (d / 'tanpyo.json').exists():
        return None
    meta = json.loads((d / 'tanpyo.json').read_text(encoding='utf-8'))
    meta['M'] = {k: [lgb.Booster(model_file=str(d / f)) for f in fs] for k, fs in meta['models'].items()}
    meta['dir'] = d
    meta['gi'] = {g: i for i, g in enumerate(meta['GL'])}
    return meta


def norm(s):
    return unicodedata.normalize('NFKC', s).strip() if isinstance(s, str) else None


def hn(s):
    """馬名の鍵(v8cy_build.norm と同じ = NFKC・空白を除く)。"""
    import re
    if not isinstance(s, str):
        return None
    s = re.sub(r'\s+', '', unicodedata.normalize('NFKC', s))
    return s or None


def grade(s, M):
    """短評 1 つ → (段, 型の番号)。短評が無い = (NaN, NaN)・表に無い言葉 = (0, NaN)。"""
    s = norm(s)
    if s is None:
        return np.nan, np.nan
    g = M['P2G'].get(s)
    return float(M['SC'].get(g, 0)) if g is not None else 0.0, float(M['gi'][g]) if g is not None else np.nan


def _flat(parsed):
    """nar_kb_works の parse_cyokyo の形(全日)→ 調教の行(研究の CSV と同じ列)。"""
    import kb_flatten as kf
    import debut_live as dl
    rows = []
    for p in parsed or []:
        t = dl.TRK.get(str(p.get('race_id') or '')[6:8])
        if t is not None:
            rows += kf.flatten_race(p, t, source='kb')
    return pd.DataFrame(rows, columns=kf.COLUMNS)


def runs_of(C):
    """調教の行 → 1 出走 1 行(馬名・馬の短評)。研究 debut_tp.build と同じく、調教日の正しい行のある出走だけ。"""
    if not len(C):
        return pd.DataFrame(columns=Q4 + ['hn', 'tp_h'])
    C = C.copy()
    C['race_date'] = C.race_date.astype(str).str[:10]
    C['race_no'] = pd.to_numeric(C.race_no, errors='coerce')
    C['umaban'] = pd.to_numeric(C.umaban, errors='coerce')
    C = C.dropna(subset=['race_no', 'umaban'])
    C['race_no'], C['umaban'] = C.race_no.astype(int), C.umaban.astype(int)
    C['work_date'] = C.work_date.astype(str)
    C = C[C.work_date.str.match(r'^\d{4}-\d\d-\d\d$') & (C.work_date < C.race_date)]
    C = C.replace({'': np.nan})
    g = C.groupby(Q4, sort=False)
    R = pd.DataFrame({'hn': g.horse_name.first().map(hn), 'tp_h': g.horse_tanpyo.first()}).reset_index()
    return R


def history(M, parsed, day, H=None, flat=None):
    """前走の元 = 固定の表(研究と同じ行)+ その表の場ごとの最後の日より後の nar_kb_works の出走(今日より前)。
    H・flat は照合用(固定の表のかわり・nar_kb_works のかわりの調教の行)。"""
    H = pd.read_parquet(M['dir'] / 'tanpyo_hist.parquet') if H is None else H
    last = H.groupby('track').race_date.max()
    D = runs_of(_flat(parsed) if flat is None else flat)
    if len(D):
        D = D[(D.race_date < day) & (D.race_date > D.track.map(last).fillna('0000'))].dropna(subset=['hn'])
        D['v'] = [grade(s, M)[0] for s in D.tp_h]
        H = pd.concat([H, D[['hn', 'track', 'race_date', 'race_no', 'umaban', 'v']]], ignore_index=True)
    return H.sort_values(['hn', 'race_date', 'race_no'], kind='mergesort').drop_duplicates(['hn', 'race_date'], keep='last')


def add_feats(D, C, M, H, day):
    """debut_live.feats の表 D(全馬・今の調教の 9 列・tp_w・tp_h・deb)に 段・型・前走の段 を足す。C = 今日の出走表の調教の行。"""
    D = D.copy()
    for c in ('w', 'h'):
        g = [grade(s, M) for s in D['tp_' + c]]
        D['v_' + c] = [a for a, _ in g]
        D['c_' + c] = [b for _, b in g]
    T = runs_of(C)  # 今日の出走表の調教に載った出走(研究の表の行)
    T = T[T.race_date == day]
    p = H[H.race_date < day].groupby('hn').tail(1).set_index('hn').v  # 馬ごとの一つ前
    T['pv_h'] = T.hn.map(p)
    T['race_date'] = T.race_date.astype(str)
    D = D.drop(columns=['pv_h'], errors='ignore').merge(T[Q4 + ['pv_h']], on=Q4, how='left', validate='1:1')
    D['lay'] = ~D.deb.astype(bool)
    return D


def add6(D, T):
    """材料表 T の元の列 → 前日に作れる 6 列(研究 tanpyo_sitb_prod.add8 と同じ式)。T に無い列は空。"""
    D = D.drop(columns=[c for c in SRC6 + PRE6 if c in D.columns])
    t = T.reindex(columns=Q4 + SRC6).copy()
    t['race_date'] = t.race_date.astype(str).str[:10]
    t['race_no'], t['umaban'] = pd.to_numeric(t.race_no).astype(int), pd.to_numeric(t.umaban).astype(int)
    D = D.merge(t.drop_duplicates(Q4), on=Q4, how='left', validate='1:1')
    D['f_rest1'] = (D.g_nrest == 1).astype(float)
    D['d_rest'] = pd.to_numeric(D.g_rest, errors='coerce')
    D['f_jra1'] = (D.l_jra == 1).astype(float)
    D['f_nar1'] = (D.l_nar == 1).astype(float)
    D['f_move1'] = (D.i_move == 1).astype(float)
    D['e_first'] = pd.to_numeric(D.e_first, errors='coerce')
    return D


def bw2(F, bwd):
    """当日の公式の体重の増減 → 体重の 2 列(研究 add8 と同じ)。"""
    F['o_bwchg'] = pd.to_numeric(pd.Series(np.asarray(bwd, float)), errors='coerce').to_numpy(float)
    F['f_bwabs'] = np.abs(F.o_bwchg)
    return F


def _lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sig(z):
    return 1 / (1 + np.exp(-z))


def _p3prime(z, g):
    import debut_live
    return debut_live.p3prime(z, g)


def apply(M, ver, F, p1, p3, g):
    """材料の表 F(行 = 馬・OLD9 + NEW + lay)・土台 p1・p3・レースの番号 g → (p1′, p3′, u3, u1)。層の馬のいないレース・3 頭以下は今のまま。"""
    F = F.reset_index(drop=True)
    p1, p3, g = np.asarray(p1, float), np.asarray(p3, float), np.asarray(g)
    lay = F.lay.to_numpy(bool)
    fe = M.get('feats_' + ver, M['feats'])  # 決め 36: day8 は 8 列入りの模型・day / pre は決め 30 の 15 列
    miss = [c for c in fe if c != 'off3' and c not in F.columns]
    if miss:
        raise KeyError(f'短評の層の材料が無い {miss}')
    A = F.assign(off3=_lg(p3)).reindex(columns=fe).astype(float).to_numpy()
    u3, u1 = np.zeros(len(F)), np.zeros(len(F))
    if lay.any():
        u3[lay] = np.mean([b.predict(A[lay], raw_score=True) for b in M['M'][f'{ver}_p3']], axis=0)
        u1[lay] = np.mean([b.predict(A[lay], raw_score=True) for b in M['M'][f'{ver}_p1']], axis=0)
    _, gi = np.unique(g, return_inverse=True)
    R = gi.max() + 1
    n = np.bincount(gi, minlength=R)
    hl = (np.bincount(gi, lay.astype(float), R) > 0) & (n > 3)
    s = hl[gi]
    q1 = _sig(_lg(p1) + u1)
    q1 = q1 / np.bincount(gi, q1, R)[gi]
    q3 = np.maximum(_sig(_lg(p3) + u3), np.minimum(q1, 0.999))
    out3 = p3.copy()
    if s.any():
        _, g2 = np.unique(gi[s], return_inverse=True)
        out3[s] = _p3prime(_lg(q3[s]), g2)
    return np.where(s, q1, p1), out3, np.where(s, u3, 0.0), np.where(s, u1, 0.0)


def apply_csv(M, csv_path, D, log=log0):
    """前日の表の CSV(勝つ率の直しの後)を直す: p1・p3p(元は p1_tpl0・p3p_tpl0)・rank・mark・tpl_u3・tpl_u1。→ 直したレース数"""
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p1_tpl0' in x.columns:  # 2 度かけない
        log('前日版 済み')
        return 0
    x['race_date'] = x.race_date.astype(str).str[:10]
    x['race_no'], x['umaban'] = x.race_no.astype(int), x.umaban.astype(int)
    F = x[Q4].merge(D[Q4 + OLD9 + NEW + ['lay']], on=Q4, how='left', validate='1:1')
    F['lay'] = F.lay.fillna(True).astype(bool)
    g = x.groupby(KEY, sort=False).ngroup().to_numpy()
    x['p1_tpl0'], x['p3p_tpl0'] = x.p1, x.p3p
    q1, q3, u3, u1 = apply(M, 'pre', F, x.p1.to_numpy(float), x.p3p.to_numpy(float), g)
    x['p1'], x['p3p'], x['tpl_u3'], x['tpl_u1'] = q1, q3, u3, u1
    o = x.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map(MK).fillna('')
    x = x.sort_values(KEY + ['rank'], kind='mergesort')
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    n = int(pd.Series(u3 != 0).groupby(g).any().sum())
    top = lambda c: x.loc[x.groupby(KEY, sort=False)[c].idxmax(), KEY + ['umaban']].set_index(KEY).umaban  # noqa: E731
    log('前日版に足した', n, 'R・外した分 3 着内 幅', round(float(u3[u3 != 0].std()), 4) if n else 0,
        '・本命が替わった', int((top('p3p') != top('p3p_tpl0')).sum()), 'R')
    return n


def apply_day(M, b, p1, p3p):
    """当日の便(v29_gap.day_marks・勝つ率の直しの後): 1 レースの土台の表 b(tpl_ 列)・p1・p3p → (p1′, p3′)。材料が無ければ None。"""
    global LAST_VER
    LAST_VER = None
    base = ['tpl_' + c for c in OLD9 + NEW] + ['tpl_lay']
    if not set(base) <= set(b.columns) or b.tpl_lay.isna().all():
        return None
    six = [f'tpl_{c}' for c in PRE6]
    ver = 'day8' if 'day8_p3' in M['M'] and set(six) <= set(b.columns) else 'day'  # 前日の便が 6 列を書けなかった日は決め 30 のまま(レースの中の空は普通の欠け)
    cs = OLD9 + NEW + (PRE6 if ver == 'day8' else [])
    F = pd.DataFrame({c: pd.to_numeric(b['tpl_' + c], errors='coerce').to_numpy(float) for c in cs})
    if ver == 'day8':
        F = bw2(F, b['bwd'] if 'bwd' in b.columns else np.full(len(b), np.nan))
    F['lay'] = b.tpl_lay.fillna(1).astype(float).to_numpy() > 0
    q1, q3, _, _ = apply(M, ver, F, p1, p3p, np.zeros(len(b), int))
    LAST_VER = ver
    return q1, q3


# ================================================================ 便の入口(v3_daily・第12版の日・勝つ率の直しの後)
def run(day, T, F, csv_path, base_csv, parsed, log=log0):
    import time
    import debut_live as dl
    t0 = time.time()
    M = load()
    if M is None:
        log('模型なし(足さない)')
        return 0
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p1_t10' not in x.columns:
        log('勝つ率の直しの後でない = 足さない(学んだ土台と違う)')
        return 0
    C, src = dl.card_src(day, parsed)
    R = dl.entries(C) if len(C) else pd.DataFrame(columns=Q4 + ['tp_w', 'tp_h'] + dl.TM)
    for c in dl.TM:  # 時計の比べ(初出走の層だけが使う)はこの層では使わない = 空の列で feats の形に合わせる
        if c not in R.columns:
            R[c] = np.nan
    D = dl.feats(x, T, F, R)
    H = history(M, parsed, day)
    D = add_feats(D, C, M, H, day)
    D = add6(D, T)
    LASTD[day] = D  # 決め 49: F3 の材料(寸評の軸・段・型・状況の印・f3_live が読む)
    log('状況の印(決め 36)休み明け初戦', int((D.f_rest1 == 1).sum()), '・日数あり', int(D.d_rest.notna().sum()), '/', len(D),
        '・転入 中央', int((D.f_jra1 == 1).sum()), '・他地区', int((D.f_nar1 == 1).sum()), '・転厩', int((D.f_move1 == 1).sum()),
        '・材料表に無い列', [c for c in SRC6 if c not in T.columns])
    log('出走表の調教', src, len(C), '行・馬の短評あり', int(D.v_h.notna().sum()), '/', len(D), '頭・最終追いの短評あり', int(D.v_w.notna().sum()),
        '・前走の段あり', int(D.pv_h.notna().sum()), '・表に無い言葉', int((D.v_h.notna() & D.c_h.isna()).sum() + (D.v_w.notna() & D.c_w.isna()).sum()),
        '・初出走の層の馬(触らない)', int((~D.lay).sum()), '・前走の元', len(H), '行・秒', round(time.time() - t0))
    n = apply_csv(M, csv_path, D, log=log)
    bp = Path(base_csv)
    if bp.exists():
        vb = pd.read_csv(bp, encoding='utf-8-sig').drop(columns=TPL, errors='ignore')
        vb['race_date'] = vb.race_date.astype(str).str[:10]
        vb['race_no'], vb['umaban'] = vb.race_no.astype(int), vb.umaban.astype(int)
        cs = OLD9 + NEW + (PRE6 if all(c in T.columns for c in SRC6) else [])  # 材料表に元の列が無い日は 6 列を書かない = 当日は決め 30 の模型
        vb = vb.drop(columns=[f'tpl_{c}' for c in PRE6], errors='ignore')
        Z = D[Q4 + cs].rename(columns={c: 'tpl_' + c for c in cs})
        Z['tpl_lay'] = D.lay.astype(float).to_numpy()
        vb = vb.merge(Z, on=Q4, how='left', validate='1:1')
        vb.to_csv(bp, index=False, encoding='utf-8-sig')
        log('直前版へ材料', int(vb.tpl_lay.notna().sum()), '頭・状況の印 6 列', '書いた' if len(cs) > len(OLD9 + NEW) else '書かない(材料表に元の列が無い = 決め 30 のまま)')
    return n


# ================================================================ 手元の照合(研究の材料・予想と比べる)
def check(days=None, cut='2025-09-01'):
    """研究の CSV(debut_tp.load_csv)を今日の出走表に使い、研究の tanpyo_prod_preds(学び直した模型の値)と比べる。
    前走の元は 固定の表を cut より前だけに切り、cut 以後は研究の CSV を nar_kb_works のかわりに足す(本番の足し方の照合)。
    今の調教の 9 列と初出走の印は研究の値を渡す(debut_live の照合で済み)。"""
    sys.path.insert(0, 'C:/Users/kouki/OneDrive/デスクトップ/nankan-ai-v3/src/f5_scripts')
    import debut_tp as dt
    import debut_live as dl
    M = load()
    P = pd.read_parquet('C:/Users/kouki/nankan_ai/v3/tanpyo_prod_preds.parquet')
    P['race_date'] = P.race_date.astype(str).str[:10]
    C = dt.load_csv()
    H0 = pd.read_parquet(M['dir'] / 'tanpyo_hist.parquet')
    Hc = H0[H0.race_date < cut]
    Cc = C[C.race_date.astype(str).str[:10] >= cut]
    if days is None:
        dd = sorted(P.race_date.unique())
        days = dd[::max(1, len(dd) // 60)]
    res, n3 = [], 0
    for day in days:
        Pd = P[P.race_date == day].sort_values(Q4).reset_index(drop=True)
        Cd = C[C.race_date.astype(str).str[:10] == day]
        R = dl.entries(Cd)
        D = Pd[Q4 + OLD9].merge(R[Q4 + ['tp_w', 'tp_h']], on=Q4, how='left', validate='1:1')
        D['deb'] = ~Pd.lay.to_numpy(bool)
        H = history(M, None, day, H=Hc if day >= cut else H0, flat=Cc if day >= cut else C.iloc[0:0])
        D = add_feats(D, Cd, M, H, day)
        for c in NEW + ['tp_w', 'tp_h']:
            a, b = D[c], Pd[c]
            if c.startswith('tp_'):
                same = (a.isna() & b.isna()) | (a.map(norm) == b.map(norm))
            else:
                a, b = a.to_numpy(float), b.to_numpy(float)
                same = (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-9)
            res.append({'day': day, '列': c, '行': len(D), '一致': float(np.mean(same))})
        g = Pd.groupby(KEY, sort=False).ngroup().to_numpy()
        n3 += int((pd.Series(g).value_counts() <= 3).sum())
        for ver in ('day', 'pre'):  # 決め 30 の模型(決め 36 の day8 は check8 で照合)
            F = Pd[Q4 + OLD9 + NEW].copy()
            F['lay'] = Pd.lay.to_numpy(bool)
            q1, q3, u3, u1 = apply(M, ver, F, Pd[f'p1b_{ver}'].to_numpy(float), Pd[f'base_{ver}'].to_numpy(float), g)
            for nm, a, b in (('u3', u3, Pd[f'u3_{ver}']), ('u1', u1, Pd[f'u1_{ver}']), ('p3', q3, Pd[f'p3_{ver}']), ('p1', q1, Pd[f'p1_{ver}'])):
                b = np.where(Pd.hl.to_numpy(bool) | (nm[0] == 'p'), b.to_numpy(float), 0.0)  # 層の馬のいないレースの外した分は 0
                res.append({'day': day, '列': f'{nm}_{ver}', '行': len(Pd), '一致': float(np.mean(np.abs(a - b) <= (1e-9 if nm[0] == 'u' else 1e-6)))})
    Rr = pd.DataFrame(res)
    S = Rr.groupby('列', sort=False).agg(行=('行', 'sum'), 一致=('一致', 'mean'), 最小=('一致', 'min'))
    print(S.to_string())
    print('日', len(days), '・3 頭以下のレース', n3, '・全列の一致の最小', S['最小'].min(), '・一致 1.0 の列', int((S['最小'] == 1).sum()), '/', len(S))
    return Rr



def check8(days=None):
    """決め 36 の直前版: 研究の元の列(feat_t4)を材料表 T のかわりに add6・bw2 へ通し、研究 tanpyo_sitb_prod_preds の 8 列・外した分・率と比べる。
    apply_day(当日の便の 1 レースずつ・tpl_ と bwd から)でも同じ率になるかを見る。"""
    M = load()
    P = pd.read_parquet('C:/Users/kouki/nankan_ai/v3/tanpyo_sitb_prod_preds.parquet')
    P['race_date'] = P.race_date.astype(str).str[:10]
    V = 'C:/Users/kouki/nankan_ai/v3/'
    T = pd.concat([pd.read_parquet(V + f, columns=Q4 + SRC6 + ['o_bwchg']) for f in ('feat_t4_explore.parquet', 'feat_t4_open.parquet')]).drop_duplicates(Q4)
    T['race_date'] = T.race_date.astype(str).str[:10]
    if days is None:
        dd = sorted(P.race_date.unique())
        days = dd[::max(1, len(dd) // 60)]
    res = []
    for day in days:
        Pd = P[P.race_date == day].sort_values(Q4).reset_index(drop=True)
        Td = T[T.race_date == day]
        D = add6(Pd[Q4 + OLD9 + NEW].copy(), Td)
        bwd = Pd[Q4].merge(Td[Q4 + ['o_bwchg']], on=Q4, how='left', validate='1:1').o_bwchg.to_numpy(float)
        D = bw2(D, bwd)
        for c in ADD8:
            a, b = D[c].to_numpy(float), Pd[c].to_numpy(float)
            res.append({'列': c, '行': len(D), '一致': float(np.mean((np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-9)))})
        g = Pd.groupby(KEY, sort=False).ngroup().to_numpy()
        F = D.copy()
        F['lay'] = Pd.lay.to_numpy(bool)
        q1, q3, u3, u1 = apply(M, 'day8', F, Pd.p1b_day.to_numpy(float), Pd.base_day.to_numpy(float), g)
        for nm, a, b in (('u3', u3, Pd.u3_day), ('u1', u1, Pd.u1_day), ('p3', q3, Pd.p3_day), ('p1', q1, Pd.p1_day)):
            b = np.where(Pd.hl.to_numpy(bool) | (nm[0] == 'p'), b.to_numpy(float), 0.0)
            res.append({'列': nm + '_day', '行': len(Pd), '一致': float(np.mean(np.abs(a - b) <= (1e-9 if nm[0] == 'u' else 1e-6)))})
        # 当日の便の道: レースごとに tpl_ と bwd の表 b から apply_day
        Z = D[Q4 + OLD9 + NEW + PRE6].rename(columns={c: 'tpl_' + c for c in OLD9 + NEW + PRE6})
        Z['tpl_lay'] = Pd.lay.astype(float).to_numpy()
        Z['bwd'] = bwd
        ok = []
        for _, ix in Z.groupby(KEY, sort=False).indices.items():
            b = Z.iloc[ix].reset_index(drop=True)
            r = apply_day(M, b, Pd.p1b_day.to_numpy(float)[ix], Pd.base_day.to_numpy(float)[ix])
            ok.append(r is not None and LAST_VER == 'day8' and np.allclose(r[1], q3[ix], atol=1e-9) and np.allclose(r[0], q1[ix], atol=1e-9))
        res.append({'列': 'apply_day = apply', '行': len(ok), '一致': float(np.mean(ok))})
    Rr = pd.DataFrame(res)
    S = Rr.groupby('列', sort=False).agg(行=('行', 'sum'), 一致=('一致', 'mean'), 最小=('一致', 'min'))
    print(S.to_string())
    print('日', len(days), '・全列の一致の最小', S['最小'].min())
    return Rr


if __name__ == '__main__':
    if sys.argv[1] == 'check':
        check(sys.argv[2:] or None)
    elif sys.argv[1] == 'check8':
        check8(sys.argv[2:] or None)
