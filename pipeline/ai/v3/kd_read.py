"""KDSCOPE(C:/KDSCOPE/Data)の JV-Data 形式の固定長ファイルを読む(読むだけ・書き込みしない)。

書式は v3/spec/JV-Data4901.xlsx(SE 555・RA 1272・UM 1609・HN 251 バイト、末尾 CR/LF)。
NU は UM と同じ並び(馬主名まで)と仮定し、レコード長は実物の 1492。
NS(315)・NR(434)は仕様書が無いので、先頭を見て推定した位置で読み、確かめてから使う。
出力: v3/kd_se.parquet・kd_horse.parquet・kd_jra_runs.parquet・(確かめられたら)kd_noken.parquet、out/kd_read.md
"""
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

KD = __import__('os').environ.get('V3_KD', 'C:/KDSCOPE/Data').rstrip('/') + '/'
V3 = __import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3').rstrip('/') + '/'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'out', 'kd_read.md')
sys.path.insert(0, HERE)

NANKAN = {42: '浦和', 43: '船橋', 44: '大井', 45: '川崎'}
REP = []  # 報告の行


def say(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    REP.append(s)


def md(df):
    df = df.reset_index()
    h = [str(c) for c in df.columns]
    rows = ["| " + " | ".join(h) + " |", "|" + "---|" * len(h)]
    for r in df.itertuples(index=False):
        rows.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(rows)


# ---------- 固定長の道具 ----------
def num(arr, s, l):
    sub = arr[:, s:s + l].astype(np.int64) - 48
    ok = ((sub >= 0) & (sub <= 9)).all(1)
    v = (sub * (10 ** np.arange(l - 1, -1, -1))).sum(1).astype(np.float64)
    v[~ok] = np.nan
    return v


def sstr(arr, s, l):
    b = np.ascontiguousarray(arr[:, s:s + l]).view(f'S{l}').ravel()
    return [x.decode('cp932', 'replace').replace('\u3000', ' ').strip() for x in b]


def chunks(path, L, head, n=200000):
    """L バイトずつの記録を n 件ずつ返す。頭 2 文字と末尾 CR/LF を確かめる。"""
    bad = 0
    with open(path, 'rb') as f:
        while True:
            buf = f.read(L * n)
            if not buf:
                break
            if len(buf) % L:
                raise SystemExit(f'要判断: {path} の長さが {L} の倍数でない')
            a = np.frombuffer(buf, dtype=np.uint8).reshape(-1, L)
            ok = (a[:, 0] == ord(head[0])) & (a[:, 1] == ord(head[1])) & (a[:, L - 2] == 13) & (a[:, L - 1] == 10)
            bad += int((~ok).sum())
            yield a[ok]
    if bad:
        say(f'  注意: {os.path.basename(path)} で頭・区切りの合わない記録 {bad} 件を除いた')


def norm(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ''
    s = unicodedata.normalize('NFKC', str(s))
    s = re.sub(r'(株式会社|有限会社|\(株\)|\(有\)|㈱|㈲)', '', s)
    return re.sub(r'\s+', '', s)


def t4(v):  # 1234 → 1分23秒4
    v = np.asarray(v, dtype=float)
    out = (v // 1000) * 60 + (v % 1000) / 10
    out[(v <= 0) | np.isnan(v)] = np.nan
    return out


# ---------- 1. SE ----------
def read_se():
    dst = V3 + 'kd_se.parquet'
    files = sorted(x for x in os.listdir(KD + 'SE') if x.endswith('.DAT'))
    writer = None
    cnt = Counter()
    total = 0
    for fn in files:
        for a in chunks(KD + 'SE/' + fn, 555, 'SE'):
            if len(a) == 0:
                continue
            d = {
                'file': [fn] * len(a),
                'kubun': sstr(a, 2, 1),
                'year': num(a, 11, 4), 'md': num(a, 15, 4), 'jyo': num(a, 19, 2),
                'kaiji': num(a, 21, 2), 'nichiji': num(a, 23, 2), 'race': num(a, 25, 2),
                'waku': num(a, 27, 1), 'umaban': num(a, 28, 2),
                'ketto': num(a, 30, 10), 'name': sstr(a, 40, 36),
                'sex': num(a, 78, 1), 'age': num(a, 82, 2),
                'trainer_cd': sstr(a, 85, 5), 'trainer': sstr(a, 90, 8),
                'kinryo': num(a, 288, 3) / 10, 'jockey_cd': sstr(a, 296, 5), 'jockey': sstr(a, 306, 8),
                'weight': num(a, 324, 3), 'wsign': sstr(a, 327, 1), 'wdiff': num(a, 328, 3),
                'ijo': num(a, 331, 1), 'nyusen': num(a, 332, 2), 'finish': num(a, 334, 2),
                'time_raw': num(a, 338, 4),
                'c1': num(a, 351, 2), 'c2': num(a, 353, 2), 'c3': num(a, 355, 2), 'c4': num(a, 357, 2),
                'odds': num(a, 359, 4) / 10, 'pop': num(a, 363, 2), 'prize': num(a, 365, 8),
                'l4f': num(a, 387, 3) / 10, 'l3f': num(a, 390, 3) / 10,
                'tdiff': sstr(a, 531, 4), 'kyakushitsu': num(a, 552, 1),
            }
            d['time_sec'] = t4(d['time_raw'])
            for k in ('l3f', 'l4f'):
                d[k] = np.where(d[k] >= 99.9, np.nan, d[k])
            df = pd.DataFrame(d)
            df['date'] = pd.to_datetime((df.year * 10000 + df.md).astype('Int64').astype(str), format='%Y%m%d', errors='coerce')
            t = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(dst, t.schema)
            writer.write_table(t)
            total += len(df)
            cen = df.jyo.between(1, 10)
            for (y, c), n in df.groupby([df.year, np.where(cen, '中央', '地方ほか')]).size().items():
                cnt[(int(y), c)] += n
    writer.close()
    say(f'## 1. SE(馬毎レース情報)\n読んだ記録 {total:,} 件({len(files)} ファイル)→ v3/kd_se.parquet')
    tab = pd.Series(cnt).unstack(fill_value=0).sort_index()
    say('\n年ごとの件数(場コード 01〜10 = 中央)\n')
    say(md(tab))
    return tab


# ---------- RA ----------
def read_ra():
    parts = []
    for a in chunks(KD + 'RA/RA.DAT', 1272, 'RA'):
        parts.append(pd.DataFrame({
            'ra_kubun': sstr(a, 2, 1), 'make': num(a, 3, 8),
            'year': num(a, 11, 4), 'md': num(a, 15, 4), 'jyo': num(a, 19, 2),
            'kaiji': num(a, 21, 2), 'nichiji': num(a, 23, 2), 'race': num(a, 25, 2),
            'dist': num(a, 697, 4), 'track': num(a, 705, 2), 'n_starters': num(a, 883, 2),
            'baba_turf': num(a, 888, 1), 'baba_dirt': num(a, 889, 1),
        }))
    ra = pd.concat(parts, ignore_index=True)
    n0 = len(ra)
    key = ['year', 'md', 'jyo', 'kaiji', 'nichiji', 'race']
    ra = ra.sort_values('make').drop_duplicates(key, keep='last')
    say(f'\n## RA(レース詳細)\n読んだ記録 {n0:,} 件・重複を除いて {len(ra):,} レース・年 {int(ra.year.min())}〜{int(ra.year.max())}'
        f'(中央 {int(ra.jyo.between(1, 10).sum()):,}・地方ほか {int((~ra.jyo.between(1, 10)).sum()):,})')
    return ra


# ---------- 2. 南関の照らし合わせ ----------
def check_nankan():
    se = pd.read_parquet(V3 + 'kd_se.parquet', columns=['jyo', 'date', 'race', 'umaban', 'name', 'finish', 'ketto'],
                         filters=[('jyo', 'in', [42.0, 43.0, 44.0, 45.0])])
    say(f'\n## 2. SE の南関分と手元の走りの照らし合わせ\nKDSCOPE の南関(42〜45)の記録 {len(se):,} 件')
    if len(se) == 0:
        say('KDSCOPE に南関の走りは無い')
        return se
    se['track'] = se.jyo.astype(int).map(NANKAN)
    se['race_date'] = se.date.dt.strftime('%Y-%m-%d')
    se = se.drop_duplicates(['track', 'race_date', 'race', 'umaban'], keep='last')
    say(f'年の範囲 {se.date.min():%Y-%m-%d}〜{se.date.max():%Y-%m-%d}')
    from load_outcomes import load_archive
    cols = ['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'finish']
    loc = [load_archive('runs')[cols]]
    for f in ['db_runs_confirm_2022-01_2025-08.parquet', 'db_runs_sealed_2025-09_2026-08.parquet']:
        loc.append(pd.read_parquet(V3 + f, columns=cols))
    loc = pd.concat(loc, ignore_index=True)
    loc = loc[loc.track.isin(NANKAN.values())].copy()
    loc['race_date'] = loc.race_date.astype(str).str[:10]
    loc = loc.drop_duplicates(['track', 'race_date', 'race_no', 'runner_number'], keep='last')
    loc['race'] = loc.race_no.astype(float)
    loc['umaban'] = loc.runner_number.astype(float)
    m = loc.merge(se, on=['track', 'race_date', 'race', 'umaban'], how='left', suffixes=('_l', '_k'))
    m['year'] = m.race_date.str[:4]
    m['found'] = m.name.notna()
    m['name_ok'] = m.found & (m.horse_name.map(norm) == m.name.map(norm))
    fin = m.found & (m.finish_l > 0) & (m.finish_k > 0)
    m['fin_cmp'] = fin
    m['fin_ok'] = fin & (m.finish_l == m.finish_k)
    g = m.groupby('year').agg(手元の走り=('found', 'size'), KDにある=('found', 'sum'),
                              馬名一致=('name_ok', 'sum'), 着順比べた=('fin_cmp', 'sum'), 着順一致=('fin_ok', 'sum'))
    g['KDにある%'] = (100 * g.KDにある / g.手元の走り).round(2)
    g['馬名一致%'] = (100 * g.馬名一致 / g.KDにある.clip(lower=1)).round(2)
    g['着順一致%'] = (100 * g.着順一致 / g.着順比べた.clip(lower=1)).round(2)
    say('\n手元の南関の走り(2014〜2026-08)を (場・日付・R・馬番) で KDSCOPE とつないだ結果\n')
    say(md(g))
    return se


# ---------- 3. UM・NU・HN ----------
def read_master(path, L, head):
    parts = []
    for a in chunks(path, L, head):
        d = {'kubun': sstr(a, 2, 1), 'make': num(a, 3, 8), 'ketto': num(a, 11, 10),
             'massho': num(a, 21, 1), 'birth': num(a, 38, 8), 'name': sstr(a, 46, 36),
             'sex': num(a, 200, 1), 'keiro': num(a, 202, 2)}
        for k, nm in enumerate(['sire', 'dam', 'ss', 'sd', 'bms', 'ds']):
            d[nm + '_id'] = num(a, 204 + 46 * k, 10)
            d[nm] = sstr(a, 214 + 46 * k, 36)
        d.update({'tozai': num(a, 848, 1), 'trainer_cd': sstr(a, 849, 5), 'trainer': sstr(a, 854, 8),
                  'breeder_cd': sstr(a, 882, 8), 'breeder': sstr(a, 890, 72), 'area': sstr(a, 962, 20),
                  'owner_cd': sstr(a, 982, 6), 'owner': sstr(a, 988, 64)})
        parts.append(pd.DataFrame(d))
    df = pd.concat(parts, ignore_index=True)
    return df.sort_values('make').drop_duplicates('ketto', keep='last')


def read_hn():
    parts = []
    for a in chunks(KD + 'HN1/HN.DAT', 251, 'HN'):
        parts.append(pd.DataFrame({'make': num(a, 3, 8), 'hn_id': num(a, 11, 10), 'hn_name': sstr(a, 40, 36)}))
    hn = pd.concat(parts, ignore_index=True)
    return hn.sort_values('make').drop_duplicates('hn_id', keep='last')


def read_pckeiba():
    rows = []
    with open(V3 + 'pckeiba_uma_chiho.csv', encoding='cp932', errors='replace') as f:
        head = re.findall(r'="((?:[^"]|"")*)"', f.readline())
        for line in f:
            v = re.findall(r'="((?:[^"]|"")*)"', line)
            if len(v) == len(head):
                rows.append(v)
    return pd.DataFrame(rows, columns=head)


def horses():
    say('\n## 3. 馬の台帳(UM・NU)')
    um = read_master(KD + 'UM1/UM.DAT', 1609, 'UM')
    um['src'] = 'UM'
    nu = read_master(KD + 'NU1/NU.DAT', 1492, 'NU')
    nu['src'] = 'NU'
    hn = read_hn()
    say(f'UM(中央の競走馬マスタ){len(um):,} 頭・NU(地方の競走馬マスタ・UM と同じ並びと仮定・長さ 1492){len(nu):,} 頭・HN(繁殖馬){len(hn):,} 頭')
    hmap = dict(zip(hn.hn_id, hn.hn_name))
    df = pd.concat([um, nu], ignore_index=True)
    filled = 0
    for nm in ['sire', 'dam', 'ss', 'sd', 'bms', 'ds']:
        blank = (df[nm] == '') & df[nm + '_id'].notna() & (df[nm + '_id'] > 0)
        df.loc[blank, nm] = df.loc[blank, nm + '_id'].map(hmap).fillna('')
        filled += int(blank.sum())
    say(f'血統の名前が空で HN の名前で埋めた数 {filled:,}(せりの値段は UM・NU に項目が無く、入っていない)')
    df['birth_year'] = (df.birth // 10000)
    df.to_parquet(V3 + 'kd_horse.parquet', index=False)
    say('保存 v3/kd_horse.parquet(UM と NU を src 列で区別して縦につないだ)')
    by = df.groupby(['birth_year', 'src']).size().unstack(fill_value=0)
    by = by[by.index >= 1990]
    say('\n生まれ年ごとの頭数(1990 年以降)\n')
    say(md(by))
    # 照らし合わせ
    pk = read_pckeiba()
    pk['key'] = pk['馬名'].map(norm) + '|' + pk['生年月日'].str.replace('/', '')
    pk = pk.drop_duplicates('key', keep=False)
    nu2 = nu.copy()
    nu2['key'] = nu2.name.map(norm) + '|' + nu2.birth.astype('Int64').astype(str)
    nu2 = nu2.drop_duplicates('key', keep=False)
    j = pk.merge(nu2, on='key', how='inner')
    res = {}
    for a, b in [('父', 'sire'), ('母', 'dam'), ('母父', 'bms'), ('生産者', 'breeder'), ('産地名', 'area'), ('馬主', 'owner')]:
        res[a] = 100 * (j[a].map(norm) == j[b].map(norm)).mean()
    say(f'\nNU と pckeiba_uma_chiho.csv({len(pk):,} 頭)を 馬名+生年月日 でつないだ: {len(j):,} 頭'
        f'(pckeiba の {100 * len(j) / max(len(pk), 1):.1f}%)')
    say('一致率 %: ' + '・'.join(f'{k} {v:.2f}' for k, v in res.items()))
    return df, res


# ---------- 4. 中央での成績 ----------
def jra_runs(ra):
    se = pd.read_parquet(V3 + 'kd_se.parquet',
                         columns=['year', 'md', 'jyo', 'kaiji', 'nichiji', 'race', 'umaban', 'ketto', 'name', 'date',
                                  'finish', 'time_sec', 'l3f', 'pop', 'odds', 'kinryo', 'weight', 'age', 'kubun'],
                         filters=[('jyo', '>=', 1.0), ('jyo', '<=', 10.0)])
    key = ['year', 'md', 'jyo', 'kaiji', 'nichiji', 'race']
    n0 = len(se)
    se = se.drop_duplicates(key + ['umaban'], keep='last')
    se = se.merge(ra[key + ['dist', 'track', 'n_starters']], on=key, how='left')
    tr = se.track
    se['surface'] = np.select([tr.between(10, 22), tr.between(23, 29), tr.between(51, 59)], ['芝', 'ダ', '障'], '')
    se['birth_year'] = se.ketto // 1000000
    se = se.sort_values(['ketto', 'date'])
    se.drop(columns=['kaiji', 'nichiji', 'md']).to_parquet(V3 + 'kd_jra_runs.parquet', index=False)
    say(f'\n## 4. 中央での成績の表\n中央の場(01〜10)の記録 {n0:,} 件・重複を除いて {len(se):,} 件・{se.ketto.nunique():,} 頭'
        f'・{se.date.min():%Y-%m-%d}〜{se.date.max():%Y-%m-%d}・RA とつながった {100 * se.dist.notna().mean():.2f}%'
        f' → v3/kd_jra_runs.parquet(血統登録番号・日付の順)')


# ---------- 5. 能力試験(NS・NR) ----------
def noken():
    say('\n## 5. 能力試験(NS・NR・仕様書なし)')
    ns = pd.concat([pd.DataFrame({
        'make': num(a, 3, 8), 'year': num(a, 11, 4), 'md': num(a, 15, 4), 'jyo': num(a, 19, 2),
        'heat': num(a, 21, 2), 'umaban': num(a, 23, 2), 'ketto': num(a, 25, 10), 'name': sstr(a, 35, 36),
        'sex': num(a, 71, 1), 'age': num(a, 75, 2), 'trainer': sstr(a, 82, 8), 'jockey': sstr(a, 103, 16),
        'weight': num(a, 119, 3), 'ijo': num(a, 126, 1), 'finish': num(a, 127, 2), 'time_raw': num(a, 131, 4),
    }) for a in chunks(KD + 'NS/NS.DAT', 315, 'NS')], ignore_index=True)
    nr = pd.concat([pd.DataFrame({
        'year': num(a, 11, 4), 'md': num(a, 15, 4), 'jyo': num(a, 19, 2), 'heat': num(a, 21, 2),
        'youbi': num(a, 23, 1), 'dist': num(a, 24, 4),
    }) for a in chunks(KD + 'NR/NR.DAT', 434, 'NR')], ignore_index=True)
    say(f'NS {len(ns):,} 件・NR {len(nr):,} 組・年 {int(ns.year.min())}〜{int(ns.year.max())}・場 '
        + '・'.join(f'{NANKAN.get(int(k), k)} {v}' for k, v in ns.jyo.value_counts().sort_index().items()))
    say('推定した位置(0 始まり): 年 11・月日 15・場 19・組 21・馬番 23・血統登録番号 25・馬名 35(36)・馬齢 75・着順 127・タイム 131(4 桁 = 分秒 1 位)。NR: 曜日 23・距離 24(4)')
    ns['date'] = pd.to_datetime((ns.year * 10000 + ns.md).astype('Int64').astype(str), format='%Y%m%d', errors='coerce')
    ns['time_sec'] = t4(ns.time_raw)
    nr['date'] = pd.to_datetime((nr.year * 10000 + nr.md).astype('Int64').astype(str), format='%Y%m%d', errors='coerce')
    # 曜日の確かめ(土 1・日 2 … 金 7 と推定)
    wd = (nr.date.dt.dayofweek + 2) % 7 + 1  # Mon=0 → 3
    ok_wd = 100 * (wd == nr.youbi).mean()
    ns = ns.merge(nr[['date', 'jyo', 'heat', 'dist']].drop_duplicates(['date', 'jyo', 'heat']), on=['date', 'jyo', 'heat'], how='left')
    join_nr = 100 * ns.dist.notna().mean()
    # タイムのもっともらしさ(200m あたりの秒)
    t = ns[(ns.time_sec > 0) & (ns.dist > 0)]
    per = t.time_sec / (t.dist / 200)
    in_rng = 100 * per.between(11, 20).mean()
    # デビュー前か: SE の同じ血統登録番号の最初の走り
    se = pd.read_parquet(V3 + 'kd_se.parquet', columns=['ketto', 'date', 'jyo'])
    first = se[se.ketto > 0].groupby('ketto').date.min()
    f = ns.groupby('ketto').date.min().rename('ns_first').to_frame().join(first.rename('debut'), how='inner')
    pre_se = 100 * (f.ns_first <= f.debut).mean() if len(f) else np.nan
    # 手元の南関の走り(馬名)でも
    from load_outcomes import load_archive
    loc = load_archive('runs')[['track', 'race_date', 'horse_name']]
    loc = loc[loc.track.isin(NANKAN.values())]
    ld = loc.groupby(loc.horse_name.map(norm)).race_date.min()
    ns14 = ns[ns.year >= 2014]
    g = ns14.groupby(ns14.name.map(norm)).date.min().rename('ns_first').to_frame()
    g = g.join(pd.to_datetime(ld).rename('debut'), how='inner')
    g = g[g.debut >= pd.Timestamp('2014-04-01')]  # 手元の走りの頭の外は除く
    pre_loc = 100 * (g.ns_first <= g.debut).mean() if len(g) else np.nan
    say(f'確かめ: NR の曜日が日付と合う {ok_wd:.2f}%・NS が NR の組とつながる {join_nr:.2f}%'
        f'・200m あたり 11〜20 秒に入る {in_rng:.2f}%(中央値 {per.median():.2f} 秒・距離 '
        + '・'.join(f'{int(k)}m {v}' for k, v in t.dist.value_counts().sort_index().items()) + ')')
    say(f'デビュー前か: SE の同じ血統登録番号の最初の走りより前か同じ日 {pre_se:.2f}%({len(f):,} 頭)'
        f'・手元の南関の走り(馬名・2014-04 以降に初出走)より前 {pre_loc:.2f}%({len(g):,} 頭)')
    good = ok_wd >= 95 and join_nr >= 95 and in_rng >= 95 and (pre_se >= 90 or (len(f) == 0 and pre_loc >= 90))
    if good:
        keep = ['date', 'jyo', 'heat', 'umaban', 'ketto', 'name', 'sex', 'age', 'trainer', 'jockey', 'weight',
                'ijo', 'finish', 'time_raw', 'time_sec', 'dist']
        ns[keep].to_parquet(V3 + 'kd_noken.parquet', index=False)
        say('判定: 確かめられた(基準 曜日・組・範囲 95% 以上・デビュー前 90% 以上)→ v3/kd_noken.parquet')
    else:
        say('判定: 確かめられない → 使わない(要判断)')


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if stage in ('all', 'se') and not os.path.exists(V3 + 'kd_se.parquet'):
        read_se()
    elif os.path.exists(V3 + 'kd_se.parquet'):
        t = pq.read_table(V3 + 'kd_se.parquet', columns=['year', 'jyo']).to_pandas()
        tab = t.groupby([t.year, np.where(t.jyo.between(1, 10), '中央', '地方ほか')]).size().unstack(fill_value=0)
        say(f'## 1. SE(馬毎レース情報)\n読んだ記録 {len(t):,} 件 → v3/kd_se.parquet\n\n年ごとの件数(場コード 01〜10 = 中央)\n')
        say(md(tab))
    ra = read_ra()
    check_nankan()
    horses()
    jra_runs(ra)
    noken()
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('# KDSCOPE を読む(src/kd_read.py)\n\nC:/KDSCOPE/Data は読むだけ。書式は JV-Data4901.xlsx。\n\n' + '\n'.join(REP) + '\n')


if __name__ == '__main__':
    main()
