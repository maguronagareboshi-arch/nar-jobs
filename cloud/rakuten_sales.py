# -*- coding: utf-8 -*-
"""§54.1 P1: 券種別の総票数・返還票数を楽天競馬の払戻ページから集める(2026-08-29 設計)。

⛔keiba.go.jp に票数ページは無い(実測)。楽天の race_dividend/list に**払戻と券種別の総票数・返還票数が同居**
しており、RACEID のレース番号部分はダミーでも**その日その場の全レースが1ページで返る**
(既存資産= keiba-deploy/modules/app-main.js fetchRakutenDividendsForDay の実測)。
RACEID = YYYYMMDD + 場コード2桁(= keiba.go.jp の k_babaCode と同一・高知31/園田27で実証) + 00000001。

  py -3.12 -X utf8 cloud/rakuten_sales.py --env pipeline/.env.nar --check 2026-08-28 園田   # オラクル(書かない)
  py -3.12 -X utf8 cloud/rakuten_sales.py --env pipeline/.env.nar --days 3                  # ドライラン(直近3日)
  py -3.12 -X utf8 cloud/rakuten_sales.py --env pipeline/.env.nar --days 3 --apply          # 実弾
環境変数: SUPABASE_URL / SUPABASE_ANON_KEY(読み) / SUPABASE_SERVICE_KEY(--apply)
終了コード: 0 正常 / 1 一部失敗 / 2 前提の読み取り失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from load_nar_official import load_env, upsert  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; nar-jobs/1.0)"
SLEEP = 1.2

# 場コード(= keiba.go.jp k_babaCode)。pipeline/probe_babacode.py の実測で確定させる。
# ⛔ここに無い場は取りに行かない(推定でコードを作らない)
BABA = {
    "帯広ば": "3", "門別": "36", "盛岡": "10", "水沢": "11", "浦和": "18", "船橋": "19",
    "大井": "20", "川崎": "21", "金沢": "22", "笠松": "23", "名古屋": "24",
    "園田": "27", "姫路": "28", "高知": "31", "佐賀": "32",
}
# 楽天の券種名 → js/data.js TICKET_* の英名(9券種)
TICKETS = {"単勝": "win", "複勝": "place", "枠複": "bracket_quinella", "枠単": "bracket_exacta",
           "馬複": "quinella", "馬単": "exacta", "ワイド": "wide", "三連複": "trio", "三連単": "trifecta"}


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def http_get(url, tries=3, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    last = None
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except Exception as e:
            last = e
            if n < tries - 1:
                time.sleep(2 * (n + 1))
    raise RuntimeError(f"GET 失敗: {type(last).__name__}: {str(last)[:120]}")


def sb_rows(base, key, path):
    req = urllib.request.Request(f"{base}/rest/v1/{path}", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Accept-Encoding": "gzip", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def sb_all(base, key, path):
    out, off = [], 0
    while True:
        c = sb_rows(base, key, f"{path}&limit=1000&offset={off}")
        out.extend(c)
        if len(c) < 1000:
            return out
        off += 1000


# ---------------------------------------------------------------- 楽天ページのパース

_VOTE_RE = re.compile(r'<th scope="row">([^<]+)</th>\s*<td>([\d,]+)</td>')


def _vote_table(block):
    """「総票数」「返還票数」の小テーブル(9券種)→ {英名: int}。券種名が読めない行は捨てて数える"""
    out, dropped = {}, []
    for name, num in _VOTE_RE.findall(block):
        key = TICKETS.get(name.strip())
        if key:
            out[key] = int(num.replace(",", ""))
        else:
            dropped.append(name.strip())
    return out, dropped


def parse_day(html):
    """1日ぶんのページ → {race_no: {'votes': {...}, 'refunds': {...}}}。票数の無いレースは入らない(未確定・中止)"""
    out = {}
    parts = re.split(r'<h3 class="headline"><span>■</span>(\d+)R', html)
    for i in range(1, len(parts) - 1, 2):
        no = int(parts[i])
        block = parts[i + 1]
        m = re.search(r"総票数([\s\S]*?)返還票数([\s\S]*?)</table>\s*</td>", block)
        if not m:
            continue
        votes, d1 = _vote_table(m.group(1))
        refunds, d2 = _vote_table(m.group(2))
        if d1 or d2:
            log(f"  ⚠ {no}R: 読めない券種名 {sorted(set(d1 + d2))}(その券種だけ落ちる)")
        if votes and sum(votes.values()) > 0:
            out[no] = {"votes": {k: votes.get(k, 0) for k in TICKETS.values()},
                       "refunds": {k: refunds.get(k, 0) for k in TICKETS.values()}}
    return out


# 楽天 title の場名(「帯広ば」だけ表記が同じ「帯広ば競馬場」なのでそのまま通る)。
# ⛔取ったページの title に「場名+日付」が無ければ**その日は捨てる**(コード違い・リダイレクトを黙って飲まない。
#  2026-08-29 実測= 13場で title 一致・水沢/姫路は8月非開催で未実証のためこのガードが保険)
def fetch_day(date_iso, track):
    ymd = date_iso.replace("-", "")
    code = BABA[track]
    url = f"https://keiba.rakuten.co.jp/race_dividend/list/RACEID/{ymd}{int(code):02d}00000001"
    html = http_get(url)
    m = re.search(r"<title>([^<]+)</title>", html)
    title = m.group(1) if m else ""
    if track not in title or date_iso.replace("-", "/") not in title:
        raise RuntimeError(f"title不一致(場コード疑い): {title[:60]}")
    return parse_day(html), url


# ---------------------------------------------------------------- 入り口

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=3, help="今日から遡る日数(既定3。バックフィルは大きく)")
    ap.add_argument("--check", nargs=2, metavar=("DATE", "TRACK"),
                    help="オラクル: 楽天の払戻値を nar_race_payouts と突合(書かない)")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY", "") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    service = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_ANON_KEY が要る"); return 2
    if a.apply and not service:
        log("--apply には SUPABASE_SERVICE_KEY が要る"); return 2

    # ---- オラクル: 同じページの払戻値と nar_race_payouts を突合(票数の器の信頼性を裏取る) ----
    if a.check:
        d_iso, track = a.check
        day, url = fetch_day(d_iso, track)
        log(f"{url} → {len(day)}R の票数")
        rows = sb_rows(base, key, f"nar_race_payouts?select=race_no,payouts&track=eq.{urllib.parse.quote(track)}"
                                  f"&race_date=eq.{d_iso}&order=race_no.asc")
        html = http_get(url)
        ng = ok = 0
        for r in rows:
            no = int(r["race_no"])
            # 楽天ページのそのRブロックから払戻(円)を取り、DB と突合(券種×組は複雑なので単勝だけ=器の検算)
            m = re.search(rf'<h3 class="headline"><span>■</span>{no}R([\s\S]*?)(?=<h3 class="headline">|$)', html)
            if not m:
                continue
            rk = re.search(r'<th scope="row">単勝</th>\s*<td class="number"[^>]*>\s*(\d+)\s*</td>\s*'
                           r'<td class="money"[^>]*>\s*([\d,]+)\s*円', m.group(1))
            db = next((p for p in (r["payouts"] or []) if p.get("t") == "win"), None)
            if not rk or not db:
                continue
            if int(rk.group(2).replace(",", "")) == int(db["y"]) and rk.group(1) == str(db["c"]):
                ok += 1
            else:
                log(f"  NG {no}R 単勝: 楽天 {rk.group(1)}={rk.group(2)}円 / DB {db['c']}={db['y']}円"); ng += 1
        tot = sum(sum(x["votes"].values()) for x in day.values())
        log(f"オラクル {d_iso} {track}: 単勝払戻 一致{ok}/不一致{ng}・総票数合計 {tot:,}票(売上 {tot * 100:,}円)")
        return 0 if ng == 0 and ok > 0 else 1

    # ---- 対象: nar_races の開催(日×場)のうち、nar_sales の保存レース数が競走数に足りないもの ----
    # ⛔当日は書かない(途中確定を「完了」と凍結した事故 2026-08-29)。完了=保存レース数>=競走数。
    #   不足のまま埋まらない日(中止等)は --days の窓を出た時点で追うのをやめる
    today = dt.datetime.now(JST).date()
    since = str(today - dt.timedelta(days=a.days))
    until = str(today - dt.timedelta(days=1))
    races = sb_all(base, key, f"nar_races?select=race_date,track,race_no&race_date=gte.{since}"
                              f"&race_date=lte.{until}&order=race_date.asc,track.asc,race_no.asc")
    expected = {}
    for r in races:
        expected.setdefault((r["race_date"], r["track"]), set()).add(r["race_no"])
    have = sb_all(base, key, f"nar_sales?select=race_date,track,race_no&race_date=gte.{since}"
                             f"&order=race_date.asc,track.asc,race_no.asc")
    saved = {}
    for h in have:
        saved.setdefault((h["race_date"], h["track"]), set()).add(h["race_no"])
    targets = sorted(k for k, nos in expected.items()
                     if k[1] in BABA and len(saved.get(k, ())) < len(nos))
    partial = [k for k in targets if saved.get(k)]
    skipped = sorted({t for _, t in expected if t not in BABA})
    if skipped:
        log(f"⚠ 場コード未確定でスキップ: {skipped}(BABA 表に足すまで取らない)")
    if partial:
        log(f"補完 {len(partial)}組(保存済みが競走数に不足): {[f'{d} {t}' for d, t in partial]}")
    log(f"対象 {len(targets)}組(日×場)・{since}〜{until}")

    fails = 0
    for d_iso, track in targets:
        try:
            day, url = fetch_day(d_iso, track)
        except Exception as e:
            log(f"⚠ {d_iso} {track}: 取得失敗 {e}"); fails += 1; time.sleep(SLEEP); continue
        if not day:
            log(f"{d_iso} {track}: 票数なし(未確定/中止?)→残す")
            time.sleep(SLEEP)
            continue
        rows = [{"track": track, "race_date": d_iso, "race_no": no,
                 "votes": v["votes"], "refunds": v["refunds"],
                 "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()} for no, v in sorted(day.items())]
        if not a.apply:
            tot = sum(sum(x["votes"].values()) for x in day.values())
            log(f"(dry) {d_iso} {track}: {len(rows)}R・総票数 {tot:,}")
        else:
            st, msg = upsert(base, service, "nar_sales", "track,race_date,race_no", rows)
            if st in (200, 201):
                log(f"保存 {d_iso} {track}: {len(rows)}R")
            else:
                log(f"⚠ 保存失敗 {d_iso} {track}: {st} {str(msg)[:120]}"); fails += 1
        time.sleep(SLEEP)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
