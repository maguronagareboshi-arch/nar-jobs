"""南関公式(nankankeiba.com)を本番 DB(東京)の pg_net 経由で取る(2026-11-03)。

10/31 ごろから南関公式が GitHub ランナー(国外)を 403 で拒む。DB からは 200(§195d 大井と同じ)。
RPC jp_fetch_start(urls)→ id を受け取り、jp_fetch_result(ids) を返事が来るまで見る(pipeline/sql/jp_fetch_pgnet_20261103.sql)。
中身は元のバイト(Shift_JIS のまま)で返す。使う側は今までどおり cp932 で読む。

via_db(url) は「DB 経由にする先か」。NK_VIA_DB=0 で直に取る(手元の PC など国内から回すとき)。
"""
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

HOSTS = ("https://www.nankankeiba.com/",)


def via_db(url):
    return url.startswith(HOSTS) and os.environ.get("NK_VIA_DB", "1") != "0" \
        and bool(os.environ.get("SUPABASE_URL")) and bool(os.environ.get("SUPABASE_SERVICE_KEY"))


def _rpc(name, body, timeout=30):
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(f"{base}/rest/v1/rpc/{name}", data=json.dumps(body).encode(),
                                 headers={"apikey": key, "Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch(url, timeout=40):
    """元のバイトを返す。先方の 4xx/5xx は urllib.error.HTTPError(直に取ったときと同じ形)、返事が来なければ TimeoutError。"""
    rid = _rpc("jp_fetch_start", {"p_urls": [url]})[0]
    end = time.monotonic() + timeout
    wait = 0.3
    while time.monotonic() < end:
        time.sleep(wait)
        wait = min(wait * 1.5, 2.0)
        rows = _rpc("jp_fetch_result", {"p_ids": [rid]})
        if not rows:
            continue
        r = rows[0]
        if r.get("err") or r.get("status") is None:
            raise urllib.error.URLError(f"pg_net: {r.get('err')}")
        body = base64.b64decode(r.get("body_b64") or "")
        if r["status"] >= 400:
            raise urllib.error.HTTPError(url, r["status"], "via DB", None, io.BytesIO(body))
        return body
    raise TimeoutError(f"pg_net の返事が {timeout} 秒で来ない: {url}")


class _Resp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content


def session_get(session, url, timeout=30):
    """requests の session.get(url) の代わり(2026-11-08)。DB 経由にする先なら pg_net で取り、status_code・content だけの返事を返す。
    先方の 4xx/5xx はその status、返事が来ない・pg_net の誤りは requests.ConnectionError(直に取ったときと同じ扱いになる)。"""
    if not via_db(url):
        return session.get(url, timeout=timeout)
    import requests
    try:
        return _Resp(200, fetch(url, timeout=max(timeout, 40)))
    except urllib.error.HTTPError as e:
        return _Resp(e.code, b"")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise requests.ConnectionError(str(e))
