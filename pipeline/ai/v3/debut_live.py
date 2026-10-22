# -*- coding: utf-8 -*-
"""初出走の層(決め 28・研究 nankan-ai-v3 src/f5_scripts/debut_tp.py・debut_prod_fit.py・ユーザー承認 2026-10-14)。

初出走の馬だけ、追い切りの寸評(最終追い・馬)と、同じコース・脚色の過去 1 年と比べた時計で、前日版と直前版の率を直す。
- 初出走 = l_debut = 1 かつ(2 歳 か 3 歳以上で中央の走り j7_n = 0)。初出走のいないレースは触らない。
- 材料 35 列 = 今の調教の 9 列(CY6・cy_day_pct_rk・cy_stable_rk・shinba)+ has_tp + 寸評の軸 2 × 11 + 時計 5(crs_pct3/5/h・n_w・span)。
- 寸評 = その日の出走表の調教(nar_kb_works・kb_works.install が読んだ分)。追い切りの無い馬は空。
- 時計の比べ = 本番の調教の表 W(CSV + nar_kb_works・v8cy_build.prep_works 済み)の同じコース・脚色・調教日 [レースの日 − 365, レースの日)・
  分かった日(載った出走表のレースの日の最小)≤ レースの日・20 本以上。
- 前日版 = 前日の表(第12版)の p3′ の logit に外した分を足し、下限 min(p1, p3′)・合計 3(4 頭以上のレース)。
- 直前版 = 外した分 dbt_u を v29 の土台へ。当日の便が並び読みの後に足す(v29_gap.day_marks)。
模型 = V3_DEBUT/debut_tp.json・debut_{pre,day}_s{種}.txt(リリース v3-debut-20261014)。
"""
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ASSET = Path(os.environ.get('V3_DEBUT', 'C:/Users/kouki/nankan_ai/v3/debut_prod'))
KEY = ['track', 'race_date', 'race_no']
Q4 = KEY + ['umaban']
CY6 = ['cy_day_pct', 'cy_self', 'cy_stable', 'cy_int', 'cy_n14', 'cy_gap']


def log0(*a):
    print('[debut]', *a, flush=True)


# ================================================================ 寸評の決まり(研究 debut_tp.py の写し・中身は変えない)
AXR = {
    'cond': (['仕上がり良好', '仕上がり万全', '好調', '好気配', 'デキ安定', '万全', '充実', '張り上々', '引き締ま', '元気一杯', '活気', '気合乗',
              '絶好調', '本調子取り戻', '好仕上', '上積み十分', '迫力', '好馬体', '高いレベル', '仕上る', '仕上がる', 'デキ落ちなし', '疲れなく',
              '態勢整う', 'ふっくら', '気配良'],
             ['重め', '仕上がりひと', '途上', '攻め量物足', 'もう一追い欲し', '完調', '絞り切れず', '上積み薄', '割引',
              'ブランク', '精彩を欠', 'デキ今ひと', '本調子には', '息遣い荒', '気配今ひ', '気配今一']),
    'move': (['軽快', 'スムーズ', '上々', '伸び良', '抜群', '鋭く', '鋭さ出', 'キビキビ', '力強', '素軽', '反応良', '手応え十分', '好時計', '時計以上',
              '絶好', '豪快', '躍動', 'ハツラツ', 'シャープ', '小気味', '推進力ある', '脚取り確か', 'スピード感', '伸び目立', '伸び抜群', '動き良',
              '余裕ある動き', '余裕ある手応え', '常に動く', '単走の割に動く', '脚力見せ', '今までにない動き', '動き目立', '重心低い', '突き放す',
              '前走以上', '動きだけは', '時計平凡も伸び良', '動く'],
             ['平凡', '物足り', '不満', '欠く', '欠け', '案外', '見劣', '動き今ひと', '反応ひと', '鈍い', '重苦し', 'バテ', 'ジリ', '要し', 'ズブ',
              '鋭さひと', '粘りひと', '伸びひと', '一本調子', '動かず', '動かぬ']),
    'improve': (['良化', '上昇', '上向', '一変', '持ち直', '復調', '戻る', '更に上', '気配良化'],
                ['さほど良化', '良化度合遅', '上昇味薄', '変わり身無', '前走時ほど', '成長が見えず']),
    'awase': (['先着', '余裕持っての併入', '食い下', '互角', 'アオる', '脚いろで勝', '併入で良', '突き放', '心配な', '心配無', '不安なし'],
              ['遅れ', '見劣り', '追い比べで見']),
    'temper': (['折り合いスムーズ', '落ち着'], ['引っ掛', '気性難', 'ササ', 'モタれ', '頭の高', '頭が高', '頭を上げ', '尻尾', 'フラつ', '若さ',
                                          '落ち着き欲し', '手前替えず', 'ゲート不安', 'ゴール後も緩めず']),
}
FLAG = {'gaik': ['外厩', 'トレセン', 'プール', '牧場'], 'norik': ['乗り込', '乗込', '入念', '丹念', '熱心'],
        'light': ['手控', '軽め', 'セーブ', '軽量']}
AXN = list(AXR) + list(FLAG) + ['concede', 'total']
TP = [p + a for p in ('w_', 'h_') for a in AXN]
TM = ['crs_pct3', 'crs_pct5', 'crs_pcth', 'n_w', 'span']
LASTD = {}  # 日 → 前日の便の材料の表 D(決め 49 の F3 が読む)


def norm(s):
    return unicodedata.normalize('NFKC', s).strip() if isinstance(s, str) else None


def main_clause(s):
    """「A も B」は B だけを読む(いつも・もう は除く)。"""
    t = s.replace('いつも', '##').replace('もう', '%%')
    i = t.rfind('も')
    if 0 < i < len(t) - 1:
        t = t[i + 1:]
    return t.replace('##', 'いつも').replace('%%', 'もう')


def axes(s):
    s = norm(s)
    out = dict.fromkeys(AXN, np.nan)
    if not s:
        return out
    concede = bool(re.search(r'(が|も)$', s)) and not s.endswith('いつも')
    b = main_clause(s) if not concede else s
    for ax, (pos, neg) in AXR.items():
        p = any(w in b for w in pos)
        n = any(w in b for w in neg)
        if ax == 'awase':  # 遅れ + 心配なし/余裕/良化/実戦/追わず は遅れを打ち消す
            if '遅れ' in b and any(w in b for w in ('心配', '不安', '余裕', '良化', '実戦', '追わず', '好時計')):
                n = False
            if '先着' in b and any(w in b for w in ('案外', '平凡', '一応')):
                p = False
        out[ax] = -1.0 if n else (1.0 if p else 0.0)  # 両方ある時は悪い方(「力強さに欠け」)
    for f, ws in FLAG.items():
        out[f] = float(any(w in s for w in ws))
    out['concede'] = float(concede)
    out['total'] = out['cond'] + out['move'] + out['improve'] + out['awase'] + out['temper'] + 0.5 * out['norik'] - 0.5 * out['concede']
    return out


# ================================================================ 材料
def _cls(s):
    import v8cy_build as cb
    return cb.CLS.get(cb.norm(s), np.nan) if isinstance(s, str) else np.nan


TRK = {'10': '大井', '11': '川崎', '12': '船橋', '13': '浦和'}  # t8_forecast.TRK と同じ(race_id の 7〜8 桁目)


def card(parsed, day):
    """race_id ごとの調教(parse_cyokyo の形)→ その日の南関の出走表の調教の行(研究の CSV と同じ列)。"""
    import kb_flatten as kf
    rows = []
    for p in parsed:
        rid = str(p.get('race_id') or '')
        t = TRK.get(rid[6:8])
        if t is None or str(kf.race_date_of(rid, p.get('race_date')))[:10] != day:
            continue
        rows += kf.flatten_race(p, t, source='kb')
    C = pd.DataFrame(rows, columns=kf.COLUMNS)
    return C.apply(lambda s: s.map(lambda v: np.nan if v is None or (isinstance(v, float) and np.isnan(v)) or v == '' else str(v))).astype(object)


def card_src(day, parsed=None):
    """その日の出走表の調教: ① kb_works が読んだ nar_kb_works(便)② 手元の JSON(t8_forecast.JD)③ 調教の CSV(寸評の欄があるとき)。"""
    C = card(parsed, day) if parsed else None
    if C is not None and len(C):
        return C, 'nar_kb_works'
    import t8_forecast as t8
    ps = [json.loads(f.read_text(encoding='utf-8')) for f in sorted(t8.JD.glob(f'{day[:4]}*{day[5:7]}{day[8:10]}.json')) if TRK.get(f.stem[6:8]) and f.stem[12:16] == day[5:7] + day[8:10]]
    C = card(ps, day)
    if len(C):
        return C, 'json'
    import v8cy_build as cy
    P = [pd.read_csv(f, dtype=str, encoding='utf-8-sig') for t in TRK.values() for f in [cy.SRC / f'cyokyo_{t}_{day[:4]}.csv'] if f.exists()]
    C = pd.concat(P, ignore_index=True) if P else pd.DataFrame()
    C = C[C.race_date.astype(str).str[:10] == day] if len(C) else C
    return (C, 'csv') if len(C) and {'horse_tanpyo', 'work_tanpyo'} <= set(C.columns) else (pd.DataFrame(), 'なし')


def entries(C):
    """出走表の調教の行 → 1 頭 1 行(研究 debut_tp.build の出走ごとの部分と同じ): 最終追い・寸評・本数・日数・時計。"""
    C = C.copy()
    C['race_date'] = C.race_date.astype(str).str[:10]
    C['race_no'] = pd.to_numeric(C.race_no, errors='coerce')
    C['umaban'] = pd.to_numeric(C.umaban, errors='coerce')
    C = C.dropna(subset=['race_no', 'umaban'])
    C['race_no'], C['umaban'] = C.race_no.astype(int), C.umaban.astype(int)
    C['work_date'] = C.work_date.astype(str)
    C = C[C.work_date.str.match(r'^\d{4}-\d\d-\d\d$') & (C.work_date < C.race_date)].copy()
    for c in ('t_5f', 't_half', 't_3f'):
        C[c] = pd.to_numeric(C[c], errors='coerce')
    if not len(C):
        return pd.DataFrame(columns=Q4 + ['tp_w', 'tp_h', 'n_w', 'span', 'course', 'cls', 't_5f', 't_half', 't_3f'])
    C['cls'] = C.ashiiro.map(_cls)
    C['fin'] = (C.kind == 'final').astype(int)
    C = C.sort_values(Q4 + ['fin', 'work_date'], kind='mergesort')
    g = C.groupby(Q4, sort=False)
    F = g.tail(1).set_index(Q4)
    wt = C[C.work_tanpyo.notna()].groupby(Q4 + ['work_date']).work_tanpyo.first()
    idx = pd.MultiIndex.from_frame(F.reset_index()[Q4 + ['work_date']])
    R = pd.DataFrame(index=F.index)
    R['tp_w'] = wt.reindex(idx).to_numpy()
    R['tp_h'] = g.horse_tanpyo.first().reindex(F.index).to_numpy()
    R['n_w'] = C.drop_duplicates(Q4 + ['work_date', 'course']).groupby(Q4).size().reindex(F.index).to_numpy(float)
    first = g.work_date.min().reindex(F.index)
    R['span'] = (pd.to_datetime(pd.Series(F.index.get_level_values('race_date'))) - pd.to_datetime(pd.Series(first.to_numpy()))).dt.days.to_numpy(float)
    R['course'], R['cls'] = F.course.to_numpy(), F.cls.to_numpy()
    for c in ('t_5f', 't_half', 't_3f'):
        R[c] = F[c].to_numpy(float)
    return R.reset_index()


def pool(W):
    """調教の表(全馬・全期間)→ 比べの元: 同じ追い切りは 1 本・分かった日 = その追い切りが載った出走表のレースの日の最小。"""
    W = W.copy()
    W['race_date'] = W.race_date.astype(str).str[:10]
    W['work_date'] = W.work_date.astype(str).str[:10]
    if 'cls' not in W.columns:
        W['cls'] = W.ashiiro.map(_cls)
    for c in ('t_5f', 't_half', 't_3f'):
        W[c] = pd.to_numeric(W[c], errors='coerce')
    U = W.drop_duplicates(['horse_name', 'work_date', 'course', 'ashiiro', 't_5f', 't_half', 't_3f']).copy()
    seen = W.groupby(['horse_name', 'work_date', 'course', 'ashiiro']).race_date.min()
    U['sd'] = seen.reindex(pd.MultiIndex.from_frame(U[['horse_name', 'work_date', 'course', 'ashiiro']])).to_numpy()
    U['wd'] = pd.to_datetime(U.work_date).values.astype('datetime64[D]').astype(np.int64)
    U['sdn'] = pd.to_datetime(U.sd).values.astype('datetime64[D]').astype(np.int64)
    return {k: d for k, d in U[U.cls.notna()].groupby(['course', 'cls'])}


def crs_pct(R, Ug):
    R = R.copy()
    R['rd'] = pd.to_datetime(R.race_date).values.astype('datetime64[D]').astype(np.int64)
    for c in ('pct3', 'pct5', 'pcth'):
        R['crs_' + c] = np.nan
    Rq = R[R.cls.notna() & R.course.notna()]
    for (crs, cl, rd), d in Rq.groupby(['course', 'cls', 'rd']):
        P = Ug.get((crs, cl))
        if P is None:
            continue
        m = (P.sdn.to_numpy() <= rd) & (P.wd.to_numpy() < rd) & (P.wd.to_numpy() >= rd - 365)
        for tcol, ocol in (('t_3f', 'crs_pct3'), ('t_5f', 'crs_pct5'), ('t_half', 'crs_pcth')):
            pt = np.sort(P[tcol].to_numpy(float)[m])
            pt = pt[~np.isnan(pt)]
            x = d[tcol].to_numpy(float)
            n = len(pt) - 1  # 自分を 1 本含む(同じ出走表の最終追いは分かった日 ≤ レースの日)
            fast = np.searchsorted(pt, x, 'left').astype(float)
            R.loc[d.index, ocol] = np.where((n >= 20) & ~np.isnan(x), fast / max(n, 1), np.nan)
    return R.drop(columns=['rd'])


def _q4(x):
    x = x.copy()
    x['race_date'] = x.race_date.astype(str).str[:10]
    x['race_no'] = x.race_no.astype(int)
    x['umaban'] = x.umaban.astype(int)
    return x


def feats(x, T, F, R):
    """前日の表 x(全出走馬)+ 材料 T(l_debut・g_age・j7_n・b_young)+ 調教 F(CY6)+ 出走ごとの寸評・時計 R → 1 馬 1 行(初出走の印 deb)。"""
    D = _q4(x[Q4])
    t = _q4(T[Q4 + ['b_young', 'l_debut', 'g_age', 'j7_n']]).drop_duplicates(Q4)
    f = _q4(F[Q4 + CY6]).drop_duplicates(Q4) if F is not None and len(F) else pd.DataFrame(columns=Q4 + CY6)
    D = D.merge(t, on=Q4, how='left', validate='1:1').merge(f, on=Q4, how='left', validate='1:1')
    D = D.sort_values(Q4, kind='mergesort').reset_index(drop=True)
    g = [D[k] for k in KEY]
    D['shinba'] = (D.b_young.fillna(0) % 10 == 1).groupby(g).transform('any').astype(float)  # t8_forecast.add_rk と同じ
    for c in ('cy_day_pct', 'cy_stable'):
        r = D[c].groupby(g).rank(method='average')
        m = D[c].notna().groupby(g).transform('sum')
        D[c + '_rk'] = np.where(D[c].isna(), 0.0, np.where(m > 1, (r - 1) / (m - 1).clip(lower=1), 0.5))
    R = _q4(R) if len(R) else R
    D = D.merge(R[Q4 + ['tp_w', 'tp_h'] + TM], on=Q4, how='left', validate='1:1')
    A = pd.DataFrame([axes(s) for s in D.tp_w]).add_prefix('w_')
    H = pd.DataFrame([axes(s) for s in D.tp_h]).add_prefix('h_')
    D = pd.concat([D, A, H], axis=1)
    D['has_tp'] = (D.tp_w.notna() | D.tp_h.notna()).astype(float)
    D['deb'] = (D.l_debut == 1) & ((D.g_age == 2) | ((D.g_age >= 3) & (D.j7_n.fillna(0) == 0) & (D.race_date >= '2023-12-01')))
    return D


def models(kind):
    import lightgbm as lgb
    meta = json.loads((ASSET / 'debut_tp.json').read_text(encoding='utf-8'))
    return [lgb.Booster(model_file=str(ASSET / f)) for f in meta['models'][kind]], meta['feats']


def resid(D, kind):
    """初出走の行だけ 外した分(種 3 本の raw の平均)・それ以外は NaN。"""
    M, cols = models(kind)
    u = np.full(len(D), np.nan)
    m = D.deb.to_numpy(bool)
    if m.any():
        A = D.loc[m, cols].astype(float).to_numpy()
        u[m] = np.mean([b.predict(A, raw_score=True) for b in M], axis=0)
    return u


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def p3prime(z, g):
    R = g.max() + 1
    lo, hi = np.full(R, -30.0), np.full(R, 30.0)
    for _ in range(100):
        mid = (lo + hi) / 2
        up = np.bincount(g, 1 / (1 + np.exp(-(z + mid[g]))), R) < 3
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    return 1 / (1 + np.exp(-(z + ((lo + hi) / 2)[g])))


def apply_pre(x, D):
    """前日の表 x(第12版)→ 初出走のいるレース(4 頭以上)だけ p3′ = 合計 3(max(sig(logit p3′ + 外した分), min(p1, p3′)))・印を出し直す。
    元の値は p3p_dbt・mark_dbt に残す。外した分は dbt_pre_u(初出走の行だけ)。"""
    x = _q4(x.drop(columns=[c for c in ('dbt_pre_u', 'p3p_dbt', 'mark_dbt') if c in x.columns]))
    x = x.merge(D[Q4 + ['u_pre']].rename(columns={'u_pre': 'dbt_pre_u'}), on=Q4, how='left', validate='1:1')
    x['p3p_dbt'], x['mark_dbt'] = x.p3p, x['mark']
    hd = x.dbt_pre_u.notna().groupby([x[k] for k in KEY]).transform('any').to_numpy()
    big = x.groupby(KEY, sort=False).umaban.transform('size').to_numpy() > 3
    s = hd & big
    if s.any():
        y = x[s]
        g = y.groupby(KEY, sort=False).ngroup().to_numpy()
        b1 = np.minimum(y.p1.to_numpy(float), y.p3p.to_numpy(float))
        q0 = np.maximum(1 / (1 + np.exp(-(lg(y.p3p) + y.dbt_pre_u.fillna(0.0).to_numpy(float)))), b1)
        x.loc[s, 'p3p'] = p3prime(lg(q0), g)
    o = x.sort_values(KEY + ['p3p', 'p1', 'umaban'], ascending=[True, True, True, False, False, True], kind='mergesort')
    x['rank'] = (o.groupby(KEY, sort=False).cumcount() + 1).reindex(x.index)
    x['mark'] = x['rank'].map({1: '◎', 2: '○', 3: '▲', 4: '△', 5: '△'}).fillna('')
    return x


# ================================================================ 便の入口
def run(day, T, F, csv_path, base_csv, parsed, W, log=log0):
    """v3_daily(第12版の日だけ): 前日の表を直し、直前版の外した分 dbt_u を v29 の土台へ。→ 初出走の頭数(足さなかったら 0)。"""
    import time
    t0 = time.time()
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    C, src = card_src(day, parsed)
    R = entries(C) if len(C) else pd.DataFrame(columns=Q4 + ['tp_w', 'tp_h', 'course', 'cls', 't_5f', 't_half', 't_3f'] + TM)
    if len(R):
        R = crs_pct(R, pool(W))
    D = feats(x, T, F, R)
    LASTD[day] = D  # 決め 49: F3 の材料(時計の比べ crs_pct3/5/h・f3_live が読む)
    D['u_pre'], D['u_day'] = resid(D, 'pre'), resid(D, 'day')
    deb = D[D.deb]
    log('初出走', len(deb), '頭', deb[KEY].drop_duplicates().shape[0], 'R・寸評あり', int(deb.has_tp.sum()),
        '・時計の比べあり', int(deb.crs_pct3.notna().sum()), '・出走表の調教', src, len(C), '行', R.shape[0], '頭・秒', round(time.time() - t0))
    if not len(deb):
        return 0
    y = apply_pre(x, D)
    ch = int((y[y['rank'] == 1].set_index(KEY).umaban != _q4(x)[x['rank'] == 1].set_index(KEY).umaban).sum())
    y = y.sort_values(KEY + ['rank'], kind='mergesort')
    y.to_csv(csv_path, index=False, encoding='utf-8-sig')
    log('前日版に足した 外した分 平均', round(float(deb.u_pre.mean()), 4), '幅', round(float(deb.u_pre.std()), 4), '・本命が替わった', ch, 'R')
    bp = Path(base_csv)
    if bp.exists():
        vb = _q4(pd.read_csv(bp, encoding='utf-8-sig').drop(columns=['dbt_u'], errors='ignore'))
        vb = vb.merge(D.loc[D.deb, Q4 + ['u_day']].rename(columns={'u_day': 'dbt_u'}), on=Q4, how='left', validate='1:1')
        vb.to_csv(bp, index=False, encoding='utf-8-sig')
        log('直前版へ外した分 dbt_u', int(vb.dbt_u.notna().sum()), '頭')
    return len(deb)


# ================================================================ 手元の照合(研究の材料・予想と比べる)
def check(days=None):
    """研究の CSV(debut_tp.load_csv)を出走表と比べの元の両方に使い、研究の debut_prod_preds(学び直した模型の値)と比べる。"""
    sys.path.insert(0, 'C:/Users/kouki/OneDrive/デスクトップ/nankan-ai-v3/src/f5_scripts')
    import debut_tp as dt
    P = pd.read_parquet('C:/Users/kouki/nankan_ai/v3/debut_prod_preds.parquet')
    C = dt.load_csv()
    Ug = pool(C)
    if days is None:
        dd = sorted(P[P.deb].race_date.unique())
        days = dd[::max(1, len(dd) // 40)]
    res = []
    for day in days:
        Pd = P[P.race_date == day].copy()
        R = crs_pct(entries(C[C.race_date == day]), Ug)
        R = R.merge(Pd[Q4], on=Q4, how='inner')
        # 前日の表のかわりに研究の行(初出走のいるレースの全馬)・T・F は研究の値をそのまま渡す
        x = Pd[Q4].copy()
        T = Pd[Q4 + ['l_debut', 'g_age', 'j7_n']].assign(b_young=np.where(Pd.shinba == 1, 1, 0))
        D = feats(x, T, Pd[Q4 + CY6], R)
        Z = D[Q4 + ['shinba', 'cy_day_pct_rk', 'cy_stable_rk']].merge(Pd[Q4 + ['shinba', 'cy_day_pct_rk', 'cy_stable_rk']], on=Q4, suffixes=('', '_r'))
        for c in ('cy_day_pct_rk', 'cy_stable_rk'):  # 参考: 順位を自分で数えた値(研究は取消の馬も入れて数える)
            res.append({'day': day, '列': '参考 自分で数えた ' + c, '行': len(Z), '一致': float((np.abs(Z[c] - Z[c + '_r']) <= 1e-9).mean())})
        D = D.drop(columns=['shinba', 'cy_day_pct_rk', 'cy_stable_rk']).merge(Pd[Q4 + ['shinba', 'cy_day_pct_rk', 'cy_stable_rk']], on=Q4)
        D['u_pre'], D['u_day'] = resid(D, 'pre'), resid(D, 'day')
        Y = D.merge(Pd, on=Q4, suffixes=('', '_r'))
        _, cols = models('pre')
        for c in cols + ['deb']:
            a, b = Y[c].to_numpy(float), Y[c + '_r'].to_numpy(float)
            same = (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-9 * np.maximum(1, np.abs(b)))
            res.append({'day': day, '列': c, '行': len(Y), '一致': float(same.mean())})
        m = Y.deb_r.to_numpy(bool)
        for k in ('pre', 'day'):
            res.append({'day': day, '列': 'u_' + k, '行': int(m.sum()),
                        '一致': float((np.abs(Y['u_' + k].to_numpy(float)[m] - Y['u_' + k + '_r'].to_numpy(float)[m]) <= 1e-9).mean())})
        # 前日版の足し方: 研究の土台 p_N を p3p・下限の前の p1 に N_b1 相当(b1_pre ≤ base なので min で同じ)
        xx = Pd[Q4].assign(p3p=Pd.base_pre.to_numpy(), p1=Pd.b1_pre.to_numpy(), mark='', p3=Pd.base_pre.to_numpy())
        y = apply_pre(xx, D[Q4 + ['u_pre']])
        y = y.merge(Pd[Q4 + ['p_pre']], on=Q4)
        res.append({'day': day, '列': 'p_pre(足した後の率)', '行': len(y), '一致': float((np.abs(y.p3p - y.p_pre) <= 1e-6).mean())})
    Rr = pd.DataFrame(res)
    S = Rr.groupby('列', sort=False).agg(行=('行', 'sum'), 一致=('一致', 'min'))
    print(S.to_string())
    print('日', len(days), '・全列の一致の最小', S['一致'].min(), '・一致 1.0 の列', int((S['一致'] == 1).sum()), '/', len(S))
    return Rr


def check_db(days=None):
    """出走表の調教を本番の元(DB nar_kb_works)から作り、研究の CSV の材料と比べる(比べの元は研究の CSV のまま)。読むだけ。"""
    import urllib.parse
    import urllib.request
    import kb_works
    sys.path.insert(0, 'C:/Users/kouki/OneDrive/デスクトップ/nankan-ai-v3/src/f5_scripts')
    import debut_tp as dt
    P = pd.read_parquet('C:/Users/kouki/nankan_ai/v3/debut_prod_preds.parquet')
    P = P[P.deb & (P.race_date >= '2025-09-01')]
    if days is None:
        dd = sorted(P.race_date.unique())
        days = dd[::max(1, len(dd) // 25)]
    C = dt.load_csv()
    Ug = pool(C)
    base, key = kb_works.creds()
    res, Z = [], []
    for day in days:
        q = [('select', kb_works.COLS), ('track', 'in.(' + ','.join(kb_works.TRACKS) + ')'), ('race_date', f'eq.{day}'), ('order', 'race_id,umaban'), ('limit', '5000')]
        req = urllib.request.Request(f'{base}/rest/v1/{kb_works.TABLE}?' + urllib.parse.urlencode(q),
                                     headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai-v3'})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read().decode('utf-8'))
        Rd = crs_pct(entries(card(kb_works.rows_to_parsed(rows), day)), Ug)
        Rc = crs_pct(entries(C[C.race_date == day]), Ug)
        Pd = P[P.race_date == day][Q4]
        a = Pd.merge(_q4(Rd), on=Q4, how='left').merge(_q4(Rc), on=Q4, how='left', suffixes=('', '_c'))
        for s in ('', '_c'):
            for p_ in ('w_', 'h_'):
                a[p_ + 'total' + s] = [axes(v)['total'] for v in a[('tp_w' if p_ == 'w_' else 'tp_h') + s]]
        a['day'] = day
        Z.append(a)
    A = pd.concat(Z, ignore_index=True)
    for c in ['tp_w', 'tp_h', 'w_total', 'h_total'] + TM:
        x, y = A[c], A[c + '_c']
        if c in ('tp_w', 'tp_h'):
            same = (x.isna() & y.isna()) | (x.map(norm) == y.map(norm))
        else:
            x, y = x.to_numpy(float), y.to_numpy(float)
            same = (np.isnan(x) & np.isnan(y)) | (np.abs(x - y) <= 1e-9)
        res.append({'列': c, '初出走': len(A), 'DB にある': int(A[c].notna().sum()), 'CSV にある': int(A[c + '_c'].notna().sum()), '一致': round(float(np.mean(same)), 4)})
    print(pd.DataFrame(res).to_string(index=False))
    bad = A[(A.tp_w.map(norm) != A.tp_w_c.map(norm)) & (A.tp_w.notna() | A.tp_w_c.notna())]
    print('寸評(最終追い)の違いの例\n', bad[['day', 'track', 'race_no', 'umaban', 'tp_w', 'tp_w_c']].head(8).to_string(index=False))
    bad = A[(A.tp_h.map(norm) != A.tp_h_c.map(norm)) & (A.tp_h.notna() | A.tp_h_c.notna())]
    print('寸評(馬)の違いの例\n', bad[['day', 'track', 'race_no', 'umaban', 'tp_h', 'tp_h_c']].head(8).to_string(index=False))
    print('日', len(days), '場ごとの初出走', A.track.value_counts().to_dict())
    return A


if __name__ == '__main__':
    if sys.argv[1] == 'check':
        check(sys.argv[2:] or None)
    elif sys.argv[1] == 'check_db':
        check_db(sys.argv[2:] or None)
