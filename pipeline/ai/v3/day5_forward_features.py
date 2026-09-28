# -*- coding: utf-8 -*-
"""5 日目(PREREG2 §7-6・承認 2026-09-25): 前向きの材料だけを出す台本。5 日目に sha256 で固定する。

  py -3.12 -X utf8 src/day5_forward_features.py fetch   # DB から 2026-09-01 以降の走り・レース・facts(全 NAR 場)と南関の払戻を写す
  py -3.12 -X utf8 src/day5_forward_features.py         # 前向きの材料 → v3/feat_forward.parquet
  py -3.12 -X utf8 src/day5_forward_features.py leak    # 前向きの抜き取り 5 日でリーク検査(§8 と同じ比べ方)→ out/day5_forward_leak.md

- 確認・封印の写し(§10 の 8 ファイル)を読んでよいのはこの台本だけ(§7-6)。返す・保存する・表示するのは
  race_date ≥ 2026-09-01 の行だけ(見張り: guard)。途中の表・集計・確認や封印の期間の p は出さない。
- 材料の作り方は day2_features.py の build をそのまま使う(段 1〜4 の定義・窓・切り方は同じ)。
- 走歴 = RAW(< 2022-01-01、load_archive の見張り付き)+ 確認・封印の写し + 前向きの写し(≥ 2026-09-01)。
  列は RAW の列に合わせ、数値の列は数値にする。
- 騎手・調教師の A/E₃ の元(ae_src)= 探索は day2_features.targets() と同じ。2022-01 以降は、南関の取消・除外でない
  出走馬の全頭に q 表(確認 = q_confirm+q_confirm_rakuten2023、封印 = q_sealed、前向き = q_forward)の
  win・plc_lo(>0)・plc_hi があり、複勝の払戻があるレース。E_mid・Y3・K の式は §2 と同じ(確定の plc)。
- 前向きの対象 = 南関 4 場・race_date ≥ 2026-09-01 の取消・除外でない出走馬の全頭(オッズの有無で絞らない。
  数える馬・買い候補の絞りは点数づけの側で E_mid(T) を使って行う)。E_mid・Y3 は確定の値が揃うレースだけ入れ、
  無ければ欠損(A/E₃ の分母と結果にだけ使う)。
- この台本を決めたのは前向きの結果を見る前(2026-09-26)。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from day2_db_copy import NANKAN, SPEC, req, tracks  # noqa: E402
from day2_features import ENTRY_COLS, KEY, RACE_COLS, build, targets  # noqa: E402
from load_outcomes import load_archive  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
FWD = '2026-09-01'
PARTS = {'confirm': '2022-01_2025-08', 'sealed': '2025-09_2026-08'}
Q = {'confirm': ['q_confirm', 'q_confirm_rakuten2023'], 'sealed': ['q_sealed'], 'forward': ['q_forward']}


def guard(df, name):
    bad = int((df.race_date.astype(str) < FWD).sum())
    if bad:
        raise SystemExit(f'⛔{name} に {FWD} より前が {bad} 行。前向きの行だけを返す')
    return df


# ---------- 前向きの写し ----------
def fetch():
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    for kind in ('runs', 'races', 'facts', 'payouts'):
        table, key = SPEC[kind]
        rows = []
        for t in (NANKAN if kind == 'payouts' else tracks()):
            off = 0
            while True:
                got = req(table, [('select', '*'), ('track', f'eq.{t}'), ('race_date', f'gte.{FWD}'),
                                  ('race_date', f'lte.{today}'), ('order', ','.join(key)),
                                  ('limit', '1000'), ('offset', str(off))])
                rows += got
                if len(got) < 1000:
                    break
                off += 1000
        df = pd.DataFrame(rows)
        for c in df.columns:
            if df[c].map(lambda v: isinstance(v, (dict, list))).any():
                df[c] = df[c].map(lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True) if v is not None else None)
        df = guard(df.sort_values(key, kind='mergesort').reset_index(drop=True), kind)
        assert not df.duplicated(key).any(), (kind, 'key dup')
        df.to_parquet(V3 / f'db_{kind}_forward.parquet', index=False)
        print(kind, 'rows', len(df), 'races', df[KEY].drop_duplicates().shape[0], 'max', df.race_date.max(), flush=True)


# ---------- 走歴 ----------
def _align(d, ref):
    d = d[[c for c in ref.columns if c in d.columns]].copy()
    for c in d.columns:
        if pd.api.types.is_numeric_dtype(ref[c]) and not pd.api.types.is_numeric_dtype(d[c]):
            d[c] = pd.to_numeric(d[c], errors='coerce')
    d['race_date'] = d.race_date.astype(str)
    return d


def load_all(name):
    a = load_archive(name)
    parts = [pd.read_parquet(V3 / f'db_{name}_{p}_{s}.parquet') for p, s in PARTS.items()]
    parts.append(pd.read_parquet(V3 / f'db_{name}_forward.parquet'))
    d = pd.concat([a] + [_align(p, a) for p in parts], ignore_index=True)
    d['race_no'] = d.race_no.astype(int)
    return d


def sources():
    runs, facts, races = load_all('runs'), load_all('facts'), load_all('races')
    runs = runs.rename(columns={'runner_number': 'umaban'})
    runs['umaban'] = runs.umaban.astype(int)
    facts['umaban'] = facts.umaban.astype(int)
    f = facts[KEY + ['umaban', 'horse_key', 'last3f', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']].rename(columns={'last3f': 'f_l3'})
    h = runs.merge(f, on=KEY + ['umaban'], how='left').merge(races[KEY + RACE_COLS], on=KEY, how='left')
    h['hid'] = h.horse_key.fillna(h.horse_name)
    return h


# ---------- 対象と A/E の元 ----------
def places():
    pay = pd.concat([pd.read_parquet(V3 / 'db_payouts_confirm_2022.parquet'),
                     pd.read_parquet(V3 / f"db_payouts_confirm_2022-11_2025-08.parquet"),
                     pd.read_parquet(V3 / f"db_payouts_sealed_2025-09_2026-08.parquet"),
                     pd.read_parquet(V3 / 'db_payouts_forward.parquet')], ignore_index=True)
    pay = pay.assign(race_date=pay.race_date.astype(str), race_no=pay.race_no.astype(int)).drop_duplicates(KEY, keep='last')
    out = {}
    for t, dt, r, js in pay[KEY + ['payouts']].itertuples(index=False):
        if js is None:
            continue
        s = {int(x['c']) for x in json.loads(js) if x.get('t') == 'place'}
        if s:
            out[(t, dt, r)] = s
    return out


def frame_later(h, place, part):
    """2022-01 以降の南関の出走馬(取消・除外でない)に q・E_mid・Y3・K を付ける。ok = §2 の対象レース。"""
    lo, hi = {'confirm': ('2022-01-01', '2025-09-01'), 'sealed': ('2025-09-01', FWD), 'forward': (FWD, '9999')}[part]
    r = h[h.track.isin(NANKAN) & (h.race_date >= lo) & (h.race_date < hi) & ~h.finish_note.isin(['取消', '除外'])]
    df = r[KEY + ['umaban']].copy()
    q = pd.concat([pd.read_parquet(V3 / f'{n}.parquet') for n in Q[part]])[KEY + ['umaban', 'win', 'plc_lo', 'plc_hi']]
    q = q.assign(race_date=q.race_date.astype(str), race_no=q.race_no.astype(int), umaban=q.umaban.astype(int))
    df = df.merge(q.drop_duplicates(KEY + ['umaban']), on=KEY + ['umaban'], how='left')
    g = df.groupby(KEY)
    ok = (g.win.transform(lambda s: s.notna().all()) & g.plc_lo.transform(lambda s: s.notna().all() and (s > 0).all())
          & g.plc_hi.transform(lambda s: s.notna().all())).astype(bool)
    ok &= pd.Series([(t, d, n) in place for t, d, n in df[KEY].itertuples(index=False)], index=df.index)
    df['n'] = g.umaban.transform('size')
    df['K'] = np.where(df.n >= 8, 3, 2)
    iw = 1 / df.win
    df['q'] = np.where(ok, iw / iw.groupby([df[k] for k in KEY]).transform('sum'), np.nan)
    e = 1 / ((df.plc_lo + df.plc_hi) / 2)
    df['E_mid'] = np.where(ok, e / e.groupby([df[k] for k in KEY]).transform('sum') * df.K, np.nan)
    df['Y3'] = [float(u in place[(t, d, n)]) if o else np.nan
                for t, d, n, u, o in zip(df.track, df.race_date, df.race_no, df.umaban, ok)]
    df['year'] = df.race_date.str[:4].astype(int)
    df['meet'] = np.nan
    return df.reset_index(drop=True), ok.to_numpy()


def inputs():
    h = sources()
    place = places()
    ae = [targets()]
    for part in ('confirm', 'sealed', 'forward'):
        df, ok = frame_later(h, place, part)
        ae.append(df[ok])
        if part == 'forward':
            fwd = df
    ae = pd.concat(ae, ignore_index=True)[KEY + ['umaban', 'E_mid', 'Y3']]
    return h, fwd, ae


def main():
    h, fwd, ae = inputs()
    X, coef = build(h, guard(fwd, 'forward targets'), ae)
    X = guard(X, 'features')
    X.to_parquet(V3 / 'feat_forward.parquet', index=False)
    feats = [c for c in X.columns if c[:2] in ('s1', 's2', 's3', 's4')]
    print('rows', len(X), 'races', X[KEY].drop_duplicates().shape[0], 'dates', X.race_date.min(), '〜', X.race_date.max(),
          'E_mid あり', int(X.E_mid.notna().sum()), 'coef', round(coef, 5))
    print('missing', X[feats].isna().mean().round(3).to_dict())


def leak():
    """§8 と同じ: 前向きの抜き取り 5 日(seed 0)。当日以降の行を消し(当日は出走表の列だけ)作り直して比べる。"""
    h, fwd, ae = inputs()
    full = pd.read_parquet(V3 / 'feat_forward.parquet')
    feats = [c for c in full.columns if c[:2] in ('s1', 's2', 's3', 's4')]
    days = np.sort(np.random.default_rng(0).choice(np.sort(fwd.race_date.unique()), 5, replace=False))
    L = ['# 5 日目: 前向きの材料のリーク検査(PREREG2 §8 と同じ比べ方)', '',
         f'比べる材料 {len(feats)} 列。一致 = 両方欠損、または差の絶対値 ≤ 1e-9。', '',
         '| 日 | 頭 | 一致したセル | 全セル | 一致 % |', '|---|---|---|---|---|']
    tot = [0, 0]
    for d in days:
        ent = h.loc[h.race_date == d, KEY + ['umaban', 'hid'] + ENTRY_COLS + RACE_COLS]
        Xd, _ = build(h[h.race_date < d], fwd[fwd.race_date == d].reset_index(drop=True), ae[ae.race_date < d], ent=ent)
        a = full[full.race_date == d].set_index(KEY + ['umaban'])[feats].sort_index()
        b = Xd.set_index(KEY + ['umaban'])[feats].sort_index()
        assert a.index.equals(b.index), d
        A, Bv = a.to_numpy(float), b.to_numpy(float)
        eq = (np.isnan(A) & np.isnan(Bv)) | (np.abs(A - Bv) <= 1e-9)
        tot[0] += int(eq.sum()); tot[1] += eq.size
        bad = [f for f, k in zip(feats, eq.all(0)) if not k]
        L.append(f'| {d} | {len(a)} | {int(eq.sum()):,} | {eq.size:,} | {100 * eq.mean():.2f}' + (f'(違う列: {"・".join(bad)})' if bad else '') + ' |')
        print(L[-1], flush=True)
    L += ['', f'計: {tot[0]:,} / {tot[1]:,} = {100 * tot[0] / tot[1]:.2f} %']
    (REPO / 'out/day5_forward_leak.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print(L[-1])


if __name__ == '__main__':
    {'fetch': fetch, 'leak': leak}.get((sys.argv[1:] or [''])[0], main)()
