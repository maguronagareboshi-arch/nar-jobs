# -*- coding: utf-8 -*-
"""第 7 版 e: 第 7 版 d(177 列 = v7_select の 138 + c7_ 28 + j7_ 11)に新しい材料の候補 4 群を足して「作る期間」で judge。
既存の台本は import して呼ぶだけ(書き換えない)。答え合わせ(open)はしない。オッズ・人気(南関)は材料に使わない。

  py -3.12 -X utf8 src/v7e_run.py all    # feat → judge → md(できている段は飛ばす)

■ 決め(結果を見る前に決めた。結果を見て変えない)
  共通: 走り = 全 NAR の走り(v7c_run.sources)のうち 取消・除外 を除いたもの。騎手・調教師・馬名は NFKC・空白消し(vc.norm)。
        「前」= そのレースの日より前(当日を含まない)。当日に分かるのは 出馬表(その日の騎手・調教師・出走の顔ぶれ)だけ。
        レースの顔ぶれ = 予想する行(feat_t6 の行)の同じレースの馬。
  1. nk7_ 能力試験: KDSCOPE の NS・NR を kd_read.py §5 の推定位置で読む。タイム > 0 かつ距離 > 0 のとき 200m あたり秒 =
     タイム ÷(距離 ÷ 200)、rel = それ − 同じ日・同じ距離の試験の平均(小さいほど速い)。着順 > 0 のとき fr = 着順 ÷ 組の頭数。
     馬へのつなぎ = v7d と同じ(台帳の 馬名|生年 → 血統登録番号、無ければ中央の走りの 馬名|生年 → 血統登録番号)。
     列: nk7_n 試験の回数・nk7_days 最後の試験からの日数・nk7_last_rel・nk7_last_fr・nk7_last_fin 最後の試験の着順・
     nk7_best_rel rel の最小。つながって試験が無ければ nk7_n = 0・他は欠け。つながらない馬は全部欠け。
     試験は NS の最後の日まで(2020 年)しか無いので、レースの日がそれより後の行は全部欠け。合否・上がりは位置が分からないので入れない。
  2. s7_ 騎手の選択(v7_ideas3 案 A・§0-2 の定義): s7_chosen = 今回の騎手が、同じレースの別の馬の直近 3 走(全 NAR・前)のどれかに
     乗っていた 1/0(騎手が欠けなら欠け)。s7_aband = この馬の前走の騎手が今回同じレースの別の馬に乗る 1/0(前走が無ければ欠け)。
  3. f7_ 厩舎の騎手配置(案 F): 主戦 = その調教師の前 365 日(当日を含まない)の走りで組数が最大の騎手(同数は名前の順で先)。
     f7_main = この馬の騎手が主戦 1/0・f7_share = 主戦の組数 ÷ 365 日の全組数・f7_tr_day = その日その場の調教師の出走数・
     f7_main_day = そのうち主戦が乗る数。調教師に 365 日の走りが無ければ f7_tr_day 以外は欠け。調教師は名前だけで見分ける。
  4. m7_ 冠名(案 G): 馬名の頭 k 文字(k = 4・3・2、馬名が k より長いとき)。冠名 = 前に走った馬(別の馬)のうちその頭文字列の
     馬が 50 頭以上ある最長の頭文字列。m7_len = その長さ(無ければ 0)・m7_nh = その頭数・m7_n = その集団の前の走りの数
     (自分の走りを除く)・m7_ratio = (3 着以内の数 + 3) ÷ (期待 + 3)、期待 = 走りごとの min(3, 頭数) ÷ 頭数の和(自分を除く)。
     頭数 = そのレースの着順 > 0 の数。冠名が無ければ m7_nh・m7_n・m7_ratio は欠け。
  漏れ検査: v7d と同じ(t4_base.pick_days の 20 日 × 作る・答え合わせ。その日までに切り、その日の結果を空にして作り直し一致を見る。
     nk7_ は試験もその日までに切り、その日の試験の着順・タイムを空に)。
  judge: 土台 = 177 列(v7d の形 c)。形 n・s・f・m = 土台 + 各群。線 = vs.judge(伸び > 2 × 標準誤差 かつ 2016〜19 の 4 年中 3 年)・
     Y3 15/500/800(vs の既定)。通った群が 2 つ以上なら、それを全部足した形 all も judge(1 つなら同じ形なので作らない)。
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_base  # noqa: E402
import t4_day3 as d3  # noqa: E402
import v7_open as vo  # noqa: E402
import v7_select as vs  # noqa: E402
import v7c_run as vc  # noqa: E402
import v7d_run as v7d  # noqa: E402
import kd_read as kr  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
KEY = d3.KEY
Q5 = KEY + ['umaban']
RESJ = V3 / 'v7e_res.json'
MD = REPO / 'out' / 'v7e_feat.md'
CACHE_E = V3 / 'v7e_cache'
GROUPS = {
    'n': ['nk7_n', 'nk7_days', 'nk7_last_rel', 'nk7_last_fr', 'nk7_last_fin', 'nk7_best_rel'],
    's': ['s7_chosen', 's7_aband'],
    'f': ['f7_main', 'f7_share', 'f7_tr_day', 'f7_main_day'],
    'm': ['m7_len', 'm7_nh', 'm7_n', 'm7_ratio'],
}
GNAME = {'n': '能力試験 nk7_', 's': '騎手の選択 s7_', 'f': '厩舎の騎手配置 f7_', 'm': '冠名 m7_', 'all': '通った群を全部'}
DEF = {'nk7_n': '前の能力試験の回数', 'nk7_days': '最後の試験からの日数', 'nk7_last_rel': '最後の試験の 200m あたり秒 − 同じ日・同じ距離の平均',
       'nk7_last_fr': '最後の試験の 着順 ÷ 組の頭数', 'nk7_last_fin': '最後の試験の着順', 'nk7_best_rel': '試験の rel の最小',
       's7_chosen': '今回の騎手が同じレースの別の馬の直近 3 走に乗っていた', 's7_aband': '前走の騎手が同じレースの別の馬に乗る',
       'f7_main': '騎手が厩舎の主戦(前 365 日の組数最大)', 'f7_share': '主戦の組数 ÷ 厩舎の 365 日の全組数',
       'f7_tr_day': 'その日その場の厩舎の出走数', 'f7_main_day': 'そのうち主戦が乗る数',
       'm7_len': '冠名の長さ(無し 0)', 'm7_nh': '冠名の前の頭数', 'm7_n': '冠名の集団の前の走り数(自分を除く)',
       'm7_ratio': '冠名の集団の 3 着以内 ÷ 期待(縮め 3・自分を除く)'}
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def res_load():
    return json.loads(RESJ.read_text(encoding='utf-8')) if RESJ.exists() else {}


def res_save(k, v):
    R = res_load()
    R[k] = v
    RESJ.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding='utf-8')


def fpath(g, part):
    return V3 / f'feat_v7e_{g}_{part}.parquet'


def nrm(s):
    return s.map(vc.norm)


def qbase(h, Q):
    hq = h.drop_duplicates(Q5)[Q5 + ['hid', 'jk', 'tr', 'nm']]
    q = Q[Q5].reset_index(drop=True).merge(hq, on=Q5, how='left', validate='1:1')
    q['date'] = pd.to_datetime(q.race_date)
    return q


def slim(h):
    """メモリ対策: 要る列だけ残し、騎手・調教師・馬名の正規化は 1 回だけ(定義は同じ)。"""
    h = h[Q5 + ['hid', 'jockey', 'trainer', 'horse_name', 'finish', 'finish_note']].copy()
    for a, b in (('jockey', 'jk'), ('trainer', 'tr'), ('horse_name', 'nm')):
        u = pd.Series(h[a].unique())
        h[b] = h[a].map(dict(zip(u, u.map(vc.norm))))
        del h[a]
    return h


def runs_of(h):
    r = h[~h.finish_note.isin(d3.CANCEL)].copy()
    r['date'] = pd.to_datetime(r.race_date)
    return r


# ================================================================ 1. nk7_ 能力試験
def read_ns():
    ns = pd.concat([pd.DataFrame({
        'year': kr.num(a, 11, 4), 'md': kr.num(a, 15, 4), 'jyo': kr.num(a, 19, 2), 'heat': kr.num(a, 21, 2),
        'ketto': kr.num(a, 25, 10), 'finish': kr.num(a, 127, 2), 'time_raw': kr.num(a, 131, 4),
    }) for a in kr.chunks(kr.KD + 'NS/NS.DAT', 315, 'NS')], ignore_index=True)
    nr = pd.concat([pd.DataFrame({
        'year': kr.num(a, 11, 4), 'md': kr.num(a, 15, 4), 'jyo': kr.num(a, 19, 2), 'heat': kr.num(a, 21, 2),
        'dist': kr.num(a, 24, 4),
    }) for a in kr.chunks(kr.KD + 'NR/NR.DAT', 434, 'NR')], ignore_index=True)
    for d in (ns, nr):
        d['date'] = pd.to_datetime((d.year * 10000 + d.md).astype('Int64').astype(str), format='%Y%m%d', errors='coerce')
    ns['time_sec'] = kr.t4(ns.time_raw)
    ns = ns.merge(nr[['date', 'jyo', 'heat', 'dist']].drop_duplicates(['date', 'jyo', 'heat']),
                  on=['date', 'jyo', 'heat'], how='left')
    ns = ns[ns.date.notna() & (ns.ketto > 0)].reset_index(drop=True)
    ns['ketto'] = ns.ketto.astype('int64')
    return ns[['date', 'jyo', 'heat', 'ketto', 'finish', 'time_sec', 'dist']]


def ns_table(ns):
    ns = ns.copy()
    ok = (ns.time_sec > 0) & (ns.dist > 0)
    ns['per'] = np.where(ok, ns.time_sec / (ns.dist / 200), np.nan)
    ns['rel'] = ns.per - ns.groupby(['date', 'dist']).per.transform('mean')
    size = ns.groupby(['date', 'jyo', 'heat']).ketto.transform('size')
    fin = ns.finish.where(ns.finish > 0)
    ns['fr'], ns['fin'] = fin / size, fin
    ns = ns.sort_values(['ketto', 'date'], kind='mergesort').reset_index(drop=True)
    ns['c_n'] = ns.groupby('ketto').cumcount() + 1.0
    ns['c_best'] = ns.rel.fillna(np.inf).groupby(ns.ketto).cummin().replace(np.inf, np.nan)
    ns['l_date'] = ns.date
    ns = ns.drop_duplicates(['ketto', 'date'], keep='last')
    return ns[['ketto', 'date', 'c_n', 'c_best', 'rel', 'fr', 'fin', 'l_date']]


def build_n(h, Q, NT, kmap, nmap, ns_end):
    q = qbase(h, Q)
    lk = vc.link_key(q.hid)
    q['ketto'] = lk.map(kmap).fillna(lk.map(nmap))
    q['_i'] = np.arange(len(q))
    lin = q.ketto.notna().to_numpy()
    a = q[lin].copy()
    a['ketto'] = a.ketto.astype('int64')
    a = a.sort_values('date', kind='mergesort')
    m = pd.merge_asof(a[['_i', 'ketto', 'date']], NT.sort_values('date', kind='mergesort'), on='date', by='ketto',
                      allow_exact_matches=False, direction='backward').set_index('_i').reindex(np.arange(len(q)))
    out = pd.DataFrame(index=np.arange(len(q)))
    v = m.c_n.to_numpy(float)
    out['nk7_n'] = np.where(lin & np.isnan(v), 0.0, v)
    out['nk7_days'] = (q.date - m.l_date).dt.days.to_numpy(float)
    out['nk7_last_rel'], out['nk7_last_fr'] = m.rel.to_numpy(float), m.fr.to_numpy(float)
    out['nk7_last_fin'], out['nk7_best_rel'] = m.fin.to_numpy(float), m.c_best.to_numpy(float)
    late = (q.date > ns_end).to_numpy()
    out.loc[late, :] = np.nan
    aux = pd.DataFrame({'n_link': lin, 'n_has': out.nk7_n.to_numpy() > 0, 'n_in': ~late})
    return out[GROUPS['n']], aux


# ================================================================ 2. s7_ 騎手の選択
def build_s(h, Q):
    q = qbase(h, Q)
    r = runs_of(h).sort_values(['hid', 'date'], kind='mergesort')
    r = r.drop_duplicates(['hid', 'date'], keep='last').reset_index(drop=True)
    g = r.groupby('hid').jk
    P = pd.DataFrame({'hid': r.hid, 'date': r.date, 'p1': r.jk, 'p2': g.shift(1), 'p3': g.shift(2)})
    q['_i'] = np.arange(len(q))
    a = q[q.hid.notna()].sort_values('date', kind='mergesort')
    m = pd.merge_asof(a[['_i', 'hid', 'date']], P.sort_values('date', kind='mergesort'), on='date', by='hid',
                      allow_exact_matches=False, direction='backward').set_index('_i').reindex(np.arange(len(q)))
    q['p1'], q['p2'], q['p3'] = m.p1.to_numpy(), m.p2.to_numpy(), m.p3.to_numpy()
    L = q[Q5 + ['p1', 'p2', 'p3']].melt(id_vars=Q5, value_name='jk').dropna(subset=['jk'])
    L = L.rename(columns={'umaban': 'uo'})[KEY + ['uo', 'jk']]
    x = q[['_i'] + Q5 + ['jk']].dropna(subset=['jk']).merge(L, on=KEY + ['jk'])
    ch = set(x[x.uo != x.umaban]._i)
    cur = q[KEY + ['umaban', 'jk']].dropna(subset=['jk']).rename(columns={'umaban': 'uo', 'jk': 'p1'})
    y = q[['_i'] + Q5 + ['p1']].dropna(subset=['p1']).merge(cur, on=KEY + ['p1'])
    ab = set(y[y.uo != y.umaban]._i)
    idx = np.arange(len(q))
    out = pd.DataFrame(index=idx)
    out['s7_chosen'] = np.where(q.jk.isna(), np.nan, np.isin(idx, list(ch)).astype(float))
    out['s7_aband'] = np.where(q.p1.isna(), np.nan, np.isin(idx, list(ab)).astype(float))
    return out[GROUPS['s']], pd.DataFrame(index=idx)


# ================================================================ 3. f7_ 厩舎の騎手配置
def build_f(h, Q):
    q = qbase(h, Q)
    r = runs_of(h)
    r = r[r.tr.notna() & r.jk.notna()]
    q['dn'] = q.date.values.astype('datetime64[D]').astype(np.int64)
    qs = q[q.tr.notna()][['tr', 'dn']].drop_duplicates()
    lo, hi = qs.dn.min() - 365, qs.dn.max()
    r = r.assign(dn=r.date.values.astype('datetime64[D]').astype(np.int64))
    rw = r[(r.dn >= lo) & (r.dn < hi) & r.tr.isin(set(qs.tr))].sort_values(['tr', 'dn'], kind='mergesort')
    res = {}
    grp = {t: (g.dn.to_numpy(), g.jk.to_numpy()) for t, g in rw.groupby('tr', sort=False)}
    for t, gq in qs.sort_values(['tr', 'dn']).groupby('tr', sort=False):
        dn, jk = grp.get(t, (np.array([], dtype=np.int64), np.array([], dtype=object)))
        c, i0, i1 = Counter(), 0, 0
        for d in gq.dn.to_numpy():
            while i1 < len(dn) and dn[i1] < d:
                c[jk[i1]] += 1; i1 += 1
            while i0 < i1 and dn[i0] < d - 365:
                c[jk[i0]] -= 1
                if c[jk[i0]] == 0:
                    del c[jk[i0]]
                i0 += 1
            if c:
                mx = max(c.values())
                res[(t, d)] = (min(k for k, v in c.items() if v == mx), mx / (i1 - i0))
    q['main'] = [res.get((t, d), (np.nan, np.nan))[0] if isinstance(t, str) else np.nan for t, d in zip(q.tr, q.dn)]
    q['share'] = [res.get((t, d), (np.nan, np.nan))[1] if isinstance(t, str) else np.nan for t, d in zip(q.tr, q.dn)]
    day = r[['track', 'race_date', 'tr', 'jk']]
    day = day[day.race_date.isin(set(q.race_date))]
    ntr = day.groupby(['track', 'race_date', 'tr']).size().rename('ntr').reset_index()
    q = q.merge(ntr, on=['track', 'race_date', 'tr'], how='left')
    dm = q[q.main.notna()][['track', 'race_date', 'tr', 'main']].drop_duplicates()
    dm = dm.merge(day.rename(columns={'jk': 'main'}), on=['track', 'race_date', 'tr', 'main'])
    dm = dm.groupby(['track', 'race_date', 'tr', 'main']).size().rename('nmain').reset_index()
    q = q.merge(dm, on=['track', 'race_date', 'tr', 'main'], how='left')
    has = q.main.notna()
    out = pd.DataFrame(index=np.arange(len(q)))
    out['f7_main'] = np.where(has, (q.jk == q.main).astype(float), np.nan)
    out['f7_share'] = q.share.astype(float).to_numpy()
    out['f7_tr_day'] = np.where(q.tr.notna(), q.ntr.fillna(0).astype(float), np.nan)
    out['f7_main_day'] = np.where(has, q.nmain.fillna(0).astype(float), np.nan)
    return out[GROUPS['f']], pd.DataFrame(index=out.index)


# ================================================================ 4. m7_ 冠名
def build_m(h, Q):
    q = qbase(h, Q)
    q['_i'] = np.arange(len(q))
    r = runs_of(h)
    r = r[r.nm.notna() & r.hid.notna()].copy()
    fin = r.finish.where(r.finish > 0)
    n = fin.notna().groupby([r[k] for k in KEY]).transform('sum')
    ok = fin.notna() & (n > 0)
    r['T'] = np.where(ok, (fin <= 3).astype(float), 0.0)
    r['E'] = np.where(ok, np.minimum(3, n) / n.where(n > 0, 1), 0.0)
    r['N'] = ok.astype(float)
    first = r.sort_values('date', kind='mergesort').drop_duplicates('hid')[['hid', 'nm', 'date']]
    # 自分の前の走り
    s = r.groupby(['hid', 'date'])[['T', 'E', 'N']].sum().groupby(level=0).cumsum().reset_index()
    a = q[q.hid.notna()].sort_values('date', kind='mergesort')
    ms = pd.merge_asof(a[['_i', 'hid', 'date']], s.sort_values('date', kind='mergesort'), on='date', by='hid',
                       allow_exact_matches=False).set_index('_i').reindex(q._i)
    sT, sE, sN = (ms[c].fillna(0).to_numpy() for c in ('T', 'E', 'N'))
    has_prev = ms['T'].notna().to_numpy()  # 自分が前に走っていれば頭数に自分が入っている
    best = {k: np.full(len(q), np.nan) for k in ('len', 'nh', 'T', 'E', 'N')}
    best['len'] = np.zeros(len(q))
    for k in (2, 3, 4):
        fk = first[first.nm.str.len() > k].assign(p=lambda x: x.nm.str[:k])
        c = fk.groupby(['p', 'date']).size().groupby(level=0).cumsum().rename('nh').reset_index()
        rk = r[r.nm.str.len() > k].assign(p=lambda x: x.nm.str[:k])
        g = rk.groupby(['p', 'date'])[['T', 'E', 'N']].sum().groupby(level=0).cumsum().reset_index()
        qk = q[q.nm.notna() & (q.nm.str.len() > k)].assign(p=lambda x: x.nm.str[:k]).sort_values('date', kind='mergesort')
        m1 = pd.merge_asof(qk[['_i', 'p', 'date']], c.sort_values('date', kind='mergesort'), on='date', by='p',
                           allow_exact_matches=False)
        m1 = pd.merge_asof(m1.sort_values('date', kind='mergesort'), g.sort_values('date', kind='mergesort'), on='date',
                           by='p', allow_exact_matches=False).set_index('_i').reindex(q._i)
        nh = m1.nh.to_numpy(float) - has_prev  # 別の馬の頭数
        use = nh >= 50
        best['len'][use] = k
        best['nh'][use] = nh[use]
        for cc, sv in (('T', sT), ('E', sE), ('N', sN)):
            best[cc][use] = m1[cc].fillna(0).to_numpy()[use] - sv[use]
    out = pd.DataFrame(index=np.arange(len(q)))
    out['m7_len'] = np.where(q.nm.isna(), np.nan, best['len'])
    out['m7_nh'] = best['nh']
    out['m7_n'] = best['N']
    out['m7_ratio'] = (best['T'] + 3) / (best['E'] + 3)
    return out[GROUPS['m']], pd.DataFrame(index=out.index)


# ================================================================ feat
def leak(g, build, h, Q, full, races, part, ns=None, extra=()):
    days = t4_base.pick_days(races)
    cols = GROUPS[g]
    per, tot = [], [0, 0]
    for X in days:
        ht = h[h.race_date <= X].copy()
        mk = (ht.race_date == X).to_numpy()
        ht.loc[mk, 'finish'] = np.nan
        ht.loc[mk & ~ht.finish_note.isin(d3.CANCEL).to_numpy(), 'finish_note'] = np.nan
        Qd = Q[Q.race_date == X].reset_index(drop=True)
        if g == 'n':
            nt = ns[ns.date <= pd.Timestamp(X)].copy()
            nt.loc[nt.date == pd.Timestamp(X), ['finish', 'time_sec']] = np.nan
            b, _ = build(ht, Qd, ns_table(nt), *extra)
        else:
            b, _ = build(ht, Qd)
        b = pd.concat([Qd[Q5], b.reset_index(drop=True)], axis=1)
        a = full[full.race_date == X].set_index(Q5)[cols].sort_index()
        b = b.set_index(Q5)[cols].sort_index()
        assert a.index.equals(b.index), X
        A, B = a.to_numpy(float), b.to_numpy(float)
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        bad = [c for c, ok in zip(cols, eq.all(0)) if not ok]
        per.append({'date': X, 'rows': len(a), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        log('漏れ', g, part, X, len(a), int(eq.sum()), eq.size, bad)
    return {'days': len(days), 'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0],
            'cells': tot[1], 'per_day': per}


def feat():
    R = res_load()
    todo = [g for g in GROUPS if not ('leak_' + g in R and fpath(g, 'explore').exists() and fpath(g, 'open').exists())]
    if not todo:
        log('feat は済み'); return
    h, races = vc.sources()
    h = slim(h)
    races = races[['track', 'race_date']].drop_duplicates()
    log('走り', len(h), h.memory_usage(deep=True).sum() // 2**20, 'MB')
    XE = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XO = vo.nk(pd.read_parquet(V3 / 'feat_t6_open.parquet'))
    Q = pd.concat([XE[Q5], XO[Q5]], ignore_index=True)
    meta = pd.concat([XE[['year']], XO[['year']]], ignore_index=True)
    nk = races[races.track.isin(d3.NANKAN)]
    ne, no = nk[nk.race_date < '2022-01-01'], nk[nk.race_date >= '2022-01-01']
    n = len(XE)
    for g in todo:
        info = {}
        if g == 'n':
            _, kmap, _ = v7d.ledger()
            nmap = v7d.jra_names(pd.read_parquet(V3 / 'kd_jra_runs.parquet'))
            ns = read_ns()
            ns_end = ns.date.max()
            log('能力試験', len(ns), ns.date.min().date(), ns_end.date())
            extra = (kmap, nmap, ns_end)
            F, aux = build_n(h, Q, ns_table(ns), *extra)
            aux = pd.concat([aux, meta], axis=1)
            rt = aux.groupby('year').agg(rows=('n_link', 'size'), link=('n_link', 'mean'), has=('n_has', 'mean'),
                                         inr=('n_in', 'mean'))
            info = {'ns_rows': len(ns), 'ns_first': str(ns.date.min().date()), 'ns_last': str(ns_end.date()),
                    'rate': {int(y): {k: float(v) for k, v in r.items()} for y, r in rt.iterrows()}}
            log('つながり\n', rt.round(4))
            bf = build_n
        else:
            extra, ns = (), None
            bf = {'s': build_s, 'f': build_f, 'm': build_m}[g]
            F, _ = bf(h, Q)
        F = pd.concat([Q[Q5], F.reset_index(drop=True)], axis=1)
        FE, FO = F.iloc[:n].reset_index(drop=True), F.iloc[n:].reset_index(drop=True)
        info['miss'] = {c: [float(FE[c].isna().mean()), float(FO[c].isna().mean())] for c in GROUPS[g]}
        info['mean'] = {c: [float(FE[c].mean()), float(FO[c].mean())] for c in GROUPS[g]}
        log(g, info['miss'], info['mean'])
        z = {'explore': leak(g, bf, h, XE[Q5], FE, ne, 'explore', ns, extra),
             'open': leak(g, bf, h, XO[Q5], FO, no, 'open', ns, extra)}
        info['leak'] = {k: {kk: v[kk] for kk in ('days', 'match_days', 'match', 'cells')} for k, v in z.items()}
        res_save('feat_' + g, info)
        if any(v['match'] != v['cells'] for v in z.values()):
            res_save('leakfail_' + g, z)
            write_md()
            raise SystemExit(f'⛔ 漏れ検査が 100% でない: {g}')
        FE.to_parquet(fpath(g, 'explore'), index=False); FO.to_parquet(fpath(g, 'open'), index=False)
        res_save('leak_' + g, info['leak'])
        log('保存', g)


# ================================================================ judge
def judge():
    R = res_load()
    if 'judge' in R:
        log('judge は済み', R['judge']); return
    d = v7d.load_d()
    for g in GROUPS:
        d = d.merge(vo.nk(pd.read_parquet(fpath(g, 'explore'))), on=Q5, how='left', validate='1:1')
    base = vc.base_cols() + v7d.C7 + v7d.J7
    assert len(base) == 177 and len(set(base)) == 177
    vs.CACHE = v7d.CACHE_D  # 土台 177 列は v7d の形 c と同じ列・同じ値
    ll0 = vs.race_ll(d, vs.fit(d, base))
    vs.CACHE = CACHE_E
    out = R.get('judge_part', {})
    for k, add in GROUPS.items():
        if k in out:
            continue
        ll1 = vs.race_ll(d, vs.fit(d, base + add))
        j = vs.judge(ll0, ll1)
        j['sum_base'], j['sum_new'] = round(float(ll0.sum()), 1), round(float(ll1.sum()), 1)
        out[k] = j
        res_save('judge_part', out)
        log('judge', k, j)
    ok = [k for k in GROUPS if out[k]['ok']]
    if len(ok) >= 2 and 'all' not in out:
        ll1 = vs.race_ll(d, vs.fit(d, base + sum((GROUPS[k] for k in ok), [])))
        j = vs.judge(ll0, ll1)
        j['sum_base'], j['sum_new'] = round(float(ll0.sum()), 1), round(float(ll1.sum()), 1)
        j['groups'] = ok
        out['all'] = j
        log('judge all', j)
    out['passed'] = ok
    res_save('judge', out)


# ================================================================ md
def pct(v):
    return f'{100 * v:.1f}%'


def write_md():
    R = res_load()
    L = ['# 第 7 版 e: 第 7 版 d(177 列)に足す候補 4 群(作る期間の judge)', '',
         '- 台本 src/v7e_run.py(定義は docstring の「決め」。結果を見て変えていない)。答え合わせの期間(open)は使っていない。',
         '- 南関のオッズ・人気は材料に使わない。「前」= レースの日より前(当日を含まない)。', '']
    fn = R.get('feat_n')
    if fn:
        L += ['## 能力試験 nk7_ のつながり(南関の出走・年ごと)', '',
              f'- NS {fn["ns_rows"]} 件({fn["ns_first"]}〜{fn["ns_last"]})。**試験は {fn["ns_last"]} までしか無いので、'
              'それより後(2021 年以降)のレースの nk7_ は全部欠け。** 合否・上がりは位置が分からないので入れていない。', '',
              '| 年 | 行 | 血統登録番号とつながった | 前に試験あり | 試験の期間内 |', '|---|---|---|---|---|']
        for y, v in fn['rate'].items():
            L.append(f'| {y} | {int(v["rows"])} | {pct(v["link"])} | {pct(v["has"])} | {pct(v["inr"])} |')
        L.append('')
    L += ['## 列の定義・欠け率・平均', '', '| 列 | 定義 | 欠け 作る | 欠け 答え合わせ | 平均 作る |', '|---|---|---|---|---|']
    for g, cols in GROUPS.items():
        f = R.get('feat_' + g)
        for c in cols:
            if f:
                L.append(f'| {c} | {DEF[c]} | {pct(f["miss"][c][0])} | {pct(f["miss"][c][1])} | {f["mean"][c][0]:.4f} |')
            else:
                L.append(f'| {c} | {DEF[c]} | — | — | — |')
    L += ['', '## 漏れ検査(t4_base.pick_days の 20 日・その日までに切り、その日の結果を空にして作り直し)', '']
    for g in GROUPS:
        f = R.get('feat_' + g)
        if f and 'leak' in f:
            L.append(f'- {g}: ' + '・'.join(f'{k} {v["match_days"]} / {v["days"]} 日一致・セル {v["match"]} / {v["cells"]}'
                                            for k, v in f['leak'].items()))
    if 'judge' in R:
        J = R['judge']
        L += ['', '## judge(土台 177 列に足す・2016〜19・Y3 15/500/800・線 = 伸び > 2 × 標準誤差 かつ 4 年中 3 年)', '',
              '| 形 | 伸び | 標準誤差 | 年ごと 2016〜19 | 通った | 和 土台 → 足した |', '|---|---|---|---|---|---|']
        for k in list(GROUPS) + ['all']:
            if k in J:
                j = J[k]
                L.append(f'| {GNAME[k]}{"(" + "+".join(j["groups"]) + ")" if k == "all" else ""} | {j["gain"]} | {j["se"]} | '
                         f'{j["years"]} | {j["ok"]} | {j["sum_base"]} → {j["sum_new"]} |')
        L += ['', f'- 通った群: {J["passed"] or "なし"}' + ('(1 つだけなので「全部足した形」はその形と同じ・作らない)'
                                                    if len(J['passed']) == 1 else '')]
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')
    log('md', MD)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    steps = {'feat': [feat], 'judge': [judge], 'md': [write_md], 'all': [feat, judge, write_md]}[cmd]
    for s in steps:
        s()
