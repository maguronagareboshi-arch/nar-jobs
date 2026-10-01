# -*- coding: utf-8 -*-
"""第 8 版 血統の見落とし確かめ(学習なし)。v7d の見込み(v7dpre_p3)に対して、血統 × コース条件の信号の段ごとに r = Y3 − p3 を見る。
既存の台本は import して呼ぶだけ(書き換えない)。

  py -3.12 -X utf8 src/v8bl_probe.py

■ 決め(結果を見る前に固定)
  走り = 全 NAR(v7c_run.sources)の 取消・除外 を除いた走り。2022-01-01 以降は読んだ直後に捨てる(assert)。
  「前」= レースの日より前(当日を含まない・t4_day3.wsum)。自分の走りは群から除く(S・M・D とも・c7_ と同じ)。
  つなぎ = v7d_run.ledger()(kd_horse・馬名|生年)。父 sire・母の父 bms・母 dam(= 母|母父)。
  頭数 = そのレースの着順 > 0 の数。期待 = 走りごとの min(3, 頭数) ÷ 頭数。比 = (3 着以内 + 3) ÷ (期待 + 3)。
  信号 = 条件の中の比 ÷ 全体の比。群のキーが無い・条件の中の前の走りが 0 なら欠け。
  距離帯 ≤1250 / ≤1550 / ≤1850 / それ以上。馬場 良・稍重 / 重・不良。季節 12〜2・3〜5・6〜8・9〜11。回り = TURN の表(無い場は欠け)。
  距離のずれ = 今回の距離 − 父(母の父)の産駒の 3 着以内の走りの距離の平均(3 着以内 20 回以上のとき)。
  芝ダ = 中央(kd_jra_runs・着順 > 0・頭数 = n_starters)の ダートの比 ÷ 芝の比。どちらかの走りが 0 なら欠け。自分の中央の走りは除く。
  見落とし = |上 − 下| ≥ 1.0 ポイント かつ > 2 × 標準誤差(開催 = 場 × 日でまとめる)かつ 6 年中 5 年以上で全体と同じ向き。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t4_day3 as d3  # noqa: E402
import v7_open as vo  # noqa: E402
import v7c_run as vc  # noqa: E402
import v7d_run as vd  # noqa: E402

V3 = Path('C:/Users/kouki/nankan_ai/v3')
REPO = Path(__file__).resolve().parent.parent
MD = REPO / 'out' / 'v8_blood_check.md'
JS = REPO / 'out' / 'v8_blood_check.json'
KEY = d3.KEY
CUT = '2022-01-01'
BIG = 100000
RIGHT = ['大井', '門別', '水沢', '金沢', '笠松', '名古屋', '園田', '姫路', '高知', '佐賀', '福山', '荒尾', '旭川', '札幌',
         '上山', '足利', '高崎', '益田', '三条', '紀三井寺']
LEFT = ['川崎', '船橋', '浦和', '盛岡', '中津', '宇都宮']
TURN = {**{t: 'R' for t in RIGHT}, **{t: 'L' for t in LEFT}}
GOING = {'良': 'A', '稍重': 'A', '重': 'B', '不良': 'B'}
GRP = {'S': 'sire', 'M': 'bms', 'D': 'dam'}
CND = {'td': 'この場×距離帯', 'd': '全場×距離帯', 'g': '馬場', 't': '回り', 's': '季節'}


def dbin(d):
    d = np.asarray(d, float)
    b = np.select([d <= 1250, d <= 1550, d <= 1850], ['1', '2', '3'], '4').astype(object)
    b[np.isnan(d)] = None
    return b


def season(dates):
    m = pd.to_datetime(dates).dt.month
    return m.map(lambda x: {12: 'w', 1: 'w', 2: 'w', 3: 'p', 4: 'p', 5: 'p', 6: 'u', 7: 'u', 8: 'u'}.get(x, 'a'))


def conds(d):
    b = dbin(d.distance_m)
    d['c_d'] = b
    d['c_td'] = np.where(pd.isna(b), None, d.track.astype(str) + '_' + pd.Series(b, index=d.index).astype(str))
    d['c_g'] = d.going.map(GOING)
    d['c_t'] = d.track.map(TURN)
    d['c_s'] = season(d.race_date).to_numpy()
    for c in ('c_d', 'c_td', 'c_g', 'c_t', 'c_s'):
        d[c] = d[c].where(pd.notna(d[c]), None)
    return d


def ratio(A):
    return (A[:, 0] + 3) / (A[:, 1] + 3)


def main():
    L, kmap, _ = vd.ledger()
    h, races = vc.sources()
    h = h[h.race_date < CUT].copy()
    assert h.race_date.max() < CUT
    r = h[~h.finish_note.isin(d3.CANCEL)].drop_duplicates(KEY + ['umaban']).copy()
    fin = pd.to_numeric(r.finish, errors='coerce')
    r['heads'] = (fin > 0).groupby([r[k] for k in KEY]).transform('sum').astype(float)
    r = r[r.heads > 0].copy()
    fin = pd.to_numeric(r.finish, errors='coerce')
    r['t3'] = ((fin > 0) & (fin <= 3)).astype(float)
    r['exp'] = np.minimum(3, r.heads) / r.heads
    r['one'] = 1.0
    r['t3d'] = r.t3 * r.distance_m.astype(float)
    r['dnum'] = d3.dnum_of(r.race_date)
    r['lk'] = vc.link_key(r.hid)
    r = r.merge(L[['sire', 'bms', 'dam']], left_on='lk', right_index=True, how='left')
    r = conds(r)
    trk_cnt = r.track.value_counts()
    unmapped = {t: int(n) for t, n in trk_cnt.items() if t not in TURN}
    going_ok = r.going.isin(list(GOING)).mean()
    print('走り', len(r), '馬場の読める割合', round(going_ok, 4), '回りの表に無い場', unmapped, flush=True)

    P = vo.nk(pd.read_parquet(V3 / 'v7d_final_preds.parquet'))
    assert P.race_date.max() < CUT
    hq = h.drop_duplicates(KEY + ['umaban'])[KEY + ['umaban', 'hid', 'distance_m', 'going']]
    q = P[KEY + ['umaban', 'year', 'n', 'Y3', 'v7dpre_p3']].merge(hq, on=KEY + ['umaban'], how='left', validate='1:1')
    q['dnum'] = d3.dnum_of(q.race_date)
    q['lk'] = vc.link_key(q.hid)
    q = q.merge(L[['sire', 'bms', 'dam']], left_on='lk', right_index=True, how='left')
    q['ketto'] = q.lk.map(kmap)
    q = conds(q)
    S = {}
    cols = ['t3', 'exp', 'one']
    self_all = np.nan_to_num(d3.wsum(r, ['hid'], cols + ['t3d'], q, BIG))
    self_c = {c: np.nan_to_num(d3.wsum(r, ['hid', 'c_' + c], cols, q, BIG)) for c in CND}
    for g, gc in GRP.items():
        T = d3.wsum(r, [gc], cols + ['t3d'], q, BIG)
        T = T - np.where(np.isnan(T), 0, self_all)
        allr = ratio(T)
        for c in CND:
            A = d3.wsum(r, [gc, 'c_' + c], cols, q, BIG)
            A = A - np.where(np.isnan(A), 0, self_c[c])
            v = ratio(A) / allr
            v[~(A[:, 2] > 0)] = np.nan
            S[f'{g}_{c}'] = v
        if g in ('S', 'M'):
            mean_d = np.where(T[:, 0] >= 20, T[:, 3] / np.where(T[:, 0] > 0, T[:, 0], np.nan), np.nan)
            off = q.distance_m.to_numpy(float) - mean_d
            S[f'{g}_doff_abs'] = np.abs(off)
            S[f'{g}_doff_sgn'] = off
        print('信号', g, flush=True)

    # 中央の芝・ダート
    J = pd.read_parquet(V3 / 'kd_jra_runs.parquet')
    J = J[J.date < pd.Timestamp(CUT)].copy()
    assert J.date.max() < pd.Timestamp(CUT)
    J = J[(J.finish > 0) & (J.n_starters > 0) & J.ketto.notna()].copy()
    sf = J.surface.astype(str)
    J['sd'] = np.where(sf.str.contains('ダ'), 'D', np.where(sf.str.contains('芝'), 'T', None))
    J = J[J.sd.notna()].copy()
    k = pd.read_parquet(V3 / 'kd_horse.parquet')
    k = k[k.ketto.notna()].copy()
    k['pri'] = (k.src != 'NU').astype(int)
    k = k.sort_values(['ketto', 'pri'], kind='mergesort').drop_duplicates('ketto', keep='first')
    for c in ('sire', 'bms'):
        k[c] = k[c].map(vc.norm)
    J['ketto'] = J.ketto.astype('int64')
    k['ketto'] = k.ketto.astype('int64')
    J = J.merge(k[['ketto', 'sire', 'bms']], on='ketto', how='left')
    t3 = (J.finish <= 3).astype(float)
    ex = np.minimum(3, J.n_starters) / J.n_starters
    isd = (J.sd == 'D').astype(float)
    J['dt3'], J['dex'], J['dn'] = t3 * isd, ex * isd, isd
    J['tt3'], J['tex'], J['tn'] = t3 * (1 - isd), ex * (1 - isd), 1 - isd
    J['dnum'] = d3.dnum_of(J.date)
    jc = ['dt3', 'dex', 'dn', 'tt3', 'tex', 'tn']
    qj = q.copy()
    qj['ketto'] = qj.ketto.astype(float)
    Js = J.copy()
    Js['ketto'] = Js.ketto.astype(float)
    selfj = np.nan_to_num(d3.wsum(Js, ['ketto'], jc, qj, BIG))
    jra_link = float(J.sire.notna().mean())
    for g, gc in (('S', 'sire'), ('M', 'bms')):
        A = d3.wsum(J, [gc], jc, q, BIG)
        A = A - np.where(np.isnan(A), 0, selfj)
        v = ((A[:, 0] + 3) / (A[:, 1] + 3)) / ((A[:, 3] + 3) / (A[:, 4] + 3))
        v[~((A[:, 2] > 0) & (A[:, 5] > 0))] = np.nan
        S[f'{g}_jdt'] = v
    print('中央', len(J), 'つながり', round(jra_link, 4), flush=True)

    # ---------------- 確かめ
    rr = ((q.Y3 - q.v7dpre_p3) * 100).to_numpy(float)
    clu = pd.factorize(q.track.astype(str) + '|' + q.race_date.astype(str))[0]
    rid = pd.factorize(q.track.astype(str) + '|' + q.race_date.astype(str) + '|' + q.race_no.astype(str))[0]
    yr = q.year.to_numpy()
    N = len(q)

    def cse_mean(m):
        x, c = rr[m], clu[m]
        e = x - x.mean()
        s = np.bincount(c, e)
        G = len(np.unique(c))
        return float(np.sqrt(G / (G - 1) * (s ** 2).sum()) / len(x))

    def cse_diff(ma, mb):
        z = np.zeros(N)
        z[ma] = (rr[ma] - rr[ma].mean()) / ma.sum()
        z[mb] = -(rr[mb] - rr[mb].mean()) / mb.sum()
        m = ma | mb
        s = np.bincount(clu[m], z[m])
        G = len(np.unique(clu[m]))
        return float(np.sqrt(G / (G - 1) * (s ** 2).sum()))

    R = {}
    for name, v in S.items():
        ok = ~np.isnan(v)
        cov = float(ok.mean())
        rk = pd.Series(v[ok]).rank(method='first').to_numpy()
        qb = np.full(N, -1)
        qb[ok] = np.minimum((rk - 1) * 5 // ok.sum(), 4).astype(int)
        bins = []
        for b in range(5):
            m = qb == b
            bins.append({'n': int(m.sum()), 'r': float(rr[m].mean()), 'se2': 2 * cse_mean(m)})
        top, bot = qb == 4, qb == 0
        diff = float(rr[top].mean() - rr[bot].mean())
        se2 = 2 * cse_diff(top, bot)
        yd = {int(y): float(rr[top & (yr == y)].mean() - rr[bot & (yr == y)].mean()) for y in range(2016, 2022)}
        same = int(sum(np.sign(x) == np.sign(diff) for x in yd.values()))
        # レース内 1 位
        T = pd.DataFrame({'rid': rid[ok], 'v': v[ok], 'i': np.nonzero(ok)[0]})
        g = T.groupby('rid').v
        T = T[(g.transform('size') >= 2) & (g.transform('nunique') >= 2)]
        is1 = (T.v == T.groupby('rid').v.transform('max')).to_numpy()
        m1, m0 = np.zeros(N, bool), np.zeros(N, bool)
        m1[T.i.to_numpy()[is1]] = True
        m0[T.i.to_numpy()[~is1]] = True
        d1 = float(rr[m1].mean() - rr[m0].mean())
        s1 = 2 * cse_diff(m1, m0)
        flag = bool(abs(diff) >= 1.0 and abs(diff) > se2 and same >= 5)
        R[name] = {'cov': cov, 'bins': bins, 'diff': diff, 'se2': se2, 'years': yd, 'same': same,
                   'in1': d1, 'in1_se2': s1, 'in1_n': int(m1.sum()), 'flag': flag}
        print(name, round(cov, 3), round(diff, 2), round(se2, 2), same, flag, flush=True)
    info = {'rows': N, 'runs': len(r), 'going_ok': float(going_ok), 'unmapped_tracks': unmapped,
            'jra_runs': len(J), 'jra_sire_link': jra_link, 'mean_r': float(rr.mean())}
    JS.write_text(json.dumps({'info': info, 'res': R}, ensure_ascii=False, indent=1), encoding='utf-8')
    write_md(R, info)


LAB = {'td': 'この場×距離帯', 'd': '全場×距離帯', 'g': '馬場(重・不良 か 良・稍重)', 't': '回り', 's': '季節',
       'doff_abs': '距離のずれ(大きさ)', 'doff_sgn': '距離のずれ(+ = 今回が長い)', 'jdt': '中央のダート向き(ダ ÷ 芝)'}
GL = {'S': '父', 'M': '母の父', 'D': '母の子(兄弟)'}


def lab(n):
    g, c = n.split('_', 1)
    return f'{GL[g]} × {LAB[c]}'


def write_md(R, info):
    fl = [n for n, x in R.items() if x['flag']]
    big = max(R, key=lambda n: abs(R[n]['diff']))
    cov = [x['cov'] for x in R.values()]
    L = ['# 血統の見落とし確かめ(第 8 版の下調べ・学習なし)', '',
         '## 要約', '',
         f'1. 父・母の父・兄弟の成績を、コース・距離・馬場・回り・季節・中央の芝ダートに分けた目安を {len(R)} 個作り、今の予想(第 7 版 d)の見込みと実際の 3 着以内の差を比べた。',
         f'2. 目安が高い馬ほど見込みより多く来ているなら「見落とし」。決めた線を越えたのは {len(fl)} 個' + (f'({"・".join(lab(n) for n in fl)})。' if fl else '。'),
         f'3. 差が一番大きかったのは「{lab(big)}」で、上の 2 割と下の 2 割の差 {R[big]["diff"]:+.2f} ポイント(ぶれの幅 ±{R[big]["se2"]:.2f})。',
         f'4. 目安が作れた馬の割合は {min(cov):.0%}〜{max(cov):.0%}(血統がつながらない・前の走りが無い馬は外した)。',
         '5. ' + ('線を越えた目安は、今の予想が取りこぼしている可能性がある(次に材料として試す候補)。' if fl else
                  '今の予想は、コースに合った血統をほぼ取りこぼしていない(差は小さいか、年ごとに向きがそろわない)。'), '',
         '## 決め(結果を見る前に固定)', '',
         '- 対象 = v7d_final_preds.parquet(2016〜2021・南関)'
         f' {info["rows"]:,} 行。r = 実際の 3 着以内(1/0)− 見込み v7dpre_p3、×100 = ポイント。全体の r の平均 {info["mean_r"]:+.2f}。',
         f'- 走り = 全 NAR {info["runs"]:,} 走(取消・除外を除く・2022 年以降は捨てた)。「前」= レースの日より前(当日を含まない)。自分の走りは群から除く。',
         '- 比 = (3 着以内 + 3) ÷ (期待 + 3)、期待 = 走りごとの min(3, 頭数) ÷ 頭数(頭数 = 着順 > 0 の数)。信号 = 条件の中の比 ÷ 全体の比。'
         '群のキーが無い・条件の中の前の走りが 0 なら欠け。',
         '- 距離帯 〜1200(≤1250)・1300〜1500(≤1550)・1600〜1800(≤1850)・1900〜。馬場 良・稍重 / 重・不良'
         f'(馬場の読める走り {info["going_ok"]:.1%})。季節 12〜2・3〜5・6〜8・9〜11。',
         '- 回り: 右 = ' + '・'.join(RIGHT) + '/ 左 = ' + '・'.join(LEFT) + '。表に無い場(ばんえい等)は欠け: '
         + '、'.join(f'{t} {n:,}' for t, n in info['unmapped_tracks'].items()) + '。',
         '- 距離のずれ = 今回の距離 − 父(母の父)の産駒の 3 着以内の走りの距離の平均(3 着以内 20 回以上)。',
         f'- 中央の芝ダ = kd_jra_runs(2022 年より前・着順 > 0・芝かダート){info["jra_runs"]:,} 走、父のつながり {info["jra_sire_link"]:.1%}。'
         'ダートの比 ÷ 芝の比、どちらかが 0 走なら欠け。自分の中央の走りは除く。',
         '- 5 段 = 欠けでない行を信号の小さい順に 5 等分(同じ値は並び順で割る)。誤差 = 2 × 標準誤差(開催 = 場 × 日でまとめる)。',
         '- 見落とし = |上 − 下| ≥ 1.0 ポイント かつ > 2 × 標準誤差 かつ 6 年中 5 年以上で全体と同じ向き。'
         '(向きは両方を見る: 距離のずれの大きさは「上が悪い」も見落とし)', '',
         '## 信号ごとの表', '',
         '| 信号 | カバー率 | 段1(下) | 段2 | 段3 | 段4 | 段5(上) | 上−下 ±2SE | 年ごと(16〜21) | 同じ向き | レース内1位−他 ±2SE | 見落とし |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for n, x in R.items():
        b = ' | '.join(f'{z["r"]:+.2f}±{z["se2"]:.2f}' for z in x['bins'])
        y = ' '.join(f'{v:+.1f}' for v in x['years'].values())
        L.append(f'| {lab(n)} | {x["cov"]:.1%} | {b} | {x["diff"]:+.2f} ±{x["se2"]:.2f} | {y} | {x["same"]}/6 | '
                 f'{x["in1"]:+.2f} ±{x["in1_se2"]:.2f} | {"はい" if x["flag"] else "—"} |')
    n0 = R[next(iter(R))]['bins']
    L += ['', f'- 各段の頭数(例: 最初の信号)= ' + '・'.join(f'{z["n"]:,}' for z in n0) + '。全信号の段ごとの頭数は out/v8_blood_check.json。', '',
          '## 見落としに当たった信号', '']
    L += [f'- {lab(n)}: 上−下 {R[n]["diff"]:+.2f}(±{R[n]["se2"]:.2f})・{R[n]["same"]}/6 年同じ向き・カバー率 {R[n]["cov"]:.1%}' for n in fl] or ['- なし']
    MD.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('書いた', MD, flush=True)


if __name__ == '__main__':
    main()
