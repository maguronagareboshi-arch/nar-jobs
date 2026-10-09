# -*- coding: utf-8 -*-
"""研究用・1 回きり: 「勝負がかり」と言われる場面の馬が、確定単勝オッズの見込み以上に勝つか(2025-10-01〜2026-09-30・地方全場)。
便 .github/workflows/yari-situations.yml(workflow_dispatch のみ)から走らせ、docs/yari-situations/result.md を書く。

⛔本番 DB では REST の単純 select だけ(取得関数は late_money.py を流用)。集計は全部ここ。書き込みなし。
定義(すべてレース前に分かる値だけ):
  前走= 同じ馬(馬名+生年月日)の nar_runs で、その日より前の最後の出走(着順あり)。中央・海外の出走は入らない。
  騎手の勝率= そのレース日より前 365 日(当日を含まない)の nar_runs の 1 着数÷騎乗数。騎乗 MIN_RIDES 未満は判定不能。
  騎手強化/弱化= 前走と騎手が違い、今回の騎手の勝率 − 前走騎手の勝率 が +5pt 以上/−5pt 以下。
  転厩初戦= 前走と調教師が違う。遠征= 前走と場が違う(同じ地区内/地区外を別行)。
  減量= weight_mark(負担重量の頭の記号)がある。休み明け= 前走から 90 日以上。連闘= 8 日以内・中 1 週= 9〜14 日。
  対照= 前走があり、どれにも当たらない馬。
  見込み= 確定単勝(nar_odds_ticks の f=true の最大 id)の 1/倍率 をレース内で正規化した和。回収率= 単勝 100 円ずつ・確定倍率。
  人気= 確定単勝倍率のレース内順位(同倍率は同順位)。
"""
import bisect
import datetime as dt
import io
import os
import sys
import urllib.parse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import rows_by_id, rows_offset, num, JST, log  # noqa: E402

D_FROM, D_TO = dt.date(2025, 10, 1), dt.date(2026, 9, 30)
H_FROM = dt.date(2024, 10, 1)  # 前走と騎手勝率のための履歴
HALF2 = dt.date(2026, 4, 1)
MIN_RIDES = 30
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "yari-situations", "result.md")

AREA = {}
for a, ts_ in (("北海道", "門別 札幌"), ("ばんえい", "帯広"), ("岩手", "盛岡 水沢"), ("南関東", "浦和 船橋 大井 川崎"),
               ("金沢", "金沢"), ("東海", "名古屋 笠松"), ("兵庫", "園田 姫路"), ("高知", "高知"), ("佐賀", "佐賀")):
    for t in ts_.split():
        AREA[t] = a


def months(a, b):
    d = dt.date(a.year, a.month, 1)
    while d <= b:
        nx = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        yield d, min(nx - dt.timedelta(days=1), b)
        d = nx


def nm(s):
    return "".join(str(s or "").split())


def fetch(base, key):
    runs, fins = [], []
    for a, b in months(H_FROM, D_TO):
        q = "race_date=gte.%s&race_date=lte.%s" % (a.isoformat(), b.isoformat())
        r = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date,"
                        "jockey,trainer,finish,weight_mark&%s&order=race_date.asc,track.asc,race_no.asc,runner_number.asc" % q)
        runs.extend(r)
        n_o = 0
        if b >= D_FROM:
            o = rows_by_id(base, key, "/rest/v1/nar_odds_ticks?select=id,track,race_date,race_no,w&f=eq.true&%s" % q)
            fins.extend(o)
            n_o = len(o)
        log("%s 出走 %d 行・確定単勝 %d 行" % (a.strftime("%Y-%m"), len(r), n_o))
    return runs, fins


def fin_int(v):
    try:
        x = int(str(v).strip())
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def cell():
    return {"n": 0, "win": 0, "exp": 0.0, "ret": 0.0, "races": set()}


def add(c, v):
    c["n"] += 1
    c["win"] += v["won"]
    c["exp"] += v["pf"]
    c["ret"] += v["won"] * v["fo"] * 100
    c["races"].add(v["rid"])


SCENES = (("all", "全馬一律"), ("j_up", "騎手強化(+5pt 以上)"), ("j_dn", "騎手弱化(−5pt 以下)"),
          ("j_unk", "騎手替わり・勝率判定不能(参考)"), ("tenkyu", "転厩初戦"), ("ensei_in", "遠征・同じ地区内"),
          ("ensei_out", "遠征・地区外"), ("genryo", "減量騎手"), ("yasumi", "休み明け(90 日以上)"),
          ("rento", "連闘(8 日以内)"), ("naka1", "中 1 週(9〜14 日)"), ("ctrl", "対照= どれにも当たらない"),
          ("noprev", "前走なし(データ内・参考)"))
POPS = (("p1", "1〜3 人気"), ("p4", "4〜6 人気"), ("p7", "7 人気以下"))


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    runs, fins = fetch(base, key)
    # 生年月日の補い(馬名に生年月日が 1 つだけなら空欄に当てる)
    bd = defaultdict(set)
    for r in runs:
        if r.get("birth_date"):
            bd[r["horse_name"]].add(r["birth_date"])
    hist = defaultdict(list)   # 馬 → [(date, track, jockey, trainer)]
    jk = defaultdict(list)     # 騎手 → [(date, won)]
    started = []
    for r in runs:
        f = fin_int(r.get("finish"))
        if f is None or not r.get("horse_name"):
            continue
        b = r.get("birth_date") or (next(iter(bd[r["horse_name"]])) if len(bd[r["horse_name"]]) == 1 else "")
        d = dt.date.fromisoformat(r["race_date"])
        hk = (r["horse_name"], b)
        j = nm(r.get("jockey"))
        hist[hk].append((d, r["track"], j, nm(r.get("trainer"))))
        if j:
            jk[j].append((d, 1 if f == 1 else 0))
        started.append((r, hk, d, f, j))
    for v in hist.values():
        v.sort()
    jd, jc = {}, {}
    for j, v in jk.items():
        v.sort()
        jd[j] = [x[0] for x in v]
        c, s = [0], 0
        for x in v:
            s += x[1]
            c.append(s)
        jc[j] = c

    def jrate(j, d):
        if j not in jd:
            return None
        a = bisect.bisect_left(jd[j], d - dt.timedelta(days=365))
        b = bisect.bisect_left(jd[j], d)
        if b - a < MIN_RIDES:
            return None
        return (jc[j][b] - jc[j][a]) / (b - a)

    final = {}
    for o in fins:
        k = (o["track"], o["race_date"], int(o["race_no"]))
        if k not in final or o["id"] > final[k]["id"]:
            final[k] = o
    ex = {"races": set(), "races_noodds": set(), "runs": 0, "runs_noodds": 0, "mark_any": 0}
    noodds_by = defaultdict(int)
    by_race = defaultdict(list)
    for r, hk, d, f, j in started:
        if not (D_FROM <= d <= D_TO):
            continue
        by_race[(r["track"], r["race_date"], int(r["race_no"]))].append((r, hk, d, f, j))
    C = {s: {"t": cell(), "p1": cell(), "p4": cell(), "p7": cell(), "h1": cell(), "h2": cell()} for s, _ in SCENES}
    marks = defaultdict(int)
    for rk, items in by_race.items():
        ex["races"].add(rk)
        fw = (final.get(rk) or {}).get("w") or {}
        od = {str(h): num(v) for h, v in fw.items() if num(v)}
        if not od:
            ex["races_noodds"].add(rk)
            noodds_by[(rk[1][:7], rk[0])] += 1
            ex["runs_noodds"] += len(items)
            continue
        s = sum(1.0 / v for v in od.values())
        for r, hk, d, f, j in items:
            h = str(r["runner_number"])
            if h not in od:
                ex["runs_noodds"] += 1
                continue
            ex["runs"] += 1
            fo = od[h]
            rank = 1 + sum(1 for x in od.values() if x < fo)
            v = {"pf": (1.0 / fo) / s, "fo": fo, "won": 1 if f == 1 else 0, "rid": "%s|%s|%d" % rk}
            sc = ["all"]
            hs = hist[hk]
            i = bisect.bisect_left(hs, (d,)) - 1
            mk = (r.get("weight_mark") or "").strip()
            if mk:
                ex["mark_any"] += 1
                marks[mk] += 1
                sc.append("genryo")
            if i < 0:
                sc.append("noprev")
            else:
                pd, pt, pj, ptr = hs[i]
                flag = False
                if pj and j and pj != j:
                    a, b = jrate(j, d), jrate(pj, d)
                    if a is None or b is None:
                        sc.append("j_unk")
                    elif a - b >= 0.05:
                        sc.append("j_up")
                        flag = True
                    elif a - b <= -0.05:
                        sc.append("j_dn")
                        flag = True
                if ptr and nm(r.get("trainer")) and ptr != nm(r.get("trainer")):
                    sc.append("tenkyu")
                    flag = True
                if pt != r["track"]:
                    sc.append("ensei_in" if AREA.get(pt, pt) == AREA.get(r["track"], r["track"]) else "ensei_out")
                    flag = True
                gap = (d - pd).days
                if gap >= 90:
                    sc.append("yasumi")
                    flag = True
                elif gap <= 8:
                    sc.append("rento")
                    flag = True
                elif gap <= 14:
                    sc.append("naka1")
                    flag = True
                if mk:
                    flag = True
                if not flag:
                    sc.append("ctrl")
            pb = "p1" if rank <= 3 else ("p4" if rank <= 6 else "p7")
            hb = "h1" if d < HALF2 else "h2"
            for x in sc:
                add(C[x]["t"], v)
                add(C[x][pb], v)
                add(C[x][hb], v)
    write(C, ex, noodds_by, marks, len(runs), len(fins))


def ae(c):
    return "%.2f" % (c["win"] / c["exp"]) if c["exp"] > 0 else "-"


def roi(c):
    return "%.1f%%" % (c["ret"] / c["n"]) if c["n"] else "-"


def row(lab, c):
    return "| %s | %d | %d | %.1f | %s | %s | %d |" % (lab, c["n"], c["win"], c["exp"], ae(c), roi(c), len(c["races"]))


HEAD = "| 場面 | 頭数 | 1着数 | 見込み | 実際÷見込み | 単勝回収率 | レース数 |\n|---|---:|---:|---:|---:|---:|---:|"


def write(C, ex, noodds_by, marks, n_runs, n_fins):
    L = ["# 勝負がかりと言われる場面(研究・1 回きり)", "",
         "期間 %s〜%s・地方全場。作成 %s。道= Actions(手元 nar-stats は Actions 内で毎回作る PG で、手元に常設の表が無いため)。"
         % (D_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "- 取得: 出走 %d 行(履歴 %s〜)・確定単勝 %d 行" % (n_runs, H_FROM, n_fins),
         "- 対象レース %d・確定単勝なしで除外 %d レース・使えた出走 %d・除外した出走 %d"
         % (len(ex["races"]), len(ex["races_noodds"]), ex["runs"], ex["runs_noodds"]),
         "- 減量の印あり %d 頭(印別 %s)" % (ex["mark_any"], "・".join("%s %d" % kv for kv in sorted(marks.items(), key=lambda x: -x[1]))),
         "- 騎手勝率は騎乗 %d 未満を判定不能。前走は地方の出走だけ(中央は入らない)。遠征の地区は 北海道/ばんえい/岩手/南関東/金沢/東海/兵庫/高知/佐賀。" % MIN_RIDES,
         "", "## 場面ごと(1 年)", "", HEAD]
    for s, lab in SCENES:
        L.append(row(lab, C[s]["t"]))
    L += ["", "## 人気別(確定単勝の順位)", "", "| 場面 | 人気 | 頭数 | 1着数 | 見込み | 実際÷見込み | 単勝回収率 | レース数 |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    for s, lab in SCENES:
        for p, pl in POPS:
            L.append("| %s | %s" % (lab, row(pl, C[s][p])[2:]))
    L += ["", "## 再現性(前半 2025-10〜2026-03/後半 2026-04〜2026-09)", "",
          "| 場面 | 前半 頭数 | 前半 実際÷見込み | 前半 回収率 | 後半 頭数 | 後半 実際÷見込み | 後半 回収率 |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for s, lab in SCENES:
        a, b = C[s]["h1"], C[s]["h2"]
        L.append("| %s | %d | %s | %s | %d | %s | %s |" % (lab, a["n"], ae(a), roi(a), b["n"], ae(b), roi(b)))
    L += ["", "## 確定単勝が無く除外したレース(月・場)", "", "| 月 | 場 | レース数 |", "|---|---|---:|"]
    for (m, t), n in sorted(noodds_by.items()):
        L.append("| %s | %s | %d |" % (m, t, n))
    L += ["", "> 見込み= 確定単勝の正規化確率の和。回収率= 単勝 100 円ずつ・確定倍率。場面は重なる(1 頭が複数行に入る)。", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
