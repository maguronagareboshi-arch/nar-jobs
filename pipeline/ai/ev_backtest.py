# -*- coding: utf-8 -*-
"""§170 C 期待値で買う検証(複勝・12 か月の WF)。**読むだけ**(DB に書かない・材料は手元のファイルだけ)。

  py -3.12 -X utf8 pipeline/ai/ev_backtest.py [--pred <wf1_pred_a.parquet>] [--flat <flat.parquet>] [--payouts <tsv>]

材料= 予測(各馬の 3着内の確率 p・前の月までで学習済み)× 締切 10 分前の複勝下限(f10_lo)と単勝(o10)×
      確定の複勝の払戻。**3 つ揃うレースだけ**使う(揃わなかった数は表に出す)。
- 市場の確率 q= (1/f10_lo) をレースの中で合計 3 になるよう割る(控除ぶんを除く・券種間の細工はしない)。
- 期待値 EV= p'×f10_lo×c・p'= (1−λ)p + λq・c= 「確定の払戻 ÷ (f10_lo×100)」の人気帯別の中央値を
  **その月より前の月だけ**から作る(最初の月は 1)。人気帯= 10 分前の複勝下限のレース内の順。
- 買う馬= EV ≥ τ・1 点 100 円・1 レース何点でも。⛔λ∈{0, 0.5}・τ∈{1.0, 1.1} の 4 組で終わり(後から動かさない)。
- 相手= 全馬買い / 1 番人気(10 分前の単勝が最小・同じなら馬番の小さい方)/ AI ◎(p が最大・同じなら馬番の小さい方)。
- 採る条件(事前に決めた)= 12 か月合計で 最大 1 本抜きの回収率 ≥ 100% かつ 100% 超の月 ≥ 7/12 かつ 点数 ≥ 1,000。
⛔自分の票でオッズが動く分は無視(100 円単位の仮定)。⛔表は標準出力だけ(ファイルやリポに数字を書かない)。
"""
import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds_hist import BANDS, HOME, band, load_pay  # noqa: E402

LAMBDAS = (0.0, 0.5)
TAUS = (1.0, 1.1)
PLACES = 3
GATE_ROI = 1.0           # 最大 1 本抜きの回収率
GATE_MONTHS = 7          # 100% を超えた月の数
GATE_POINTS = 1000       # 点数
ODDS_BANDS = ((1.0, 1.5, '1.0-1.4'), (1.5, 2.0, '1.5-1.9'), (2.0, 3.0, '2.0-2.9'),
              (3.0, 5.0, '3.0-4.9'), (5.0, 10.0, '5.0-9.9'), (10.0, 1e9, '10 以上'))
VENUES = ('高知', '門別', '大井', '船橋', '川崎', '浦和')


def odds_band(f):
    return next(lab for lo, hi, lab in ODDS_BANDS if lo <= f < hi)


def load(pred, flat, payouts):
    """→ (races, miss)。races= [(ym, key, [馬の dict…])]・日付順。miss= 揃わなかった数の内訳(月別)"""
    import pandas as pd
    pr = pd.read_parquet(pred, columns=['track', 'race_date', 'rid', 'runner_number', 'p', 'y'])
    pr['d'] = pr['race_date'].dt.strftime('%Y-%m-%d')
    pr['no'] = pr['rid'].str.rsplit('|', n=1).str[1].astype(int)
    fl = pd.read_parquet(flat, columns=['track', 'race_date', 'race_no', 'runner_number', 'o10', 'f10_lo'])
    fo = {(t, d, int(n), int(u)): (o, f) for t, d, n, u, o, f in
          zip(fl['track'], fl['race_date'], fl['race_no'], fl['runner_number'], fl['o10'], fl['f10_lo'])}
    flat_races = {(t, d, int(n)) for t, d, n in zip(fl['track'], fl['race_date'], fl['race_no'])}
    _win, plc = load_pay(payouts)
    miss = defaultdict(lambda: defaultdict(int))
    races = []
    for (t, d, no), g in pr.groupby(['track', 'd', 'no'], sort=False):
        ym = d[:7]
        key = (t, d, int(no))
        miss[ym]['予測のレース'] += 1
        if key not in flat_races:
            miss[ym]['オッズ無し'] += 1
            continue
        pay = plc.get(key)
        if not pay:
            miss[ym]['複勝の払戻無し'] += 1
            continue
        horses = []
        for u, p, y in zip(g['runner_number'], g['p'], g['y']):
            o, f = fo.get((t, d, int(no), int(u)), (None, None))
            if f is None or f != f:
                miss[ym]['f10_lo の無い馬'] += 1
                continue
            horses.append(dict(u=int(u), p=float(p), y=int(y), f=float(f),
                               o=(float(o) if o is not None and o == o else None), pay=int(pay.get(int(u), 0))))
        if len(horses) < 2:
            miss[ym]['買える馬 2 頭未満'] += 1
            continue
        s = sum(1 / h['f'] for h in horses)
        order = sorted(horses, key=lambda h: (h['f'], h['u']))
        rank, prev = 0, None
        for i, h in enumerate(order):
            if h['f'] != prev:
                rank, prev = i + 1, h['f']
            h['band'] = band(rank)
            h['q'] = (1 / h['f']) / s * PLACES
        miss[ym]['使ったレース'] += 1
        races.append((ym, key, horses))
    races.sort(key=lambda r: (r[1][1], r[1][0], r[1][2]))
    return races, miss


def c_tables(races):
    """月 → {人気帯: c}= **その月より前の月**の「払戻 ÷ (f10_lo×100)」(3着内の馬)の中央値。最初の月は 1"""
    by_month = defaultdict(lambda: defaultdict(list))
    for ym, _k, horses in races:
        for h in horses:
            if h['pay'] > 0:
                by_month[ym][h['band']].append(h['pay'] / (h['f'] * 100))
    months = sorted({r[0] for r in races})
    out, acc = {}, defaultdict(list)
    for ym in months:
        out[ym] = {b: (statistics.median(acc[b]) if acc[b] else 1.0) for _lo, _hi, b in BANDS}
        for b, L in by_month[ym].items():
            acc[b].extend(L)
    return out, months


class Book:
    """100 円均等の買いの帳面"""

    def __init__(self):
        self.pays = []                     # 当たりの払戻(円)
        self.n = 0
        self.hit = 0
        self.cum, self.peak, self.dd = 0, 0, 0
        self.month = defaultdict(lambda: [0, 0])     # ym → [点数, 払戻]

    def buy(self, ym, h):
        self.n += 1
        self.month[ym][0] += 1
        self.month[ym][1] += h['pay']
        if h['pay'] > 0:
            self.hit += 1
            self.pays.append(h['pay'])
        self.cum += h['pay'] - 100
        self.peak = max(self.peak, self.cum)
        self.dd = max(self.dd, self.peak - self.cum)

    def roi(self, drop=0):
        if not self.n:
            return None
        ret = sum(self.pays) - sum(sorted(self.pays, reverse=True)[:drop])
        return ret / (self.n * 100)

    def months_over(self, months):
        return sum(1 for m in months if self.month[m][0] and self.month[m][1] > self.month[m][0] * 100)


def pct(v):
    return '—' if v is None else f'{v * 100:.1f}%'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pred', default=str(HOME / 'wf1_pred_a.parquet'))
    ap.add_argument('--flat', default=str(HOME / 'keibaodds' / 'flat.parquet'))
    ap.add_argument('--payouts', default=str(HOME / 'payouts_2024.tsv'))
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    races, miss = load(a.pred, a.flat, a.payouts)
    cmap, months = c_tables(races)

    combos = [(lam, tau) for lam in LAMBDAS for tau in TAUS]
    books = {('EV', lam, tau): Book() for lam, tau in combos}
    base = {'全馬買い': Book(), '1 番人気': Book(), 'AI ◎': Book()}
    band_ev = {(lam, tau): defaultdict(Book) for lam, tau in combos}
    band_all = defaultdict(Book)
    venue_ev = {(lam, tau): defaultdict(Book) for lam, tau in combos}
    venue_all = defaultdict(Book)
    calib = []
    for ym, (t, _d, _no), horses in races:
        vn = t if t in VENUES else 'その他'
        fav = [h for h in horses if h['o'] is not None]
        if fav:
            base['1 番人気'].buy(ym, min(fav, key=lambda h: (h['o'], h['u'])))
        base['AI ◎'].buy(ym, max(horses, key=lambda h: (h['p'], -h['u'])))
        for h in horses:
            base['全馬買い'].buy(ym, h)
            band_all[odds_band(h['f'])].buy(ym, h)
            venue_all[vn].buy(ym, h)
            calib.append((h['p'], h['y']))
            c = cmap[ym][h['band']]
            for lam, tau in combos:
                ev = ((1 - lam) * h['p'] + lam * h['q']) * h['f'] * c
                if ev >= tau:
                    books[('EV', lam, tau)].buy(ym, h)
                    band_ev[(lam, tau)][odds_band(h['f'])].buy(ym, h)
                    venue_ev[(lam, tau)][vn].buy(ym, h)

    # ---- 揃わなかった数
    print('## C-0 揃ったレースと欠けの内訳(月別)')
    cols = ['予測のレース', 'オッズ無し', '複勝の払戻無し', '買える馬 2 頭未満', '使ったレース', 'f10_lo の無い馬']
    print('| 月 | ' + ' | '.join(cols) + ' |\n|---|' + '---|' * len(cols))
    for ym in sorted(miss):
        print(f'| {ym} | ' + ' | '.join(str(miss[ym][c]) for c in cols) + ' |')
    print('| 計 | ' + ' | '.join(str(sum(miss[m][c] for m in miss)) for c in cols) + ' |')

    print('\n## C-3 係数 c(その月より前の月の中央値・最初の月は 1)')
    print('| 月 | ' + ' | '.join(b for _l, _h, b in BANDS) + ' |\n|---|' + '---|' * len(BANDS))
    for ym in months:
        print(f'| {ym} | ' + ' | '.join(f'{cmap[ym][b]:.3f}' for _l, _h, b in BANDS) + ' |')

    # ---- 合計
    def row(name, bk):
        return (f'| {name} | {bk.n:,} | {pct(bk.hit / bk.n if bk.n else None)} | {pct(bk.roi())} | '
                f'{pct(bk.roi(1))} | {pct(bk.roi(3))} | {bk.months_over(months)}/{len(months)} | {bk.dd:,} |')

    print('\n## C-5 合計(12 か月・1 点 100 円)')
    print('| 買い方 | 点数 | 的中率(3着内) | 回収率 | 最大 1 本抜き | 上位 3 本抜き | 100% 超の月 | 最大ドローダウン(円) |')
    print('|---|---|---|---|---|---|---|---|')
    for lam, tau in combos:
        print(row(f'期待値 λ={lam} τ={tau}', books[('EV', lam, tau)]))
    for name, bk in base.items():
        print(row(name, bk))

    print('\n## C-5 月別の回収率(点数)')
    names = [(f'期待値 λ={lam} τ={tau}', books[('EV', lam, tau)]) for lam, tau in combos] + list(base.items())
    print('| 買い方 | ' + ' | '.join(m[2:] for m in months) + ' |\n|---|' + '---|' * len(months))
    for name, bk in names:
        cells = []
        for m in months:
            n, y = bk.month[m]
            cells.append(f'{y / (n * 100) * 100:.0f}%({n})' if n else '—')
        print(f'| {name} | ' + ' | '.join(cells) + ' |')

    print('\n## C-5 オッズ帯別(10 分前の複勝下限)= 期待値で選んだ馬 / その帯の全馬')
    for lam, tau in combos:
        print(f'\n### λ={lam} τ={tau}')
        print('| 帯 | 選んだ 点数 | 選んだ 的中率 | 選んだ 回収率 | 全馬 点数 | 全馬 的中率 | 全馬 回収率 |')
        print('|---|---|---|---|---|---|---|')
        for _lo, _hi, lab in ODDS_BANDS:
            e, al = band_ev[(lam, tau)][lab], band_all[lab]
            print(f'| {lab} | {e.n:,} | {pct(e.hit / e.n if e.n else None)} | {pct(e.roi())} | '
                  f'{al.n:,} | {pct(al.hit / al.n if al.n else None)} | {pct(al.roi())} |')

    print('\n## C-5 場別の回収率(点数)= 期待値で選んだ馬 4 組 / 全馬買い')
    vns = list(VENUES) + ['その他']
    print('| 場 | ' + ' | '.join(f'λ={lam} τ={tau}' for lam, tau in combos) + ' | 全馬買い |')
    print('|---|' + '---|' * (len(combos) + 1))
    for vn in vns:
        cells = [f'{pct(venue_ev[c][vn].roi())}({venue_ev[c][vn].n:,})' for c in combos]
        print(f'| {vn} | ' + ' | '.join(cells) + f' | {pct(venue_all[vn].roi())}({venue_all[vn].n:,}) |')

    print('\n## C-5 較正(p を 10 等分)= 予想 p の平均 / 実際の 3着内率')
    calib.sort()
    k = len(calib)
    print('| 帯 | 頭数 | 予想 p の平均 | 実際の 3着内率 |\n|---|---|---|---|')
    for i in range(10):
        part = calib[i * k // 10:(i + 1) * k // 10]
        if part:
            print(f'| {i + 1} | {len(part):,} | {statistics.fmean(x for x, _ in part):.3f} | '
                  f'{statistics.fmean(y for _, y in part):.3f} |')

    print('\n## C-6 採る条件(最大 1 本抜き ≥ 100% かつ 100% 超の月 ≥ 7/12 かつ 点数 ≥ 1,000)')
    ok_any = []
    for lam, tau in combos:
        bk = books[('EV', lam, tau)]
        r1, mo = bk.roi(1), bk.months_over(months)
        ok = r1 is not None and r1 >= GATE_ROI and mo >= GATE_MONTHS and bk.n >= GATE_POINTS
        print(f'- λ={lam} τ={tau}: 最大 1 本抜き {pct(r1)}・100% 超の月 {mo}/{len(months)}・点数 {bk.n:,} → '
              f'{"満たす" if ok else "満たさない"}')
        if ok:
            ok_any.append((lam, tau))
    print('- 判定: ' + ('満たす組あり= ' + '・'.join(f'λ={l} τ={t}' for l, t in ok_any) if ok_any
                      else '4 組とも満たさない= 儲かる買い方は今の材料では見つからない'))


if __name__ == '__main__':
    main()
