"""KDSCOPE の馬の台帳(v3/kd_horse.parquet)から nar_kd_pedigree 用の gzip CSV を作る(手元で 1 回・本番は触らない)。

  py -3.12 pipeline/kd_pedigree_export.py [--src C:/Users/kouki/nankan_ai/v3/kd_horse.parquet] [--out data/kd_pedigree/kd_pedigree.csv.gz]

- 2008 年以降生まれだけ。名前は NFKC+前後空白の除去。
- UM と NU で同じ ketto は NU を優先(地方の台帳)。
- 出力列= ketto, horse_name, birth_date, sex, sire, dam, broodmare_sire, breeder, src(空は空文字= 投入で null)。
"""
import argparse
import os
import unicodedata

import pandas as pd

SEX = {1: '牡', 2: '牝', 3: 'セ'}
COLS = ['ketto', 'horse_name', 'birth_date', 'sex', 'sire', 'dam', 'broodmare_sire', 'breeder', 'src']


def clean(s):
    if s is None or (isinstance(s, float) and s != s):
        return ''
    return unicodedata.normalize('NFKC', str(s)).strip()


def ymd(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return ''
    d = pd.to_datetime(str(v), format='%Y%m%d', errors='coerce')
    return '' if pd.isna(d) else d.strftime('%Y-%m-%d')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default='C:/Users/kouki/nankan_ai/v3/kd_horse.parquet')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(__file__), '..', 'data', 'kd_pedigree', 'kd_pedigree.csv.gz'))
    a = ap.parse_args()
    df = pd.read_parquet(a.src, columns=['ketto', 'birth', 'name', 'sex', 'sire', 'dam', 'bms', 'breeder', 'src', 'birth_year'])
    n0 = len(df)
    df = df[df.birth_year >= 2008].copy()
    df = df[df.ketto.notna() & (df.ketto > 0)]
    df['ketto'] = df.ketto.astype('int64').astype(str)
    df['pri'] = (df.src == 'NU').astype(int)          # NU を優先
    df = df.sort_values(['ketto', 'pri']).drop_duplicates('ketto', keep='last')
    out = pd.DataFrame({
        'ketto': df.ketto,
        'horse_name': df.name.map(clean),
        'birth_date': df.birth.map(ymd),
        'sex': df.sex.map(lambda v: SEX.get(int(v), '') if v == v and v is not None else ''),
        'sire': df.sire.map(clean), 'dam': df.dam.map(clean), 'broodmare_sire': df.bms.map(clean),
        'breeder': df.breeder.map(clean), 'src': df.src,
    })
    out = out[out.horse_name != ''][COLS]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out.to_csv(a.out, index=False, compression='gzip', encoding='utf-8')
    print(f'台帳 {n0:,} 行 → 2008 年以降・ketto 重複なし・名前あり {len(out):,} 行')
    print(f'src 内訳 {out.src.value_counts().to_dict()}')
    print(f'母あり率 {(out.dam != "").mean():.1%}・父あり率 {(out.sire != "").mean():.1%}・生年月日あり率 {(out.birth_date != "").mean():.1%}')
    dup = out[out.birth_date != ''].duplicated(['horse_name', 'birth_date'], keep=False).sum()
    print(f'(馬名, 生年月日) が重なる行 {dup:,}')
    print('生年別件数')
    print(out.birth_date.str[:4].value_counts().sort_index().to_string())
    print(f'保存 {os.path.abspath(a.out)} {os.path.getsize(a.out) / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
