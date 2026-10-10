# -*- coding: utf-8 -*-
"""他場版 v3n の毎日(2026-10-10・確かめ = out/kochi_official.md・out/kochi_blend2.md・out/nation.md)。

  py -3.12 -X utf8 src/kochi/v3n_daily.py 2026-10-11 作業の置き場 [--write] [--no-fetch] [--tracks 54,55]

1. 公式の表を落とす(k0_dl・nar-official の公開 REST・約 3 分)。KDSCOPE と同じ形に直す(k9 build)。
2. 場ごとに材料を作る(k1・k4・k8 = feat2 + G2 + n_ の 123 列・その場を走った馬)。
3. 場ごとに、その日より前(2015-01〜)で 3 着内と勝ちを学ぶ(確かめと同じ設定・毎日学び直す)。
4. base-v1 の朝の行(nar_ai_marks・model='base-v1'・timing='morning')の割合と、場の版の割合を W[場] : 1−W[場] で混ぜる
   (W は out/nation.md の選ぶ期間で決めた値)。base-v1 の行が無い・馬番がそろわないレースは書かない(後の便で書く)。
5. --write のときだけ nar_ai_marks に model='v3n-1'・timing='morning' で書く(base_v1.write_marks = 朝の行は凍結・読み直し)。
   meta.runners = [{num, p1, p3}](南関 v3 と同じ形)。画面に出すかはサイト側の旗で決める(出すまでは見えない)。
対象 = out/nation.md で「入れ替えてよい」の場から南関を除いた 8 場 + 盛岡・姫路(2026-10-10 ユーザー・線は通っていない)= 10 場。
環境変数: SUPABASE_URL・SUPABASE_ANON_KEY か SUPABASE_SERVICE_KEY・NAR_JOBS_AI(base_v1.py の場所・既定 pipeline/ai)。
"""
import json
import os
import sys
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
MODEL_ID = 'v3n-1'
W = {30: 0.75, 35: 0.75, 36: 0.5, 46: 0.5, 47: 0.75, 48: 0.5, 50: 0.75, 51: 0.5, 54: 0.75, 55: 0.5}  # 盛岡・姫路は 2026-10-10 ユーザーの判断で足した
MARKS = ['◎', '○', '▲', '△', '△']  # 2026-10-10 ユーザー決定: 印は 5 頭(◎○▲△△)
NO_MORNING = ['e_baba', 'e_tenko']  # 当日の馬場・天気 = 公式の表は前の日まで空欄 = 朝の模型に入れない(入れて空で当てると確率がずれる)
FORM = 'v3n-3: glicko18 + no-going + blood9 + sharpen'  # meta に残す作りの名前(model の名前は v3n-1 のまま = サイト・成績の読み口を変えない)
# 2026-10-11 第 3 版(v3 の out/v3n_next.md): 混ぜた割合 s を頭数の帯ごとに s^γ ÷ Σ s^γ(順位は変わらない)。γ は選ぶ期間 2024-09〜2025-08 で決めた
GAMMA = [(8, 0.89), (10, 0.95), (12, 1.01), (99, 1.15)]  # (この頭数まで, γ)


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    day, work = sys.argv[1], Path(sys.argv[2])
    write, fetch = '--write' in sys.argv, '--no-fetch' not in sys.argv
    tracks = [int(x) for x in arg('--tracks', ','.join(map(str, W))).split(',')]
    D = pd.Timestamp(day)
    work.mkdir(parents=True, exist_ok=True)
    off = work / 'official'
    import k0_dl
    if fetch:
        k0_dl.main([str(off).replace('\\', '/')])
    import k9_official as k9
    k9.O = str(off).replace('\\', '/') + '/'
    k9.ALT = work / 'off'
    runs = pd.read_parquet(off / 'runs.parquet', columns=['track', 'race_date'])
    today = set(runs.loc[runs.race_date == day, 'track'].map(k9.JYO).dropna().astype(int))
    tracks = [j for j in tracks if j in today]
    if not tracks:
        print('対象の場の開催が無い日', day)
        return
    name = {v: k for k, v in k9.JYO.items()}
    print('開催', ' '.join(name[j] for j in tracks), flush=True)
    k9.build()
    k1, k4, k8 = k9.patch()
    import k3_eval as k3
    import k10_offeval as k10
    import k20_lg
    import k25_blood
    rows, show = [], []
    for j in tracks:
        d = k9.ALT / f't{j}'
        d.mkdir(exist_ok=True)
        k1.KOCHI = j
        k1.OUT, k4.V, k8.V = d, d, d
        k1.main()
        k4.main()
        k8.main()
    # 2026-10-10 第 2 版: 南関の Glicko など 18 列(全場で 1 回)+ 朝に分からない馬場・天気の列を抜いて学ぶ(v3 の out/v3n_glicko.md)
    LG = k20_lg.build(k9.ALT / 'kd_se.parquet', k9.ALT / f't{tracks[0]}' / 'si_all.parquet', log=lambda *a: print(*a, flush=True))
    # 2026-10-11 第 3 版: 血統の相性 b9_ 9 列(全場で 1 回・公式の runs・races・profiles から・前の走りだけ)
    BL = k25_blood.build(off, log=lambda *a: print(*a, flush=True))
    for j in tracks:
        d = k9.ALT / f't{j}'
        T, cols = k10.load(d)
        x = LG[LG.track == j]
        x = pd.DataFrame({'date': pd.to_datetime(x.race_date), 'race': x.race_no.astype(T.race.dtype),
                          'umaban': x.umaban.astype(T.umaban.dtype), **{c: x[c] for c in k20_lg.LGC}})
        T = T.merge(x, on=['date', 'race', 'umaban'], how='left', validate='1:1')
        b = BL[BL.track == name[j]]
        b = pd.DataFrame({'date': pd.to_datetime(b.race_date), 'race': b.race_no.astype(T.race.dtype),
                          'umaban': b.umaban.astype(T.umaban.dtype), **{c: b[c] for c in k25_blood.B9}})
        T = T.merge(b, on=['date', 'race', 'umaban'], how='left', validate='1:1')
        cols = [c for c in cols if c not in NO_MORNING] + k20_lg.LGC + k25_blood.B9
        te = T[T.date == D].copy()
        tr = T[(T.date >= '2015-01-01') & (T.date < D)]
        if te.empty:
            continue
        for y in ('Y3', 'Y1'):
            m = k3.train(tr, y, cols)
            k = 1 if y == 'Y1' else 3
            z = k3.logit(np.minimum(k / te.n.to_numpy(float), 0.99))
            te['p' + y[1]] = 1 / (1 + np.exp(-(z + m.predict(te[cols].astype(float), raw_score=True))))
        trained_to = str(tr.date.max().date())
        trk = name[j]
        print(trk, '学び', f'{len(tr):,} 行', '〜', trained_to, '・その日の出走', len(te), flush=True)
        base = k0_dl.sb.get('/rest/v1/nar_ai_marks?select=race_no,meta&model=eq.base-v1&timing=eq.morning'
                            f'&track=eq.{urllib.parse.quote(trk)}&race_date=eq.{day}&limit=100')
        bp = {int(r['race_no']): (r['meta'] or {}) for r in base}
        w = W[j]
        for rno, g in te.groupby('race'):
            g = g.sort_values('umaban')
            nums = g.umaban.astype(int).to_numpy()
            b = bp.get(int(rno), {})
            p_b = {int(k): float(v) for k, v in (b.get('p') or {}).items()}
            w_b = {int(k): float(v) for k, v in (b.get('p_win') or {}).items()}
            if not p_b or not all(n in p_b for n in nums):
                show.append(f'{trk}{int(rno)}R base-v1 の行が無い・馬番がそろわない = 書かない')
                continue
            s3 = g.p3.to_numpy() / g.p3.sum()
            sb3 = np.array([p_b[n] for n in nums]); sb3 = sb3 / sb3.sum()
            c = w * s3 + (1 - w) * sb3
            gm = next(v for k_, v in GAMMA if len(g) <= k_)
            c = np.power(np.clip(c, 1e-9, 1), gm)
            c = c / c.sum()
            s1 = g.p1.to_numpy() / g.p1.sum()
            if w_b and all(n in w_b for n in nums):
                sb1 = np.array([w_b[n] for n in nums]); sb1 = sb1 / sb1.sum()
                c1 = w * s1 + (1 - w) * sb1
            else:
                c1 = s1
            p3 = np.clip(3 * c, 0.001, 0.999)
            order = np.argsort(-c, kind='stable')
            marks = [{'num': int(nums[i]), 'mark': MARKS[k_], 'score': round(float(c[i]) * 100, 1)} for k_, i in enumerate(order[:5])]
            meta = {'n': int(len(g)), 'model': MODEL_ID, 'form': FORM, 'w': w, 'gamma': gm, 'trained_to': trained_to,
                    'runners': [{'num': int(n), 'p1': round(float(a), 4), 'p3': round(float(b_), 4)} for n, a, b_ in zip(nums, c1, p3)],
                    'p': {str(int(n)): round(float(x), 4) for n, x in zip(nums, c)},
                    'own': {str(int(n)): [round(float(a), 4), round(float(b_), 4)] for n, a, b_ in zip(nums, g.p1, g.p3)}}
            rows.append({'track': trk, 'race_date': day, 'race_no': int(rno), 'marks': marks, 'meta': meta})
            show.append(f"{trk}{int(rno)}R " + ' '.join(f"{x['mark']}{x['num']}({x['score']})" for x in marks))
    (work / f'v3n_{day}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print('\n'.join(show))
    print('書く行', len(rows))
    if write and rows:
        sys.path.insert(0, os.environ.get('NAR_JOBS_AI', 'pipeline/ai'))
        import base_v1 as B1
        B1.MODEL_ID = MODEL_ID  # ⛔write_marks が見る先をここで差し替える(v3_daily と同じ作法)
        took = B1.write_marks(rows, day, 'morning')
        print('書いた', took, '/', len(rows))


if __name__ == '__main__':
    main()
