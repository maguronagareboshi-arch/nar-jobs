"""前日版の勝つ率に 3 着内の率を混ぜる直し(決め 71・研究 nankan-ai-v3 src/f5_scripts/p1mix71_judge.py と同じ式・判定 2026-11-05 合格・ユーザー承認 11/5)。
前日版の最後の段(3 着内の率の温度 決め 69 の後・勝つ率の守り 決め 67-2 の前)で、勝つ率を
  p1′ ∝ exp(B·ln p1 + BETA·logit p3)(レースで合計 1)
にする。3 着内の率・並び・印は動かさない(印の並べ替えは 3 着内の率が先で、勝つ率は同点崩しだけ)。
判定の土台(研究の「今」= 南関 第24版 前日版)は温度の後に勝つ率の守りを通した率なので、混ぜの前にも守りを 1 回通す(研究の予想と差 0 の形)。
その守りの後の勝つ率 = 第24版の勝つ率を p1_pm0 に残す(行の meta.pm71.p1_before = 混ぜる前の勝つ率。下流で混ぜる前の率で学んだ物はこちらを読む)。
5 頭以上のレースだけ(研究の範囲 = 5 頭以上・p3 の最大 0.995)。直前版には掛けない。
定数(B・BETA・TAG)は暗号化したリリース v3-consts の consts.json の pm71(公開のコードに数を置かない)。
"""
import numpy as np

KEY = ['track', 'race_date', 'race_no']
EPS1 = 1e-12   # 研究 p1mix70_judge の lp の切り
EPS3 = 1e-9    # 研究 n1_judge_1031.as_base の z3 の切り
MIN_N = 5      # 研究の範囲(4 頭以下のレースは研究に 0)


def _c():
    import sealed
    return sealed.get('pm71')


def tag():
    return _c()['TAG']


def mix(p1, p3, b, beta):
    """1 レース分の勝つ率 p1 と 3 着内の率 p3 → 混ぜた勝つ率(合計 1・np.ndarray)"""
    lp = np.log(np.clip(np.asarray(p1, float), EPS1, 1))
    p = np.clip(np.asarray(p3, float), EPS3, 1 - EPS3)
    e = b * lp + beta * np.log(p / (1 - p))
    w = np.exp(e - e.max())
    return w / w.sum()


def apply_csv_pre(csv_path, log=print):
    """前日版の表の CSV(温度の後・勝つ率の守りの前)の p1 を混ぜる。混ぜる前(守りの後)の勝つ率は p1_pm0・混ぜたレースは pm71 = 1。→ 混ぜた頭数"""
    import pandas as pd
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p1_pm0' in x.columns:  # 2 度かけない
        log('勝つ率の混ぜ 済み')
        return int(x['pm71'].sum())
    import p1cap
    c = _c()
    b, be = float(c['B']), float(c['BETA'])
    x['pm71'] = 0
    x['p1_new'] = np.nan
    skip = 0
    for _, g in x.groupby(KEY, sort=False):
        p1, p3 = g.p1.to_numpy(float), g.p3p.to_numpy(float)
        p1 = p1cap.cap(p1, p3)                       # 判定の形 = 混ぜの前に守りを 1 回(研究の「今」)
        x.loc[g.index, 'p1'] = p1
        if len(g) < MIN_N or not (np.isfinite(p1).all() and np.isfinite(p3).all()):
            skip += 1
            continue
        x.loc[g.index, 'p1_new'] = mix(p1, p3, b, be)
        x.loc[g.index, 'pm71'] = 1
    x['p1_pm0'] = x.p1
    m = x.pm71 == 1
    x.loc[m, 'p1'] = x.loc[m, 'p1_new']
    x = x.drop(columns=['p1_new'])
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    k = x[m].groupby(KEY, sort=False)
    top = int(sum(int(g.p1.to_numpy().argmax() != g.p1_pm0.to_numpy().argmax()) for _, g in k))
    log('勝つ率の混ぜ 混ぜた', int(m.sum()), '頭', k.ngroups, 'R・混ぜない R', skip, '・勝つ率 1 位が替わった R', top)
    return int(m.sum())
