# -*- coding: utf-8 -*-
"""§238c 網羅表 = 場 × 年月の枡に「何レース入っていて、どの項目がどれだけ埋まっているか」を焼く便。

⛔ファイル名の注意: `cloud/coverage.py` は §118「データの状態」(直近 30 日の止まり監視)で別物。
   こちらは 2014-01〜当月の**全期間の網羅表**なので、潰さずに別ファイルにした(nar_meta の鍵も別)。

  出力 = nar_meta key='coverage:v1'(索引)と key='coverage:v1:YYYY'(年ごとの枡)
    索引  {"built": "...", "from": "2014-01", "to": "2026-09", "years": ["2014", ...],
           "venues": ["obihiro", ...], "cols": ["finish", ...], "keys": ["coverage:v1:2014", ...]}
    年   {"built": "...", "year": "2014", "cells": [枡, ...]}
    枡   {"v": "ooi", "ym": "2026-08", "races": 216, "runs": 2401,
          "r": {"finish": 100.0, "time": 100.0, ...},      # ある率(%・小数1桁)
          "src": {"official": 216}}                        # レース数の出どころ内訳
  ⛔1 行の JSON を 200KB 以内にするため**年ごとに鍵を分ける**(設計 §1 の但し書き)。

  py -3.12 -X utf8 cloud/coverage_matrix.py                              # ドライラン(直近 2 か月)
  py -3.12 -X utf8 cloud/coverage_matrix.py --from 2026-08 --to 2026-08 --json out.json
  py -3.12 -X utf8 cloud/coverage_matrix.py --apply --from 2014-01       # 全期間の焼き直し
  py -3.12 -X utf8 cloud/coverage_matrix.py --selftest                   # 数え方だけ(通信なし)

環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(⛔鍵はコードに書かない・ログにも出さない)
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔**年が終わるごとに焼く**(2026-09-22)= 途中で読みが通らなくなっても、そこまでの年は nar_meta に残る。
  9/21 の事故= 2015-12 の読みが 3 回とも時間切れ→ 全部捨てて rc=2・coverage:v1* が 1 行も無かった。
  読みは 6 回まで出直す(10/20/40/60/90/120 秒・1 回の待ちは 120 秒)。
  止まったら最後に「続きは --from YYYY-MM」と出す= その月から流し直せばよい。
  既に焼けた年は索引 coverage:v1 の years に出るので、**--from をその次の年の頭にすれば飛ばせる**。

⛔本番 DB に group by を投げない= 月ごとに列を絞って REST で読み、**数えるのはこの便の中**。
⛔1000 行キャップ: 全取得は order を一意にしてページングする(深い offset で欠落しない)。
⛔推定で埋めない= 無い項目は 0.0%(空欄にしない)。
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenkai import TRACK2PREFIX                                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

UA = "nar-jobs-coverage-matrix/1.0"
JST = dt.timezone(dt.timedelta(hours=9))
PAGE = 1000
INDEX_KEY = "coverage:v1"
YEAR_KEY = "coverage:v1:%s"
FIRST_YM = "2014-01"
SOFT_LIMIT = 200 * 1024        # 1 行の JSON の目安(設計 §1)
DAILY_MONTHS = 2               # 既定= 直近 2 か月だけ数え直す
READ_TIMEOUT = 120             # ⛔本番が重いと 90 秒では読み切れない(2026-09-22 の事故)
RETRY_WAITS = [10, 20, 40, 60, 90, 120]   # 読みの出直し= 6 回・この秒数だけ空けて待つ

# 場の並び(北から・js/data.js VENUES と同じ)。⛔帯広ばは tenkai の表に無いので足す
TRACK = dict(TRACK2PREFIX)
TRACK["帯広ば"] = "obihiro"
VENUE_ORDER = ["obihiro", "monbetsu", "morioka", "mizusawa", "urawa", "funabashi", "ooi", "kawasaki",
               "kanazawa", "kasamatsu", "nagoya", "sonoda", "himeji", "kochi", "saga"]

# 項目 → (どの表で数えるか, 値のある行の見分け方)。⛔列を減らす/増やすときは画面 /coverage も直す
RUN_COLS = ["finish", "time", "last3f", "weight"]                  # nar_runs(1 頭 1 行)
FACT_COLS = ["c1", "style", "first3f", "odds_close"]               # nar_run_facts(派生表)
RACE_COLS = ["payout", "votes"]                                    # 1 レース 1 行
COLS = RUN_COLS + FACT_COLS + RACE_COLS

N_REQ = [0]


class ReadFailed(Exception):
    """前提の読み取りに失敗(⛔途中まで数えた年は焼いてから終わる)。"""


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- 通信(読むだけ+ nar_meta の upsert)

def env():
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が要る(⛔鍵はコードに書かない)")
    return base, key


def get(base, key, path, sleep=time.sleep):
    """読むだけ。⛔落とさずに 6 回まで出直す(10/20/40/60/90/120 秒)。

    それでも駄目なら ReadFailed= 呼ぶ側が**そこまでの年を焼いてから**やめる。
    """
    N_REQ[0] += 1
    req = urllib.request.Request(base + path, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA, "Accept": "application/json"})
    last = ""
    for n in range(len(RETRY_WAITS) + 1):
        try:
            with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as r:
                return json.loads(r.read())
        except Exception as e:                                      # noqa: BLE001
            last = str(e)[:160]
            if n >= len(RETRY_WAITS):
                break
            log("  ⚠読み直し %d/%d(%d 秒待つ): %s" % (n + 1, len(RETRY_WAITS), RETRY_WAITS[n], last))
            sleep(RETRY_WAITS[n])
    log("⛔ 読み取りに失敗(%d 回): %s" % (len(RETRY_WAITS) + 1, last))
    raise ReadFailed(last)


def rows_all(base, key, path):
    """⛔order は主キーで一意にしてから offset を進める(PostgREST の offset は order が一意でないと欠ける)。"""
    out, off = [], 0
    joiner = "&" if "?" in path else "?"
    while True:
        rows = get(base, key, "%s%slimit=%d&offset=%d" % (path, joiner, PAGE, off))
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        off += PAGE


def put_meta(base, key, meta_key, value):
    body = json.dumps([{"key": meta_key, "value": value}], ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base + "/rest/v1/nar_meta?on_conflict=key", data=body, method="POST",
        headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal", "User-Agent": UA})
    for n in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, ""
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code >= 500 and n < 2:
                time.sleep(3 * (n + 1))
                continue
            return e.code, msg
        except Exception as e:                                      # noqa: BLE001
            if n < 2:
                time.sleep(3 * (n + 1))
                continue
            return 0, str(e)
    return 0, "unreachable"


# ---------------------------------------------------------------- 月の並び(純関数)

def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7])
    i = (y * 12 + m - 1) + n
    return "%04d-%02d" % (i // 12, i % 12 + 1)


def ym_range(lo, hi):
    out, cur = [], lo
    while cur <= hi:
        out.append(cur)
        cur = ym_add(cur, 1)
    return out


def year_groups(months):
    """月の一覧 → [(年, [その年の月, ...]), ...](古い年から)。⛔年が終わるごとに焼くための区切り。"""
    out = []
    for ym in months:
        if not out or out[-1][0] != ym[:4]:
            out.append((ym[:4], []))
        out[-1][1].append(ym)
    return out


def ym_bounds(ym):
    """その月の [初日, 翌月の初日)。REST は gte / lt で挟む(月末日を数えない)。"""
    return ym + "-01", ym_add(ym, 1) + "-01"


# ---------------------------------------------------------------- 数え方(純関数・tests が固定入力で確かめる)

def venue_of(track):
    return TRACK.get(str(track or "").strip())


def src_of(source):
    """nar_races.source → 出どころの札。⛔画面には「公式」「過去分の取り込み」「旧データ」と出す(社名を出さない)。"""
    s = str(source or "").lower()
    if "kochi" in s and "legacy" in s:
        return "kochi_legacy"
    if "rakuten" in s or "kb" in s or "archive" in s:
        return "rakuten"
    if not s:
        return "unknown"
    return "official"


def rate(have, total):
    """ある率(%・小数 1 桁)。⛔母数 0 は None(「0% で欠けている」と区別する)。"""
    if not total:
        return None
    return round(100.0 * have / total, 1)


def key_of(r):
    return (str(r.get("track") or ""), str(r.get("race_date") or "")[:10], int(r.get("race_no") or 0))


def count_month(ym, races, runs, facts, payouts, votes):
    """1 か月ぶんの行 → 場ごとの枡 [{v, ym, races, runs, r, src}, ...]。⛔通信しない。

    ・母数= レース数(payout / votes)と 出走数(それ以外)。
    ・nar_run_facts の行が無い走は「その項目が無い」= 0% 側に数える(⛔推定で埋めない)。
    ・レースの行が無い走・場の判らない行は数えない(枡に入れる先が無いため)。
    """
    race_venue = {}
    acc = {}

    def cell(v):
        if v not in acc:
            acc[v] = {"v": v, "ym": ym, "races": 0, "runs": 0,
                      "have": dict((c, 0) for c in COLS), "src": {}}
        return acc[v]

    for r in races:
        v = venue_of(r.get("track"))
        if not v:
            continue
        k = key_of(r)
        race_venue[k] = v
        c = cell(v)
        c["races"] += 1
        s = src_of(r.get("source"))
        c["src"][s] = c["src"].get(s, 0) + 1

    fact_of = {}
    for f in facts:
        v = race_venue.get(key_of(f))
        if v:
            fact_of[(key_of(f), int(f.get("umaban") or 0))] = f

    for r in runs:
        k = key_of(r)
        v = race_venue.get(k)
        if not v:
            continue                                                # ⛔レースの行が無い走は数えない
        c = cell(v)
        c["runs"] += 1
        h = c["have"]
        if r.get("finish") is not None:
            h["finish"] += 1
        if r.get("time_sec") is not None:
            h["time"] += 1
        if r.get("last3f") is not None:
            h["last3f"] += 1
        if r.get("body_weight") is not None:
            h["weight"] += 1
        f = fact_of.get((k, int(r.get("runner_number") or 0)))
        if f:
            if f.get("c1") is not None:
                h["c1"] += 1
            if f.get("style"):
                h["style"] += 1
            if f.get("first3f") is not None:
                h["first3f"] += 1
            if f.get("win_odds_close") is not None:
                h["odds_close"] += 1

    for p in payouts:
        v = race_venue.get(key_of(p))
        if v and p.get("payouts"):
            cell(v)["have"]["payout"] += 1
    for p in votes:
        v = race_venue.get(key_of(p))
        if v and p.get("votes"):
            cell(v)["have"]["votes"] += 1

    out = []
    for v in sorted(acc, key=lambda x: VENUE_ORDER.index(x) if x in VENUE_ORDER else 99):
        c = acc[v]
        r_ = {}
        for col in COLS:
            total = c["races"] if col in RACE_COLS else c["runs"]
            r_[col] = rate(c["have"][col], total)
        out.append({"v": v, "ym": ym, "races": c["races"], "runs": c["runs"], "r": r_,
                    "src": dict(sorted(c["src"].items()))})
    return out


def merge_cells(old, new):
    """同じ (場, 年月) は新しい方で置き換える。数え直していない月は残す(⛔情報を潰さない)。"""
    by = dict(((c["v"], c["ym"]), c) for c in old)
    for c in new:
        by[(c["v"], c["ym"])] = c
    return [by[k] for k in sorted(by, key=lambda k: (k[1], VENUE_ORDER.index(k[0])
                                                     if k[0] in VENUE_ORDER else 99))]


# ---------------------------------------------------------------- 1 か月を読む

def read_month(base, key, ym):
    lo, hi = ym_bounds(ym)
    win = "&race_date=gte.%s&race_date=lt.%s" % (lo, hi)
    races = rows_all(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,source" + win
                     + "&order=race_date.asc,track.asc,race_no.asc")
    if not races:
        return [], [], [], [], []
    runs = rows_all(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,"
                    "finish,time_sec,last3f,body_weight" + win
                    + "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc")
    facts = rows_all(base, key, "/rest/v1/nar_run_facts?select=track,race_date,race_no,umaban,"
                     "c1,style,first3f,win_odds_close" + win
                     + "&order=race_date.asc,track.asc,race_no.asc,umaban.asc")
    payouts = rows_all(base, key, "/rest/v1/nar_race_payouts?select=track,race_date,race_no,payouts" + win
                       + "&order=race_date.asc,track.asc,race_no.asc")
    votes = rows_all(base, key, "/rest/v1/nar_race_votes?select=track,race_date,race_no,votes" + win
                     + "&order=race_date.asc,track.asc,race_no.asc")
    return races, runs, facts, payouts, votes


def read_meta(base, key, meta_key):
    rows = get(base, key, "/rest/v1/nar_meta?select=value&key=eq."
               + urllib.parse.quote(meta_key, safe=""))
    if not rows:
        return {}
    v = rows[0].get("value")
    return (json.loads(v) if isinstance(v, str) else (v or {})) or {}


def read_year_cells(base, key, year):
    return read_meta(base, key, YEAR_KEY % year).get("cells") or []


def merge_years(old_years, new_years):
    """索引の years。⛔前に焼いた年を消さない(今回数えていない年も残す)。"""
    return sorted(set(list(old_years or []) + list(new_years or [])))


def build_index(built, this_ym, years):
    return {"built": built, "from": FIRST_YM, "to": this_ym, "years": list(years),
            "venues": VENUE_ORDER, "cols": COLS,
            "keys": [YEAR_KEY % y for y in years],
            "note": "取れなかった項目は空欄のままで、推定で埋めていません"}


# ---------------------------------------------------------------- 自己診断(通信なし)

def selftest():
    races = [{"track": "大井", "race_date": "2026-08-01", "race_no": 1, "source": "official"},
             {"track": "大井", "race_date": "2026-08-01", "race_no": 2, "source": "rakuten"},
             {"track": "謎場", "race_date": "2026-08-01", "race_no": 1, "source": "official"}]
    runs = [{"track": "大井", "race_date": "2026-08-01", "race_no": 1, "runner_number": 1,
             "finish": 1, "time_sec": 70.0, "last3f": 38.0, "body_weight": 480},
            {"track": "大井", "race_date": "2026-08-01", "race_no": 1, "runner_number": 2,
             "finish": 2, "time_sec": 70.5, "last3f": None, "body_weight": None},
            {"track": "大井", "race_date": "2026-08-09", "race_no": 9, "runner_number": 1,
             "finish": 1, "time_sec": 70.0, "last3f": 38.0, "body_weight": 480}]
    facts = [{"track": "大井", "race_date": "2026-08-01", "race_no": 1, "umaban": 1,
              "c1": 3, "style": "先行", "first3f": 36.2, "win_odds_close": 2.1}]
    payouts = [{"track": "大井", "race_date": "2026-08-01", "race_no": 1, "payouts": [{"t": "win"}]},
               {"track": "大井", "race_date": "2026-08-01", "race_no": 2, "payouts": []}]
    votes = [{"track": "大井", "race_date": "2026-08-01", "race_no": 1, "votes": {"win": 1}}]
    cells = count_month("2026-08", races, runs, facts, payouts, votes)
    assert [c["v"] for c in cells] == ["ooi"], cells          # ⛔知らない場は枡を作らない
    c = cells[0]
    assert (c["races"], c["runs"]) == (2, 2), c               # 8-09 の走はレースの行が無いので数えない
    assert c["r"] == {"finish": 100.0, "time": 100.0, "last3f": 50.0, "weight": 50.0,
                      "c1": 50.0, "style": 50.0, "first3f": 50.0, "odds_close": 50.0,
                      "payout": 50.0, "votes": 50.0}, c["r"]
    assert c["src"] == {"official": 1, "rakuten": 1}, c["src"]
    assert rate(0, 0) is None and rate(0, 5) == 0.0
    assert ym_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert ym_bounds("2026-12") == ("2026-12-01", "2027-01-01")
    old = [{"v": "ooi", "ym": "2026-07", "races": 1}, {"v": "ooi", "ym": "2026-08", "races": 1}]
    new = [{"v": "ooi", "ym": "2026-08", "races": 2}]
    assert [x["races"] for x in merge_cells(old, new)] == [1, 2]
    assert year_groups(["2014-11", "2014-12", "2015-01"]) == [("2014", ["2014-11", "2014-12"]),
                                                              ("2015", ["2015-01"])]
    assert merge_years(["2014"], ["2015", "2014"]) == ["2014", "2015"]
    assert len(RETRY_WAITS) == 6 and READ_TIMEOUT == 120
    log("selftest OK")
    return 0


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ書く(既定は書かない)")
    ap.add_argument("--from", dest="ym_from", help="YYYY-MM(既定= 直近 2 か月)")
    ap.add_argument("--to", dest="ym_to", help="YYYY-MM(既定= 当月)")
    ap.add_argument("--json", help="枡をこのファイルにも書き出す(検品用)")
    ap.add_argument("--selftest", action="store_true", help="数え方だけ(通信なし)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    now = dt.datetime.now(JST)
    this_ym = now.strftime("%Y-%m")
    ym_to = a.ym_to or this_ym
    ym_from = a.ym_from or ym_add(ym_to, -(DAILY_MONTHS - 1))
    if ym_from < FIRST_YM:
        ym_from = FIRST_YM
    if ym_from > ym_to:
        log("⛔ --from が --to より後")
        return 2
    base, key = env()
    months = ym_range(ym_from, ym_to)
    log("網羅表 %s〜%s(%d か月)%s" % (ym_from, ym_to, len(months), "" if a.apply else " ドライラン"))

    t0 = time.time()
    built = now.strftime("%Y-%m-%dT%H:%M+09:00")
    values, empty, done_years, bad = {}, [], [], 0
    try:
        index_years = sorted(read_meta(base, key, INDEX_KEY).get("years") or []) if a.apply else []
    except ReadFailed:
        log("⛔ 索引を読めない= 何も焼かずに止める(本番が重いときは時間を置く)")
        return 2
    if index_years:
        log("既にある年= %s(飛ばすなら --from で始めの年をずらす)" % ",".join(index_years))
    failed_ym = None

    def bake(year, cells):
        """⛔年が終わるごとに焼く= 途中で落ちてもここまでは残る。"""
        nonlocal bad
        if not cells:
            return
        old = read_year_cells(base, key, year) if (a.apply or a.json) else []
        value = {"built": built, "year": year, "cells": merge_cells(old, cells)}
        values[YEAR_KEY % year] = value
        n = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        log("  %s %.1fKB" % (YEAR_KEY % year, n / 1024.0))
        if n > SOFT_LIMIT:
            log("⚠ 200KB を超えた鍵: %s(年より細かく割るか列を減らす)" % (YEAR_KEY % year))
        if not a.apply:
            done_years.append(year)
            return
        st, msg = put_meta(base, key, YEAR_KEY % year, value)
        log("nar_meta/%s %s %s" % (YEAR_KEY % year, st, msg[:120]))
        if st not in (200, 201, 204):
            bad += 1
            return                                                 # ⛔書けていない年を索引に載せない
        done_years.append(year)
        idx = build_index(built, this_ym, merge_years(index_years, done_years))
        values[INDEX_KEY] = idx
        st, msg = put_meta(base, key, INDEX_KEY, idx)
        log("nar_meta/%s %s %s" % (INDEX_KEY, st, msg[:120]))
        if st not in (200, 201, 204):
            bad += 1

    for year, yms in year_groups(months):
        cells_of_year = []
        for ym in yms:
            try:
                races, runs, facts, payouts, votes = read_month(base, key, ym)
            except ReadFailed:
                failed_ym = ym
                break
            cells = count_month(ym, races, runs, facts, payouts, votes)
            if not cells:
                empty.append(ym)
                continue
            cells_of_year.extend(cells)
            log("  %s 場 %2d・レース %5d・出走 %6d" % (ym, len(cells),
                                                    sum(c["races"] for c in cells),
                                                    sum(c["runs"] for c in cells)))
        try:
            bake(year, cells_of_year)                              # ⛔途中で落ちた年も焼く
        except ReadFailed:
            failed_ym = failed_ym or yms[0]
            log("⛔ %s の焼き込みに必要な読みが通らない= ここで止める" % year)
        if failed_ym:
            break

    n_cells = sum(len(v.get("cells") or []) for k, v in values.items() if k != INDEX_KEY)
    log("焼いた年 %s・空の月 %d・通信 %d・%.0f 秒"
        % (",".join(done_years) or "なし", len(empty), N_REQ[0], time.time() - t0))
    if not a.apply and not failed_ym:
        idx = build_index(built, this_ym, merge_years(index_years, done_years))
        values[INDEX_KEY] = idx

    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(json.dumps(values, ensure_ascii=False, indent=1))
        log("書き出し %s(枡 %d)" % (a.json, n_cells))
    if failed_ym:
        log("⛔ %s の読みで止まった。⛔続きは --from %s(焼いた年= %s)"
            % (failed_ym, failed_ym, ",".join(done_years) or "なし"))
        return 2
    if not a.apply:
        log("ドライラン(--apply で nar_meta '%s' へ入れる)" % INDEX_KEY)
        return 0
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
