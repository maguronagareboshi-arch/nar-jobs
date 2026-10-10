# -*- coding: utf-8 -*-
"""高知版 9 = 公式(keiba.go.jp の CSV → nar-official の nar_runs・nar_races・nar_run_facts・nar_horse_profiles)と
競馬ブックの中央の走り(nar_jra_runs・nar_jra_horses)だけで、KDSCOPE と同じ形の元を作る(2026-10-10)。

  py -3.12 -X utf8 src/kochi/k9_official.py build    → C:/Users/kouki/nankan_ai/v3/kochi_off/(kd_se・kd_ra・kd_horse・ra_text・ra_all)
  py -3.12 -X utf8 src/kochi/k9_official.py compare  → 高知の走りを KDSCOPE と 1 頭ずつ照らす(out/kochi_official.md に書く数字)
  py -3.12 -X utf8 src/kochi/k9_official.py feat     → k1・k4・k8 をそのまま公式の元で回す(kochi_off/kochi/ に feat2・extra・si_n)

■ 決め
  - 元はダウンロード済みの C:/Users/kouki/nankan_ai/v3/official/*.parquet(dl.py が nar-official の公開 REST から落とす)。KDSCOPE は使わない。
  - 馬 = 馬名 + 生まれ年(公式の生年月日は 2022-11 から・それより前は 年 − 年齢)。番号は作り番号(9 億台)。
  - 騎手・調教師 = 公式の名前(4 文字の略)をそのまま番号の代わりに。父・母・母父・馬主・生産者 = 名前。
  - 中央の走り = 競馬ブック(nar_jra_horses の 馬名 + 生まれ年でつなぐ)。頭数は field_size。中央の全馬は無いので
    コースの物差しが作れない = 中央の走りのタイム・上がりは使わない(SI なし)。1 着賞金は KDSCOPE の 2019〜の条件ごとの中央値。
  - 取消・除外 = ijo 1・3、中止 = 4(KDSCOPE と同じ)。着差の時計 = 勝ち馬との差(勝ち馬は 2 着との差を負で)。
"""
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

O = 'C:/Users/kouki/nankan_ai/v3/official/'
ALT = Path('C:/Users/kouki/nankan_ai/v3/kochi_off')
JYO = {'門別': 30, '盛岡': 35, '水沢': 36, '浦和': 42, '船橋': 43, '大井': 44, '川崎': 45, '金沢': 46, '笠松': 47,
       '名古屋': 48, '園田': 50, '姫路': 51, '高知': 54, '佐賀': 55, '帯広ば': 83}
JRA = {'札幌': 1, '函館': 2, '福島': 3, '新潟': 4, '東京': 5, '中山': 6, '中京': 7, '京都': 8, '阪神': 9, '小倉': 10}
BABA = {'良': 1, '稍重': 2, '重': 3, '不良': 4}
TENKO = {'晴': 1, '曇': 2, '雨': 3, '小雨': 4, '雪': 5, '小雪': 6}
SEX = {'牡': 1, '牝': 2, 'セン': 3, 'セ': 3}
IJO = {'取消': 1, '出走取消': 1, '枠順発表前取消': 1, '除外': 3, '競走除外': 3, '枠順発表前除外': 3, '中止': 4, '競走中止': 4, '落馬': 4}
JRA_PRIZE = {701: 70000, 703: 51000, 5: 76000, 10: 150000, 16: 182000, 999: 260000}  # KDSCOPE kd_ra 2019〜 の中央値(100 円)
CLS_RE = re.compile(r'(?<![A-Za-z])[A-E](?:\d|-|[一二三四五六七八九十イロハ]|級|以下|混合|$|[A-E]\d?(?:混合|[A-E]|\d|$))')
AGE_RE = re.compile(r'\d歳(?!以上)')


def nf(s):
    return unicodedata.normalize('NFKC', str(s or '')).replace(' ', '').replace('\u3000', '')


def split_name(name):
    """公式のレース名 → (クラス, 名前)。KDSCOPE の RA のクラス名に寄せる(照らし合わせで決めた):
    格の文字(C3-8・Bイ・AB混合・B級以下)を先に探し、すぐ前に「3歳」があればそこから。格が無ければ「3歳」(以上は除く)から。
    どちらも無ければクラスなし(「3歳以上」だけの重賞などは KDSCOPE もクラス名が空)。"""
    s = re.sub(r'^第\d+回', '', nf(name))
    h = len(s) // 2
    if len(s) % 2 == 0 and h and s[:h] == s[h:]:
        s = s[:h]  # 公式は「C3-15 C3 -15」「3歳-7 3歳-7」のように同じ名を 2 回並べることがある
    m = CLS_RE.search(s)
    if m:
        st = m.start() - 2 if m.start() >= 2 and re.fullmatch(r'\d歳', s[m.start() - 2:m.start()]) else m.start()
        c, n = s[st:], s[:st]
        return c, (n or (c if '混合' in c else ''))  # KDSCOPE は「AB混合」をレース名にも持つ
    m = AGE_RE.search(s)
    if m:
        c, n = s[m.start():], s[:m.start()]
        return c, (n or (c if '新馬' in c else ''))
    return '', s


def jra_ccmin(name):
    s = nf(name)
    if '新馬' in s:
        return 701
    if '未勝利' in s:
        return 703
    if '1勝' in s or '500万' in s:
        return 5
    if '2勝' in s or '1000万' in s:
        return 10
    if '3勝' in s or '1600万' in s:
        return 16
    return 999


def tdiff_str(t, grp):
    w = grp.transform('min')
    second = grp.transform(lambda x: x.nsmallest(2).iloc[-1] if x.notna().sum() >= 2 else np.nan)
    v = np.where(t == w, -(second - w), t - w)
    v = np.round(v * 10)
    return pd.Series([f"{'+' if x >= 0 else '-'}{int(abs(x)):03d}" if x == x else '' for x in v], index=t.index)


def build():
    ALT.mkdir(exist_ok=True)
    (ALT / 'kochi').mkdir(exist_ok=True)
    ru = pd.read_parquet(O + 'runs.parquet')
    ra = pd.read_parquet(O + 'races.parquet')
    fa = pd.read_parquet(O + 'facts.parquet', columns=['track', 'race_date', 'race_no', 'umaban', 'c1', 'c4', 'win_odds_close'])
    pr = pd.read_parquet(O + 'profiles.parquet')
    ru = ru[ru.track.isin(JYO)].copy()
    ru['date'] = pd.to_datetime(ru.race_date)
    by = pd.to_datetime(ru.birth_date, errors='coerce').dt.year
    ru['by'] = by.fillna(ru.date.dt.year - ru.age).astype('Int64')
    ru['hkey'] = ru.horse_name.str.replace(r'\s+', '', regex=True) + '|' + ru.by.astype(str)
    # --- 中央(競馬ブック)
    jh = pd.read_parquet(O + 'jrah.parquet', columns=['kb_horse_id', 'horse_name', 'birth_year'])
    jr = pd.read_parquet(O + 'jra.parquet')
    jh['hkey'] = jh.horse_name.str.replace(r'\s+', '', regex=True) + '|' + jh.birth_year.astype('Int64').astype(str)
    jr = jr.merge(jh[['kb_horse_id', 'hkey']], on='kb_horse_id', how='inner')
    jr = jr[jr.place.isin(JRA)].copy()
    keys = pd.Index(sorted(set(ru.hkey) | set(jr.hkey)))
    kid = pd.Series(np.arange(len(keys), dtype=np.int64) + 900_000_001, index=keys)
    ru['ketto'] = ru.hkey.map(kid)
    jr['ketto'] = jr.hkey.map(kid)
    ru = ru.merge(fa.rename(columns={'umaban': 'runner_number'}), on=['track', 'race_date', 'race_no', 'runner_number'], how='left')
    ijo = ru.finish_note.map(IJO).fillna(0)
    rk = [ru.race_date, ru.track, ru.race_no]
    ru['tdiff'] = tdiff_str(ru.time_sec.where(ijo == 0), ru.time_sec.where(ijo == 0).groupby(rk))
    se = pd.DataFrame({
        'kubun': '7', 'year': ru.date.dt.year.astype(float), 'md': (ru.date.dt.month * 100 + ru.date.dt.day).astype(float),
        'jyo': ru.track.map(JYO).astype(float), 'race': ru.race_no.astype(float), 'waku': ru.gate.astype(float),
        'umaban': ru.runner_number.astype(float), 'ketto': ru.ketto.astype(float), 'sex': ru.sex.map(SEX).astype(float),
        'age': ru.age.astype(float), 'trainer_cd': ru.trainer, 'kinryo': ru.carried_weight.astype(float),
        'jockey_cd': ru.jockey, 'ijo': ijo.astype(float), 'finish': ru.finish.fillna(0).astype(float),
        'c1': ru.c1.astype(float), 'c4': ru.c4.astype(float), 'l3f': ru.last3f.astype(float),
        'time_sec': ru.time_sec.astype(float), 'tdiff': ru.tdiff, 'odds': ru.win_odds_close.astype(float),
        'pop': ru.popularity.astype(float), 'date': ru.date, 'fsize': np.nan})
    jr['date'] = pd.to_datetime(jr.race_date)
    jijo = jr.finish_note.map(IJO).fillna(0)
    pas = jr.passing.fillna('').str.split('-')
    c1 = pd.to_numeric(pas.str[0], errors='coerce')
    c4 = pd.to_numeric(pas.str[-1], errors='coerce')
    jr['umaban'] = jr.groupby(['date', 'place', 'race_no']).cumcount() + 101  # 中央の馬番は無い = 101〜 の作り番号
    sj = pd.DataFrame({
        'kubun': '7', 'year': jr.date.dt.year.astype(float), 'md': (jr.date.dt.month * 100 + jr.date.dt.day).astype(float),
        'jyo': jr.place.map(JRA).astype(float), 'race': jr.race_no.astype(float), 'waku': np.nan, 'umaban': jr.umaban.astype(float),
        'ketto': jr.ketto.astype(float), 'sex': np.nan, 'age': np.nan, 'trainer_cd': None, 'kinryo': jr.carried_weight.astype(float),
        'jockey_cd': 'JRA_' + jr.jockey.fillna(''), 'ijo': jijo.astype(float), 'finish': jr.finish.fillna(0).astype(float),
        'c1': c1, 'c4': c4, 'l3f': np.nan, 'time_sec': np.nan, 'tdiff': '', 'odds': jr.win_odds.astype(float),
        'pop': jr.popularity.astype(float), 'date': jr.date, 'fsize': jr.field_size.astype(float)})
    SE = pd.concat([se, sj], ignore_index=True)
    SE.to_parquet(ALT / 'kd_se.parquet', index=False)
    print('走り', f'{len(se):,}', '中央', f'{len(sj):,}', flush=True)
    # --- レース(距離・芝ダ・1 着賞金・中央の条件)
    ra['date'] = pd.to_datetime(ra.race_date)
    trk = np.select([ra.surface == '芝', ra.surface == 'ダート'], [17, 24], 0)
    p1 = ra.prize_yen.map(lambda x: x[0] if x is not None and len(x) else np.nan).astype(float) / 100
    nm = [split_name(x) for x in ra.race_name]
    kind = ra.race_kind.fillna('')
    grade = np.where(kind == '重賞', 'S', np.where(kind.isin(['特別', '準重賞']), 'E', ''))
    RA = pd.DataFrame({'make': 0.0, 'year': ra.date.dt.year.astype(float), 'md': (ra.date.dt.month * 100 + ra.date.dt.day).astype(float),
                       'jyo': ra.track.map(JYO).astype(float), 'race': ra.race_no.astype(float), 'grade': grade, 'ccmin': 0.0,
                       'dist': ra.distance_m.astype(float).where(ra.distance_m > 0), 'trk': trk.astype(float), 'prize1': p1})
    RA = RA[RA.jyo.notna()]
    jrr = jr.drop_duplicates(['date', 'place', 'race_no'])
    cc = jrr.race_name.map(jra_ccmin)
    gj = jrr.race_name.fillna('').map(nf)
    jg = np.select([gj.str.contains('G1|GI$|JpnI$'), gj.str.contains('G2|GII'), gj.str.contains('G3|GIII'), gj.str.contains('L$|リステッド')],
                   ['A', 'B', 'C', 'L'], '')
    RJ = pd.DataFrame({'make': 0.0, 'year': jrr.date.dt.year.astype(float), 'md': (jrr.date.dt.month * 100 + jrr.date.dt.day).astype(float),
                       'jyo': jrr.place.map(JRA).astype(float), 'race': jrr.race_no.astype(float), 'grade': jg, 'ccmin': cc.astype(float),
                       'dist': jrr.distance.astype(float),
                       'trk': np.select([jrr.surface == '芝', jrr.surface == 'ダ'], [17, 24], 0).astype(float),
                       'prize1': cc.map(JRA_PRIZE).astype(float)})
    RAll = pd.concat([RA, RJ], ignore_index=True)
    RAll.to_parquet(ALT / 'kd_ra.parquet', index=False)
    RAll.iloc[:0].to_parquet(ALT / 'kd_ra_open.parquet', index=False)
    # --- RA の生記録の代わり(クラス名・名前・馬場・天候)
    T = pd.DataFrame({'year': RA.year.astype(int), 'md': RA.md.astype(int), 'jyo': RA.jyo.astype(int), 'race': RA.race.astype(int),
                      'cls': [c for c, _ in nm], 'rname': [n for _, n in nm],
                      'note': '', 'baba': ra.going.map(BABA).reindex(RA.index), 'tenko': ra.weather.map(TENKO).reindex(RA.index)})
    T['note'] = np.where(ra.race_name.reindex(RA.index).map(nf).str.contains('選抜'), '選抜', '')
    T['has_name'] = (T.rname != '') | kind.reindex(RA.index).isin(['特別', '重賞', '準重賞'])
    T['baba_t'] = np.where(ra.surface.reindex(RA.index) == '芝', T.baba, 0)
    T['baba_d'] = np.where(ra.surface.reindex(RA.index) == '芝', 0, T.baba)
    T.to_parquet(ALT / 'ra_text.parquet', index=False)
    # --- 馬(父・母・母父・馬主・生産者)
    pr['by'] = pd.to_datetime(pr.birth_date, errors='coerce').dt.year
    pr['hkey'] = pr.horse_name.str.replace(r'\s+', '', regex=True) + '|' + pr.by.astype('Int64').astype(str)
    pr = pr.drop_duplicates('hkey', keep='last')
    hz = pd.DataFrame({'ketto': kid.index.map(kid)}, index=kid.index)
    hz = hz.join(pr.set_index('hkey')[['sire', 'dam', 'broodmare_sire', 'owner', 'breeder', 'birth_date']])
    H = pd.DataFrame({'ketto': hz.ketto.astype(float), 'sire_id': hz.sire, 'dam_id': hz.dam, 'bms_id': hz.broodmare_sire,
                      'owner_cd': hz.owner, 'breeder_cd': hz.breeder, 'area': None,
                      'birth': pd.to_numeric(hz.birth_date.fillna('').str.replace('-', ''), errors='coerce')}).reset_index(drop=True)
    H.to_parquet(ALT / 'kd_horse.parquet', index=False)
    print('馬', f'{len(H):,}', '父あり', round(H.sire_id.notna().mean(), 3), 'レース', f'{len(RA):,}', '中央のレース', f'{len(RJ):,}')


def patch():
    """k1・k4・k8 を公式の元に向ける(関数を差し替えるだけ・作りは触らない)。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import k1_feat as k1
    import k4_extra as k4
    import k8_si as k8
    k1.V = str(ALT) + '/'
    k1.OUT = ALT / 'kochi'
    k4.V = ALT / 'kochi'
    k8.V = ALT / 'kochi'
    k8.Y0 = 2015  # 公式は 2014 から = 物差しは 2015 から
    T = pd.read_parquet(ALT / 'ra_text.parquet')
    orig = k1.load_se

    def load_se():
        se = orig()
        fs = pd.read_parquet(ALT / 'kd_se.parquet', columns=['date', 'jyo', 'race', 'umaban', 'fsize'])
        fs = fs[fs.fsize.notna()].astype({'jyo': 'int16', 'race': 'int16', 'umaban': 'int16'})
        se = se.merge(fs, on=['date', 'jyo', 'race', 'umaban'], how='left')
        se['n'] = se.fsize.fillna(se.n).astype('int16')  # 中央は頭数を公式の数に
        return se.drop(columns='fsize')

    def ra_text():
        R = T[T.jyo == k1.KOCHI].copy()
        lv = {'E': 0, 'D': 0.5, 'C3': 1, 'C2': 2, 'C1': 3, 'C': 2, 'B': 4, 'A': 5}

        def parse(c, note, name):
            m = re.match(r'^(C[123]|[ABCDE])', c)
            young = 2 if c.startswith('2歳') else 3 if c.startswith('3歳') else 0
            kumi = re.search(r'-(\d+)', c)
            g = lv[m.group(1)] if m else (6 if (not c and name) else np.nan)
            kind = 3 if any(w in name + note for w in ['重賞', '杯', '賞典', 'カップ', '記念']) and not m else \
                2 if '選抜' in note or '選抜' in name else 1 if name else 0
            return g, int(kumi.group(1)) if kumi else np.nan, young, kind
        P = [parse(c, n, nm) for c, n, nm in zip(R.cls, R.note, R.rname)]
        R[['b_cls', 'b_kumi', 'b_young', 'b_kind']] = pd.DataFrame(P, index=R.index)
        R['baba'] = R.baba.where(R.baba.between(1, 4))
        R['tenko'] = R.tenko.where(R.tenko.between(1, 6))
        R['jyo'] = np.int16(k1.KOCHI)
        R['race'] = R.race.astype('int16')
        return R[['year', 'md', 'jyo', 'race', 'b_cls', 'b_kumi', 'b_young', 'b_kind', 'baba', 'tenko']]

    def ra_all():
        return T[['year', 'md', 'jyo', 'race', 'cls', 'has_name', 'baba_t', 'baba_d']].copy()
    k1.load_se = load_se
    k1.ra_text = ra_text
    k8.ra_all = ra_all
    return k1, k4, k8


def compare():
    """高知の走り(2014〜2026-09-27)を KDSCOPE と同じ (日・R・馬番) で 1 頭ずつ照らす。"""
    k1, _, _ = patch()
    V = 'C:/Users/kouki/nankan_ai/v3/'
    cols = ['kubun', 'date', 'jyo', 'race', 'umaban', 'ketto', 'name', 'sex', 'age', 'jockey_cd', 'trainer_cd', 'kinryo', 'ijo',
            'finish', 'c1', 'c4', 'l3f', 'time_sec', 'tdiff', 'odds', 'pop', 'waku']
    K = pd.read_parquet(V + 'kd_se.parquet', columns=cols, filters=[('jyo', '==', 54.0), ('year', '>=', 2014.0)])
    K = K[~K.kubun.isin(['0', '9'])]
    K['kb'] = K.kubun.map({'7': 3, '2': 2}).fillna(1)
    K = K.sort_values('kb').drop_duplicates(['date', 'race', 'umaban'], keep='last')
    S = pd.read_parquet(ALT / 'kd_se.parquet')
    S = S[S.jyo == 54].drop_duplicates(['date', 'race', 'umaban'])
    ru = pd.read_parquet(O + 'runs.parquet', columns=['track', 'race_date', 'race_no', 'runner_number', 'horse_name'])
    ru = ru[ru.track == '高知'].assign(date=lambda x: pd.to_datetime(x.race_date), race=lambda x: x.race_no.astype(float),
                                       umaban=lambda x: x.runner_number.astype(float))
    S = S.merge(ru[['date', 'race', 'umaban', 'horse_name']], on=['date', 'race', 'umaban'], how='left')
    last = K.date.max()
    S = S[S.date <= last]
    M = K.merge(S, on=['date', 'race', 'umaban'], how='outer', suffixes=('_k', '_o'), indicator=True)
    out = [f'期間 2014-01-01〜{last.date()}・KDSCOPE {len(K):,} 頭・公式 {len(S):,} 頭',
           '両方にある ' + f"{(M._merge == 'both').mean():.4f}" + ' ・KDSCOPE だけ ' + f"{(M._merge == 'left_only').sum():,}"
           + ' ・公式だけ ' + f"{(M._merge == 'right_only').sum():,}"]
    B = M[M._merge == 'both'].copy()
    nm = B.name.fillna('').map(nf) == B.horse_name.fillna('').map(nf)
    out.append(f'馬名が同じ {nm.mean():.4f}')
    run = (B.ijo_k == 0) & (B.ijo_o == 0)
    def eq(a, b, tol=0.0):
        a, b = B[a], B[b]
        ok = a.notna() & b.notna()
        return f'{((a - b).abs() <= tol)[ok & run].mean():.4f}(両方ある {ok[run].mean():.3f})'
    B['tdk'] = pd.to_numeric(B.tdiff_k.astype(str).str.replace('+', '', regex=False), errors='coerce')
    B['tdo'] = pd.to_numeric(B.tdiff_o.astype(str).str.replace('+', '', regex=False), errors='coerce')
    B['ijk'] = B.ijo_k.replace({2: 3}).fillna(0)
    for lab, a, b, t in [('着順', 'finish_k', 'finish_o', 0), ('タイム', 'time_sec_k', 'time_sec_o', 0.05), ('上がり', 'l3f_k', 'l3f_o', 0.05),
                         ('斤量', 'kinryo_k', 'kinryo_o', 0.05), ('1 角', 'c1_k', 'c1_o', 0), ('4 角', 'c4_k', 'c4_o', 0),
                         ('着差の時計', 'tdk', 'tdo', 0), ('枠', 'waku_k', 'waku_o', 0), ('人気', 'pop_k', 'pop_o', 0),
                         ('年齢', 'age_k', 'age_o', 0), ('性', 'sex_k', 'sex_o', 0), ('単勝', 'odds_k', 'odds_o', 0.05)]:
        if lab == '単勝':
            B['odds_k'] = B.odds_k / 10
        out.append(f'{lab} 一致 {eq(a, b, t)}')
    out.append(f"取消・除外・中止の区分 一致 {(B.ijk == B.ijo_o).mean():.4f}")
    # つなぎ方の 1 対 1
    for lab, a, b in [('馬', 'ketto_k', 'ketto_o'), ('騎手', 'jockey_cd_k', 'jockey_cd_o'), ('調教師', 'trainer_cd_k', 'trainer_cd_o')]:
        x = B[[a, b]].dropna()
        f1 = x.groupby(a)[b].nunique()
        f2 = x.groupby(b)[a].nunique()
        w1 = x[a].map(f1 > 1).mean()
        w2 = x[b].map(f2 > 1).mean()
        out.append(f'{lab}: KDSCOPE の 1 つが公式の 2 つ以上に割れる走り {w1:.4f}・公式の 1 つに KDSCOPE の 2 つ以上 {w2:.4f}'
                   f'(KDSCOPE {x[a].nunique():,}・公式 {x[b].nunique():,})')
    # レース
    rk = pd.read_parquet('C:/Users/kouki/nankan_ai/v3/official/kd_ra_text_cache.parquet')
    rk = rk[rk.year >= 2014]
    ro = k1.ra_text()
    R = rk.merge(ro, on=['year', 'md', 'race'], suffixes=('_k', '_o'))
    out.append(f'レース {len(rk):,} → 公式と合う {len(R):,}')
    for c in ['b_cls', 'b_kumi', 'b_young', 'b_kind', 'baba', 'tenko']:
        a, b = R[c + '_k'], R[c + '_o']
        out.append(f'  {c} 一致 {((a == b) | (a.isna() & b.isna())).mean():.4f}')
    V2 = 'C:/Users/kouki/nankan_ai/v3/'
    kr = pd.concat([pd.read_parquet(V2 + f, columns=['make', 'year', 'md', 'jyo', 'race', 'dist', 'prize1', 'grade'], filters=[('jyo', '==', 54.0)])
                    for f in ['kd_ra.parquet', 'kd_ra_open.parquet']]).sort_values('make').drop_duplicates(['year', 'md', 'race'], keep='last')
    orr = pd.read_parquet(ALT / 'kd_ra.parquet')
    orr = orr[orr.jyo == 54]
    R2 = kr[kr.year >= 2014].merge(orr, on=['year', 'md', 'race'], suffixes=('_k', '_o'))
    out.append(f"  距離 一致 {(R2.dist_k == R2.dist_o).mean():.4f}・1 着賞金 一致 {((R2.prize1_k - R2.prize1_o).abs() < 1).mean():.4f}")
    out.append('  KDSCOPE の格 × 公式の種類: ' + str(pd.crosstab(R2.grade_k, R2.grade_o).to_dict()))
    print('\n'.join(out))
    bad = B[run & B.time_sec_k.notna() & B.time_sec_o.notna() & ((B.time_sec_k - B.time_sec_o).abs() > 0.05)]
    print(bad.groupby(bad.date.dt.year).size().to_dict())
    print(bad[['date', 'race', 'umaban', 'name', 'time_sec_k', 'time_sec_o', 'finish_k', 'finish_o']].head(8).to_string())
    bad = B[run & ((B.c4_k - B.c4_o).abs() > 0)]
    print('4角ずれ', bad.groupby(bad.date.dt.year).size().to_dict())


def feat():
    k1, k4, k8 = patch()
    k1.main()
    k4.main()
    k8.main()


if __name__ == '__main__':
    {'build': build, 'compare': compare, 'feat': feat}[sys.argv[1]]()
