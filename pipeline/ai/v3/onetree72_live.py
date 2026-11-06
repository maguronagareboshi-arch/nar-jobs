# -*- coding: utf-8 -*-
"""南関 直前版に「一本の木」を 5 割混ぜる(決め 72・研究 nankan-ai-v3 src/f5_scripts/onetree72_judge.py・onetree72_prod.py・
判定 2026-11-06 合格・out/onetree72_judge.md)。

一本の木 = 1 頭 1 行・460 列の LightGBM(3 着内 2400 本・勝ち 800 本・2018-06〜2026-08 で学んだ・種 1)。
- 前日の便(v3_daily・F3 の材料の後): 段 1 の 182 列(t9.table の材料 T のその日の分)を v29 の土台へ 'OT:' + 列名 で書く。
  F3 の 287 列は f3_live が 'F3:' + 列名 で書いた物をそのまま使う(段 1 と値の違う 2 列は 'F3:b_lv'・'F3:g_rest')。
- 当日の便(v29_gap.day_marks・第 23 版の全部の段の後 = 勝つ率の守りの後):
  1. 460 列 → z3 = logit(3/n) + 3 着内の木・z1 = logit(1/n) + 勝ちの木(n = その R の頭数・列は 32 ビットにそろえる)。
     当日の体重 3 列と馬場の得手 3 列は F3 と同じ埋め方(f3_live.day_x と同じ)。
  2. 並び読み u(第 23 版と同じ seq2_live.resid の出力): p1 = sig(z1 + 0.2u) を合計 1・p3 = max(sig(z3 + u), min(p1, 0.999)) を合計 3。
  3. 併せ馬の相手(awase_live の res・mar ÷ SD・重みは一本の木の側の W1・W3 = 判定と同じ作りで学んだ物):
     p1′ = p1 e^{D·W1} を合計 1・p3′ = max(sig(z3 + u + D·W3), min(p1′, 0.999)) を合計 3。
  4. 枠の内外の有利(gate68_live の式): 窓 = 一本の木の側の直しの前の p3(直前の行の meta.ot72.p0・DB に無い R は暗号化の定数の ot72_win.csv)。
     答え・開催日・前の日の結果のそろい(lag)は第 23 版の窓と同じ物を使う。
  5. 勝つ率の守り(p1cap.cap)。
  6. 第 23 版(全部の段の後)と MIX : 1 − MIX(勝つ率は対数・3 着内は logit)→ 勝つ率は合計 1・3 着内は max(·, min(p1, 0.999)) で合計 3 → 勝つ率の守り。
混ぜるのは ON の日から(それより前は一本の木の側を作って meta.ot72.p0 に残すだけ = 窓をためる)、かつ窓の行が第 23 版の窓の COVER 以上ある場だけ。
定数(MIX・CU・WU1・W1・W3・ON・COVER・TAG)は暗号化したリリース v3-consts の consts.json の ot72(公開のコードに数を置かない)。
模型は暗号化したリリース v3-ot72-*(V3_OT72 = 開けた置き場: ot72.json・ot72_y3.txt・ot72_y1.txt)。
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed

ASSET = Path(os.environ.get('V3_OT72', 'C:/Users/kouki/nankan_ai/onetree72_prod/m_2026-09-01'))
PFX, F3P = 'OT:', 'F3:'
KEY = ['track', 'race_date', 'race_no']
Q4 = KEY + ['umaban']
DAYC = ('body_weight', 'o_bwchg', 'f_bwabs')   # 当日の便が埋める列(f3_live.DAYC と同じ)
GOING = {'v8bl:S_g': 'v8bl_S_g', 'v8bl:M_g': 'v8bl_M_g', 'v8bl:D_g': 'v8bl_D_g'}   # f3_live.GOING と同じ
WIN_FILL = 'ot72_win.csv'   # 窓の元の補い(DB に meta.ot72.p0 の無い R・一本の木の側の直しの前の p3)
MIN_N = 5
_C = None


def log0(*a):
    print('[ot72]', *a, flush=True)


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('ot72')
    return _C


def tag():
    return consts()['TAG']


# ------------------------------------------------------------------ 模型
def load(d=None):
    """模型 2 本と列(ot72.json)。無ければ None。"""
    import lightgbm as lgb
    d = Path(d) if d else ASSET
    if not (d / 'ot72.json').exists():
        return None
    m = json.loads((d / 'ot72.json').read_text(encoding='utf-8'))
    m['M'] = {t: lgb.Booster(model_file=str(d / v['file'])) for t, v in m['models'].items()}
    m['c182'] = list(consts()['C182'])
    assert set(m['c182']) <= set(m['cols']) and len(m['cols']) == len(set(m['cols'])), '一本の木の列が定数と合わない'
    for t, b in m['M'].items():
        assert b.num_feature() == len(m['cols']), (t, b.num_feature(), len(m['cols']))
    m['dir'] = d
    return m


def has_cols(M, B):
    """土台に前日の便が書いた 'OT:' と 'F3:' の列がそろっているか。"""
    need = set()
    for c in M['cols']:
        if c in M['c182']:
            need.add(PFX + c)
        elif c.startswith(F3P):
            need.add(c)
        elif c not in DAYC:
            need.add(F3P + c)
    return need <= set(B.columns)


# ------------------------------------------------------------------ 前日の便: 段 1 の 182 列を v29 の土台へ
def run_pre(day, T, base_csv, log=log0):
    """便の入口(v3_daily・F3 の材料の後): T = t9.table の材料(e7.features の表)。→ 書いた頭数(書かなかったら 0)。
    列の並びは暗号化の定数 ot72.C182(前日の便は模型を読まない)。"""
    c182 = list(consts()['C182'])
    x = T.copy()
    x['race_date'] = x.race_date.astype(str).str[:10]
    x = x[x.race_date == str(day)]
    miss = [c for c in c182 if c not in x.columns]
    if miss:
        raise KeyError(f'段 1 の列が無い {miss[:12]}(計 {len(miss)})')
    x['race_no'] = pd.to_numeric(x.race_no).astype(int)
    x['umaban'] = pd.to_numeric(x.umaban).astype(int)
    x = x[Q4 + c182].drop_duplicates(Q4)
    X = x.rename(columns={c: PFX + c for c in c182})
    bp = Path(base_csv)
    vb = pd.read_csv(bp, encoding='utf-8-sig')
    vb['race_date'] = vb.race_date.astype(str).str[:10]
    vb = vb.drop(columns=[c for c in vb.columns if c.startswith(PFX)]).merge(X.assign(_ot=1), on=Q4, how='left', validate='1:1')
    got = int(vb._ot.notna().sum())   # 段 1 の材料と結べた頭数
    vb = vb.drop(columns='_ot')
    fill = vb[[PFX + c for c in c182]].notna().mean()
    vb.to_csv(bp, index=False, encoding='utf-8-sig')
    log('直前版へ一本の木の段 1 の材料', got, '/', len(vb), '頭', len(c182), '列・値のある割合 平均', round(float(fill.mean()), 3),
        '・全部空の列', [c for c in fill.index if fill[c] == 0][:8])
    return got


# ------------------------------------------------------------------ 当日の便
def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-np.asarray(z, float)))


def sum3(p3):
    """合計 3 にそろえる(v29_gap._sum3・t6_base.p3prime と同じ: logit をずらす二分法 [−30, +30]・100 回)。"""
    p = np.clip(np.asarray(p3, float), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    lo, hi = -30.0, 30.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if (1 / (1 + np.exp(-(z + mid)))).sum() < 3 else (lo, mid)
    return 1 / (1 + np.exp(-(z + (lo + hi) / 2)))


def soft(lp, a):
    """研究 awase60_judge.soft と同じ(1 レース分)。"""
    e = np.asarray(lp, float) + np.asarray(a, float)
    w = np.exp(e - e.max())
    return w / w.sum()


def day_x(M, b):
    """1 レースの土台 b(v29_gap.feats の後: bw・bwd・馬場の得手 v8bl_*)→ 木の材料 (n, 460) の 32 ビット。前日の列が無ければ None。"""
    if not has_cols(M, b):
        return None
    c182 = set(M['c182'])
    bwd = pd.to_numeric(b['bwd'], errors='coerce').to_numpy(float) if 'bwd' in b.columns else np.full(len(b), np.nan)
    out = {}
    for c in M['cols']:
        if c in c182:
            v = pd.to_numeric(b[PFX + c], errors='coerce').to_numpy(float)
        elif c.startswith(F3P):
            v = pd.to_numeric(b[c], errors='coerce').to_numpy(float)
        elif c == 'body_weight':
            v = pd.to_numeric(b['bw'], errors='coerce').to_numpy(float) if 'bw' in b.columns else np.full(len(b), np.nan)
        elif c == 'o_bwchg':
            v = bwd
        elif c == 'f_bwabs':
            v = np.abs(bwd)
        else:
            v = pd.to_numeric(b[F3P + c], errors='coerce').to_numpy(float)
            if c in GOING and GOING[c] in b.columns:
                v = np.where(np.isfinite(v), v, pd.to_numeric(b[GOING[c]], errors='coerce').to_numpy(float))
        out[c] = v
    return pd.DataFrame(out)[M['cols']].to_numpy(np.float32)


def tree_z(M, X):
    """→ (z3, z1) = logit(k/n) + 木の値(研究 onetree72_judge.fit と同じ)。"""
    n = len(X)
    z3 = lg(np.full(n, 3.0 / n)) + M['M']['Y3'].predict(X, raw_score=True)
    z1 = lg(np.full(n, 1.0 / n)) + M['M']['Y1'].predict(X, raw_score=True)
    return z3, z1


def chain_pre(z3, z1, u, D):
    """並び読み → 併せ馬の相手(研究 onetree_fit_1106.chain_tree の '18'・'19' と同じ)。→ (p1′, p3′(合計 3)= 枠の直しの前)"""
    C = consts()
    cu, wu1 = float(C['CU']), float(C['WU1'])
    w1, w3 = np.asarray(C['W1'], float), np.asarray(C['W3'], float)
    u = np.asarray(u, float)
    r1 = sig(np.asarray(z1, float) + wu1 * cu * u)
    p1 = r1 / r1.sum()
    zz = np.asarray(z3, float) + cu * u
    D = np.asarray(D, float)
    p1n = soft(np.log(np.clip(p1, 1e-12, 1)), D @ w1)
    p3n = sum3(np.maximum(sig(zz + D @ w3), np.minimum(p1n, 0.999)))
    return p1n, p3n


def chain_post(p1n, p3n, a):
    """枠の内外の有利(研究 chain_tree の '23' と同じ)→ 勝つ率の守り。→ (p1, p3)"""
    import p1cap
    a = np.zeros(len(p1n)) if a is None else np.asarray(a, float)
    p1g = soft(np.log(np.clip(p1n, 1e-12, 1)), a)
    p3g = sig(lg(np.clip(p3n, 1e-9, 1 - 1e-9)) + a)
    return p1cap.cap(p1g, p3g), p3g


def mix(t1, t3, s1, s3):
    """一本の木の側 (t1, t3) と第 23 版 (s1, s3)(どちらも守りの後)を混ぜる(研究 onetree72_judge.mix と同じ)。→ (p1, p3 の合計の前, p3)"""
    import p1cap
    w = float(consts()['MIX'])
    e = np.exp(w * np.log(np.clip(t1, 1e-12, 1)) + (1 - w) * np.log(np.clip(s1, 1e-12, 1)))
    p1 = e / e.sum()
    raw = np.maximum(sig(w * lg(np.clip(t3, 1e-9, 1 - 1e-9)) + (1 - w) * lg(np.clip(s3, 1e-9, 1 - 1e-9))), np.minimum(p1, 0.999))
    p3 = sum3(raw)
    return p1cap.cap(p1, p3), raw, p3


def aw_d(AW, track, rno, nums):
    """併せ馬の相手の材料 D(awase_live.apply と同じ: (res, mar) ÷ SD・相手の行の無い馬は 0)。"""
    import awase_live
    D = np.array([(AW or {}).get((track, int(rno), int(u)), (0.0, 0.0)) for u in nums], float)
    return D / awase_live.SD


# ------------------------------------------------------------------ 一本の木の側の枠の窓
def fill_rows():
    """DB に meta.ot72.p0 の無い頃の一本の木の側の直しの前の p3(手元で作った表・暗号化の定数の ot72_win.csv)。無ければ空。"""
    import sealed
    try:
        p = sealed.path(WIN_FILL)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=Q4 + ['p3'])
    if not Path(p).exists():
        return pd.DataFrame(columns=Q4 + ['p3'])
    x = pd.read_csv(p, dtype={'track': str, 'race_date': str})
    return x.assign(race_no=x.race_no.astype(int), umaban=x.umaban.astype(int), p3=x.p3.astype(float))[Q4 + ['p3']]


def window_rows(marks, fill):
    """直前の行の meta.ot72.p0 → 馬ごとの p3(src = db)。DB に行の無い R は fill(src = fill)。"""
    rows = []
    for r in marks:
        p0 = r.get('p0') or {}
        for n, v in p0.items():
            rows.append((r['track'], str(r['race_date'])[:10], int(r['race_no']), int(n), float(v), 'db'))
    W = pd.DataFrame(rows, columns=Q4 + ['p3', 'src'])
    if fill is not None and len(fill):
        s = fill.merge(W[KEY].drop_duplicates().assign(_db=1), on=KEY, how='left')
        W = pd.concat([W, s[s._db.isna()][Q4 + ['p3']].assign(src='fill')], ignore_index=True)
    return W


def fetch_marks(d0, day):
    import gate68_live
    tq = urllib.parse.quote(','.join(gate68_live.TRACKS))
    return gate68_live._get_all(f'/rest/v1/nar_ai_marks?select=track,race_date,race_no,p0:meta->ot72->p0'
                                f'&model=eq.v3-9&timing=eq.last&track=in.({tq})&race_date=gte.{d0}&race_date=lt.{day}&order=race_date,track,race_no')


def cover(Wt, Wg, day, lag, win):
    """場ごとの窓の埋まり = 一本の木の側の窓の馬 ÷ 第 23 版の窓の馬(同じ 56 日)。"""
    out = {}
    for t in set(Wg.track) | set(Wt.track):
        hi = (pd.Timestamp(day) - pd.Timedelta(days=int(lag.get(t, 1)))).strftime('%Y-%m-%d')
        lo = (pd.Timestamp(hi) - pd.Timedelta(days=win)).strftime('%Y-%m-%d')
        ng = int(((Wg.track == t) & (Wg.race_date >= lo) & (Wg.race_date < hi)).sum())
        nt = int(((Wt.track == t) & (Wt.race_date >= lo) & (Wt.race_date < hi)).sum())
        out[t] = round(nt / ng, 4) if ng else 0.0
    return out


def load_gate(day, G68, marks=None, fill=None, log=log0):
    """便で 1 回: 一本の木の側の枠の表(gate68_live.table の形)。G68 = 第 23 版の表(答え・開催日・lag・窓の行を借りる)。読めなければ例外。"""
    import gate68_live
    win = int(gate68_live.consts()['WIN'])
    d0 = (dt.date.fromisoformat(day) - dt.timedelta(days=win + 1)).isoformat()
    marks = fetch_marks(d0, day) if marks is None else marks
    W = window_rows(marks, fill_rows() if fill is None else fill)
    D = W.merge(G68['ans'], on=Q4, how='inner')
    T = gate68_live.table(D, G68['days'], day, G68['lag'])
    cv = cover(D, G68['W'], day, G68['lag'], win)
    st = {'rows': int(len(D)), 'R': int(D[KEY].drop_duplicates().shape[0]), 'db': int((D.src == 'db').sum()), 'fill': int((D.src == 'fill').sum()),
          'd0': (str(D.race_date.min()) if len(D) else None), 'cover': cv}
    log('一本の木の側の枠の窓', st, '・a', {f'{t}{g}': round(v[0], 3) for (t, g), v in sorted(T.items())})
    return {'T': T, 'lag': G68['lag'], 'st': st, 'cover': cv, 'day': day}


def mixing_on(day, track, GT):
    """その日・その場で混ぜるか(ON の日から・窓の埋まりが COVER 以上)。"""
    C = consts()
    on = str(C.get('ON') or '9999-12-31')
    return str(day) >= on and GT is not None and float(GT['cover'].get(track, 0.0)) >= float(C['COVER'])


def apply_day(M, GT, AW, b, track, rno, u, s1, s3, day):
    """当日の便(v29_gap.day_marks・第 23 版の全部の段の後)。b = feats の後の 1 レース(馬番の順)・(s1, s3) = 第 23 版の最後の率。
    → dict(on, p1, p3raw, p3, meta) か None(材料が無い)。on = False の時は率を変えず meta だけ(窓をためる)。"""
    if M is None or u is None or len(b) < MIN_N:
        return None
    X = day_x(M, b)
    if X is None:
        return None
    nums = b.umaban.astype(int).to_numpy()
    z3, z1 = tree_z(M, X)
    p1n, p3n = chain_pre(z3, z1, u, aw_d(AW, track, rno, nums))
    import gate68_live
    a = gate68_live.race_a(GT, track, nums) if GT is not None else None
    t1, t3 = chain_post(p1n, p3n, a)
    on = mixing_on(day, track, GT) and a is not None
    m = {'tag': tag(), 'm': str(M.get('cut', '')), 'on': bool(on), 'cov': float((GT or {}).get('cover', {}).get(track, 0.0)),
         'p0': {str(int(n)): round(float(x), 6) for n, x in zip(nums, p3n)}}
    if not on:
        return {'on': False, 'meta': m}
    p1, raw, p3 = mix(t1, t3, s1, s3)
    m['s1'] = {str(int(n)): round(float(x), 4) for n, x in zip(nums, s1)}
    m['s3'] = {str(int(n)): round(float(x), 4) for n, x in zip(nums, s3)}
    return {'on': True, 'p1': p1, 'p3raw': raw, 'p3': p3, 'meta': m}
