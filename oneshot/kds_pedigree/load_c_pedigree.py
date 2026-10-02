"""案件 C: 投入 CSV を本番へ入れる(既存行は上書きしない= on conflict do nothing)。
⛔本体がユーザーに「手動」への切替を頼んでから流す。既定は数えるだけ(--apply で書く)。
  set SUPABASE_URL=https://qgsnsdjvzzeazbazjlwa.supabase.co
  set SUPABASE_SERVICE_KEY=...(秘密・ログに出さない)
  python load_c_pedigree.py            # 行数だけ
  python load_c_pedigree.py --apply    # profiles → nar_horses の順に 500 行ずつ
PostgREST の Prefer: resolution=ignore-duplicates = INSERT ... ON CONFLICT (鍵) DO NOTHING。
"""
import csv, json, os, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS = [('nar_horse_profiles_new.csv', 'nar_horse_profiles', 'horse_name,birth_date'),
        ('nar_horses_new.csv', 'nar_horses', 'horse_name')]
INT_COLS = {'runs'}


def rows(fn):
    with open(os.path.join(HERE, fn), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            yield {k: (int(v) if k in INT_COLS and v else (v if v != '' else None)) for k, v in r.items()}


def post(url, key, table, conflict, batch):
    req = urllib.request.Request(
        f'{url}/rest/v1/{table}?on_conflict={conflict}', data=json.dumps(batch, ensure_ascii=False).encode(),
        method='POST', headers={'apikey': key, 'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                                'Prefer': 'resolution=ignore-duplicates,return=minimal'})
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code < 500 or a == 2:
                raise SystemExit(f'{table}: HTTP {e.code} {e.read().decode()[:200]}')
        except Exception:
            if a == 2:
                raise
        time.sleep(3 * (a + 1))


def main():
    apply = '--apply' in sys.argv
    url, key = os.environ.get('SUPABASE_URL', '').rstrip('/'), os.environ.get('SUPABASE_SERVICE_KEY', '')
    if apply and not (url and key):
        raise SystemExit('SUPABASE_URL / SUPABASE_SERVICE_KEY が無い')
    for fn, table, conflict in JOBS:
        data = list(rows(fn))
        print(f'{table}: {len(data):,} 行({fn})')
        if not apply:
            continue
        for i in range(0, len(data), 500):
            post(url, key, table, conflict, data[i:i + 500])
        print(f'{table}: 送った {len(data):,} 行(既存の鍵は飛ばされる)')


if __name__ == '__main__':
    main()
