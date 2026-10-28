# -*- coding: utf-8 -*-
"""ばんえい 第 3 版の公式の表(2026-10-28)。pipeline/ai/kochi/k0_dl.py と同じ読み方で、帯広ばだけを手元の parquet に落とす。

  python -X utf8 pipeline/ai/banei/bn_dl.py <置き場> [YYYY-MM-DD]   # <置き場>/official/{runs,races,profiles}.parquet
当日の分は公式の当日 ZIP(cloud/nar_official_csv の部品・cloud/ai_last_today.py と同じ取り方)を重ねる(today()・overlay())。
⛔読むだけ。本番の表には書かない。
"""
import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'kochi'))
import k0_dl as K0  # noqa: E402

TR = '帯広ば'
RUN_SEL = ('track,race_date,race_no,runner_number,gate,horse_name,birth_date,sex,age,jockey,trainer,trainer_area,carried_weight,'
           'weight_mark,body_weight,finish,finish_note,time_sec,margin,last3f,popularity')
RACE_SEL = ('track,race_date,race_no,race_name,race_kind,surface,direction,distance_m,weather,going,field_size,condition,prize_yen,'
            'race_last3f,corners,cancelled')


def log(*a):
    print('[bn_dl]', *a, flush=True)


def by_month(table, sel, order, last):
    from concurrent.futures import ThreadPoolExecutor
    m = pd.period_range('2014-01', last[:7], freq='M')
    jobs = [(str(p.start_time.date()), min(str(p.end_time.date()), last)) for p in m]

    def one(j):
        a, b = j
        return K0.pages(f'/rest/v1/{table}?select={sel}&track=eq.{K0.q(TR)}&race_date=gte.{a}&race_date=lte.{b}&order={order}')
    rows = []
    with ThreadPoolExecutor(6) as ex:
        for r in ex.map(one, jobs):
            rows += r
    return pd.DataFrame(rows)


def fetch(root, day):
    """帯広ばの runs・races(2014-01〜その日)と profiles(全部)。"""
    o = Path(root) / 'official'
    o.mkdir(parents=True, exist_ok=True)
    # ⛔order= は一意の列の組(月の中で日付を入れないと、ページの切れ目で行が重なったり抜けたりする = 10/28 の試しの便で落ちた)
    ru = by_month('nar_runs', RUN_SEL, 'race_date,race_no,runner_number', day)
    ra = by_month('nar_races', RACE_SEL, 'race_date,race_no', day)
    for name, x, k in (('runs', ru, ['race_date', 'race_no', 'runner_number']), ('races', ra, ['race_date', 'race_no'])):
        dup = int(x.duplicated(k).sum())
        if dup:
            raise SystemExit(f'⛔{name} に同じ行が {dup} 本(取り方の誤り)= 止まる')
    pr = K0.whole('nar_horse_profiles', 'horse_name,birth_date')
    ru.to_parquet(o / 'runs.parquet', index=False); ra.to_parquet(o / 'races.parquet', index=False); pr.to_parquet(o / 'profiles.parquet', index=False)
    log('runs', len(ru), 'races', len(ra), 'profiles', len(pr), '最後の日', ru.race_date.max())
    return ru, ra


def refresh_day(root, day):
    """直前の周: 手元の runs・races の当日の行だけ REST から取り直す(取消・除外・体重の更新を拾う)。"""
    o = Path(root) / 'official'
    ru = pd.read_parquet(o / 'runs.parquet'); ra = pd.read_parquet(o / 'races.parquet')
    nu = pd.DataFrame(K0.pages(f'/rest/v1/nar_runs?select={RUN_SEL}&track=eq.{K0.q(TR)}&race_date=eq.{day}&order=race_no,runner_number'))
    na = pd.DataFrame(K0.pages(f'/rest/v1/nar_races?select={RACE_SEL}&track=eq.{K0.q(TR)}&race_date=eq.{day}&order=race_no'))
    if nu.empty or na.empty:
        log('当日の行が REST に無い = 手元のまま'); return
    for new, old in ((nu, ru), (na, ra)):     # 空の列(体重がまだ等)も数の列のまま
        for c in new.columns:
            if c in old and old[c].dtype.kind in 'fi':
                new[c] = pd.to_numeric(new[c], errors='coerce').astype(float if new[c].isna().any() or old[c].dtype.kind == 'f' else old[c].dtype)
    ru = pd.concat([ru[ru.race_date.astype(str) != day], nu], ignore_index=True)
    ra = pd.concat([ra[ra.race_date.astype(str) != day], na], ignore_index=True)
    ru.to_parquet(o / 'runs.parquet', index=False); ra.to_parquet(o / 'races.parquet', index=False)
    log('当日の行を取り直した', len(nu), '頭', len(na), 'R')


def need_zip(root, day, now=None, lo=15, hi=120):
    """公式に負荷をかけない: 1R の水分が空か、発走まで lo〜hi 分で取消でない馬の体重が空のレースがある時だけ ZIP を取る。"""
    o = Path(root) / 'official'
    ru = pd.read_parquet(o / 'runs.parquet'); ra = pd.read_parquet(o / 'races.parquet')
    ru = ru[ru.race_date.astype(str) == day]; ra = ra[ra.race_date.astype(str) == day]
    if ra.empty:
        return False
    if going_num(ra.sort_values('race_no').going.iloc[0]) is None:
        return True
    now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    miss = set(ru[ru.body_weight.isna() & ru.finish_note.fillna('').str.strip().eq('')].race_no.astype(int))
    for r, (pt, _g) in post_times(day).items():
        m = re.fullmatch(r'(\d{1,2}):?(\d{2})', str(pt or '').strip())
        if r in miss and m:
            at = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(int(m.group(1)), int(m.group(2))), now.tzinfo)
            if lo <= (at - now).total_seconds() / 60 <= hi:
                return True
    return False


def going_num(s):
    """'1.5' / '1.5%' / '水分1.5' → 1.5。読めなければ None"""
    m = re.search(r'\d+(?:\.\d+)?', str(s or ''))
    return float(m.group(0)) if m else None


def post_times(day):
    rs = K0.sb.get(f'/rest/v1/nar_races?select=race_no,post_time,going&track=eq.{K0.q(TR)}&race_date=eq.{day}&order=race_no&limit=50')
    return {int(r['race_no']): (r.get('post_time'), r.get('going')) for r in rs}


def today(day):
    """公式の当日 ZIP → 帯広ばの (体重 {(R, 馬番): (体重, 増減)}, 水分 {R: '1.5'}, 発走 {R: '1450'})。取れなければ空。"""
    sys.path.insert(0, str(HERE.parents[2] / 'cloud'))
    try:
        from nar_official_csv import download_archive, download_url, normalize_archive
        url = download_url('race', scope='daily', race_date=day)
        payload, final_url = download_archive(url, timeout=60)
        doc = normalize_archive(payload, kind='race', scope='daily', source_url=final_url,
                                observed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    except Exception as e:  # noqa: BLE001
        log('当日 ZIP の取得失敗', type(e).__name__, str(e)[:120])
        return {}, {}, {}
    bw, go, pt = {}, {}, {}
    for h in doc.get('horses') or []:
        if h.get('track') == TR and str(h.get('race_date'))[:10] == day and h.get('body_weight') is not None:
            bw[(int(h['race_no']), int(h['runner_number']))] = (float(h['body_weight']), h.get('body_weight_change'))
    for r in doc.get('races') or []:
        if r.get('track') == TR and str(r.get('race_date'))[:10] == day:
            g = going_num(r.get('going'))
            if g is not None:
                go[int(r['race_no'])] = f'{g:g}'
            if r.get('post_time'):
                pt[int(r['race_no'])] = r['post_time']
    log('当日 ZIP: 体重', len(bw), '頭・水分', go, '・発走', len(pt), 'R')
    return bw, go, pt


def overlay(root, day, bw, go):
    """手元の runs・races の当日の行に、ZIP の体重と水分を重ねる(空で上書きしない)。"""
    o = Path(root) / 'official'
    ru = pd.read_parquet(o / 'runs.parquet'); ra = pd.read_parquet(o / 'races.parquet')
    ru['race_date'] = ru.race_date.astype(str); ra['race_date'] = ra.race_date.astype(str)
    n = 0
    for (r, u), (w, _c) in bw.items():
        m = (ru.race_date == day) & (ru.race_no == r) & (ru.runner_number == u)
        if m.any():
            ru.loc[m, 'body_weight'] = w; n += int(m.sum())
    for r, g in go.items():
        ra.loc[(ra.race_date == day) & (ra.race_no == r), 'going'] = g
    ru.to_parquet(o / 'runs.parquet', index=False); ra.to_parquet(o / 'races.parquet', index=False)
    log('重ねた: 体重', n, '頭・水分', len(go), 'R')


def zip_step(root, day):
    """取った ZIP の体重・水分は置き場に溜め(official/zip_DAY.json)、当日の行を取り直した後も毎回重ね直す。"""
    import json
    f = Path(root) / 'official' / f'zip_{day}.json'
    c = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {'bw': {}, 'go': {}}
    _apply(root, day, c)
    if need_zip(root, day):
        bw, go, _ = today(day)
        c['bw'].update({f'{r}_{u}': v[0] for (r, u), v in bw.items()}); c['go'].update({str(r): g for r, g in go.items()})
        f.write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')
        _apply(root, day, c)


def _apply(root, day, c):
    bw = {(int(k.split('_')[0]), int(k.split('_')[1])): (v, None) for k, v in c['bw'].items()}
    go = {int(k): v for k, v in c['go'].items()}
    if bw or go:
        overlay(root, day, bw, go)


if __name__ == '__main__':
    a = sys.argv[1:]
    fetch(a[0], a[1] if len(a) > 1 else dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat())
