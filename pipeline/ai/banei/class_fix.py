# -*- coding: utf-8 -*-
"""ばんえいの級の読みの直し(2026-10-28 ユーザー決定・v3 の src/banei/class_fix_pre.py の parse_class_fixed の写し・計算は同じ)。
「…A1-2」「…B3混合」など名の末尾の級を先に読む・「ＯＰＥＮ」だけで OP にしない。feat_v1.parse_class をこれに差し替えて使う。"""
import re
import unicodedata

import numpy as np

import feat_v1 as f1

_orig = f1.parse_class


def parse_class_fixed(name, cond):
    r = _orig(name, cond)
    nm = unicodedata.normalize('NFKC', name or '').replace(' ', '').replace('\u3000', '')
    young = bool(r['cls_young'])
    tok, kumi = r['cls_tok'], r['kumi']
    tail = re.search(r'([A-D][1-4]?)(?:-(\d+))?(混合)?$', nm)
    op = ('オープン' in nm) or bool(re.search(r'(?<![A-Za-z])OP(?![A-Za-z])', nm))
    if op and not tail:
        tok = 'OP'
    elif op and 'オープン' in nm and '混合' in nm:
        tok = 'OP'                                   # 「オープン・A1 混合」は今のまま
    elif tail and tok not in ('SEN', 'NEW', 'MI') and not ('未受賞' in nm or re.search(r'受賞-\d', nm)):
        tok = tail.group(1); kumi = float(tail.group(2)) if tail.group(2) else np.nan
    elif tok == 'OP' and not op:                     # 「ＯＰＥＮ」だけで OP になっていた行
        tok = 'X'; kumi = np.nan
    if young:
        lv = {'OP': 5, 'SEN': 5, 'A': 4, 'B': 3, 'C': 2, 'D': 1, 'JU': 1.5, 'MI': 0.5, 'NEW': 0}.get(tok[0] if tok[0] in 'ABCD' else tok, np.nan)
    else:
        lv = {'OP': 12, 'SEN': 11, 'A1': 10, 'A2': 9, 'A': 9.5, 'B1': 8, 'B2': 7, 'B3': 6, 'B4': 5, 'B': 6.5,
              'C1': 4, 'C2': 3, 'C': 3.5, 'D': 2, 'D1': 2}.get(tok, np.nan)
    r.update(cls_tok=tok, cls_level=lv, kumi=kumi, cls_key=('Y' + r['cls_age'] if young else 'O') + tok)
    stakes = bool(re.search(r'第\d+回', nm)) and tok in ('OP', 'SEN')
    r['grade'] = 2 if stakes else r['grade'] if r['grade'] != 2 else 1
    return r
