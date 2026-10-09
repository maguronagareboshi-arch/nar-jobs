# -*- coding: utf-8 -*-
"""研究用・1 回きり: 「勝負がかり」と言われる場面の馬が、人気からの見込み以上に勝つか(2025-10-01〜2026-09-30・地方全場)。
便 .github/workflows/yari-situations.yml(workflow_dispatch のみ)から走らせ、docs/yari-situations/result.md を書く。

⛔本番 DB では REST の単純 select だけ(取得関数は late_money.py を流用)。集計は全部ここ。書き込みなし。
確定単勝は 2025-10〜2026-08 が無い(nar_odds_ticks・win_odds_close とも)→ 人気と単勝払戻で数える(2026-10-10 決定)。
定義(すべてレース前に分かる値だけ):
  前走= 同じ馬(馬名+生年月日)の nar_runs で、その日より前の最後の出走(着順あり)。中央・海外の出走は入らない。
  騎手の勝率= そのレース日より前 365 日(当日を含まない)の nar_runs の 1 着数÷騎乗数。騎乗 MIN_RIDES 未満は判定不能。
  騎手強化/弱化= 前走と騎手が違い、今回の騎手の勝率 − 前走騎手の勝率 が +5pt 以上/−5pt 以下。
  転厩初戦= 前走と調教師が違う。遠征= 前走と場が違う(同じ地区内/地区外を別行)。
  減量= weight_mark(負担重量の頭の記号)がある。休み明け= 前走から 90 日以上。連闘= 8 日以内・中 1 週= 9〜14 日。
  対照= 前走があり、どれにも当たらない馬(追加区分の 2 つは対照の判定に使わない)。
  追加: 人気急上昇= 前走人気 − 今回人気 >= 5。前走凡走の上位人気= 前走 6 着以下で今回 1〜3 番人気。
  見込み= 「人気順位×頭数(〜8/9〜10/11〜12/13〜)」ごとの勝率を当てた和。前半の馬は後半から作った表・後半の馬は前半の表(交差)。
  回収率= 1 着馬は単勝払戻 y(100 円あたり)・他は 0 の和÷頭数。同着・払戻なし・人気が空のレースは除外。
  9 月の照合= 確定単勝(nar_odds_ticks f=true の最大 id)の正規化確率を見込み・確定倍率で回収率(同じ馬だけ)。
"""
import bisect
import datetime as dt
import io
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import rows_by_id, rows_offset, num, JST, log  # noqa: E402
import research_period as rp  # noqa: E402

D_FROM, D_TO, SCHED = rp.period(dt.date(2025, 10, 1), dt.date(2026, 9, 30), yearly=True)
H_FROM = rp.one_year_from(D_FROM - dt.timedelta(days=1))  # 前走と騎手勝率のための履歴(既定 2024-10-01)
HALF2 = rp.add_months(D_FROM, 6)  # 既定 2026-04-01
H1_LAB = "前半 %s〜%s" % (rp.ym(D_FROM), rp.ym(HALF2 - dt.timedelta(days=1)))
H2_LAB = "後半 %s〜%s" % (rp.ym(HALF2), rp.ym(D_TO))
SEP = dt.date(2026, 9, 1)
MIN_RIDES = 30
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "yari-situations", rp.out_name(SCHED, D_TO))

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
    runs, pays, fins = [], [], []
    for a, b in months(H_FROM, D_TO):
        q = "race_date=gte.%s&race_date=lte.%s" % (a.isoformat(), b.isoformat())
        r = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date,"
                        "jockey,trainer,finish,popularity,weight_mark&%s"
                        "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc" % q)
        runs.extend(r)
        n_p = n_o = 0
        if b >= D_FROM:
            p = rows_offset(base, key, "/rest/v1/nar_race_payouts?select=track,race_date,race_no,payouts&%s"
                            "&order=race_date.asc,track.asc,race_no.asc" % q)
            pays.extend(p)
            n_p = len(p)
        if a >= SEP:
            o = rows_by_id(base, key, "/rest/v1/nar_odds_ticks?select=id,track,race_date,race_no,w&f=eq.true&%s" % q)
            fins.extend(o)
            n_o = len(o)
        log("%s 出走 %d 行・払戻 %d 行・確定単勝 %d 行" % (a.strftime("%Y-%m"), len(r), n_p, n_o))
    return runs, pays, fins


def to_int(v):
    try:
        x = int(str(v).strip())
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def cell():
    return {"n": 0, "win": 0, "exp": 0.0, "ret": 0.0, "races": set()}


def add(c, won, exp, ret, rid):
    c["n"] += 1
    c["win"] += won
    c["exp"] += exp
    c["ret"] += ret
    c["races"].add(rid)


SCENES = (("all", "全馬一律"), ("j_up", "騎手強化(+5pt 以上)"), ("j_dn", "騎手弱化(−5pt 以下)"),
          ("j_unk", "騎手替わり・勝率判定不能(参考)"), ("tenkyu", "転厩初戦"), ("ensei_in", "遠征・同じ地区内"),
          ("ensei_out", "遠征・地区外"), ("genryo", "減量騎手"), ("yasumi", "休み明け(90 日以上)"),
          ("rento", "連闘(8 日以内)"), ("naka1", "中 1 週(9〜14 日)"), ("ctrl", "対照= どれにも当たらない"),
          ("noprev", "前走なし(データ内・参考)"))
EXTRA = (("pop_up", "人気急上昇(前走人気より 5 つ以上上)"), ("weak_fav", "前走 6 着以下で今回 1〜3 番人気"))
POPS = (("p1", "1〜3 人気"), ("p4", "4〜6 人気"), ("p7", "7 人気以下"))


def fbin(n):
    return "〜8" if n <= 8 else ("9〜10" if n <= 10 else ("11〜12" if n <= 12 else "13〜"))


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    runs, pays, fins = fetch(base, key)
    bd = defaultdict(set)
    for r in runs:
        if r.get("birth_date"):
            bd[r["horse_name"]].add(r["birth_date"])
    hist = defaultdict(list)   # 馬 → [(date, track, jockey, trainer, pop, finish)]
    jk = defaultdict(list)
    started = []
    for r in runs:
        f = to_int(r.get("finish"))
        if f is None or not r.get("horse_name"):
            continue
        b = r.get("birth_date") or (next(iter(bd[r["horse_name"]])) if len(bd[r["horse_name"]]) == 1 else "")
        d = dt.date.fromisoformat(r["race_date"])
        hk = (r["horse_name"], b)
        j = nm(r.get("jockey"))
        hist[hk].append((d, r["track"], j, nm(r.get("trainer")), to_int(r.get("popularity")), f))
        if j:
            jk[j].append((d, 1 if f == 1 else 0))
        started.append((r, hk, d, f, j))
    hdates = {}
    for k, v in hist.items():
        v.sort(key=lambda x: x[0])
        hdates[k] = [x[0] for x in v]
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

    def rk(o):
        return (o["track"], o["race_date"], int(o["race_no"]))

    payk = {}
    for p in pays:
        w = [x for x in (p.get("payouts") or []) if isinstance(x, dict) and x.get("t") == "win"]
        payk[rk(p)] = w
    final = {}
    for o in fins:
        k = rk(o)
        if k not in final or o["id"] > final[k]["id"]:
            final[k] = o
    by_race = defaultdict(list)
    for it in started:
        if D_FROM <= it[2] <= D_TO:
            by_race[rk(it[0])].append(it)
    ex = defaultdict(int)
    ex_pop_runs = 0
    used = []
    for k, items in by_race.items():
        ex["races"] += 1
        nopop = [it for it in items if to_int(it[0].get("popularity")) is None]
        if nopop:
            ex["races_nopop"] += 1
            ex_pop_runs += len(nopop)
            ex["runs_nopop_race"] += len(items)
            continue
        w = payk.get(k)
        if not w:
            ex["races_nopay"] += 1
            ex["runs_nopay"] += len(items)
            continue
        winners = [it for it in items if it[3] == 1]
        if len(w) != 1 or len(winners) != 1 or num(w[0].get("y")) is None \
                or str(w[0].get("c")).strip() != str(winners[0][0]["runner_number"]):
            ex["races_dh"] += 1
            ex["runs_dh"] += len(items)
            continue
        used.append((k, items, num(w[0]["y"])))
    tab = {"h1": defaultdict(lambda: [0, 0]), "h2": defaultdict(lambda: [0, 0])}
    for k, items, y in used:
        hb = "h1" if items[0][2] < HALF2 else "h2"
        fb = fbin(len(items))
        for r, hk, d, f, j in items:
            t = tab[hb][(to_int(r["popularity"]), fb)]
            t[0] += 1
            t[1] += 1 if f == 1 else 0

    def rate(hb, p, fb):
        t = tab[hb].get((p, fb))
        return (t[1] / t[0]) if t and t[0] else None

    C = {s: {x: cell() for x in ("t", "p1", "p4", "p7", "h1", "h2")} for s, _ in SCENES + EXTRA}
    chk = {x: cell() for x in ("h1", "h2")}
    sep = {x: cell() for x in ("all_pop", "all_odd", "tk_pop", "tk_odd")}
    marks = defaultdict(int)
    for k, items, y in used:
        rid = "%s|%s|%d" % k
        fb = fbin(len(items))
        fw = (final.get(k) or {}).get("w") or {}
        od = {str(h): num(v) for h, v in fw.items() if num(v)}
        osum = sum(1.0 / v for v in od.values()) if od else 0
        for r, hk, d, f, j in items:
            pop = to_int(r["popularity"])
            hb = "h1" if d < HALF2 else "h2"
            other = "h2" if hb == "h1" else "h1"
            e = rate(other, pop, fb)
            if e is None:
                ex["runs_nocell"] += 1
                e = 0.0
            won = 1 if f == 1 else 0
            ret = y if won else 0.0
            ex["runs"] += 1
            add(chk[hb], won, rate(hb, pop, fb) or 0.0, ret, rid)
            sc, xs = ["all"], []
            hs = hist[hk]
            i = bisect.bisect_left(hdates[hk], d) - 1
            mk = (r.get("weight_mark") or "").strip()
            if mk:
                marks[mk] += 1
                sc.append("genryo")
            if i < 0:
                sc.append("noprev")
            else:
                pd, pt, pj, ptr, ppop, pf = hs[i]
                flag = bool(mk)
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
                if not flag:
                    sc.append("ctrl")
                if ppop is not None and ppop - pop >= 5:
                    xs.append("pop_up")
                if pf >= 6 and pop <= 3:
                    xs.append("weak_fav")
            pb = "p1" if pop <= 3 else ("p4" if pop <= 6 else "p7")
            for x in sc:
                add(C[x]["t"], won, e, ret, rid)
                add(C[x][pb], won, e, ret, rid)
                add(C[x][hb], won, e, ret, rid)
            for x in xs:
                add(C[x]["t"], won, e, ret, rid)
                add(C[x][hb], won, e, ret, rid)
            h = str(r["runner_number"])
            if d >= SEP and h in od:
                fo = od[h]
                for s_, p_ in (("all", "all"), ("tenkyu", "tk")):
                    if s_ in sc:
                        add(sep[p_ + "_pop"], won, e, ret, rid)
                        add(sep[p_ + "_odd"], won, (1.0 / fo) / osum, won * fo * 100, rid)
    write(C, chk, sep, ex, ex_pop_runs, marks, len(runs), len(pays), len(fins), tab)


def ae(c):
    return "%.2f" % (c["win"] / c["exp"]) if c["exp"] > 0 else "-"


def roi(c):
    return "%.1f%%" % (c["ret"] / c["n"]) if c["n"] else "-"


def row(lab, c):
    return "| %s | %d | %d | %.1f | %s | %s | %d |" % (lab, c["n"], c["win"], c["exp"], ae(c), roi(c), len(c["races"]))


HEAD = "| 場面 | 頭数 | 1着数 | 見込み | 実際÷見込み | 単勝回収率 | レース数 |\n|---|---:|---:|---:|---:|---:|---:|"


def write(C, chk, sep, ex, ex_pop_runs, marks, n_runs, n_pays, n_fins, tab):
    L = ["# 勝負がかりと言われる場面(研究・1 回きり・人気と単勝払戻で)", "",
         "期間 %s〜%s・地方全場。作成 %s。道= Actions(手元 nar-stats は Actions 内で毎回作る PG で常設の表が無い)。"
         "確定単勝は 2025-10〜2026-08 が無いので、見込みは人気順位×頭数の勝率表(前半⇔後半の交差)。"
         % (D_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "- 取得: 出走 %d 行(履歴 %s〜)・払戻 %d 行・確定単勝(9 月)%d 行" % (n_runs, H_FROM, n_pays, n_fins),
         "- 対象レース %d・使えた出走 %d" % (ex["races"], ex["runs"]),
         "- 除外: 人気が空 %d レース(空の馬 %d 頭・レース全体 %d 頭)・払戻なし %d レース(%d 頭)・同着/払戻と 1 着が合わない %d レース(%d 頭)"
         % (ex["races_nopop"], ex_pop_runs, ex["runs_nopop_race"], ex["races_nopay"], ex["runs_nopay"], ex["races_dh"], ex["runs_dh"]),
         "- 勝率表に該当マスなし(見込み 0 で数えた)%d 頭" % ex["runs_nocell"],
         "- 減量の印 %s" % "・".join("%s %d" % kv for kv in sorted(marks.items(), key=lambda x: -x[1])),
         "- 騎手勝率は騎乗 %d 未満を判定不能。前走は地方の出走だけ(中央は入らない)。遠征の地区は 北海道/ばんえい/岩手/南関東/金沢/東海/兵庫/高知/佐賀。" % MIN_RIDES,
         "", "## 照合= 全馬一律の実際÷見込み", "", "| 半期 | 交差の表で当てた | 同じ半期の表で当てた(参考・1.00 になるはず) |", "|---|---:|---:|"]
    for hb, lab in (("h1", H1_LAB), ("h2", H2_LAB)):
        L.append("| %s | %s | %s |" % (lab, ae(C["all"][hb]), ae(chk[hb])))
    L += ["", "## 9 月だけ= 人気版と確定オッズ版の差(同じ馬)", "", HEAD,
          row("全馬一律・人気版", sep["all_pop"]), row("全馬一律・確定オッズ版", sep["all_odd"]),
          row("転厩初戦・人気版", sep["tk_pop"]), row("転厩初戦・確定オッズ版", sep["tk_odd"]),
          "", "## 場面ごと(1 年)", "", HEAD]
    for s, lab in SCENES + EXTRA:
        L.append(row(lab, C[s]["t"]))
    L += ["", "## 人気別", "", "| 場面 | 人気 | 頭数 | 1着数 | 見込み | 実際÷見込み | 単勝回収率 | レース数 |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    for s, lab in SCENES:
        for p, pl in POPS:
            L.append("| %s | %s" % (lab, row(pl, C[s][p])[2:]))
    L += ["", "## 再現性(%s/%s)" % (H1_LAB, H2_LAB), "",
          "| 場面 | 前半 頭数 | 前半 実際÷見込み | 前半 回収率 | 後半 頭数 | 後半 実際÷見込み | 後半 回収率 |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for s, lab in SCENES + EXTRA:
        a, b = C[s]["h1"], C[s]["h2"]
        L.append("| %s | %d | %s | %s | %d | %s | %s |" % (lab, a["n"], ae(a), roi(a), b["n"], ae(b), roi(b)))
    L += ["", "## 勝率表(人気 1〜6・前半/後半)", "", "| 頭数 | 人気 | 前半 頭数 | 前半 勝率 | 後半 頭数 | 後半 勝率 |", "|---|---:|---:|---:|---:|---:|"]
    for fb in ("〜8", "9〜10", "11〜12", "13〜"):
        for p in range(1, 7):
            a, b = tab["h1"].get((p, fb), [0, 0]), tab["h2"].get((p, fb), [0, 0])
            L.append("| %s | %d | %d | %s | %d | %s |" % (fb, p, a[0], "%.3f" % (a[1] / a[0]) if a[0] else "-",
                                                       b[0], "%.3f" % (b[1] / b[0]) if b[0] else "-"))
    L += ["", "> 回収率= 単勝払戻(100 円あたり)の和÷頭数。場面は重なる(1 頭が複数行に入る)。追加区分 2 つは対照の判定に使わない。", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
