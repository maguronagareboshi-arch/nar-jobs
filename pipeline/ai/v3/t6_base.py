# -*- coding: utf-8 -*-
"""第 6 版 2 日目(PREREG6 §3・§4・§9 ②・§10・§11): 新しい 4 列(h2h・elo_z・nori・bw_diff)を 2014〜2021 の RAW から
日付の順に作り、部品の点検・見張りの線の元・リーク検査をして v3/feat_t6_explore.parquet に保存する。学習はしない。
2022-01-01 以降のファイルは開かない(t4_day3.raw の assert + ここでも assert)。第 4・5 版の台本は直さずに呼ぶ。

  py -3.12 -X utf8 src/t6_base.py build   # 4 列 → p3′ の点検 → 部品の点検 → 見張りの線の元 → feat_t6_explore
  py -3.12 -X utf8 src/t6_base.py leak    # リーク検査(20 日・seed 0・うち 4 日は 1 月。t4_base.pick_days を南関の開催日で)

■ 決め書に無い細部(この台本で決めた・段の当てはめ外を見る前。見た後は変えない)
  1. 4 列の定義は out/v6_work/v6_quick.py の build(乗り比べ 126〜138・直接対決 211〜224・ベスト体重 235〜241・
     Elo 253〜282 行)を写した cols4()。違いは bw_diff の今回の体重を材料の表の o_bw にすることだけ
     (走りの表の body_weight と同じ行で差 0・両方欠けも一致を assert)。
  2. 付ける行 T = feat_t5_explore の全行(2015〜2021)。行の順も feat_t5_explore のまま保存する。
     T の馬の鍵・騎手・rid・前走の騎手 pj は、走りの表(取消・除外を除く)に (場・日付・R・馬番) で付ける(1:1 を assert)。
  3. 同じ日のレースの処理順(Elo): 日付 → rid(RAW を t4_day3.sources_from で読んだ順に KEY で ngroup)。
     同じ日に 2 回以上出走する馬の鍵 = 0 を assert するので、同じ日の中の順は値を変えない。
  4. 着順の無い出走(中止・失格など)の着順 = そのレースの出走数(取消・除外を除く)。h2h・Elo 共通。
  5. p3′: レースごとに δ を二分法(区間 [−30, +30]・100 回・最後は区間の中点)で求める。p3 は 1e-6〜1 − 1e-6 に切って logit。
     ニュートン法の比べ = δ0 = 0 から 50 回(δ ← δ − (Σp − 3) ÷ Σp(1 − p))。順の一致 = レース内の順位(同じ値は最小の順位)が同じ。
  6. 見張りの線の元(§9 ②): 分母 = その年の全 NAR の出走(取消・除外を除く)で、南関 4 場と南関以外に分ける。
     騎手名のつながり = 騎手名(NFKC)が、その日の 365 日前〜前日の全 NAR の出走(取消・除外を除く)の騎手名に 1 回以上ある割合
     (騎手名が欠けの出走はつながらないに数える)。馬体重のある割合 = body_weight が欠けでない割合。
     線 = 2016〜2021 の年ごとの最小 − 0.05。
  7. 連闘 = T の馬のうち、走りの表の前走(取消・除外を除く・全 NAR)の日が予想する日の前日である馬(2016〜2021)。
  8. リーク検査: 抜き取り日 d について、走りの表(sources_from の後・NFKC の後)から d より後の行を消し、d の行は取消・除外の行を
     消したうえで、残す列 = track・race_date・race_no・umaban・jockey・body_weight・horse_name・horse_key・hid だけにし、
     ほかの列(finish・finish_note・time_raw・time_sec・margin・last3f・f_l3・popularity・body_weight_change・通過順・
     レースの列など)をすべて欠けにして cols4() で作り直す。比べるのは d のレースの h2h・elo_z・nori・bw_diff
     (欠けの位置も一致・|差| ≤ 1e-9)。o_bw は材料の表のもの(当日の発表)。
  9. 一致の判定は |差| ≤ 1e-9(両方欠けも一致)。
"""
import json
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_base  # noqa: E402
import t4_day3  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
FEAT5 = V3 / 'feat_t5_explore.parquet'
FEAT6 = V3 / 'feat_t6_explore.parquet'
PREDS5 = V3 / 't5_day3_preds.parquet'
V6COLS = V3 / 'v6_cols.parquet'
RES = V3 / 't6_day2.json'
MD = REPO / 'out/t6_day2_parts.md'
KEY = t4_day3.KEY
NANKAN = t4_day3.NANKAN
CANCEL = t4_day3.CANCEL
NEW4 = ['h2h', 'elo_z', 'nori', 'bw_diff']
KEEP_D = KEY + ['umaban', 'jockey', 'body_weight', 'horse_name', 'horse_key', 'hid']
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.1f}s]', *a, flush=True)


def res_load():
    return json.loads(RES.read_text(encoding='utf-8')) if RES.exists() else {}


def res_save(k, v):
    z = res_load()
    z[k] = v
    RES.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding='utf-8')


def dnum(s):
    return pd.to_datetime(s).values.astype('datetime64[D]').astype(np.int64)


def wsum(ek, ed, ev, qk, qd, lo, hi):
    """v6_quick.wsum と同じ: events の和を query (key, day) ごとに day−lo 〜 day−hi(両端を含む)で取る。"""
    ek = pd.Series(ek).astype(object).to_numpy()
    qk = pd.Series(qk).astype(object).to_numpy()
    ok = pd.notna(ek)
    ek, ed, ev = ek[ok], np.asarray(ed)[ok], np.asarray(ev, float)[ok]
    if ev.ndim == 1:
        ev = ev[:, None]
    cats = pd.Index(pd.unique(ek))
    ec = cats.get_indexer(ek).astype(np.int64)
    qc = np.where(pd.notna(qk), cats.get_indexer(np.where(pd.notna(qk), qk, '__none__')), -1).astype(np.int64)
    pos = ec * 100000 + ed
    o = np.argsort(pos, kind='stable')
    pos, ev = pos[o], ev[o]
    cs = np.vstack([np.zeros((1, ev.shape[1])), np.cumsum(ev, 0)])
    qd = np.asarray(qd)
    a = np.searchsorted(pos, qc * 100000 + (qd - lo), 'left')
    b = np.searchsorted(pos, qc * 100000 + (qd - hi), 'right')
    out = cs[b] - cs[a]
    out[qc < 0] = 0
    return out


def eqmask(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-9)


# ================================================================ 読み込み
def load_h():
    runs, facts, races = t4_day3.raw()
    h = t4_day3.sources_from(runs, facts, races)
    for c in ('jockey', 'trainer'):
        h[c] = h[c].map(lambda x: unicodedata.normalize('NFKC', x) if isinstance(x, str) else x)
    h = h[h.race_date >= '2013-01-01'].reset_index(drop=True)
    assert h.race_date.max() < '2022-01-01' and h.race_date.min() >= '2014-01-01', (h.race_date.min(), h.race_date.max())
    return h, races


def starts(h):
    h = h.copy()
    h['dn'] = dnum(h.race_date)
    h['rid'] = h.groupby(KEY, sort=False).ngroup()
    st = h[~h.finish_note.isin(CANCEL)].copy()
    st['nst'] = st.groupby('rid').umaban.transform('size')
    st['fin'] = st.finish.where(st.finish.notna(), st.nst).astype(float)
    st = st.sort_values(['hid', 'dn', 'race_no'], kind='mergesort').reset_index(drop=True)
    same = st.hid.eq(st.hid.shift())
    st['pj'] = st.jockey.shift().where(same & (st.dn - st.dn.shift() <= 365))
    st['prev_dn'] = st.dn.shift().where(same)
    return st


# ================================================================ 4 列(v6_quick.build と同じ定義)
def cols4(st, T):
    """T: KEY・umaban・o_bw を持つ表(index は何でもよい)。4 列と途中の列を T の行の順で返す。"""
    dup = int(st.duplicated(['hid', 'race_date']).sum())
    assert dup == 0, ('同じ日に 2 回以上出走する馬の鍵', dup)
    T = T[KEY + ['umaban', 'o_bw']].copy()
    T['_i'] = np.arange(len(T))
    T['race_no'] = T.race_no.astype(int)
    T = T.merge(st[KEY + ['umaban', 'hid', 'rid', 'dn', 'jockey', 'body_weight', 'pj', 'prev_dn']],
                on=KEY + ['umaban'], how='left', validate='1:1')
    T['dn'] = dnum(T.race_date)

    # 乗り比べ(v6_quick 126〜138)
    A = T[['rid', 'umaban', 'jockey', 'pj']]
    ch = A.dropna(subset=['jockey']).merge(A.dropna(subset=['pj'])[['rid', 'umaban', 'pj']].rename(
        columns={'umaban': 'uk', 'pj': 'jockey'}), on=['rid', 'jockey'])
    ch = ch[ch.umaban != ch.uk].groupby(['rid', 'umaban']).size().rename('ch')
    dr = A.dropna(subset=['pj']).merge(A[['rid', 'umaban', 'jockey']].rename(columns={'umaban': 'uk', 'jockey': 'pj'}),
                                        on=['rid', 'pj'])
    dr = dr[(dr.umaban != dr.uk) & (dr.pj != dr.jockey)].groupby(['rid', 'umaban']).size().rename('dr')
    T = T.join(ch, on=['rid', 'umaban']).join(dr, on=['rid', 'umaban'])
    T['nori_ch'] = (T.ch.fillna(0) > 0).astype(float)
    T['nori_dr'] = (T.dr.fillna(0) > 0).astype(float)
    T['nori'] = T.nori_ch - T.nori_dr

    # 直接対決(v6_quick 211〜224)
    Q = T[['rid', 'umaban', 'hid', 'dn']].rename(columns={'rid': 'rt', 'dn': 'dt'})
    H = st[['hid', 'rid', 'dn', 'fin']]
    PP = Q.merge(H, on='hid')
    PP = PP[(PP.dn < PP.dt) & (PP.dn >= PP.dt - 365)][['rt', 'umaban', 'rid', 'fin']]
    QQ = PP.merge(PP, on=['rt', 'rid'], suffixes=('', '_o'))
    QQ = QQ[QQ.umaban != QQ.umaban_o]
    QQ['W'], QQ['L'] = (QQ.fin < QQ.fin_o).astype(float), (QQ.fin > QQ.fin_o).astype(float)
    hh = QQ.groupby(['rt', 'umaban'])[['W', 'L']].sum()
    T = T.join(hh, on=['rid', 'umaban'])
    nm = T.W.fillna(0) + T.L.fillna(0)
    T['h2h'] = np.where(nm > 0, (T.W.fillna(0) + 1) / (nm + 2) - 0.5, np.nan)

    # ベスト体重との差(v6_quick 235〜241。今回の体重 = o_bw)
    g3 = st[(st.finish <= 3) & st.body_weight.notna()]
    bw = wsum(g3.hid, g3.dn, np.c_[g3.body_weight.astype(float), np.ones(len(g3))], T.hid, T.dn, 1095, 1)
    T['best_bw'] = np.where(bw[:, 1] > 0, bw[:, 0] / np.maximum(bw[:, 1], 1), np.nan)
    T['bw_diff'] = T.o_bw.astype(float) - T.best_bw

    # 多頭数 Elo(v6_quick 253〜282)
    st2 = st.sort_values(['dn', 'rid'], kind='mergesort').reset_index(drop=True)
    hc = pd.factorize(st2.hid)[0]
    rating = np.full(hc.max() + 1, np.nan)
    pre = np.full(len(st2), np.nan)
    rid = st2.rid.to_numpy()
    fin = st2.fin.to_numpy()
    b = np.flatnonzero(np.r_[True, rid[1:] != rid[:-1], True])
    K = 32.0
    for s, e in zip(b[:-1], b[1:]):
        ix = hc[s:e]
        r0 = rating[ix]
        pre[s:e] = r0
        n = e - s
        if n < 2:
            continue
        known = ~np.isnan(r0)
        r = np.where(known, r0, r0[known].mean() if known.any() else 1500.0)
        f = fin[s:e]
        S_ = (f[:, None] < f[None, :]) + 0.5 * (f[:, None] == f[None, :])
        E_ = 1 / (1 + 10 ** ((r[None, :] - r[:, None]) / 400))
        np.fill_diagonal(S_, 0)
        np.fill_diagonal(E_, 0)
        rating[ix] = r + K / (n - 1) * (S_ - E_).sum(1)
    st2['elo'] = pre
    T = T.merge(st2[KEY + ['umaban', 'elo']], on=KEY + ['umaban'], how='left', validate='m:1')
    gz = T.groupby(KEY).elo
    T['elo_z'] = (T.elo - gz.transform('mean')) / gz.transform('std')
    T = T.sort_values('_i').reset_index(drop=True)
    assert (T._i.to_numpy() == np.arange(len(T))).all()
    return T


# ================================================================ p3′
def p3prime(df, col, key=KEY):
    """合計 3 にそろえた p3′(二分法 [−30, +30]・100 回)と、ニュートン法 50 回の値・レースごとの δ。"""
    g = df.groupby(key, sort=False).ngroup().to_numpy()
    p = np.clip(df[col].to_numpy(float), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    R = g.max() + 1
    lo, hi = np.full(R, -30.0), np.full(R, 30.0)
    for _ in range(100):
        mid = (lo + hi) / 2
        S = np.bincount(g, 1 / (1 + np.exp(-(z + mid[g]))), R)
        up = S < 3
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    d = (lo + hi) / 2
    q = 1 / (1 + np.exp(-(z + d[g])))
    dn = np.zeros(R)
    for _ in range(50):
        pn = 1 / (1 + np.exp(-(z + dn[g])))
        dn = dn - (np.bincount(g, pn, R) - 3) / np.bincount(g, pn * (1 - pn), R)
    qn = 1 / (1 + np.exp(-(z + dn[g])))
    return q, qn, d, g


def check_p3():
    P = pd.read_parquet(PREDS5)
    out = {}
    for c in ('v5pre_p3', 'v5day_p3', 'v4pre_p3', 'v4day_p3'):
        q, qn, d, g = p3prime(P, c)
        R = g.max() + 1
        err = float(np.abs(np.bincount(g, q, R) - 3).max())
        ra = pd.Series(P[c].to_numpy(float)).groupby(g).rank(method='min').to_numpy()
        rb = pd.Series(q).groupby(g).rank(method='min').to_numpy()
        newton = float(np.abs(q - qn).max())
        out[c] = {'races': int(R), 'sum_err_max': err, 'order_same': bool((ra == rb).all()), 'newton_diff_max': newton,
                  'delta_min': float(d.min()), 'delta_max': float(d.max()), 'gt1': int((q > 1).sum())}
        log('p3′', c, out[c])
        assert err <= 1e-9 and (ra == rb).all() and newton <= 1e-9, (c, out[c])
    return out


# ================================================================ build
def build():
    h, races = load_h()
    log('RAW', len(h), h.race_date.min(), h.race_date.max())
    st = starts(h)
    dup = int(st.duplicated(['hid', 'race_date']).sum())
    log('starts', len(st), 'dup', dup)
    F = pd.read_parquet(FEAT5)
    log('feat_t5_explore', F.shape)
    T = cols4(st, F)
    z = {'raw_rows': int(len(h)), 'starts': int(len(st)), 'raw_max': h.race_date.max(), 'dup_same_day': dup,
         'T_rows': int(len(T)), 'T_hid_rate': float(T.hid.notna().mean())}
    chk = {}

    # ベスト体重の今回の体重
    a, b2 = T.o_bw.to_numpy(float), T.body_weight.to_numpy(float)
    bw_ok = eqmask(a, b2)
    chk['o_bw_eq'] = {'rows': int(len(T)), 'match': int(bw_ok.sum()), 'both_nan': int((np.isnan(a) & np.isnan(b2)).sum())}
    log('o_bw', chk['o_bw_eq'])

    # p3′
    chk['p3prime'] = check_p3()

    # 下調べとの一致
    V = pd.read_parquet(V6COLS, columns=KEY + ['umaban'] + NEW4)
    V['race_no'] = V.race_no.astype(int)
    M = T[KEY + ['umaban'] + NEW4].merge(V, on=KEY + ['umaban'], how='inner', suffixes=('', '_v'), validate='1:1')
    per = {c: int(eqmask(M[c], M[c + '_v']).sum()) for c in NEW4}
    chk['v6_match'] = {'v6_rows': int(len(V)), 'joined': int(len(M)), 'match': per}
    log('v6 一致', chk['v6_match'])

    # 土台の表が変わらない
    O = F.copy()
    for c in NEW4:
        O[c] = T[c].to_numpy()
    import t5_day3
    same = [c for c in F.columns if not O[c].equals(F[c])]
    banned = sorted((set(t5_day3.ALL5) | set(NEW4)) & t4_day3.BANNED)
    chk['base_same'] = {'cols': int(len(F.columns)), 'changed': same, 'banned_in_features': banned,
                        'feat_cols_118': int(len(t5_day3.ALL5))}
    log('土台', chk['base_same'])

    # 記録: 年ごと
    T['year'] = T.race_date.str[:4].astype(int)
    rec = {}
    for y, g in T.groupby('year'):
        rec[str(y)] = {'rows': int(len(g)), **{c: round(float(g[c].notna().mean()), 4) for c in NEW4},
                       'nori_ch1': round(float((g.nori_ch == 1).mean()), 4),
                       'nori_dr1': round(float((g.nori_dr == 1).mean()), 4),
                       'rentou': int((g.dn - g.prev_dn == 1).sum())}
    z['yearly'] = rec
    z['rentou_2016_2021'] = int(sum(v['rentou'] for k, v in rec.items() if int(k) >= 2016))
    log('年ごと', rec)

    # 見張りの線の元(§9 ②)
    S = st[(st.race_date >= '2015-01-01')].copy()
    cnt = wsum(st.jockey, st.dn, np.ones(len(st)), S.jockey, S.dn, 365, 1)[:, 0]
    S['jlink'] = (cnt > 0).astype(float)
    S['bwok'] = S.body_weight.notna().astype(float)
    S['year'] = S.race_date.str[:4].astype(int)
    S['area'] = np.where(S.track.isin(NANKAN), 'nankan', 'other')
    wt = {}
    for (ar, y), g in S.groupby(['area', 'year']):
        wt.setdefault(ar, {})[str(y)] = {'n': int(len(g)), 'jlink': round(float(g.jlink.mean()), 4),
                                         'bw': round(float(g.bwok.mean()), 4)}
    lines = {}
    for ar, d in wt.items():
        for m in ('jlink', 'bw'):
            mn = min(v[m] for k, v in d.items() if int(k) >= 2016)
            lines[f'{ar}_{m}'] = {'min_2016_2021': mn, 'line': round(mn - 0.05, 4)}
    z['watch_base'] = {'yearly': wt, 'lines': lines}
    log('見張りの線の元', lines)

    z['checks'] = chk
    ok = {'v6_match': all(v == len(V) for v in per.values()) and len(M) == len(V),
          'dup0': dup == 0,
          'base_same': not same and not banned,
          'o_bw_eq': chk['o_bw_eq']['match'] == len(T),
          'p3prime': True}
    z['pass'] = ok
    res_save('build', z)
    log('合否', ok)
    if not all(ok.values()):
        raise SystemExit('⛔ 部品の点検に届かない(feat_t6_explore は保存しない)')
    O.to_parquet(FEAT6)
    log('保存', FEAT6, O.shape)


# ================================================================ leak
def leak():
    h, races = load_h()
    full = pd.read_parquet(FEAT6)
    full['race_no'] = full.race_no.astype(int)
    days = t4_base.pick_days(races[races.track.isin(NANKAN)])
    blank = [c for c in h.columns if c not in KEEP_D]
    per, tot = [], [0, 0]
    for X in days:
        prev = h[h.race_date < X]
        cur = h[(h.race_date == X) & ~h.finish_note.isin(CANCEL)].copy()
        cur[blank] = np.nan
        hd = pd.concat([prev, cur], ignore_index=True)
        st = starts(hd)
        Td = full[full.race_date == X].reset_index(drop=True)
        T = cols4(st, Td)
        eq = np.column_stack([eqmask(T[c], Td[c]) for c in NEW4])
        bad = [c for c, okc in zip(NEW4, eq.all(0)) if not okc]
        per.append({'date': X, 'rows': int(len(Td)), 'match': int(eq.sum()), 'cells': int(eq.size), 'bad_cols': bad})
        tot[0] += int(eq.sum()); tot[1] += int(eq.size)
        log(X, len(Td), int(eq.sum()), eq.size, bad)
    z = {'days': len(days), 'jan_days': sum(p['date'][5:7] == '01' for p in per),
         'match_days': sum(p['match'] == p['cells'] for p in per), 'match': tot[0], 'cells': tot[1],
         'cols': NEW4, 'per_day': per}
    res_save('leak', z)
    log('一致', z['match_days'], '/', z['days'], '日', tot[0], '/', tot[1])
    if tot[0] != tot[1]:
        raise SystemExit('⛔ リーク検査が 100% でない')


if __name__ == '__main__':
    {'build': build, 'leak': leak}[sys.argv[1]]()
