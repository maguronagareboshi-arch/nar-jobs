# -*- coding: utf-8 -*-
"""ばんえい(帯広)第 3 版の便(2026-10-28・v3 の src/banei/prod/banei_v3.py を便の形に・ばんえい 決め 6 の形)。

z = 0.8 × logit(第 2 版の木 355 列) + 0.2 × 平らな模型 + 並び読みの外した分 → 3 着内率 = 合計 3 に割り直すだけ(案 1・ユーザー 10/28)
→ 勝つ率 = exp(b1 × z) をレースの中で合計 1 に(イ・2026-10-30 から。前は 3 着内率の割合 = ア)。級は class_fix.parse_class_fixed で読む。オッズ・人気は使わない。

  python -X utf8 pipeline/ai/banei/banei_v3.py fit DAY <模型の置き場>                    # 朝: 前の日までで学ぶ(木・並び読み 3 種・平ら)
  python -X utf8 pipeline/ai/banei/banei_v3.py predict DAY <模型の置き場> [--write]      # 直前の周: 当日の体重・1R の水分で当てて書く
  python -X utf8 pipeline/ai/banei/banei_v3.py morning DAY <模型の置き場> [--write]      # 朝: 体重 = 前走・1R の水分と天候 = 前の開催日の 1R で当てて書く
  python -X utf8 pipeline/ai/banei/banei_v3.py selftest DAY                              # 手元: 分けた学び・当ては研究の run と同じ値か
置き場の環境変数: BANEI_V3 = 表の根(official/・banei_kb/・banei_kb/prod/v2_oof.parquet・banei_kb/banei_v2_lock.json)。
  便では fit・predict の頭で公式の表を REST から落とし(bn_dl)、競馬ブックの表を固めた表 + DB の nar_kb_banei で作る(bn_kb)。
  BANEI_LOCAL=1 なら落とさず、手元の表をそのまま使う(手元の通し)。

外した分の初期値(並び読みの学びの土台)= 第 2 版の「その行を学んでいない予想」:
  固めた表 v2_oof.parquet(〜2026-10-05)→ 本番の行の meta.p_v2(model='banei-3'・timing='last')→ どちらも無い日は
  その月の頭より前で学んだ第 2 版の木で埋める(月ごと)。

止まる(書かない)= base-v1 の帯広の印が残る:
  当日の行が無い・前の開催日の競馬ブックが無い・1R の水分が無い・率に空。レースごとには、取消でない馬の体重がそろっていないレースは書かない。
朝の版(2026-10-28 ユーザー承認・v3 の out/banei_morning_v3.md): 模型は直前版と同じ。当日の行だけ 体重 → その馬の前走の体重(増減 0・
  前走の無い馬は空)・1R の水分と天候 → 前の開催日の 1R の値 に差し替えて当てる。選びの期間 716 R で本命 3 着内 直前 65.9% → 朝 64.7%。
⛔本番に書くのは nar_ai_marks の model='banei-3'・timing='last' と 'morning'(朝は凍結 = 既にある行は触らない)だけ(base_v1.write_marks・発走 15 分前を過ぎた行は DB のトリガーが捨てる)。
"""
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import feat_v1 as f1  # noqa: E402
import feat_v2 as f2  # noqa: E402
import class_fix as cf  # noqa: E402
import seq_core as sc  # noqa: E402
import noken as nkm  # noqa: E402

V = f1.OUT
OUTD = V + 'prod/'
K = ['race_date', 'race_no', 'runner_number']
MODEL_ID = 'banei-3'
MARKS = ['◎', '○', '▲', '△', '△']
FORM = 'banei-4: v2tree355 0.8 + flat 0.2 + seq res + b*noken(debut) / clsfix / p3 sum3 / p1 = exp(b1*z) share'
GAP_FROM = '2026-09-01'   # 固めた表の前の版(〜2026-08)より後 = 月ごとの埋めの対象
LOCAL = os.environ.get('BANEI_LOCAL') == '1'
JST = dt.timezone(dt.timedelta(hours=9))
T0 = time.time()
lg = sc.lg


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def lock():
    p = os.environ.get('BANEI_LOCK', V + 'banei_v2_lock.json')
    L = json.load(open(p, encoding='utf-8'))
    P = dict(objective='binary', learning_rate=0.03, num_leaves=63, min_data_in_leaf=100, feature_fraction=0.7, bagging_fraction=0.8,
             bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=0, num_threads=int(os.environ.get('BANEI_TREE_THREADS', '16')))
    P.update(L['params'])
    return L, P, L['cols_v1'] + L['cols_v2']


# ---------------------------------------------------------------- 材料(研究と同じ)
def tables(cutoff, fix=True, drop_race=None):
    f1.parse_class = cf.parse_class_fixed if fix else cf._orig
    ru, ra, pr, kd = f1.load()
    if drop_race:
        ra = ra[~((ra.race_date.astype(str) == cutoff) & (ra.race_no == drop_race))]
    keep1 = json.load(open(V + 'feat_v1_cols.json', encoding='utf-8'))['features']
    keep2 = json.load(open(V + 'feat_v2_cols.json', encoding='utf-8'))['features_v2']
    ID, F, base = f1.build(ru, ra, pr, kd, cutoff=cutoff)
    D1 = ID.join(F)[f1.IDCOLS + keep1]
    N, _ = f2.build(ru, ra, pr, kd, cutoff=cutoff, base=base)
    D2 = D1.merge(N[K + keep2], on=K, how='left', validate='1:1')
    for x in (D1, D2):
        x['race_date'] = x.race_date.astype(str); x['race_no'] = x.race_no.astype(int); x['runner_number'] = x.runner_number.astype(int)
    log('材料', D2.shape, '級の直し', fix)
    return D1, D2, ru


def seq_arrays(D1, ru, cutoff=None):
    """seq_banei.build と同じ入力(過去 10 走 × 29・今回 19)を、保存せずに返す。"""
    import seq_banei as sb
    f = D1[K + ['hk', 'rkey', 'scratch', 'dnf', 'finish', 'y_top3', 'a08_age', 'a09_sex', 'f99_cw', 'g127_bw', 'g128_bw_diff',
                'h139_cls_level', 'h147_prize1', 'b17_going_day', 'ref_going_race', 'a11_n_start', 'f117_mare_mixed', 'b29_month']].copy()
    ru = ru[ru.track == '帯広ば'][K + ['jockey', 'trainer', 'time_sec']].copy()
    kb = f2.load_kb(cutoff)[K + ['seg_front', 'seg_obst', 'seg_back', 'pass1', 'pass2', 'pass3']]
    for x in (ru, kb):
        x['race_date'] = x.race_date.astype(str); x['race_no'] = x.race_no.astype(int); x['runner_number'] = x.runner_number.astype(int)
    if cutoff is not None:
        ru.loc[ru.race_date == cutoff, 'time_sec'] = np.nan
    saved = {}
    orig_read, orig_save = pd.read_parquet, np.savez

    def rp(path, columns=None, filters=None):
        if path.endswith('feat_v1.parquet'):
            return f[columns].copy()
        if path.endswith('official/runs.parquet'):
            return ru.assign(track='帯広ば')[columns].copy()
        if path.endswith('kb_runs.parquet'):
            return kb.rename(columns={'runner_number': 'umaban'})[columns].copy()
        return orig_read(path, columns=columns, filters=filters)
    pd.read_parquet = rp
    np.savez = lambda _p, **kw: saved.update(kw)
    try:
        sb.build()
    finally:
        pd.read_parquet, np.savez = orig_read, orig_save
    return saved


def S_of(Z, off):
    rid, slot, date = Z['rid'], Z['slot'], Z['date']
    n, nr = len(rid), rid.max() + 1
    R = np.zeros((nr, sc.MAXN), np.int64) - 1
    R[rid, slot] = np.arange(n)
    rdate = np.empty(nr, 'U10'); rdate[rid] = date
    has_off = np.zeros(nr, bool); has_off[rid[~np.isnan(off)]] = True
    return dict(hist=np.nan_to_num(Z['hist']), ctx=np.nan_to_num(Z['ctx']), y3=Z['y3'], off=off, R=R, rdate=rdate, has_off=has_off,
                n=n, date=date)


# ---------------------------------------------------------------- 外した分の初期値
def frozen_oof():
    o = pd.read_parquet(OUTD + 'v2_oof.parquet')
    o['race_date'] = o.race_date.astype(str); o['race_no'] = o.race_no.astype(int); o['runner_number'] = o.runner_number.astype(int)
    return o[K + ['off']]


def db_oof(since):
    """本番の行の meta.p_v2(その日の第 2 版 = 前の日まで学んだ木)→ 外した分の初期値。読めなければ空。"""
    if LOCAL or os.environ.get('BANEI_NO_DB') == '1':
        return pd.DataFrame(columns=K + ['off'])
    try:
        import bn_kb
        rs, off = [], 0
        while True:
            r = bn_kb.rest(f'/rest/v1/nar_ai_marks?select=race_date,race_no,meta&model=eq.{MODEL_ID}&timing=eq.last'
                           f'&track=eq.{bn_kb.urllib.parse.quote("帯広ば")}&race_date=gte.{since}&order=race_date,race_no&limit=1000&offset={off}')
            rs += r
            if len(r) < 1000:
                break
            off += 1000
    except Exception as e:  # noqa: BLE001
        log('本番の行の p_v2 が読めない', type(e).__name__, str(e)[:120])
        return pd.DataFrame(columns=K + ['off'])
    out = [{'race_date': str(r['race_date'])[:10], 'race_no': int(r['race_no']), 'runner_number': int(n), 'off': float(lg(np.float64(p)))}
           for r in rs for n, p in ((r.get('meta') or {}).get('p_v2') or {}).items()]
    log('本番の行の p_v2', len(out), '頭')
    return pd.DataFrame(out, columns=K + ['off'])


def tree_fit(D2, lo):
    import lightgbm as lgb
    L, P, COLS = lock()
    d = D2[(D2.scratch == 0)]
    tr = d[d.y_top3.notna() & (d.race_date >= L['start']) & (d.race_date < lo)]
    m = lgb.train(P, lgb.Dataset(tr[COLS], tr.y_top3.astype(int)), num_boost_round=L['iters'])
    log('第 2 版の木', lo, '学び', len(tr))
    return m


def tree_apply(m, D2, lo, hi):
    _, _, COLS = lock()
    d = D2[(D2.scratch == 0)]
    cur = d[(d.race_date >= lo) & (d.race_date < hi)][K].copy()
    cur['p_v2'] = m.predict(d.loc[cur.index, COLS])
    return cur


def gap_oof(D2, have, day):
    """固めた表にも本番の行にも無い日(GAP_FROM 〜 前の日・結果のある行)を、その月の頭より前で学んだ第 2 版の木で埋める。"""
    d = D2[(D2.scratch == 0) & D2.y_top3.notna() & (D2.race_date >= GAP_FROM) & (D2.race_date < day)][K]
    miss = d.merge(have[K].assign(h=1), on=K, how='left')
    miss = miss[miss.h.isna()]
    if miss.empty:
        return pd.DataFrame(columns=K + ['off'])
    outs = []
    for p in sorted(pd.PeriodIndex(miss.race_date, freq='M').unique()):
        lo, hi = str(p.start_time.date()), min(str((p + 1).start_time.date()), day)
        days = sorted(miss[(miss.race_date >= lo) & (miss.race_date < hi)].race_date.unique())
        c = tree_apply(tree_fit(D2, lo), D2, lo, hi)
        c = c[c.race_date.isin(days)]
        outs.append(c.assign(off=lg(c.p_v2.to_numpy(float)))[K + ['off']])
        log('月ごとの埋め', p, len(days), '日', len(c), '頭')
    return pd.concat(outs, ignore_index=True)


def oof_table(D2, day, use_db=True, use_gap=True):
    o = frozen_oof()
    if use_db:
        o = pd.concat([o, db_oof((pd.Timestamp(o.race_date.max()) + pd.Timedelta(days=1)).date().isoformat())])
        o = o.drop_duplicates(K, keep='first')
    if use_gap:
        o = pd.concat([o, gap_oof(D2, o, day)], ignore_index=True)
    return o


def offsets(Z, o, extra=None):
    E = pd.DataFrame({'race_date': Z['date'], 'race_no': Z['race_no'].astype(int), 'runner_number': Z['umaban'].astype(int)})
    if extra is not None:
        o = pd.concat([o, extra[K + ['off']]]).drop_duplicates(K, keep='last')
    return E.merge(o, on=K, how='left').off.to_numpy(np.float32)


# ---------------------------------------------------------------- 入力をそろえる
def prev_kb_ok(D2, day):
    """前の開催日(取りやめでないレースのある最後の日)の競馬ブックがあるか。全 R 取りやめの日は飛ばす。"""
    ra = pd.read_parquet(f1.V3 + 'official/races.parquet', columns=['track', 'race_date', 'cancelled'])
    ra = ra[(ra.track == '帯広ば') & (ra.race_date.astype(str) < day) & ra.cancelled.fillna('').astype(str).str.strip().eq('')]
    prev = str(ra.race_date.astype(str).max()) if len(ra) else D2[D2.race_date < day].race_date.max()
    return prev in set(f2.load_kb(None).race_date.astype(str)), prev


def get_inputs(day, refresh_today_only=False):
    """便: 公式の表を REST から(refresh_today_only = 当日の行だけ取り直す)・競馬ブックの表を作る・当日 ZIP を重ねる。手元(BANEI_LOCAL)は何もしない。"""
    if LOCAL:
        return
    import bn_dl
    import bn_kb
    root = f1.V3
    if refresh_today_only and Path(root + 'official/runs.parquet').exists():
        bn_dl.refresh_day(root, day)
    else:
        bn_dl.fetch(root, day)
        bn_kb.table(root)
    bn_dl.zip_step(root, day)


# ---------------------------------------------------------------- 入口
def fit(day, mdir, use_db=True, use_gap=True):
    """朝: 前の日までで 木・並び読み(3 種)・平らな模型を学んで mdir に置く。止まる時は 2 を返す(書かない)。"""
    mdir = Path(mdir); mdir.mkdir(parents=True, exist_ok=True)
    get_inputs(day)
    D1, D2, ru = tables(day)
    if D2[(D2.race_date == day) & (D2.scratch == 0)].empty:
        log('止まる: 当日の行が無い'); return 2
    ok, prev = prev_kb_ok(D2, day)
    if not ok:
        log('止まる: 前の開催日の競馬ブックが無い', prev); return 2
    tm = tree_fit(D2, day)
    o = oof_table(D2, day, use_db, use_gap)
    Z = seq_arrays(D1, ru, day)
    S = S_of(Z, offsets(Z, o))
    states = sc.seq_fit(S['hist'], S['ctx'], S, day, log)
    fm = sc.flat_fit(S['hist'], S['ctx'], S, day, 0)
    (mdir / 'tree.txt').write_text(tm.model_to_string(), encoding='utf-8')
    (mdir / 'flat.txt').write_text(fm.model_to_string(), encoding='utf-8')
    sc.save_states(states, mdir / 'seq.pt')
    o.to_parquet(mdir / 'oof.parquet', index=False)
    info = dict(day=day, prev=prev, form=FORM, oof_rows=int(len(o)), oof_to=str(o.race_date.max()),
                has_off=int(S['has_off'].sum()), made=dt.datetime.now(JST).isoformat(timespec='seconds'))
    (mdir / 'info.json').write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    log('学び済み', info)
    return 0


def score(day, mdir, drop_race=None, no_going=False):
    """当日の行の率(研究の predict と同じ式)。止まる時は None。"""
    mdir = Path(mdir)
    info = json.loads((mdir / 'info.json').read_text(encoding='utf-8'))
    if info['day'] != day:
        log('止まる: 模型の日が違う', info['day']); return None, None
    D1, D2, ru = tables(day, drop_race=drop_race)
    today = D2[(D2.race_date == day) & (D2.scratch == 0)]
    if today.empty:
        log('止まる: 当日の行が無い'); return None, None
    ok, prev = prev_kb_ok(D2, day)
    if not ok:
        log('止まる: 前の開催日の競馬ブックが無い', prev); return None, None
    if no_going or today.b17_going_day.isna().all():
        log('止まる: 1R の水分が無い'); return None, None
    nxt = str((pd.Timestamp(day) + pd.Timedelta(days=1)).date())
    v2 = tree_apply(sc.booster_from((mdir / 'tree.txt').read_text(encoding='utf-8')), D2, day, nxt)
    Z = seq_arrays(D1, ru, day)
    o = pd.read_parquet(mdir / 'oof.parquet')
    S = S_of(Z, offsets(Z, o, v2.assign(off=lg(v2.p_v2.to_numpy(float)))))
    res = sc.seq_apply(sc.load_states(mdir / 'seq.pt'), S['hist'], S['ctx'], S, day, nxt)
    fl = sc.flat_apply(sc.booster_from((mdir / 'flat.txt').read_text(encoding='utf-8')), S['hist'], S['ctx'], S, day, nxt)
    cur = (S['date'] >= day) & (S['date'] < nxt)
    out = pd.DataFrame({'race_date': Z['date'][cur], 'race_no': Z['race_no'][cur].astype(int), 'runner_number': Z['umaban'][cur].astype(int),
                        'rkey': Z['rkey'][cur], 'res': res[cur], 'flat': fl[cur]})
    out = out.merge(v2, on=K, how='left', validate='1:1')
    out = out.merge(today[K + ['horse_name', 'a12_runs']], on=K, how='left', validate='1:1')
    P = nkm.params()
    try:
        out['nk'], hit, deb, nt = nkm.nk_of(out, P)
        log('能検', '新馬', deb, '頭のうち結べた', hit, '・合格の回', nt, '・b', P['b'])
    except Exception as e:  # noqa: BLE001  ⛔能検が読めない日は 0(= 第 3 版と同じ)で続け、meta.nk_src に残す
        out['nk'] = 0.0; P = dict(P, src='none')
        log('能検が読めない = 足さない', repr(e)[:200])
    info = dict(info, nk_b=P['b'], nk_src=P.get('src', 'ok'))
    z = (1 - sc.W_FLAT) * lg(out.p_v2.to_numpy(float)) + sc.W_FLAT * out.flat + out.res + float(P['b']) * out.nk
    out['p'] = 1 / (1 + np.exp(-z))
    out['p3'] = (out.p / out.groupby('rkey').p.transform('sum') * 3).clip(1e-4, 1 - 1e-4)      # 案 1: 割り直すだけ
    out['p1'], b1, src = p1_of(out, z)                                                          # イ: exp(b1 × z) の割合
    info = dict(info, p1_b=b1, p1_src=src)
    log('勝つ率', src, 'b1', b1)
    bad = int(out[['res', 'flat', 'p_v2']].isna().any(axis=1).sum())
    log('当て', len(out), '頭', out.rkey.nunique(), 'R', '空', bad)
    if out[['p', 'p3', 'p1']].isna().any().any():
        log('止まる: 率に空'); return None, None
    bw = today.set_index(['race_no', 'runner_number']).g127_bw
    out['bw_ok'] = [bool(pd.notna(bw.get((r, n))) and bw.get((r, n)) > 0) for r, n in zip(out.race_no, out.runner_number)]
    out['going_day'] = float(today.b17_going_day.dropna().iloc[0])
    return out, info


def p1_params():
    return json.load(open(os.environ.get('BANEI_P1', f1.OUT + 'banei_p1.json'), encoding='utf-8'))


def p1_of(out, z):
    """勝つ率 イ = exp(b1 × z) をレースの中で合計 1 に(2026-10-30・v3 の out/banei_p1_check.md・b1 は固めた表 banei_kb/banei_p1.json)。
    ア(3 着内率の割合)は強い馬を低く・人気薄を高く見ていた(確かめ 3,295 R: 本命の見込み 22.7% に実際 34.8%)。
    ⛔係数が読めない日は ア で続け、meta.p1_src='share' に残す。印の順(3 着内率の順)は変わらない。"""
    try:
        b1 = float(p1_params()['b1'])
    except Exception as e:  # noqa: BLE001
        log('勝つ率の係数が読めない = 3 着内率の割合(ア)で出す', repr(e)[:200])
        return out.p3 / out.groupby('rkey').p3.transform('sum'), None, 'share'
    zz = pd.Series(np.asarray(z, float), index=out.index)
    s = np.exp(b1 * (zz - zz.groupby(out.rkey).transform('max')))
    p1 = (s / s.groupby(out.rkey).transform('sum')).to_numpy()
    p3, rk = out.p3.to_numpy(float), out.rkey.to_numpy()
    for r in np.unique(rk[p1 > p3]):  # ⛔3 着内率を超える馬(確かめ 46,029 頭に 1 頭)は 3 着内率で止め、余りを同じ R の他の馬へ割合で配る
        m = rk == r
        o = m & (p1 > p3)
        ex = float((p1[o] - p3[o]).sum())
        p1[o] = p3[o]
        p1[m & ~o] *= 1 + ex / float(p1[m & ~o].sum())
    return pd.Series(p1, index=out.index), b1, 'ok'


def morning_frames(frames, day):
    """朝の版: 当日の行だけ、体重 = その馬の前走の体重・1R の水分と天候 = 前の開催日(水分のある最後の 1R)の値。"""
    ru, ra, pr, kd = frames
    ru, ra = ru.copy(), ra.copy()
    ds = ru.race_date.astype(str)
    hk = ru.horse_name.astype(str) + '|' + ru.birth_date.astype(str)
    h = ru[(ds < day) & ru.body_weight.notna()].assign(hk=hk).sort_values(['race_date', 'race_no'])
    t = ds == day
    ru.loc[t, 'body_weight'] = hk[t].map(h.groupby('hk').body_weight.last()).to_numpy()
    rs = ra.race_date.astype(str)
    first = ra[(rs < day) & ra.cancelled.isna()].sort_values(['race_date', 'race_no']).groupby('race_date').first()
    first = first[pd.to_numeric(first.going, errors='coerce').notna()]
    r1 = first.iloc[-1]
    ra.loc[rs == day, ['going', 'weather']] = [r1.going, r1.weather]
    log('朝の埋め', '体重 前走', int(ru.loc[t, 'body_weight'].notna().sum()), '/', int(t.sum()), '頭', '水分', r1.going, r1.weather, '=', r1.name)
    return ru, ra, pr, kd


def rows_of(out, info, day, need_bw=True, timing='last'):
    rows, skip = [], []
    for rno, g in out.groupby('race_no'):
        if need_bw and not g.bw_ok.all():
            skip.append(f'{rno}R(体重 {int((~g.bw_ok).sum())} 頭空)'); continue
        g = g.sort_values('runner_number')
        order = np.argsort(-g.p3.to_numpy(), kind='stable')
        sc_ = g.p3.to_numpy() / g.p3.sum()
        nums = g.runner_number.to_numpy()
        marks = [{'num': int(nums[i]), 'mark': MARKS[k], 'score': round(float(sc_[i]) * 100, 1)} for k, i in enumerate(order[:5])]
        meta = {'n': int(len(g)), 'model': MODEL_ID, 'form': FORM, 'timing': timing, 'trained_to': info['prev'], 'going_day': g.going_day.iloc[0],
                'runners': [{'num': int(n), 'p1': round(float(a), 4), 'p3': round(float(b), 4)} for n, a, b in zip(nums, g.p1, g.p3)],
                'p_v2': {str(int(n)): round(float(x), 6) for n, x in zip(nums, g.p_v2)},
                'p': {str(int(n)): round(float(x), 4) for n, x in zip(nums, g.p)},
                'nk': {str(int(n)): round(float(x), 4) for n, x in zip(nums, g.nk) if x != 0}, 'nk_b': info.get('nk_b'), 'nk_src': info.get('nk_src'),
                'p1_b': info.get('p1_b'), 'p1_src': info.get('p1_src')}
        rows.append({'track': '帯広ば', 'race_date': day, 'race_no': int(rno), 'marks': marks, 'meta': meta})
    return rows, skip


def predict(day, mdir, write=False, drop_race=None, no_going=False):
    """直前の周: 当日の行だけ取り直し・ZIP を重ね・当てて、体重のそろったレースを書く(前の回と同じ中身のレースは書かない)。"""
    get_inputs(day, refresh_today_only=True)
    out, info = score(day, mdir, drop_race, no_going)
    if out is None:
        return 2
    rows, skip = rows_of(out, info, day)
    for r in rows:
        print(f"帯広ば{r['race_no']}R " + ' '.join(f"{m['mark']}{m['num']}({m['score']})" for m in r['marks']), flush=True)
    log('書ける', len(rows), 'R・体重待ち', ' '.join(skip) or 'なし')
    Path(mdir, f'banei3_{day}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    if not write or not rows:
        return 0
    import bn_kb
    try:
        have = bn_kb.rest(f'/rest/v1/nar_ai_marks?select=race_no,meta&model=eq.{MODEL_ID}&timing=eq.last'
                          f'&track=eq.{bn_kb.urllib.parse.quote("帯広ば")}&race_date=eq.{day}&limit=100')
        have = {int(r['race_no']): (r.get('meta') or {}).get('runners') for r in have}
    except Exception:  # noqa: BLE001
        have = {}
    rows = [r for r in rows if have.get(r['race_no']) != r['meta']['runners']]
    if not rows:
        log('前の回と同じ = 書かない'); return 0
    sys.path.insert(0, str(HERE.parent))
    import base_v1 as B1
    B1.MODEL_ID = MODEL_ID  # ⛔write_marks が見る先をここで差し替える(v3n_daily と同じ作法)
    B1.write_marks(rows, day, 'last')
    return 0


def morning(day, mdir, write=False):
    """朝: 当日の行を取り直し、体重と 1R の水分・天候を朝に分かる値で埋めて当て、全レースを timing='morning' で書く(凍結)。"""
    get_inputs(day, refresh_today_only=True)
    orig = f1.load
    f1.load = lambda: morning_frames(orig(), day)
    try:
        out, info = score(day, mdir)
    finally:
        f1.load = orig
    if out is None:
        return 2
    rows, _ = rows_of(out, info, day, need_bw=False, timing='morning')
    for r in rows:
        print(f"朝 帯広ば{r['race_no']}R " + ' '.join(f"{m['mark']}{m['num']}({m['score']})" for m in r['marks']), flush=True)
    log('朝 書ける', len(rows), 'R')
    Path(mdir, f'banei3_morning_{day}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    if not write or not rows:
        return 0
    sys.path.insert(0, str(HERE.parent))
    import base_v1 as B1
    B1.MODEL_ID = MODEL_ID  # ⛔write_marks が見る先をここで差し替える(朝 = 既にある行は触らない)
    B1.write_marks(rows, day, 'morning')
    return 0


def selftest(day):
    """手元: 分けた fit → score が、研究の run(v3 の banei_kb/prod/run_DAY.parquet)と同じ値か。外した分の初期値は研究と同じ(固めた表だけ)。"""
    mdir = Path(OUTD) / f'selftest_{day}'
    if fit(day, mdir, use_db=False, use_gap=False):
        return 1
    out, _ = score(day, mdir)
    ref = pd.read_parquet(OUTD + f'run_{day}.parquet')
    ref['race_date'] = ref.race_date.astype(str)
    x = out.merge(ref, on=K, suffixes=('', '_ref'))
    r = dict(day=day, rows=len(out), ref=len(ref), joined=len(x), **{f'{c}_maxdiff': float((x[c] - x[c + '_ref']).abs().max())
                                                                         for c in ('p_v2', 'flat', 'res', 'p', 'p3', 'p1')},
             fav_same=float(x.groupby('rkey').apply(lambda g: g.p3.idxmax() == g.p3_ref.idxmax()).mean()))
    log('照合', r)
    Path(OUTD, f'selftest_{day}.json').write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0


def fill(to_day):
    """手元で 1 回: 固めた表に GAP_FROM 〜 to_day を月ごとの第 2 版の木で足す(前の版は v2_oof_to2608.parquet に残す)。"""
    D1, D2, ru = tables(None)
    nxt = str((pd.Timestamp(to_day) + pd.Timedelta(days=1)).date())
    o = frozen_oof()
    g = gap_oof(D2, o, nxt)
    if not os.path.exists(OUTD + 'v2_oof_to2608.parquet'):
        os.replace(OUTD + 'v2_oof.parquet', OUTD + 'v2_oof_to2608.parquet')
    n = pd.concat([o, g], ignore_index=True).drop_duplicates(K, keep='first')
    n.to_parquet(OUTD + 'v2_oof.parquet', index=False)
    log('固めた初期値', len(o), '→', len(n), '最後の日', n.race_date.max(), '足した日', sorted(g.race_date.unique()))


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'fill':
        fill(a[1])
    elif a[0] == 'fit':
        sys.exit(fit(a[1], a[2]))
    elif a[0] == 'predict':
        dr = int(a[a.index('--drop-race') + 1]) if '--drop-race' in a else None
        sys.exit(predict(a[1], a[2], '--write' in a, dr, '--no-going' in a))
    elif a[0] == 'morning':
        sys.exit(morning(a[1], a[2], '--write' in a))
    elif a[0] == 'selftest':
        sys.exit(selftest(a[1]))
