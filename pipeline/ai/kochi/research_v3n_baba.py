# -*- coding: utf-8 -*-
"""研究(2026-11-03): 他場版 v3n の場の材料の馬場差 D_T を、サイトの馬場差(cond-stats/v1/baba-hist の d1)に替えると予想が良くなるか。
⛔本番の便・DB は変えない(公開 REST を読むだけ・書き込みなし)。k8_si は書き換えない = main の 1 行の前に差し替えを挟んだ写しを k8 の名前空間で作る。

  python -X utf8 pipeline/ai/kochi/research_v3n_baba.py work out
A = 今の k8(D_T そのまま)・B = SI の式の D_T だけをサイトの d1 に(南関・中央・サイトに無い場日は今のまま。TEN・UP は替えない)。
学び 2015-01-01〜2025-10-31・試し 2025-11-01〜最新を 1 回だけ(k10_offeval.run_from と同じ k3.train の Y1・Y3)。
"""
import inspect
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TRACKS = [30, 36, 46, 47, 48, 50, 54, 55]   # 門別・水沢・金沢・笠松・名古屋・園田・高知・佐賀
NANKAN = {'浦和', '船橋', '大井', '川崎'}
PREFIX = {"門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "金沢": "kanazawa", "笠松": "kasamatsu",
          "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga"}  # cloud/baba.py TRACK2PREFIX から南関を除く
URL = 'https://qgsnsdjvzzeazbazjlwa.supabase.co/storage/v1/object/public/cond-stats/v1/baba-hist/{}.json'
TR_FROM, TE_FROM = '2015-01-01', '2025-11-01'
STAT = {}


def site_d1(jyo_of):
    m = {}
    for nm, pf in PREFIX.items():
        r = requests.get(URL.format(pf), timeout=60)
        r.raise_for_status()
        for d, v in r.json().get('days', {}).items():
            if v.get('d1') is not None:
                m[(d, jyo_of[nm])] = float(v['d1'])
    print('サイトの馬場差 場日', len(m), flush=True)
    return m


def make_swap(S):
    def swap(R):
        key = list(zip(R.date.dt.strftime('%Y-%m-%d'), R.jyo.astype(int)))
        s = pd.Series([S.get(k, np.nan) for k in key], index=R.index)
        tgt = R.jyo.isin({j for _, j in S}) & (R.year >= 2015)
        old = R.D_T.copy()
        both = s.notna() & old.notna()
        dd = R.loc[both].drop_duplicates('dtk')
        STAT['corr_D_T_d1'] = float(np.corrcoef(old[dd.index], s[dd.index])[0, 1])
        STAT['mean_D_T'], STAT['mean_d1'] = float(old[dd.index].mean()), float(s[dd.index].mean())
        STAT['swap_share_target_days'] = float(R.loc[tgt].drop_duplicates('dtk').dtk.isin(set(R.loc[tgt & s.notna(), 'dtk'])).mean())
        STAT['swap_share_target_races'] = float((tgt & s.notna()).sum() / max(tgt.sum(), 1))
        R['D_T'] = np.where(s.notna(), s, old)
        print('差し替え', STAT, flush=True)
        return R
    return swap


def build_b(k8, swap):
    src = inspect.getsource(k8.main)
    anchor = "    R['kT'] = [kmaps"
    assert src.count(anchor) == 1, 'k8.main の差し込み口が無い'
    src = src.replace('def main():', 'def main_b():', 1).replace(anchor, '    R = _SWAP_B(R)\n' + anchor, 1)
    k8.__dict__['_SWAP_B'] = swap
    exec(compile(src, k8.__file__, 'exec'), k8.__dict__)
    return k8.main_b


def fit_pred(T, cols):
    import k3_eval as k3
    tr = T[(T.date >= TR_FROM) & (T.date < TE_FROM) & T.Y3.notna() & T.Y1.notna()]
    te = T[(T.date >= TE_FROM) & T.Y3.notna() & T.Y1.notna()][['date', 'race', 'umaban', 'n', 'Y1', 'Y3']].copy()
    X = T.loc[te.index, cols]
    for y in ('Y3', 'Y1'):
        m = k3.train(tr, y, cols)
        k = 1 if y == 'Y1' else 3
        z = k3.logit(np.minimum(k / te.n.to_numpy(float), 0.99))
        te['p' + y[1]] = 1 / (1 + np.exp(-(z + m.predict(X.astype(float), raw_score=True))))
    return te, len(tr)


def race_table(P):
    P = P.copy()
    g = P.groupby(['date', 'race'])
    P['p1n'] = P.p1 / g.p1.transform('sum')
    p3 = P.p3.clip(1e-6, 1 - 1e-6)
    P['ll3'] = -(P.Y3 * np.log(p3) + (1 - P.Y3) * np.log(1 - p3))
    P['ll1'] = -np.log(P.p1n.clip(1e-9)) * P.Y1
    s = P.sort_values(['date', 'race', 'p3', 'umaban'], ascending=[True, True, False, True], kind='mergesort')
    R = s.groupby(['date', 'race']).agg(ll3=('ll3', 'sum'), nh=('ll3', 'size'), ll1s=('ll1', 'sum'), nw=('Y1', 'sum'),
                                       top3=('Y3', 'first'), topw=('Y1', 'first'))
    R = R[R.nw >= 1]
    R['ll1'] = R.ll1s / R.nw
    return R[['ll3', 'nh', 'll1', 'top3', 'topw']]


def metrics(R):
    return {'ll3': R.ll3.sum() / R.nh.sum(), 'll1': R.ll1.mean(), 'top3': R.top3.mean(), 'topw': R.topw.mean()}


def boot(RA, RB, rng, n=1000):
    J = RA.join(RB, lsuffix='_a', rsuffix='_b', how='inner')
    A = J[[c + '_a' for c in ('ll3', 'nh', 'll1', 'top3', 'topw')]].to_numpy(float)
    B = J[[c + '_b' for c in ('ll3', 'nh', 'll1', 'top3', 'topw')]].to_numpy(float)
    def f(a, b):
        return np.array([b[:, 0].sum() / b[:, 1].sum() - a[:, 0].sum() / a[:, 1].sum(),
                         b[:, 2].mean() - a[:, 2].mean(), b[:, 3].mean() - a[:, 3].mean(), b[:, 4].mean() - a[:, 4].mean()])
    pt = f(A, B)
    bs = np.array([f(A[i], B[i]) for i in (rng.integers(0, len(J), len(J)) for _ in range(n))])
    lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
    return len(J), pt, lo, hi


def main():
    work, out = Path(sys.argv[1]), Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    off = work / 'official'
    import k0_dl
    k0_dl.main([str(off).replace('\\', '/')])
    import k9_official as k9
    k9.O = str(off).replace('\\', '/') + '/'
    k9.ALT = work / 'off'
    k9.build()
    k1, k4, k8 = k9.patch()
    import k10_offeval as k10
    name = {v: k for k, v in k9.JYO.items()}
    S = site_d1(k9.JYO)
    main_b = build_b(k8, make_swap(S))
    rng = np.random.default_rng(0)
    preds, rows, stat = {}, [], {}
    for j in TRACKS:
        da, db = k9.ALT / f't{j}', k9.ALT / f'b{j}'
        da.mkdir(exist_ok=True)
        k1.KOCHI = j
        k1.OUT, k4.V, k8.V = da, da, da
        k1.main()
        k4.main()
        k8.main()
        if db.exists():
            shutil.rmtree(db)
        shutil.copytree(da, db)
        for f in ('si_n.parquet', 'si_all.parquet'):
            (db / f).unlink(missing_ok=True)
        k8.V = db
        STAT.clear()
        main_b()
        stat[name[j]] = dict(STAT)
        TA, cols = k10.load(da)
        TB, colsb = k10.load(db)
        assert cols == colsb, '列が違う'
        pa, ntr = fit_pred(TA, cols)
        pb, _ = fit_pred(TB, cols)
        te = TA[TA.date >= TE_FROM]
        stat[name[j]]['test_n_nonnull_A'] = float(te[[c for c in cols if c.startswith('n_')]].notna().mean().mean())
        stat[name[j]]['ntrain'] = int(ntr)
        RA, RB = race_table(pa), race_table(pb)
        preds[name[j]] = (RA, RB)
        print(name[j], '学び', ntr, '試しレース', len(RA), metrics(RA), metrics(RB), flush=True)
    allA = pd.concat({k: v[0] for k, v in preds.items()}, names=['trk'])
    allB = pd.concat({k: v[1] for k, v in preds.items()}, names=['trk'])
    last = str(allA.index.get_level_values('date').max().date())
    sets = [('試し全体', allA, allB)]
    m10 = allA.index.get_level_values('date') >= '2026-10-01'
    sets.append(('2026-10-01 以降', allA[m10], allB[allB.index.get_level_values('date') >= '2026-10-01']))
    for k, (a, b) in preds.items():
        sets.append((k, a, b))
    for lab, a, b in sets:
        n, pt, lo, hi = boot(a, b, rng)
        ma, mb = metrics(a), metrics(b)
        rows.append({'set': lab, 'races': n, **{f'A_{k}': v for k, v in ma.items()}, **{f'B_{k}': v for k, v in mb.items()},
                     **{f'd_{k}': float(x) for k, x in zip(('ll3', 'll1', 'top3', 'topw'), pt)},
                     **{f'lo_{k}': float(x) for k, x in zip(('ll3', 'll1', 'top3', 'topw'), lo)},
                     **{f'hi_{k}': float(x) for k, x in zip(('ll3', 'll1', 'top3', 'topw'), hi)}})
    res = {'test_from': TE_FROM, 'test_last': last, 'train': [TR_FROM, '2025-10-31'], 'rows': rows, 'swap': stat}
    (out / 'research_v3n_baba.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    L = [f'試し {TE_FROM}〜{last}', '| 組 | R | 3着内 損失 A | B−A [95%] | 1着 損失 A | B−A [95%] | 最上位 3着内 A | B−A [95%] | 最上位 勝率 A | B−A [95%] |',
         '|---|---:|---:|---|---:|---|---:|---|---:|---|']
    for r in rows:
        L.append(f"| {r['set']} | {r['races']} | {r['A_ll3']:.4f} | {r['d_ll3']:+.4f} [{r['lo_ll3']:+.4f}, {r['hi_ll3']:+.4f}] | "
                 f"{r['A_ll1']:.4f} | {r['d_ll1']:+.4f} [{r['lo_ll1']:+.4f}, {r['hi_ll1']:+.4f}] | "
                 f"{r['A_top3'] * 100:.2f}% | {r['d_top3'] * 100:+.2f} [{r['lo_top3'] * 100:+.2f}, {r['hi_top3'] * 100:+.2f}] | "
                 f"{r['A_topw'] * 100:.2f}% | {r['d_topw'] * 100:+.2f} [{r['lo_topw'] * 100:+.2f}, {r['hi_topw'] * 100:+.2f}] |")
    L += ['', '| 場 | D_T と d1 の相関 | D_T 平均 | d1 平均 | 差し替えた場日の割合(2015〜・対象場) | 走りの割合 |', '|---|---:|---:|---:|---:|---:|']
    for k, v in stat.items():
        L.append(f"| {k} | {v.get('corr_D_T_d1', float('nan')):.3f} | {v.get('mean_D_T', float('nan')):+.3f} | {v.get('mean_d1', float('nan')):+.3f} | "
                 f"{v.get('swap_share_target_days', float('nan')):.3f} | {v.get('swap_share_target_races', float('nan')):.3f} |")
    (out / 'research_v3n_baba.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
