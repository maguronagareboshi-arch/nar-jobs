"""Supabase REST の読み(GET)を gzip で受け取る共通部品(2026-11-06 送信量対策)。

Python の urllib は既定で圧縮を頼まない → 便の受け取りが無圧縮で 4〜8 倍の送信量になっていた。
GET のときだけ 'Accept-Encoding: gzip' を足し、応答が gzip なら解凍して元のバイト列を返す。
POST/PATCH など(送る側)は見出しを足さず、そのまま読む。
例外・時間切れ・再試行は呼び手の今のまま(ここでは再試行しない)。HTTPError の本文も解凍して投げ直す。
標準ライブラリだけ。
"""
import gzip
import io
import urllib.error
import urllib.request


def _decode(body, headers):
    enc = ((headers.get("Content-Encoding") if headers is not None else None) or "").strip().lower()
    if enc == "gzip" and body:
        return gzip.decompress(body)
    return body


def _want_gzip(req):
    if req.get_method() != "GET":
        return
    if not req.has_header("Accept-encoding"):
        req.add_header("Accept-Encoding", "gzip")


def open_read(req, timeout):
    """urlopen して (status, headers, 解凍済みの本文 bytes) を返す。"""
    _want_gzip(req)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, r.headers, _decode(body, r.headers)
    except urllib.error.HTTPError as e:
        enc = ((e.headers.get("Content-Encoding") if e.headers is not None else None) or "").strip().lower()
        if enc != "gzip":
            raise
        try:
            body = _decode(e.read(), e.headers)
        except Exception:                                            # noqa: BLE001
            raise e from None
        raise urllib.error.HTTPError(e.url, e.code, e.msg, e.headers, io.BytesIO(body)) from None


def read(req, timeout):
    """urlopen して解凍済みの本文 bytes だけ返す。"""
    return open_read(req, timeout)[2]
