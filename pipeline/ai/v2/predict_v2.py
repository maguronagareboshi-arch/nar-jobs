# -*- coding: utf-8 -*-
"""base-v2 の**朝の推論**。feat_v4.parquet から当日の南関 4 場を切り出し、固定模型 relnew_v4_20260923 で
p_own を出して `nar_ai_marks`(model='base-v2'・timing='morning')に書く。

  python -X utf8 predict_v2.py --date 2026-09-22 --out out/pred_base_v2.csv          # 書かない
  python -X utf8 predict_v2.py --date 2026-09-22 --out out/pred_base_v2.csv --write  # 本番へ upsert

写し元:
  add_rel_cols / predict … C:/Users/kouki/nankan_ai/paper/predict_daily.py(2026-09-23 の写し・式は変えない)
  印の並べ方 / 書き込み  … pipeline/ai/base_v1.py の build_marks / write_marks(MODEL_ID だけ差し替え)

⛔学習はしない(固定模型)。⛔本番へ流すのは REST の upsert だけ(SQL は流さない)。
⛔鍵は印字しない。⛔既にある morning の行は触らない(凍結)。
⛔発走 15 分前を過ぎた行は DB のトリガーが静かに捨てる= 読み直して「取り込まれず」をログに出すが、
  それ自体は失敗にしない(終了コード 0)。
"""
from __future__ import annotations
import argparse, csv, datetime as dt, json, os, sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.stdout.reconfigure(encoding='utf-8')

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))            # pipeline/ai/
import base_v1 as B1                            # noqa: E402

MODEL_ID = 'base-v2'
B1.MODEL_ID = MODEL_ID                          # ⛔write_marks が見る先をここで差し替える
TIMING = 'morning'
MARKS = ['◎', '○', '▲', '△']
JST = dt.timezone(dt.timedelta(hours=9))
NANKAN = ['大井', '川崎', '船橋', '浦和']
MODEL_STAMP = 'relnew_v4_20260923'
MODEL_DIR = str(HERE / 'model')
NAI_ROOT = (os.environ.get('NAI_ROOT') or 'C:/Users/kouki/nankan_ai/').replace(chr(92), '/').rstrip('/') + '/'


def log(*a):
    print(dt.datetime.now(JST).strftime('%H:%M:%S'), *a, flush=True)


# ---------------------------------------------- predict_daily.py の写し(式は 1 つも変えない)
def add_rel_cols(df, meta):
    """レース内の rel_/rk_ を e5c_train_v2.load と同じ式で作る(1 日分なので軽い)。"""
    df = df.copy()
    df['rid'] = (df['track'].astype(str) + '|' + pd.to_datetime(df['race_date']).dt.strftime('%Y-%m-%d')
                 + '|' + df['race_no'].astype(str))
    g = df.groupby('rid', sort=False)
    df['fld_n'] = g['runner_number'].transform('size').astype('float32')
    for c in list(meta['rel_targets']) + list(meta['relnew_targets']):
        if c not in df.columns:
            continue
        df['rel_' + c] = (df[c] - g[c].transform('mean')).astype('float32')
        df['rk_' + c] = g[c].rank(pct=True, method='average').astype('float32')
    return df


def predict(df, meta, bst):
    cols = meta['feature_cols']
    missing = [c for c in cols if c not in df.columns]
    X = pd.DataFrame(index=df.index)
    for c in cols:
        X[c] = pd.to_numeric(df[c], errors='coerce') if c in df.columns else np.nan
    raw = bst.predict(X.to_numpy(dtype=np.float64), num_iteration=meta['best_iteration'])
    ix, iy = np.asarray(meta['isotonic']['x']), np.asarray(meta['isotonic']['y'])
    p = np.interp(raw, ix, iy, left=float(iy[0]), right=float(iy[-1]))
    p = np.clip(p, 1e-9, None)
    s = pd.Series(p).groupby(df['rid'].values).transform('sum').to_numpy()
    return p / s, missing


# ---------------------------------------------- 印(base_v1.build_marks と同じ並べ方)
def build_marks(d, day, model_file):
    """⛔base_v1.build_marks と同じ: finish_note の空いている馬だけ・4 頭未満はスキップ・
    s = p/Σp・上位 4 頭に ◎○▲△・score = round(s*100, 1)。"""
    rows = []
    for rid, g in d.groupby('rid', sort=False):
        runnable = g[g['finish_note'].fillna('') == '']
        if len(runnable) < 4:
            continue
        s = runnable['p'] / runnable['p'].sum()
        meta = {'n': int(len(runnable)), 'model': MODEL_ID,
                'p': {str(int(u)): round(float(v), 4) for u, v in zip(runnable['runner_number'], s)},
                'model_file': model_file, 'stamp': MODEL_STAMP}
        order = runnable.assign(s=s).sort_values(['s', 'runner_number'],
                                                 ascending=[False, True]).head(4)
        marks = [{'num': int(r.runner_number), 'mark': MARKS[i], 'score': round(float(r.s) * 100, 1)}
                 for i, r in enumerate(order.itertuples())]
        track, _, no = rid.split('|')
        rows.append({'track': track, 'race_date': str(day), 'race_no': int(no),
                     'marks': marks, 'meta': meta})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=str(dt.datetime.now(JST).date()))
    ap.add_argument('--feat', default=NAI_ROOT + 'feat_v4.parquet')
    ap.add_argument('--model', default=MODEL_STAMP)
    ap.add_argument('--out', default='')
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()

    txt = os.path.join(MODEL_DIR, a.model + '.txt')
    jsn = os.path.join(MODEL_DIR, a.model + '.json')
    if not (os.path.exists(txt) and os.path.exists(jsn)):
        raise SystemExit('⛔固定模型が無い %s' % txt)
    meta = json.load(open(jsn, encoding='utf-8'))
    bst = lgb.Booster(model_file=txt)
    log('模型 %s 特徴量 %d 本 iter=%d' % (a.model, meta['n_features'], meta['best_iteration']))

    df = pd.read_parquet(a.feat)
    df['race_date'] = pd.to_datetime(df['race_date'])
    d = df[(df['race_date'] == pd.Timestamp(a.date)) & (df['track'].isin(NANKAN))].copy()
    del df
    if len(d) == 0:
        log('%s は南関 4 場の出走が無い = 何も書かない' % a.date)
        return 0

    d = add_rel_cols(d, meta)
    p, missing = predict(d, meta, bst)
    d['p'] = p
    log('%s %d R / %d 頭 / 欠けた特徴量 %d 本' % (a.date, d['rid'].nunique(), len(d), len(missing)))
    if missing:
        log('⚠欠けた特徴量の例', missing[:8])

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, 'w', encoding='utf-8', newline='') as h:
            w = csv.writer(h)
            w.writerow(['race_date', 'track', 'race_no', 'runner_number', 'p_own', 'model', 'model_file'])
            for (tr, rno, un), pv in zip(zip(d['track'], d['race_no'], d['runner_number']), p):
                w.writerow([a.date, tr, int(rno), int(un), round(float(pv), 6),
                            MODEL_ID, a.model + '.txt'])
        log('→', a.out)

    rows = build_marks(d, a.date, a.model + '.txt')
    log('印の付いたレース %d R(4 頭未満と取消は除く)' % len(rows))
    if not a.write:
        log('--write が無い = 本番へは書かない')
        return 0
    if not rows:
        log('skip 書く印が無い')
        return 0
    took = B1.write_marks(rows, a.date, TIMING)
    if took == 0:
        log('skip 取り込まれた行は 0(既にある morning 行の凍結か、発走 15 分前を過ぎた)= 失敗にしない')
    return 0


if __name__ == '__main__':
    sys.exit(main())
