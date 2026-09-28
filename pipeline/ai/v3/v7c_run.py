# -*- coding: utf-8 -*-
"""第 7 版 c7: 走歴の少ない馬のための血統・生産者・馬主の材料(PC-KEIBA の馬の台帳)→ 漏れ検査 → judge → 当てはめ外 → 答え合わせの期間の予想。
既存の台本は import して呼ぶだけ(書き換えない)。

  py -3.12 -X utf8 src/v7c_run.py all    # feat → judge → final → open(できている段は飛ばす)

■ 決め(この台本で決めた細部)
  1. 台帳の列は 父・母・母父・馬主・生産者・産地名・生年月日 だけ(今の時点の値の列は使わない)。馬主は今の値。
     名前は NFKC + 空白を消す。つなぐ鍵 = 馬名|生年(手元の hid = horse_key「名前|生年」)。台帳で同じ鍵が 2 頭以上なら外す。
     母の鍵 = 母|母父(同名の別の牝馬を分けるため)。
  2. 走り = 全 NAR の走り(取消・除外を除く・中止は 3 着外)。デビュー = その馬の手元で最初の走り。転入初戦 = 南関の走りで前の走りが
     南関以外。2 歳戦 = その走りの馬の年齢が 2。
  3. どの率も「その日より前」(t4_day3.wsum の [当日 − 100000, 当日 − 1])。自分の走りは群から除く。
     縮め = (3着内 + 3 × 全体率)/(出走 + 3)。全体率もその日より前の全 NAR(2 歳戦だけ・デビューだけ・初戦だけは同じ区分の全体率)。
  4. 兄弟の数 = 同じ母の、その日より前にデビューした自分以外の馬の数。
  5. c7_monage = 2 歳なら生まれ月・3 歳なら 20 + 生まれ月・4 歳以上 40。c7_area = 日高 1・胆振 2・その他 3(産地名が無ければ欠け)。
"""
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_base  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t6_base  # noqa: E402
import v7_open as vo  # noqa: E402
import v7_select as vs  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
KEY = d3.KEY
LED = V3 / 'pckeiba_uma_chiho.csv'
FEX, FOP = V3 / 'feat_c7_explore.parquet', V3 / 'feat_c7_open.parquet'
LEAKJ = V3 / 'v7c_leak.json'
RESJ = V3 / 'v7c_res.json'
MD = REPO / 'out' / 'v7_feat_c.md'
BIG = 100000
CS = ['one', 't3', 'w', 'y2', 't3y2', 'deb', 't3deb', 'fst', 't3fst']
HIDAKA = ['新ひだか町', '浦河町', '日高町', '門別町', '新冠町', '様似町', 'えりも町', '平取町', '静内町', '三石町']
IBURI = ['苫小牧市', '安平町', '早来町', '追分町', '白老町', 'むかわ町', '鵡川町', '穂別町', '厚真町', '伊達市', '洞爺湖町',
         '虻田町', '豊浦町', '登別市', '室蘭市', '壮瞥町', '大滝村']
C7 = (['c7_s_n', 'c7_s_t3', 'c7_s_w', 'c7_s_t3y2', 'c7_s_t3deb',
       'c7_m_n', 'c7_m_t3', 'c7_m_w', 'c7_m_t3y2', 'c7_m_t3deb',
       'c7_d_sib', 'c7_d_n', 'c7_d_t3',
       'c7_b_n', 'c7_b_t3', 'c7_b_w', 'c7_b_t3fst',
       'c7_o_n', 'c7_o_t3', 'c7_o_w', 'c7_o_t3fst',
       'c7_bmon', 'c7_monage', 'c7_area',
       'c7_s_t3_rk', 'c7_d_t3_rk', 'c7_b_t3_rk', 'c7_o_t3_rk'])
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def norm(s):
    if not isinstance(s, str):
        return np.nan
    s = re.sub(r'\s+', '', unicodedata.normalize('NFKC', s))
    return s if s else np.nan


# ================================================================ 台帳
def ledger():
    c = pd.read_csv(LED, encoding='cp932', dtype=str)
    c.columns = [re.sub(r'^="(.*)"$', r'\1', k) for k in c.columns]
    for k in c.columns:
        c[k] = c[k].str.replace(r'^="(.*)"$', r'\1', regex=True)
    assert len(c) == 92831, len(c)
    c = c[['馬名', '父', '母', '母父', '馬主', '生産者', '産地名', '生年月日']].copy()
    for k in ['馬名', '父', '母', '母父', '馬主', '生産者', '産地名']:
        c[k] = c[k].map(norm)
    c['lk'] = c['馬名'] + '|' + c['生年月日'].str[:4]
    c['bmon'] = pd.to_numeric(c['生年月日'].str[5:7], errors='coerce')
    c['dam'] = c['母'] + '|' + c['母父'].fillna('')
    c.loc[c['母'].isna(), 'dam'] = np.nan
    c['area'] = np.where(c['産地名'].isin(HIDAKA), 1.0, np.where(c['産地名'].isin(IBURI), 2.0, 3.0))
    c.loc[c['産地名'].isna(), 'area'] = np.nan
    c = c[c.lk.notna()]
    dup = c.lk.duplicated(keep=False)
    L = c[~dup].rename(columns={'父': 'sire', '母父': 'bms', '馬主': 'owner', '生産者': 'breeder'})
    return L[['lk', 'sire', 'bms', 'dam', 'owner', 'breeder', 'bmon', 'area']].set_index('lk'), int(dup.sum())


def link_key(hid):
    u = pd.Series(hid.unique())
    m = u.astype(str).str.extract(r'^(.*)\|(\d{4})$')
    k = m[0].map(norm) + '|' + m[1]
    return hid.map(dict(zip(u, k)))


# ================================================================ 材料
def run_table(h, L):
    r = h[~h.finish_note.isin(d3.CANCEL)][KEY + ['umaban', 'hid', 'age', 'finish']].drop_duplicates(KEY + ['umaban'])
    r = r.copy()
    r['dnum'] = d3.dnum_of(r.race_date)
    r = r.sort_values(['hid', 'dnum'], kind='mergesort').reset_index(drop=True)
    same = r.hid.eq(r.hid.shift()).to_numpy()
    r['one'] = 1.0
    r['t3'] = (r.finish <= 3).astype(float)
    r['w'] = (r.finish == 1).astype(float)
    r['y2'] = (r.age == 2).astype(float)
    r['deb'] = (~same).astype(float)
    tr = same & r.track.isin(d3.NANKAN).to_numpy() & ~r.track.shift().isin(d3.NANKAN).to_numpy()
    r['fst'] = ((r.deb == 1) | tr).astype(float)
    r['t3y2'], r['t3deb'], r['t3fst'] = r.t3 * r.y2, r.t3 * r.deb, r.t3 * r.fst
    r['_all'] = 'a'
    r['lk'] = link_key(r.hid)
    return r.merge(L, left_on='lk', right_index=True, how='left')


def build(h, Q, L):
    """h = 全 NAR の走り(sources_from)、Q = 作る行(KEY + umaban)。c7_ 列を Q の順で返す。"""
    r = run_table(h, L)
    hq = h.drop_duplicates(KEY + ['umaban'])[KEY + ['umaban', 'hid', 'age']]
    q = Q[KEY + ['umaban']].merge(hq, on=KEY + ['umaban'], how='left', validate='1:1')
    q['dnum'] = d3.dnum_of(q.race_date)
    q['lk'] = link_key(q.hid)
    q = q.merge(L, left_on='lk', right_index=True, how='left')
    q['_all'] = 'a'
    ix = {c: i for i, c in enumerate(CS)}
    G = d3.wsum(r, ['_all'], CS, q, BIG)
    S = d3.wsum(r, ['hid'], CS, q, BIG)
    S = np.nan_to_num(S)
    with np.errstate(all='ignore'):
        pr = {k: G[:, ix[k]] / G[:, ix[b]] for k, b in (('t3', 'one'), ('w', 'one'), ('t3y2', 'y2'),
                                                       ('t3deb', 'deb'), ('t3fst', 'fst'))}
    out = pd.DataFrame(index=q.index)

    def shr(A, k, b):
        return (A[:, ix[k]] + 3 * pr[k]) / (A[:, ix[b]] + 3)

    for tag, by in (('s', 'sire'), ('m', 'bms'), ('d', 'dam'), ('b', 'breeder'), ('o', 'owner')):
        A = d3.wsum(r, [by], CS, q, BIG)
        A = A - np.where(np.isnan(A), 0, S)
        if tag in ('s', 'm'):
            out[f'c7_{tag}_n'], out[f'c7_{tag}_t3'], out[f'c7_{tag}_w'] = A[:, ix['one']], shr(A, 't3', 'one'), shr(A, 'w', 'one')
            out[f'c7_{tag}_t3y2'], out[f'c7_{tag}_t3deb'] = shr(A, 't3y2', 'y2'), shr(A, 't3deb', 'deb')
        elif tag == 'd':
            out['c7_d_sib'], out['c7_d_n'], out['c7_d_t3'] = A[:, ix['deb']], A[:, ix['one']], shr(A, 't3', 'one')
        else:
            out[f'c7_{tag}_n'], out[f'c7_{tag}_t3'], out[f'c7_{tag}_w'] = A[:, ix['one']], shr(A, 't3', 'one'), shr(A, 'w', 'one')
            out[f'c7_{tag}_t3fst'] = shr(A, 't3fst', 'fst')
    out['c7_bmon'] = q.bmon.to_numpy(float)
    age = q.age.to_numpy(float)
    out['c7_monage'] = np.where(age == 2, q.bmon, np.where(age == 3, 20 + q.bmon, np.where(np.isnan(age), np.nan, 40.0)))
    out.loc[q.bmon.isna().to_numpy(), 'c7_monage'] = np.nan
    out['c7_area'] = q.area.to_numpy(float)
    T = pd.concat([q[KEY].reset_index(drop=True), out.reset_index(drop=True)], axis=1)
    for c in ('c7_s_t3', 'c7_d_t3', 'c7_b_t3', 'c7_o_t3'):
        out[c + '_rk'] = d3.in_race_rank(T, c)
    out = out[C7]
    res = pd.concat([Q[KEY + ['umaban']].reset_index(drop=True), out.reset_index(drop=True)], axis=1)
    aux = pd.DataFrame({'linked': q.sire.notna().to_numpy() | q.dam.notna().to_numpy() | q.owner.notna().to_numpy(),
                        'inled': q.lk.isin(L.index).to_numpy(), 'selfn': S[:, ix['one']]})
    return res, aux


def sources():
    runs, facts, races = vo.raw_all()
    h = d3.sources_from(runs, facts, races)
    return h, races


def leak_check(h, Q, full, L, races, part):
    days = t4_base.pick_days(races)
    per, tot = [], [0, 0]
    for X in days:
        ht = h[h.race_date <= X].copy()
        mk = (ht.race_date == X).to_numpy()
        ht.loc[mk, 'finish'] = np.nan
        ht.loc[mk & ~ht.finish_note.isin(d3.CANCEL).to_numpy(), 'finish_note'] = np.nan
        Qd = Q[Q.race_date == X].reset_index(drop=True)
        b, _ = build(ht, Qd, L)
        a = full[full.race_date == X].set_index(KEY + ['umaban'])[C7].sort_index()
        b = b.set_index(KEY + ['umaban'])[C7].sort_index()
        assert a.index.equals(b.index), X
        A, B = a.to_numpy(float), b.to_numpy(float)
        eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
        bad = [c for c, ok in zip(C7, eq.all(0)) if not ok]
        per.append({'date': X, 'rows': len(a), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        log(part, X, len(a), int(eq.sum()), eq.size, bad)
    return {'days': len(days), 'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0],
            'cells': tot[1], 'per_day': per}


def feat():
    if FEX.exists() and FOP.exists() and LEAKJ.exists():
        log('feat は済み'); return
    L, ndup = ledger()
    log('台帳', len(L), '重複で外した', ndup)
    h, races = sources()
    log('走り', len(h))
    XE = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XO = vo.nk(pd.read_parquet(V3 / 'feat_t6_open.parquet'))
    Q = pd.concat([XE[KEY + ['umaban']], XO[KEY + ['umaban']]], ignore_index=True)
    F, aux = build(h, Q, L)
    meta = pd.concat([XE[['year', 'Y3']], XO[['year', 'Y3']]], ignore_index=True)
    aux = pd.concat([aux, meta], axis=1)
    rate = aux.groupby('year').agg(rows=('inled', 'size'), inled=('inled', 'mean'), linked=('linked', 'mean'))
    log('つながった割合\n', rate.round(4))
    FE, FO = F.iloc[:len(XE)].reset_index(drop=True), F.iloc[len(XE):].reset_index(drop=True)
    assert FE[KEY + ['umaban']].equals(XE[KEY + ['umaban']]) and FO[KEY + ['umaban']].equals(XO[KEY + ['umaban']])
    info = {'ledger': len(L), 'dup_removed': ndup, 'rate': {int(y): {k: float(v) for k, v in r.items()}
                                                             for y, r in rate.iterrows()}}
    # 2016〜19 の順位相関
    ae = aux.iloc[:len(XE)].reset_index(drop=True)
    m = ae.year.between(2016, 2019).to_numpy()
    deb = m & (ae.selfn.to_numpy() == 0)
    info['corr'] = {c: [float(FE.loc[m, c].corr(ae.Y3[m], method='spearman')),
                        float(FE.loc[deb, c].corr(ae.Y3[deb], method='spearman'))] for c in C7}
    info['n_debut_rows'] = int(deb.sum())
    info['miss'] = {c: [float(FE[c].isna().mean()), float(FO[c].isna().mean())] for c in C7}
    low = [y for y in range(2015, 2022) if info['rate'][y]['inled'] < 0.9]
    RESJ.write_text(json.dumps({'feat': info}, ensure_ascii=False, indent=1), encoding='utf-8')
    if low:
        write_md()
        raise SystemExit(f'要判断: つながった割合が 9 割未満の年 {low}')
    FE.to_parquet(FEX, index=False)
    FO.to_parquet(FOP, index=False)
    log('保存', FEX, FE.shape, FOP, FO.shape)
    # 漏れ検査
    nk = races[races.track.isin(d3.NANKAN)]
    z = {'explore': leak_check(h, XE[KEY + ['umaban']], FE, L, nk[nk.race_date < '2022-01-01'], 'explore'),
         'open': leak_check(h, XO[KEY + ['umaban']], FO, L, nk[nk.race_date >= '2022-01-01'], 'open')}
    LEAKJ.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding='utf-8')
    write_md()
    for k, v in z.items():
        log('漏れ検査', k, v['match_days'], '/', v['days'], v['match'], '/', v['cells'])
    if any(v['match'] != v['cells'] for v in z.values()):
        FEX.unlink(); FOP.unlink(); LEAKJ.unlink()
        raise SystemExit('⛔ 漏れ検査が 100% でない')


# ================================================================ judge・final・open
def base_cols():
    return json.loads((V3 / 'v7_select.json').read_text(encoding='utf-8'))['cols']


def load_d():
    d = vs.load()
    c = vo.nk(pd.read_parquet(FEX))
    d['race_no'] = d.race_no.astype(int)
    d = d.merge(c, on=KEY + ['umaban'], how='left', validate='1:1')
    return d


def res_save(k, v):
    R = json.loads(RESJ.read_text(encoding='utf-8'))
    R[k] = v
    RESJ.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding='utf-8')


def judge():
    R = json.loads(RESJ.read_text(encoding='utf-8'))
    if 'judge' in R:
        log('judge は済み', R['judge']); return
    d = load_d()
    base = base_cols()
    assert len(base) == 138
    ll0 = vs.race_ll(d, vs.fit(d, base))
    ll1 = vs.race_ll(d, vs.fit(d, base + C7))
    j = vs.judge(ll0, ll1)
    j['sum_base'], j['sum_c7'] = round(float(ll0.sum()), 1), round(float(ll1.sum()), 1)
    res_save('judge', j)
    log('judge', j)


def final():
    out_p = V3 / 'v7c_final_preds.parquet'
    if out_p.exists():
        log('final は済み'); return
    d = load_d()
    cols = base_cols() + C7
    ys = vs.SEL_Y + vs.CHK_Y
    te = d[d.year.isin(ys)].copy()
    out = te[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop']].copy()
    r1 = vs.fit(d, cols, 'Y1', ys, (31, 500, 400))
    r3 = vs.fit(d, cols, 'Y3', ys, (15, 100, 1200))
    p1 = r1 / pd.Series(r1, index=te.index).groupby([te[k] for k in KEY]).transform('sum').to_numpy()
    out['v7cpre_p1'], out['v7cpre_p3'] = p1, np.maximum(r3, p1)
    out['v7cpre_p3p'] = t6_base.p3prime(out, 'v7cpre_p3')[0]
    P7 = vo.nk(pd.read_parquet(V3 / 'v7_final_preds.parquet'))[KEY + ['umaban', 'v7pre_p1', 'v7pre_p3', 'v7pre_p3p']]
    out = vo.nk(out).merge(P7, on=KEY + ['umaban'], how='left', validate='1:1')
    assert out.v7pre_p3p.notna().all() and out.v7cpre_p3p.notna().all()
    out.to_parquet(out_p, index=False)
    log('保存', out_p, out.shape)


def train(tr, target, cols):
    cfg = vo.CFG[target]
    z = d3.logit((1 if target == 'Y1' else 3) / tr.n.to_numpy(float))
    prm = dict(d3.BASE, num_leaves=cfg[0], min_data_in_leaf=cfg[1])
    return lgb.train(prm, lgb.Dataset(tr[cols].astype(float), label=tr[target].to_numpy(float), init_score=z),
                     num_boost_round=cfg[2])


def open_():
    out_p = V3 / 'v7c_open_preds.parquet'
    if out_p.exists():
        log('open は済み'); return
    cols = base_cols() + C7
    T = vo.nk(pd.read_parquet(vo.FEAT_OUT))
    assert len(T) == 172738
    T = T.merge(vo.nk(pd.read_parquet(FOP)), on=KEY + ['umaban'], how='left', validate='1:1')
    X6 = vo.nk(pd.read_parquet(V3 / 'feat_t6_explore.parquet'))
    XB = vo.nk(pd.read_parquet(V3 / 'feat_v7b_explore.parquet'))
    X = X6.merge(XB[KEY + ['umaban'] + vo.B7], on=KEY + ['umaban'], how='left', validate='1:1')
    X = X.merge(vo.nk(pd.read_parquet(FEX)), on=KEY + ['umaban'], how='left', validate='1:1')
    assert len(X) == len(X6) and X.race_date.max() < '2022-01-01' and set(T.columns) <= set(X.columns)
    ALL = o.sort4(pd.concat([X[list(T.columns)], T], ignore_index=True))
    assert not ALL.duplicated(KEY + ['umaban']).any()
    P = []
    for name, lo, hi in o.SEGS:
        tr = ALL[ALL.race_date < lo]
        te = o.seg_rows(T, lo, hi)
        r = {}
        for t in ('Y1', 'Y3'):
            m = train(tr, t, cols)
            z = d3.logit((1 if t == 'Y1' else 3) / te.n.to_numpy(float))
            r[t] = d3.sig(z + m.predict(te[cols].astype(float), raw_score=True))
        x = te[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop']].copy()
        x['seg'] = name
        p1 = r['Y1'] / pd.Series(r['Y1'], index=x.index).groupby([x[k] for k in KEY]).transform('sum').to_numpy()
        x['v7cpre_p1'], x['v7cpre_p3'] = p1, np.maximum(r['Y3'], p1)
        x['v7cpre_p3p'] = t6_base.p3prime(x, 'v7cpre_p3')[0]
        P.append(x)
        log('区切り', name, '学び', len(tr), '予想', len(x))
    out = pd.concat(P, ignore_index=True).sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    P7 = vo.nk(pd.read_parquet(vo.PRED_OUT))[KEY + ['umaban', 'v7pre_p1', 'v7pre_p3', 'v7pre_p3p']]
    out = out.merge(P7, on=KEY + ['umaban'], how='left', validate='1:1')
    assert len(out) == 172738 and out.v7pre_p3p.notna().all() and out.v7cpre_p3p.notna().all()
    out.to_parquet(out_p, index=False)
    log('保存', out_p, out.shape)


# ================================================================ md
DEF = {'s': '父の産駒', 'm': '母父の産駒', 'd': '母の子(兄弟・母|母父)', 'b': '生産者の生産馬', 'o': '馬主(今の値)の所有馬'}
SUF = {'n': '出走数(自分を除く・その日より前・全 NAR)', 't3': '3 着以内率(縮め)', 'w': '勝率(縮め)',
       't3y2': '2 歳戦だけの 3 着以内率(縮め)', 't3deb': 'デビュー戦だけの 3 着以内率(縮め)', 'sib': '兄弟の数(その日より前にデビュー)',
       't3fst': '新馬戦(デビュー)・転入初戦だけの 3 着以内率(縮め)', 't3_rk': '3 着以内率のレース内の順位割合'}


def write_md():
    R = json.loads(RESJ.read_text(encoding='utf-8'))
    f = R['feat']
    L = ['# 第 7 版 c7: 血統・生産者・馬主の材料(PC-KEIBA の馬の台帳)', '',
         f'- 台帳 {f["ledger"]} 頭(同じ鍵「馬名|生年」が 2 頭以上で外した {f["dup_removed"]} 行)。馬主は **今の値を使った**'
         '(持ち主の替わりは記録に無い)。獲得賞金・着度数・全芝・全ダ・所属・調教師・性齢は使わない。',
         '- 率はすべてその日より前の全 NAR の走り(取消・除外を除く)から。自分の走りは群から除く。縮め = (3着内 + 3 × その日より前の全体率)/(出走 + 3)。',
         f'- 列 {len(C7)}', '', '## つながった割合(南関の出走・年ごと)', '', '| 年 | 行 | 台帳に鍵あり | 父・母・馬主のどれかあり |', '|---|---|---|---|']
    for y, v in f['rate'].items():
        L.append(f'| {y} | {int(v["rows"])} | {100 * v["inled"]:.2f}% | {100 * v["linked"]:.2f}% |')
    L += ['', '## 列の定義・欠け率・順位相関(Y3・2016〜19)', '',
          f'デビュー = 手元で前の走りが無い行({f["n_debut_rows"]} 行)。', '',
          '| 列 | 定義 | 欠け 作る | 欠け 答え合わせ | 相関 全体 | 相関 デビュー |', '|---|---|---|---|---|---|']
    for c in C7:
        p = c.split('_')
        if c == 'c7_bmon':
            de = '生まれ月'
        elif c == 'c7_monage':
            de = '生まれ月 × 年齢(2 歳 = 月・3 歳 = 20 + 月・4 歳以上 40)'
        elif c == 'c7_area':
            de = '産地 日高 1・胆振 2・その他 3'
        else:
            de = DEF[p[1]] + ' ' + SUF['_'.join(p[2:])]
        mi, co = f['miss'][c], f['corr'][c]
        L.append(f'| {c} | {de} | {100 * mi[0]:.1f}% | {100 * mi[1]:.1f}% | {co[0]:+.4f} | {co[1]:+.4f} |')
    if LEAKJ.exists():
        z = json.loads(LEAKJ.read_text(encoding='utf-8'))
        L += ['', '## 漏れ検査(t4_base.pick_days の 20 日・その日の結果を空にして作り直し)', '']
        for k, v in z.items():
            L.append(f'- {k}: {v["match_days"]} / {v["days"]} 日一致・セル {v["match"]} / {v["cells"]}')
    if 'judge' in R:
        j = R['judge']
        L += ['', '## judge(土台 v7_select.json の 138 列 + c7_ 1 群・2016〜19・Y3 15/500/800)', '',
              f'- 伸び {j["gain"]}・標準誤差 {j["se"]}・年ごと {j["years"]}・通った {j["ok"]}(和 {j["sum_base"]} → {j["sum_c7"]})']
    L += ['', '## 予想', '', '- v3/v7c_final_preds.parquet(2016〜21 の当てはめ外・v7_select.final と同じ手順)',
          '- v3/v7c_open_preds.parquet(2022-01〜2026-08・v7_open と同じ区切りの学び直し)',
          '- 列 v7cpre_p1・v7cpre_p3・v7cpre_p3p、比べ用に v7pre_p1・v7pre_p3・v7pre_p3p']
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    steps = {'feat': [feat], 'judge': [judge], 'final': [final], 'open': [open_], 'md': [write_md],
             'all': [feat, judge, final, open_, write_md]}[cmd]
    for s in steps:
        s()
