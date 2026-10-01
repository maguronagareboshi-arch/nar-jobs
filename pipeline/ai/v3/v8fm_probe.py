# -*- coding: utf-8 -*-
"""第 8 版 馬の季節・復調・忘れた頃・厩舎力の見落とし確かめ(学習なし)。決め = out/v8fm_plan.md(変えない)。
見方は src/v8bl_probe.py と同じ(r = Y3 − v7dpre_p3・5 等分・開催日ごとの誤差・年ごとの向き・レース内 1 位)。

  py -3.12 -X utf8 src/v8fm_probe.py

■ 実装の決め(結果を見る前)
  SI = v3/t4_base_2014_2021.parquet の走りごとの SI(南関)。馬 = hk(馬名|生年)。「前」= レースの日より前・SI のある走りだけ。
  直近 5 走 = SI のある前の走りの新しい方から 5 つ(PREREG4 §3-3 の a_ab と同じ)。能力の見込み = その行の a_ab(t4_base)。
  H3 は 320〜410 日前の走り 1 つ以上。H4 は直近 5 走より前・730 日以内 1 つ以上。H5b は 2〜5 走前 1 つ以上。H2 の「過去」は全部の前の走り。
  全 NAR = v7c_run.sources の取消・除外を除いた走り(馬 = hid)。比 = (3 着以内 + 3) ÷ (期待 + 3)。H1b の窓は全部の前(上限なし)。
  調教師 = vc.norm(trainer)。T2〜T4 は自分(この馬)の走りを除く(v8bl と同じ)。条件の中の前の走りが 0 なら欠け。
  T2 のクラスの群 = t4_base の区分 k0(南関の走りだけで比を取る。分子・分母とも南関の走り)。T4 の距離帯 = v8bl.dbin。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_day3 as d3  # noqa: E402
import v7_open as vo  # noqa: E402
import v7c_run as vc  # noqa: E402
import v8bl_probe as bl  # noqa: E402

V3 = Path('C:/Users/kouki/nankan_ai/v3')
REPO = Path(__file__).resolve().parent.parent
MD = REPO / 'out' / 'v8fm_check.md'
JS = REPO / 'out' / 'v8fm_check.json'
KEY = d3.KEY
CUT = '2022-01-01'
BIG = 100000
SEAS = {12: 'w', 1: 'w', 2: 'w', 3: 'p', 4: 'p', 5: 'p', 6: 'u', 7: 'u', 8: 'u', 9: 'a', 10: 'a', 11: 'a'}
LAB = {'H1': '季節の得手(同じ季節の SI − ほかの季節)', 'H1b': '同じ季節の成績(全 NAR・着順)',
       'H2': '暖かくなると動く(3〜6 月のレース: 3〜6 月の SI − 12〜2 月)', 'H3': '昨年の同じ時期(320〜410 日前の SI − 見込み)',
       'H4': '忘れた実力(5 走より前・2 年以内の最高 SI − 見込み)', 'H4b': '2 年の最高 SI − 見込み',
       'H5': '復調(前走の SI − 5 走より前の最高)', 'H5b': '上向き(前走の SI − 2〜5 走前の平均)',
       'H6': '忘れられ度(最後に 3 着以内からの日数)', 'T1': '厩舎の規模(365 日の別の馬の数)',
       'T2': '厩舎 × クラス(比 ÷ 全体)', 'T3': '厩舎 × この場(比 ÷ 全体)', 'T4': '厩舎 × 距離帯(比 ÷ 全体)'}


def si_signals(t):
    """t4_base の行ごとに H1〜H5b を出す(t は hk・dnum の順)。"""
    t = t.sort_values(['hk', 'dnum'], kind='mergesort').reset_index(drop=True)
    out = {k: np.full(len(t), np.nan) for k in ('H1', 'H2', 'H3', 'H4', 'H4b', 'H5', 'H5b')}
    hk = t.hk.to_numpy()
    starts = np.r_[0, np.nonzero(hk[1:] != hk[:-1])[0] + 1, len(t)]
    D = t.dnum.to_numpy()
    S = t.SI.to_numpy(float)
    M = t.month.to_numpy()
    A = t.a_ab.to_numpy(float)
    SE = np.array([SEAS[m] for m in M])
    for a, b in zip(starts[:-1], starts[1:]):
        for i in range(a, b):
            m = (D[a:i] < D[i]) & ~np.isnan(S[a:i])
            if not m.any():
                continue
            idx = np.arange(a, i)[m]
            pd_, ps, pm, pse = D[idx], S[idx], M[idx], SE[idx]
            age = D[i] - pd_
            # H1
            w3 = age <= 1095
            same, oth = w3 & (pse == SE[i]), w3 & (pse != SE[i])
            if same.sum() >= 2 and oth.sum() >= 2:
                out['H1'][i] = ps[same].mean() - ps[oth].mean()
            # H2
            if 3 <= M[i] <= 6:
                sp, wi = (pm >= 3) & (pm <= 6), (pm == 12) | (pm <= 2)
                if sp.sum() >= 2 and wi.sum() >= 2:
                    out['H2'][i] = ps[sp].mean() - ps[wi].mean()
            ab = A[i]
            # H3
            ly = (age >= 320) & (age <= 410)
            if ly.any():
                out['H3'][i] = ps[ly].mean() - ab
            n = len(ps)
            older = np.zeros(n, bool)
            older[:max(n - 5, 0)] = True
            ow = older & (age <= 730)
            if ow.any():
                out['H4'][i] = ps[ow].max() - ab
                out['H5'][i] = ps[-1] - ps[ow].max()
            w2 = age <= 730
            if w2.any():
                out['H4b'][i] = ps[w2].max() - ab
            if n >= 2:
                out['H5b'][i] = ps[-1] - ps[max(n - 5, 0):n - 1].mean()
    for k, v in out.items():
        t[k] = v
    return t


def distinct_count(r, q, days):
    """q の各行について、同じ trainer が [dnum − days, dnum − 1] に走らせた別の hid の数。"""
    s = r[['trainer', 'hid', 'dnum']].dropna().drop_duplicates().sort_values(['trainer', 'hid', 'dnum'])
    nxt = s.groupby(['trainer', 'hid']).dnum.shift(-1)
    st = s.dnum + 1
    en = np.minimum(s.dnum + days, nxt.fillna(np.inf))
    ev = pd.concat([pd.DataFrame({'trainer': s.trainer, 't': st, 'v': 1.0}),
                    pd.DataFrame({'trainer': s.trainer, 't': en + 1, 'v': -1.0})])
    ev = ev[np.isfinite(ev.t)]
    ev['t'] = ev.t.astype(np.int64)
    ev = ev.groupby(['trainer', 't']).v.sum().reset_index().sort_values(['trainer', 't'])
    ev['c'] = ev.groupby('trainer').v.cumsum()
    ev = ev.sort_values('t')
    ok = q.trainer.notna().to_numpy()
    qq = pd.DataFrame({'trainer': q.trainer.to_numpy()[ok], 't': q.dnum.to_numpy()[ok].astype(np.int64),
                       '_i': np.arange(len(q))[ok]}).sort_values('t')
    m = pd.merge_asof(qq, ev[['trainer', 't', 'c']], on='t', by='trainer', allow_exact_matches=True)
    res = np.full(len(q), np.nan)
    res[m._i.to_numpy()] = m.c.fillna(0.0).to_numpy()
    selfr = d3.wsum(r.dropna(subset=['trainer']), ['trainer', 'hid'], ['one'], q, days)[:, 0]
    res = res - (np.nan_to_num(selfr) > 0)
    return res


def ratio(A):
    return (A[:, 0] + 3) / (A[:, 1] + 3)


def trainer_ratio(src, q, cond, days):
    cols = ['t3', 'exp', 'one']
    T = d3.wsum(src, ['trainer'], cols, q, days) - np.nan_to_num(d3.wsum(src, ['trainer', 'hid'], cols, q, days))
    C = d3.wsum(src, ['trainer', cond], cols, q, days) - np.nan_to_num(d3.wsum(src, ['trainer', 'hid', cond], cols, q, days))
    v = ratio(C) / ratio(T)
    v[~(C[:, 2] > 0)] = np.nan
    return v


def main():
    h, races = vc.sources()
    h = h[h.race_date < CUT].copy()
    assert h.race_date.max() < CUT
    r = h[~h.finish_note.isin(d3.CANCEL)].drop_duplicates(KEY + ['umaban']).copy()
    fin = pd.to_numeric(r.finish, errors='coerce')
    r['heads'] = (fin > 0).groupby([r[k] for k in KEY]).transform('sum').astype(float)
    r = r[r.heads > 0].copy()
    fin = pd.to_numeric(r.finish, errors='coerce')
    r['t3'] = ((fin > 0) & (fin <= 3)).astype(float)
    r['exp'] = np.minimum(3, r.heads) / r.heads
    r['one'] = 1.0
    r['dnum'] = d3.dnum_of(r.race_date)
    r['trainer'] = r.trainer.map(lambda x: vc.norm(x) if isinstance(x, str) and x.strip() else None)
    r['seas'] = pd.to_datetime(r.race_date).dt.month.map(SEAS)
    r['dbin'] = bl.dbin(r.distance_m)
    print('走り', len(r), flush=True)

    # 走りごとの SI(南関)
    t = pd.read_parquet(V3 / 't4_base_2014_2021.parquet',
                        columns=KEY + ['runner_number', 'hk', 'SI', 'a_ab', 'k0'])
    t = t.rename(columns={'runner_number': 'umaban'})
    t = vo.nk(t)
    assert t.race_date.max() < CUT
    t['dnum'] = d3.dnum_of(t.race_date)
    t['month'] = pd.to_datetime(t.race_date).dt.month.to_numpy()
    t = si_signals(t)
    print('SI の信号', len(t), flush=True)

    P = vo.nk(pd.read_parquet(V3 / 'v7d_final_preds.parquet'))
    assert P.race_date.max() < CUT
    hq = r[KEY + ['umaban', 'hid', 'distance_m', 'trainer', 'seas', 'dbin']]
    q = P[KEY + ['umaban', 'year', 'n', 'Y3', 'v7dpre_p3']].merge(hq, on=KEY + ['umaban'], how='left', validate='1:1')
    q = q.merge(t[KEY + ['umaban', 'k0', 'H1', 'H2', 'H3', 'H4', 'H4b', 'H5', 'H5b']], on=KEY + ['umaban'],
                how='left', validate='1:1')
    q['dnum'] = d3.dnum_of(q.race_date)
    link = {'hid': float(q.hid.notna().mean()), 'trainer': float(q.trainer.notna().mean()), 'k0': float(q.k0.notna().mean())}
    print('つながり', link, flush=True)
    S = {k: q[k].to_numpy(float) for k in ('H1',)}

    # H1b 同じ季節の成績(全 NAR)
    cols = ['t3', 'exp', 'one']
    Aall = d3.wsum(r, ['hid'], cols, q, BIG)
    As = d3.wsum(r, ['hid', 'seas'], cols, q, BIG)
    v = ratio(As) / ratio(Aall)
    v[~(As[:, 2] > 0)] = np.nan
    S['H1b'] = v
    for k in ('H2', 'H3', 'H4', 'H4b', 'H5', 'H5b'):
        S[k] = q[k].to_numpy(float)

    # H6 最後に 3 着以内からの日数
    tp = r[r.t3 == 1][['hid', 'dnum']].dropna().drop_duplicates().rename(columns={'dnum': 't'}).sort_values('t')
    ok = q.hid.notna().to_numpy()
    qq = pd.DataFrame({'hid': q.hid.to_numpy()[ok], 't': q.dnum.to_numpy()[ok], '_i': np.arange(len(q))[ok]})
    tp['last'] = tp.t
    m = pd.merge_asof(qq.sort_values('t'), tp, on='t', by='hid', allow_exact_matches=False)
    v = np.full(len(q), np.nan)
    v[m._i.to_numpy()] = (m.t - m['last']).to_numpy(float)
    v[v > 730] = np.nan
    S['H6'] = v
    print('H 群', flush=True)

    # 厩舎
    rt = r[r.trainer.notna()].copy()
    S['T1'] = distinct_count(rt, q, 365)
    rn = rt.merge(t[KEY + ['umaban', 'k0']], on=KEY + ['umaban'], how='inner')
    S['T2'] = trainer_ratio(rn, q, 'k0', 730)
    S['T3'] = trainer_ratio(rt, q, 'track', 730)
    S['T4'] = trainer_ratio(rt, q, 'dbin', 730)
    print('T 群', flush=True)

    # ---------------- 確かめ(v8bl_probe と同じ)
    rr = ((q.Y3 - q.v7dpre_p3) * 100).to_numpy(float)
    clu = pd.factorize(q.track.astype(str) + '|' + q.race_date.astype(str))[0]
    rid = pd.factorize(q.track.astype(str) + '|' + q.race_date.astype(str) + '|' + q.race_no.astype(str))[0]
    yr = q.year.to_numpy()
    N = len(q)

    def cse_mean(m):
        x, c = rr[m], clu[m]
        e = x - x.mean()
        s = np.bincount(c, e)
        G = len(np.unique(c))
        return float(np.sqrt(G / (G - 1) * (s ** 2).sum()) / len(x))

    def cse_diff(ma, mb):
        z = np.zeros(N)
        z[ma] = (rr[ma] - rr[ma].mean()) / ma.sum()
        z[mb] = -(rr[mb] - rr[mb].mean()) / mb.sum()
        mm = ma | mb
        s = np.bincount(clu[mm], z[mm])
        G = len(np.unique(clu[mm]))
        return float(np.sqrt(G / (G - 1) * (s ** 2).sum()))

    R = {}
    for name in LAB:
        v = S[name]
        ok = ~np.isnan(v)
        cov = float(ok.mean())
        rk = pd.Series(v[ok]).rank(method='first').to_numpy()
        qb = np.full(N, -1)
        qb[ok] = np.minimum((rk - 1) * 5 // ok.sum(), 4).astype(int)
        bins = []
        for b in range(5):
            mb = qb == b
            bins.append({'n': int(mb.sum()), 'r': float(rr[mb].mean()), 'se2': 2 * cse_mean(mb),
                         'lo': float(np.nanmin(v[mb])), 'hi': float(np.nanmax(v[mb]))})
        top, bot = qb == 4, qb == 0
        diff = float(rr[top].mean() - rr[bot].mean())
        se2 = 2 * cse_diff(top, bot)
        yd = {int(y): float(rr[top & (yr == y)].mean() - rr[bot & (yr == y)].mean()) for y in range(2016, 2022)}
        same = int(sum(np.sign(x) == np.sign(diff) for x in yd.values()))
        T = pd.DataFrame({'rid': rid[ok], 'v': v[ok], 'i': np.nonzero(ok)[0]})
        g = T.groupby('rid').v
        T = T[(g.transform('size') >= 2) & (g.transform('nunique') >= 2)]
        is1 = (T.v == T.groupby('rid').v.transform('max')).to_numpy()
        m1, m0 = np.zeros(N, bool), np.zeros(N, bool)
        m1[T.i.to_numpy()[is1]] = True
        m0[T.i.to_numpy()[~is1]] = True
        d1 = float(rr[m1].mean() - rr[m0].mean())
        s1 = 2 * cse_diff(m1, m0)
        flag = bool(abs(diff) >= 1.0 and abs(diff) > se2 and same >= 5)
        worth = bool(abs(diff) >= 3.0)
        R[name] = {'cov': cov, 'bins': bins, 'diff': diff, 'se2': se2, 'years': yd, 'same': same,
                   'in1': d1, 'in1_se2': s1, 'in1_n': int(m1.sum()), 'flag': flag, 'worth': worth}
        print(name, round(cov, 3), round(diff, 2), round(se2, 2), same, flag, worth, flush=True)
    info = {'rows': N, 'runs': len(r), 'si_rows': len(t), 'link': link, 'mean_r': float(rr.mean())}
    JS.write_text(json.dumps({'info': info, 'res': R}, ensure_ascii=False, indent=1), encoding='utf-8')
    write_md(R, info)


def write_md(R, info):
    fl = [n for n, x in R.items() if x['flag']]
    wo = [n for n, x in R.items() if x['worth']]
    big = max(R, key=lambda n: abs(R[n]['diff']))
    cov = [x['cov'] for x in R.values()]
    L = ['# 馬の季節・復調・忘れた頃・厩舎力の見落とし確かめ(第 8 版の下調べ・学習なし)', '',
         '## 要約', '',
         f'1. 季節の得手・昨年の同じ時期・昔の最高の走り・前走の戻り具合・最後に 3 着に来てからの日数・厩舎の大きさと得意な条件の目安を {len(R)} 個作り、今の予想の見込みと実際の 3 着以内のずれを比べた。',
         f'2. 目安が高い馬ほど見込みより多く(または少なく)来ているなら「見落とし」。決めた線を越えたのは {len(fl)} 個' + (f'({"・".join(n for n in fl)})。' if fl else '。'),
         f'3. ずれが一番大きかったのは {big}「{LAB[big]}」で、上の 2 割と下の 2 割の差 {R[big]["diff"]:+.2f} ポイント(ぶれの幅 ±{R[big]["se2"]:.2f})。',
         f'4. 作って試す値打ちの線(差 3 ポイント以上)を越えたのは {len(wo)} 個' + (f'({"・".join(wo)})。' if wo else '。') + f' 目安が作れた馬の割合は {min(cov):.0%}〜{max(cov):.0%}。',
         '5. ' + ('線を越えた目安は、次に材料として作って試す候補。' if wo else
                  '今の予想は、季節・復調・忘れた頃・厩舎の力をほぼ拾えている(ずれは小さい)。'), '',
         '## 決め(out/v8fm_plan.md・変えていない)と実装の細部', '',
         f'- 対象 = v7d_final_preds.parquet(2016〜2021・南関){info["rows"]:,} 行。r = 実際の 3 着以内 − v7dpre_p3、×100 = ポイント。全体の r の平均 {info["mean_r"]:+.2f}。',
         f'- 全 NAR の走り {info["runs"]:,}(取消・除外を除く・2022 年以降は捨てた)。SI の走り(t4_base・南関){info["si_rows"]:,}。つながり: '
         + '・'.join(f'{k} {v:.1%}' for k, v in info['link'].items()) + '。',
         '- 直近 5 走 = SI のある前の走りの新しい方から 5 つ。能力の見込み = その行の a_ab。H3 は 320〜410 日前 1 走以上・H4/H5 は 5 走より前・730 日以内 1 走以上・H5b は 2〜5 走前 1 走以上・H2 の過去は全部の前の走り・H1b の窓は上限なし。',
         '- T2〜T4 は自分の馬の走りを除く・条件の中の前の走りが 0 なら欠け。T2 のクラスの群 = t4_base の区分 k0(南関の走りだけ)。T1 は自分を除いた別の馬の数。',
         '- 見落とし = |上 − 下| ≥ 1.0 かつ > 2 × 標準誤差(開催 = 場 × 日)かつ 6 年中 5 年以上同じ向き。作って試す値打ち = |上 − 下| ≥ 3.0。', '',
         '## 信号ごとの表', '',
         '| 信号 | カバー率 | 段1(下) | 段2 | 段3 | 段4 | 段5(上) | 上−下 ±2SE | 年ごと(16〜21) | 同じ向き | レース内1位−他 ±2SE | 見落とし | 作って試す値打ち |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for n, x in R.items():
        b = ' | '.join(f'{z["r"]:+.2f}±{z["se2"]:.2f}' for z in x['bins'])
        y = ' '.join(f'{v:+.1f}' for v in x['years'].values())
        L.append(f'| {n} {LAB[n]} | {x["cov"]:.1%} | {b} | {x["diff"]:+.2f} ±{x["se2"]:.2f} | {y} | {x["same"]}/6 | '
                 f'{x["in1"]:+.2f} ±{x["in1_se2"]:.2f} | {"はい" if x["flag"] else "—"} | {"はい" if x["worth"] else "—"} |')
    L += ['', '- 段ごとの頭数と値の範囲は out/v8fm_check.json。', '',
          '## 線を越えた信号', '']
    L += [f'- {n}: 上−下 {R[n]["diff"]:+.2f}(±{R[n]["se2"]:.2f})・{R[n]["same"]}/6 年・カバー率 {R[n]["cov"]:.1%}'
          f'・{"作って試す値打ちあり" if R[n]["worth"] else "値打ちの線には届かず"}' for n in fl] or ['- なし']
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('書いた', MD, flush=True)


if __name__ == '__main__':
    main()
