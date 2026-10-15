# -*- coding: utf-8 -*-
"""他場版 v3n の率の直し(A = E1)と能力検査の時計(B = 能検)の本番の部品(2026-10-13・v3 の out/v3n_ab.md で 3 個とも通った)。

決め書 = v3 の out/v3n_ab_plan.md 第 2 版「作り」「通ったら」。研究の台本 = v3 の src/kochi/k43_ab.py(e1・noken・renorm)と
src/kochi/k39c_noken_sql.sql(能検の窓とつなぎ)。定数は選びの期間(2024-09〜25-08)だけで決めた値。

apply(p3, z): 1 レースの 3 着内の率(並び読みを足した後・取消の割り直しの後)→ 直した率。
  1. A: p' = σ(b·logit p + c_R)(c_R は Σp' = min(3, 頭数) になる数・二分法 60 回)
  2. B: 能検の z のある馬が 1 頭でもいれば p'' = σ(logit p' + β·z + c'_R)(c'_R で再び Σ = min(3, 頭数))
  3. [0.001, 0.999] で切る(今と同じ)。
  取消の後の頭数が 4 未満のレースはかけない(研究で測っていない)。E1 の前の率にだけかける(2 度かけると傾きが b² になる)。
noken_z(...): 初出走の馬の能検の z(馬番 → z・無い馬は入れない)。nar_meta の *_noken から k39c と同じ作りで出す。
"""
import datetime as dt
import re
from decimal import Decimal

import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed
import sealed  # noqa: E402  定数は暗号化したリリース(公開のコードに置かない)

_S = sealed.get('v3n_e1')
B_E1 = _S['B_E1']              # A の傾き b(選び全体で対数損失が最小)
S_NOKEN = _S['S_NOKEN']        # 選びの初出走の馬の秒の差の標準偏差 s(秒)
BETA_NOKEN = _S['BETA_NOKEN']  # 能検の z の係数 β(E1 の後の logit を固定の項にしたロジスティック)
EPS = 1e-3
N_MIN = 4             # 取消の後の頭数がこれ未満のレースはかけない
FORM_TAG = '+e1+noken'
NOKEN_KEYS = ('monbetsu_noken', 'iwate_noken', 'kanazawa_noken', 'kasamatsu_noken', 'nagoya_noken', 'hyogo_noken',
              'kochi_noken', 'saga_noken')


def _clip(p):
    return np.clip(np.asarray(p, float), EPS, 1 - EPS)


def _lg(p):
    p = _clip(p)
    return np.log(p / (1 - p))


def _sig(z):
    return 1 / (1 + np.exp(-z))


def _renorm(z):
    """Σ σ(z + c) = min(3, 頭数) になる c(研究の renorm と同じ二分法・1 レース分)。"""
    tgt = float(min(3, len(z)))
    lo, hi = -15.0, 15.0
    for _ in range(60):
        c = (lo + hi) / 2
        if _sig(z + c).sum() > tgt:
            hi = c
        else:
            lo = c
    return _sig(z + (lo + hi) / 2)


def apply(p3, z=None):
    """1 レースの 3 着内の率の配列 → (直した率の配列 [0.001, 0.999]、かけたか)。z = 能検の z の配列(無い馬は 0)。"""
    p3 = np.asarray(p3, float)
    if len(p3) < N_MIN:
        return _clip(p3), False
    pE = _renorm(B_E1 * _lg(p3))
    if z is not None:
        z = np.nan_to_num(np.asarray(z, float))
        if np.any(z != 0):
            pE = _renorm(_lg(pE) + BETA_NOKEN * z)
    return _clip(pE), True


# ---------------- 能検の z(k39c_noken_sql.sql と同じ作り) ----------------
_T1 = re.compile(r'^[0-9]{1,2}[.:][0-9]{2}([.][0-9])?$')
_T2 = re.compile(r'^[0-9]{2}[.][0-9]$')


def _sec(t):
    """'1:02.3' / '1.02.3' / '62.3' → 秒(SQL と同じ読み・numeric の値を float に)。読めなければ None。"""
    t = str(t or '')
    if not (_T1.match(t) or _T2.match(t)):
        return None
    a = t.replace(':', '.').split('.')
    if len(a) == 3:
        v = Decimal(int(a[0]) * 60 + int(a[1])) + Decimal(int(a[2])) / Decimal(10)
    else:
        v = Decimal(int(a[0])) + Decimal(int(a[1])) / Decimal(10)
    return float(v)


def noken_rows(meta_rows):
    """nar_meta の行([{key, value}])→ 時計の読める能検の行 [(地区, 日, 距離, 馬名, 秒)]。合否は見ない。"""
    out = []
    for m in meta_rows:
        for dd in ((m.get('value') or {}).get('days') or []):
            try:
                nd = dt.date.fromisoformat(str(dd.get('date'))[:10])
            except ValueError:
                continue
            for rc in (dd.get('races') or []):
                dist = str(rc.get('dist') if rc.get('dist') is not None else '')
                for x in (rc.get('rows') or []):
                    s = _sec(x.get('time'))
                    if s is None:
                        continue
                    nm = str(x.get('name') or '').lstrip('×○□*').replace(' ', '')
                    out.append((m.get('key'), nd, dist, nm, s))
    return out


def _median(v):
    """percentile_cont(0.5)(Postgres と同じ補間)。"""
    v = sorted(v)
    pos = 0.5 * (len(v) - 1)
    lo = int(np.floor(pos))
    hi = int(np.ceil(pos))
    return v[lo] + (pos - lo) * (v[hi] - v[lo])


def noken_z(rows, debuts, day):
    """rows = noken_rows の出力・debuts = {馬番: 馬名}(初出走の馬だけ)・day = 'YYYY-MM-DD'(初出走の日)→ {馬番: z}。
    つなぐ回 = 馬名が同じで day より前・365 日以内の一番新しい回。真ん中 = 同じ地区・同じ距離・その回の日の前 30 日〜その日
    (自分を含む)の中央値・3 件未満は z なし。秒の差は 0.1 秒に丸める(研究の写しと同じ)。z = clip(秒の差 / s, −3, 3)。"""
    if not rows or not debuts:
        return {}
    d0 = dt.date.fromisoformat(day)
    byname = {}
    for r in rows:
        byname.setdefault(r[3], []).append(r)
    out = {}
    for num, nm in debuts.items():
        c = [r for r in byname.get(nm, []) if r[1] < d0 and r[1] >= d0 - dt.timedelta(days=365)]
        if not c:
            continue
        k, nd, dist, _, sec = max(c, key=lambda r: r[1])
        w = [r[4] for r in rows if r[0] == k and r[2] == dist and nd - dt.timedelta(days=30) <= r[1] <= nd]
        if len(w) < 3:
            continue
        tz = min(999, max(1, int(np.rint((sec - _median(w)) * 10)) + 500))
        out[int(num)] = float(np.clip((tz - 500) / 10 / S_NOKEN, -3, 3))
    return out


def fetch_rows(sb):
    """nar-official の nar_meta から能検の行を読む(sb = k0_dl.sb)。"""
    keys = ','.join(NOKEN_KEYS)
    return noken_rows(sb.get(f'/rest/v1/nar_meta?select=key,value&key=in.({keys})'))
