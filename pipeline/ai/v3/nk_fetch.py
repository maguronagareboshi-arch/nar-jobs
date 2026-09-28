# -*- coding: utf-8 -*-
"""南関の能力・調教試験の結果を公式サイト(nankankeiba.com)から集める(ユーザー承認 2026-09-27)。

  py -3.12 -X utf8 src/nk_fetch.py fetch    # 2019-07-01〜2026-08-31 の全日 × 4 場(nk_skip.json の日は飛ばす)。取った分は飛ばして再開
  py -3.12 -X utf8 src/nk_fetch.py parse    # 保存した HTML → v3/nk_shiken.parquet

URL = https://www.nankankeiba.com/shiken_list/{YYYYMMDD}{場}.do(18 浦和・19 船橋・20 大井・21 川崎)。無い日は 404。
場ごとに 4 本並列・各本 0.5 秒おき(ユーザー承認 2026-09-27)。守りで止まったら 1 本・2 秒おきに戻す(nk_fetch.sh)・User-Agent は requests の既定・エラーは 3 回まで間を空けて再試行。
200 の HTML は v3/nk_html/{YYYYMMDD}{場}.html、404 は v3/nk_html/_404*.txt に 1 行ずつ記録(再開で飛ばす)。
表の列: R・距離・馬名・父・母・母父・騎手・調教師・性齢・体重・試験内容・タイム・合否・ord(R の中のページ上の並び順 1〜)。
"""
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
HD = V3 / 'nk_html'
F404 = HD / '_404.txt'
OUT = V3 / 'nk_shiken.parquet'
JYO = {18: '浦和', 19: '船橋', 20: '大井', 21: '川崎'}
D0, D1 = date(2019, 7, 1), date(2026, 8, 31)
URL = 'https://www.nankankeiba.com/shiken_list/{}{}.do'


STOP = HD / '_STOP'
FALLBACK = V3 / 'nk_fallback.txt'


def done_keys():
    done = set()
    for f in HD.glob('_404*.txt'):
        done |= set(f.read_text(encoding='utf-8').split())
    return done | {p.stem for p in HD.glob('*.html')}


def fetch(jyo=None, gap=0.5):
    """jyo を与えるとその場だけ(4 本並列用・ユーザー承認 2026-09-27)。守り: 429・503・接続拒否・タイムアウトが 5 回続いたら
    _STOP を置いて止まる(他の本も _STOP を見て止まる)。jyo なし・gap 2 秒が戻し用の 1 本。HTML の保存だけ(表にしない)。"""
    HD.mkdir(parents=True, exist_ok=True)
    done = done_keys()
    js = [int(jyo)] if jyo else list(JYO)
    keys = []
    d = D0
    while d <= D1:
        keys += [f'{d:%Y%m%d}{j}' for j in js]
        d += timedelta(days=1)
    sk = V3 / 'nk_skip.json'
    skip = set(json.loads(sk.read_text(encoding='utf-8'))['skip']) if sk.exists() else set()
    todo = [k for k in keys if k not in done and k not in skip]
    f404 = HD / (f'_404_{jyo}.txt' if jyo else '_404.txt')
    print(f'場 {js}・間隔 {gap}・全 {len(keys)}・残り {len(todo)}', flush=True)
    s = requests.Session()
    last = 0.0
    n200 = n404 = nerr = streak = 0
    for i, k in enumerate(todo):
        if jyo and STOP.exists():
            print('_STOP を見て止まる', flush=True); return
        for t in range(4):
            w = gap - (time.time() - last)
            if w > 0:
                time.sleep(w)
            last = time.time()
            try:
                r = s.get(URL.format(k[:8], k[8:]), timeout=30)
                if r.status_code == 200:
                    (HD / f'{k}.html').write_bytes(r.content); n200 += 1; streak = 0
                    break
                if r.status_code == 404:
                    with open(f404, 'a', encoding='utf-8') as f:
                        f.write(k + '\n')
                    n404 += 1; streak = 0
                    break
                if r.status_code in (429, 503):
                    streak += 1
                raise RuntimeError(f'status {r.status_code}')
            except (requests.ConnectionError, requests.Timeout) as e:
                streak += 1
                err = e
            except Exception as e:  # noqa: BLE001
                err = e
            if jyo and streak >= 5:
                STOP.write_text(f'{jyo} {k} {err}', encoding='utf-8')
                print('⛔ 5 回続いた: _STOP', k, err, flush=True); return
            if t == 3:
                nerr += 1
                print('失敗', k, err, flush=True)
            else:
                time.sleep(10 * (t + 1))
        if i % 200 == 0:
            print(f'{i}/{len(todo)} {k} 200={n200} 404={n404} err={nerr}', flush=True)
    print(f'終わり 200={n200} 404={n404} err={nerr}', flush=True)


TD = re.compile(r'<td([^>]*)>(.*?)</td>', re.S)
TDH = re.compile(r'<(td|th)([^>]*)>(.*?)</\1>', re.S)
TAG = re.compile(r'<[^>]+>')


def cell(x):
    return re.sub(r'\s+', ' ', TAG.sub('', x).replace('&nbsp;', ' ')).strip()


def tsec(x):
    m = re.fullmatch(r'(?:(\d+):)?(\d+(?:\.\d+)?)', x)
    return (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else float('nan')


def parse_one(p):
    """2023 年までの形(table.tb01・全部 td)と 2024 年からの形(table.js-fixed1-table の tbody・R と距離は th)の両方を読む。"""
    h = p.read_bytes().decode('cp932', errors='replace')
    a = h.find('js-fixed1-table')
    if a >= 0:
        a = h.find('<tbody', a)
        cs = [(t, attr, cell(v)) for t, attr, v in TDH.findall(h[a:h.find('</table>', a)])]
    else:
        a = h.find('<table class="tb01')
        if a < 0:
            return []
        cs = [('td', attr, cell(v)) for attr, v in TD.findall(h[a:h.find('</table>', a)])]
    cs = [(t, attr, v) for t, attr, v in cs]
    rows, i, R, dist, ordn = [], 0, None, None, 0
    while i < len(cs):
        if cs[i][0] == 'th' or not ('al-left' in cs[i][1] or 'is-left' in cs[i][1]):  # R と距離(新しい R の頭)
            R, dist, ordn = cs[i][2], cs[i + 1][2], 0
            i += 2
        v = [c[2] for c in cs[i:i + 11]]
        if len(v) < 11:
            break
        ordn += 1
        rows.append({'key': p.stem, 'R': R, 'dist': dist, 'name': v[0], 'sire': v[1], 'dam': v[2], 'jockey': v[3],
                     'trainer': v[4], 'sexage': v[5], 'weight': v[6], 'kind': v[7], 'time': v[8], 'result': v[9],
                     'damsire': v[10], 'ord': ordn})
        i += 11
    return rows


def parse():
    rows = []
    for p in sorted(HD.glob('*.html')):
        rows += parse_one(p)
    d = pd.DataFrame(rows)
    d['date'] = pd.to_datetime(d.key.str[:8], format='%Y%m%d')
    d['jyo'] = d.key.str[8:].astype(int)
    d['R'] = pd.to_numeric(d.R, errors='coerce')
    d['dist'] = pd.to_numeric(d.dist, errors='coerce')
    d['time_sec'] = d.time.map(tsec)
    d.drop(columns='key').to_parquet(OUT, index=False)
    n404 = sum(len(f.read_text(encoding='utf-8').split()) for f in HD.glob('_404*.txt'))
    print('HTML', len(list(HD.glob('*.html'))), '404', n404, '行', len(d), '日', d[['date', 'jyo']].drop_duplicates().shape[0])
    print(d.kind.value_counts().to_dict(), d.result.value_counts().head(8).to_dict())
    print('タイム欠け', d.time_sec.isna().mean(), '距離', d.dist.value_counts().head(6).to_dict())


if __name__ == '__main__':
    if sys.argv[1] == 'fetch':
        fetch(sys.argv[2] if len(sys.argv) > 2 else None, float(sys.argv[3]) if len(sys.argv) > 3 else 0.5)
    else:
        parse()
