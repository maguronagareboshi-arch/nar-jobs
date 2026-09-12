# -*- coding: utf-8 -*-
"""base-v1 予想AI(§129 段階 2/3)。特徴量表 `nar_ai_feat_run`(Actions 内 Postgres で毎朝作る・§129d)から学習し、
今日の出走馬に ◎○▲△ を付けて `nar_ai_marks`(model='base-v1')に書く。

  python pipeline/ai/base_v1.py fit     --feat out/nar_ai_feat_run.csv.gz --model out/base_v1.model.json [--variant morning|last]
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


# ---------------------------------------------------------------- 学習
def fit(feat_path, model_path, variant='last'):
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
    out = {'model': MODEL_ID, 'trained_at': dt.datetime.now(JST).isoformat(timespec='seconds'),
           'trained_to': str(tr['race_date'].max().date()), 'n_rows': int(len(tr)), 'cols': cols,
           'rounds': [ROUNDS_BIN, ROUNDS_RANK], 'variant': variant, 'dropped': dropped,
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


def build_marks(df, day, m, bst_b, bst_r, timing):
    d = df[(df['race_date'] == pd.Timestamp(day)) & df['finish'].isna()].copy()
    if len(d) == 0:
        return []
    d['p'] = predict_df(d, m, bst_b, bst_r)
    need = baba_tracks(df) if timing == 'last' else set()          # §143b 馬場が普段から入る場(1 回だけ数える)
    rows, skipped = [], {}
    for rid, g in d.groupby('rid', sort=False):
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
        order = runnable.assign(s=s).sort_values(['s', 'runner_number'], ascending=[False, True]).head(4)
        marks = [{'num': int(r.runner_number), 'mark': MARKS[i], 'score': round(float(r.s) * 100, 1)}
                 for i, r in enumerate(order.itertuples())]
        track, _, no = rid.split('|')
        rows.append({'track': track, 'race_date': str(day), 'race_no': int(no), 'marks': marks, 'meta': meta})
    for k in sorted(skipped):
        log('  skip', k, '=', skipped[k], 'race')            # ⛔黙って減らさない(なぜ書かないかを出す)
    return rows


def sb_get(base, key, path):
    req = urllib.request.Request(f'{base}/rest/v1/{path}',
                                 headers={'apikey': key, 'Authorization': f'Bearer {key}', 'User-Agent': 'nar-ai'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def creds():
    base = os.environ.get('SUPABASE_URL') or os.environ.get('NAR_SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('NAR_SUPABASE_SERVICE_KEY')
    if not (base and key):
        env = load_env(str(HERE.parent / '.env.nar'))
        base, key = env.get('SUPABASE_URL'), env.get('SUPABASE_SERVICE_KEY')
    return base.rstrip('/'), key


def write_marks(rows, day, timing):
    """§143 timing='morning'= 既にある行は触らない(凍結)。'last'= 毎回上書き。
    ⛔どちらも書くのは**その timing の行だけ**。⚠発走 15 分前を過ぎた行は DB のトリガーが
    静かに捨てる(ai_marks_guard_20260825.sql)ので、⛔「エラーが出なかった」を採用の証拠にせず読み直す。"""
    base, key = creds()
    now = dt.datetime.now(JST).isoformat(timespec='seconds')
    out = []
    if timing == 'morning':
        have = sb_get(base, key, f'{TABLE}?select=track,race_no,timing&model=eq.{MODEL_ID}'
                                 f'&race_date=eq.{day}&timing=eq.morning&limit=2000')
        have = {(r['track'], r['race_no']) for r in have}
        rows = [r for r in rows if (r['track'], r['race_no']) not in have]
        if len(have):
            log('skip', len(have), 'existing morning rows (凍結)')
    for r in rows:
        out.append(dict(model=MODEL_ID, track=r['track'], race_date=r['race_date'], race_no=r['race_no'],
                        timing=timing, marks=r['marks'], meta=r['meta'], computed_at=now))
    if not out:
        log('nothing to write')
        return 0
    st, err = upsert(base, key, TABLE, CONFLICT, out)
    if st not in (200, 201, 204):
        raise SystemExit(f'upsert failed: {st} {err}')
    log('tried', len(out), timing, 'rows for', day, '=', ' '.join(f"{r['track']}{r['race_no']}R" for r in rows[:12]))
    # 読み直し= 実際に入ったのはどれか(凍結後は静かに捨てられる)
    back = sb_get(base, key, f'{TABLE}?select=track,race_no,computed_at&model=eq.{MODEL_ID}'
                             f'&race_date=eq.{day}&timing=eq.{timing}&limit=2000')
    # ⚠REST は UTC(+00:00)で返し、now は JST(+09:00)= 文字で比べると一致しない(Fable 9/9 実測)→ 時刻として比べる
    def _t(x):
        try:
            return dt.datetime.fromisoformat(str(x).replace('Z', '+00:00')).astimezone(JST).replace(microsecond=0)
        except (TypeError, ValueError):
            return None
    now_t = _t(now)
    took = {(r['track'], r['race_no']) for r in back if _t(r.get('computed_at')) == now_t}
    miss = [f"{r['track']}{r['race_no']}R" for r in rows if (r['track'], r['race_no']) not in took]
    log('took', len(took), '/', len(out), ('(捨てられた= 発走15分前を過ぎている: ' + ' '.join(miss[:12]) + ')') if miss else '')
    return len(took)


def predict(feat_path, model_path, day, write, timing):
    if timing not in VARIANTS:
        raise SystemExit('--timing は morning か last')
    m, bst_b, bst_r = load_model(model_path)
    variant = m.get('variant') or 'last'          # variant の無い古い模型は全列= last 扱い
    if variant != timing:
        raise SystemExit(f'模型は variant={variant} なのに --timing {timing} で呼ばれた'
                         f'(⛔朝の模型で直前予想を書かない・逆も)')
    df = load_feat(feat_path)
    rows = build_marks(df, day, m, bst_b, bst_r, timing)
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
    a = ap.parse_args()
    if a.cmd == 'fit':
        fit(a.feat, a.model, a.variant)
    else:
        if not a.timing:
            raise SystemExit('predict には --timing morning|last が要ります')
        day = a.date or dt.datetime.now(JST).date().isoformat()
        predict(a.feat, a.model, day, a.write, a.timing)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
