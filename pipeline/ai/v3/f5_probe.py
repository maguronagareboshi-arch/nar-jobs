# -*- coding: utf-8 -*-
"""新しい材料 本命 5 個(着順と時計の乖離・前走の相手のその後・乗り替わりの読み・当日の馬場の傾き・頭一つ抜け)の見落とし確かめ(学習なし)。
決め = out/f5_plan.md(変えない)。見方は src/v8fa_probe.py と同じ(r = Y3 − v7dpre_p3・5 等分・開催日ごとの誤差・年ごとの向き)。追加で 2016〜18 と 2019〜21 に分けた向き。

  py -3.12 -X utf8 src/f5_probe.py

■ 実装の決め(結果を見る前に固定)
  共通: 走り r = v8fa_probe.main と同じ(取消・除外を除き 2022 年以降は読んだ直後に捨てて assert)。SI・a_ab = t4_base_2014_2021(南関)。
  U 着順と時計の乖離: 各走で SI のある馬の SI 順位比(速い方が小さい・順位÷SI のある頭数)と着順比(着順÷頭数)の差 = 着順比 − SI 順位比。直近 5 走・730 日以内(2 走以上)の平均。
  F 前走の相手のその後: 今回の 60 日以上前・365 日以内の一番新しい走りのレースで、自分以外の出走馬の「その走りの後 60 日以内の 3 着以内率」(後の走りが 1 走以上ある馬の走り全部の合計 ÷ 走数)。
    FA(期待との差)は期待の作り方が決まらないので出さない(決め書からの簡略化・結果を見る前)。
  J 乗り替わりの読み: 前走(一番新しい前の走り・年齢を問わない)の騎手 ≠ 今回の騎手のとき、前走の騎手が同じ日に乗る別の馬(同じレースまたは同じ日の別のレース)の a_ab のうち最大 − 今回の馬の a_ab。前走の騎手が今日乗らなければ欠け。
    JR = 前走の騎手が同じレースの別の馬に乗る場合の同じ差(それ以外は欠け)。
  B 当日の馬場の傾き: 同じ場・同じ日の前のレース(3 レース以上)で、最初の角の位置比 0.3 以下の馬の(3 着以内 − 3/頭数)の平均 = 先行の偏り。BF = 先行の偏り × (0.5 − この馬の直近 5 走の位置比の平均・2 走以上)。
    BG = (内枠(馬番 ≤ 頭数/3)の(3 着以内 − 3/頭数)の平均 − 外枠(馬番 > 頭数×2/3)の平均)× (今回の馬が内枠 1・外枠 −1・中 0)。
  D 頭一つ抜け: a_ab − 同じレースの自分以外の a_ab の最大(a_ab のある馬が 2 頭以上のレース)。DS = 同じレースの a_ab の標準偏差(混戦度)。
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

V3 = Path('C:/Users/kouki/nankan_ai/v3')
REPO = Path(__file__).resolve().parent.parent
MD = REPO / 'out' / 'f5_check.md'
JS = REPO / 'out' / 'f5_check.json'
KEY = d3.KEY
CUT = '2022-01-01'
LAB = {'U': '着順と時計の乖離(時計の割に着順が悪かった走りの平均)', 'F': '前走の相手のその後(60 日後までの 3 着以内率)',
       'J': '乗り替わりの読み(前走騎手の今日の別の馬の a_ab − 今回の馬)', 'JR': '同・前走騎手が同じレースの別の馬に乗る場合',
       'BF': '当日の先行の偏り × 先行型', 'BG': '当日の内外の偏り × 内枠', 'D': '頭一つ抜け(a_ab − 他の最大)', 'DS': '混戦度(a_ab の標準偏差)'}


def rid_of(df):
    return pd.factorize(df.track.astype(str) + '|' + df.race_date.astype(str) + '|' + df.race_no.astype(str))[0]


def main():
    h, races = vc.sources()
    h = h[h.race_date < CUT]
    keep = KEY + ['umaban', 'hid', 'jockey', 'finish', 'finish_note', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']
    h = h[[c for c in dict.fromkeys(keep) if c in h.columns]].copy()
    del races
    assert h.race_date.max() < CUT
    r = h[~h.finish_note.isin(d3.CANCEL)].drop_duplicates(KEY + ['umaban']).copy()
    fin = pd.to_numeric(r.finish, errors='coerce')
    r['heads'] = (fin > 0).groupby([r[k] for k in KEY]).transform('sum').astype(float)
    r = r[r.heads > 0].copy()
    fin = pd.to_numeric(r.finish, errors='coerce')
    r['fin'] = fin
    r['t3'] = ((fin > 0) & (fin <= 3)).astype(float)
    r['dnum'] = d3.dnum_of(r.race_date)
    pos, n = d3.first_corner(r)
    r['pr'] = pos / np.where(n > 0, n, np.nan)
    r['jockey'] = r.jockey.map(lambda x: vc.norm(x) if isinstance(x, str) and x.strip() else None)
    r['um'] = pd.to_numeric(r.umaban, errors='coerce')
    print('走り', len(r), flush=True)

    t = pd.read_parquet(V3 / 't4_base_2014_2021.parquet', columns=KEY + ['runner_number', 'SI', 'a_ab'])
    t = t.rename(columns={'runner_number': 'umaban'})
    t = vo.nk(t)
    assert t.race_date.max() < CUT
    rs = r.merge(t[KEY + ['umaban', 'SI', 'a_ab']], on=KEY + ['umaban'], how='left', validate='1:1')
    rs = rs.dropna(subset=['hid']).copy()
    rs['rid'] = rid_of(rs)
    # U の素: 走りごとの (着順比 − SI 順位比)
    sic = rs.SI.notna()
    rs['sirk'] = np.nan
    g = rs[sic].groupby('rid').SI
    rs.loc[sic, 'sirk'] = (g.rank(ascending=False, method='average') / g.transform('count')).to_numpy()
    rs['u'] = rs.fin / rs.heads - rs.sirk
    rs.loc[~(rs.fin > 0), 'u'] = np.nan

    # F の素: 走りごとの「後 60 日以内の 3 着以内(合計・走数)」
    rs = rs.sort_values(['hid', 'dnum'], kind='mergesort').reset_index(drop=True)
    hid = rs.hid.to_numpy()
    starts = np.r_[0, np.nonzero(hid[1:] != hid[:-1])[0] + 1, len(rs)]
    D = rs.dnum.to_numpy(float)
    T3 = rs.t3.to_numpy(float)
    cs = np.r_[0, np.cumsum(T3)]
    ls, ln = np.zeros(len(rs)), np.zeros(len(rs))
    for a, b in zip(starts[:-1], starts[1:]):
        d = D[a:b]
        hi = np.searchsorted(d, d + 60, side='right')
        idx = np.arange(a, b)
        lo = idx + 1
        hi = a + hi
        ls[a:b] = cs[hi] - cs[lo]
        ln[a:b] = hi - lo
    rs['l_sum'], rs['l_n'] = ls, ln
    gr = rs.groupby('rid')
    rs['R_sum'] = gr.l_sum.transform('sum')
    rs['R_n'] = gr.l_n.transform('sum')
    rs['F_run'] = (rs.R_sum - rs.l_sum) / (rs.R_n - rs.l_n).where(lambda x: x > 0)
    print('U・F の素', flush=True)

    # B の素: レースごとの先行・内外の偏り → 同じ日の前のレースの累積
    rs['ex'] = rs.t3 - 3.0 / rs.heads
    fr = rs.pr <= 0.3
    inner = rs.um <= rs.heads / 3
    outer = rs.um > rs.heads * 2 / 3
    rr_ = pd.DataFrame({'track': rs.track, 'race_date': rs.race_date, 'race_no': pd.to_numeric(rs.race_no, errors='coerce'), 'rid': rs.rid,
                        'f_s': np.where(fr, rs.ex, 0.0), 'f_n': fr.astype(float),
                        'i_s': np.where(inner, rs.ex, 0.0), 'i_n': inner.astype(float),
                        'o_s': np.where(outer, rs.ex, 0.0), 'o_n': outer.astype(float)})
    RC = rr_.groupby('rid').agg(track=('track', 'first'), race_date=('race_date', 'first'), race_no=('race_no', 'first'),
                                f_s=('f_s', 'sum'), f_n=('f_n', 'sum'), i_s=('i_s', 'sum'), i_n=('i_n', 'sum'),
                                o_s=('o_s', 'sum'), o_n=('o_n', 'sum')).reset_index()
    RC = RC.sort_values(['track', 'race_date', 'race_no'], kind='mergesort')
    gd = RC.groupby(['track', 'race_date'])
    for c in ('f_s', 'f_n', 'i_s', 'i_n', 'o_s', 'o_n'):
        RC['c_' + c] = gd[c].cumsum() - RC[c]
    RC['c_races'] = gd.cumcount()
    ok = RC.c_races >= 3
    with np.errstate(invalid='ignore', divide='ignore'):
        RC['bf'] = np.where(ok & (RC.c_f_n > 0), RC.c_f_s / RC.c_f_n, np.nan)
        RC['bg'] = np.where(ok & (RC.c_i_n > 0) & (RC.c_o_n > 0), RC.c_i_s / RC.c_i_n - RC.c_o_s / RC.c_o_n, np.nan)
    RC = RC.set_index('rid')

    # 予想の行
    P = vo.nk(pd.read_parquet(V3 / 'v7d_final_preds.parquet'))
    assert P.race_date.max() < CUT
    q = P[KEY + ['umaban', 'year', 'n', 'Y3', 'v7dpre_p3']].merge(
        rs[KEY + ['umaban', 'hid', 'jockey', 'um', 'a_ab', 'rid']], on=KEY + ['umaban'], how='left', validate='1:1')
    q['dnum'] = d3.dnum_of(q.race_date)
    N = len(q)
    print('つながり hid', float(q.hid.notna().mean()), flush=True)

    # 馬ごとの前の走りを引く
    grp = rs.groupby('hid', sort=False).indices
    U_, PR_, J_, F_ = rs.u.to_numpy(float), rs.pr.to_numpy(float), rs.jockey.to_numpy(object), rs.F_run.to_numpy(float)
    rid_arr = rs.rid.to_numpy()
    qh, qd = q.hid.to_numpy(object), q.dnum.to_numpy(float)
    S = {k: np.full(N, np.nan) for k in LAB}
    prev_j = np.empty(N, dtype=object)
    prmean = np.full(N, np.nan)
    for j in range(N):
        ix = grp.get(qh[j]) if isinstance(qh[j], str) else None
        if ix is None:
            continue
        k = np.searchsorted(D[ix], qd[j], side='left')
        if k == 0:
            continue
        p = ix[:k]
        age = qd[j] - D[p]
        w = p[age <= 730][-5:]
        u = U_[w]
        u = u[~np.isnan(u)]
        if len(u) >= 2:
            S['U'][j] = u.mean()
        pv = PR_[p[-5:]]
        pv = pv[~np.isnan(pv)]
        if len(pv) >= 2:
            prmean[j] = pv.mean()
        prev_j[j] = J_[p[-1]]
        m = (age >= 60) & (age <= 365)
        if m.any():
            S['F'][j] = F_[p[m][-1]]
    print('U・F・前走騎手', flush=True)

    # J: 前走の騎手が同じ日に乗る別の馬の a_ab
    today = rs[rs.jockey.notna() & rs.a_ab.notna()][['race_date', 'jockey', 'rid', 'a_ab']]
    tg = {k: (g.rid.to_numpy(), g.a_ab.to_numpy(float)) for k, g in today.groupby(['race_date', 'jockey'])}
    qj, qrid, qa, qdate = q.jockey.to_numpy(object), q.rid.to_numpy(), q.a_ab.to_numpy(float), q.race_date.to_numpy()
    for j in range(N):
        pj = prev_j[j]
        if not isinstance(pj, str) or not isinstance(qj[j], str) or pj == qj[j] or np.isnan(qa[j]):
            continue
        e = tg.get((qdate[j], pj))
        if e is None:
            continue
        rids, aa = e
        S['J'][j] = aa.max() - qa[j]
        same = rids == qrid[j]
        if same.any():
            S['JR'][j] = aa[same].max() - qa[j]

    # B: 当日の馬場の傾き
    bf = RC.bf.reindex(q.rid).to_numpy(float)
    bg = RC.bg.reindex(q.rid).to_numpy(float)
    S['BF'] = bf * (0.5 - prmean)
    um, nh = q.um.to_numpy(float), q.n.to_numpy(float)
    gs = np.where(um <= nh / 3, 1.0, np.where(um > nh * 2 / 3, -1.0, 0.0))
    S['BG'] = np.where(gs != 0, bg * gs, np.nan)
    S['BG'] = np.where(np.isnan(bg), np.nan, bg * gs)
    S['BG'][gs == 0] = np.nan

    # D: 頭一つ抜け
    a = pd.Series(qa)
    ga = a.groupby(qrid)
    cnt = ga.transform('count').to_numpy()
    mx = ga.transform('max').to_numpy()
    # 自分以外の最大: 自分が最大なら 2 番目
    second = a.groupby(qrid).transform(lambda s: s.nlargest(2).iloc[-1] if s.count() >= 2 else np.nan).to_numpy()
    oth = np.where(qa >= mx, second, mx)
    S['D'] = np.where(cnt >= 2, qa - oth, np.nan)
    S['DS'] = np.where(cnt >= 2, ga.transform('std').to_numpy(), np.nan)
    print('B・D', flush=True)

    # ---------------- 確かめ(v8fa_probe と同じ)
    rr = ((q.Y3 - q.v7dpre_p3) * 100).to_numpy(float)
    clu = pd.factorize(q.track.astype(str) + '|' + q.race_date.astype(str))[0]
    yr = q.year.to_numpy()

    def cse_diff(ma, mb):
        z = np.zeros(N)
        z[ma] = (rr[ma] - rr[ma].mean()) / ma.sum()
        z[mb] = -(rr[mb] - rr[mb].mean()) / mb.sum()
        mm = ma | mb
        s = np.bincount(clu[mm], z[mm])
        G_ = len(np.unique(clu[mm]))
        return float(np.sqrt(G_ / (G_ - 1) * (s ** 2).sum()))

    def cse_mean(m):
        x, c = rr[m], clu[m]
        s = np.bincount(c, x - x.mean())
        G_ = len(np.unique(c))
        return float(np.sqrt(G_ / (G_ - 1) * (s ** 2).sum()) / len(x))

    R = {}
    for name in LAB:
        v = S[name]
        ok = ~np.isnan(v)
        rk = pd.Series(v[ok]).rank(method='first').to_numpy()
        qb = np.full(N, -1)
        qb[ok] = np.minimum((rk - 1) * 5 // ok.sum(), 4).astype(int)
        bins = [{'n': int((qb == b).sum()), 'r': float(rr[qb == b].mean()), 'se2': 2 * cse_mean(qb == b),
                 'lo': float(np.nanmin(v[qb == b])), 'hi': float(np.nanmax(v[qb == b]))} for b in range(5)]
        tp, bt = qb == 4, qb == 0
        diff = float(rr[tp].mean() - rr[bt].mean())
        se2 = 2 * cse_diff(tp, bt)
        yd = {int(y): float(rr[tp & (yr == y)].mean() - rr[bt & (yr == y)].mean()) for y in range(2016, 2022)}
        same = int(sum(np.sign(x) == np.sign(diff) for x in yd.values()))
        half = {}
        for lab, ys in (('16-18', (2016, 2017, 2018)), ('19-21', (2019, 2020, 2021))):
            hm = np.isin(yr, ys)
            half[lab] = float(rr[tp & hm].mean() - rr[bt & hm].mean())
        both = bool(np.sign(half['16-18']) == np.sign(half['19-21']) == np.sign(diff))
        flag = bool(abs(diff) >= 1.0 and abs(diff) > se2 and same >= 5 and both)
        R[name] = {'cov': float(ok.mean()), 'bins': bins, 'diff': diff, 'se2': se2, 'years': yd, 'same': same, 'half': half,
                   'both': both, 'flag': flag, 'worth': bool(abs(diff) >= 3.0)}
        print(name, round(float(ok.mean()), 3), round(diff, 2), round(se2, 2), same, half, flag, flush=True)
    info = {'rows': N, 'mean_r': float(rr.mean())}
    JS.write_text(json.dumps({'info': info, 'res': R}, ensure_ascii=False, indent=1), encoding='utf-8')
    write_md(R, info)


def write_md(R, info):
    fl = [n for n, x in R.items() if x['flag']]
    L = ['# 新しい材料 本命 5 個の見落とし確かめ(学習なし・探索期間 2016〜21)', '',
         f'決め = out/f5_plan.md。対象 v7d_final_preds.parquet {info["rows"]:,} 行・r = 実際の 3 着以内 − v7dpre_p3(×100 = ポイント)・全体の平均 {info["mean_r"]:+.2f}。', '',
         f'- 見落としの線(|上−下| ≥ 1.0・> 2SE・6 年中 5 年同じ向き・前半後半とも同じ向き)を越えたのは {len(fl)} 本' + (f'({"・".join(fl)})' if fl else '') + '。', '',
         '| 信号 | カバー率 | 段1(下) | 段2 | 段3 | 段4 | 段5(上) | 上−下 ±2SE | 年ごと 16〜21 | 同じ向き | 前半/後半 | 見落とし | 値打ち(≥3) |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for n, x in R.items():
        b = ' | '.join(f'{z["r"]:+.2f}±{z["se2"]:.2f}' for z in x['bins'])
        y = ' '.join(f'{v:+.1f}' for v in x['years'].values())
        hf = f'{x["half"]["16-18"]:+.2f}/{x["half"]["19-21"]:+.2f}'
        L.append(f'| {n} {LAB[n]} | {x["cov"]:.1%} | {b} | {x["diff"]:+.2f} ±{x["se2"]:.2f} | {y} | {x["same"]}/6 | {hf} | '
                 f'{"はい" if x["flag"] else "—"} | {"はい" if x["worth"] else "—"} |')
    doc = (__doc__ or '').split('■ 実装の決め(結果を見る前に固定)')[1]
    L += ['', '## 決めた式', '', '```', doc.strip('\n'), '```']
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('書いた', MD, flush=True)


if __name__ == '__main__':
    main()
