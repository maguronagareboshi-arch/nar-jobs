"""研究用・1 回きり。out/rows.csv から A(本番)・B(A+組の直線補正)・C(18+組の特徴で木を作り直し)を比べて out/result.md を書く。
前後 2 通り: S1= 作る 9/8〜10/5・採点 10/6〜10/19、S2= 入れ替え。物差しは /odds-record と同じ(平均のずれ%・幅的中%・近い/遠いレース数)。
"""
import json
import numpy as np
import pandas as pd
import lightgbm as lgb

D = pd.read_csv('out/rows.csv')
M = json.load(open('out/meta.json'))
CATS, K = M['cats'], float(M['k'])
NEW = ['lu', 'lw', 'ls', 'cu', 'cw', 'cs']
X18 = ['x%d' % i for i in range(18)]
LGB_P = dict(learning_rate=0.05, num_leaves=63, min_data_in_leaf=200, feature_fraction=0.9, bagging_fraction=0.8,
             bagging_freq=1, verbose=-1, seed=1)
TS = [5, 10, 20, 30]
SPL = {'S1': (('2026-09-08', '2026-10-05'), ('2026-10-06', '2026-10-19')),
       'S2': (('2026-10-06', '2026-10-19'), ('2026-09-08', '2026-10-05'))}


def inr(df, a):
    return df[(df.d >= a[0]) & (df.d <= a[1])]


def fit_B(tr):
    co = {}
    for T in TS:
        t = tr[tr['T'] == T]
        X = np.column_stack([np.ones(len(t))] + [t[c].fillna(0).values for c in NEW])
        y = np.log(t.fin.values / t.midA.values)
        co[T] = np.linalg.lstsq(X, y, rcond=None)[0]
    return co


def apply_B(te, co):
    g = np.zeros(len(te))
    for T in TS:
        s = (te['T'] == T).values
        X = np.column_stack([np.ones(s.sum())] + [te.loc[s, c].fillna(0).values for c in NEW])
        g[s] = X @ co[T]
    e = np.exp(g)
    return te.midA.values * e, te.lowA.values * e, te.highA.values * e


def Xc(df):
    x = df[X18 + NEW].copy()
    x['x8'] = pd.Categorical(df.x8.round().astype(int), categories=list(range(len(CATS))))
    return x


def fit_pred_C(tr, te):
    ds = lgb.Dataset(Xc(tr), np.log(tr.fin.values / tr.cur.values), categorical_feature=['x8'], free_raw_data=False)
    q = []
    for a in (0.1, 0.5, 0.9):
        m = lgb.train(dict(LGB_P, objective='quantile', alpha=a), ds, num_boost_round=200)
        q.append(m.predict(Xc(te)))
    q = np.sort(np.vstack(q).T, axis=1)
    cur = te.cur.values
    return cur * np.exp(q[:, 1]), cur * np.exp(q[:, 1] - K * (q[:, 1] - q[:, 0])), cur * np.exp(q[:, 1] + K * (q[:, 2] - q[:, 1]))


def score(te, mid, lo, hi):
    x = te[['d', 'track', 'no', 'T', 'cur', 'fin']].copy()
    x['ef'] = np.abs(x.fin / mid - 1) * 100
    x['er'] = np.abs(x.fin / x.cur - 1) * 100
    x['hit'] = ((x.fin >= lo) & (x.fin <= hi)).astype(int)
    return x


def summ(x):
    r = x.groupby(['d', 'track', 'no', 'T'])[['ef', 'er']].mean()
    a, b = r.ef.round(), r.er.round()
    return pd.Series(dict(races=len(r), n=len(x), dev=x.ef.mean(), ref=x.er.mean(), hit=x.hit.mean() * 100,
                          win=int((a < b).sum()), lose=int((a > b).sum()), tie=int((a == b).sum())))


L = []
P = L.append
c = M['counts']
P('# 最終予測に 馬連・ワイド・3連複の売れ方を足す研究(%s〜%s)\n' % (M['from'], M['to']))
P('- 模型 built_on=%s・k=%s・場 %d・補正の since=%s' % (M['built_on'], K, len(CATS), ','.join(M['adjSince'])))
P('- 日 %d・レース %d・レース×T %d(単勝の刻みが T+4 分より古く外した %d)・行(馬) %d' % (c['days'], c['races'], c['raceT'], c['raceT_skipGap'], c['rows']))
P('\n| 券種 | 組の刻み | 確定で除外 | 発走後で除外 | 日付違い | 候補 | T 時点あり(レース×T) | 10 分前もあり | 欠け |\n|---|---|---|---|---|---|---|---|---|')
for k in ('umaren', 'wide', 'sanrenpuku'):
    f, u = c['full'][k], c['comboUse'][k]
    P(f"| {k} | {f['all']} | {f['final']} | {f['afterPost']} | {f['otherDay']} | {f['cand']} | {u['now']} | {u['prev']} | {u['miss']} |")
P('\n組の形(先頭 2 組): `%s`\n' % json.dumps(c.get('firstCombo', {}), ensure_ascii=False))

res = {}
for sn, (fa, ta) in SPL.items():
    tr, te = inr(D, fa), inr(D, ta)
    co = fit_B(tr)
    S = {'A': score(te, te.midA.values, te.lowA.values, te.highA.values),
         'B': score(te, *apply_B(te, co)),
         'C': score(te, *fit_pred_C(tr, te))}
    res[sn] = S
    P(f'\n## {sn} 作る {fa[0]}〜{fa[1]}(行 {len(tr)})・採点 {ta[0]}〜{ta[1]}(行 {len(te)})\n')
    P('B の係数(切片, lu, lw, ls, cu, cw, cs): ' + '・'.join(f'T{T}=[' + ', '.join('%.3f' % v for v in co[T]) + ']' for T in TS) + '\n')
    P('| T | 本 | レース | 馬 | 平均のずれ% | 今のオッズのまま% | 幅的中% | 近い | 遠い | 同じ | A との差(pt) |\n|---|---|---|---|---|---|---|---|---|---|---|')
    for T in TS:
        base = None
        for nm in 'ABC':
            s = summ(S[nm][S[nm]['T'] == T])
            if nm == 'A':
                base = s.dev
            P(f"| {T} | {nm} | {int(s.races)} | {int(s.n)} | {s.dev:.2f} | {s.ref:.2f} | {s.hit:.1f} | {int(s.win)} | {int(s.lose)} | {int(s.tie)} | {s.dev - base:+.2f} |")
    for T in (10, 5):
        P(f'\n場ごと T={T}(平均のずれ% A / B / C・幅的中% A / B / C・レース)\n')
        P('| 場 | レース | A | B | C | 的中 A | 的中 B | 的中 C |\n|---|---|---|---|---|---|---|---|')
        for trk in sorted(S['A'].track.unique()):
            ss = {nm: summ(S[nm][(S[nm]['T'] == T) & (S[nm].track == trk)]) for nm in 'ABC'}
            if ss['A'].n == 0:
                continue
            P(f"| {trk} | {int(ss['A'].races)} | {ss['A'].dev:.2f} | {ss['B'].dev:.2f} | {ss['C'].dev:.2f} | {ss['A'].hit:.1f} | {ss['B'].hit:.1f} | {ss['C'].hit:.1f} |")

P('\n## 判定の材料(T=10 の A との差 pt・負= 縮んだ)\n')
P('| 本 | S1 | S2 | 両方で A に勝ち | T10 で 0.5pt 以上 |\n|---|---|---|---|---|')
for nm in 'BC':
    dd = {}
    for sn in SPL:
        S = res[sn]
        dd[sn] = summ(S[nm][S[nm]['T'] == 10]).dev - summ(S['A'][S['A']['T'] == 10]).dev
    allT = all(summ(res[sn][nm][res[sn][nm]['T'] == T]).dev < summ(res[sn]['A'][res[sn]['A']['T'] == T]).dev for sn in SPL for T in TS)
    P(f"| {nm} | {dd['S1']:+.2f} | {dd['S2']:+.2f} | {'はい' if allT else 'いいえ'}(全 T) | {'はい' if max(dd.values()) <= -0.5 else 'いいえ'} |")
open('out/result.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')
print('\n'.join(L))
