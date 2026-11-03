# -*- coding: utf-8 -*-
"""base-v1 予想AI(§129 段階 2/3)。特徴量表 `nar_ai_feat_run`(Actions 内 Postgres で毎朝作る・§129d)から学習し、
今日の出走馬に ◎○▲△ を付けて `nar_ai_marks`(model='base-v1')に書く。

  python pipeline/ai/base_v1.py fit     --feat out/nar_ai_feat_run.csv.gz --model out/base_v1.model.json [--variant morning|last] [--wf-out <parquet>]
  python pipeline/ai/base_v1.py predict --feat out/nar_ai_feat_run.csv.gz --model out/base_v1.model.json --timing morning|last [--write] [--date YYYY-MM-DD]

§143(#545)2026-09-09 朝便と直前便に分けた:
  - 朝便(06:30)= 当日の馬体重・馬場が**まだ無い**ので、それに依る列を抜いた模型(variant='morning')で
    morning の印だけ書く。⛔last の行は作らない。
  - 直前便(日中 30 分おき)= 全列の模型(variant='last')で、体重と馬場が**全頭そろった**レースだけ
    last を上書きする(発走 15 分前を過ぎた行は DB のトリガーが静かに捨てる= 書けたかは読み直して確かめる)。
  - ⛔模型の variant と --timing が食い違ったら落とす(朝の模型で直前予想を書かない・逆も)。

設計(設計書・評価は 設計台帳 §10 #527):
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
§224a(2026-09-19)1 着の見込み p_win を足した(⛔3 着内の p・印・列は 1 バイトも変えない):
  - fit= 1 着の模型 bst_w(y= y_win・PARAMS/列は同じ・反復は win_wf 12 折の早期終了の中央値)を同梱。
  - 較正= fit の中で 12 か月ウォークフォワード(月ごとに前だけで学習)の p_win(レース内で合計 1)を 10 帯に切り、
    帯ごとの「実際に 1 着だった率」を model.json の cal_win に入れる。⛔市場(人気・オッズ)は較正に使わない。
  - predict= p_win を帯の実績へ置き換え(帯の中は線形補間)→ レース内で合計 1 → meta.p_win と meta.cal。
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
import ai_common as AC  # noqa: E402  2026-11-03 共通の部品は ai_common へ写した(中身は同じ)
from ai_common import (TABLE, CONFLICT, JST, REL, CAL_ID, CAL_EDGES, log, add_relative, race_norm,  # noqa: E402,F401
                       cal_table, win_calibrate, sb_get, creds)

MODEL_ID = 'base-v1'
MARKS = ['◎', '○', '▲', '△', '△']   # 2026-10-10 ユーザー決定: 印は 5 頭(◎○▲△△)
NANKAN = {'浦和', '船橋', '大井', '川崎'}   # 2026-10-10 ユーザー決定: 南関 4 場は南関特化 AI だけ= base-v1 は書かない
BANEI = {'帯広ば'}   # 2026-10-29 ユーザー決定: 帯広はばんえい 第 3 版(banei-3)だけ= base-v1 は書かない(第 3 版が書けない日は印なし)

KEY = ['track', 'race_date', 'race_no', 'runner_number', 'horse_key']
LABEL = ['finish', 'finish_note', 'popularity', 'y_top3', 'y_win', 'updated_at']
MARKET = ['prev_ninki', 'p1_ninki', 'p2_ninki', 'p3_ninki', 'p4_ninki', 'p5_ninki']
PL_NULL = ['pl_theta', 'pl_n', 'jk_beta', 'tr_gamma', 'r_plth_pct', 'pl_gap_top', 'jk_beta_delta']
# §143 当日の馬体重・馬場が分からないと埋まらない列(朝便の模型では抜く)。
# ⛔推定ではなく **SQL を読んで + 実測で**確定した(2026-09-09・まだ走っていない 2 日 821 行で NaN 率を見た):
#   ① 今日の馬体重・馬場そのもの(NaN 率 100%)
#      bataiju_now / bataiju_diff / baba_now / bw_dev / bw_season_dev
#   ② 今日の馬場での過去成績(w_h_gng は going_ord で切っている= 今日の馬場が要る)
#      rgm_gap(100% NaN)/ rgm_n ⚠**NaN でなく 0 になる**(学習の平均 11.5 走 → 当日は全行 0= 嘘の 0)
#      sire_rgm_gap(86% NaN)/ mf_rgm_gap(90% NaN)
#   ③ 今日の馬装具(当日発表・100% NaN)gear_now / gear_first / gear_off
#      ⛔gear_n / gear_hit は過去の集計なので**残す**
#   ④ ⚠**器の都合で当日だけ空になっていた 6 列**(waku_bias_30/365・pace_bias_30/365・baba_io_365・
#      trk_recent_dmz)は §143b(2026-09-09)で SQL を直した= `t_bias` / `t_baba` を
#      **前の開催日を引く lateral**(baba_diff_d と同じ形)にしたので**朝でも入る**= この表には入れない。
#      ⚠SQL を戻したら、この 6 列も戻すこと(⛔片方だけ動かすと朝の模型が空の列を覚える)。
# ⛔wet_n / wet_fuku / wet_tza_gap は**抜かない**= 過去の道悪成績で、今日の馬場に依らない(実測 NaN 率 0〜13%)。
TODAY_COLS = ['bataiju_now', 'bataiju_diff', 'baba_now', 'bw_dev', 'bw_season_dev',
              'rgm_gap', 'rgm_n', 'sire_rgm_gap', 'mf_rgm_gap',
              'gear_now', 'gear_first', 'gear_off']
VARIANTS = ('morning', 'last')
PARAMS = dict(objective='binary', learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
              feature_fraction=0.6, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0,
              max_bin=255, verbose=-1, num_threads=0, seed=7)
ROUNDS_BIN = 850        # ウォークフォワード 12 折の早期終了の中央値(580〜1404)
ROUNDS_RANK = 380       # 同(258〜583)
# §224a 1 着の模型と較正
ROUNDS_WIN = 520        # win_wf(§170 段 2 C)12 折の早期終了の中央値(389〜775)
CAL_MONTHS = 12         # 較正に使うウォークフォワードの月数(trained_to の前の月まで)


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


def today_cols(cols):
    """§143 当日列と、そこから作った rel_/rk_ の派生(名前で判定)。⛔並びは cols のまま"""
    base = set(TODAY_COLS)
    out = []
    for c in cols:
        if c in base or (c.startswith(('rel_', 'rk_')) and c.split('_', 1)[1] in base):
            out.append(c)
    return out


def feature_cols(df, variant='last'):
    drop = set(KEY + LABEL + PL_NULL + MARKET + ['rid', 'y'])
    cols = [c for c in df.columns if c not in drop and df[c].dtype.kind in 'fiu']
    if variant == 'morning':
        cut = set(today_cols(cols))
        cols = [c for c in cols if c not in cut]
    return cols


# ---------------------------------------------------------------- §224a 1 着の見込み
def win_label(d):
    """1 着の印= y_win(無ければ finish==1)"""
    if 'y_win' in d.columns and d['y_win'].notna().all():
        return d['y_win'].astype(int).values
    return (d['finish'] == 1).astype(int).values


def win_walkforward(tr, cols, yw, months=CAL_MONTHS):
    """trained_to の前の月までの months か月を、月ごとに**その月より前だけ**で学習して当てる(反復は固定)。
    返す= rid・track・race_date・runner_number・y・p_win(レース内で合計 1)"""
    import lightgbm as lgb
    last = pd.Period(tr['race_date'].max(), freq='M') - 1
    parts = []
    y = pd.Series(yw, index=tr.index)
    for per in pd.period_range(last - (months - 1), last, freq='M'):
        ts, te = per.start_time, per.end_time
        trn = tr[tr['race_date'] < ts]
        tst = tr[(tr['race_date'] >= ts) & (tr['race_date'] <= te)]
        if len(tst) == 0 or len(trn) == 0:
            continue
        t0 = time.time()
        bst = lgb.train(PARAMS, lgb.Dataset(trn[cols], y[trn.index]), num_boost_round=ROUNDS_WIN)
        part = tst[['rid', 'track', 'race_date', 'runner_number']].copy()
        part['y'] = y[tst.index].values
        part['p_win'] = race_norm(bst.predict(tst[cols]), tst['rid'])
        parts.append(part)
        log('  wf', str(per), 'train', len(trn), 'test', len(tst), round(time.time() - t0), 's')
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=['rid', 'track', 'race_date', 'runner_number', 'y', 'p_win'])


def log_cal(cal):
    log('cal_win', cal['id'], '(帯= 見込み%: 件数 / 見込みの平均% / 実際の 1 着率%)')
    for i in range(len(cal['n'])):
        lo, hi = cal['edges'][i] * 100, cal['edges'][i + 1] * 100
        pr, rt = cal['pred'][i], cal['rate'][i]
        log('   %5.1f-%5.1f: %6d / %s / %s' % (lo, hi, cal['n'][i], '-' if pr is None else '%.2f' % (pr * 100),
                                              '-' if rt is None else '%.2f' % (rt * 100)))


# ---------------------------------------------------------------- 学習
def fit(feat_path, model_path, variant='last', wf_out=None):
    import lightgbm as lgb
    if variant not in VARIANTS:
        raise SystemExit('--variant は morning か last')
    df = load_feat(feat_path)
    tr = df[df['finish'].notna() & (df['finish_note'].fillna('') == '')].copy()
    tr['y'] = tr['y_top3'].astype(int)
    all_cols = feature_cols(tr, 'last')
    cols = feature_cols(tr, variant)
    dropped = [c for c in all_cols if c not in set(cols)]
    log('variant', variant, 'train rows', len(tr), 'cols', len(cols),
        ('(当日列 %d 本を抜いた)' % len(dropped)) if dropped else '', 'to', tr['race_date'].max().date())
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
    # §224a 1 着の模型(全期間)と、12 か月ウォークフォワードで作る較正表
    t0 = time.time()
    yw = win_label(tr)
    bst_w = lgb.train(PARAMS, lgb.Dataset(tr[cols], yw), num_boost_round=ROUNDS_WIN)
    log('win done', round(time.time() - t0), 's')
    wf = win_walkforward(tr, cols, yw)
    cal = cal_table(wf['p_win'].values, wf['y'].values)
    cal['months'] = [str(wf['race_date'].min().date()), str(wf['race_date'].max().date())] if len(wf) else []
    log_cal(cal)
    if wf_out:
        wf.to_parquet(wf_out, index=False)
        log('wf ->', wf_out, len(wf), 'rows')
    out = {'model': MODEL_ID, 'trained_at': dt.datetime.now(JST).isoformat(timespec='seconds'),
           'trained_to': str(tr['race_date'].max().date()), 'n_rows': int(len(tr)), 'cols': cols,
           'rounds': [ROUNDS_BIN, ROUNDS_RANK], 'variant': variant, 'dropped': dropped,
           'binary': bst_b.model_to_string(), 'rank': bst_r.model_to_string(),
           'rounds_win': ROUNDS_WIN, 'win': bst_w.model_to_string(), 'cal_win': cal,
           'baba_tracks': sorted(baba_tracks(tr))}   # §143b 監査 11/3: 当日の表には着順が無い= 学習の時に数えて持たせる
    Path(model_path).write_text(json.dumps(out), encoding='utf-8')
    log('saved', model_path, round(Path(model_path).stat().st_size / 1e6, 1), 'MB')


def load_model(model_path):
    import lightgbm as lgb
    m = json.loads(Path(model_path).read_text(encoding='utf-8'))
    return m, lgb.Booster(model_str=m['binary']), lgb.Booster(model_str=m['rank'])


def load_win(m):
    """§224a 1 着の模型(model.json の 'win')。⛔無い古い模型は None= p_win を出さない"""
    if not m.get('win') or not m.get('cal_win'):
        return None
    import lightgbm as lgb
    return lgb.Booster(model_str=m['win'])


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
def baba_tracks(df):
    """§143b 馬場(baba_now)が**その場では普段から入る**か。⛔場名は書かない(規則を足さない)=
    学習に使える行(着順のある行)で 1 度でも入っていれば「入る場」。
    ⚠帯広ばんえいの going は含水率の数字なので学習行でも常に NULL= 「馬場は要らない場」になる。"""
    if 'baba_now' not in df.columns or 'finish' not in df.columns:
        return set()
    past = df[df['finish'].notna()]
    n = past.groupby('track')['baba_now'].count()
    return {t for t, c in n.items() if c > 0}


def today_ready(runnable, need_baba=True):
    """§143 直前予想を書いてよいか= 走る全頭に**今日の馬体重**があること。
    ⛔1 頭でも欠けたら書かない(0 で埋めない)。
    §143b 馬場は**その場で普段から入るときだけ**要る(need_baba)。⛔普段から入らない場(帯広ばんえい)は
    全頭 NULL のまま通す= そこだけ直前予想が永久に出ないのを避ける。⚠入る場で一部だけ欠けているのは通さない。"""
    if 'bataiju_now' not in runnable.columns or 'baba_now' not in runnable.columns:
        return False, 'bataiju_now/baba_now という列が無い'
    if runnable['bataiju_now'].isna().any():
        return False, '馬体重が %d/%d 頭' % (int(runnable['bataiju_now'].notna().sum()), len(runnable))
    if runnable['baba_now'].isna().any():
        if need_baba:
            return False, '馬場が無い'
        if runnable['baba_now'].notna().any():
            return False, '馬場が %d/%d 頭' % (int(runnable['baba_now'].notna().sum()), len(runnable))
    return True, ''


def build_marks(df, day, m, bst_b, bst_r, timing, bst_w=None):
    d = df[(df['race_date'] == pd.Timestamp(day)) & df['finish'].isna()].copy()
    if len(d) == 0:
        return []
    d['p'] = predict_df(d, m, bst_b, bst_r)
    if bst_w is not None:                                          # §224a 1 着の見込み(較正前・レース内で割る前)
        d['pw'] = bst_w.predict(d[m['cols']])
    pw_all = []
    # §143b 馬場が普段から入る場。⛔当日の表には着順が無く数えられない= 学習の時に数えた一覧を使う(古い模型は今までどおり)
    need = set(m.get('baba_tracks') or baba_tracks(df)) if timing == 'last' else set()
    rows, skipped = [], {}
    for rid, g in d.groupby('rid', sort=False):
        if rid.split('|')[0] in NANKAN | BANEI:                  # ⛔write_marks は v3 系と共用= 絞り込みはここだけ
            continue
        runnable = g[g['finish_note'].fillna('') == '']            # 発走前に分かる取消・除外は外す
        if len(runnable) < 4:
            continue
        meta = {'n': int(len(runnable)), 'model': MODEL_ID, 'trained_to': m['trained_to'],
                'rounds': m['rounds']}
        if timing == 'last':
            ok, why = today_ready(runnable, rid.split('|')[0] in need)
            if not ok:
                skipped.setdefault(rid.split('|')[0] + ' ' + why, 0)
                skipped[rid.split('|')[0] + ' ' + why] += 1
                continue
            meta['timing'] = 'last'
            meta['bw_n'] = int(runnable['bataiju_now'].notna().sum())
        s = runnable['p'] / runnable['p'].sum()
        # §170 B 全頭の s(= p/Σp)を残す= 期待値の検証用。⛔marks(上位 5 頭)の形は変えない
        meta['p'] = {str(int(u)): round(float(v), 4) for u, v in zip(runnable['runner_number'], s)}
        # 2026-10-11 配り直す前の 3 着内の見込み(predict_df の値そのまま)= 画面の「3着内」。南関特化の p3 と同じ読み方。
        #   ⛔meta.p(合計 1)・marks は変えない
        meta['p3'] = {str(int(u)): round(float(v), 4) for u, v in zip(runnable['runner_number'], runnable['p'])}
        if bst_w is not None:
            # §224a 走る馬の中で合計 1 → 帯の実績へ置き換え → もう一度合計 1。⛔meta.p・marks は触らない
            w = race_norm(runnable['pw'].values, runnable['rid'])
            wc = win_calibrate(w, m['cal_win'])
            wc = wc / wc.sum() if wc.sum() > 0 else w
            meta['p_win'] = {str(int(u)): round(float(v), 4) for u, v in zip(runnable['runner_number'], wc)}
            meta['cal'] = CAL_ID
            pw_all.extend(wc)
        order = runnable.assign(s=s).sort_values(['s', 'runner_number'], ascending=[False, True]).head(5)
        marks = [{'num': int(r.runner_number), 'mark': MARKS[i], 'score': round(float(r.s) * 100, 1)}
                 for i, r in enumerate(order.itertuples())]
        track, _, no = rid.split('|')
        rows.append({'track': track, 'race_date': str(day), 'race_no': int(no), 'marks': marks, 'meta': meta})
    for k in sorted(skipped):
        log('  skip', k, '=', skipped[k], 'race')            # ⛔黙って減らさない(なぜ書かないかを出す)
    if pw_all:                                                     # §224a p_win の帯別の頭数(較正後)
        c = np.bincount(np.clip(np.digitize(pw_all, CAL_EDGES[1:-1]), 0, len(CAL_EDGES) - 2), minlength=len(CAL_EDGES) - 1)
        log('  p_win 帯別の頭数(較正後)', ' '.join('%g-%g%%:%d' % (CAL_EDGES[i] * 100, CAL_EDGES[i + 1] * 100, n)
                                                  for i, n in enumerate(c)))
    return rows


def write_marks(rows, day, timing):
    """ai_common.write_marks に model='base-v1' を渡す薄い包み(凍結・読み直しは ai_common と同じ)"""
    return AC.write_marks(rows, day, timing, MODEL_ID)


def predict(feat_path, model_path, day, write, timing):
    if timing not in VARIANTS:
        raise SystemExit('--timing は morning か last')
    m, bst_b, bst_r = load_model(model_path)
    bst_w = load_win(m)
    if bst_w is None:
        log('⚠1 着の模型が無い(古い model.json)= meta.p_win は出さない')
    else:
        log_cal(m['cal_win'])
    variant = m.get('variant') or 'last'          # variant の無い古い模型は全列= last 扱い
    if variant != timing:
        raise SystemExit(f'模型は variant={variant} なのに --timing {timing} で呼ばれた'
                         f'(⛔朝の模型で直前予想を書かない・逆も)')
    df = load_feat(feat_path)
    rows = build_marks(df, day, m, bst_b, bst_r, timing, bst_w)
    log('marks for', day, timing, '=', len(rows), 'races')
    for r in rows[:6]:
        log(' ', r['track'], f"{r['race_no']}R", ' '.join(f"{x['mark']}{x['num']}({x['score']})" for x in r['marks']))
    if write and rows:
        write_marks(rows, day, timing)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fit', 'predict'])
    ap.add_argument('--feat', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--date', default=None, help='YYYY-MM-DD(既定= 今日 JST)')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--variant', choices=VARIANTS, default='last', help='fit: 朝便の模型は morning')
    ap.add_argument('--timing', choices=VARIANTS, default=None, help='predict: 必須(既定なし)')
    ap.add_argument('--wf-out', default=None, help='fit: §224a 1 着の 12 か月 WF の予測を parquet に残す(研究用)')
    a = ap.parse_args()
    if a.cmd == 'fit':
        fit(a.feat, a.model, a.variant, a.wf_out)
    else:
        if not a.timing:
            raise SystemExit('predict には --timing morning|last が要ります')
        day = a.date or dt.datetime.now(JST).date().isoformat()
        predict(a.feat, a.model, day, a.write, a.timing)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
