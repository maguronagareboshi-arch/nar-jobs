# -*- coding: utf-8 -*-
"""§181 今日走るオークション取引馬 —— 今日の出馬表×取引(auction_sales)→ nar_meta 'auction_today'。

トップの 1 行と /auction の発走時刻が読む。**判定(初出走・除外・頭数)は書かない**= 画面の 1 か所で決める。
  python cloud/auction_today.py --env pipeline/.env.nar            # ドライラン(表示だけ・匿名キーでも動く)
  python cloud/auction_today.py --env pipeline/.env.nar --apply    # 書き込み
workflow(nar-refresh.yml)では noken_debuts.py の直後に回す(30 分ごと= 取消が 30 分以内に反映・冪等)。
10/16 前の晩の分: top-band 便の夜の回(JST 22:10)が `--date 翌日 --key auction_next` で翌日分を別の鍵に書く
(翌日の出馬表は前日までに入っている= 実測。画面のトップは auction_today が今日でなければ auction_next を使う)。

value= {built, date, rows:[{track, no, umaban, name, post_time, note, sales:[{date, source, item_id, price, sold,
        category, url, runs_after, first_after}]}]}。rows は取引が 1 件以上ある出走だけ・sales は新しい順。
⛔note= nar_runs の finish_note(無ければ margin)の字そのまま(取消・除外の読み取りは画面)。
⛔開催が無い日も rows=[] を**書く**(前日の残りを使わせない)。⛔読み取りに失敗したら書かない(前の値が残る)。
10/30 通信量: 同じ 1 本で件数だけの小さい鍵 '<鍵>_n'= {built, date, n, m} も書く(トップは 211 KB の行でなく件数だけ読む)。
  数え方は画面の auctionTodayCounts / auctionFirstAfter と同じ(count_first_after)。/auction は今までどおり大きい鍵を読む。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from noken_debuts import enc, load_env, log, req, rows  # noqa: E402

SALE_COLS = "horse_name,auction_date,source,item_id,price,sold,category,url,runs_after,first_after"
PAGE = 1000


def all_rows(base, key, path, order):
    """⛔1 日の出馬表は 1000 行を超える日がある= 一意の並びで取り切るまで続きを読む"""
    out, off = [], 0
    while True:
        part = rows(base, key, f"{path}&order={order}&limit={PAGE}&offset={off}")
        out += part
        if len(part) < PAGE:
            return out
        off += PAGE


def post_time(v):
    m = re.match(r"^(\d{1,2}):?(\d{2})$", str(v or "").strip())      # '1310' 型(区切りなし)も '13:10' も受ける
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def build(base, key, today):
    races = all_rows(base, key, f"/rest/v1/nar_races?select=track,race_no,post_time&race_date=eq.{today}",
                     "track.asc,race_no.asc")
    runs = all_rows(base, key, "/rest/v1/nar_runs?select=track,race_no,runner_number,horse_name,finish_note,margin"
                               f"&race_date=eq.{today}", "track.asc,race_no.asc,runner_number.asc")
    ht = {(str(r["track"]), int(r["race_no"])): post_time(r.get("post_time")) for r in races}
    names = sorted({str(r.get("horse_name") or "") for r in runs} - {""})
    log(f"{today} レース {len(races)}・出走 {len(runs)}行・馬名 {len(names)}頭")
    sales = {}
    for i in range(0, len(names), 80):          # ⛔数百頭まとめると URL が長すぎる(画面の getAuctionFlags と同じ 80 頭)
        inlist = ",".join('"' + n.replace('"', "") + '"' for n in names[i:i + 80])
        for s in all_rows(base, key, f"/rest/v1/auction_sales?select={SALE_COLS}&horse_name=in.({enc(inlist)})",
                          "horse_name.asc,auction_date.desc,source.asc,item_id.asc"):
            sales.setdefault(str(s["horse_name"]), []).append({
                "date": s.get("auction_date"), "source": s.get("source"), "item_id": s.get("item_id"),
                "price": s.get("price"), "sold": bool(s.get("sold")), "category": s.get("category"), "url": s.get("url"),
                "runs_after": s.get("runs_after"), "first_after": s.get("first_after")})
    out, seen = [], set()
    for r in runs:
        name, k = str(r.get("horse_name") or ""), (str(r["track"]), int(r["race_no"]), int(r["runner_number"]))
        if not sales.get(name) or k in seen:
            continue
        seen.add(k)
        out.append({"track": k[0], "no": k[1], "umaban": k[2], "name": name, "post_time": ht.get(k[:2]),
                    "note": (str(r.get("finish_note") or "").strip() or str(r.get("margin") or "").strip() or None),
                    "sales": sorted(sales[name], key=lambda s: str(s["date"] or ""), reverse=True)})
    return out


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOT_STARTER_RE = re.compile(r"(取消|除外)")


def count_first_after(out, today):
    """トップの件数(画面 js/pages/top.js auctionTodayCounts と js/data.js parseAuctionToday・auctionFirstAfter と同じ)。
    n= 一番新しい取引がセリ市場でなく取消・除外でない出走・m= そのうち落札後の初出走(落札 2022-11-01 以降・今日より前・
    落札後 0 走か落札後の最初の出走が今日)。⛔日付の読めない取引は先に落とす(画面と同じ)"""
    n = m = 0
    for x in out:
        sales = [s for s in (x.get("sales") or []) if s and DATE_RE.match(str(s.get("date") or ""))]
        if not sales or sales[0].get("source") in ("jrha", "hba") or NOT_STARTER_RE.search(str(x.get("note") or "")):
            continue
        n += 1
        a = sales[0]
        d, fa = str(a["date"]), str(a.get("first_after") or "")
        if a.get("sold") and "2022-11-01" <= d < today and (a.get("runs_after") == 0 or fa == today):
            m += 1
    return {"n": n, "m": m}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="表示だけ(既定と同じ)")
    ap.add_argument("--date", help="YYYY-MM-DD(既定= JST の今日・夜の回は翌日)")
    ap.add_argument("--key", default="auction_today", choices=["auction_today", "auction_next"])
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or ("" if a.apply else os.environ.get("SUPABASE_ANON_KEY", ""))
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
    today = a.date or str(dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date())
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", today):
        log("--date は YYYY-MM-DD"); return 2
    try:
        out = build(base, key, today)
    except Exception as e:  # ⛔読み取りに失敗したら書かない(前の値が残る= 画面は built の日付で判定)
        log(f"読み取りに失敗(書かない) {type(e).__name__}"); return 1
    not_sale = sum(1 for x in out if x["sales"][0]["source"] not in ("jrha", "hba"))
    log(f"取引のある出走 {len(out)}行(一番新しい取引がセリ市場でない {not_sale}・発走時刻なし "
        f"{sum(1 for x in out if not x['post_time'])}・note あり {sum(1 for x in out if x['note'])})")
    built = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    value = {"built": built, "date": today, "rows": out}
    small = {"built": built, "date": today, **count_first_after(out, today)}
    log(f"件数の鍵 {a.key}_n: n={small['n']}・m={small['m']}")
    if not a.apply or a.dry_run:
        log(f"ドライラン(--apply で書く・鍵 {a.key}・{today})"); return 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    # ⛔2 つの鍵は同じ 1 本で書く(片方だけ新しい状態を作らない)
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": a.key, "value": value, "updated_at": now},
                            {"key": a.key + "_n", "value": small, "updated_at": now}], ensure_ascii=False).encode("utf-8"))
    log(f"nar_meta/{a.key}・{a.key}_n({today})更新 {st}")
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
