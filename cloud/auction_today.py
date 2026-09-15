# -*- coding: utf-8 -*-
"""§181 今日走るオークション取引馬 —— 今日の出馬表×取引(auction_sales)→ nar_meta 'auction_today'。

トップの 1 行と /auction の発走時刻が読む。**判定(初出走・除外・頭数)は書かない**= 画面の 1 か所で決める。
  python cloud/auction_today.py --env pipeline/.env.nar            # ドライラン(表示だけ・匿名キーでも動く)
  python cloud/auction_today.py --env pipeline/.env.nar --apply    # 書き込み
workflow(nar-refresh.yml)では noken_debuts.py の直後に回す(30 分ごと= 取消が 30 分以内に反映・冪等)。

value= {built, date, rows:[{track, no, umaban, name, post_time, note, sales:[{date, source, item_id, price, sold,
        category, url, runs_after, first_after}]}]}。rows は取引が 1 件以上ある出走だけ・sales は新しい順。
⛔note= nar_runs の finish_note(無ければ margin)の字そのまま(取消・除外の読み取りは画面)。
⛔開催が無い日も rows=[] を**書く**(前日の残りを使わせない)。⛔読み取りに失敗したら書かない(前の値が残る)。
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="表示だけ(既定と同じ)")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or ("" if a.apply else os.environ.get("SUPABASE_ANON_KEY", ""))
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
    today = str(dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date())
    try:
        out = build(base, key, today)
    except Exception as e:  # ⛔読み取りに失敗したら書かない(前の値が残る= 画面は built の日付で判定)
        log(f"読み取りに失敗(書かない) {type(e).__name__}"); return 1
    not_sale = sum(1 for x in out if x["sales"][0]["source"] not in ("jrha", "hba"))
    log(f"取引のある出走 {len(out)}行(一番新しい取引がセリ市場でない {not_sale}・発走時刻なし "
        f"{sum(1 for x in out if not x['post_time'])}・note あり {sum(1 for x in out if x['note'])})")
    value = {"built": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds"), "date": today, "rows": out}
    if not a.apply:
        log("ドライラン(--apply で書く)"); return 0
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": "auction_today", "value": value,
                             "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}], ensure_ascii=False).encode("utf-8"))
    log(f"nar_meta/auction_today 更新 {st}")
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
