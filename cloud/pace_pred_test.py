# -*- coding: utf-8 -*-
"""研究用(手押しだけ): 出走全頭の前半3F で「流れ(速い/平均/遅い)」を当てる試し。⛔本番 DB は読むだけ。

正解= nar_race_pace.pace(実際の流れ・§232)。当てる期間= 2025-09〜2026-08 の 12 か月・nar_race_pace にある場すべて。
特徴量はレースごとに **発走日より前の走だけ**(馬の過去走は race_date < その日)。テンの作り方は tenkai.py の
ten_values / ten_std / ten_band / day_off をそのまま使う(day_off は本番と同じ TEN_DAY_ADJ=False= 使わない)。
標準と四分位は **そのレースの月の 1 日より前の 1 年**の走だけ(本番の ten_year_days と同じ窓)。

比べる 3 つ(月ごとのウォークフォワード・月 m に使えるのは m より前の 12 か月だけ)
  A= 今の見立て(tenkai.add_pace と同じ 1 頭ルール・PACE_TRACKS で絞らず全場で計算)
  B= 場ごとの多項ロジスティック回帰(sklearn・StandardScaler・正則化は既定)。欠ける値は 0 と欠損フラグ
  C= 前 12 か月にいちばん多かった流れ
⛔出すのは集計の数字だけ(result.md / result.json)。走ごと・馬ごとの行は出さない(repo は PUBLIC)。

  python cloud/pace_pred_test.py --out out      # 環境変数 SUPABASE_URL / SUPABASE_SERVICE_KEY
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tenkai as tk  # noqa: E402

WORDS = ("速い", "平均", "遅い")
TEST_FROM, TEST_TO = "2025-09", "2026-08"   # 当てる月
TRAIN_MONTHS = 12                             # 学習に使う前の月数
B_MIN_TRAIN = 30                              # B の学習行がこれ未満の場・月は B を出さない(小標本で回帰しない)


def ym_add(ym, k):
    y, m = int(ym[:4]), int(ym[5:7])
    m0 = y * 12 + (m - 1) + k
    return "%04d-%02d" % (m0 // 12, m0 % 12 + 1)


def months(lo, hi):
    out, m = [], lo
    while m <= hi:
        out.append(m)
        m = ym_add(m, 1)
    return out


def year_slice(ten_of, before):
    """ten_of のうち [before − 365 日, before) の走だけ(本番の ten_year_days と同じ 1 年の窓)"""
    lo = (dt.date.fromisoformat(before) - dt.timedelta(days=365)).isoformat()
    return {k: v for k, v in ten_of.items() if lo <= k[1] < before}


def race_features(t, d, rows, by_horse, style_at_race, ten_of, std, band):
    """1 レース → (特徴量 dict, A の答え or None)。⛔馬の過去走は race_date < d だけ。

    rows= そのレースの走(runner_number・horse_name・birth_date)/ style_at_race= {馬番: 型}(発走前 as-of の派生表)
    """
    tens, lead, front = {}, [], []
    for e in rows:
        u = e.get("runner_number")
        if u is None:
            continue
        u = int(u)
        hist = [x for x in by_horse.get(e.get("horse_name"), [])
                if tk.same_horse(e.get("birth_date"), x.get("birth_date")) and x["race_date"] < d]
        picked = tk.pick_runs(hist, t)
        tv = tk.ten_values(picked, ten_of, std, None) if ten_of else []
        if len(tv) >= tk.TEN_MIN_RUNS:
            tens[u] = round(statistics.median([v for v, _a in tv]), 2)
        st = style_at_race.get(u)
        if st == "逃げ":
            lead.append(u)
        elif st == "先行":
            front.append(u)
    fs = sorted(tens.values())
    feat = {"f1": fs[0] if len(fs) > 0 else None, "f2": fs[1] if len(fs) > 1 else None,
            "f3": fs[2] if len(fs) > 2 else None, "n_ten": len(fs),
            "n_lead": len(lead), "n_front": len(front), "solo": 1 if len(lead) == 1 else 0}
    # A= add_pace と同じ: 逃げ候補(0 頭なら先行)の中でテンのいちばん速い馬 → pace_word
    cands = sorted(lead) or sorted(front)
    best = None
    for u in cands:
        if u in tens and (best is None or tens[u] < best):
            best = tens[u]
    a = tk.pace_word(t, best, band) if best is not None else None
    return feat, a


def vec(f):
    """特徴量 → 数の並び。⛔欠ける値は 0 と欠損フラグ(1= 欠け)"""
    out = []
    for k in ("f1", "f2", "f3"):
        out += [0.0, 1.0] if f[k] is None else [float(f[k]), 0.0]
    return out + [float(f["n_ten"]), float(f["n_lead"]), float(f["n_front"]), float(f["solo"])]


def mode_label(labels):
    """最頻の流れ。同数は WORDS の順(速い→平均→遅い)。空なら None"""
    if not labels:
        return None
    c = {w: 0 for w in WORDS}
    for x in labels:
        c[x] = c.get(x, 0) + 1
    return max(WORDS, key=lambda w: (c[w], -WORDS.index(w)))


def fit_predict(train, test):
    """B= 標準化つき多項ロジスティック回帰。⛔正則化は既定のまま(調整しない)"""
    ys = [r["y"] for r in train]
    if len(train) < B_MIN_TRAIN:
        return [None] * len(test)
    if len(set(ys)) == 1:
        return [ys[0]] * len(test)
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    m.fit([vec(r["f"]) for r in train], ys)
    return list(m.predict([vec(r["f"]) for r in test])) if test else []


def walk_forward(recs, test_months, use_b=True):
    """recs= [{t, ym, y, f, a}] → 場ごとの {(場): 数}。月 m の B/C は m より前の TRAIN_MONTHS か月だけで作る"""
    by_t = {}
    for r in recs:
        by_t.setdefault(r["t"], []).append(r)
    stat = {}
    for t, rs in sorted(by_t.items()):
        s = {k: 0 for k in ("n", "a_n", "a_hit", "b_n", "b_hit", "b_on_a", "c_n", "c_hit")}
        for m in test_months:
            test = [r for r in rs if r["ym"] == m]
            if not test:
                continue
            lo = ym_add(m, -TRAIN_MONTHS)
            train = [r for r in rs if lo <= r["ym"] < m]
            c = mode_label([r["y"] for r in train])
            bp = fit_predict(train, test) if use_b else [None] * len(test)
            for r, b in zip(test, bp):
                s["n"] += 1
                if r["a"] is not None:
                    s["a_n"] += 1
                    s["a_hit"] += 1 if r["a"] == r["y"] else 0
                    s["b_on_a"] += 1 if (b is not None and b == r["y"]) else 0
                if b is not None:
                    s["b_n"] += 1
                    s["b_hit"] += 1 if b == r["y"] else 0
                if c is not None:
                    s["c_n"] += 1
                    s["c_hit"] += 1 if c == r["y"] else 0
        if s["n"]:
            stat[t] = s
    return stat


def rate(a, b):
    return round(a / b, 4) if b else None


def summarize(stat):
    rows = {}
    tot = {k: 0 for k in ("n", "a_n", "a_hit", "b_n", "b_hit", "b_on_a", "c_n", "c_hit")}
    for t, s in list(stat.items()) + [("全体", None)]:
        if s is None:
            s = tot
        else:
            for k in tot:
                tot[k] += s[k]
        rows[t] = {"races": s["n"],
                   "a_cover": rate(s["a_n"], s["n"]), "a_hit_cover": rate(s["a_hit"], s["a_n"]),
                   "a_hit_all": rate(s["a_hit"], s["n"]),
                   "b_cover": rate(s["b_n"], s["n"]), "b_hit_cover": rate(s["b_hit"], s["b_n"]),
                   "b_hit_all": rate(s["b_hit"], s["n"]), "b_hit_on_a": rate(s["b_on_a"], s["a_n"]),
                   "c_cover": rate(s["c_n"], s["n"]), "c_hit_cover": rate(s["c_hit"], s["c_n"]),
                   "c_hit_all": rate(s["c_hit"], s["n"])}
    return rows


def pct(x):
    return "-" if x is None else "%.1f%%" % (100 * x)


def to_md(rows, meta):
    head = ("| 場 | レース | A 出せた | A 一致(出せた) | A 一致(全) | B 出せた | B 一致(出せた) | B 一致(全) "
            "| B 一致(A と同じ範囲) | C 一致(出せた) | C 一致(全) |")
    out = ["# 前半3F で流れを当てる試し", "", "期間 %s〜%s・月ごとのウォークフォワード(前 %d か月で学習)"
           % (TEST_FROM, TEST_TO, TRAIN_MONTHS), "", "```", json.dumps(meta, ensure_ascii=False), "```", "",
           head, "|" + "---|" * 11]
    for t, r in rows.items():
        out.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            t, r["races"], pct(r["a_cover"]), pct(r["a_hit_cover"]), pct(r["a_hit_all"]),
            pct(r["b_cover"]), pct(r["b_hit_cover"]), pct(r["b_hit_all"]), pct(r["b_hit_on_a"]),
            pct(r["c_hit_cover"]), pct(r["c_hit_all"])))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        tk.log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    feat_months = months(ym_add(TEST_FROM, -TRAIN_MONTHS), TEST_TO)      # 特徴量を作る月(学習ぶん込み)
    f_lo = feat_months[0] + "-01"
    f_hi = (dt.date.fromisoformat(ym_add(TEST_TO, 1) + "-01") - dt.timedelta(days=1)).isoformat()
    far = (dt.date.fromisoformat(f_lo) - dt.timedelta(days=tk.PAST_DAYS + 1)).isoformat()
    tk.log("特徴量 %s〜%s・過去走は %s から" % (f_lo, f_hi, far))

    labels = tk.rows_window(base, key, "/rest/v1/nar_race_pace?select=track,race_date,race_no,pace"
                            "&race_date=gte.{lo}&race_date=lte.{hi}&order=race_date.asc,track.asc,race_no.asc",
                            f_lo, f_hi)
    labels = [r for r in labels if r.get("pace") in WORDS]
    tk.log("  正解 %d 本・要求 %d 回" % (len(labels), tk.N_REQ[0]))
    runs = tk.rows_window(base, key,
                          "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date"
                          "&race_date=gte.{lo}&race_date=lte.{hi}&finish=not.is.null"
                          "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc", far, f_hi)
    tk.log("  走 %d 行・要求 %d 回" % (len(runs), tk.N_REQ[0]))
    by_horse, by_race = {}, {}
    for r in runs:
        by_horse.setdefault(r["horse_name"], []).append(r)
        by_race.setdefault((r["track"], r["race_date"], int(r["race_no"])), []).append(r)
    for v in by_horse.values():
        v.sort(key=lambda x: (x["race_date"], x["race_no"]), reverse=True)
    need = {(r["track"], r["race_date"]) for r in runs if r["track"] in tk.TEN_TRACKS}
    ten_all, _s, _b, _o = tk.fetch_ten(base, key, need)
    tk.log("  テン %d 走・要求 %d 回" % (len(ten_all), tk.N_REQ[0]))
    style_at = tk.fetch_style_window(base, key, {r["race_date"] for r in labels})
    tk.log("  派生表の型 %d 頭・要求 %d 回" % (len(style_at), tk.N_REQ[0]))
    sty_by_race = {}
    for (t, d, no, u), v in style_at.items():
        sty_by_race.setdefault((t, d, int(no)), {})[u] = v[0]

    by_month = {}
    for r in labels:
        by_month.setdefault(r["race_date"][:7], []).append(r)
    recs = []
    for ym in feat_months:
        start = ym + "-01"
        ten_y = year_slice(ten_all, start)
        std = tk.ten_std(ten_y, start)
        band = tk.ten_band(ten_y, std, None, start)
        for r in by_month.get(ym, []):
            k = (r["track"], r["race_date"], int(r["race_no"]))
            f, av = race_features(r["track"], r["race_date"], by_race.get(k, []), by_horse,
                                  sty_by_race.get(k, {}), ten_all, std, band)
            recs.append({"t": r["track"], "ym": ym, "y": r["pace"], "f": f, "a": av})
        tk.log("  %s レース %d 本・標準 %d 組・帯 %d 場" % (ym, len(by_month.get(ym, [])), len(std), len(band)))
    stat = walk_forward(recs, months(TEST_FROM, TEST_TO))
    rows = summarize(stat)
    meta = {"built": dt.datetime.now(tk.JST).isoformat(timespec="minutes"), "test": [TEST_FROM, TEST_TO],
            "train_months": TRAIN_MONTHS, "b_min_train": B_MIN_TRAIN, "requests": tk.N_REQ[0],
            "features": ["f1", "f2", "f3", "miss1", "miss2", "miss3", "n_ten", "n_lead", "n_front", "solo"]}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as fp:
        json.dump({"meta": meta, "tracks": rows}, fp, ensure_ascii=False, indent=1)
    md = to_md(rows, meta)
    with open(os.path.join(a.out, "result.md"), "w", encoding="utf-8") as fp:
        fp.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
