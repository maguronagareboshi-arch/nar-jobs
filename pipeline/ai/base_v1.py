# -*- coding: utf-8 -*-
"""base-v1 予想AI(§129 段階 2/3)。特徴量表 `nar_ai_feat_run`(Actions 内 Postgres で毎朝作る・§129d)から学習し、
今日の出走馬に ◎○▲△ を付けて `nar_ai_marks`(model='base-v1')に書く。

  python pipeline/ai/base_v1.py fit     --feat out/nar_ai_feat_run.csv.gz --model out/base_v1.model.json
  python pipeline/ai/base_v1.py predict --feat out/nar_ai_feat_run.csv.gz --model out/base_v1.model.json [--write] [--date YYYY-MM-DD]

設計(docs/proposal_s129b_base_v1_20260907.md・評価は docs/DESIGN §10 #527):
  - 目的変数= 3 着以内(y_top3)。⛔取消・除外(finish_note あり)は学習に使わない。
  - 模型 2 本の平均= LightGBM 2 値(binary)+ LightGBM 順位学習(lambdarank・1着3/2着2/3着1)。
    ウォークフォワード 12 か月(2025-09〜2026-08・15,423 レース)の実測= ◎3着内率 73.6%・◎単勝回収 84.0%
    (人気 1 番= 76.1% / 81.1%・base-v0 の記録= 56.7% / 60%)。⛔この数字は研究用 research_walkforward.py で再現できる。
  - 基礎力だけ= **人気・オッズは入れない**(市場アンカーは印の並びに使わない= 2026-07-13 の巻き戻しの教訓)。
    前走人気(p*_ninki・prev_ninki)も入れない(入れても 12 か月で差が無かった)。
  - レース内の相対値(J 章)= 主要 28 列について「レース平均との差」と「レース内の順位割合」を足す。
  - 学習の反復回数は固定(ウォークフォワードの早期終了の中央値)= 毎朝の学習で valid を切らない。
  - 凍結= base-v0 と同じ表・同じ鍵(model, track, race_date, race_no, timing)。morning/last とも
    **既にある行は触らない**(この模型は日中に変わる入力を持たないので両方同じ印)。
⛔鍵は印字しない。⛔本番へは REST の upsert だけ(SQL は流さない)。
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))            # pipeline/
from load_nar_official import load_env, upsert  # noqa: E402

MODEL_ID = 'base-v1'
TABLE = 'nar_ai_marks'
CONFLICT = 'model,track,race_date,race_no,timing'
MARKS = ['◎', '○', '▲', '△']
JST = dt.timezone(dt.timedelta(hours=9))

KEY = ['track', 'race_date', 'race_no', 'runner_number', 'horse_key']
LABEL = ['finish', 'finish_note', 'popularity', 'y_top3', 'y_win', 'updated_at']
MARKET = ['prev_ninki', 'p1_ninki', 'p2_ninki', 'p3_ninki', 'p4_ninki', 'p5_ninki']
PL_NULL = ['pl_theta', 'pl_n', 'jk_beta', 'tr_gamma', 'r_plth_pct', 'pl_gap_top', 'jk_beta_delta']
REL = ['avg_rz_3', 'best_rz_5', 'avg_time_z_3', 'avg_time_za_3', 'fukusho_rate_5', 'prize_local_log',
       'kishu_fuku_1y', 'chokyo_fuku_1y', 'dist_fukusho_rate', 'uma_place_fuku', 'avg_l3z_3', 'best_l3z_5',
       'qpts', 'opp_str_now', 'bw_dev', 'futan', 'barei', 'p1_chaku', 'p1_sa', 'avg_chakujun_3',
       'p1_rz', 'p1_tz', 'days_since_prev', 'n_tz_5', 'has_hist', 'prev_best5', 'jc_tier', 'gear_now']
PARAMS = dict(objective='binary', learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
              feature_fraction=0.6, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0,
              max_bin=255, verbose=-1, num_threads=0, seed=7)
ROUNDS_BIN = 850        # ウォークフォワード 12 折の早期終了の中央値(580〜1404)
ROUNDS_RANK = 380       # 同(258〜583)


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ---------------------------------------------------------------- 特徴量
def load_feat(path):
    t0 = time.time()
    if str(path).endswith('.parquet'):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, low_memory=False)
    for c in df.columns:
        if df[c].dtype == object and c not in ('track', 'race_date', 'horse_key', 'finish_note', 'updated_at'):
            df[c] = pd.to_numeric(df[c], errors='coerce')
    df['race_date'] = pd.to_datetime(df['race_date'])
    num = [c for c in df.columns if df[c].dtype.kind == 'f']
    df[num] = df[num].astype('float32')
    df['rid'] = df['track'] + '|' + df['race_date'].dt.strftime('%Y-%m-%d') + '|' + df['race_no'].astype(str)
    df = add_relative(df)
    log('feat', len(df), 'rows', round(time.time() - t0, 1), 's')
    return df


def add_relative(df):
    """レース内の相対値を足して返す(⛔1 列ずつ足すと pandas が断片化するので concat で一度に)"""
    g = df.groupby('rid', sort=False)
    new = {'fld_n': g['runner_number'].transform('size').astype('float32')}
    for c in REL:
        if c not in df.columns:
            continue
        new['rel_' + c] = (df[c] - g[c].transform('mean')).astype('float32')
        new['rk_' + c] = g[c].rank(pct=True, method='average').astype('float32')
    return pd.concat([df, pd.DataFrame(new, index=df.index)], axis=1)


def feature_cols(df):
    drop = set(KEY + LABEL + PL_NULL + MARKET + ['rid', 'y'])
    return [c for c in df.columns if c not in drop and df[c].dtype.kind in 'fiu']


# ---------------------------------------------------------------- 学習
def fit(feat_path, model_path):
    import lightgbm as lgb
    df = load_feat(feat_path)
    tr = df[df['finish'].notna() & (df['finish_note'].fillna('') == '')].copy()
    tr['y'] = tr['y_top3'].astype(int)
    cols = feature_cols(tr)
    log('train rows', len(tr), 'cols', len(cols), 'to', tr['race_date'].max().date())
    t0 = time.time()
    bst_b = lgb.train(PARAMS, lgb.Dataset(tr[cols], tr['y']), num_boost_round=ROUNDS_BIN)
    log('binary done', round(time.time() - t0), 's')
    t0 = time.time()
    trs = tr.sort_values('rid')
    rel = np.clip(4 - trs['finish'].values, 0, 3).astype(int)
    grp = trs.groupby('rid', sort=False).size().values
    pr = dict(PARAMS, objective='lambdarank', metric='ndcg', eval_at=[3], lambdarank_truncation_level=6)
    bst_r = lgb.train(pr, lgb.Dataset(trs[cols], rel, group=grp), num_boost_round=ROUNDS_RANK)
    log('rank done', round(time.time() - t0), 's')
    out = {'model': MODEL_ID, 'trained_at': dt.datetime.now(JST).isoformat(timespec='seconds'),
           'trained_to': str(tr['race_date'].max().date()), 'n_rows': int(len(tr)), 'cols': cols,
           'rounds': [ROUNDS_BIN, ROUNDS_RANK],
           'binary': bst_b.model_to_string(), 'rank': bst_r.model_to_string()}
    Path(model_path).write_text(json.dumps(out), encoding='utf-8')
    log('saved', model_path, round(Path(model_path).stat().st_size / 1e6, 1), 'MB')


def load_model(model_path):
    import lightgbm as lgb
    m = json.loads(Path(model_path).read_text(encoding='utf-8'))
    return m, lgb.Booster(model_str=m['binary']), lgb.Booster(model_str=m['rank'])


def predict_df(df, m, bst_b, bst_r):
    """df= 予測したい行(rid 付き)。返す= p(2 本の平均)"""
    cols = m['cols']
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    pb = bst_b.predict(df[cols])
    raw = pd.Series(bst_r.predict(df[cols]), index=df.index)
    e = np.exp(raw - raw.groupby(df['rid']).transform('max'))
    prr = (e / e.groupby(df['rid']).transform('sum') * 3).clip(1e-4, 1 - 1e-4).values
    return (pb + prr) / 2


# ---------------------------------------------------------------- 今日の印
def build_marks(df, day, m, bst_b, bst_r):
    d = df[(df['race_date'] == pd.Timestamp(day)) & df['finish'].isna()].copy()
    if len(d) == 0:
        return []
    d['p'] = predict_df(d, m, bst_b, bst_r)
    rows = []
    for rid, g in d.groupby('rid', sort=False):
        runnable = g[g['finish_note'].fillna('') == '']            # 発走前に分かる取消・除外は外す
        if len(runnable) < 4:
            continue
        s = runnable['p'] / runnable['p'].sum()
        order = runnable.assign(s=s).sort_values(['s', 'runner_number'], ascending=[False, True]).head(4)
        marks = [{'num': int(r.runner_number), 'mark': MARKS[i], 'score': round(float(r.s) * 100, 1)}
                 for i, r in enumerate(order.itertuples())]
        track, _, no = rid.split('|')
        rows.append({'track': track, 'race_date': str(day), 'race_no': int(no), 'marks': marks,
                     'meta': {'n': int(len(runnable)), 'model': MODEL_ID, 'trained_to': m['trained_to'],
                              'rounds': m['rounds']}})
    return rows


def sb_get(base, key, path):
    req = urllib.request.Request(f'{base}/rest/v1/{path}',
                                 headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def write_marks(rows, day):
    base = os.environ.get('SUPABASE_URL') or os.environ.get('NAR_SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('NAR_SUPABASE_SERVICE_KEY')
    if not (base and key):
        env = load_env(str(HERE.parent / '.env.nar'))
        base, key = env.get('SUPABASE_URL'), env.get('SUPABASE_SERVICE_KEY')
    base = base.rstrip('/')
    # 凍結= 既にある行は触らない(morning も last も)
    have = sb_get(base, key, f'{TABLE}?select=track,race_no,timing&model=eq.{MODEL_ID}&race_date=eq.{day}&limit=2000')
    have = {(r['track'], r['race_no'], r['timing']) for r in have}
    now = dt.datetime.now(JST).isoformat(timespec='seconds')
    out = []
    for r in rows:
        for timing in ('morning', 'last'):
            if (r['track'], r['race_no'], timing) in have:
                continue
            out.append(dict(model=MODEL_ID, track=r['track'], race_date=r['race_date'], race_no=r['race_no'],
                            timing=timing, marks=r['marks'], meta=r['meta'], computed_at=now))
    if not out:
        log('nothing to write (all rows exist)')
        return 0
    st, err = upsert(base, key, TABLE, CONFLICT, out)
    if st not in (200, 201, 204):
        raise SystemExit(f'upsert failed: {st} {err}')
    log('wrote', len(out), 'rows for', day, '(skipped', len(rows) * 2 - len(out), 'existing)')
    return len(out)


def predict(feat_path, model_path, day, write):
    m, bst_b, bst_r = load_model(model_path)
    df = load_feat(feat_path)
    rows = build_marks(df, day, m, bst_b, bst_r)
    log('marks for', day, '=', len(rows), 'races')
    for r in rows[:6]:
        log(' ', r['track'], f"{r['race_no']}R", ' '.join(f"{x['mark']}{x['num']}({x['score']})" for x in r['marks']))
    if write and rows:
        write_marks(rows, day)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fit', 'predict'])
    ap.add_argument('--feat', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--date', default=None, help='YYYY-MM-DD(既定= 今日 JST)')
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'fit':
        fit(a.feat, a.model)
    else:
        day = a.date or dt.datetime.now(JST).date().isoformat()
        predict(a.feat, a.model, day, a.write)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
