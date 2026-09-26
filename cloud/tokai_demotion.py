# -*- coding: utf-8 -*-
"""§287 笠松・名古屋の「降級の目安」を表 nar_tokai_demotion へ書く(便 tokai-demotion.yml)。

  出どころ= 主催者の一覧 PDF(番組賞金 P の列)
    笠松= https://www.kasamatsu-keiba.com/raceprogram の「出走投票準備一覧」(開催ごと)
    名古屋= https://www.nagoyakeiba.com/info/program/file/<年度>-<回>-<日>.pdf(出走馬編成一覧表・日ごと)
  式= nar-site/BACKTEST-demotion-tokai-20260926.md「再照合2」(scratchpad dm/a4.py の写し):
    Pt= 一覧の P + 一覧の日以後の収得、E= 前回の見直しの翌日から今回の見直しまでの一般格の収得、
    期間中に一般格で勝った or E > 0.25Pt なら控除なし、それ以外 P1= floor(0.75Pt + E)。P2= P1 − ceil(0.25P1)(以後の稼ぎ 0)。
    収得= nar_runs の 1〜5 着 × nar_races.prize_yen × 率(重賞は nar_graded_schedule の格で SPI 0.6・SPII/III 0.7・JpN 0.3・
    格が分からない重賞 0.6)を千円で切り捨て。2・3 歳限定戦(競走条件)は E と勝ちに数えない。
  見直しの日:
    笠松= 6・9・12・3 月の月末開催の後。公式(要綱 10(6)イ・お知らせ・番組)に日付の記載は無い(9/26 確認)。
      決め方の順= ① nar_meta 'tokai_adj_days'(一度決まった日は据え置き)② 一覧から特定(ks_detect_adj:
      同じ馬の続けて 2 つの一覧の日 a<b で P が減った組を数え、a<=c<b となる組が最多の一覧の日 c= 見直しの日。
      3・6・9・12 月の日だけ・組 20 以上かつ減った割合 20% 以上)→ --apply で nar_meta に保存
      ③ 設定値 ADJ_SET ④ 月が終わっていればその月の最後の開催日(nar_races)⑤ 月末。
    名古屋= 第 7・13・19・26 回の後(その回の最後の一覧の日。次の回の一覧が出ていなければ設定値)
    直近の見直しが一覧に反映済みか= 最新の一覧の開催が見直しの日より後に始まっていれば反映済み(日付で決める)。
    そうでなければ pending(発表待ち)として、見直し前の P から P1 を先に当てる。P が減った割合はログの参考値だけ。
  出すのは「今の一般格で P>=2500 かつ P1 か P2 で級が下がる見込み」の馬だけ(モックと同じ)。

  python cloud/tokai_demotion.py --dry-run [--out x.csv]   # 取得→解析→DB を読む→CSV だけ(書かない)
  python cloud/tokai_demotion.py --apply                   # upsert→同じ場の古い行を消す→heartbeat 'tokai_demotion'
  python cloud/tokai_demotion.py --probe                   # 走者から 2 サイトに届くかだけ
  python cloud/tokai_demotion.py --apply --if-raced-yesterday   # 前日に笠松・名古屋の開催が無ければ何もしない(exit 0)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常 / 1 投入失敗 / 2 取得・解析の失敗
"""
import argparse
import collections
import csv
import datetime as dt
import io
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
KS_PAGE = "https://www.kasamatsu-keiba.com/raceprogram"
KS_BASE = "https://www.kasamatsu-keiba.com"
NG_FILE = "https://www.nagoyakeiba.com/info/program/file/{fy}-{k}-{d}.pdf"
TABLE = "nar_tokai_demotion"
BEAT_JOB = "tokai_demotion"
JST = dt.timezone(dt.timedelta(hours=9))
TRACK = {"KS": "笠松", "NG": "名古屋"}
VENUE = {"KS": "kasamatsu", "NG": "nagoya"}
KS_MONTHS = (3, 6, 9, 12)
NG_MEETS = (7, 13, 19, 26)
# 設定値(見分けられないとき・月/回の途中)。笠松= 'YYYY-MM' → 見直しの日、名古屋= (年度, 回) → 見直しの日
ADJ_SET = {
    "KS": {"2025-12": "2025-12-31", "2026-03": "2026-03-20", "2026-06": "2026-06-26", "2026-09": "2026-09-25"},
    "NG": {(2025, 26): "2026-03-31", (2026, 7): "2026-07-03", (2026, 13): "2026-10-02"},
}
KS_DAYS_BACK = 200          # 笠松の一覧を取る範囲(日)= 見直し 2 回分
NG_MEETS_BACK = 8           # 名古屋の一覧を取る範囲(今の回から何回前まで)
LINE = {"A": 4500, "B": 2500, "C": 0}
RK = {"A": 3, "B": 2, "C": 1}
RATE = {"SPI": 0.6, "SPII": 0.7, "SPIII": 0.7, "JPNI": 0.3, "JPNII": 0.3, "JPNIII": 0.3}
META_KEY = "tokai_adj_days"   # nar_meta: {"KS": {"YYYY-MM": "YYYY-MM-DD"}, "src": {"YYYY-MM": "一覧" | "設定値"}}
DETECT_MIN_PAIRS = 20
DETECT_MIN_RATIO = 0.2
COLS = ["venue", "horse_name", "cls_now", "p_now", "earn", "won", "p1", "cls1", "p2", "cls2", "need_man", "pending", "asof"]


def log(*a):
    print(*a, flush=True)


def cls(P):
    return "A" if P >= 4500 else "B" if P >= 2500 else "C"


CIR = "".join(chr(c) for c in range(0x2460, 0x2474))


def N(s):
    return unicodedata.normalize("NFKC", "".join("#" if ch in CIR else ch for ch in (s or "")))


def NF(s):
    return unicodedata.normalize("NFKC", s or "").replace(" ", "")


# ---------- 取得 ----------
def http(url, head=False, timeout=40):
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, method="HEAD" if head else "GET",
                                         headers={"User-Agent": UA, "Accept-Language": "ja"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return b"" if head else r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"取得できない {url}: {type(last).__name__}: {str(last)[:120]}")


def ks_links(today):
    h = http(KS_PAGE).decode("utf-8", "replace")
    out = []
    for href, label in re.findall(r'href="(/resources/pdfs/raceprogram/[^"]+\.pdf)"[^>]*>\s*<p[^>]*>([^<]*)<', h):
        if "一覧" not in label:
            continue
        m = re.search(r"/(\d{10})_", href)
        d = dt.datetime.fromtimestamp(int(m.group(1)), JST).date() if m else None
        if d and (today - d).days <= KS_DAYS_BACK:
            out.append((d, KS_BASE + href))
    return sorted(set(out))


def fiscal(d):
    return d.year if d.month >= 4 else d.year - 1


def ng_urls(today):
    """(年度, 回, 日, url) の一覧。今年度の最後の回を HEAD で探し、そこから NG_MEETS_BACK 回前まで(前年度に跨ぐ分も)。"""
    fy = fiscal(today)
    kmax, miss, k = 0, 0, 1
    while k <= 30 and miss < 2:
        if http(NG_FILE.format(fy=fy, k=k, d=1), head=True) is None:
            miss += 1
        else:
            kmax, miss = k, 0
        k += 1
    want = [(fy, k) for k in range(max(1, kmax - NG_MEETS_BACK), kmax + 1)]
    if kmax - NG_MEETS_BACK < 1:
        want = [(fy - 1, k) for k in range(26 + (kmax - NG_MEETS_BACK), 27)] + want
    out = []
    for y, k in want:
        for d in range(1, 9):
            u = NG_FILE.format(fy=y, k=k, d=d)
            if http(u, head=True) is None:
                break
            out.append((y, k, d, u))
    return out


# ---------- 解析(dm/parse.py の写し) ----------
KANA = r"[゠-ヿA-Za-z]"
NAME = r"(%s[゠-ヿA-Za-z0-9・\.\']*)" % KANA
TR = r"([一-鿿々][一-鿿々ケヶ]*)"
HN = re.compile(r"(?:^|\s|\))(?:○|希\s*)*○?" + NAME + r"\s+(牡|牝|セ)\s*(\d+)\s+(?:[ABC]\s+)?([\d,]+|未出走)\s*" + TR)
HK = re.compile(r"(?:([ABC]\d+|\d+R希望)\s+)?" + NAME + r"\s+(?:(\d+)R\s+)?(?:#\s*)?(\d{1,5})\s*" + TR + r"(?:\s+(\d{2})(?!\d))?")


def rows_of(words, tol=3):
    rows = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0] - w["top"]) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([w["top"], [w]])
    return [(t, sorted(ws, key=lambda w: w["x0"])) for t, ws in rows]


def parse_ng(data, fy, k):
    import pdfplumber
    out = []
    for pg in pdfplumber.open(io.BytesIO(data)).pages:
        W = pg.width
        ws = pg.extract_words(keep_blank_chars=False)
        for w in ws:
            w["text"] = N(w["text"])
        full = N(pg.extract_text() or "")
        m = re.search(r"(\d{4})年\s*(\d+)月\s*(\d+)日", full)
        if not m:
            continue
        DATE = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
        bw = (W - 120) / 4
        bands = [[] for _ in range(4)]
        for w in ws:
            bands[min(3, max(0, int((w["x0"] - 58) // bw)))].append(w)
        block = None
        for b in range(4):
            for _, rw in rows_of(bands[b]):
                s = " ".join(w["text"] for w in rw)
                if re.search(r"レース\s+(\d+)(?:\+補(\d+))?$", s):
                    block = []
                    continue
                for g in re.findall(r"(3歳|2歳|[ABC])(\d*)[a-z]?組", s) + ([("3歳", "")] if re.search(r"\s3歳\s+\d\d:\d\d", s) else []):
                    if block is not None:
                        block.append(g[0] + g[1])
                for h in HN.finditer(s):
                    name, sex, age, P, tr = h.groups()
                    bl = "/".join(block) if block else ""
                    age = int(age)
                    rc = "3歳" if ("3歳" in bl and age == 3) else "2歳" if ("2歳" in bl and age == 2) else "G"
                    out.append(dict(trk="NG", meet=(fy, k), name=name, P=(-1 if P == "未出走" else int(P.replace(",", ""))),
                                    rc=rc, date=DATE))
    return out


def parse_ks(data, today):
    import pdfplumber
    pdf = pdfplumber.open(io.BytesIO(data))
    full0 = N(pdf.pages[0].extract_text() or "")
    mk = re.search(r"令和(\d)年度.*?第\s*(\d+)\s*回", full0, re.S)
    if not mk:
        return []
    reiwa = int(mk.group(1))
    out = []
    for pg in pdf.pages:
        ws = pg.extract_words()
        for w in ws:
            w["text"] = N(w["text"])
        full = N(pg.extract_text() or "")
        dm = re.search(r"第\d+日目\s*(\d+)月\s*(\d+)日", full)
        if not dm:
            continue
        mo = int(dm.group(1))
        yr = 2018 + reiwa + (1 if mo < 4 else 0)
        d = dt.date(yr, mo, int(dm.group(2)))
        if (d - today).days > 60:
            d = d.replace(year=d.year - 1)
        DATE = d.isoformat()
        xs = sorted(w["x0"] for w in ws if w["text"].startswith("サラ系"))
        cl = []
        for x in xs:
            if not cl or x - cl[-1][-1] > 40:
                cl.append([x])
            else:
                cl[-1].append(x)
        starts = [min(c) - 45 for c in cl] or [0]
        bands = [[] for _ in starts]
        for w in ws:
            b = max([i for i, s in enumerate(starts) if w["x0"] >= s - 15] or [0])
            bands[b].append(w)
        for b in range(len(starts)):
            rcls = None
            sub = None
            for _, rw in rows_of(bands[b]):
                s = " ".join(w["text"] for w in rw)
                m = re.search(r"サラ系(一般|3歳|2歳)\s+(.+?)\s+(\d{3,4})$", s)
                if m:
                    g = m.group(2).replace("特別", "").strip()
                    rcls = ("3歳" if m.group(1) == "3歳" else "2歳" if m.group(1) == "2歳" else g[0])
                    sub = None
                    continue
                if s.startswith("J ") or "補欠" in s:
                    continue
                for h in HK.finditer(s):
                    pre, name, rr, P, tr, wt = h.groups()
                    c = rcls
                    if pre and re.match(r"[ABC]\d+", pre):
                        sub = pre[0]
                    if sub and rcls not in ("3歳", "2歳"):
                        c = sub
                    out.append(dict(trk="KS", meet=("R%d" % reiwa, int(mk.group(2))), name=name, P=int(P),
                                    rc=(c if c in ("3歳", "2歳") else "G"), date=DATE))
    return out


# ---------- DB(読むだけ) ----------
def sb_all(url, key, path, page=1000):
    out, off = [], 0
    while True:
        req = urllib.request.Request(f"{url}/rest/v1/{path}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items",
            "Range": f"{off}-{off + page - 1}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read())
        out += got
        if len(got) < page:
            return out
        off += page


def q(s):
    return urllib.parse.quote(s)


def trk_in():
    return q(",".join(TRACK.values()))


def raced_yesterday(url, key, today):
    y = (today - dt.timedelta(days=1)).isoformat()
    got = sb_all(url, key, f"nar_races?select=race_date&track=in.({trk_in()})&race_date=eq.{y}&limit=1")
    return bool(got)


def ks_race_days(url, key, since):
    got = sb_all(url, key, f"nar_races?select=race_date&track=eq.{q('笠松')}&race_no=eq.1&race_date=gte.{since}&order=race_date")
    return sorted({g["race_date"][:10] for g in got})


def load_earn(url, key, names, since, until):
    """馬名 → [(date, e 千円, win, age_limited)]。東海 2 場の nar_runs(since < date <= until)。"""
    runs = []
    nm = sorted(names)
    for i in range(0, len(nm), 80):
        inq = q(",".join('"' + n + '"' for n in nm[i:i + 80]))
        runs += sb_all(url, key, f"nar_runs?select=track,race_date,race_no,horse_name,finish&horse_name=in.({inq})"
                                 f"&track=in.({trk_in()})&race_date=gt.{since}&race_date=lte.{until}"
                                 f"&order=race_date,track,race_no,horse_name")
    races = sb_all(url, key, f"nar_races?select=track,race_date,race_no,prize_yen,condition&track=in.({trk_in()})"
                             f"&race_date=gt.{since}&race_date=lte.{until}&order=race_date,track,race_no")
    graded = sb_all(url, key, f"nar_graded?select=track,race_date,race_no,race_name,race_kind&track=in.({trk_in()})"
                              f"&race_date=gt.{since}&race_date=lte.{until}&order=race_date,track,race_no")
    sched = sb_all(url, key, f"nar_graded_schedule?select=race_date,track,race_name,grade&track=in.({trk_in()})"
                             f"&race_date=gt.{since}&race_date=lte.{until}&order=race_date,track,race_name")
    R = {(r["track"], r["race_date"][:10], r["race_no"]): r for r in races}
    G = {(g["track"], g["race_date"][:10], g["race_no"]): g for g in graded}

    def rate(k):
        g = G.get(k)
        if not g:
            return 1.0
        for x in sched:
            if x["race_date"][:10] == k[1] and x["track"] == k[0] and NF(x["race_name"]) in NF(g["race_name"]):
                gr = NF(x.get("grade")).upper()
                if gr in RATE:
                    return RATE[gr]
        if NF(g.get("race_kind")) == "重賞":
            return 1.0
        return 0.6

    out = collections.defaultdict(list)
    for x in runs:
        k = (x["track"], x["race_date"][:10], x["race_no"])
        r = R.get(k) or {}
        f = x.get("finish")
        pz = r.get("prize_yen") or []
        e = int(pz[f - 1] * rate(k)) // 1000 if (f and 1 <= f <= 5 and f <= len(pz) and pz[f - 1]) else 0
        agel = bool(re.search(r"系(2歳|3歳)(?!以上)", NF(r.get("condition"))))
        out[NF(x["horse_name"])].append((k[1], e, f == 1, agel))
    return out


# ---------- 見直しの日 ----------
def ks_detect_adj(rows):
    """一覧の行から笠松の見直しの日を特定する → {'YYYY-MM': 'YYYY-MM-DD'}。
    同じ馬の続けて 2 つの一覧の日 (a, b) で一般格だった馬の P が減った組を数え、a <= c < b となる組が
    最多の一覧の日 c(3・6・9・12 月の日だけ・同数なら遅い日)をその月の見直しの日とする。
    減った組が DETECT_MIN_PAIRS 以上かつ c をまたぐ組のうち減った割合が DETECT_MIN_RATIO 以上のときだけ。"""
    tl = collections.defaultdict(dict)
    for r in rows:
        if r["P"] >= 0:
            tl[r["name"]][r["date"]] = r
    dec, allp = [], []
    for d in tl.values():
        ts = sorted(d)
        for a, b in zip(ts, ts[1:]):
            if d[a]["rc"] != "G" or d[a]["P"] <= 0:
                continue
            allp.append((a, b))
            if d[b]["P"] < d[a]["P"]:
                dec.append((a, b))
    days = sorted({r["date"] for r in rows})
    best = {}
    for c in days:
        if int(c[5:7]) not in KS_MONTHS:
            continue
        k = sum(1 for a, b in dec if a <= c < b)
        n = sum(1 for a, b in allp if a <= c < b)
        ym = c[:7]
        if k and (ym not in best or (k, c) >= best[ym][:2]):
            best[ym] = (k, c, n)
    out = {}
    for ym, (k, c, n) in sorted(best.items()):
        if k >= DETECT_MIN_PAIRS and n and k / n >= DETECT_MIN_RATIO:
            out[ym] = c
            log(f"笠松: 一覧から見直しの日 {c}(減った組 {k}/{n})")
    return out


def load_adj_meta(url, key):
    if not (url and key):
        return {}
    got = sb_all(url, key, f"nar_meta?select=value&key=eq.{META_KEY}")
    v = got[0]["value"] if got and isinstance(got[0].get("value"), dict) else {}
    return v


def save_adj_meta(url, key, value):
    from load_nar_official import upsert
    st, msg = upsert(url, key, "nar_meta", "key", [{
        "key": META_KEY, "value": value, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}])
    if st >= 300:
        raise RuntimeError(f"nar_meta upsert {st} {msg}")


def ks_known_adj(meta, detected):
    """nar_meta の日(据え置き)+ 一覧から新しく特定した月。→ (known, 新しい meta か None)"""
    known = dict((meta or {}).get("KS") or {})
    src = dict((meta or {}).get("src") or {})
    new = False
    for ym, d in detected.items():
        if ym not in known:
            known[ym], src[ym], new = d, "一覧", True
        elif known[ym] != d:
            log(f"::warning::笠松 {ym}: nar_meta の見直しの日 {known[ym]} と一覧から特定した日 {d} が違う(nar_meta を使う)")
    return known, ({"KS": known, "src": src} if new else None)


def ks_candidates(today, race_days, known=None):
    """[(date, passed)] 古い順。① 特定済み(nar_meta/一覧)② 設定値 ③ 月が終わっていれば最後の開催日 ④ 月末。"""
    known = known or {}
    out = []
    for y in (today.year - 1, today.year, today.year + 1):
        for m in KS_MONTHS:
            ym = "%d-%02d" % (y, m)
            end = (dt.date(y, m, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            days = [d for d in race_days if d.startswith(ym)]
            if ym in known:
                s = known[ym]
            elif ym in ADJ_SET["KS"]:
                s = ADJ_SET["KS"][ym]
            elif end < today and days:
                s = days[-1]
            else:
                s = end.isoformat()
            out.append((s, s < today.isoformat()))
    return sorted(set(out))


def ng_race_days(url, key, since):
    got = sb_all(url, key, f"nar_races?select=race_date&track=eq.{q('名古屋')}&race_no=eq.1&race_date=gte.{since}&order=race_date")
    return {g["race_date"][:10] for g in got}


def ng_candidates(today, lists, race_days=None):
    """lists= 解析した名古屋の行。回の最後の一覧の日(次の回の一覧が出ていれば確定)/設定値。"""
    last = collections.defaultdict(str)
    for r in lists:
        if race_days is None or r["date"] in race_days:
            last[r["meet"]] = max(last[r["meet"]], r["date"])
    out = []
    fy = fiscal(today)
    for y in (fy - 1, fy, fy + 1):
        for k in NG_MEETS:
            nxt = (y, k + 1) if k < 26 else (y + 1, 1)
            if last.get((y, k)) and any(m >= nxt for m in last):
                out.append((last[(y, k)], True))
            elif (y, k) in ADJ_SET["NG"]:
                s = ADJ_SET["NG"][(y, k)]
                out.append((s, s < today.isoformat()))
            elif last.get((y, k)):
                out.append((last[(y, k)], last[(y, k)] < today.isoformat()))
            else:
                s = "%d-%s" % (y + (1 if k == 26 else 0), {7: "07-01", 13: "10-01", 19: "12-31", 26: "03-31"}[k])
                out.append((s, s < today.isoformat()))
    return sorted(set(out))


def published(tl, D):
    """見直し D をまたぐ同じ馬の一覧の組のうち P が減った割合。組が無ければ None。"""
    n = dn = 0
    for d in tl.values():
        a = [t for t in d if t <= D]
        b = [t for t in d if t > D]
        if not a or not b:
            continue
        pa, pb = d[max(a)], d[min(b)]
        if pa["rc"] != "G" or pa["P"] <= 0:
            continue
        n += 1
        dn += pb["P"] < pa["P"]
    return (dn / n if n else None), n


# ---------- 式 ----------
def forecast(trk, lists, cands, today, url, key):
    tl = collections.defaultdict(dict)
    for r in lists:
        if r["P"] >= 0:
            tl[r["name"]][r["date"]] = r
    passed = [c for c, p in cands if p]
    future = [c for c, p in cands if not p]
    Cl = passed[-1]
    ratio, npair = published(tl, Cl)   # 参考値(ログだけ)
    # 反映済みか= 最新の一覧の開催(同じ meet の最初の日)が見直しの日より後に始まっているか
    start = {}
    for r in lists:
        start[r["meet"]] = min(start.get(r["meet"], r["date"]), r["date"])
    last_meet = max(lists, key=lambda r: r["date"])["meet"]
    pending = not (start[last_meet] > Cl)
    if pending:
        st, D, D2 = passed[-2], Cl, future[0]
    else:
        st, D, D2 = Cl, future[0], (future[1] if len(future) > 1 else None)
    log(f"{TRACK[trk]}: 直近の見直し {Cl}(またぐ組 {npair}・減った割合 {ratio if ratio is None else round(ratio, 2)})"
        f"・最新の一覧の開催 {last_meet} は {start[last_meet]} 始まり→ {'発表待ち' if pending else '反映済み'}・期間 {st}〜{D}・その次 {D2}")
    until = min(D, today.isoformat())
    cand = {}
    for n, d in tl.items():
        pre = [t for t in sorted(d) if st < t <= D]
        if not pre:
            continue
        lp = d[pre[-1]]
        if lp["rc"] != "G" or lp["P"] < 2500:
            continue
        cand[n] = lp
    ern = load_earn(url, key, set(cand), st, until) if (url and key and cand) else {}
    out = []
    for n, lp in cand.items():
        P = lp["P"]
        runs = ern.get(NF(n), [])
        after = sum(e for t, e, w, a in runs if t >= lp["date"])
        E = sum(e for t, e, w, a in runs if not a)
        wn = any(w and not a for t, e, w, a in runs)
        Pt = P + after
        P1 = Pt if (wn or E > 0.25 * Pt) else math.floor(0.75 * Pt + E)
        P2 = P1 - math.ceil(0.25 * P1)
        c0, c1, c2 = cls(P), cls(P1), cls(P2)
        if not (RK[c1] < RK[c0] or RK[c2] < RK[c1]):
            continue
        if pending:
            need = max(0, math.ceil((LINE[c1] - math.floor(0.75 * P1)) / 10)) if RK[c2] < RK[c1] else None
        elif RK[c1] < RK[c0]:
            need = max(0, math.ceil((LINE[c0] - P1) / 10))
        else:
            need = max(0, math.ceil((LINE[c1] - math.floor(0.75 * P1)) / 10))
        out.append(dict(venue=VENUE[trk], horse_name=n, cls_now=c0, p_now=P, earn=E, won=wn, p1=P1, cls1=c1,
                         p2=P2, cls2=c2, need_man=need, pending=pending))
    return out, dict(adj=Cl, pending=pending, st=st, D=D, D2=D2)


# ---------- 書く ----------
def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in COLS})


def apply_rows(url, key, venue, rows, asof):
    from load_nar_official import upsert
    if rows:
        st, msg = upsert(url, key, TABLE, "venue,horse_name", rows)
        if st >= 300:
            raise RuntimeError(f"upsert {st} {msg}")
    path = f"{TABLE}?venue=eq.{venue}&asof=lt.{q(asof)}"
    req = urllib.request.Request(f"{url}/rest/v1/{path}", method="DELETE", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=60):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--if-raced-yesterday", action="store_true")
    ap.add_argument("--out", help="CSV の出力先")
    ap.add_argument("--today", help="基準日(試し用 YYYY-MM-DD)")
    a = ap.parse_args()
    apply_ = a.apply and not a.dry_run
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    import beat as B

    def say(ok, note):
        if apply_:
            B.beat(BEAT_JOB, ok, note)
        log(f"heartbeat {BEAT_JOB} {'ok' if ok else 'fail'} {note}" + ("" if apply_ else "(ドライラン= 書かない)"))

    if a.probe:
        ks = ks_links(today)
        ng = http(NG_FILE.format(fy=fiscal(today), k=1, d=1), head=True)
        log(f"probe 笠松 一覧 {len(ks)} 件・名古屋 {'ok' if ng is not None else 'なし'}")
        return 0 if ks and ng is not None else 2
    if a.if_raced_yesterday and url and key and not raced_yesterday(url, key, today):
        log("前日に笠松・名古屋の開催なし= 何もしない")
        return 0
    try:
        ks_rows = []
        for d, u in ks_links(today):
            ks_rows += parse_ks(http(u), today)
        ng_rows = []
        for y, k, d, u in ng_urls(today):
            ng_rows += parse_ng(http(u), y, k)
        if not ks_rows or not ng_rows:
            raise ValueError(f"一覧の行が 0(笠松 {len(ks_rows)}・名古屋 {len(ng_rows)})")
    except Exception as e:
        log(f"::error::一覧を取得・解析できない: {e}")
        say(False, f"取得失敗 {str(e)[:80]}")
        return 2
    log(f"一覧の行= 笠松 {len(ks_rows)}・名古屋 {len(ng_rows)}")
    # 所属= 両場の一覧に出た回数の多い方(dm/a2.py)
    cnt = collections.Counter((r["name"], r["trk"]) for r in ks_rows + ng_rows)
    home = lambda n, t: cnt[(n, t)] > cnt[(n, "NG" if t == "KS" else "KS")]
    asof = dt.datetime.now(JST).isoformat(timespec="seconds")
    try:
        race_days = ks_race_days(url, key, (today - dt.timedelta(days=400)).isoformat()) if (url and key) else []
        known, new_meta = ks_known_adj(load_adj_meta(url, key), ks_detect_adj(ks_rows))
        allrows, meta = [], {}
        for trk, lists, cands in (("KS", ks_rows, ks_candidates(today, race_days, known)), ("NG", ng_rows, ng_candidates(today, ng_rows, ng_race_days(url, key, (today - dt.timedelta(days=400)).isoformat()) if (url and key) else None))):
            lists = [r for r in lists if home(r["name"], trk)]
            rows, m = forecast(trk, lists, cands, today, url, key)
            for r in rows:
                r["asof"] = asof
            allrows += rows
            meta[trk] = (len(rows), m)
            log(f"{TRACK[trk]}: 見込みの行 {len(rows)}")
    except Exception as e:
        log(f"::error::式の計算に失敗: {type(e).__name__}: {e}")
        say(False, f"計算失敗 {str(e)[:80]}")
        return 2
    out = a.out or f"tokai_demotion_{today.isoformat()}.csv"
    write_csv(out, allrows)
    log(f"CSV= {out}")
    if not apply_:
        return 0
    try:
        if new_meta:
            save_adj_meta(url, key, new_meta)
            log(f"nar_meta/{META_KEY} 更新 {new_meta['KS']}")
        for trk in ("KS", "NG"):
            apply_rows(url, key, VENUE[trk], [r for r in allrows if r["venue"] == VENUE[trk]], asof)
    except Exception as e:
        log(f"::error::投入失敗: {e}")
        say(False, "投入失敗")
        return 1
    say(True, " ".join(f"{TRACK[t]}={meta[t][0]}{'(発表待ち)' if meta[t][1]['pending'] else ''}" for t in ("KS", "NG")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
