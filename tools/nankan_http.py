# -*- coding: utf-8 -*-
"""§196b 下調べ用の nankankeiba 取得(手元だけ)。1.8 秒間隔・cp932・data/cache_nankan/ にキャッシュ。
⛔ uma_info(いまの値)もこの下調べでは 1 回だけ読んでキャッシュする(下調べの間に値が動くと突合がぶれる)。
UA は日次の便(cloud/nankan_points.py)と同じ。取得の本数と所要は STATS に数える(HANDOFF の「通信」)。
"""
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cloud"))
sys.path.insert(0, str(HERE.parent / "pipeline"))
BASE = "https://www.nankankeiba.com"
CACHE = HERE.parent / "data" / "cache_nankan"
SLEEP = 1.8
STATS = {"requests": 0, "seconds": 0.0, "errors": 0, "cache_hits": 0}
_last = [0.0]


def _ua():
    try:
        import nankan_points
        return nankan_points.UA
    except Exception:  # noqa: BLE001
        return "nar-jobs-recon/1.0"


UA = _ua()


def get(path, refresh=False):
    """path= '/uma_info/123.do' など。キャッシュがあれば読まない。存在しない等は '' を返す。"""
    f = CACHE / path.strip("/").replace("/", "__")
    if f.exists() and not refresh:
        STATS["cache_hits"] += 1
        return f.read_bytes().decode("cp932", errors="replace")
    gap = time.monotonic() - _last[0]
    if gap < SLEEP:
        time.sleep(SLEEP - gap)
    t0 = time.monotonic()
    body = b""
    try:
        req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
    except Exception as e:  # noqa: BLE001
        STATS["errors"] += 1
        print("  GET ERR", path, type(e).__name__, str(e)[:80], flush=True)
    finally:
        _last[0] = time.monotonic()
        STATS["requests"] += 1
        STATS["seconds"] += time.monotonic() - t0
    if body:                                     # ⛔取れなかったページはキャッシュしない(次に取り直す)
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
    return body.decode("cp932", errors="replace")
