# -*- coding: utf-8 -*-
"""§54.4: 楽天サラブレッドオークションの保全収集(2026-09-02 設計・承認)。

⛔楽天は過去回のページを持たない(終了後1〜2日で次回一覧に置き換わる・Waybackは月1断面のみ=2026-09-02実測)。
  だから**前向きに毎回保全する**。表示は別フェーズ(§54.4の手3)・ここではデータを残すことだけが仕事。

データ源 = https://auction.keiba.rakuten.co.jp/top の window.__NUXT__(SSR埋め込み・XHRなし)。
  - getAuctionItems.data[] … 出品一覧(グループ→umaList→list)。item = {itemId, topItemName(完全な馬名),
    offererName, basicInfoUrl(JBIS URL=恒久ID), pdfUrl(血統表・URLに開催日 YYMMDD が入る), sex, age,
    birthday(育成馬のみ), price(現役のみ=総賞金表示)}
  - getHorseItems.data.items … 開催中のライブ商品(価格・入札)。開催外は []。
    ⛔形は開催中しか見えない=初回取得(2026-09-04木 22時台)までパースを決め打ちしない。生を全部残す。
  - getPickupHorse.data.title … 「第691回サラブレッドオークション」= 回番号の出どころ

実行(開催日= 毎週 木・日 12:00〜21:00/21:30/22:00+自動延長):
  py -3.12 -X utf8 cloud/auction_rakuten.py --phase list    # 開催日朝: 出品一覧+JBIS ID を保存
  py -3.12 -X utf8 cloud/auction_rakuten.py --phase close   # 22:08/22:38/23:03 JST: 価格を3回撮る(自動延長よけ)
  py -3.12 -X utf8 cloud/auction_rakuten.py                 # phase 自動(JST 12時前=list / 以後=close)
書き先: cloud/data/auction/rakuten/{YYMMDD}_list.json / {YYMMDD}_close.json(passes[]に追記)
        + 同名 *_nuxt_*.json.gz(__NUXT__.data の生=パーサが壊れても情報は残る)
終了コード: 0 正常(開催なしを含む) / 2 取得失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "auction" / "rakuten"
JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; unified-viewer/1.0; +maguronagareboshi@gmail.com)"
URL = "https://auction.keiba.rakuten.co.jp/top"


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def fetch_nuxt():
    """ページを開いて __NUXT__.data(評価済みオブジェクト)を丸ごと取る"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA)
        pg.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        pg.goto(URL, wait_until="load", timeout=60_000)
        pg.wait_for_timeout(1500)
        data = pg.evaluate("() => JSON.parse(JSON.stringify((window.__NUXT__ && window.__NUXT__.data) || null))")
        b.close()
    if not data:
        raise RuntimeError("__NUXT__.data が取れない(ページ構造が変わった?)")
    return data


def listing_items(data):
    """getAuctionItems → フラットな馬リスト。⛔フィールドは生のまま残す(潰さない)"""
    out = []
    for g in (data.get("getAuctionItems") or {}).get("data") or []:
        for uma in g.get("umaList") or []:
            for it in uma.get("list") or []:
                rec = dict(it)
                rec["group_title"] = uma.get("topItemTitle")
                out.append(rec)
    return out


def round_ymd(items, live_items):
    """開催日 YYMMDD は血統表PDFのURLから(260903_horse_01)。listing→live の順で探す"""
    for it in items + live_items:
        m = re.search(r"/(\d{6})_horse_", str(it.get("pdfUrl") or "") + json.dumps(it, ensure_ascii=False))
        if m:
            return m.group(1)
    return f"{dt.datetime.now(JST):%y%m%d}"


def save_gz(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["list", "close"], default=None)
    a = ap.parse_args()
    now = dt.datetime.now(JST)
    phase = a.phase or ("list" if now.hour < 12 else "close")

    try:
        data = fetch_nuxt()
    except Exception as e:
        log(f"取得失敗: {e}")
        return 2

    items = listing_items(data)
    live = ((data.get("getHorseItems") or {}).get("data") or {}).get("items") or []
    pickup = ((data.get("getPickupHorse") or {}).get("data") or {}) or {}
    m = re.search(r"第(\d+)回", str(pickup.get("title") or ""))
    round_no = int(m.group(1)) if m else None
    if not items and not live:
        log("出品も開催中商品も無し(休止週?)→何も書かない")
        return 0
    ymd = round_ymd(items, live)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now.isoformat(timespec="seconds")

    if phase == "list":
        obj = {"source": "auction.keiba.rakuten.co.jp", "round": round_no, "ymd": ymd,
               "fetched_at": stamp, "count": len(items), "items": items}
        (OUT / f"{ymd}_list.json").write_text(
            json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        save_gz(OUT / f"{ymd}_list_nuxt.json.gz", data)
        log(f"list 保存: 第{round_no}回 {ymd} {len(items)}頭")
    else:
        path = OUT / f"{ymd}_close.json"
        obj = {"source": "auction.keiba.rakuten.co.jp", "round": round_no, "ymd": ymd, "passes": []}
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
        obj["passes"].append({"fetched_at": stamp, "live_count": len(live), "live_items": live})
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        save_gz(OUT / f"{ymd}_close_nuxt_{now:%H%M}.json.gz", data)
        log(f"close 保存: 第{round_no}回 {ymd} live {len(live)}件(pass {len(obj['passes'])})")
        if not live:
            log("⚠ live_items が空(終了直後に片付いた/開催外)。他の pass が撮れていれば良し")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
