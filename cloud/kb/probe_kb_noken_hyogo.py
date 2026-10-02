# -*- coding: utf-8 -*-
"""兵庫(園田 37・西脇 45)能検の過去分が競馬ブックで読めるかの下見(2026-10-02)。⛔DB に書かない・⛔頁の HTML を出さない(public repo)。

a) 2015-01〜今月の月一覧で 兵庫(37/45)・笠松(19)・名古屋(34)の日数を年ごとに数える(日のページは開かない)
b) 2021〜2025 の 6 月の兵庫の最初の日+2026 の 1 日を collect_day で読み、頭数・時計・着順・合否の数を出す
"""
import argparse
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch import make_client                                   # noqa: E402
from fetch_kb_noken_hyogo import collect_day                    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CODES = {"37": "園田", "45": "西脇", "19": "笠松", "34": "名古屋"}


def log(m):
    print(m, flush=True)


def month_ids(client, ym):
    try:
        html = client.get("/chihou/nouken/%s" % ym)
    except Exception as e:
        log(f"{ym}: 一覧が取れない ({type(e).__name__})")
        return None
    a = set(re.findall(r'href="(\d{10})"', html))
    b = set(re.findall(r'/chihou/nouken/(\d{10})', html))
    if a != b and b - a:
        log(f"{ym}: href の形が違う id {len(b - a)} 件(相対 {len(a)}・絶対 {len(b)})")
    return sorted(i for i in (a | b) if i[:6] == ym)


def structure(html):
    """読めないときの形だけ(⛔中身は出さない)。"""
    classes = re.findall(r'<table class="([^"]*)"', html)
    ths = [re.sub(r"<[^>]+>|\s+", "", t) for t in re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)][:16]
    return (f"len={len(html)} midasi_sub={html.count('midasi_sub')} nouken={html.count('nouken')} "
            f"tables={classes[:6]} th={ths} login_form={'login' in html.lower()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-login", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    client, ok = make_client(a)
    if not ok:
        log("! ログインできていない")
    today = dt.date.today()
    per = defaultdict(lambda: defaultdict(int))        # code -> year -> days
    june = {}                                           # year -> [(date, code)]
    any_day = {}                                        # year -> [(date, code)]
    d = dt.date(2015, 1, 1)
    while d <= today:
        ym = d.strftime("%Y%m")
        ids = month_ids(client, ym)
        for i in ids or []:
            c = i[8:]
            if c in CODES:
                per[c][d.year] += 1
                if c in ("37", "45"):
                    any_day.setdefault(d.year, []).append((i[:8], c))
                    if d.month == 6:
                        june.setdefault(d.year, []).append((i[:8], c))
        d = (d.replace(day=28) + dt.timedelta(days=7)).replace(day=1)

    log("== 月一覧の年別日数 ==")
    years = list(range(2015, today.year + 1))
    log("場\t" + "\t".join(map(str, years)))
    for c, nm in CODES.items():
        log(nm + "\t" + "\t".join(str(per[c].get(y, 0)) for y in years))

    log("== 1 日ずつ読む ==")
    picks = []
    for y in range(2021, 2026):
        cand = sorted(june.get(y) or any_day.get(y) or [])
        if cand:
            picks.append(cand[0])
        else:
            log(f"{y}: 兵庫の日が一覧に無い")
    c26 = sorted(june.get(2026) or any_day.get(2026) or [])
    if c26:
        picks.append(c26[0])
    for date, code in picks:
        day, why = collect_day(client, date, code)
        if day is None:
            log(f"{date} {CODES[code]}: 読めない({why})")
            try:
                log("  形: " + structure(client.get("/chihou/nouken/%s%s" % (date, code))))
            except Exception as e:
                log(f"  形も取れない ({type(e).__name__})")
            continue
        rows = [r for rc in day["races"] for r in rc["rows"]]
        nt = sum(1 for r in rows if r["time"])
        nf = sum(1 for r in rows if r["fin"])
        nk = sum(1 for r in rows if r["ok"])
        log(f"{date} {CODES[code]}: {len(day['races'])}組 頭数 {len(rows)} 時計 {nt} 着順 {nf} 合否 {nk} "
            f"距離 {'/'.join(str(r['dist']) for r in day['races'])}")
        for r in rows[:2]:
            log("  例: " + " | ".join(str(r[k]) for k in ("fin", "umaban", "name", "time", "kind", "ok")))
        if not (nt and nf and nk):
            try:
                log("  形: " + structure(client.get("/chihou/nouken/%s%s" % (date, code))))
            except Exception as e:
                log(f"  形も取れない ({type(e).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
