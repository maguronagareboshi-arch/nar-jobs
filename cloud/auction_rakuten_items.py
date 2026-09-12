# -*- coding: utf-8 -*-
"""§54.4b: 楽天サラオクの全史保全(2026-09-02。ユーザーの「URLに秘密があったりしない?」が正解だった)。

⛔#352: 「楽天は過去に戻れない」は**誤りだった**。トップに導線が無いだけで全商品が残存
  (/item/1=2016-09-08 の第1回〜/item/16934=今週。independentシステム移行時からの全部)。
⭐#357: **公開JSON API `GET /api/item/{id}` がある**(baseURL は __NUXT__.config.public.apiUrlClient)。
  HTML(30KB)+node評価が要らず、応答300ms・3KB。**欠番は HTTP 400**= 判定が明快(HTMLは200のまま空だった)。
  HTML経由と同一データであることを #1766 で実測突合(落札740000/入札32行/user_bid 7/description 3201字/画像6)。

取れるもの(=閲覧者への武器):
  current_price(落札価格)・start_price・start/end_datetime・bid_history全行(hammer_flag=1が落札bid)・
  user_bid(ニックネーム+自動入札の上限)・images・seller・**description**
  = 「本馬について」の開示文。⭐**故障歴・悪癖・病歴/手術歴・ゲート試験/調教再審査歴・南関東転入可否・
  在厩場所・預託料**がここに書かれる(業務規程6条=未公表なら落札者が契約解除できる=**開示の信頼度が高い**)。

実行:
  py -3.12 -X utf8 cloud/auction_rakuten_items.py --ids 1 1766 16934 999999   # 試運転
  py -3.12 -X utf8 cloud/auction_rakuten_items.py --backfill                  # 1から上端まで(約35分)
  py -3.12 -X utf8 cloud/auction_rakuten_items.py --weekly                    # 新規+未終了の取り直し
書き先: cloud/data/auction/rakuten_items/{id//1000:03d}xxx.jsonl.gz(500件ブロックごとに1メンバー追記)
        + state.json。⛔旧 .jsonl も読む(移行期の混在を許す)
終了コード: 0 完了 / 1 一部失敗 / 2 前提失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "auction" / "rakuten_items"
STATE = OUT / "state.json"
JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; nar-jobs/1.0)"
API = "https://auction.keiba.rakuten.co.jp/api/item/"

WORKERS = 8
RATE = 8.0          # 1秒あたりの上限(全体)。⛔429/5xx を受けたら自動で半分に落とす
BLOCK = 500         # このID数ずつ処理して書き出し+state保存(=途中で殺されてもここまでは残る)
MISS_STOP = 60      # 連続欠番がこれだけ続いたら上端


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


class Limiter:
    """全スレッド共通の速度制限。サーバに押し返されたら自分から遅くする"""

    def __init__(self, rate):
        self.min_gap = 1.0 / rate
        self.next_at = 0.0
        self.lock = threading.Lock()
        self.backoffs = 0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_at)
            self.next_at = t + self.min_gap
        d = t - time.monotonic()
        if d > 0:
            time.sleep(d)

    def slow_down(self):
        with self.lock:
            if self.min_gap < 2.0:
                self.min_gap *= 2
                self.backoffs += 1
                log(f"  ⚠ サーバに押し返された→速度を半分に(いま {1 / self.min_gap:.1f} req/s)")


LIM = Limiter(RATE)


def fetch_item(item_id, tries=3):
    """→ dict(item) / 'miss' / 例外。⛔400=欠番(実測)・429/5xx は減速して再試行"""
    req = urllib.request.Request(f"{API}{item_id}",
                                 headers={"User-Agent": UA, "Accept-Encoding": "gzip",
                                          "Accept": "application/json"})
    last = None
    for n in range(tries):
        LIM.wait()
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            j = json.loads(raw.decode("utf-8"))
            item = ((j or {}).get("data") or {}).get("item")
            return item if item else "miss"
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return "miss"          # 欠番。決定的なので再試行しない
            if e.code in (429, 500, 502, 503, 504):
                LIM.slow_down()
            last = e
        except Exception as e:
            last = e
        if n < tries - 1:
            time.sleep(1.5 * (n + 1))
    raise RuntimeError(f"{type(last).__name__}: {str(last)[:90]}")


# ---------------------------------------------------------------- 保存

def shard_of(item_id):
    return f"{item_id // 1000:03d}xxx"


def load_have():
    """取得済み id 集合。.jsonl.gz と旧 .jsonl の両方を読む(読めない行は未取得扱い)"""
    have = set()
    if not OUT.exists():
        return have
    for f in sorted(list(OUT.glob("*xxx.jsonl.gz")) + list(OUT.glob("*xxx.jsonl"))):
        try:
            text = gzip.open(f, "rt", encoding="utf-8").read() if f.suffix == ".gz" \
                else f.read_text(encoding="utf-8")
        except (OSError, EOFError, gzip.BadGzipFile):
            continue
        for line in text.splitlines():
            if line.strip():
                try:
                    have.add(json.loads(line)["id"])
                except json.JSONDecodeError:
                    continue
    return have


def load_records(min_id=0):
    """min_id 以上のレコード(同idは後の行が勝つ)"""
    recs = {}
    if not OUT.exists():
        return recs
    for f in sorted(list(OUT.glob("*xxx.jsonl.gz")) + list(OUT.glob("*xxx.jsonl"))):
        try:
            text = gzip.open(f, "rt", encoding="utf-8").read() if f.suffix == ".gz" \
                else f.read_text(encoding="utf-8")
        except (OSError, EOFError, gzip.BadGzipFile):
            continue
        for line in text.splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r["id"] >= min_id:
                    recs[r["id"]] = r
    return recs


def flush(records):
    """シャードごとに gzip メンバーを1つ追記(=ブロック単位でよく縮む・追記でも読める)"""
    OUT.mkdir(parents=True, exist_ok=True)
    by_shard = {}
    for r in records:
        by_shard.setdefault(shard_of(r["id"]), []).append(r)
    for shard, rows in by_shard.items():
        rows.sort(key=lambda r: r["id"])
        body = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)
        with gzip.open(OUT / f"{shard}.jsonl.gz", "at", encoding="utf-8") as f:
            f.write(body)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"max_id": 0, "misses": [], "retry": []}


def save_state(st):
    OUT.mkdir(parents=True, exist_ok=True)
    st["updated_at"] = dt.datetime.now(JST).isoformat(timespec="seconds")
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 収集

def run_block(ids):
    """ids を並列に取得 → (records, misses, fails)"""
    recs, miss, fail = [], [], []
    now = dt.datetime.now(JST).isoformat(timespec="seconds")

    def one(i):
        try:
            return i, fetch_item(i), None
        except Exception as e:
            return i, None, e

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, res, err in ex.map(one, ids):
            if err is not None:
                log(f"  ⚠ #{i}: {err}")
                fail.append(i)
            elif res == "miss":
                miss.append(i)
            else:
                recs.append({"id": i, "fetched_at": now, "item": res})
    recs.sort(key=lambda r: r["id"])
    return recs, sorted(miss), sorted(fail)


def crawl_up(start, skip, st):
    """start から BLOCK 件ずつ上へ。連続 MISS_STOP 欠番で上端とみなす"""
    got_n, miss_all, fail_all, streak, cur = 0, [], [], 0, start
    t0 = time.monotonic()
    while streak < MISS_STOP:
        ids = [i for i in range(cur, cur + BLOCK) if i not in skip]
        cur += BLOCK
        if not ids:
            continue
        recs, miss, fail = run_block(ids)
        flush(recs)
        got_n += len(recs)
        miss_all += miss
        fail_all += fail
        # 連続欠番は「このブロックの末尾から下って何個続いたか」で数える(取れた物が1つでもあれば0に戻る)
        got_ids = {r["id"] for r in recs}
        s = 0
        for i in reversed(ids):
            if i in got_ids or i in fail:
                break
            s += 1
        streak = (streak + s) if s == len(ids) else s
        st["max_id"] = max([st["max_id"]] + [r["id"] for r in recs])
        st["misses"] = sorted(m for m in set(st["misses"]) | set(miss_all) if m <= st["max_id"])
        st["retry"] = sorted(set(st["retry"]) | set(fail_all))
        save_state(st)
        rate = got_n / max(time.monotonic() - t0, 1e-9)
        log(f"  〜#{cur - 1}: 取得{got_n} 欠番{len(miss_all)} 失敗{len(fail_all)}"
            f" 連続欠番{streak} ({rate:.1f}件/秒)")
    return got_n, miss_all, fail_all


def stale_ids(st):
    """取得した時点でまだ終わっていなかった商品(=価格が確定前)→ 取り直す(#353)"""
    recs = load_records(max(st["max_id"] - 300, 1))
    out = []
    for i, r in sorted(recs.items()):
        end = str((r.get("item") or {}).get("end_datetime") or "")
        fetched = str(r.get("fetched_at") or "")[:19].replace("T", " ")
        if not end or end >= fetched:
            out.append(i)
    return out[:400]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", type=int)
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--weekly", action="store_true")
    ap.add_argument("--start", type=int, default=1)
    a = ap.parse_args()
    st = load_state()

    if a.ids:
        recs, miss, fail = run_block(a.ids)
        for r in recs:
            it = r["item"]
            log(f"#{r['id']}: {str(it.get('name'))[:26]} 落札={it.get('current_price'):,} "
                f"入札{len(it.get('bid_history') or [])}行 終了={it.get('end_datetime')}")
        if miss:
            log(f"欠番: {miss}")
        flush(recs)
        return 1 if fail else 0

    if a.backfill or a.weekly:
        have = load_have()
        log(f"取得済み {len(have)}件 / max_id={st['max_id']} / 既知欠番{len(st['misses'])}")
        redo_n = 0
        if a.weekly:
            redo = stale_ids(st)
            if redo:
                recs, _, _ = run_block(redo)
                flush(recs)
                redo_n = len(recs)
                log(f"取り直し(取得時に未終了だった商品): {redo_n}/{len(redo)}件")
        skip = have | set(st["misses"])
        start = a.start if a.backfill else max([st["max_id"]] + list(have) + [0]) + 1
        got, miss, fail = crawl_up(start, skip, st)
        st["retry"] = sorted(set(fail))
        save_state(st)
        log(f"{'backfill' if a.backfill else 'weekly'}: 新規{got} 取り直し{redo_n} 欠番{len(miss)} "
            f"失敗{len(fail)} 累計{len(have) + got} max_id={st['max_id']}")
        return 1 if fail else 0

    log("モード指定なし(--ids / --backfill / --weekly)")
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
