# -*- coding: utf-8 -*-
"""研究用・1 回きり: cloud/yarazu_nankan.py(f2cbc62)の主張を別の実装で照合し、反証を試す。
便 .github/workflows/yarazu-nankan-check.yml(workflow_dispatch のみ)から走らせ、docs/yarazu-nankan/check.md を書く。
⛔本番 DB は REST の単純 select だけ(場×年ごと・order は一意の列の組)。書き込みなし。馬名・騎手・調教師・馬主は結果に出さない。
⛔前任の台本・nankan_demotion.py・nankan_hist.py は import しない。線・着内ポイント表・開催の区切り・算定日はここで書く。

決まり(公式 Q&A https://www.nankankeiba.com/info/qanda/program.html を 2026-10-17 に読んだ):
  格付基準表(上半期 1〜6 月・下半期 7〜12 月)= 下の LINE_UP / LINE_DN。nankan_demotion.py の KAMI/SHIMO と全欄一致。
  違い= 公式には C3 の線がある(4 歳 0[4 月以降 20]/20・5 歳 80・6 歳 160・7 歳以上 240)。KAMI には無い(下の級が無いので降級ではない)。
  番組ポイント= 1〜5 着の着内ポイント(⇒ 入着= 1〜5 着)。反映は開催最終日の全レース終了後。
  級は開催ごとに「算定日(前々開催の最終日・南関 4 場の日割)までの点 × 表」で決める(大井番組 5(4)エ・12(1)、
  nar-site/RULES-nankan-class-20260926.md の原文抜き)。表の半期と馬齢は開催の初日で取る(同 §294b)。
定義 A(前任の再現)= 切替日 S を日付で使う。点= S より前に終わった最後の開催の行。実際= S 以後の最初の走の級。
定義 B(直した定義)= 切替後の最初の開催= 初日が S 以後の開催。点= その開催の算定日の点。実際= その開催の走の級。
  ③の締め D_S= S 以後に初日が来る最初の開催(4 場通し)の算定日。締めまで 0〜44 日= 的・45〜134 日= 対照(締めより後に終わる開催の走は外す)。
"""
import bisect
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

TRACKS = ("大井", "川崎", "船橋", "浦和")
CL = ["A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3"]
# 格付基準表(3,4,5,6,7,8歳以上)。None= 空欄。公式 Q&A から書いた
LINE_UP = {"A1": [2800, 3400, 4300, 5000, 5500, 5900], "A2": [2000, 2200, 2500, 3200, 3700, 4100],
           "B1": [1500, 1700, 1900, 2200, 2700, 3000], "B2": [1100, 1200, 1400, 1700, 2000, 2200],
           "B3": [700, 800, 1000, 1300, 1600, 1800], "C1": [None, 500, 700, 1000, 1300, 1500],
           "C2": [None, 200, 400, 700, 1000, 1200], "C3": [None, 0, 80, 160, 240, 240]}
LINE_DN = {"A1": [3000, 3600, 4400, 5200, 5700, 5900], "A2": [2200, 2300, 2600, 3400, 3900, 4100],
           "B1": [1700, 1800, 2000, 2500, 2900, 3000], "B2": [1200, 1300, 1500, 1800, 2100, 2200],
           "B3": [800, 900, 1100, 1400, 1700, 1800], "C1": [500, 600, 800, 1100, 1400, 1500],
           "C2": [200, 300, 500, 800, 1100, 1200], "C3": [None, 20, 80, 160, 240, 240]}
# 着内ポイント表(1〜5 着)。公式 Q&A
P_SP = {"A1": (600, 240, 150, 90, 60), "A2": (500, 200, 125, 75, 50), "B1": (320, 128, 80, 48, 32),
        "B2": (280, 112, 70, 42, 28), "B3": (240, 96, 60, 36, 24), "C1": (200, 80, 50, 30, 20),
        "C2": (180, 72, 45, 27, 18), "C3": (140, 56, 35, 21, 14), "3歳": (280, 112, 70, 42, 28), "2歳": (320, 128, 80, 48, 32)}
P_NM = {"A2": (320, 128, 80, 48, 32), "B1": (280, 112, 70, 42, 28), "B2": (240, 96, 60, 36, 24),
        "B3": (200, 80, 50, 30, 20), "C1": (150, 60, 38, 23, 15), "C2": (100, 40, 25, 15, 10), "C3": (80, 32, 20, 12, 8),
        "3歳前": (220, 88, 55, 33, 22), "3歳後": (160, 64, 40, 24, 16), "2歳": (250, 100, 63, 38, 25), "新馬": (280, 112, 70, 42, 28)}
P_JUN = {"格付": (700, 252, 154, 91, 63), "若": (600, 216, 132, 78, 54)}
P_G = {"2歳": {1: (2000, 700, 400, 200, 100), 2: (1500, 525, 300, 150, 75), 3: (1200, 420, 240, 120, 60), 4: (1000, 350, 200, 100, 50), 5: (840, 294, 168, 84, 42)},
       "3歳": {1: (2400, 840, 480, 240, 120), 2: (1800, 630, 360, 180, 90), 3: (1400, 490, 280, 140, 70), 4: (1200, 420, 240, 120, 60), 5: (1000, 350, 200, 100, 50)},
       "古馬": {1: (5000, 1750, 1000, 500, 250), 2: (3100, 1085, 620, 310, 155), 3: (2600, 910, 520, 260, 130), 4: (2100, 735, 420, 210, 105), 5: (1600, 560, 320, 160, 80)}}

SW = [dt.date(2024, 7, 1), dt.date(2025, 1, 1), dt.date(2025, 7, 1), dt.date(2026, 1, 1), dt.date(2026, 7, 1)]
ALL_SW = SW + [dt.date(2027, 1, 1)]
D_FROM, D_TO = dt.date(2024, 1, 1), dt.date(2026, 9, 30)
FETCH_FROM, FETCH_TO = dt.date(2023, 7, 1), dt.date(2026, 10, 16)
MEET_GAP = 4
FIRST_AFTER = 120
MIN_CELL, MIN_CTRL = 30, 10
BOOT = 1000
MARK_DAYS = 180
PRIOR_VALID = [dt.date(2024, 7, 1), dt.date(2025, 1, 1), dt.date(2026, 1, 1)]
RNG = np.random.default_rng(20261017)
HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "docs" / "yarazu-nankan" / "check.md"
PAGE = 1000
FW = str.maketrans("ＡＢＣＳＩ１２３４５６７８９０", "ABCSI1234567890")
qq = urllib.parse.quote


def log(s):
    print(s, file=sys.stderr, flush=True)


def get(base, key, path):
    for i in range(5):
        req = urllib.request.Request(base + path, headers={"apikey": key, "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=180) as x:
                return json.loads(x.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if (isinstance(e, urllib.error.HTTPError) and e.code < 500) or i == 4:
                raise
            log("retry %s" % str(e)[:80])
            time.sleep(6 * (i + 1))


def paged(base, key, path):
    out, off = [], 0
    while True:
        c = get(base, key, "%s&limit=%d&offset=%d" % (path, PAGE, off))
        out += c
        if len(c) < PAGE:
            return out
        off += PAGE


def fetch(base, key):
    runs, races = [], []
    for tr in TRACKS:
        for y in range(FETCH_FROM.year, FETCH_TO.year + 1):
            a, b = max(dt.date(y, 1, 1), FETCH_FROM), min(dt.date(y, 12, 31), FETCH_TO)
            f = "track=eq.%s&race_date=gte.%s&race_date=lte.%s" % (qq(tr), a, b)
            runs += paged(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,age,finish,"
                          "finish_note,popularity&%s&order=race_date.asc,race_no.asc,runner_number.asc" % f)
            races += paged(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,race_name,race_kind,condition,nankan"
                           "&%s&order=race_date.asc,race_no.asc" % f)
            log("%s %d runs %d races %d" % (tr, y, len(runs), len(races)))
    pts = paged(base, key, "/rest/v1/nar_nankan_points?select=code,horse_name,birth_date&order=code.asc")
    hist = paged(base, key, "/rest/v1/nar_nankan_point_hist?select=code,meet_end,points,kaku_ran&order=code.asc,meet_end.asc")
    log("points %d hist %d" % (len(pts), len(hist)))
    return runs, races, pts, hist


def ii(v):
    try:
        x = int(str(v).strip())
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def kcls(s):
    s = str(s or "").strip().translate(FW).upper()
    return s if s in CL else None


def name_classes(name):
    s = str(name or "").translate(FW)
    return sorted(set(re.findall(r"([ABC][123])(?![0-9])", s)), key=CL.index)


def race_class(rc):
    """単一の級(選抜・特選を含む)。選定・オープン・重賞・準重賞・混合は None"""
    if not rc:
        return None
    c = name_classes(rc.get("race_name"))
    if len(c) != 1 or rc.get("race_kind") in ("重賞", "準重賞") or re.search(r"選定|オープン", str(rc.get("race_name") or "")):
        return None
    return c[0]


def age_group(rc):
    s = (str(rc.get("race_name") or "") + " " + str(rc.get("condition") or "")).translate(FW)
    if "2歳" in s:
        return "2歳"
    if re.search(r"3歳(?!以上|上)", s) and not re.search(r"3上|3歳以上", s):
        return "3歳"
    return "古馬"


def ptab(rc):
    """このレースの 1〜5 着の着内ポイント。主催者の値(nankan.pts)を先に。決まらなければ None"""
    if not rc:
        return None, "レースなし"
    nk = rc.get("nankan") or {}
    if isinstance(nk, dict) and isinstance(nk.get("pts"), list) and len(nk["pts"]) == 5:
        try:
            return tuple(float(x) for x in nk["pts"]), "公式"
        except (TypeError, ValueError):
            pass
    kind, name = rc.get("race_kind") or "", str(rc.get("race_name") or "").translate(FW)
    ag = age_group(rc)
    if kind == "重賞":
        m = re.search(r"(Jpn|G|S)\s*([ⅠⅡⅢ]|III|II|I)", name)
        if not m:
            return None, "重賞の格が名前に無い"
        g = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "I": 1, "II": 2, "III": 3}[m.group(2)]
        lv = {("Jpn", 1): 1, ("G", 1): 1, ("Jpn", 2): 2, ("S", 1): 2, ("Jpn", 3): 3, ("S", 2): 3, ("S", 3): 4}.get((m.group(1), g))
        if lv is None:
            return None, "重賞の格が読めない"
        if "牝" in name and m.group(1) == "S":
            lv += 1
        return P_G[ag][min(lv, 5)], "表"
    if kind == "準重賞":
        return (P_JUN["若"] if ag in ("2歳", "3歳") else P_JUN["格付"]), "表"
    if kind not in ("特別", "普通"):
        return None, "種類なし"
    tab = P_SP if kind == "特別" else P_NM
    c = name_classes(name)
    if c:
        return (tab.get(c[0]), "表") if tab.get(c[0]) else (None, "表に無い級")
    if ag == "2歳":
        return (P_NM["新馬"] if (kind == "普通" and "新馬" in name) else tab["2歳"]), "表"
    if ag == "3歳":
        if kind == "特別":
            return P_SP["3歳"], "表"
        return P_NM["3歳前" if int(str(rc["race_date"])[5:7]) <= 6 else "3歳後"], "表"
    if "オープン" in name and kind == "特別":
        return P_SP["A1"], "表"
    return None, "級が名前に無い"


def line(S, k, age):
    if k not in LINE_UP or age is None or age < 3:
        return None
    t = LINE_UP if S.month == 1 else LINE_DN
    return t[k][min(age, 8) - 3]


def status(P, p1, L):
    if L is None or P is None or p1 is None:
        return None
    return "安全" if P >= L else ("境目" if P + p1 >= L else "深く圏内")


# ---------------------------------------------------------------- 下ごしらえ
def build(runs, races, pts, hist):
    RC = {(r["track"], str(r["race_date"])[:10], int(r["race_no"])): r for r in races if r.get("race_no") is not None}
    # 開催= 場ごとに開催日を並べ、間 MEET_GAP 日以内を同じ開催
    days = defaultdict(set)
    for (tr, d, _) in RC:
        days[tr].add(d)
    meet_of, meets = {}, []
    for tr, ds in days.items():
        ds = sorted(dt.date.fromisoformat(x) for x in ds)
        cur = [ds[0]]
        for d in ds[1:]:
            if (d - cur[-1]).days <= MEET_GAP:
                cur.append(d)
            else:
                meets.append((cur[0], cur[-1], tr))
                cur = [d]
        meets.append((cur[0], cur[-1], tr))
    meets.sort()
    santei = {}
    for i, m in enumerate(meets):
        santei[m] = meets[i - 2][1] if i >= 2 else None
    for m in meets:
        d = m[0]
        while d <= m[1]:
            meet_of[(m[2], d)] = m
            d += dt.timedelta(days=1)
    # 切替ごとの締め D_S= S 以後に初日が来る最初の開催の算定日
    cut = {}
    for S in ALL_SW:
        f = [m for m in meets if m[0] >= S]
        cut[S] = santei[f[0]] if f else S
    # 馬コード
    nm = defaultdict(set)
    birth = {}
    for p in pts:
        if p.get("horse_name"):
            nm[p["horse_name"]].add(str(p["code"]))
        birth[str(p["code"])] = p.get("birth_date")
    code_of = {n: next(iter(c)) for n, c in nm.items() if len(c) == 1}
    H = defaultdict(list)
    for h in hist:
        pv = h.get("points")
        H[str(h["code"])].append((dt.date.fromisoformat(str(h["meet_end"])[:10]),
                                  None if pv is None else float(pv), kcls(h.get("kaku_ran"))))
    for c in H:
        H[c].sort(key=lambda x: x[0])
    # 走
    byrace = defaultdict(list)
    for r in runs:
        if r.get("race_no") is None:
            continue
        byrace[(r["track"], str(r["race_date"])[:10], int(r["race_no"]))].append(r)
    R, srcs = [], Counter()
    for k, rs in byrace.items():
        rc = RC.get(k)
        tab, src = ptab(rc)
        n = sum(1 for r in rs if ii(r.get("finish")))
        d = dt.date.fromisoformat(k[1])
        m = meet_of.get((k[0], d))
        for r in rs:
            f = ii(r.get("finish"))
            srcs[src] += 1
            R.append({"tr": k[0], "d": d, "no": k[2], "rn": str(r.get("runner_number")), "name": r.get("horse_name"),
                      "age": ii(r.get("age")), "fin": f, "pop": ii(r.get("popularity")), "n": n,
                      "p1": tab[0] if tab else None,
                      "pt": (0.0 if (f is None or f > 5) else (tab[f - 1] if tab else None)),
                      "kr": race_class(rc), "meet": m})
    R.sort(key=lambda v: (v["d"], v["tr"], v["no"], v["rn"]))
    return R, RC, meets, santei, cut, code_of, birth, H, srcs


def byear(code, birth):
    if code[:4].isdigit():
        return int(code[:4])
    b = birth.get(code)
    return int(str(b)[:4]) if b else None


def pts_asof(Hc, d, strict):
    """d より前(strict)/ d 以前 に終わった開催の最後の行 → (行の位置, 点)"""
    ds = [x[0] for x in Hc]
    i = (bisect.bisect_left(ds, d) if strict else bisect.bisect_right(ds, d)) - 1
    return (i, Hc[i][1]) if i >= 0 else (None, None)


# ---------------------------------------------------------------- 見込み
def expectation(R):
    cell = defaultdict(lambda: np.zeros(4))
    for v in R:
        if v["fin"] and v["pop"] and v["n"] and D_FROM <= v["d"] <= D_TO:
            cell[(v["pop"], v["n"], v["d"].year)] += [1, v["fin"] <= 5, v["fin"] <= 3, v["fin"]]
    tot = defaultdict(lambda: np.zeros(4))
    for (p, n, y), c in cell.items():
        tot[(p, n)] += c
    memo = {}

    def e(p, n, y):
        if (p, n, y) not in memo:
            t = tot.get((p, n))
            x = None
            if t is not None:
                dd = t - cell.get((p, n, y), np.zeros(4))
                if dd[0] >= MIN_CELL:
                    x = (dd[1] / dd[0], dd[2] / dd[0], dd[3] / dd[0])
            memo[(p, n, y)] = x
        return memo[(p, n, y)]
    return e


MET = [("in5", "入着(1〜5着)率 pt", 100, 1), ("top3", "3着内率 pt", 100, 1), ("fin", "着順", 1, 3)]


def resid(v, e):
    if not (v["fin"] and v["pop"] and v["n"]):
        return None
    x = e(v["pop"], v["n"], v["d"].year)
    if not x:
        return None
    return {"in5": (v["fin"] <= 5) - x[0], "top3": (v["fin"] <= 3) - x[1], "fin": v["fin"] - x[2]}


# ---------------------------------------------------------------- ① 組み立て直し
def rebuild(R, meets, santei, code_of, birth, H, mode):
    """mode A= 前任の定義の再現 / B= 開催の初日と算定日で直した定義"""
    byh = defaultdict(list)
    for v in R:
        c = code_of.get(v["name"])
        if c:
            byh[c].append(v)
    rows, why = [], Counter()
    for S in SW:
        for c, Hc in H.items():
            rs = byh.get(c, [])
            by = byear(c, birth)
            if mode == "A":
                i, P = pts_asof(Hc, S, True)
                if i is None or Hc[i][0] < S - dt.timedelta(days=183):
                    continue
                k = Hc[i][2]
                ds = [x["d"] for x in rs]
                j = bisect.bisect_left(ds, S)
                pre = rs[j - 1] if j > 0 else None
                if k is None and pre is not None:
                    k = pre["kr"]
                post = rs[j] if j < len(rs) and (rs[j]["d"] - S).days <= FIRST_AFTER else None
                if P is None or k is None:
                    why["点か級なし"] += 1
                    continue
                pk = post["kr"] if post else None
            else:
                post = next((x for x in rs if x["meet"] and x["meet"][0] >= S and (x["d"] - S).days <= FIRST_AFTER
                             and x["kr"]), None)
                pre_l = [x for x in rs if x["d"] < S and x["d"] >= S - dt.timedelta(days=183) and x["kr"]
                         and (post is None or x["d"] < post["meet"][0])]
                pre = pre_l[-1] if pre_l else None
                k = pre["kr"] if pre else None
                if post is None:
                    if k is None:
                        continue
                    why["切替後 120 日以内に級つきの走なし"] += 1
                    continue
                D1 = santei.get(post["meet"])
                i, P = pts_asof(Hc, D1, False) if D1 else (None, None)
                if k is None:
                    why["切替前 183 日に級つきの走なし"] += 1
                    continue
                if P is None:
                    why["算定日の点なし"] += 1
                    continue
                pk = post["kr"]
            age = (S.year - by) if by else None
            age_b = None if age is None else (age if S.month == 7 else age - 1)
            L = line(S, k, age)
            if k == "C3" or age is None or age < 3 or age_b >= 8 or not L:
                why["対象外(C3・8歳以上・線空欄・馬齢不明)"] += 1
                continue
            if mode == "A" and post is None:
                why["切替後 120 日以内に走なし"] += 1
                continue
            if pk is None:
                why["切替後最初の走が単一の級でない"] += 1
                continue
            rows.append({"S": S, "code": c, "k": k, "age": age, "P": P, "L": L, "pred": P < L,
                         "down": CL.index(pk) > CL.index(k), "post": post, "pre": pre,
                         "tr": (pre or post)["tr"]})
    return rows, why


def agree(rows, S, tr=None):
    g = [r for r in rows if r["S"] == S and (tr is None or r["tr"] == tr)]
    P = sum(r["pred"] for r in g)
    A = sum(r["down"] for r in g)
    B = sum(r["pred"] and r["down"] for r in g)
    pr, rc = (B / P if P else None), (B / A if A else None)
    return len(g), P, A, B, pr, rc, (min(pr, rc) if pr is not None and rc is not None else None)


# ---------------------------------------------------------------- 走ごとの区分
def classify(R, code_of, birth, H, e, cut):
    """各走の材料。区分に使うのは発走前の値だけ(点・級・線・時期)。"""
    byn = defaultdict(list)
    for v in R:
        byn[v["name"]].append(v)
    last_run = {n: rs[-1]["d"] for n, rs in byn.items()}
    out, why = [], Counter()
    cuts = sorted(ALL_SW)
    for name, rs in byn.items():
        c = code_of.get(name)
        for j, v in enumerate(rs):
            if not (D_FROM <= v["d"] <= D_TO):
                continue
            if not c or c not in H:
                why["コードか点の履歴なし"] += 1
                continue
            m = resid(v, e)
            if not m:
                why["見込みなし"] += 1
                continue
            Hc = H[c]
            i, P = pts_asof(Hc, v["d"], True)
            if i is None or P is None:
                why["レース前の点なし"] += 1
                continue
            bad = False
            for x in rs[:j]:
                if x["d"] > Hc[i][0]:
                    if x["pt"] is None:
                        bad = True
                        break
                    P += x["pt"]
            if bad or v["p1"] is None:
                why["点が決まらない"] += 1
                continue
            k = v["kr"]
            if k is None and v["meet"]:
                hh = [x for x in Hc if x[0] == v["meet"][1]]
                k = hh[0][2] if hh else None
            if k is None:
                why["級なし"] += 1
                continue
            by = byear(c, birth)
            prev = rs[:j]
            fp = [x["fin"] for x in prev[-2:]]
            p2 = sum(fp) if len(fp) == 2 and all(fp) else None
            g = (v["d"] - prev[-1]["d"]).days if prev else None
            lay = (k, "無" if p2 is None else ("~6" if p2 <= 6 else "7-12" if p2 <= 12 else "13-18" if p2 <= 18 else "19~"),
                   "1" if v["pop"] == 1 else "2-3" if v["pop"] <= 3 else "4-6" if v["pop"] <= 6 else "7~",
                   "無" if g is None else ("~14" if g <= 14 else "15-28" if g <= 28 else "29-56" if g <= 56 else "57~"))
            me = v["meet"][1] if v["meet"] else v["d"]
            # 定義 A の的(切替日)/ 定義 B の的(締め)
            iA = bisect.bisect_right(cuts, v["d"])
            SA = cuts[iA] if iA < len(cuts) else None
            SB = next((S for S in cuts if cut[S] >= me), None)
            rec = {"code": c, "d": v["d"], "m": m, "lay": lay, "k": k, "P": P, "p1": v["p1"], "by": by, "me": me,
                   "SA": SA, "SB": SB,
                   "mark": (None if v["d"] > FETCH_TO - dt.timedelta(days=MARK_DAYS)
                            else last_run[name] <= v["d"] + dt.timedelta(days=MARK_DAYS))}
            for tag, S in (("A", SA), ("B", SB)):
                if S is None:
                    rec["st" + tag] = rec["ex" + tag] = None
                    continue
                age = S.year - by if by else None
                if age is None or age < 3:
                    rec["st" + tag], rec["ex" + tag] = None, None
                    continue
                age_b = age if S.month == 7 else age - 1
                if k == "C3":
                    rec["ex" + tag] = "C3"
                    Lo = line(S, "C3", age)
                    rec["st" + tag] = None
                    rec["ps" + tag] = None if Lo is None else ("境目" if Lo <= P < Lo + v["p1"] else "他")
                    continue
                L = line(S, k, age)
                if age_b >= 8:
                    rec["ex" + tag] = "8歳以上"
                    rec["st" + tag] = None
                    rec["ps" + tag] = None if L is None else ("境目" if L <= P < L + v["p1"] else "他")
                    continue
                if not L:
                    rec["ex" + tag], rec["st" + tag], rec["ps" + tag] = "線空欄", None, None
                    continue
                rec["ex" + tag], rec["ps" + tag] = None, None
                rec["st" + tag] = status(P, v["p1"], L)
            out.append(rec)
    return out, why


def phase_A(x, valid, shift=0):
    S = x["SA"]
    if S is None:
        return None, None
    if shift:
        fs = sorted(s + dt.timedelta(days=shift) for s in ALL_SW)
        i = bisect.bisect_right(fs, x["d"])
        if i >= len(fs):
            return None, None
        S = fs[i] - dt.timedelta(days=shift)
    if S not in valid:
        return None, None
    dd = (S + dt.timedelta(days=shift) - x["d"]).days
    return ("的" if 1 <= dd <= 45 else "対照" if 46 <= dd <= 135 else None), S


def phase_B(x, valid, cut, shift=0):
    if shift:
        S = next((s for s in sorted(ALL_SW) if cut[s] + dt.timedelta(days=shift) >= x["me"]), None)
    else:
        S = x["SB"]
    if S is None or S not in valid:
        return None, None
    dd = (cut[S] + dt.timedelta(days=shift) - x["d"]).days
    return ("的" if 0 <= dd <= 44 else "対照" if 45 <= dd <= 134 else None), S


# ---------------------------------------------------------------- 比べ
class Comp:
    def __init__(self, T, C, hidx):
        cT, cC = Counter(t[1] for t in T), Counter(t[1] for t in C)
        ok = sorted(l for l in cT if cC.get(l, 0) >= MIN_CTRL)
        li = {l: i for i, l in enumerate(ok)}
        T = [t for t in T if t[1] in li]
        C = [t for t in C if t[1] in li]
        self.nl, self.nT, self.nC = len(ok), len(T), len(C)
        self.hT = np.array([hidx[t[0]] for t in T], dtype=np.int64)
        self.hC = np.array([hidx[t[0]] for t in C], dtype=np.int64)
        self.lT = np.array([li[t[1]] for t in T], dtype=np.int64)
        self.lC = np.array([li[t[1]] for t in C], dtype=np.int64)
        self.yT = np.array([t[2] for t in T], dtype=float)
        self.yC = np.array([t[2] for t in C], dtype=float)

    def val(self, w=None):
        if self.nl == 0 or self.nT == 0:
            return None
        wT = np.ones(self.nT) if w is None else w[self.hT].astype(float)
        wC = np.ones(self.nC) if w is None else w[self.hC].astype(float)
        nT = np.bincount(self.lT, wT, self.nl)
        nC = np.bincount(self.lC, wC, self.nl)
        sT = np.bincount(self.lT, wT * self.yT, self.nl)
        sC = np.bincount(self.lC, wC * self.yC, self.nl)
        g = (nT > 0) & (nC > 0)
        if not g.any():
            return None
        return float(((sT[g] / nT[g] - sC[g] / nC[g]) * nT[g]).sum() / nT[g].sum())


def pct(vals):
    v = [x for x in vals if x is not None]
    if len(v) < 0.9 * BOOT:
        return None
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def f(x, sc, nd):
    return "-" if x is None else ("%+." + str(nd) + "f") % (x * sc)


def fci(c, sc, nd):
    return "-" if c is None else "[%s, %s]" % (f(c[0], sc, nd), f(c[1], sc, nd))


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not (base and key):
        log("鍵が無い")
        return 2
    runs, races, pts, hist = fetch(base, key)
    R, RC, meets, santei, cut, code_of, birth, H, srcs = build(runs, races, pts, hist)
    e = expectation(R)
    O = []
    w = O.append
    w("# 南関4場 降級前のヤラズ 照合と反証(check)")
    w("")
    w("- 台本 cloud/yarazu_nankan_check.py・便 yarazu-nankan-check.yml(手動 1 回)。前任 cloud/yarazu_nankan.py(f2cbc62)の result.md を別の実装で照合")
    w("- 作成 %s UTC・出どころ nar_runs / nar_races / nar_nankan_points / nar_nankan_point_hist(読むだけ)・走 %s〜%s(印のため %s まで取得)"
      % (dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), D_FROM, D_TO, FETCH_TO))
    w("- 馬名・騎手・調教師・馬主は出さない")
    w("")
    w("## 0. 決まりと下ごしらえ")
    w("")
    w("- 線: 公式 Q&A の格付基準表と nankan_demotion.py KAMI(上半期)/SHIMO(下半期)は A1〜C2 の全欄一致。違い= 公式には C3 の線(4歳 0[4月以降 20]/20・5歳 80・6歳 160・7歳以上 240)があり KAMI に無い(C3 は下の級が無く降級ではない= 対象外のまま)。")
    w("- 入着= 1〜5 着(公式 Q&A「番組ポイントとは 1着から5着までの着内ポイントの合計」)。前任と同じ。")
    w("- 公式の決まりで前任の式と違う所: 級は開催ごとに「算定日(前々開催の最終日・4 場の日割)の点 × 表」で決まり、表の半期と馬齢は開催の初日で取る(RULES-nankan-class-20260926.md の原文抜き)。前任は切替日 S の日付と「S より前に終わった最後の開催の点」で見ている。")
    hm = Counter()
    mend = defaultdict(set)
    for m in meets:
        mend[m[1]].add(m[2])
    for c, Hc in H.items():
        for x in Hc:
            if x[0] >= D_FROM:
                hm[x[0] in mend] += 1
    w("- 開催の区切り(場ごとに間 %d 日以内)= %d 開催。点の履歴の開催最終日のうち区切りの最終日と一致 %d / %d。"
      % (MEET_GAP, len(meets), hm[True], hm[True] + hm[False]))
    w("- 切替ごとの締め D_S(S 以後に初日が来る最初の開催の算定日)と、S をまたぐ開催: " + "・".join(
        "%s→%s(またぐ %s)" % (S, cut[S], ",".join("%s %s〜%s" % (m[2], m[0].strftime("%m/%d"), m[1].strftime("%m/%d"))
                                               for m in meets if m[0] < S <= m[1]) or "なし") for S in SW))
    w("- 着内ポイントの出どころ(走): " + "・".join("%s %d" % kv for kv in srcs.most_common()))
    w("")

    # ① 再現
    rows = {}
    whys = {}
    for mode in ("A", "B"):
        rows[mode], whys[mode] = rebuild(R, meets, santei, code_of, birth, H, mode)
    w("## 1. 組み立て直しの一致率(A= 前任の定義の再現・B= 開催の初日と算定日で直した定義)")
    w("")
    w("一致率= min(予測のうち当たり, 実際のうち拾えた)。")
    w("")
    w("| 切替 | 前任 | A 馬 | A 予測/実際/両方 | A 一致率 | B 馬 | B 予測/実際/両方 | B 当たり | B 拾い | B 一致率 |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    prior = {SW[0]: "97.6%(312・82/82/80)", SW[1]: "97.8%(552・135/133/132)", SW[2]: "62.2%(594・164/105/102)",
             SW[3]: "96.7%(925・269/275/266)", SW[4]: "73.2%(1057・284/221/208)"}
    validB = []
    for S in SW:
        a = agree(rows["A"], S)
        b = agree(rows["B"], S)
        w("| %s | %s | %d | %d/%d/%d | %s | %d | %d/%d/%d | %s | %s | %s |" % (
            S, prior[S], a[0], a[1], a[2], a[3], "-" if a[6] is None else "%.1f%%" % (a[6] * 100),
            b[0], b[1], b[2], b[3], "-" if b[4] is None else "%.1f%%" % (b[4] * 100),
            "-" if b[5] is None else "%.1f%%" % (b[5] * 100), "-" if b[6] is None else "%.1f%%" % (b[6] * 100)))
        if b[6] is not None and b[6] >= 0.8:
            validB.append(S)
    w("")
    w("- A の除いた数: " + "・".join("%s %d" % kv for kv in whys["A"].most_common()))
    w("- B の除いた数: " + "・".join("%s %d" % kv for kv in whys["B"].most_common()))
    w("- B で 80%% 以上の回(③で使う): %s" % ("・".join(str(s) for s in validB) or "なし"))
    w("")

    # ② 外れの型(A の予測「下がる」で下がらなかった馬)
    w("## 2. 定義 A の外れ(予測「下がる」・実際は下がらず)の型")
    w("")
    w("型は上から順に 1 つだけ当てる。またぐ= 切替後最初の走が S より前に始まった開催(旧い級のまま)。算定日の点= その馬の S 以後に初日が来る最初の級つきの開催の算定日の点が線以上。")
    w("")
    w("| 切替 | 外れ | またぐ開催で走った | 算定日までに点が線を越えた | 3歳 | 上の級へ | 他 | 見逃し(A) | 見逃し(B) |")
    w("|---|---|---|---|---|---|---|---|---|")
    bmap = {(r["S"], r["code"]): r for r in rows["B"]}
    for S in SW:
        fp = [r for r in rows["A"] if r["S"] == S and r["pred"] and not r["down"]]
        t = Counter()
        for r in fp:
            p = r["post"]
            rb = bmap.get((S, r["code"]))
            if p["meet"] and p["meet"][0] < S:
                t["span"] += 1
            elif rb is not None and not rb["pred"]:
                t["pts"] += 1
            elif r["age"] == 3:
                t["y3"] += 1
            elif CL.index(p["kr"]) < CL.index(r["k"]):
                t["up"] += 1
            else:
                t["other"] += 1
        fnA = sum(1 for r in rows["A"] if r["S"] == S and r["down"] and not r["pred"])
        fnB = sum(1 for r in rows["B"] if r["S"] == S and r["down"] and not r["pred"])
        w("| %s | %d | %d | %d | %d | %d | %d | %d | %d |" % (S, len(fp), t["span"], t["pts"], t["y3"], t["up"], t["other"], fnA, fnB))
    w("")

    # 走の区分
    X, whyX = classify(R, code_of, birth, H, e, cut)
    hidx = {c: i for i, c in enumerate(sorted({x["code"] for x in X}))}
    draws = [np.bincount(RNG.integers(0, len(hidx), len(hidx)), minlength=len(hidx)) for _ in range(BOOT)]

    def comp(sel, phf, met):
        T, C = [], []
        for x in X:
            if not sel(x):
                continue
            ph, S = phf(x)
            if ph is None:
                continue
            (T if ph == "的" else C).append((x["code"], x["lay"], x["m"][met]))
        return Comp(T, C, hidx)

    def one(cm):
        return cm.val(), pct([cm.val(dw) for dw in draws])

    def dd(c1, c2):
        a, b = c1.val(), c2.val()
        v = None if a is None or b is None else a - b
        bs = []
        for dw in draws:
            x1, x2 = c1.val(dw), c2.val(dw)
            bs.append(None if x1 is None or x2 is None else x1 - x2)
        return v, pct(bs)

    def count(sel, phf):
        c = Counter()
        for x in X:
            if sel(x):
                ph, _ = phf(x)
                if ph:
                    c[ph] += 1
        return c

    pA = lambda x: phase_A(x, PRIOR_VALID)
    vB = validB
    pB = lambda x: phase_B(x, vB, cut)
    w("## 3. 主の比べ(的 − 対照・層でそろえた「実際 − 見込み」)")
    w("")
    w("A= 前任の定義(前任の使う回 2024-07・2025-01・2026-01・切替日まで 1〜45 / 46〜135 日)。B= 直した定義(使う回 %s・締め D_S まで 0〜44 / 45〜134 日)。"
      % ("・".join(str(s) for s in vB) or "なし"))
    w("")
    w("| 定義 | 区分 | 指標 | 区分の走(的/対照) | 層に入った走(的/対照) | 差 | 95% | 前任 |")
    w("|---|---|---|---|---|---|---|---|")
    PRI = {("境目", "in5"): "-0.4 [-6.4, +5.4]・884/1547・446/838", ("安全", "in5"): "-0.7 [-3.5, +2.2]・2208/3174",
           ("深く圏内", "in5"): "-6.7 [-32.4, +21.8]", ("dd", "in5"): "+0.3 [-6.1, +6.4]",
           ("境目", "top3"): "-2.3 [-7.3, +2.3]", ("境目", "fin"): "+0.178 [-0.165, +0.550]",
           ("dd", "top3"): "-2.2", ("dd", "fin"): "+0.110"}
    res = {}
    for tag, phf in (("A", pA), ("B", pB)):
        for met, lb, sc, nd in MET:
            cs = {}
            for st in ("境目", "安全", "深く圏内"):
                sel = (lambda x, st=st, tag=tag: x.get("st" + tag) == st)
                cm = comp(sel, phf, met)
                cs[st] = cm
                if met != "in5" and st == "深く圏内":
                    continue
                v, b = one(cm)
                cn = count(sel, phf)
                res[(tag, st, met)] = (v, b)
                w("| %s | %s | %s | %d/%d | %d/%d | %s | %s | %s |" % (tag, st, lb, cn["的"], cn["対照"], cm.nT, cm.nC,
                                                                 f(v, sc, nd), fci(b, sc, nd), PRI.get((st, met), "") if tag == "A" else ""))
            v, b = dd(cs["境目"], cs["安全"])
            res[(tag, "dd", met)] = (v, b)
            w("| %s | 差の差(境目 − 安全) | %s | - | - | %s | %s | %s |" % (tag, lb, f(v, sc, nd), fci(b, sc, nd),
                                                                     PRI.get(("dd", met), "") if tag == "A" else ""))
    w("")
    w("- 走の除いた数: " + "・".join("%s %d" % kv for kv in whyX.most_common()))
    w("")

    # ③ 抜け
    w("## 4. 引退馬の抜け(コードか点の履歴が無い走)")
    w("")
    tot = [v for v in R if D_FROM <= v["d"] <= D_TO and v["fin"]]

    def miss(v):
        c = code_of.get(v["name"])
        return not c or c not in H

    def tbl(keyf, title):
        g = defaultdict(lambda: [0, 0])
        for v in tot:
            k = keyf(v)
            g[k][0] += 1
            g[k][1] += miss(v)
        w("| %s | 走 | 抜け | 抜けの割合 |" % title)
        w("|---|---|---|---|")
        for k in sorted(g, key=lambda z: str(z)):
            a, b = g[k]
            w("| %s | %d | %d | %.1f%% |" % (k, a, b, b / a * 100))
        w("")
    a_all = len(tot)
    b_all = sum(miss(v) for v in tot)
    w("全体: 着順つきの走 %d のうち抜け %d(%.1f%%)。" % (a_all, b_all, b_all / a_all * 100))
    w("")
    tbl(lambda v: "%d%s" % (v["d"].year, "上" if v["d"].month <= 6 else "下"), "期間")
    tbl(lambda v: v["kr"] or "級なしのレース", "レースの級")
    tbl(lambda v: "不明" if v["age"] is None else ("%d歳" % v["age"] if v["age"] < 8 else "8歳以上"), "年齢(走の時点)")
    w("### 4-2. 残った走を「その後 %d 日以内に南関で走らなくなった馬」で分けた主の比べ(定義 B・入着率)" % MARK_DAYS)
    w("")
    w("印= この走の後 %d 日の間に南関の最後の走がある(%s までの走で判定・それより後の走は印なし= 外す)。⚠後から分かる事実= 群を決める材料には使わず、分けて見るだけ。"
      % (MARK_DAYS, FETCH_TO - dt.timedelta(days=MARK_DAYS)))
    w("")
    w("| 印 | 区分 | 走(的/対照) | 差 | 95% | 差の差(境目 − 安全) | 95% |")
    w("|---|---|---|---|---|---|---|")
    for mk in (True, False):
        cb = comp(lambda x, mk=mk: x.get("stB") == "境目" and x["mark"] is mk, pB, "in5")
        cs = comp(lambda x, mk=mk: x.get("stB") == "安全" and x["mark"] is mk, pB, "in5")
        v, b = one(cb)
        v2, b2 = dd(cb, cs)
        res[("mark", mk)] = (v, b, v2, b2)
        w("| %s | 境目 | %d/%d | %s | %s | %s | %s |" % ("あり" if mk else "なし", cb.nT, cb.nC, f(v, 100, 1), fci(b, 100, 1),
                                                     f(v2, 100, 1), fci(b2, 100, 1)))
    mk_n = Counter((x["mark"], phase_B(x, vB, cut)[0]) for x in X if x.get("stB") == "境目")
    w("")
    w("境目の走の印: " + "・".join("%s×%s %d" % (k[0], k[1], n) for k, n in sorted(mk_n.items(), key=str) if k[1]))
    w("")

    # ④ 反証
    w("## 5. 反証(定義 B・入着率と着順)")
    w("")
    w("a 対象外= 線が動かない/降級が無い群に「線のすぐ上(線 ≤ 点 < 線 + 1 着の点)」を見かけの境目として当てる(前任の作り= 7歳の上げ幅・C2÷2 とは別)。8歳以上は今の級の線(上下半期で同じ)、C3 は公式の C3 の線。")
    w("b 偽の日= 締め D_S を ±60 日ずらし時期だけ偽の日で切る(区分は本当の切替の線)。c 同じ馬の中= 馬×回ごとの(的 − 対照)。層つき= 各走から同じ層の対照の平均を引いてから差。")
    w("")
    w("| 反証 | 指標 | 走(的/対照) | 差 | 95% |")
    w("|---|---|---|---|---|")
    fk = {}
    for met, lb, sc, nd in MET:
        if met == "top3":
            continue
        for ex in ("8歳以上", "C3"):
            cm = comp(lambda x, ex=ex: x.get("exB") == ex and x.get("psB") == "境目", pB, met)
            v, b = one(cm)
            fk[("a" + ex, met)] = (v, b)
            w("| a 対象外 %s・見かけの境目 | %s | %d/%d | %s | %s |" % (ex, lb, cm.nT, cm.nC, f(v, sc, nd), fci(b, sc, nd)))
        for sh in (-60, 60):
            cm = comp(lambda x: x.get("stB") == "境目", lambda x, sh=sh: phase_B(x, vB, cut, sh), met)
            v, b = one(cm)
            fk[("b%+d" % sh, met)] = (v, b)
            w("| b 偽の締め %+d 日・境目 | %s | %d/%d | %s | %s |" % (sh, lb, cm.nT, cm.nC, f(v, sc, nd), fci(b, sc, nd)))
        # c 同じ馬の中
        for adj in (False, True):
            lm = defaultdict(list)
            if adj:
                for x in X:
                    if x.get("stB") == "境目":
                        ph, S = pB(x)
                        if ph == "対照":
                            lm[x["lay"]].append(x["m"][met])
                lmean = {k: float(np.mean(v)) for k, v in lm.items() if len(v) >= MIN_CTRL}
            per = defaultdict(lambda: {"的": [], "対照": []})
            for x in X:
                if x.get("stB") != "境目":
                    continue
                ph, S = pB(x)
                if ph is None:
                    continue
                y = x["m"][met]
                if adj:
                    if x["lay"] not in lmean:
                        continue
                    y -= lmean[x["lay"]]
                per[(x["code"], S)][ph].append(y)
            it = [(hidx[c], np.mean(d["的"]) - np.mean(d["対照"]), len(d["的"]), len(d["対照"]))
                  for (c, S), d in per.items() if d["的"] and d["対照"]]
            if not it:
                w("| c 同じ馬の中%s | %s | 0 | - | - |" % ("・層つき" if adj else "", lb))
                continue
            hi = np.array([t[0] for t in it])
            dv = np.array([t[1] for t in it])
            wv = np.array([t[2] for t in it], dtype=float)
            v = float((dv * wv).sum() / wv.sum())
            bs = []
            for dw in draws:
                ww = dw[hi] * wv
                bs.append(float((dv * ww).sum() / ww.sum()) if ww.sum() > 0 else None)
            b = pct(bs)
            fk[("c" + ("adj" if adj else ""), met)] = (v, b)
            w("| c 同じ馬の中%s | %s | %d/%d(馬×回 %d) | %s | %s |" % ("・層つき" if adj else "・層なし", lb, int(wv.sum()),
                                                               sum(t[3] for t in it), len(it), f(v, sc, nd), fci(b, sc, nd)))
    w("")

    def sig(vb, met):
        v, b = vb
        if v is None or b is None:
            return False
        return b[1] < 0 if met in ("in5", "top3") else b[0] > 0
    realB = sig(res[("B", "境目", "in5")], "in5") or sig(res[("B", "境目", "fin")], "fin")
    ddB = sig(res[("B", "dd", "in5")], "in5") or sig(res[("B", "dd", "fin")], "fin")
    realA = sig(res[("A", "境目", "in5")], "in5") or sig(res[("A", "境目", "fin")], "fin")
    w("## 6. 判定")
    w("")
    w("境目×的のヤラズの向き(入着率は −・着順は +)に 95%% が 0 をまたがない= A %s・B %s・B の差の差 %s → %s"
      % ("出た" if realA else "出ない", "出た" if realB else "出ない", "出た" if ddB else "出ない",
         "痕跡は言えない(変わらず)" if not (realB or ddB) else "要再検討(B で向きが出た)"))
    w("")
    w("差= 層ごとの(的 − 対照)を的の走の数で重み付け。層= 級×前2走の着順合計×人気×前走からの間隔(前任と同じ区分)・対照 %d 走未満の層は捨てる。見込み= 人気×頭数(自分の年を除く・%d 走未満は捨てる)。95%% は馬ごとのクラスタ bootstrap %d 回。"
      % (MIN_CTRL, MIN_CELL, BOOT))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(O) + "\n", encoding="utf-8")
    print("\n".join(O))
    return 0


if __name__ == "__main__":
    sys.exit(main())
