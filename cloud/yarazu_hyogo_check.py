# -*- coding: utf-8 -*-
"""研究用・1 回きり: cloud/yarazu_hyogo.py(b90f514)の主張 A・B を別の実装で照合し、反証を 4 つ試す。
便 .github/workflows/yarazu-hyogo-check.yml(workflow_dispatch のみ)から走らせ、docs/yarazu-hyogo/check.md を書く。
⛔本番 DB は REST の単純 select だけ(場×年ごと・order は一意の列の組)。書き込みなし。馬名などは結果に出さない。
⛔前任の台本・class_calc.py は import しない。級の読み取り・修正日の検出・集計は全部ここで書く。

定義(前任の説明に合わせ、作りは独立):
- 級= 台帳(nar_horse_prize.runs)の cls を全角にそろえ ^[ＡＢＣ][１２３]([一二三四五])?$ を古馬の級とする。
  重賞(race_kind)・cls に 重賞/交流/認定/初出 は級なし。レース名に 2歳/3歳 があり「以上」が無ければ若馬の表(別ラベル)。
- 修正日= 古馬の級で上→下へ動いた続いた 2 走の間 (a, b](45 日以内)を数え、重なりが最大の日(最大が並べば早い日)を取り、
  その日を含む区間を除いて繰り返す(重なり 8 未満で止める・30 日以内の重複は捨てる)。
- 近3走・境目 B・近い/遠い・安全/深く圏内・見込み(人気×頭数・使う年・自分の年を除く)・C'・層・差・bootstrap は前任の説明どおり。
  ただし C' は「どの修正の近3走にも入らない走」(前任は辞書の上書きで、前の修正の近3走が C' に入ることがある)。
反証:
 1 C' の偏り= 間隔・60 日あたりの出走数・次走までの日数・次の級が上がる割合・時期を並べ、間隔の区分を層に足す。同じ馬の中の差。
 2 発走時点の定義= 前回の修正+直近 3 回の間隔の中央値を見込み日とし、見込み日まで 21 日以内(過ぎた分も含む)・
   この走を 3 走目とみなした近い(前 2 走は同じ級の続いた在籍)を的、見込み日まで 22 日以上の走(級が変わって 3 走目以降)を対照。
 3 偽の修正日= 全修正日を −30 日・+30 日にずらし、近3走・位置・C' を偽の日で作る(境目 B は本当の回のものを使う)。
 4 対象外の級= A1・C3 に同じ近いを当てる。境目はその回の A2〜C2 の降級割合(k/N)を A1・C3 の頭数に掛けた順位の合計。
"""
import bisect
import datetime as dt
import io
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

import numpy as np

TRACKS = ("園田", "姫路")
CLS = ["Ａ１", "Ａ２", "Ｂ１", "Ｂ２", "Ｃ１", "Ｃ２", "Ｃ３"]
EXCL = ("Ａ１", "Ｃ３")
Y_FROM, D_TO = 2014, dt.date(2026, 9, 30)
MIN_CELL = 30
BOOT = 1000
RNG = np.random.default_rng(20261017)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "yarazu-hyogo", "check.md")
PAGE = 1000


def log(s):
    print(s, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- 取得
def get(base, key, path):
    for i in range(4):
        r = urllib.request.Request(base + path, headers={"apikey": key, "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(r, timeout=180) as x:
                return json.loads(x.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code < 500 or i == 3:
                raise
            log("  再試行 %s" % str(e)[:80])
            time.sleep(5 * (i + 1))


def pages(base, key, path):
    """⛔path の order= は一意の列の組。"""
    out, off = [], 0
    while True:
        c = get(base, key, "%s&limit=%d&offset=%d" % (path, PAGE, off))
        out.extend(c)
        if len(c) < PAGE:
            return out
        off += PAGE


def fetch(base, key):
    q = urllib.parse.quote
    runs, races = [], []
    for tr in TRACKS:
        for y in range(Y_FROM, D_TO.year + 1):
            f = "track=eq.%s&race_date=gte.%d-01-01&race_date=lte.%s" % (q(tr), y, min(dt.date(y, 12, 31), D_TO))
            runs += pages(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,"
                          "finish,popularity,time_sec,last3f&%s&order=race_date.asc,race_no.asc,runner_number.asc" % f)
            races += pages(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,race_name,race_kind&%s"
                           "&order=race_date.asc,race_no.asc" % f)
            log("%s %d 累計 走 %d・レース %d" % (tr, y, len(runs), len(races)))
    names = sorted({r["horse_name"] for r in runs if r.get("horse_name")})
    codes = set()
    for i in range(0, len(names), 80):
        inq = ",".join('"' + n.replace('"', '') + '"' for n in names[i:i + 80])
        for c in pages(base, key, "/rest/v1/nar_horse_codes?select=code,horse_name&horse_name=in.(%s)&order=code.asc,horse_name.asc"
                       % q(inq)):
            codes.add(c["code"])
    cs = sorted(codes)
    led = []
    for i in range(0, len(cs), 100):
        led += pages(base, key, "/rest/v1/nar_horse_prize?select=code,horse_name,runs&code=in.(%s)&order=code.asc"
                     % ",".join(q(str(c)) for c in cs[i:i + 100]))
    log("馬名 %d・コード %d・台帳 %d" % (len(names), len(cs), len(led)))
    return runs, races, led


def pint(v):
    try:
        x = int(str(v).strip())
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def pflt(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pdate(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 級の読み取り(独自)
Z = str.maketrans("0123456789ABCabc", "０１２３４５６７８９ＡＢＣＡＢＣ")
OLD_RE = re.compile(r"^([ＡＢＣ][１２３])([一二三四五])?$")
YOUNG_RE = re.compile(r"[23２３]歳")
UNMATCHED = Counter()


def label(x, race):
    cls = str(x.get("cls") or "").strip().translate(Z)
    rn = str((race or {}).get("race_name") or x.get("name") or "")
    kind = str((race or {}).get("race_kind") or "")
    if kind == "重賞" or any(w in cls for w in ("重賞", "交流", "認定", "初出")):
        return None
    young = bool(YOUNG_RE.search(rn)) and "以上" not in rn
    m = OLD_RE.match(cls)
    if m and m.group(1) in CLS:
        return ("y", m.group(1)) if young else ("old", m.group(1))
    if young and cls[:1] in ("Ａ", "Ｂ", "Ｃ"):
        return ("y", cls)
    UNMATCHED[cls] += 1
    return None


# ---------------------------------------------------------------- 下ごしらえ
def build_nr(runs):
    by = defaultdict(list)
    for r in runs:
        if r.get("race_no") is None:
            continue
        by[(r["track"], str(r["race_date"])[:10], int(r["race_no"]))].append(r)
    nr = {}
    for k, rs in by.items():
        fins = [r for r in rs if pint(r.get("finish"))]
        n = len(fins)
        ts = [pflt(r.get("time_sec")) for r in fins if pflt(r.get("time_sec"))]
        wt = min(ts) if ts else None
        l3s = sorted(pflt(r.get("last3f")) for r in fins if pflt(r.get("last3f")))
        for r in rs:
            f, t, l = pint(r.get("finish")), pflt(r.get("time_sec")), pflt(r.get("last3f"))
            nr[k + (r.get("horse_name"),)] = {
                "fin": f, "pop": pint(r.get("popularity")), "n": n, "year": int(k[1][:4]),
                "mar": (t - wt) if (f and t and wt) else None,
                "l3r": (bisect.bisect_left(l3s, l) + 1) if (f and l and l3s) else None}
    return nr


def build_exp(nr, years):
    cell = defaultdict(lambda: np.zeros(7))
    for v in nr.values():
        if v["fin"] and v["pop"] and v["n"] and v["year"] in years:
            c = cell[(v["pop"], v["n"], v["year"])]
            c += [1, v["fin"], v["fin"] <= 3, v["mar"] or 0.0, v["mar"] is not None, v["l3r"] or 0, v["l3r"] is not None]
    tot = defaultdict(lambda: np.zeros(7))
    for (p, n, y), c in cell.items():
        tot[(p, n)] += c
    cache = {}

    def exp(p, n, y):
        kk = (p, n, y)
        if kk in cache:
            return cache[kk]
        t = tot.get((p, n))
        out = None
        if t is not None:
            d = t - cell.get((p, n, y), np.zeros(7))
            if d[0] >= MIN_CELL:
                out = {"fin": d[1] / d[0], "top3": d[2] / d[0],
                       "mar": d[3] / d[4] if d[4] >= MIN_CELL else None,
                       "l3r": d[5] / d[6] if d[6] >= MIN_CELL else None}
        cache[kk] = out
        return out
    return exp


def metrics(v, exp):
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


def build_seqs(led, races, nr):
    seqs, alld = {}, {}
    for r in led:
        seq, ds = [], set()
        for x in r.get("runs") or []:
            d = pdate(x.get("d"))
            if not d or d > D_TO:
                continue
            ds.add(d)
            if x.get("tr") not in TRACKS:
                continue
            no = pint(x.get("no"))
            k = (x.get("tr"), d.isoformat(), no)
            fin = x.get("fin") if isinstance(x.get("fin"), int) and x.get("fin") > 0 else None
            seq.append({"d": d, "no": no or 0, "lab": label(x, races.get(k)), "fin": fin,
                        "nrv": nr.get(k + (r.get("horse_name"),))})
        seq.sort(key=lambda y: (y["d"], y["no"]))
        seqs[r["code"]] = seq
        alld[r["code"]] = sorted(ds)
    return seqs, alld


# ---------------------------------------------------------------- 修正日の検出(独自)
def detect_revs(seqs):
    pairs = []
    for seq in seqs.values():
        prev = None
        for x in seq:
            if not x["lab"]:
                continue
            if prev and prev["lab"][0] == "old" and x["lab"][0] == "old" \
                    and CLS.index(x["lab"][1]) > CLS.index(prev["lab"][1]) and 0 < (x["d"] - prev["d"]).days <= 45:
                pairs.append((prev["d"], x["d"]))
            prev = x
    rem, revs = list(pairs), []
    while rem:
        cov = Counter()
        for a, b in rem:
            for i in range(1, (b - a).days + 1):
                cov[a + dt.timedelta(days=i)] += 1
        best = max(cov.values())
        if best < 8:
            break
        day = min(d for d, c in cov.items() if c == best)
        rem = [p for p in rem if not (p[0] < day <= p[1])]
        if all(abs((day - r).days) >= 30 for r in revs):
            revs.append(day)
    return sorted(revs), len(pairs)


# ---------------------------------------------------------------- ① 近3走
def rebuild(seqs, revs):
    """→ groups[(i,c)]=[(合計, 降級, code)]・last3[(code,i)]=[(j,f)]・cls_at[(code,i)]=c"""
    groups, last3, cls_at = defaultdict(list), {}, {}
    for code, seq in seqs.items():
        li = [j for j, x in enumerate(seq) if x["lab"]]
        ld = [seq[j]["d"] for j in li]
        for i, R in enumerate(revs):
            pR = revs[i - 1] if i > 0 else R - dt.timedelta(days=75)
            nR = revs[i + 1] if i + 1 < len(revs) else R + dt.timedelta(days=75)
            nb = bisect.bisect_left(ld, R)
            if nb == 0:
                continue
            last = seq[li[nb - 1]]
            if last["lab"][0] != "old" or last["d"] <= pR:
                continue
            if nb >= len(li) or ld[nb] >= nR or seq[li[nb]]["lab"][0] != "old":
                continue
            c, nc = last["lab"][1], seq[li[nb]]["lab"][1]
            got = []
            for t in range(nb - 1, -1, -1):
                x = seq[li[t]]
                if x["lab"] != ("old", c):
                    break
                if x["fin"]:
                    got.append((li[t], x["fin"]))
                if len(got) == 3:
                    break
            if len(got) < 3:
                continue
            got.reverse()
            last3[(code, i)] = got
            cls_at[(code, i)] = c
            groups[(i, c)].append((sum(f for _, f in got), CLS.index(nc) > CLS.index(c), code))
    return groups, last3, cls_at


def match(g):
    k = sum(1 for _, d, _ in g if d)
    if k == 0:
        return 0, 0.0, None
    s = sorted(g, key=lambda x: -x[0])
    t = s[k - 1][0]
    above = [x for x in s if x[0] > t]
    tie = [x for x in s if x[0] == t]
    ov = sum(1 for x in above if x[1]) + (k - len(above)) * sum(1 for x in tie if x[1]) / len(tie)
    return k, ov, t


def boundaries(groups, nrev):
    t = {}
    frac = {}
    for i in range(nrev):
        K = N = 0
        for c in CLS:
            if c in EXCL or (i, c) not in groups:
                continue
            k, _, tt = match(groups[(i, c)])
            K += k
            N += len(groups[(i, c)])
            if tt is not None:
                t[(i, c)] = tt
        frac[i] = K / N if N else 0.0
    for i in range(nrev):          # A1・C3 の見かけの境目(反証 4)
        for c in EXCL:
            g = groups.get((i, c))
            if not g:
                continue
            kk = int(round(frac[i] * len(g)))
            if kk >= 1:
                t[(i, c)] = sorted((x[0] for x in g), reverse=True)[kk - 1]
    return t


def bfun(t):
    def B(i, c):
        prev = [t[(j, c)] for j in range(i - 1, -1, -1) if (j, c) in t][:3]
        return statistics.median(prev) if len(prev) == 3 else None
    return B


def cat_of(B, p, s, efin):
    dl = B * p / 3 - s - efin
    return "近い" if abs(dl) <= 3 else ("遠い・安全" if dl > 3 else "深く圏内")


def make_in3(seqs, last3, cls_at, B, E):
    out = defaultdict(list)    # (code, j) → [(i, p, 区分)]
    for (code, i), got in last3.items():
        b = B(i, cls_at[(code, i)])
        s = 0
        for p, (j, f) in enumerate(got, 1):
            mm = metrics(seqs[code][j]["nrv"], E)
            cat = cat_of(b, p, s, mm["efin"]) if (b is not None and mm) else "見込みなし"
            out[(code, j)].append((i, p, cat))
            s += f
    return out


def fbin(t):
    return "2〜6" if t <= 6 else "7〜10" if t <= 10 else "11〜14" if t <= 14 else "15〜18" if t <= 18 else "19以上"


def pbin(p):
    return "1〜3" if p <= 3 else "4〜6" if p <= 6 else "7以上"


def gbin(g):
    if g is None:
        return None
    return "〜14" if g <= 14 else "15〜28" if g <= 28 else "29〜56" if g <= 56 else "57〜"


def records(seqs, alld, revs, in3, E, passed, classes):
    """走ごとの記録。grp= 区分・位置 / C' / X(級が変わった直後)。"""
    out = []
    for code, seq in seqs.items():
        prev_lab, kk = None, 0
        ds = alld[code]
        li = [j for j, x in enumerate(seq) if x["lab"]]
        nxt_lab = {}
        for a, b in zip(li, li[1:]):
            nxt_lab[a] = seq[b]["lab"]
        for j, x in enumerate(seq):
            if x["lab"]:
                kk = kk + 1 if x["lab"] == prev_lab else 1
                prev_lab = x["lab"]
            if not x["lab"] or x["lab"][0] != "old" or x["lab"][1] not in classes:
                continue
            i = bisect.bisect_right(revs, x["d"])
            if i >= len(revs) or revs[i].year not in passed:
                continue
            mm = metrics(x["nrv"], E)
            if not mm:
                continue
            c = x["lab"][1]
            layer = None
            if j >= 2 and seq[j - 1]["fin"] and seq[j - 2]["fin"]:
                layer = (c, fbin(seq[j - 1]["fin"] + seq[j - 2]["fin"]), pbin(x["nrv"]["pop"]))
            ent = [e for e in in3.get((code, j), []) if e[0] == i]
            if ent:
                grp = "%s・%d走目" % (ent[0][2], ent[0][1])
            elif in3.get((code, j)):
                grp = "他の回の近3走"
            elif kk <= 2:
                grp = "X"
            else:
                grp = "C'"
            k0 = bisect.bisect_left(ds, x["d"])
            gap = (x["d"] - ds[k0 - 1]).days if k0 > 0 else None
            k1 = bisect.bisect_right(ds, x["d"])
            nxt = (ds[k1] - x["d"]).days if k1 < len(ds) else None
            pR = revs[i - 1] if i > 0 else revs[i] - dt.timedelta(days=75)
            L = (revs[i] - pR).days
            cnt = sum(1 for y in seq if pR <= y["d"] < revs[i])
            nl = nxt_lab.get(j)
            promo = bool(nl and nl[0] == "old" and CLS.index(nl[1]) < CLS.index(c))
            out.append({"grp": grp, "code": code, "year": x["d"].year, "d": x["d"], "i": i, "c": c, "kk": kk, "j": j,
                        "layer": layer, "gap": gap, "gb": gbin(gap), "nxt": nxt, "r60": cnt * 60.0 / L if L else None,
                        "promo": promo, "m": mm})
    return out


# ---------------------------------------------------------------- 比べ
def compare(tK, rK, lay, keys=("fin", "top3", "mar", "l3r")):
    tK = [r for r in tK if lay(r) is not None]
    rK = [r for r in rK if lay(r) is not None]
    nl = Counter(lay(r) for r in rK)
    keep = {L for L, n in nl.items() if n >= 20}
    tK2 = [r for r in tK if lay(r) in keep]
    rK2 = [r for r in rK if lay(r) in keep]
    out = {"n": len(tK2), "nR": len(rK2), "drop": len(tK) - len(tK2)}
    if not tK2:
        return out
    layers = sorted(keep)
    lix = {L: n for n, L in enumerate(layers)}
    hs = sorted({r["code"] for r in tK2} | {r["code"] for r in rK2})
    hix = {h: n for n, h in enumerate(hs)}
    H = len(hs)
    W = np.stack([np.bincount(RNG.integers(0, H, H), minlength=H).astype(float) for _ in range(BOOT)])
    for k in keys:
        ST = np.zeros((H, len(layers)))
        NT, SR, NR = np.zeros_like(ST), np.zeros_like(ST), np.zeros_like(ST)
        for r in tK2:
            if k in r["m"]:
                ST[hix[r["code"]], lix[lay(r)]] += r["m"][k]
                NT[hix[r["code"]], lix[lay(r)]] += 1
        for r in rK2:
            if k in r["m"]:
                SR[hix[r["code"]], lix[lay(r)]] += r["m"][k]
                NR[hix[r["code"]], lix[lay(r)]] += 1

        def est(st, nt, sr, nrr):
            ok = (nt > 0) & (nrr > 0)
            if not np.any(ok):
                return np.nan
            return float((nt[ok] * (st[ok] / nt[ok] - sr[ok] / nrr[ok])).sum() / nt[ok].sum())

        pt = est(ST.sum(0), NT.sum(0), SR.sum(0), NR.sum(0))
        a, b, c_, d_ = W @ ST, W @ NT, W @ SR, W @ NR
        with np.errstate(invalid="ignore", divide="ignore"):
            ok = (b > 0) & (d_ > 0)
            dd = np.where(ok, a / np.where(b > 0, b, 1) - c_ / np.where(d_ > 0, d_, 1), 0.0)
            bs = (np.where(ok, b, 0) * dd).sum(1) / np.where(ok, b, 0).sum(1)
        lo, hi = np.nanpercentile(bs, [2.5, 97.5])
        yrs = {}
        for y in sorted({r["year"] for r in tK2}):
            ty = [r for r in tK2 if r["year"] == y and k in r["m"]]
            if len(ty) < 20:
                continue
            acc = defaultdict(lambda: [0.0, 0, 0.0, 0])
            for r in ty:
                acc[lay(r)][0] += r["m"][k]
                acc[lay(r)][1] += 1
            for r in rK2:
                if r["year"] == y and k in r["m"]:
                    acc[lay(r)][2] += r["m"][k]
                    acc[lay(r)][3] += 1
            nu = de = 0.0
            for v in acc.values():
                if v[1] and v[3]:
                    nu += v[1] * (v[0] / v[1] - v[2] / v[3])
                    de += v[1]
            if de:
                yrs[y] = nu / de
        out[k] = (pt, lo, hi, sum(1 for v in yrs.values() if v > 0), len(yrs))
    return out


def within_horse(tK, rK, keys=("fin", "top3")):
    """同じ馬の中: (その馬の的の平均 − その馬の対照の平均) を的の走の数で重み付け。"""
    out = {}
    for k in keys:
        tt, rr = defaultdict(list), defaultdict(list)
        for r in tK:
            if k in r["m"]:
                tt[r["code"]].append(r["m"][k])
        for r in rK:
            if k in r["m"]:
                rr[r["code"]].append(r["m"][k])
        hs = sorted(set(tt) & set(rr))
        if not hs:
            continue
        n = np.array([len(tt[h]) for h in hs], dtype=float)
        dv = np.array([np.mean(tt[h]) - np.mean(rr[h]) for h in hs])
        pt = float((n * dv).sum() / n.sum())
        H = len(hs)
        bs = []
        for _ in range(BOOT):
            w = np.bincount(RNG.integers(0, H, H), minlength=H) * n
            bs.append((w * dv).sum() / w.sum())
        lo, hi = np.percentile(bs, [2.5, 97.5])
        out[k] = (pt, lo, hi, H, int(n.sum()), sum(len(rr[h]) for h in hs))
    return out


def fmt(res, k):
    if k not in res:
        return "-"
    pt, lo, hi = res[k][:3]
    if k == "top3":
        return "%+.1f [%+.1f, %+.1f]" % (100 * pt, 100 * lo, 100 * hi)
    return "%+.3f [%+.3f, %+.3f]" % (pt, lo, hi)


def yrs(res, k):
    return "%d/%d" % res[k][3:5] if k in res else "-"


def q(vals, ps=(25, 50, 75)):
    v = [x for x in vals if x is not None]
    if not v:
        return "-"
    return "・".join("%.0f" % np.percentile(v, p) for p in ps) + "(平均 %.1f)" % np.mean(v)


# ---------------------------------------------------------------- 本体
def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    runs, races_l, led = fetch(base, key)
    races = {(r["track"], str(r["race_date"])[:10], int(r["race_no"])): r for r in races_l if r.get("race_no") is not None}
    nr = build_nr(runs)
    seqs, alld = build_seqs(led, races, nr)
    revs, npairs = detect_revs(seqs)
    revs = [R for R in revs if R.year >= Y_FROM and R <= D_TO]
    log("修正の日 %d: %s" % (len(revs), [r.isoformat() for r in revs]))
    PRED = ["2021-07-03", "2022-01-21", "2022-07-07", "2022-09-10", "2022-11-11", "2023-01-19", "2023-03-09",
            "2023-05-05", "2023-07-08", "2023-09-23", "2023-11-24", "2024-01-19", "2024-03-08", "2024-05-03",
            "2024-07-06", "2024-09-07", "2024-11-15", "2025-01-24", "2025-03-14", "2025-05-09", "2025-07-05",
            "2025-09-06", "2025-11-07", "2026-01-09", "2026-03-06", "2026-05-08", "2026-07-04", "2026-09-05"]
    mine = {r.isoformat() for r in revs}
    same = len(mine & set(PRED))

    groups, last3, cls_at = rebuild(seqs, revs)
    yt = defaultdict(lambda: [0, 0.0])
    for (i, c), g in groups.items():
        if c in EXCL:
            continue
        k, ov, _ = match(g)
        yt[revs[i].year][0] += k
        yt[revs[i].year][1] += ov
    K = sum(v[0] for v in yt.values())
    OV = sum(v[1] for v in yt.values())
    passed = {y for y, v in yt.items() if v[0] and v[1] / v[0] >= 0.70}
    log("一致率 %.4f・降級 %d・使う年 %s" % (OV / K if K else 0, K, sorted(passed)))
    E = build_exp(nr, passed)
    T = boundaries(groups, len(revs))
    B = bfun(T)
    in3 = make_in3(seqs, last3, cls_at, B, E)
    main_cls = [c for c in CLS if c not in EXCL]
    recs = records(seqs, alld, revs, in3, E, passed, main_cls)
    G = defaultdict(list)
    for r in recs:
        G[r["grp"]].append(r)
    base_lay = lambda r: r["layer"]  # noqa: E731
    gap_lay = lambda r: (r["layer"] + (r["gb"],)) if (r["layer"] and r["gb"]) else None  # noqa: E731
    tgt, Cp = G["近い・3走目"], G["C'"]
    A = compare(tgt, Cp, base_lay)
    Bc = compare(tgt, G["近い・1走目"], base_lay)
    Cd = compare(G["深く圏内・3走目"], Cp, base_lay, ("fin", "top3"))
    Cs = compare(G["遠い・安全・3走目"], Cp, base_lay, ("fin", "top3"))
    log("A 3着内 %s" % fmt(A, "top3"))

    # 反証 1
    A_gap = compare(tgt, Cp, gap_lay, ("fin", "top3"))
    i_min = min((r["i"] for r in tgt), default=0)
    Cp_same = [r for r in Cp if r["i"] >= i_min]
    A_per = compare(tgt, Cp_same, base_lay, ("fin", "top3"))
    A_nopromo = compare(tgt, [r for r in Cp if not r["promo"]], base_lay, ("fin", "top3"))
    A_both = compare(tgt, [r for r in Cp_same if not r["promo"]], gap_lay, ("fin", "top3"))
    WH = within_horse([r for r in tgt if r["layer"]], [r for r in Cp if r["layer"]])

    # 反証 2 発走時点の定義
    T2, C2 = [], []
    n_actual3 = 0
    for r in recs:
        ip = bisect.bisect_right(revs, r["d"]) - 1
        if ip < 3 or r["kk"] < 3:
            continue
        iv = [(revs[ip - t] - revs[ip - t - 1]).days for t in range(3)]
        Rh = revs[ip] + dt.timedelta(days=statistics.median(iv))
        dto = (Rh - r["d"]).days
        if dto > 21:
            C2.append(r)
            continue
        seq = seqs[r["code"]]
        lab = seq[r["j"]]["lab"]
        s, got = 0, 0
        for t in range(r["j"] - 1, -1, -1):
            y = seq[t]
            if not y["lab"]:
                continue
            if y["lab"] != lab:
                break
            if y["fin"]:
                s += y["fin"]
                got += 1
                if got == 2:
                    break
        b = B(ip + 1, r["c"])
        if got < 2 or b is None:
            continue
        if cat_of(b, 3, s, r["m"]["efin"]) == "近い":
            T2.append(r)
            n_actual3 += r["grp"].endswith("・3走目")
    A2 = compare(T2, C2, base_lay)
    A2g = compare(T2, C2, gap_lay, ("fin", "top3"))

    # 反証 3 偽の日
    fake = {}
    for sh in (-30, 30):
        fr = [R + dt.timedelta(days=sh) for R in revs]
        g_f, l3_f, ca_f = rebuild(seqs, fr)
        in3_f = make_in3(seqs, l3_f, ca_f, B, E)    # B は本当の回の境目(回の番号は同じ)
        rf = records(seqs, alld, fr, in3_f, E, passed, main_cls)
        Gf = defaultdict(list)
        for r in rf:
            Gf[r["grp"]].append(r)
        fake[sh] = (compare(Gf["近い・3走目"], Gf["C'"], base_lay, ("fin", "top3")), len(Gf["C'"]))

    # 反証 4 A1・C3
    r4 = records(seqs, alld, revs, in3, E, passed, list(EXCL))
    G4 = defaultdict(list)
    for r in r4:
        G4[r["grp"]].append(r)
    A4 = {}
    for c in EXCL:
        A4[c] = compare([r for r in G4["近い・3走目"] if r["c"] == c], [r for r in G4["C'"] if r["c"] == c],
                        base_lay, ("fin", "top3"))
    A4["両方"] = compare(G4["近い・3走目"], G4["C'"], base_lay, ("fin", "top3"))

    # ---------------------------------------------------------------- 書き出し
    o = io.StringIO()
    w = lambda s="": o.write(s + "\n")  # noqa: E731
    w("# 兵庫 降級前のヤラズ 研究集計の照合と反証(別実装)")
    w()
    w("- 照合先 cloud/yarazu_hyogo.py(b90f514)・docs/yarazu-hyogo/result2.md。台本 cloud/yarazu_hyogo_check.py(前任・class_calc は使わない)")
    w("- 出どころ nar_runs / nar_races / nar_horse_codes / nar_horse_prize(読むだけ)・%d-01〜%s" % (Y_FROM, D_TO))
    w("- 作成 %s UTC(GitHub Actions)・馬名・騎手・調教師・馬主は出さない" % dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    w()
    w("## 1. 再現")
    w()
    w("| 項目 | この実装 | 前任 |")
    w("|---|---|---|")
    w("| 修正日の数(降級の 2 走の組 %d) | %d(前任と同じ日 %d) | 28 |" % (npairs, len(revs), same))
    w("| 一致率(上位 k 頭 ∩ 降級・A2〜C2) | %.1f%%(降級 %d) | 91.1%%(1472) |" % (100 * OV / K if K else 0, K))
    w("| 使う年 | %s | 2021〜2026 |" % "・".join(map(str, sorted(passed))))
    for nm, pv in (("近い・3走目", "989(⑦)"), ("近い・2走目", "-"), ("近い・1走目", "-"), ("遠い・安全・3走目", "1542(⑦)"),
                   ("深く圏内・3走目", "754(⑦)"), ("見込みなし・3走目", "-"), ("C'", "4264"), ("X", "7429"), ("他の回の近3走", "(C' に入る)")):
        w("| 走の数 %s | %d | %s |" % (nm, len(G[nm]), pv))
    w()
    w("修正日(この実装): " + "・".join(r.isoformat() for r in revs))
    w("前任に無い日: %s / この実装に無い前任の日: %s" % ("・".join(sorted(mine - set(PRED))) or "なし",
                                                "・".join(sorted(set(PRED) - mine)) or "なし"))
    w()
    w("| 比べ | 指標 | 走(使った/対照) | 差 [95%] | 年の向き | 前任 |")
    w("|---|---|---|---|---|---|")
    prevA = {"fin": "+0.507 [+0.304, +0.700]", "top3": "-6.0 [-8.9, -3.2]", "mar": "+0.191 [+0.099, +0.285]",
             "l3r": "+0.331 [+0.102, +0.571]"}
    prevB = {"fin": "+0.115 [-0.111, +0.316]", "top3": "+0.2 [-2.8, +3.1]", "mar": "+0.116 [+0.024, +0.206]",
             "l3r": "+0.063 [-0.194, +0.313]"}
    KN = {"fin": "着順", "top3": "3着内 (pt)", "mar": "秒差", "l3r": "上がり順位"}
    for lab, res, pv in (("A 近い・3走目 − C'", A, prevA), ("B 近い・3走目 − 近い・1走目", Bc, prevB)):
        for k in ("fin", "top3", "mar", "l3r"):
            w("| %s | %s | %d/%d | %s | %s | %s |" % (lab, KN[k], res["n"], res["nR"], fmt(res, k), yrs(res, k), pv[k]))
    for lab, res, pv in (("深く圏内・3走目 − C'", Cd, "-6.1 [-9.8, -2.7]"), ("遠い・安全・3走目 − C'", Cs, "+0.2 [-2.3, +2.8]")):
        w("| %s | 3着内 (pt) | %d/%d | %s | %s | %s |" % (lab, res["n"], res["nR"], fmt(res, "top3"), yrs(res, "top3"), pv))
    w()
    w("級の読み取りで級なしにした cls(兵庫の台帳の走・上位 10): " +
      "・".join("%s %d" % (k or "(空)", v) for k, v in UNMATCHED.most_common(10)))
    w()
    w("## 2. 反証 1(C' の偏り)")
    w()
    w("| 群 | 走 | 前走からの日数 25・50・75% | 〜14 / 15〜28 / 29〜56 / 57〜 (%) | 修正の間 60 日あたりの出走数 25・50・75% | 次走までの日数 25・50・75% | 次の級が上(昇級) | 修正 4 回目より前 |")
    w("|---|---|---|---|---|---|---|---|")
    for nm, rs in (("近い・3走目", tgt), ("C'", Cp), ("近い・1走目", G["近い・1走目"])):
        gb = Counter(r["gb"] for r in rs)
        tot = sum(gb[x] for x in ("〜14", "15〜28", "29〜56", "57〜")) or 1
        w("| %s | %d | %s | %s | %s | %s | %.1f%% | %.1f%% |" % (
            nm, len(rs), q([r["gap"] for r in rs]),
            " / ".join("%.0f" % (100 * gb[x] / tot) for x in ("〜14", "15〜28", "29〜56", "57〜")),
            q([r["r60"] for r in rs]), q([r["nxt"] for r in rs]),
            100 * sum(r["promo"] for r in rs) / max(1, len(rs)), 100 * sum(r["i"] < i_min for r in rs) / max(1, len(rs))))
    w()
    w("| そろえ方(近い・3走目 − C') | 走(使った/対照) | 着順 | 3着内 (pt) | 年の向き(3着内) |")
    w("|---|---|---|---|---|")
    for lab, res in (("前任どおり(級×前2走×人気)", A), ("+間隔の区分", A_gap), ("C' を同じ時期(修正 %d 回目以後)に限る" % (i_min + 1), A_per),
                     ("C' から次走で昇級した走を除く(診断)", A_nopromo), ("同じ時期+昇級除く+間隔の区分", A_both),
                     ("発走時点の定義(反証 2 と同じ)", A2), ("発走時点の定義+間隔の区分", A2g)):
        w("| %s | %d/%d | %s | %s | %s |" % (lab, res["n"], res["nR"], fmt(res, "fin"), fmt(res, "top3"), yrs(res, "top3")))
    w()
    w("同じ馬の中の差(近い・3走目の馬の、その馬自身の C' の走との差・層なし・的の走の数で重み付け)")
    w()
    w("| 指標 | 馬 | 的の走 / 対照の走 | 差 [95%] |")
    w("|---|---|---|---|")
    for k in ("fin", "top3"):
        if k in WH:
            pt, lo, hi, H, nt, nc = WH[k]
            sc = 100 if k == "top3" else 1
            w("| %s | %d | %d / %d | %+.3g [%+.3g, %+.3g] |" % (KN[k], H, nt, nc, sc * pt, sc * lo, sc * hi))
    w()
    w("## 3. 反証 2(発走時点の定義)")
    w()
    w("- 見込み日= 直前の修正日+直近 3 回の間隔の中央値。的= 見込み日まで 21 日以内(過ぎた分も含む)で、この走を 3 走目とみなすと近い走。")
    w("- 対照= 見込み日まで 22 日以上の走(級が変わって 3 走目以降・A2〜C2)。どちらも修正 4 回目以後。")
    w("- 的 %d 走のうち、後から見て本当に修正前の最後(3 走目)だった走 %d(%.0f%%)。" % (len(T2), n_actual3, 100 * n_actual3 / max(1, len(T2))))
    w()
    w("| 指標 | 走(使った/対照) | 差 [95%] | 年の向き |")
    w("|---|---|---|---|")
    for k in ("fin", "top3", "mar", "l3r"):
        w("| %s | %d/%d | %s | %s |" % (KN[k], A2["n"], A2["nR"], fmt(A2, k), yrs(A2, k)))
    w()
    w("## 4. 反証 3(偽の修正日・境目は本当の回のもの)")
    w()
    w("| 修正日のずらし | 近い・3走目(使った/対照) | 着順 | 3着内 (pt) | 年の向き(3着内) |")
    w("|---|---|---|---|---|")
    w("| 0 日(本当) | %d/%d | %s | %s | %s |" % (A["n"], A["nR"], fmt(A, "fin"), fmt(A, "top3"), yrs(A, "top3")))
    for sh in (-30, 30):
        res = fake[sh][0]
        w("| %+d 日 | %d/%d | %s | %s | %s |" % (sh, res["n"], res["nR"], fmt(res, "fin"), fmt(res, "top3"), yrs(res, "top3")))
    w()
    w("## 5. 反証 4(対象外の級 A1・C3 に同じ近いを当てる)")
    w()
    w("| 級 | 近い・3走目(使った/対照) | 着順 | 3着内 (pt) | 年の向き(3着内) |")
    w("|---|---|---|---|---|")
    for c in list(EXCL) + ["両方"]:
        res = A4[c]
        w("| %s | %d/%d | %s | %s | %s |" % (c, res["n"], res["nR"], fmt(res, "fin"), fmt(res, "top3"), yrs(res, "top3")))
    w()
    w("差= 層ごとの(的 − 対照)の「実際 − 見込み」を的の走の数で重み付け。95% は馬ごとのクラスタ bootstrap 1000 回。対照 20 走未満の層は捨てる。")
    w("着順・秒差・上がり順位は + が悪い・3着内は − が悪い。")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(o.getvalue())
    log(o.getvalue())


if __name__ == "__main__":
    main()
