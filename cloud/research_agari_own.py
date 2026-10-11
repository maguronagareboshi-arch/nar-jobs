# -*- coding: utf-8 -*-
"""研究用・1 回きり: 「この日の傾向」の上がりの差を、能力の差を除いた物差し(いつもとの差)に変えたらどうなるか(高知 1 年)。
便 .github/workflows/research-agari-own.yml(workflow_dispatch のみ)から走らせ、docs/research-agari-own/result.md を書く。
⛔本番 DB では REST の単純 select だけ。集計は全部ここ。書き込みなし。

定義:
  期間= 高知 2025-10-01〜2026-10-11 の開催日。走路改修 2026-08-03〜09-01 は印だけ(除かない)。
  4角= day_trend_base.corner_points の "4"(名前の数字・2 周は後)。4角 6 頭以上のレースだけ。
  前= 4角 1〜3 番手。後ろ A= 4角で最後から 3 頭(番手 >= 頭数−2)。後ろ B= 今の定義(番手 >= min(7, 頭数−2))。
  上がり= last3f が 30〜55 秒(0.0 は落ちる)・完走(着順あり・取消/除外/失格/中止なし)。
  いつもの上がり= その日より前の直近 5 走(全場・距離 ±200m・完走・上がり 30〜55)の中央値。3 走未満は数えない。
  今の差= 後ろの上がり平均 − 前の上がり平均(各 2 頭以上)。新しい差= 後ろの(今日−いつも)平均 − 前の(今日−いつも)平均(各 2 頭以上)。
  日ごとの値= その日のレース値の平均。当たり= その日の 4角7番手以下の 3着以内頭数 − 頭数×ふだん率
  (ふだん率= この 1 年の同じ表から、その日を抜いた 4角7番手以下の 3着内率)。
"""
import datetime as dt
import os
import statistics
import sys
import urllib.parse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from day_trend_base import corner_points, toint, is_cancelled, rows_all, log  # noqa: E402

TRACK = "高知"
D_FROM, D_TO = "2025-10-01", "2026-10-11"
H_FROM = "2024-01-01"
REPAIR = ("2026-08-03", "2026-09-01")
EXAMPLES = ["2026-10-11", "2026-10-04"]
L3_OK = (30.0, 55.0)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "research-agari-own", "result.md")


def months(a, b):
    y, m = int(a[:4]), int(a[5:7])
    while f"{y:04d}-{m:02d}" <= b[:7]:
        nx = dt.date(y + (m == 12), m % 12 + 1, 1)
        last = (nx - dt.timedelta(days=1)).isoformat()
        yield f"{y:04d}-{m:02d}-01", min(last, b)
        y, m = nx.year, nx.month


def q(s):
    return urllib.parse.quote(str(s), safe="")


def nm(s):
    return "".join(str(s or "").split())


def l3_of(x):
    try:
        v = float(x.get("last3f"))
    except Exception:
        return None
    return v if L3_OK[0] <= v <= L3_OK[1] else None


def fin_of(x):
    note = x.get("finish_note") or ""
    if "取消" in note or "除外" in note or "失格" in note or "中止" in note:
        return None
    return toint(x.get("finish"))


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((u - mx) ** 2 for u in xs) ** .5
    sy = sum((v - my) ** 2 for v in ys) ** .5
    if sx == 0 or sy == 0:
        return None
    return sum((u - mx) * (v - my) for u, v in zip(xs, ys)) / sx / sy


def qt(vals, f):
    v = sorted(vals)
    return v[min(len(v) - 1, int(f * (len(v) - 1) + 0.5))]


def msd(vals):
    if not vals:
        return "-", "-", 0
    return f"{statistics.mean(vals):+.3f}", (f"{statistics.stdev(vals):.3f}" if len(vals) > 1 else "-"), len(vals)


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    dist = {}          # (track,date,no) -> 距離
    hist = defaultdict(list)   # 馬 -> [(date, track, no, dist, l3)]  完走+上がり有効
    kraces, kruns = [], defaultdict(list)
    for a, b in months(H_FROM, D_TO):
        f = f"&race_date=gte.{a}&race_date=lte.{b}"
        rs = rows_all(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,distance_m,cancelled" + f
                      + "&order=race_date.asc,track.asc,race_no.asc")
        for r in rs:
            if not is_cancelled(r.get("cancelled")) and r.get("distance_m") not in (None, ""):
                dist[(r["track"], r["race_date"], int(r["race_no"]))] = int(float(r["distance_m"]))
        ru = rows_all(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date,"
                      "finish,finish_note,last3f" + f + "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc")
        for x in ru:
            k = (x["track"], x["race_date"], int(x["race_no"]))
            hk = (nm(x.get("horse_name")), x.get("birth_date") or "")
            fn, l3 = fin_of(x), l3_of(x)
            if fn is not None and l3 is not None and k in dist and hk[0]:
                hist[hk].append((x["race_date"], x["track"], k[2], dist[k], l3))
            if x["track"] == TRACK and D_FROM <= x["race_date"] <= D_TO:
                kruns[k].append(x)
        if b >= D_FROM:
            kr = rows_all(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,distance_m,corners,cancelled"
                          f"&track=eq.{q(TRACK)}" + f"&race_date=gte.{max(a, D_FROM)}" + "&order=race_date.asc,race_no.asc")
            kraces.extend(kr)
        log(f"{a[:7]} レース {len(rs)}・出走 {len(ru)}")
    for v in hist.values():
        v.sort()

    def usual(hk, d, D):
        prev = [h for h in hist.get(hk, []) if h[0] < d and abs(h[3] - D) <= 200]
        last5 = prev[-5:]
        return (statistics.median([h[4] for h in last5]), len(last5)) if len(last5) >= 3 else (None, len(last5))

    races = []   # 1 レースの値
    cnt = defaultdict(int)
    for r in kraces:
        k = (r["track"], r["race_date"], int(r["race_no"]))
        if is_cancelled(r.get("cancelled")) or k not in dist or not kruns.get(k):
            continue
        mp4 = corner_points(r.get("corners")).get("4")
        if not mp4:
            cnt["4角なし"] += 1
            continue
        ent = []
        for x in kruns[k]:
            note = x.get("finish_note") or ""
            if "取消" in note or "除外" in note:
                continue
            ent.append((toint(x.get("runner_number")), fin_of(x), l3_of(x), (nm(x.get("horse_name")), x.get("birth_date") or "")))
        if not any(e[1] is not None for e in ent):
            continue
        rks = {e[0]: mp4[e[0]] for e in ent if e[0] in mp4}
        n4 = len(rks)
        if n4 < 6:
            cnt["4角5頭以下"] += 1
            continue
        D = dist[k]
        cutA, cutB = n4 - 2, min(7, n4 - 2)
        rec = {"d": k[1], "no": k[2], "n4": n4}
        grp = {"F": [], "A": [], "B": []}
        for num, fn, l3, hk in ent:
            if num not in rks or fn is None or l3 is None:
                continue
            rk = rks[num]
            u, nprev = usual(hk, k[1], D)
            for g, ok in (("F", rk <= 3), ("A", rk >= cutA), ("B", rk >= cutB)):
                if ok:
                    grp[g].append((l3, u))
                    cnt[f"対象_{g}"] += 1
                    cnt[f"数えない_{g}"] += u is None
        for g, v in grp.items():
            raw = [a for a, _ in v]
            own = [a - u for a, u in v if u is not None]
            rec[g + "raw"] = sum(raw) / len(raw) if len(raw) >= 2 else None
            rec[g + "own"] = sum(own) / len(own) if len(own) >= 2 else None
        for g in ("A", "B"):
            rec["cur" + g] = rec[g + "raw"] - rec["Fraw"] if rec[g + "raw"] is not None and rec["Fraw"] is not None else None
            rec["new" + g] = rec[g + "own"] - rec["Fown"] if rec[g + "own"] is not None and rec["Fown"] is not None else None
        # 当たり= 4角7番手以下(rank >= 7)の頭数と 3着以内
        back7 = [e for e in ent if e[0] in rks and rks[e[0]] >= 7]
        rec["b7n"] = len(back7)
        rec["b7t3"] = sum(1 for e in back7 if e[1] is not None and 1 <= e[1] <= 3)
        races.append(rec)
    log(f"数えたレース {len(races)}")

    # 日ごと
    days = defaultdict(list)
    for x in races:
        days[x["d"]].append(x)
    totN = sum(x["b7n"] for x in races)
    totT = sum(x["b7t3"] for x in races)
    DAY = {}
    for d, xs in sorted(days.items()):
        e = {"R": len(xs), "rep": REPAIR[0] <= d <= REPAIR[1]}
        for m in ("curA", "newA", "curB", "newB", "Fraw", "Araw", "Braw", "Fown", "Aown", "Bown"):
            v = [x[m] for x in xs if x[m] is not None]
            e[m] = sum(v) / len(v) if v else None
            e[m + "_n"] = len(v)
        n, t = sum(x["b7n"] for x in xs), sum(x["b7t3"] for x in xs)
        p = (totT - t) / (totN - n) if totN - n else None
        e["hit"] = t - n * p if p is not None else None
        e["b7"] = (t, n * p if p is not None else None)
        DAY[d] = e

    L = []
    A = L.append
    A("# 上がりの差を「いつもとの差」に変えたら(高知 1 年・研究)")
    A(f"台本 cloud/research_agari_own.py・便 research-agari-own.yml・作成 {dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')} JST。本番 DB は読むだけ。")
    A(f"- 期間 {D_FROM}〜{D_TO}・開催日 {len(DAY)}(うち走路改修 {REPAIR[0]}〜{REPAIR[1]} の日 {sum(1 for e in DAY.values() if e['rep'])})・数えたレース {len(races)}(4角 6 頭以上)。"
          f"外したレース: 4角なし {cnt['4角なし']}・4角 5 頭以下 {cnt['4角5頭以下']}。")
    A("- 前= 4角1〜3番手。後ろA= 4角で最後から 3 頭(案①)。後ろB= 今の定義(4角7番手以下・8 頭以下は最後の 3 頭)。")
    A("- いつもとの差= 今日の上がり − 直近 5 走(全場・距離±200m・完走・30〜55 秒)の中央値。3 走未満の馬は新しい差に入れない。+ = 遅い。")
    A("- 今の差= 後ろの上がり平均 − 前の平均。新しい差= 後ろのいつもとの差の平均 − 前のいつもとの差の平均。+ = 後ろの方が遅い。")
    A("")
    A("## 数えなかった頭数(上がり有効の完走馬のうち、近走 3 走未満)")
    A("| 組 | 対象 | 数えない | 割合 |")
    A("|---|---|---|---|")
    for g, lab in (("F", "前"), ("A", "後ろA"), ("B", "後ろB")):
        a, b = cnt[f"対象_{g}"], cnt[f"数えない_{g}"]
        A(f"| {lab} | {a} | {b} | {b / a:.1%} |" if a else f"| {lab} | 0 | 0 | - |")
    A("")
    A("## 1. 1 年の全レース(レースごとの値の平均・標準偏差・R 数)")
    A("| 物差し | 平均 | 標準偏差 | R |")
    A("|---|---|---|---|")
    for m, lab in (("curA", "今の差(後ろA)"), ("newA", "新しい差(後ろA)"), ("curB", "今の差(後ろB)"), ("newB", "新しい差(後ろB)"),
                   ("Fown", "前のいつもとの差"), ("Aown", "後ろAのいつもとの差"), ("Bown", "後ろBのいつもとの差"),
                   ("Fraw", "前の上がり(秒)"), ("Araw", "後ろAの上がり(秒)"), ("Braw", "後ろBの上がり(秒)")):
        mm, sd, n = msd([x[m] for x in races if x[m] is not None])
        A(f"| {lab} | {mm} | {sd} | {n} |")
    for g in ("A", "B"):
        both = [x for x in races if x["cur" + g] is not None and x["new" + g] is not None]
        r = pearson([x["cur" + g] for x in both], [x["new" + g] for x in both])
        A(f"- 後ろ{g}: 両方出たレース {len(both)}・レースごとの今の差と新しい差の相関 {r:+.3f}" if r is not None else f"- 後ろ{g}: -")
    A("")
    A("## 2. 日ごとの値(その日のレース値の平均)の分布")
    A("| 物差し | 日数 | 平均 | 10% | 50% | 90% |")
    A("|---|---|---|---|---|---|")
    for m, lab in (("curA", "今の差(後ろA)"), ("newA", "新しい差(後ろA)"), ("curB", "今の差(後ろB)"), ("newB", "新しい差(後ろB)")):
        v = [e[m] for e in DAY.values() if e[m] is not None]
        if v:
            A(f"| {lab} | {len(v)} | {statistics.mean(v):+.3f} | {qt(v, .1):+.3f} | {qt(v, .5):+.3f} | {qt(v, .9):+.3f} |")
    for g in ("A", "B"):
        ds = [e for e in DAY.values() if e["cur" + g] is not None and e["new" + g] is not None]
        r = pearson([e["cur" + g] for e in ds], [e["new" + g] for e in ds])
        A(f"- 後ろ{g}: 日ごとの今の差と新しい差の相関 {r:+.3f}(日数 {len(ds)})" if r is not None else f"- 後ろ{g}: -")
    A("")
    A("## 3. 当たりとの連動(日ごと)")
    A(f"- 当たり= その日の 4角7番手以下の 3着以内 − 頭数×ふだん率。ふだん率= 1 年全体 {totT}/{totN} = {totT / totN:.3f}(各日はその日を抜く)。")
    A("- 相関が負に大きいほど「後ろが遅い(差が +)日に後ろが来ない」と連動。")
    A("| 物差し | 日数 | 当たりとの相関 | 改修期間を除くと |")
    A("|---|---|---|---|")
    for m, lab in (("curA", "今の差(後ろA)"), ("newA", "新しい差(後ろA)"), ("curB", "今の差(後ろB)"), ("newB", "新しい差(後ろB)"),
                   ("Fown", "前のいつもとの差"), ("Bown", "後ろBのいつもとの差")):
        ds = [e for e in DAY.values() if e[m] is not None and e["hit"] is not None]
        r = pearson([e[m] for e in ds], [e["hit"] for e in ds])
        ds2 = [e for e in ds if not e["rep"]]
        r2 = pearson([e[m] for e in ds2], [e["hit"] for e in ds2])
        A(f"| {lab} | {len(ds)} | {r:+.3f} | {r2:+.3f}({len(ds2)}) |" if r is not None and r2 is not None else f"| {lab} | {len(ds)} | - | - |")
    A("")
    A("## 4. 例の日")
    A("| 日付 | R | 前のいつもとの差 | 後ろAのいつもとの差 | 後ろBのいつもとの差 | 新しい差 A | 新しい差 B | 今の差 A | 今の差 B | 4角7〜 3着内 実際/期待 |")
    A("|---|---|---|---|---|---|---|---|---|---|")

    def f3(v):
        return "-" if v is None else f"{v:+.2f}"
    for d in EXAMPLES:
        e = DAY.get(d)
        if not e:
            A(f"| {d} | 開催なし/データなし | | | | | | | | |")
            continue
        A(f"| {d} | {e['R']} | {f3(e['Fown'])} | {f3(e['Aown'])} | {f3(e['Bown'])} | {f3(e['newA'])} | {f3(e['newB'])} | "
          f"{f3(e['curA'])} | {f3(e['curB'])} | {e['b7'][0]}/{e['b7'][1]:.1f} |")
    A("")
    A("## 付表 日ごと(* = 走路改修の期間)")
    A("| 日付 | R | 今の差 A | 新しい差 A | 今の差 B | 新しい差 B | 前のいつもとの差 | 後ろBのいつもとの差 | 当たり |")
    A("|---|---|---|---|---|---|---|---|---|")
    for d, e in DAY.items():
        A(f"| {d}{'*' if e['rep'] else ''} | {e['R']} | {f3(e['curA'])} | {f3(e['newA'])} | {f3(e['curB'])} | {f3(e['newB'])} | "
          f"{f3(e['Fown'])} | {f3(e['Bown'])} | {f3(e['hit'])} |")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:60]))


if __name__ == "__main__":
    main()
