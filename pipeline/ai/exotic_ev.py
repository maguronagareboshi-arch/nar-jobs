# -*- coding: utf-8 -*-
"""§170 段 2 B/C 三連単・馬単の期待値で買う検証(12 か月・1 点 100 円)。**読むだけ**(手元のファイルだけ)。

  py -3.12 -X utf8 pipeline/ai/exotic_ev.py [--kinds sanrentan,umatan] [--pwin <wf1_win_pred.parquet>]

- 材料= 10 分前の単勝 o10(keibaodds flat)× 楽天の確定オッズの全組(rakuten/*.parquet)× 確定の払戻(payouts tsv)。
  **3 つ揃うレースだけ**(揃わない数は月別に表へ)。
- 各馬の勝つ確率 q= (1/o10) ÷ Σ(1/o10)。順番付きの確率= Harville 式
  P(i→j→k)= q_i·q_j/(1−q_i)·q_k/(1−q_i−q_j)・P(i→j)= q_i·q_j/(1−q_i)。
- EV= P × **確定** odds(c=1= **甘い側の近似**= 締切前に買う人は確定オッズを知らない)。買う組= EV ≥ τ・τ∈{1.0, 1.2}。
- AI あり(C)= p′= (1−λ)·p_win + λ·q・λ= 0.5(p_win はレース内で Σ=1 に揃える)。--pwin があるときだけ横に並べる。
- 相手= ①確定 odds がいちばん低い組 ②10 分前の単勝人気 1→2(→3)の組 ③AI ◎→○(→▲)(p_top3 の上位)④全組買い。
- 採る条件(事前に固定)= 最大 1 本抜き ≥ 100% かつ 100% 超の月 ≥ 7/12 かつ 点数 ≥ 3,000。⛔τ・λ を後から動かさない。
⛔自分の票でオッズが動く分は無視(100 円単位の仮定)。⛔表は標準出力だけ。
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds_hist import HOME  # noqa: E402

TAUS = (1.0, 1.2)
LAM = 0.5
GATE_ROI, GATE_MONTHS, GATE_POINTS = 1.0, 7, 3000
VENUES = ('高知', '門別', '大井', '船橋', '川崎', '浦和')
KIND = {
    'sanrentan': ('trifecta', 3, ((0, 50, '〜50'), (50, 200, '50-200'), (200, 1000, '200-1000'), (1000, 1e12, '1000 超'))),
    # ⚠馬単の帯は設計に字が無い= 三連単の 1/5 ぐらいの刻み
    'umatan': ('exacta', 2, ((0, 10, '〜10'), (10, 30, '10-30'), (30, 100, '30-100'), (100, 1e12, '100 超'))),
}
EV_BANDS = ((1.0, 1.2, '1.0-1.2'), (1.2, 1.5, '1.2-1.5'), (1.5, 2.0, '1.5-2'), (2.0, 1e12, '2 以上'))


class Book:
    def __init__(self):
        self.pays, self.n, self.hit = [], 0, 0
        self.cum, self.peak, self.dd = 0, 0, 0
        self.month = defaultdict(lambda: [0, 0])
        self.races = 0

    def buy_many(self, ym, pays):
        """pays= その回に買った組の払戻(円)の配列(外れは 0)"""
        k = len(pays)
        if not k:
            return
        self.races += 1
        tot = int(pays.sum())
        self.n += k
        hits = pays[pays > 0]
        self.hit += len(hits)
        self.pays.extend(int(x) for x in hits)
        self.month[ym][0] += k
        self.month[ym][1] += tot
        # 1 レースの中の順番は問わない= レースの終わりで損益を足す(ドローダウンはレース単位)
        self.cum += tot - 100 * k
        self.peak = max(self.peak, self.cum)
        self.dd = max(self.dd, self.peak - self.cum)

    def roi(self, drop=0):
        if not self.n:
            return None
        return (sum(self.pays) - sum(sorted(self.pays, reverse=True)[:drop])) / (self.n * 100)

    def over(self, months):
        return sum(1 for m in months if self.month[m][0] and self.month[m][1] > self.month[m][0] * 100)


def pct(v):
    return '—' if v is None else f'{v * 100:.1f}%'


def load_common(flat, pred, pwin, tsv):
    import pandas as pd
    fl = pd.read_parquet(flat, columns=['track', 'race_date', 'race_no', 'runner_number', 'o10', 'fin'])
    o10, fin = defaultdict(dict), defaultdict(dict)
    for t, d, n, u, o, f in zip(fl['track'], fl['race_date'], fl['race_no'], fl['runner_number'], fl['o10'], fl['fin']):
        key = (t, str(d), int(n))
        if o == o and o is not None and o > 0:
            o10[key][int(u)] = float(o)
        if f == f and f is not None and f > 0:
            fin[key][int(u)] = float(f)
    pr = pd.read_parquet(pred, columns=['rid', 'runner_number', 'p'])
    marks = defaultdict(list)
    for rid, u, p in sorted(zip(pr['rid'], pr['runner_number'], pr['p']), key=lambda x: (x[0], -x[2], x[1])):
        t, d, n = rid.split('|')
        marks[(t, d, int(n))].append(int(u))
    pw = None
    if pwin and Path(pwin).exists():
        w = pd.read_parquet(pwin, columns=['rid', 'runner_number', 'p_win'])
        pw = defaultdict(dict)
        for rid, u, p in zip(w['rid'], w['runner_number'], w['p_win']):
            t, d, n = rid.split('|')
            pw[(t, d, int(n))][int(u)] = float(p)
    pay = {}
    with open(tsv, encoding='utf-8') as f:
        for line in f:
            t, d, n, p = line.rstrip('\n').split('\t')
            pay[(t, d, int(n))] = json.loads(p)
    return o10, fin, marks, pw, pay


def harville(q, a, b, c=None):
    """q= 馬番 → 確率の配列(添字= 馬番)。a,b,(c)= 組の馬番の配列"""
    qa, qb = q[a], q[b]
    p = qa * qb / np.clip(1 - qa, 1e-9, None)
    if c is not None:
        qc = q[c]
        p = p * qc / np.clip(1 - qa - qb, 1e-9, None)
    return p


def run_kind(kind, rak_dir, o10, fin, marks, pw, pay):
    import pandas as pd
    tick, r, obands = KIND[kind]
    df = pd.read_parquet(Path(rak_dir) / f'{kind}.parquet')
    cols = ['first', 'second'] + (['third'] if r == 3 else [])
    modes = ['AI なし'] + (['AI あり λ=0.5'] if pw is not None else [])
    books = {(m, t): Book() for m in modes for t in TAUS}
    base = {'確定 odds 最低の組': Book(), '単勝人気順の組': Book(), 'AI ◎○▲ の組': Book(), '全組買い': Book()}
    ev_band = {m: defaultdict(Book) for m in modes}
    o_band = {(m, t): defaultdict(Book) for m in modes for t in TAUS}
    o_all = defaultdict(Book)
    v_book = {(m, t): defaultdict(Book) for m in modes for t in TAUS}
    v_all = defaultdict(Book)
    calib = {m: ([], []) for m in modes}
    miss = defaultdict(lambda: defaultdict(int))
    months = set()
    groups = df.groupby(['track', 'race_date', 'race_no'], sort=False)
    order = sorted(groups.groups.keys(), key=lambda k: (k[1], k[0], k[2]))
    for key in order:
        g = groups.get_group(key)
        t, d, n = key[0], str(key[1]), int(key[2])
        k3 = (t, d, n)
        ym = d[:7]
        months.add(ym)
        miss[ym]['組のあるレース'] += 1
        qo = o10.get(k3)
        if not qo or len(qo) < r + 1:
            miss[ym]['10 分前の単勝が無い'] += 1
            continue
        hits = [x for x in pay.get(k3, []) if x.get('t') == tick]
        if not hits:
            miss[ym]['払戻が無い'] += 1
            continue
        paid = {tuple(int(v) for v in re.findall(r'\d+', str(h['c']))): int(h['y']) for h in hits}
        maxu = max(max(qo), int(g[cols].values.max())) + 1
        inv = np.zeros(maxu)
        for u, o in qo.items():
            inv[u] = 1 / o
        q = inv / inv.sum()
        arr = g[cols].values.astype(int)
        odds = g['odds'].values.astype(float)
        ok = np.all(q[arr] > 0, axis=1)
        if not ok.all():
            miss[ym]['組の馬に 10 分前の単勝が無い組'] += int((~ok).sum())
        arr, odds = arr[ok], odds[ok]
        if not len(arr):
            miss[ym]['買える組が無い'] += 1
            continue
        pays = np.array([paid.get(tuple(x), 0) for x in arr], dtype=float)
        miss[ym]['使ったレース'] += 1
        vn = t if t in VENUES else 'その他'
        # 相手
        i_min = int(np.lexsort((arr[:, 1], arr[:, 0], odds))[0])
        base['確定 odds 最低の組'].buy_many(ym, pays[[i_min]])
        pop = [u for u, _ in sorted(qo.items(), key=lambda x: (x[1], x[0]))][:r]
        for name, want in (('単勝人気順の組', pop), ('AI ◎○▲ の組', marks.get(k3, [])[:r])):
            if len(want) == r:
                hit = np.all(arr == np.array(want), axis=1)
                if hit.any():
                    base[name].buy_many(ym, pays[hit])
                else:
                    miss[ym][f'{name}が表に無い'] += 1
        base['全組買い'].buy_many(ym, pays)
        for lo, hi, lab in obands:
            sel = (odds >= lo) & (odds < hi)
            if sel.any():
                o_all[lab].buy_many(ym, pays[sel])
        v_all[vn].buy_many(ym, pays)
        # 期待値
        for m in modes:
            if m == 'AI なし':
                prob = q
            else:
                wp = pw.get(k3)
                if not wp or any(u not in wp for u in qo):
                    miss[ym]['勝つ確率の予測が無い(AI あり)'] += 1
                    continue
                w = np.zeros(maxu)
                for u in qo:
                    w[u] = wp[u]
                w = w / w.sum()
                prob = (1 - LAM) * w + LAM * q
            P = harville(prob, arr[:, 0], arr[:, 1], arr[:, 2] if r == 3 else None)
            ev = P * odds
            calib[m][0].append(P.astype(np.float32))
            calib[m][1].append((pays > 0).astype(np.int8))
            for tau in TAUS:
                buy = ev >= tau
                if buy.any():
                    books[(m, tau)].buy_many(ym, pays[buy])
                    v_book[(m, tau)][vn].buy_many(ym, pays[buy])
                    for lo, hi, lab in obands:
                        sel = buy & (odds >= lo) & (odds < hi)
                        if sel.any():
                            o_band[(m, tau)][lab].buy_many(ym, pays[sel])
            for lo, hi, lab in EV_BANDS:
                sel = (ev >= lo) & (ev < hi)
                if sel.any():
                    ev_band[m][lab].buy_many(ym, pays[sel])
    months = sorted(months)
    used = sum(miss[m]['使ったレース'] for m in miss)
    print(f'\n# {kind}(確定 odds・c=1= 甘い側の近似)')
    print('\n## 揃ったレースと欠けの内訳(月別)')
    mcols = sorted({c for m in miss for c in miss[m]})
    print('| 月 | ' + ' | '.join(mcols) + ' |\n|---|' + '---|' * len(mcols))
    for ym in months:
        print(f'| {ym} | ' + ' | '.join(str(miss[ym][c]) for c in mcols) + ' |')
    print('| 計 | ' + ' | '.join(str(sum(miss[m][c] for m in miss)) for c in mcols) + ' |')

    def row(name, bk):
        return (f'| {name} | {bk.n:,} | {bk.hit:,} | {pct(bk.hit / bk.n if bk.n else None)} | {pct(bk.roi())} | {pct(bk.roi(1))} | '
                f'{pct(bk.roi(3))} | {bk.over(months)}/{len(months)} | {bk.dd:,} | {bk.n / used if used else 0:.1f} |')

    print(f'\n## 合計(12 か月・1 点 100 円・使ったレース {used:,})')
    print('| 買い方 | 点数 | 的中数 | 的中率 | 回収率 | 最大 1 本抜き | 上位 3 本抜き | 100% 超の月 | 最大ドローダウン(円) | 1 レースあたりの点数 |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    names = [(f'{m} τ={t}', books[(m, t)]) for m in modes for t in TAUS] + list(base.items())
    for nm, bk in names:
        print(row(nm, bk))
    print('\n## 月別の回収率(点数)')
    print('| 買い方 | ' + ' | '.join(m[2:] for m in months) + ' |\n|---|' + '---|' * len(months))
    for nm, bk in names:
        print(f'| {nm} | ' + ' | '.join((f'{bk.month[m][1] / (bk.month[m][0] * 100) * 100:.0f}%({bk.month[m][0]:,})'
                                        if bk.month[m][0] else '—') for m in months) + ' |')
    print('\n## EV の帯別(その帯の組を全部買ったとき)')
    print('| 版 | 帯 | 点数 | 的中率 | 回収率 |\n|---|---|---|---|---|')
    for m in modes:
        for _lo, _hi, lab in EV_BANDS:
            bk = ev_band[m][lab]
            print(f'| {m} | {lab} | {bk.n:,} | {pct(bk.hit / bk.n if bk.n else None)} | {pct(bk.roi())} |')
    print('\n## 較正(Harville の P を 10 等分)= 予想 P の平均 / 実際の的中率')
    for m in modes:
        P = np.concatenate(calib[m][0]) if calib[m][0] else np.array([])
        Y = np.concatenate(calib[m][1]) if calib[m][1] else np.array([])
        if not len(P):
            continue
        idx = np.argsort(P, kind='stable')
        print(f'\n### {m}(組 {len(P):,})\n| 帯 | 組 | 予想 P の平均 | 実際の的中率 |\n|---|---|---|---|')
        for i, part in enumerate(np.array_split(idx, 10)):
            print(f'| {i + 1} | {len(part):,} | {P[part].mean():.5f} | {Y[part].mean():.5f} |')
    print('\n## オッズ帯別= 期待値で選んだ組 / その帯の全組')
    for m in modes:
        for tau in TAUS:
            print(f'\n### {m} τ={tau}\n| 帯 | 選んだ 点数 | 選んだ 的中率 | 選んだ 回収率 | 全組 点数 | 全組 的中率 | 全組 回収率 |')
            print('|---|---|---|---|---|---|---|')
            for _lo, _hi, lab in obands:
                e, al = o_band[(m, tau)][lab], o_all[lab]
                print(f'| {lab} | {e.n:,} | {pct(e.hit / e.n if e.n else None)} | {pct(e.roi())} | '
                      f'{al.n:,} | {pct(al.hit / al.n if al.n else None)} | {pct(al.roi())} |')
    print('\n## 場別の回収率(点数)')
    heads = [f'{m} τ={t}' for m in modes for t in TAUS]
    print('| 場 | ' + ' | '.join(heads) + ' | 全組買い |\n|---|' + '---|' * (len(heads) + 1))
    for vn in list(VENUES) + ['その他']:
        cells = [f'{pct(v_book[(m, t)][vn].roi())}({v_book[(m, t)][vn].n:,})' for m in modes for t in TAUS]
        print(f'| {vn} | ' + ' | '.join(cells) + f' | {pct(v_all[vn].roi())}({v_all[vn].n:,}) |')
    print(f'\n## 採る条件(最大 1 本抜き ≥ 100% かつ 100% 超の月 ≥ {GATE_MONTHS}/12 かつ 点数 ≥ {GATE_POINTS:,})')
    ok_any = []
    for m in modes:
        for tau in TAUS:
            bk = books[(m, tau)]
            r1, mo = bk.roi(1), bk.over(months)
            ok = r1 is not None and r1 >= GATE_ROI and mo >= GATE_MONTHS and bk.n >= GATE_POINTS
            print(f'- {kind} {m} τ={tau}: 最大 1 本抜き {pct(r1)}・100% 超の月 {mo}/{len(months)}・点数 {bk.n:,} → '
                  f'{"満たす" if ok else "満たさない"}')
            if ok:
                ok_any.append(f'{m} τ={tau}')
    print(f'- {kind} 判定: ' + ('満たす組あり= ' + '・'.join(ok_any) if ok_any else '満たす組なし'))


def ref_win(fin, pw, pay, flat_months=None):
    """C の参考= p_win の較正(10 帯)と単勝 1 点(p_win × 確定単勝 fin ≥ τ)の回収率"""
    P, Y, books = [], [], {t: Book() for t in TAUS}
    months = set()
    for k3 in sorted(pw, key=lambda k: (k[1], k[0], k[2])):
        wp, fo = pw[k3], fin.get(k3)
        wins = {int(x['c']): int(x['y']) for x in pay.get(k3, []) if x.get('t') == 'win'}
        if not fo or not wins:
            continue
        s = sum(wp.values())
        if s <= 0:
            continue
        ym = k3[1][:7]
        months.add(ym)
        for u, p in wp.items():
            pn = p / s
            P.append(pn)
            Y.append(1 if u in wins else 0)
            for tau in TAUS:
                if u in fo and pn * fo[u] >= tau:
                    books[tau].buy_many(ym, np.array([wins.get(u, 0)], dtype=float))
    months = sorted(months)
    P, Y = np.array(P), np.array(Y)
    print('\n# C の参考= 勝つ確率 p_win(レース内で Σ=1)')
    print('\n## 較正(10 等分)\n| 帯 | 頭数 | 予想 p_win の平均 | 実際の 1 着率 |\n|---|---|---|---|')
    idx = np.argsort(P, kind='stable')
    for i, part in enumerate(np.array_split(idx, 10)):
        print(f'| {i + 1} | {len(part):,} | {P[part].mean():.4f} | {Y[part].mean():.4f} |')
    print('\n## 単勝 1 点(p_win × 確定単勝 ≥ τ)\n| τ | 点数 | 的中率 | 回収率 | 最大 1 本抜き | 100% 超の月 |\n|---|---|---|---|---|---|')
    for tau, bk in books.items():
        print(f'| {tau} | {bk.n:,} | {pct(bk.hit / bk.n if bk.n else None)} | {pct(bk.roi())} | {pct(bk.roi(1))} | '
              f'{bk.over(months)}/{len(months)} |')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--flat', default=str(HOME / 'keibaodds' / 'flat.parquet'))
    ap.add_argument('--rakuten', default=str(HOME / 'rakuten'))
    ap.add_argument('--pred', default=str(HOME / 'wf1_pred_a.parquet'))
    ap.add_argument('--pwin', default=None)
    ap.add_argument('--payouts', default=str(HOME / 'payouts_2024.tsv'))
    ap.add_argument('--kinds', default='sanrentan,umatan')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    o10, fin, marks, pw, pay = load_common(a.flat, a.pred, a.pwin, a.payouts)
    for k in a.kinds.split(','):
        run_kind(k, a.rakuten, o10, fin, marks, pw, pay)
    if pw is not None:
        ref_win(fin, pw, pay)


if __name__ == '__main__':
    main()
