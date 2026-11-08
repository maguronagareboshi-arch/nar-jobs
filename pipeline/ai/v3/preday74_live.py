# -*- coding: utf-8 -*-
"""南関 前日版の作り直し(決め 74・研究 nankan-ai-v3 src/f5_scripts/preday74_judge.py・preday74_prod.py・判定 2026-11-06 合格・
out/preday74_judge.md)= 南関 第27版 前日版 = 第25版 + 前日の一本の木 5 割 + 前日の F3 2 割。

前日の便(v3_daily)の最後の段(勝つ率の守り p1cap の後 = 第25版の最後の率)に 1 段:
  1. 前日の一本の木: 452 列(決め 72 の 460 列から当日の 8 列を外した物)= 土台の 'OT:'(段 1 の 182 列・onetree72_live.run_pre が書く)と
     'F3:'(f3_live.run が書く)→ z3 = logit(3/n) + 3 着内の木・z1 = logit(1/n) + 勝ちの木(onetree72_live.tree_z・32 ビット)。
  2. 一本の木の側の鎖(研究 chain_pre): 前日の並び読み u_P(seqpre_live の sq_u・無い馬は 0)→ p1 = sig(z1 + WU1·CU·u_P) を合計 1・
     p3 = max(sig(z3 + CU·u_P + D·W3), …)(onetree72_live と同じ形・併せ馬の重みは一本の木の側の W1・W3)
     → 枠の内外の有利(lag 1・窓 = 一本の木の側の直しの前の p3 = 前日の行の meta.pt74.p0)→ 勝つ率の守り。
     温度(決め 69)と勝つ率の混ぜ(決め 71)は一本の木の側には通さない(研究がそうなっている)。
  3. 混ぜ(研究 mix_last): 3 着内 = 第25版と logit で MIX : 1 − MIX → max(·, min(第25版の勝つ率, 0.999)) を合計 3。
     勝つ率 = 第25版の勝つ率 × (混ぜた 3 着内 ÷ 第25版の 3 着内)^FOL → 合計 1 → 守り。3 着内 = max(·, min(勝つ率, 0.999)) を合計 3。
  4. 前日の F3(研究 add_f3): q = 種 3 本の確率の平均の logit(279 列・f3_live.qlogit と同じ)。
     勝ち = (1 − WF3)·ln p1 + WF3·(q1 + u_P) → 合計 1・3 着内 = sig((1 − WF3)·logit p3 + WF3·(q3 + u_P)) を max(·, min(p1, 0.999)) で合計 3 → 守り。
1〜4 は 1 つの段。どこかで落ちたら第25版のまま(meta.pt74.err)。ON の日より前は率を変えず meta.pt74.p0 だけ残す(窓をためる)。
人気・オッズは材料にも重みにも使わない。
定数(MIX・CU・WU1・FOL・WF3・W1・W3・ON・COVER・C182・TAG)は暗号化したリリース v3-consts の consts.json の pt74。
模型は暗号化したリリース v3-pt74-*(V3_PT74 = 開けた置き場: ot74.json・ot74_y3.txt・ot74_y1.txt・f3pre.json・f3pre_p{3,1}_s*.txt)。
"""
import json
import os
import sys
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed

import onetree72_live as ot  # noqa: E402  部品を使い回す(tree_z・day_x・sum3・soft・chain_post・aw_d・load_gate・window_rows)

ASSET = Path(os.environ.get('V3_PT74', 'C:/Users/kouki/nankan_ai/preday74_prod/pack'))
KEY = ['track', 'race_date', 'race_no']
Q4 = KEY + ['umaban']
F3P = 'F3:'
MIN_N = 5
MK = ['◎', '○', '▲', '△']
_C = None


def log0(*a):
    print('[pt74]', *a, flush=True)


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('pt74')
    return _C


def tag():
    return consts()['TAG']


# ------------------------------------------------------------------ 模型
def load76(d):
    """決め 76(第28版 前日版): 前日の一本の木 種 1〜3 × 2 本(452 + 調教の元の記録 88 列)。ot76.json が無ければ None。"""
    import lightgbm as lgb
    if not (d / 'ot76.json').exists():
        return None
    m = json.loads((d / 'ot76.json').read_text(encoding='utf-8'))
    m['seedM'] = [{t: lgb.Booster(model_file=str(d / m['models'][f'{t}_s{s}']['file'])) for t in ('Y3', 'Y1')} for s in m['seeds']]
    m['cols'], m['cy'] = list(m['base_cols']), list(m['cy_cols'])
    assert len(m['seeds']) == 3 and len(m['cols']) == 452 and len(m['cy']) == 88, (m['seeds'], len(m['cols']), len(m['cy']))
    for sm in m['seedM']:
        for t, b in sm.items():
            assert b.num_feature() == len(m['cols']) + len(m['cy']), (t, b.num_feature())
    m['ver'] = 28
    import cy76_live
    c = cy76_live.consts()
    m['aw'] = (c['W1'], c['W3'])   # 決め 76 の木の側の併せ馬の重み
    return m


def load(d=None):
    """一本の木 2 本(452 列)と前日の F3 6 本(279 列)。無ければ None。
    ot76.json があれば決め 76 の木(種 3 本の平均 + 88 列)を主にし、決め 74 の木は 88 列の元が無い日の控え(M['alt'])。"""
    import lightgbm as lgb
    d = Path(d) if d else ASSET
    if not (d / 'ot74.json').exists() or not (d / 'f3pre.json').exists():
        return None
    m = json.loads((d / 'ot74.json').read_text(encoding='utf-8'))
    m['M'] = {t: lgb.Booster(model_file=str(d / v['file'])) for t, v in m['models'].items()}
    m['c182'] = list(consts()['C182'])
    m['ver'] = 27
    assert set(m['c182']) <= set(m['cols']) and len(m['cols']) == len(set(m['cols'])), '一本の木の列が定数と合わない'
    assert not set(m['cols']) & set(ot.DAYC) and not set(m['cols']) & set(ot.GOING), '前日の一本の木に当日の列がある'
    for t, b in m['M'].items():
        assert b.num_feature() == len(m['cols']), (t, b.num_feature(), len(m['cols']))
    f = json.loads((d / 'f3pre.json').read_text(encoding='utf-8'))
    f['M'] = {t: [lgb.Booster(model_file=str(d / x)) for x in fs] for t, fs in f['models'].items()}
    for t, bs in f['M'].items():
        assert len(bs) == 3 and all(b.num_feature() == len(f['cols']) for b in bs), (t, len(bs))
    m['F3'] = f
    m['dir'] = d
    m76 = load76(d)
    if m76 is not None:  # 主 = 決め 76・控え = 決め 74(F3 は同じ)
        assert m76['cols'] == m['cols'], '決め 76 の木の 452 列が決め 74 と違う'
        m76.update(c182=m['c182'], F3=f, dir=d, alt=m)
        return m76
    return m


def tree_z(M, X):
    """→ (z3, z1)。決め 76 は種 3 本の z の平均(研究 cyraw76_judge.zavg と同じ)・決め 74 は onetree72_live.tree_z。"""
    if 'seedM' not in M:
        return ot.tree_z(M, X)
    a = [ot.tree_z({'M': sm}, X) for sm in M['seedM']]
    return np.mean([x[0] for x in a], axis=0), np.mean([x[1] for x in a], axis=0)


def tree_x(M, b, cy):
    """452 列(day_x)+ 決め 76 は調教の元の記録 88 列(cy = その日の cy76_live.feats を Q4 で引いた表・無い馬は欠け)。"""
    X = ot.day_x(M, b)
    if X is None or 'cy' not in M:
        return X
    k = pd.MultiIndex.from_arrays([b.track.astype(str), b.race_date.astype(str).str[:10], b.race_no.astype(int), b.umaban.astype(int)])
    C = cy.reindex(k)[M['cy']].to_numpy(np.float32)
    return np.hstack([X, C])


def f3_x(F, b):
    """1 レースの土台 b → 前日の F3 の材料 (n, 279)(f3_live.day_x から当日の列を除いた形)。列が無ければ None。"""
    have = [F3P + c for c in F['cols']]
    if not set(have) <= set(b.columns):
        return None
    X = pd.DataFrame({c: pd.to_numeric(b[F3P + c], errors='coerce').to_numpy(float) for c in F['cols']})
    for c in F.get('f32', []):  # 研究の表で 32 ビットの列は 32 ビットに丸める
        X[c] = X[c].astype(np.float32).astype(float)
    return X[F['cols']].to_numpy(float)


def f3_q(F, X):
    """種 3 本の確率の平均の logit(f3_live.qlogit と同じ・端は 1e-4)→ (q3, q1)。"""
    out = {}
    for t in ('p3', 'p1'):
        q = np.clip(np.mean([m.predict(X) for m in F['M'][t]], axis=0), 1e-4, 1 - 1e-4)
        out[t] = np.log(q / (1 - q))
    return out['p3'], out['p1']


# ------------------------------------------------------------------ 式(研究 preday74_judge と同じ)
def chain_pre(z3, z1, u, D, W=None):
    """前日の並び読み → 併せ馬の相手(onetree72_live.chain_pre と同じ式・定数は pt74)。→ (p1′, p3′(合計 3)= 枠の直しの前)
    W = 一本の木の側の併せ馬の重み (W1, W3)。None は pt74(決め 74 の木)・決め 76 の木は cy76 の W1・W3(木に合わせて学んだ重み)。"""
    C = consts()
    cu, wu1 = float(C['CU']), float(C['WU1'])
    W = (C['W1'], C['W3']) if W is None else W
    w1, w3 = np.asarray(W[0], float), np.asarray(W[1], float)
    u = np.asarray(u, float)
    r1 = ot.sig(np.asarray(z1, float) + wu1 * cu * u)
    p1 = r1 / r1.sum()
    zz = np.asarray(z3, float) + cu * u
    D = np.asarray(D, float)
    p1n = ot.soft(np.log(np.clip(p1, 1e-12, 1)), D @ w1)
    p3n = ot.sum3(np.maximum(ot.sig(zz + D @ w3), np.minimum(p1n, 0.999)))
    return p1n, p3n


def mix(t1, t3, s1, s3):
    """研究 mix_last: (t1, t3) = 一本の木の側(守りの後)・(s1, s3) = 第25版の最後の率。→ (p1, p3)"""
    import p1cap
    C = consts()
    w, k = float(C['MIX']), float(C['FOL'])
    s1, s3 = np.asarray(s1, float), np.asarray(s3, float)
    p3m = ot.sum3(np.maximum(ot.sig(w * ot.lg(np.clip(t3, 1e-9, 1 - 1e-9)) + (1 - w) * ot.lg(np.clip(s3, 1e-9, 1 - 1e-9))), np.minimum(s1, 0.999)))
    q = s1 * np.exp(k * np.log(np.clip(p3m, 1e-9, 1) / np.clip(s3, 1e-9, 1)))
    p1 = p1cap.cap(q / q.sum(), p3m)
    return p1, ot.sum3(np.maximum(p3m, np.minimum(p1, 0.999)))


def add_f3(p1, p3, q3, q1, u):
    """研究 add_f3: 前日の F3 を WF3 の割合で足す。→ (p1, p3)"""
    import p1cap
    wf = float(consts()['WF3'])
    u = np.asarray(u, float)
    o1 = (1 - wf) * np.log(np.clip(p1, 1e-12, 1)) + wf * (np.asarray(q1, float) + u)
    o3 = (1 - wf) * ot.lg(np.clip(p3, 1e-9, 1 - 1e-9)) + wf * (np.asarray(q3, float) + u)
    e = np.exp(o1)
    r1 = e / e.sum()
    r3 = ot.sum3(np.maximum(ot.sig(o3), np.minimum(r1, 0.999)))
    return p1cap.cap(r1, r3), r3


def race_tree(M, b, u, D, a, cy=None):
    """1 レース(馬番の順)の一本の木の側(1・2)。→ dict(p0 = 一本の木の側の直しの前の p3・t1・t3・Xf)。材料が無ければ None。"""
    X = tree_x(M, b, cy)
    Xf = f3_x(M['F3'], b)
    if X is None or Xf is None:
        return None
    z3, z1 = tree_z(M, X)
    p1n, p3n = chain_pre(z3, z1, u, D, M.get('aw'))
    t1, t3 = ot.chain_post(p1n, p3n, a)
    return {'p0': p3n, 't1': t1, 't3': t3, 'Xf': Xf, 'z3': z3, 'z1': z1}


def race_mix(M, r, u, s1, s3):
    """混ぜと前日の F3(3・4)。→ (p1, p3) = 第27版の率"""
    m1, m3 = mix(r['t1'], r['t3'], s1, s3)
    q3, q1 = f3_q(M['F3'], r['Xf'])
    return add_f3(m1, m3, q3, q1, u)


def race(M, b, u, D, a, s1, s3, cy=None):
    """1 レース通し(照合用)。→ dict(p0・p1・p3)か None。"""
    r = race_tree(M, b, u, D, a, cy)
    if r is None:
        return None
    r['p1'], r['p3'] = race_mix(M, r, u, s1, s3)
    return r


# ------------------------------------------------------------------ 一本の木の側の枠の窓(lag 1・前日の行の meta.pt74.p0)
def fetch_marks(d0, day):
    import gate68_live
    tq = urllib.parse.quote(','.join(gate68_live.TRACKS))
    return gate68_live._get_all(f'/rest/v1/nar_ai_marks?select=track,race_date,race_no,p0:meta->pt74->p0'
                                f'&model=eq.v3-9&timing=eq.morning&track=in.({tq})&race_date=gte.{d0}&race_date=lt.{day}&order=race_date,track,race_no')


def load_gate(day, G68, marks=None, log=log0):
    """便で 1 回: 一本の木の側の枠の表。G68 = 第25版の側の朝の表(gate68_live.load(day, 'morning'))の答え・開催日・lag(全部 1)を借りる。"""
    import datetime as dt
    import gate68_live
    win = int(gate68_live.consts()['WIN'])
    d0 = (dt.date.fromisoformat(day) - dt.timedelta(days=win + 1)).isoformat()
    marks = fetch_marks(d0, day) if marks is None else marks
    assert all(int(v) == 1 for v in G68['lag'].values()), ('前日版の窓は lag 1', G68['lag'])
    return ot.load_gate(day, G68, marks=marks, fill=pd.DataFrame(columns=Q4 + ['p3']), log=lambda *a: log('(前日)', *a))


def mixing_on(day, track, GT):
    C = consts()
    return str(day) >= str(C.get('ON') or '9999-12-31') and GT is not None and float(GT['cover'].get(track, 0.0)) >= float(C['COVER'])


# ------------------------------------------------------------------ 便の入口(v3_daily・勝つ率の守りの後)
def apply_csv_pre(M, GT, AW, day, csv_path, base_csv, log=log0, cy=None):
    """前日版の表の CSV(第25版の最後 = 勝つ率の守りの後)を直す: 混ぜたレースの p1・p3p(元は p1_t74・p3p_t74)・rank・mark。
    → {(場, R): meta.pt74}(混ぜたかは meta['on']・どの木かは meta['ver'] = 28 決め 76 / 27 決め 74)。
    cy = その日の調教の元の記録 88 列(cy76_live.feats)。決め 76 の木で cy が空(その日の追い切りの行が 1 本も無い)なら決め 74 の木(第27版)。"""
    if 'cy' in M:
        if cy is None or not len(cy):
            log('(前日) 調教の元の記録が 0 行 = 決め 74 の木(第27版)で作る')
            M = M['alt']
        else:
            cy = cy.assign(race_date=cy.race_date.astype(str).str[:10], race_no=cy.race_no.astype(int), umaban=cy.umaban.astype(int)).drop_duplicates(Q4).set_index(Q4)
            log('(前日) 調教の元の記録', len(cy), '頭・決め 76 の木(第28版)')
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p1_t74' in x.columns:  # 2 度かけない
        raise RuntimeError('決め 74 の段は済み')
    vb = pd.read_csv(base_csv, encoding='utf-8-sig')
    vb['race_date'] = vb.race_date.astype(str).str[:10]
    vb['race_no'] = pd.to_numeric(vb.race_no).astype(int)
    vb['umaban'] = pd.to_numeric(vb.umaban).astype(int)
    vb = vb.drop_duplicates(Q4).set_index(Q4)
    x['p1_t74'], x['p3p_t74'] = x.p1, x.p3p
    out, st = {}, {'on': 0, 'shadow': 0, 'none': 0, 'err': 0}
    for (tr, rd, rno), g in x.groupby(KEY, sort=False):
        g = g.sort_values('umaban', kind='mergesort')
        nums = g.umaban.astype(int).to_numpy()
        if len(g) < MIN_N:
            st['none'] += 1
            continue
        try:
            b = vb.loc[[(tr, str(rd)[:10], int(rno), int(n)) for n in nums]].reset_index()
        except KeyError:
            st['none'] += 1
            continue
        u = pd.to_numeric(g['sq_u'], errors='coerce').to_numpy(float) if 'sq_u' in g.columns else np.zeros(len(g))
        u = np.where(np.isfinite(u), u, 0.0)   # 研究: 並び読みの無い馬は 0
        a = None
        import gate68_live
        if GT is not None:
            a = gate68_live.race_a(GT, tr, nums)
        s1, s3 = g.p1.to_numpy(float), g.p3p.to_numpy(float)
        m = {'tag': tag(), 'ver': int(M['ver']), 'on': False, 'cov': float((GT or {}).get('cover', {}).get(tr, 0.0))}
        try:
            r = race_tree(M, b, u, ot.aw_d(AW, tr, rno, nums), a, cy)
            if r is None:
                st['none'] += 1
                continue
            m['p0'] = {str(int(n)): round(float(v), 6) for n, v in zip(nums, r['p0'])}   # 窓の元(混ぜが落ちても残す)
            on = mixing_on(day, tr, GT) and a is not None
            if on:
                p1, p3 = race_mix(M, r, u, s1, s3)
                if not (np.isfinite(p1).all() and np.isfinite(p3).all() and abs(float(p1.sum()) - 1) < 1e-6 and abs(float(p3.sum()) - 3) < 1e-6
                        and (p1 <= p3 + 1e-12).all()):
                    raise ValueError('率が数でないか合計が 1・3 でないか勝つ率 > 3 着内')
                x.loc[g.index, 'p1'], x.loc[g.index, 'p3p'] = p1, p3
                m['on'] = True
                m['s1'] = {str(int(n)): round(float(v), 4) for n, v in zip(nums, s1)}   # 第25版の最後の率
                m['s3'] = {str(int(n)): round(float(v), 4) for n, v in zip(nums, s3)}
                st['on'] += 1
            else:
                st['shadow'] += 1
        except Exception as e:  # noqa: BLE001  落ちたレースは第25版のまま(p0 が出来ていれば残す)
            x.loc[g.index, 'p1'], x.loc[g.index, 'p3p'] = s1, s3
            m['on'] = False
            m['err'] = f'{type(e).__name__} {str(e)[:80]}'
            st['err'] += 1
        out[(tr, int(rno))] = m
    o = x.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map(dict(enumerate(MK, 1))).fillna('')
    x = x.sort_values(KEY + ['rank'], kind='mergesort')
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    top = lambda c: x.loc[x.groupby(KEY, sort=False)[c].idxmax(), KEY + ['umaban']].set_index(KEY).umaban  # noqa: E731
    log('前日の一本の木 + F3', st, '・本命が替わった', int((top('p3p') != top('p3p_t74')).sum()), 'R')
    return out
