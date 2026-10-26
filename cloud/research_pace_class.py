"""研究用・1 回きり(10/27)。ペースの札の基準を「場 × 距離 × クラス」にしたとき、窓 1 年・2 年・3 年で
どうなるかを測り docs/research-pace-class/result.md を書く。
  ⛔本番 DB は REST の単純 select だけ。集計は全部 Python。書き込みなし。
  比べる= 今の道(場 × 距離・1 年)/ クラス別 1 年 / 2 年 / 3 年 / クラス別 1 年で高知も四分位
  python cloud/research_pace_class.py      # 環境変数 SUPABASE_URL / SUPABASE_SERVICE_KEY
"""
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tenkai as tk  # noqa: E402

OUT = "docs/research-pace-class"
LO = "2025-10-01"                      # 札を数える期間の頭(指示書の表と同じ)
NANKAN = ("大井", "船橋", "川崎", "浦和")
WORD = {"速い": "ハイ", "平均": "ミドル", "遅い": "スロー"}
CONFIGS = [("今の道(場×距離・1年)", 365, False, True), ("クラス別・1年", 365, True, True),
           ("クラス別・2年", 730, True, True), ("クラス別・3年", 1095, True, True),
           ("クラス別・1年・高知も四分位", 365, True, False)]


def nk_bucket(c):
    if c in ("重賞",):
        return "重賞"
    if c and (c[0] == "A" or c == "OP"):
        return "A"
    if c and c[0] == "B":
        return "B"
    if c in ("C1", "C2", "C3"):
        return c
    return None


def dist3(rows):
    n = len(rows)
    if not n:
        return n, None
    c = {w: 0 for w in WORD}
    for r in rows:
        c[r["pace"]] += 1
    return n, tuple(c[w] / n * 100 for w in ("速い", "平均", "遅い"))


def tvd(p):
    """25/50/25 からのずれ(0= ぴったり・100= 全部が 1 つの札)"""
    return (abs(p[0] - 25) + abs(p[1] - 50) + abs(p[2] - 25)) / 2


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        tk.log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    hi = (dt.datetime.now(tk.JST).date() - dt.timedelta(days=1)).isoformat()
    far = (dt.date.fromisoformat(LO) - dt.timedelta(days=1095 + 31)).isoformat()
    cls = {}
    fastest = tk.pace_fastest(base, key, far, hi, cls_out=cls)
    tk.log("レース %d 本(%s 〜 %s)・要求 %d 回" % (len(fastest), far, hi, tk.N_REQ[0]))
    days = sorted({d for (_t, d, _n) in fastest if d >= LO})
    res = {}
    for name, yrs, bc, kf in CONFIGS:
        rows, skip, lv = tk.pace_rows(base, key, days, fastest=fastest, cls=cls, years=yrs, by_class=bc, kochi_fixed=kf)
        res[name] = ({(r["track"], r["race_date"], r["race_no"]): r for r in rows}, skip, lv)
        tk.log("%s 行 %d 飛ばし %s 段 %s" % (name, len(rows), skip, lv))
    n_target = sum(1 for k in fastest if k[1] >= LO)
    os.makedirs(OUT, exist_ok=True)
    L = ["# ペースの札 クラス別の基準(研究・%s)" % hi, "",
         "札を数えた期間 %s 〜 %s・前半の取れたレース %d 本(1200m 以上・全場)。" % (LO, hi, n_target), ""]

    # 1) 基準の段と札の出たレース
    L += ["## 1. 基準をどの組で作れたか", "", "| 方式 | 札の出たレース | クラス | まとめたクラス | 場×距離に戻った | 札なし |", "|---|---|---|---|---|---|"]
    for name, *_ in CONFIGS:
        m, skip, lv = res[name]
        n = len(m)
        f = lambda k: "%.1f%%" % (lv.get(k, 0) / n * 100) if n and lv else "—"
        L.append("| %s | %d | %s | %s | %s | %d |" % (name, n, f("クラス"), f("まとめ"), f("場距離"), n_target - n))
    # 30 走に届く組の割合(2026-10-01 の窓・対象期間に出てきた (場, 距離, クラス))
    L += ["", "30 走に届く (場, 距離, クラス) の組の割合(2026-10-01 の基準・その窓に 1 走でもある組のうち):", "",
          "| 窓 | 組の数 | 30 走以上 | 割合 |", "|---|---|---|---|"]
    ref = "2026-10-01"
    for yrs in (365, 730, 1095):
        lo = (dt.date.fromisoformat(ref) - dt.timedelta(days=yrs)).isoformat()
        cnt = {}
        for (t, d, no), (_v, dm, _u) in fastest.items():
            if lo <= d < ref and cls.get((t, d, no)):
                k = (t, dm, cls[(t, d, no)])
                cnt[k] = cnt.get(k, 0) + 1
        ok = sum(1 for v in cnt.values() if v >= tk.PACE_STD_MIN)
        L.append("| %d 年 | %d | %d | %.0f%% |" % (yrs // 365, len(cnt), ok, ok / len(cnt) * 100 if cnt else 0))

    # 2) 南関 4 場のクラス別(指示書の表と同じ分け方)
    L += ["", "## 2. 南関 4 場 クラス別の札(ハイ/ミドル/スロー %)", ""]
    hdr = "| クラス | " + " | ".join(n for n, *_ in CONFIGS) + " |"
    L += [hdr, "|---" * (len(CONFIGS) + 1) + "|"]
    for b in ("重賞", "A", "B", "C1", "C2", "C3"):
        cells = []
        for name, *_ in CONFIGS:
            m = res[name][0]
            n, p = dist3([r for k, r in m.items() if k[0] in NANKAN and nk_bucket(cls.get(k)) == b])
            cells.append("%d本 %.0f/%.0f/%.0f" % ((n,) + p) if p else "—")
        L.append("| %s | %s |" % (b, " | ".join(cells)))

    # 3) 全場 (場, クラス) ごとの 25/50/25 からのずれ(30 本以上の組・本数で重み)
    L += ["", "## 3. 札の安定(25/50/25 からのずれ・0 がぴったり)", "",
          "(場, クラス) の組(30 本以上)ごとのずれを本数で重みづけ。小さいほど札がクラスでなく流れを表す。", "",
          "| 場 | " + " | ".join(n for n, *_ in CONFIGS) + " |", "|---" * (len(CONFIGS) + 1) + "|"]
    tracks = sorted({k[0] for k in res[CONFIGS[0][0]][0]})
    allv = {n: [0.0, 0] for n, *_ in CONFIGS}
    for t in tracks + ["全場"]:
        cells = []
        for name, *_ in CONFIGS:
            if t == "全場":
                a = allv[name]
                cells.append("%.1f" % (a[0] / a[1]) if a[1] else "—")
                continue
            m = res[name][0]
            grp = {}
            for k, r in m.items():
                if k[0] == t:
                    grp.setdefault(cls.get(k) or "不明", []).append(r)
            sw = sn = 0
            for c, rs in grp.items():
                n, p = dist3(rs)
                if n >= 30:
                    sw += tvd(p) * n
                    sn += n
            allv[name][0] += sw
            allv[name][1] += sn
            cells.append("%.1f" % (sw / sn) if sn else "—")
        L.append("| %s | %s |" % (t, " | ".join(cells)))

    # 4) 今の道から札が替わったレース(場ごと)
    old = res[CONFIGS[0][0]][0]
    L += ["", "## 4. 今の道から札が替わったレース(同じレースで比べる)", "",
          "| 場 | " + " | ".join(n for n, *_ in CONFIGS[1:]) + " |", "|---" * len(CONFIGS) + "|"]
    for t in tracks + ["全場"]:
        cells = []
        for name, *_ in CONFIGS[1:]:
            m = res[name][0]
            ks = [k for k in old if k in m and (t == "全場" or k[0] == t)]
            ch = sum(1 for k in ks if old[k]["pace"] != m[k]["pace"])
            cells.append("%d/%d(%.0f%%)" % (ch, len(ks), ch / len(ks) * 100) if ks else "—")
        L.append("| %s | %s |" % (t, " | ".join(cells)))
    # 南関 クラスごと
    L += ["", "南関 4 場 クラスごと(クラス別・1年):", "", "| クラス | 替わった | ハイ→ミドル以下 | スロー→ミドル以上 |", "|---|---|---|---|"]
    m = res["クラス別・1年"][0]
    for b in ("重賞", "A", "B", "C1", "C2", "C3"):
        ks = [k for k in old if k in m and k[0] in NANKAN and nk_bucket(cls.get(k)) == b]
        ch = sum(1 for k in ks if old[k]["pace"] != m[k]["pace"])
        h = sum(1 for k in ks if old[k]["pace"] == "速い" and m[k]["pace"] != "速い")
        sl = sum(1 for k in ks if old[k]["pace"] == "遅い" and m[k]["pace"] != "遅い")
        L.append("| %s | %d/%d | %d | %d |" % (b, ch, len(ks), h, sl))
    with open(os.path.join(OUT, "result.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    # サイトの読み方と照らす用= 名前ごとのクラス
    names = {}
    for r in tk.rows_window(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,race_name,race_kind"
                            "&race_date=gte.{lo}&race_date=lte.{hi}&order=race_date.asc,track.asc,race_no.asc", LO, hi):
        k = (r["track"], r.get("race_name") or "", r.get("race_kind") or "")
        names[k] = names.get(k, 0) + 1
    with open(os.path.join(OUT, "class_names.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["track", "race_name", "race_kind", "pace_class", "n"])
        for (t, nm, kd), n in sorted(names.items()):
            w.writerow([t, nm, kd, tk.pace_class(nm, kd, t) or "", n])
    tk.log("書いた %s/result.md" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
