# -*- coding: utf-8 -*-
"""研究(2026-11-04): 他場版 v3n の時計の物差し(k8_si)のクラスの箱に「組」を足すと、日の速さ D_T・SI・予想がどう変わるか。
⛔本番の便・DB・模型は変えない(公開 REST を読むだけ・書き込みなし)。k8_si は書き換えない = main の写しを k8 の名前空間で作る。

  python -X utf8 pipeline/ai/kochi/research_v3n_grp.py work out
A = 今の k8。B = cls_key の地方の級に組の番号(C3-12 → 54_C3-12・3歳-4 → 54_Y3-4・選抜 → -S)を足す。
    前 3 年で 30 R に満たない組の箱は、親の級(54_C3)へ戻す(親も足りなければ今と同じ other)。
学び・試しは research_v3n_baba と同じ(学び 2015-01-01〜2025-10-31・試し 2025-11-01〜最新を 1 回だけ)。
出すもの: 予想の良さの差の表(md・json)・地方の各レースの D_T と級の差(A・B)と SI の差の平均(races.parquet)。
"""
import inspect
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import research_v3n_baba as rb  # noqa: E402

TRACKS = [54] + [j for j in rb.TRACKS if j != 54]
DUMP = {}


def make_cls_b(orig):
    def f(jyo, cls, has_name, ccmin):
        k = orig(jyo, cls, has_name, ccmin)
        if k is None or jyo <= 10:
            return k
        base = re.search(r'_(Y2|Y3|[A-E]\d?)$', k)
        if not base:
            return k
        m = re.search(r'-(\d+)', cls)
        if m:
            return f'{k}-{int(m.group(1))}'
        if '選抜' in cls:
            return k + '-S'
        return k
    return f


def make_km(min_r):
    def km(kc):
        tot = {}
        for k, n in kc.items():
            p = k.split('-')[0]
            tot[p] = tot.get(p, 0) + n
        out = {}
        for k, n in kc.items():
            p = k.split('-')[0]
            if n >= min_r:
                out[k] = k
            elif tot.get(p, 0) >= min_r:
                out[k] = p
            else:
                out[k] = k.split('_')[0] + '_other'
        return out
    return km


def make_dump(tag):
    def dump(R):
        if tag not in DUMP:
            X = R[(R.jyo > 10) & (R.year >= 2015)]
            DUMP[tag] = X[['date', 'jyo', 'race', 'dist', 'cls', 'k0', 'dtk', 'gmode', 'vT', 'bc_T', 'dl_T', 'D_T']].copy()
            print('写し', tag, len(DUMP[tag]), flush=True)
        return R
    return dump


def build(k8, tag, grp):
    src = inspect.getsource(k8.main)
    anchor = "    R['kT'] = [kmaps"
    kml = "            km = {k: (k if n >= MIN_R else k.split('_')[0] + '_other') for k, n in kc.items()}"
    call = "R['k0'] = [cls_key("
    assert src.count(anchor) == 1 and src.count(kml) == 1 and src.count(call) == 1, 'k8.main の差し込み口が無い'
    src = src.replace('def main():', f'def main_{tag}():', 1).replace(anchor, f'    R = _DUMP_{tag}(R)\n' + anchor, 1)
    if grp:
        src = src.replace(kml, "            km = _KM_B(kc)", 1).replace(call, "R['k0'] = [_CLS_B(", 1)
        k8.__dict__['_KM_B'] = make_km(k8.MIN_R)
        k8.__dict__['_CLS_B'] = make_cls_b(k8.cls_key)
    k8.__dict__[f'_DUMP_{tag}'] = make_dump(tag)
    exec(compile(src, k8.__file__, 'exec'), k8.__dict__)
    return k8.__dict__[f'main_{tag}']


def si_diff(da, db):
    c = ['date', 'jyo', 'race', 'umaban', 'SI', 'prior']
    a = pd.read_parquet(da / 'si_all.parquet', columns=c)
    b = pd.read_parquet(db / 'si_all.parquet', columns=c)
    a, b = a[a.jyo.astype(int) > 10], b[b.jyo.astype(int) > 10]
    M = a.merge(b, on=['date', 'jyo', 'race', 'umaban'], suffixes=('_a', '_b'))
    M['dSI'] = M.SI_b - M.SI_a
    M['dprior'] = M.prior_b - M.prior_a
    M['jyo'], M['race'] = M.jyo.astype(int), M.race.astype(int)
    return M.groupby(['date', 'jyo', 'race']).agg(dSI=('dSI', 'mean'), dprior=('dprior', 'mean'), nh=('dSI', 'count'),
                                                  SI_a=('SI_a', 'mean')).reset_index()


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
    main_a, main_b = build(k8, 'a', False), build(k8, 'b', True)
    rng = np.random.default_rng(0)
    preds, rows, info = {}, [], {}
    for j in TRACKS:
        da, db = k9.ALT / f't{j}', k9.ALT / f'g{j}'
        da.mkdir(exist_ok=True)
        k1.KOCHI = j
        k1.OUT, k4.V, k8.V = da, da, da
        k1.main()
        k4.main()
        main_a()
        if db.exists():
            shutil.rmtree(db)
        shutil.copytree(da, db)
        for f in ('si_n.parquet', 'si_all.parquet'):
            (db / f).unlink(missing_ok=True)
        k8.V = db
        main_b()
        if j == TRACKS[0]:
            A, B = DUMP['a'], DUMP['b']
            kb = B[B.jyo == 54].k0.value_counts()
            print('高知の箱 B', kb.head(40).to_dict(), flush=True)
            assert (kb.index.str.match(r'54_C3-\d+')).sum() >= 10, '高知の C3 の組が読めていない'
            X = A.merge(B[['date', 'jyo', 'race', 'k0', 'dl_T', 'D_T']], on=['date', 'jyo', 'race'], suffixes=('_a', '_b'))
            X = X.merge(si_diff(da, db), on=['date', 'jyo', 'race'], how='left')
            X.to_parquet(out / 'races.parquet', index=False)
            info['races'] = len(X)
        TA, cols = k10.load(da)
        TB, colsb = k10.load(db)
        assert cols == colsb, '列が違う'
        pa, ntr = rb.fit_pred(TA, cols)
        pb, _ = rb.fit_pred(TB, cols)
        preds[name[j]] = (rb.race_table(pa), rb.race_table(pb))
        print(name[j], '学び', ntr, '試しレース', len(preds[name[j]][0]), rb.metrics(preds[name[j]][0]), rb.metrics(preds[name[j]][1]), flush=True)
    allA = pd.concat({k: v[0] for k, v in preds.items()}, names=['trk'])
    allB = pd.concat({k: v[1] for k, v in preds.items()}, names=['trk'])
    last = str(allA.index.get_level_values('date').max().date())
    sets = [('試し全体', allA, allB)] + [(k, a, b) for k, (a, b) in preds.items()]
    for lab, a, b in sets:
        n, pt, lo, hi = rb.boot(a, b, rng)
        ma, mb = rb.metrics(a), rb.metrics(b)
        rows.append({'set': lab, 'races': n, **{f'A_{k}': v for k, v in ma.items()}, **{f'B_{k}': v for k, v in mb.items()},
                     **{f'd_{k}': float(x) for k, x in zip(('ll3', 'll1', 'top3', 'topw'), pt)},
                     **{f'lo_{k}': float(x) for k, x in zip(('ll3', 'll1', 'top3', 'topw'), lo)},
                     **{f'hi_{k}': float(x) for k, x in zip(('ll3', 'll1', 'top3', 'topw'), hi)}})
    res = {'test_from': rb.TE_FROM, 'test_last': last, 'train': [rb.TR_FROM, '2025-10-31'], 'rows': rows, 'info': info}
    (out / 'research_v3n_grp.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    L = [f'試し {rb.TE_FROM}〜{last}', '| 組 | R | 3着内 損失 A | B−A [95%] | 1着 損失 A | B−A [95%] | 最上位 3着内 A | B−A [95%] | 最上位 勝率 A | B−A [95%] |',
         '|---|---:|---:|---|---:|---|---:|---|---:|---|']
    for r in rows:
        L.append(f"| {r['set']} | {r['races']} | {r['A_ll3']:.4f} | {r['d_ll3']:+.4f} [{r['lo_ll3']:+.4f}, {r['hi_ll3']:+.4f}] | "
                 f"{r['A_ll1']:.4f} | {r['d_ll1']:+.4f} [{r['lo_ll1']:+.4f}, {r['hi_ll1']:+.4f}] | "
                 f"{r['A_top3'] * 100:.2f}% | {r['d_top3'] * 100:+.2f} [{r['lo_top3'] * 100:+.2f}, {r['hi_top3'] * 100:+.2f}] | "
                 f"{r['A_topw'] * 100:.2f}% | {r['d_topw'] * 100:+.2f} [{r['lo_topw'] * 100:+.2f}, {r['hi_topw'] * 100:+.2f}] |")
    (out / 'research_v3n_grp.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
