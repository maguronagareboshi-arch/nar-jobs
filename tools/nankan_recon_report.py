# -*- coding: utf-8 -*-
"""§196b 検算 50 頭の集計(data/recon/sample_runs.csv → 標準出力)。⛔通信しない・DB に触らない。

不一致は一致率を出す前に原因で分ける(⛔閾値やパッチで合わせに行かない)。分け方は上から順に当てる:
  遠征 / 同着 / 半期切替の直後(前の半期の格のまま)/ 昇級の遅れ(3 週間前の値なら一致)/
  境界の数点(基準との差 15 点以内)/ 選抜・選定馬(自分と違う格のレースに出られる)/ 転入直後 / その他
"""
import collections
import csv
import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nankan_recon as R  # noqa: E402

LAG_DAYS = 21
EDGE = 15


def prev_half_day(d):
    y, m = int(d[:4]), int(d[5:7])
    return "%d-06-30" % y if m >= 7 else "%d-12-31" % (y - 1)


def thresholds(age, d):
    col = min(age, 8) - 3
    return [t for t in (R.TH[R.half(d)][k][col] for k in R.CLASSES[:-1]) if t is not None]


def main():
    rows = list(csv.DictReader(open(R.DATA / "sample_runs.csv", encoding="utf-8")))
    by = collections.defaultdict(list)
    for r in rows:
        by[r["code"]].append(r)
    for rs in by.values():
        rs.sort(key=lambda r: (r["d"], int(r["no"])))
    n_pts = sum(1 for r in rows if r["earned_off"] != "")
    same_pts = sum(1 for r in rows if r["earned_off"] != "" and r["earned_calc"] != "" and abs(float(r["earned_calc"]) - float(r["earned_off"])) < 0.51)
    print("着内ポイント(DB の名前+公式の表 vs 公式ページ)= %d / %d 走一致" % (same_pts, n_pts))
    for key, label in (("o_R1", "公式の点で逆算"), ("kaku_R1A", "DB の点で逆算")):
        tot = 0
        ok = 0
        none = 0
        causes = collections.Counter()
        ex = collections.defaultdict(list)
        for code, rs in by.items():
            for i, r in enumerate(rs):
                cls = r["off_cls"].split("/") if r["off_cls"] else []
                if not cls:
                    continue
                tot += 1
                g = r[key]
                if not g:
                    none += 1
                    causes["復元できない(走歴の欠け・点が決まらない)"] += 1
                    continue
                if g in cls:
                    ok += 1
                    continue
                age = int(r["age"])
                bcol = "o_before" if key == "o_R1" else "points_before"
                before = float(r[bcol]) if r[bcol] else None
                earlier = [y for y in rs[:i] if (dt.date.fromisoformat(r["d"]) - dt.date.fromisoformat(y["d"])).days >= LAG_DAYS]
                old_pts = float(earlier[-1][bcol]) if earlier and earlier[-1][bcol] else None
                if r["remote_between"] == "True" and any(y["d"] >= r["d"] for y in rs):
                    c = "遠征(間に他地区の走)"
                elif r["tie"] == "True":
                    c = "同着"
                elif int(r["d"][5:7]) in (1, 7) and int(r["d"][8:10]) <= 25 and R.grade(before, age - (1 if r["d"][5:7] == "01" else 0), prev_half_day(r["d"])) in cls:
                    c = "半期切替の直後(前の半期の格のまま)"
                elif old_pts is not None and R.grade(old_pts, age, r["d"]) in cls and R.CLASSES.index(g) < R.CLASSES.index(cls[0]):
                    c = "昇級の遅れ(%d 日前の値なら一致)" % LAG_DAYS
                elif before is not None and min(abs(before - t) for t in thresholds(age, r["d"])) <= EDGE:
                    c = "境界の数点(基準との差 %d 点以内)" % EDGE
                elif ("選抜" in r["off_title"] or "選定" in r["off_title"]):
                    c = "選抜・選定馬(違う格のレース)"
                elif r["first_nk"] and (dt.date.fromisoformat(r["d"]) - dt.date.fromisoformat(r["first_nk"])).days <= 60:
                    c = "転入直後(南関の初走から 60 日以内)"
                else:
                    c = "その他"
                causes[c] += 1
                ex[c].append("%s %s %s%sR %s 復元=%s 当時=%s 点=%s" % (r["horse"], r["d"], r["track"], r["no"], r["off_title"][-18:], g, r["off_cls"], r[bcol]))
        print("\n== 格の突き合わせ(%s・R1)= 格のあるレース %d 走・一致 %d(%.1f%%)" % (label, tot, ok, 100 * ok / max(tot, 1)))
        for c, v in causes.most_common():
            print("  %-40s %d" % (c, v))
            for e in ex[c][:4]:
                print("      ", e)
    r2 = sum(1 for r in rows if r["o_R1"] != r["o_R2"])
    print("\nR1 と R2(前々開催)で格が違った走: %d" % r2)


if __name__ == "__main__":
    main()
