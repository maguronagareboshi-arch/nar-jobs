# -*- coding: utf-8 -*-
"""第 3 版 4 日目(判断の日)の台本(PREREG3 §1・§6・§8)。3 日目に sha256 で固定する。値を見て形・設定・材料は変えない。

  py -3.12 -X utf8 src/t3_open.py dry       # 3 日目の通し試験: 探索の写しだけで 2021 を作り直し、2 日目の材料と 100% 一致・旧 AI の比べ方の自己一致
  py -3.12 -X utf8 src/t3_open.py confirm   # 4 日目 ①: 確認(2022-01〜2025-08)を 1 回だけ開ける → out/t3_day4_confirm.md
  py -3.12 -X utf8 src/t3_open.py retrain   # 4 日目 ②: 2015〜2025-08 で両版を学び直す(2 回の一致)→ models/t3d4_*.txt
  py -3.12 -X utf8 src/t3_open.py sealed    # 4 日目 ③: 封印(2025-09〜2026-08)を 1 回だけ開け、旧 AI と比べる → out/t3_day4_sealed.md

- 順序は ①→②→③ だけ(前の段の出力が無ければ止まる)。confirm と sealed は開ける前に verify_hashes を流し、NG なら止まる。
- 走歴 = RAW(< 2022-01-01、load_archive の見張り付き)+ DB の写し。confirm は確認の写しだけ、sealed は確認と封印の写しだけを読む
  (前向きの写し db_*_forward_t3 は予想表の台本 t3_forecast.py だけが読む)。読み込んだ走歴の最後の日が区間の終わり以上なら止まる(見張り)。
- 材料は t3_day2_features の targets3・finish_table と day2_features の build をそのまま使う(2 日目と同じ作り方)。
  予想するレースと Y1・Y3 は着順から(PREREG3 §2)。途中の表(欠損率・分布)は出さない。
- 確認の予想 = 3 日目の模型(models/t3_*、2015〜2021 で学習)。封印の予想 = 学び直した模型(models/t3d4_*、2015〜2025-08)。
- 学び直しの材料 = 2 日目の材料の表(2015〜2021)+ confirm が保存した確認の材料の表(v3/feat_t3_confirm.parquet)。
- バグ直し(4 日目・開ける前): DB は途中から「出走取消・競走除外・競走中止」「名前|生年月日」と書くようになっていた
  (前向きの写しで確認。2021 年までの DB と RAW は「取消・除外・中止」「名前|生年」)。sources で RAW の書き方にそろえ、
  見張り(知らない書き方・鍵の形・2022 年以降の鍵の欠け・区間の最初の月の走歴のつながり)を足した。通ったときは数字を出さない。
- 旧 AI との比べ方・物差し・区間・判定は t3_eval.py(§6)。合格 = 前日版と当日版のどちらも、b_all と b_nankan の両方で「上回った」。
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from day2_features import KEY, NANKAN, RACE_COLS, build  # noqa: E402
from day5_forward_features import _align  # noqa: E402
from load_outcomes import load_archive  # noqa: E402
from t3_day2_features import finish_table, targets3  # noqa: E402
from t3_eval import (OLD, V3, VERSIONS, VNAME, breakdown, check_grid, compare_old, fmt, load_old, predict,  # noqa: E402
                     race_table, summary, train)

import lightgbm as lgb  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MD = Path(__import__('os').environ.get('V3_MODELS', 'C:/Users/kouki/OneDrive/デスクトップ/nankan-ai-v3/models'))
FILES = {'confirm': '2022-01_2025-08', 'sealed': '2025-09_2026-08', 'forward': 't3'}
SPAN = {'dry': ('2021-01-01', '2022-01-01', []), 'confirm': ('2022-01-01', '2025-09-01', ['confirm']),
        'sealed': ('2025-09-01', '2026-09-01', ['confirm', 'sealed']),
        'forward': ('2026-09-01', '9999-12-31', ['confirm', 'sealed', 'forward'])}  # 予想表(t3_forecast.py)だけが使う
# DB は途中から書き方が変わった(4 日目・開ける前に前向きの写しで確認): 取消などの書き方と、馬の鍵の「名前|生年月日」。RAW と
# 2021 年までの DB は「取消・除外・中止」「名前|生年」。どちらの書き方でも RAW にそろえる(RAW には何も起きない)。
NOTE = {'出走取消': '取消', '競走除外': '除外', '競走中止': '中止'}
NOTES = {'取消', '除外', '中止', '失格', '降着'}  # 失格・降着は走った馬(2 日目と同じ扱い)
OLD_MONTHS = [f'{y}-{m:02d}' for y, m in [(2025, 9), (2025, 10), (2025, 11), (2025, 12)] + [(2026, k) for k in range(1, 9)]]


def verify():
    r = subprocess.run([sys.executable, '-X', 'utf8', str(REPO / 'src/verify_hashes.py')], capture_output=True, text=True,
                       encoding='utf-8')
    last = r.stdout.strip().splitlines()[-1]
    print('verify_hashes:', last, flush=True)
    if r.returncode:
        raise SystemExit('⛔ verify_hashes が NG。開けない')


def sources(part):
    lo, hi, parts = SPAN[part]
    out = {}
    for name in ('runs', 'facts', 'races'):
        a = load_archive(name)
        d = pd.concat([a] + [_align(pd.read_parquet(V3 / f'db_{name}_{p}_{FILES[p]}.parquet'), a) for p in parts],
                      ignore_index=True)
        d['race_no'] = d.race_no.astype(int)
        if d.race_date.max() >= hi:
            raise SystemExit(f'⛔ {name} に {hi} 以降の行がある')
        out[name] = d
    runs = out['runs'].rename(columns={'runner_number': 'umaban'})
    runs['umaban'] = runs.umaban.astype(int)
    runs['finish_note'] = runs.finish_note.replace(NOTE)
    bad = sorted(set(runs.finish_note.dropna().unique()) - NOTES)
    if bad:
        raise SystemExit(f'⛔ 知らない finish_note の書き方: {bad}')
    facts = out['facts']
    facts['umaban'] = facts.umaban.astype(int)
    facts['horse_key'] = facts.horse_key.str.replace(r'\|(\d{4})-\d\d-\d\d$', r'|\1', regex=True)
    nb = int((~facts.horse_key.dropna().str.contains(r'\|\d{4}$')).sum())
    if nb:
        raise SystemExit(f'⛔ 「名前|生年」でない馬の鍵が {nb} 行')
    f = facts[KEY + ['umaban', 'horse_key', 'last3f', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']].rename(columns={'last3f': 'f_l3'})
    h = runs.merge(f, on=KEY + ['umaban'], how='left').merge(out['races'][KEY + RACE_COLS], on=KEY, how='left')
    h['hid'] = h.horse_key.fillna(h.horse_name)
    later = h[h.track.isin(NANKAN) & (h.race_date >= '2022-01-01')]
    if len(later) and later.horse_key.isna().mean() > 0.01:
        raise SystemExit('⛔ 2022 年以降の南関の走りで馬の鍵が無い行が 1% を超える')
    return h


def link_guard(h, lo):
    """見張り(結果の値は使わない・通ったときは数字を出さない): 区間の最初の 31 日の南関の出走馬のうち、それより前に走歴が
    無い馬の割合が、2021-12(RAW)の同じ割合より 0.10 以上多ければ止める(RAW と DB で馬がつながっているか)。"""
    hh = h[~h.finish_note.isin(['取消', '除外'])][['hid', 'race_date', 'track']]
    first = hh.groupby('hid').race_date.min()

    def share(a):
        b = (pd.Timestamp(a) + pd.Timedelta(days=31)).strftime('%Y-%m-%d')
        r = hh[hh.track.isin(NANKAN) & (hh.race_date >= a) & (hh.race_date < b)]
        return float((r.hid.map(first) >= a).mean())

    if share(lo) > share('2021-12-01') + 0.10:
        raise SystemExit('⛔ 区間の最初の月に走歴のつながらない馬が多すぎる(馬の鍵の書き方を確かめる)')
    print('見張り OK(書き方・馬の鍵・走歴のつながり)', flush=True)


def features(part):
    lo, hi, _ = SPAN[part]
    h = sources(part)
    link_guard(h, lo)
    tg = targets3(h)
    X, _ = build(h, tg[(tg.race_date >= lo) & (tg.race_date < hi)].reset_index(drop=True), tg)
    X = finish_table(X, h, tg)
    assert X.race_date.min() >= lo and X.race_date.max() < hi
    return X.sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)


def models(prefix):
    def one(fp):  # 日本語を含むパスは LightGBM が開けないので文字列で渡す
        return lgb.Booster(model_str=fp.read_text(encoding='utf-8'))
    return {v: (one(MD / f'{prefix}_{v}_Y1.txt'), one(MD / f'{prefix}_{v}_Y3.txt')) for v in VERSIONS}


def report(X, M, title):
    L = [f'# {title}', '', f"{X[KEY].drop_duplicates().shape[0]:,} R・{len(X):,} 頭。区間 = 開催日単位のブートストラップ 2,000 回の 95%。", '',
         '| 版 | ◎ の勝率 | ◎ の 3 着以内率 | 勝ちの対数尤度(レースあたり)| 3 着以内の対数尤度 | Σp3 − 3(平均)|', '|---|---|---|---|---|---|']
    P, Rs = {}, {}
    for v, cols in VERSIONS.items():
        x = predict(*M[v], X, cols)
        R = race_table(x)
        s = summary(R)
        P[v], Rs[v] = x, R
        L.append(f"| {VNAME[v]} | {fmt(s['win'])} | {fmt(s['top3'])} | {fmt(s['ll1'])} | {fmt(s['ll3'])} | "
                 f"{(x.groupby(KEY).p3.sum() - 3).mean():+.3f} |")
    L += [f"| 頭数だけ(段 0)| ― | ― | {s['base_ll1']:.3f} | {s['base_ll3']:.3f} | ― |",
          f"| 1 番人気(比べる相手だけ・{s['fav_races']:,} R)| {fmt(s['fav_win'])} | {fmt(s['fav_top3'])} | ― | ― | ― |", '',
          '## 区分ごと(点だけ・記録)', '', '| 区分 | 値 | レース | 前日版 ◎ 3 着以内率 | 当日版 ◎ 3 着以内率 | 1 番人気 3 着以内率 |',
          '|---|---|---|---|---|---|']
    for (_, a), (_, c) in zip(breakdown(Rs['pre']).iterrows(), breakdown(Rs['day']).iterrows()):
        L.append(f"| {a['区分']} | {a['値']} | {a['レース']:,} | {a['◎ 3 着以内率']:.3f} | {c['◎ 3 着以内率']:.3f} | {a['1 番人気 3 着以内率']:.3f} |")
    return L, P


def judge(P, old):
    L = ['', '## 旧 AI との比べ方(PREREG3 §6・同じレースの対・新 − 旧)', '',
         '| 版 | 旧 AI | レース | 新 ◎ 3 着以内率 | 旧 ◎ 3 着以内率 | 差(95% 区間)| 判定 | ◎ 勝率の差 | 対数尤度の差 Y1 | Y3 | 新 − 1 番人気(3 着以内率)|',
         '|---|---|---|---|---|---|---|---|---|---|---|']
    verdicts = []
    for v in VERSIONS:
        r = compare_old(P[v], old)
        for o in OLD:
            b = r[o]
            verdicts.append(b['verdict'])
            L.append(f"| {VNAME[v]} | {o} | {r['races']:,} | {b['top3'][0]:.3f} | {b['old_top3'][0]:.3f} | {fmt(b['d_top3'])} | "
                     f"**{b['verdict']}** | {fmt(b['d_win'])} | {fmt(b['d_ll1'])} | {fmt(b['d_ll3'])} | {fmt(b['d_fav_top3'])} |")
        L.append(f"(旧 AI のファイルに無い新 AI の出走馬がいたレース: {r['races_lacking_old_rows']})")
    ok = all(x == '上回った' for x in verdicts)
    L += ['', f"**合格の判定: {'合格' if ok else '不合格'}**(4 つの比べ方すべてが「上回った」で合格)",
          '当日版は馬場・馬体重を使い、旧 AI は前日の情報だけ。旧 AI は月ごとに学び直している(旧 AI に有利な条件)。']
    return L, ok


def dry():
    """3 日目の通し試験(探索の期間だけ)。結果の値は物差しの確かめにだけ使い、表は出さない。"""
    check_grid()
    X = features('dry')
    ref = pd.read_parquet(V3 / 'feat_t3_explore.parquet')
    ref = ref[ref.year == 2021].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    assert X[KEY + ['umaban']].equals(ref[KEY + ['umaban']]), '馬の並びが違う'
    assert list(X.columns) == list(ref.columns), '列が違う(学び直しで 2 つの表をつなげない)'
    cols = VERSIONS['day'] + ['n', 'Y1', 'Y3', 'pop']
    A, B = X[cols].to_numpy(float), ref[cols].to_numpy(float)
    eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
    print(f'材料の一致: {int(eq.sum()):,} / {eq.size:,}', flush=True)
    assert eq.all()
    M = models('t3')
    L, P = report(X, M, 'dry')
    # 旧 AI の代わりに、新 AI 自身(b_all)と頭数だけ(b_nankan)を入れて比べ方を確かめる
    fake = P['pre'][KEY + ['umaban', 'n', 'p1', 'p3']].copy()
    fake['b_all_win'], fake['b_all_top3'] = fake.p1, fake.p3
    fake['b_nankan_win'], fake['b_nankan_top3'] = 1 / fake.n, 3 / fake.n
    r = compare_old(P['pre'], fake)
    a, nk = r['b_all'], r['b_nankan']
    print('自己比較: レース', r['races'], '欠け', r['races_lacking_old_rows'], 'd_top3', a['d_top3'], 'd_ll1', a['d_ll1'],
          'd_ll3', a['d_ll3'], a['verdict'], '/ 頭数だけとの比較', nk['verdict'], flush=True)
    assert r['races_lacking_old_rows'] == 0 and all(abs(x) < 1e-12 for k in ('d_top3', 'd_win', 'd_ll1', 'd_ll3') for x in a[k])
    assert a['verdict'] == '差は誤差の範囲' and nk['verdict'] == '上回った'
    part = fake[~((fake.race_no == 1) & (fake.umaban == 1))]  # ファイルに無い馬を作る
    r2 = compare_old(P['pre'], part)
    assert r2['races_lacking_old_rows'] == int(((P['pre'].race_no == 1) & (P['pre'].umaban == 1)).sum())
    x = P['pre'].merge(part[KEY].drop_duplicates(), on=KEY)
    assert r2['races'] == x[KEY].drop_duplicates().shape[0]
    print('欠けのあるレース', r2['races_lacking_old_rows'], 'd_ll1', fmt(r2['b_all']['d_ll1'], 5), flush=True)
    JL, ok = judge(P, fake)
    assert sum(x.startswith(('| 前日版 |', '| 当日版 |')) for x in JL) == 4 and any('合格の判定' in x for x in JL)
    print('dry OK')


def confirm():
    verify()
    check_grid()
    out = REPO / 'out/t3_day4_confirm.md'
    if out.exists():
        raise SystemExit('⛔ 確認は開けてある(1 回だけ)')
    X = features('confirm')
    X.to_parquet(V3 / 'feat_t3_confirm.parquet', index=False)
    L, _ = report(X, models('t3'), '第 3 版 4 日目: 確認(2022-01〜2025-08・3 日目の模型 = 2015〜2021 で学習)')
    out.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


def retrain():
    check_grid()
    assert (REPO / 'out/t3_day4_confirm.md').exists(), '確認を先に開ける'
    a = pd.read_parquet(V3 / 'feat_t3_explore.parquet')
    b = pd.read_parquet(V3 / 'feat_t3_confirm.parquet')
    df = pd.concat([a, b[a.columns]], ignore_index=True)
    df = df.sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)  # 3 日目の fit と同じ並び
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < '2025-09-01'
    assert not df.duplicated(KEY + ['umaban']).any()
    meta = {'train': '2015-01-01〜2025-08-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]), 'files': {}}
    for v, cols in VERSIONS.items():
        for t in ('Y1', 'Y3'):
            s1, s2 = train(df, cols, t).model_to_string(), train(df, cols, t).model_to_string()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {v} {t}')
            fp = MD / f't3d4_{v}_{t}.txt'
            fp.write_text(s1, encoding='utf-8', newline='\n')
            meta['files'][fp.name] = {'cols': cols}
            print(v, t, '一致', flush=True)
    (MD / 't3d4_models.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')


def sealed():
    verify()
    check_grid()
    out = REPO / 'out/t3_day4_sealed.md'
    if out.exists():
        raise SystemExit('⛔ 封印は開けてある(1 回だけ)')
    assert (MD / 't3d4_models.json').exists(), '学び直しを先に'
    X = features('sealed')
    X.to_parquet(V3 / 'feat_t3_sealed.parquet', index=False)  # 5 日目の学び直しに使う
    L, P = report(X, models('t3d4'), '第 3 版 4 日目: 封印(2025-09〜2026-08・学び直した模型 = 2015〜2025-08)')
    JL, ok = judge(P, load_old(OLD_MONTHS))
    L += JL
    out.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    {'dry': dry, 'confirm': confirm, 'retrain': retrain, 'sealed': sealed}[sys.argv[1]]()
