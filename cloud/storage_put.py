#!/usr/bin/env python3
"""監査 A3(2026-09-24): 本番表のバックアップ・利用者メモの書き出しを、公開 repo の成果物でなく
Supabase Storage の非公開バケット odds-archive(cloud/odds_archive.py と同じ・public=false)へ置く。

  put   --prefix backup/2026-09-24/ FILE...   上げる(同じ名前は上書き)→取り直して中身(sha256)が同じか確かめる。
        .gz でないファイルは gzip してから <名前>.gz で上げる(Content-Type は odds_archive と同じ application/gzip)。
  prune --root backup/ --days 30               root の下の YYYY-MM-DD フォルダのうち、JST 今日から days 日より古いものを消す。
        ⛔消すのは backup/ か viewer-notes/ の下だけ(odds_archive の刻みの書き出しには触らない)。

失敗(HTTP エラー・照合の不一致)は例外= rc 1 で便を赤くする(バックアップが無言で抜けないように)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(service_role・既存の secret)
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import sys
import urllib.request

BUCKET = "odds-archive"
UA = "nar-jobs storage_put (+https://nar.yukochi.com/)"
PRUNE_ROOTS = ("backup/", "viewer-notes/")
JST = dt.timezone(dt.timedelta(hours=9))


def log(msg):
    print(msg, flush=True)


def req(base, key, path, method="GET", body=None, headers=None, timeout=300):
    h = {"apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA}
    if headers:
        h.update(headers)
    r = urllib.request.Request(base + path, method=method, data=body, headers=h)
    with urllib.request.urlopen(r, timeout=timeout) as x:
        return x.status, x.read(), dict(x.headers)


def put(base, key, prefix, files):
    if not prefix.endswith("/") or prefix.startswith("/") or ".." in prefix:
        raise ValueError("prefix は 'xxx/' の形で: %r" % prefix)
    if not files:
        raise SystemExit("上げるファイルが 0 個")
    for f in files:
        data = open(f, "rb").read()
        name = os.path.basename(f)
        if not name.endswith(".gz"):
            data = gzip.compress(data, 6)
            name += ".gz"
        path = prefix + name
        req(base, key, "/storage/v1/object/%s/%s" % (BUCKET, path), "POST", data,
            {"Content-Type": "application/gzip", "x-upsert": "true"})
        _st, back, _h = req(base, key, "/storage/v1/object/%s/%s" % (BUCKET, path))
        if hashlib.sha256(back).hexdigest() != hashlib.sha256(data).hexdigest():
            raise RuntimeError("取り直した中身が違う: %s/%s" % (BUCKET, path))
        log("上げた %s/%s(%d bytes・照合 OK)" % (BUCKET, path, len(data)))


def list_names(base, key, prefix):
    body = json.dumps({"prefix": prefix, "limit": 1000, "offset": 0,
                       "sortBy": {"column": "name", "order": "asc"}}).encode("utf-8")
    _st, out, _h = req(base, key, "/storage/v1/object/list/%s" % BUCKET, "POST", body,
                       {"Content-Type": "application/json"})
    return json.loads(out or b"[]")


def prune(base, key, root, days):
    if root not in PRUNE_ROOTS:
        raise ValueError("消してよい root は %s だけ: %r" % (PRUNE_ROOTS, root))
    cut = dt.datetime.now(JST).date() - dt.timedelta(days=days)
    gone = 0
    for e in list_names(base, key, root):
        n = e.get("name") or ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", n) or dt.date.fromisoformat(n) >= cut:
            continue
        paths = [root + n + "/" + x["name"] for x in list_names(base, key, root + n + "/") if x.get("name")]
        if paths:
            body = json.dumps({"prefixes": paths}).encode("utf-8")
            req(base, key, "/storage/v1/object/%s" % BUCKET, "DELETE", body, {"Content-Type": "application/json"})
        gone += 1
        log("消した %s/%s%s/(%d 個)" % (BUCKET, root, n, len(paths)))
    log("prune: %s の %s より古い日付フォルダ %d 個を消した" % (root, cut.isoformat(), gone))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("put")
    p.add_argument("--prefix", required=True)
    p.add_argument("files", nargs="*")
    q = sub.add_parser("prune")
    q.add_argument("--root", required=True)
    q.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    if a.cmd == "put":
        put(base, key, a.prefix, a.files)
    else:
        prune(base, key, a.root, a.days)


if __name__ == "__main__":
    sys.exit(main())
