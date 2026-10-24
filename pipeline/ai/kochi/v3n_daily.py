# -*- coding: utf-8 -*-
"""他場版 v3n の毎日(2026-10-10・確かめ = out/kochi_official.md・out/kochi_blend2.md・out/nation.md)。

  py -3.12 -X utf8 src/kochi/v3n_daily.py 2026-10-11 作業の置き場 [--write] [--no-fetch] [--tracks 54,55]

1. 公式の表を落とす(k0_dl・nar-official の公開 REST・約 3 分)。KDSCOPE と同じ形に直す(k9 build)。
2. 場ごとに材料を作る(k1・k4・k8 = feat2 + G2 + n_ の 123 列・その場を走った馬)。
3. 2026-10-15 第 9 版(決め 31・v3 の out/v3n_one_u.md): 全国 1 本の固定の木(v3n_one・暗号化リリース・年 1 回 9 月に学び直す)に
   base-v1 の朝の材料表(nar-ai-feat の成果物 nar_ai_feat_run・--feat)のその日の行 + 2. の場の材料 v_ + 場の番号を入れて当てる。
   (第 8 版までの「場ごとに毎日学ぶ木 × W + base-v1 の行の混ぜ」はやめた)。材料表に無い・馬番がそろわないレースは書かない(後の便で書く)。
4. γ・3 着内の曲線(v3n_one_p5.json)→ 並び読み u(イの p5 で仕上げた重み)→ E1・能検 → 勝つ率の直し(k は版ごと・暗号化した定数)。
   2026-10-15 第 10 版(決め 32・v3 の out/v3n_2015_u.md): 木を材料表 2014〜・学び 2015-01〜の B15 に替えた(便の材料表は今のまま)。
   γ・曲線・並び読みの重みは B15 の p5 で決め直し・勝つ率の直しの k も B15 で決め直し(meta.one15)。
   2026-10-25 第 11 版(決め 54・v3 の out/v3n_trees_judge.md): 同じ作りの木の本数を 3 着内 2 値 2550・順位 1140・勝ち 1040 本に(form が trees54)。
   γ・曲線・並び読み・E1・能検・勝つ率の直しの k(mo3)・混ぜ(mo3)を新しい木で決め直し(meta.trees54・meta.one15 も残す = 混ぜ・f41 の入口は同じ)。
5. --write のときだけ nar_ai_marks に model='v3n-1'・timing='morning' で書く(base_v1.write_marks = 朝の行は凍結・読み直し)。
   meta.runners = [{num, p1, p3}](南関 v3 と同じ形)。画面に出すかはサイト側の旗で決める(出すまでは見えない)。
対象 = out/nation.md で「入れ替えてよい」の場から南関を除いた 8 場 + 盛岡・姫路(2026-10-10 ユーザー・線は通っていない)= 10 場。
環境変数: SUPABASE_URL・SUPABASE_ANON_KEY か SUPABASE_SERVICE_KEY・NAR_JOBS_AI(base_v1.py の場所・既定 pipeline/ai)。
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, os.environ.get('NAR_JOBS_AI', str(HERE.parent)))  # base_v1(材料表の読み・帯の表)
MODEL_ID = 'v3n-1'
W = {30: 0.75, 35: 0.75, 36: 0.5, 46: 0.5, 47: 0.75, 48: 0.5, 50: 0.75, 51: 0.5, 54: 0.75, 55: 0.5}  # 対象 10 場(第 9 版から混ぜの割合は使わない・場の一覧として残す)
MARKS = ['◎', '○', '▲', '△', '△']  # 2026-10-10 ユーザー決定: 印は 5 頭(◎○▲△△)
NO_MORNING = ['e_baba', 'e_tenko']  # 当日の馬場・天気 = 公式の表は前の日まで空欄 = 朝の模型に入れない(入れて空で当てると確率がずれる)
FORM = 'v3n-11: trees54 (base-v1 + v_ + trk・2015〜・木 2550/1140/1040) + seq-trees54'  # meta に残す作りの名前(model の名前は v3n-1 のまま = サイト・成績の読み口を変えない)・v3n_one.FORM と同じ
# γ(頭数の帯ごとの s^γ ÷ Σ)と 3 着内の曲線は第 9 版から v3n_one_p5.json(イの選びで決め直した値)


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
    import k10_offeval as k10
    import k20_lg
    import k25_blood
    import k29_seq_live
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
    # 2026-10-12 第 6 版: 並び読み AI(14 場 + 中央の過去 10 走)の外した分を 3 着内の率に足す(out/v3n_seq.md)。⛔失敗しても第 5 版のまま書く
    try:
        SQ = k29_seq_live.prep(off, day, [name[j] for j in tracks], log=lambda *a: print(*a, flush=True))
    except Exception as e:  # noqa: BLE001
        print('並び読み 失敗 = 第 5 版のまま', type(e).__name__, str(e)[:200], flush=True)
        SQ = None
    # 2026-10-13 第 7 版: 率の直し E1 と初出走の能検の z(v3 の out/v3n_ab.md・v3n_e1.py)。⛔能検が読めなくても E1 だけで書く
    import v3n_e1
    import v3n_p1
    import v3n_p1mix  # 決め 40: 画面の勝つ率を 3 着内率と混ぜる(定数は暗号化した定数)
    NZ, nk_ok = {}, False
    try:
        NK = v3n_e1.fetch_rows(k0_dl.sb)
        ru = pd.read_parquet(off / 'runs.parquet', columns=['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'birth_date'])
        ru['race_date'] = ru.race_date.astype(str).str[:10]
        ru['hid'] = ru.horse_name.astype(str) + '|' + ru.birth_date.astype(str).str[:10]
        seen = set(ru.loc[ru.race_date < day, 'hid'])   # 全場の公式の記録で今日より前に 1 行でもある馬 = 初出走でない(研究の nprev と同じ)
        td = ru[(ru.race_date == day) & ~ru.hid.isin(seen)].copy()
        td['num'] = pd.to_numeric(td.runner_number, errors='coerce')
        td = td.dropna(subset=['num'])
        for (t_, r_), g_ in td.groupby(['track', 'race_no']):
            zz = v3n_e1.noken_z(NK, {int(n): str(h) for n, h in zip(g_.num, g_.horse_name)}, day)
            if zz:
                NZ[(str(t_), int(r_))] = zz
        nk_ok = True
        print('能検の行', len(NK), '・今日の初出走', len(td), '頭・z のある馬', sum(len(v) for v in NZ.values()), flush=True)
    except Exception as e:  # noqa: BLE001
        print('能検 読めない = 率の直し E1 だけ', type(e).__name__, str(e)[:200], flush=True)
        NZ = {}
    # 2026-10-15 第 9 版(決め 31): 場の木 × W + base-v1 の行の混ぜをやめ、全国 1 本の固定の木(v3n_one)で当てる。
    #   材料 = base-v1 の朝の材料表(nar-ai-feat の成果物 nar_ai_feat_run)のその日の行 + 場の材料 v_(上で作った t{場})+ 場の番号。
    #   材料表に無い・馬番がそろわないレースは書かない(後の便で書く)。⛔木が読めなければ何も書かない(落ちる)
    import v3n_one
    ONE = v3n_one.load()
    T54 = str(ONE.get('form', '')).endswith('trees54')  # 第 11 版の木(決め 54)= k と混ぜを mo3・行に meta.trees54
    ONE15 = T54 or str(ONE.get('form', '')).endswith('one15')  # 第 10 版の木(決め 32)= 勝つ率の直しの k を mo2・行に meta.one15
    VK = 'mo3' if T54 else 'mo2' if ONE15 else 'mo1'
    MV = 'mo3' if T54 else 'mo'  # 混ぜの定数(決め 40 = mo・決め 54 で学び直し = mo3)
    feat = arg('--feat', os.environ.get('V3N_FEAT', 'feat/nar_ai_feat_run.csv.gz'))
    FD = v3n_one.feat_day(feat, day, [name[j] for j in tracks])
    print('材料表', feat, 'その日の行', len(FD), '・木', ONE['cut'], '切り(〜', ONE['trained_to'], ')', flush=True)
    TE, VT = {}, []
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
        te = T[T.date == D].copy()
        if te.empty:
            continue
        TE[j] = te
        VT.append(pd.DataFrame({'track': name[j], 'race_date': day, 'race_no': te.race.astype('int64').to_numpy(),
                                'runner_number': te.umaban.astype('int64').to_numpy(),
                                **{c: (te[c].astype('float32').to_numpy() if c in te.columns else np.full(len(te), np.nan, 'float32'))
                                   for c in ONE['vcols']}}))
        print(name[j], '・その日の出走', len(te), '・場の材料の欠け列', sum(c not in te.columns for c in ONE['vcols']), flush=True)
    PR = {}
    if VT and not FD.empty:
        pr = v3n_one.predict(ONE, FD, pd.concat(VT, ignore_index=True))
        PR = {(t_, int(r_)): g_.set_index('runner_number') for (t_, r_), g_ in pr.groupby(['track', 'race_no'])}
    trained_to = ONE['trained_to']
    for j, te in TE.items():
        trk = name[j]
        for rno, g in te.groupby('race'):
            g = g.sort_values('umaban')
            nums = g.umaban.astype(int).to_numpy()
            P = PR.get((trk, int(rno)))
            if P is None or not all(n in P.index for n in nums):
                show.append(f'{trk}{int(rno)}R base-v1 の材料表に無い・馬番がそろわない = 書かない')
                continue
            g3, pwg = P.loc[nums, 'g3'].to_numpy(float), P.loc[nums, 'pwg'].to_numpy(float)
            s3 = g3 / g3.sum()
            c1 = pwg / pwg.sum()
            gm = v3n_one.gamma(len(g))
            c = v3n_one.sharpen(s3, len(g))
            p3 = v3n_one.p3(c, len(g))  # 第 9 版: イの頭数 3 帯の曲線(v3n_one_p5.json)
            u = k29_seq_live.resid(SQ, trk, rno, nums)  # 並び読みの外した分(イの p5 で仕上げた重み・無ければ足さない)
            if u is not None:
                p3 = np.clip(1 / (1 + np.exp(-(np.log(p3 / (1 - p3)) + u))), 0.001, 0.999)
            nz = NZ.get((trk, int(rno)), {})
            p3, e1on = v3n_e1.apply(p3, np.array([nz.get(int(n), 0.0) for n in nums]))  # 第 7 版: 取消の前の頭数で E1 + 能検(4 頭未満はかけない)
            key = p3 if (u is not None or (e1on and nz)) else c   # 印 = 並び読み・能検を足した 3 着内の率の順(E1 は並びを変えない)
            sc = key / key.sum()
            order = np.argsort(-key, kind='stable')
            marks = [{'num': int(nums[i]), 'mark': MARKS[k_], 'score': round(float(sc[i]) * 100, 1)} for k_, i in enumerate(order[:5])]
            # 勝つ率の直し(決め 29・第 9 版の k = 決め 31): c1 = イの勝ち(帯の表の後)に 並び読み u + 能検 β·z を付いて行かせる。表示の p3 = max(p3, p1)
            zz = np.array([nz.get(int(n), 0.0) for n in nums]) if e1on else np.zeros(len(nums))
            q1 = v3n_p1.follow(c1, (np.asarray(u, float) if u is not None else 0.0) + v3n_e1.BETA_NOKEN * zz, VK)
            q1r = q1  # 混ぜる前の勝つ率(meta.p1_raw)
            mixed = ONE15 and len(nums) >= v3n_p1mix.MIN_N  # 混ぜの定数は第 10 版(B15)で学んだ = 第 10 版の行だけ・4 頭以下は混ぜない
            if mixed:
                q1 = v3n_p1mix.mix(q1, p3, MV)  # 画面の勝つ率を 3 着内率と混ぜる(決め 40)。印は上で決めたまま
            p3s = np.maximum(p3, q1)
            meta = {'n': int(len(g)), 'model': MODEL_ID, 'form': FORM + (('+e1+noken' if nk_ok else '+e1') if e1on else ''), 'one': ONE['cut'], **({'one15': True} if ONE15 else {}), **({'trees54': True} if T54 else {}),
                    'gamma': gm, 'trained_to': trained_to, 'seq': u is not None,
                    **({'u': {str(int(n)): round(float(x), 4) for n, x in zip(nums, u)}} if u is not None else {}),
                    **({'noken_z': {str(k_): float(v) for k_, v in sorted(nz.items())}} if nz else {}),
                    'runners': [{'num': int(n), 'p1': round(float(a), 4), 'p3': round(float(b_), 4)} for n, a, b_ in zip(nums, q1, p3s)],
                    'p1c': {str(int(n)): round(float(a), 6) for n, a in zip(nums, c1)}, 'p1f': v3n_p1.TAG[VK],
                    **({'p1_raw': {str(int(n)): round(float(a), 6) for n, a in zip(nums, q1r)}, 'p1mix': v3n_p1mix.TAG[MV]} if mixed else {}),
                    'p': {str(int(n)): round(float(x), 4) for n, x in zip(nums, c)},
                    'own': {str(int(n)): [round(float(a), 4), round(float(b_), 4)] for n, a, b_ in zip(nums, c1, g3)}}
            rows.append({'track': trk, 'race_date': day, 'race_no': int(rno), 'marks': marks, 'meta': meta})
            show.append(f"{trk}{int(rno)}R " + ' '.join(f"{x['mark']}{x['num']}({x['score']})" for x in marks))
    (work / f'v3n_{day}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print('\n'.join(show))
    print('書く行', len(rows))
    print('勝つ率の混ぜ(決め 40)', sum(1 for r in rows if r['meta'].get('p1mix')), '/', len(rows), 'R')
    if write and rows:
        sys.path.insert(0, os.environ.get('NAR_JOBS_AI', 'pipeline/ai'))
        import base_v1 as B1
        B1.MODEL_ID = MODEL_ID  # ⛔write_marks が見る先をここで差し替える(v3_daily と同じ作法)
        took = B1.write_marks(rows, day, 'morning')
        print('書いた', took, '/', len(rows))


if __name__ == '__main__':
    main()
