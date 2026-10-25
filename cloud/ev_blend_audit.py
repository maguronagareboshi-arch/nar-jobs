# -*- coding: utf-8 -*-
"""AI の 1 着見込みと市場(10 分前の単勝から逆算)を混ぜたときの検証(Benter 1994 型)。便 .github/workflows/ev-blend-audit.yml(手動だけ)。

  python3 cloud/ev_blend_audit.py --from 2026-09-08 --to 2026-10-24 [--out out/ev_blend_audit]

⛔読むだけ(REST の単純 select・日ごと)。nar_meta にも他の表にも書かない。⛔標準ライブラリだけ。
⛔公開 repo なので出力は集計表だけ(レースの鍵・馬ごとの値は出さない)。repo には commit しない(成果物で受け取る)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。

対象= nar_ai_marks の base-v1(meta.p_win)・v3n-1 と v3-9(meta.runners[].p1)。timing は last があれば last・無ければ morning(数を表に出す)。
o10= cloud/ev_coef_audit.py と同じ(発走−10 分以前の最後の刻み・時刻は asof が t の 0〜30 分前ならそれ)。
数えるレース= 1 着が 1 頭だけ・その馬に o10 と見込みと単勝払戻がある。馬= o10 と見込みがある馬(見込みはその中で合計 1 に直す)。
市場 q= (1/o10) をレース内で合計 1。混ぜた c ∝ exp(α·log p + β·log q)(レース内で合計 1)。α・β はレースごとの条件付きロジットの最尤(ニュートン法)。
モデルごとに日付で前半(レース数で半分まで)で α・β を決め、後半で評価。参考に全期間の α・β も。
期待値= 確率 × o10 × 補正(ev_coef:v1 の今の値)≥ 1 を単勝 100 円ずつ。
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "nar-jobs ev_blend_audit"
PAGE = 1000
BANDS = ((0, 3.0, '<3'), (3.0, 10.0, '3-9.9'), (10.0, 30.0, '10-29.9'), (30.0, 100.0, '30-99.9'), (100.0, 1e12, '>=100'))
BLAB = [b[2] for b in BANDS]
COEF = {'<3': 0.9474, '3-9.9': 0.8537, '10-29.9': 0.9008, '30-99.9': 1.0048, '>=100': 0.9984}   # ev_coef:v1(asof 2026-08-31)
MODELS = ('base-v1', 'v3n-1', 'v3-9')
NAME = {'base-v1': '試験運用 base-v1', 'v3n-1': '他場版 v3n-1', 'v3-9': '南関特化 v3-9'}
PMIN = 1e-6


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


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x >= 0 and x == x else None


def band(o):
    return next(lab for lo, hi, lab in BANDS if lo <= o < hi)


def tick_min(r):
    t = hm(r.get("t"))
    a = hm(r.get("asof"))
    if t is not None and a is not None and 0 <= t - a <= 30:
        return a
    return t


def o10_of(trs, pm):
    best = None
    for r in trs:
        if r.get("f") or not isinstance(r.get("w"), dict) or not r["w"]:
            continue
        m = tick_min(r)
        if m is None or m > pm - 10:
            continue
        if best is None or (m, r["id"]) > (best[0], best[1]["id"]):
            best = (m, r)
    return best[1]["w"] if best else None


def probs_of(model, m):
    """mark 行 → {馬番: 見込み} か None。"""
    if model == 'base-v1':
        pw = m.get("pw")
        if not isinstance(pw, dict) or not pw:
            return None
        out = {}
        for k, v in pw.items():
            x = fnum(v)
            if x is not None:
                out[int(k)] = x
        return out or None
    rn = m.get("rn")
    if not isinstance(rn, list) or not rn:
        return None
    out = {}
    for x in rn:
        if isinstance(x, dict) and x.get("num") is not None:
            p = fnum(x.get("p1"))
            if p is not None:
                out[int(x["num"])] = p
    return out or None


def collect(base, key, d0, d1):
    """→ recs[model] = [(日, [(o10, p, y, pay), …])]・cnt[model] = 数え上げ"""
    recs = {m: [] for m in MODELS}
    cnt = {m: {"marks_race": 0, "last": 0, "morning": 0, "other": 0, "no_post": 0, "no_o10": 0, "no_pay": 0,
               "winners_not1": 0, "winner_missing": 0, "used": 0, "p_zero": 0, "days": set()} for m in MODELS}
    day = d0
    while day <= d1:
        ds = day.isoformat()
        d = urllib.parse.quote(ds)
        races = rows_offset(base, key, "/rest/v1/nar_races?select=track,race_no,post_time&race_date=eq.%s&order=track.asc,race_no.asc" % d)
        runs = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_no,runner_number,finish&race_date=eq.%s"
                           "&order=track.asc,race_no.asc,runner_number.asc" % d)
        marks = rows_offset(base, key, "/rest/v1/nar_ai_marks?select=model,track,race_no,timing,pw:meta->p_win,rn:meta->runners"
                            "&model=in.(%s)&race_date=eq.%s&order=model.asc,track.asc,race_no.asc,timing.asc" % (",".join(MODELS), d))
        if not marks:
            log("%s marks 0" % ds)
            day += dt.timedelta(days=1)
            continue
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
        fin = {}
        for r in runs:
            try:
                f = int(str(r.get("finish")).strip())
            except (TypeError, ValueError):
                f = None
            fin.setdefault((r["track"], int(r["race_no"])), {})[int(r["runner_number"])] = f
        pick = {}
        for m in marks:
            k = (m["model"], m["track"], int(m["race_no"]))
            if probs_of(m["model"], m) is None:
                continue
            tmg = m.get("timing")
            rank = {"last": 0, "morning": 1}.get(tmg, 2)
            if k not in pick or rank < pick[k][0]:
                pick[k] = (rank, m)
        o10c = {}
        for (model, track, no), (rank, m) in sorted(pick.items()):
            c = cnt[model]
            c["marks_race"] += 1
            c[{0: "last", 1: "morning"}.get(rank, "other")] += 1
            rk = (track, no)
            pm = post.get(rk)
            if pm is None:
                c["no_post"] += 1
                continue
            if rk not in o10c:
                o10c[rk] = o10_of(tk.get(rk) or [], pm)
            w10 = o10c[rk]
            if not w10:
                c["no_o10"] += 1
                continue
            fr = fin.get(rk) or {}
            ws = [u for u, f in fr.items() if f == 1]
            if len(ws) != 1:
                c["winners_not1"] += 1
                continue
            wu = ws[0]
            py = pay.get((track, no, wu))
            if py is None:
                c["no_pay"] += 1
                continue
            pr = probs_of(model, m)
            rows = []
            for u in fr:
                o = num(w10.get(str(u)))
                p = pr.get(u)
                if o is None or p is None:
                    continue
                rows.append((o, p, 1 if u == wu else 0, py if u == wu else 0.0))
            if not any(r[2] for r in rows) or len(rows) < 2:
                c["winner_missing"] += 1
                continue
            c["used"] += 1
            c["days"].add(ds)
            c["p_zero"] += sum(1 for r in rows if r[1] < PMIN)
            recs[model].append((ds, rows))
        log("%s marks %d" % (ds, len(pick)))
        day += dt.timedelta(days=1)
    return recs, cnt


# ---------------------------------------------------------------- 分析
def prep(rows):
    """→ [(o10, p, q, y, pay, lp, lq)](p・q はレース内で合計 1)"""
    ps = [max(r[1], PMIN) for r in rows]
    sp = sum(ps)
    iq = [1.0 / r[0] for r in rows]
    sq = sum(iq)
    out = []
    for (o, _p, y, py), p, q in zip(rows, ps, iq):
        p, q = p / sp, q / sq
        out.append((o, p, q, y, py, math.log(p), math.log(q)))
    return out


def blend(race, a, b):
    z = [a * x[5] + b * x[6] for x in race]
    mx = max(z)
    e = [math.exp(v - mx) for v in z]
    s = sum(e)
    return [v / s for v in e]


def loglik(races, a, b):
    t = 0.0
    for r in races:
        c = blend(r, a, b)
        t += sum(math.log(max(ci, 1e-300)) for ci, x in zip(c, r) if x[3])
    return t


def fit(races):
    """条件付きロジットの最尤(ニュートン法・半分ずつ戻る)。"""
    a, b = 1.0, 0.0
    ll = loglik(races, a, b)
    for _ in range(100):
        g1 = g2 = h11 = h12 = h22 = 0.0
        for r in races:
            c = blend(r, a, b)
            e1 = sum(ci * x[5] for ci, x in zip(c, r))
            e2 = sum(ci * x[6] for ci, x in zip(c, r))
            v11 = sum(ci * x[5] * x[5] for ci, x in zip(c, r)) - e1 * e1
            v12 = sum(ci * x[5] * x[6] for ci, x in zip(c, r)) - e1 * e2
            v22 = sum(ci * x[6] * x[6] for ci, x in zip(c, r)) - e2 * e2
            for ci, x in zip(c, r):
                if x[3]:
                    g1 += x[5] - e1
                    g2 += x[6] - e2
            h11 += v11
            h12 += v12
            h22 += v22
        det = h11 * h22 - h12 * h12
        if det <= 0:
            break
        da = (h22 * g1 - h12 * g2) / det
        db = (-h12 * g1 + h11 * g2) / det
        step = 1.0
        while step > 1e-6:
            na, nb = a + step * da, b + step * db
            nll = loglik(races, na, nb)
            if nll >= ll - 1e-12:
                break
            step /= 2
        if step <= 1e-6:
            break
        a, b, ll = na, nb, nll
        if abs(step * da) < 1e-7 and abs(step * db) < 1e-7:
            break
    return a, b


def logloss(races, kind, a=None, b=None):
    t = 0.0
    for r in races:
        if kind == 'ai':
            pw = next(x[1] for x in r if x[3])
        elif kind == 'mk':
            pw = next(x[2] for x in r if x[3])
        else:
            pw = next(ci for ci, x in zip(blend(r, a, b), r) if x[3])
        t -= math.log(max(pw, 1e-300))
    return t / len(races) if races else None


def bets(races, kind, a=None, b=None):
    """→ {帯: [点数, 当たり, 払戻の和, 最大払戻]}・'計' も"""
    t = {lab: [0, 0, 0.0, 0.0] for lab in BLAB + ['計']}
    for r in races:
        pr = [x[1] for x in r] if kind == 'ai' else blend(r, a, b)
        for p, x in zip(pr, r):
            o = x[0]
            lab = band(o)
            if p * o * COEF[lab] < 1.0:
                continue
            for k in (lab, '計'):
                t[k][0] += 1
                t[k][1] += x[3]
                t[k][2] += x[4]
                t[k][3] = max(t[k][3], x[4])
    return t


def ret(c):
    n, h, s, mx = c
    r = '—' if not n else '%.1f%%' % (s / n)
    rx = '—' if n < 2 else '%.1f%%' % ((s - mx) / (n - 1))
    return n, h, r, rx


def analyze(recs, cnt):
    md = ["# AI と市場を混ぜた検証(Benter 型)\n",
          "混ぜた確率 c ∝ exp(α·log p + β·log q)・q= 10 分前単勝の 1/o10 を合計 1。期待値= 確率 × o10 × ev_coef:v1(%s)≥ 1。"
          "前半で α・β を決め後半で評価。回収率は単勝 100 円ずつ。\n" % "/".join("%g" % COEF[b] for b in BLAB)]
    P = md.append
    P("## 件数\n\n| モデル | 予想のあるレース | うち last | morning | 発走時刻なし | o10 なし | 1着が1頭でない | 払戻なし | 勝ち馬の見込み/o10 なし | 数えたレース | 日数 | 見込み 0 の馬 |")
    P("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m in MODELS:
        c = cnt[m]
        P("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |" % (NAME[m], c["marks_race"], c["last"], c["morning"], c["no_post"],
          c["no_o10"], c["winners_not1"], c["no_pay"], c["winner_missing"], c["used"], len(c["days"]), c["p_zero"]))
    for m in MODELS:
        rs = sorted(recs[m], key=lambda x: x[0])
        P("\n## %s\n" % NAME[m])
        if len(rs) < 20:
            P("数えたレースが %d しかないので出さない。" % len(rs))
            continue
        days = sorted({d for d, _ in rs})
        per = {}
        for d, _ in rs:
            per[d] = per.get(d, 0) + 1
        half, acc, cut = len(rs) / 2.0, 0, days[-1]
        for d in days:
            if acc + per[d] > half and acc > 0:
                cut = d
                break
            acc += per[d]
        tr = [prep(r) for d, r in rs if d < cut]
        te = [prep(r) for d, r in rs if d >= cut]
        al = tr + te
        trd = sorted({d for d, _ in rs if d < cut})
        ted = sorted({d for d, _ in rs if d >= cut})
        P("前半= %s〜%s(%d 日・%d レース・%d 頭)/ 後半= %s〜%s(%d 日・%d レース・%d 頭)\n" % (
            trd[0], trd[-1], len(trd), len(tr), sum(len(r) for r in tr), ted[0], ted[-1], len(ted), len(te), sum(len(r) for r in te)))
        if len(te) < 300:
            P("⚠後半のレースが %d と少ない= 数字は揺れが大きい(参考)。\n" % len(te))
        a, b = fit(tr)
        fa, fb = fit(al)
        P("| α・β | α(AI) | β(市場) |\n|---|---|---|\n| 前半で決めた | %.3f | %.3f |\n| 全期間で決めた(参考) | %.3f | %.3f |\n" % (a, b, fa, fb))
        P("| 後半の 1 着の対数損失(1 レース平均) | 値 |\n|---|---|")
        P("| AI だけ | %.4f |\n| 市場だけ | %.4f |\n| 混ぜた後(前半の α・β) | %.4f |\n| 混ぜた後(全期間の α・β・参考) | %.4f |\n" % (
            logloss(te, 'ai'), logloss(te, 'mk'), logloss(te, 'bl', a, b), logloss(te, 'bl', fa, fb)))
        P("| 後半・期待値 ≥1 | 帯 | 点数 | 当たり | 回収率 | 最大払戻 1 件を除く |\n|---|---|---|---|---|---|")
        for lab, kind, ab in (("AI だけ", 'ai', (None, None)), ("混ぜた後", 'bl', (a, b)), ("混ぜた後(全期間 α・β)", 'bl', (fa, fb))):
            t = bets(te, kind, *ab)
            for k in ['計'] + BLAB:
                n, h, r, rx = ret(t[k])
                P("| %s | %s | %d | %d | %s | %s |" % (lab, k, n, h, r, rx))
    return "\n".join(md) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True)
    ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--out", default="out/ev_blend_audit")
    a = ap.parse_args()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    recs, cnt = collect(base, key, dt.date.fromisoformat(a.d0), dt.date.fromisoformat(a.d1))
    for m in MODELS:
        log("COUNT %s used %d marks %d last %d morning %d" % (m, cnt[m]["used"], cnt[m]["marks_race"], cnt[m]["last"], cnt[m]["morning"]))
    md = analyze(recs, cnt)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "blend.md"), "w", encoding="utf-8") as f:
        f.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
