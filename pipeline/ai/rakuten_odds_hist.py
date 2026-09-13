# -*- coding: utf-8 -*-
"""§170 段 2 A 楽天の**確定オッズ**(三連単・馬単・全組)を過去 12 か月ぶん取る道具。**読むだけ**(DB に書かない)。

  py -3.12 -X utf8 pipeline/ai/rakuten_odds_hist.py fetch [--shard i/n] [--gap 秒] [--limit N]
  py -3.12 -X utf8 pipeline/ai/rakuten_odds_hist.py flat     # 塊をまとめて sanrentan.parquet / umatan.parquet
  py -3.12 -X utf8 pipeline/ai/rakuten_odds_hist.py check    # 見張り (i)〜(iv)

- 対象= <keibaodds>/flat.parquet にあるレース(場・日・R)。⛔総当たりで叩かない。
- URL= https://keiba.rakuten.co.jp/odds/{sanrentan|umatan}/RACEID/<日付 8 桁><場コード 2 桁>000000<R 2 桁>(UTF-8)。
  ⛔RACEID は 18 桁でなければ投げない(打ち間違いを見張る)。
- **ページは保存しない**= 「順位・組番・オッズ」の表(人気順= 全組)から組と odds だけ取り、shard ごとに
  200 レースずつ parquet の塊(.part → rename)にする。取れたレースは塊から読み直して飛ばす(レジューム)。
- HTTP 429/503= その shard は 30 秒止めて同じ URL を続ける。⛔それ以外の失敗が 20 回続いたら止まる。
- 取れなかったレースは <out>/missing.tsv(場・日・R・券種・理由)。
"""
import argparse
import datetime as dt
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds_hist import HOME  # noqa: E402

UA = 'Mozilla/5.0 (compatible; nar-jobs research)'
URL = 'https://keiba.rakuten.co.jp/odds/{kind}/RACEID/{rid}'
KINDS = ('sanrentan', 'umatan')
PICK = {'sanrentan': 3, 'umatan': 2}
# 場コード(= keiba.go.jp k_babaCode)。⛔cloud/rakuten_sales.py の表と同じ字(cloud と pipeline は互いに import しない)
BABA = {
    '帯広ば': '3', '門別': '36', '盛岡': '10', '水沢': '11', '浦和': '18', '船橋': '19',
    '大井': '20', '川崎': '21', '金沢': '22', '笠松': '23', '名古屋': '24',
    '園田': '27', '姫路': '28', '高知': '31', '佐賀': '32',
}
CHUNK = 200
FAIL_STOP = 20
BACKOFF = 30


def log(*a):
    print(f'[{dt.datetime.now():%H:%M:%S}]', *a, flush=True)


def race_id(track, day, no):
    """→ 18 桁の RACEID。⛔場コードが表に無い・桁が違うときは None(投げない)"""
    code = BABA.get(track)
    if code is None:
        return None
    rid = day.replace('-', '') + f'{int(code):02d}' + '000000' + f'{int(no):02d}'
    return rid if len(rid) == 18 and rid.isdigit() else None


def _strip(s):
    return re.sub(r'<[^>]+>|\s+', '', s)


def split_combo(s):
    """組番の字(例 '4→1→9'・'4-1-9')→ (4, 1, 9)。数字だけ取り出す"""
    return tuple(int(x) for x in re.findall(r'\d+', _strip(s)))


def parse_rank_table(html, r):
    """ページ → ({(1着, 2着[, 3着]): odds}, ページの日付 'YYYY/MM/DD' か None, 出走頭数 か None)。
    「順位・組番・オッズ」の表の**最初のもの**(人気順)を読む。odds の無い組(取消など)は入れない"""
    title = re.search(r'<title>(.*?)</title>', html, re.S)
    m = re.search(r'(\d{4}/\d{2}/\d{2})', title.group(1)) if title else None
    day = m.group(1) if m and m.group(1) != '0000/00/00' else None
    first = re.search(r'aria-label="出馬表"[^>]*>(.*?)</table>', html, re.S)
    heads = None
    if first:
        ths = [_strip(x) for x in re.findall(r'<th[^>]*>(.*?)</th>', first.group(1), re.S)]
        heads = sum(1 for x in ths if x.isdigit()) or None
    out = {}
    for body in re.findall(r'<table[^>]*>(.*?)</table>', html, re.S):
        ths = [_strip(x) for x in re.findall(r'<th[^>]*>(.*?)</th>', body, re.S)]
        if ths[:3] != ['順位', '組番', 'オッズ']:
            continue
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
            if len(cells) < 3:
                continue
            combo = split_combo(cells[1])
            om = re.search(r'(\d+(?:\.\d+)?)', _strip(cells[2]))
            if len(combo) == r and om:
                out[combo] = float(om.group(1))
        break
    return out, day, heads


def races_from_flat(flat):
    import pandas as pd
    d = pd.read_parquet(flat, columns=['track', 'race_date', 'race_no'])
    return sorted({(t, str(x), int(n)) for t, x, n in zip(d['track'], d['race_date'], d['race_no'])})


def get(url):
    r = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(r, timeout=60) as x:
        return x.status, x.read().decode('utf-8', errors='replace')


def chunk_dir(out):
    return out / 'chunks'


def done_races(out, kind):
    import pandas as pd
    got = set()
    for fp in chunk_dir(out).glob(f'{kind}_s*_c*.parquet'):
        d = pd.read_parquet(fp, columns=['track', 'race_date', 'race_no'])
        got |= {(t, x, int(n)) for t, x, n in zip(d['track'], d['race_date'], d['race_no'])}
    return got


def missing_done(out):
    fp = out / 'missing.tsv'
    got = set()
    if fp.exists():
        for line in fp.read_text(encoding='utf-8').splitlines():
            t, d, n, k, _why = line.split('\t')
            got.add((t, d, int(n), k))
    return got


def write_chunk(out, kind, shard, rows):
    import pandas as pd
    cd = chunk_dir(out)
    cd.mkdir(parents=True, exist_ok=True)
    i = 0
    while (cd / f'{kind}_s{shard}_c{i}.parquet').exists():
        i += 1
    fp = cd / f'{kind}_s{shard}_c{i}.parquet'
    part = fp.with_suffix('.part')
    pd.DataFrame(rows).to_parquet(part, index=False)
    os.replace(part, fp)


def fetch(flat, out, limit, shard=(0, 1), gap=0.0):
    si, sn = shard
    out.mkdir(parents=True, exist_ok=True)
    races = [r for i, r in enumerate(races_from_flat(flat)) if i % sn == si]
    skip = {k: done_races(out, k) for k in KINDS}
    miss = missing_done(out)
    buf = {k: [] for k in KINDS}
    nbuf = {k: 0 for k in KINDS}
    fail = ok = n_miss = 0
    t0 = time.time()
    todo = [(r, k) for r in races for k in KINDS if r not in skip[k] and (r + (k,)) not in miss]
    if limit:
        todo = todo[:limit]
    log(f'shard {si}/{sn}: レース {len(races)}・残り {len(todo)} 本(券種×レース)')
    mfp = open(out / 'missing.tsv', 'a', encoding='utf-8')
    for idx, ((track, day, no), kind) in enumerate(todo):
        rid = race_id(track, day, no)
        if rid is None:
            mfp.write(f'{track}\t{day}\t{no}\t{kind}\tRACEID を作れない\n')
            n_miss += 1
            continue
        url = URL.format(kind=kind, rid=rid)
        while True:
            try:
                st, html = get(url)
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 503):
                    log(f'shard {si}: HTTP {e.code}= {BACKOFF} 秒止めて続き')
                    time.sleep(BACKOFF)
                    continue
                st, html = e.code, ''
                break
            except Exception as e:                     # noqa: BLE001  通信の失敗は数えて止まる
                st, html = None, repr(e)
                break
        if st != 200:
            fail += 1
            log(f'shard {si}: 失敗 {fail} 連続 {track} {day} {no}R {kind} {st}')
            if fail >= FAIL_STOP:
                log(f'shard {si}: ⛔失敗 {FAIL_STOP} 連続= 止める(blocked)')
                break
            continue
        fail = 0
        combos, pday, heads = parse_rank_table(html, PICK[kind])
        if pday != day.replace('-', '/'):
            mfp.write(f'{track}\t{day}\t{no}\t{kind}\tページの日付が違う({pday})\n')
            n_miss += 1
        elif not combos:
            mfp.write(f'{track}\t{day}\t{no}\t{kind}\t組の表が無い\n')
            n_miss += 1
        else:
            for c, o in combos.items():
                row = dict(track=track, race_date=day, race_no=no, heads=heads, odds=o, first=c[0], second=c[1])
                if len(c) == 3:
                    row['third'] = c[2]
                buf[kind].append(row)
            nbuf[kind] += 1
            ok += 1
            if nbuf[kind] >= CHUNK:
                write_chunk(out, kind, si, buf[kind])
                buf[kind], nbuf[kind] = [], 0
        mfp.flush()
        if (idx + 1) % 200 == 0:
            log(f'shard {si}: {idx + 1}/{len(todo)}・取れた {ok}・取れない {n_miss}・{time.time() - t0:.0f} 秒')
        if gap:
            time.sleep(gap)
    for k in KINDS:
        if buf[k]:
            write_chunk(out, k, si, buf[k])
    mfp.close()
    log(f'shard {si}: end 取れた {ok}・取れない {n_miss}・失敗の連続 {fail}・{time.time() - t0:.0f} 秒')


def flat_cmd(out):
    import pandas as pd
    for k in KINDS:
        parts = sorted(chunk_dir(out).glob(f'{k}_s*_c*.parquet'))
        if not parts:
            log(k, '塊なし')
            continue
        df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
        cols = ['track', 'race_date', 'race_no', 'first', 'second'] + (['third'] if k == 'sanrentan' else [])
        df = df.drop_duplicates(cols).sort_values(cols).reset_index(drop=True)
        fp = out / f'{k}.parquet'
        part = fp.with_suffix('.part')
        df.to_parquet(part, index=False)
        os.replace(part, fp)
        log(k, '塊', len(parts), '行', len(df), 'レース', df.groupby(['track', 'race_date', 'race_no']).ngroups, '->', fp)


def check(out, flat, tsv):
    """見張り (i) 組の数 = nPr (ii) 勝った組の odds×100 = 払戻 (iii) Σ1/odds (iv) 場ごとの取れた率"""
    import statistics
    import pandas as pd
    from odds_hist import load_pay  # noqa: F401  (単勝・複勝の読み方と同じ tsv)
    import json
    fl = pd.read_parquet(flat, columns=['track', 'race_date', 'race_no', 'runner_number', 'o10', 'fin'])
    heads_flat = fl.groupby(['track', 'race_date', 'race_no'])['runner_number'].nunique().to_dict()
    live_flat = fl[fl['fin'].notna()].groupby(['track', 'race_date', 'race_no'])['runner_number'].nunique().to_dict()
    pay = {}
    with open(tsv, encoding='utf-8') as f:
        for line in f:
            t, d, n, p = line.rstrip('\n').split('\t')
            pay[(t, d, int(n))] = json.loads(p)
    want = races_from_flat(flat)
    for k, tick in (('sanrentan', 'trifecta'), ('umatan', 'exacta')):
        fp = out / f'{k}.parquet'
        if not fp.exists():
            print(f'\n## {k}: {fp} が無い(flat を先に)')
            continue
        df = pd.read_parquet(fp)
        r = PICK[k]
        keys = ['track', 'race_date', 'race_no']
        print(f'\n## {k}= 行 {len(df):,}・レース {df.groupby(keys).ngroups:,} / 対象 {len(want):,}')
        # (i)
        cnt = df.groupby(keys).size()
        page_heads = df.groupby(keys)['heads'].first()
        why = defaultdict(int)
        ok_n = 0
        for key, c in cnt.items():
            n_live = live_flat.get(key)
            npr = (lambda n: n * (n - 1) * (n - 2) if r == 3 else n * (n - 1))
            if n_live and c == npr(n_live):
                ok_n += 1
            elif page_heads.get(key) and c == npr(int(page_heads[key])):
                why['ページの頭数と一致(取消の数え方の違い)'] += 1
            elif heads_flat.get(key) and c == npr(heads_flat[key]):
                why['外部 A の馬数(取消込み)と一致'] += 1
            else:
                why['どれとも合わない'] += 1
        print(f'- (i) 組の数 = nPr(確定の着順のある頭数)= {ok_n:,} / {len(cnt):,}({ok_n / max(len(cnt), 1):.1%})・違いの分類 {dict(why)}')
        # (ii)
        combo_cols = ['first', 'second'] + (['third'] if r == 3 else [])
        idx = df.set_index(keys + combo_cols)['odds']
        ratios, off, nopay, nohit = [], 0, 0, 0
        for key in cnt.index:
            hits = [x for x in pay.get(key, []) if x.get('t') == tick]
            if not hits:
                nopay += 1
                continue
            for h in hits:
                c = tuple(int(x) for x in re.findall(r'\d+', str(h.get('c'))))
                o = idx.get(key + c)
                if o is None:
                    nohit += 1
                    continue
                q = h['y'] / (o * 100)
                ratios.append(q)
                off += not (0.99 <= q <= 1.01)
        med = statistics.median(ratios) if ratios else float('nan')
        print(f'- (ii) 勝った組 {len(ratios):,}・比の中央値 {med:.3f}・0.99〜1.01 を外れた {off:,}'
              f'({off / max(len(ratios), 1):.1%})・払戻の無いレース {nopay:,}・勝った組が表に無い {nohit:,}')
        # (iii)
        sig = df.assign(inv=1 / df['odds']).groupby(keys)['inv'].sum()
        print(f'- (iii) Σ1/odds の中央値 {sig.median():.3f}(10%点 {sig.quantile(0.1):.3f}・90%点 {sig.quantile(0.9):.3f})')
        # (iv)
        by = defaultdict(lambda: [0, 0])
        got = set(cnt.index)
        for w in want:
            by[w[0]][0] += 1
            by[w[0]][1] += w in got
        print('- (iv) 場ごとの取れた率')
        print('| 場 | レース | 取れた | 率 |\n|---|---|---|---|')
        for t, (a, b) in sorted(by.items(), key=lambda x: -x[1][0]):
            print(f'| {t} | {a:,} | {b:,} | {b / a:.1%} |')
        print(f'| 計 | {sum(v[0] for v in by.values()):,} | {sum(v[1] for v in by.values()):,} | '
              f'{sum(v[1] for v in by.values()) / max(sum(v[0] for v in by.values()), 1):.1%} |')
    mp = out / 'missing.tsv'
    if mp.exists():
        why = defaultdict(int)
        for line in mp.read_text(encoding='utf-8').splitlines():
            parts = line.split('\t')
            why[(parts[3], re.sub(r'\(.*\)', '', parts[4]))] += 1
        print(f'\n## missing.tsv の内訳= {dict(why)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fetch', 'flat', 'check'])
    ap.add_argument('--flat', default=str(HOME / 'keibaodds' / 'flat.parquet'))
    ap.add_argument('--out', default=str(HOME / 'rakuten'))
    ap.add_argument('--payouts', default=str(HOME / 'payouts_2024.tsv'))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--shard', default='0/1', help='i/n= 並べたレースの i%%n 番目だけ取る(別プロセスで同時に回す)')
    ap.add_argument('--gap', type=float, default=0.0, help='1 本ごとの待ち秒(既定 0= ユーザー 9/15「超高速」)')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    out = Path(a.out)
    if a.cmd == 'fetch':
        si, sn = (int(x) for x in a.shard.split('/'))
        fetch(Path(a.flat), out, a.limit, (si, sn), a.gap)
    elif a.cmd == 'flat':
        flat_cmd(out)
    else:
        check(out, Path(a.flat), a.payouts)


if __name__ == '__main__':
    main()
