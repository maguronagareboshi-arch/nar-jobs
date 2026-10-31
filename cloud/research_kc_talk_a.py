"""研究用(11/1): 騎手の話は当たっているか — 集計 A(research/kc-talk-check-20261101/SPEC.md だけを見て書いた)。
入力= KC_TALK_DATA(既定 /tmp/kc_talk)の runs.csv・talks.csv。出力= docs/research-kc-talk/result_a.csv。
標準ライブラリだけ。--selftest で小さい作り物の手計算と照合する。
⛔結果には数だけ(馬名・コメントの言葉は書かない)。
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

RFROM, RTO = "2024-03-01", "2026-10-30"
KEYS = ["kyori_long", "kyori_short", "pref_long", "pref_short", "baba_wet", "baba_dry",
        "natsu", "kankaku", "waku_out", "waku_in"]
WORSE = {"kyori_long", "kyori_short", "natsu", "kankaku"}   # 予想の向き= 悪くなる(ほかは良くなる)
COLS = ["key", "units", "horses", "hit_runs", "miss_runs", "d_finish", "d_top3", "d_pop",
        "b_finish", "b_top3", "b_pop", "dd_finish", "dd_top3", "dd_pop", "agree", "disagree"]


def ival(v):
    v = (v or "").strip()
    return int(float(v)) if v else None


def label_keys(labels, dist):
    """1 つのコメントの鍵の集合(同じ鍵は 1 回)。"""
    out = set()
    for l in labels or []:
        if not isinstance(l, dict):
            continue
        k, sg, v = l.get("k"), str(l.get("s")), l.get("v")
        if k == "kyori" and sg == "-" and v in ("long", "short"):
            if dist is not None:
                out.add(f"kyori_{v}:{dist}")
        elif k == "kyori_pref" and sg == "0" and v in ("long", "short"):
            out.add("pref_" + v)
        elif k == "baba" and sg == "0" and v in ("wet", "dry"):
            out.add("baba_" + v)
        elif k == "natsu" and sg == "-":
            out.add("natsu")
        elif k == "kankaku" and sg == "-":
            out.add("kankaku")
        elif k == "waku" and sg == "0" and v in ("out", "in"):
            out.add("waku_" + v)
    return out


def cond(key, r):
    """R が当たる側= True・当たらない側= False・数えない= None。"""
    kind, _, x = key.partition(":")
    d = r["distance_m"]
    if kind == "kyori_long":
        return None if d is None else d >= int(x)
    if kind == "kyori_short":
        return None if d is None else d <= int(x)
    if kind in ("pref_long", "pref_short"):
        pd = r["prev_dist"]
        if pd is None or d is None:
            return None
        return d > pd if kind == "pref_long" else d < pd
    if kind == "baba_wet":
        g = r["going"]
        return True if g in ("重", "不") else False if g == "良" else None
    if kind == "baba_dry":
        g = r["going"]
        return True if g == "良" else False if g in ("重", "不") else None
    if kind == "natsu":
        return 6 <= int(r["race_date"][5:7]) <= 9
    if kind == "kankaku":
        return None if r["weeks"] is None else r["weeks"] >= 8
    if kind == "waku_out":
        w = r["waku"]
        return None if w is None else 7 <= w <= 8
    if kind == "waku_in":
        w = r["waku"]
        return None if w is None else 1 <= w <= 2
    raise ValueError(key)


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def unit_diff(rs):
    """rs= [(hit, run)]。→ (d_finish, d_top3, d_pop or None, n_hit, n_miss) or None。"""
    h = [r for c, r in rs if c]
    m = [r for c, r in rs if not c]
    if not h or not m:
        return None
    df = mean([r["finish"] for r in h]) - mean([r["finish"] for r in m])
    dt3 = mean([1 if r["finish"] <= 3 else 0 for r in h]) - mean([1 if r["finish"] <= 3 else 0 for r in m])
    hp = [r["finish"] - r["popularity"] for r in h if r["popularity"] is not None]
    mp = [r["finish"] - r["popularity"] for r in m if r["popularity"] is not None]
    dp = mean(hp) - mean(mp) if hp and mp else None
    return df, dt3, dp, len(h), len(m)


def prepare(runs, talks):
    """runs/talks= dict の list(CSV の文字列のまま)。→ 馬ごとの対象の走(前走・間隔・その日の鍵の回数つき)。"""
    by_h = {}
    for r in runs:
        by_h.setdefault(r["horse_key"], []).append(r)
    tk = {}
    for t in talks:
        try:
            labels = json.loads(t["labels"]) if t["labels"] else []
        except ValueError:
            labels = []
        tk.setdefault(t["horse_key"], []).append((t["race_date"], label_keys(labels, ival(t["distance_m"]))))
    targets = {}
    for hk, rs in by_h.items():
        rs.sort(key=lambda r: (r["race_date"], int(r["race_no"])))
        tl = tk.get(hk, [])
        out = []
        for i, r in enumerate(rs):
            if not (r["track"] == "高知" and r["status"] == "ok" and (r["finish"] or "").strip()
                    and RFROM <= r["race_date"] <= RTO):
                continue
            prev = None
            for p in reversed(rs[:i]):
                if p["race_date"] < r["race_date"] and p["status"] in ("ok", "chushi"):
                    prev = p
                    break
            weeks = None
            if prev:
                days = (dt.date.fromisoformat(r["race_date"]) - dt.date.fromisoformat(prev["race_date"])).days
                weeks = max(days // 7 - 1, 0)
            cnt = {}
            for d, ks in tl:
                if d < r["race_date"]:
                    for k in ks:
                        cnt[k] = cnt.get(k, 0) + 1
            out.append({"race_date": r["race_date"], "distance_m": ival(r["distance_m"]), "going": r["going"],
                        "waku": ival(r["waku"]), "finish": ival(r["finish"]), "popularity": ival(r["popularity"]),
                        "prev_dist": ival(prev["distance_m"]) if prev else None, "weeks": weeks,
                        "stood": {k for k, n in cnt.items() if n >= 2}})
        if out:
            targets[hk] = out
    return targets


def aggregate(runs, talks):
    targets = prepare(runs, talks)
    # 話ありの単位(馬×鍵)
    units = {}   # key(kyori は :X つき) -> [(hk, diff)]
    for hk, rs in targets.items():
        keys = set().union(*(r["stood"] for r in rs))
        for k in keys:
            u = unit_diff([(c, r) for r in rs if k in r["stood"] for c in [cond(k, r)] if c is not None])
            if u:
                units.setdefault(k, []).append((hk, u))
    # 土台(鍵ごと・その鍵が立っていない走だけ・全馬)
    base = {}
    for k in units:
        ds = []
        for hk, rs in targets.items():
            u = unit_diff([(c, r) for r in rs if k not in r["stood"] for c in [cond(k, r)] if c is not None])
            if u:
                ds.append(u)
        fp = [u[2] for u in ds if u[2] is not None]
        base[k] = (mean([u[0] for u in ds]), mean([u[1] for u in ds]), mean(fp))
    rows = []
    for kind in KEYS:
        us = [(k, hk, u) for k, lst in units.items() if k.partition(":")[0] == kind for hk, u in lst]
        row = {c: "" for c in COLS}
        row["key"] = kind
        row["units"] = len(us)
        if us:
            row["horses"] = len({hk for _, hk, _ in us})
            row["hit_runs"] = sum(u[3] for _, _, u in us)
            row["miss_runs"] = sum(u[4] for _, _, u in us)
            for j, nm in enumerate(["finish", "top3", "pop"]):
                ok = [(k, u) for k, _, u in us if u[j] is not None]
                row["d_" + nm] = mean([u[j] for _, u in ok])
                bb = [(u[j], base[k][j]) for k, u in ok if base[k][j] is not None]
                row["b_" + nm] = mean([b for _, b in bb])
                row["dd_" + nm] = mean([a - b for a, b in bb])
            worse = kind in WORSE
            row["agree"] = sum(1 for _, _, u in us if (u[0] > 0 if worse else u[0] < 0))
            row["disagree"] = sum(1 for _, _, u in us if (u[0] < 0 if worse else u[0] > 0))
        else:
            row["units"] = 0
        rows.append(row)
    return rows


def fmt(v):
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def read_csv(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for r in rows:
            w.writerow([fmt(r[c]) for c in COLS])


def selftest():
    def run(hk, d, dist, going, fin, pop, track="高知", st="ok", waku="1"):
        return {"horse_key": hk, "track": track, "race_date": d, "race_no": "1", "umaban": "1", "waku": waku,
                "distance_m": str(dist), "going": going, "finish": str(fin), "popularity": str(pop),
                "field_size": "8", "status": st}
    A, B, C = "A|2018-01-01", "B|", "C|2019-02-02"
    runs = [
        run(A, "2024-03-03", 1400, "良", 5, 3),   # 前走なし
        run(A, "2024-03-10", 1400, "良", 4, 2),   # 2 回目の話の日= まだ 1 回(同じ日は数えない)
        run(A, "2024-03-17", 1400, "重", 1, 4),
        run(A, "2024-03-24", 1600, "稍", 2, 1),   # 稍= baba は数えない・pref は当たる
        run(A, "2024-03-31", 1300, "良", 6, ""),  # 人気空
        run(A, "2024-04-07", 1400, "不", 3, 2),
        run(B, "2024-03-03", 1400, "重", 2, 1), run(B, "2024-03-10", 1400, "良", 4, 2),
        run(B, "2024-03-17", 1400, "良", 6, 6),
        run(C, "2024-03-03", 1400, "不", 5, 5), run(C, "2024-03-10", 1400, "良", 1, 3),
        run(C, "2024-03-17", 1400, "良", 1, 1, st="torikeshi"),   # 対象外
    ]
    lab1 = json.dumps([{"k": "baba", "s": "0", "v": "wet", "e": ""}, {"k": "baba", "s": "0", "v": "wet", "e": ""},
                       {"k": "kyori_pref", "s": "0", "v": "long", "e": ""}, {"k": "baba", "s": "-", "v": "dry", "e": ""}])
    lab2 = json.dumps([{"k": "baba", "s": "0", "v": "wet", "e": ""}, {"k": "kyori_pref", "s": 0, "v": "long", "e": ""}])
    talks = [{"horse_key": A, "race_date": "2024-03-03", "race_no": "1", "distance_m": "1400", "labels": lab1},
             {"horse_key": A, "race_date": "2024-03-10", "race_no": "1", "distance_m": "1400", "labels": lab2}]
    rows = {r["key"]: r for r in aggregate(runs, talks)}
    # 手計算(説明は SPEC の境界)
    # baba_wet A: 当たる 3/17 着1・4/7 着3 / 当たらない 3/31 着6(3/24 稍は外す・3/10 はまだ 1 回)
    #   d_finish= 2−6= −4・d_top3= 1−0= 1・人気の差= 当たらない側に人気が無い→外す
    #   土台: B= 2−5= −3・3着内 1−0= 1・人気 1−0= 1 / C= 5−1= 4・0−1= −1・0−(−2)= 2(3/17 取消は外す)/ A は当たる側なし
    #   → b_finish 0.5・b_top3 0・dd_finish −4.5・dd_top3 1・人気は単位側に無いので空
    exp_wet = {"units": 1, "horses": 1, "hit_runs": 2, "miss_runs": 1, "d_finish": -4.0, "d_top3": 1.0,
               "d_pop": None, "b_finish": 0.5, "b_top3": 0.0, "b_pop": None, "dd_finish": -4.5, "dd_top3": 1.0,
               "dd_pop": None, "agree": 1, "disagree": 0}
    # pref_long A: 当たる 3/24(1600>1400)着2 人気1・4/7(1400>1300)着3 人気2 / 当たらない 3/17 着1 人気4・3/31 着6 人気空
    #   d_finish= 2.5−3.5= −1・d_top3= 1−0.5= 0.5・d_pop= 1−(−3)= 4・土台は全馬で当たる側が無い→空
    exp_pref = {"units": 1, "horses": 1, "hit_runs": 2, "miss_runs": 2, "d_finish": -1.0, "d_top3": 0.5,
                "d_pop": 4.0, "b_finish": None, "b_top3": None, "b_pop": None, "dd_finish": None, "dd_top3": None,
                "dd_pop": None, "agree": 1, "disagree": 0}
    bad = []
    for key, exp in (("baba_wet", exp_wet), ("pref_long", exp_pref)):
        for c, v in exp.items():
            got = rows[key][c]
            got = None if got == "" else got
            if (v is None) != (got is None) or (v is not None and abs(got - v) > 1e-9):
                bad.append(f"{key}.{c}: 期待 {v} 実際 {got}")
    for k in KEYS:
        if k not in ("baba_wet", "pref_long") and rows[k]["units"] != 0:
            bad.append(f"{k}: 単位 0 のはず {rows[k]['units']}")
    if bad:
        print("selftest 失敗:\n  " + "\n  ".join(bad))
        return 1
    print("selftest ok (baba_wet 15 項・pref_long 15 項・ほか 8 鍵 0 単位)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default="docs/research-kc-talk/result_a.csv")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    src = os.environ.get("KC_TALK_DATA", "/tmp/kc_talk")
    runs = read_csv(os.path.join(src, "runs.csv"))
    talks = read_csv(os.path.join(src, "talks.csv"))
    rows = aggregate(runs, talks)
    write_rows(rows, a.out)
    print(f"集計 A: runs {len(runs)}・talks {len(talks)} → {a.out}")
    for r in rows:
        print("  " + ",".join(fmt(r[c]) for c in COLS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
