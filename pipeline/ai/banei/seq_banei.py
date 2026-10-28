# -*- coding: utf-8 -*-
"""南関で効いた仕組みを帯広に移す下見(2026-10-27・ユーザー「進めて」)。確かめの期間(2024-10〜)には触らない。

1. 並び読み(南関 seq2/seq3 と同じ模型 seq_day.model = 過去 10 走を GRU で読み、同じレースの馬どうしを見合う)。
   1 走 = 時計の速さ(水分 0.2 刻み × 重量 50kg 刻みでならす)・勝ち馬との秒差・着順の割合・1 着/3 着内/中止・頭数・水分・重量・重量÷体重・
          馬体重と増減・級の水準・1 着の賞金・前半/障害/後半のレースの中央値との差・障害で止まった印・通過順 3 つ・
          今日と同じ騎手か・同じ調教師か(南関 seq3 で効きの主)・何日前・今日との重量の差・水分の差・有り。人気・オッズは使わない。
   今回 = 水分(1R の値)・重量・重量÷体重・馬体重と増減・年齢・性・頭数・馬番の位置・級・賞金・前走から何日・過去の数・月・牝馬の混合戦。
   学び: 単独で 2014-04〜2022-03 を学ぶ(古い 1 割で止めどころ)→ 第 2 版の見込みを初期値に「外した分」だけを学ぶ
         (学びの期間の見込み = 第 2 版の年ごとに外した予想 f10k_parts/base_cv.parquet)→ 選び 2022-04〜2024-09 を第 2 版の選びの予想の上に当てる。
2. 平らな模型の 2 割混ぜ(南関 F3): 過去 10 走の値を横に並べた木(LightGBM)を 2014-04〜2022-03 で学び、第 2 版とロジットで 8:2 に混ぜる。
- 偽 = 入力(過去走・今回)を年の中で行ごとにまぜた同じ手順(南関と同じ)× 3。種は 3 つの平均。

  py -3.12 -X utf8 src/banei/seq_banei.py build    # → v3/banei_kb/seq_tensors.npz
  py -3.12 -X utf8 src/banei/seq_banei.py fit      # → v3/banei_kb/seq_select_pred.parquet・out/banei_seq_select.md
"""
# 2026-10-28 nar-jobs に写した(v3 の src/banei/seq_banei.py の写し・計算は同じ)。変えたのは置き場(環境変数 BANEI_V3)と、研究だけの関数を外したこと。
import sys
import time

import numpy as np
import pandas as pd

import feat_v1 as _f1  # noqa: E402
V3 = _f1.V3
V = V3 + 'banei_kb/'
TEN = V + 'seq_tensors.npz'
K = ['race_date', 'race_no', 'runner_number']
H, MAXN = 10, 10
LEARN = ('2014-04-01', '2022-04-01')
SEL = ('2022-04-01', '2024-10-01')
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s]', *a, flush=True)


def build():
    f = pd.read_parquet(V + 'feat_v1.parquet', columns=K + ['hk', 'rkey', 'scratch', 'dnf', 'finish', 'y_top3', 'a08_age', 'a09_sex', 'f99_cw',
                                                          'g127_bw', 'g128_bw_diff', 'h139_cls_level', 'h147_prize1', 'b17_going_day',
                                                          'ref_going_race', 'a11_n_start', 'f117_mare_mixed', 'b29_month'])
    f['race_date'] = f.race_date.astype(str); f['race_no'] = f.race_no.astype(int); f['runner_number'] = f.runner_number.astype(int)
    ru = pd.read_parquet(V3 + 'official/runs.parquet', columns=K + ['track', 'jockey', 'trainer', 'time_sec'], filters=[('track', '==', '帯広ば')])
    kb = pd.read_parquet(V + 'kb_runs.parquet', columns=['race_date', 'race_no', 'umaban', 'seg_front', 'seg_obst', 'seg_back', 'pass1', 'pass2', 'pass3'])
    kb = kb.rename(columns={'umaban': 'runner_number'})
    for x in (ru, kb):
        x['race_date'] = x.race_date.astype(str); x['race_no'] = x.race_no.astype(int); x['runner_number'] = x.runner_number.astype(int)
    d = f[f.scratch == 0].merge(ru.drop(columns='track').drop_duplicates(K), on=K, how='left').merge(kb.drop_duplicates(K), on=K, how='left')
    d['dn'] = (pd.to_datetime(d.race_date) - pd.Timestamp('2014-01-01')).dt.days.astype(float)
    d['stop'] = d.dnf.fillna(0).astype(float)
    fin = pd.to_numeric(d.finish, errors='coerce')
    d['Y1'] = ((fin == 1) & (d.stop == 0)).astype(float); d['Y3'] = d.y_top3.fillna(0).astype(float)
    d['nh'] = d.groupby('rkey').hk.transform('size').astype(float)
    d['frel'] = np.where(d.stop == 1, 1.0, ((fin - 1) / np.maximum(d.nh - 1, 1)).clip(0, 1))
    ts = d.time_sec.where((d.stop == 0) & (d.time_sec > 0))
    d['gb'] = (d.ref_going_race.fillna(d.b17_going_day) * 5).round().clip(upper=30)
    d['wb'] = (d.f99_cw // 50).clip(upper=20)
    st = d[d.race_date < LEARN[1]].assign(ts=ts).groupby(['gb', 'wb']).ts.agg(['mean', 'std', 'count']).reset_index()
    st = st[st['count'] >= 30]
    d = d.merge(st, on=['gb', 'wb'], how='left')
    ts = d.time_sec.where((d.stop == 0) & (d.time_sec > 0))
    d['tz'] = (-(ts - d['mean']) / d['std']).clip(-4, 4)
    d['behind'] = ((ts - ts.groupby(d.rkey).transform('min')) / 10).clip(0, 5)
    for c in ['seg_front', 'seg_obst', 'seg_back']:
        v = d[c].where((d[c] > 0) & (d.stop == 0))
        d[c + '_r'] = ((v - v.groupby(d.rkey).transform('median')) / 10).clip(-3, 3)
    vo = d.seg_obst.where((d.seg_obst > 0) & (d.stop == 0))
    d['ostop'] = (vo >= 2 * vo.groupby(d.rkey).transform('median')).astype(float)   # d69 と同じ線
    for c in ['pass1', 'pass2', 'pass3']:
        d[c + '_r'] = pd.to_numeric(d[c], errors='coerce') / d.nh
    d = d.sort_values(['hk', 'dn', 'race_no']).reset_index(drop=True)
    bw = d.g127_bw.where(d.g127_bw > 0)
    lp1 = np.log(d.h147_prize1.where(d.h147_prize1 > 0))
    run = np.column_stack([
        d.tz.fillna(0), d.tz.isna(), d.behind.fillna(2.5) / 2 - 0.5, d.frel, d.Y1, d.Y3, d.stop, (d.nh - 9) / 2,
        d.ref_going_race.fillna(d.b17_going_day).fillna(2) - 2, (d.f99_cw - 650) / 150, (d.f99_cw / bw).fillna(0.65) * 3 - 2,
        (bw.fillna(1000) - 1000) / 80, d.g128_bw_diff.fillna(0).clip(-40, 40) / 15, d.h139_cls_level.fillna(0) / 5, (lp1.fillna(12) - 12),
        d.seg_front_r.fillna(0), d.seg_obst_r.fillna(0), d.seg_back_r.fillna(0), d.seg_obst_r.isna(), d.ostop.fillna(0),
        d.pass1_r.fillna(0.5), d.pass2_r.fillna(0.5), d.pass3_r.fillna(0.5)]).astype(np.float32)
    FR = run.shape[1]
    hk, dn = d.hk.to_numpy(), d.dn.to_numpy()
    pos = d.groupby('hk').cumcount().to_numpy()
    jk, tr = d.jockey.fillna('?').to_numpy(), d.trainer.fillna('?').to_numpy()
    cw, gg = d.f99_cw.to_numpy(float), d.ref_going_race.fillna(d.b17_going_day).to_numpy(float)
    gday = d.b17_going_day.to_numpy(float)   # 今日の水分は 1R の値(第 1 版と同じ)
    tgt = np.where(d.race_date.to_numpy() >= LEARN[0])[0]
    NX = 6
    hist = np.zeros((len(tgt), H, FR + NX), np.float32)
    for k in range(1, H + 1):
        j = tgt - k
        ok = (j >= 0) & (pos[tgt] >= k)
        jj, ii = j[ok], np.where(ok)[0]
        same = (hk[jj] == hk[tgt[ii]]) & (dn[jj] < dn[tgt[ii]])
        jj, ii = jj[same], ii[same]
        s = H - k
        hist[ii, s, :FR] = run[jj]
        hist[ii, s, FR] = np.log1p(dn[tgt[ii]] - dn[jj]) / 3 - 1.5
        hist[ii, s, FR + 1] = np.nan_to_num((cw[tgt[ii]] - cw[jj]) / 50)
        hist[ii, s, FR + 2] = np.nan_to_num(gday[tgt[ii]] - gg[jj])
        hist[ii, s, FR + 3] = (jk[tgt[ii]] == jk[jj])
        hist[ii, s, FR + 4] = (tr[tgt[ii]] == tr[jj])
        hist[ii, s, FR + 5] = 1.0
    T = d.iloc[tgt].reset_index(drop=True)
    nprev = hist[:, :, -1].sum(1)
    gap = np.where(nprev > 0, hist[:, H - 1, FR], 0)
    tb = T.g127_bw.where(T.g127_bw > 0)
    lpt = np.log(T.h147_prize1.where(T.h147_prize1 > 0))
    ctx = np.column_stack([
        T.b17_going_day.fillna(2) - 2, (T.f99_cw - 650) / 150, (T.f99_cw / tb).fillna(0.65) * 3 - 2, (tb.fillna(1000) - 1000) / 80,
        T.g128_bw_diff.fillna(0).clip(-40, 40) / 15, tb.isna(), (T.a08_age.fillna(4) - 4) / 2, T.a09_sex == 1, T.a09_sex == 2,
        (T.nh - 9) / 2, (T.runner_number - 1) / np.maximum(T.nh - 1, 1), T.h139_cls_level.fillna(0) / 5, lpt.fillna(12) - 12,
        gap, nprev == 0, nprev / 10, np.sin(T.b29_month / 6 * np.pi), np.cos(T.b29_month / 6 * np.pi), T.f117_mare_mixed.fillna(0)]).astype(np.float32)
    T['rid'] = pd.factorize(T.rkey)[0]
    T['slot'] = T.groupby('rid').cumcount()
    assert T.slot.max() < MAXN, T.slot.max()
    np.savez(TEN, hist=hist, ctx=ctx, rid=T.rid.to_numpy(), slot=T.slot.to_numpy(), y3=T.Y3.to_numpy(np.float32),
             date=T.race_date.to_numpy().astype('U10'), race_no=T.race_no.to_numpy(), umaban=T.runner_number.to_numpy(),
             hk=T.hk.to_numpy().astype('U40'), rkey=T.rkey.to_numpy().astype('U40'))
    log('保存', hist.shape, ctx.shape, '過去 0 走', round(float((nprev == 0).mean()), 4), '10 走そろう', round(float((nprev == H).mean()), 3),
        '時計のある走り', round(float(d.tz.notna().mean()), 3), '区間のある走り', round(float(d.seg_obst_r.notna().mean()), 3))
