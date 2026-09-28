# -*- coding: utf-8 -*-
"""第 5 版 4 日目・5 日目(判断の日)の台本(PREREG5 §1・§3・§5・§6・§7・§9)。4 日目に sha256 で固定する。値を見て形・設定・材料は変えない。
第 4 版の台本(t4_*.py)と t5_base.py・t5_day3.py は直さずに呼ぶ。

  py -3.12 -X utf8 src/t5_open.py fit          # 4 日目: 2015〜2021 で第 5 版の前日版・当日版 × Y1・Y3 を 2 回ずつ学習(文字列の一致)→ models/t5_*.txt
  py -3.12 -X utf8 src/t5_open.py formatcheck  # 4 日目: §9 の書き方の確かめ ①② → out/t5_day4_format.md(確かめる期間・封印の結果の列は読まない)
  py -3.12 -X utf8 src/t5_open.py dry          # 4 日目: 探索の 2021 だけで、open と同じ道を通す通し試験(表は出さない)
  py -3.12 -X utf8 src/t5_open.py open         # 5 日目(判断の日)だけ: 確かめる期間(2022-01〜2026-08)を 1 回だけ開ける(3 回目の使用)→ out/t5_day5_open.md

■ 決め書に無い細部(4 日目に決めた。開ける前。見た後は変えない)
  1. 読み込み = t4_open.load4(part)(t3_open.sources の走り h・link_guard・騎手/調教師の NFKC と、races4 のレースの表)。races4 は RAW と
     DB の写しの全列(_align で RAW の列にそろえる)を返すので、第 5 版で要る furlongs・race_last3f・corners・prize_yen(南関以外の NAR も)
     はそのまま入る。load5 はそれらの列があること・南関以外のレースがあることを assert する。
  2. 材料 = PREREG5 §3 の順: base_of(t4_open)→ rebuild(U, 第 4 版の SI) が U の a_prior〜k_* と 100% 一致(assert)→ make_si5 →
     rebuild(U, SI5)(a_ab と make_si5 の a_ab5 の一致を assert)→ t4_day3.feat_new・assemble(〔v3〕の列は build3 → finish_table。
     t4_open.build4 と同じ)→ t5_day3.parts_of(U5, h の南関の c1〜n4, races, h, 作る行)で 22 列を足す。
  3. t5_base の o_table は年を t5_base.YRS(2015〜2021)から取るので、2022 年以降の o_s が作られず 0 になる。台本は make_si5 を呼ぶ前に
     t5_base.YRS を 2015〜(U の最後の年)に置き換える(t5_base.py は直さない。2021 年までは同じ値 = dry で確かめる)。
  4. ラップ = races の furlongs(JSON の数の列・空や数でない値や 0 以下があれば読めない)。勝ち時計 = そのレースの U の time_sec の最小
     (t5_day3 細部 2 と同じ)。レースのラップの外れ = ラップが読めない か |ラップの合計 − 勝ち時計| > 0.1 秒。上がり 3F の外れ = ラップが
     読めない・race_last3f が欠け・|最後の 3 ハロンの合計 − race_last3f| > 0.05 秒のどれか。数えるのは勝ち時計のある南関のレースだけ。
  5. 通過順の見張り = 区間の U の南関のレースを t5_day3.corners_table に通し、知らない記号の数 0・読めないレースの割合 ≤ 0.001。
  6. 欠けの見張り(SI5・SIp・FR)= parts_of の走りの表(南関・取消/除外を除く)で年ごとの欠けの割合。線 = 2016〜2021 の年ごとの最大 + 0.05。
     D_proj の作れた日 = 日×場(dtk)ごと。線 = 2016〜2021 の年ごとの最小 − 0.10。o_s の動き = 区間の各年の 4 場の |o(y) − o(y−1)| ≤ 3、
     γ = 区間の各年 > 0。
  7. SI から作らない列 = 前日版 93 列のうち t5_base.REPLACED(21 列)以外の 72 列 + 段 6 の 3 列 + n・Y1・Y3。open では feat_t4_open、
     dry では feat_t4_explore の 2021 と 100% 一致(|差| ≤ 1e-9・両方欠けも一致)。
  8. 第 4 版の学び直しの確かめ(§7): 区切り ① の 4 本が models/t4_* と文字列一致(しなければ止まる)。区切りごとの ◎ 3 着以内率(前日版・
     当日版)とレースの数、全体の ◎ 勝率・◎ 3 着以内率・対数尤度 Y1・Y3(前日版・当日版)を小数 3 桁の文字列にして out/t4_day5_open.md
     の値と比べる。第 4 版の予想(全区切り)と確かめは第 5 版の学習より前に済ませる。
  9. 旧 AI の絞りは t4_open.old_filter(第 4 版 §7 と同じ)。open では予想の前に区切り ⑤ の残るレースの数が 3,163 であることを見張る
     (第 4 版 5 日目と同じ表・同じ絞りなので、違えば読み込みのずれとして止まる)。
  10. open は確かめる期間の第 5 版の材料の表を v3/feat_t5_open.parquet に保存する(6 日目の学び直し用)。
  11. §6 追加 4(群を外す当てはめ外)は作る期間の記録なので open では出さない。追加 1〜3 は出す。
  12. formatcheck ①: RAW と v3/db_check_2020_2021_races の南関の同じレース(KEY)。ラップ = 長さが同じで各ハロン |差| ≤ 0.05。
     上がり 3F = |差| ≤ 0.05。通過順 = corners_table の読めた/読めないが同じで、読めたレースは 3 角・4 角の差・外の数が全馬で同じ
     (載っている馬の組も同じ)。賞金 = prize_list の 1〜5 番目が同じ。どれも両方とも読めない(欠け)は一致に数える。
  13. formatcheck ②: 前向きの写し(db_*_forward_t3・2026-09-01〜)の南関のレースのうち、走りの time_sec があるレース(走ったレース)で
     細部 4・5 を数える。確かめる・封印の写しは track・KEY・prize_yen だけを読み、prize_list で読めないレースを南関/南関以外で数える。
  14. 見張りの追加(5 日目・開ける前の点検 out/t5_day5_preopen.md の直すべき 1・ユーザー承認 2026-09-26): SIp は mis が欠けると SI5 に
     戻り、FR は物差しの馬がいないと SI5 のままなので、SIp・FR の欠けの見張りは SI5 の見張りと同じになる。guard5 に、parts_of の走りの
     表で年ごとの「最初の角の位置(pos)がある」「流れの点(RS)がある」「物差しの馬がいる(nk > 0)」割合を足し、区間の各年が 2016〜2021
     の年ごとの最小 − 0.05 以上を見る(通ったときは数字を出さない)。
  15. 通過順の見張りの分け方(5 日目・open が細部 5 の見張りで止まった後・ユーザー承認 2026-09-26): 2023〜2026 の DB の写しに通過順が空
     (角の項目 0 個)のレースがある(107 R・22 の日×場に固まる・うち 4 日は全レース・同じレースのレースの上がり 3F も 107 R で欠け
     = その日のレースの詳細の取り込み損ね。知らない記号 0・作る期間 0/22,208・前向き 0/216)。空のレースはデータの欠けとして分け、
     ① 通過順が入っているレースで知らない記号 0・読めない ≤ 0.001(細部 5 の線のまま)② 空のレースの割合は年ごとに 2016〜2021 の
     年ごとの最大(0)+ 0.05 以下、を見る。空のレースの x_* は欠けのまま(corners_table が行を出さない。材料の作り方は変えない)。
     予想表の台本(t5_forecast.watch_laps)も同じ guard_laps を呼ぶ。
"""
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_eval  # noqa: E402
import t3_open  # noqa: E402
import t4_day3 as d3  # noqa: E402
import t4_open as o  # noqa: E402
import t5_base  # noqa: E402
import t5_day3 as d5  # noqa: E402
from day2_features import build as build3  # noqa: E402
from day5_forward_features import _align  # noqa: E402
from load_outcomes import load_archive  # noqa: E402
from t3_day2_features import finish_table, targets3  # noqa: E402

V3 = o.V3
REPO = o.REPO
MD = o.MD
OUT_OPEN = REPO / 'out/t5_day5_open.md'
OUT_FMT = REPO / 'out/t5_day4_format.md'
FEAT5 = d5.FEAT
FEAT_OPEN5 = V3 / 'feat_t5_open.parquet'
REF4_MD = REPO / 'out/t4_day5_open.md'
KEY, RK = d3.KEY, t5_base.RK
NANKAN = d3.NANKAN
CANCEL = o.CANCEL
SPAN = o.SPAN4
SEGS = o.SEGS
VN = o.VN
CORNER = ['c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4']
PRE_A, DAY6, ALL5 = d5.PRE_A, d5.DAY6, d5.ALL5
NONSI = [c for c in PRE_A if c not in t5_base.REPLACED] + DAY6
OLD_RACES = 3163
assert len(NONSI) == 75


# ================================================================ 設定
def grid5():
    g = json.loads((V3 / 't5_grid.json').read_text(encoding='utf-8'))
    assert g['kept'] == d5.PRE_ALL5 and len(g['kept']) == 115, 't5_grid.json の kept が段 A〜C の 115 列でない'
    return {'pre': list(g['kept']), 'day': list(g['kept']) + DAY6}, {'Y1': tuple(g['Y1']), 'Y3': tuple(g['Y3'])}


C5, CFG5 = grid5()


def train5(df, cols, target):
    assert len(cols) == len(set(cols)) and not d3.BANNED & set(cols)
    cfg = CFG5[target]
    z = d3.logit((1 if target == 'Y1' else 3) / df.n.to_numpy(float))
    prm = dict(d3.BASE, num_leaves=cfg[0], min_data_in_leaf=cfg[1])
    return lgb.train(prm, lgb.Dataset(df[cols].astype(float), label=df[target].to_numpy(float), init_score=z),
                     num_boost_round=cfg[2])


def train_v5(T5, lo):
    tr = o.sort4(T5[T5.race_date < lo])
    return {v: (train5(tr, C5[v], 'Y1'), train5(tr, C5[v], 'Y3')) for v in ('pre', 'day')}


def models5(prefix):
    return {v: (o.booster(MD / f'{prefix}_{v}_Y1.txt'), o.booster(MD / f'{prefix}_{v}_Y3.txt')) for v in ('pre', 'day')}


# ================================================================ fit(4 日目)
def fit():
    df = o.sort4(pd.read_parquet(FEAT5))
    assert df.race_date.min() >= '2015-01-01' and df.race_date.max() < '2022-01-01'
    meta = {'train': '2015-01-01〜2021-12-31', 'rows': len(df), 'races': int(df[KEY].drop_duplicates().shape[0]),
            'cfg': {k: list(v) for k, v in CFG5.items()}, 'files': {}}
    for v, cols in C5.items():
        for t in ('Y1', 'Y3'):
            s1, s2 = train5(df, cols, t).model_to_string(), train5(df, cols, t).model_to_string()
            if s1 != s2:
                raise SystemExit(f'⛔ 2 回の学習が一致しない: {v} {t}')
            fp = MD / f't5_{v}_{t}.txt'
            fp.write_text(s1, encoding='utf-8', newline='\n')
            meta['files'][fp.name] = {'cols': cols}
            print(v, t, '一致', len(cols), '列', flush=True)
    (MD / 't5_models.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')


# ================================================================ 読み込み・材料
def load5(part):
    h, races = o.load4(part)
    need = {'furlongs', 'race_last3f', 'corners', 'prize_yen'}
    assert need <= set(races.columns), f'races に {need - set(races.columns)} が無い'
    assert (~races.track.isin(NANKAN)).any(), 'races に南関以外のレースが無い(g_eps の分母)'
    return h, races


def si5_of(U):
    """細部 3: t5_base.YRS を U の最後の年まで延ばしてから make_si5。"""
    t5_base.YRS = list(range(2015, int(U.year.max()) + 1))
    return t5_base.make_si5(U)


def base5(h, races):
    """→ U(第 4 版の土台)・U5 = rebuild(U, SI5)・make_si5 の出力と記録。"""
    U = o.base_of(h, races)
    R0 = t5_base.rebuild(U, U.SI)
    assert R0[RK + ['runner_number']].equals(U[RK + ['runner_number']]), 'rebuild の行の並びが U と違う'
    bad = {c: int((~t5_base.eqmask(R0[c], U[c])).sum()) for c in t5_base.REB}
    assert not any(bad.values()), f'⛔ rebuild(U, 第 4 版の SI) が t4_base と一致しない {bad}'
    R, info = si5_of(U)
    U5 = t5_base.rebuild(U, R.SI5.to_numpy())
    assert t5_base.eqmask(U5.a_ab, R.a_ab5).all(), 'a_ab5 と rebuild の a_ab が合わない'
    return U, U5, R, info


def build5(h, races, lo, hi):
    """確かめる期間の第 5 版の材料の表(META + 118 列・[lo, hi) の予想する行)と部品。"""
    U, U5, R, info = base5(h, races)
    tg = targets3(h)
    tgt = tg[(tg.race_date >= lo) & (tg.race_date < hi)].reset_index(drop=True)
    X3, _ = build3(h, tgt, tg)
    X3 = finish_table(X3, h, tg)
    T = d3.assemble(d3.feat_new(U5, h, races, tg, tgt), X3)
    d = (T.h_j3 - T.h_j3_own).abs()
    assert (d.fillna(0) <= 1e-9).all() and (T.h_j3.isna() == T.h_j3_own.isna()).all(), 'h_j3 の作り直しが合わない'
    fc = h[h.track.isin(NANKAN)][KEY + ['umaban'] + CORNER]
    N, P, S, pinfo = d5.parts_of(U5, fc, races, h, tgt)
    T['race_no'], T['umaban'] = T.race_no.astype(int), T.umaban.astype(int)
    T = T.merge(N, on=KEY + ['umaban'], how='left', validate='1:1', indicator=True)
    assert (T.pop('_merge') == 'both').all()
    T = o.sort4(T[d3.META + ALL5])
    assert not d3.BANNED & set(ALL5) and len(ALL5) == 118
    assert T.race_date.min() >= lo and T.race_date.max() < hi
    return T, {'U': U, 'R': R, 'info': info, 'P': P, 'pinfo': pinfo}


# ================================================================ ラップ・通過順
def laps_of(s):
    try:
        v = json.loads(s) if isinstance(s, str) else None
    except Exception:
        return None
    if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        return None
    v = [float(x) for x in v]
    return v if all(x > 0 for x in v) else None


def lap_table(R, tw):
    """R = レースの表(KEY・furlongs・race_last3f)、tw = KEY と勝ち時計 tw。勝ち時計のある南関のレースだけ → 外れの印。"""
    x = R[R.track.isin(NANKAN)][KEY + ['furlongs', 'race_last3f']].drop_duplicates(KEY).copy()
    x['race_no'] = x.race_no.astype(int)
    x = x.merge(tw, on=KEY, how='inner')
    x = x[x.tw.notna()].reset_index(drop=True)
    L = [laps_of(s) for s in x.furlongs]
    x['unread'] = [v is None for v in L]
    x['lap_off'] = [v is None or abs(sum(v) - t) > 0.1 for v, t in zip(L, x.tw)]
    x['l3_off'] = [v is None or len(v) < 3 or not (l3 == l3) or abs(sum(v[-3:]) - l3) > 0.05
                   for v, l3 in zip(L, x.race_last3f.astype(float))]
    return x


def win_time(U):
    t = U.groupby([U.track, U.race_date, U.race_no.astype(int)]).time_sec.min().rename('tw').reset_index()
    return t


def empty_corners(s):
    """細部 15: 通過順が空(角の項目が 0 個の JSON のリスト)= データの欠け。"""
    try:
        v = json.loads(s) if isinstance(s, str) else None
    except Exception:
        return False
    return isinstance(v, list) and len(v) == 0


def guard_laps(races, tw, lo, hi, what='区間'):
    """細部 4・5 の見張り(通ったときは数字を出さない)。tw = 勝ち時計(KEY・tw)。"""
    R = races[races.track.isin(NANKAN) & (races.race_date >= lo) & (races.race_date < hi)]
    R = R.merge(tw[KEY], on=KEY, how='inner') if len(R) else R
    emp = R.corners.map(empty_corners).astype(bool) if len(R) else pd.Series([], dtype=bool)
    X, S, unk, _ = d5.corners_table(R[~emp.to_numpy()])
    if sum(unk.values()) > 0 or (len(S) and float((~S.ok).mean()) > 0.001):
        raise SystemExit(f'⛔ {what}の通過順に知らない記号があるか、読めないレースが 0.1% を超えた')
    if len(R) and (emp.groupby(R.race_date.astype(str).str[:4].to_numpy()).mean() > 0.05).any():
        raise SystemExit(f'⛔ {what}の通過順が空のレースの割合が 5% を超えた年がある')
    lt = lap_table(R, tw)
    if len(lt) and (float(lt.lap_off.mean()) > 0.01 or float(lt.l3_off.mean()) > 0.01):
        raise SystemExit(f'⛔ {what}のラップの合計と勝ち時計の差が 0.1 秒を超えるレースか、上がり 3F の不一致が 1% を超えた')


def guard5(B, races, lo, hi):
    """§9 の第 5 版の見張り(通ったときは数字を出さない)。B = build5 の部品。"""
    U, R, info, P, pinfo = B['U'], B['R'], B['info'], B['P'], B['pinfo']
    Us = U[(U.race_date >= lo) & (U.race_date < hi)]
    guard_laps(races, win_time(Us), lo, hi)
    for col, nm in (('SI', 'SI5'), ('SIp', 'SIp'), ('FR', 'FR')):
        m = P.assign(miss=P[col].isna())
        base = m[(m.year >= 2016) & (m.year <= 2021)].groupby('year').miss.mean().max()
        s = m[(m.race_date >= lo) & (m.race_date < hi)].groupby('year').miss.mean()
        if (s > base + 0.05).any():
            raise SystemExit(f'⛔ {nm} の欠けの割合が 2016〜2021 の年ごとの最大 + 5 ポイントを超えた年がある')
    # 細部 14: 段 B・C の入力の続き具合(SIp・FR は SI5 が欠けたときだけ欠けるので、上の見張りでは切れを捕まえられない)
    for nm, ok in (('最初の角の位置', P.pos.notna()), ('流れの点 RS', P.RS.notna()), ('物差しの馬', P.nk.fillna(0) > 0)):
        m = P.assign(ok=ok.to_numpy())
        base = m[(m.year >= 2016) & (m.year <= 2021)].groupby('year').ok.mean().min()
        s = m[(m.race_date >= lo) & (m.race_date < hi)].groupby('year').ok.mean()
        if (s < base - 0.05).any():
            raise SystemExit(f'⛔ {nm}がある割合が 2016〜2021 の年ごとの最小 − 5 ポイントを下回った年がある')
    DD =pd.DataFrame({'dtk': U.dtk.to_numpy(), 'year': U.year.to_numpy(), 'race_date': U.race_date.to_numpy(),
                       'dp': R.D_proj.to_numpy()}).drop_duplicates('dtk')
    sh = DD.assign(ok=DD.dp.notna())
    base = sh[(sh.year >= 2016) & (sh.year <= 2021)].groupby('year').ok.mean().min()
    s = sh[(sh.race_date >= lo) & (sh.race_date < hi)].groupby('year').ok.mean()
    if (s < base - 0.10).any():
        raise SystemExit('⛔ D_proj の作れた日の割合が 2016〜2021 の年ごとの最小 − 10 ポイントを下回った年がある')
    ys = sorted(set(int(y) for y in Us.year.unique()))
    O = info['o']
    for y in ys:
        if y not in O or y - 1 not in O:
            raise SystemExit(f'⛔ {y} 年の o_s が作られていない')
        if max(abs(O[y]['o'][t] - O[y - 1]['o'][t]) for t in NANKAN) > 3:
            raise SystemExit('⛔ o_s の前年からの動きが 3 点を超えた年がある')
        if not pinfo['gamma'].get(y, -1) > 0:
            raise SystemExit('⛔ γ が 0 以下の年がある')


def nonsi_check(T5, T4):
    """細部 7: SI から作らない列(と n・Y1・Y3)が第 4 版の表と 100% 一致。"""
    a = T5[KEY + ['umaban']].astype(str).reset_index(drop=True)
    b = T4[KEY + ['umaban']].astype(str).reset_index(drop=True)
    assert a.equals(b), '第 5 版と第 4 版の表で行が違う'
    cols = NONSI + ['n', 'Y1', 'Y3']
    bad = {c: int((~t5_base.eqmask(T5[c].to_numpy(float), T4[c].to_numpy(float))).sum()) for c in cols}
    if any(bad.values()):
        raise SystemExit(f'⛔ SI から作らない列が第 4 版の表と一致しない: {[c for c, v in bad.items() if v]}')
    return len(cols)


# ================================================================ 第 4 版の学び直しの確かめ
def ref4():
    over, seg = {}, {}
    for line in REF4_MD.read_text(encoding='utf-8').splitlines():
        c = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(c) == 6 and c[0] in ('第 4 版 前日版', '第 4 版 当日版'):
            over.setdefault('pre' if '前日' in c[0] else 'day', [x.split('(')[0] for x in c[1:5]])
        if len(c) == 8 and c[0] == '区切り':
            seg.setdefault(c[1], (c[2], c[3], c[5]))
    assert set(over) == {'pre', 'day'} and set(seg) == {s[0] for s in SEGS}, 't4_day5_open.md の読み取りが崩れた'
    return over, seg


def v4_values(tabs):
    over = {}
    for v in ('pre', 'day'):
        s = t3_eval.summary(tabs['v4' + v])
        over[v] = [f"{s[k][0]:.3f}" for k in ('win', 'top3', 'll1', 'll3')]
    seg = {}
    for name, _, _ in SEGS:
        m = (tabs['v4pre'].seg == name).to_numpy()
        seg[name] = (f'{int(m.sum()):,}', f"{tabs['v4pre'].top3.to_numpy()[m].mean():.3f}",
                     f"{tabs['v4day'].top3.to_numpy()[m].mean():.3f}")
    return over, seg


def check_ref4(tabs):
    if v4_values(tabs) != ref4():
        raise SystemExit('⛔ 第 4 版の学び直しの値が out/t4_day5_open.md と書かれた桁で一致しない')


# ================================================================ 区切りごとの学び直しと予想
def seg_v4(T4, segs):
    P, M1 = {'v4pre': [], 'v4day': []}, None
    for name, lo, hi in segs:
        M = o.train_v4(T4, lo)
        if lo == '2022-01-01':
            M1 = o.same_models(M, 't4')
        t4 = o.seg_rows(T4, lo, hi)
        for v in ('pre', 'day'):
            P['v4' + v].append(t3_eval.predict(*M[v], t4, o.C4[v]).assign(seg=name))
        print('第 4 版 区切り', name, '予想済み', flush=True)
    return {k: pd.concat(v, ignore_index=True) for k, v in P.items()}, M1


def seg_v5(T5, T4, segs):
    P = {'v5pre': [], 'v5day': []}
    for name, lo, hi in segs:
        t5, t4 = o.seg_rows(T5, lo, hi), o.seg_rows(T4, lo, hi)
        o.assert_pair(t5, t4)
        M = train_v5(T5, lo)
        for v in ('pre', 'day'):
            P['v5' + v].append(t3_eval.predict(*M[v], t5, C5[v]).assign(seg=name))
        print('第 5 版 区切り', name, '予想済み', flush=True)
    return {k: pd.concat(v, ignore_index=True) for k, v in P.items()}


def sort_p(P):
    return {k: v.sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True) for k, v in P.items()}


# ================================================================ 比べ方・記録
KS = ('v5pre', 'v4pre', 'v5day', 'v4day')
NM = {'v5pre': '第 5 版 前日版', 'v4pre': '第 4 版 前日版', 'v5day': '第 5 版 当日版', 'v4day': '第 4 版 当日版'}


def breakdown5(tabs):
    rows = []
    base = tabs['v5pre'].assign(year=tabs['v5pre'].race_date.astype(str).str[:4])
    base['era'] = np.where(base.year <= '2023', '2023 年以前', '2024 年以降')
    band = pd.cut(base.n, [0, 8, 12, 99], labels=['5〜8 頭', '9〜12 頭', '13 頭以上']).astype(str)
    for name, key in [('区切り', base.seg), ('年', base.year), ('場', base.track), ('頭数', band), ('制度', base.era)]:
        for val in sorted(key.unique()):
            m = (key == val).to_numpy()
            rows.append([name, val, int(m.sum())] + [float(tabs[k].top3.to_numpy()[m].mean()) for k in KS] +
                        [float(np.nanmean(tabs['v5pre'].fav_top3.to_numpy()[m]))])
    for k in ('v5pre', 'v5day'):
        m = tabs[k].trans.to_numpy()
        rows.append([f'◎ が転入馬({VN[k[2:]]}の ◎)', '', int(m.sum())] + [float(tabs[kk].top3.to_numpy()[m].mean()) for kk in KS] +
                    [float(np.nanmean(tabs['v5pre'].fav_top3.to_numpy()[m]))])
    return rows


def kinds5(P, tabs):
    x = P['v5pre']
    ty = x.groupby(KEY).agg(deb=('l_debut', lambda s: (s == 1).any()), tj=('l_jra', lambda s: (s == 1).any()),
                            tn=('l_nar', lambda s: (s == 1).any())).reset_index()
    ty['kind'] = np.where(ty.deb, '初出走の馬がいる', np.where(ty.tj | ty.tn, '転入初戦の馬がいる(初出走なし)', 'どちらもいない'))
    out = []
    for k in KS:
        Rk = tabs[k].merge(ty[KEY + ['kind']], on=KEY, how='left')
        for kk, g in Rk.groupby('kind'):
            out.append([NM[k], kk, int(len(g)), float(g.win.mean()), float(g.top3.mean()), float(g.fav_top3.mean())])
    return out


def parts_rec(B, lo, hi):
    U, R, info, pinfo = B['U'], B['R'], B['info'], B['pinfo']
    ys = sorted(set(int(y) for y in U[(U.race_date >= lo) & (U.race_date < hi)].year.unique()))
    DD = pd.DataFrame({'dtk': U.dtk.to_numpy(), 'year': U.year.to_numpy(), 'dp': R.D_proj.to_numpy()}).drop_duplicates('dtk')
    L = ['| 年 | o_s(' + '・'.join(NANKAN) + ')| m_AB + m_BA(6 組)| γ | c_y | c\'_y | D_proj の作れた日 |', '|---|---|---|---|---|---|---|']
    for y in ys:
        oy = info['o'][y]
        L.append(f"| {y} | {'・'.join(f'{oy['o'][t]:+.2f}' for t in NANKAN)} | "
                 f"{'・'.join(f'{p['m_sum']:+.2f}' for p in oy['pairs'])} | {pinfo['gamma'][y]:+.4f} | {pinfo['c_y'].get(y, 0.0):+.3f} | "
                 f"{info['c'].get(y, 0.0):+.3f} | {float(DD[DD.year == y].dp.notna().mean()):.3f} |")
    return L


def report(P, T5, old, notes, B, lo, hi, title):
    P = sort_p(P)
    tabs = o.tables(P, T5)
    for k in tabs:
        assert tabs[k][KEY].equals(tabs['v5pre'][KEY])
    f = t3_eval.fmt
    S = {k: t3_eval.summary(R) for k, R in tabs.items()}
    L = [f'# {title}', '',
         f"{len(tabs['v5pre']):,} R・{len(P['v5pre']):,} 頭(確かめる期間の 3 回目の使用)。区間 = 開催日単位のブートストラップ 2,000 回の 95%。"
         '区切りごとに直前までの全部(2015〜)で両版を学び直した。', '',
         '| 版 | ◎ 勝率 | ◎ 3 着以内率 | 対数尤度 Y1(レースあたり)| 対数尤度 Y3 | 1 番人気 3 着以内率 |', '|---|---|---|---|---|---|']
    for k in KS:
        s = S[k]
        L.append(f"| {NM[k]} | {f(s['win'])} | {f(s['top3'])} | {f(s['ll1'])} | {f(s['ll3'])} | {f(s['fav_top3'])} |")
    s = S['v5pre']
    L += [f"| 頭数だけ(段 0)| ― | ― | {s['base_ll1']:.3f} | {s['base_ll3']:.3f} | ― |", '',
          '## 第 4 版との比べ(§7・同じレースの対・第 5 版 − 第 4 版)', '',
          '| 版 | ◎ 3 着以内率の差(95% 区間)| 判定 | ◎ 勝率の差 | 対数尤度の差 Y1 | Y3 | 第 5 版 − 1 番人気(◎ 3 着以内率)|',
          '|---|---|---|---|---|---|---|']
    V = {}
    for v in ('pre', 'day'):
        b = o.diff_boot(tabs['v5' + v], tabs['v4' + v])
        V[v] = b['verdict']
        L.append(f"| {VN[v]} | {f(b['d_top3'])} | **{b['verdict']}** | {f(b['d_win'])} | {f(b['d_ll1'])} | {f(b['d_ll3'])} | "
                 f"{S['v5' + v]['top3'][0] - S['v5' + v]['fav_top3'][0]:+.3f} |")
    better = all(x == '上回った' for x in V.values())
    L += ['', f"**「第 4 版より良い」: {'届いた(毎日の予想表を第 5 版に切り替え、第 4 版の表も並べて作る)' if better else '届かなかった(毎日の予想表は第 4 版のまま)'}**"
          '(前日版・当日版の両方で「上回った」)', '',
          '## 旧 AI との比べ(§7・区切り ⑤・b_all・b_nankan・新 − 旧)', '']
    te5 = P['v5pre'][P['v5pre'].seg == '⑤']
    keep, why, nall = o.old_filter(te5, old, notes)
    L += [f"区切り ⑤ の予想するレース {nall:,} R のうち、旧 AI のファイルに出走した全馬(中止を含む)があるレース {len(keep):,} R で比べる。"
          '除いたレース: ' + '・'.join(f'{k} {v:,}' for k, v in why.items()) + '。', '',
          '| 版 | 旧 AI | レース | 新 ◎ 3 着以内率 | 旧 ◎ 3 着以内率 | 差(95% 区間)| 判定 | ◎ 勝率の差 | 対数尤度の差 Y1 | Y3 | 新 − 1 番人気 |',
          '|---|---|---|---|---|---|---|---|---|---|---|']
    vo = []
    for v in ('pre', 'day'):
        x = P['v5' + v][P['v5' + v].seg == '⑤'].merge(keep, on=KEY, how='inner')
        r = t3_eval.compare_old(x, old)
        for ob in t3_eval.OLD:
            b = r[ob]
            vo.append(b['verdict'])
            L.append(f"| {VN[v]} | {ob} | {r['races']:,} | {b['top3'][0]:.3f} | {b['old_top3'][0]:.3f} | {f(b['d_top3'])} | "
                     f"**{b['verdict']}** | {f(b['d_win'])} | {f(b['d_ll1'])} | {f(b['d_ll3'])} | {f(b['d_fav_top3'])} |")
        L.append(f"({VN[v]}: 旧 AI の確率が空の馬がいたレース {r['races_lacking_old_rows']})")
    beat = all(x == '上回った' for x in vo)
    L += ['', f"**「旧 AI を超えた」(目標): {'届いた' if beat else '届かなかった'}**(前日版・当日版 × b_all・b_nankan の 4 つすべてで「上回った」)",
          '旧 AI は前日の情報だけで月ごとに学び直している。当日版は馬場・馬体重を使う。区切り ⑤ の第 5 版は 2025-08 までで 1 回だけ学んだ。', '',
          '## 内訳(§6・点だけ・記録)', '',
          '| 区分 | 値 | レース | 第 5 版 前日 | 第 4 版 前日 | 第 5 版 当日 | 第 4 版 当日 | 1 番人気 |', '|---|---|---|---|---|---|---|---|']
    for r in breakdown5(tabs):
        L.append(f'| {r[0]} | {r[1]} | {r[2]:,} | ' + ' | '.join(f'{x:.3f}' for x in r[3:]) + ' |')
    L += ['', '### §6 追加 1: レースの種類ごと', '', '| 版 | 種類 | R | ◎ 勝率 | ◎ 3 着以内率 | 1 番人気 3 着以内率 | 差(ポイント)|',
          '|---|---|---|---|---|---|---|']
    for r in kinds5(P, tabs):
        L.append(f'| {r[0]} | {r[1]} | {r[2]:,} | {r[3]:.3f} | {r[4]:.3f} | {r[5]:.3f} | {(r[4] - r[5]) * 100:+.2f} |')
    L += ['', '### §6 追加 2: 確率の当たり具合(見込みの平均 / 実際・馬の数)と温度 β(記録だけ・予想表には当てない)', '']
    for k in KS:
        x = P[k]
        cal = d5.calib(x, x.p1.to_numpy(), x.p3.to_numpy())
        for nm in ('p1', 'p3'):
            L.append(f'- {NM[k]} {nm}: ' + '・'.join(f'{b} {m:.3f}/{a:.3f}({n:,})' for b, n, m, a in cal[nm]))
        be = d5.beta_of(x, x.p1.to_numpy())
        L.append(f"- {NM[k]} β {be['beta']:.3f}(Y1 の対数尤度 {be['LL1_before']:.5f} → {be['LL1_after']:.5f})")
    L += ['', '### §6 追加 3: 部品の値(区間の年)', ''] + parts_rec(B, lo, hi)
    L += ['', '見張り(§9): 書き方・格の読めないレース・SI/テン/上がり/c1 の欠け・転入の 1 戦目・馬のつながり・通過順(入っているレースの読み取り・'
          '空のレースの割合)・ラップ・上がり 3F・'
          'SI5/SIp/FR の欠け・最初の角の位置/流れの点/物差しの馬のある割合・D_proj の作れた日・o_s の動き・γ・SI から作らない列の一致・第 4 版の学び直し(区切り ① の模型と '
          'out/t4_day5_open.md の値)・旧 AI の絞りの数 = すべて通った。', '']
    return L, {'better': better, 'beat': beat, 'v4': V, 'old': vo}


# ================================================================ formatcheck(4 日目)
def corner_cmp(A, B):
    """corners_table 2 つ(RAW・DB)を同じレースで比べる → レースごとの一致。"""
    Xa, Sa, ua, _ = d5.corners_table(A)
    Xb, Sb, ub, _ = d5.corners_table(B)
    S = Sa[KEY + ['ok']].merge(Sb[KEY + ['ok']], on=KEY, suffixes=('_r', '_d'))
    J = Xa.merge(Xb, on=KEY + ['umaban'], how='outer', suffixes=('_r', '_d'))
    bad = np.zeros(len(J), bool)
    for c in ('gap3', 'gap4', 'wide3', 'wide4'):
        bad |= ~t5_base.eqmask(J[c + '_r'], J[c + '_d'])
    badr = J[bad][KEY].drop_duplicates().assign(_b=True)
    S = S.merge(badr, on=KEY, how='left')
    S['same'] = (S.ok_r == S.ok_d) & S._b.isna()
    return S, ua, ub


def formatcheck():
    res = {}
    cols = KEY + ['furlongs', 'race_last3f', 'corners', 'prize_yen']
    # ① RAW と DB(2020〜2021 の写し・作る期間なので結果の列も見てよい)
    ref = load_archive('races')
    ra = ref[ref.track.isin(NANKAN) & (ref.race_date >= '2020-01-01') & (ref.race_date < '2022-01-01')][cols].copy()
    rawdb = pd.read_parquet(V3 / 'db_check_2020_2021_races.parquet')
    db = _align(rawdb, ref)
    db = db[db.track.isin(NANKAN)][cols].copy()
    for x in (ra, db):
        x['race_no'] = x.race_no.astype(int)
    J = ra.merge(db, on=KEY, suffixes=('_r', '_d'))
    one = {}
    la, lb = [laps_of(s) for s in J.furlongs_r], [laps_of(s) for s in J.furlongs_d]
    eq = [(a is None and b is None) or (a is not None and b is not None and len(a) == len(b) and
                                         all(abs(p - q) <= 0.05 for p, q in zip(a, b))) for a, b in zip(la, lb)]
    one['ラップ(各ハロン 0.05 秒以内)'] = [float(np.mean(eq)), int(len(eq) - sum(eq)), sum(a is None for a in la), sum(b is None for b in lb)]
    a, b = J.race_last3f_r.astype(float), J.race_last3f_d.astype(float)
    e3 = (a.isna() & b.isna()) | ((a - b).abs() <= 0.05)
    one['レースの上がり 3F'] = [float(e3.mean()), int((~e3).sum()), int(a.isna().sum()), int(b.isna().sum())]
    Sc, ua, ub = corner_cmp(J[KEY + ['corners_r']].rename(columns={'corners_r': 'corners'}),
                            J[KEY + ['corners_d']].rename(columns={'corners_d': 'corners'}))
    one['通過順の読み(3 角・4 角の差と外の数・全馬)'] = [float(Sc.same.mean()), int((~Sc.same).sum()), int((~Sc.ok_r).sum()), int((~Sc.ok_d).sum())]
    pa, pb = [d5.prize_list(s) for s in J.prize_yen_r], [d5.prize_list(s) for s in J.prize_yen_d]
    ep = [(x is None and y is None) or (x is not None and y is not None and x[:5] == y[:5]) for x, y in zip(pa, pb)]
    one['賞金の 1〜5 着'] = [float(np.mean(ep)), int(len(ep) - sum(ep)), sum(x is None for x in pa), sum(y is None for y in pb)]
    res['one'] = {'races_raw': int(len(ra)), 'races_db': int(len(db)), 'races_join': int(len(J)), 'items': one,
                  'unknown_raw': ua, 'unknown_db': ub, 'ok': all(v[0] >= 0.99 for v in one.values())}
    print('①', {k: round(v[0], 4) for k, v in one.items()}, flush=True)
    # ② 前向きの写し(封じていない)のラップ・通過順・上がり 3F
    fr = _align(pd.read_parquet(V3 / 'db_races_forward_t3.parquet'), ref)
    fr = fr[fr.track.isin(NANKAN) & (fr.race_date >= '2026-09-01')].copy()
    fr['race_no'] = fr.race_no.astype(int)
    fw = pd.read_parquet(V3 / 'db_runs_forward_t3.parquet', columns=KEY + ['time_sec'])
    fw = fw[fw.track.isin(NANKAN)].copy()
    fw['race_date'], fw['race_no'] = fw.race_date.astype(str), fw.race_no.astype(int)
    tw = fw.groupby(KEY).time_sec.min().rename('tw').reset_index()
    tw = tw[tw.tw.notna()]
    run = fr.merge(tw[KEY], on=KEY, how='inner')
    X, S, unk, names = d5.corners_table(run)
    lt = lap_table(run, tw)
    two = {'races_all': int(fr.drop_duplicates(KEY).shape[0]), 'races_run': int(len(S)), 'unknown': unk,
           'corner_unread': float((~S.ok).mean()) if len(S) else 0.0, 'corner_unread_n': int((~S.ok).sum()),
           'corner_names': names, 'lap_unread': int(lt.unread.sum()), 'lap_ok': float(1 - lt.lap_off.mean()),
           'l3_ok': float(1 - lt.l3_off.mean()), 'lap_races': int(len(lt)),
           'date_max': str(fr.race_date.max())}
    two['ok'] = (sum(unk.values()) == 0 and two['corner_unread'] <= 0.001 and two['lap_ok'] >= 0.99 and two['l3_ok'] >= 0.99)
    print('② 前向き', {k: v for k, v in two.items() if k not in ('corner_names',)}, flush=True)
    # ② 確かめる期間・封印・前向きの写しの賞金(結果でない列だけを読む)
    prz = {}
    for p in ('confirm', 'sealed', 'forward'):
        R = pd.read_parquet(V3 / f'db_races_{p}_{o.FILES[p]}.parquet', columns=KEY + ['prize_yen']).drop_duplicates(KEY)
        un = R.prize_yen.map(d5.prize_list).isna()
        nk = R.track.isin(NANKAN)
        kinds = R[un].prize_yen.map(lambda x: 'null' if x is None else str(x)[:20]).value_counts().head(5)
        prz[p] = {'nankan': int(nk.sum()), 'nankan_bad': int((un & nk).sum()), 'other': int((~nk).sum()),
                  'other_bad': int((un & ~nk).sum()), 'other_share': float((un & ~nk).sum() / max(1, (~nk).sum())),
                  'bad_kinds': {str(k): int(v) for k, v in kinds.items()}}
        prz[p]['ok'] = prz[p]['nankan_bad'] == 0 and prz[p]['other_share'] <= 0.01
        print('② 賞金', p, prz[p], flush=True)
    res['two'] = two
    res['prize'] = prz
    (V3 / 't5_day4_format.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    L = ['# 第 5 版 4 日目: 書き方の確かめ(PREREG5 §9 ①②・確かめる期間と封印の結果の列は読まない)', '',
         '台本 src/t5_open.py formatcheck。読み方は open・予想表と同じ関数(t5_open.laps_of・lap_table、t5_day3.corners_table・prize_list)。', '',
         '## ① RAW と DB の写し(2020〜2021・南関)の同じレース', '',
         f"レース RAW {res['one']['races_raw']:,}・DB {res['one']['races_db']:,}・つながった {res['one']['races_join']:,}。", '',
         '| 項目 | 一致 | 一致しない | RAW の欠け・読めない | DB の欠け・読めない | 線 99% |', '|---|---|---|---|---|---|']
    for nm, (r, bad, na, nb) in one.items():
        L.append(f"| {nm} | {r:.4f} | {bad:,} | {na:,} | {nb:,} | {'合' if r >= 0.99 else '否'} |")
    L += ['', f"知らない記号(通過順): RAW {ua or 'なし'}・DB {ub or 'なし'}。", '',
          '## ② 前向きの写し(2026-09-01〜・南関・走ったレース)のラップ・通過順・上がり 3F', '',
          f"レース {two['races_all']:,}(うち走ったレース {two['races_run']:,}・最後の日 {two['date_max']})。", '',
          '| 項目 | 値 | 線 | 合否 |', '|---|---|---|---|',
          f"| 通過順の知らない記号 | {sum(unk.values())}({unk or 'なし'})| 0 | {'合' if sum(unk.values()) == 0 else '否'} |",
          f"| 通過順の読めないレース | {two['corner_unread']:.4f}({two['corner_unread_n']})| ≤ 0.001 | {'合' if two['corner_unread'] <= 0.001 else '否'} |",
          f"| ラップの合計と勝ち時計の差が 0.1 秒以内 | {two['lap_ok']:.4f}({two['lap_races']:,} R・ラップの読めない {two['lap_unread']})| ≥ 0.99 | {'合' if two['lap_ok'] >= 0.99 else '否'} |",
          f"| レースの上がり 3F = 最後の 3 ハロン | {two['l3_ok']:.4f} | ≥ 0.99 | {'合' if two['l3_ok'] >= 0.99 else '否'} |",
          '', f"通過順の角の名前(記録): {names}", '',
          '## ② 賞金の読めないレース(prize_yen だけを読む)', '',
          '| 写し | 南関のレース | 読めない(線 0)| 南関以外のレース | 読めない(線 ≤ 1%)| 合否 |', '|---|---|---|---|---|---|']
    for p, c in prz.items():
        L.append(f"| {p} | {c['nankan']:,} | {c['nankan_bad']} | {c['other']:,} | {c['other_bad']:,}({c['other_share']:.4f})| "
                 f"{'合' if c['ok'] else '否'}{'(記録)' if p == 'forward' else ''} |")
    L += ['', f"読めない賞金の形(記録): { {p: c['bad_kinds'] for p, c in prz.items()} }", '',
          f"**合否: ① {'合' if res['one']['ok'] else '否'}・② 前向き {'合' if two['ok'] else '否'}・② 賞金 "
          f"{'合' if prz['confirm']['ok'] and prz['sealed']['ok'] else '否'}**"]
    OUT_FMT.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


# ================================================================ dry(4 日目)
def dry():
    lo, hi, _ = SPAN['dry']
    h, races = load5('dry')
    o.guard_format(h, races, lo, hi)
    T, B = build5(h, races, lo, hi)
    o.guard_si(B['U'], h, lo, hi)
    guard5(B, races, lo, hi)
    ref5 = o.sort4(pd.read_parquet(FEAT5))
    r21 = ref5[ref5.year == 2021].reset_index(drop=True)
    assert T[KEY + ['umaban']].astype(str).equals(r21[KEY + ['umaban']].astype(str)), '馬の並びが違う'
    assert list(T.columns) == list(ref5.columns), '列が違う'
    cols = ['n', 'Y1', 'Y3', 'pop'] + ALL5
    A, Bm = T[cols].to_numpy(float), r21[cols].to_numpy(float)
    eq = (np.isnan(A) & np.isnan(Bm)) | (np.abs(A - Bm) <= 1e-9)
    print(f'材料の一致(2021・第 5 版の表): {int(eq.sum()):,} / {eq.size:,}', flush=True)
    assert eq.all(), [c for c, k in zip(cols, eq.all(0)) if not k]
    ex4 = o.sort4(pd.read_parquet(d3.FEAT))
    n4 = nonsi_check(T, ex4[ex4.year == 2021].reset_index(drop=True))
    print(f'SI から作らない列の一致(2021・feat_t4_explore): {n4} 列 100%', flush=True)
    T5 = pd.concat([ref5[ref5.race_date < lo], T], ignore_index=True)
    o.guard_transfer(T5, lo, hi)
    print('見張り OK', flush=True)
    # 第 4 版の区切り ① の学び直し(2015〜2021)が models/t4_* と一致するか・t4_day5_open.md の読み取り
    if not o.same_models(o.train_v4(ex4, '2022-01-01'), 't4'):
        raise SystemExit('⛔ 第 4 版の区切り ① の学び直しが models/t4_* と一致しない')
    print('第 4 版の区切り ① の学び直し = models/t4_* と文字列一致', flush=True)
    over, seg = ref4()
    print('t4_day5_open.md の読み取り: 全体 2 版・区切り', len(seg), flush=True)
    segs = [('2021', lo, hi)]
    P4, _ = seg_v4(ex4, segs)
    P5 = seg_v5(T5, ex4, segs)
    P = sort_p({**P5, **P4})
    # 2021 の学び直しが 3 日目の当てはめ外と一致するか
    pr = pd.read_parquet(d5.PREDS)
    pr = pr[pr.year == 2021].sort_values(KEY + ['umaban'], kind='mergesort').reset_index(drop=True)
    for k in KS:
        x = P[k]
        assert x[KEY + ['umaban']].astype(str).equals(pr[KEY + ['umaban']].astype(str))
        dd = max(float(np.abs(x.p1.to_numpy() - pr[f'{k}_p1'].to_numpy()).max()),
                 float(np.abs(x.p3.to_numpy() - pr[f'{k}_p3'].to_numpy()).max()))
        print(f'2021 の学び直し {k}: 3 日目の当てはめ外との差の最大 {dd:.2e}', flush=True)
        assert dd <= 1e-9, f'{k} の 2021 の学び直しが 3 日目の当てはめ外と一致しない'
    tabs = o.tables(P, T5)
    z = o.diff_boot(tabs['v4pre'], tabs['v4pre'])
    assert all(abs(x) < 1e-12 for k in ('d_top3', 'd_win', 'd_ll1', 'd_ll3') for x in z[k]) and z['verdict'] == '差は誤差の範囲'
    print('第 4 版を自分自身と比べて差 0・判定', z['verdict'], flush=True)
    for v in ('pre', 'day'):
        b = o.diff_boot(tabs['v5' + v], tabs['v4' + v])
        print(f"(探索 2021・記録)第 5 版 − 第 4 版 {v}: ◎ 3 着以内率の差 {t3_eval.fmt(b['d_top3'])} {b['verdict']}", flush=True)
    # 旧 AI の比べ方: 第 5 版自身を b_all、頭数だけを b_nankan にしたファイルから、中止の馬と 1 頭を抜く(第 4 版 dry と同じ)
    notes = h[KEY + ['umaban', 'finish_note']].drop_duplicates(KEY + ['umaban'])
    x = P['v5pre'].merge(notes, on=KEY + ['umaban'], how='left')
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
    keep, why, nall = o.old_filter(P['v5pre'], fk, notes)
    ex_other = x[other & ~stop][KEY].drop_duplicates().merge(drop_race.assign(_f=1), on=KEY, how='left')
    ex_other = ex_other[ex_other._f.isna()].drop(columns='_f')
    e_stop = exp_stop.merge(ex_other.assign(_o=1), on=KEY, how='left')
    assert why['ファイルに無いレース'] == 1 and why['そのほかの馬が無い'] == len(ex_other) == 1
    assert why['中止の馬だけが無い'] == int(e_stop._o.isna().sum()), why
    assert len(keep) + sum(why.values()) == nall
    print('旧 AI の絞り: 理由別', why, '/ 全', nall, flush=True)
    r = t3_eval.compare_old(P['v5pre'].merge(keep, on=KEY), fk)
    assert r['races'] == len(keep) and r['races_lacking_old_rows'] == 0
    assert all(abs(v) < 1e-12 for k in ('d_top3', 'd_win', 'd_ll1', 'd_ll3') for v in r['b_all'][k])
    assert r['b_all']['verdict'] == '差は誤差の範囲' and r['b_nankan']['verdict'] == '上回った'
    P['v5pre'] = P['v5pre'].assign(seg='⑤')  # report は区切り ⑤ を旧 AI と比べるので、dry では 2021 を ⑤ とみなす
    P['v5day'] = P['v5day'].assign(seg='⑤')
    L, J = report(P, T5, fk, notes, B, lo, hi, 'dry(書き出さない)')
    assert any('「第 4 版より良い」' in s for s in L) and any('「旧 AI を超えた」' in s for s in L)
    assert sum(s.startswith(('| 前日版 | b_', '| 当日版 | b_')) for s in L) == 4
    print('dry OK', flush=True)


# ================================================================ open(5 日目・判断の日)
def open_():
    if OUT_OPEN.exists():
        raise SystemExit('⛔ 確かめる期間は第 5 版で開けてある(1 回だけ)')
    o.verify()
    lo, hi, _ = SPAN['open']
    h, races = load5('open')
    o.guard_format(h, races, lo, hi)
    T, B = build5(h, races, lo, hi)
    o.guard_si(B['U'], h, lo, hi)
    guard5(B, races, lo, hi)
    op4 = o.sort4(pd.read_parquet(o.FEAT_OPEN))
    nonsi_check(T, op4)
    ex5 = pd.read_parquet(FEAT5)
    T5 = pd.concat([ex5, T[ex5.columns]], ignore_index=True)
    assert not T5.duplicated(KEY + ['umaban']).any()
    o.guard_transfer(T5, lo, hi)
    ex4 = pd.read_parquet(d3.FEAT)
    T4 = pd.concat([ex4, op4[ex4.columns]], ignore_index=True)
    assert not T4.duplicated(KEY + ['umaban']).any()
    notes = h[KEY + ['umaban', 'finish_note']].drop_duplicates(KEY + ['umaban'])
    old = t3_eval.load_old(t3_open.OLD_MONTHS)
    keep, _, _ = o.old_filter(o.seg_rows(T5, *SEGS[-1][1:]), old, notes)
    if len(keep) != OLD_RACES:
        raise SystemExit('⛔ 旧 AI の絞りで残るレースの数が第 4 版 5 日目と違う(読み込みのずれ)')
    T.to_parquet(FEAT_OPEN5, index=False)
    print('見張り OK', flush=True)
    P4, m1 = seg_v4(T4, SEGS)
    if not m1:
        raise SystemExit('⛔ 第 4 版の区切り ① の学び直しが models/t4_* と文字列で一致しない')
    check_ref4(o.tables(sort_p(P4), T4))
    print('第 4 版の学び直しの確かめ OK', flush=True)
    P5 = seg_v5(T5, T4, SEGS)
    L, J = report({**P5, **P4}, T5, old, notes, B, lo, hi,
                  '第 5 版 5 日目: 確かめる期間(2022-01〜2026-08・5 区切り)を 1 回だけ開ける(3 回目の使用)')
    OUT_OPEN.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    {'fit': fit, 'formatcheck': formatcheck, 'dry': dry, 'open': open_}[sys.argv[1]]()
