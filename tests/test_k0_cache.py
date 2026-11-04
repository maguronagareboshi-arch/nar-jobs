# -*- coding: utf-8 -*-
"""k0_dl の控え(K0_CACHE)= 偽の行で「控え+直近の差分 = 丸ごと」と、丸ごとの回だけ dirty.flag が立つことを確かめる(11/5)。
  py -3.12 -X utf8 tests/test_k0_cache.py"""
import datetime as dt
import shutil
import sys
import tempfile
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'ai' / 'kochi'))
import os  # noqa: E402
os.environ.setdefault("SUPABASE_ANON_KEY", "test")  # 偽の鍵= 本番には繋がない(sb.get は差し替え)
import k0_dl as K  # noqa: E402

TODAY = dt.date.today()
DB = {}


def _rows():
    out = []
    for t in ['園田', '大井', '高知']:
        d = dt.date(2014, 1, 5)
        while d <= TODAY:
            for rno in (1, 2):
                for u in range(1, 4):
                    out.append(dict(track=t, race_date=d.isoformat(), race_no=rno, umaban=u, x=f'{t}{d}{rno}{u}'))
            d += dt.timedelta(days=17)
    return out


def fake_get(path, tries=4):
    u = urllib.parse.urlparse(path)
    table = u.path.rsplit('/', 1)[1]
    qs = urllib.parse.parse_qsl(u.query)
    rows = DB[table]
    for k, v in qs:
        if k in ('select', 'order', 'limit', 'offset'):
            continue
        op, val = v.split('.', 1)
        if op == 'eq': rows = [r for r in rows if str(r[k]) == val]
        elif op == 'gte': rows = [r for r in rows if r[k] >= val]
        elif op == 'lte': rows = [r for r in rows if r[k] <= val]
    d = dict(qs)
    keys = d['order'].split(',')
    rows = sorted(rows, key=lambda r: [r[c] for c in keys])
    off, lim = int(d['offset']), int(d['limit'])
    return [dict(r) for r in rows[off:off + lim]]


def run(cache, sel='track,race_date,race_no,umaban,x'):
    K.CACHE = cache
    return K.by_track_month('nar_run_facts', sel, 'race_no,umaban')


def run_whole(cache):
    K.CACHE = cache
    return K.whole('nar_jra_runs', 'track,race_date,race_no,umaban', by_date=True)


def main():
    K.sb.get = staticmethod(fake_get)
    K.TR = ['園田', '大井', '高知']
    base = _rows()
    DB['nar_run_facts'] = base
    DB['nar_jra_runs'] = base
    tmp = Path(tempfile.mkdtemp(prefix='k0t_', dir=Path(__file__).resolve().parent))
    try:
        c = str(tmp / 'c')
        f1 = run(c)
        w1 = run_whole(c)
        assert (Path(c) / K.DIRTY).exists(), '丸ごとの回に dirty.flag が無い'
        (Path(c) / K.DIRTY).unlink()
        # 直近の行を直す・足す・消す(古い月は触らない= 控えの前提)
        since = (TODAY - dt.timedelta(days=K.DIFF_DAYS)).replace(day=1).isoformat()
        new = [dict(r, x=r['x'] + '!') if r['race_date'] >= since and r['umaban'] == 2 else r for r in base]
        new = [r for r in new if not (r['race_date'] >= since and r['umaban'] == 3 and r['race_no'] == 2)]
        new.append(dict(track='大井', race_date=TODAY.isoformat(), race_no=9, umaban=1, x='new'))
        DB['nar_run_facts'] = new
        DB['nar_jra_runs'] = new
        f2 = run(c)          # 控え+差分
        w2 = run_whole(c)
        assert not (Path(c) / K.DIRTY).exists(), '差分だけの回に dirty.flag が立った'
        f3 = run('')         # 丸ごと(控え無し)
        w3 = run_whole('')
        assert f2.equals(f3), '控え+差分 ≠ 丸ごと(by_track_month)'
        assert w2.equals(w3), '控え+差分 ≠ 丸ごと(whole by_date)'
        assert len(f1) == len(base) and len(f2) == len(new) and len(w2) == len(new)
        # sel が変わったら丸ごと+dirty
        run(c, sel='track,race_date,race_no,umaban')
        assert (Path(c) / K.DIRTY).exists(), 'sel 変更で dirty.flag が無い'
        print('ok', len(base), len(new))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
