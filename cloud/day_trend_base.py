# -*- coding: utf-8 -*-
"""今日ここまでの傾向 段 3「ふだんの値」を場×月ごとに作る月 1 回の便(2026-10-09)。

受け渡しの形の正本= nar-site\\SPEC_day_trend_base_20261009.md・仕様の正本= DESIGN_today_trend_20260928.md §0・§1-6。
数え方の元= nar-site\\research\\today-trend\\mock_v3.py(写した。10/9 訂正= 枠は整数の [頭数, 3着内]・n<30 の枠は書かない・L3 は pre で広げる)。

  py -3.12 -X utf8 cloud/day_trend_base.py --month 2026-10 --venue kochi --dry-run --out out/
  python3 cloud/day_trend_base.py --month 2026-09,2026-10 --apply      # nar_meta へ upsert

置き場= nar_meta key `day_trend_base:<場の URL 名>:<YYYY-MM>`(列は足さない)。
期間= その月の 1 日より前の 5 年。場の変化(/sand の履歴 §301 の「全部入れ替え」「下地の工事」・名古屋の移転 2022-04-08)の
後だけを使う。変化の後が 300R 未満なら 1 つ前の区切りの後まで広げ、それでも届かなければ 5 年。名古屋は 2022-04-08 より前を入れない。
⛔本番 DB では REST の単純 select だけ(場×月ごと・offset は一意の order・filter 値は全部符号化)。集計は全部この中。
⛔標準ライブラリだけ。環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--env でファイルからも読める)
"""
import argparse
import calendar
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baba  # noqa: E402  band_of・load_env だけ使う(⛔baba の関数の動きは変えない)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = "nar-jobs/1.0"
JST = dt.timezone(dt.timedelta(hours=9))
META_PREFIX = "day_trend_base"
BANEI = "帯広ば"
NAG, NAG_BOUNDARY = "名古屋", "2022-04-08"
NAG_CUT = {"raw": NAG_BOUNDARY, "text": "名古屋競馬場の移転(弥富)"}
VKEY = {"門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "浦和": "urawa", "船橋": "funabashi",
        "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa", "笠松": "kasamatsu", "名古屋": "nagoya",
        "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga", BANEI: "obihiro"}
CUT_TYPES = ("全部入れ替え", "下地の工事")
POST_MIN = 300                 # 区切りの後がこれ未満なら 1 つ前の区切りへ
YEARS = 5
GOINGS = {"良", "稍重", "重", "不良"}
L3_OK = (30.0, 55.0)           # 上がりの有効範囲(秒)・0.0= 公式の非計測は落ちる
ZONES = ("front", "mid", "back")
POP_BANDS = ("1", "2-3", "4-6", "7+")
SAND_URL = "https://yukochi.com/data/sand-history.json"
CN = re.compile(r"([１２３４1234])(?:角|コーナー)")
DIG = {"１": "1", "２": "2", "３": "3", "４": "4", "1": "1", "2": "2", "3": "3", "4": "4"}


def log(msg):
    print(msg, flush=True)


# ─── クラス帯(baba.band_of を包む・§1-6 の直し 1 つ)────────────────────────
def band_fix(race_name, condition=None, track=None):
    """名前か条件に「歳以上」があってクラス字が無い(baba が None/3y)レース= "上"。ほかは baba.band_of(name, track) のまま"""
    b = baba.band_of(race_name, track)
    if "歳以上" in (str(race_name or "") + str(condition or "")) and b in (None, "3y"):
        return "上"
    return b


# ─── 通過順(viewer js/data.js cornerRanks の写し・research と同じ)──────────────
def corner_ranks(order):
    s = str(order if order is not None else "").strip()
    if not s:
        return None
    out, rank, i = {}, 1, 0
    while i < len(s):
        ch = s[i]
        if ch in (",", "-", "=", " ", "　"):
            i += 1
            continue
        if ch == "(":
            end = s.find(")", i)
            if end < 0:
                return None
            nums = []
            for x in s[i + 1:end].split(","):
                x = x.strip()
                if not re.fullmatch(r"\d+", x) or int(x) <= 0:
                    return None
                nums.append(int(x))
            if not nums:
                return None
            for n in nums:
                out.setdefault(n, rank)
            rank += len(nums)
            i = end + 1
            continue
        m = re.match(r"\d+", s[i:])
        if not m:
            return None
        n = int(m.group(0))
        out.setdefault(n, rank)
        rank += 1
        i += len(m.group(0))
    return out or None


def corner_points(corners):
    """{"1".."4": {馬番: 番手}}。角は名前の数字・2 周は後(ゴールに近い方)で上書き"""
    cs = corners
    if isinstance(cs, str):
        try:
            cs = json.loads(cs) if cs.strip() else []
        except Exception:
            cs = []
    if not isinstance(cs, list):
        return {}
    pts = {}
    for c in cs:
        if not isinstance(c, dict):
            continue
        m = CN.search(str(c.get("name") or ""))
        rk = corner_ranks(c.get("order"))
        if m and rk:
            pts[DIG[m.group(1)]] = rk
    return pts


def toint(v):
    try:
        return int(float(v))
    except Exception:
        return None


def zone(rk):
    return 0 if rk <= 3 else 1 if rk <= 6 else 2


def pbk(p):
    return None if p is None else "1" if p == 1 else "2-3" if p <= 3 else "4-6" if p <= 6 else "7+"


def rerank(vals):
    """出走馬の人気を付け直す(同じ値は同じ順位= 1,2,2,4)"""
    xs = sorted(v for v in vals.values() if v is not None)
    return {k: (None if v is None else 1 + sum(1 for u in xs if u < v)) for k, v in vals.items()}


def moist_bucket(g):
    try:
        v = float(g)
    except Exception:
        return None
    return "〜0.9" if v < 1.0 else "1.0〜1.9" if v < 2.0 else "2.0〜2.9" if v < 3.0 else "3.0〜"


def dist_key(race):
    """画面の distKey(r)= surface の値そのまま+距離の数字"""
    d = race.get("distance_m")
    return f"{race.get('surface') or ''}{int(float(d)) if d not in (None, '') else ''}"


def is_cancelled(v):
    return v not in (None, "", False, "False", "false")


# ─── 1 レースの値 ──────────────────────────────────────────────────
def race_record(race, runs):
    """数えるレースの値。数えない(中止・着順なし・名古屋の移転前)なら None"""
    t, d = race["track"], race["race_date"]
    if t == NAG and d < NAG_BOUNDARY:
        return None
    if is_cancelled(race.get("cancelled")) or not runs:
        return None
    ent = []
    for x in runs:
        note = x.get("finish_note") or ""
        if "取消" in note or "除外" in note:
            continue
        f = toint(x.get("finish"))
        if "失格" in note or "中止" in note:
            f = None
        try:
            l3 = float(x.get("last3f"))
            l3 = l3 if L3_OK[0] <= l3 <= L3_OK[1] else None
        except Exception:
            l3 = None
        ent.append([toint(x.get("runner_number")), f, l3, toint(x.get("popularity"))])
    if not any(e[1] is not None for e in ent):
        return None
    rp = rerank({e[0]: e[3] for e in ent})
    for e in ent:
        e[3] = rp[e[0]]
    top3 = lambda f: f is not None and 1 <= f <= 3  # noqa: E731
    rec = {"d": d, "no": int(race["race_no"]), "dk": dist_key(race),
           "band": band_fix(race.get("race_name"), race.get("condition"), t)}
    # 人気帯ごとの [頭数, 3着内](10/9 訂正= 頭数あたりの率の元・mock_v3.py と同じ)
    rec["pop"] = [[sum(1 for e in ent if pbk(e[3]) == b), sum(1 for e in ent if pbk(e[3]) == b and top3(e[1]))]
                  for b in POP_BANDS]
    if t == BANEI:
        rec["going"] = moist_bucket(race.get("going"))
        return rec
    g = race.get("going")
    rec["going"] = g if g in GOINGS else None
    pts = corner_points(race.get("corners"))
    cz = {}
    for c, mp in pts.items():
        v = [[0, 0], [0, 0], [0, 0]]          # 前・中・後ろの [頭数, 3着内]
        for num, f, _, _ in ent:
            if num in mp:
                z = v[zone(mp[num])]
                z[0] += 1
                z[1] += top3(f)
        cz[c] = v
    rec["cz"] = cz
    # 上がりの差= 後ろ(4角7番手以下・4角の頭数 8 以下は最後の 3 頭)の平均 − 前(4角1〜3番手)の平均
    rec["ag"] = None
    mp4 = pts.get("4")
    if mp4:
        rks = {e[0]: mp4[e[0]] for e in ent if e[0] in mp4}
        n4 = len(rks)
        if n4 >= 6:
            cut = min(7, n4 - 2)
            fr = [e[2] for e in ent if e[0] in rks and rks[e[0]] <= 3 and e[1] is not None and e[2] is not None]
            bk = [e[2] for e in ent if e[0] in rks and rks[e[0]] >= cut and e[1] is not None and e[2] is not None]
            if len(fr) >= 2 and len(bk) >= 2:
                rec["ag"] = sum(bk) / len(bk) - sum(fr) / len(fr)
    return rec


def cell_keys(rec):
    """L0→L3 の鍵。馬場が無ければ L2 から・クラス帯が無ければ L1 から"""
    ks = [f"L0|{rec['band']}|{rec['going']}|{rec['dk']}", f"L1|{rec['going']}|{rec['dk']}", f"L2|{rec['dk']}", "L3"]
    start = 2 if rec["going"] is None else 1 if rec["band"] is None else 0
    return ks[start:]


# ─── 枠の集計(10/9 訂正= 整数の [頭数, 3着内] を持つ・率は画面で割る)──────────────
MIN_N = 30          # 枠の R 数がこれ未満は書かない(L3 は例外= pre で広げる)


def cell_of(recs, banei=False, pre=False):
    """レースの束 → 1 枠。角が無いレースはその角に入れない・agari= [R数, 平均, 分散(標本)]"""
    out = {"n": len(recs), "pre": pre}
    pop = [[0, 0] for _ in POP_BANDS]
    cor, ag = {}, []
    for r in recs:
        for i, (h, w) in enumerate(r["pop"]):
            pop[i][0] += h
            pop[i][1] += w
        if banei:
            continue
        for c, v in r["cz"].items():
            cc = cor.setdefault(c, [[0, 0], [0, 0], [0, 0]])
            for zi in range(3):
                cc[zi][0] += v[zi][0]
                cc[zi][1] += v[zi][1]
        if r["ag"] is not None:
            ag.append(r["ag"])
    if not banei:
        out["corners"] = {c: cor[c] for c in sorted(cor)}
    out["pop"] = pop
    if not banei and ag:
        mu = sum(ag) / len(ag)
        var = sum((a - mu) ** 2 for a in ag) / (len(ag) - 1) if len(ag) > 1 else 0.0
        out["agari"] = [len(ag), round(mu, 4), round(var, 4)]
    return out


def build_cells(recs, banei=False, before=None):
    """recs= 期間の中のレース(日付順)。before= 期間より前のレース(L3 の pre 用・日付順)"""
    groups = {}
    for r in recs:
        for k in cell_keys(r):
            groups.setdefault(k, []).append(r)
    cells = {}
    for k in sorted(groups):
        if k != "L3" and len(groups[k]) >= MIN_N:
            cells[k] = cell_of(groups[k], banei)
    l3 = list(recs)
    pre = False
    if len(l3) < MIN_N and before:
        l3 = (list(before) + l3)[-MIN_N:]        # 区切りの前へ新しい順に広げて 30R
        pre = True
    if l3:
        cells["L3"] = cell_of(l3, banei, pre)
    return cells


# ─── 期間(場の変化で区切る)──────────────────────────────────────────
def month_end(y, m):
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def cut_from(raw):
    """/sand の raw の期間の終わりの翌日。終わりが無い(「〜」で終わる)なら始めの日から(mock_v3.py の写し)"""
    s = str(raw).split("(")[0].strip()
    a, sep, b = s.partition("〜")
    m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", a)
    y, mo = int(m.group(1)), int(m.group(2))
    dd = int(m.group(3)) if m.group(3) and m.group(3) != "00" else None
    b = b.strip()
    if sep and not b:
        return dt.date(y, mo, dd or 1)
    if not sep:
        end = dt.date(y, mo, dd) if dd else month_end(y, mo)
    else:
        m4 = re.match(r"(\d{4})-(\d{2})-(\d{2})$", b)
        m2 = re.match(r"(\d{2})-(\d{2})$", b)
        m1 = re.match(r"(\d{1,2})$", b)
        if m4:
            end = dt.date(int(m4.group(1)), int(m4.group(2)), int(m4.group(3)))
        elif m2:
            end = dt.date(y + (int(m2.group(1)) < mo), int(m2.group(1)), int(m2.group(2)))
        elif m1 and dd:
            end = dt.date(y, mo, int(m1.group(1)))
        elif m1:
            em = int(m1.group(1))
            end = month_end(y + (em < mo), em)
        else:
            raise ValueError(raw)
    return end + dt.timedelta(days=1)


def minus_years(d, years=YEARS):
    y = dt.date.fromisoformat(d)
    try:
        return y.replace(year=y.year - years).isoformat()
    except ValueError:
        return y.replace(year=y.year - years, day=28).isoformat()


def cuts_of(track, sand):
    """[(区切りの日, {"raw","text"})](古い順)。名古屋は移転の日を足す"""
    out = {}
    for e in (sand.get("venues") or {}).get(VKEY[track], []):
        if any(x in CUT_TYPES for x in (e.get("types") or [])):
            out[cut_from(e["raw"]).isoformat()] = {"raw": e["raw"], "text": e.get("text")}
    if track == NAG:
        out.setdefault(NAG_BOUNDARY, NAG_CUT)
    return sorted(out.items())


def window_of(track, mf, dates, sand):
    """mf= その月の 1 日(ISO)。dates= 数えるレースの日(mf より前)。→ (from, cut, note, post)"""
    d5 = minus_years(mf)
    cuts = [(cf, c) for cf, c in cuts_of(track, sand) if cf < mf]
    after = [(cf, c) for cf, c in cuts if cf > d5]
    if not after:
        w0, cut, note, post = d5, None, None, None
    else:
        w0, cut = after[-1]
        post = sum(1 for d in dates if d >= w0)
        note = None
        if post < POST_MIN:
            nw = d5
            for cf, _ in reversed(after[:-1]):
                if sum(1 for d in dates if d >= cf) >= POST_MIN:
                    nw = cf
                    break
            note = f"{cut['raw']} の改修の後は {post}R のため {nw} 以降を使う"
            w0 = nw
    if track == NAG and w0 < NAG_BOUNDARY:
        w0 = NAG_BOUNDARY
    return w0, cut, note, post


def build_value(track, month, recs, sand, built_at):
    """recs= その場の数えるレース(日付の制限なし)→ SPEC の value"""
    mf = f"{month}-01"
    prior = [r for r in recs if r["d"] < mf]
    w0, cut, note, post = window_of(track, mf, [r["d"] for r in prior], sand)
    use = [r for r in prior if r["d"] >= w0]
    before = sorted((r for r in prior if r["d"] < w0), key=lambda r: (r["d"], r["no"]))
    use.sort(key=lambda r: (r["d"], r["no"]))
    to = (dt.date.fromisoformat(mf) - dt.timedelta(days=1)).isoformat()
    banei = track == BANEI
    return {"venue": VKEY[track], "month": month, "built_at": built_at, "banei": banei,
            "window": {"from": w0, "to": to, "post_races": post, "cut": cut, "note": note},
            "cells": build_cells(use, banei=banei, before=before)}


# ─── 取得(REST の単純 select だけ)──────────────────────────────────────
def req(base, key, path, method="GET", body=None):
    r = urllib.request.Request(base + path, method=method, data=body, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(r, timeout=90) as x:
        return x.status, x.read().decode("utf-8")


def q(v):
    return urllib.parse.quote(str(v), safe="")


def rows_all(base, key, path, tries=4, wait=5):
    out, off = [], 0
    while True:
        for k in range(tries):
            try:
                _, body = req(base, key, f"{path}&limit=1000&offset={off}")
                break
            except Exception as e:  # noqa: BLE001
                if k == tries - 1:
                    raise
                log(f"  取得の再試行 {k + 1}/{tries - 1}(offset={off}): {e}")
                time.sleep(wait * (2 ** k))
        c = json.loads(body)
        out.extend(c)
        time.sleep(0.2)
        if len(c) < 1000:
            return out
        off += 1000


RACE_COLS = "track,race_date,race_no,race_name,condition,surface,distance_m,going,corners,cancelled"
RUN_COLS = "track,race_date,race_no,runner_number,finish,finish_note,popularity,last3f"


def months_between(d0, d1):
    y, m = int(d0[:4]), int(d0[5:7])
    while f"{y:04d}-{m:02d}" <= d1[:7]:
        a = max(d0, f"{y:04d}-{m:02d}-01")
        b = min(d1, month_end(y, m).isoformat())
        yield a, b
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch(base, key, d0, d1, tracks):
    """[d0, d1] の races と runs を場×月ごとに引き、場ごとの数えるレースにする"""
    recs = {t: [] for t in tracks}
    for t in tracks:
        nr = nn = 0
        for a, b in months_between(d0, d1):
            f = f"&track=eq.{q(t)}&race_date=gte.{q(a)}&race_date=lte.{q(b)}"
            races = rows_all(base, key, f"/rest/v1/nar_races?select={RACE_COLS}{f}"
                                        "&order=race_date.asc,race_no.asc")
            runs = rows_all(base, key, f"/rest/v1/nar_runs?select={RUN_COLS}{f}"
                                       "&order=race_date.asc,race_no.asc,runner_number.asc")
            by = {}
            for x in runs:
                by.setdefault((x["race_date"], int(x["race_no"])), []).append(x)
            for r in races:
                rec = race_record(r, by.get((r["race_date"], int(r["race_no"]))))
                if rec:
                    recs[t].append(rec)
            nr += len(races)
            nn += len(runs)
        log(f"{t}: レース {nr} / 出走 {nn} / 数える {len(recs[t])}")
    return recs


def load_sand(src):
    if re.match(r"https?://", src):
        r = urllib.request.Request(src, headers={"User-Agent": UA})
        with urllib.request.urlopen(r, timeout=60) as x:
            return json.loads(x.read().decode("utf-8"))
    with open(src, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="", help="YYYY-MM(カンマで複数)。空= JST の今月")
    ap.add_argument("--venue", default="", help="場の URL 名か場名(カンマで複数)。空= 全 15 場")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="JSON をファイルに出すだけ")
    g.add_argument("--apply", action="store_true", help="nar_meta へ upsert")
    ap.add_argument("--out", default="day_trend_base_out", help="--dry-run の出し先")
    ap.add_argument("--sand", default=SAND_URL, help="/sand の履歴(URL かファイル)")
    ap.add_argument("--env")
    a = ap.parse_args(argv)
    if a.env:
        baba.load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    now = dt.datetime.now(JST)
    months = sorted({m.strip() for m in a.month.split(",") if m.strip()} or {now.strftime("%Y-%m")})
    for m in months:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m):
            log(f"月の形が違う: {m}")
            return 2
    inv = {v: k for k, v in VKEY.items()}
    if a.venue.strip():
        tracks = []
        for v in a.venue.split(","):
            v = v.strip()
            t = inv.get(v) or (v if v in VKEY else None)
            if not t:
                log(f"場が分からない: {v}")
                return 2
            tracks.append(t)
    else:
        tracks = list(VKEY)
    sand = load_sand(a.sand)
    d0 = minus_years(f"{months[0]}-01")
    d1 = (dt.date.fromisoformat(f"{months[-1]}-01") - dt.timedelta(days=1)).isoformat()
    log(f"月 {months} / 場 {len(tracks)} / 読む期間 {d0}〜{d1}")
    recs = fetch(base, key, d0, d1, tracks)
    built_at = now.replace(microsecond=0).isoformat()
    rows = []
    for t in tracks:
        for m in months:
            v = build_value(t, m, recs[t], sand, built_at)
            s = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            w = v["window"]
            log(f"{t} {m}: 枠 {len(v['cells'])}・{len(s.encode('utf-8')) / 1024:.1f}KB・期間 {w['from']}〜{w['to']}"
                + (f"・{w['note']}" if w["note"] else ""))
            rows.append((f"{META_PREFIX}:{VKEY[t]}:{m}", v, s))
    if a.dry_run:
        os.makedirs(a.out, exist_ok=True)
        for k, _, s in rows:
            with open(os.path.join(a.out, k.replace(":", "_") + ".json"), "w", encoding="utf-8") as f:
                f.write(s)
        log(f"ドライラン= {len(rows)} 本を {a.out} に出した(本番に書かない)")
        return 0
    up = dt.datetime.now(dt.timezone.utc).isoformat()
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": k, "value": v, "updated_at": up} for k, v, _ in rows],
                           ensure_ascii=False).encode("utf-8"))
    log(f"nar_meta {len(rows)} 本 upsert {st}")
    return 0 if st in (200, 201, 204) else 1


if __name__ == "__main__":
    sys.exit(main())
