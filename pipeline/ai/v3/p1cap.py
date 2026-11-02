"""勝つ率 ≦ 3 着内の率 の守り(決め 67-2・研究 nankan-ai-v3 src/f5_scripts/correct67_2_guard.py の guard と同じ・ユーザー承認 2026-11-01)。
全部の段の後に、勝つ率を 3 着内の率(合計 3 にそろえた後の値)で頭打ちにし、余りを同じレースの頭打ちでない馬へ勝つ率の割合で配る(和を保つ)。
新しい違反が無くなるまで繰り返す。3 着内の率は変えない = 本命と 3 着内の当たりは動かない。
わけ: 最後の段は p3 を p1 以上に上げてから 3 にそろえるので、そろえた後に p3 < p1 に戻る馬が出る(研究で直前版 1 頭・前日版 298 頭 / 13.5 万頭)。
"""
import numpy as np

KEY = ['track', 'race_date', 'race_no']
TAG = '決め67-2 勝つ率の守り'
EPS = 1e-12


def cap(p1, p3, it=50):
    """1 レース分の勝つ率 p1 と 3 着内の率 p3(合計 3 にそろえた後)→ 直した p1(np.ndarray)。"""
    p1 = np.asarray(p1, float).copy()
    p3 = np.asarray(p3, float)
    for _ in range(it):
        o = p1 > p3 + EPS
        if not o.any():
            return p1
        ex = float((p1[o] - p3[o]).sum())
        p1[o] = p3[o]
        free = ~o & (p1 < p3 - EPS)
        if not free.any():
            return p1
        p1[free] *= 1 + ex / float(p1[free].sum())
    return p1


def apply_csv(csv_path, log=print):
    """前日版の表の CSV(全部の段の後)の p1 を直す。元の値は p1_cap0。→ 勝つ率を動かした頭数"""
    import pandas as pd
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    if 'p1_cap0' in x.columns:  # 2 度かけない
        log('勝つ率の守り 済み')
        return int((x.p1 != x.p1_cap0).sum())
    x['p1_cap0'] = x.p1
    for _, g in x.groupby(KEY, sort=False):
        x.loc[g.index, 'p1'] = cap(g.p1.to_numpy(float), g.p3p.to_numpy(float))
    n = int((x.p1 != x.p1_cap0).sum())
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    log('勝つ率の守り', f'勝つ率を動かした馬 {n}')
    return n
