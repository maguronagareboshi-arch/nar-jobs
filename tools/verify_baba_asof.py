# -*- coding: utf-8 -*-
"""cloud/baba.py の as-of 化(§17 監査の直し)を、手元の写しだけで検証する。
⛔本番 DB には触らない。読むのは C:/Users/kouki/nankan_ai/raw/*.csv.gz だけ(audit_baba.py と同じ材料)。

  py -3 -X utf8 tools/verify_baba_asof.py            # 検証3本 + 365 と season の比較表
  py -3 -X utf8 tools/verify_baba_asof.py --md       # 比較表を Markdown で吐く(docs 貼り付け用)

検証:
  1. as-of= 日 d の標準に d 以降の時計が1本も混ざらない(窓の上限が d であること・値が B 版と一致)
  2. 凍結= 同じ過去日を2回組んでも値が動かない(2回目は frozen を渡して据え置き)
  3. 当日暫定= 終わったレース(勝ち時計のある走)だけから出て "p":true が付く
"""
import argparse
import csv
import datetime as dt
import gzip
import io
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cloud import baba  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RAW = r"C:/Users/kouki/nankan_ai/raw"
NANKAN = {"大井": "ooi", "船橋": "funabashi", "川崎": "kawasaki", "浦和": "urawa"}
FROM, TO = dt.date(2025, 9, 1), dt.date(2026, 8, 31)


def rd(name):
    with gzip.open(os.path.join(RAW, name), "rt", encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        h = next(r)
        i = {c: k for k, c in enumerate(h)}
        for row in r:
            yield row, i


def load_samples():
    races = {}
    for row, i in rd("nar_races.csv.gz"):
        if row[i["track"]] not in NANKAN:
            continue
        races[(row[i["track"]], row[i["race_date"]], row[i["race_no"]])] = (
            row[i["distance_m"]], row[i["race_name"]], row[i["going"]])
    out = []
    for row, i in rd("nar_runs.csv.gz"):
        tr = row[i["track"]]
        if tr not in NANKAN or row[i["finish"]] != "1" or not row[i["time_sec"]]:
            continue
        m = races.get((tr, row[i["race_date"]], row[i["race_no"]]))
        if not m or not m[0]:
            continue
        out.append((tr, row[i["race_date"]], int(m[0]), baba.band_of(m[1], tr),
                    float(row[i["time_sec"]]), m[2] or ""))
    out.sort(key=lambda s: s[1])
    return out


def days_in(samples, lo, hi):
    return {s[1] for s in samples if lo.isoformat() <= s[1] <= hi.isoformat()}


def run(samples, targets, baseline, today, frozen=None, rebuild_all=False):
    return baba.build_days(samples, targets, baseline, today=today,
                           frozen=frozen, rebuild_all=rebuild_all)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    samples = load_samples()
    print("勝ち時計 %d本(南関4場)" % len(samples))
    targets = days_in(samples, FROM, TO)
    ok = True

    # ── 1. as-of: 標準の窓に d 以降が入らない
    bad = []
    for d in (dt.date(2025, 9, 5), dt.date(2026, 2, 6), dt.date(2026, 8, 31)):
        for bl in ("365", "season", "1095"):
            for lo, hi in baba.baseline_ranges(d, bl):
                if hi > d.isoformat():
                    bad.append((d, bl, lo, hi))
    print("1. as-of 窓の上限: %s" % ("OK(その日と未来は標準に入らない)" if not bad else "NG %s" % bad))
    ok &= not bad

    # 参照実装(素直な総当たり)と build_days が一致するか
    ref_bad = 0
    ref_days = sorted(targets)[-12:]
    for ds in ref_days:
        d = dt.date.fromisoformat(ds)
        for tr in NANKAN:
            rows = [(s[2], s[3], s[4]) for s in samples if s[0] == tr and s[1] == ds]
            if not rows:
                continue
            lo = (d - dt.timedelta(days=baba.STD_DAYS)).isoformat()
            bb, bd = {}, {}
            for s in samples:
                if s[0] != tr or not (lo <= s[1] < ds):
                    continue
                bd.setdefault((s[2],), []).append(s[4])
                if s[3]:
                    bb.setdefault((s[2], s[3]), []).append(s[4])
            devs = []
            for dist, band, t in rows:
                med = None
                if band and len(bb.get((dist, band), [])) >= baba.MIN_BAND:
                    med = statistics.median(bb[(dist, band)])
                elif len(bd.get((dist,), [])) >= baba.MIN_BAND:
                    med = statistics.median(bd[(dist,)])
                if med is not None:
                    devs.append(t - med)
            want = round(statistics.median(devs), 1) if len(devs) >= baba.MIN_RACES else None
            got = run(samples, {ds}, "365", d + dt.timedelta(days=1))[0].get(ds, {}).get(NANKAN[tr])
            got = got["d"] if got else None
            if want != got:
                ref_bad += 1
                print("   ずれ %s %s: 総当たり %s / build_days %s" % (ds, tr, want, got))
    print("   参照実装との一致(直近12日×4場): %s" % ("OK" if not ref_bad else "NG %d" % ref_bad))
    ok &= not ref_bad

    # ── 2. 凍結: 同じ過去日を2回組んでも動かない
    today = TO + dt.timedelta(days=1)
    first, _, _ = run(samples, targets, "365", today)
    # 2回目は「材料が増えた」状態を模して today を1か月進める(昔なら値が動いていた場面)
    second, rebuilt2, _ = run(samples, targets, "365", today + dt.timedelta(days=30), frozen=first)
    moved = [(d, p, first[d][p]["d"], second[d][p]["d"])
             for d in first for p in first[d]
             if p in second.get(d, {}) and first[d][p]["d"] != second[d][p]["d"]]
    lost = [(d, p) for d in first for p in first[d] if p not in second.get(d, {})]
    print("2. 凍結: 組み直した場日 %d / 動いた値 %d / 消えた値 %d → %s"
          % (rebuilt2, len(moved), len(lost), "OK" if not moved and not lost else "NG"))
    if moved[:5]:
        print("   例 %s" % moved[:5])
    ok &= not moved and not lost
    # --rebuild-all のときだけ動くこと(凍結が効いているかの裏取り)
    third, rebuilt3, _ = run(samples, targets, "365", today, frozen=first, rebuild_all=True)
    print("   --rebuild-all では組み直す: %d 場日 → %s" % (rebuilt3, "OK" if rebuilt3 > 0 else "NG"))

    # ── 3. 当日暫定: 終わったレースだけ・p フラグ
    day = max(targets)
    d = dt.date.fromisoformat(day)
    cur, _, _ = run(samples, {day}, "365", d)          # today = その日 = 開催中
    prov = {p: c for p in cur.get(day, {}) for c in [cur[day][p]]}
    allp = all(c.get("p") for c in prov.values()) and prov
    nfin = {}
    for s in samples:
        if s[1] == day:
            nfin[NANKAN[s[0]]] = nfin.get(NANKAN[s[0]], 0) + 1
    same_n = all(c["n"] <= nfin.get(p, 0) for p, c in prov.items())
    fin, _, _ = run(samples, {day}, "365", d + dt.timedelta(days=1))
    noprov = not any(c.get("p") for c in fin.get(day, {}).values())
    print("3. 当日暫定: %s → p 印 %s / 終わったレース数以内 %s / 翌日は確定 %s"
          % ({p: (c["d"], c["n"]) for p, c in prov.items()},
             "OK" if allp else "NG", "OK" if same_n else "NG", "OK" if noprov else "NG"))
    ok &= bool(allp) and same_n and noprov

    # ── 365 と season の比較(2025-09〜2026-08)
    a365, _, _ = run(samples, targets, "365", today)
    asea, _, _ = run(samples, targets, "season", today)
    rows = []
    for name, prefix in sorted(NANKAN.items(), key=lambda kv: kv[0]):
        v3 = [a365[d][prefix]["d"] for d in sorted(a365) if prefix in a365[d]]
        vs = [asea[d][prefix]["d"] for d in sorted(asea) if prefix in asea[d]]
        both = [(a365[d][prefix]["d"], asea[d][prefix]["d"]) for d in sorted(a365)
                if prefix in a365[d] and prefix in asea.get(d, {})]
        flat = baba_flat = 0.3
        word = sum(1 for x, y in both
                   if (abs(x) <= flat) != (abs(y) <= flat) or (x * y < 0 and max(abs(x), abs(y)) > flat))
        rows.append((name, len(v3), statistics.median(v3), min(v3), max(v3),
                     len(vs), statistics.median(vs) if vs else None,
                     min(vs) if vs else None, max(vs) if vs else None,
                     statistics.median([abs(x - y) for x, y in both]) if both else None,
                     max([abs(x - y) for x, y in both]) if both else None,
                     word, len(both)))
        _ = baba_flat
    hdr = "| 場 | 場日 | 365 中央 | 365 最小 | 365 最大 | 季節 中央 | 季節 最小 | 季節 最大 | |Δ| 中央 | |Δ| 最大 | 言葉が変わる |"
    print("\n### 365 版 と 季節版 の比較(2025-09-01〜2026-08-31)")
    print(hdr)
    print("|" + "---|" * 11)
    for r in rows:
        print("| %s | %d | %+.2f | %+.1f | %+.1f | %+.2f | %+.1f | %+.1f | %.2f | %.2f | %d/%d |"
              % (r[0], r[1], r[2], r[3], r[4], r[6], r[7], r[8], r[9], r[10], r[11], r[12]))
    # 月ごと(季節成分が取れたか)
    print("\n### 月ごとの中央値(365 / 季節)")
    print("| 場 | 月 | 365 | 季節 |")
    print("|---|---|---|---|")
    for name, prefix in sorted(NANKAN.items()):
        by = {}
        for d in sorted(a365):
            if prefix in a365[d]:
                by.setdefault(d[:7], []).append((a365[d][prefix]["d"],
                                                 asea.get(d, {}).get(prefix, {}).get("d")))
        for ym in sorted(by):
            xs = [p[0] for p in by[ym]]
            ys = [p[1] for p in by[ym] if p[1] is not None]
            print("| %s | %s | %+.1f | %s |" % (name, ym, statistics.median(xs),
                                                ("%+.1f" % statistics.median(ys)) if ys else "—"))
    print("\n判定: %s" % ("すべて OK" if ok else "NG あり"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
