"""研究用・1 回きり(続き)。前便 run 39411417972 の out/rows.csv を使い、A(本番)・C(18+組 6)・D(18 だけ)を比べて out2/result2.md を書く。
C・D の k は作る期間の T10 で幅的中 80% になる最小の k(0.80〜3.00・0.01 刻み・calib.py と同じ)。採点期間は見ない。
"""
import json
import os
import numpy as np
import pandas as pd
import lightgbm as lgb

D = pd.read_csv('out/rows.csv')
M = json.load(open('out/meta.json'))
CATS = M['cats']
NEW = ['lu', 'lw', 'ls', 'cu', 'cw', 'cs']
X18 = ['x%d' % i for i in range(18)]
LGB_P = dict(learning_rate=0.05, num_leaves=63, min_data_in_leaf=200, feature_fraction=0.9, bagging_fraction=0.8,
             bagging_freq=1, verbose=-1, seed=1)
TS = [5, 10, 20, 30]
SPL = {'S1': (('2026-09-08', '2026-10-05'), ('2026-10-06', '2026-10-19')),
       'S2': (('2026-10-06', '2026-10-19'), ('2026-09-08', '2026-10-05'))}


def inr(df, a):
    return df[(df.d >= a[0]) & (df.d <= a[1])]


def X(df, feats):
    x = df[feats].copy()
    x['x8'] = pd.Categorical(df.x8.round().astype(int), categories=list(range(len(CATS))))
    return x


def fit_pred(tr, te, feats):
    ds = lgb.Dataset(X(tr, feats), np.log(tr.fin.values / tr.cur.values), categorical_feature=['x8'], free_raw_data=False)
    qtr, qte = [], []
    for a in (0.1, 0.5, 0.9):
        m = lgb.train(dict(LGB_P, objective='quantile', alpha=a), ds, num_boost_round=200)
        qtr.append(m.predict(X(tr, feats)))
        qte.append(m.predict(X(te, feats)))
    qtr = np.sort(np.vstack(qtr).T, axis=1)
    qte = np.sort(np.vstack(qte).T, axis=1)
    # k= 作る期間の T10 で幅的中 80% になる最小の k
    s = (tr['T'] == 10).values
    y, q = np.log(tr.fin.values[s] / tr.cur.values[s]), qtr[s]
    k = 3.0
    for kk in np.arange(0.80, 3.001, 0.01):
        if ((y >= q[:, 1] - kk * (q[:, 1] - q[:, 0])) & (y <= q[:, 1] + kk * (q[:, 2] - q[:, 1]))).mean() >= 0.80:
            k = round(float(kk), 2)
            break
    cur = te.cur.values
    return (cur * np.exp(qte[:, 1]), cur * np.exp(qte[:, 1] - k * (qte[:, 1] - qte[:, 0])),
            cur * np.exp(qte[:, 1] + k * (qte[:, 2] - qte[:, 1]))), k


def score(te, mid, lo, hi):
    x = te[['d', 'track', 'no', 'T', 'cur', 'fin']].copy()
    x['ef'] = np.abs(x.fin / mid - 1) * 100
    x['er'] = np.abs(x.fin / x.cur - 1) * 100
    x['hit'] = ((x.fin >= lo) & (x.fin <= hi)).astype(int)
    return x


def summ(x):
    r = x.groupby(['d', 'track', 'no', 'T'])[['ef', 'er']].mean()
    a, b = r.ef.round(), r.er.round()
    return pd.Series(dict(races=len(r), n=len(x), dev=x.ef.mean(), hit=x.hit.mean() * 100,
                          win=int((a < b).sum()), lose=int((a > b).sum()), tie=int((a == b).sum())))


L = []
P = L.append
P('\n## 続き(対照 D と k の取り直し)\n')
P('- 材料= 前便 run 39411417972 の rows.csv(%d 行)をそのまま使う。D= 18 特徴だけ・C と同じ材料・分け・木の設定。' % len(D))
P('- C・D の k= 作る期間の T10 で幅的中 80%% になる最小の k(作る期間の当てはめ値で取る・採点期間は見ない)。A は本番のまま(k=%s)。\n' % M['k'])
contrib = {}
for sn, (fa, ta) in SPL.items():
    tr, te = inr(D, fa), inr(D, ta)
    (pc, kc), (pd_, kd) = fit_pred(tr, te, X18 + NEW), fit_pred(tr, te, X18)
    S = {'A': score(te, te.midA.values, te.lowA.values, te.highA.values), 'C': score(te, *pc), 'D': score(te, *pd_)}
    P(f'### {sn} 作る {fa[0]}〜{fa[1]}・採点 {ta[0]}〜{ta[1]}・k C={kc} D={kd}\n')
    P('| T | 本 | レース | 平均のずれ% | 幅的中% | 近い | 遠い | 同じ | A との差(pt) |\n|---|---|---|---|---|---|---|---|---|')
    for T in TS:
        ss = {nm: summ(S[nm][S[nm]['T'] == T]) for nm in 'ACD'}
        for nm in 'ACD':
            s = ss[nm]
            P(f"| {T} | {nm} | {int(s.races)} | {s.dev:.2f} | {s.hit:.1f} | {int(s.win)} | {int(s.lose)} | {int(s.tie)} | {s.dev - ss['A'].dev:+.2f} |")
        if T == 10:
            contrib[sn] = ss['C'].dev - ss['D'].dev
    P('')
P('### 組の寄与= C−D の T10 差(pt・負= 組の特徴で縮んだ)\n')
P('| S1 | S2 |\n|---|---|')
P(f"| {contrib['S1']:+.2f} | {contrib['S2']:+.2f} |\n")
ok = all(v <= -0.5 for v in contrib.values())
P('判定: ' + ('**組の特徴が効く**(C−D が S1・S2 とも −0.5pt 以下)' if ok else '**効いたのは作り直し**(C−D が S1・S2 の両方では −0.5pt 以下にならない)'))
os.makedirs('out2', exist_ok=True)
open('out2/result2.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')
print('\n'.join(L))
