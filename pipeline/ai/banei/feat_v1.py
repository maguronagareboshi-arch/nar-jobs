# -*- coding: utf-8 -*-
"""ばんえい 第 1 版の材料の表(ばんえい 決め 1・out/banei_design_plan.md §A・§B・§5)。

  py -3.12 -X utf8 src/banei/feat_v1.py            # 表を作る
  py -3.12 -X utf8 src/banei/feat_v1.py --leakcheck # 漏れの点検(切った日で作り直して一致を見る)

元: v3/official/{runs,races,profiles}.parquet の帯広ば・v3/banei_kb/kd_banei_runs.parquet(2013 年以前の走りの履歴だけ)。
出力: v3/banei_kb/feat_v1.parquet(1 頭 1 行)・feat_v1_cols.json(材料の列)・feat_v1_base.json(基準時計の係数)。
漏れの決まり(§A 直す 5・直す 3・直す 4):
  - 率・履歴は全部「前の日まで」(merge_asof の allow_exact_matches=False・日ごとにまとめて更新)。
  - 基準時計の係数は学びの期間(2014-04〜2022-03)の走りだけで作る。
  - 同じ日の前のレースの結果は使わない。当日の水分・天候はその日の 1R の値。
  - 当日に分かるのは出馬表(重量・馬番・騎手・組)と当日の馬体重だけ。
"""
# 2026-10-28 nar-jobs に写した(v3 の src/banei/feat_v1.py の写し・計算は同じ)。変えたのは置き場(環境変数 BANEI_V3)と、研究だけの関数を外したこと。
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

import numpy as np
import pandas as pd

V3 = os.environ.get('BANEI_V3', 'C:/Users/kouki/nankan_ai/v3/').rstrip('/') + '/'
OUT = V3 + 'banei_kb/'
TRAIN = ('2014-04-01', '2022-04-01')
NLAG = 10


# ---------------------------------------------------------------- 読み込み
def load():
    ru = pd.read_parquet(V3 + 'official/runs.parquet', filters=[('track', '==', '帯広ば')])
    ra = pd.read_parquet(V3 + 'official/races.parquet', filters=[('track', '==', '帯広ば')])
    pr = pd.read_parquet(V3 + 'official/profiles.parquet')
    kd = pd.read_parquet(V3 + 'banei_kb/kd_banei_runs.parquet')
    return ru, ra, pr, kd


def parse_class(name, cond):
    nm = unicodedata.normalize('NFKC', name or '').replace(' ', '').replace('\u3000', '')
    cd = unicodedata.normalize('NFKC', cond or '').replace(' ', '').replace('\u3000', '')
    m = re.search(r'([2-5])歳(以上)?', cd)
    age_lim = (m.group(1) + ('+' if m.group(2) else '')) if m else ''
    young = age_lim in ('2', '3')
    kumi = np.nan
    if 'オープン' in nm or 'OP' in nm:
        tok = 'OP'
    elif '選抜' in nm:
        tok = 'SEN'
    elif '新馬' in nm:
        tok = 'NEW'
    elif '未受賞' in nm:
        tok = 'MI'
    elif '受賞' in nm:
        tok = 'JU'
        k = re.search(r'受賞-(\d+)', nm)
        kumi = float(k.group(1)) if k else np.nan
    else:
        ms = list(re.finditer(r'(?<![A-Za-z])([A-D])([1-4])?(?:-(\d+))?(?![A-Za-z0-9])', nm))
        if ms:
            g = ms[-1]
            tok = g.group(1) + (g.group(2) or '')
            kumi = float(g.group(3)) if g.group(3) else np.nan
        else:
            tok = 'X'
    if young:
        lv = {'OP': 5, 'SEN': 5, 'A': 4, 'B': 3, 'C': 2, 'D': 1, 'JU': 1.5, 'MI': 0.5, 'NEW': 0}.get(tok[0] if tok[0] in 'ABCD' else tok, np.nan)
    else:
        lv = {'OP': 12, 'SEN': 11, 'A1': 10, 'A2': 9, 'A': 9.5, 'B1': 8, 'B2': 7, 'B3': 6, 'B4': 5, 'B': 6.5,
              'C1': 4, 'C2': 3, 'C': 3.5, 'D': 2, 'D1': 2}.get(tok, np.nan)
    named = bool(re.search(r'(特別|賞|記念|杯|カップ|C$|ステークス|ダービー|オークス)', re.sub(r'[A-D][1-4]?-\d+.*$', '', nm)))
    stakes = bool(re.search(r'第\d+回', nm)) and tok in ('OP', 'SEN')
    grade = 2 if stakes else (1 if named or re.search(r'第\d+回', nm) else 0)
    return dict(cls_tok=tok, cls_age=age_lim, cls_young=int(young), cls_level=lv, kumi=kumi, grade=grade,
                hcap=3 if 'ハンデ' in nm else (2 if '別定' in nm else (1 if '定量' in nm else 0)),
                kitei=int('規定' in cd), mare_only=int('牝' in nm), area_lim=int('産地限定' in nm or '産駒特別' in nm),
                cls_key=('Y' + age_lim if young else 'O') + tok)


def fy_of(d):
    return np.where(d.dt.month >= 4, d.dt.year, d.dt.year - 1)


def prep(ru, ra, pr, kd, cutoff=None, race_going=False):
    """公式の走り(2014-01〜)と KDSCOPE の走り(〜2013-12)を 1 本の履歴にし、予想の行(公式の全出走)を作る。
    cutoff を渡すと、その日より後を落とし、その日の結果(着・時計・2R 以降の水分と天候)を空にする(漏れの点検)。"""
    ra = ra[ra.cancelled.isna()].copy()
    ru = ru.merge(ra[['race_date', 'race_no']], on=['race_date', 'race_no'])
    if cutoff is not None:
        ru = ru[ru.race_date <= cutoff].copy()
        ra = ra[ra.race_date <= cutoff].copy()
        d = ru.race_date == cutoff
        scr = ru.finish_note.isin(['取消', '除外', '出走取消', '競走除外'])
        ru.loc[d, ['finish', 'time_sec', 'popularity']] = np.nan
        ru.loc[d & ~scr, 'finish_note'] = None
        ru.loc[d, 'margin'] = None
        d1 = (ra.race_date == cutoff) & (ra.race_no > ra[ra.race_date == cutoff].race_no.min())
        ra.loc[d1, ['going', 'weather']] = None
    ra['going_f'] = pd.to_numeric(ra.going, errors='coerce')
    cl = pd.DataFrame([parse_class(a, b) for a, b in zip(ra.race_name, ra.condition)], index=ra.index)
    ra = pd.concat([ra, cl], axis=1)
    ra['prize1'] = ra.prize_yen.map(lambda x: float(x[0]) if x is not None and len(x) else np.nan)
    ra['prize_list'] = ra.prize_yen.map(lambda x: list(x) if x is not None else [])
    # 当日の水分・天候 = その日の 1R の値(§A 直す 3)
    first = ra.sort_values('race_no').groupby('race_date').first()[['going_f', 'weather']]
    first.columns = ['day_going', 'day_weather']
    ra = ra.merge(first, left_on='race_date', right_index=True, how='left')
    if race_going:  # 参考だけ(§A 直す 3): レースごとの水分・天候で当てた形
        ra['day_going'] = ra.going_f; ra['day_weather'] = ra.weather

    ru = ru.merge(ra[['race_date', 'race_no', 'going_f', 'weather', 'day_going', 'day_weather', 'cls_tok', 'cls_age',
                      'cls_young', 'cls_level', 'kumi', 'grade', 'hcap', 'kitei', 'mare_only', 'area_lim', 'cls_key',
                      'prize1', 'prize_list', 'field_size']], on=['race_date', 'race_no'], how='left')
    ru['by'] = ru.race_date.str[:4].astype(int) - ru.age
    ru['hk'] = ru.horse_name + '_' + ru.by.astype(str)
    ru['scratch'] = ru.finish_note.isin(['取消', '除外', '出走取消', '競走除外']).astype(int)
    ru['dnf'] = ((ru.finish_note.isin(['中止', '競走中止']) | (ru.margin == '競走取止め')) & (ru.scratch == 0)).astype(int)
    ru['prize_won'] = [float(pl[int(f) - 1]) if f == f and 1 <= f <= len(pl) else 0.0 for f, pl in zip(ru.finish, ru.prize_list)]
    ru['src'] = 'off'

    # KDSCOPE(2013 年以前だけ)。騎手・調教師の名は重なる期間の対応で公式の 3 文字名へ寄せる
    kdo = kd[kd.race_date < '2014-01-01'].copy()
    ov = kd[kd.race_date >= '2014-01-01'].merge(ru[['race_date', 'race_no', 'runner_number', 'jockey', 'trainer']],
                                                 left_on=['race_date', 'race_no', 'umaban'],
                                                 right_on=['race_date', 'race_no', 'runner_number'], suffixes=('_k', ''))
    jmap = ov.groupby('jockey_k').jockey.agg(lambda s: s.value_counts().index[0]).to_dict()
    tmap = ov.groupby('trainer_k').trainer.agg(lambda s: s.value_counts().index[0]).to_dict()
    kdo['jockey'] = kdo.jockey.map(lambda x: jmap.get(x, 'kd:' + str(x)))
    kdo['trainer'] = kdo.trainer.map(lambda x: tmap.get(x, 'kd:' + str(x)))
    kdo['by'] = kdo.race_date.str[:4].astype(int) - kdo.age.astype(int)
    kdo['hk'] = kdo.horse_name + '_' + kdo.by.astype(str)
    kdo['scratch'] = kdo.ijo.isin([1, 2, 3]).astype(int)
    kdo['dnf'] = (kdo.ijo == 4).astype(int)
    kdo['prize_won'] = kdo.prize_100yen.fillna(0) * 100
    kdo['runner_number'] = kdo.umaban
    kdo['sex'] = kdo.sex_cd.map({1.0: '牡', 2.0: '牝', 3.0: 'セン'})
    kdo['src'] = 'kd'
    cols = ['src', 'race_date', 'race_no', 'runner_number', 'hk', 'jockey', 'trainer', 'finish', 'time_sec', 'scratch', 'dnf', 'prize_won', 'age', 'sex']
    H = pd.concat([ru, kdo[cols]], ignore_index=True)
    H['date'] = pd.to_datetime(H.race_date)
    H['fy'] = fy_of(H.date)
    H['rkey'] = H.race_date + '_' + H.race_no.astype(str).str.zfill(2)

    # 血統(公式の馬の情報・馬名 + 生年)
    pr = pr.assign(hk=pr.horse_name + '_' + pr.birth_date.str[:4])[['hk', 'sire', 'dam', 'broodmare_sire', 'breeder', 'birth_date']].rename(columns={'birth_date': 'pr_birth'})
    pr = pr.drop_duplicates('hk')
    return H, ra, pr


# ---------------------------------------------------------------- 基準時計(学びの期間だけ)
def gbin(g):
    return np.clip(np.round(g, 1), 0.4, 4.0)


def fit_base(H):
    t = H[(H.src == 'off') & (H.race_date >= TRAIN[0]) & (H.race_date < TRAIN[1]) & H.finish.notna() & H.time_sec.notna()
          & H.going_f.notna() & (H.dnf == 0)].copy()
    X = pd.get_dummies(pd.DataFrame({'g': gbin(t.going_f).astype(str), 'w': (np.clip(t.carried_weight, 460, 900) // 20 * 20).astype(int).astype(str),
                                     'c': t.cls_key}), drop_first=False).astype(float)
    y = np.log(t.time_sec.values)
    beta, *_ = np.linalg.lstsq(X.values, y, rcond=None)
    coef = dict(zip(X.columns, beta))
    # 1 着との時計差を重量差で直す係数(同じレースの中で 秒差 ~ 重量差)
    t['wt'] = t.groupby('rkey').time_sec.transform('min')
    t['wcw'] = t.groupby('rkey').carried_weight.transform('mean')
    m = (t.time_sec - t.wt < 60)
    b_w = float(np.polyfit((t.carried_weight - t.wcw)[m], (t.time_sec - t.wt)[m], 1)[0])
    p3 = float((t.finish <= 3).mean())
    p1 = float((t.finish == 1).mean())
    return dict(coef=coef, b_w=b_w, p3=p3, p1=p1, n=int(len(t)))


def apply_base(H, base):
    coef = base['coef']
    g = 'g_' + gbin(H.going_f).astype(str)
    w = 'w_' + (np.clip(H.carried_weight, 460, 900) // 20 * 20).fillna(0).astype(int).astype(str)
    c = 'c_' + H.cls_key.fillna('')
    mean_c = np.mean([v for k, v in coef.items() if k.startswith('c_')])
    pred = g.map(coef).astype(float) + w.map(coef).astype(float) + c.map(coef).fillna(mean_c).astype(float)
    ok = (H.src == 'off') & H.time_sec.notna() & (H.dnf == 0) & H.going_f.notna()
    H['tidx'] = np.where(ok, (pred - np.log(H.time_sec)) * 100, np.nan)  # 大きいほど速い(% 単位)
    # 日ごとの馬場差(前走以前の時計の直しにだけ使う・§A 直す 4)
    win = H[ok & (H.finish == 1)].groupby('race_date').tidx.median()
    H['dayvar'] = H.race_date.map(win)
    H['tidx_dc'] = H.tidx - H.dayvar
    rk = H.groupby('rkey')
    H['t_win'] = rk.time_sec.transform('min')
    H['margin_s'] = H.time_sec - H.t_win
    H['cw_win'] = H.rkey.map(H[H.finish == 1].drop_duplicates('rkey').set_index('rkey').carried_weight)
    H['margin_w'] = H.margin_s - base['b_w'] * (H.carried_weight - H.cw_win)
    H['tidx_rank'] = rk.tidx.rank(ascending=False, pct=True)
    H['race_tidx_win'] = H.rkey.map(H[H.finish == 1].drop_duplicates('rkey').set_index('rkey').tidx)
    return H


# ---------------------------------------------------------------- 力の値・直接対決(日ごとにまとめて更新)
def ratings(H):
    h = H[H.scratch == 0].sort_values(['date', 'race_no']).copy()
    h['ord'] = np.where(h.finish.notna(), h.finish, np.where(h.dnf == 1, 99, np.nan))
    R = defaultdict(lambda: 1500.0)
    Rm = defaultdict(lambda: 1500.0)
    N = defaultdict(int)
    beat = defaultdict(int)          # (a, b): a が b に先着した数
    last_ahead = {}                  # 馬 → 前走で先着された馬の集合
    last_win = {}                    # 馬 → (前走の勝ち馬, その時点の勝ち馬の走数・3 着内数)
    cum = defaultdict(lambda: [0, 0])
    out = {}
    for d, dd in h.groupby('date', sort=True):
        races = [g for _, g in dd.groupby('rkey')]
        # 前の日までの値で今日の行を作る
        for g in races:
            hs = g.hk.tolist()
            pre = np.array([R[x] for x in hs])
            for i, x in enumerate(hs):
                opp = [y for y in hs if y != x]
                w_ = sum(beat[(x, y)] for y in opp)
                l_ = sum(beat[(y, x)] for y in opp)
                la = last_ahead.get(x, set())
                lw = last_win.get(x)
                if lw is not None and lw[0] in cum:
                    c = cum[lw[0]]
                    wn, w3 = c[0] - lw[1], c[1] - lw[2]
                else:
                    wn, w3 = np.nan, np.nan
                out[(g.rkey.iat[0], x)] = (R[x], Rm[x], N[x], float(np.mean(np.delete(pre, i))) if len(hs) > 1 else np.nan,
                                           w_ - l_, w_ + l_, sum(1 for y in opp if y in la), wn, w3)
        # 結果で更新(結果の無い行は更新しない)
        for g in races:
            g = g[g.ord.notna()]
            if len(g) < 2:
                continue
            hs = g.hk.tolist(); o = g.ord.values; ti = g.tidx.values
            r0 = np.array([R[x] for x in hs]); m0 = np.array([Rm[x] for x in hs])
            n = len(hs)
            e = 1 / (1 + 10 ** ((r0[None, :] - r0[:, None]) / 400))
            s = (o[:, None] < o[None, :]).astype(float) + 0.5 * (o[:, None] == o[None, :])
            np.fill_diagonal(e, 0); np.fill_diagonal(s, 0)
            dr = 32 * (s - e).sum(1) / (n - 1)
            em = 1 / (1 + 10 ** ((m0[None, :] - m0[:, None]) / 400))
            if np.isfinite(ti).sum() >= 2:
                tt = np.where(np.isfinite(ti), ti, np.nanmin(ti) - 5)
                sm = 1 / (1 + np.exp(-(tt[:, None] - tt[None, :]) / 3))
            else:
                sm = s
            np.fill_diagonal(em, 0); np.fill_diagonal(sm, 0)
            dm = 32 * (sm - em).sum(1) / (n - 1)
            wk = hs[int(np.argmin(o))]
            for i, x in enumerate(hs):
                R[x] += dr[i]; Rm[x] += dm[i]; N[x] += 1
                last_ahead[x] = {hs[j] for j in range(n) if o[j] < o[i]}
                last_win[x] = (wk, cum[wk][0], cum[wk][1]) if wk != x else None
                for j in range(n):
                    if o[i] < o[j]:
                        beat[(x, hs[j])] += 1
            for i, x in enumerate(hs):
                cum[x][0] += 1; cum[x][1] += int(o[i] <= 3)
    df = pd.DataFrame([(k[0], k[1]) + v for k, v in out.items()],
                      columns=['rkey', 'hk', 'l199_elo', 'l208_elo_t', 'l199_elo_n', 'l202_opp_elo_now', 'l201_h2h_net', 'l201_h2h_n',
                               'l200_beaten_by_in_field', 'l203_lastwinner_runs', 'l203_lastwinner_top3'])
    return df


# ---------------------------------------------------------------- 率(前の日まで)
def ent_rate(H, T, keys, name, p, windows=(None,), hkeys=None, k=5.0):
    """keys の組ごとの 3 着内・勝ちの率を前の日まで数えて T に付ける。hkeys = H 側の列名(T 側と違う時)。"""
    hkeys = hkeys or keys
    h = H[(H.scratch == 0)].copy()
    h['n_'] = 1; h['t3_'] = (h.finish <= 3).astype(int); h['w1_'] = (h.finish == 1).astype(int)
    h = h.dropna(subset=hkeys)
    g = h.groupby(hkeys + ['date'])[['n_', 't3_', 'w1_']].sum().reset_index()
    g[['cn', 'c3', 'c1']] = g.groupby(hkeys)[['n_', 't3_', 'w1_']].cumsum()
    g = g.rename(columns=dict(zip(hkeys, keys))).sort_values('date')
    for kk in keys:
        g[kk] = g[kk].astype(str)
    tt = T[keys + ['date']].copy()
    for kk in keys:
        tt[kk] = tt[kk].astype(str)
    tt['_i'] = np.arange(len(tt))
    res = {}
    for wd in windows:
        q = tt.copy()
        q['date'] = q.date if wd is None else q.date - pd.Timedelta(days=wd)
        q = q.sort_values('date')
        m = pd.merge_asof(q, g[keys + ['date', 'cn', 'c3', 'c1']], on='date', by=keys, allow_exact_matches=False)
        m = m.sort_values('_i')
        res[wd] = m[['cn', 'c3', 'c1']].fillna(0).values
    a = res[None]
    if len(windows) > 1:
        a = a - res[windows[1]]
    n, c3, c1 = a[:, 0], a[:, 1], a[:, 2]
    ok = T[keys].notna().all(1).values
    T[name + '_n'] = np.where(ok, n, np.nan)
    T[name + '_r3'] = np.where(ok, (c3 + k * p['p3']) / (n + k), np.nan)
    T[name + '_r1'] = np.where(ok, (c1 + k * p['p1']) / (n + k), np.nan)


# ---------------------------------------------------------------- 本体
def build(ru, ra, pr, kd, cutoff=None, base=None, race_going=False):
    H, ra, pr = prep(ru, ra, pr, kd, cutoff, race_going)
    if base is None:
        base = fit_base(H)
    H = apply_base(H, base)
    H = H.merge(pr, on='hk', how='left')
    H['ran'] = 1 - H.scratch
    H['top3'] = (H.finish <= 3).astype(float)
    H['win'] = (H.finish == 1).astype(float)
    H['fin_rel'] = H.finish / H.groupby('rkey').ran.transform('sum')
    H['gband'] = pd.cut(H.going_f, [-1, 1.05, 1.95, 2.95, 99], labels=False)
    H['wband'] = (H.carried_weight // 50).astype('float')
    H['wband10'] = (H.carried_weight // 10).astype('float')
    H['cw_rel'] = H.carried_weight - H.groupby('rkey').carried_weight.transform('mean')
    H['winter'] = H.date.dt.month.isin([12, 1, 2, 3]).astype(int)
    H['snow'] = H.weather.fillna('').str.contains('雪').astype(int)
    H['young_lv'] = H.cls_young

    # 予想の行 = 公式の全出走(取消も残す)
    T = H[H.src == 'off'].copy()
    T['n_entries'] = T.groupby('rkey').hk.transform('size')
    T['n_start'] = T.groupby('rkey').ran.transform('sum')

    # ---- 馬ごとの履歴(走った行だけ・前の日まで)
    R_ = H[H.ran == 1].sort_values(['hk', 'date']).copy()
    gh = R_.groupby('hk')
    R_['c_n'] = gh.cumcount() + 1
    R_['c_noff'] = gh.src.transform(lambda s: (s == 'off').cumsum())
    for c in ['top3', 'win', 'dnf', 'prize_won', 'snow']:
        R_['c_' + c] = gh[c].cumsum()
    R_['c_cwmax'] = gh.carried_weight.cummax()
    R_['c_cwmax'] = R_.groupby('hk').c_cwmax.ffill()
    R_['_cwwin'] = R_.carried_weight.where(R_.finish == 1)
    R_['c_cwwinmax'] = R_.groupby('hk')._cwwin.cummax()
    R_['c_cwwinmax'] = R_.groupby('hk').c_cwwinmax.ffill()
    R_['c_cw_best'] = R_.carried_weight.where(R_.tidx == R_.groupby('hk').tidx.cummax())
    R_['c_cw_best'] = R_.groupby('hk').c_cw_best.ffill()
    R_['c_bw_sum'] = R_.groupby('hk').body_weight.cumsum(); R_['c_bw_cnt'] = R_.body_weight.notna().astype(int).groupby(R_.hk).cumsum()
    bw3 = R_.body_weight.where(R_.finish <= 3)
    R_['c_bw3_sum'] = bw3.fillna(0).groupby(R_.hk).cumsum(); R_['c_bw3_cnt'] = bw3.notna().astype(int).groupby(R_.hk).cumsum()
    for nm, cond in [('light', R_.going_f >= 2.5), ('heavy', R_.going_f <= 1.2), ('wint', R_.winter == 1), ('summ', R_.winter == 0),
                     ('snowd', R_.snow == 1), ('a_lv', (R_.cls_level >= 9) & (R_.cls_young == 0)), ('stk', R_.grade == 2)]:
        R_['c_' + nm + '_n'] = cond.astype(int).groupby(R_.hk).cumsum()
        R_['c_' + nm + '_3'] = (cond & (R_.finish <= 3)).astype(int).groupby(R_.hk).cumsum()
    R_['_ret'] = (R_.date - gh.date.shift()).dt.days >= 60
    R_['c_ret_n'] = R_._ret.astype(int).groupby(R_.hk).cumsum()
    R_['c_ret_3'] = (R_._ret & (R_.finish <= 3)).astype(int).groupby(R_.hk).cumsum()
    R_['_last_win_date'] = R_.date.where(R_.finish == 1)
    R_['c_last_win_date'] = R_.groupby('hk')._last_win_date.ffill()
    R_['_last_ret_date'] = R_.date.where(R_._ret | (gh.cumcount() == 0))
    R_['c_last_ret_date'] = R_.groupby('hk')._last_ret_date.ffill()
    R_['c_runs_since_ret'] = R_.groupby(['hk', R_.c_last_ret_date]).cumcount() + 1
    # 連勝(勝ち時計が遅い = 勝ち馬の時計の指数が 0 未満)
    w = (R_.finish == 1).astype(int)
    R_['c_streak'] = w.groupby((w != w.groupby(R_.hk).shift()).cumsum()).cumsum() * w
    R_['c_slowwin3'] = ((R_.finish == 1) & (R_.tidx < 0)).astype(int)
    R_['c_slowwin3'] = R_.groupby('hk').c_slowwin3.transform(lambda s: s.rolling(3, min_periods=1).sum())
    lagv = ['date', 'finish', 'fin_rel', 'top3', 'tidx', 'tidx_dc', 'going_f', 'carried_weight', 'body_weight', 'cls_level', 'cls_young',
            'kumi', 'cls_key', 'jockey', 'trainer', 'margin_s', 'margin_w', 'prize1', 'dnf', 'time_sec', 'tidx_rank', 'cw_rel',
            'dayvar', 'race_tidx_win', 'grade', 'src', 'mare_only', 'cls_age', 'rkey']
    for k in range(1, NLAG + 1):
        for v in lagv:
            R_[f'L{k}_{v}'] = gh[v].shift(k - 1)
    # 年度の中の走数・3 着内・賞金
    gf = R_.groupby(['hk', 'fy'])
    R_['f_n'] = gf.cumcount() + 1; R_['f_3'] = gf.top3.cumsum(); R_['f_prize'] = gf.prize_won.cumsum()
    R_['fy_s'] = R_.fy
    keep = ['hk', 'date', 'fy_s'] + [c for c in R_.columns if c.startswith(('c_', 'L', 'f_'))]
    S = R_[keep].sort_values('date')
    T = T.sort_values('date')
    T = pd.merge_asof(T, S, on='date', by='hk', allow_exact_matches=False)
    T = T.sort_values(['race_date', 'race_no', 'runner_number']).reset_index(drop=True)
    # 1 年前の頃の値(前の日まで・±45 日)
    yr = R_[['hk', 'date', 'tidx', 'body_weight', 'cls_level', 'cls_young']].rename(columns={'tidx': 'y1_tidx', 'body_weight': 'y1_bw', 'cls_level': 'y1_cls', 'cls_young': 'y1_young'})
    yr = yr.sort_values('date'); yr['date_y'] = yr.date
    q = T[['hk', 'date']].copy(); q['_i'] = np.arange(len(q)); q['date'] = q.date - pd.Timedelta(days=365)
    m = pd.merge_asof(q.sort_values('date'), yr, on='date', by='hk', direction='nearest', tolerance=pd.Timedelta(days=45)).sort_values('_i')
    for c in ['y1_tidx', 'y1_bw', 'y1_cls', 'y1_young']:
        T[c] = m[c].values
    # 最後の出走(取消を含む)の状態
    E = H[H.src == 'off'].sort_values('date')[['hk', 'date', 'scratch', 'dnf']].rename(columns={'scratch': 'e_scr', 'dnf': 'e_dnf'})
    T['_i'] = np.arange(len(T))
    T = pd.merge_asof(T, E, on='date', by='hk', allow_exact_matches=False).sort_values('_i').reset_index(drop=True)

    F = pd.DataFrame(index=T.index)
    L = lambda k, v: T[f'L{k}_{v}']
    lags = lambda v: np.column_stack([L(k, v).astype(float).values for k in range(1, NLAG + 1)])
    nan = np.nan
    # A 基本
    F['a01_fin_l1'] = L(1, 'finish')
    for k in range(2, 6):
        F[f'a02_fin_l{k}'] = L(k, 'finish')
    f5 = lags('finish')[:, :5]; fr5 = lags('fin_rel')[:, :5]
    with np.errstate(all='ignore'):
        F['a03_fin_mean5'] = np.nanmean(f5, 1); F['a03_fin_min5'] = np.nanmin(f5, 1); F['a03_finrel_mean5'] = np.nanmean(fr5, 1)
    F['a04_margin_l1'] = L(1, 'margin_s')
    F['a05_margin_w_l1'] = L(1, 'margin_w')
    F['a06_top3_rate_all'] = T.c_top3 / T.c_n
    F['a06_win_rate_all'] = T.c_win / T.c_n
    fy_same = T.fy_s == T.fy
    F['a06_top3_rate_fy'] = np.where(fy_same, T.f_3 / T.f_n, nan)
    with np.errstate(all='ignore'):
        F['a07_top3_rate10'] = np.nanmean(lags('top3'), 1)
    F['a08_age'] = T.age
    F['a09_sex'] = T.sex.map({'牡': 0, '牝': 1, 'セン': 2})
    F['a10_umaban'] = T.runner_number
    F['a11_n_entries'] = T.n_entries; F['a11_n_start'] = T.n_start
    F['a12_runs'] = T.c_n.fillna(0)
    F['a12x_runs_off'] = T.c_noff.fillna(0)   # 公式の走りが何走そろっているか(§A 直す 1)
    F['a13_runs_fy'] = np.where(fy_same, T.f_n, 0)
    F['a14_last_scr'] = T.e_scr; F['a14_last_dnf'] = T.e_dnf
    F['a15_dnf_cnt'] = T.c_dnf.fillna(0)
    sameg = sum(((L(k, 'cls_key') == T.cls_key) & (L(k, 'kumi') == T.kumi)).astype(int) for k in range(1, NLAG + 1))
    F['a16_same_group_n10'] = sameg
    # B 水分・季節
    F['b17_going_day'] = T.day_going
    F['b18_going_band'] = pd.cut(T.day_going, [-1, 1.05, 1.95, 2.95, 99], labels=False).astype(float)
    F['b19_going_l1'] = L(1, 'going_f')
    F['b20_going_diff'] = T.day_going - L(1, 'going_f')
    F['b21_light_r3'] = (T.c_light_3 + 2 * F.a06_top3_rate_all.fillna(base['p3'])) / (T.c_light_n + 2)
    F['b22_heavy_r3'] = (T.c_heavy_3 + 2 * F.a06_top3_rate_all.fillna(base['p3'])) / (T.c_heavy_n + 2)
    F['b21_light_n'] = T.c_light_n; F['b22_heavy_n'] = T.c_heavy_n
    F['b23_light_minus_heavy'] = F.b21_light_r3 - F.b22_heavy_r3
    G = lags('going_f'); FI = lags('finish'); TI = lags('tidx'); CW = lags('carried_weight')
    dg = np.abs(G - T.day_going.values[:, None])
    order = np.argsort(np.where(np.isfinite(dg), dg, 99), 1)[:, :3]
    nf = np.take_along_axis(FI, order, 1); nd = np.take_along_axis(dg, order, 1)
    with np.errstate(all='ignore'):
        F['b24_fin_near_going3'] = np.nanmean(np.where(np.isfinite(nd), nf, nan), 1)
    # 馬ごとの 時計の指数 ~ 水分 の傾き(10 走)と今回の水分での見込み
    def slope(x, y, minn=4):
        ok = np.isfinite(x) & np.isfinite(y)
        n = ok.sum(1)
        xm = np.where(ok, x, 0).sum(1) / np.maximum(n, 1); ym = np.where(ok, y, 0).sum(1) / np.maximum(n, 1)
        dx = np.where(ok, x - xm[:, None], 0); dy = np.where(ok, y - ym[:, None], 0)
        vx = (dx * dx).sum(1)
        b = np.where((n >= minn) & (vx > 1e-9), (dx * dy).sum(1) / np.where(vx > 1e-9, vx, 1), nan)
        return b, xm, ym, n
    b, xm, ym, n = slope(G, TI)
    F['b26_tidx_going_slope'] = b
    F['b25_tidx_at_going'] = np.where(np.isfinite(b), ym + b * (T.day_going.values - xm), nan)
    F['b27_weather_day'] = T.day_weather.map({'晴': 0, '曇': 1, '小雨': 2, '雨': 3, '小雪': 4, '雪': 5})
    F['b28_snow_r3'] = (T.c_snowd_3 + 2 * F.a06_top3_rate_all.fillna(base['p3'])) / (T.c_snowd_n + 2)
    F['b29_month'] = T.date.dt.month
    days = pd.Series(sorted(T.date.unique()))
    dfy = pd.DataFrame({'date': days, 'fy': fy_of(days)}); dfy['mi'] = dfy.groupby('fy').cumcount() + 1
    F['b30_day_in_fy'] = T.date.map(dfy.set_index('date').mi)
    F['b31_fy_end'] = T.date.dt.month.isin([2, 3]).astype(int)
    F['b37_winter_minus_summer'] = ((T.c_wint_3 + 2 * base['p3']) / (T.c_wint_n + 2) - (T.c_summ_3 + 2 * base['p3']) / (T.c_summ_n + 2))
    F['b37_is_winter'] = T.date.dt.month.isin([12, 1, 2, 3]).astype(int)
    # C 時計
    F['c39_time_l1'] = L(1, 'time_sec')
    F['c40_tidx_l1'] = L(1, 'tidx')
    F['c40_tidx_dc_l1'] = L(1, 'tidx_dc')   # 日ごとの馬場差で直した値(C 57 の使い方)
    TD = lags('tidx_dc')
    with np.errstate(all='ignore'):
        F['c41_tidx_max5'] = np.nanmax(TI[:, :5], 1); F['c42_tidx_mean5'] = np.nanmean(TI[:, :5], 1)
        F['c41_tidxdc_max5'] = np.nanmax(TD[:, :5], 1); F['c42_tidxdc_mean5'] = np.nanmean(TD[:, :5], 1)
        F['c44_tidx_std5'] = np.nanstd(TI[:, :5], 1)
        F['c47_tidx_2nd5'] = -np.sort(-np.where(np.isfinite(TI[:, :5]), TI[:, :5], -np.inf), 1)[:, 1]
        F.loc[~np.isfinite(F.c47_tidx_2nd5), 'c47_tidx_2nd5'] = nan
        b3, *_ = slope(np.tile(-np.arange(3.0), (len(T), 1)), TD[:, :3], minn=3)
        F['c43_tidx_trend3'] = b3
        near_w = np.abs(CW - T.carried_weight.values[:, None]) <= 30
        F['c45_tidx_near_cw'] = np.nanmean(np.where(near_w, TD, nan), 1)
        F['c46_tidx_near_going'] = np.nanmean(np.where(dg <= 0.3, TD, nan), 1)
    with np.errstate(all='ignore'):
        F['c48_margin_w_mean3'] = np.nanmean(lags('margin_w')[:, :3], 1)
    F['c50_slow_wins3'] = T.c_slowwin3
    F['c53_tidx_rank_l1'] = L(1, 'tidx_rank')
    F['c54_tidx_vs_1y'] = F.c42_tidx_mean5 - T.y1_tidx
    F['c55_young_growth'] = np.where(T.age <= 3, F.c54_tidx_vs_1y, nan)
    if 'dayvar_sd' not in base:  # 荒れた日の線も学びの期間だけで作る
        base['dayvar_sd'] = float(H[(H.race_date >= TRAIN[0]) & (H.race_date < TRAIN[1])].drop_duplicates('race_date').dayvar.std())
    sd = base['dayvar_sd']
    F['c56_odd_day_l1'] = (L(1, 'dayvar').abs() > 2 * sd).astype(float).where(L(1, 'dayvar').notna())
    F['c57_dayvar_l1'] = L(1, 'dayvar')
    F['c58_cw_at_best'] = T.c_cw_best
    # F 重量
    cw = T.carried_weight
    F['f99_cw'] = cw; F['f100_cw_l1'] = L(1, 'carried_weight'); F['f101_cw_diff'] = cw - L(1, 'carried_weight')
    F['f102_cw_max'] = T.c_cwmax; F['f103_cw_minus_max'] = cw - T.c_cwmax; F['f104_cw_first'] = (cw > T.c_cwmax).astype(float).where(T.c_cwmax.notna())
    F['f105_cw_per_bw'] = cw / T.body_weight
    F['f106_cw_per_bw_l1'] = L(1, 'carried_weight') / L(1, 'body_weight')
    F['f107_cwbw_diff'] = F.f105_cw_per_bw - F.f106_cw_per_bw_l1
    F['f109_cw_win_max'] = T.c_cwwinmax; F['f110_cw_minus_winmax'] = cw - T.c_cwwinmax
    rk = T.groupby('rkey').carried_weight
    F['f111_cw_rank'] = rk.rank(ascending=False, pct=True); F['f112_cw_rel'] = cw - rk.transform('mean')
    F['f116_mark'] = T.weight_mark.map({'☆': 1, '△': 2}).fillna(0)
    F['f117_mare_mixed'] = ((T.sex == '牝') & (T.mare_only == 0)).astype(int)
    F['f118_cw_over_min'] = cw - rk.transform('min')
    F['f119_hcap'] = T.hcap; F['f119_kitei'] = T.kitei
    F['f120_cw_under_top'] = rk.transform('max') - cw
    F['f125_cw_up20'] = (F.f101_cw_diff >= 20).astype(float).where(F.f101_cw_diff.notna())
    F['f126_cw_per_age'] = cw / T.age
    up = (lags('carried_weight')[:, :-1] > lags('carried_weight')[:, 1:]) & np.isfinite(lags('carried_weight')[:, 1:])
    drop = lags('fin_rel')[:, :-1] > lags('fin_rel')[:, 1:]
    with np.errstate(all='ignore'):
        F['f123_up_then_worse'] = np.where(up.sum(1) >= 2, (up & drop).sum(1) / up.sum(1), nan)
    F['f124_tidx_cw_slope'], *_ = slope(CW, TD)
    CR = lags('cw_rel'); FR = lags('fin_rel')
    F['f113_power'], *_ = slope(CR, -FR)   # 相対の重量が重い時ほど着が良い = パワー型(+)
    # 帯の中の自分の率(10 kg 刻み・自分の全体の率へ寄せる)
    WB = lags('carried_weight') // 10
    same = WB == (cw.values // 10)[:, None]
    n_ = same.sum(1); t3_ = (same & (lags('top3') == 1)).sum(1)
    F['f108_cw_band_r3'] = (t3_ + 2 * F.a06_top3_rate_all.fillna(base['p3'])) / (n_ + 2)
    # G 馬体重
    bw = T.body_weight
    F['g127_bw'] = bw; F['g128_bw_diff'] = bw - L(1, 'body_weight')
    F['g129_bw_vs_mean'] = bw - T.c_bw_sum / T.c_bw_cnt.replace(0, nan)
    F['g130_bw_vs_top3'] = bw - T.c_bw3_sum / T.c_bw3_cnt.replace(0, nan)
    F['g131_bw_rank'] = T.groupby('rkey').body_weight.rank(ascending=False, pct=True)
    F['g132_bw_minus_cw'] = bw - cw
    F['g133_bw_trend3'], *_ = slope(np.tile(-np.arange(4.0), (len(T), 1)), np.column_stack([bw.values, lags('body_weight')[:, :3]]), minn=3)
    F['g134_bw_down20'] = (F.g128_bw_diff <= -20).astype(float).where(F.g128_bw_diff.notna())
    F['g135_bw_up20'] = (F.g128_bw_diff >= 20).astype(float).where(F.g128_bw_diff.notna())
    F['g136_bw_vs_1y'] = bw - T.y1_bw
    F['g137_young_bw_growth'] = np.where(T.age <= 3, F.g136_bw_vs_1y, nan)
    # H 級・組・賞金
    F['h139_cls_level'] = T.cls_level; F['h139_cls_young'] = T.cls_young; F['h139_cls_age'] = T.cls_age.map({'2': 2, '3': 3, '4': 4, '5': 5, '3+': 13, '4+': 14}).astype(float)
    F['h140_kumi'] = T.kumi
    F['h141_cls_l1'] = L(1, 'cls_level'); F['h141_kumi_l1'] = L(1, 'kumi')
    samescale = L(1, 'cls_young') == T.cls_young
    F['h142_cls_change'] = np.where(samescale, np.sign(T.cls_level - L(1, 'cls_level')), nan)
    F['h143_kumi_change'] = np.where(samescale & (L(1, 'cls_key') == T.cls_key), T.kumi - L(1, 'kumi'), nan)
    F['h146_grade'] = T.grade; F['h147_prize1'] = T.prize1
    F['h148_prize_fy'] = np.where(fy_same, T.f_prize, 0); F['h149_prize_all'] = T.c_prize_won.fillna(0)
    F['h150_prize1_l1'] = L(1, 'prize1')
    F['h151_mare_only'] = T.mare_only; F['h151_area_lim'] = T.area_lim
    F['h152_fy_start'] = (F.b30_day_in_fy <= 6).astype(int)
    F['h153_first_after_drop'] = ((T.fy_s != T.fy) & (F.h142_cls_change < 0)).astype(float).where(T.fy_s.notna())
    F['h154_a_runs'] = T.c_a_lv_n.fillna(0)
    sg3 = sum((((L(k, 'cls_key') == T.cls_key) & (L(k, 'kumi') == T.kumi)) & (L(k, 'top3') == 1)).astype(int) for k in range(1, NLAG + 1))
    F['h155_same_group_r3'] = (sg3 + 2 * F.a06_top3_rate_all.fillna(base['p3'])) / (sameg + 2)
    F['h156_stakes_runs'] = T.c_stk_n.fillna(0)
    F['h157_young_to_mixed'] = ((L(1, 'cls_young') == 1) & (T.cls_young == 0)).astype(float).where(L(1, 'cls_young').notna())
    F['h158_cls_1y'] = np.where(T.y1_young == T.cls_young, T.y1_cls, nan)
    # I 騎手
    F['i164_jockey_change'] = (T.jockey != L(1, 'jockey')).astype(float).where(L(1, 'jockey').notna())
    chg = sum(((L(k, 'jockey') != L(k + 1, 'jockey')) & L(k + 1, 'jockey').notna()).astype(int) for k in range(1, 4))
    F['i166_jockey_changes3'] = chg.where(L(2, 'jockey').notna())
    F['i171_mark'] = F.f116_mark
    # M 状況
    gap = (T.date - L(1, 'date')).dt.days
    F['m211_days'] = gap; F['m212_rest30'] = (gap >= 30).astype(float).where(gap.notna()); F['m212_rest60'] = (gap >= 60).astype(float).where(gap.notna())
    F['m213_runs_since_rest'] = np.where(gap >= 60, 0, T.c_runs_since_ret)
    F['m214_short'] = (gap <= 6).astype(float).where(gap.notna())
    F['m215_ret_r3'] = (T.c_ret_3 + 2 * F.a06_top3_rate_all.fillna(base['p3'])) / (T.c_ret_n + 2)
    F['m216_fy_first'] = (T.fy_s != T.fy).astype(int)
    F['m217_runs_per_year'] = T.c_n.fillna(0) / np.maximum(T.age - 1, 1)
    F['m218_big_loss_l1'] = (L(1, 'fin_rel') > 0.7).astype(float).where(L(1, 'fin_rel').notna())
    F['m219_won_l1'] = (L(1, 'finish') == 1).astype(float).where(L(1, 'date').notna())
    F['m220_days_since_win'] = (T.date - T.c_last_win_date).dt.days
    F['m221_dnf_l1'] = L(1, 'dnf')

    # 率(前の日まで)
    T['gband'] = F.b18_going_band; T['wband'] = (cw // 50).astype(float)
    T['clsk'] = T.cls_key; H['clsk'] = H.cls_key
    T['debut'] = (F.a12_runs == 0).astype(int)
    H = H.sort_values(['hk', 'date'])
    H['debut'] = (H.groupby('hk').ran.cumsum() - H.ran == 0).astype(int)
    H['_gap'] = (H.date - H[H.ran == 1].groupby('hk').date.shift()).dt.days
    H['ret_flag'] = (H._gap >= 60).astype(int)
    T['ret_flag'] = F.m212_rest60.fillna(0).astype(int)
    H['_cwup'] = (H.carried_weight - H[H.ran == 1].groupby('hk').carried_weight.shift() > 0).astype(int)
    T['_cwup'] = (F.f101_cw_diff > 0).astype(int)
    H['young'] = (H.age <= 3).astype(int); T['young'] = (T.age <= 3).astype(int)
    T['jk_tr'] = T.jockey + '|' + T.trainer; H['jk_tr'] = H.jockey + '|' + H.trainer
    T['hk_jk'] = T.hk + '|' + T.jockey; H['hk_jk'] = H.hk + '|' + H.jockey
    p = base
    ent_rate(H, T, ['jockey', 'fy'], 'i159_jk_fy', p)
    ent_rate(H, T, ['jockey'], 'i160_jk', p)
    ent_rate(H, T, ['jockey'], 'i172_jk_30d', p, windows=(None, 30))
    ent_rate(H, T, ['jockey', 'gband'], 'i161_jk_going', p)
    ent_rate(H, T, ['jockey', 'wband'], 'i162_jk_cw', p)
    ent_rate(H, T, ['jockey', 'clsk'], 'i163_jk_cls', p)
    ent_rate(H, T, ['hk_jk'], 'i167_horse_jk', p)
    ent_rate(H, T, ['jk_tr'], 'i173_jk_tr', p)
    ent_rate(H, T, ['trainer', 'fy'], 'j177_tr_fy', p)
    ent_rate(H, T, ['trainer'], 'j178_tr', p)
    ent_rate(H, T, ['trainer', 'gband'], 'j179_tr_going', p)
    ent_rate(H, T, ['trainer'], 'j180_tr_30d', p, windows=(None, 30))
    ent_rate(H, T, ['trainer', 'ret_flag'], 'j181_tr_ret', p)
    ent_rate(H, T, ['trainer', '_cwup'], 'j182_tr_cwup', p)
    ent_rate(H, T, ['trainer'], 'j184_tr_365d', p, windows=(None, 365))
    ent_rate(H, T, ['trainer', 'young'], 'j185_tr_young', p)
    ent_rate(H, T, ['sire'], 'k189_sire', p)
    ent_rate(H, T, ['sire', 'gband'], 'k190_sire_going', p)
    ent_rate(H, T, ['sire', 'wband'], 'k191_sire_cw', p)
    ent_rate(H, T, ['broodmare_sire'], 'k192_bms', p)
    ent_rate(H, T, ['breeder'], 'k193_breeder', p)
    ent_rate(H, T, ['dam'], 'k196_dam', p)
    T['age_c'] = np.minimum(T.age, 6).astype(float); H['age_c'] = np.minimum(H.age, 6).astype(float)
    ent_rate(H, T, ['sire', 'age_c'], 'k197_sire_age', p)
    ent_rate(H, T, ['sire', 'debut'], 'o236_sire_debut', p)
    rate_cols = [c for c in T.columns if re.match(r'^[ijko]\d{3}_', c)]
    for c in rate_cols:
        F[c] = T[c]
    # きょうだい = 母の子の数から自分の分を引く
    own_n = T.c_n.fillna(0) - 0  # 公式・KD を合わせた自分の走数
    own3 = T.c_top3.fillna(0)
    sib_n = F.k196_dam_n - own_n
    F['k196_sib_n'] = sib_n.clip(lower=0)
    F['k196_sib_r3'] = ((F.k196_dam_r3 * (F.k196_dam_n + 5) - own3) / (sib_n.clip(lower=0) + 5)).where(sib_n >= 0)
    F = F.drop(columns=['k196_dam_n', 'k196_dam_r3', 'k196_dam_r1'])
    F['k187_sire'] = T.sire; F['k188_bms'] = T.broodmare_sire
    bd = pd.to_datetime(T.pr_birth, errors='coerce')
    F['k195_birth_doy'] = bd.dt.dayofyear

    # L 力の値・直接対決
    Rt = ratings(H)
    Rt['_k'] = Rt.rkey + '|' + Rt.hk
    Rt = Rt.set_index('_k')
    key = T.rkey + '|' + T.hk
    for c in Rt.columns[2:]:
        F[c] = key.map(Rt[c]).values
    F['l202_opp_elo_l1'] = (T.L1_rkey + '|' + T.hk).map(Rt.l202_opp_elo_now).values
    F['l203_lastwinner_r3'] = F.l203_lastwinner_top3 / F.l203_lastwinner_runs.replace(0, np.nan)
    # 力の値の上り調子(前の日まで: 今の値 − 3 走前の時点の値)
    F['l205_elo_trend3'] = F.l199_elo - (T.L3_rkey + '|' + T.hk).map(Rt.l199_elo).values
    F['l206_streak'] = T.c_streak.fillna(0)
    F['l206_streak_x_opp'] = F.l206_streak * (F.l202_opp_elo_l1 - 1500)
    # 前の騎手の今の率(乗り替わりの差)
    ent_rate(H, T, ['L1_jockey'], 'tmp_prevjk', p, hkeys=['jockey'])
    F['i165_jk_minus_prev'] = np.where(F.i164_jockey_change == 1, F.i160_jk_r3 - T.tmp_prevjk_r3, np.where(F.i164_jockey_change == 0, 0.0, np.nan))

    # P レースの中の相対の値
    rk = T.rkey
    rel = ['l199_elo', 'l208_elo_t', 'c42_tidx_mean5', 'c41_tidx_max5', 'c42_tidxdc_mean5', 'c40_tidx_dc_l1', 'b25_tidx_at_going',
           'a06_top3_rate_all', 'a03_finrel_mean5', 'i160_jk_r3', 'i159_jk_fy_r3', 'j178_tr_r3', 'k189_sire_r3', 'f99_cw', 'f105_cw_per_bw',
           'g127_bw', 'h149_prize_all', 'h148_prize_fy', 'b23_light_minus_heavy', 'c46_tidx_near_going', 'f103_cw_minus_max', 'a12_runs']
    run_mask = T.scratch.values == 0
    for c in rel:
        v = F[c].where(run_mask)  # 直前版の相対 = 取消を除いた頭数(§A 注意 6)
        F['p237_' + c + '_d'] = F[c] - v.groupby(rk).transform('mean')
        F['p238_' + c + '_rk'] = v.groupby(rk).rank(ascending=False, pct=True)
    e = F.l199_elo.where(run_mask)
    srt = e.groupby(rk).transform(lambda s: s.nlargest(2).iloc[0] - s.nlargest(2).iloc[-1] if s.notna().sum() >= 2 else np.nan)
    F['p239_elo_gap12'] = srt
    F['p240_cw_range'] = T.carried_weight.where(run_mask).groupby(rk).transform('max') - T.carried_weight.where(run_mask).groupby(rk).transform('min')
    F['p241_field_going_apt'] = F.b23_light_minus_heavy.where(run_mask).groupby(rk).transform('mean')
    F['p245_same_trainer'] = T.groupby([rk, T.trainer]).hk.transform('size') - 1
    ridden = set(zip(rk, T.jockey))
    F['p246_jk_taken'] = [int(lj == lj and lj != j and (r, lj) in ridden) for r, lj, j in zip(rk, T.L1_jockey, T.jockey)]
    F['p246_jk_taken'] = F.p246_jk_taken.where(T.L1_jockey.notna())

    F = F.drop(columns=[c for c in F.columns if c.startswith('tmp_')])
    ID = T[['race_date', 'race_no', 'runner_number', 'hk', 'horse_name', 'rkey', 'fy']].copy()
    ID['scratch'] = T.scratch; ID['dnf'] = T.dnf; ID['finish'] = T.finish
    ID['y_win'] = np.where(T.scratch == 1, np.nan, (T.finish == 1).astype(float))
    ID['y_top3'] = np.where(T.scratch == 1, np.nan, (T.finish <= 3).astype(float))
    ID['ref_pop'] = T.popularity   # 材料にしない(人気薄の物差しだけ)
    ID['ref_going_race'] = T.going_f  # 材料にしない(参考: レースごとの水分)
    return ID, F, base


IDCOLS = ['race_date', 'race_no', 'runner_number', 'hk', 'horse_name', 'rkey', 'fy', 'scratch', 'dnf', 'finish', 'y_win', 'y_top3',
          'ref_pop', 'ref_going_race']
CATS = ['k187_sire', 'k188_bms']
PERIODS = [('学び', '2014-04-01', '2022-04-01'), ('選び', '2022-04-01', '2024-10-01'), ('確かめ', '2024-10-01', '2026-09-01'),
           ('その後', '2026-09-01', '2027-01-01')]
