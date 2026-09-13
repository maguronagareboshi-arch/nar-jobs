# -*- coding: utf-8 -*-
"""§170 A 締切前の全馬オッズ(過去 12 か月)を外部の履歴 API から取る道具。**読むだけ**(DB に書かない)。

  py -3.12 -X utf8 pipeline/ai/odds_hist.py fetch  [--pred <parquet>] [--out <dir>] [--limit N]
  py -3.12 -X utf8 pipeline/ai/odds_hist.py flat   [--out <dir>]
  py -3.12 -X utf8 pipeline/ai/odds_hist.py check  [--out <dir>] [--payouts <tsv>]

- fetch= 予測 parquet にあるレース(場・日・R)だけを 1 本ずつ取る。⛔総当たりしない・同時 1 本・0.6 秒間隔。
  保存= <out>/raw/<場>_<日>_r<N>.json.gz(再実行で飛ばす)。開催なし(HTTP 500 か race_info が空)は
  {"empty": true} を置いて飛ばす(失敗扱いにしない)。それ以外の失敗は置かない= 次の実行で取り直す。
- flat= 1 馬 1 行の <out>/flat.parquet。o10= 発走 10 分前以前でいちばん遅い観測の単勝・f10_lo= 同時点の複勝の下限・
  fin/ffin_lo= 最終。⚠この API の複勝は下限しか無い= f10_hi/ffin_hi は常に空。
- check= 見張り 3 つ(最終オッズと公式払戻の比・10 分前の観測が無いレース・場ごとの取れた率)と
  係数 c(払戻 ÷ 10 分前のオッズ×100 の中央値・人気帯×月)を出す。
⛔取った材料はリポに入れない(既定の置き場= ~/ai_v1/keibaodds/)。
"""
from __future__ import annotations
import argparse, datetime as dt, gzip, json, os, statistics, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path

HOME = Path(os.path.expanduser('~')) / 'ai_v1'
URL = 'https://keibaodds.com/odds?page=1&race_kind=nar&race_date={d}&race_track={t}&race_no={n}'
TRACK_API = {'帯広ば': '帯広'}                  # 当方の場名 → API の場名(違うものだけ)
GAP = 0.6
BANDS = ((1, 1, '1'), (2, 3, '2-3'), (4, 6, '4-6'), (7, 99, '7+'))


def log(*a):
    print(dt.datetime.now().strftime('%H:%M:%S'), *a, flush=True)


def raw_path(out, track, day, no):
    return out / 'raw' / f'{track}_{day}_r{no}.json.gz'


def races_from_pred(pred):
    import pandas as pd
    d = pd.read_parquet(pred, columns=['track', 'race_date', 'rid'])
    d = d.drop_duplicates('rid')
    return sorted((t, rd.strftime('%Y-%m-%d'), int(rid.split('|')[2]))
                  for t, rd, rid in zip(d['track'], d['race_date'], d['rid']))


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research; 1 req/0.6s)'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def slim(j):
    """保存するのは 1 レース分の race_info だけ(他の日・JRA の枠は捨てる)。"""
    ri = ((j.get('nar_info') or {}).get('race_info') or [])
    return ri[0] if ri else None


def fetch(pred, out, limit, shard=(0, 1), gap=GAP):
    """shard=(i, n)= 並べたレースの i 番目おき(i%n)だけ取る= 別プロセスで同時に回せる(担当は重ならない)。
    ⛔失敗が 20 回続いたら相手に止められたとみなして 'blocked' と書いて終わる(叩き続けない)。"""
    allr = races_from_pred(pred)
    si, sn = shard
    todo = [r for k, r in enumerate(allr) if k % sn == si and not raw_path(out, *r).exists()]
    (out / 'raw').mkdir(parents=True, exist_ok=True)
    log('shard', f'{si}/{sn}', 'races', len(allr), 'todo', len(todo), 'gap', gap)
    ok = empty = fail = streak = 0
    for i, (track, day, no) in enumerate(todo[:limit] if limit else todo):
        url = URL.format(d=day, t=urllib.parse.quote(TRACK_API.get(track, track)), n=no)
        body = None
        for attempt in range(3):
            try:
                body = slim(get_json(url)) or {'empty': True}
                break
            except urllib.error.HTTPError as e:
                if e.code == 500:
                    body = {'empty': True, 'http': 500}
                    break
                log('http', e.code, track, day, no)
            except Exception as e:                           # noqa: BLE001 通信の揺れは 3 回まで
                log('err', type(e).__name__, track, day, no)
            time.sleep(max(gap, 0.6) * (attempt + 2))
        if body is None:
            fail += 1
            streak += 1
            if streak >= 20:
                log('blocked', 'shard', f'{si}/{sn}', 'fail streak', streak, 'at', track, day, no)
                break
        else:
            streak = 0
            dst = raw_path(out, track, day, no)
            tmp = dst.with_name(dst.name + '.part')          # 途中で止めても書きかけを「取得済み」にしない
            with gzip.open(tmp, 'wt', encoding='utf-8') as f:
                json.dump(body, f, ensure_ascii=False)
            os.replace(tmp, dst)
            empty += 1 if body.get('empty') else 0
            ok += 0 if body.get('empty') else 1
        if (i + 1) % 200 == 0:
            log('done', i + 1, 'ok', ok, 'empty', empty, 'fail', fail)
        if gap:
            time.sleep(gap)
    log('end ok', ok, 'empty', empty, 'fail', fail)


def _hm(s):
    s = (s or '').strip()
    if len(s) != 5 or s[2] != ':':
        return None
    return int(s[:2]) * 60 + int(s[3:])


def pick10(times, pops, post_min):
    """(t10 の字, 10 分前の {馬番: オッズ}, 最終の {馬番: オッズ})。先頭 1 個は「最終」の字(化けることがある)。"""
    fin = pops[0] if pops else {}
    best = None
    for s, p in zip(times[1:], pops[1:]):
        m = _hm(s)
        if m is None or m > post_min - 10 or not p:
            continue
        if best is None or m > best[0]:
            best = (m, s.strip(), p)
    return (best[1], best[2]) if best else (None, {}), fin


def flat_rows(track, day, no, ri):
    info = ri.get('race_info') or {}
    oi = ri.get('odds_info') or {}
    post = (info.get('race_date_time') or '')[11:16] or info.get('race_time')
    post_min = _hm(post)
    tt, pp = oi.get('time_odds_times') or {}, oi.get('time_pops') or {}
    if post_min is None or 'tanpuku' not in tt:
        return []
    (t10, w10), wfin = pick10(tt['tanpuku'], pp.get('tanpuku') or [], post_min)
    (_, h10), hfin = pick10(tt.get('huku') or [], pp.get('huku') or [], post_min)
    rows = []
    for k in (ri.get('horse_info') or {}):
        def fl(x):
            try:
                v = float(x)
                return v if v > 0 else None
            except (TypeError, ValueError):
                return None
        rows.append(dict(track=track, race_date=day, race_no=no, runner_number=int(k), post=post, t10=t10,
                         o10=fl(w10.get(k)), f10_lo=fl(h10.get(k)), f10_hi=None,
                         fin=fl(wfin.get(k)), ffin_lo=fl(hfin.get(k)), ffin_hi=None))
    return rows


def flat(out):
    import pandas as pd
    rows, n_file, n_empty, bad = [], 0, 0, []
    for fp in sorted((out / 'raw').glob('*.json.gz')):
        n_file += 1
        track, day, r = fp.name[:-len('.json.gz')].rsplit('_', 2)
        try:
            with gzip.open(fp, 'rt', encoding='utf-8') as f:
                ri = json.load(f)
        except (OSError, EOFError, ValueError):
            bad.append(fp.name)                                # ⛔黙って飛ばさない= 数と名前を出す(消せば次の fetch で取り直す)
            continue
        if ri.get('empty'):
            n_empty += 1
            continue
        rows += flat_rows(track, day, int(r[1:]), ri)
    df = pd.DataFrame(rows)
    df.to_parquet(out / 'flat.parquet', index=False)
    log('files', n_file, 'empty', n_empty, 'bad', len(bad), bad[:5], 'rows', len(df), '->', out / 'flat.parquet')


def load_pay(tsv):
    win, plc = {}, {}
    with open(tsv, encoding='utf-8') as f:
        for line in f:
            t, d, n, p = line.rstrip('\n').split('\t')
            for x in json.loads(p):
                if x['t'] == 'win':
                    win.setdefault((t, d, int(n)), {})[int(x['c'])] = x['y']
                elif x['t'] == 'place':
                    plc.setdefault((t, d, int(n)), {})[int(x['c'])] = x['y']
    return win, plc


def band(rank):
    return next(b for lo, hi, b in BANDS if lo <= rank <= hi)


def check(out, pred, tsv):
    import pandas as pd
    df = pd.read_parquet(out / 'flat.parquet')
    want = races_from_pred(pred)
    win, plc = load_pay(tsv)
    got = {(t, d, int(n)) for t, d, n in zip(df['track'], df['race_date'], df['race_no'])}
    # (iii) 場ごとの取れた率
    by = defaultdict(lambda: [0, 0])
    for r in want:
        by[r[0]][0] += 1
        by[r[0]][1] += r in got
    print('\n## 見張り (iii) 場ごとの取れた率(予測 parquet のレースに対して)')
    print('| 場 | レース | 取れた | 率 |\n|---|---|---|---|')
    for t, (a, b) in sorted(by.items(), key=lambda x: -x[1][0]):
        print(f'| {t} | {a} | {b} | {b / a:.1%} |')
    a, b = sum(v[0] for v in by.values()), sum(v[1] for v in by.values())
    print(f'| 計 | {a} | {b} | {b / a:.1%} |')
    # (i) 勝ち馬の最終オッズ×100 と公式払戻
    ratios, off, nopay = [], 0, 0
    c_win = defaultdict(list)
    c_plc = defaultdict(list)
    no10 = 0
    for (t, d, n), g in df.groupby(['track', 'race_date', 'race_no']):
        w = win.get((t, d, n))
        if not w:
            nopay += 1
            continue
        if g['o10'].notna().sum() == 0:
            no10 += 1
        rank10 = g['o10'].rank(method='min')
        prank10 = g['f10_lo'].rank(method='min')
        ym = d[:7]
        for u, y in w.items():
            row = g[g['runner_number'] == u]
            if row.empty:
                continue
            fo = row['fin'].iloc[0]
            if fo:
                r = y / (fo * 100)
                ratios.append(r)
                off += not (0.99 <= r <= 1.01)
            o10 = row['o10'].iloc[0]
            if o10 and o10 == o10:
                c_win[(band(int(rank10[row.index[0]])), ym)].append(y / (o10 * 100))
        for u, y in (plc.get((t, d, n)) or {}).items():
            row = g[g['runner_number'] == u]
            if row.empty:
                continue
            f10 = row['f10_lo'].iloc[0]
            if f10 and f10 == f10:
                c_plc[(band(int(prank10[row.index[0]])), ym)].append(y / (f10 * 100))
    print('\n## 見張り (i) 勝ち馬の 最終単勝×100 と 公式払戻')
    print(f'- 比べた勝ち馬 {len(ratios)}・比の中央値 {statistics.median(ratios):.3f}・0.99〜1.01 を外れた {off} 件'
          f'({off / max(len(ratios), 1):.1%})・払戻の無いレース {nopay}')
    print('\n## 見張り (ii) 発走 10 分前より前の観測が無いレース')
    print(f'- {no10} / {df.groupby(["track", "race_date", "race_no"]).ngroups} レース')
    months = sorted({k[1] for k in c_win} | {k[1] for k in c_plc})
    for name, C, lab in (('単勝', c_win, '勝ち馬の払戻 ÷ (o10×100)・人気帯= 10 分前の単勝の順'),
                         ('複勝', c_plc, '3着内の馬の複勝払戻 ÷ (f10_lo×100)・人気帯= 10 分前の複勝下限の順')):
        print(f'\n## 係数 c({name})= {lab}・中央値(件数)')
        print('| 人気帯 | 12 か月 | ' + ' | '.join(m[2:] for m in months) + ' |')
        print('|---|---|' + '---|' * len(months))
        for _, _, b in BANDS:
            allv = [v for (bb, _), L in C.items() if bb == b for v in L]
            cells = []
            for m in months:
                L = C.get((b, m), [])
                cells.append(f'{statistics.median(L):.3f}({len(L)})' if L else '-')
            print(f'| {b} | {statistics.median(allv):.3f}({len(allv)}) | ' + ' | '.join(cells) + ' |'
                  if allv else f'| {b} | - |')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fetch', 'flat', 'check'])
    ap.add_argument('--pred', default=str(HOME / 'wf1_pred_a.parquet'))
    ap.add_argument('--out', default=str(HOME / 'keibaodds'))
    ap.add_argument('--payouts', default=str(HOME / 'payouts_2024.tsv'))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--shard', default='0/1', help='i/n= 並べたレースの i%%n 番目だけ取る(別プロセスで同時に回す)')
    ap.add_argument('--gap', type=float, default=GAP, help='1 本ごとの待ち秒(既定 0.6)')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    out = Path(a.out)
    if a.cmd == 'fetch':
        si, sn = (int(x) for x in a.shard.split('/'))
        fetch(a.pred, out, a.limit, (si, sn), a.gap)
    elif a.cmd == 'flat':
        flat(out)
    else:
        check(out, a.pred, a.payouts)


if __name__ == '__main__':
    main()
