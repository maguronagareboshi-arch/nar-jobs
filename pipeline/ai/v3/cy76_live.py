# -*- coding: utf-8 -*-
"""決め 76(南関 第28版 前日版): 調教の元の記録 88 列を、その日の出走表の追い切り欄から作る
(研究 nankan-ai-v3 src/f5_scripts/cyraw76_judge.py の build と同じ式・研究の列 cyraw76_feat.parquet と照合済み)。

- 元 = その日の出走表の追い切りの行(debut_live.card_src = nar_kb_works の頁を kb_flatten で平らにした行・研究の CSV と同じ列)。
  出走表の全部の馬(後で取消になった馬を含む)で作る。過去の追い切りは要らない(前走との差は使わない)。
- 番号の表(コース・脚色・位置)と時計の物差し(コース × 馬場 × 強さの系の平均とばらつき)は 2022 年までで固定した値
  = 暗号化した定数 v3-consts の cy76(公開のコードに数字を書かない)。
- 返り = Q4 + 88 列(float32)。追い切りの行の無い馬は行が無い(使う側で欠け = NaN)。
"""
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed

K = ['track', 'race_date', 'race_no', 'umaban']
RK = ['track', 'race_date', 'race_no']
T = ['t_1mile', 't_7f', 't_6f', 't_5f', 't_half', 't_3f', 't_1f']
PER = ['gap', 'fin', 'crs', 'hanro', 'bb', 't_6f', 't_5f', 't_half', 't_3f', 't_1f', 'ashi', 'cls', 'z3', 'z4', 'z5', 'z1', 'lap', 'pos']
CLS = {**{k: 0 for k in ('馬なり', '楽走', '末抑え', '直抑え')}, **{k: 1 for k in ('強め', '稍強め', '末強め', '直強め')},
       **{k: 2 for k in ('一杯', '末一杯', '直一杯', '稍一杯', '叩一杯')}}
BABA = {'良': 0, '稍': 1, '重': 2, '不': 3}
ZC = (('t_3f', 'z3'), ('t_half', 'z4'), ('t_5f', 'z5'), ('t_1f', 'z1'))
_C = None


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('cy76')
    return _C


def norm(s):
    if not isinstance(s, str):
        return np.nan
    s = re.sub(r'\s+', '', unicodedata.normalize('NFKC', s))
    return s if s else np.nan


def feats(W, C=None):
    """追い切りの行(研究の CSV の列)→ Q4 + 88 列。C = 定数(maps・z・nk・cols)。"""
    C = consts() if C is None else C
    cols = list(C['cols'])
    if W is None or not len(W):
        return pd.DataFrame(columns=K + cols)
    W = W.copy()
    for c in ('course', 'baba', 'ashiiro', 'position', 'kind', 'is_hanro', 'source') + tuple(T):
        if c not in W.columns:
            W[c] = np.nan
    W['race_date'] = W.race_date.astype(str).str[:10]
    W['work_date'] = W.work_date.astype(str).str[:10]
    W['race_no'] = pd.to_numeric(W.race_no, errors='coerce')
    W['umaban'] = pd.to_numeric(W.umaban, errors='coerce')
    W = W[W.race_no.notna() & W.umaban.notna() & W.work_date.str.match(r'^\d{4}-\d\d-\d\d$') & (W.work_date < W.race_date)].copy()
    if not len(W):
        return pd.DataFrame(columns=K + cols)
    W['race_no'] = W.race_no.astype(int)
    W['umaban'] = W.umaban.astype(int)
    for c in T:
        W[c] = pd.to_numeric(W[c], errors='coerce')
    W['cls'] = W.ashiiro.map(lambda s: CLS.get(norm(s), np.nan))
    W['bb'] = W.baba.map(lambda s: BABA.get(norm(s), np.nan))
    W['hanro'] = pd.to_numeric(W.is_hanro, errors='coerce')
    W['fin'] = (W.kind == 'final').astype(float)
    W['_crs'] = W.course.map(norm)
    W['_ashi'] = W.ashiiro.map(norm)
    W['_pos'] = W.position.map(norm)
    for nm in ('crs', 'ashi', 'pos'):
        mp = C['maps'][nm]
        m, top = mp['map'], int(mp['top'])
        W[nm] = W['_' + nm].map(lambda x, m=m, top=top: m.get(x, top) if isinstance(x, str) else np.nan).astype(float)
    # 研究と同じ: 同じ馬の同じ本(調教日・コース・3F・半マイル・種別)は 1 本(t は数にしてから比べる = 研究の CSV の数の書き方に依らない)
    W = W.drop_duplicates(K + ['work_date', 'course', 't_3f', 't_half', 'kind']).reset_index(drop=True)
    g = ['crs', 'bb', 'cls']
    for c, nm in ZC:
        st = pd.DataFrame(C['z'][nm])
        if not len(st):
            W[nm] = np.nan
            continue
        st = st[g + ['mean', 'std']].astype(float)
        W = W.merge(st.rename(columns={'mean': f'_m{nm}', 'std': f'_s{nm}'}), on=g, how='left')
        W[nm] = (W[c] - W[f'_m{nm}']) / W[f'_s{nm}']
        W = W.drop(columns=[f'_m{nm}', f'_s{nm}'])
    W['gap'] = (pd.to_datetime(W.race_date) - pd.to_datetime(W.work_date)).dt.days
    W['lap'] = W.t_half - W.t_3f
    W = W.sort_values(K + ['gap', 'fin'], ascending=[True] * 4 + [True, False], kind='mergesort')
    W['k'] = W.groupby(K).cumcount()
    nk = int(C['nk'])
    A = W[W.k < nk].pivot_table(index=K, columns='k', values=PER, aggfunc='first')
    A.columns = [f'cr{k + 1}_{c}' for c, k in A.columns]
    A = A.reset_index()
    H = W.groupby(K).agg(cr_n=('gap', 'size'), cr_n14=('gap', lambda x: (x <= 14).sum()), cr_n30=('gap', lambda x: (x <= 30).sum()),
                         cr_nstrong=('cls', lambda x: (x >= 1).sum()), cr_bestz3=('z3', 'min'), cr_bestz4=('z4', 'min')).reset_index()
    F = A.merge(H, on=K, how='outer')
    for c in cols:                      # 研究の表で全部空の列(その日に 4 本目が無い等)も形をそろえる
        if c not in F.columns and not c.endswith(('_rk', '_dz')):
            F[c] = np.nan
    for c in ('cr1_z3', 'cr1_z4', 'cr_bestz3', 'cr_bestz4', 'cr_n30'):
        F[c + '_rk'] = F.groupby(RK)[c].rank(pct=True)
        F[c + '_dz'] = F[c] - F.groupby(RK)[c].transform('mean')
    F = F.sort_values(K, kind='mergesort').reset_index(drop=True)
    F[cols] = F[cols].astype('float32')
    return F[K + cols]
