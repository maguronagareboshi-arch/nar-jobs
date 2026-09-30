# -*- coding: utf-8 -*-
"""南関 AI v3 の買う層「市場のずれ模型 v29」(nankan-ai-v3 src/v29_final.py で学んだ模型を読むだけ・学習はしない)。

予想の AI(第 9 版)はオッズを見ない。この層だけがオッズを使い、「市場の勝つ率 → 実際」のずれを足して単勝の買い候補を出す。
  買い候補 = AI の 3 着以内の率 p3′ ≥ 0.05 かつ 期待値(模型の勝つ率 × その時の単勝オッズ)≥ 1.00。

  1) 前日(nar-ai-v3 の便の中・v3_daily.py から): base(day, h, T, F, table_csv) → OUT/DAY_v29_base.csv
     = 馬ごとの AI の率・理由の列 33・体重の履歴(平常体重・好走時の体重・前走)。当日の体重とオッズは入れない。
  2) 当日(v3-gap-live の便): python -X utf8 pipeline/ai/v3/v29_gap.py live DAY BASE_CSV MODEL_DIR [--write] [--until HH:MM]
     各レースの締め切り(発走 2 分前)の 8 分前 = 発走 10 分前を過ぎたら 1 回だけ、
     その時点の単勝オッズ(nar_odds_ticks の最新)・公式の当日の体重と馬場で材料を作り、候補を決める。
     --write のときだけ nar_meta に key = 'v3_gap:DAY:場:R' で upsert(レースごとに別の key = 2 本の便が重なっても壊れない)。
     ⛔公開 repo のログに候補(馬番・オッズ)は出さない。出すのは件数だけ。
  3) 検算(手元): python -X utf8 pipeline/ai/v3/v29_gap.py replay DAY BASE_CSV MODEL_DIR ODDS_CSV WEIGHTS_CSV
     = 与えたオッズ・体重で同じ計算をして表を出す(研究側の予想と照合する用)。

材料の定義は nankan-ai-v3 の src/v27_mkt_gap.py(market・FE)と src/v27_bw_feat.py(F1〜F11・G1〜G5)に合わせる。
違い(本番で避けられないもの): 人気の順位 rp は確定の人気ではなくその時のオッズの順(同じなら馬番の若い順)。
AI の率は出走する馬(オッズのある馬)だけで p1 を合計 1・p3′ を合計 3 に戻す。
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
JST = dt.timezone(dt.timedelta(hours=9))
KEY = ['track', 'race_date', 'race_no']
Q5 = KEY + ['umaban']
NANKAN = ['大井', '船橋', '川崎', '浦和']
XCOL = ['c_fin1', 'c_fin5', 'c_top3_5', 'a_si1', 'a_ab', 'k_si_rank', 'k_ab_rank', 'a_tdiff1', 'a_up1', 'p_mis1', 'g_rest',
        'b_gchg', 'b_lvchg', 'h_chg', 'h_j3', 'h_jrank', 'i_t3', 'j_umaban', 'j_gate', 'd_chg', 'g_age', 'g_sex',
        'g_starts', 'l_debut', 'l_jra', 'l_nar']
CY6 = ['cy_day_pct', 'cy_self', 'cy_stable', 'cy_int', 'cy_n14', 'cy_gap']
HIST = ['bw_norm', 'BEST', 'PREVW', 'PREVF', 'PREVD']
MODEL_FILE, META_FILE = 'v29_gap_y1.txt', 'v29_gap.json'
DECIDE_MIN = 10   # 発走 10 分前 = 締め切り(発走 2 分前)の 8 分前を過ぎたら決める
LATE_MIN = 3      # 発走 3 分前を過ぎても決まっていないレースは見送る(古い材料で後から書かない)


def log(*a):
    print('[v29]', *a, flush=True)


def _nk(d):
    d = d.copy()
    d['race_date'] = d.race_date.astype(str).str[:10]
    d['race_no'] = pd.to_numeric(d.race_no).astype(int)
    if 'umaban' in d.columns:
        d['umaban'] = pd.to_numeric(d.umaban).astype(int)
    return d


# ================================================================ 1) 前日: 馬ごとの土台
def bw_hist(h, day, hids):
    """その日の馬(hids)の、day より前の走りから 平常体重(直近 5 走の平均・2 走以上)・好走時(3 着内・3 年以内)の体重の平均・
    前走の体重/着/間隔(日)。v27_bw_feat.py の h2 の作りと同じ(その日の行の 1 つ前までを見る)。"""
    x = h.loc[h.hid.isin(hids) & (h.race_date.astype(str).str[:10] < day),
              ['hid', 'race_date', 'race_no', 'track', 'body_weight', 'finish']].copy()
    x['bw'] = pd.to_numeric(x.body_weight, errors='coerce').where(lambda s: s > 0)
    x['fin'] = pd.to_numeric(x.finish, errors='coerce')
    x['dn'] = pd.to_datetime(x.race_date.astype(str).str[:10]).values.astype('datetime64[D]').astype(np.int64)
    x = x.sort_values(['hid', 'dn'], kind='mergesort').drop_duplicates(['hid', 'race_date', 'race_no', 'track'])
    dn0 = int(np.datetime64(day, 'D').astype(np.int64))
    out = {}
    for hid, g in x.groupby('hid', sort=False):
        bw, fin, dn = g.bw.to_numpy(float), g.fin.to_numpy(float), g.dn.to_numpy(float)
        last5 = bw[-5:]
        ok = ~np.isnan(last5)
        m = (fin >= 1) & (fin <= 3) & (dn0 - dn <= 1095) & ~np.isnan(bw)
        out[hid] = dict(bw_norm=last5[ok].mean() if ok.sum() >= 2 else np.nan,
                        BEST=bw[m].mean() if m.any() else np.nan,
                        PREVW=bw[-1], PREVF=fin[-1], PREVD=float(dn0 - dn[-1]))
    r = pd.DataFrame.from_dict(out, orient='index', columns=HIST)
    r.index.name = 'hid'
    return r.reset_index()


def base(day, h, T, F, table_csv):
    """前日の表(p1・p3′・印)+ 理由の列 + 調教 6 列 + 体重の履歴 → 1 馬 1 行。"""
    x = _nk(pd.read_csv(table_csv, encoding='utf-8-sig'))[Q5 + ['horse_name', 'n', 'p1', 'p3p']]
    t = _nk(T[T.race_date.astype(str).str[:10] == day])[Q5 + XCOL].drop_duplicates(Q5)
    f = _nk(F)[Q5 + CY6].drop_duplicates(Q5) if F is not None and len(F) else pd.DataFrame(columns=Q5 + CY6)
    d = _nk(h[(h.race_date.astype(str).str[:10] == day) & h.track.isin(NANKAN)])
    d = d[Q5 + ['hid', 'age', 'sex', 'carried_weight', 'distance_m']].drop_duplicates(Q5, keep='last')
    b = x.merge(t, on=Q5, how='left', validate='1:1').merge(f, on=Q5, how='left', validate='1:1')
    b = b.merge(d, on=Q5, how='left', validate='1:1')
    b['si_ab'] = b.a_si1 - b.a_ab
    b = b.merge(bw_hist(h, day, set(b.hid.dropna())), on='hid', how='left')
    return b.drop(columns=['hid'])


# ================================================================ 2) 当日: 材料と候補
def feats(B, odds, wt, going):
    """B = base の 1 レース分。odds = {馬番: 単勝}・wt = {馬番: (体重, 増減)}・going = 馬場。オッズのある馬だけ残す。"""
    b = B.copy()
    b['win'] = b.umaban.map(lambda u: odds.get(int(u)))
    b = b[b.win.notna() & (b.win > 0)].copy()
    if len(b) < 2:
        return b.iloc[0:0]
    b['p1'] = b.p1 / b.p1.sum()
    b['p3p'] = 3 * b.p3p / b.p3p.sum() if len(b) > 3 else b.p3p
    b['n'] = len(b)
    b = b.sort_values(['p3p', 'p1', 'umaban'], ascending=[False, False, True], kind='mergesort')
    b['rk'] = np.arange(1, len(b) + 1)
    b = b.sort_values(['win', 'umaban'], kind='mergesort')
    b['rp'] = np.arange(1, len(b) + 1)
    b = b.sort_values('umaban').reset_index(drop=True)
    m = 1 / b.win
    b['q'] = m / m.sum()
    b['lq'] = np.log(b.q)
    b['lp1'] = np.log(b.p1.clip(lower=1e-4))
    b['gap'] = b.lp1 - b.lq
    # 体重 15 列(v27_bw_feat.py と同じ式)
    b['bw'] = b.umaban.map(lambda u: (wt.get(int(u)) or (None, None))[0]).astype(float)
    b['bwd'] = b.umaban.map(lambda u: (wt.get(int(u)) or (None, None))[1]).astype(float)
    b['bw'] = b.bw.where(b.bw > 0)
    cw = pd.to_numeric(b.carried_weight, errors='coerce')
    age = pd.to_numeric(b.age, errors='coerce')
    dist = pd.to_numeric(b.distance_m, errors='coerce')
    rel = b.bw - b.bw.mean()
    b['F1'] = rel
    b['F2'] = rel / b.bw.std()
    b['F3'] = b.bw.rank(pct=True)
    b['F4'] = b.bw - b.bw_norm
    b['F5'] = b.bwd
    b['F6'] = rel * (dist <= 1200)
    b['F7'] = rel * (age <= 2)
    b['F8'] = rel * (going in ('重', '不良'))
    b['F9'] = np.where(age <= 2, np.where(b.sex == '牝', 1.0, np.where(b.sex == '牡', -1.0, 0.0)), 0.0)
    b['F10'] = b.bw / cw
    b['F11'] = rel * (b.sex == '牝')
    dnow = b.bw - b.BEST
    dprev = (b.PREVW - b.BEST).where(b.PREVD <= 120)
    b['G1'] = dnow
    b['G2'] = dnow.abs()
    b['G3'] = dprev.abs() - dnow.abs()
    b['G4'] = b.G3 * (b.PREVF >= 4)
    b['G5'] = b.G3.where((b.PREVF >= 4) & (dprev.abs() >= 8))
    return b


def load_model(mdir):
    import lightgbm as lgb
    meta = json.loads((Path(mdir) / META_FILE).read_text(encoding='utf-8'))
    return lgb.Booster(model_str=(Path(mdir) / MODEL_FILE).read_text(encoding='utf-8')), meta


def score(b, model, meta):
    """模型の勝つ率 pg1(レース内で合計 1)・期待値 ev・候補の印 buy。"""
    X = b[meta['features']].astype(float)
    q = b.q.clip(1e-4, 1 - 1e-4).to_numpy()
    z = np.log(q / (1 - q)) + model.predict(X, raw_score=True)
    p = 1 / (1 + np.exp(-z))
    b = b.copy()
    b['pg1'] = p / p.sum()
    b['ev'] = b.pg1 * b.win
    b['buy'] = (b.p3p >= meta['p3_min']) & (b.ev >= meta['line'])
    return b


def decide(B, odds, wt, going, model, meta):
    b = feats(B, odds, wt, going)
    return score(b, model, meta) if len(b) else b


# ================================================================ 本番の読み書き(REST・読むのは公開の表・書くのは nar_meta だけ)
def _req(path, method='GET', body=None):
    base, key = os.environ['SUPABASE_URL'].rstrip('/'), os.environ['SUPABASE_SERVICE_KEY']
    r = urllib.request.Request(base + path, method=method, data=body, headers={
        'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates,return=minimal'})
    with urllib.request.urlopen(r, timeout=60) as x:
        return x.status, x.read().decode('utf-8')


def _get(path):
    return json.loads(_req(path)[1])


def races_of(day):
    q = urllib.parse.quote(','.join(NANKAN))
    return _get(f'/rest/v1/nar_races?race_date=eq.{day}&track=in.({q})&select=track,race_no,post_time,going,cancelled')


def latest_odds(track, day, rno):
    t = urllib.parse.quote(track)
    r = _get(f'/rest/v1/nar_odds_ticks?track=eq.{t}&race_date=eq.{day}&race_no=eq.{rno}&f=eq.false'
             '&select=id,t,asof,w&order=id.desc&limit=1')
    if not r:
        return None, None
    w = r[0].get('w') or {}
    return {int(k): float(v) for k, v in w.items() if v not in (None, '') and float(v) > 0}, r[0].get('asof') or r[0].get('t')


def exists(key):
    return bool(_get(f"/rest/v1/nar_meta?key=eq.{urllib.parse.quote(key)}&select=key"))


def done_keys(day):
    r = _get(f"/rest/v1/nar_meta?key=like.{urllib.parse.quote(f'v3_gap:{day}:')}*&select=key")
    return {x['key'] for x in r}


def put_meta(key, value):
    body = json.dumps([{'key': key, 'value': value, 'updated_at': dt.datetime.now(dt.timezone.utc).isoformat()}],
                      ensure_ascii=False).encode('utf-8')
    st, _ = _req('/rest/v1/nar_meta?on_conflict=key', 'POST', body)
    return st


def official_today(day):
    """公式の当日 ZIP(refresh.py・ai_last_today.py と同じ部品)→ ({(場, R): {馬番: (体重, 増減)}}, {(場, R): 馬場})"""
    sys.path.insert(0, str(HERE.parents[2] / 'cloud'))
    from nar_official_csv import download_archive, download_url, normalize_archive
    url = download_url('race', scope='daily', race_date=day)
    payload, final_url = download_archive(url, timeout=60)
    doc = normalize_archive(payload, kind='race', scope='daily', source_url=final_url,
                            observed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    wt, go = {}, {}
    for h in doc.get('horses') or []:
        if str(h.get('race_date') or '')[:10] == day and h.get('body_weight') is not None:
            wt.setdefault((h['track'], int(h['race_no'])), {})[int(h['runner_number'])] = (
                h['body_weight'], h.get('body_weight_change'))
    for r in doc.get('races') or []:
        if str(r.get('race_date') or '')[:10] == day and r.get('going'):
            go[(r['track'], int(r['race_no']))] = r['going']
    return wt, go


def post_at(day, pt):
    s = str(pt or '').replace(':', '').strip()
    if len(s) not in (3, 4) or not s.isdigit():
        return None
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(int(s[:-2]), int(s[-2:])), JST)


def live(day, base_csv, mdir, write, until):
    model, meta = load_model(mdir)
    B = _nk(pd.read_csv(base_csv, encoding='utf-8-sig'))
    end = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(*map(int, until.split(':'))), JST)
    log('day', day, 'base', len(B), '頭', B[KEY].drop_duplicates().shape[0], 'R', 'write', write, 'until', until)
    done = done_keys(day) if write else set()
    wt, go, wt_at = {}, {}, None
    n_w = n_buy = 0
    while True:
        now = dt.datetime.now(JST)
        try:
            races = [r for r in races_of(day) if not str(r.get('cancelled') or '').strip()]
        except Exception as e:  # noqa: BLE001  読めない回は飛ばす(次の回で読み直す)
            log('nar_races: 読めない', type(e).__name__)
            time.sleep(20)
            continue
        todo = []
        for r in races:
            at = post_at(day, r.get('post_time'))
            k = f"v3_gap:{day}:{r['track']}:{int(r['race_no'])}"
            if at is None or k in done or at > end + dt.timedelta(minutes=DECIDE_MIN):
                continue
            mins = (at - now).total_seconds() / 60
            if mins < LATE_MIN:
                done.add(k)
                continue
            todo.append((mins, r, k, at))
        if not todo:
            log('終わり: 書いた', n_w, 'R・候補', n_buy, '頭')
            return 0
        due = [x for x in todo if x[0] <= DECIDE_MIN]
        if due:
            need = [x for x in due if len(wt.get((x[1]['track'], int(x[1]['race_no'])), {})) == 0]
            if need and (wt_at is None or (now - wt_at).total_seconds() > 120):
                try:
                    wt, go = official_today(day)
                except Exception as e:  # noqa: BLE001  取れなければ体重なしで決める(模型は欠けを扱える)
                    log('公式の当日 ZIP: 失敗', type(e).__name__)
                wt_at = now
            for mins, r, k, at in due:
                tr, rno = r['track'], int(r['race_no'])
                try:
                    if write and exists(k):  # もう 1 本の便が先に決めた
                        done.add(k)
                        continue
                    odds, asof = latest_odds(tr, day, rno)
                except Exception as e:  # noqa: BLE001
                    log(f'{tr}{rno}R: 読めない {type(e).__name__}(次の回)')
                    continue
                Bk = B[(B.track == tr) & (B.race_no == rno)]
                if not odds or Bk.empty:
                    log(f'{tr}{rno}R: オッズか土台が無い(見送り)')
                    done.add(k)
                    continue
                w = wt.get((tr, rno), {})
                b = decide(Bk, odds, w, go.get((tr, rno)) or r.get('going') or '', model, meta)
                if b.empty:
                    done.add(k)
                    continue
                c = b[b.buy]
                val = {'model': 'v29', 'line': meta['line'], 'p3_min': meta['p3_min'], 'post': at.strftime('%H:%M'),
                       'decided_at': now.strftime('%H:%M:%S'), 'odds_asof': asof, 'n': int(len(b)),
                       'weights': int(b.bw.notna().sum()),
                       'buy': [{'num': int(x.umaban), 'name': x.horse_name, 'odds': float(x.win),
                                'ev': round(float(x.ev), 3), 'pg1': round(float(x.pg1), 4), 'q': round(float(x.q), 4),
                                'p3': round(float(x.p3p), 4)} for x in c.itertuples()],
                       'runners': [{'num': int(x.umaban), 'odds': float(x.win), 'pg1': round(float(x.pg1), 4),
                                    'ev': round(float(x.ev), 3)} for x in b.itertuples()]}
                try:
                    st = put_meta(k, val) if write else 'dry'
                except Exception as e:  # noqa: BLE001
                    log(f'{tr}{rno}R: 書けない {type(e).__name__}(次の回)')
                    continue
                done.add(k)
                n_w += 1
                n_buy += len(c)
                log(f'{tr}{rno}R: 発走 {at:%H:%M}・{now:%H:%M:%S} に決めた・{len(b)} 頭(体重 {val["weights"]})'
                    f'・候補 {len(c)} 頭・書き込み {st}')
        if now > end:
            log('時間切れ: 書いた', n_w, 'R・候補', n_buy, '頭')
            return 0
        time.sleep(20)


# ================================================================ 3) 検算
def replay(day, base_csv, mdir, odds_csv, wt_csv, out_csv):
    """odds_csv = track,race_no,umaban,win・wt_csv = track,race_no,umaban,body_weight,body_weight_change,going"""
    model, meta = load_model(mdir)
    B = _nk(pd.read_csv(base_csv, encoding='utf-8-sig'))
    O = pd.read_csv(odds_csv, encoding='utf-8-sig')
    W = pd.read_csv(wt_csv, encoding='utf-8-sig')
    res = []
    for (tr, rno), Bk in B.groupby(['track', 'race_no'], sort=False):
        o = O[(O.track == tr) & (O.race_no == rno)]
        w = W[(W.track == tr) & (W.race_no == rno)]
        odds = {int(u): float(v) for u, v in zip(o.umaban, o.win) if v == v and v > 0}
        wt = {int(u): (a, c) for u, a, c in zip(w.umaban, w.body_weight, w.body_weight_change)}
        going = w.going.dropna().iloc[0] if 'going' in w and w.going.notna().any() else ''
        b = decide(Bk, odds, wt, going, model, meta)
        if len(b):
            res.append(b)
    R = pd.concat(res, ignore_index=True)
    R.to_csv(out_csv, index=False, encoding='utf-8-sig')
    log('replay', len(R), '頭・候補', int(R.buy.sum()))
    return R


def main():
    a = sys.argv[1:]
    if a[0] == 'live':
        until = a[a.index('--until') + 1] if '--until' in a else '21:15'
        return live(a[1], a[2], a[3], '--write' in a, until)
    if a[0] == 'replay':
        replay(*a[1:7])
        return 0
    raise SystemExit('live / replay')


if __name__ == '__main__':
    sys.exit(main())
