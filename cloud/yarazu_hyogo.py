# -*- coding: utf-8 -*-
"""研究用・1 回きり: 兵庫(園田・姫路)の格付修正(降級)の直前に、着順を悪くして降級を狙う走り(ヤラズ)の痕跡があるか。
便 .github/workflows/yarazu-hyogo.yml(workflow_dispatch のみ)から走らせ、docs/yarazu-hyogo/result.md を書く。
⛔本番 DB は REST の単純 select だけ(年ごと・order は一意の列の組)。書き込みなし。馬名などは結果に出さない。

決まり: 令和8年度 番組要綱 第5-2(3)= 格付修正(概ね2か月ごと・日付は非公表)で、同一クラスの近3走の着順合計の多い順に降級。
A1・C3 は対象外。修正の日・級の読み取りは class_calc.py の hyogo_tables・hyogo_label・hyogo_revisions をそのまま使う。
扱う級は古馬の表(old)だけ(3歳単独の表は対象外)。
① 修正 R ごと・級 c ごとに、R の前の最後の単独クラスの走が c の馬(前の修正より後に c で走った馬)について、
   c の連続した在籍の近3走(数えられる走)の着順合計を出す。実際の降級= R 以後〜次の修正前の最初の単独クラスの走が下の級。
   近3走が 3 つに満たない馬・R 後に単独クラスの走が無い馬は数えない。一致率= 上位 k 頭(同点は按分)∩実際の降級 ÷ k。
   着順なし(中止・除外など): a= 頭数と同じ着 / b= 数えずに前の走で補う。
② 近3走に入る走= 次の修正 R の時点の近3走に入る走(何番目か 1〜3・3= 修正前の最後)。
   境目の見込み B= その級の前の 3 回(k>0 の回)の境目の合計の中央値(R の値は使わない)。前に数えた走の合計 s・位置 p から
   「この走の後の走は境目なみ(B/3 ずつ)」として、降級圏に入る着 f*= B×p/3 − s。人気からの見込み着順 e と比べ
   |f*−e|≤3= 近い・f*−e>3= 遠い・安全・f*−e<−3= 最初から深く圏内。
   対照 C= 次の修正の近3走に入らない走(A1・C3 以外)。対照 D= A1・C3 の走。
③ 見込み= 人気×頭数ごとの平均(着順・3着内率・勝ち馬との秒差・上がり3F 順位)。自分の年を除いた全年(兵庫の全走)から作る。
   95% 区間= 馬ごとのクラスタ bootstrap 1000 回。
④ 降級直後= 実際に下がった馬の R 後の兵庫の 1・2 戦目。対照= 下がった先の級に R 前から居て R 後も同じ級で走った馬。
⑥ 見込みのずれ= 使う年の全走で 実際 − 見込み の平均。今の表と「使う年だけで作り直した表」を比べ、ほぼ 0 の方を⑦に使う。
⑦ 調子をそろえた比べ= C から級が変わった直後の 1・2 戦目を除いた C' と、級×前 2 走の着順合計×人気の層の中で比べる。
結果は docs/yarazu-hyogo/result2.md(①〜⑤は前回と同じ作り方・result.md は残す)。
"""
import datetime as dt
import io
import os
import statistics
import sys
import urllib.parse
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import class_calc as cc  # noqa: E402
from late_money import rows_offset, num, log  # noqa: E402

Y_FROM, Y_TO = 2014, 2026
D_TO = dt.date(2026, 9, 30)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "yarazu-hyogo", "result2.md")
EXCL = ("Ａ１", "Ｃ３")
MIN_CELL = 30
BOOT = 1000
RNG = np.random.default_rng(20261016)


def to_int(v):
    try:
        x = int(str(v).strip())
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 取得
def fetch(base, key):
    q = urllib.parse.quote
    runs, races, pays = [], [], []
    for tr in cc.HYOGO_TRACKS:
        for y in range(Y_FROM, Y_TO + 1):
            a, b = "%d-01-01" % y, min(dt.date(y, 12, 31), D_TO).isoformat()
            f = "track=eq.%s&race_date=gte.%s&race_date=lte.%s" % (q(tr), a, b)
            r = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,"
                            "finish,finish_note,popularity,time_sec,last3f&%s"
                            "&order=race_date.asc,race_no.asc,runner_number.asc" % f)
            rc = rows_offset(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,race_name,race_kind&%s"
                             "&order=race_date.asc,race_no.asc" % f)
            p = rows_offset(base, key, "/rest/v1/nar_race_payouts?select=track,race_date,race_no,payouts&%s"
                            "&order=race_date.asc,race_no.asc" % f)
            runs += r
            races += rc
            pays += p
            log("%s %d 出走 %d・レース %d・払戻 %d" % (tr, y, len(r), len(rc), len(p)))
    names = sorted({r["horse_name"] for r in runs if r.get("horse_name")})
    codes = []
    for i in range(0, len(names), 80):
        inq = ",".join('"' + n + '"' for n in names[i:i + 80])
        codes += cc.sb_all(base, key, "%s?select=code,horse_name&horse_name=in.(%s)" % (cc.T_CODES, q(inq)))
    cs = sorted({c["code"] for c in codes})
    log("馬名 %d・コード %d" % (len(names), len(cs)))
    led = []
    for i in range(0, len(cs), 100):
        led += cc.sb_all(base, key, "%s?select=code,horse_name,runs&code=in.(%s)" % (cc.T_PRIZE, ",".join(cs[i:i + 100])))
    log("台帳 %d 頭" % len(led))
    return runs, races, pays, led


# ---------------------------------------------------------------- 下ごしらえ
def build_nr(runs):
    by_race = defaultdict(list)
    for r in runs:
        if r.get("race_no") is None:
            continue
        by_race[(r["track"], str(r["race_date"])[:10], int(r["race_no"]))].append(r)
    nr, rinfo = {}, {}
    for k, rs in by_race.items():
        fins = [r for r in rs if to_int(r.get("finish"))]
        n = len(fins)
        started = n + sum(1 for r in rs if not to_int(r.get("finish")) and "中止" in str(r.get("finish_note") or ""))
        ts = [fnum(r.get("time_sec")) for r in fins if fnum(r.get("time_sec"))]
        wt = min(ts) if ts else None
        l3 = sorted(fnum(r.get("last3f")) for r in fins if fnum(r.get("last3f")))
        rinfo[k] = {"n": n, "started": started}
        for r in rs:
            f = to_int(r.get("finish"))
            t = fnum(r.get("time_sec"))
            l = fnum(r.get("last3f"))
            nr[k + (r.get("horse_name"),)] = {
                "fin": f, "pop": to_int(r.get("popularity")), "n": n, "started": started,
                "mar": (t - wt) if (f and t and wt) else None,
                "l3r": (l3.index(l) + 1) if (f and l and l3) else None,
                "num": str(r.get("runner_number")).strip() if r.get("runner_number") is not None else None,
                "year": int(k[1][:4]), "race": k}
    return nr, rinfo


def build_exp(nr, years=None):
    """(pop, n, year) → [件数, 着順和, 3着内, 秒差和, 秒差件数, 上がり順位和, 上がり件数]。years を渡すとその年の走だけで作る"""
    cell = defaultdict(lambda: [0, 0.0, 0, 0.0, 0, 0.0, 0])
    for v in nr.values():
        if v["fin"] and v["pop"] and v["n"] and (years is None or v["year"] in years):
            c = cell[(v["pop"], v["n"], v["year"])]
            c[0] += 1
            c[1] += v["fin"]
            c[2] += v["fin"] <= 3
            if v["mar"] is not None:
                c[3] += v["mar"]
                c[4] += 1
            if v["l3r"] is not None:
                c[5] += v["l3r"]
                c[6] += 1
    tot = defaultdict(lambda: [0, 0.0, 0, 0.0, 0, 0.0, 0])
    for (p, n, y), c in cell.items():
        t = tot[(p, n)]
        for i in range(7):
            t[i] += c[i]

    def exp(pop, n, year):
        t = tot.get((pop, n))
        if not t:
            return None
        c = cell.get((pop, n, year), [0] * 7)
        d = [t[i] - c[i] for i in range(7)]
        if d[0] < MIN_CELL:
            return None
        return {"fin": d[1] / d[0], "top3": d[2] / d[0],
                "mar": d[3] / d[4] if d[4] >= MIN_CELL else None,
                "l3r": d[5] / d[6] if d[6] >= MIN_CELL else None}
    return exp


def metrics(v, exp):
    """走 → {fin, top3, mar, l3r} の 実際 − 見込み(取れない指標は入れない)"""
    if not v or not v["fin"] or not v["pop"] or not v["n"]:
        return None
    e = exp(v["pop"], v["n"], v["year"])
    if not e:
        return None
    m = {"fin": v["fin"] - e["fin"], "top3": (1.0 if v["fin"] <= 3 else 0.0) - e["top3"], "efin": e["fin"]}
    if v["mar"] is not None and e["mar"] is not None:
        m["mar"] = v["mar"] - e["mar"]
    if v["l3r"] is not None and e["l3r"] is not None:
        m["l3r"] = v["l3r"] - e["l3r"]
    return m


def horse_seqs(led, races, nr):
    """code → 兵庫の走(日付順): {d, tr, no, lab, fin, nrv}。lab は単独クラスでなければ None。"""
    out = {}
    for r in led:
        seq = []
        for x in r.get("runs") or []:
            d = cc._date(x.get("d"))
            if x.get("tr") not in cc.HYOGO_TRACKS or not d or d > D_TO:
                continue
            k = (x.get("tr"),) + cc._rkey(x)
            lab = cc.hyogo_label(x, races.get(k))
            fin = x.get("fin") if isinstance(x.get("fin"), int) and x.get("fin") > 0 else None
            seq.append({"d": d, "tr": x.get("tr"), "no": k[2], "lab": lab, "fin": fin,
                        "nrv": nr.get(k + (r.get("horse_name"),))})
        seq.sort(key=lambda y: (y["d"], y["no"] or 0))
        out[r["code"]] = seq
    return out


def counted(run, method):
    """数える着順(method a= 着順なしは頭数・b= 数えない→ None)"""
    if run["fin"]:
        return run["fin"]
    if method == "a":
        v = run["nrv"]
        if v and v["started"]:
            return v["started"]
    return None


# ---------------------------------------------------------------- ① 見直しの組み立て直し
def rebuild(seqs, revs, names, method):
    """→ groups[(i, c)] = [(合計, 降級, code)]・last3[(code, i)] = [(走の idx, 着)]・state[(code,i)] = (c, 次の級)"""
    groups = defaultdict(list)
    last3, state = {}, {}
    short = Counter()
    for code, seq in seqs.items():
        lab_idx = [j for j, x in enumerate(seq) if x["lab"]]
        for i, R in enumerate(revs):
            prevR = revs[i - 1] if i > 0 else R - dt.timedelta(days=75)
            nextR = revs[i + 1] if i + 1 < len(revs) else R + dt.timedelta(days=75)
            before = [j for j in lab_idx if seq[j]["d"] < R]
            if not before:
                continue
            last = seq[before[-1]]
            if last["lab"][0] != "old" or last["d"] <= prevR:
                continue
            c = last["lab"][1]
            after = [j for j in lab_idx if R <= seq[j]["d"] < nextR]
            if not after or seq[after[0]]["lab"][0] != "old":
                continue
            nc = seq[after[0]]["lab"][1]
            state[(code, i)] = (c, nc)
            if c in EXCL:
                continue
            got = []
            for j in reversed(before):
                if seq[j]["lab"] != ("old", c):
                    break
                f = counted(seq[j], method)
                if f is not None:
                    got.append((j, f))
                if len(got) == 3:
                    break
            dem = names.index(nc) > names.index(c)
            if len(got) < 3:
                short[dem] += 1
                continue
            got.reverse()
            last3[(code, i)] = got
            groups[(i, c)].append((sum(f for _, f in got), dem, code))
    return groups, last3, state, short


def match(group):
    k = sum(1 for _, d, _ in group if d)
    if k == 0:
        return 0, 0.0, None
    s = sorted(group, key=lambda x: -x[0])
    t = s[k - 1][0]
    above = [g for g in s if g[0] > t]
    tie = [g for g in s if g[0] == t]
    slots = k - len(above)
    ov = sum(1 for g in above if g[1]) + slots * sum(1 for g in tie if g[1]) / len(tie)
    return k, ov, t


def year_table(groups, revs):
    yr = defaultdict(lambda: {"revs": set(), "k": 0, "ov": 0.0, "t": []})
    for (i, c), g in groups.items():
        k, ov, t = match(g)
        y = yr[revs[i].year]
        y["revs"].add(i)
        y["k"] += k
        y["ov"] += ov
        if t is not None:
            y["t"].append(t)
    return yr


# ---------------------------------------------------------------- 集計の器
class Acc:
    """群 → 指標 → 馬 → [和, 件数]・年 → 指標 → [和, 件数]"""

    def __init__(self):
        self.h = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0.0, 0])))
        self.y = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0.0, 0])))

    def add(self, g, code, year, m):
        for k in ("fin", "top3", "mar", "l3r"):
            if k in m:
                a = self.h[g][k][code]
                a[0] += m[k]
                a[1] += 1
                b = self.y[g][k][year]
                b[0] += m[k]
                b[1] += 1

    def n(self, g):
        return sum(v[1] for v in self.h[g]["fin"].values())

    def boot(self, g, k, ref=None):
        """→ (平均, 下, 上, 差の平均, 差の下, 差の上)。ref があれば g − ref の差も(馬を共通に引き直す)"""
        hs = sorted(set(self.h[g][k]) | (set(self.h[ref][k]) if ref else set()))
        if not hs:
            return None
        sg = np.array([self.h[g][k].get(x, [0, 0])[0] for x in hs])
        cg = np.array([self.h[g][k].get(x, [0, 0])[1] for x in hs], dtype=float)
        if cg.sum() == 0:
            return None
        if ref:
            sr = np.array([self.h[ref][k].get(x, [0, 0])[0] for x in hs])
            cr = np.array([self.h[ref][k].get(x, [0, 0])[1] for x in hs], dtype=float)
        H = len(hs)
        bm, bd = [], []
        for _ in range(BOOT):
            w = np.bincount(RNG.integers(0, H, H), minlength=H)
            a = (w * cg).sum()
            mg = (w * sg).sum() / a if a else np.nan
            bm.append(mg)
            if ref:
                b = (w * cr).sum()
                bd.append(mg - ((w * sr).sum() / b if b else np.nan))
        mean = sg.sum() / cg.sum()
        lo, hi = np.nanpercentile(bm, [2.5, 97.5])
        if ref:
            d = mean - sr.sum() / cr.sum()
            dl, dh = np.nanpercentile(bd, [2.5, 97.5])
            return mean, lo, hi, d, dl, dh
        return mean, lo, hi, None, None, None

    def years(self, g, k):
        ys = {y: v[0] / v[1] for y, v in self.y[g][k].items() if v[1] >= 20}
        return sum(1 for v in ys.values() if v > 0), len(ys)


def pay_maps(pays):
    out = {}
    for p in pays:
        if p.get("race_no") is None:
            continue
        w, pl = {}, {}
        for x in p.get("payouts") or []:
            if not isinstance(x, dict):
                continue
            c, y = str(x.get("c") or "").strip(), num(x.get("y"))
            if y is None:
                continue
            if x.get("t") == "win":
                w[c] = y
            elif x.get("t") == "place":
                pl[c] = y
        if w or pl:
            out[(p["track"], str(p["race_date"])[:10], int(p["race_no"]))] = (w, pl)
    return out


# ---------------------------------------------------------------- 本体
def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    system = next(s for s in cc.load_consts()["SYSTEMS"] if s["id"] == "hyogo")
    tables = cc.hyogo_tables(system)
    names = [c for c, _, _ in tables[0]]
    log("古馬の表: %s" % names)
    runs, races_l, pays, led = fetch(base, key)
    races = {}
    for r in races_l:
        if r.get("race_no") is not None:
            races[(r["track"], str(r["race_date"])[:10], int(r["race_no"]))] = r
    nr, rinfo = build_nr(runs)
    exp = build_exp(nr)
    pm = pay_maps(pays)
    seqs = horse_seqs(led, races, nr)
    revs = cc.hyogo_revisions(led, races, tables)
    revs = [R for R in revs if Y_FROM <= R.year and R <= D_TO]
    log("修正の日 %d 回: %s" % (len(revs), [x.isoformat() for x in revs]))

    # 範囲の確認(年ごと): nar_runs 出走・台帳の兵庫の走・うち単独クラス(古馬)・nar_runs と突き合った割合
    cov = defaultdict(lambda: [0, 0, 0, 0])
    for v in nr.values():
        cov[v["year"]][0] += 1
    for seq in seqs.values():
        for x in seq:
            c = cov[x["d"].year]
            c[1] += 1
            c[2] += bool(x["lab"] and x["lab"][0] == "old")
            c[3] += bool(x["nrv"])

    res = {}
    for m in ("a", "b"):
        g, l3, st, short = rebuild(seqs, revs, names, m)
        yt = year_table(g, revs)
        K = sum(v["k"] for v in yt.values())
        OV = sum(v["ov"] for v in yt.values())
        res[m] = {"groups": g, "last3": l3, "state": st, "short": short, "yt": yt, "rate": OV / K if K else 0.0, "K": K}
        log("着順なし %s: 一致率 %.4f(降級 %d)" % (m, res[m]["rate"], K))
    M = "a" if res["a"]["rate"] >= res["b"]["rate"] else "b"
    R0 = res[M]
    yt = R0["yt"]
    passed = {y for y, v in yt.items() if v["k"] and v["ov"] / v["k"] >= 0.70}
    log("使う年: %s" % sorted(passed))

    # 境目(級×回)
    bnd = {}
    for (i, c), gg in R0["groups"].items():
        k, ov, t = match(gg)
        if t is not None:
            bnd[(i, c)] = t

    def exp_b(i, c):
        prev = [bnd[(j, c)] for j in range(i - 1, -1, -1) if (j, c) in bnd][:3]
        return statistics.median(prev) if len(prev) == 3 else None

    # ② ③ 走ごとの区分
    def make_in3(ex):
        out = {}   # (code, 走の idx) → (i, 位置, 区分)
        for (code, i), got in R0["last3"].items():
            c = R0["state"][(code, i)][0]
            B = exp_b(i, c)
            s = 0
            for p, (j, f) in enumerate(got, 1):
                cat = "見込みなし"
                if B is not None:
                    v = seqs[code][j]["nrv"]
                    mm = metrics(v, ex) if v else None
                    if mm:
                        delta = B * p / 3 - s - mm["efin"]
                        cat = "近い" if abs(delta) <= 3 else ("遠い・安全" if delta > 3 else "深く圏内")
                out[(code, j)] = (i, p, cat)
                s += f
        return out

    acc = Acc()
    in3 = make_in3(exp)
    nC = nD = 0
    for code, seq in seqs.items():
        for j, x in enumerate(seq):
            if not x["lab"] or x["lab"][0] != "old":
                continue
            i = next((t for t, R in enumerate(revs) if R > x["d"]), None)
            if i is None or revs[i].year not in passed:
                continue
            mm = metrics(x["nrv"], exp)
            if not mm:
                continue
            yr = x["d"].year
            if x["lab"][1] in EXCL:
                acc.add("D", code, yr, mm)
                nD += 1
            elif (code, j) in in3 and in3[(code, j)][0] == i:
                _, p, cat = in3[(code, j)]
                acc.add("%s・%d走目" % (cat, p), code, yr, mm)
                acc.add("近3走すべて", code, yr, mm)
            else:
                acc.add("C", code, yr, mm)
                nC += 1

    # ④ 降級直後
    acc4 = Acc()
    roi = defaultdict(lambda: [0, 0.0, 0, 0.0, 0])   # 群 → [件数(払戻あり), 単勝払戻和, 件数, 複勝払戻和, 件数]
    pay_dates = []
    st_all = R0["state"]
    # 対照は「下がった先の級」に R の前から居て R 後も同じ級で走った馬
    dest = Counter(nc for (code, i), (c, nc) in st_all.items()
                   if revs[i].year in passed and names.index(nc) > names.index(c) and c not in EXCL)
    for (code, i), (c, nc) in st_all.items():
        if revs[i].year not in passed:
            continue
        if names.index(nc) > names.index(c) and c not in EXCL:
            grp = "降級"
        elif nc == c and c in dest:
            grp = "前から居る"
        else:
            continue
        seq = seqs[code]
        post = [x for x in seq if x["d"] >= revs[i] and x["nrv"] and x["nrv"]["fin"]][:2]
        for p, x in enumerate(post, 1):
            g = "%s・%d戦目" % (grp, p)
            g = g if grp == "降級" else "%s(級 %s)・%d戦目" % (grp, c, p)
            mm = metrics(x["nrv"], exp)
            if mm:
                acc4.add(g, code, x["d"].year, mm)
                if grp != "降級":
                    acc4.add("%s・%d戦目(先の級すべて)" % (grp, p), code, x["d"].year, mm)
            v = x["nrv"]
            pmap = pm.get(v["race"])
            if pmap and v["num"]:
                w, pl = pmap
                rr = roi["%s・%d戦目" % (grp, p)]
                rr[0] += 1
                rr[1] += w.get(v["num"], 0.0) if v["fin"] == 1 else 0.0
                rr[3] += pl.get(v["num"], 0.0) if v["fin"] <= 3 else 0.0
                pay_dates.append(v["race"][1])

    # ---------------------------------------------------------------- ⑥ 見込みの表のずれ
    use_years = set(passed)
    exp_new = build_exp(nr, years=use_years)

    def bias(ex, vals):
        a = [0.0, 0.0, 0, 0]   # 着順和, 3着内和, 件数, 見込みなし
        for v in vals:
            if v["year"] not in use_years or not v["fin"]:
                continue
            mm = metrics(v, ex)
            if not mm:
                a[3] += 1
                continue
            a[0] += mm["fin"]
            a[1] += mm["top3"]
            a[2] += 1
        return (a[0] / a[2] if a[2] else None, a[1] / a[2] if a[2] else None, a[2], a[3])

    led_vals = list({id(x["nrv"]): x["nrv"] for seq in seqs.values() for x in seq if x["nrv"]}.values())
    b6 = {}
    for nm, ex in (("今の作り方(2014〜 全年・自分の年を除く)", exp), ("作り直し(使う年だけ・自分の年を除く)", exp_new)):
        b6[nm] = (bias(ex, nr.values()), bias(ex, led_vals))
    ok6 = {nm: (v[0][0] is not None and abs(v[0][0]) < 0.03 and abs(100 * v[0][1]) < 0.5) for nm, v in b6.items()}
    nm_old, nm_new = list(b6)
    if ok6[nm_old] and ok6[nm_new]:
        pick = nm_old if abs(b6[nm_old][0][0]) <= abs(b6[nm_new][0][0]) else nm_new
    elif ok6[nm_old]:
        pick = nm_old
    else:
        pick = nm_new
    E = exp if pick == nm_old else exp_new
    log("⑥ 見込み: %s を使う" % pick)

    # ---------------------------------------------------------------- ⑦ 調子をそろえた比べ
    in3E = make_in3(E)

    def fbin(t):
        return "2〜6" if t <= 6 else "7〜10" if t <= 10 else "11〜14" if t <= 14 else "15〜18" if t <= 18 else "19以上"

    def pbin(p):
        return "1〜3" if p <= 3 else "4〜6" if p <= 6 else "7以上"

    recs = []   # (群, code, 年, 層 or None, 指標)
    nCp = nCx = 0
    for code, seq in seqs.items():
        prev_lab, kk = None, 0
        for j, x in enumerate(seq):
            if x["lab"]:
                kk = kk + 1 if x["lab"] == prev_lab else 1
                prev_lab = x["lab"]
            if not x["lab"] or x["lab"][0] != "old" or x["lab"][1] in EXCL:
                continue
            i = next((t for t, R in enumerate(revs) if R > x["d"]), None)
            if i is None or revs[i].year not in passed:
                continue
            mm = metrics(x["nrv"], E)
            if not mm:
                continue
            layer = None
            if j >= 2:
                f1, f2 = counted(seq[j - 1], M), counted(seq[j - 2], M)
                if f1 is not None and f2 is not None:
                    layer = (x["lab"][1], fbin(f1 + f2), pbin(x["nrv"]["pop"]))
            yr = x["d"].year
            if (code, j) in in3E and in3E[(code, j)][0] == i:
                _, p, cat = in3E[(code, j)]
                recs.append(("%s・%d走目" % (cat, p), code, yr, layer, mm))
            elif kk <= 2:
                nCx += 1
            else:
                recs.append(("C'", code, yr, layer, mm))
                nCp += 1

    def compare(T, Rg):
        rT = [r for r in recs if r[0] == T]
        rR = [r for r in recs if r[0] == Rg]
        nR_l = Counter(r[3] for r in rR if r[3] is not None)
        keep = {L for L, n in nR_l.items() if n >= 20}
        drop_none = sum(1 for r in rT if r[3] is None)
        drop_small = sum(1 for r in rT if r[3] is not None and r[3] not in keep)
        tK = [r for r in rT if r[3] in keep]
        rK = [r for r in rR if r[3] in keep]
        layers = sorted(keep)
        li = {L: n for n, L in enumerate(layers)}
        hs = sorted({r[1] for r in tK} | {r[1] for r in rK})
        hix = {h: n for n, h in enumerate(hs)}
        out = {"n": len(tK), "drop_none": drop_none, "drop_small": drop_small, "nR": len(rK), "nRall": len(rR)}
        for k in ("fin", "top3", "mar", "l3r"):
            if not tK or not layers:
                continue
            ST = np.zeros((len(hs), len(layers)))
            NT = np.zeros_like(ST)
            SR = np.zeros_like(ST)
            NR = np.zeros_like(ST)
            for r in tK:
                if k in r[4]:
                    ST[hix[r[1]], li[r[3]]] += r[4][k]
                    NT[hix[r[1]], li[r[3]]] += 1
            for r in rK:
                if k in r[4]:
                    SR[hix[r[1]], li[r[3]]] += r[4][k]
                    NR[hix[r[1]], li[r[3]]] += 1

            def est(st, nt, sr, nrr):
                ok = (nt > 0) & (nrr > 0)
                if not ok.any():
                    return np.nan
                d = st[ok] / nt[ok] - sr[ok] / nrr[ok]
                return float((nt[ok] * d).sum() / nt[ok].sum())

            pt = est(ST.sum(0), NT.sum(0), SR.sum(0), NR.sum(0))
            H = len(hs)
            bs = []
            for _ in range(BOOT):
                w_ = np.bincount(RNG.integers(0, H, H), minlength=H).astype(float)
                bs.append(est(w_ @ ST, w_ @ NT, w_ @ SR, w_ @ NR))
            lo, hi_ = np.nanpercentile(bs, [2.5, 97.5])
            ys = {}
            for y in sorted({r[2] for r in tK}):
                ty = [r for r in tK if r[2] == y and k in r[4]]
                if len(ty) < 20:
                    continue
                a = defaultdict(lambda: [0.0, 0, 0.0, 0])
                for r in ty:
                    a[r[3]][0] += r[4][k]
                    a[r[3]][1] += 1
                for r in rK:
                    if r[2] == y and k in r[4]:
                        a[r[3]][2] += r[4][k]
                        a[r[3]][3] += 1
                num_ = den = 0.0
                for v in a.values():
                    if v[1] and v[3]:
                        num_ += v[1] * (v[0] / v[1] - v[2] / v[3])
                        den += v[1]
                if den:
                    ys[y] = num_ / den
            out[k] = (pt, lo, hi_, int(NT.sum()), sum(1 for v in ys.values() if v > 0), len(ys))
        return out

    comps = [("A", "近い・3走目", "C'"), ("B", "近い・3走目", "近い・1走目"),
             ("C", "深く圏内・3走目", "C'"), ("C", "遠い・安全・3走目", "C'")]
    cres = [(lab, T, Rg, compare(T, Rg)) for lab, T, Rg in comps]
    log("⑦ C' %d 走・級が変わった直後で除いた %d 走" % (nCp, nCx))

    # ---------------------------------------------------------------- 書き出し
    o = io.StringIO()
    w = lambda s="": o.write(s + "\n")  # noqa: E731
    w("# 兵庫(園田・姫路) 格付修正の直前のヤラズの痕跡(研究集計)")
    w()
    w("- 期間 %d-01〜%s・出どころ nar_runs / nar_races / nar_race_payouts / nar_horse_prize(台帳の走)・本番 DB は読むだけ" % (Y_FROM, D_TO))
    w("- 修正の日は class_calc.hyogo_revisions で走歴から検出(%d 回)。扱う級は古馬の表 %s のうち A1・C3 以外" % (len(revs), "・".join(names)))
    w("- 作成 %s(GitHub Actions)" % dt.datetime.now(cc.JST).strftime("%Y-%m-%d %H:%M JST"))
    w()
    w("## 0. 範囲(年ごと)")
    w()
    w("| 年 | nar_runs 出走 | 台帳の兵庫の走 | うち古馬の単独クラス | nar_runs と突き合った |")
    w("|---|---|---|---|---|")
    for y in sorted(cov):
        c = cov[y]
        w("| %d | %d | %d | %d | %d |" % (y, c[0], c[1], c[2], c[3]))
    w()
    w("修正の日: " + "・".join(x.isoformat() for x in revs))
    w()
    w("## ① 見直しの組み立て直し(近3走の着順合計の上位 k 頭 ∩ 実際の降級)")
    w()
    w("| 着順なしの扱い | 一致率 | 降級数(数えた馬) | 近3走が 3 つに満たず数えなかった馬(降級/据え置きなど) |")
    w("|---|---|---|---|")
    for m, lab in (("a", "a 頭数と同じ着"), ("b", "b 数えずに前の走で補う")):
        r = res[m]
        w("| %s | %.1f%% | %d | %d / %d |" % (lab, 100 * r["rate"], r["K"], r["short"][True], r["short"][False]))
    w()
    w("以後は **%s** を使う。" % ("a" if M == "a" else "b"))
    w()
    w("| 年 | 修正回数 | 降級数 | 一致率 | 境目の合計の中央値 | ②以降 |")
    w("|---|---|---|---|---|---|")
    for y in sorted(yt):
        v = yt[y]
        rt = v["ov"] / v["k"] if v["k"] else None
        w("| %d | %d | %d | %s | %s | %s |" % (y, len(v["revs"]), v["k"], "-" if rt is None else "%.1f%%" % (100 * rt),
                                             "-" if not v["t"] else "%g" % statistics.median(v["t"]),
                                             "使う" if y in passed else "外す(70% 未満)" if v["k"] else "外す(降級なし)"))
    w()
    w("## ②③ 走ごとの区分(使う年だけ・実際 − 人気からの見込み・95%% 区間は馬ごとのクラスタ bootstrap %d 回)" % BOOT)
    w()
    w("着順・秒差・上がり順位は + が「見込みより悪い」、3着内は − が「見込みより悪い」。差= その群 − 対照 C。年の向き= + の年/年数(各年 20 走以上)。")
    w()
    labels = {"fin": "着順", "top3": "3着内率", "mar": "勝ち馬との秒差", "l3r": "上がり3F 順位"}
    order = ["近い・3走目", "近い・2走目", "近い・1走目", "遠い・安全・3走目", "遠い・安全・2走目", "遠い・安全・1走目",
             "深く圏内・3走目", "深く圏内・2走目", "深く圏内・1走目", "見込みなし・3走目", "見込みなし・2走目", "見込みなし・1走目",
             "近3走すべて", "C", "D"]
    sumline = {}
    for k in ("fin", "top3", "mar", "l3r"):
        w("### %s" % labels[k])
        w()
        w("| 区分 | 走 | 実際 − 見込み [95%] | 差(− C) [95%] | 年の向き |")
        w("|---|---|---|---|---|")
        for g in order:
            if g not in acc.h or not acc.h[g][k]:
                continue
            b = acc.boot(g, k, ref=None if g == "C" else "C")
            if not b:
                continue
            nn = sum(v[1] for v in acc.h[g][k].values())
            sc = 100 if k == "top3" else 1
            fmt = "%+.1f" if k == "top3" else "%+.3f"
            dif = "-" if b[3] is None else (fmt + " [" + fmt + ", " + fmt + "]") % (sc * b[3], sc * b[4], sc * b[5])
            up, ny = acc.years(g, k)
            w("| %s | %d | %s | %s | %d/%d |" % (g if g not in ("C", "D") else ("対照 C= 近3走に入らない" if g == "C" else "対照 D= A1・C3"),
                                               nn, (fmt + " [" + fmt + ", " + fmt + "]") % (sc * b[0], sc * b[1], sc * b[2]), dif, up, ny))
            if g in ("近い・3走目", "C"):
                sumline[(g, k)] = (b, up, ny)
        w()
    w("(3着内率の単位は pt。走の数は C %d・D %d)" % (nC, nD))
    w()
    w("## ④ 降級直後(使う年だけ)")
    w()
    w("下がった先の級の内訳: " + "・".join("%s %d" % (c, n) for c, n in sorted(dest.items(), key=lambda x: names.index(x[0]))))
    w()
    w("| 群 | 走 | 3着内率の実際 − 見込み [95%] (pt) | 着順の実際 − 見込み |")
    w("|---|---|---|---|")
    keys4 = ["降級・1戦目", "降級・2戦目", "前から居る・1戦目(先の級すべて)", "前から居る・2戦目(先の級すべて)"] + \
        sorted(g for g in acc4.h if g.startswith("前から居る(級"))
    for g in keys4:
        if g not in acc4.h:
            continue
        b = acc4.boot(g, "top3")
        f = acc4.boot(g, "fin")
        nn = sum(v[1] for v in acc4.h[g]["top3"].values())
        w("| %s | %d | %+.1f [%+.1f, %+.1f] | %+.3f [%+.3f, %+.3f] |" % (g, nn, 100 * b[0], 100 * b[1], 100 * b[2], f[0], f[1], f[2]))
        sumline[("④", g)] = b
    w()
    w("前から居る= 降級馬が下がった先の級に R の前から居て、R 後も同じ級で走った馬(C3 も含む)。(級 X) は級ごとの内訳。")
    w()
    if pay_dates:
        w("回収率(nar_race_payouts がある走だけ・%s〜%s)" % (min(pay_dates), max(pay_dates)))
    else:
        w("回収率: 払戻のある走なし")
    w()
    w("| 群 | 払戻のある走 | 単勝回収率 | 複勝回収率 |")
    w("|---|---|---|---|")
    for g in ("降級・1戦目", "降級・2戦目", "前から居る・1戦目", "前から居る・2戦目"):
        rr = roi.get(g)
        if rr and rr[0]:
            w("| %s | %d | %.1f%% | %.1f%% |" % (g, rr[0], rr[1] / rr[0], rr[3] / rr[0]))
    w()
    w("## ⑤ 結論の材料")
    w()
    for k in ("fin", "top3"):
        a = sumline.get(("近い・3走目", k))
        if a:
            b, up, ny = a
            zero = not (b[4] <= 0 <= b[5])
            worse = (b[3] > 0) if k != "top3" else (b[3] < 0)
            w("- %s: 近い・3走目 − C = %+.3f [%+.3f, %+.3f]・区間が 0 に%s・向き %s・年の向き(+ の年) %d/%d"
              % (labels[k], b[3], b[4], b[5], "かからない" if zero else "かかる", "見込みより悪い" if worse else "悪くない", up, ny))
    w()
    w("## ⑥ 見込みの表のずれ(使う年 %s の兵庫の走・実際 − 見込みの平均)" % "・".join(str(y) for y in sorted(use_years)))
    w()
    w("| 見込みの作り方 | 範囲 | 走 | 着順 | 3着内 (pt) | 見込みなし | 全走が 着順<0.03 かつ 3着内<0.5pt |")
    w("|---|---|---|---|---|---|---|")
    for nm, (ba, bl) in b6.items():
        for rng_, bb in (("全走", ba), ("台帳に載る馬だけ", bl)):
            w("| %s | %s | %d | %s | %s | %d | %s |" % (nm, rng_, bb[2], "-" if bb[0] is None else "%+.4f" % bb[0],
                                                   "-" if bb[1] is None else "%+.2f" % (100 * bb[1]), bb[3],
                                                   ("満たす" if ok6[nm] else "満たさない") if rng_ == "全走" else ""))
    w()
    w("以後(⑦)は **%s** を使う%s。" % (pick, "" if (ok6[nm_old] or ok6[nm_new]) else "(どちらも基準を満たさなかったので作り直した方)"))
    w("全走と台帳に載る馬だけの違い(%s の見込み・台帳に載る − 全走): 着順 %+.4f・3着内 %+.2f pt。" % (
        pick, b6[pick][1][0] - b6[pick][0][0], 100 * (b6[pick][1][1] - b6[pick][0][1])))
    w()
    w("## ⑦ 調子をそろえた比べ(使う年だけ・%s の見込み)" % pick)
    w()
    w("- C'= 対照 C(近3走に入らない・A1・C3 以外)から、級が変わった直後の 1・2 戦目を除いた走(%d 走・除いた走 %d)。台帳の最初の走も「変わった直後」に数える。" % (nCp, nCx))
    w("- 層= 級 × 前 2 走(兵庫・級を問わない・着順なしは①の扱い %s)の着順合計 2〜6・7〜10・11〜14・15〜18・19以上 × 人気 1〜3・4〜6・7以上。" % M)
    w("- 差= 層ごとの(比べる群 − 対照)の「実際 − 見込み」の差を、比べる群の走の数で重み付けした平均。95%% 区間は馬ごとのクラスタ bootstrap %d 回。年の向き= + の年/年数(その年の比べる群が 20 走以上)。" % BOOT)
    w("- 対照の走が 20 未満の層は捨てる。着順・秒差・上がり順位は + が悪い、3着内は − が悪い。")
    w()
    w("| 比べ | 比べる群 − 対照 | 指標 | 比べる群の走 | 差 [95%] | 年の向き |")
    w("|---|---|---|---|---|---|")
    for lab, T, Rg, r in cres:
        for k in ("fin", "top3", "mar", "l3r"):
            if k not in r:
                continue
            pt, lo, hi_, nn, up, ny = r[k]
            sc = 100 if k == "top3" else 1
            fmt = "%+.1f" if k == "top3" else "%+.3f"
            w("| %s | %s − %s | %s | %d | %s | %d/%d |" % (lab, T, Rg, labels[k] + (" (pt)" if k == "top3" else ""), nn,
                                                       (fmt + " [" + fmt + ", " + fmt + "]") % (sc * pt, sc * lo, sc * hi_), up, ny))
    w()
    w("| 比べ | 比べる群 − 対照 | 使った走 | 捨てた走(前 2 走が取れない) | 捨てた走(対照 20 走未満の層) | 対照の走(使った/全部) |")
    w("|---|---|---|---|---|---|")
    for lab, T, Rg, r in cres:
        w("| %s | %s − %s | %d | %d | %d | %d / %d |" % (lab, T, Rg, r["n"], r["drop_none"], r["drop_small"], r["nR"], r["nRall"]))
    w()
    w("定義は cloud/yarazu_hyogo.py の頭の説明。馬名・騎手・調教師・馬主は出さない。")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(o.getvalue())
    log("書いた %s" % OUT)


if __name__ == "__main__":
    main()
