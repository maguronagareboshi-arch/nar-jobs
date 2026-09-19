# -*- coding: utf-8 -*-
"""§224e 下調べ(手元だけ・本番 DB は読むだけ)= 前半3F の実測がある走で「走破タイム−上り3F」からの推定がどれだけずれるか。

  py -3.12 -X utf8 tools/first3f_survey.py --from 2025-10-01 --to 2026-08-31 --out docs/notes_s224e.md
環境変数: SUPABASE_URL / SUPABASE_ANON_KEY(読むだけ)

- 実測= 高知(当サイトの計測 nar_own_runs)・専門紙の場(nar_kb_runs)・岩手の紙面(nar_paper_runs)。
- 走破タイム・上り3F は公式の結果(nar_runs)、距離は nar_races。⛔3F の前半だけ(距離が 3F の区間を持つ走)。
- 推定 x= (走破タイム − 上り3F) × 600 ÷ (距離 − 600)(前半を等速とみなした按分)。ずれ= 実測 − x。
- 補正= 場×距離の中央値を x に足す。当てはめた期間の中(in)と、前の期間の中央値を後の期間に当てた場合(後ろ向き)の両方を数える。
- 取得は場ごと・30 日の窓・一意な並び(offset のずれを出さない)。⛔書き込みはしない。
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

SOURCES = (("nar_own_runs", "当サイトの計測"), ("nar_kb_runs", "専門紙"), ("nar_paper_runs", "紙面"))
PAGE = 1000
STATS = {"requests": 0, "rows": 0}


def get(path):
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_ANON_KEY"]
    req = urllib.request.Request(base + "/rest/v1/" + path, headers={"apikey": key, "Authorization": "Bearer " + key})
    for n in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                STATS["requests"] += 1
                return json.loads(r.read())
        except Exception:  # noqa: BLE001
            if n == 2:
                raise
            time.sleep(2 + n * 3)


def windows(d0, d1, days=30):
    a = d0
    while a <= d1:
        b = min(d1, a + dt.timedelta(days=days - 1))
        yield a.isoformat(), b.isoformat()
        a = b + dt.timedelta(days=1)


def pages(table, select, filt, order):
    off = 0
    while True:
        rows = get(f"{table}?select={select}&{filt}&order={order}&limit={PAGE}&offset={off}")
        STATS["rows"] += len(rows)
        yield from rows
        if len(rows) < PAGE:
            return
        off += PAGE


def collect(d0, d1):
    measured = {}   # (track, date, no, umaban) → (first3f, 出どころ)
    for table, label in SOURCES:
        for a, b in windows(d0, d1):
            filt = f"first3f=not.is.null&race_date=gte.{a}&race_date=lte.{b}"
            for r in pages(table, "track,race_date,race_no,umaban,first3f", filt, "track,race_date,race_no,umaban"):
                track = r["track"] if table != "nar_own_runs" else (r.get("track") or "高知")
                k = (track, r["race_date"], int(r["race_no"]), int(r["umaban"]))
                if table == "nar_paper_runs" or k not in measured:   # 画面と同じ= 紙面を優先
                    measured[k] = (float(r["first3f"]), label)
    tracks = sorted({k[0] for k in measured})
    runs, dist = {}, {}
    for track in tracks:
        tq = urllib.parse.quote(track)
        for a, b in windows(d0, d1):
            filt = f"track=eq.{tq}&race_date=gte.{a}&race_date=lte.{b}"
            for r in pages("nar_races", "track,race_date,race_no,distance_m,surface", filt, "race_date,race_no"):
                dist[(track, r["race_date"], int(r["race_no"]))] = r.get("distance_m")
            for r in pages("nar_runs", "track,race_date,race_no,runner_number,time_sec,last3f",
                           filt + "&time_sec=not.is.null&last3f=not.is.null", "race_date,race_no,runner_number"):
                if r.get("runner_number") is not None:
                    runs[(track, r["race_date"], int(r["race_no"]), int(r["runner_number"]))] = (float(r["time_sec"]), float(r["last3f"]))
    return measured, runs, dist


def dist_band(d):
    return "1800以上" if d >= 1800 else str(d)


def quart(xs):
    q = statistics.quantiles(xs, n=4, method="inclusive") if len(xs) >= 2 else [xs[0]] * 3
    return q[0], statistics.median(xs), q[2]


def within(xs, lim):
    return 100.0 * sum(1 for x in xs if abs(x) <= lim + 1e-9) / len(xs) if xs else None


def analyse(measured, runs, dist, split):
    rows, skipped = [], {"結果なし": 0, "距離なし・3F でない": 0}
    for k, (f3, label) in measured.items():
        d = dist.get(k[:3])
        if not d or d < 1200:
            skipped["距離なし・3F でない"] += 1
            continue
        tr = runs.get(k)
        if not tr:
            skipped["結果なし"] += 1
            continue
        t, l3 = tr
        x = (t - l3) * 600.0 / (d - 600)
        rows.append({"track": k[0], "date": k[1], "band": dist_band(int(d)), "src": label, "diff": f3 - x})
    groups = {}
    for r in rows:
        groups.setdefault((r["track"], r["band"]), []).append(r)
    out = []
    for (track, band), rs in sorted(groups.items(), key=lambda g: (g[0][0], g[0][1])):
        ds = [r["diff"] for r in rs]
        q1, med, q3 = quart(ds)
        fit = [r["diff"] for r in rs if r["date"] < split]
        test = [r["diff"] for r in rs if r["date"] >= split]
        oos = [x - statistics.median(fit) for x in test] if fit and test else []
        out.append({"track": track, "band": band, "src": "・".join(sorted({r["src"] for r in rs})), "n": len(ds),
                    "q1": q1, "med": med, "q3": q3, "raw05": within(ds, 0.5),
                    "in03": within([x - med for x in ds], 0.3), "in05": within([x - med for x in ds], 0.5),
                    "n_fit": len(fit), "n_test": len(test), "oos05": within(oos, 0.5)})
    return out, skipped, len(rows)


def fmt(v, d=2):
    return "—" if v is None else f"{v:.{d}f}"


def write_md(path, out, skipped, n_used, n_meas, args, split):
    ok = [g for g in out if g["in05"] is not None and g["in05"] >= 80]
    lines = [
        "# §224e 前半3F の推定(走破タイム−上り3F の按分)と実測のずれ",
        "",
        f"期間 {args.date_from}〜{args.date_to}・実測のある走 {n_meas}・突き合わせた走 {n_used}"
        f"(除外: 結果なし {skipped['結果なし']}・距離なし/1200m 未満 {skipped['距離なし・3F でない']})。"
        "本番 DB は読むだけ。",
        "",
        "- 推定 x= (走破タイム − 上り3F) × 600 ÷ (距離 − 600)。ずれ= 実測 − x(+ は実測のほうが遅い)。",
        "- 補正あり(in)= 場×距離の中央値を x に足した値で |実測 − 推定| を数えた割合(当てはめた期間の中)。",
        f"- 後ろ向き= {split} より前の中央値を {split} 以降に当てたときの 0.5 秒以内の割合(件数は 前/後)。",
        "- 採る条件(設計)= 補正あり 0.5 秒以内が 80% 以上= ✓(件数の条件は足していない= 件数と後ろ向きの列で見る)。",
        "",
        "| 場 | 距離 | 出どころ | 件数 | 四分位 1 | 中央値 | 四分位 3 | 補正なし ≤0.5 | 補正あり ≤0.3 | 補正あり ≤0.5 | 後ろ向き ≤0.5(前/後) | 採る |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|:---:|",
    ]
    for g in out:
        mark = "✓" if g in ok else ""
        lines.append(f"| {g['track']} | {g['band']} | {g['src']} | {g['n']} | {fmt(g['q1'])} | {fmt(g['med'])} | {fmt(g['q3'])} | "
                     f"{fmt(g['raw05'], 1)}% | {fmt(g['in03'], 1)}% | {fmt(g['in05'], 1)}% | "
                     f"{fmt(g['oos05'], 1) + '%' if g['oos05'] is not None else '—'}({g['n_fit']}/{g['n_test']}) | {mark} |")
    tot = [g for g in out]
    all05 = sum(g["in05"] * g["n"] for g in tot) / max(1, sum(g["n"] for g in tot))
    lines += ["", f"全体(件数で重み)の補正あり 0.5 秒以内= {all05:.1f}%。✓ の組= {len(ok)}/{len(out)}(走 {sum(g['n'] for g in ok)})。",
              f"取得= {STATS['requests']} 本・{STATS['rows']} 行(REST・30 日の窓)。", ""]
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    return ok, all05


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", default="2025-10-01")
    ap.add_argument("--to", dest="date_to", default="2026-08-31")
    ap.add_argument("--split", default="2026-06-01")
    ap.add_argument("--out", default="docs/notes_s224e.md")
    a = ap.parse_args()
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_ANON_KEY"):
        print("SUPABASE_URL / SUPABASE_ANON_KEY が要る"); return 2
    t0 = time.time()
    measured, runs, dist = collect(dt.date.fromisoformat(a.date_from), dt.date.fromisoformat(a.date_to))
    out, skipped, n_used = analyse(measured, runs, dist, a.split)
    ok, all05 = write_md(a.out, out, skipped, n_used, len(measured), a, a.split)
    print(f"実測 {len(measured)}・突き合わせ {n_used}・組 {len(out)}・✓ {len(ok)}・全体 {all05:.1f}%・"
          f"取得 {STATS['requests']} 本 {STATS['rows']} 行・{time.time() - t0:.0f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
