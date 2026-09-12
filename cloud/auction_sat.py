# -*- coding: utf-8 -*-
"""§54.4: サタデーオークション(sat-auction.jp・毎週土曜)の保全収集(2026-09-02 設計・承認)。

事実(2026-09-02実測): /auction/{通し番号} の馬ページは**全過去分が公開のまま残っている**
  (#108=2024-04-06終了・#1169=2026-01-31終了を実確認)。落札価格・入札数・入札履歴・落札候補者・
  販売申込者・血統・在厩場所(=移籍元)まで載る。公式フッターに「過去の落札馬」導線あり=結果公開は運営の意図。
⛔ただし「残っている」は「残し続ける約束」ではない=消されたら終わりなので今のうちに全量保全する。
⛔API(/api/public/refresh-item 等)は直POSTだと401(アプリがトークンを付ける)。ページを開いて
  **サイト自身の通信を傍受**する(Playwright response listener)。DOMテキストも保険で丸ごと残す。
⛔/stock /tender(在厩販売・テンダー)は対象外で開始(欲しくなったら別判断)。

実行:
  py -3.12 -X utf8 cloud/auction_sat.py --ids 108 1169 999999   # 試運転(実在2+欠番1)
  py -3.12 -X utf8 cloud/auction_sat.py --backfill              # 1から連続40欠番まで全量(約80分)
  py -3.12 -X utf8 cloud/auction_sat.py --weekly                # 既知max+1から新規分+未終了の再取得
書き先: cloud/data/auction/sat/items.jsonl(1行1取得・追記のみ・同idは後の行が最新) / state.json
終了コード: 0 正常 / 1 一部失敗 / 2 前提失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "auction" / "sat"
ITEMS = OUT / "items.jsonl"
STATE = OUT / "state.json"
JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; nar-jobs/1.0)"
BASE = "https://www.sat-auction.jp/auction/"
SLEEP = 1.0
MISS_STOP = 40   # 連続欠番でここまで来たら「上端」とみなす


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"max_id": 0, "misses": [], "retry": []}


def save_state(st):
    OUT.mkdir(parents=True, exist_ok=True)
    st["updated_at"] = dt.datetime.now(JST).isoformat(timespec="seconds")
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def load_items():
    """items.jsonl → {id: record}(後の行が勝つ)"""
    out = {}
    if ITEMS.exists():
        for line in ITEMS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue   # 途中で殺された切れ端行。読めない=未取得扱い→次回そのidを取り直す
                out[r["id"]] = r
    return out


def append_item(rec):
    OUT.mkdir(parents=True, exist_ok=True)
    with ITEMS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def _unwrap(obj):
    """APIは JSON化した Node Buffer(zlib圧縮JSON)を返す(2026-09-02実測: {"type":"Buffer","data":[120,156,...]})。
    クライアントJSが解凍している。こちらも解凍して中身のJSONにする。読めなければ生のまま返す(潰さない)"""
    try:
        if isinstance(obj, dict) and obj.get("type") == "Buffer" and isinstance(obj.get("data"), list):
            return json.loads(zlib.decompress(bytes(obj["data"])).decode("utf-8"))
    except Exception:
        pass
    return obj


def fetch_one(pg, lot_id):
    """1ページ取得 → record か 'miss' か例外。apiはサイト自身の /api/public/ 通信の傍受"""
    captured = {}

    def on_response(res):
        u = res.url
        if "/api/public/refresh-item" in u or "/api/public/get-auction-item" in u:
            try:
                captured["item"] = _unwrap(res.json())
            except Exception:
                pass

    pg.on("response", on_response)
    try:
        pg.goto(f"{BASE}{lot_id}", wait_until="networkidle", timeout=45_000)
        pg.wait_for_timeout(700)
        url = pg.url
        title = pg.title()
        if "/auction/" not in url or title.startswith("サタデーオークション"):
            # 欠番は /index?filter=... へ飛ばされ、題名も汎用に戻る(2026-09-02実測)。
            # ⛔ただし一時的な弾き(リダイレクト/描画前)も同じ見た目になる=呼び出し側で再試行してから確定する
            return ("miss", f"url={url} title={title[:40]}")
        text = pg.evaluate("() => (document.querySelector('main')||document.body).innerText")
        norm = re.sub(r"\s+", " ", text)
        ended = bool(re.search(r"残り時間\s*終了", norm)) or None
        return {"id": lot_id, "url": url, "fetched_at": dt.datetime.now(JST).isoformat(timespec="seconds"),
                "title": title.split("｜")[0], "ended": ended, "api": captured.get("item"), "text": text}
    finally:
        pg.remove_listener("response", on_response)


def fetch_verified(pg, lot_id):
    """欠番は3秒置いて2回目でだけ確定する(2026-09-02: 実在の#108/#1169が一時欠番に化けた実測への防御)"""
    rec = fetch_one(pg, lot_id)
    if isinstance(rec, tuple):
        time.sleep(3)
        rec2 = fetch_one(pg, lot_id)
        if isinstance(rec2, tuple):
            log(f"  欠番確定 #{lot_id}({rec2[1]})")
            return "miss"
        return rec2
    return rec


def crawl(ids, label):
    """ids を順に取得して追記。戻り= (取れた, 欠番, 失敗)"""
    from playwright.sync_api import sync_playwright
    got, miss, fail = [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA)
        pg.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        for n, lot_id in enumerate(ids):
            try:
                rec = fetch_verified(pg, lot_id)
            except Exception as e:
                log(f"  ⚠ #{lot_id}: {type(e).__name__} {str(e)[:80]}")
                fail.append(lot_id)
                time.sleep(SLEEP)
                continue
            if rec == "miss":
                miss.append(lot_id)
            else:
                append_item(rec)
                got.append(lot_id)
            if (n + 1) % 25 == 0:
                log(f"  {label} {n + 1}/{len(ids)}: 取得{len(got)} 欠番{len(miss)} 失敗{len(fail)}")
            time.sleep(SLEEP)
        b.close()
    return got, miss, fail


def probe_up(start, known_miss, limit):
    """start から上へ、連続 MISS_STOP 欠番まで番号を作る(既知欠番は数に入れず再訪もしない)"""
    from playwright.sync_api import sync_playwright
    got, miss, fail = [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA)
        pg.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        lot_id, streak, done = start, 0, 0
        while streak < MISS_STOP and (not limit or done < limit):
            if lot_id in known_miss:
                lot_id += 1
                continue
            try:
                rec = fetch_verified(pg, lot_id)
            except Exception as e:
                log(f"  ⚠ #{lot_id}: {type(e).__name__} {str(e)[:80]}")
                fail.append(lot_id)
                streak = 0   # 失敗は欠番の証拠にしない(上端の見切りを早まらない)
                lot_id += 1
                done += 1
                time.sleep(SLEEP)
                continue
            if rec == "miss":
                miss.append(lot_id)
                streak += 1
            else:
                append_item(rec)
                got.append(lot_id)
                streak = 0
            done += 1
            if done % 25 == 0:
                log(f"  probe #{lot_id}: 取得{len(got)} 欠番{len(miss)} 失敗{len(fail)}")
            lot_id += 1
            time.sleep(SLEEP)
        b.close()
    return got, miss, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", type=int, help="試運転: この番号だけ取る")
    ap.add_argument("--backfill", action="store_true", help="1から上端まで全量(取得済み・既知欠番は跳ばす)")
    ap.add_argument("--weekly", action="store_true", help="新規分+未終了の再取得+前回失敗の再試行")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="この回の最大取得ページ数(0=無制限)")
    a = ap.parse_args()
    st = load_state()
    have = load_items()

    if a.ids:
        got, miss, fail = crawl(a.ids, "ids")
        log(f"ids: 取得{got} 欠番{miss} 失敗{fail}")
        return 1 if fail else 0

    if a.backfill:
        known_miss = set(st["misses"]) | set(have.keys())   # 取得済みも再訪しない
        got, miss, fail = probe_up(a.start, known_miss, a.limit)
        st["retry"] = sorted(set(st["retry"]) | set(fail))
        st["max_id"] = max([st["max_id"]] + got + list(have.keys()))
        # ⛔上端(max_id)より上の欠番は「まだ発番されていないだけ」= 記憶すると未来の新ロットを先に殺す(#351)
        st["misses"] = sorted(m for m in set(st["misses"]) | set(miss) if m <= st["max_id"])
        save_state(st)
        log(f"backfill: 取得{len(got)} 欠番{len(miss)} 失敗{len(fail)} max_id={st['max_id']}")
        return 1 if fail else 0

    if a.weekly:
        # ①前回失敗の再試行 ②未終了(ended≠True)の再取得 ③max+1から上へ新規
        # ⛔ended の判定(正規表現)が万一壊れても週次が全量再取得に化けないよう、②は直近60番だけ見る
        recent = max([st["max_id"]] + list(have.keys()) + [0]) - 60
        redo = sorted(set(st["retry"]) | {i for i, r in have.items()
                                          if r.get("ended") is not True and i > recent})
        got1, miss1, fail1 = crawl(redo, "redo") if redo else ([], [], [])
        start = max([st["max_id"]] + list(have.keys()) + [0]) + 1
        got2, miss2, fail2 = probe_up(start, set(st["misses"]), a.limit)
        st["retry"] = sorted(set(fail1) | set(fail2))
        st["max_id"] = max([st["max_id"]] + got2 + [start - 1])
        # redo の miss は上書き扱いにしない。⛔上端より上の欠番は記憶しない(#351: 未来のIDを先に殺す)
        st["misses"] = sorted(m for m in set(st["misses"]) | set(miss2) if m <= st["max_id"])
        save_state(st)
        log(f"weekly: 再取得{len(got1)} 新規{len(got2)} 欠番{len(miss2)} 失敗{len(fail1) + len(fail2)} max_id={st['max_id']}")
        return 1 if (fail1 or fail2) else 0

    log("モード指定なし(--ids / --backfill / --weekly)")
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
