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
        if op == 'in': rows = [r for r in rows if str(r[k]) in val.strip('()').split(',')]
        elif op == 'lt': rows = [r for r in rows if r[k] < val]
        elif op == 'eq': rows = [r for r in rows if str(r[k]) == val]
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


JKEY = ['kb_horse_id', 'race_date', 'place', 'race_no']


def _jra_db():
    """中央の走り: 馬 30 頭 × 2014〜今日まで 60 日おき。updated_at は全部古い日"""
    out = []
    for h in range(30):
        d = dt.date(2014, 1, 5) + dt.timedelta(days=h)
        while d <= TODAY:
            out.append(dict(kb_horse_id=f'{h:07d}', race_date=d.isoformat(), place='東京', race_no=1, x=f'{h}{d}', updated_at='2014-01-01T00:00:00'))
            d += dt.timedelta(days=60)
    return out


def _horses(rows, extra=()):
    g = {}
    for r in rows:
        n, last = g.get(r['kb_horse_id'], (0, ''))
        g[r['kb_horse_id']] = (n + 1, max(last, r['race_date']))
    return [dict(kb_horse_id=k, jra_runs=n, last_jra_date=l) for k, (n, l) in g.items()] + [dict(kb_horse_id=k, jra_runs=None, last_jra_date=None) for k in extra]


def _jra_run(cache, full_days_ago=3):
    """控えを full_days_ago 日前の丸ごととして読む(meta の full を書き換え)"""
    import json as _j
    K.CACHE = cache
    if cache and (Path(cache) / 'meta.json').exists():
        m = _j.loads((Path(cache) / 'meta.json').read_text(encoding='utf-8'))
        m['nar_jra_runs']['full'] = (TODAY - dt.timedelta(days=full_days_ago)).isoformat()
        (Path(cache) / 'meta.json').write_text(_j.dumps(m), encoding='utf-8')
    h = K.whole('nar_jra_horses', 'kb_horse_id')
    return K.whole('nar_jra_runs', 'kb_horse_id,race_date,race_no', by_date=True, late_key=JKEY, horses=h)


def _same(a, b):
    c = [x for x in a.columns if x != 'updated_at']
    return a[c].astype(str).sort_values(JKEY).reset_index(drop=True).equals(b[c].astype(str).sort_values(JKEY).reset_index(drop=True))


def test_jra_late(tmp_path):
    """11/22 の穴(控えの後に入った古い日付の中央の走りが届かない)と 11/23 の守り 3 つ"""
    old = (K.sb.__dict__.get('get'), K.TR)
    K.sb.get = staticmethod(fake_get)  # pytest から呼ばれても偽の DB を使う(本番に繋がない)
    K.TR = ['園田', '大井', '高知']
    try:
        _jra_late(tmp_path)
    finally:
        if old[0] is None:
            del K.sb.get
        else:
            K.sb.get = old[0]
        K.TR = old[1]


def _jra_late(tmp):
    since = (TODAY - dt.timedelta(days=K.DIFF_DAYS)).replace(day=1).isoformat()
    now = TODAY.isoformat() + 'T01:00:00'
    base = _jra_db()
    # ① 控えの後に: 転入馬 A の古い走り 5 本が入る・仮の馬 kdB が消える・馬 0000005 の古い走りが 1 本消える(updated_at は動かない)
    db0 = base + [dict(r, kb_horse_id='kdB0001') for r in base if r['kb_horse_id'] == '0000002']
    db1 = [r for r in base if not (r['kb_horse_id'] == '0000005' and r['race_date'] == min(x['race_date'] for x in base if x['kb_horse_id'] == '0000005'))]
    db1 += [dict(kb_horse_id='A000001', race_date=f'2025-0{i}-10', place='中山', race_no=i, x='A', updated_at=now) for i in range(1, 6)]
    for name, cut_full in [('ok', None), ('late_max', 'late'), ('gone_max', 'gone')]:
        c = str(tmp / f'j_{name}')
        DB['nar_jra_runs'], DB['nar_jra_horses'] = db0, _horses(db0)
        _jra_run(c)
        (Path(c) / K.DIRTY).unlink()
        DB['nar_jra_runs'], DB['nar_jra_horses'] = db1, _horses(db1, extra=['NOINFO1'])
        if cut_full == 'late':
            K.LATE_MAX = 3                         # 後から入った行が多すぎ → 丸ごと
        if cut_full == 'gone':
            DB['nar_jra_horses'] = DB['nar_jra_horses'][:5]   # 馬の表が途中で切れた → 消さずに丸ごと
            K.GONE_MAX = 10
        got = _jra_run(c)
        K.LATE_MAX, K.GONE_MAX = 20000, 500
        truth = K.pd.DataFrame(db1)
        assert _same(got, truth), f'{name}: 控えの読みが DB の姿と合わない'
        assert int((got.kb_horse_id == 'A000001').sum()) == 5 and not (got.kb_horse_id == 'kdB0001').any(), name
        full_again = (Path(c) / K.DIRTY).exists()
        assert full_again == (cut_full is not None), f'{name}: 守りに掛かったら丸ごと(dirty)・掛からなければ差分だけ'
    # 直す前の形(late_key なし)では A が届かない = この試験が穴を捉えている
    c = str(tmp / 'j_old')
    DB['nar_jra_runs'], DB['nar_jra_horses'] = db0, _horses(db0)
    K.CACHE = c
    K.whole('nar_jra_runs', 'kb_horse_id,race_date,race_no', by_date=True)
    DB['nar_jra_runs'] = db1
    import json as _j
    m = _j.loads((Path(c) / 'meta.json').read_text(encoding='utf-8')); m['nar_jra_runs']['full'] = (TODAY - dt.timedelta(days=3)).isoformat()
    (Path(c) / 'meta.json').write_text(_j.dumps(m), encoding='utf-8')
    old = K.whole('nar_jra_runs', 'kb_horse_id,race_date,race_no', by_date=True)
    assert int((old.kb_horse_id == 'A000001').sum()) == 0, '直す前の形で A が届いた = 試験が穴を再現していない'
    assert since > '2025-05-10'


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
        _jra_late(tmp)
        print('ok', len(base), len(new), 'jra_late ok')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
