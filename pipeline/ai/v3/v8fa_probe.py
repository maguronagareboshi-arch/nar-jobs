# -*- coding: utf-8 -*-
"""第 8 版 FABLE の案(厩舎の上積み・得意条件への戻り・走りの型の戻り・好走時の体重との差・単騎度)の見落とし確かめ(学習なし)。
決め = out/v8fa_plan.md(変えない)。見方は src/v8fm_probe.py と同じ(r = Y3 − v7dpre_p3・5 等分・開催日ごとの誤差・年ごとの向き・レース内 1 位)。

  py -3.12 -X utf8 src/v8fa_probe.py

■ 実装の決め(結果を見る前・式に幅がある所はここで 1 つに決めた)
  共通: 「前」= レースの日より前の走りだけ。2022 年以降は読んだ直後に捨てて assert。SI・a_ab・ten_i = t4_base(南関)。全 NAR = v7c_run.sources の取消・除外を除く走り(馬 = hid)。
  案 1 e = SI − a_ab(南関の走り・両方ある走り)。調教師 = vc.norm(trainer)。自分の馬の走りは除く(v8fm と同じ)。
    TP 厩舎の上積み = 前 730 日の e の和 ÷ (走数 + 30)。走数 0 は欠け。
    TS 厩舎のぶれ = 前 730 日の e の標準偏差(走数 10 未満は欠け)。
    TG 預かってからの伸び = 全 NAR で調教師が変わった所を「預かり」とし、新しい厩舎で 5 走続いた預かりだけ使う。
       伸び = 新しい厩舎の 3〜5 走目の SI 平均 − 預かる前 3 走の SI 平均(SI は南関の走りだけ・両側 1 走以上)。
       その預かりは 5 走目の日に分かるものとし、調教師ごとに前の全期間の伸びの和 ÷ (頭数 + 10)。0 頭は欠け。
  案 2 前走 = t4_base(南関)の SI のある前の走りの一番新しいもの。距離帯 = 〜1200・1201〜1500・1501〜1800・1801〜。
    CB 得意条件への戻り = (今回の場 × 距離帯での前の SI 平均) − (前走の場 × 距離帯での前の SI 平均)。どちらか 2 走未満は欠け。
       今回と前走が同じ条件なら 0。CB4 = CB を前走 4 着以下(着順が数字で 4 以上)の行だけに絞ったもの。昇級の補助(cond_back_g)は作らない。
  案 3 全 NAR。位置比 = 最初の角の位置 ÷ その角の頭数(t4_day3.first_corner)。上がり順位比 = レース内の上がり 3F の順位(小さいほど速い・同着は平均)÷ 上がりのある頭数。
    好走 = 3 着以内・730 日以内・値あり、2 回以上。P* = 好走時の位置比の平均。dev1 = |前走の位置比 − P*|・dev25 = 2〜5 走前の |位置比 − P*| の平均(1 走以上)。
    SB 型の戻り(位置) = dev25 − dev1。UB 型の戻り(上がり) = 同じ形を上がり順位比で。前走 = 全 NAR の一番新しい前の走り。
  案 4 全 NAR。馬体重 = runs.body_weight(数字でないものは欠け)。前走が 90 日以内の行だけ(ほかは欠け)。
    BL = 前走の体重 − 好走(3 着以内・1095 日以内・体重あり・1 回以上)の平均体重。BT = 前走 − 前々走の体重。
    BS = 前走の体重 − この馬の前の走りのうち今回と同じ月(暦の月)の体重の平均(1 走以上・前走も含む)。
  案 6 前半の速さの点 = この馬の前の走りのうち ten_i のある新しい方から 5 つの平均(1 つ以上)。レース(予想の対象の行)で 1 位の馬だけ、1 位 − 2 位(同点は 0)。
    ほかの馬は欠け。値のある馬が 2 頭未満のレースは欠け。レース内 1 位 − 他は 1 レース 1 頭なので出さない。
  i_t3 との相関は読む範囲の表に i_t3 が無いため測っていない。
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
MD = REPO / 'out' / 'v8fa_check.md'
JS = REPO / 'out' / 'v8fa_check.json'
KEY = d3.KEY
CUT = '2022-01-01'
BIG = 100000
LAB = {'TP': '案1 厩舎の上積み(馬の力を除いた残りの平均)', 'TS': '案1 厩舎のぶれ(残りのばらつき)',
       'TG': '案1 預かってからの伸び(厩舎平均)', 'CB': '案2 得意条件への戻り(今回の条件の SI − 前走の条件の SI)',
       'CB4': '案2 同じ・前走 4 着以下だけ', 'SB': '案3 走りの型の戻り(位置取り)', 'UB': '案3 走りの型の戻り(上がり)',
       'BL': '案4 前走の体重 − 好走時の体重', 'BT': '案4 前走 − 前々走の体重', 'BS': '案4 前走の体重 − 同じ月の体重',
       'TEN': '案6 単騎度(前半の速さ 1 位の馬の 2 位との差)'}


def dbin4(d):
    d = pd.to_numeric(d, errors='coerce').to_numpy(float)
    b = np.full(len(d), np.nan)
    b[d <= 1200] = 0
    b[(d > 1200) & (d <= 1500)] = 1
    b[(d > 1500) & (d <= 1800)] = 2
    b[d > 1800] = 3
    return b


def t_signals(t):
    """t4_base(hk・dnum の順)の行ごとに CB・前走の着順・前半の点を出す。"""
    t = t.sort_values(['hk', 'dnum'], kind='mergesort').reset_index(drop=True)
    CB, PF, TEN = (np.full(len(t), np.nan) for _ in range(3))
    hk = t.hk.to_numpy()
    starts = np.r_[0, np.nonzero(hk[1:] != hk[:-1])[0] + 1, len(t)]
    D = t.dnum.to_numpy()
    S = t.SI.to_numpy(float)
    TI = t.ten_i.to_numpy(float)
    TR = pd.factorize(t.track)[0]
    B = t.db4.to_numpy(float)
    F = pd.to_numeric(t.finish, errors='coerce').to_numpy(float)
    for a, b in zip(starts[:-1], starts[1:]):
        for i in range(a, b):
            pr = D[a:i] < D[i]
            if not pr.any():
                continue
            idx = np.arange(a, i)[pr]
            tv = TI[idx]
            tv = tv[~np.isnan(tv)]
            if len(tv):
                TEN[i] = tv[-5:].mean()
            idx = idx[~np.isnan(S[idx])]
            if not len(idx):
                continue
            last = idx[-1]
            PF[i] = F[last]
            now = (TR[idx] == TR[i]) & (B[idx] == B[i])
            prv = (TR[idx] == TR[last]) & (B[idx] == B[last])
            if now.sum() >= 2 and prv.sum() >= 2:
                CB[i] = S[idx][now].mean() - S[idx][prv].mean()
    t['CB'], t['pfin'], t['ten5'] = CB, PF, TEN
    return t


def nar_signals(r, q):
    """全 NAR の走り r から q の各行の SB・UB・BL・BT・BS。"""
    s = r[['hid', 'dnum', 't3', 'pr', 'ur', 'bw', 'month']].dropna(subset=['hid']).sort_values(['hid', 'dnum'], kind='mergesort')
    out = {k: np.full(len(q), np.nan) for k in ('SB', 'UB', 'BL', 'BT', 'BS')}
    grp = s.groupby('hid', sort=False).indices
    D, T3, PR, UR, BW, MO = (s[c].to_numpy(float) for c in ('dnum', 't3', 'pr', 'ur', 'bw', 'month'))
    qh, qd = q.hid.to_numpy(), q.dnum.to_numpy(float)
    qm = pd.to_datetime(q.race_date).dt.month.to_numpy(float)
    for j in range(len(q)):
        ix = grp.get(qh[j]) if isinstance(qh[j], str) else None
        if ix is None:
            continue
        d = D[ix]
        k = np.searchsorted(d, qd[j], side='left')
        if k == 0:
            continue
        p = ix[:k]
        age = qd[j] - D[p]
        for key, V in (('SB', PR), ('UB', UR)):
            v = V[p]
            g = (T3[p] == 1) & (age <= 730) & ~np.isnan(v)
            if g.sum() >= 2:
                st = v[g].mean()
                d1 = abs(v[-1] - st)
                w = v[max(k - 5, 0):k - 1]
                w = w[~np.isnan(w)]
                if not np.isnan(d1) and len(w):
                    out[key][j] = np.abs(w - st).mean() - d1
        if age[-1] <= 90 and not np.isnan(BW[p[-1]]):
            bl = BW[p[-1]]
            bw = BW[p]
            g = (T3[p] == 1) & (age <= 1095) & ~np.isnan(bw)
            if g.any():
                out['BL'][j] = bl - bw[g].mean()
            if k >= 2 and not np.isnan(bw[-2]):
                out['BT'][j] = bl - bw[-2]
            g = (MO[p] == qm[j]) & ~np.isnan(bw)
            if g.any():
                out['BS'][j] = bl - bw[g].mean()
    return out


def trainer_gain(r):
    """預かり(調教師が変わった所)ごとの伸びと、分かる日。"""
    s = r[['hid', 'dnum', 'trainer', 'SI']].dropna(subset=['hid', 'trainer']).sort_values(['hid', 'dnum'], kind='mergesort')
    rows = []
    for hid, g in s.groupby('hid', sort=False):
        tr, d, si = g.trainer.to_numpy(), g.dnum.to_numpy(), g.SI.to_numpy(float)
        for i in range(1, len(g)):
            if tr[i] == tr[i - 1] or i + 4 >= len(g):
                continue
            if not (tr[i:i + 5] == tr[i]).all():
                continue
            bef, aft = si[max(i - 3, 0):i], si[i + 2:i + 5]
            bef, aft = bef[~np.isnan(bef)], aft[~np.isnan(aft)]
            if len(bef) and len(aft):
                rows.append((tr[i], hid, int(d[i + 4]), aft.mean() - bef.mean()))
    ev = pd.DataFrame(rows, columns=['trainer', 'hid', 'dnum', 'g'])
    ev['one'] = 1.0
    return ev


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
    r['dnum'] = d3.dnum_of(r.race_date)
    r['month'] = pd.to_datetime(r.race_date).dt.month.astype(float)
    r['trainer'] = r.trainer.map(lambda x: vc.norm(x) if isinstance(x, str) and x.strip() else None)
    pos, n = d3.first_corner(r)
    r['pr'] = pos / np.where(n > 0, n, np.nan)
    l3 = pd.to_numeric(r.f_l3, errors='coerce').where(lambda x: x > 0)
    r['l3'] = l3
    g = r.groupby(KEY).l3
    r['ur'] = g.rank(method='average') / g.transform('count')
    r['bw'] = pd.to_numeric(r.body_weight, errors='coerce').where(lambda x: x > 0)
    print('走り', len(r), flush=True)

    t = pd.read_parquet(V3 / 't4_base_2014_2021.parquet',
                        columns=KEY + ['runner_number', 'hk', 'distance_m', 'finish', 'SI', 'a_ab', 'ten_i'])
    t = t.rename(columns={'runner_number': 'umaban'})
    t = vo.nk(t)
    assert t.race_date.max() < CUT
    t['dnum'] = d3.dnum_of(t.race_date)
    t['db4'] = dbin4(t.distance_m)
    t = t_signals(t)
    print('SI の信号', len(t), flush=True)

    P = vo.nk(pd.read_parquet(V3 / 'v7d_final_preds.parquet'))
    assert P.race_date.max() < CUT
    q = P[KEY + ['umaban', 'year', 'n', 'Y3', 'v7dpre_p3']].merge(r[KEY + ['umaban', 'hid', 'trainer']],
                                                                    on=KEY + ['umaban'], how='left', validate='1:1')
    q = q.merge(t[KEY + ['umaban', 'CB', 'pfin', 'ten5']], on=KEY + ['umaban'], how='left', validate='1:1')
    q['dnum'] = d3.dnum_of(q.race_date)
    link = {'hid': float(q.hid.notna().mean()), 'trainer': float(q.trainer.notna().mean()),
            'si_row': float(q.pfin.notna().mean())}
    print('つながり', link, flush=True)
    S = {}

    # 案 1
    rs = r.merge(t[KEY + ['umaban', 'SI', 'a_ab']], on=KEY + ['umaban'], how='left', validate='1:1')
    e = rs[rs.trainer.notna() & rs.SI.notna() & rs.a_ab.notna()].copy()
    e['e'] = e.SI - e.a_ab
    e['e2'] = e.e ** 2
    e['one'] = 1.0
    cols = ['e', 'e2', 'one']
    A = d3.wsum(e, ['trainer'], cols, q, 730) - np.nan_to_num(d3.wsum(e, ['trainer', 'hid'], cols, q, 730))
    nn = A[:, 2]
    with np.errstate(invalid='ignore', divide='ignore'):
        v = A[:, 0] / (nn + 30)
        v[~(nn > 0)] = np.nan
        S['TP'] = v
        m = A[:, 0] / nn
        sd = np.sqrt(np.maximum(A[:, 1] / nn - m ** 2, 0) * nn / np.maximum(nn - 1, 1))
        sd[~(nn >= 10)] = np.nan
        S['TS'] = sd
    ev = trainer_gain(rs)
    print('預かり', len(ev), flush=True)
    G = d3.wsum(ev, ['trainer'], ['g', 'one'], q, BIG) - np.nan_to_num(d3.wsum(ev, ['trainer', 'hid'], ['g', 'one'], q, BIG))
    with np.errstate(invalid='ignore'):
        v = G[:, 0] / (G[:, 1] + 10)
    v[~(G[:, 1] > 0)] = np.nan
    S['TG'] = v
    print('案 1', flush=True)

    # 案 2
    S['CB'] = q.CB.to_numpy(float)
    v = S['CB'].copy()
    v[~(q.pfin.to_numpy(float) >= 4)] = np.nan
    S['CB4'] = v

    # 案 3・4
    o = nar_signals(r, q)
    for k in ('SB', 'UB', 'BL', 'BT', 'BS'):
        S[k] = o[k]
    print('案 3・4', flush=True)

    # 案 6
    rid = pd.factorize(q.track.astype(str) + '|' + q.race_date.astype(str) + '|' + q.race_no.astype(str))[0]
    T = pd.DataFrame({'rid': rid, 'v': q.ten5.to_numpy(float), 'i': np.arange(len(q))}).dropna(subset=['v'])
    T = T.sort_values(['rid', 'v'], ascending=[True, False], kind='mergesort')
    T['k'] = T.groupby('rid').cumcount()
    top = T[T.k == 0].set_index('rid')
    sec = T[T.k == 1].set_index('rid')
    top = top.join(sec.v.rename('v2'), how='inner')
    v = np.full(len(q), np.nan)
    v[top.i.to_numpy()] = (top.v - top.v2).to_numpy()
    S['TEN'] = v

    # ---------------- 確かめ(v8fm_probe と同じ)
    rr = ((q.Y3 - q.v7dpre_p3) * 100).to_numpy(float)
    clu = pd.factorize(q.track.astype(str) + '|' + q.race_date.astype(str))[0]
    yr = q.year.to_numpy()
    N = len(q)

    def cse_mean(m):
        x, c = rr[m], clu[m]
        e_ = x - x.mean()
        s = np.bincount(c, e_)
        G_ = len(np.unique(c))
        return float(np.sqrt(G_ / (G_ - 1) * (s ** 2).sum()) / len(x))

    def cse_diff(ma, mb):
        z = np.zeros(N)
        z[ma] = (rr[ma] - rr[ma].mean()) / ma.sum()
        z[mb] = -(rr[mb] - rr[mb].mean()) / mb.sum()
        mm = ma | mb
        s = np.bincount(clu[mm], z[mm])
        G_ = len(np.unique(clu[mm]))
        return float(np.sqrt(G_ / (G_ - 1) * (s ** 2).sum()))

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
        tp, bt = qb == 4, qb == 0
        diff = float(rr[tp].mean() - rr[bt].mean())
        se2 = 2 * cse_diff(tp, bt)
        yd = {int(y): float(rr[tp & (yr == y)].mean() - rr[bt & (yr == y)].mean()) for y in range(2016, 2022)}
        same = int(sum(np.sign(x) == np.sign(diff) for x in yd.values()))
        TT = pd.DataFrame({'rid': rid[ok], 'v': v[ok], 'i': np.nonzero(ok)[0]})
        g = TT.groupby('rid').v
        TT = TT[(g.transform('size') >= 2) & (g.transform('nunique') >= 2)]
        d1 = s1 = None
        n1 = 0
        if len(TT):
            is1 = (TT.v == TT.groupby('rid').v.transform('max')).to_numpy()
            m1, m0 = np.zeros(N, bool), np.zeros(N, bool)
            m1[TT.i.to_numpy()[is1]] = True
            m0[TT.i.to_numpy()[~is1]] = True
            d1 = float(rr[m1].mean() - rr[m0].mean())
            s1 = 2 * cse_diff(m1, m0)
            n1 = int(m1.sum())
        flag = bool(abs(diff) >= 1.0 and abs(diff) > se2 and same >= 5)
        worth = bool(abs(diff) >= 3.0)
        R[name] = {'cov': cov, 'bins': bins, 'diff': diff, 'se2': se2, 'years': yd, 'same': same,
                   'in1': d1, 'in1_se2': s1, 'in1_n': n1, 'flag': flag, 'worth': worth}
        print(name, round(cov, 3), round(diff, 2), round(se2, 2), same, flag, worth, flush=True)
    info = {'rows': N, 'runs': len(r), 'si_rows': len(t), 'events': len(ev), 'link': link, 'mean_r': float(rr.mean())}
    JS.write_text(json.dumps({'info': info, 'res': R}, ensure_ascii=False, indent=1), encoding='utf-8')
    write_md(R, info)


def write_md(R, info):
    fl = [n for n, x in R.items() if x['flag']]
    wo = [n for n, x in R.items() if x['worth']]
    big = max(R, key=lambda n: abs(R[n]['diff']))
    cov = [x['cov'] for x in R.values()]
    L = ['# FABLE の案(厩舎の上積み・得意条件への戻り・走りの型の戻り・体重・単騎度)の見落とし確かめ(第 8 版の下調べ・学習なし)', '',
         '## 要約', '',
         f'1. 厩舎が馬を見込みより走らせる度合い・得意な場と距離に戻る度合い・いつもの走り方に戻った度合い・好走したときの体重との差・楽に逃げられる度合いの目安を {len(R)} 個作り、今の予想の見込みと実際の 3 着以内のずれを比べた。',
         f'2. 目安が高い馬ほど見込みより多く(または少なく)来ているなら「見落とし」。決めた線を越えたのは {len(fl)} 個' + (f'({"・".join(fl)})。' if fl else '。'),
         f'3. ずれが一番大きかったのは {big}「{LAB[big]}」で、上の 2 割と下の 2 割の差 {R[big]["diff"]:+.2f} ポイント(ぶれの幅 ±{R[big]["se2"]:.2f})。',
         f'4. 作って試す値打ちの線(差 3 ポイント以上)を越えたのは {len(wo)} 個' + (f'({"・".join(wo)})。' if wo else '。') + f' 目安が作れた馬の割合は {min(cov):.0%}〜{max(cov):.0%}。',
         '5. ' + ('線を越えた目安は、次に材料として作って試す候補。' if wo else
                  '今の予想は、厩舎の腕・得意条件・走り方・体重・逃げやすさをほぼ拾えている(ずれは小さい)。'), '',
         '## 信号ごとの表', '',
         f'対象 = v7d_final_preds.parquet(2016〜2021・南関){info["rows"]:,} 行。r = 実際の 3 着以内 − v7dpre_p3(×100 = ポイント)。全体の r の平均 {info["mean_r"]:+.2f}。'
         f' 全 NAR の走り {info["runs"]:,}・SI の走り {info["si_rows"]:,}・預かり {info["events"]:,} 件。つながり: '
         + '・'.join(f'{k} {v:.1%}' for k, v in info['link'].items()) + '。', '',
         '| 信号 | カバー率 | 段1(下) | 段2 | 段3 | 段4 | 段5(上) | 上−下 ±2SE | 年ごと(16〜21) | 同じ向き | レース内1位−他 ±2SE | 見落とし | 作って試す値打ち |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for n, x in R.items():
        b = ' | '.join(f'{z["r"]:+.2f}±{z["se2"]:.2f}' for z in x['bins'])
        y = ' '.join(f'{v:+.1f}' for v in x['years'].values())
        i1 = f'{x["in1"]:+.2f} ±{x["in1_se2"]:.2f}' if x['in1'] is not None else '—(1 レース 1 頭)'
        L.append(f'| {n} {LAB[n]} | {x["cov"]:.1%} | {b} | {x["diff"]:+.2f} ±{x["se2"]:.2f} | {y} | {x["same"]}/6 | '
                 f'{i1} | {"はい" if x["flag"] else "—"} | {"はい" if x["worth"] else "—"} |')
    L += ['', '- 段ごとの頭数と値の範囲は out/v8fa_check.json。',
          '- 見落とし = |上 − 下| ≥ 1.0 かつ > 2 × 標準誤差(開催 = 場 × 日)かつ 6 年中 5 年以上同じ向き。作って試す値打ち = |上 − 下| ≥ 3.0(out/v8fa_plan.md・変えていない)。', '',
          '## 線を越えた信号', '']
    L += [f'- {n}: 上−下 {R[n]["diff"]:+.2f}(±{R[n]["se2"]:.2f})・{R[n]["same"]}/6 年・カバー率 {R[n]["cov"]:.1%}'
          f'・{"作って試す値打ちあり" if R[n]["worth"] else "値打ちの線には届かず"}' for n in fl] or ['- なし']
    doc = (__doc__ or '').split('■ 実装の決め(結果を見る前・式に幅がある所はここで 1 つに決めた)')[1]
    L += ['', '## 決めた式(結果を見る前に src/v8fa_probe.py に固定)', '', '```', doc.strip('\n'), '```']
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('書いた', MD, flush=True)


if __name__ == '__main__':
    main()
