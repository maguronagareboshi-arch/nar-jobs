# -*- coding: utf-8 -*-
"""期待値の補正を「締切までの時間 × 単勝の倍率の帯」ごとに作り直す集計の材料集め。便 .github/workflows/ev-coef-time-audit.yml(手動だけ)。

  python3 cloud/ev_coef_time_audit.py --from 2026-09-02 --to 2026-10-24 [--out out/ev_coef_time_audit]

⛔読むだけ(REST の単純 select・日ごと)。nar_meta にも他の表にも書かない。⛔標準ライブラリだけ。
⛔公開 repo なので出力はレースの鍵(場・日・R・馬番)を落とした値の並びと件数だけ。repo には commit しない(成果物で受け取る)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。

定義: 勝ち馬(1 着が 1 頭だけのレース)について r = 単勝払戻 ÷ (時刻 t のその馬の単勝 × 100)。帯= 時刻 t の単勝で 5 帯。
刻みの時刻= asof(主催者の「HH:MM 現在」)が取得時刻 t の 0〜30 分前ならそれ・それ以外は t(cloud/ev_coef_audit.py と同じ)。
基準の時刻 2 通り: final= 確定の刻み(f=true の最大 id)の時刻・post= nar_races.post_time。
区分= 基準から何分前か m(0≤m)で [0,2) [2,5) [5,10) [10,20) [20,30) [30,60) [60,∞)・各区分でいちばん新しい刻み 1 つ。
  first= そのレースのいちばん古い刻み(確定以外)。確定の刻みは区分に使わない。
出力 agg.json: r[基準][区分][帯]= r の並び(小数 5 桁)・cov[基準][区分]= 刻みのあるレース数・選んだ刻みの m の合計・
  gaps[区分]= 続く 2 つの刻みの間隔(分)の度数(後ろの刻みの区分・基準 final)・races= 数えたレース数・fin_post= 確定の時刻 − 発走 の度数。
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "nar-jobs ev_coef_time_audit"
PAGE = 1000
BANDS = ((0, 3.0, '<3'), (3.0, 10.0, '3-9.9'), (10.0, 30.0, '10-29.9'), (30.0, 100.0, '30-99.9'), (100.0, 1e12, '>=100'))
SEGS = (('0-2', 0, 2), ('2-5', 2, 5), ('5-10', 5, 10), ('10-20', 10, 20), ('20-30', 20, 30), ('30-60', 30, 60), ('60+', 60, 10 ** 6))


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def req(base, key, path, tries=3):
    last = None
    for i in range(tries):
        r = urllib.request.Request(base + path, headers={"apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA})
        try:
            with urllib.request.urlopen(r, timeout=180) as x:
                return json.loads(x.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 or i == tries - 1:
                raise
            time.sleep(5)
        except urllib.error.URLError as e:
            last = e
            if i == tries - 1:
                raise
            time.sleep(5)
    raise last


def rows_by_id(base, key, path):
    out, last = [], None
    while True:
        c = req(base, key, path + "&order=id.asc&limit=%d" % PAGE + ("" if last is None else "&id=gt.%d" % last))
        out.extend(c)
        if len(c) < PAGE:
            return out
        last = c[-1]["id"]


def rows_offset(base, key, path):
    """⛔path の order= は一意にすること。"""
    out, off = [], 0
    while True:
        c = req(base, key, "%s&limit=%d&offset=%d" % (path, PAGE, off))
        out.extend(c)
        if len(c) < PAGE:
            return out
        off += PAGE


def hm(s):
    if s is None:
        return None
    s = str(s).strip()
    try:
        if ":" in s:
            h, m = s.split(":")[:2]
        elif len(s) in (3, 4) and s.isdigit():
            h, m = s[:-2], s[-2:]
        else:
            return None
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def band(o):
    return next(lab for lo, hi, lab in BANDS if lo <= o < hi)


def tick_min(r):
    t = hm(r.get("t"))
    a = hm(r.get("asof"))
    if t is not None and a is not None and 0 <= t - a <= 30:
        return a
    return t


def seg_of(m):
    for lab, lo, hi in SEGS:
        if lo <= m < hi:
            return lab
    return None


def add(h, k, n=1):
    h[k] = h.get(k, 0) + n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True)
    ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--out", default="out/ev_coef_time_audit")
    a = ap.parse_args()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    R = {ref: {} for ref in ("final", "post")}
    cov = {ref: {} for ref in ("final", "post")}
    races_n = {"final": 0, "post": 0}
    skip = {}
    gaps, fin_post = {}, {}
    day, d1 = dt.date.fromisoformat(a.d0), dt.date.fromisoformat(a.d1)
    while day <= d1:
        ds = day.isoformat()
        d = urllib.parse.quote(ds)
        races = rows_offset(base, key, "/rest/v1/nar_races?select=track,race_no,post_time&race_date=eq.%s&order=track.asc,race_no.asc" % d)
        runs = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_no,runner_number,finish&race_date=eq.%s"
                           "&order=track.asc,race_no.asc,runner_number.asc" % d)
        ticks = rows_by_id(base, key, "/rest/v1/nar_odds_ticks?select=id,track,race_no,t,asof,f,w&race_date=eq.%s" % d)
        pays = rows_offset(base, key, "/rest/v1/nar_race_payouts?select=track,race_no,payouts&race_date=eq.%s&order=track.asc,race_no.asc" % d)
        post = {(r["track"], int(r["race_no"])): hm(r.get("post_time")) for r in races}
        tk = {}
        for r in ticks:
            tk.setdefault((r["track"], int(r["race_no"])), []).append(r)
        pay = {}
        for p in pays:
            for x in p.get("payouts") or []:
                if isinstance(x, dict) and x.get("t") == "win":
                    try:
                        pay[(p["track"], int(p["race_no"]), int(x["c"]))] = float(x["y"])
                    except (TypeError, ValueError, KeyError):
                        pass
        win = {}
        for r in runs:
            try:
                if int(str(r.get("finish")).strip()) == 1:
                    win.setdefault((r["track"], int(r["race_no"])), []).append(int(r["runner_number"]))
            except (TypeError, ValueError):
                pass
        nr = 0
        for rk, trs in tk.items():
            ws = win.get(rk) or []
            if len(ws) != 1:
                add(skip, "winners_not1")
                continue
            u = ws[0]
            py = pay.get((rk[0], rk[1], u))
            if py is None:
                add(skip, "no_pay")
                continue
            mids = []
            for r in trs:
                if r.get("f") or not isinstance(r.get("w"), dict):
                    continue
                tm = tick_min(r)
                if tm is None:
                    continue
                mids.append((tm, r["id"], num(r["w"].get(str(u)))))
            if not mids:
                add(skip, "no_mid")
                continue
            mids.sort()
            fins = [r for r in trs if r.get("f")]
            refs = {}
            if fins:
                ft = tick_min(max(fins, key=lambda r: r["id"]))
                if ft is not None:
                    refs["final"] = ft
                    if post.get(rk) is not None:
                        add(fin_post, str(max(-30, min(30, ft - post[rk]))))
            if post.get(rk) is not None:
                refs["post"] = post[rk]
            if not refs:
                add(skip, "no_ref")
                continue
            nr += 1
            for ref, t0 in refs.items():
                races_n[ref] += 1
                pick = {}
                for tm, tid, o in mids:
                    m = t0 - tm
                    s = seg_of(m) if m >= 0 else None
                    if s is not None and (s not in pick or (tm, tid) > (pick[s][0], pick[s][1])):
                        pick[s] = (tm, tid, o, m)
                first = mids[0]
                if t0 - first[0] >= 0:
                    pick["first"] = (first[0], first[1], first[2], t0 - first[0])
                for s, (tm, tid, o, m) in pick.items():
                    c = cov[ref].setdefault(s, {"races": 0, "m_sum": 0, "no_odds": 0})
                    c["races"] += 1
                    c["m_sum"] += m
                    if o is None:
                        c["no_odds"] += 1
                        continue
                    R[ref].setdefault(s, {}).setdefault(band(o), []).append(round(py / (o * 100), 5))
            if "final" in refs:
                t0 = refs["final"]
                for (ta, _, _), (tb, _, _) in zip(mids, mids[1:]):
                    s = seg_of(t0 - tb) if t0 - tb >= 0 else None
                    if s is not None:
                        add(gaps.setdefault(s, {}), str(min(tb - ta, 61)))
        log("%s races %d" % (ds, nr))
        day += dt.timedelta(days=1)
    for ref in R:
        for s in R[ref]:
            for b in R[ref][s]:
                R[ref][s][b].sort()
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "agg.json"), "w", encoding="utf-8") as f:
        json.dump({"from": a.d0, "to": a.d1, "r": R, "cov": cov, "races": races_n, "skip": skip, "gaps": gaps, "fin_post": fin_post},
                  f, ensure_ascii=False, separators=(",", ":"))
    log("races %s skip %s" % (json.dumps(races_n), json.dumps(skip)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
