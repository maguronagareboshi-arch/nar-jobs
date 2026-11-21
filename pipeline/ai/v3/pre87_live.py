# -*- coding: utf-8 -*-
"""前日版の並び読みを 3 案まとめ + 調教の挟みに替える(南関 AI v3 決め 87・2026-11-21 ユーザー例外採用・研究 nankan-ai-v3 src/f5_scripts/seqlab.py 案 b87・
本番の学び seqpre87_prod_fit.py)。南関 第32版 前日版 = 第31版 前日版の「前日の並び読み u_P(種 1951〜1953・決め 63 の材料 DAY_seq2.npz)」を、
決め 82 の 3 案まとめの並び(DAY_b82.npz = 調教の挟み + 併せ馬 + ① の 21 列)を前日の形で学んだ重み(種 1954〜1956)で読んだ u_P に替える。

読み方・足し方は決め 63(seqpre_live)と同じ(当日の 8 列は重みの meta の day_cols のとおり空・p1_k 0.2)。替えるのは重みと材料だけ:
  重み = V3_PRE87(リリース v3-pre87 を開いた所)の seqpre_model.npz・seqpre_prod.json
  材料 = 前日の便の seq2_live.prep が書いた OUT/DAY_b82.npz(見張りに届かず書かれなかった日は替えない = 第31版 前日版のまま)
後の段(前日の一本の木の鎖 preday74・直前版の土台 dayonpre77 の D77:up)は前日版の表の sq_u を読むので、そのまま新しい u_P を使う。
替えたレースには表に sq87 = 1 を付ける(行の meta.sq87・版の字・直前版の土台の D77:v = 32 の元)。
"""
import os
from pathlib import Path

ASSET = Path(os.environ.get('V3_PRE87', 'C:/Users/kouki/nankan_ai/v3_c67/c1p/v3/seqpre87_prod/rel'))   # リリース v3-pre87 を開いた所
_C = None


def log0(*a):
    print('[pre87]', *a, flush=True)


def consts():
    """暗号化したリリース v3-consts の consts.json の pre87(ON・TAG)。"""
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('pre87')
    return _C


def is_on(day):
    """その日(レースの日)が決め 87 の ON 以降か(定数が読めなければ例外)。"""
    return str(day) >= str(consts().get('ON') or '9999-12-31')


def tag():
    return consts()['TAG']


def load(day, out, log=log0):
    """ON の日で重みと DAY_b82.npz があれば seqpre_live と同じ形の S(+ 'pre87': True)。無ければ None(= 決め 63 の今の重みで読む)。"""
    import seqpre_live
    if not is_on(day):
        log('ON の前(前日の並び読みは今のまま)', consts().get('ON'))
        return None
    npz = Path(out) / f'{day}_b82.npz'
    if not npz.exists():
        log('3 案まとめの並びの材料なし(前日の並び読みは今のまま = 第31版 前日版)', npz.name)
        return None
    S = seqpre_live.load(ASSET, npz)
    if S is None:
        log('重みなし(前日の並び読みは今のまま = 第31版 前日版)', ASSET)
        return None
    m = S['meta']
    assert list(m['seeds']) == [1954, 1955, 1956], m['seeds']
    S['pre87'] = True
    log('重み', ASSET.name, '種', m['seeds'], '形', m['H'], m['fh'], m['fc'], '・材料', npz.name, S['n'], '頭')
    return S


def mark_csv(csv_path, log=log0):
    """前日の並び読みを足したレース(sq_u のあるレース)に sq87 = 1。→ 印を付けたレース数"""
    import pandas as pd
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    k = ['track', 'race_date', 'race_no']
    has = x.groupby(k, sort=False).sq_u.transform(lambda s: s.notna().any()) if 'sq_u' in x.columns else pd.Series(False, index=x.index)
    x['sq87'] = has.astype(int)
    x.to_csv(csv_path, index=False, encoding='utf-8-sig')
    n = int(x[has].drop_duplicates(k).shape[0])
    log('前日の並び読みを替えたレース', n)
    return n
