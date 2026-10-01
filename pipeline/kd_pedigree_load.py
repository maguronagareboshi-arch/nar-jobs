"""data/kd_pedigree/kd_pedigree.csv.gz を本番の nar_kd_pedigree に 1000 行ずつ upsert する(便 kd-pedigree-load.yml)。

  python pipeline/kd_pedigree_load.py [--dry-run]
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常 / 1 投入失敗。冪等(何度流しても同じ)。
"""
import argparse
import csv
import datetime as dt
import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load_nar_official import upsert  # noqa: E402

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'kd_pedigree', 'kd_pedigree.csv.gz')
BATCH = 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with gzip.open(CSV, 'rt', encoding='utf-8', newline='') as f:
        rows = [{k: (v if v != '' else None) for k, v in r.items()} | {'updated_at': now} for r in csv.DictReader(f)]
    print(f'CSV {len(rows):,} 行')
    if a.dry_run:
        print('ドライラン= 書かない'); return 0
    url = os.environ['SUPABASE_URL'].rstrip('/')
    key = os.environ['SUPABASE_SERVICE_KEY']
    for i in range(0, len(rows), BATCH):
        st, msg = upsert(url, key, 'nar_kd_pedigree', 'ketto', rows[i:i + BATCH])
        if st >= 300:
            print(f'upsert 失敗 {i:,} 行目から {st} {msg}'); return 1
        if (i // BATCH) % 50 == 0:
            print(f'  {i + len(rows[i:i + BATCH]):,} 行済み')
    print(f'upsert 済み {len(rows):,} 行')
    return 0


if __name__ == '__main__':
    sys.exit(main())
