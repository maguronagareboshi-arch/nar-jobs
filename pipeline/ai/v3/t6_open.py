# -*- coding: utf-8 -*-
"""第 6 版 4 日目・5 日目(判断の日)の台本(PREREG6 §1・§2・§5・§6・§7・§9)。4 日目に sha256 で固定する。値を見て形・設定・材料は変えない。
t3_*・t4_*・t5_*・t6_base.py・t6_day3.py は直さずに呼ぶ。

  py -3.12 -X utf8 src/t6_open.py fit    # 4 日目: 2015〜2021 で第 6 版の前日版・当日版 × Y1・Y3 を 2 回ずつ学習(文字列の一致)→ models/t6_*.txt
  py -3.12 -X utf8 src/t6_open.py fmt    # 4 日目: §9 の書き方の確かめ ①② → out/t6_day4_format.md・v3/t6_day4_format.json
  py -3.12 -X utf8 src/t6_open.py dry    # 4 日目: 探索の 2021 だけで、open と同じ道を通す通し試験(RAW の道だけ・表は出さない)
  py -3.12 -X utf8 src/t6_open.py open   # 5 日目(判断の日)だけ: 確かめる期間(2022-01〜2026-08)を 1 回だけ開ける(4 回目の使用)→ out/t6_day5_open.md

■ 決め書に無い細部(4 日目に決めた。開ける前。見た後は変えない。変えてよいのはバグ直しだけ)
  1. 読み込み = t4_open.load4(part)(t3_open.sources の走り h・link_guard・騎手/調教師の NFKC)。4 列の元の走り = h のうち
     2013-01-01 以降(t6_base.load_h と同じ切り方。最初の日 ≥ 2014-01-01・最後の日 < 区間の終わりを assert)→ t6_base.starts → t6_base.cols4。
     付ける行 = open では v3/feat_t5_open.parquet の全行、dry では feat_t5_explore の 2021 の行。どの行も走りの表にあること・
     bw_diff の今回の体重 o_bw と走りの表の body_weight が同じ行で一致(両方欠けも一致)を assert。
  2. 材料の表 = 付ける行の表 + 4 列(feat_t6_explore と同じ列の順)。open は v3/feat_t6_open.parquet に保存(6 日目の学び直し用)。
  3. 見張り (2)(PREREG6 §9・4 列の元の走り・全 NAR・区間の年 × 南関/南関以外。通ったときは数字を出さない):
     (a) 取消・除外を除く出走で、着順があるのに 1〜そのレースの出走数(取消・除外を除く)の整数でない = 0
     (b) 着順のあるレースのうち着順 1 の馬がいないレースの割合 ≤ 0.01(2016〜2021 の年ごとの最大 0 + 0.01)
     (c) 着順も注記も無い出走(取消・除外も含む全行が分母)≤ 0.01。**細部 12 で 2 つに分けた**(c1)(c2)
     (d) 1 月のつながり = その年の 1 月の出走(取消・除外を除く・出走の単位)のうち、その馬(馬の鍵 hid)にその日より前の全 NAR の
         出走(取消・除外を除く・2014〜)がある割合 ≥ 南関 0.945・南関以外 0.963。バグ直し(4 日目 fmt・開ける前): はじめ「馬の単位・
         1 月 1 日より前」で数えて 1 日目の値と合わなかった(RAW 2016〜2021 の最小 0.9541・0.9649)→ 出走の単位・その日より前にすると
         1 日目の値(0.9653〜0.9751・0.9827〜0.9887)と 4 桁で一致したので、これに直した(線は動かしていない)。
     (e) 馬体重があって 300 kg 未満か 700 kg 超(0 以下を含む)の出走 = 0 (f) 同じ日に 2 回以上出走する馬の鍵 = 0(cols4 の assert も全期間で見る)
  4. 見張り (3): 付けた行の区間の年ごとと区切りごと(open は t4_open.SEGS の 5 つ、dry は 2021 を 1 つ)に、h2h のある割合 ≥ 0.751・
     elo_z ≥ 0.905・nori_ch = 1 の割合 ≥ 0.091・nori_dr = 1 ≥ 0.100。bw_diff は最終形に入らなかった(t6_grid.json)ので作るが見張らない。
  5. 旧 AI の絞りの見張り = 区切り ⑤ の付けた行を t4_open.old_filter に通して残るレースが 3,163(第 4・5 版 5 日目と同じ)。
  6. 保存した予想の確かめ(§7): ◎ = p1 の 1 位(同じなら p3 → 馬番・t6_day3.rtab)の 3 着以内率を 4 桁と 3 桁の文字列にして定数 REF7 と比べる。
     dry では v3/t5_day3_preds の 2021 を t5_day3_res.json の line.metrics の top3_2021 と == で比べる。
  7. 第 6 版の学び直し = feat_t6_explore + feat_t6_open のうち区切りの始まりより前・並べ方 t4_open.sort4・設定 v3/t6_grid.json
     (前日版 = kept 118 列・当日版 = kept_day 121 列・Y1 31/500/400・Y3 15/100/1200)・t4_day3.BASE・初期値 logit(1/n)・logit(3/n)。
     区切り ① の 4 本が models/t6_* と文字列一致しなければ止まる。予想 = t3_eval.predict の p1・p3 → t6_day3.p3p(= t6_base.p3prime・
     合計 3 と順の assert つき)の p3′ → ◎ = p3′ → p1 → 馬番(t6_day3.rtab)。
  8. 比べ = t6_day3.rtab のレースの表(第 6 版: ◎ = p3′ の 1 位・Y3 の対数尤度 = p3′。第 5・4 版: ◎ = p1 の 1 位・Y3 = p3)を KEY の順に
     t4_open.diff_boot(t3_eval.boot・開催日 2,000 回・seed 0)。対数尤度の差 Y3 は p3′ − p3 なので記録だけ。
  9. compare_old6 = t3_eval.compare_old の写し。変えたのは新 AI のレースの表だけ(◎ = p3′ → p1 → 馬番・Y3 の対数尤度 = p3′)。
     旧 AI の ◎ = b_*_win の 1 位(同じなら馬番)のまま。記録用に旧 AI の ◎ を max(b_*_top3, 旧 AI の p1)の 1 位(同じなら馬番)にした
     差(d_top3_b)も出す。
  10. fmt の読み方 = t3_open.sources の書き方のそろえ(_align・取消などの書き方・馬の鍵「名前|生年」・hid)と load4 の騎手の NFKC を写した
      norm_h。確かめる期間・封印の写しは結果でない列(場・日付・R・馬番・馬名・騎手・馬体重・着順の注記・馬の鍵)だけを読む。
      着順の注記は種類だけを出す。dry で norm_h の RAW が load4('dry') の h と同じ列で一致することを確かめる。
  11. fmt ① = RAW と v3/db_check_2020_2021_runs・run_facts(南関 2020〜2021・KEY + 馬番でつなぐ)。着順・着順の注記・騎手(NFKC)・
      馬体重・馬の鍵(horse_key)が同じ値か両方欠け。fmt ② の騎手名のつながり・馬体重のある割合は t6_base 細部 6 と同じ定義(分母 = 取消・
      除外を除く出走・騎手名が欠けはつながらない)。線は 2 日目の値(2016〜2021 の年ごとの最小 − 0.05)。
  12. 見張り (2)(c) を分ける(ユーザー承認 2026-09-27・第 5 版の細部 15 と同じ形): open の 1 回目が (c) で止まった(数字は出ていない)。
      原因(形だけ見た)= DB の写しには開催を取りやめたレース(races.cancelled = refund・nosale)の出走が「着順も注記も無い行」として
      残る(全頭の着順も注記も無いレース 354〔南関 93・南関以外 261〕のうち 346 に取りやめの印。南関の 93 は予想するレースに入らない)。
      RAW(〜2021)にはほぼ無い(全頭無いレースの割合 南関 0・南関以外 最大 0.0012)。バグではなくデータの違いなので:
      (c1) 全頭の着順も注記も無いレース(取消・除外を除く出走が全頭とも着順も注記も無い)を除いたレースの行で、着順も注記も無い行 ≤ 0.01(元の線)
      (c2) 全頭の着順も注記も無いレースの割合(取消・除外を除く出走がいるレースが分母)が、年ごとに 2016〜2021 の最大 + 0.05 以下
           (南関 0 + 0.05 = 0.05・南関以外 0.0012 + 0.05 = 0.0512)
      材料の作り方は変えない(そのレースは全頭同じ着順のまま。直接対決は同着を数えないので変わらず、Elo は少し平らになるが、
      損をするのは第 6 版の側)。
"""
import json
import sys
import unicodedata
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_eval  # noqa: E402
import t3_open  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t6_base  # noqa: E402
import t6_day3  # noqa: E402
from day5_forward_features import _align  # noqa: E402
from load_outcomes import load_archive  # noqa: E402

V3 = o.V3
REPO = o.REPO
MD = o.MD
FEAT5X = V3 / 'feat_t5_explore.parquet'
FEAT6X = t6_base.FEAT6
FEAT5O = V3 / 'feat_t5_open.parquet'
FEAT6O = V3 / 'feat_t6_open.parquet'
PRED5X = V3 / 't5_day3_preds.parquet'
PRED5O = V3 / 't5_day5_preds_open.parquet'
PRED6X = V3 / 't6_day3_preds.parquet'
PRED6O = V3 / 't6_day5_preds_open.parquet'
RES5 = V3 / 't5_day3_res.json'
OUT_OPEN = REPO / 'out/t6_day5_open.md'
OUT_FMT = REPO / 'out/t6_day4_format.md'
FMT_JSON = V3 / 't6_day4_format.json'
KEY, NANKAN, CANCEL = d3.KEY, d3.NANKAN, o.CANCEL
NEW4 = t6_base.NEW4
SPAN, SEGS, VN = o.SPAN4, o.SEGS, o.VN
END = '2026-09-01'
OLD_RACES = 3163
# §7: 保存した予想の ◎ 3 着以内率(LEDGER の第 5 版 5 日目の反証の後半 = 4 桁・out/t5_day5_open.md = 3 桁)
REF7 = {'v5pre': ('0.6885', '0.689'), 'v5day': ('0.6888', '0.689'), 'v4pre': ('0.6826', '0.683'), 'v4day': ('0.6868', '0.687')}
# §9 ② の線(2 日目に作る期間で数えた 2016〜2021 の年ごとの最小 − 0.05・1 月のつながりは 1 日目の最小 − 0.02)
FMT_LINE = {'jlink': {'nankan': 0.9486, 'other': 0.9492}, 'bw': {'nankan': 0.9487, 'other': 0.9459},
            'jan': {'nankan': 0.945, 'other': 0.963}}
JAN_BASE = {'nankan': 0.9653, 'other': 0.9827}  # 1 日目の 2016〜2021 の最小(記録の照らし合わせだけ)
NOTES5 = {'取消', '除外', '中止', '失格', '降着'}
W3 = {'h2h': 0.751, 'elo_z': 0.905, 'nori_ch1': 0.091, 'nori_dr1': 0.100}
NOWIN_LINE, NOFIN_LINE = 0.01, 0.01
EMPTY_LINE = {'nankan': 0.05, 'other': 0.0512}  # 細部 12 (c2): 2016〜2021 の最大(南関 0・南関以外 0.0012)+ 0.05
RUN6 = KEY + ['runner_number', 'horse_name', 'jockey', 'body_weight', 'finish_note']
FACT6 = KEY + ['umaban', 'horse_key']
KS = ('v6pre', 'v5pre', 'v4pre', 'v6day', 'v5day', 'v4day')
NM = {'v6pre': '第 6 版 前日版', 'v5pre': '第 5 版 前日版', 'v4pre': '第 4 版 前日版', 'v6day': '第 6 版 当日版',
      'v5day': '第 5 版 当日版', 'v4day': '第 4 版 当日版', 's0': '頭数だけ(段 0)'}


def stop(msg):
    raise SystemExit('⛔ ' + msg)


# ================================================================ 設定
def grid6():
    g = json.loads((V3 / 't6_grid.json').read_text(encoding='utf-8'))
    g5 = json.loads((V3 / 't5_grid.json').read_text(encoding='utf-8'))
    assert g['kept'] == list(g5['kept']) + ['h2h', 'elo_z', 'nori'] and len(g['kept']) == 118, 't6_grid.json の kept が違う'
    assert g['kept_day'] == g['kept'] + d3.FEATS4[6] and len(g['kept_day']) == 121, 't6_grid.json の kept_day が違う'
    assert tuple(g['Y1']) == (31, 500, 400) and tuple(g['Y3']) == (15, 100, 1200), 't6_grid.json の設定が違う'
    return {'pre': list(g['kept']), 'day': list(g['kept_day'])}, {'Y1': tuple(g['Y1']), 'Y3': tuple(g['Y3'])}


C6, CFG6 = grid6()


def train6(df, cols, target):
    assert len(cols) == len(set(cols)) and not d3.BANNED & set(cols)
    cfg = CFG6[target]
    z = d3.logit((1 if target == 'Y1' else 3) / df.n.to_numpy(float))
    prm = dict(d3.BASE, num_leaves=cfg[0], min_data_in_leaf=cfg[1])
    return lgb.train(prm, lgb.Dataset(df[cols].astype(float), label=df[target].to_numpy(float), init_score=z),
                     num_boost_round=cfg[2])


def train_v6(T6, lo):
    tr = o.sort4(T6[T6.race_date < lo])
    return {v: (train6(tr, C6[v], 'Y1'), train6(tr, C6[v], 'Y3')) for v in ('pre', 'day')}


def nk(df):
    df = df.copy()
    df['race_date'] = df.race_date.astype(str)
    df['race_no'] = df.race_no.astype(int)
    df['umaban'] = df.umaban.astype(int)
    return df


# ================================================================ fit(4 日目)
def fit():
    df = o.sort4(pd.read_parquet(FEAT6X))
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < '2022-01-01'
    meta = {'train': '2015-01-01〜2021-12-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]),
            'cfg': {k: list(v) for k, v in CFG6.items()}, 'files': {}}
    for v, cols in C6.items():
        for t in ('Y1', 'Y3'):
            s1, s2 = train6(df, cols, t).model_to_string(), train6(df, cols, t).model_to_string()
            if s1 != s2:
                stop(f'2 回の学習が一致しない: {v} {t}')
            fp = MD / f't6_{v}_{t}.txt'
            fp.write_text(s1, encoding='utf-8', newline='\n')
            meta['files'][fp.name] = {'cols': cols}
            print(v, t, '2 回の学習が文字列で一致', len(cols), '列', flush=True)
    (MD / 't6_models.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print('行', meta['rows'], 'レース', meta['races'], flush=True)


# ================================================================ 4 列
def build6(h, F, hi):
    """F(KEY・馬番・o_bw・year を持つ付ける行)に 4 列を付けた表と、見張り・記録用の部品。"""
    h = h[h.race_date >= '2013-01-01'].reset_index(drop=True)
    assert h.race_date.min() >= '2014-01-01' and h.race_date.max() < hi, (h.race_date.min(), h.race_date.max())
    st = t6_base.starts(h)
    F = nk(F).reset_index(drop=True)
    T = t6_base.cols4(st, F)
    assert T.rid.notna().all(), '付ける行に走りの表に無い行がある'
    assert t6_base.eqmask(T.o_bw, T.body_weight).all(), 'o_bw と走りの表の馬体重が一致しない'
    out = F.copy()
    for c in NEW4:
        out[c] = T[c].to_numpy()
    aux = F[KEY + ['umaban']].assign(year=F.race_date.str[:4], nori_ch=T.nori_ch.to_numpy(), nori_dr=T.nori_dr.to_numpy(),
                                     rentou=(T.dn - T.prev_dn == 1).to_numpy())
    return out, aux, h, st


# ================================================================ 見張り
def area_year(x):
    return x.assign(area=np.where(x.track.isin(NANKAN), 'nankan', 'other'), year=x.race_date.str[:4])


def jan_rates(s, years):
    """1 月のつながり(細部 3 (d))。s = 取消・除外を除く出走(area・year つき・2014〜の全部)。"""
    first = s.groupby('hid').race_date.min()
    out = {}
    for (ar, y), g in s[s.race_date.str[5:7] == '01'].groupby(['area', 'year']):
        if y in years:
            out[(ar, y)] = float((g.hid.map(first) < g.race_date).mean())
    return out


def guard_runs(h, lo, hi):
    """見張り (2)。通ったときは数字を出さない。"""
    a = area_year(h)
    x = a[(a.race_date >= lo) & (a.race_date < hi)].copy()
    years = sorted(x.year.unique())
    s = x[~x.finish_note.isin(CANCEL)].copy()
    s['nst'] = s.groupby(KEY).umaban.transform('size')
    f = s.finish.astype(float)
    if (f.notna() & ((f != np.floor(f)) | (f < 1) | (f > s.nst))).any():
        stop('見張り (2): 着順が 1〜出走数の整数でない出走がある')
    s['w1'], s['hasf'] = (f == 1).to_numpy(), f.notna().to_numpy()
    g = s.groupby(['area', 'year'] + KEY)[['w1', 'hasf']].any()
    g = g[g.hasf]
    if len(g) and ((~g.w1).groupby(level=['area', 'year']).mean() > NOWIN_LINE).any():
        stop('見張り (2): 勝ち馬のいないレースの割合が 0.01 を超えた')
    s['nof'] = (s.finish.isna() & s.finish_note.isna()).to_numpy()
    e = s.groupby(['area', 'year'] + KEY).nof.all()  # 細部 12: 全頭の着順も注記も無いレース
    if any(v > EMPTY_LINE[ar] for (ar, _y), v in e.groupby(level=['area', 'year']).mean().items()):
        stop('見張り (2)(c2): 全頭の着順も注記も無いレースの割合が線を超えた')
    ek = pd.MultiIndex.from_frame(e[e].reset_index()[KEY])
    xe = x[~pd.MultiIndex.from_frame(x[KEY]).isin(ek)]
    nf = (xe.finish.isna() & xe.finish_note.isna()).groupby([xe.area, xe.year]).mean()
    if (nf > NOFIN_LINE).any():
        stop('見張り (2)(c1): 着順も注記も無い出走が 1% を超えた')
    sa = area_year(h[~h.finish_note.isin(CANCEL)])
    for (ar, y), r in jan_rates(sa, years).items():
        if r < FMT_LINE['jan'][ar]:
            stop('見張り (2): 1 月のつながりが線を下回った')
    bw = s.body_weight.astype(float)
    if (bw.notna() & ((bw < 300) | (bw > 700))).any():
        stop('見張り (2): 馬体重が 300 kg 未満か 700 kg 超の出走がある')
    if int(s[s.hid.notna()].duplicated(['hid', 'race_date']).sum()):
        stop('見張り (2): 同じ日に 2 回以上出走する馬の鍵がある')


def seg_of(dates, segs):
    s = pd.Series([None] * len(dates), index=dates.index, dtype=object)
    for name, lo, hi in segs:
        s[(dates >= lo) & (dates < hi)] = name
    return s


def guard_cols(T6, aux, lo, hi, segs):
    """見張り (3)(最終形に入った列だけ)。通ったときは数字を出さない。"""
    m = ((T6.race_date >= lo) & (T6.race_date < hi)).to_numpy()
    X = pd.DataFrame({'year': aux.year.to_numpy()[m], 'seg': seg_of(T6.race_date[m], segs).to_numpy(),
                      'h2h': T6.h2h.notna().to_numpy()[m], 'elo_z': T6.elo_z.notna().to_numpy()[m],
                      'nori_ch1': (aux.nori_ch == 1).to_numpy()[m], 'nori_dr1': (aux.nori_dr == 1).to_numpy()[m]})
    assert X.seg.notna().all()
    for by in ('year', 'seg'):
        r = X.groupby(by)[list(W3)].mean()
        for c, line in W3.items():
            if (r[c] < line).any():
                stop(f'見張り (3): {c} の割合が線を下回った({by})')


# ================================================================ 予想・比べ
def seg_v6(T6, segs):
    P, info = {'v6pre': [], 'v6day': []}, {}
    for name, lo, hi in segs:
        M = train_v6(T6, lo)
        if lo == '2022-01-01' and not o.same_models(M, 't6'):
            stop('第 6 版の区切り ① の学び直しが models/t6_* と文字列で一致しない')
        t = o.seg_rows(T6, lo, hi)
        for v in ('pre', 'day'):
            x = t3_eval.predict(*M[v], t, C6[v])
            q, dl = t6_day3.p3p(x, x.p3.to_numpy())
            P['v6' + v].append(x.assign(p3p=q, seg=name))
            info[(name, v)] = (float(dl.min()), float(dl.max()))
        print('第 6 版 区切り', name, '予想済み', flush=True)
    return {k: pd.concat(v, ignore_index=True).sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
            for k, v in P.items()}, info


BASEC = KEY + ['umaban', 'seg', 'n', 'Y1', 'Y3', 'pop', 'l_debut', 'l_jra', 'l_nar']


def saved_frames(base, S, names):
    """base = 第 6 版の予想の行、S = 保存した予想、names = {版: (p1 の列, p3 の列)} → 同じ行の並びの表。"""
    b = base[BASEC]
    S = nk(S)
    out = {}
    for k, (c1, c3) in names.items():
        x = b.merge(S[KEY + ['umaban', c1, c3]].rename(columns={c1: 'p1', c3: 'p3'}), on=KEY + ['umaban'], how='left',
                    validate='1:1')
        assert x.p1.notna().all() and x.p3.notna().all(), f'{k} の保存した予想に無い行がある'
        out[k] = x
    return out


def tab_of(k, x):
    p1 = x.p1.to_numpy()
    if k.startswith('v6'):
        R = t6_day3.rtab(x, p1, x.p3p.to_numpy(), x.p3p.to_numpy(), p1, p3raw=x.p3.to_numpy())
    elif k == 's0':
        n = x.n.to_numpy(float)
        R = t6_day3.rtab(x, 1 / n, 3 / n, np.zeros(len(x)), np.zeros(len(x)))
    else:
        R = t6_day3.rtab(x, p1, x.p3.to_numpy(), p1, x.p3.to_numpy())
    R = R.merge(x[KEY + ['seg']].drop_duplicates(KEY), on=KEY, how='left')
    tr = x[KEY + ['umaban', 'l_jra', 'l_nar']].rename(columns={'umaban': 'top_uma'})
    R = R.merge(tr, on=KEY + ['top_uma'], how='left')
    R['trans'] = R.l_jra.between(1, 5) | R.l_nar.between(1, 5)
    return R.drop(columns=['l_jra', 'l_nar'])


def tabs_of(P):
    T = {k: tab_of(k, P[k]) for k in KS}
    T['s0'] = tab_of('s0', P['v6pre'])
    for k in T:
        assert T[k][KEY].equals(T['v6pre'][KEY])
    return T


def saved_top3(x):
    """◎ = p1 → p3 → 馬番の 3 着以内率(§7 の確かめ)。"""
    return float(t6_day3.rtab(x, x.p1.to_numpy(), x.p3.to_numpy(), x.p1.to_numpy(), x.p3.to_numpy()).top3.mean())


def compare_old6(te, old, B=2000):
    """t3_eval.compare_old の写し(細部 9)。te = 新 AI の予想(p1・p3・p3p・Y1・Y3・pop つき)。"""
    OLD = t3_eval.OLD
    races_old = old[KEY].drop_duplicates()
    te = te.merge(races_old, on=KEY, how='inner')
    oc = [f'{ob}_{t}' for ob in OLD for t in ('win', 'top3')]
    j = te.merge(old[KEY + ['umaban'] + oc], on=KEY + ['umaban'], how='left')
    grp = [j[k] for k in KEY]
    lack = int(j[j[oc].isna().any(axis=1).groupby(grp).transform('any')][KEY].drop_duplicates().shape[0])
    new = t6_day3.rtab(j, j.p1.to_numpy(), j.p3p.to_numpy(), j.p3p.to_numpy(), j.p1.to_numpy())  # 変えたところ
    res = {'races': len(new), 'races_lacking_old_rows': lack}
    for ob in OLD:
        w = j[f'{ob}_win'].fillna(-1.0)
        pw = j[f'{ob}_win'].to_numpy(float)
        p1o = pw / pd.Series(pw, index=j.index).groupby([j[k] for k in KEY]).transform('sum').to_numpy()
        p3o = np.maximum(j[f'{ob}_top3'].to_numpy(float), p1o)
        jo = j.assign(o_w=w, o_p1=p1o, o_p3=np.where(np.isnan(p3o), np.nan, p3o), o_t=np.where(np.isnan(p3o), -1.0, p3o))
        top = jo.sort_values(KEY + ['o_w', 'umaban'], ascending=[True, True, True, False, True],
                             kind='mergesort').groupby(KEY, sort=False).head(1).set_index(KEY)
        topb = jo.sort_values(KEY + ['o_t', 'umaban'], ascending=[True, True, True, False, True],
                              kind='mergesort').groupby(KEY, sort=False).head(1).set_index(KEY)
        R = new.set_index(KEY).copy()
        R['old_win'], R['old_top3'] = top.Y1, top.Y3
        R['old_top3_b'] = topb.Y3
        miss = j[[f'{ob}_win', f'{ob}_top3']].isna().any(axis=1).groupby(grp).transform('any')
        ok = jo[~miss]
        ro = t3_eval.race_table(ok.assign(p1=ok.o_p1, p3=ok.o_p3)).set_index(KEY)
        R['d_top3'] = R.top3 - R.old_top3
        R['d_win'] = R.win - R.old_win
        R['d_ll1'] = R.ll1 - ro.ll1
        R['d_ll3'] = R.ll3 - ro.ll3
        R['d_fav_top3'] = R.top3 - R.fav_top3
        R['d_top3_b'] = R.top3 - R.old_top3_b
        b = t3_eval.boot(R.reset_index(), ['top3', 'old_top3', 'd_top3', 'd_win', 'd_ll1', 'd_ll3', 'd_fav_top3',
                                           'old_top3_b', 'd_top3_b'], B)
        lo, hi = b['d_top3'][1], b['d_top3'][2]
        b['verdict'] = '上回った' if lo > 0 else ('下回った' if hi < 0 else '差は誤差の範囲')
        res[ob] = b
    return res


# ================================================================ 記録
def breakdown6(tabs):
    rows = []
    base = tabs['v6pre'].assign(year=tabs['v6pre'].race_date.astype(str).str[:4])
    base['era'] = np.where(base.year <= '2023', '2023 年以前', '2024 年以降')
    band = pd.cut(base.n, [0, 8, 12, 99], labels=['5〜8 頭', '9〜12 頭', '13 頭以上']).astype(str)
    fav = tabs['v6pre'].fav_top3.to_numpy()
    for name, key in [('区切り', base.seg), ('年', base.year), ('場', base.track), ('頭数', band), ('制度', base.era)]:
        for val in sorted(key.unique()):
            m = (key == val).to_numpy()
            rows.append([name, val, int(m.sum())] + [float(tabs[k].top3.to_numpy()[m].mean()) for k in KS] +
                        [float(np.nanmean(fav[m]))])
    for k in ('v6pre', 'v6day'):
        m = tabs[k].trans.to_numpy()
        rows.append([f'◎ が転入馬({VN[k[2:]]}の ◎)', '', int(m.sum())] + [float(tabs[kk].top3.to_numpy()[m].mean()) for kk in KS] +
                    [float(np.nanmean(fav[m]))])
    return rows


def kinds6(P, tabs):
    x = P['v6pre']
    ty = x.groupby(KEY).agg(deb=('l_debut', lambda s: (s == 1).any()), tj=('l_jra', lambda s: (s == 1).any()),
                            tn=('l_nar', lambda s: (s == 1).any())).reset_index()
    ty['kind'] = np.where(ty.deb, '初出走の馬がいる', np.where(ty.tj | ty.tn, '転入初戦の馬がいる(初出走なし)', 'どちらもいない'))
    out = []
    for k in KS:
        Rk = tabs[k].merge(ty[KEY + ['kind']], on=KEY, how='left')
        Rk = Rk[Rk.fav_top3.notna()]
        for kk, g in Rk.groupby('kind'):
            out.append([NM[k], kk, int(len(g)), float(g.win.mean()), float(g.top3.mean()), float(g.fav_top3.mean())])
    return out


def calib6(x):
    out = {}
    for nm, p, y, e in (('p1', 'p1', 'Y1', [0, .05, .1, .2, .3, .5, 1.01]), ('p3′', 'p3p', 'Y3', [0, .1, .2, .4, .6, .8, 1.01])):
        out[nm] = [(str(a), int(len(b)), float(b[p].mean()) if len(b) else None, float(b[y].mean()) if len(b) else None)
                   for a, b in x.groupby(pd.cut(x[p], e, right=False), observed=False)]
    return out


def report6(P, old, notes, aux, info, title, use):
    tabs = tabs_of(P)
    f = t3_eval.fmt
    S = {k: t3_eval.boot(R, ['win', 'top3', 'll1', 'll3', 'fav_win', 'fav_top3'] + (['ll3r'] if 'll3r' in R else []))
         for k, R in tabs.items()}
    nr = len(tabs['v6pre'])
    L = [f'# {title}', '',
         f"{nr:,} R・{len(P['v6pre']):,} 頭({use})。区間 = 開催日単位のブートストラップ 2,000 回の 95%。第 6 版は区切りごとに直前までの全部"
         '(2015〜)で学び直した。第 5 版・第 4 版は 3 回目に同じ学び方をして保存した予想(v3/t5_day5_preds_open.parquet)。'
         '第 6 版の ◎ = 3 着以内の確率 p3′(合計 3)の 1 位、第 5 版・第 4 版の ◎ = 勝つ確率 p1 の 1 位。', '',
         '| 版 | ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1(レースあたり)| 対数尤度 Y3(第 6 版は p3′)| Y3(直す前の p3)| 1 番人気 3 着以内率 |',
         '|---|---|---|---|---|---|---|']
    for k in KS + ('s0',):
        s = S[k]
        L.append(f"| {NM[k]} | {f(s['win'])} | {f(s['top3'])} | {f(s['ll1'])} | {f(s['ll3'])} | "
                 f"{f(s['ll3r']) if 'll3r' in s else '―'} | {f(s['fav_top3'])} |")
    L += ['', '## 第 5 版・第 4 版との比べ(§7・同じレースの対・第 6 版 − 相手)', '',
          '| 版 | 相手 | ◎ 3 着以内率の差(95% 区間)| 判定 | ◎ 勝率の差 | 対数尤度の差 Y1 | Y3(p3′ − p3・記録)| 第 6 版 − 1 番人気(◎ 3 着以内率)|',
          '|---|---|---|---|---|---|---|---|']
    V = {}
    for v in ('pre', 'day'):
        for ob in ('v5', 'v4'):
            b = o.diff_boot(tabs['v6' + v], tabs[ob + v])
            V[(v, ob)] = b['verdict']
            L.append(f"| {VN[v]} | 第 {ob[1]} 版 | {f(b['d_top3'])} | **{b['verdict']}** | {f(b['d_win'])} | {f(b['d_ll1'])} | "
                     f"{f(b['d_ll3'])} | {S['v6' + v]['top3'][0] - S['v6' + v]['fav_top3'][0]:+.3f} |")
    better = all(x == '上回った' for x in V.values())
    L += ['', f"**「第 5 版・第 4 版より良い」: {'届いた(6 日目から毎日の予想表を第 6 版に切り替える)' if better else '届かなかった(毎日の予想表は第 4 版のまま)'}**"
          '(前日版・当日版 × 第 5 版・第 4 版の 4 つすべてで「上回った」)', '',
          '## 旧 AI との比べ(§7・区切り ⑤・b_all・b_nankan・新 − 旧)', '']
    te5 = P['v6pre'][P['v6pre'].seg == '⑤']
    keep, why, nall = o.old_filter(te5, old, notes)
    L += [f"区切り ⑤ の予想するレース {nall:,} R のうち、旧 AI のファイルに出走した全馬(中止を含む)があるレース {len(keep):,} R で比べる。"
          '除いたレース: ' + '・'.join(f'{k} {v:,}' for k, v in why.items()) + '。旧 AI の ◎ = 旧 AI の勝つ確率の 1 位。', '',
          '| 版 | 旧 AI | レース | 新 ◎ 3 着以内率 | 旧 ◎ 3 着以内率 | 差(95% 区間)| 判定 | ◎ 勝率の差 | 対数尤度の差 Y1 | Y3 | 新 − 1 番人気 | 記録: 旧 ◎ を 3 着以内の確率の 1 位にしたときの差 |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|']
    vo = []
    for v in ('pre', 'day'):
        x = P['v6' + v][P['v6' + v].seg == '⑤'].merge(keep, on=KEY, how='inner')
        r = compare_old6(x, old)
        for ob in t3_eval.OLD:
            b = r[ob]
            vo.append(b['verdict'])
            L.append(f"| {VN[v]} | {ob} | {r['races']:,} | {b['top3'][0]:.3f} | {b['old_top3'][0]:.3f} | {f(b['d_top3'])} | "
                     f"**{b['verdict']}** | {f(b['d_win'])} | {f(b['d_ll1'])} | {f(b['d_ll3'])} | {f(b['d_fav_top3'])} | {f(b['d_top3_b'])} |")
        L.append(f"({VN[v]}: 旧 AI の確率が空の馬がいたレース {r['races_lacking_old_rows']})")
    beat = all(x == '上回った' for x in vo)
    L += ['', f"**「旧 AI を超えた」(目標): {'届いた' if beat else '届かなかった'}**(前日版・当日版 × b_all・b_nankan の 4 つすべてで「上回った」)",
          '旧 AI は前日の情報だけで月ごとに学び直している。当日版は馬場・馬体重を使う(新 AI が多くの情報を使う)。区切り ⑤ の第 6 版は 2025-08 までで 1 回だけ学んだ。', '',
          '## 内訳(§6・◎ 3 着以内率・点だけ・記録)', '',
          '| 区分 | 値 | レース | 第 6 版 前日 | 第 5 版 前日 | 第 4 版 前日 | 第 6 版 当日 | 第 5 版 当日 | 第 4 版 当日 | 1 番人気 |',
          '|---|---|---|---|---|---|---|---|---|---|']
    for r in breakdown6(tabs):
        L.append(f'| {r[0]} | {r[1]} | {r[2]:,} | ' + ' | '.join(f'{x:.3f}' for x in r[3:]) + ' |')
    L += ['', '### レースの種類ごと(1 番人気のいるレース)', '', '| 版 | 種類 | R | ◎ 勝率 | ◎ 3 着以内率 | 1 番人気 3 着以内率 | 差(ポイント)|',
          '|---|---|---|---|---|---|---|']
    for r in kinds6(P, tabs):
        L.append(f'| {r[0]} | {r[1]} | {r[2]:,} | {r[3]:.3f} | {r[4]:.3f} | {r[5]:.3f} | {(r[4] - r[5]) * 100:+.2f} |')
    L += ['', '### 選び方の内訳', '']
    for v in ('pre', 'day'):
        x = P['v6' + v]
        Rp = t6_day3.rtab(x, x.p1.to_numpy(), x.p3.to_numpy(), x.p1.to_numpy(), x.p3.to_numpy())
        R6, R5 = tabs['v6' + v], tabs['v5' + v]
        dif = R6.top_uma.to_numpy() != R5.top_uma.to_numpy()
        L.append(f"- {VN[v]}: 第 6 版で ◎ = p1 の 1 位にしたとき 3 着以内率 {Rp.top3.mean():.4f}・勝率 {Rp.win.mean():.4f}/"
                 f"◎ が第 5 版と違うレース {dif.mean():.3f}({int(dif.sum()):,} R)・そのレースで 第 6 版 {R6.top3.to_numpy()[dif].mean():.4f}・"
                 f"第 5 版 {R5.top3.to_numpy()[dif].mean():.4f}")
    L += ['', '### 確率の当たり具合(見込みの平均 / 実際・馬の数)', '']
    for v in ('pre', 'day'):
        x = P['v6' + v]
        for nm, c in calib6(x).items():
            L.append(f'- 第 6 版 {VN[v]} {nm}: ' + '・'.join(f'{a} {m:.3f}/{y:.3f}({n:,})' if n else f'{a} ―(0)' for a, n, m, y in c))
        L.append(f"- 第 6 版 {VN[v]}: p1 > p3′ の馬 {int((x.p1 > x.p3p).sum())}・δ "
                 + '・'.join(f'{s} {info[(s, v)][0]:+.4f}〜{info[(s, v)][1]:+.4f}' for s in dict.fromkeys(x.seg)))
    L += ['', '### 部品の値(付けた行・年ごと)', '', '| 年 | 行 | h2h | elo_z | nori | bw_diff | nori_ch = 1 | nori_dr = 1 | 連闘 |',
          '|---|---|---|---|---|---|---|---|---|']
    A = aux.assign(**{c: P['_feat'][c].notna().to_numpy() for c in NEW4})
    for y, g in A.groupby('year'):
        L.append(f"| {y} | {len(g):,} | " + ' | '.join(f'{g[c].mean():.4f}' for c in NEW4) +
                 f" | {(g.nori_ch == 1).mean():.4f} | {(g.nori_dr == 1).mean():.4f} | {int(g.rentou.sum())} |")
    L += ['', '見張り(§9): ハッシュ・表と保存した予想の組・2026-09-01 以降を読まない・4 列の元の走り(着順の形・勝ち馬のいないレース・着順も注記も無い出走〔全頭無いレースは分けて数える・細部 12〕・'
          '1 月のつながり・馬体重の外れ・同じ日の 2 回出走)・4 列の値のある割合(h2h・elo_z・nori_ch・nori_dr)・旧 AI の絞りの数・保存した予想の ◎ の率・'
          '区切り ① の模型の一致 = すべて通った。', '']
    return L, {'better': better, 'beat': beat, 'v': {f'{a}-{b}': x for (a, b), x in V.items()}, 'old': vo}


# ================================================================ fmt(4 日目)
def norm_h(runs, facts):
    """t3_open.sources の書き方のそろえ + load4 の騎手の NFKC を写したもの(細部 10)。着順の注記の種類と鍵の形の外れの数も返す。"""
    runs = runs.rename(columns={'runner_number': 'umaban'}).copy()
    for d in (runs, facts):
        d['race_no'] = d.race_no.astype(int)
        d['umaban'] = d.umaban.astype(int)
    runs['finish_note'] = runs.finish_note.replace(t3_open.NOTE)
    kinds = sorted(set(runs.finish_note.dropna().unique()))
    facts = facts.copy()
    facts['horse_key'] = facts.horse_key.str.replace(r'\|(\d{4})-\d\d-\d\d$', r'|\1', regex=True)
    nb = int((~facts.horse_key.dropna().str.contains(r'\|\d{4}$')).sum())
    h = runs.merge(facts[KEY + ['umaban', 'horse_key']], on=KEY + ['umaban'], how='left')
    h['hid'] = h.horse_key.fillna(h.horse_name)
    h['jockey'] = h.jockey.map(lambda x: unicodedata.normalize('NFKC', x) if isinstance(x, str) else x)
    return h, kinds, nb


def safe_sources(parts, hi, extra=()):
    """RAW + DB の写し(parts)を結果でない列だけで読む(extra は RAW・2020〜2021 の写しでだけ使う)。"""
    ra, fa = load_archive('runs'), load_archive('facts')
    rc = RUN6 + list(extra)
    runs = pd.concat([ra[rc]] + [_align(pd.read_parquet(V3 / f'db_runs_{p}_{t3_open.FILES[p]}.parquet', columns=rc), ra)
                                 for p in parts], ignore_index=True)
    facts = pd.concat([fa[FACT6]] + [_align(pd.read_parquet(V3 / f'db_facts_{p}_{t3_open.FILES[p]}.parquet', columns=FACT6), fa)
                                     for p in parts], ignore_index=True)
    for d in (runs, facts):
        if d.race_date.max() >= hi:
            stop(f'{hi} 以降の行がある')
    return norm_h(runs, facts), ra, fa


def fmt():
    res = {}
    # ① RAW と DB の写し(2020〜2021・南関・作る期間なので結果の列も見てよい)
    (hr, _, _), ra, fa = safe_sources([], '2022-01-01', extra=('finish',))
    dr = _align(pd.read_parquet(V3 / 'db_check_2020_2021_runs.parquet', columns=RUN6 + ['finish']), ra)
    df_ = _align(pd.read_parquet(V3 / 'db_check_2020_2021_run_facts.parquet', columns=FACT6), fa)
    hd, kd, nbd = norm_h(dr, df_)
    A = hr[hr.track.isin(NANKAN) & (hr.race_date >= '2020-01-01') & (hr.race_date < '2022-01-01')]
    B = hd[hd.track.isin(NANKAN) & (hd.race_date >= '2020-01-01') & (hd.race_date < '2022-01-01')]
    J = A.merge(B, on=KEY + ['umaban'], suffixes=('_r', '_d'))
    one = {}
    for c, nm, num in (('finish', '着順', True), ('finish_note', '着順の注記', False), ('jockey', '騎手(NFKC)', False),
                       ('body_weight', '馬体重', True), ('horse_key', '馬の鍵', False)):
        a, b = J[c + '_r'], J[c + '_d']
        if num:
            eq = t6_base.eqmask(a.astype(float), b.astype(float))
        else:
            eq = ((a.isna() & b.isna()) | (a.astype(object) == b.astype(object))).to_numpy()
        one[nm] = [float(eq.mean()), int((~eq).sum()), int(a.isna().sum()), int(b.isna().sum())]
    res['one'] = {'runs_raw': int(len(A)), 'runs_db': int(len(B)), 'runs_join': int(len(J)), 'items': one,
                  'db_note_kinds': kd, 'db_key_bad': nbd, 'ok': all(v[0] >= 0.99 for v in one.values())}
    print('①', {k: round(v[0], 4) for k, v in one.items()}, 'つながった', len(J), flush=True)
    # ② 確かめる期間・封印の写し(結果でない列だけ)
    (h, _, nb), _, _ = safe_sources(['confirm', 'sealed'], END)
    db_kinds = sorted(set(h[h.race_date >= '2022-01-01'].finish_note.dropna().unique()))
    s = area_year(h[~h.finish_note.isin(CANCEL)]).reset_index(drop=True)
    s['dn'] = t6_base.dnum(s.race_date)
    q = s[s.race_date >= '2016-01-01']
    cnt = t6_base.wsum(s.jockey, s.dn, np.ones(len(s)), q.jockey, q.dn, 365, 1)[:, 0]
    q = q.assign(jlink=(cnt > 0), bwok=q.body_weight.notna())
    jl = q.groupby(['area', 'year']).jlink.mean()
    bwr = q.groupby(['area', 'year']).bwok.mean()
    jan = jan_rates(s, sorted(q.year.unique()))
    later = s[s.race_date >= '2022-01-01']
    dup = int(later[later.hid.notna()].duplicated(['hid', 'race_date']).sum())
    rows, ok2 = [], True
    for (ar, y) in sorted(jl.index):
        r = {'area': ar, 'year': y, 'jlink': float(jl[(ar, y)]), 'bw': float(bwr[(ar, y)]), 'jan': jan.get((ar, y))}
        if y >= '2022':
            r['ok'] = (r['jlink'] >= FMT_LINE['jlink'][ar] and r['bw'] >= FMT_LINE['bw'][ar] and
                       r['jan'] is not None and r['jan'] >= FMT_LINE['jan'][ar])
            ok2 &= r['ok']
        rows.append(r)
    base = {}
    for ar in ('nankan', 'other'):
        rr = [r for r in rows if r['area'] == ar and '2016' <= r['year'] <= '2021']
        base[ar] = {m: min(r[m] for r in rr) for m in ('jlink', 'bw', 'jan')}
    kinds_ok = set(db_kinds) <= NOTES5
    two = {'rows': rows, 'db_note_kinds': db_kinds, 'kinds_ok': kinds_ok, 'dup_same_day_2022_': dup, 'key_bad_rows': nb,
           'base_2016_2021': base, 'ok': bool(ok2 and kinds_ok and dup == 0),
           'min_2022_': {ar: {m: min(r[m] for r in rows if r['area'] == ar and r['year'] >= '2022') for m in ('jlink', 'bw', 'jan')}
                         for ar in ('nankan', 'other')}}
    res['two'] = two
    print('②', two['min_2022_'], '種類', db_kinds, 'dup', dup, '合' if two['ok'] else '否', flush=True)
    FMT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    AR = {'nankan': '南関', 'other': '南関以外'}
    L = ['# 第 6 版 4 日目: 書き方の確かめ(PREREG6 §9 ①②・確かめる期間と封印の結果の列は読まない)', '',
         '台本 src/t6_open.py fmt。読み方は open と同じそろえ方(t3_open.sources の書き方のそろえ + load4 の騎手の NFKC を写した norm_h。'
         'dry で RAW の h と一致を確かめる)。確かめる期間・封印の写しは 場・日付・R・馬番・馬名・騎手・馬体重・着順の注記・馬の鍵 だけを読んだ。', '',
         '## ① RAW と DB の写し(2020〜2021・南関)の同じ出走', '',
         f"出走 RAW {res['one']['runs_raw']:,}・DB {res['one']['runs_db']:,}・つながった {res['one']['runs_join']:,}。", '',
         '| 項目 | 一致 | 一致しない | RAW の欠け | DB の欠け | 線 99% |', '|---|---|---|---|---|---|']
    for nm, (r, bad, na, nb_) in one.items():
        L.append(f"| {nm} | {r:.4f} | {bad:,} | {na:,} | {nb_:,} | {'合' if r >= 0.99 else '否'} |")
    L += ['', '## ② 確かめる期間・封印の写し(結果でない列だけ・取消と除外を除く出走)', '',
          '| 場 | 年 | 騎手名のつながり | 馬体重のある割合 | 1 月のつながり | 合否 |', '|---|---|---|---|---|---|']
    for r in rows:
        if r['year'] >= '2022':
            L.append(f"| {AR[r['area']]} | {r['year']} | {r['jlink']:.4f} | {r['bw']:.4f} | {r['jan']:.4f} | {'合' if r['ok'] else '否'} |")
    L += ['', '| 場 | 線: 騎手名 | 線: 馬体重 | 線: 1 月 | 2022〜の最小: 騎手名 | 馬体重 | 1 月 |', '|---|---|---|---|---|---|---|']
    for ar in ('nankan', 'other'):
        m = two['min_2022_'][ar]
        L.append(f"| {AR[ar]} | {FMT_LINE['jlink'][ar]} | {FMT_LINE['bw'][ar]} | {FMT_LINE['jan'][ar]} | {m['jlink']:.4f} | {m['bw']:.4f} | {m['jan']:.4f} |")
    L += ['', f"着順の注記の種類(DB 2022〜): {'・'.join(db_kinds)} → {'⊆ 取消・除外・中止・失格・降着(合)' if kinds_ok else 'RAW に無い種類がある(否)'}",
          f"同じ日に 2 回以上出走する馬の鍵(DB 2022〜): {dup}({'合' if dup == 0 else '否'})",
          f"「名前|生年」でない馬の鍵の行(RAW + DB・記録): {nb}", '',
          '記録(線の元の照らし合わせ・同じ読み方で RAW 2016〜2021 の年ごとの最小): '
          + '・'.join(f"{AR[ar]} 騎手名 {base[ar]['jlink']:.4f}(線 + 0.05 = {FMT_LINE['jlink'][ar] + 0.05:.4f})・馬体重 {base[ar]['bw']:.4f}"
                      f"(線 + 0.05 = {FMT_LINE['bw'][ar] + 0.05:.4f})・1 月 {base[ar]['jan']:.4f}(1 日目 {JAN_BASE[ar]})" for ar in ('nankan', 'other')), '',
          f"**合否: ① {'合' if res['one']['ok'] else '否'}・② {'合' if two['ok'] else '否'}**"]
    OUT_FMT.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


# ================================================================ dry(4 日目)
def dry():
    lo, hi, _ = SPAN['dry']
    h, races = o.load4('dry')
    assert h.race_date.max() < hi
    # 細部 10: fmt の読み方(norm_h)が open の読み方(load4)と RAW で一致
    (hs, _, _), _, _ = safe_sources([], hi)
    cmp = KEY + ['umaban', 'horse_name', 'jockey', 'body_weight', 'finish_note', 'horse_key', 'hid']
    a = h[cmp].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    b = hs[cmp].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    assert a.astype(str).equals(b.astype(str)), 'fmt の読み方が load4 と一致しない'
    print('fmt の読み方 = load4 の h(RAW・9 列)一致', len(a), flush=True)
    # ① 4 列
    X6 = o.sort4(nk(pd.read_parquet(FEAT6X)))
    F = X6[X6.year == 2021].drop(columns=NEW4).reset_index(drop=True)
    T, aux, hh, st = build6(h, F, hi)
    r21 = X6[X6.year == 2021].reset_index(drop=True)
    assert list(T.columns) == list(r21.columns) and T[KEY + ['umaban']].equals(r21[KEY + ['umaban']])
    cols = ['n', 'Y1', 'Y3', 'pop'] + C6['day'] + ['bw_diff']
    A_, B_ = T[cols].to_numpy(float), r21[cols].to_numpy(float)
    eq = (np.isnan(A_) & np.isnan(B_)) | (np.abs(A_ - B_) <= 1e-9)
    print(f'① 4 列の一致(2021・feat_t6_explore): {int(eq.sum()):,} / {eq.size:,}', flush=True)
    assert eq.all(), [c for c, k in zip(cols, eq.all(0)) if not k]
    # ⑥ 見張り (2)(3)
    segs = [('2021', lo, hi)]
    guard_runs(hh, lo, hi)
    guard_cols(T, aux, lo, hi, segs)
    print('⑥ 見張り (2)(3) OK(2021)', flush=True)
    # ④ 保存した第 5 版・第 4 版の線
    S5 = nk(pd.read_parquet(PRED5X))
    S5 = S5[(S5.race_date >= lo) & (S5.race_date < hi)]
    lm = json.loads(RES5.read_text(encoding='utf-8'))['line']['metrics']
    base = T.assign(seg='2021').sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    SF = saved_frames(base, S5, {k: (f'{k}_p1', f'{k}_p3') for k in ('v5pre', 'v5day', 'v4pre', 'v4day')})
    for k, x in SF.items():
        v = saved_top3(x)
        print(f'④ {k} 2021 の ◎ 3 着以内率 {v:.4f} 保存値との差 {v - lm[k]["top3_2021"]:.1e}', flush=True)
        assert v == lm[k]['top3_2021'], k
    # 区切り ① の学び直し = models/t6_*
    if not o.same_models(train_v6(X6, '2022-01-01'), 't6'):
        stop('区切り ① の学び直し(2015〜2021)が models/t6_* と一致しない')
    print('区切り ① の学び直し = models/t6_* と文字列一致(4 本)', flush=True)
    # ② 2015〜2020 で学び直した 2021
    T6 = pd.concat([X6[X6.race_date < lo], T], ignore_index=True)
    P6, info = seg_v6(T6, segs)
    pr = nk(pd.read_parquet(PRED6X))
    pr = pr[pr.year == 2021].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    for v in ('pre', 'day'):
        x = P6['v6' + v]
        assert x[KEY + ['umaban']].equals(pr[KEY + ['umaban']])
        dd = max(float(np.abs(x[c].to_numpy() - pr[f'v6{v}_{c}'].to_numpy()).max()) for c in ('p1', 'p3', 'p3p'))
        print(f'② 2021 の学び直し v6{v}(p1・p3・p3′): 3 日目の当てはめ外との差の最大 {dd:.2e}', flush=True)
        assert dd <= 1e-9
    P = {**P6, **SF}
    tabs = tabs_of({k: P[k] for k in KS})
    # ③ 自分自身と比べて差 0
    for v in ('pre', 'day'):
        z = o.diff_boot(tabs['v6' + v], tabs['v6' + v])
        assert all(abs(x) < 1e-12 for k in ('d_top3', 'd_win', 'd_ll1', 'd_ll3') for x in z[k]) and z['verdict'] == '差は誤差の範囲'
    print('③ 第 6 版を自分自身と比べて差 0・判定 差は誤差の範囲', flush=True)
    for v in ('pre', 'day'):
        for ob in ('v5', 'v4'):
            b = o.diff_boot(tabs['v6' + v], tabs[ob + v])
            print(f"(探索 2021・記録)第 6 版 − {ob} {v}: ◎ 3 着以内率の差 {t3_eval.fmt(b['d_top3'])} {b['verdict']}", flush=True)
    # ⑤ 旧 AI の絞りと compare_old6 の自己試験(t5_open.dry と同じやり方)
    notes = hh[KEY + ['umaban', 'finish_note']].drop_duplicates(KEY + ['umaban'])
    x = P['v6pre'].merge(notes, on=KEY + ['umaban'], how='left')
    fake = x[KEY + ['umaban', 'n', 'p1', 'p3', 'p3p']].copy()
    fake['b_all_win'], fake['b_all_top3'] = fake.p3p, fake.p3p
    fake['b_nankan_win'], fake['b_nankan_top3'] = 1 / fake.n, 3 / fake.n
    stp = (x.finish_note == '中止').to_numpy()
    first_race = x[KEY].drop_duplicates().iloc[[0]]
    in_first = x.merge(first_race.assign(_f=True), on=KEY, how='left')._f.fillna(False).to_numpy().astype(bool)
    other = in_first & (x.umaban == x.umaban[in_first].max()).to_numpy()
    drop_race = x[KEY].drop_duplicates().iloc[[-1]]
    lack_race = x.merge(drop_race.assign(_f=True), on=KEY, how='left')._f.fillna(False).to_numpy().astype(bool)
    fk = fake[~stp & ~(other & ~stp) & ~lack_race]
    exp_stop = x[stp][KEY].drop_duplicates().merge(drop_race.assign(_f=1), on=KEY, how='left')
    exp_stop = exp_stop[exp_stop._f.isna()].drop(columns='_f')
    keep, why, nall = o.old_filter(P['v6pre'], fk, notes)
    ex_other = x[other & ~stp][KEY].drop_duplicates().merge(drop_race.assign(_f=1), on=KEY, how='left')
    ex_other = ex_other[ex_other._f.isna()].drop(columns='_f')
    e_stop = exp_stop.merge(ex_other.assign(_o=1), on=KEY, how='left')
    assert why['ファイルに無いレース'] == 1 and why['そのほかの馬が無い'] == len(ex_other) == 1
    assert why['中止の馬だけが無い'] == int(e_stop._o.isna().sum()), why
    assert len(keep) + sum(why.values()) == nall
    print('⑤ 旧 AI の絞り: 理由別', why, '/ 全', nall, flush=True)
    te = P['v6pre'].merge(keep, on=KEY)
    r = compare_old6(te, fk)  # 旧 AI = 第 6 版の p3′ を勝つ確率に置いたもの → ◎ と Y3 の対数尤度が同じ
    assert r['races'] == len(keep) and r['races_lacking_old_rows'] == 0
    assert all(abs(v) < 1e-12 for k in ('d_top3', 'd_win', 'd_ll3') for v in r['b_all'][k]), r['b_all']
    assert r['b_all']['verdict'] == '差は誤差の範囲' and r['b_nankan']['verdict'] == '上回った'
    fkB = fk.assign(b_all_win=fk.p1, b_all_top3=fk.p3)  # 旧 AI = 第 6 版の p1・p3 → 旧 AI の側は compare_old と同じ・記録の ◎ が同じ
    rB, rC = compare_old6(te, fkB), t3_eval.compare_old(te, fkB)
    for ob in t3_eval.OLD:
        for k in ('old_top3', 'd_ll1'):
            assert all(abs(p - q) < 1e-12 for p, q in zip(rB[ob][k], rC[ob][k])), (ob, k)
    assert all(abs(v) < 1e-12 for k in ('d_top3_b', 'd_ll1') for v in rB['b_all'][k]), rB['b_all']
    print('⑤ compare_old6 の自己試験 OK(◎・対数尤度 Y3 の差 0/旧 AI の側 = t3_eval.compare_old/記録の ◎ の差 0)', flush=True)
    P = {k: v.assign(seg='⑤') for k, v in P.items()}  # report は区切り ⑤ を旧 AI と比べるので、dry では 2021 を ⑤ とみなす
    P['_feat'] = T
    info = {('⑤', v): info[('2021', v)] for v in ('pre', 'day')}
    L, J = report6(P, fk, notes, aux, info, 'dry(書き出さない)', 'dry')
    assert any('「第 5 版・第 4 版より良い」' in s for s in L) and any('「旧 AI を超えた」' in s for s in L)
    assert sum(s.startswith(('| 前日版 | b_', '| 当日版 | b_')) for s in L) == 4
    assert sum(s.startswith(('| 前日版 | 第 ', '| 当日版 | 第 ')) for s in L) == 4
    print('dry OK', flush=True)


# ================================================================ open(5 日目・判断の日)
def open_():
    if OUT_OPEN.exists():
        stop('確かめる期間は第 6 版で開けてある(1 回だけ)')
    lo, hi, _ = SPAN['open']
    assert hi == END
    # 1. ハッシュ・組の一致・2026-09-01 以降を読まない
    o.verify()
    F5 = o.sort4(nk(pd.read_parquet(FEAT5O)))
    S5 = nk(pd.read_parquet(PRED5O))
    assert F5.race_date.max() < END and S5.race_date.max() < END and F5.race_date.min() >= lo
    a = F5[KEY + ['umaban']].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    b = S5[KEY + ['umaban']].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    assert a.equals(b), 'feat_t5_open と t5_day5_preds_open の (場・日付・R・馬番) が一致しない'
    h, races = o.load4('open')
    assert h.race_date.max() < END and races.race_date.max() < END
    # 2. 4 列
    T, aux, hh, st = build6(h, F5, hi)
    X6 = o.sort4(nk(pd.read_parquet(FEAT6X)))
    T = T[list(X6.columns)]
    T.to_parquet(FEAT6O, index=False)
    T6 = pd.concat([X6, T], ignore_index=True)
    assert not T6.duplicated(KEY + ['umaban']).any()
    # 3. 見張り (2)(3)・旧 AI の絞りの数(通ったときは数字を出さない)
    guard_runs(hh, lo, hi)
    guard_cols(T, aux, lo, hi, SEGS)
    notes = hh[KEY + ['umaban', 'finish_note']].drop_duplicates(KEY + ['umaban'])
    old = t3_eval.load_old(t3_open.OLD_MONTHS)
    keep, _, _ = o.old_filter(o.seg_rows(T, *SEGS[-1][1:]), old, notes)
    if len(keep) != OLD_RACES:
        stop('旧 AI の絞りで残るレースの数が第 4・5 版 5 日目と違う(読み込みのずれ)')
    # 4. 保存した予想の確かめ(§7)
    base = T.assign(seg=seg_of(T.race_date, SEGS)).sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    SF = saved_frames(base, S5, {k: (f'p1_{k}', f'p3_{k}') for k in REF7})
    for k, x in SF.items():
        v = saved_top3(x)
        if (f'{v:.4f}', f'{v:.3f}') != REF7[k]:
            stop(f'保存した予想の ◎ 3 着以内率が決め書の値と合わない({k})')
    print('見張り OK', flush=True)
    # 5. 第 6 版の学び直しと予想
    P6, info = seg_v6(T6, SEGS)
    for k in P6:
        assert P6[k][KEY + ['umaban']].equals(base[KEY + ['umaban']])
    pp = P6['v6pre'][KEY + ['umaban', 'seg']].copy()
    for v in ('pre', 'day'):
        for c in ('p1', 'p3', 'p3p'):
            pp[f'{c}_v6{v}'] = P6['v6' + v][c].to_numpy()
    pp.to_parquet(PRED6O, index=False)
    # 6・7. 比べと記録
    P = {**P6, **SF, '_feat': T}
    L, J = report6(P, old, notes, aux, info,
                   '第 6 版 5 日目: 開ける前の止まりどころに当たったうえで開けた(4 回目)— 確かめる期間(2022-01〜2026-08・5 区切り)を 1 回だけ開ける',
                   '確かめる期間の 4 回目の使用')
    OUT_OPEN.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    {'fit': fit, 'fmt': fmt, 'dry': dry, 'open': open_}[sys.argv[1]]()
