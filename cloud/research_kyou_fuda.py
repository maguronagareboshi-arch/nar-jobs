# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-11-04)。/ai のレース札に「1強・2強・混戦」を出してよいかの裏付け。
便 .github/workflows/research-kyou-fuda.yml(手動だけ)。⛔読むだけ(REST の単純 select・日ごと)。⛔標準ライブラリだけ。
⛔公開 repo なので出力は集計表だけ(レースの鍵・馬ごとの値は出さない)。

  python cloud/research_kyou_fuda.py --out out/RESULT_kyou_fuda.md [--from 2026-01-01 --to 2026-11-03]

対象= nar_ai_marks の base-v1(meta.p_win)・v3n-1 と v3-9(meta.runners[].p1)。timing は朝(morning)と直前(last)を別々に。
未来の値を混ぜない= computed_at(日本時間)がレース日の発走時刻より前の行だけ(前日以前に作った行は可)。
結果確定= nar_runs に 1 着(finish=1)がいるレース。
群(倍率 k= 1.5/2.0/2.5): 勝率を大きい順 p1≥p2≥p3。A= p1 ≥ k·p2。B= A でなく p2 ≥ k·p3。C= その他。
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

UA = "nar-jobs research_kyou_fuda"
PAGE = 1000
MODELS = ('base-v1', 'v3n-1', 'v3-9')
NAME = {'base-v1': '試験運用 base-v1', 'v3n-1': '他場版 v3n-1', 'v3-9': '南関特化 v3-9'}
TIMINGS = ('morning', 'last')
TNAME = {'morning': '朝(南関特化は前日)', 'last': '直前'}
KS = (1.5, 2.0, 2.5)
JST = dt.timezone(dt.timedelta(hours=9))
MIN_VENUE = 200


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


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x >= 0 and x == x else None


def probs_of(model, m):
    if model == 'base-v1':
        pw = m.get("pw")
        if not isinstance(pw, dict) or not pw:
            return None
        out = {}
        for k, v in pw.items():
            x = fnum(v)
            if x is not None:
                try:
                    out[int(k)] = x
                except ValueError:
                    pass
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


def honmei(m):
    for x in m.get("marks") or []:
        if isinstance(x, dict) and x.get("mark") == "◎":
            try:
                return int(x.get("num"))
            except (TypeError, ValueError):
                return None
    return None


def jst_of(s):
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(JST)


def pre_race(computed_at, race_date, post_min):
    t = jst_of(computed_at)
    if t is None or post_min is None:
        return False
    if t.date() < race_date:
        return True
    if t.date() > race_date:
        return False
    return t.hour * 60 + t.minute < post_min


def first_day(base, key):
    ds = []
    for md in MODELS:
        r = req(base, key, "/rest/v1/nar_ai_marks?select=race_date&model=eq.%s&order=race_date.asc&limit=1" % md)
        if r:
            ds.append(dt.date.fromisoformat(r[0]["race_date"]))
    return min(ds)


def collect(base, key, d0, d1, cnt):
    """→ recs: list of dict(model, timing, track, p=[降順], hon_fin, top_fin(勝率1位の着), top2_ok, hon_p)"""
    recs = []
    day = d0
    while day <= d1:
        d = urllib.parse.quote(day.isoformat())
        marks = rows_offset(base, key, "/rest/v1/nar_ai_marks?select=model,track,race_no,timing,computed_at,marks,"
                            "pw:meta->p_win,rn:meta->runners&model=in.(%s)&race_date=eq.%s"
                            "&order=model.asc,track.asc,race_no.asc,timing.asc" % (",".join(MODELS), d))
        if not marks:
            day += dt.timedelta(days=1)
            continue
        races = rows_offset(base, key, "/rest/v1/nar_races?select=track,race_no,post_time&race_date=eq.%s&order=track.asc,race_no.asc" % d)
        runs = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_no,runner_number,finish&race_date=eq.%s"
                           "&order=track.asc,race_no.asc,runner_number.asc" % d)
        post = {(r["track"], int(r["race_no"])): hm(r.get("post_time")) for r in races}
        fin = {}
        for r in runs:
            try:
                f = int(str(r.get("finish")).strip())
            except (TypeError, ValueError):
                f = None
            try:
                fin.setdefault((r["track"], int(r["race_no"])), {})[int(r["runner_number"])] = f
            except (TypeError, ValueError):
                pass
        seen = set()
        for m in marks:
            model, tmg = m["model"], m.get("timing")
            if tmg not in TIMINGS:
                continue
            rk = (m["track"], int(m["race_no"]))
            kk = (model, tmg) + rk
            if kk in seen:
                continue
            seen.add(kk)
            c = cnt[(model, tmg)]
            c["rows"] += 1
            pr = probs_of(model, m)
            if pr is None or len(pr) < 3:
                c["no_p"] += 1
                continue
            if not pre_race(m.get("computed_at"), day, post.get(rk)):
                c["not_pre"] += 1
                continue
            fr = fin.get(rk) or {}
            if not any(v == 1 for v in fr.values()):
                c["no_result"] += 1
                continue
            hn = honmei(m)
            if hn is None:
                c["no_hon"] += 1
                continue
            order = sorted(pr.items(), key=lambda kv: (-kv[1], kv[0]))
            ps = [v for _, v in order]
            top2 = {order[0][0], order[1][0]}
            ft = {u for u, f in fr.items() if f is not None and f <= 2}
            hf = fr.get(hn)
            recs.append({
                "model": model, "timing": tmg, "track": rk[0], "p": ps,
                "hon_win": hf == 1, "hon_top3": hf is not None and hf <= 3,
                "top_win": fr.get(order[0][0]) == 1,
                "top2_ok": ft == top2,
                "hon_p": pr.get(hn),
                "date": day,
            })
            c["used"] += 1
            c["days"].add(day)
        log("%s marks %d recs %d" % (day.isoformat(), len(marks), len(recs)))
        day += dt.timedelta(days=1)
    return recs


def group(ps, k):
    p1, p2, p3 = ps[0], ps[1], ps[2]
    if p1 >= k * p2 and p1 > 0:
        return "A"
    if p2 >= k * p3 and p2 > 0:
        return "B"
    return "C"


def wilson(x, n):
    if n == 0:
        return None
    z = 1.96
    p = x / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, c - h, c + h


def pc(x, n):
    w = wilson(x, n)
    if w is None:
        return "—"
    return "%.1f%% (%.1f–%.1f)" % (w[0] * 100, w[1] * 100, w[2] * 100)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def fm(x):
    return "—" if x is None else "%.1f%%" % (x * 100)


HEAD = ("| 群 | レース数 | 割合 | ◎1着率 | ◎3着内率 | 1・2着=勝率上位2頭 | 勝率1位の1着率 | 勝率1位の予想勝率の平均 | ◎の予想勝率の平均 |\n"
        "|---|---:|---:|---|---|---|---|---:|---:|")
GNAME = {"A": "A 1強", "B": "B 2強", "C": "C 混戦"}


def row(label, rs, total):
    n = len(rs)
    return "| %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
        label, n, fm(n / total if total else None),
        pc(sum(r["hon_win"] for r in rs), n), pc(sum(r["hon_top3"] for r in rs), n),
        pc(sum(r["top2_ok"] for r in rs), n), pc(sum(r["top_win"] for r in rs), n),
        fm(mean([r["p"][0] for r in rs])), fm(mean([r["hon_p"] for r in rs])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0")
    ap.add_argument("--to", dest="d1")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    d0 = dt.date.fromisoformat(a.d0) if a.d0 else first_day(base, key)
    d1 = dt.date.fromisoformat(a.d1) if a.d1 else (dt.datetime.now(JST).date() - dt.timedelta(days=1))
    cnt = {(m, t): {"rows": 0, "no_p": 0, "not_pre": 0, "no_result": 0, "no_hon": 0, "used": 0, "days": set()}
           for m in MODELS for t in TIMINGS}
    recs = collect(base, key, d0, d1, cnt)

    L = ["# 1強・2強・混戦の札の裏付け(%s〜%s)" % (d0, d1), "",
         "群: 勝率を大きい順に p1≥p2≥p3。A 1強= p1 ≥ k×p2。B 2強= A でなく p2 ≥ k×p3。C 混戦= その他。括弧は 95% 信頼区間(Wilson)。",
         "対象= 発走時刻より前に保存された行(computed_at・日本時間)・1 着が確定したレース・◎がある行。", "",
         "## 数え上げ", "",
         "| 模型 | 時点 | 行 | 勝率なし/3頭未満 | 発走後の保存(除外) | 結果なし | ◎なし | 使用 | 日数 | 期間 |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for m in MODELS:
        for t in TIMINGS:
            c = cnt[(m, t)]
            ds = sorted(c["days"])
            L.append("| %s | %s | %d | %d | %d | %d | %d | %d | %d | %s |" % (
                NAME[m], TNAME[t], c["rows"], c["no_p"], c["not_pre"], c["no_result"], c["no_hon"], c["used"], len(ds),
                ("%s〜%s" % (ds[0], ds[-1])) if ds else "—"))
    L.append("")
    for m in MODELS:
        for t in TIMINGS:
            rs = [r for r in recs if r["model"] == m and r["timing"] == t]
            if not rs:
                continue
            L += ["## %s・%s(%d レース)" % (NAME[m], TNAME[t], len(rs)), ""]
            for k in KS:
                L += ["### 倍率 k=%.1f" % k, "", HEAD]
                for g in "ABC":
                    L.append(row(GNAME[g], [r for r in rs if group(r["p"], k) == g], len(rs)))
                L.append(row("全体", rs, len(rs)))
                L.append("")
            # 場ごと(k=2.0)
            by = {}
            for r in rs:
                by.setdefault(r["track"], []).append(r)
            big = sorted([tr for tr, v in by.items() if len(v) >= MIN_VENUE], key=lambda tr: -len(by[tr]))
            small = [r for tr, v in by.items() if len(v) < MIN_VENUE for r in v]
            L += ["### 場ごと(k=2.0・%d レース未満の場はまとめた)" % MIN_VENUE, "",
                  "| 場 | 群 | レース数 | 割合 | ◎1着率 | ◎3着内率 | 1・2着=勝率上位2頭 | 勝率1位の1着率 | 勝率1位の予想勝率の平均 | ◎の予想勝率の平均 |",
                  "|---|---|---:|---:|---|---|---|---|---:|---:|"]
            groups = [(tr, by[tr]) for tr in big]
            if small:
                groups.append(("その他 %d 場" % len({r["track"] for r in small}), small))
            for tr, v in groups:
                for g in "ABC":
                    L.append("| %s %s" % (tr, row(GNAME[g], [r for r in v if group(r["p"], 2.0) == g], len(v))))
            L.append("")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    log("done recs %d -> %s" % (len(recs), a.out))


if __name__ == "__main__":
    main()
