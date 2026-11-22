# -*- coding: utf-8 -*-
"""高知版 0 = nar-official の公式の表を手元の parquet に落とす(読むだけ・公開の anon 鍵)。場 × 月ごとに 1000 行ずつ。
  py -3.12 -X utf8 src/kochi/k0_dl.py [出す先] [表…]  → runs・races・facts・profiles・jra・jrah(・ext)の parquet
  鍵 = 環境変数 SUPABASE_URL・SUPABASE_ANON_KEY か SUPABASE_SERVICE_KEY(無ければ src/f5_scripts/week_backfill.py の公開の鍵)。"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[3] / 'cloud'))  # 2026-11-06 送信量: 受け取りを gzip で
import sb_gzip  # noqa: E402
from jst import jst_today  # noqa: E402  (cloud/jst.py・#8 JST の今日)
import pandas as pd
D = 'C:/Users/kouki/nankan_ai/v3/official/'
URL = os.environ.get('SUPABASE_URL', 'https://qgsnsdjvzzeazbazjlwa.supabase.co').rstrip('/')
KEY = os.environ.get('SUPABASE_SERVICE_KEY', '') or os.environ.get('SUPABASE_ANON_KEY', '')   # 段3(10/19): nar_runs は管理用の鍵で
if not KEY:
    _t = (Path(__file__).resolve().parents[1] / 'f5_scripts' / 'week_backfill.py').read_text(encoding='utf-8')
    KEY = ''.join(re.findall(r"'([^']*)'", _t.split('KEY = (')[1].split(')')[0]))


class sb:
    @staticmethod
    def get(path, tries=4):
        for i in range(tries):
            try:
                req = urllib.request.Request(URL + path, headers={'apikey': KEY, 'Authorization': 'Bearer ' + KEY})
                return json.loads(sb_gzip.read(req, 120).decode('utf-8'))
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(3 * (i + 1))
TR = ['園田', '帯広ば', '大井', '名古屋', '高知', '佐賀', '門別', '金沢', '笠松', '川崎', '船橋', '浦和', '盛岡', '水沢', '姫路']
q = urllib.parse.quote
def pages(path):
    out, off = [], 0
    while True:
        r = sb.get(f'{path}&limit=1000&offset={off}')
        out += r
        if len(r) < 1000: return out
        off += 1000
# 2026-10-31 通信量: 便が毎回 2014〜を丸ごと読んでいた(1 回 約 1 GB × 1 日 5 回 = API の約 4 割)。
# K0_CACHE(便のキャッシュの置き場)があれば、前回の表を控えに使い、直近 DIFF_DAYS 日を含む月からだけ読み直す。
# 控えが FULL_DAYS 日より古い・列が違う・無いときは丸ごと読む(古い月の後からの直しは最長 FULL_DAYS 日で入る)。K0_CACHE が無ければ今まで通り。
CACHE = os.environ.get('K0_CACHE', '')
DIFF_DAYS, FULL_DAYS = 92, 7
# 控えの版: 2 = 月の取り方に日付の並びを入れた(11/3)。前の版の控えはページの切れ目で行が抜けている恐れ= 丸ごと読み直す
CACHE_VER = 2
DIRTY = 'dirty.flag'   # 控えの封の前に便が消す(控えの中には入れない)


def _meta():
    try:
        return json.loads((Path(CACHE) / 'meta.json').read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return {}


def _base(table, sel):
    """(控えの表, 読み直す始めの日) か (None, None)= 丸ごと"""
    if not CACHE:
        return None, None
    m, f = _meta().get(table, {}), Path(CACHE) / f'{table}.parquet'
    today = jst_today()
    if not f.exists() or m.get('sel') != sel or m.get('ver') != CACHE_VER or not m.get('full') or (today - dt.date.fromisoformat(m['full'])).days >= FULL_DAYS:
        print(table, '控え 無し/古い → 丸ごと', m.get('full'), flush=True)
        return None, None
    since = (today - dt.timedelta(days=DIFF_DAYS)).replace(day=1).isoformat()
    base = pd.read_parquet(f)
    print(table, '控え', len(base), '行(丸ごと', m['full'], ')+', since, '〜を読み直す', flush=True)
    return base, since


def _merge(old, new, sort):
    df = pd.concat([old, new], ignore_index=True) if len(new) else old.reset_index(drop=True)
    key = pd.DataFrame(dict(enumerate(sort(df))))
    return df.iloc[key.sort_values(list(key.columns), kind='mergesort').index].reset_index(drop=True)


def _keep(table, sel, df, full):
    if CACHE:
        Path(CACHE).mkdir(parents=True, exist_ok=True)
        df.to_parquet(Path(CACHE) / f'{table}.parquet', index=False)
        m = _meta()
        m[table] = {'sel': sel, 'ver': CACHE_VER, 'full': dt.date.today().isoformat() if full else m.get(table, {}).get('full')}
        (Path(CACHE) / 'meta.json').write_text(json.dumps(m, ensure_ascii=False), encoding='utf-8')
        # 11/5: 丸ごと読んだ回は印を置く= 便はこの印があるときだけ控えを新しい鍵で保存する。
        # (前は 1 日 1 鍵で、その日最初の便= nar-ai-last が facts を読まないまま保存し、後の v3n の facts 丸ごとは鍵が既にあって保存されず毎回丸ごとだった)
        if full:
            (Path(CACHE) / DIRTY).write_text(table + '\n', encoding='utf-8')
    return df


def months():
    m = pd.period_range('2014-01', (dt.date.today() + dt.timedelta(days=40)).strftime('%Y-%m'), freq='M')
    return [(str(p.start_time.date()), str(p.end_time.date())) for p in m]
def by_track_month(table, sel, order):
    base, since = _base(table, sel)
    jobs = [(t, a, b) for t in TR for a, b in months() if base is None or a >= since]
    def one(j):
        t, a, b = j
        # ⛔order= は一意の列の組(月の中で日付を入れないと、ページの切れ目で行が重なったり抜けたりする= ばんえい 27984e3 と同じ・11/3 監査)
        return pages(f'/rest/v1/{table}?select={sel}&track=eq.{q(t)}&race_date=gte.{a}&race_date=lte.{b}&order=race_date,{order}')
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(6) as ex:
        for i, r in enumerate(ex.map(one, jobs)):
            rows += r
            if i % 300 == 0: print(table, i, len(jobs), len(rows), round(time.time() - t0), flush=True)
    df = pd.DataFrame(rows)
    if base is not None:   # 古い月は控えのまま・新しい月だけ差し替える。並びは丸ごとと同じ(場の順 → 月 → 月の中は読んだ順)
        df = _merge(base[base.race_date < since], df, sort=lambda d: [d.track.map(TR.index), d.race_date.str[:7]])
    k = ['track', 'race_date'] + order.split(',')
    dup = int(df.duplicated(k).sum())
    if dup:
        raise SystemExit(f'⛔{table} に同じ行が {dup} 本(取り方の誤り)= 止まる')
    return _keep(table, sel, df, base is None)
# 2026-11-23 守り(FABLE の監査): 後から入った行が多すぎ・消える馬が多すぎ・数が合わない馬が多すぎ = 控えを捨てて丸ごと読む
# (丸ごとの回は控えを作り直すので、次の朝からまた少しだけ読む = 通信が増えるのはその 1 回だけ)
LATE_MAX, GONE_MAX, FIX_MAX = 20000, 500, 2000


def _pages_cap(path, cap):
    out, off = [], 0
    while True:
        r = sb.get(f'{path}&limit=1000&offset={off}')
        out += r
        if len(r) < 1000 or len(out) > cap:
            return out
        off += 1000


def _late(table, old, since, key, horses):
    """2026-11-22 穴の直し: 控えの古い行(since より前の日付)に、控えを丸ごと読んだ日より後に DB へ入った行を足す。
    中央の走り(nar_jra_runs)は転入馬が出馬表に出た日に古い走りまでまとめて入る = 日付で読み直す範囲の外になり、
    次の丸ごと(最長 7 日)まで本番に届かなかった(11/22 高知 6R プラニスフェリオ: 中央 18 走が全部抜け 3 着内 16.9% → 1 着)。
    ・入った・入れ直した行 = updated_at が丸ごとの日の前日以降(日の境と時差の余裕に 1 日)で since より前の日付の行を読み、同じ鍵の控えの行と差し替える。
    ・消えた馬 = 仮の行(kd*)の置き換えなどで DB から消えた馬の行は、今の馬の表(horses)に無い馬として控えから落とす。
    返り値 None = 守りに掛かった(行が LATE_MAX 超・消える馬が GONE_MAX 超・馬の表が空)→ 呼び手が丸ごとに戻す。"""
    if key is None or not len(old):
        return old
    full = _meta().get(table, {}).get('full')
    cut = (dt.date.fromisoformat(full) - dt.timedelta(days=1)).isoformat()
    t0 = time.time()
    new = pd.DataFrame(_pages_cap(f'/rest/v1/{table}?select=*&updated_at=gte.{cut}&race_date=lt.{since}&order={",".join(key)}', LATE_MAX))
    if len(new) > LATE_MAX:
        print(f'⚠{table} 控えより後に入った古い日付の行が {LATE_MAX} 超(まとめての直し?)→ 丸ごとに戻す', flush=True)
        return None
    ids = set(horses.kb_horse_id) if horses is not None else set()
    gone = ~old.kb_horse_id.isin(ids)
    n_gone = old.kb_horse_id[gone].nunique()
    if not ids or n_gone > GONE_MAX:
        print(f'⚠{table} 馬の表が空か、消える馬が {n_gone} 頭(> {GONE_MAX}・表の読み切れの恐れ)→ 消さずに丸ごとに戻す', flush=True)
        return None
    if len(new):
        k_old = pd.MultiIndex.from_frame(old[key].astype(str))
        k_new = pd.MultiIndex.from_frame(new[key].astype(str))
        old = pd.concat([old[~k_old.isin(k_new) & ~gone], new[new.kb_horse_id.isin(ids)][old.columns]], ignore_index=True)
    else:
        old = old[~gone]
    print(table, '控えより後に入った古い日付の行', len(new), '・消えた馬', n_gone, '頭', int(gone.sum()), '行(', cut, '〜 更新)', round(time.time() - t0), flush=True)
    return old


def _jra_bad(df, horses):
    """馬の表の「中央の走り数(jra_runs)・最後の日(last_jra_date)」と、走りの表の馬ごとの行数・最後の日が合わない馬。
    jra_runs が空(取れなかった馬)は数えない。行の中身の直しや付け替えも、日時(updated_at)に頼らずここで拾う。"""
    h = horses.drop_duplicates('kb_horse_id').set_index('kb_horse_id')
    want = pd.to_numeric(h.jra_runs, errors='coerce')
    h, want = h[want.notna()], want[want.notna()]
    g = df.groupby('kb_horse_id').race_date.agg(['size', 'max']).reindex(h.index)
    n_ok = g['size'].fillna(0).astype(int) == want.astype(int)
    l_ok = g['max'].fillna('').astype(str).str[:10] == h.last_jra_date.fillna('').astype(str).str[:10]
    return list(h.index[~(n_ok & l_ok)])


def _jra_fix(table, df, horses, key, sort):
    """数の合わない馬だけ ID 指定で読み直し、その馬の行を丸ごと差し替える。直らない馬は ⛔ で記録に出す(便は止めない)。
    返り値 (df, 合わなかった馬の数) / 合わない馬が FIX_MAX 超なら (None, 数) = 呼び手が丸ごとに戻す。"""
    t0 = time.time()
    bad = _jra_bad(df, horses)
    if len(bad) > FIX_MAX:
        return None, len(bad)
    if bad:
        got = []
        for i in range(0, len(bad), 40):
            got += pages(f'/rest/v1/{table}?select=*&kb_horse_id=in.({",".join(bad[i:i + 40])})&order={",".join(key)}')
        got = pd.DataFrame(got, columns=df.columns) if got else df.iloc[:0]
        df = _merge(df[~df.kb_horse_id.isin(bad)], got[df.columns], sort)
    left = _jra_bad(df, horses) if bad else []
    msg = f'{table} 馬の表と数の合わない馬 {len(bad)} 頭 → 読み直し → 残り {len(left)} 頭 {left[:5]}'
    print(('⛔' if left else '') + msg, round(time.time() - t0), flush=True)
    if left and os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(f'- ⛔ k0_dl: {msg}\n')
    return df, len(bad)


def whole(table, order, by_date=False, late_key=None, horses=None, _force_full=False):
    base, since = _base(table, '*') if by_date and not _force_full else (None, None)
    flt = f'&race_date=gte.{since}' if base is not None else ''
    rows, off, t0 = [], 0, time.time()
    def one(o): return sb.get(f'/rest/v1/{table}?select=*{flt}&order={order}&limit=1000&offset={o}')
    while True:
        with ThreadPoolExecutor(6) as ex:
            rs = list(ex.map(one, range(off, off + 6000, 1000)))
        for r in rs: rows += r
        off += 6000
        if any(len(r) < 1000 for r in rs): break
    print(table, len(rows), round(time.time() - t0), flush=True)
    df = pd.DataFrame(rows)
    if not by_date:
        return df
    c0, rest = order.split(',')[0], order.split(',')[1:]
    ref = base if base is not None else df
    rank = {v: i for i, v in enumerate(ref[c0].drop_duplicates())} if len(ref) else {}
    # 丸ごとの並び = order の列の順。頭の列(文字)は DB の照合順なので、控えにある値は控えの順を使う(新しい値だけ後ろ)
    sort = lambda d: [d[c0].map(rank).fillna(len(rank)), d[c0].where(~d[c0].isin(rank), '')] + [d[c] for c in rest]  # noqa: E731
    if base is not None:
        old = _late(table, base[base.race_date < since], since, late_key, horses)
        if old is None:
            return whole(table, order, by_date, late_key, horses, _force_full=True)
        df = _merge(old, df, sort)
    if late_key is not None and horses is not None and len(df):
        df2, n_bad = _jra_fix(table, df, horses, late_key, sort)
        if df2 is None:
            if base is not None:
                print(f'⚠{table} 数の合わない馬が {n_bad} 頭(> {FIX_MAX})→ 丸ごとに戻す', flush=True)
                return whole(table, order, by_date, late_key, horses, _force_full=True)
            print(f'⛔{table} 丸ごとでも数の合わない馬が {n_bad} 頭(DB の表どうしの食い違い)', flush=True)
        else:
            df = df2
    return _keep(table, '*', df, base is None)
def main(argv):
    global D
    if argv and ('/' in argv[0] or chr(92) in argv[0]):
        D = argv[0].rstrip('/') + '/'
        argv = argv[1:]
    Path(D).mkdir(parents=True, exist_ok=True)
    what = argv or ['races', 'runs', 'facts', 'profiles', 'jra', 'jrah']
    if 'races' in what:
        by_track_month('nar_races', 'track,race_date,race_no,race_name,race_kind,surface,direction,distance_m,weather,going,field_size,condition,prize_yen,race_last3f,corners,cancelled',
                       'race_no').to_parquet(D + 'races.parquet', index=False)
    if 'runs' in what:
        by_track_month('nar_runs', 'track,race_date,race_no,runner_number,gate,horse_name,birth_date,sex,age,jockey,trainer,trainer_area,carried_weight,weight_mark,body_weight,finish,finish_note,time_sec,margin,last3f,popularity',
                       'race_no,runner_number').to_parquet(D + 'runs.parquet', index=False)
    if 'facts' in what:
        by_track_month('nar_run_facts', 'track,race_date,race_no,umaban,horse_key,c1,n1,c4,n4,first3f,win_odds_close',
                       'race_no,umaban').to_parquet(D + 'facts.parquet', index=False)
    if 'profiles' in what:
        whole('nar_horse_profiles', 'horse_name,birth_date').to_parquet(D + 'profiles.parquet', index=False)
    if 'ext' in what:
        whole('nar_horse_ext_ids', 'source,ext_id').to_parquet(D + 'ext.parquet', index=False)
    # 11/23: 馬の表は先に 1 回だけ読み、中央の走りの守り(消えた馬・数の突き合わせ)にも使う(同じ表を 2 回読まない)
    jrah = whole('nar_jra_horses', 'kb_horse_id') if ('jra' in what or 'jrah' in what) else None
    if 'jra' in what:
        whole('nar_jra_runs', 'kb_horse_id,race_date,race_no', by_date=True,
              late_key=['kb_horse_id', 'race_date', 'place', 'race_no'], horses=jrah).to_parquet(D + 'jra.parquet', index=False)
    if 'jrah' in what:
        jrah.to_parquet(D + 'jrah.parquet', index=False)
    print('done')


if __name__ == '__main__':
    main(sys.argv[1:])
