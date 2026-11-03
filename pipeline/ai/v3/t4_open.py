# -*- coding: utf-8 -*-
"""第 4 版 4 日目・5 日目(判断の日)の台本(PREREG4 §1・§2・§5・§6・§7・§9)。4 日目に sha256 で固定する。値を見て形・設定・材料は変えない。

  py -3.12 -X utf8 src/t4_open.py fit          # 4 日目: 2015〜2021 で前日版・当日版 × Y1・Y3 を 2 回ずつ学習(文字列の一致)→ models/t4_*.txt
  py -3.12 -X utf8 src/t4_open.py formatcheck  # 4 日目: §9 の書き方の確かめ ①② → out/t4_day4_format.md(結果の列は読まない)
  py -3.12 -X utf8 src/t4_open.py dry          # 4 日目: 探索の 2021 だけで、open と同じ道を通す通し試験(表は出さない)
  py -3.12 -X utf8 src/t4_open.py open         # 5 日目(判断の日)だけ: 確かめる期間(2022-01〜2026-08)を 1 回だけ開ける → out/t4_day5_open.md

■ 決め書に無い細部(4 日目に決めた。開ける前。見た後は変えない)
  1. 読み込み = t3_open.sources(part)(取消などの書き方・馬の鍵「名前|生年」のそろえと見張り)の走り h と、新しく書いた races4(part)
     (RAW + DB の写しを _align でそろえる)。_align は RAW で空(数の型)の direction を数に変えて消すので、DB の direction は元の値から
     読み直す(NFKC・空白を消して「右」「左」、空は欠け、ほかは知らない書き方として止まる)。post_time は RAW(数 1745.0)も DB(文字 '1745')も
     NFKC・「:」を消して 3〜4 桁の数字として読む(読めなければ欠け)。
  2. t4_base.build に渡す走り = h から races・facts の列(RACE_COLS・f_l3・c1〜n4・hid)を外し、umaban を runner_number に戻したもの
     (南関・2014〜)。材料は t4_day3 の feat_new・assemble をそのまま使う(3 日目の features と同じ作り方)。
  3. 書き方の見張り(南関・その区間のレース/走り): 知らない回りの書き方・知らない減量の印・発走時刻の読めない行・年齢条件の読めない行・
     賞金の読めない行がそれぞれ 0、格の読めないレースが 1% 以下、大井で direction が空のレースが 2023 年以降に 0。1 つでも外れたら止まる。
  4. SI の欠けの見張り = 南関の出走(取消・除外を除く)のうち SI の無い割合を年ごとに出し、区間の各年が 2016〜2021 の年ごとの最大 + 0.05 以下。
     転入の見張り = 予想する行のうち l_jra = 1 か l_nar = 1 の割合を月ごとに出し、区間の各月が 2016〜2021 の月ごとの最大 × 1.5 以下
     (2016〜2021 は feat_t4_explore から)。通ったときは数字を出さない。
  5. 第 4 版の学び直しの行 = feat_t4_explore(2015〜2021)+ open で作った確かめる期間の表のうち区切りの始まりより前、並べ方は
     ['year', 場, 日付, R, 馬番](t4_day3.load4 と同じ)。設定は v3/t4_grid.json。区切り ① の第 4 版の模型が models/t4_* と一致するかは
     記録だけ(止めるのは第 3 版の ①・⑤ だけ。§7)。
  6. 旧 AI の絞り: 区切り ⑤ の予想するレースのうち、旧 AI のファイルにある(場・日付・R・馬番)が予想する行の全馬にあるレースだけ。
     除いた理由は「ファイルに無いレース」「中止の馬だけが無い」「そのほかの馬が無い」の 3 つに分けて数える(中止 = h の finish_note)。
  7. open は確かめる期間の第 4 版の材料の表を v3/feat_t4_open.parquet に保存する(6 日目の学び直し用)。
  8. formatcheck ①: 両方とも読めない(欠け)のは一致に数える。減量の印は H_MARK の番号(無しは 0)で比べる。
  9. バグ直し(4 日目・formatcheck ② で発見・開ける前): DB の確認・封印・前向きの写しは condition の後ろに半角空白 + 斤量の決め
     (「一般 別定」「2歳 定量」「3歳以上 ハンデ」)を書く(2020〜2021 の写しと RAW には無い)。t4_base.parse_name は空白を消して読むので
     「2歳別定」となり年齢条件・若馬の区分・格が読めなかった → races4 の読み込み(prep)で後ろの「空白 + 別定/定量/ハンデ/馬齢」を外す。
     t3_open.sources の h(第 3 版の材料の元)は変えない。
  10. バグ直し(5 日目・開ける前の点検 out/t4_day5_preopen.md で発見): DB は 2022-11-03 から騎手・調教師の名前の空白を全角で書く
     (RAW と 2022-10 までは半角。確認の写しで騎手 953 行・調教師 834 行)。load4 で jockey・trainer を NFKC にそろえる(同じ人が
     別人として数えられるのを防ぐ。RAW の名前は NFKC で重ならないので作る期間の材料は変わらない=dry で確かめる)。第 3 版の保存した表は変えない。
  11. 見張りの追加(5 日目・ユーザー承認 2026-09-26): SI と同じ線(年ごとの欠けの割合が 2016〜2021 の最大 + 5 ポイント以下)で、
     テン指数・上がり指数(U)と最初の角の位置 c1(南関の出走・取消と除外を除く)も見張る。止まるだけで、通ったときの数字は変わらない。
"""
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_eval  # noqa: E402
import t3_open  # noqa: E402
import t4_base  # noqa: E402
import t4_day3 as d3  # noqa: E402
from day2_features import RACE_COLS, build as build3  # noqa: E402
from day5_forward_features import _align  # noqa: E402
from load_outcomes import load_archive  # noqa: E402
from t3_day2_features import finish_table, targets3  # noqa: E402

V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
REPO = Path(__file__).resolve().parent.parent
MD = Path(__import__('os').environ.get('V3_MODELS', 'C:/Users/kouki/OneDrive/デスクトップ/nankan-ai-v3/models'))
OUT_OPEN = REPO / 'out/t4_day5_open.md'
OUT_FMT = REPO / 'out/t4_day4_format.md'
FEAT_OPEN = V3 / 'feat_t4_open.parquet'
KEY = d3.KEY
NANKAN = d3.NANKAN
CANCEL = ['取消', '除外']
FILES = t3_open.FILES
# (見出し, 始まり, 終わり(含まない), t3_open.sources に渡す part)
SPAN4 = {'dry': ('2021-01-01', '2022-01-01', 'dry'), 'open': ('2022-01-01', '2026-09-01', 'sealed'),
         'forward': ('2026-09-01', '9999-12-31', 'forward')}
SEGS = [('①', '2022-01-01', '2023-01-01'), ('②', '2023-01-01', '2024-01-01'), ('③', '2024-01-01', '2025-01-01'),
        ('④', '2025-01-01', '2025-09-01'), ('⑤', '2025-09-01', '2026-09-01')]
REF3 = {'2022-01-01': 't3', '2025-09-01': 't3d4'}  # 第 3 版の区切り ①・⑤ の模型(一致しなければ止まる)
REF4 = {'2022-01-01': 't4'}  # 第 4 版の区切り ①(記録だけ)
FACT_COLS = ['f_l3', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']
RACE_SAFE = KEY + ['race_name', 'condition', 'prize_yen', 'post_time', 'direction']
RUN_SAFE = KEY + ['runner_number', 'weight_mark']
VN = {'pre': '前日版', 'day': '当日版'}
RE_RULE = re.compile(r'\s+(別定|定量|ハンデ|馬齢)$')  # バグ直し(4 日目 formatcheck): DB は 2022 年以降、condition の後ろに斤量の決めを書く


# ================================================================ 設定
def grid4():
    g = json.loads((V3 / 't4_grid.json').read_text(encoding='utf-8'))
    assert g['kept'] == d3.PRE_ALL and len(g['kept']) == 93, 't4_grid.json の kept が段 1〜5 の 93 列でない'
    cols = {'pre': list(g['kept']), 'day': list(g['kept']) + d3.FEATS4[6]}
    return cols, {'Y1': tuple(g['Y1']), 'Y3': tuple(g['Y3'])}


C4, CFG4 = grid4()


def train4(df, cols, target):
    assert len(cols) == len(set(cols)) and not d3.BANNED & set(cols)
    cfg = CFG4[target]
    z = d3.logit((1 if target == 'Y1' else 3) / df.n.to_numpy(float))
    prm = dict(d3.BASE, num_leaves=cfg[0], min_data_in_leaf=cfg[1])
    return lgb.train(prm, lgb.Dataset(df[cols].astype(float), label=df[target].to_numpy(float), init_score=z),
                     num_boost_round=cfg[2])


def sort4(df):
    return df.sort_values(['year'] + KEY + ['umaban'], kind='mergesort').reset_index(drop=True)


def booster(fp):  # 日本語を含むパスは LightGBM が開けないので文字列で渡す
    return lgb.Booster(model_str=fp.read_text(encoding='utf-8'))


def models4(prefix):
    return {v: (booster(MD / f'{prefix}_{v}_Y1.txt'), booster(MD / f'{prefix}_{v}_Y3.txt')) for v in ('pre', 'day')}


def verify():
    r = subprocess.run([sys.executable, '-X', 'utf8', str(REPO / 'src/verify_hashes.py')], capture_output=True, text=True,
                       encoding='utf-8')
    print('verify_hashes:', r.stdout.strip().splitlines()[-1], flush=True)
    if r.returncode:
        raise SystemExit('⛔ verify_hashes が NG。開けない')


# ================================================================ fit(4 日目)
def fit():
    df = sort4(pd.read_parquet(d3.FEAT))
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < '2022-01-01'
    meta = {'train': '2015-01-01〜2021-12-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]),
            'cfg': {k: list(v) for k, v in CFG4.items()}, 'files': {}}
    for v, cols in C4.items():
        for t in ('Y1', 'Y3'):
            s1, s2 = train4(df, cols, t).model_to_string(), train4(df, cols, t).model_to_string()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {v} {t}')
            fp = MD / f't4_{v}_{t}.txt'
            fp.write_text(s1, encoding='utf-8', newline='\n')
            meta['files'][fp.name] = {'cols': cols}
            print(v, t, '一致', flush=True)
    (MD / 't4_models.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')


# ================================================================ 読み込み
def norm_dir(x, strict=True):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(x)))
    if s == '' or s.lower() in ('nan', 'none'):
        return np.nan
    if s in ('右', '左'):
        return s
    if strict:
        raise SystemExit(f'⛔ 知らない回りの書き方: {s!r}')
    return '?'


def parse_pt(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = unicodedata.normalize('NFKC', str(x)).strip().replace(':', '')
    m = re.fullmatch(r'(\d{3,4})(\.0+)?', s)
    return float(m.group(1)) if m else np.nan


def db_races(p, ref, cols=None, strict=True):
    raw = pd.read_parquet(V3 / f'db_races_{p}_{FILES[p]}.parquet', columns=cols)
    return prep(_align(raw, ref), raw, strict)


def norm_cond(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return x
    return RE_RULE.sub('', unicodedata.normalize('NFKC', str(x)).rstrip())


def prep(al, raw, strict=True):
    """direction・post_time は元の値(raw)から読み直し、condition の後ろの斤量の決め(別定・定量・ハンデ・馬齢)を外す。"""
    al['direction'] = [norm_dir(x, strict) for x in raw.direction]
    al['post_time'] = [parse_pt(x) for x in raw.post_time]
    al['condition'] = [norm_cond(x) for x in raw.condition]
    return al


def races4(part, cols=None, strict=True):
    lo, hi, tp = SPAN4[part]
    ref = load_archive('races')
    a = ref.copy()
    if cols:
        a = a[cols]
    a = prep(a, a.copy(), strict)
    d = pd.concat([a] + [db_races(p, ref, cols, strict) for p in t3_open.SPAN[tp][2]], ignore_index=True)
    d['race_no'] = d.race_no.astype(int)
    if d.race_date.max() >= hi:
        raise SystemExit(f'⛔ races に {hi} 以降の行がある')
    return d


def load4(part):
    """(h, races): h = t3_open.sources の走り(見張り付き)、races = 新しい列を足したレースの表。"""
    lo, hi, tp = SPAN4[part]
    h = t3_open.sources(tp)
    t3_open.link_guard(h, lo)
    for c in ('jockey', 'trainer'):  # 細部 10(バグ直し): DB は 2022-11-03 から名前の空白を全角で書く → NFKC でそろえる
        h[c] = h[c].map(lambda x: unicodedata.normalize('NFKC', x) if isinstance(x, str) else x)
    return h, races4(part)


# ================================================================ 書き方の見張り
def fmt_counts(races, runs, lo, hi):
    """南関・[lo, hi) のレースと走りの書き方の数(races は races4 の形、direction は norm_dir(strict=False) 済み)。"""
    R = races[races.track.isin(NANKAN) & (races.race_date >= lo) & (races.race_date < hi)].copy()
    P = pd.DataFrame([t4_base.parse_name(n, c) for n, c in zip(R.race_name, R.condition)],
                     columns=['b_g', 'b_kumi', 'b_young', 'b_age', 'b_kind', 'k0', 'b_unread'], index=R.index)
    R = pd.concat([R, P], axis=1)
    R['b_prize'] = R.prize_yen.map(t4_base.prize)
    W = runs[runs.track.isin(NANKAN) & (runs.race_date >= lo) & (runs.race_date < hi)]
    wm = set(W.weight_mark.dropna().unique())
    oi = R[(R.track == '大井') & R.direction.isna()]
    return {'races': int(len(R)), 'unread': float(R.b_unread.mean()) if len(R) else 0.0,
            'unread_n': int(R.b_unread.sum()), 'unread_ex': list(R[R.b_unread == 1].race_name.astype(str).head(8)),
            'age_bad': int(R.b_age.isna().sum()), 'age_ex': sorted(set(R[R.b_age.isna()].condition.astype(str)))[:8],
            'prize_bad': int(R.b_prize.isna().sum()), 'pt_bad': int(R.post_time.isna().sum()),
            'dir_unknown': int((R.direction == '?').sum()), 'wm_unknown': sorted(wm - set(d3.H_MARK)),
            'oi_empty_by_year': {str(k): int(v) for k, v in oi.race_date.str[:4].value_counts().sort_index().items()},
            'oi_empty_2023': int((oi.race_date >= '2023-01-01').sum())}


def fmt_ok(c):
    return (c['unread'] <= 0.01 and c['age_bad'] == 0 and c['prize_bad'] == 0 and c['pt_bad'] == 0 and
            c['dir_unknown'] == 0 and not c['wm_unknown'] and c['oi_empty_2023'] == 0)


def guard_format(h, races, lo, hi):
    c = fmt_counts(races, h, lo, hi)
    if not fmt_ok(c):
        raise SystemExit('⛔ 書き方の見張りで止まる(知らない書き方・格の読めないレース・大井の回りの空)')


def guard_si(U, h, lo, hi):
    """欠けの見張り: SI(PREREG4 §9)と、細部 11 のテン指数・上がり指数・最初の角の位置。通ったときは数字を出さない。"""
    def check(D, col, name):
        D = D.assign(miss=D[col].isna())
        base = D[(D.year >= 2016) & (D.year <= 2021)].groupby('year').miss.mean().max()
        s = D[(D.race_date >= lo) & (D.race_date < hi)].groupby('year').miss.mean()
        if (s > base + 0.05).any():
            raise SystemExit(f'⛔ {name} の欠けの割合が 2016〜2021 の年ごとの最大 + 5 ポイントを超えた年がある')

    for col, name in (('SI', 'SI'), ('ten_i', 'テン指数'), ('up_i', '上がり指数')):
        check(U, col, name)
    r = h[h.track.isin(NANKAN) & ~h.finish_note.isin(['取消', '除外']) & (h.race_date >= '2014-01-01')]
    check(r.assign(year=r.race_date.str[:4].astype(int)), 'c1', '最初の角の位置(c1)')


def guard_transfer(T, lo, hi):
    ex = pd.read_parquet(d3.FEAT, columns=['race_date', 'year', 'l_jra', 'l_nar'])
    f = lambda d: ((d.l_jra == 1) | (d.l_nar == 1)).groupby(d.race_date.str[:7]).mean()
    base = f(ex[(ex.year >= 2016) & (ex.year <= 2021)]).max()
    s = f(T[(T.race_date >= lo) & (T.race_date < hi)])
    if (s > 1.5 * base).any():
        raise SystemExit('⛔ 転入の 1 戦目の割合が 2016〜2021 の月ごとの最大の 1.5 倍を超えた月がある(馬のつながりを確かめる)')


# ================================================================ 材料
def runs_of(h):
    r = h.drop(columns=[c for c in RACE_COLS + FACT_COLS + ['hid'] if c in h.columns]).rename(columns={'umaban': 'runner_number'})
    return r[r.track.isin(NANKAN) & (r.race_date >= '2014-01-01')].reset_index(drop=True)


def base_of(h, races):
    c = races[races.track.isin(NANKAN) & (races.race_date >= '2014-01-01')].reset_index(drop=True)
    return t4_base.build(runs_of(h), c, log=lambda *a: None)


def build4(h, races, lo, hi):
    """確かめる期間の第 4 版の材料の表(t4_day3.features と同じ作り方・[lo, hi) の予想する行)と t4_base の出力。"""
    U = base_of(h, races)
    tg = targets3(h)
    tgt = tg[(tg.race_date >= lo) & (tg.race_date < hi)].reset_index(drop=True)
    X3, _ = build3(h, tgt, tg)
    X3 = finish_table(X3, h, tg)
    T = d3.assemble(d3.feat_new(U, h, races, tg, tgt), X3)
    d = (T.h_j3 - T.h_j3_own).abs()
    assert (d.fillna(0) <= 1e-9).all() and (T.h_j3.isna() == T.h_j3_own.isna()).all(), 'h_j3 の作り直しが合わない'
    T = sort4(T[d3.META + d3.ALL])
    assert not d3.BANNED & set(d3.ALL) and T.race_date.min() >= lo and T.race_date.max() < hi
    return T, U


# ================================================================ 学び直しと予想
def train_v3(T3, lo):
    tr = sort4(T3[T3.race_date < lo])
    return {v: (t3_eval.train(tr, cols, 'Y1'), t3_eval.train(tr, cols, 'Y3')) for v, cols in t3_eval.VERSIONS.items()}


def train_v4(T4, lo):
    tr = sort4(T4[T4.race_date < lo])
    return {v: (train4(tr, C4[v], 'Y1'), train4(tr, C4[v], 'Y3')) for v in ('pre', 'day')}


def same_models(M, prefix):
    return all(M[v][i].model_to_string() == (MD / f'{prefix}_{v}_{t}.txt').read_text(encoding='utf-8')
               for v in ('pre', 'day') for i, t in enumerate(('Y1', 'Y3')))


def check_ref3(M3, lo):
    if lo in REF3 and not same_models(M3, REF3[lo]):
        raise SystemExit(f'⛔ 第 3 版の学び直し({lo} まで)が models/{REF3[lo]}_* と文字列で一致しない')


def seg_rows(T, lo, hi):
    return T[(T.race_date >= lo) & (T.race_date < hi)].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)


def assert_pair(t4, t3):
    a = t4[KEY + ['umaban', 'n']].reset_index(drop=True)
    b = t3[KEY + ['umaban', 'n']].reset_index(drop=True)
    b = b.astype(a.dtypes.to_dict())
    assert a.equals(b), '第 4 版と第 3 版の表で (場・日付・R・馬番) の組か n が一致しない'
    assert (t4.Y1.to_numpy() == t3.Y1.to_numpy()).all() and (t4.Y3.to_numpy() == t3.Y3.to_numpy()).all()


def run_segments(T4, T3, segs):
    """区切りごとに両版を直前までで学び直して予想。返す: {'v4pre': 予想の表, ...}・区切り ① の第 4 版の一致(記録)。"""
    P = {k: [] for k in ('v4pre', 'v4day', 'v3pre', 'v3day')}
    rec = {}
    for name, lo, hi in segs:
        t4, t3 = seg_rows(T4, lo, hi), seg_rows(T3, lo, hi)
        assert_pair(t4, t3)
        M3 = train_v3(T3, lo)
        check_ref3(M3, lo)
        M4 = train_v4(T4, lo)
        if lo in REF4:
            rec[name] = same_models(M4, REF4[lo])
        for v in ('pre', 'day'):
            P['v4' + v].append(t3_eval.predict(*M4[v], t4, C4[v]).assign(seg=name))
            P['v3' + v].append(t3_eval.predict(*M3[v], t3, t3_eval.VERSIONS[v]).assign(seg=name))
        print('区切り', name, '予想済み', flush=True)
    return {k: pd.concat(v, ignore_index=True) for k, v in P.items()}, rec


# ================================================================ 比べ方
def tables(P, T4):
    """版ごとのレースの表(t3_eval.race_table)に区切り・◎ が転入馬かを足す。"""
    tr = T4[KEY + ['umaban', 'l_jra', 'l_nar']]
    out = {}
    for k, x in P.items():
        R = t3_eval.race_table(x)
        R = R.merge(x[KEY + ['seg']].drop_duplicates(KEY), on=KEY, how='left')
        R = R.merge(tr.rename(columns={'umaban': 'top_uma'}), on=KEY + ['top_uma'], how='left')
        R['trans'] = R.l_jra.between(1, 5) | R.l_nar.between(1, 5)
        out[k] = R.drop(columns=['l_jra', 'l_nar'])
    return out


def verdict(lo, hi):
    return '上回った' if lo > 0 else ('下回った' if hi < 0 else '差は誤差の範囲')


def diff_boot(a, b):
    a, b = a.set_index(KEY), b.set_index(KEY)
    assert a.index.equals(b.index)
    D = (a[['win', 'top3', 'll1', 'll3']] - b[['win', 'top3', 'll1', 'll3']]).add_prefix('d_').reset_index()
    bb = t3_eval.boot(D, ['d_win', 'd_top3', 'd_ll1', 'd_ll3'])
    bb['verdict'] = verdict(bb['d_top3'][1], bb['d_top3'][2])
    return bb


def old_filter(te, old, notes):
    """区切り ⑤ の予想するレースのうち、旧 AI のファイルに予想する行の全馬があるレースだけを残す。除いた数を理由別に。"""
    have = old[KEY + ['umaban']].drop_duplicates().assign(_in=True)
    rf = old[KEY].drop_duplicates().assign(_rf=True)
    j = te[KEY + ['umaban']].merge(have, on=KEY + ['umaban'], how='left').merge(rf, on=KEY, how='left')
    j = j.merge(notes, on=KEY + ['umaban'], how='left')
    j['_in'] = j._in.fillna(False).astype(bool)
    j['_rf'] = j._rf.fillna(False).astype(bool)
    j['miss'] = ~j._in
    j['other'] = j.miss & (j.finish_note != '中止')
    g = j.groupby(KEY)
    r = pd.DataFrame({'rf': g._rf.first(), 'miss': g.miss.any(), 'other': g.other.any()})
    keep = r[r.rf & ~r.miss].reset_index()[KEY]
    why = {'ファイルに無いレース': int((~r.rf).sum()), '中止の馬だけが無い': int((r.rf & r.miss & ~r.other).sum()),
           'そのほかの馬が無い': int((r.rf & r.other).sum())}
    return keep, why, int(len(r))


def breakdown(tabs):
    rows = []
    ks = ('v4pre', 'v3pre', 'v4day', 'v3day')
    base = tabs['v4pre'].assign(year=tabs['v4pre'].race_date.astype(str).str[:4])
    base['era'] = np.where(base.year <= '2023', '2023 年以前', '2024 年以降')
    band = pd.cut(base.n, [0, 8, 12, 99], labels=['5〜8 頭', '9〜12 頭', '13 頭以上']).astype(str)
    groups = [('区切り', base.seg), ('年', base.year), ('場', base.track), ('頭数', band), ('制度', base.era)]
    for name, key in groups:
        for val in sorted(key.unique()):
            m = (key == val).to_numpy()
            rows.append([name, val, int(m.sum())] + [float(tabs[k].top3.to_numpy()[m].mean()) for k in ks] +
                        [float(np.nanmean(tabs['v4pre'].fav_top3.to_numpy()[m]))])
    for k in ('v4pre', 'v4day'):
        m = tabs[k].trans.to_numpy()
        rows.append([f'◎ が転入馬({VN[k[2:]]}の ◎)', '', int(m.sum())] +
                    [float(tabs[kk].top3.to_numpy()[m].mean()) for kk in ks] + [float(np.nanmean(tabs['v4pre'].fav_top3.to_numpy()[m]))])
    return rows


def report(P, T4, old, notes, rec, title):
    """md の行と判定。P = run_segments の予想。old = 旧 AI(区切り ⑤)。"""
    for k in P:
        P[k] = P[k].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    tabs = tables(P, T4)
    for k in tabs:
        assert tabs[k][KEY].equals(tabs['v4pre'][KEY])
    f = t3_eval.fmt
    S = {k: t3_eval.summary(R) for k, R in tabs.items()}
    nr = len(tabs['v4pre'])
    L = [f'# {title}', '', f"{nr:,} R・{len(P['v4pre']):,} 頭(確かめる期間の 2 回目の使用)。区間 = 開催日単位のブートストラップ 2,000 回の 95%。"
         '区切りごとに直前までの全部(2015〜)で両版を学び直した。', '',
         '| 版 | ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1(レースあたり)| 対数尤度 Y3 | 1 番人気 3 着以内率 |', '|---|---|---|---|---|---|']
    for k, nm in (('v4pre', '第 4 版 前日版'), ('v3pre', '第 3 版 前日版'), ('v4day', '第 4 版 当日版'), ('v3day', '第 3 版 当日版')):
        s = S[k]
        L.append(f"| {nm} | {f(s['win'])} | {f(s['top3'])} | {f(s['ll1'])} | {f(s['ll3'])} | {f(s['fav_top3'])} |")
    s = S['v4pre']
    L += [f"| 頭数だけ(段 0)| ― | ― | {s['base_ll1']:.3f} | {s['base_ll3']:.3f} | ― |", '',
          '## 第 3 版との比べ(§7・同じレースの対・第 4 版 − 第 3 版)', '',
          '| 版 | ◎ 3 着以内率の差(95% 区間)| 判定 | ◎ 勝率の差 | 対数尤度の差 Y1 | Y3 |', '|---|---|---|---|---|---|']
    V = {}
    for v in ('pre', 'day'):
        b = diff_boot(tabs['v4' + v], tabs['v3' + v])
        V[v] = b['verdict']
        L.append(f"| {VN[v]} | {f(b['d_top3'])} | **{b['verdict']}** | {f(b['d_win'])} | {f(b['d_ll1'])} | {f(b['d_ll3'])} |")
    better = all(x == '上回った' for x in V.values())
    L += ['', f"**「第 3 版より良い」: {'届いた(毎日の予想表を第 4 版に切り替える)' if better else '届かなかった(毎日の予想表は第 3 版のまま)'}**"
          '(前日版・当日版の両方で「上回った」)', '']
    # 旧 AI(区切り ⑤)
    L += ['## 旧 AI との比べ(§7・区切り ⑤・PREREG3 §6 の b_all・b_nankan・新 − 旧)', '']
    te5 = P['v4pre'][P['v4pre'].seg == '⑤']
    keep, why, nall = old_filter(te5, old, notes)
    L += [f"区切り ⑤ の予想するレース {nall:,} R のうち、旧 AI のファイルに出走した全馬(中止を含む)があるレース {len(keep):,} R で比べる。"
          '除いたレース: ' + '・'.join(f'{k} {v:,}' for k, v in why.items()) + '。', '',
          '| 版 | 旧 AI | レース | 新 ◎ 3 着以内率 | 旧 ◎ 3 着以内率 | 差(95% 区間)| 判定 | ◎ 勝率の差 | 対数尤度の差 Y1 | Y3 | 新 − 1 番人気 |',
          '|---|---|---|---|---|---|---|---|---|---|---|']
    vo = []
    for v in ('pre', 'day'):
        x = P['v4' + v][P['v4' + v].seg == '⑤'].merge(keep, on=KEY, how='inner')
        r = t3_eval.compare_old(x, old)
        for o in t3_eval.OLD:
            b = r[o]
            vo.append(b['verdict'])
            L.append(f"| {VN[v]} | {o} | {r['races']:,} | {b['top3'][0]:.3f} | {b['old_top3'][0]:.3f} | {f(b['d_top3'])} | "
                     f"**{b['verdict']}** | {f(b['d_win'])} | {f(b['d_ll1'])} | {f(b['d_ll3'])} | {f(b['d_fav_top3'])} |")
        L.append(f"({VN[v]}: 旧 AI の確率が空の馬がいたレース {r['races_lacking_old_rows']})")
    beat = all(x == '上回った' for x in vo)
    L += ['', f"**「旧 AI を超えた」(目標): {'届いた' if beat else '届かなかった'}**(前日版・当日版 × b_all・b_nankan の 4 つすべてで「上回った」)",
          '旧 AI は前日の情報だけで月ごとに学び直している。第 4 版の当日版は馬場・馬体重を使う。区切り ⑤ の第 4 版は 2025-08 までで 1 回だけ学んだ。', '',
          '## 内訳(§6・点だけ・記録)', '',
          '| 区分 | 値 | レース | 第 4 版 前日 | 第 3 版 前日 | 第 4 版 当日 | 第 3 版 当日 | 1 番人気 |', '|---|---|---|---|---|---|---|---|']
    for r in breakdown(tabs):
        L.append(f'| {r[0]} | {r[1]} | {r[2]:,} | ' + ' | '.join(f'{x:.3f}' for x in r[3:]) + ' |')
    L += ['', '見張り(§9): 書き方・格の読めないレース・SI の欠け・転入の 1 戦目・馬のつながり・第 3 版の区切り ①⑤ の模型の一致 = すべて通った。',
          f"第 4 版の区切り ① の模型と models/t4_* の一致(記録): {'一致' if rec.get('①') else '不一致'}", '']
    return L, {'better': better, 'beat': beat, 'v3': V, 'old': vo}


# ================================================================ formatcheck(4 日目)
def formatcheck():
    res = {}
    # ① RAW と DB(2020〜2021 の写し)の同じレース
    ref = load_archive('races')
    ra = ref[ref.track.isin(NANKAN) & (ref.race_date >= '2020-01-01')][RACE_SAFE].copy()
    ra = prep(ra, ra.copy(), False)
    rawdb = pd.read_parquet(V3 / 'db_check_2020_2021_races.parquet', columns=RACE_SAFE)
    db = prep(_align(rawdb, ref), rawdb, False)
    db = db[db.track.isin(NANKAN)]
    cols = ['b_g', 'b_kumi', 'b_young', 'b_age', 'b_kind', 'k0', 'b_unread']

    def parsed(R):
        P = pd.DataFrame([t4_base.parse_name(n, c) for n, c in zip(R.race_name, R.condition)], columns=cols, index=R.index)
        P['b_prize'] = R.prize_yen.map(t4_base.prize)
        P['post_time'] = R.post_time
        return pd.concat([R[KEY], P], axis=1)
    A, B = parsed(ra), parsed(db)
    J = A.merge(B, on=KEY, suffixes=('_r', '_d'))
    one = {}
    for c, nm in (('b_g', '格'), ('b_kumi', '組'), ('b_prize', '賞金'), ('b_age', '年齢条件'), ('post_time', '発走時刻'),
                  ('b_young', '若馬の区分(記録)'), ('b_kind', 'レースの種類(名前から・記録)')):
        a, b = J[c + '_r'].astype(float), J[c + '_d'].astype(float)
        eq = (a.isna() & b.isna()) | (np.abs(a - b) <= 1e-9)
        one[nm] = [float(eq.mean()), int((~eq).sum()), int(a.isna().sum()), int(b.isna().sum())]
    rr = load_archive('runs')
    rr = rr[rr.track.isin(NANKAN) & (rr.race_date >= '2020-01-01')][RUN_SAFE]
    rd = pd.read_parquet(V3 / 'db_check_2020_2021_runs.parquet', columns=RUN_SAFE)
    rd = rd[rd.track.isin(NANKAN)]
    JR = rr.merge(rd, on=KEY + ['runner_number'], suffixes=('_r', '_d'))
    mr, md_ = JR.weight_mark_r.map(d3.H_MARK).fillna(0), JR.weight_mark_d.map(d3.H_MARK).fillna(0)
    unk = sorted((set(JR.weight_mark_r.dropna()) | set(JR.weight_mark_d.dropna())) - set(d3.H_MARK))
    one['減量の印'] = [float((mr == md_).mean()), int((mr != md_).sum()), 0, 0]
    res['one'] = {'races_raw': int(len(A)), 'races_db': int(len(B)), 'races_join': int(len(J)), 'runs_join': int(len(JR)),
                  'items': one, 'wm_unknown': unk,
                  'dir_raw': {str(k): int(v) for k, v in ra.direction.value_counts(dropna=False).items()},
                  'dir_db': {str(k): int(v) for k, v in db.direction.value_counts(dropna=False).items()}}
    # ② 確認・封印・前向きの写しの結果でない列
    two = {}
    for p, lo, hi in (('confirm', '2022-01-01', '2025-09-01'), ('sealed', '2025-09-01', '2026-09-01'),
                      ('forward', '2026-09-01', '9999-12-31')):
        rawp = pd.read_parquet(V3 / f'db_races_{p}_{FILES[p]}.parquet', columns=RACE_SAFE)
        rawp = rawp[rawp.track.isin(NANKAN)]
        R = db_races(p, ref, RACE_SAFE, strict=False)
        W = pd.read_parquet(V3 / f'db_runs_{p}_{FILES[p]}.parquet', columns=RUN_SAFE)
        c = fmt_counts(R, W, lo, hi)
        pt_kind = rawp.post_time.map(lambda x: 'null' if x is None or (isinstance(x, float) and np.isnan(x))
                                     else re.sub(r'\d', '9', unicodedata.normalize('NFKC', str(x)).strip())).value_counts()
        c['pt_kinds'] = {str(k): int(v) for k, v in pt_kind.items()}
        c['dir_kinds'] = {f'{t}:{k}': int(v) for (t, k), v in rawp.assign(direction=rawp.direction.astype(str))
                          .groupby(['track', 'direction']).size().items()}
        c['cond_kinds'] = {str(k): int(v) for k, v in rawp.condition.value_counts(dropna=False).items()}
        c['prize_kinds'] = {str(k): int(v) for k, v in rawp.prize_yen.map(
            lambda x: 'null' if x is None else ('[数…]' if re.fullmatch(r'\[\d+(, \d+)*\]', str(x)) else str(x)[:20])).value_counts().items()}
        c['wm_kinds'] = {str(k): int(v) for k, v in W[W.track.isin(NANKAN)].weight_mark.value_counts(dropna=False).items()}
        c['ok'] = fmt_ok(c)
        two[p] = c
        print(p, c['races'], 'ok' if c['ok'] else 'NG', flush=True)
    res['two'] = two
    (V3 / 't4_day4_format.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    L = ['# 第 4 版 4 日目: 書き方の確かめ(PREREG4 §9 ①②・結果の列は読まない)', '',
         '台本 src/t4_open.py formatcheck。読み方は open・予想表と同じ関数(races4 の norm_dir・parse_pt・_align、t4_base.parse_name・prize)。', '',
         '## ① RAW と DB の写し(2020〜2021・南関)の同じレース', '',
         f"レース RAW {res['one']['races_raw']:,}・DB {res['one']['races_db']:,}・つながった {res['one']['races_join']:,}。"
         f"走り(減量の印)つながった {res['one']['runs_join']:,}。", '',
         '| 項目 | 一致 | 一致しない | RAW の欠け | DB の欠け | 線 99% |', '|---|---|---|---|---|---|']
    for nm, (r, bad, na, nb) in one.items():
        line = '―' if '記録' in nm else ('合' if r >= 0.99 else '否')
        L.append(f'| {nm} | {r:.4f} | {bad:,} | {na:,} | {nb:,} | {line} |')
    L += ['', f"知らない減量の印: {unk or 'なし'}。回り(RAW): {res['one']['dir_raw']}・(DB): {res['one']['dir_db']}(この写しでは両方とも空)", '',
          '## ② 確認・封印・前向きの写しの結果でない列(南関)', '',
          '| 写し | レース | 格の読めない(線 ≤ 1%)| 年齢条件の読めない(0)| 賞金の読めない(0)| 発走時刻の読めない(0)| 知らない回り(0)| 知らない減量の印(0)| 大井の回りが空(2023 年以降 0)| 合否 |',
          '|---|---|---|---|---|---|---|---|---|---|']
    for p, c in two.items():
        L.append(f"| {p} | {c['races']:,} | {c['unread']:.4f}({c['unread_n']})| {c['age_bad']} | {c['prize_bad']} | {c['pt_bad']} | "
                 f"{c['dir_unknown']} | {c['wm_unknown'] or 0} | {c['oi_empty_by_year'] or 0}(2023 年以降 {c['oi_empty_2023']})| "
                 f"{'合' if c['ok'] else '否'} |")
    L += ['', '### 値の種類(記録)', '']
    for p, c in two.items():
        L += [f"- {p}: 発走時刻の形 {c['pt_kinds']}/回り {c['dir_kinds']}/年齢条件 {c['cond_kinds']}/賞金の形 {c['prize_kinds']}/"
              f"減量の印 {c['wm_kinds']}", f"  - 格の読めないレースの例: {c['unread_ex']}/年齢条件の読めない例: {c['age_ex']}"]
    OUT_FMT.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


# ================================================================ dry(4 日目)
def dry():
    t3_eval.check_grid()
    lo, hi, _ = SPAN4['dry']
    h, races = load4('dry')
    guard_format(h, races, lo, hi)
    T, U = build4(h, races, lo, hi)
    ref = sort4(pd.read_parquet(d3.FEAT))
    r21 = ref[ref.year == 2021].reset_index(drop=True)
    assert T[KEY + ['umaban']].equals(r21[KEY + ['umaban']]), '馬の並びが違う'
    assert list(T.columns) == list(ref.columns), '列が違う'
    cols = ['n', 'Y1', 'Y3', 'pop'] + d3.ALL
    A, B = T[cols].to_numpy(float), r21[cols].to_numpy(float)
    eq = (np.isnan(A) & np.isnan(B)) | (np.abs(A - B) <= 1e-9)
    print(f'材料の一致(2021): {int(eq.sum()):,} / {eq.size:,}', flush=True)
    assert eq.all(), [c for c, k in zip(cols, eq.all(0)) if not k]
    guard_si(U, h, lo, hi)
    T4 = pd.concat([ref[ref.race_date < lo], T], ignore_index=True)
    guard_transfer(T4, lo, hi)
    T3 = pd.read_parquet(V3 / 'feat_t3_explore.parquet')
    P, rec = run_segments(T4, T3, [('2021', lo, hi)])
    # 区切り ① の第 3 版の学び直し(2015〜2021)が models/t3_* と一致するか
    check_ref3(train_v3(T3, '2022-01-01'), '2022-01-01')
    print('第 3 版の区切り ① の学び直し = models/t3_* と文字列一致', flush=True)
    for k in P:
        P[k] = P[k].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    tabs = tables(P, T4)
    z = diff_boot(tabs['v3pre'], tabs['v3pre'])
    assert all(abs(x) < 1e-12 for k in ('d_top3', 'd_win', 'd_ll1', 'd_ll3') for x in z[k]) and z['verdict'] == '差は誤差の範囲'
    print('第 3 版を自分自身と比べて差 0・判定', z['verdict'], flush=True)
    for v in ('pre', 'day'):
        b = diff_boot(tabs['v4' + v], tabs['v3' + v])
        print(f"(探索 2021・記録)第 4 版 − 第 3 版 {v}: ◎ 3 着以内率の差 {t3_eval.fmt(b['d_top3'])} {b['verdict']}", flush=True)
    # 旧 AI の比べ方: 第 4 版自身を b_all、頭数だけを b_nankan にしたファイルから、中止の馬と 1 頭を抜く
    notes = h[KEY + ['umaban', 'finish_note']].drop_duplicates(KEY + ['umaban'])
    x = P['v4pre'].merge(notes, on=KEY + ['umaban'], how='left')
    fake = x[KEY + ['umaban', 'n', 'p1', 'p3']].copy()
    fake['b_all_win'], fake['b_all_top3'] = fake.p1, fake.p3
    fake['b_nankan_win'], fake['b_nankan_top3'] = 1 / fake.n, 3 / fake.n
    stop = (x.finish_note == '中止').to_numpy()
    first_race = x[KEY].drop_duplicates().iloc[[0]]
    in_first = x.merge(first_race.assign(_f=True), on=KEY, how='left')._f.fillna(False).to_numpy().astype(bool)
    other = in_first & (x.umaban == x.umaban[in_first].max()).to_numpy()
    drop_race = x[KEY].drop_duplicates().iloc[[-1]]
    lack_race = x.merge(drop_race.assign(_f=True), on=KEY, how='left')._f.fillna(False).to_numpy()
    fk = fake[~stop & ~(other & ~stop) & ~lack_race]
    exp_stop = x[stop][KEY].drop_duplicates().merge(drop_race.assign(_f=1), on=KEY, how='left')
    exp_stop = exp_stop[exp_stop._f.isna()].drop(columns='_f')
    keep, why, nall = old_filter(P['v4pre'], fk, notes)
    ex_other = x[other & ~stop][KEY].drop_duplicates().merge(drop_race.assign(_f=1), on=KEY, how='left')
    ex_other = ex_other[ex_other._f.isna()].drop(columns='_f')
    e_stop = exp_stop.merge(ex_other.assign(_o=1), on=KEY, how='left')
    assert why['ファイルに無いレース'] == 1 and why['そのほかの馬が無い'] == len(ex_other) == 1
    assert why['中止の馬だけが無い'] == int(e_stop._o.isna().sum()), why
    assert len(keep) + sum(why.values()) == nall
    print('旧 AI の絞り: 理由別', why, '/ 全', nall, flush=True)
    r = t3_eval.compare_old(P['v4pre'].merge(keep, on=KEY), fk)
    assert r['races'] == len(keep) and r['races_lacking_old_rows'] == 0
    assert all(abs(v) < 1e-12 for k in ('d_top3', 'd_win', 'd_ll1', 'd_ll3') for v in r['b_all'][k])
    assert r['b_all']['verdict'] == '差は誤差の範囲' and r['b_nankan']['verdict'] == '上回った'
    L, J = report(P, T4, fk, notes, rec, 'dry(書き出さない)')
    assert any('「第 3 版より良い」' in s for s in L) and any('「旧 AI を超えた」' in s for s in L)
    assert sum(s.startswith(('| 前日版 | b_', '| 当日版 | b_')) for s in L) == 4
    print('dry OK', flush=True)


# ================================================================ open(5 日目・判断の日)
def open_():
    if OUT_OPEN.exists():
        raise SystemExit('⛔ 確かめる期間は開けてある(1 回だけ)')
    verify()
    t3_eval.check_grid()
    lo, hi, _ = SPAN4['open']
    h, races = load4('open')
    guard_format(h, races, lo, hi)
    T, U = build4(h, races, lo, hi)
    guard_si(U, h, lo, hi)
    T.to_parquet(FEAT_OPEN, index=False)
    ex = pd.read_parquet(d3.FEAT)
    T4 = pd.concat([ex, T[ex.columns]], ignore_index=True)
    assert not T4.duplicated(KEY + ['umaban']).any()
    guard_transfer(T4, lo, hi)
    parts = [pd.read_parquet(V3 / f'feat_t3_{p}.parquet') for p in ('explore', 'confirm', 'sealed')]
    T3 = pd.concat([parts[0]] + [p[parts[0].columns] for p in parts[1:]], ignore_index=True)
    assert not T3.duplicated(KEY + ['umaban']).any()
    print('見張り OK', flush=True)
    P, rec = run_segments(T4, T3, SEGS)
    notes = h[KEY + ['umaban', 'finish_note']].drop_duplicates(KEY + ['umaban'])
    L, J = report(P, T4, t3_eval.load_old(t3_open.OLD_MONTHS), notes, rec,
                  '第 4 版 5 日目: 確かめる期間(2022-01〜2026-08・5 区切り)を 1 回だけ開ける')
    OUT_OPEN.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    {'fit': fit, 'formatcheck': formatcheck, 'dry': dry, 'open': open_}[sys.argv[1]]()
