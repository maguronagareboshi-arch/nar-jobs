# -*- coding: utf-8 -*-
"""第 6 版 3 日目(PREREG6 §2・§4-1・§5・§6・§11 の 3 日目): 前の再現 → 段 D → 段 E → 段 F1 → 最終形の格子 → 段 F2 → 当日版
→ 第 5 版・第 4 版の線 → 開ける前の止まりどころ → 記録(§6)。2022-01-01 以降のファイルは開かない(assert)。
t3_*・t4_*・t5_*・t6_base.py は直さずに呼ぶ。

  py -3.12 -X utf8 src/t6_day3.py all     # 上の順に 1 回だけ流す(止まる条件に当たったらそこで止まる)
  py -3.12 -X utf8 src/t6_day3.py md      # out/t6_day3.md を書き直すだけ

■ 決め書に無い細部(この台本で決めた・段の当てはめ外を初めて見る前。見た後は変えない。変えてよいのはバグ直しだけ)
  1. 材料 = v3/feat_t6_explore.parquet を t5_base.load_feat で読む(year・KEY・馬番の順・z1・z3・最大日付 < 2022-01-01 を assert)。
     当てはめ外 = t4_day3.test_frame(2016〜2021 をこの順に)。模型は t4_day3.fit_pred(CACHE = v3/t6_cache に差し替え)。
     土台の 115 列 = v3/t5_grid.json の kept(順もそのまま)。当日 3 列 = t4_day3.FEATS4[6]。
  2. 模型のタグ: 再現 t6_C・段 E t6_E・段 E の列外し t6_E_noh2h/t6_E_noelo(Y3 だけ・p1 は段 E の Y1)・段 F1 t6_F1_{残した段}・
     格子 t6_grid_{残した段}・段 F2 の前 t6_F2pre_{残した段}・段 F2 t6_F2_{残した段}・当日版 t6_day_{残した段}{F2 を残したら F2}。
  3. p3 = t4_day3.finish の値(= max(r3, 同じ組の Y1 の p1)。t3_eval.predict と同じ)。p3′ = t6_base.p3prime(二分法)を
     te の KEY で。レースごとに |合計 − 3| ≤ 1e-9・レース内の順位(同じ値は最小の順位)が p3 と同じを assert。
  4. ◎(第 6 版)= p3′ の大きい順 → p1 の大きい順 → 馬番の小さい順(mergesort)の 1 位。第 5 版・第 4 版・再現は
     t4_day3.metrics・t3_eval.race_table と同じ(p1 → p3 → 馬番)。対数尤度は 1e-6〜1 − 1e-6 に切ってレースあたり(t4_day3.metrics と同じ)。
  5. 前の再現: t4_day3.metrics の win・top3・LL1・LL3 が t5_day3_res.json の stages.rows.C と |差| ≤ 1e-12(第 5 版 3 日目と同じ
     「差 0」の扱い)。◎ の率は整数の平均なので実際は完全一致。
  6. 段の採否: (i) ΔLL3 > 0(丸めない)かつ (ii) ◎ 3 着以内率 ≥ 前 − 0.005。段 D の前 = 再現の値(p3・◎ = p1)。
     段 D の LL3 = 同じ予想の p3′。段 E・F1 の前 = 残した形(段 D を当てたもの)。
  7. 格子: t4_day3.GRID の順に 8 通り。Y1 は LL1 の合計(= レースあたり × R)が最大(同じなら GRID の先)。その p1 で
     p3 = max(r3, p1) → p3′ の LL3 が最大の Y3(同じなら GRID の先)。
  8. 段 F2: 前 = 前日版の最終形の列 + 当日 3 列・後 = + bw_diff(どちらも段の設定 15/500/800)。当日版 = 格子の設定。
  9. 第 5 版・第 4 版の線: v3/t5_day3_preds.parquet の v5pre・v5day・v4pre・v4day。◎ 3 着以内率を t4_day3.metrics で出し
     t5_day3_res.json の line.metrics の top3 と完全一致(==)。(場・日付・R・馬番)・n・Y1・Y3 を te と文字列で完全一致。
     1 番人気は te の pop(同じ行)。
  10. 止まりどころ: 対の差 = レースごとの ◎ の Y3 の差(第 6 版 − 相手)を t3_eval.boot(開催日 2,000 回・seed 0)。
      半幅 h = (上限 − 下限) ÷ 2。見込み(ポイント単位): s = 1.11h ÷ 1.96・① Φ((d − 1.96s) ÷ s)・② Φ((d − 1.96s) ÷ √(s² + 0.3²))。
      止まりどころ = 第 6 版 − 第 5 版の下限 ≤ 0 が前日版・当日版のどちらか。
  11. 記録: 段 0 = p1 1/n・p3 3/n(合計 3 なので p3′ = p3)・◎ = 馬番の小さい馬。年・場・頭数の帯(n 5〜8・9〜12・13〜)・
      レースの種類(l_debut = 1 がいる/それ以外で l_jra か l_nar が 1 がいる/どちらもいない)の 1 番人気との差 =
      1 番人気のいるレースでの(◎ 3 着以内率 − 1 番人気 3 着以内率)。当たり具合の表は帯の左を含む(t5_day3.calib と同じ帯)。
      ◎ が第 5 版と違う = 同じ版(前日/当日)どうしで ◎ の馬番が違うレース。
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_eval  # noqa: E402
import t4_day3  # noqa: E402
import t5_base  # noqa: E402
import t6_base  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
FEAT = V3 / 'feat_t6_explore.parquet'
PREDS5 = V3 / 't5_day3_preds.parquet'
RES5 = V3 / 't5_day3_res.json'
GRID5 = V3 / 't5_grid.json'
PREDS = V3 / 't6_day3_preds.parquet'
RES = V3 / 't6_day3_res.json'
GRID6 = V3 / 't6_grid.json'
MD = REPO / 'out/t6_day3.md'
LEDGER = REPO / 'LEDGER.md'
KEY = t4_day3.KEY
DAY6 = t4_day3.FEATS4[6]
CFG = t4_day3.STAGE_CFG
EVAL = t4_day3.YEARS
BANDS = [(5, 8, '5〜8'), (9, 12, '9〜12'), (13, 99, '13〜')]


def res_load():
    return json.loads(RES.read_text(encoding='utf-8')) if RES.exists() else {}


def res_save(k, v):
    r = res_load()
    r[k] = v
    RES.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding='utf-8')


def ledger(a, b, c):
    with LEDGER.open('a', encoding='utf-8') as f:
        f.write(f'| 3(第 6 版) | {a} | {b} | {c} |\n')


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def setup():
    t4_day3.CACHE = V3 / 't6_cache'
    d = t5_base.load_feat(FEAT)
    assert d.race_date.max() < '2022-01-01'
    return d, t4_day3.test_frame(d)


def p3p(te, p3):
    q, _, dl, g = t6_base.p3prime(te[KEY].assign(_p3=p3), '_p3')
    R = g.max() + 1
    assert np.abs(np.bincount(g, q, R) - 3).max() <= 1e-9
    ra = pd.Series(np.asarray(p3, float)).groupby(g).rank(method='min').to_numpy()
    rb = pd.Series(q).groupby(g).rank(method='min').to_numpy()
    assert (ra == rb).all()
    return q, dl


def rtab(te, p1, p3, s1, s2, p3raw=None):
    """レースごと 1 行: ◎(s1 → s2 → 馬番)の Y1・Y3・対数尤度・1 番人気。"""
    c = lambda v: np.clip(np.asarray(v, float), 1e-6, 1 - 1e-6)  # noqa: E731
    x = te[KEY + ['umaban', 'Y1', 'Y3', 'pop']].assign(_p1=c(p1), _p3=c(p3), _s1=np.asarray(s1, float), _s2=np.asarray(s2, float))
    x['ll1'] = x.Y1 * np.log(x._p1) + (1 - x.Y1) * np.log(1 - x._p1)
    x['ll3'] = x.Y3 * np.log(x._p3) + (1 - x.Y3) * np.log(1 - x._p3)
    if p3raw is not None:
        x['_r'] = c(p3raw)
        x['ll3r'] = x.Y3 * np.log(x._r) + (1 - x.Y3) * np.log(1 - x._r)
    g = x.groupby(KEY, sort=True)
    R = g[['ll1', 'll3'] + (['ll3r'] if p3raw is not None else [])].sum()
    R['n'] = g.size()
    top = x.sort_values(KEY + ['_s1', '_s2', 'umaban'], ascending=[True, True, True, False, False, True],
                        kind='mergesort').groupby(KEY, sort=False).head(1).set_index(KEY)
    R['win'], R['top3'], R['top_uma'] = top.Y1, top.Y3, top.umaban
    f = x[x['pop'] == 1].drop_duplicates(KEY).set_index(KEY)
    R['fav_win'], R['fav_top3'] = f.Y1, f.Y3
    R = R.reset_index()
    R['year'] = R.race_date.astype(str).str[:4]
    return R


def m6(te, p1, p3):
    """第 6 版の物差し: LL3 = p3′・◎ = p3′ → p1 → 馬番。直す前の p3 の LL3 と ◎ = p1 の率も返す。"""
    q, dl = p3p(te, p3)
    R = rtab(te, p1, q, q, p1, p3raw=p3)
    Rp = rtab(te, p1, p3, p1, p3)
    m = dict(LL1=float(R.ll1.mean()), LL3=float(R.ll3.mean()), LL3raw=float(R.ll3r.mean()), win=float(R.win.mean()),
             top3=float(R.top3.mean()), win_p1=float(Rp.win.mean()), top3_p1=float(Rp.top3.mean()), races=int(len(R)),
             delta_min=float(dl.min()), delta_max=float(dl.max()))
    m.update({f'top3_{y}': float(g.top3.mean()) for y, g in R.groupby('year')})
    return m, q, R


def fit(d, te, cols, tag, cfg1=CFG, cfg3=CFG, r1=None):
    if r1 is None:
        r1 = t4_day3.fit_pred(d, cols, 'Y1', cfg1, tag)
    r3 = t4_day3.fit_pred(d, cols, 'Y3', cfg3, tag)
    p1, p3 = t4_day3.finish(te, r1, r3)
    return r1, p1, p3


def judge(m, prev):
    d3, d1, dt = m['LL3'] - prev['LL3'], m['LL1'] - prev['LL1'], m['top3'] - prev['top3']
    return dict(dLL3=d3, dLL1=d1, dtop3=dt, dwin=m['win'] - prev['win'], keep=bool(d3 > 0 and m['top3'] >= prev['top3'] - 0.005))


def row_txt(x):
    return (f"ΔLL Y3 {x['dLL3']:+.3f}({x['dLL3']:+.5f})・Y1 {x['dLL1']:+.3f}({x['dLL1']:+.5f})・◎ 3 着以内率 {x['top3']:.3f}"
            f"({x['dtop3'] * 100:+.2f} ポイント)・◎ 勝率 {x['win']:.3f} → {'残す' if x['keep'] else '残さない'}")


def all_():
    RES.unlink(missing_ok=True)
    d, te = setup()
    g5 = json.loads(GRID5.read_text(encoding='utf-8'))
    base = list(g5['kept'])
    assert len(base) == 115 and not set(base) & ({'h2h', 'elo_z', 'nori', 'bw_diff'} | set(DAY6))
    r5 = json.loads(RES5.read_text(encoding='utf-8'))
    assert base == r5['stages']['kept']
    # 1. 前の再現
    r1, p1, p3 = fit(d, te, base, 't6_C')
    mC = t4_day3.metrics(te, p1, p3)
    ref = r5['stages']['rows']['C']
    dd = {k: mC[k] - ref[k] for k in ('win', 'top3', 'LL1', 'LL3')}
    ok = all(abs(v) <= 1e-12 for v in dd.values())
    res_save('repro', {'m': mC, 'diff': dd, 'ok': ok})
    ledger('前の再現(第 5 版の 115 列・15/500/800・拡張窓 2016〜2021・◎ = p1 の 1 位)',
           f"◎ 勝率 {mC['win']:.3f}・◎ 3 着以内率 {mC['top3']:.3f}・Y1 {mC['LL1']:.3f}・Y3 {mC['LL3']:.3f}・stages.rows.C との差 "
           f"{max(abs(v) for v in dd.values()):.1e} → {'合' if ok else '否'}", 'out/t6_day3.md・v3/t6_day3_res.json')
    print('再現', dd, ok, flush=True)
    if not ok:
        md()
        raise SystemExit('⛔ 前の再現が合わない')
    # 2. 段 D
    mD, _, _ = m6(te, p1, p3)
    prevC = dict(LL3=mC['LL3'], LL1=mC['LL1'], top3=mC['top3'], win=mC['win'])
    jD = judge(mD, prevC)
    rows = {'C': dict(cols=115, **mC), 'D': dict(cols=115, prev='C', **jD, **mD)}
    res_save('stages', {'rows': rows})
    ledger('段 D(◎ = p3′ の 1 位・p3′ = 目盛りを一律にずらして合計 3・材料は足さない・前 = 第 5 版の段 C)',
           row_txt({**jD, **mD}) + f"・δ {mD['delta_min']:+.3f}〜{mD['delta_max']:+.3f}", 'out/t6_day3.md・v3/t6_day3_res.json')
    print('段 D', jD, mD['top3'], flush=True)
    if not jD['keep']:
        md()
        raise SystemExit('⛔ 段 D が採否の決まりに届かない')
    # 3. 段 E → F1
    kept, prev, code, loo = list(base), mD, 'D', {}
    for s, new in (('E', ['h2h', 'elo_z']), ('F1', ['nori'])):
        cols = kept + new
        tag = 't6_E' if s == 'E' else f't6_F1_{code}'
        r1s, p1s, p3s = fit(d, te, cols, tag)
        m, _, _ = m6(te, p1s, p3s)
        j = judge(m, prev)
        rows[s] = dict(cols=len(cols), prev=code, **j, **m)
        if s == 'E':
            for c in new:
                cc = [x for x in cols if x != c]
                _, pa, pb = fit(d, te, cc, f"t6_E_no{'h2h' if c == 'h2h' else 'elo'}", r1=r1s)
                mm, _, _ = m6(te, pa, pb)
                loo[c] = {'LL3_without': mm['LL3'], 'dLL3': m['LL3'] - mm['LL3'], 'top3_without': mm['top3']}
        ledger(f"段 {s}(+ {'・'.join(new)}・15/500/800・前 = 段 {code})", row_txt({**j, **m}) + (
            '・記録 列外しの ΔLL Y3 ' + '・'.join(f"{k} {v['dLL3']:+.5f}" for k, v in loo.items()) if s == 'E' else ''),
            'out/t6_day3.md・v3/t6_day3_res.json')
        print(s, j, m['top3'], flush=True)
        if j['keep']:
            kept, prev, code = cols, m, code + s
        res_save('stages', {'rows': rows, 'kept': kept, 'code': code, 'loo': loo})
    # 4. 格子
    g1 = []
    for cfg in t4_day3.GRID:
        a = t4_day3.fit_pred(d, kept, 'Y1', cfg, f't6_grid_{code}')
        q1, _ = t4_day3.finish(te, a, a)
        g1.append((t4_day3.metrics(te, q1, q1)['LL1'], cfg, a))
    b1 = max(g1, key=lambda t: t[0])
    g3 = []
    for cfg in t4_day3.GRID:
        b = t4_day3.fit_pred(d, kept, 'Y3', cfg, f't6_grid_{code}')
        q1, q3 = t4_day3.finish(te, b1[2], b)
        g3.append((m6(te, q1, q3)[0]['LL3'], cfg))
    b3 = max(g3, key=lambda t: t[0])
    c1, c3 = b1[1], b3[1]
    _, P1pre, P3pre = fit(d, te, kept, f't6_grid_{code}', c1, c3)
    mpre, Qpre, Rpre = m6(te, P1pre, P3pre)
    res_save('grid', {'Y1': list(c1), 'Y3': list(c3), 'kept': kept, 'code': code, 'g1': [[x[0], list(x[1])] for x in g1],
                      'g3': [[x[0], list(x[1])] for x in g3], 'final': mpre})
    ledger(f'最終形の格子 8 通り(段 {code}・{len(kept)} 列・Y1 → Y3〔p3′〕)',
           f"Y1 {'/'.join(map(str, c1))}・Y3 {'/'.join(map(str, c3))}・◎ 勝率 {mpre['win']:.3f}・◎ 3 着以内率 {mpre['top3']:.3f}・"
           f"Y1 {mpre['LL1']:.3f}・Y3(p3′){mpre['LL3']:.3f}・Y3(直す前){mpre['LL3raw']:.3f}", 'out/t6_day3.md・v3/t6_grid.json')
    print('格子', c1, c3, mpre['top3'], flush=True)
    # 5. 段 F2
    dcols = kept + DAY6
    _, a1, a3 = fit(d, te, dcols, f't6_F2pre_{code}')
    mF0, _, _ = m6(te, a1, a3)
    _, b1_, b3_ = fit(d, te, dcols + ['bw_diff'], f't6_F2_{code}')
    mF2, _, _ = m6(te, b1_, b3_)
    jF2 = judge(mF2, mF0)
    rows['F2pre'] = dict(cols=len(dcols), **mF0)
    rows['F2'] = dict(cols=len(dcols) + 1, prev='F2pre', **jF2, **mF2)
    kept_day = dcols + (['bw_diff'] if jF2['keep'] else [])
    res_save('stages', {'rows': rows, 'kept': kept, 'code': code, 'loo': loo, 'kept_day': kept_day})
    ledger(f'段 F2(当日版だけ・+ bw_diff・15/500/800・前 = 前日版の最終形の列 + 当日 3 列 {len(dcols)} 列)', row_txt({**jF2, **mF2}),
           'out/t6_day3.md・v3/t6_day3_res.json')
    print('F2', jF2, flush=True)
    # 6. 当日版
    _, P1day, P3day = fit(d, te, kept_day, f"t6_day_{code}{'F2' if jF2['keep'] else ''}", c1, c3)
    mday, Qday, Rday = m6(te, P1day, P3day)
    res_save('day', {'cols': len(kept_day), **mday})
    GRID6.write_text(json.dumps({'Y1': list(c1), 'Y3': list(c3), 'kept': kept, 'kept_day': kept_day}, ensure_ascii=False),
                     encoding='utf-8')
    ledger(f"当日版(前日版の最終形 + 当日 3 列{' + bw_diff' if jF2['keep'] else ''}・{len(kept_day)} 列・格子と同じ設定)",
           f"◎ 勝率 {mday['win']:.3f}・◎ 3 着以内率 {mday['top3']:.3f}・Y1 {mday['LL1']:.3f}・Y3(p3′){mday['LL3']:.3f}・"
           f"Y3(直す前){mday['LL3raw']:.3f}", 'out/t6_day3.md・v3/t6_grid.json')
    print('当日版', mday['top3'], flush=True)
    # 7. 線
    P = pd.read_parquet(PREDS5)
    assert P.race_date.astype(str).max() < '2022-01-01'
    kk = ['track', 'race_date', 'race_no', 'umaban', 'n', 'Y1', 'Y3']
    a_ = te[kk].reset_index(drop=True).copy()
    b_ = P[kk].reset_index(drop=True).copy()
    for z in (a_, b_):
        z['race_no'] = z.race_no.astype(int)
    assert a_.astype(str).equals(b_.astype(str)), '第 6 版と保存した予想の (場・日付・R・馬番)・n・Y1・Y3 が一致しない'
    lm = r5['line']['metrics']
    tabs, M, chk = {'v6pre': Rpre, 'v6day': Rday}, {'v6pre': mpre, 'v6day': mday}, {}
    for k in ('v5pre', 'v5day', 'v4pre', 'v4day'):
        q1, q3 = P[f'{k}_p1'].to_numpy(), P[f'{k}_p3'].to_numpy()
        mk = t4_day3.metrics(te, q1, q3)
        chk[k] = mk['top3'] - lm[k]['top3']
        assert mk['top3'] == lm[k]['top3'], f'{k} の ◎ 3 着以内率が保存値と合わない'
        M[k] = mk
        tabs[k] = rtab(te, q1, q3, q1, q3)
    ledger('第 5 版・第 4 版の線(v3/t5_day3_preds.parquet・◎ = p1 の 1 位)',
           '保存値との差 ' + '・'.join(f'{k} {M[k]["top3"]:.3f}(差 {v:.0e})' for k, v in chk.items()) + '・鍵・n・Y1・Y3 完全一致',
           'out/t6_day3.md')
    # 8. 止まりどころ
    probe, B = {}, {}
    for v in ('pre', 'day'):
        for o in ('v5', 'v4'):
            a, b = tabs['v6' + v].set_index(KEY), tabs[o + v].set_index(KEY)
            assert a.index.equals(b.index)
            D = (a[['win', 'top3', 'll1']] - b[['win', 'top3', 'll1']]).add_prefix('d_').reset_index()
            bb = t3_eval.boot(D, ['d_win', 'd_top3', 'd_ll1'])
            pt, lo, hi = [x * 100 for x in bb['d_top3']]
            h = (hi - lo) / 2
            s = 1.11 * h / 1.96
            probe[f'v6{v}-{o}{v}'] = dict(d=pt, lo=lo, hi=hi, h=h, p1=phi((pt - 1.96 * s) / s),
                                          p2=phi((pt - 1.96 * s) / math.sqrt(s * s + 0.09)), d_win=list(bb['d_win']),
                                          d_ll1=list(bb['d_ll1']), same_top=float((a.top_uma == b.top_uma).mean()))
    stop = [v for v in ('pre', 'day') if probe[f'v6{v}-v5{v}']['lo'] <= 0]
    res_save('probe', {'probe': probe, 'stop': stop, 'line_check': chk})
    for k, q in probe.items():
        ledger(f'開ける前の差 {k}(◎ 3 着以内率・開催日ブートストラップ 2,000 回・seed 0)',
               f"{q['d']:+.3f} ポイント(95% {q['lo']:+.3f}〜{q['hi']:+.3f})・半幅 h {q['h']:.3f}・「上回った」の見込み ① {q['p1']:.3f} ② {q['p2']:.3f}",
               'out/t6_day3.md・v3/t6_day3_res.json')
    ledger('開ける前の止まりどころ(§5 ②・第 6 版 − 第 5 版の下限)',
           ('当たった: 下限が 0 以下 = ' + '・'.join({'pre': '前日版', 'day': '当日版'}[x] for x in stop) + '。確かめる期間は開けずにユーザーに聞く')
           if stop else '当たらない(前日版・当日版とも下限 > 0)', 'out/t6_day3.md')
    print('止まりどころ', probe, stop, flush=True)
    # 9. 記録
    n0 = te.n.to_numpy(float)
    tabs['s0'] = rtab(te, 1 / n0, 3 / n0, np.zeros(len(te)), np.zeros(len(te)))
    summ = {}
    for k, R in tabs.items():
        cols = ['win', 'top3', 'll1', 'll3', 'fav_win', 'fav_top3'] + (['ll3r'] if 'll3r' in R else [])
        summ[k] = {c: list(v) for c, v in t3_eval.boot(R, cols).items()}
    ty = te.groupby(KEY).agg(deb=('l_debut', lambda s: (s == 1).any()), jr=('l_jra', lambda s: (s == 1).any()),
                             nr=('l_nar', lambda s: (s == 1).any())).reset_index()
    ty['kind'] = np.where(ty.deb, '初出走がいる', np.where(ty.jr | ty.nr, '転入初戦がいる(初出走なし)', 'どちらもいない'))
    br = {}
    for k, R in tabs.items():
        R = R.merge(ty[KEY + ['kind']], on=KEY, how='left')
        R['band'] = pd.cut(R.n, [4, 8, 12, 99], labels=[b[2] for b in BANDS]).astype(str)
        F = R[R.fav_top3.notna()]
        br[k] = {by: {str(g): dict(races=int(len(x)), top3=float(x.top3.mean()), fav_top3=float(x.fav_top3.mean()),
                                   diff=float((x.top3 - x.fav_top3).mean())) for g, x in F.groupby(by)}
                 for by in ('year', 'track', 'band', 'kind')}
    sel = {}
    for v, R6 in (('pre', Rpre), ('day', Rday)):
        R5 = tabs['v5' + v]
        diff = (R6.top_uma.to_numpy() != R5.top_uma.to_numpy())
        sel[v] = dict(top3_p1=M['v6' + v]['top3_p1'], win_p1=M['v6' + v]['win_p1'], share_diff=float(diff.mean()),
                      races_diff=int(diff.sum()), v6_top3_diff=float(R6.top3[diff].mean()), v5_top3_diff=float(R5.top3[diff].mean()))
    cal, gt = {}, {}
    for v, p1_, q_ in (('pre', P1pre, Qpre), ('day', P1day, Qday)):
        x = te[['Y1', 'Y3']].assign(p1=p1_, p3=q_)
        cal[v] = {}
        for nm, p, y, e in (('p1', 'p1', 'Y1', [0, .05, .1, .2, .3, .5, 1.01]), ('p3′', 'p3', 'Y3', [0, .1, .2, .4, .6, .8, 1.01])):
            cal[v][nm] = [[str(a), int(len(b)), float(b[p].mean()) if len(b) else None, float(b[y].mean()) if len(b) else None]
                          for a, b in x.groupby(pd.cut(x[p], e, right=False), observed=False)]
        gt[v] = int((p1_ > q_).sum())
    res_save('record', {'summary': summ, 'breakdown': br, 'select': sel, 'calib': cal, 'p1_gt_p3p': gt,
                        'delta': {v: [M['v6' + v]['delta_min'], M['v6' + v]['delta_max']] for v in ('pre', 'day')}})
    pp = te[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3']].reset_index(drop=True)
    pp['v6pre_p1'], pp['v6pre_p3'], pp['v6pre_p3p'] = P1pre, P3pre, Qpre
    pp['v6day_p1'], pp['v6day_p3'], pp['v6day_p3p'] = P1day, P3day, Qday
    pp.to_parquet(PREDS, index=False)
    ledger('記録(§6)', f"第 6 版 ◎ = p1 の 1 位にしたとき 前日 {sel['pre']['top3_p1']:.3f}・当日 {sel['day']['top3_p1']:.3f}/◎ が第 5 版と違う "
           f"前日 {sel['pre']['share_diff']:.3f}・当日 {sel['day']['share_diff']:.3f}/p1 > p3′ の馬 {gt['pre']}・{gt['day']}",
           'out/t6_day3.md・v3/t6_day3_preds.parquet')
    md()
    if stop:
        raise SystemExit('⛔ 開ける前の止まりどころに当たった(記録まで書いた)')


# ================================================================ md
def md():
    r = res_load()
    f = lambda t, dd=4: f"{t[0]:.{dd}f}({t[1]:.{dd}f}〜{t[2]:.{dd}f})"  # noqa: E731
    L = ['# 第 6 版 3 日目: 前の再現・段 D・E・F1・格子・段 F2・当日版・線・開ける前の止まりどころ(PREREG6 §5・§6)', '',
         '台本 src/t6_day3.py(決め書に無い細部 11 個は台本の頭)。材料 v3/feat_t6_explore.parquet。対数尤度はレースあたり。'
         'Y3 の対数尤度と ◎ は p3′(合計 3)で測る(再現の行 C だけ p3・◎ = p1)。', '']
    if 'repro' in r:
        z = r['repro']
        L += [f"前の再現(段 C・115 列・15/500/800): {'合' if z['ok'] else '否'}・stages.rows.C との差 "
              + '・'.join(f'{k} {v:.1e}' for k, v in z['diff'].items()), '']
    if 'stages' in r:
        s = r['stages']
        L += ['## 段の表(拡張窓 2016〜2021・葉 15・最小 500・木 800)', '',
              '| 段 | 列 | 前 | ◎ 勝率 | ◎ 3 着以内率 | Y1 | Y3(p3′) | Y3(直す前) | ΔLL Y3 | ΔLL Y1 | ◎ 率の差 | 残す |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for k, x in s['rows'].items():
            L.append(f"| {k} | {x['cols']} | {x.get('prev', '')} | {x['win']:.4f} | {x['top3']:.4f} | {x['LL1']:.5f} | {x['LL3']:.5f} | "
                     f"{x.get('LL3raw', x['LL3']):.5f} | {x.get('dLL3', float('nan')):+.5f} | {x.get('dLL1', float('nan')):+.5f} | "
                     f"{x.get('dtop3', float('nan')) * 100:+.2f} | {('○' if x['keep'] else '×') if 'keep' in x else ''} |")
        if 'code' in s:
            L += ['', f"残した形: 段 {s['code']}・前日 {len(s['kept'])} 列" + (f"・当日 {len(s['kept_day'])} 列" if 'kept_day' in s else '')
                  + '(この決まりは ◎ を最大 0.49 ポイント下げる段を残しうる)', '']
        if s.get('loo'):
            L += ['段 E の列外し(記録・Y3 だけ): ' + '・'.join(f"{k} を外すと ΔLL Y3 {v['dLL3']:+.5f}(◎ {v['top3_without']:.4f})"
                                              for k, v in s['loo'].items()), '']
    if 'grid' in r:
        g = r['grid']
        L += ['## 最終形の格子', '', '| 目的 | 葉/最小/木 | 対数尤度 | 選択 |', '|---|---|---|---|']
        L += [f"| Y1 | {'/'.join(map(str, c))} | {ll:.5f} | {'○' if c == g['Y1'] else ''} |" for ll, c in g['g1']]
        L += [f"| Y3(p3′) | {'/'.join(map(str, c))} | {ll:.5f} | {'○' if c == g['Y3'] else ''} |" for ll, c in g['g3']]
        m = g['final']
        L += ['', f"前日版: ◎ 勝率 {m['win']:.4f}・◎ 3 着以内率 {m['top3']:.4f}・Y1 {m['LL1']:.5f}・Y3(p3′){m['LL3']:.5f}・"
              f"Y3(直す前){m['LL3raw']:.5f}", '']
    if 'day' in r:
        m = r['day']
        L += [f"当日版({m['cols']} 列): ◎ 勝率 {m['win']:.4f}・◎ 3 着以内率 {m['top3']:.4f}・Y1 {m['LL1']:.5f}・Y3(p3′){m['LL3']:.5f}・"
              f"Y3(直す前){m['LL3raw']:.5f}", '']
    if 'probe' in r:
        p = r['probe']
        L += ['## 線と開ける前の止まりどころ(◎ 3 着以内率の対の差・ポイント・開催日 2,000 回・seed 0)', '',
              '線の確かめ(保存値との差): ' + '・'.join(f'{k} {v:.0e}' for k, v in p['line_check'].items()), '',
              '| 差 | d | 95% 区間 | 半幅 h | ◎ が同じ | 見込み ① | 見込み ② |', '|---|---|---|---|---|---|---|']
        for k, q in p['probe'].items():
            L.append(f"| {k} | {q['d']:+.3f} | {q['lo']:+.3f}〜{q['hi']:+.3f} | {q['h']:.3f} | {q['same_top']:.3f} | {q['p1']:.3f} | {q['p2']:.3f} |")
        L += ['', ('**開ける前の止まりどころに当たった**(第 6 版 − 第 5 版の下限 ≤ 0: '
                   + '・'.join({'pre': '前日版', 'day': '当日版'}[x] for x in p['stop']) + ')。確かめる期間は開けずにユーザーに聞く。')
              if p['stop'] else '開ける前の止まりどころ: 当たらない(前日版・当日版とも第 6 版 − 第 5 版の下限 > 0)。', '']
    if 'record' in r:
        z = r['record']
        nm = {'v6pre': '第 6 版 前日', 'v6day': '第 6 版 当日', 'v5pre': '第 5 版 前日', 'v5day': '第 5 版 当日',
              'v4pre': '第 4 版 前日', 'v4day': '第 4 版 当日', 's0': '段 0'}
        L += ['## 記録(§6)', '', '| 版 | ◎ 勝率 | ◎ 3 着以内率 | Y1 | Y3 | Y3(直す前) | 1 番人気 勝率 | 1 番人気 3 着以内率 |',
              '|---|---|---|---|---|---|---|---|']
        for k, S in z['summary'].items():
            L.append(f"| {nm[k]} | {f(S['win'])} | {f(S['top3'])} | {f(S['ll1'])} | {f(S['ll3'])} | "
                     f"{f(S['ll3r']) if 'll3r' in S else ''} | {f(S['fav_win'])} | {f(S['fav_top3'])} |")
        L += ['', '### 1 番人気との差(◎ 3 着以内率 − 1 番人気・ポイント)', '']
        for by, t in (('year', '年'), ('track', '場'), ('band', '頭数'), ('kind', 'レースの種類')):
            gs = list(z['breakdown']['v6pre'][by])
            L += [f'| {t} | ' + ' | '.join(nm[k] for k in z['breakdown']) + ' |', '|---' * (len(z['breakdown']) + 1) + '|']
            for gg in gs:
                L.append(f'| {gg}({z["breakdown"]["v6pre"][by][gg]["races"]:,} R) | '
                         + ' | '.join(f"{z['breakdown'][k][by][gg]['diff'] * 100:+.2f}" for k in z['breakdown']) + ' |')
            L.append('')
        for v, t in (('pre', '前日版'), ('day', '当日版')):
            s = z['select'][v]
            L.append(f"- 選び方の内訳 {t}: ◎ = p1 の 1 位にしたとき 3 着以内率 {s['top3_p1']:.4f}・勝率 {s['win_p1']:.4f}/◎ が第 5 版と違う "
                     f"{s['share_diff']:.3f}({s['races_diff']:,} R)・そのレースで 第 6 版 {s['v6_top3_diff']:.4f}・第 5 版 {s['v5_top3_diff']:.4f}")
        L.append('')
        for v, t in (('pre', '前日版'), ('day', '当日版')):
            for k2, c in z['calib'][v].items():
                L.append(f"- 当たり具合 {t} {k2}(見込み/実際・馬): " + '・'.join(
                    f"{a} {m:.3f}/{y:.3f}({n:,})" if n else f"{a} ―(0)" for a, n, m, y in c))
            L.append(f"- {t}: p1 > p3′ の馬 {z['p1_gt_p3p'][v]}・δ {z['delta'][v][0]:+.4f}〜{z['delta'][v][1]:+.4f}")
        L.append('')
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')


if __name__ == '__main__':
    {'all': all_, 'md': md}[sys.argv[1]]()
