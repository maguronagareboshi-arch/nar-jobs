# -*- coding: utf-8 -*-
"""§190 案 2 ワイドの期待値で買う検証(AI の p 上位 6 頭の 15 組・12 か月の WF・1 点 100 円)。**読むだけ**(手元のファイルだけ)。

  py -3.12 -X utf8 pipeline/ai/wide_ev.py [--pred <wf1_pred_a.parquet>] [--pwin <wf1_win_pred.parquet>]
      [--flat <flat.parquet>] [--raw <raw の置き場>] [--payouts <tsv>]

- 候補= 各レースで p(3着内)の順位 6 位以内(同じ p は馬番の小さい方が上= ev_backtest.p_ranks)の 15 組。
  出走 6 頭未満は飛ばす。
- P(a,b)= p_win(レース内で Σ=1)を強さとした Plackett–Luce で、上位 3 着の並び n(n−1)(n−2) 通りを全部数え、
  a と b が両方入る並びの確率を足す(全組の Σ= 3)。
- w10= 外部の締切前オッズのワイド(下限)の時点のうち、時刻の字が単勝の t10 と同じもの。
  時刻が無い・ワイドの時点が無い・15 組のどれかが載っていない → **そのレースは飛ばす**(埋めない・数を表に出す)。
- q= (1/w10) ÷ Σ(載っている組の 1/w10) × 3(P と同じ尺= 全組で 3・複勝の §170 が 3 に揃えたのと同じ)。
  p′= (1−λ)P + λq。
- c_wide= 当たった組の「払戻 ÷ (最終の値×100)」を、組の w10 の帯 {<10, 10-29.9, 30-99.9, ≥100} 別に
  **その月より前の月だけ**で中央値(最初の月は 1)。⛔帯を後から動かさない。
- 買う組= p′×w10×c_wide ≥ τ(1 レース 0〜15 点)。⛔λ∈{0, 0.5}×τ∈{1.0, 1.2} の 4 組で終わり
  (後から組を足さない・場別/帯別に後から絞った組は採らない)。
- 相手= 15 組ボックス / AI ◎-○ 1 点 / AI ◎-○・◎-▲ 2 点 / 1-2 番人気 1 点(10 分前の単勝・同じなら馬番の小さい方)。
- 採る条件(事前に固定)= 最大 1 本抜き ≥ 100% かつ 100% 超の月 ≥ 7/12 かつ 点数 ≥ 3,000。
⛔自分の票でオッズが動く分は無視(100 円単位の仮定)。⛔表は標準出力だけ(出どころの社名・URL は書かない)。
"""
import argparse
import gzip
import json
import re
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ev_backtest import p_ranks  # noqa: E402
from exotic_ev import Book, pct  # noqa: E402
from odds_hist import HOME  # noqa: E402

TOP = 6
LAMBDAS = (0.0, 0.5)
TAUS = (1.0, 1.2)
GATE_ROI, GATE_MONTHS, GATE_POINTS = 1.0, 7, 3000
PLACES = 3
W_BANDS = ((0.0, 10.0, '<10'), (10.0, 30.0, '10-29.9'), (30.0, 100.0, '30-99.9'), (100.0, 1e12, '≥100'))


def w_band(v):
    return next(lab for lo, hi, lab in W_BANDS if lo <= v < hi)


def pair_probs(strength):
    """強さ(1 次元・レース内で Σ=1 に揃える)→ n×n の P(i と j が両方上位 3 着)。対角は 0・i<j の Σ= 3。
    Plackett–Luce の並び (1 着 i, 2 着 j, 3 着 k) の確率 s_i·s_j/(1−s_i)·s_k/(1−s_i−s_j) を全部並べて足す"""
    s = np.asarray(strength, dtype=float)
    s = s / s.sum()
    n = len(s)
    if n < PLACES:
        return None
    i, j, k = s[:, None, None], s[None, :, None], s[None, None, :]
    with np.errstate(divide='ignore', invalid='ignore'):
        T = i * (j / (1 - i)) * (k / (1 - i - j))
    eye = np.eye(n, dtype=bool)
    same = eye[:, :, None] | eye[:, None, :] | eye[None, :, :]          # 同じ馬が 2 回出る並びは無い
    T = np.nan_to_num(np.where(same, 0.0, T), nan=0.0, posinf=0.0, neginf=0.0)
    m12, m13, m23 = T.sum(axis=2), T.sum(axis=1), T.sum(axis=0)          # 組が 1-2 着・1-3 着・2-3 着
    return m12 + m12.T + m13 + m13.T + m23 + m23.T


def norm_pairs(d):
    """{'1-5': 1.8, …} → {(1, 5): 1.8}(小さい馬番が先・値の無い組は入れない)"""
    out = {}
    for key, v in (d or {}).items():
        nums = [int(x) for x in re.findall(r'\d+', str(key))]
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if len(nums) == 2 and nums[0] != nums[1] and v > 0:
            out[tuple(sorted(nums))] = v
    return out


def pick_wide(times, pops, label):
    """ワイドの時点のリスト(先頭は「最終」)から、時刻の字が label(単勝の t10)と同じ時点の {(a,b): 値}。無ければ None"""
    if not label or not times or not pops:
        return None
    for s, p in zip(times[1:], pops[1:]):
        if str(s).strip() == str(label).strip() and p:
            return norm_pairs(p)
    return None


def c_tables(obs, months):
    """obs= 月 → [(帯, 払戻 ÷ (最終×100))]。→ 月 → {帯: c}= **その月より前の月**の中央値(最初の月は 1)"""
    out, acc = {}, defaultdict(list)
    for ym in months:
        out[ym] = {lab: (statistics.median(acc[lab]) if acc[lab] else 1.0) for _lo, _hi, lab in W_BANDS}
        for b, r in obs.get(ym, []):
            acc[b].append(r)
    return out


def rid_key(rid):
    t, d, n = rid.split('|')
    return (d, t, int(n))


def load(pred, pwin, flat, raw, payouts, top=TOP):
    """→ (races, miss)。races= 日付順の dict(月・鍵・候補・15 組の行・c の材料・1-2 番人気・払戻)"""
    import pandas as pd
    pr = pd.read_parquet(pred, columns=['rid', 'runner_number', 'p'])
    ps = defaultdict(list)
    for rid, u, p in zip(pr['rid'], pr['runner_number'], pr['p']):
        ps[rid].append((int(u), float(p)))
    pw = defaultdict(dict)
    w = pd.read_parquet(pwin, columns=['rid', 'runner_number', 'p_win'])
    for rid, u, p in zip(w['rid'], w['runner_number'], w['p_win']):
        if p == p and p is not None:
            pw[rid][int(u)] = float(p)
    fl = pd.read_parquet(flat, columns=['track', 'race_date', 'race_no', 'runner_number', 't10', 'o10'])
    t10, o10 = {}, defaultdict(dict)
    for t, d, n, u, lab, o in zip(fl['track'], fl['race_date'], fl['race_no'], fl['runner_number'], fl['t10'], fl['o10']):
        key = (t, str(d), int(n))
        if lab and key not in t10:
            t10[key] = str(lab)
        if o is not None and o == o and o > 0:
            o10[key][int(u)] = float(o)
    pay = {}
    with open(payouts, encoding='utf-8') as f:
        for line in f:
            t, d, n, p = line.rstrip('\n').split('\t')
            hits = {}
            for x in json.loads(p):
                if x.get('t') == 'wide':
                    nums = [int(v) for v in re.findall(r'\d+', str(x.get('c')))]
                    if len(nums) == 2:
                        hits[tuple(sorted(nums))] = int(x.get('y') or 0)
            if hits:
                pay[(t, d, int(n))] = hits
    miss = defaultdict(lambda: defaultdict(int))
    races = []
    for rid in sorted(ps, key=rid_key):
        t, d, n = rid.split('|')
        key, ym = (t, d, int(n)), d[:7]
        miss[ym]['予測のレース'] += 1
        runners = ps[rid]
        if len(runners) < top:
            miss[ym]['出走 6 頭未満'] += 1
            continue
        ranks = p_ranks(runners)
        cand = sorted((u for u in ranks if ranks[u] <= top), key=lambda u: ranks[u])
        wp = pw.get(rid)
        if not wp or any(u not in wp for u, _ in runners):
            miss[ym]['勝つ確率の予測が無い'] += 1
            continue
        lab = t10.get(key)
        if not lab:
            miss[ym]['t10 の時刻が無い'] += 1
            continue
        fp = Path(raw) / f'{t}_{d}_r{n}.json.gz'
        if not fp.exists():
            miss[ym]['締切前オッズのファイルが無い'] += 1
            continue
        try:
            with gzip.open(fp, 'rt', encoding='utf-8') as fh:
                ri = json.load(fh)
        except (OSError, EOFError, ValueError):
            miss[ym]['締切前オッズが読めない'] += 1
            continue
        oi = ri.get('odds_info') or {}
        times = (oi.get('time_odds_times') or {}).get('wide')
        pops = (oi.get('time_pops') or {}).get('wide')
        if not times or not pops:
            miss[ym]['ワイドの時点が無い'] += 1
            continue
        w10 = pick_wide(times, pops, lab)
        if w10 is None:
            miss[ym]['t10 と同じ時刻のワイドが無い'] += 1
            continue
        pairs = list(combinations(sorted(cand), 2))
        if any(pp not in w10 for pp in pairs):
            miss[ym]['15 組のどれかが載っていない'] += 1
            continue
        hits = pay.get(key)
        if hits is None:
            miss[ym]['ワイドの払戻が無い'] += 1
            continue
        us = [u for u, _ in runners]
        idx = {u: i for i, u in enumerate(us)}
        P = pair_probs([wp[u] for u in us])
        inv = sum(1 / v for v in w10.values())
        rows = [dict(a=a, b=b, P=float(P[idx[a], idx[b]]), w=w10[(a, b)], q=(1 / w10[(a, b)]) / inv * PLACES,
                     pay=int(hits.get((a, b), 0)), band=w_band(w10[(a, b)])) for a, b in pairs]
        wfin = norm_pairs(pops[0])
        cobs = [(w_band(w10[k]), y / (wfin[k] * 100)) for k, y in hits.items() if k in w10 and k in wfin]
        pop12 = [u for u, _ in sorted(o10.get(key, {}).items(), key=lambda x: (x[1], x[0]))[:2]]
        miss[ym]['使ったレース'] += 1
        races.append(dict(ym=ym, key=key, cand=cand, rows=rows, cobs=cobs, pop=pop12, hits=hits))
    return races, miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pred', default=str(HOME / 'wf1_pred_a.parquet'))
    ap.add_argument('--pwin', default=str(HOME / 'wf1_win_pred.parquet'))
    ap.add_argument('--flat', default=str(HOME / 'keibaodds' / 'flat.parquet'))
    ap.add_argument('--raw', default=str(HOME / 'keibaodds' / 'raw'))
    ap.add_argument('--payouts', default=str(HOME / 'payouts_2024.tsv'))
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    races, miss = load(a.pred, a.pwin, a.flat, a.raw, a.payouts)
    months = sorted({r['ym'] for r in races})
    obs = defaultdict(list)
    for r in races:
        obs[r['ym']].extend(r['cobs'])
    cmap = c_tables(obs, months)

    combos = [(lam, tau) for lam in LAMBDAS for tau in TAUS]
    books = {c: Book() for c in combos}
    base = {'15 組ボックス': Book(), 'AI ◎-○ 1 点': Book(), 'AI ◎-○・◎-▲ 2 点': Book(), '1-2 番人気 1 点': Book()}
    band_sel = {c: defaultdict(Book) for c in combos}
    cal_P, cal_Y = [], []
    for r in races:
        ym, rows, hits = r['ym'], r['rows'], r['hits']

        def pay_of(x, y):
            return hits.get(tuple(sorted((x, y))), 0)
        base['15 組ボックス'].buy_many(ym, np.array([x['pay'] for x in rows], dtype=float))
        c1, c2, c3 = r['cand'][:3]
        base['AI ◎-○ 1 点'].buy_many(ym, np.array([pay_of(c1, c2)], dtype=float))
        base['AI ◎-○・◎-▲ 2 点'].buy_many(ym, np.array([pay_of(c1, c2), pay_of(c1, c3)], dtype=float))
        if len(r['pop']) == 2:
            base['1-2 番人気 1 点'].buy_many(ym, np.array([pay_of(*r['pop'])], dtype=float))
        for x in rows:
            cal_P.append(x['P'])
            cal_Y.append(1 if x['pay'] > 0 else 0)
        cm = cmap[ym]
        for lam, tau in combos:
            sel = [x for x in rows if ((1 - lam) * x['P'] + lam * x['q']) * x['w'] * cm[x['band']] >= tau]
            if sel:
                books[(lam, tau)].buy_many(ym, np.array([x['pay'] for x in sel], dtype=float))
                for x in sel:
                    band_sel[(lam, tau)][x['band']].buy_many(ym, np.array([x['pay']], dtype=float))

    used = len(races)
    print('# §190 案 2 ワイド × AI の p 上位 6 頭の 15 組(外部の締切前オッズ= 下限・確定の払戻)')
    print('\n## 揃ったレースと飛ばした数(月別)')
    mcols = ['予測のレース', '出走 6 頭未満', '勝つ確率の予測が無い', 't10 の時刻が無い', '締切前オッズのファイルが無い',
             '締切前オッズが読めない', 'ワイドの時点が無い', 't10 と同じ時刻のワイドが無い', '15 組のどれかが載っていない',
             'ワイドの払戻が無い', '使ったレース']
    print('| 月 | ' + ' | '.join(mcols) + ' |\n|---|' + '---|' * len(mcols))
    for ym in sorted(miss):
        print(f'| {ym} | ' + ' | '.join(str(miss[ym][c]) for c in mcols) + ' |')
    print('| 計 | ' + ' | '.join(str(sum(miss[m][c] for m in miss)) for c in mcols) + ' |')

    print('\n## c_wide(その月より前の月の中央値・最初の月は 1)= 払戻 ÷ (最終の値×100)・帯は w10')
    print('| 月 | ' + ' | '.join(lab for _l, _h, lab in W_BANDS) + ' |\n|---|' + '---|' * len(W_BANDS))
    for ym in months:
        print(f'| {ym} | ' + ' | '.join(f'{cmap[ym][lab]:.3f}' for _l, _h, lab in W_BANDS) + ' |')

    def row(name, bk):
        return (f'| {name} | {bk.n:,} | {bk.hit:,} | {pct(bk.hit / bk.n if bk.n else None)} | {pct(bk.roi())} | '
                f'{pct(bk.roi(1))} | {pct(bk.roi(3))} | {bk.over(months)}/{len(months)} | {bk.dd:,} | '
                f'{bk.n / used if used else 0:.2f} |')

    print(f'\n## 合計(12 か月・1 点 100 円・使ったレース {used:,})')
    print('| 買い方 | 点数 | 的中数 | 的中率 | 回収率 | 最大 1 本抜き | 上位 3 本抜き | 100% 超の月 | 最大ドローダウン(円) | 1 レースあたりの点数 |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    names = [(f'期待値 λ={lam} τ={tau}', books[(lam, tau)]) for lam, tau in combos] + list(base.items())
    for nm, bk in names:
        print(row(nm, bk))

    print('\n## 月別の回収率(点数)')
    print('| 買い方 | ' + ' | '.join(m[2:] for m in months) + ' |\n|---|' + '---|' * len(months))
    for nm, bk in names:
        print(f'| {nm} | ' + ' | '.join((f'{bk.month[m][1] / (bk.month[m][0] * 100) * 100:.0f}%({bk.month[m][0]:,})'
                                        if bk.month[m][0] else '—') for m in months) + ' |')

    print('\n## w10 の帯別= 期待値で選んだ組(読むだけ・採否に使わない)')
    print('| 帯 | ' + ' | '.join(f'λ={lam} τ={tau} 点数 | 回収率' for lam, tau in combos) + ' |')
    print('|---|' + '---|---|' * len(combos))
    for _lo, _hi, lab in W_BANDS:
        print(f'| {lab} | ' + ' | '.join(f'{band_sel[c][lab].n:,} | {pct(band_sel[c][lab].roi())}' for c in combos) + ' |')

    print('\n## 較正の診断(15 組の P(a,b) を 10 等分・読むだけ)= 予想 P の平均 / 実際の的中率')
    P, Y = np.array(cal_P), np.array(cal_Y)
    if len(P):
        idx = np.argsort(P, kind='stable')
        print(f'| 帯 | 組 | 予想 P の平均 | 実際の的中率 |\n|---|---|---|---|')
        for i, part in enumerate(np.array_split(idx, 10)):
            print(f'| {i + 1} | {len(part):,} | {P[part].mean():.4f} | {Y[part].mean():.4f} |')

    print(f'\n## 採る条件(最大 1 本抜き ≥ 100% かつ 100% 超の月 ≥ {GATE_MONTHS}/12 かつ 点数 ≥ {GATE_POINTS:,})')
    ok_any = []
    for lam, tau in combos:
        bk = books[(lam, tau)]
        r1, mo = bk.roi(1), bk.over(months)
        ok = r1 is not None and r1 >= GATE_ROI and mo >= GATE_MONTHS and bk.n >= GATE_POINTS
        print(f'- ワイド λ={lam} τ={tau}: 最大 1 本抜き {pct(r1)}・100% 超の月 {mo}/{len(months)}・点数 {bk.n:,} → '
              f'{"満たす" if ok else "満たさない"}')
        if ok:
            ok_any.append(f'λ={lam} τ={tau}')
    print('- 判定: ' + ('満たす組あり= ' + '・'.join(ok_any) if ok_any else '4 組とも満たさない'))


if __name__ == '__main__':
    main()
