# -*- coding: utf-8 -*-
"""南関 直前版の作り直し(決め 77・研究 nankan-ai-v3 src/f5_scripts/dayonpre77_judge.py・dayonpre75_judge.py の day75・fin・add_eb・follow・
判定 2026-11-09 合格・out/dayonpre77_judge.md)= 南関 第28版 直前版 = 第28版 前日版の最後の率 + 当日の情報だけの段。

前日の便(v3_daily)= write_base: 土台の表(DAY_v29_base.csv)に 1 頭ずつ
  D77:n1・D77:n3 = 第28版 前日版の最後の率(preday74_live.apply_csv_pre の後・丸めない)
  D77:up       = 前日の並び読み u_P(seqpre_live の sq_u)
  D77:pnx      = 前日の土台 p_Nx(f10k_bundle.run の直後・debut_live.run の前の 3 着内率 = capture_pnx で控えた値)
  D77:on       = そのレースの前日版の行が meta.pt74.on かつ ver 28 の時だけ 1
  D77:nf       = 前日のそのレースの頭数(取消の割り直しの目印)
  を書く。前日版の表(p1・p3p・印)には触らない。
直前の便(v29_gap.day_marks)= apply_day: 第26版の全部の段の後に 1 段(第26版の率は meta.dp77.s1・s3 に残す)
  ① 並び読みの差 du = u_X − u_P(どちらも無い馬は 0)→ 勝つ率の log に WDU1 倍・3 着内の logit に WDU3 倍 → 合計 1・3 → 守り(研究 fin)
  ② 当日の土台の差 eb = logit p_day − logit p_Nx(どちらかが無い馬は 0)→ 3 着内の logit に WEB 倍 → 合計 3
     → 勝つ率は付いていく × 比^KFOL → 合計 1 → 守り → 3 着内を勝つ率以上にして合計 3(研究 add_eb・follow)
  p_day = 束 f10k の足し分 b19_u を足した直後・並び読みの前の 3 着内率(day_marks がその場で持つ)。
  取消: 残った馬で計算(N・u_P は研究 fin の合計 1・3 で割り直し・p_Nx は前日の頭数より少ない時だけ残った馬で合計 3 にしてから eb)。
第28版にするのは ON の日から・前日版の行が第28版(D77:on)・残った全部の馬に N・p_Nx がある・並び読み u_X と p_day がある・
当日の馬場と残った全部の馬の体重がある時だけ。
ほか(第27版の控えの日・pt74.err・材料の欠け)は第26版のまま(eb = 0 にはしない・わけを meta.dp77.why)。
人気・オッズは材料にも重みにも使わない。定数(WDU1・WDU3・WEB・KFOL・ON・TAG)は暗号化したリリース v3-consts の consts.json の dp77。
"""
import numpy as np
import pandas as pd

P = 'D77:'
COLS = [P + c for c in ('n1', 'n3', 'up', 'pnx', 'on', 'nf')]
Q4 = ['track', 'race_date', 'race_no', 'umaban']
KEY = Q4[:3]
_C = None


def log0(*a):
    print('[dp77]', *a, flush=True)


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('dp77')
    return _C


def tag():
    return consts()['TAG']


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def ln(p):
    return np.log(np.clip(np.asarray(p, float), 1e-12, 1))


def sig(z):
    return 1 / (1 + np.exp(-np.asarray(z, float)))


def sum3(p3):
    import onetree72_live as ot
    return ot.sum3(p3)


def cap(p1, p3):
    import p1cap
    return p1cap.cap(p1, p3)


def fin(o1, o3):
    """研究 fin: 勝つ率 = exp(o1) を合計 1・3 着内 = sig(o3) を勝つ率以上にして合計 3 → 勝つ率の守り。"""
    e = np.exp(np.asarray(o1, float))
    q1 = e / e.sum()
    q3 = sum3(np.maximum(sig(o3), np.minimum(q1, 0.999)))
    return cap(q1, q3), q3


def follow(p1_0, p3_0, p3m, k):
    """研究 follow: 勝つ率を 3 着内率の比^k で付いていかせ → 合計 1 → 守り。"""
    q = np.asarray(p1_0, float) * np.exp(k * np.log(np.clip(p3m, 1e-9, 1) / np.clip(p3_0, 1e-9, 1)))
    return cap(q / q.sum(), p3m)


def race(n1, n3, du, eb, C=None):
    """1 レース(馬番の順)。n1・n3 = 第28版 前日版の最後の率・du・eb = 差。→ (p1, p3) = 第28版 直前版の率(研究 day75 と同じ)。"""
    C = consts() if C is None else C
    du, eb = np.asarray(du, float), np.asarray(eb, float)
    q1, q3 = fin(ln(n1) + float(C['WDU1']) * du, lg(n3) + float(C['WDU3']) * du)
    q3n = sum3(np.maximum(sig(lg(q3) + float(C['WEB']) * eb), np.minimum(q1, 0.999)))
    q1n = follow(q1, q3, q3n, float(C['KFOL']))
    return q1n, sum3(np.maximum(q3n, np.minimum(q1n, 0.999)))


def diffs(up, ux, pnx, pday):
    """du・eb(研究 parts: 無い馬は 0)。"""
    ux = np.asarray(ux, float)
    up = np.asarray(up, float)
    du = np.where(np.isfinite(ux), ux, 0.0) - np.where(np.isfinite(up), up, 0.0)
    eb = lg(pday) - lg(pnx)
    eb = np.where(np.isfinite(np.asarray(pday, float)) & np.isfinite(np.asarray(pnx, float)) & np.isfinite(eb), eb, 0.0)
    return du, eb


# ------------------------------------------------------------------ 前日の便(v3_daily)
def _norm(x):
    x = x.copy()
    x['race_date'] = x.race_date.astype(str).str[:10]
    x['race_no'] = pd.to_numeric(x.race_no).astype(int)
    x['umaban'] = pd.to_numeric(x.umaban).astype(int)
    return x


def capture_pnx(csv_path):
    """f10k_bundle.run の直後(debut_live.run の前)の前日版の表の 3 着内率を控える(読むだけ)。→ DataFrame(Q4 + pnx)"""
    x = _norm(pd.read_csv(csv_path, encoding='utf-8-sig'))
    return x[Q4].assign(pnx=pd.to_numeric(x.p3p, errors='coerce').to_numpy(float))


def write_base(csv_path, base_csv, PT74, pnx, log=log0):
    """前日版の表の最後(第28版 前日版)の率・sq_u・控えた p_Nx・第28版かの印を土台の表に足す(前日版の表は読むだけ)。→ D77:on のレース数"""
    x = _norm(pd.read_csv(csv_path, encoding='utf-8-sig'))
    on = {k for k, m in (PT74 or {}).items() if m.get('on') and int(m.get('ver', 27)) == 28 and not m.get('err')}
    d = x[Q4].copy()
    d[P + 'n1'] = pd.to_numeric(x.p1, errors='coerce').to_numpy(float)
    d[P + 'n3'] = pd.to_numeric(x.p3p, errors='coerce').to_numpy(float)
    d[P + 'up'] = pd.to_numeric(x['sq_u'], errors='coerce').to_numpy(float) if 'sq_u' in x.columns else np.nan
    d[P + 'on'] = [int((t, int(r)) in on) for t, r in zip(d.track, d.race_no)]
    d[P + 'nf'] = d.groupby(KEY).umaban.transform('size').astype(int)
    if pnx is not None:
        d = d.merge(pnx.rename(columns={'pnx': P + 'pnx'}), on=Q4, how='left', validate='1:1')
    else:
        d[P + 'pnx'] = np.nan
    # 前からの列は文字のまま読んで書く(数に読み直すと 1e-16 の丸めが入る = 当日の便の第26版の材料を 1 桁も変えない)
    vb = pd.read_csv(base_csv, encoding='utf-8-sig', dtype=str, keep_default_na=False).drop(columns=COLS, errors='ignore')
    k = _norm(vb[Q4])
    add = k.merge(d[Q4 + COLS].drop_duplicates(Q4), on=Q4, how='left', validate='m:1')
    assert len(add) == len(vb)
    for c in COLS:
        vb[c] = add[c].to_numpy()
    vb['D77:v'] = '29'   # 2026-11-09 決め 67-5: この土台を作った前日の便が第29版(能検の結びの直し入り)= 当日の便はこの印がある時だけ「第29版 直前版」と名乗る
    vb.to_csv(base_csv, index=False, encoding='utf-8-sig')
    n = int(d.drop_duplicates(KEY)[P + 'on'].sum())
    log('(前日) 決め 77 の土台', len(d), '頭・第28版のレース', n, '・p_Nx あり率', round(float(d[P + 'pnx'].notna().mean()), 3))
    return n


# ------------------------------------------------------------------ 直前の便(v29_gap.day_marks・第26版の全部の段の後)
def apply_day(b, day, ux, pday, s1, s3, going=''):
    """b = feats の後の 1 レース(馬番の順・取消を除く・当日の体重 bw)・going = 当日の馬場・ux = 直前の並び読み(seq2_live.resid)・pday = 当日の土台(b19_u の直後)・
    (s1, s3) = 第26版の最後の率。→ dict(on, p1, p3, meta)。on = False の時は率を変えず meta だけ(わけ why)。"""
    C = consts()
    nums = b.umaban.astype(int).to_numpy()
    m = {'tag': C['TAG'], 'on': False}

    def no(why):
        m['why'] = why
        return {'on': False, 'meta': m}
    if str(day) < str(C.get('ON') or '9999-12-31'):
        return no('ON の前')
    if not set(COLS) <= set(b.columns):
        return no('土台に D77 の列が無い')
    g = {c: pd.to_numeric(b[c], errors='coerce').to_numpy(float) for c in COLS}
    if not (g[P + 'on'] == 1).all():
        return no('前日版が第28版でない')
    if ux is None or pday is None:
        return no('並び読みか当日の土台が無い')
    if len(b) < 4:
        return no('4 頭未満')
    if not str(going or '').strip() or 'bw' not in b.columns or not pd.to_numeric(b.bw, errors='coerce').notna().all():
        return no('当日の馬場か体重が無い')   # 研究の p_day は実際の馬場と体重で常に埋まっている = eb を 0 にせず第26版のまま
    n1, n3, pnx = g[P + 'n1'], g[P + 'n3'], g[P + 'pnx']
    if not (np.isfinite(n1).all() and np.isfinite(n3).all() and np.isfinite(pnx).all()):
        return no('前日版の率か p_Nx の欠け')
    nf = int(np.nanmax(g[P + 'nf']))
    if len(b) < nf:   # 取消: p_Nx は残った馬で合計 3 にしてから(N は fin が割り直す)
        pnx = sum3(pnx)
    try:
        du, eb = diffs(g[P + 'up'], ux, pnx, pday)
        p1, p3 = race(n1, n3, du, eb, C)
        if not (np.isfinite(p1).all() and np.isfinite(p3).all() and abs(float(p1.sum()) - 1) < 1e-6 and abs(float(p3.sum()) - 3) < 1e-6
                and (p1 <= p3 + 1e-12).all()):
            raise ValueError('率が数でないか合計が 1・3 でないか勝つ率 > 3 着内')
    except Exception as e:  # noqa: BLE001
        m['err'] = f'{type(e).__name__} {str(e)[:80]}'
        return no('計算が落ちた')
    m['on'] = True
    m['cx'] = int(nf - len(b))   # 取消の頭数
    m['s1'] = {str(int(n)): round(float(v), 4) for n, v in zip(nums, s1)}   # 第26版の最後の率
    m['s3'] = {str(int(n)): round(float(v), 4) for n, v in zip(nums, s3)}
    m['du'] = {str(int(n)): round(float(v), 4) for n, v in zip(nums, du)}
    m['eb'] = {str(int(n)): round(float(v), 4) for n, v in zip(nums, eb)}
    return {'on': True, 'p1': p1, 'p3': p3, 'meta': m}
