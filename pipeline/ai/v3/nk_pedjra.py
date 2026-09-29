# -*- coding: utf-8 -*-
"""南関のその日の出走馬の血統(父・母・母父・生年)と中央の成績を nankankeiba.com の馬ページから取る(ユーザー承認 2026-09-29「足す」)。

  python -X utf8 pipeline/ai/v3/nk_pedjra.py DATE OUTDIR [--cache DIR]

1. 開催の一覧 /calendar/{年}{期の初月}.do → その日の南関 4 場(18 浦和・19 船橋・20 大井・21 川崎)の /program/{日付}{場}{回}{日}.do
   → 出馬表 /syousai/{…}{R}.do → 馬ページ /uma_info/{血統登録番号 10 桁}.do(= kd_horse.ketto)。
2. 1.5 秒おき・User-Agent は requests の既定(nk_fetch の作法)。429/503 は 30 秒待って 1 回だけやり直し。取れない馬は飛ばす。
   429/503・接続の失敗が 5 回続いたらそこで止める(取れた分だけ書く)。
3. 出力(OUTDIR = 便では V3_KD。状態は持たない = その日の出走馬だけ):
   kd_live_horse.parquet    … kd_horse と同じ列(ketto・birth・name・sex・sire・dam・bms・owner・breeder・area・birth_year・src='NK'、他は空)
   kd_live_jra_runs.parquet … kd_jra_runs と同じ列(中央 10 場の走りだけ。year・jyo・race・umaban・ketto・name・date・finish・time_sec・
                              l3f・pop・kinryo・weight・dist・n_starters・surface・birth_year、他は空)。取消・除外は finish=0。
   足し方は v7d_run.kd_horse()・kd_jra_runs()(固定ファイルは書き換えない)。
--cache DIR: 取った HTML を DIR に置き、あれば読み直す(手元の照合用。便では使わない)。
"""
import re
import sys
import time
import unicodedata
from datetime import date as Date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = 'https://www.nankankeiba.com'
GAP = 1.5
NK = {'18', '19', '20', '21'}
JRA = {'札幌': 1, '函館': 2, '福島': 3, '新潟': 4, '東京': 5, '中山': 6, '中京': 7, '京都': 8, '阪神': 9, '小倉': 10}
SEX = {'牡': 1.0, '牝': 2.0, 'セ': 3.0, 'せ': 3.0}
V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))


def log(*a):
    print('[nk_pedjra]', *a, flush=True)


class Getter:
    def __init__(self, cache=None):
        self.s, self.last, self.streak, self.n = requests.Session(), 0.0, 0, 0
        self.cache = Path(cache) if cache else None
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)

    def get(self, path):
        cp = self.cache / (path.strip('/').replace('/', '_') + '.html') if self.cache else None
        if cp and cp.exists():
            return cp.read_bytes().decode('cp932', 'replace')
        if self.streak >= 5:
            raise RuntimeError('5 回続いて失敗・止める')
        for t in range(2):
            w = GAP - (time.time() - self.last)
            if w > 0:
                time.sleep(w)
            self.last = time.time()
            self.n += 1
            try:
                r = self.s.get(BASE + path, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as e:
                self.streak += 1
                if t == 0:
                    time.sleep(30); continue
                raise RuntimeError(f'{path} {e}')
            if r.status_code == 200:
                self.streak = 0
                if cp:
                    cp.write_bytes(r.content)
                return r.content.decode('cp932', 'replace')
            if r.status_code in (429, 503):
                self.streak += 1
                if t == 0:
                    time.sleep(30); continue
            raise RuntimeError(f'{path} status {r.status_code}')


def text(h):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h).replace('&nbsp;', ' '))


def nfkc(x):
    return unicodedata.normalize('NFKC', x).strip() if isinstance(x, str) else x


ROW = re.compile(r'(\d{4}) (\d\d)/(\d\d) (\S+?)☆? (\S+) 着 /(\d+) 頭 (.*) (\S+) (\S+)/(\S+) (\S+) (\S+) (\S+) (\S+) '
                 r'(\d+)R (\d+)m(?:/(\S+))? (\d+) 番 (\d+) 人(?: (\S+) (\d+|計不|-) ([\d.]+))?')


def tsec(x):
    m = re.fullmatch(r'(?:(\d+):)?(\d+(?:\.\d+)?)', x or '')
    return float(m.group(1) or 0) * 60 + float(m.group(2)) if m else np.nan


def surface(suf):
    """距離の後ろの表示(「1200m/芝」の「芝」)。中央ダートの表示は 2026-09-28/29 の実例で確かめて決めた(out/v13live.md)。"""
    s = suf or ''
    if '芝' in s:
        return '芝'
    if '障' in s:
        return '障'
    return 'ダ'


def corp(x):
    """馬主・生産者の法人の印((株)・(有)・(組) 等・株式会社・有限会社・合同会社)を消す。"""
    x = unicodedata.normalize('NFKC', x or '')
    x = re.sub(r'\([^()]{1,2}\)|(株式会社|有限会社|合同会社)', '', x)
    return re.sub(r'\s+', ' ', x).strip() or None


def parse_uma(h, ketto):
    t = text(h)
    pd3 = re.search(r'父 \(\S+\) (.+?) 母 \(\S+\) (.+?) 母父 \(\S+\) (.+?) 生年月日', t)  # 外国馬は名前に空白あり
    g = lambda i: nfkc(pd3.group(i)) if pd3 else None
    b = re.search(r'生年月日 (\d{4})年(\d+)月(\d+)日', t)
    head = t[t.find('競走馬詳細データ'):]
    nm = re.search(r'現在 (\S+) （\S+?）\s?(\S)', head)
    ob = re.match(r'馬主名 (.+?) 生産牧場 (.+?) 生産地 (\S+) 総収得賞金', t[t.rfind('馬主名'):])  # 2 つ目の欄(格の混ざらない方)
    owner = breeder = area = None
    if ob:  # kd_horse の書き方に寄せる: 法人の印を消す・生産地は都道府県と郡を消す
        owner, breeder = (corp(ob.group(i)) for i in (1, 2))
        area = re.sub(r'^(北海道|東京都|京都府|大阪府|.{2,3}県)', '', ob.group(3))
        area = re.sub(r'^\S+?郡', '', area)
        area = {'新ひだか': '新ひだか町'}.get(area, area) or None  # 馬ページは「新ひだか」までしか出ない
    birth = int(b.group(1)) * 10000 + int(b.group(2)) * 100 + int(b.group(3)) if b else np.nan
    name = nm.group(1) if nm else None
    horse = {'ketto': float(ketto), 'birth': float(birth), 'name': name, 'sex': SEX.get(nm.group(2), np.nan) if nm else np.nan,
             'sire': g(1), 'dam': g(2), 'bms': g(3), 'owner': owner, 'breeder': breeder, 'area': area,
             'birth_year': float(birth // 10000) if b else np.nan, 'src': 'NK'}
    a, z = t.find('出走履歴'), t.find('年月日 場名 R')
    rows, bad = [], 0
    for seg in re.split(r' (?=20\d\d \d\d/\d\d )', t[a:z] if a >= 0 else ''):
        if not re.match(r'20\d\d \d\d/\d\d ', seg):
            continue
        m = ROW.match(seg)
        if not m:
            bad += 1
            continue
        jo = m.group(4)
        if jo not in JRA:
            continue
        fin = pd.to_numeric(nfkc(m.group(5)), errors='coerce')
        l3 = pd.to_numeric(m.group(13), errors='coerce')
        wt = pd.to_numeric(m.group(21), errors='coerce') if m.group(21) else np.nan
        rows.append({'year': float(m.group(1)), 'jyo': float(JRA[jo]), 'race': float(m.group(15)), 'umaban': float(m.group(18)),
                     'ketto': float(ketto), 'name': name, 'date': pd.Timestamp(f'{m.group(1)}-{m.group(2)}-{m.group(3)}'),
                     'finish': 0.0 if pd.isna(fin) else float(fin), 'time_sec': tsec(m.group(11)), 'l3f': l3,
                     'pop': float(m.group(19)), 'kinryo': pd.to_numeric(m.group(22), errors='coerce') if m.group(22) else np.nan,
                     'weight': wt, 'dist': float(m.group(16)), 'n_starters': float(m.group(6)),
                     'surface': '障' if '障害' in m.group(7) else surface(m.group(17)), 'surf_raw': m.group(17) or '', 'birth_year': horse['birth_year']})
    return horse, rows, bad


def like(df, fixed_path):
    """固定ファイルと同じ列・同じ型にする(固定ファイルは読むだけ・列の型は schema から)。"""
    import pyarrow.parquet as pq
    sch = pq.read_schema(fixed_path)
    out = pd.DataFrame(index=df.index)
    for f in sch:
        c, ty = f.name, str(f.type)
        v = df[c] if c in df.columns else pd.Series([None] * len(df), index=df.index)
        if ty.startswith('timestamp'):
            out[c] = pd.to_datetime(v).astype('datetime64[ns]')
        elif ty in ('double', 'float', 'int64', 'int32'):
            out[c] = pd.to_numeric(v, errors='coerce').astype('float64' if ty in ('double', 'float') else 'Int64')
        else:
            out[c] = v.astype(object).where(v.notna(), None)
    return out


def programs(G, day):
    d = Date.fromisoformat(day)
    q = f'{d.year}{(d.month - 1) // 3 * 3 + 1:02d}'
    ds = d.strftime('%Y%m%d')
    for cal in (f'/calendar/{q}.do', '/calendar/000000.do'):
        try:
            h = G.get(cal)
        except RuntimeError as e:
            log('calendar', cal, e); continue
        p = sorted({x for x in re.findall(r'/program/(\d{14})\.do', h) if x[:8] == ds and x[8:10] in NK})
        if p:
            return p
    return []


def main():
    a = sys.argv[1:]
    day, out = a[0], Path(a[1])
    cache = a[a.index('--cache') + 1] if '--cache' in a else None
    G = Getter(cache)
    H, R, nbad, nfail = [], [], 0, 0
    try:
        progs = programs(G, day)
        log('day', day, 'program', progs)
        races = []
        for p in progs:
            races += sorted(set(re.findall(r'/syousai/(%s\d{2})\.do' % p, G.get(f'/program/{p}.do'))))
        ids = []
        for r in races:
            ids += re.findall(r'/uma_info/(\d{10})\.do', G.get(f'/syousai/{r}.do'))
        ids = list(dict.fromkeys(ids))
        log('races', len(races), 'horses', len(ids))
        for k in ids:
            try:
                h, rows, bad = parse_uma(G.get(f'/uma_info/{k}.do'), int(k))
            except RuntimeError as e:
                nfail += 1
                log('失敗', e)
                if G.streak >= 5:
                    break
                continue
            H.append(h); R += rows; nbad += bad
    except RuntimeError as e:
        log('止まった', e)
    log('fetch', G.n, 'horses', len(H), 'fail', nfail, 'unread_rows', nbad, 'jra_runs', len(R))
    if not H:
        log('何も取れない = live を書かない(固定ファイルのまま)'); return
    out.mkdir(parents=True, exist_ok=True)
    Hd = pd.DataFrame(H).drop_duplicates('ketto')
    Rd = pd.DataFrame(R, columns=['year', 'jyo', 'race', 'umaban', 'ketto', 'name', 'date', 'finish', 'time_sec', 'l3f', 'pop',
                                  'kinryo', 'weight', 'dist', 'n_starters', 'surface', 'surf_raw', 'birth_year'])
    if len(Rd):
        log('中央の距離の後ろの表示', Rd.surf_raw.value_counts().to_dict())
        Rd = Rd.drop_duplicates(['ketto', 'date', 'jyo', 'race'])
    for df, fixed, name in ((Hd, 'kd_horse.parquet', 'kd_live_horse.parquet'), (Rd, 'kd_jra_runs.parquet', 'kd_live_jra_runs.parquet')):
        fp = V3 / fixed
        x = like(df, fp) if fp.exists() else df
        tmp = out / (name + '.tmp')
        x.to_parquet(tmp, index=False)
        tmp.replace(out / name)
        log('書いた', out / name, len(x))


if __name__ == '__main__':
    main()
