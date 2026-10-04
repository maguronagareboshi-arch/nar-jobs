# -*- coding: utf-8 -*-
"""v31: 市場のずれ模型に足す「前に捨てた材料の前日版 51 本」をその日の出走馬について作る(研究 nankan-ai-v3 の
src/f5_scripts/bundle_t9.py・src/v31_bundle_gap.py と同じ値になるように)。

材料の作り方は研究の 4 台本(f5_probe・v8fa_probe・v8fm_probe・v8bl_probe・写しをそのまま置いた)を動かして作る。
台本は書き換えず、読み込みの所だけ差し込む(研究の bundle_t9.probe と同じ作法):
  - CUT(この日より前だけ読む見張り)= その日の翌日
  - 走り h・レースの表 = 便がその日の予想に使った h・races(その日の行は出走表だけ = 着順が無い)
  - SI の土台 = t4_open.base_of(h, races)(第 9 版の材料と同じ作り)
  - 行の表 = その日の南関の出走馬
  - 中央の走り・血統 = v7d_run.kd_jra_runs()・kd_horse()(固定ファイル + その日の取り込み)
  - 着順の無いその日の行は、着順 99(3 着の外)を仮に入れる(研究の台本は着順の無いレースを捨てるため。
    材料はどれも「前の走り」だけから作るので、この仮の値は材料に入らない = 研究の値と照合して確かめた)。
列名は研究の v31_bundle_gap.bundle と同じ(f5_U・v8fa_BL・v8bl_S_g など)。当日の BF・BG は作るが返さない。

  python -X utf8 pipeline/ai/v3/v31_bundle.py check DAY [DAY ...]   # 手元: 研究の値(v3/probe_S26_*.parquet)と照合
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
NAMES = ['f5_probe', 'v8fa_probe', 'v8fm_probe', 'v8bl_probe']
KEY = ['track', 'race_date', 'race_no']
Q5 = KEY + ['umaban']
NANKAN = ['大井', '川崎', '船橋', '浦和']
DROP = ['f5_BF', 'f5_BG']
GOING_COLS = ['v8bl_S_g', 'v8bl_M_g', 'v8bl_D_g']
GOING_ALT = {'A': '良', 'B': '重'}  # v8bl_probe.GOING の 2 つの帯の代表


def pick_going(B, going):
    """当日の馬場で馬場の得手 3 列を 2 通りの中から選ぶ(馬場が分からない・2 通りが無ければそのまま)。"""
    ab = {'良': 'A', '稍重': 'A', '重': 'B', '不良': 'B'}.get(str(going or '').strip())
    B = B.copy()
    if ab is None:
        return B
    for c in GOING_COLS:
        if f'{c}__{ab}' in B.columns:
            B[c] = B[f'{c}__{ab}']
    return B


def _rows(h, day):
    d = h[(h.race_date.astype(str).str[:10] == day) & h.track.isin(NANKAN)].drop_duplicates(Q5).copy()
    d = d[Q5].copy()
    d['year'] = int(day[:4])
    d['n'] = d.groupby(KEY).umaban.transform('size')
    d['Y3'] = 0.0
    d['v7dpre_p3'] = 0.5
    return d.reset_index(drop=True)


def _run(name, inj, cut):
    src = HERE / f'{name}.py'
    code = src.read_text(encoding='utf-8')
    rep = [("CUT = '2022-01-01'", f"CUT = '{cut}'"),
           ("h, races = vc.sources()", "h, races = _INJ['h'].copy(), _INJ['races'].copy()"),
           ("pd.read_parquet(V3 / 't4_base_2014_2021.parquet'", "_INJ['readU'](None"),
           ("pd.read_parquet(V3 / 'v7d_final_preds.parquet')", "_INJ['rows'].copy()"),
           ("pd.read_parquet(V3 / 'kd_jra_runs.parquet')", "vd.kd_jra_runs()"),
           ("pd.read_parquet(V3 / 'kd_horse.parquet')", "vd.kd_horse()")]
    for a, b in rep:
        code = code.replace(a, b)
    assert f"CUT = '{cut}'" in code and "_INJ['rows']" in code and "_INJ['h']" in code, name
    marker = '    rr = ((q.Y3 - q.v7dpre_p3) * 100).to_numpy(float)'
    assert code.count(marker) == 1, name
    dump = ("    _D = q[KEY + ['umaban']].copy()\n"
            "    for _k, _v in S.items():\n"
            "        _D['S_' + _k] = np.asarray(_v, float)\n"
            "    _INJ['out'] = _D\n"
            "    return\n")
    code = code.replace(marker, dump + marker)
    g = {'__name__': '__main__', '__file__': str(src), '_INJ': inj}
    exec(compile(code, str(src), 'exec'), g)
    D = inj.pop('out')
    return D.rename(columns={c: f'{name[:-6]}_{c[2:]}' for c in D.columns if c.startswith('S_')})


def feats51(day, h, races, U=None, log=print):
    """→ その日の南関の出走馬 1 頭 1 行(Q5 + 51 列)。h・races は便の予想と同じもの(その日の行は出走表)。"""
    import t4_open
    cut = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    h = h[h.race_date.astype(str).str[:10] <= day].copy()
    races = races[races.race_date.astype(str).str[:10] <= day].copy()
    if U is None:
        U = t4_open.base_of(h, races)
    U = U[U.race_date.astype(str).str[:10] <= day]
    rows = _rows(h, day)
    today = h.race_date.astype(str).str[:10] == day
    fin = pd.to_numeric(h.finish, errors='coerce')
    m = today & ~(fin > 0)
    h.loc[m, 'finish'] = 99 if pd.api.types.is_numeric_dtype(h.finish) else '99'
    log('v31 51 本: 出走', len(rows), '・仮の着順を入れた行', int(m.sum()))

    def readU(_, columns=None):
        return U[columns].copy() if columns is not None else U.copy()
    out = rows[Q5].copy()
    for n in NAMES:
        D = _run(n, {'h': h, 'races': races, 'readU': readU, 'rows': rows}, cut)
        out = out.merge(D, on=Q5, how='left', validate='1:1')
    out = out.drop(columns=[c for c in DROP if c in out.columns])
    # 馬場の得手 3 列(v8bl の S_g・M_g・D_g)は今回の馬場で決まる。前の晩は馬場が分からず空になるので、
    # その日の南関の馬場を「良・稍重(A)」「重・不良(B)」に置いた 2 通りを作っておき、当日の便が実際の馬場で選ぶ
    # (v29_gap.feats)。研究は実際の馬場で作っていた = 当日の便で研究と同じ値になる(check_going で照合)。
    for ab, gv in GOING_ALT.items():
        h2, r2 = h.copy(), races.copy()
        h2.loc[today & h2.track.isin(NANKAN), 'going'] = gv
        r2.loc[(r2.race_date.astype(str).str[:10] == day) & r2.track.isin(NANKAN), 'going'] = gv
        D = _run('v8bl_probe', {'h': h2, 'races': r2, 'readU': readU, 'rows': rows}, cut)
        D = D[Q5 + GOING_COLS].rename(columns={c: f'{c}__{ab}' for c in GOING_COLS})
        out = out.merge(D, on=Q5, how='left', validate='1:1')
    out['race_date'] = out.race_date.astype(str).str[:10]
    out['race_no'] = pd.to_numeric(out.race_no).astype(int)
    out['umaban'] = pd.to_numeric(out.umaban).astype(int)
    return out


def check(days):
    import t4_forecast
    import t4_open
    V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
    R = None
    for n in NAMES:
        x = pd.read_parquet(V3 / f'probe_S26_{n}.parquet')
        x = x.rename(columns={c: f'{n[:-6]}_{c[2:]}' for c in x.columns if c.startswith('S_')})
        R = x if R is None else R.merge(x, on=Q5, how='outer')
    R['race_no'], R['umaban'] = R.race_no.astype(int), R.umaban.astype(int)
    R['race_date'] = R.race_date.astype(str).str[:10]
    h0, races0 = t4_forecast.fill_key(*t4_open.load4('open'))
    for day in days:
        h = h0[h0.race_date.astype(str).str[:10] <= day].copy()
        # その日の行を出走表に戻す(結果の列を空に)
        today = h.race_date.astype(str).str[:10] == day
        for c in ('finish', 'time_sec', 'last3f', 'margin', 'f_l3', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4',
                  'body_weight', 'body_weight_change', 'popularity', 'odds_win'):
            if c in h.columns:
                h.loc[today, c] = np.nan
        F = feats51(day, h, races0)
        F['race_no'], F['umaban'] = F.race_no.astype(int), F.umaban.astype(int)
        F['race_date'] = F.race_date.astype(str).str[:10]
        m = F.merge(R, on=Q5, how='left', suffixes=('', '_r'))
        cs = [c for c in F.columns if c not in Q5]
        bad = {}
        for c in cs:
            a, b = m[c].to_numpy(float), m[c + '_r'].to_numpy(float)
            ok = (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-6)
            if not ok.all():
                bad[c] = (int((~ok).sum()), round(float(np.nanmean(np.abs(a - b))), 4))
        print('照合', day, '頭', len(F), '研究とつながった', int(m[cs[0] + '_r'].notna().sum() if cs else 0),
              '列', len(cs), '合わない列', len(bad), bad, flush=True)


def check_going(days):
    """手元: その日の馬場を隠して作り、実際の馬場で 2 通りから選んだ馬場の得手 3 列を研究の値と照合する。"""
    import t4_forecast
    import t4_open
    V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
    R = pd.read_parquet(V3 / 'probe_S26_v8bl_probe.parquet')
    R = R.rename(columns={c: f'v8bl_{c[2:]}' for c in R.columns if c.startswith('S_')})[Q5 + GOING_COLS]
    R['race_no'], R['umaban'] = R.race_no.astype(int), R.umaban.astype(int)
    R['race_date'] = R.race_date.astype(str).str[:10]
    h0, races0 = t4_forecast.fill_key(*t4_open.load4('open'))
    for day in days:
        h = h0[h0.race_date.astype(str).str[:10] <= day].copy()
        races = races0.copy()
        today = h.race_date.astype(str).str[:10] == day
        for c in ('finish', 'time_sec', 'last3f', 'margin', 'f_l3', 'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4',
                  'body_weight', 'body_weight_change', 'popularity', 'odds_win'):
            if c in h.columns:
                h.loc[today, c] = np.nan
        rt = races.race_date.astype(str).str[:10] == day
        real = races.loc[rt & races.track.isin(NANKAN), KEY + ['going']].copy()
        h.loc[today, 'going'] = None
        races.loc[rt, 'going'] = None
        F = feats51(day, h, races)
        real['race_date'], real['race_no'] = real.race_date.astype(str).str[:10], real.race_no.astype(int)
        F = F.merge(real, on=KEY, how='left')
        G = pd.concat([pick_going(g, gv) for gv, g in F.groupby(F.going.fillna(''), sort=False)])
        m = G.merge(R, on=Q5, how='left', suffixes=('', '_r'))
        res = {}
        for c in GOING_COLS:
            a, b = m[c].to_numpy(float), m[c + '_r'].to_numpy(float)
            ok = (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-6)
            res[c] = (int((~ok).sum()), round(float(np.isfinite(a).mean()), 3))
        print('馬場の照合', day, '頭', len(G), '馬場', dict(real.going.value_counts()), '列ごと(合わない頭・あり率)', res, flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'check':
        check(sys.argv[2:])
    elif sys.argv[1] == 'check_going':
        check_going(sys.argv[2:])
