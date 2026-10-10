# -*- coding: utf-8 -*-
"""同じ略称の 2014〜2021 の走りを KDSCOPE SE の調教師コードで本人判定し、ページ本人の走りだけ keep CSV に出す。

10/10 直し(loose-ends #20): 本人は「氏名」でなく「KD の調教師コード」で決める。
  同姓同名(例 加藤和宏= 金沢 NC と JRA CH にコードが 2 つ)を名前で寄せると別人の走りが入るため。
  同じ氏名のコードが 2 つ以上なら、KD 台帳の生年月日が名簿の生年月日と同じコードだけを本人のコードとする
  (NC には JRA の調教師も入っているので NC/CH では分けられない)。
手元で py -3.12 で 1 回(KDSCOPE と kd_se.parquet が要る)。本番は anon キーで読むだけ。
元: nar-site/research/owner-breeder/same_abbr_keep.py(10/2)。
"""
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict


def nrm(s):
    s = unicodedata.normalize('NFKC', str(s))
    return re.sub(r'\s+', '', s)


def owner_codes(owner_name, owner_birth, codes_by_name, birth_of):
    """ページ本人のコード集合。同じ氏名のコードが 1 つならそれ。2 つ以上(同姓同名)なら
    KD 台帳の生年月日が名簿(nar_persons.birth)と同じコードだけ(合わなければ空= 本人コード無し)。"""
    if not owner_name:
        return set()
    cs = set(codes_by_name.get(nrm(owner_name), ()))
    if len(cs) <= 1:
        return cs
    b = (owner_birth or '').replace('-', '')
    return {c for c in cs if b and birth_of.get(c) == b}


def judge(code, codes, has_owner):
    """1 走の判定。code= KD の調教師コード(None= KD に無い)。"""
    if code is None:
        return 'KD無し'
    if not has_owner:
        return '本人なし'
    if not codes:
        return '本人コード無し'
    return 'keep' if code in codes else '別人'


def main():
    import numpy as np
    import pandas as pd
    import requests

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, '..', 'ai', 'v3'))
    from kd_read import num, sstr  # noqa

    KD = 'C:/KDSCOPE/Data/'
    V3 = 'C:/Users/kouki/nankan_ai/v3/'
    OUTMD = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, 'same_abbr_keep.md')
    JYO = {30: '門別', 31: '北見', 32: '岩見沢', 33: '帯広', 34: '旭川', 35: '盛岡', 36: '水沢', 37: '上山', 38: '三条',
           39: '足利', 40: '宇都宮', 41: '高崎', 42: '浦和', 43: '船橋', 44: '大井', 45: '川崎', 46: '金沢', 47: '笠松',
           48: '名古屋', 49: '紀三井寺', 50: '園田', 51: '姫路', 52: '益田', 53: '福山', 54: '高知', 55: '佐賀', 56: '荒尾',
           57: '中津', 58: '札幌(地)', 59: '函館(地)', 60: '新潟(地)', 61: '中京(地)', 83: '帯広(ば)'}

    def recs(path, L, head):
        with open(path, 'rb') as f:
            buf = f.read()
        k = len(buf) // L
        a = np.frombuffer(buf[:k * L], dtype=np.uint8).reshape(-1, L)
        ok = (a[:, 0] == ord(head[0])) & (a[:, 1] == ord(head[1]))
        return a[ok]

    def master(path, L, head, ab):
        a = recs(KD + path, L, head)
        df = pd.DataFrame({'make': num(a, 3, 8), 'code': sstr(a, 11, 5), 'name': sstr(a, 41, 34), 'birth': sstr(a, 33, 8)})
        return df.sort_values('make').drop_duplicates('code', keep='last')

    nc = master('NC/NC.DAT', 5098, 'NC', 105)
    ch = master('CH/CH.DAT', 3862, 'CH', 105)
    code_by = defaultdict(set)
    for c, n in list(zip(ch.code, ch.name)) + list(zip(nc.code, nc.name)):
        code_by[nrm(n)].add(c)
    birth_of = dict(zip(ch.code, ch.birth))
    birth_of.update(dict(zip(nc.code, nc.birth)))
    name_of = dict(zip(ch.code, ch.name.map(nrm)))
    name_of.update(dict(zip(nc.code, nc.name.map(nrm))))
    collide = len(set(nc.code) & set(ch.code))

    se = pd.read_parquet(V3 + 'kd_se.parquet', columns=['year', 'md', 'jyo', 'race', 'umaban', 'name', 'trainer_cd'])
    se = se[(se.jyo >= 30) & (se.jyo <= 89) & (se.year >= 2014) & (se.year <= 2021)].dropna(subset=['md', 'race', 'umaban'])
    se = se.drop_duplicates(['year', 'md', 'jyo', 'race', 'umaban'])
    se['date'] = [f'{int(y):04d}-{int(m) // 100:02d}-{int(m) % 100:02d}' for y, m in zip(se.year, se.md)]
    se['trk'] = se.jyo.astype(int).map(lambda j: re.sub(r'\(.*\)', '', JYO.get(j, str(j))))
    se['race'] = se.race.astype(int)
    se['umaban'] = se.umaban.astype(int)
    se['hn'] = se['name'].map(nrm)
    se['cd'] = se.trainer_cd.map(lambda c: str(c).strip() if c is not None and str(c).strip() else None)
    k1 = {(d, t, r, u): c for d, t, r, u, c in zip(se.date, se.trk, se.race, se.umaban, se.cd) if c}
    k2, k3 = defaultdict(list), defaultdict(list)
    for d, r, u, h, c in zip(se.date, se.race, se.umaban, se.hn, se.cd):
        if c:
            k2[(d, r, u, h)].append(c)
            k3[(d, h)].append(c)

    src = open(r'C:/Users/kouki/AppData/Local/Temp/viewer-master/js/data.js', encoding='utf-8').read()
    U = re.search(r"NAR_URL = '([^']+)'", src).group(1)
    K = re.search(r"NAR_KEY = '([^']+)'", src).group(1)
    H = {'apikey': K, 'Authorization': 'Bearer ' + K}
    S = requests.Session()

    def get_all(table, params, order):
        out, off = [], 0
        while True:
            p = dict(params, order=order, limit='1000', offset=str(off))
            r = S.get(f'{U}/rest/v1/{table}', params=p, headers=H, timeout=60)
            r.raise_for_status()
            js = r.json()
            out += js
            if len(js) < 1000:
                return out
            off += 1000

    abbrs = pd.read_csv(os.path.join(here, 'trainer_same_abbr_exclude.csv'), encoding='utf-8-sig', dtype=str)['abbr'].map(nrm).tolist()
    pers = get_all('nar_persons', {'select': 'name_full,name_short,area,license_no,birth', 'kind': 'eq.trainer'}, 'license_no')
    by_short = defaultdict(list)
    for p in pers:
        by_short[nrm(p['name_short'] or '')].append(p)

    runs = []
    for a in abbrs:
        runs += get_all('nar_runs', {'select': 'track,race_date,race_no,runner_number,horse_name,trainer',
                                     'trainer': f'eq.{a}', 'and': '(race_date.gte.2014-01-01,race_date.lte.2021-12-31)'},
                        'track,race_date,race_no,runner_number')
    runs = pd.DataFrame(runs)
    runs['ab'] = runs.trainer.map(nrm)

    owner, oarea, onote, ocodes, obirth = {}, {}, {}, {}, {}
    for a in abbrs:
        ps = by_short.get(a, [])
        loc = [p for p in ps if (p['area'] or '') != 'JRA']
        if len(ps) == 1:
            owner[a], oarea[a], onote[a], obirth[a] = nrm(ps[0]['name_full']), ps[0]['area'], ps[0]['area'], ps[0]['birth']
        elif len(loc) == 1:
            owner[a], oarea[a], obirth[a] = nrm(loc[0]['name_full']), loc[0]['area'], loc[0]['birth']
            onote[a] = loc[0]['area'] + f'(他 {len(ps) - 1} 人 JRA)'
        elif len(loc) > 1:
            owner[a] = None; onote[a] = '地方が複数: ' + '/'.join(nrm(p['name_full']) + '(' + p['area'] + ')' for p in loc)
        elif len(ps) == 0:
            owner[a] = None; onote[a] = '名簿に無し'
        else:
            owner[a] = None; onote[a] = '要判断: JRA だけ複数: ' + '/'.join(nrm(p['name_full']) for p in ps)
        ocodes[a] = owner_codes(owner[a], obirth.get(a), code_by, birth_of) if owner[a] else set()

    # 同じ氏名のコードが 2 つ以上ある略称(名前で寄せると混ざる形)
    same_name = {a: sorted(code_by[owner[a]]) for a in abbrs if owner[a] and len(code_by.get(owner[a], ())) > 1}

    res, kdc, how = [], [], Counter()
    for t, d, r, u, h, a in zip(runs.track, runs.race_date, runs.race_no, runs.runner_number, runs.horse_name, runs.ab):
        c = k1.get((d, re.sub(r'\(.*\)', '', t), int(r), int(u)))
        if c is not None:
            how['場R馬番'] += 1
        else:
            s = set(k2.get((d, int(r), int(u), nrm(h or '')), []))
            if len(s) == 1:
                c = s.pop(); how['R馬番+馬名'] += 1
            else:
                s = set(k3.get((d, nrm(h or '')), []))
                if len(s) == 1:
                    c = s.pop(); how['馬名'] += 1
        kdc.append(c or '')
        res.append(judge(c, ocodes.get(a, set()), owner.get(a) is not None))
    runs['kdcd'] = kdc
    runs['res'] = res

    key = ['track', 'race_date', 'race_no', 'runner_number']
    outp = os.path.join(here, 'trainer_same_abbr_keep.csv')
    old = pd.read_csv(outp, dtype=str)
    keep = runs[runs.res == 'keep'][key].drop_duplicates().sort_values(key)
    keep.to_csv(outp, index=False, encoding='utf-8', lineterminator='\n')

    # 前後差(略称ごと)
    rk = runs[key].astype(str).agg('|'.join, axis=1)
    oldk = set(old[key].astype(str).agg('|'.join, axis=1))
    runs['was'] = rk.isin(oldk)
    runs['now'] = runs.res == 'keep'
    out_ = runs[runs.was & ~runs.now]
    in_ = runs[~runs.was & runs.now]

    t = pd.crosstab(runs.ab, runs.res).reindex(abbrs).fillna(0).astype(int)
    for c in ['keep', '別人', 'KD無し', '本人なし', '本人コード無し']:
        if c not in t.columns:
            t[c] = 0
    L = ['# 同じ略称の走りを KDSCOPE の調教師コードで本人判定(2014〜2021・10/10 コード版)', '',
         f'- 対象 {len(runs)} 走・keep {int(t["keep"].sum())}・別人 {int(t["別人"].sum())}・KD無し {int(t["KD無し"].sum())}'
         f'・本人なし {int(t["本人なし"].sum())}・本人コード無し {int(t["本人コード無し"].sum())}',
         f'- 前回 keep {len(old)} 行 → 今回 {len(keep)} 行(外れた {len(out_)} 走・入った {len(in_)} 走)',
         f'- NC と CH でコードが重なる数 {collide}',
         f'- 突き合わせの方法: ' + '・'.join(f'{k} {v}' for k, v in how.items()), '',
         '## 同じ氏名のコードが 2 つ以上ある略称(本人の台帳のコードだけ keep)', '',
         '| 略称 | 本人 | 所属 | 名簿の生年月日 | 本人のコード | 同名の全コード(KD 生年月日) |', '|---|---|---|---|---|']
    for a, cs in same_name.items():
        L.append(f'| {a} | {owner[a]} | {oarea.get(a)} | {obirth.get(a)} | {"/".join(sorted(ocodes[a]))} '
                 f'| {"/".join(c + "(" + birth_of.get(c, "") + ")" for c in cs)} |')
    L += ['', '## 前後差(略称ごと)', '', '| 略称 | 外れた走 | 入った走 | 外れた走の場 | 外れた走の KD コード |', '|---|---|---|---|---|']
    for a in abbrs:
        o, i = out_[out_.ab == a], in_[in_.ab == a]
        if len(o) or len(i):
            L.append(f'| {a} | {len(o)} | {len(i)} | {"/".join(f"{k}{v}" for k, v in o.track.value_counts().items())} '
                     f'| {"/".join(f"{k}:{name_of.get(k, "")}" for k in sorted(set(o.kdcd)))} |')
    L += ['', '| 略称 | 対象走数 | keep | 別人 | KD無し | 本人なし | 本人コード無し | ページの本人 | 所属・備考 |',
          '|---|---|---|---|---|---|---|---|---|']
    for a in abbrs:
        row = t.loc[a] if a in t.index else None
        g = (lambda c: int(row[c])) if row is not None else (lambda c: 0)
        tot = int(row.sum()) if row is not None else 0
        L.append(f'| {a} | {tot} | {g("keep")} | {g("別人")} | {g("KD無し")} | {g("本人なし")} | {g("本人コード無し")} '
                 f'| {owner.get(a) or "なし"} | {onote.get(a)} |')
    open(OUTMD, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L[:7]))


if __name__ == '__main__':
    main()
