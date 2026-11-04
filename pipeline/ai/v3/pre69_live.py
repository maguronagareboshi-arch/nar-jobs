"""前日版の 3 着内の率をなだらかにする直し(決め 69・研究 nankan-ai-v3 src/f5_scripts/pre69_judge.py の apply と同じ・ユーザー承認 2026-11-04)。
前日版の最後の段(枠の内外の有利の直し 決め 68 の後・勝つ率の守り 決め 67-2 の前)で、3 着内の率を p3′ = sig(A·logit p3 + K) にする。
合計 3 に割り直さない(決め 68 と同じ)。勝つ率は動かさない(後ろの勝つ率の守りがそのまま効く)。並びは変わらない(単調な直し)。
判定の土台(研究の「今」)は決め 68 の後に勝つ率の守りを通した率なので、直しの前にも守りを 1 回通す(研究の予想と差 0 になる形)。
直前版には掛けない。定数(A・K・TAG)は暗号化したリリース v3-consts の consts.json の pt69(公開のコードに数を置かない)。
"""
import numpy as np

KEY = ['track', 'race_date', 'race_no']
EPS = 1e-9   # 研究 n1_judge_1031.as_base の z3 と同じ切り


def _c():
    import sealed
    return sealed.get('pt69')


def tag():
    return _c()['TAG']


def temp(p3, a, k):
    """3 着内の率 → 直した率(np.ndarray)"""
    p = np.clip(np.asarray(p3, float), EPS, 1 - EPS)
    return 1 / (1 + np.exp(-(a * np.log(p / (1 - p)) + k)))


def apply_csv_pre(csv_path, log=print):
    """前日版の表の CSV(決め 68 の後・勝つ率の守りの前)の p3p を直す。元の値は p3p_pt0・p1_pt0。→ 直した頭数"""
    import pandas as pd
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p3p_pt0' in x.columns:  # 2 度かけない
        log('3 着内の率の温度 済み')
        return int(len(x))
    import p1cap
    c = _c()
    x['p1_pt0'], x['p3p_pt0'] = x.p1, x.p3p
    for _, g in x.groupby(KEY, sort=False):  # 判定の形 = 直しの前の率で勝つ率の守りを 1 回(研究の「今」)→ 直し → 後ろの段の守り
        x.loc[g.index, 'p1'] = p1cap.cap(g.p1.to_numpy(float), g.p3p.to_numpy(float))
    x['p3p'] = temp(x.p3p.to_numpy(float), float(c['A']), float(c['K']))
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    s = x.groupby(KEY, sort=False).p3p.sum()
    log('3 着内の率の温度 直した', len(x), '頭', s.size, 'R・3 着内の合計の中央', round(float(s.median()), 3))
    return int(len(x))
