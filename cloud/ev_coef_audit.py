# -*- coding: utf-8 -*-
"""期待値の補正(nar_meta ev_coef:v1)の監査用の材料を本番 DB から集める研究便。便 .github/workflows/ev-coef-audit.yml(手動だけ)。

  python3 cloud/ev_coef_audit.py --from 2026-09-01 --to 2026-10-24 [--out out/ev_coef_audit]

⛔読むだけ(REST の単純 select・日ごと)。nar_meta にも他の表にも書かない。⛔標準ライブラリだけ。
⛔公開 repo なので出力はレースの鍵(場・日・R・馬番)を落とした集計だけ。repo には commit しない(成果物で受け取る)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。

o10 の取り方(pipeline/ai/odds_hist.py の pick10 と同じ考え): その馬の 10 分前の単勝= nar_odds_ticks のうち
  時刻 ≤ 発走(nar_races.post_time)−10 分 でいちばん遅い刻みの w[馬番]。時刻= asof(主催者の「HH:MM 現在」)が
  取得時刻 t の 0〜30 分前ならそれ・それ以外は t(nar-viewer js/data.js tickAsof と同じ)。0 以下・空は無し。
確定の単勝= f=true の最大 id の刻みの w。払戻= nar_race_payouts の t='win'。勝ち= nar_runs.finish が 1。
AI の 1 着見込み= nar_ai_marks(model='base-v1')の meta.p_win(較正後)。timing は last があれば last・無ければ morning。

出力 agg.json:
  cov[月]= 件数(レース・発走時刻あり・刻みあり・o10 あり・確定あり・払戻あり・勝ち馬で o10 と払戻あり・p_win あり)と
           選んだ刻みの「発走の何分前か」の分布・asof を使った刻みの数
  win[月][帯]= 勝ち馬の 払戻 ÷ (o10×100) の値の並び(小数 5 桁・昇順)
  winfin[月][帯]= 勝ち馬の 確定単勝 ÷ o10(小数 4 桁の度数)・allfin[月][帯]= 全出走馬の 確定単勝 ÷ o10(同)
  bets= [月, 南関か, o10, p_win, 勝ち, 払戻] の並び(p_win と o10 がある馬だけ・p_win の昇順)
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

UA = "nar-jobs ev_coef_audit"
PAGE = 1000
BANDS = ((0, 3.0, '<3'), (3.0, 10.0, '3-9.9'), (10.0, 30.0, '10-29.9'), (30.0, 100.0, '30-99.9'), (100.0, 1e12, '>=100'))
NANKAN = {'浦和', '船橋', '大井', '川崎'}
MODEL = 'base-v1'


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
    """刻みの時刻(分)と asof を使ったか。"""
    t = hm(r.get("t"))
    a = hm(r.get("asof"))
    if t is not None and a is not None and 0 <= t - a <= 30:
        return a, True
    return t, False


def fetch_day(base, key, day):
    d = urllib.parse.quote(day)
    races = rows_offset(base, key, "/rest/v1/nar_races?select=track,race_no,post_time&race_date=eq.%s&order=track.asc,race_no.asc" % d)
    runs = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_no,runner_number,finish&race_date=eq.%s"
                       "&order=track.asc,race_no.asc,runner_number.asc" % d)
    ticks = rows_by_id(base, key, "/rest/v1/nar_odds_ticks?select=id,track,race_no,t,asof,f,w&race_date=eq.%s" % d)
    pays = rows_offset(base, key, "/rest/v1/nar_race_payouts?select=track,race_no,payouts&race_date=eq.%s&order=track.asc,race_no.asc" % d)
    marks = rows_offset(base, key, "/rest/v1/nar_ai_marks?select=track,race_no,timing,pw:meta->p_win&model=eq.%s&race_date=eq.%s"
                        "&order=track.asc,race_no.asc,timing.asc" % (MODEL, d))
    return races, runs, ticks, pays, marks


def new_cov():
    return {"races": 0, "post": 0, "ticks": 0, "o10_race": 0, "final_race": 0, "pay_race": 0, "runners": 0,
            "o10_runner": 0, "winners": 0, "win_o10_pay": 0, "pw_race": 0, "pw_o10_runner": 0, "asof_used": 0,
            "gap": {}}


def add_hist(h, k):
    h[k] = h.get(k, 0) + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True)
    ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--out", default="out/ev_coef_audit")
    a = ap.parse_args()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    d0, d1 = dt.date.fromisoformat(a.d0), dt.date.fromisoformat(a.d1)
    cov, win, winfin, allfin, bets = {}, {}, {}, {}, []
    day = d0
    while day <= d1:
        ds = day.isoformat()
        ym = ds[:7]
        races, runs, ticks, pays, marks = fetch_day(base, key, ds)
        c = cov.setdefault(ym, new_cov())
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
        payrace = {(p["track"], int(p["race_no"])) for p in pays if any(isinstance(x, dict) and x.get("t") == "win" for x in (p.get("payouts") or []))}
        pw = {}
        for m in marks:
            k = (m["track"], int(m["race_no"]))
            if not isinstance(m.get("pw"), dict) or not m["pw"]:
                continue
            if k not in pw or m.get("timing") == "last":
                pw[k] = m["pw"]
        byrace = {}
        for r in runs:
            byrace.setdefault((r["track"], int(r["race_no"])), []).append(r)
        nday = 0
        for k, rs in byrace.items():
            c["races"] += 1
            pm = post.get(k)
            if k in pw:
                c["pw_race"] += 1
            if k in payrace:
                c["pay_race"] += 1
            if pm is None:
                continue
            c["post"] += 1
            trs = tk.get(k) or []
            if not trs:
                continue
            c["ticks"] += 1
            best = None
            for r in trs:
                if r.get("f") or not isinstance(r.get("w"), dict) or not r["w"]:
                    continue
                m, used = tick_min(r)
                if m is None or m > pm - 10:
                    continue
                if best is None or (m, r["id"]) > (best[0], best[1]["id"]):
                    best = (m, r, used)
            fins = [r for r in trs if r.get("f") and isinstance(r.get("w"), dict)]
            fw = max(fins, key=lambda r: r["id"])["w"] if fins else None
            if fw:
                c["final_race"] += 1
            if best is None:
                continue
            c["o10_race"] += 1
            if best[2]:
                c["asof_used"] += 1
            g = pm - best[0]
            add_hist(c["gap"], "10-11" if g <= 11 else "12-15" if g <= 15 else "16-30" if g <= 30 else "31+")
            w10 = best[1]["w"]
            for r in rs:
                u = int(r["runner_number"])
                c["runners"] += 1
                o10 = num(w10.get(str(u)))
                if o10 is None:
                    continue
                c["o10_runner"] += 1
                b = band(o10)
                try:
                    y = 1 if int(str(r.get("finish")).strip()) == 1 else 0
                except (TypeError, ValueError):
                    y = 0
                fo = num(fw.get(str(u))) if fw else None
                py = pay.get((k[0], k[1], u))
                if fo is not None:
                    add_hist(allfin.setdefault(ym, {}).setdefault(b, {}), "%.4f" % (fo / o10))
                if y:
                    c["winners"] += 1
                    if py is not None:
                        c["win_o10_pay"] += 1
                        win.setdefault(ym, {}).setdefault(b, []).append(round(py / (o10 * 100), 5))
                    if fo is not None:
                        add_hist(winfin.setdefault(ym, {}).setdefault(b, {}), "%.4f" % (fo / o10))
                if k in pw:
                    p = pw[k].get(str(u))
                    try:
                        p = float(p)
                    except (TypeError, ValueError):
                        p = None
                    if p is not None:
                        c["pw_o10_runner"] += 1
                        bets.append([ym, 1 if k[0] in NANKAN else 0, o10, round(p, 4), y, py if (y and py is not None) else 0])
            nday += 1
        log("%s races %d (o10 あり %d)" % (ds, len(byrace), nday))
        day += dt.timedelta(days=1)
    for ym in win:
        for b in win[ym]:
            win[ym][b].sort()
    bets.sort(key=lambda x: (x[3], x[2]))
    os.makedirs(a.out, exist_ok=True)
    out = {"from": a.d0, "to": a.d1, "model": MODEL, "cov": cov, "win": win, "winfin": winfin, "allfin": allfin, "bets": bets}
    with open(os.path.join(a.out, "agg.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    for ym in sorted(cov):
        x = cov[ym]
        log("COV %s races %d post %d ticks %d o10 %d final %d pay %d winners(o10&pay) %d pw_race %d" % (
            ym, x["races"], x["post"], x["ticks"], x["o10_race"], x["final_race"], x["pay_race"], x["win_o10_pay"], x["pw_race"]))
    log("bets rows %d" % len(bets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
