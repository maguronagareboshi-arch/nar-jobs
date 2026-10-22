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
  D= B と同じ回帰・同じ頭数の特徴量で、テンだけ §232b の物差しに入れ替えたもの(全 14 場)。
     各馬のテン= 過去の走(発走日より前だけ)の「走破タイム − 上がり3F」(= 距離 −600m の通過)−
     場×距離の平年値(tenkai.pace_std・そのレースの月の 1 日より前の 1 年)。値の出た直近 D_RUNS 走の平均・
     最少 tk.TEN_MIN_RUNS 走・1200m 未満は除く(tenkai.CHIHOU_MIN_DIST)。他場の走もその場の平年値との差で使う。
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
# 偶然でないかの検定(McNemar・正確二項・Holm 補正)。⛔場は決め打ち(結果を見て足し引きしない)
MC_TRACKS_BC = ("門別", "金沢", "船橋", "大井", "高知", "川崎", "盛岡")   # B と C を比べる 7 場
MC_TRACKS_BA = ("大井", "門別", "船橋", "川崎", "浦和", "高知")          # 今の見立て A が出ている場
MC_ALPHA = 0.05
MC_KEYS = ("bc_b", "bc_c", "ba_b", "ba_a")    # bc_b= B だけ当たり / bc_c= C だけ / ba_b= B だけ / ba_a= A だけ
# D(§232b の物差しのテン)。⛔場は決め打ちの 14 場(ばんえいは上がり3F が無いので入らない)
MC_TRACKS_D = ("門別", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢", "笠松", "名古屋", "園田", "姫路",
               "高知", "佐賀")
D_RUNS = tk.PACE_D_RUNS                       # D のテンに使う直近の走数(⛔本番 tenkai と同じ値)
STAT_KEYS = ("n", "a_n", "a_hit", "b_n", "b_hit", "b_on_a", "c_n", "c_hit", "d_n", "d_hit",
             "h_n", "h_b", "h_d")             # h_n= 出走頭数 / h_b= B のテンが付いた頭数 / h_d= D のテンが付いた頭数


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
    feat = tk.pace_feat(tens, lead, front)      # ⛔本番(tenkai の全頭版)と同じ関数
    # A= add_pace と同じ: 逃げ候補(0 頭なら先行)の中でテンのいちばん速い馬 → pace_word
    cands = sorted(lead) or sorted(front)
    best = None
    for u in cands:
        if u in tens and (best is None or tens[u] < best):
            best = tens[u]
    a = tk.pace_word(t, best, band) if best is not None else None
    return feat, a


d_ten = tk.d_ten   # ⛔本番(tenkai の全頭版)と同じ関数


def race_features_d(d, rows, by_horse, style_at_race, dval, dstd):
    """D の特徴量(B と同じ tk.pace_feat・テンだけ d_ten)。⛔馬の過去走は race_date < d だけ"""
    tens, lead, front = {}, [], []
    for e in rows:
        u = e.get("runner_number")
        if u is None:
            continue
        u = int(u)
        hist = [x for x in by_horse.get(e.get("horse_name"), [])
                if tk.same_horse(e.get("birth_date"), x.get("birth_date")) and x["race_date"] < d]
        v = d_ten(hist, d, dval, dstd)
        if v is not None:
            tens[u] = v
        st = style_at_race.get(u)
        if st == "逃げ":
            lead.append(u)
        elif st == "先行":
            front.append(u)
    return tk.pace_feat(tens, lead, front)


vec = tk.pace_vec   # ⛔本番(tenkai の全頭版)と同じ関数


def mode_label(labels):
    """最頻の流れ。同数は WORDS の順(速い→平均→遅い)。空なら None"""
    if not labels:
        return None
    c = {w: 0 for w in WORDS}
    for x in labels:
        c[x] = c.get(x, 0) + 1
    return max(WORDS, key=lambda w: (c[w], -WORDS.index(w)))


def fit_model(train, fk="f"):
    """B の学習。None(行が足りない)/ ("const", 語)/ sklearn の pipeline。⛔正則化は既定のまま(調整しない)。
    ⛔本番の係数(cloud/pace_model.py)もこの関数で作る"""
    ys = [r["y"] for r in train]
    if len(train) < B_MIN_TRAIN:
        return None
    if len(set(ys)) == 1:
        return ("const", ys[0])
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    m.fit([vec(r[fk]) for r in train], ys)
    return m


def fit_predict(train, test, fk="f"):
    """B= 標準化つき多項ロジスティック回帰(fk="fd" で D)"""
    m = fit_model(train, fk)
    if m is None:
        return [None] * len(test)
    if isinstance(m, tuple):
        return [m[1]] * len(test)
    return list(m.predict([vec(r[fk]) for r in test])) if test else []


def walk_forward(recs, test_months, use_b=True):
    """recs= [{t, ym, y, f, a}] → 場ごとの {(場): 数}。月 m の B/C は m より前の TRAIN_MONTHS か月だけで作る"""
    by_t = {}
    for r in recs:
        by_t.setdefault(r["t"], []).append(r)
    stat = {}
    for t, rs in sorted(by_t.items()):
        s = {k: 0 for k in STAT_KEYS}
        bc, ba, dc, db = [], [], [], []     # McNemar の組(同じレースの当たり外れ)
        for m in test_months:
            test = [r for r in rs if r["ym"] == m]
            if not test:
                continue
            lo = ym_add(m, -TRAIN_MONTHS)
            train = [r for r in rs if lo <= r["ym"] < m]
            c = mode_label([r["y"] for r in train])
            bp = fit_predict(train, test) if use_b else [None] * len(test)
            has_d = use_b and all("fd" in r for r in train + test)
            dp = fit_predict(train, test, "fd") if has_d else [None] * len(test)
            for r, b, dd in zip(test, bp, dp):
                s["n"] += 1
                s["h_n"] += r.get("nr", 0)
                s["h_b"] += (r["f"] or {}).get("n_ten", 0)
                s["h_d"] += (r.get("fd") or {}).get("n_ten", 0)
                if dd is not None:
                    s["d_n"] += 1
                    s["d_hit"] += 1 if dd == r["y"] else 0
                    if c is not None:
                        dc.append((dd == r["y"], c == r["y"]))
                    if b is not None:
                        db.append((dd == r["y"], b == r["y"]))
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
                if b is not None and c is not None:
                    bc.append((b == r["y"], c == r["y"]))
                if b is not None and r["a"] is not None:
                    ba.append((b == r["y"], r["a"] == r["y"]))
        s["bc_b"], s["bc_c"] = mc_count(bc)
        s["ba_b"], s["ba_a"] = mc_count(ba)
        s["dc_d"], s["dc_c"] = mc_count(dc)
        s["db_d"], s["db_b"] = mc_count(db)
        if s["n"]:
            stat[t] = s
    return stat


def mc_count(pairs):
    """[(x 当たり, y 当たり)] → (x だけ当たり, y だけ当たり)。両方当たり・両方外れは数えない"""
    xo = sum(1 for x, y in pairs if x and not y)
    yo = sum(1 for x, y in pairs if y and not x)
    return xo, yo


def mc_p(xo, yo):
    """McNemar の正確二項(両側)。n= xo+yo が 0 なら 1"""
    import math
    n = xo + yo
    if n == 0:
        return 1.0
    k = min(xo, yo)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def holm(ps):
    """{名: p} → {名: 補正後 p}(Holm・単調にそろえる)"""
    items = sorted(ps.items(), key=lambda kv: kv[1])
    m, out, run = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def mcnemar_rows(stat, tracks, xk, yk):
    """場ごとの (x だけ, y だけ, p, 補正後 p, 合格)。合格= 補正後 p < MC_ALPHA かつ x だけ > y だけ"""
    raw = {}
    for t in tracks:
        s = stat.get(t) or {}
        xo, yo = s.get(xk, 0), s.get(yk, 0)
        raw[t] = (xo, yo, mc_p(xo, yo))
    adj = holm({t: v[2] for t, v in raw.items()})
    return {t: {"x_only": v[0], "y_only": v[1], "p": v[2], "p_holm": adj[t],
                "pass": bool(adj[t] < MC_ALPHA and v[0] > v[1])} for t, v in raw.items()}


def rate(a, b):
    return round(a / b, 4) if b else None


def summarize(stat):
    rows = {}
    tot = {k: 0 for k in STAT_KEYS}
    for t, s in list(stat.items()) + [("全体", None)]:
        if s is None:
            s = tot
        else:
            for k in tot:
                tot[k] += s.get(k, 0)
        rows[t] = {"races": s["n"],
                   "a_cover": rate(s["a_n"], s["n"]), "a_hit_cover": rate(s["a_hit"], s["a_n"]),
                   "a_hit_all": rate(s["a_hit"], s["n"]),
                   "b_cover": rate(s["b_n"], s["n"]), "b_hit_cover": rate(s["b_hit"], s["b_n"]),
                   "b_hit_all": rate(s["b_hit"], s["n"]), "b_hit_on_a": rate(s["b_on_a"], s["a_n"]),
                   "c_cover": rate(s["c_n"], s["n"]), "c_hit_cover": rate(s["c_hit"], s["c_n"]),
                   "c_hit_all": rate(s["c_hit"], s["n"]),
                   "d_cover": rate(s.get("d_n", 0), s["n"]), "d_hit_cover": rate(s.get("d_hit", 0), s.get("d_n", 0)),
                   "d_hit_all": rate(s.get("d_hit", 0), s["n"]),
                   "horse_ten_b": rate(s.get("h_b", 0), s.get("h_n", 0)),
                   "horse_ten_d": rate(s.get("h_d", 0), s.get("h_n", 0))}
    return rows


def pct(x):
    return "-" if x is None else "%.1f%%" % (100 * x)


def mc_md(mc, title, xn, yn):
    out = ["", "## " + title, "", "| 場 | %s だけ当たり | %s だけ当たり | p | 補正後 p(Holm) | 合格 |" % (xn, yn),
           "|---|---|---|---|---|---|"]
    for t, r in mc.items():
        out.append("| %s | %d | %d | %.4g | %.4g | %s |" % (t, r["x_only"], r["y_only"], r["p"], r["p_holm"],
                                                         "合格" if r["pass"] else "-"))
    return out


def to_md(rows, meta, mc=None):
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
    if mc:
        out += mc_md(mc["b_vs_c"], "偶然でないか(B と C・McNemar 正確二項・7 場で Holm・合格= 補正後 p<%.2f かつ B が多い)"
                     % MC_ALPHA, "B", "C")
        out += mc_md(mc["b_vs_a"], "偶然でないか(B と A・A が出せたレースだけ・6 場で Holm)", "B", "A")
    if mc and "d_vs_c" in mc:
        out += ["", "## D(テンを「走破タイム − 上がり3F」に入れ替え・全 14 場)", "",
                "| 場 | レース | D 出せた | D 一致(全) | B 一致(全) | C 一致(全) | テンが付いた馬 B | テンが付いた馬 D |",
                "|---|---|---|---|---|---|---|---|"]
        for t, r in rows.items():
            out.append("| %s | %d | %s | %s | %s | %s | %s | %s |" % (
                t, r["races"], pct(r["d_cover"]), pct(r["d_hit_all"]), pct(r["b_hit_all"]), pct(r["c_hit_all"]),
                pct(r["horse_ten_b"]), pct(r["horse_ten_d"])))
        out += mc_md(mc["d_vs_c"], "偶然でないか(D と C・14 場で Holm・合格= 補正後 p<%.2f かつ D が多い)"
                     % MC_ALPHA, "D", "C")
        out += mc_md(mc["d_vs_b"], "偶然でないか(D と B・14 場で Holm・合格= 補正後 p<%.2f かつ D が多い)"
                     % MC_ALPHA, "D", "B")
    return "\n".join(out) + "\n"


def load_recs(base, key, feat_months, with_d=False):
    """feat_months の各月のレース → [{t, ym, y, f, a, nr}](with_d なら fd も)。
    ⛔本番の係数(cloud/pace_model.py)も同じ材料で作る(with_d=True)"""
    f_lo = feat_months[0] + "-01"
    f_hi = (dt.date.fromisoformat(ym_add(feat_months[-1], 1) + "-01") - dt.timedelta(days=1)).isoformat()
    far = (dt.date.fromisoformat(f_lo) - dt.timedelta(days=tk.PAST_DAYS + 1)).isoformat()
    tk.log("特徴量 %s〜%s・過去走は %s から" % (f_lo, f_hi, far))

    labels = tk.rows_window(base, key, "/rest/v1/nar_race_pace?select=track,race_date,race_no,pace"
                            "&race_date=gte.{lo}&race_date=lte.{hi}&order=race_date.asc,track.asc,race_no.asc",
                            f_lo, f_hi)
    labels = [r for r in labels if r.get("pace") in WORDS]
    tk.log("  正解 %d 本・要求 %d 回" % (len(labels), tk.N_REQ[0]))
    runs = tk.rows_window(base, key,
                          "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date"
                          + (",time_sec,last3f" if with_d else "") +
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
    dval, fastest = {}, {}
    if with_d:
        # §232b と同じ材料: 距離は nar_races・前半= 走破 − 上がり3F・1200m 未満と 0 以下は除く
        dist = {}
        for r in tk.rows_window(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,distance_m"
                                "&race_date=gte.{lo}&race_date=lte.{hi}"
                                "&order=race_date.asc,track.asc,race_no.asc", far, f_hi):
            if r.get("distance_m"):
                dist[(r["track"], r["race_date"], int(r["race_no"]))] = int(r["distance_m"])
        dval = tk.d_values(runs, dist)          # ⛔本番(tenkai の全頭版)と同じ関数
        items = [(t, d, no, u, v, dm) for (t, d, no, u), (v, dm) in dval.items()]
        fastest = tk.race_fastest(items)        # ⛔§232b の関数をそのまま
        tk.log("  D の材料 %d 走・%d レース・要求 %d 回" % (len(dval), len(fastest), tk.N_REQ[0]))
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
        dstd = tk.pace_std(fastest, start) if with_d else {}     # ⛔§232b の平年値(その月より前の 1 年)
        for r in by_month.get(ym, []):
            k = (r["track"], r["race_date"], int(r["race_no"]))
            f, av = race_features(r["track"], r["race_date"], by_race.get(k, []), by_horse,
                                  sty_by_race.get(k, {}), ten_all, std, band)
            rec = {"t": r["track"], "ym": ym, "y": r["pace"], "f": f, "a": av, "nr": len(by_race.get(k, []))}
            if with_d:
                rec["fd"] = race_features_d(r["race_date"], by_race.get(k, []), by_horse, sty_by_race.get(k, {}),
                                            dval, dstd)
            recs.append(rec)
        tk.log("  %s レース %d 本・標準 %d 組・帯 %d 場" % (ym, len(by_month.get(ym, [])), len(std), len(band)))
    return recs


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
    recs = load_recs(base, key, feat_months, with_d=True)
    stat = walk_forward(recs, months(TEST_FROM, TEST_TO))
    rows = summarize(stat)
    mc = {"b_vs_c": mcnemar_rows(stat, MC_TRACKS_BC, "bc_b", "bc_c"),
          "b_vs_a": mcnemar_rows(stat, MC_TRACKS_BA, "ba_b", "ba_a"),
          "d_vs_c": mcnemar_rows(stat, MC_TRACKS_D, "dc_d", "dc_c"),
          "d_vs_b": mcnemar_rows(stat, MC_TRACKS_D, "db_d", "db_b")}
    meta = {"built": dt.datetime.now(tk.JST).isoformat(timespec="minutes"), "test": [TEST_FROM, TEST_TO],
            "train_months": TRAIN_MONTHS, "b_min_train": B_MIN_TRAIN, "requests": tk.N_REQ[0],
            "d_runs": D_RUNS, "d_min_runs": tk.TEN_MIN_RUNS, "d_min_dist": tk.CHIHOU_MIN_DIST,
            "features": ["f1", "f2", "f3", "miss1", "miss2", "miss3", "n_ten", "n_lead", "n_front", "solo"]}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as fp:
        json.dump({"meta": meta, "tracks": rows, "mcnemar": mc}, fp, ensure_ascii=False, indent=1)
    md = to_md(rows, meta, mc)
    with open(os.path.join(a.out, "result.md"), "w", encoding="utf-8") as fp:
        fp.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
