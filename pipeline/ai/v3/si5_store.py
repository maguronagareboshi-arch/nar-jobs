# -*- coding: utf-8 -*-
"""南関の走破指数 SI5 を走りごとに DB の nar_si5 へ保存する(2026-10-26・サイトの馬柱と持ちタイム表の「指数」の列)。

  便の中(v3_daily): install() → t9.table(…) → write(day)       = 直近 DAYS 日分を upsert(計算は変えない・控えるだけ)
  過去分(2014〜)は 1 回だけ: 便 nar-ai-v3 を si5_all=yes で手動起動(write=no でよい)= write(day, days=None)
  手元(鍵があるとき):  python -X utf8 pipeline/ai/v3/si5_store.py push FILE.parquet   = FILE の行を書く
                     python -X utf8 pipeline/ai/v3/si5_store.py check FILE.parquet  = DB の値と FILE を照らす(書かない)

- 値 = 便が予想の材料に作る t5_open.si5_of(U)(= t5_base.make_si5)の SI5 そのもの。新しい定数は足さない。
- 確定した日の値は後から動かない(2015〜21 の 25.5 万走で差 0)= 毎日は直近 DAYS 日だけ書き直す。
- 表の nar_si5 は DB のトリガーで nar_runs.si5 に写り、サイトは今までの窓口(runs_*)で読む(sql/si5_store.sql)。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TABLE = 'nar_si5'
CONFLICT = 'track,race_date,race_no,runner_number'
NANKAN = ['浦和', '船橋', '大井', '川崎']
DAYS = 21
CHUNK = 2000
CACHE = {}


def log(*a):
    print('[si5]', *a, flush=True)


def install():
    """t5_open.si5_of の戻りを控える(値は変えない)。何度呼ばれても行の一番多い回を残す。"""
    import t5_open
    f0 = t5_open.si5_of

    def f1(U):
        r = f0(U)
        if len(U) >= len(CACHE.get('U', ())):
            CACHE['U'], CACHE['R'] = U.reset_index(drop=True), r[0]
        return r
    t5_open.si5_of = f1


def frame(U=None, R=None):
    """→ 南関の SI5 のある走だけ(track・race_date 文字・race_no・runner_number・horse_key・si5 小数 1 桁)。"""
    U = CACHE['U'] if U is None else U.reset_index(drop=True)
    R = CACHE['R'] if R is None else R
    assert len(U) == len(R), 'U と make_si5 の行数が違う'
    x = pd.DataFrame({'track': U.track.to_numpy(), 'race_date': pd.to_datetime(U.race_date).dt.strftime('%Y-%m-%d').to_numpy(),
                      'race_no': U.race_no.astype(int).to_numpy(), 'runner_number': U.runner_number.astype(int).to_numpy(),
                      'horse_key': U.hk.astype(str).to_numpy(), 'si5': np.round(R.SI5.to_numpy(float), 1)})
    x = x[x.track.isin(NANKAN) & np.isfinite(x.si5)]
    assert not x.duplicated(['track', 'race_date', 'race_no', 'runner_number']).any(), '同じ走が 2 行ある'
    return x.reset_index(drop=True)


def _push(x):
    sys.path.insert(0, str(HERE.parent))
    import base_v1 as B1
    base, key = B1.creds()
    recs = x.to_dict('records')
    for i in range(0, len(recs), CHUNK):
        st, err = B1.upsert(base, key, TABLE, CONFLICT, recs[i:i + CHUNK])
        if st not in (200, 201, 204):
            raise SystemExit(f'nar_si5 upsert failed: {st} {err}')
        if i and i % (CHUNK * 25) == 0:
            log('書いた', i, '/', len(recs))
    return base, key


def read_back(lo, hi):
    """DB の nar_si5 の [lo, hi) を読む(照合用)。"""
    sys.path.insert(0, str(HERE.parent))
    import base_v1 as B1
    base, key = B1.creds()
    out, off = [], 0
    while True:
        rows = B1.sb_get(base, key, f'{TABLE}?select=track,race_date,race_no,runner_number,si5'
                                    f'&race_date=gte.{lo}&race_date=lt.{hi}&order=race_date,track,race_no,runner_number'
                                    f'&limit=1000&offset={off}')
        out += rows
        if len(rows) < 1000:
            break
        off += 1000
    return pd.DataFrame(out, columns=['track', 'race_date', 'race_no', 'runner_number', 'si5'])


def compare(x, db):
    k = ['track', 'race_date', 'race_no', 'runner_number']
    m = x.merge(db.astype({'si5': float}), on=k, how='left', suffixes=('', '_db'), validate='1:1')
    same = int((m.si5_db - m.si5).abs().le(0.05).sum())
    return {'行': len(x), 'DB にある': int(m.si5_db.notna().sum()), '一致': same}


def write(day, days=DAYS):
    """便の中: 控えた U・SI5 から [day − days, day)(days=None = 全期間)を書いて読み直す。→ 照合の数(書けなければ例外)。"""
    if 'U' not in CACHE:
        raise RuntimeError('SI5 を控えていない(install の後に表を作る)')
    x = frame()
    lo = x.race_date.min() if days is None else (pd.Timestamp(day) - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
    x = x[(x.race_date >= lo) & (x.race_date < str(day))]
    if x.empty:
        log('書く走なし', lo, '〜', day)
        return {'行': 0}
    _push(x)
    c = compare(x, read_back(lo, str(day)))
    log('nar_si5', lo, '〜', day, c)
    return c


def main():
    a = sys.argv[1:]
    x = pd.read_parquet(a[1])
    x = x.astype({'race_date': str})
    if a[0] == 'push':
        log('過去分を書く', len(x), '行', x.race_date.min(), '〜', x.race_date.max())
        _push(x)
    lo, hi = x.race_date.min(), (pd.Timestamp(x.race_date.max()) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    log('照合', compare(x, read_back(lo, hi)))


if __name__ == '__main__':
    main()
