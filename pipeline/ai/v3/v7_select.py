# -*- coding: utf-8 -*-
"""第 7 版 A: 材料の足し引きを自動で回す(DESIGN §12・§12 F の守り)。2022-01-01 以降の行は読まない。

  py -3.12 -X utf8 src/v7_select.py select   # 2016〜19 の当てはめ外で群ごとに足す → 抜く(2020〜21 は見ない)
  py -3.12 -X utf8 src/v7_select.py final    # 決めた形で 2016〜21 を当てはめ外で出し、2020〜21 を 1 回だけ見る

■ 決め(見る前に書いた)
  1. 土台 = 第 6 版の前日の列(v3/t6_grid.json の kept)。新しい列 = feat_v7a・feat_v7b の a7_・b7_ で始まる列(d7_ = 当日は前日版に入れない)。
  2. 群 = 新しい列は番号の頭の文字(A〜O)と self。土台の列は頭の文字(a・b・k・c・f・h・i・d・e・g・j・l・p・x・r)と
     対戦の網(g_eps・g_eps_rank・h2h・elo_z・nori)。
  3. 物差し = 3 着以内の模型(Y3・設定 15/500/800)の対数尤度の和。当てはめ外 = 2016〜19 の年ごと(前の年すべてで学ぶ)。
  4. 採る線 = 和の伸び > 2 × 標準誤差(レースごとの差から)かつ 4 年中 3 年以上で伸びる。
     足す: 通った群のうち伸びの一番大きい群を足し、残りでやり直す(通る群が無くなるまで)。
     抜く: 足し終えた形から群を 1 つずつ抜き、抜いて伸びる群(同じ線)を一番大きい順に 1 つずつ抜く(無くなるまで)。
  5. 保存ファイル名に列の一覧の md5 を入れる(古い予想を黙って読まない)。
"""
import hashlib
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_day3  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
KEY = ['track', 'race_date', 'race_no']
CACHE = V3 / 'v7_cache'
SEL_Y, CHK_Y = [2016, 2017, 2018, 2019], [2020, 2021]
CFG = (15, 500, 800)
NET = ['g_eps', 'g_eps_rank', 'h2h', 'elo_z', 'nori']
STATE = V3 / 'v7_select.json'
LOG = REPO / 'out' / 'v7_select.md'


def load():
    d = pd.read_parquet(V3 / 'feat_t6_explore.parquet')
    for f in ('feat_v7a_explore.parquet', 'feat_v7b_explore.parquet'):
        if (V3 / f).exists():
            x = pd.read_parquet(V3 / f)
            x['race_no'] = x.race_no.astype(int)
            new = [c for c in x.columns if c[:3] in ('a7_', 'b7_', 'd7_')]
            d = d.merge(x[KEY + ['umaban'] + new], on=KEY + ['umaban'], how='left', validate='1:1')
    d = d.sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    assert d.race_date.max() < '2022-01-01'
    d['z1'], d['z3'] = t4_day3.logit(1 / d.n), t4_day3.logit(3 / d.n)
    d['rid'] = d.groupby(KEY, sort=False).ngroup()
    return d


def groups_of(d, base):
    G = {}
    for c in base:
        G.setdefault('網' if c in NET else '土台_' + c.split('_')[0], []).append(c)
    for c in d.columns:
        if c[:3] in ('a7_', 'b7_'):
            code = c.split('_')[1]
            G.setdefault('新_' + ('self' if code == 'self' else code[0]), []).append(c)
    return G


def fit(d, cols, target='Y3', years=SEL_Y, cfg=CFG):
    CACHE.mkdir(exist_ok=True)
    assert not t4_day3.BANNED & set(cols) and len(cols) == len(set(cols))
    h = hashlib.md5('|'.join(cols).encode()).hexdigest()[:12]
    out = []
    for y in years:
        fp = CACHE / f'{target}_{cfg[0]}_{cfg[1]}_{cfg[2]}_{y}_{h}.npy'
        if fp.exists():
            out.append(np.load(fp)); continue
        tr, te = d[d.year < y], d[d.year == y]
        z = 'z1' if target == 'Y1' else 'z3'
        prm = dict(t4_day3.BASE, num_leaves=cfg[0], min_data_in_leaf=cfg[1])
        m = lgb.train(prm, lgb.Dataset(tr[cols].astype(float), label=tr[target].to_numpy(float),
                                       init_score=tr[z].to_numpy()), num_boost_round=cfg[2])
        p = t4_day3.sig(te[z].to_numpy() + m.predict(te[cols].astype(float), raw_score=True))
        np.save(fp, p)
        out.append(p)
    return np.concatenate(out)


def race_ll(d, p, years=SEL_Y, y='Y3'):
    te = d[d.year.isin(years)]
    p = np.clip(p, 1e-6, 1 - 1e-6)
    v = te[y].to_numpy() * np.log(p) + (1 - te[y].to_numpy()) * np.log(1 - p)
    return pd.Series(v).groupby([te.rid.to_numpy(), te.year.to_numpy()]).sum()


def judge(a, b):
    """a = 前・b = 後のレースごとの対数尤度。伸び・標準誤差・年ごとの伸び・通ったか。"""
    x = b - a
    tot, se = float(x.sum()), float(x.std() * np.sqrt(len(x)))
    per = x.groupby(level=1).sum()
    ok = tot > 2 * se and int((per > 0).sum()) >= 3
    return dict(gain=round(tot, 2), se=round(se, 2), years=[round(v, 2) for v in per], ok=bool(ok))


def log(s):
    print(s, flush=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(s + '\n')


def select():
    d = load()
    base = json.loads((V3 / 't6_grid.json').read_text(encoding='utf-8'))['kept']
    G = groups_of(d, base)
    LOG.write_text('# 第 7 版 A: 材料の足し引き(2016〜19 の当てはめ外・3 着以内の対数尤度の和)\n\n', encoding='utf-8')
    log(f'- 群 {len(G)}(土台 {sum(k.startswith("土台") or k == "網" for k in G)}・新 {sum(k.startswith("新") for k in G)})・'
        f'新しい列 {sum(len(v) for k, v in G.items() if k.startswith("新"))}')
    cur = [g for g in G if not g.startswith('新')]
    cols = lambda gs: [c for g in gs for c in G[g]]
    ll_cur = race_ll(d, fit(d, cols(cur)))
    log(f'- 土台(第 6 版の前日の列 {len(cols(cur))})の和 {ll_cur.sum():.1f}\n\n## 足す\n')
    while True:
        res = {}
        for g in [g for g in G if g not in cur]:
            res[g] = judge(ll_cur, race_ll(d, fit(d, cols(cur + [g]))))
            log(f'- {g}({len(G[g])} 列): {res[g]}')
        good = {g: r for g, r in res.items() if r['ok']}
        if not good:
            break
        g = max(good, key=lambda k: good[k]['gain'])
        cur.append(g)
        ll_cur = race_ll(d, fit(d, cols(cur)))
        log(f'\n**足した: {g}** → 和 {ll_cur.sum():.1f}\n')
    log('\n## 抜く\n')
    while True:
        res = {}
        for g in cur:
            res[g] = judge(ll_cur, race_ll(d, fit(d, cols([x for x in cur if x != g]))))
            log(f'- {g} を抜く: {res[g]}')
        good = {g: r for g, r in res.items() if r['ok']}
        if not good:
            break
        g = max(good, key=lambda k: good[k]['gain'])
        cur.remove(g)
        ll_cur = race_ll(d, fit(d, cols(cur)))
        log(f'\n**抜いた: {g}** → 和 {ll_cur.sum():.1f}\n')
    STATE.write_text(json.dumps({'groups': cur, 'cols': cols(cur)}, ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'\n## 決まった形: 群 {len(cur)}・列 {len(cols(cur))}\n\n{cur}')


def final():
    """決めた形と第 6 版の土台を、同じ手順(設定は第 6 版の格子 Y1 31/500/400・Y3 15/100/1200)で 2016〜21 の当てはめ外に出す。
    ◎ = p3′ の大きい順 → p1 → 馬番。2020〜21 はここで初めて見る(1 回だけ)。"""
    import t6_base
    d = load()
    st = json.loads(STATE.read_text(encoding='utf-8'))
    base = json.loads((V3 / 't6_grid.json').read_text(encoding='utf-8'))['kept']
    ys = SEL_Y + CHK_Y
    te = d[d.year.isin(ys)].copy()
    out = te[KEY + ['umaban', 'year', 'n', 'Y1', 'Y3', 'pop']].copy()
    res = {}
    for tag, cols in (('v6re', base), ('v7pre', st['cols'])):
        r1 = fit(d, cols, 'Y1', ys, (31, 500, 400))
        r3 = fit(d, cols, 'Y3', ys, (15, 100, 1200))
        p1 = r1 / pd.Series(r1, index=te.index).groupby([te[k] for k in KEY]).transform('sum').to_numpy()
        out[f'{tag}_p1'], out[f'{tag}_p3'] = p1, np.maximum(r3, p1)
        out[f'{tag}_p3p'] = t6_base.p3prime(out, f'{tag}_p3')[0]
        top = out.sort_values(KEY + [f'{tag}_p3p', f'{tag}_p1', 'umaban'], ascending=[True] * 3 + [False, False, True],
                              kind='mergesort').groupby(KEY, sort=False).head(1)
        q = out[f'{tag}_p3p'].clip(1e-6, 1 - 1e-6)
        ll = (out.Y3 * np.log(q) + (1 - out.Y3) * np.log(1 - q)).groupby([out[k] for k in KEY]).sum()
        yr = out.groupby(KEY).year.first()
        res[tag] = {part: dict(top3=round(100 * top[top.year.isin(yy)].Y3.mean(), 2),
                               LL3=round(float(ll[yr.isin(yy)].mean()), 4), races=int(yr.isin(yy).sum()))
                    for part, yy in (('2016〜19', SEL_Y), ('2020〜21', CHK_Y))}
    fav = out[out['pop'] == 1]
    res['1番人気'] = {part: dict(top3=round(100 * fav[fav.year.isin(yy)].Y3.mean(), 2)) for part, yy in
                     (('2016〜19', SEL_Y), ('2020〜21', CHK_Y))}
    out.to_parquet(V3 / 'v7_final_preds.parquet', index=False)
    (V3 / 'v7_final.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    L = ['# 第 7 版 A: 決めた形の当てはめ外(前日版・作る期間)', '', f'- 列 {len(st["cols"])}(第 6 版 {len(base)})', '',
         '| 版 | 期間 | ◎ 3 着以内 % | 3 着以内の対数尤度/レース | レース |', '|---|---|---|---|---|']
    for tag in ('v6re', 'v7pre'):
        for part, v in res[tag].items():
            L.append(f'| {tag} | {part} | {v["top3"]} | {v["LL3"]} | {v["races"]} |')
    for part, v in res['1番人気'].items():
        L.append(f'| 1 番人気 | {part} | {v["top3"]} | — | — |')
    (REPO / 'out' / 'v7_final.md').write_text(chr(10).join(L) + chr(10), encoding='utf-8')
    print(chr(10).join(L))


if __name__ == '__main__':
    {'select': select, 'final': final}[sys.argv[1]]()
