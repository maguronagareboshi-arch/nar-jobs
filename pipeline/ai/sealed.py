# -*- coding: utf-8 -*-
"""予想の学んだ定数・表を暗号化したリリースから読む(公開のコードに数を平文で置かない・2026-10-15)。

置き場 = 環境変数 V3_CONSTS(便は取り込みの段が v3_consts.tar.gz.enc を開けて置き、GITHUB_ENV で渡す)。
無ければ手元の C:/Users/kouki/nankan_ai/v3/consts_prod。中身 = consts.json(部品ごとの定数)+ 表のファイル。
無い・読めない時は例外で止める(黙って別の値で予想を出さない)。便は予想の前に `python sealed.py check` で確かめ、
落ちたら便を赤にする(主の模型が取れない日と同じ扱い)。
"""
import json
import os
import sys
from pathlib import Path

DIR = Path(os.environ.get('V3_CONSTS', 'C:/Users/kouki/nankan_ai/v3/consts_prod'))
FILES = ['consts.json', 'v3n_one_p5.json', 'k26_cal_table.json', 'dw_pat_dict.json.gz', 'dw_pat_fallback.json.gz',
         'v3n_f41_grp.parquet', 'v3n_f41_horse.parquet']   # 2026-10-17 決め 41 の固めた表(KDS から・父・生産者の群の合計と馬の台帳)
NEED = {'p1_follow': ['FORM', 'TAG'], 'danwa_marks': ['CONST'], 't14_bundle': ['M_GLOB', 'V0'],
        'v3n_p1': ['K', 'TAG'], 'v3n_e1': ['B_E1', 'S_NOKEN', 'BETA_NOKEN'], 'v3n_p1mix': ['AB', 'TAG'],
        'v3n_f41': ['NAMES', 'BETA', 'B', 'TAG', 'CUT'], 'f3_blend': ['W'],
        'si5_disp': ['TAG', 'DB_CUT', 'POS', 'CUT', 'ERR', 'MEAN', 'SAND'],
        'awase60': ['W1', 'W3', 'W1_PRE', 'W3_PRE', 'SD', 'TAG'],
        'v3n_rb61': ['W', 'WIN', 'LAM', 'gamma', 'nb', 'curve', 'TAG']}   # 2026-10-31 決め 61 他場の 2 本目の木の混ぜ・内外の有利(v3n_rb61)   # 2026-10-28 決め 60 併せ馬の相手の層(awase_live)   # 2026-10-27 サイトの指数の表示の直し(si5_store.disp)   # 2026-10-22 決め 49 F3 の混ぜの重み
_C = None


def path(name):
    p = DIR / name
    if not p.is_file():
        raise FileNotFoundError(f'暗号化の定数が無い: {p}(V3_CONSTS を確かめる)')
    return p


def get(part):
    """部品の定数の辞書(consts.json の part)"""
    global _C
    if _C is None:
        _C = json.loads(path('consts.json').read_text(encoding='utf-8'))
    return _C[part]


def check():
    for f in FILES:
        path(f)
    for part, keys in NEED.items():
        miss = [k for k in keys if k not in get(part)]
        if miss:
            raise KeyError(f'consts.json の {part} に {miss} が無い')
    miss = [v for v in ('mo4', 'di4') if v not in get('v3n_p1')['K']]   # 決め 61 の勝つ率の直しの k
    if miss:
        raise KeyError(f'consts.json の v3n_p1.K に {miss} が無い')
    for f in ('v3n_one_p5.json', 'k26_cal_table.json'):
        json.loads(path(f).read_text(encoding='utf-8'))
    return f'定数 OK: {DIR}({len(FILES)} 個)'


if __name__ == '__main__' and sys.argv[1:] == ['check']:
    print(check())
