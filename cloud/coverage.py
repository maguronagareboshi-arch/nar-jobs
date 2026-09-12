#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本体 cloud: 「データの状態」= 取り込めたかを毎朝、行数で見る(DESIGN §118・#487 の反省)。

job が success かではなく **行が入ったか** を、データの種類 × 場ごとに数えて nar_meta `coverage` に 1 枚で書く。
/status(閲覧者向け「データの状態」)がこれを読む。管理者向けの「止まっている行」も同じ 1 枚から出す。

  出力 = nar_meta key='coverage' の value:
    {"built": "2026-09-06T09:31+09:00", "today": "2026-09-06",
     "rows": [{"kind": "results", "venue": "ooi", "expected": 5, "have": 5, "last": "2026-09-04",
               "missing": [], "stale_days": 2, "warn_after": 3, "note": "…", "src": "nar"}, …]}
  kind = results(確定結果)/ entries(出馬表)/ odds(当日オッズ)/ sales(売上・払戻)/ noken(能力検査)/
         health(疾病・競走事故の読み取り)/ organizer(主催者公式の記事)/ penalties(制裁)/ auction(オークション)/
         stats(集計の作られた日)
  expected は「主催者の開催日程(nar_meta kaisai_schedule)から数えた日」。数えられない種類は null。
  ⛔価値判断はしない= 数と日付だけ。色や「遅い/悪い」の語は画面にも出さない。

  py -3.12 -X utf8 cloud/coverage.py --env pipeline/.env.nar              # ドライラン(既定)= 表を出すだけ
  py -3.12 -X utf8 cloud/coverage.py --env pipeline/.env.nar --apply      # nar_meta へ upsert
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--env が無ければ環境変数だけで動く)
終了コード: 0(止まっている行があっても 0= 監視は job を落とさない。⚠ 行をログの末尾に出す)/ 2 前提の読み取りに失敗

⛔旧 DB(chihou_meta の 5 場の能検= PC の他場ジョブが書く)は **公開 anon キーで読むだけ**。キーは js/data.js に
  書いてある公開のもの(閲覧者の画面と同じ)を読む= 秘密を増やさない。書かない。
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenkai import TRACK2PREFIX  # noqa: E402

UA = "nar-jobs-coverage/1.0"
META_KEY = "coverage"
JST = dt.timezone(dt.timedelta(hours=9))
OLD_URL = "https://jcrcftvrsgmsewwdkqha.supabase.co"
DATA_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "js", "data.js")

# nar_races.track → 場の prefix。⛔tenkai の表に帯広だけ無いので足す(表を 2 つ作らない)
TRACK = dict(TRACK2PREFIX)
TRACK["帯広ば"] = "obihiro"
PREFIX2TRACK = {v: k for k, v in TRACK.items()}
# 北から(js/data.js VENUES の order と同じ)
VENUE_ORDER = ["obihiro", "monbetsu", "morioka", "mizusawa", "urawa", "funabashi", "ooi", "kawasaki",
               "kanazawa", "kasamatsu", "nagoya", "sonoda", "himeji", "kochi", "saga"]
# 能検の地区(js/data.js NOKEN_NAR / NOKEN_CHIHOU と同じ)。src= どこが書いているか
# §117b(2026-09-06) 5 場も nar_meta(主催者公式・cloud)へ移った= 13 地区全部 nar。PC 側は空
NOKEN_NAR = ["banei", "iwate", "kasamatsu", "nagoya", "hyogo", "kochi", "saga", "kanazawa",
             "monbetsu", "ooi", "funabashi", "kawasaki", "urawa"]
NOKEN_PC = []

# 「止まっている」とみなす日数(種類ごと・admin の一覧に出す基準)。⛔小サンプルから動かさない
WARN_AFTER = {"results": 3, "entries": 3, "odds": 3, "sales": 3, "noken": 21, "health": 3,
              "organizer": 14, "penalties": 21, "auction": {"rakuten": 5, "sat": 9}, "stats": 3}

N_REQ = [0]


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(base, key, path, method="GET", body=None, headers=None):
    N_REQ[0] += 1
    h = {"apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
         "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(base + path, method=method, data=body, headers=h)
    with urllib.request.urlopen(r, timeout=180) as x:
        return x.status, x.read().decode("utf-8")


def fetch_all(base, key, path, page=1000):
    """Range で 1000 行ずつ(Supabase の上限)。⛔order は呼び出し側が一意にする(#postgrest-offset)。"""
    out = []
    lo = 0
    while True:
        _st, body = req(base, key, path, headers={"Range-Unit": "items", "Range": "%d-%d" % (lo, lo + page - 1)})
        rows = json.loads(body) if body else []
        out.extend(rows)
        if len(rows) < page:
            return out
        lo += page


def one(base, key, path):
    _st, body = req(base, key, path)
    rows = json.loads(body) if body else []
    return rows[0] if rows else None


def days_between(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def row(kind, venue, **kw):
    r = {"kind": kind, "venue": venue, "expected": None, "have": 0, "last": None, "missing": [],
         "stale_days": None, "warn_after": WARN_AFTER.get(kind), "note": "", "src": "nar"}
    r.update(kw)
    return r


def finish_row(r, today):
    if r["last"]:
        r["stale_days"] = days_between(r["last"], today)
    return r


# ---------------------------------------------------------------- 期待(主催者の開催日程)
def kaisai_days(base, key):
    """{prefix: set(date)}。nar_meta kaisai_schedule(cloud/convene.py)。無ければ空。"""
    m = one(base, key, "/rest/v1/nar_meta?select=value&key=eq.kaisai_schedule")
    out = {}
    if not m:
        return out, None
    v = m["value"]
    v = json.loads(v) if isinstance(v, str) else v
    for date, items in (v.get("days") or {}).items():
        for it in items or []:
            if isinstance(it, list) and it:
                out.setdefault(str(it[0]), set()).add(date)
    return out, v.get("built")


# ---------------------------------------------------------------- 種類ごと
def results_entries(base, key, expect, today, rows):
    lo = (dt.date.fromisoformat(today) - dt.timedelta(days=30)).isoformat()
    hi = (dt.date.fromisoformat(today) + dt.timedelta(days=7)).isoformat()
    races = fetch_all(base, key, "/rest/v1/nar_races?select=track,race_date,race_no&race_date=gte.%s&race_date=lte.%s"
                      "&order=track,race_date,race_no" % (lo, hi))
    have_entry = {}
    for r in races:
        p = TRACK.get(r["track"])
        if p:
            have_entry.setdefault(p, set()).add(r["race_date"])
    # 確定結果= 1R の着順が入っている日(1R の出走馬 5 頭までを見る= 取消でも誰かは finish を持つ)
    runs = fetch_all(base, key, "/rest/v1/nar_runs?select=track,race_date&race_date=gte.%s&race_date=lte.%s"
                     "&race_no=eq.1&runner_number=lte.5&finish=not.is.null&order=track,race_date,runner_number"
                     % (lo, today))
    have_res = {}
    for r in runs:
        p = TRACK.get(r["track"])
        if p:
            have_res.setdefault(p, set()).add(r["race_date"])
    yesterday = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
    tomorrow3 = (dt.date.fromisoformat(today) + dt.timedelta(days=3)).isoformat()
    # ⚠開催日程(kaisai_schedule)は当月+先2か月しか持たない= 前月は期待を数えられない。期待の窓は日程のある日から
    all_days = sorted(d for s in expect.values() for d in s)
    lo_exp = max(lo, all_days[0]) if all_days else lo
    for p in VENUE_ORDER:
        exp_all = expect.get(p, set())
        # 結果: 日程のある範囲(最長30日前)〜昨日の開催日
        exp = sorted(d for d in exp_all if lo_exp <= d <= yesterday)
        have = have_res.get(p, set())
        r = row("results", p, expected=len(exp) if expect else None, have=len(have & set(exp)) if expect else len(have),
                last=max(have) if have else None, missing=[d for d in exp if d not in have],
                note="" if expect else "開催日程が無いので期待は数えられない")
        rows.append(finish_row(r, today))
        # 出馬表: 今日〜3日先の開催日(出馬表は前日の夕方に出る= 当日分と翌日分を主に見る)
        exp2 = sorted(d for d in exp_all if today <= d <= tomorrow3)
        have2 = have_entry.get(p, set())
        r2 = row("entries", p, expected=len(exp2) if expect else None, have=len(have2 & set(exp2)) if exp2 else 0,
                 last=max(have2) if have2 else None, missing=[d for d in exp2 if d not in have2 and d <= (dt.date.fromisoformat(today) + dt.timedelta(days=1)).isoformat()],
                 note="" if exp2 else "先3日に開催なし")
        rows.append(finish_row(r2, today))
    return have_res


def odds_sales(base, key, have_res, today, rows):
    lo = (dt.date.fromisoformat(today) - dt.timedelta(days=14)).isoformat()
    for kind, table in (("odds", "nar_race_odds"), ("sales", "nar_sales")):
        got = fetch_all(base, key, "/rest/v1/%s?select=track,race_date&race_date=gte.%s&race_date=lte.%s&race_no=eq.1"
                        "&order=track,race_date" % (table, lo, today))
        have = {}
        for r in got:
            p = TRACK.get(r["track"])
            if p:
                have.setdefault(p, set()).add(r["race_date"])
        for p in VENUE_ORDER:
            exp = sorted(d for d in have_res.get(p, set()) if lo <= d < today)   # 昨日までの、結果のある日に対して
            h = have.get(p, set())
            r = row(kind, p, expected=len(exp), have=len(h & set(exp)), last=max(h) if h else None,
                    missing=[d for d in exp if d not in h])
            rows.append(finish_row(r, today))


def noken_days(value):
    v = json.loads(value) if isinstance(value, str) else value
    days = (v or {}).get("days") or []
    ds = sorted(str(d.get("date", "")) for d in days if d.get("date"))
    vids = 0
    for d in days:
        has = d.get("video") or d.get("videoUrl") or d.get("videoUrls") or \
            any(r.get("video") or r.get("mp4") for r in (d.get("races") or []) if isinstance(r, dict))
        if has:
            vids += 1
    return ds, vids


def noken(base, key, old_key, today, rows):
    keys = ",".join("%s_noken" % p for p in NOKEN_NAR)
    got = fetch_all(base, key, "/rest/v1/nar_meta?select=key,value,updated_at&key=in.(%s)&order=key" % keys)
    by = {r["key"]: r for r in got}
    for p in NOKEN_NAR:
        m = by.get("%s_noken" % p)
        ds, vids = noken_days(m["value"]) if m else ([], 0)
        r = row("noken", p, have=len(ds), last=ds[-1] if ds else None, src="nar",
                note="映像のある日 %d" % vids if ds else "行なし")
        rows.append(finish_row(r, today))
    if not old_key:
        for p in NOKEN_PC:
            rows.append(row("noken", p, src="pc", note="旧DBのキーが読めない"))
        return
    keys = ",".join("%s_noken" % p for p in NOKEN_PC)
    try:
        got = fetch_all(OLD_URL, old_key, "/rest/v1/chihou_meta?select=key,value&key=in.(%s)&order=key" % keys)
    except Exception as e:                                       # noqa: BLE001
        log("  ⚠ 旧DB(chihou_meta)が読めない: %s" % str(e)[:100])
        got = []
    by = {r["key"]: r for r in got}
    for p in NOKEN_PC:
        m = by.get("%s_noken" % p)
        ds, vids = noken_days(m["value"]) if m else ([], 0)
        r = row("noken", p, have=len(ds), last=ds[-1] if ds else None, src="pc",
                note=("映像のある日 %d" % vids if ds else "行なし") + "・PC の他場ジョブが書く(§117 で cloud へ)")
        rows.append(finish_row(r, today))


def health(base, key, today, rows):
    imps = fetch_all(base, key, "/rest/v1/nar_health_imports?select=source_kind,status,last_checked_at"
                     "&order=source_kind,source_ref")
    agg = {}
    for r in imps:
        a = agg.setdefault(r["source_kind"], {"complete": 0, "review": 0, "error": 0, "other": 0, "last": None})
        st = r.get("status") or "other"
        a[st if st in a else "other"] += 1
        d = (r.get("last_checked_at") or "")[:10]
        if d and (a["last"] is None or d > a["last"]):
            a["last"] = d
    for sk in sorted(agg):
        a = agg[sk]
        r = row("health", sk, have=a["complete"], last=a["last"],
                note="読めた %d・確認待ち %d・失敗 %d" % (a["complete"], a["review"], a["error"]))
        rows.append(finish_row(r, today))
    # 主催者公式の記事(§109/§110)= events の source_kind `<slug>_official`
    lo = (dt.date.fromisoformat(today) - dt.timedelta(days=120)).isoformat()
    evs = fetch_all(base, key, "/rest/v1/nar_horse_health_events?select=source_kind,event_date,race_date,updated_at"
                    "&source_kind=like.*_official&updated_at=gte.%s&order=source_kind,event_id" % lo)
    org = {}
    for r in evs:
        a = org.setdefault(r["source_kind"], {"n": 0, "last": None, "upd": None})
        a["n"] += 1
        d = r.get("event_date") or r.get("race_date")
        if d and (a["last"] is None or d > a["last"]):
            a["last"] = d
        u = (r.get("updated_at") or "")[:10]
        if u and (a["upd"] is None or u > a["upd"]):
            a["upd"] = u
    for sk in sorted(org):
        a = org[sk]
        p = sk.replace("_official", "")
        r = row("organizer", p, have=a["n"], last=a["last"], note="直近120日の行・最後に書いた日 %s" % (a["upd"] or "-"))
        rows.append(finish_row(r, today))


def penalties(base, key, have_res, today, rows):
    lo = (dt.date.fromisoformat(today) - dt.timedelta(days=60)).isoformat()
    got = fetch_all(base, key, "/rest/v1/nar_penalties?select=track,race_date&race_date=gte.%s&order=penalty_id" % lo)
    by = {}
    for r in got:
        p = TRACK.get(r["track"])
        if p:
            by.setdefault(p, []).append(r["race_date"])
    for p in VENUE_ORDER:
        ds = by.get(p, [])
        last_res = max(have_res.get(p, set())) if have_res.get(p) else None
        r = row("penalties", p, have=len(ds), last=max(ds) if ds else None,
                note="直近60日の行。制裁が無い日は行が無い(成績表は %s まで)" % (last_res or "-"))
        rows.append(finish_row(r, today))


def auction(base, key, today, rows):
    lo = (dt.date.fromisoformat(today) - dt.timedelta(days=45)).isoformat()
    got = fetch_all(base, key, "/rest/v1/auction_sales?select=source,round_no,auction_date,price"
                    "&source=in.(rakuten,sat)&auction_date=gte.%s&order=source,item_id" % lo)
    agg = {}
    for r in got:
        a = agg.setdefault(r["source"], {})
        d = a.setdefault(r["auction_date"], {"n": 0, "priced": 0, "round": r.get("round_no")})
        d["n"] += 1
        if r.get("price") is not None:
            d["priced"] += 1
    for src in ("rakuten", "sat"):
        days = agg.get(src, {})
        past = sorted(d for d in days if d <= today)
        last = past[-1] if past else None
        det = days.get(last) if last else None
        note = ""
        if det:
            note = "最終回 %s= %d 頭(価格あり %d)" % (("第%s回 " % det["round"]) if det["round"] else "", det["n"], det["priced"])
        fut = sorted(d for d in days if d > today)
        if fut:
            note += "・先の出品 %s %d 頭" % (fut[0], days[fut[0]]["n"])
        r = row("auction", src, have=sum(v["n"] for v in days.values()), last=last, note=note,
                warn_after=WARN_AFTER["auction"][src])
        rows.append(finish_row(r, today))


def stats(base, key, today, rows, kaisai_built):
    def newest(path, field):
        m = one(base, key, path)
        return (m or {}).get(field, None)
    items = [
        ("person_stats", "リーディング(人)", (newest("/rest/v1/nar_person_stats?select=updated_at&order=updated_at.desc&limit=1", "updated_at") or "")[:10]),
        ("venue_stats", "競馬場データ", (newest("/rest/v1/nar_venue_stats?select=updated_at&order=updated_at.desc&limit=1", "updated_at") or "")[:10]),
        ("graded", "重賞", (newest("/rest/v1/nar_graded?select=updated_at&order=updated_at.desc&limit=1", "updated_at") or "")[:10]),
        ("ai_marks", "AI印", newest("/rest/v1/nar_ai_marks?select=race_date&order=race_date.desc&limit=1", "race_date")),
        ("changes", "移籍・転厩", (newest("/rest/v1/nar_horse_changes?select=created_at&order=created_at.desc&limit=1", "created_at") or "")[:10]),
        ("odds_full", "全券種オッズ", (newest("/rest/v1/nar_odds_full?select=observed_at&order=observed_at.desc&limit=1", "observed_at") or "")[:10]),
        ("kaisai", "開催日程", kaisai_built),
    ]
    metas = fetch_all(base, key, "/rest/v1/nar_meta?select=key,updated_at&key=in.(baba_diff,baba_trend,noken_index)&order=key")
    names = {"baba_diff": "馬場差", "baba_trend": "馬場の傾向", "noken_index": "能検の索引"}
    for m in metas:
        items.append((m["key"], names.get(m["key"], m["key"]), (m.get("updated_at") or "")[:10]))
    cs = fetch_all(base, key, "/rest/v1/nar_meta?select=key,updated_at&key=like.course_stats:*&order=key")
    if cs:
        items.append(("course_stats", "コース別データ(%d場)" % len(cs), min((m.get("updated_at") or "")[:10] for m in cs)))
    for k, label, last in items:
        r = row("stats", k, have=1 if last else 0, last=last or None, note=label)
        rows.append(finish_row(r, today))


def old_anon_key():
    """js/data.js の公開 anon キー(旧 DB)。⛔書き込みには使わない・ログに出さない。"""
    try:
        s = io.open(DATA_JS, encoding="utf-8").read(4000)
        m = re.search(r"SUPABASE_KEY\s*=\s*'(eyJ[A-Za-z0-9._-]+)'", s)
        return m.group(1) if m else None
    except OSError:
        return None


def stale_rows(rows):
    out = []
    for r in rows:
        wa = r.get("warn_after")
        if r.get("missing"):
            out.append(r)
        elif r.get("last") is None and r["kind"] in ("noken", "health", "auction", "stats"):
            out.append(r)
        elif wa is not None and r.get("stale_days") is not None and r["stale_days"] > wa \
                and r["kind"] not in ("results", "entries", "odds", "sales", "penalties"):
            # 開催が無い場は結果が古くて当然= results 系は missing(開催日程との差)だけで見る
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true", help="nar_meta へ入れる(既定はドライラン)")
    ap.add_argument("--json", help="結果を JSON で書き出す(検品用)")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が要る")
        return 2
    now = dt.datetime.now(JST)
    today = now.date().isoformat()
    rows = []
    try:
        expect, kaisai_built = kaisai_days(base, key)
        log("開催日程 built=%s 場=%d" % (kaisai_built, len(expect)))
        have_res = results_entries(base, key, expect, today, rows)
        odds_sales(base, key, have_res, today, rows)
        noken(base, key, old_anon_key(), today, rows)
        health(base, key, today, rows)
        penalties(base, key, have_res, today, rows)
        auction(base, key, today, rows)
        stats(base, key, today, rows, kaisai_built)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as e:
        log("⛔ 読み取りに失敗: %s" % str(e)[:200])
        return 2
    value = {"built": now.strftime("%Y-%m-%dT%H:%M+09:00"), "today": today, "rows": rows}
    for r in rows:
        log("  %-10s %-12s 期待 %-4s 実際 %-4s 最新 %-10s 欠け %-3d %s" % (
            r["kind"], r["venue"], "-" if r["expected"] is None else r["expected"], r["have"],
            r["last"] or "-", len(r["missing"]), r["note"]))
    st = stale_rows(rows)
    log("行 %d・通信 %d" % (len(rows), N_REQ[0]))
    if st:
        log("⚠ 止まっている/欠けている行 %d: %s" % (len(st), " / ".join(
            "%s:%s%s" % (r["kind"], r["venue"], ("(欠け " + ",".join(r["missing"][:3]) + ")") if r["missing"] else
                        ("(最新 %s)" % (r["last"] or "-"))) for r in st[:20])))
    else:
        log("✅ 止まっている行なし")
    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(json.dumps(value, ensure_ascii=False, indent=1))
    if not a.apply:
        log("ドライラン(--apply で nar_meta '%s' へ入れる)" % META_KEY)
        return 0
    body = json.dumps([{"key": META_KEY, "value": value, "updated_at": now.isoformat()}], ensure_ascii=False).encode("utf-8")
    stc, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST", body)
    log("nar_meta/%s 更新 %s" % (META_KEY, stc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
