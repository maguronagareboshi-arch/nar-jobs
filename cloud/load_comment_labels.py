"""騎手コメントの分類(taxonomy v2・22,515 行)を本番 DB の nar_comment_labels へ入れる 1 回きりの台本(2026-10-31)。

- 入力: data/comment_labels_v2.jsonl.gz(1 行= {"id":"<16進 10 桁>","l":[...]})
- 表: public.nar_comment_labels(hid text 主キー, labels jsonb, model text, labeled_at timestamptz default now())
- id → hid、l → labels、model は固定文字列。on_conflict=hid の upsert を 1,000 行ずつ。何度流しても同じ(冪等)。
- --dry-run は件数を数えるだけ(鍵は要らない)。
- 鍵は環境変数(SUPABASE_URL / SUPABASE_SERVICE_KEY)。書き方は cloud/fix_weight_change.py と同じ。⛔鍵はログに出さない。
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "comment_labels_v2.jsonl.gz"
TABLE = "nar_comment_labels"
MODEL = "claude-opus-5-5 (manual read, taxonomy v2)"
BATCH = 1000
UA = "nar-jobs/1.0"


def log(msg):
    print(msg, flush=True)


def req(url, key, path, method="GET", body=None, prefer="resolution=merge-duplicates,return=minimal"):
    r = urllib.request.Request(url + path, data=body, method=method, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Content-Type": "application/json", "Prefer": prefer})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(r, timeout=90) as x:
                return x.status, x.read().decode("utf-8"), x.headers
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt == 0:
                time.sleep(3); continue
            return e.code, e.read().decode("utf-8")[:300], e.headers
        except Exception as e:  # noqa: BLE001
            if attempt == 0:
                time.sleep(3); continue
            return 0, str(e), {}


def read_rows(path):
    rows = {}
    bad = 0
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            o = json.loads(raw)
            hid = str(o.get("id", ""))
            labels = o.get("l")
            if len(hid) != 10 or any(c not in "0123456789abcdef" for c in hid) or not isinstance(labels, list):
                bad += 1; continue
            rows[hid] = labels  # 同じ hid が重なったら後の行(1 回の upsert に同じ鍵を 2 度入れない)
    return rows, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(SRC))
    ap.add_argument("--dry-run", action="store_true", help="件数を数えるだけ(書かない・鍵は要らない)")
    a = ap.parse_args()

    rows, bad = read_rows(a.file)
    n_lab = sum(len(v) for v in rows.values())
    log("読んだ行 %d(形の悪い行 %d・ラベル延べ %d・空ラベル %d)" % (
        len(rows), bad, n_lab, sum(1 for v in rows.values() if not v)))
    if a.dry_run:
        log("ドライラン(書き込みなし)。upsert 予定 %d 行・%d 束" % (len(rows), (len(rows) + BATCH - 1) // BATCH))
        return 0

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2

    send = [{"hid": h, "labels": l, "model": MODEL} for h, l in sorted(rows.items())]
    for i in range(0, len(send), BATCH):
        st, msg, _ = req(url, key, "/rest/v1/%s?on_conflict=hid" % TABLE, "POST",
                         json.dumps(send[i:i + BATCH], ensure_ascii=False).encode("utf-8"))
        if st not in (200, 201, 204):
            log("   投入 %s %s(%d 行目から)" % (st, msg, i)); return 1
        log("   %d / %d" % (min(i + BATCH, len(send)), len(send)))
    log("upsert 済み %d 行" % len(send))

    st, _, hd = req(url, key, "/rest/v1/%s?select=hid&limit=1" % TABLE, "GET", prefer="count=exact")
    rng = hd.get("Content-Range", "") if hd else ""
    log("表 %s の件数 %s(HTTP %s)" % (TABLE, rng.split("/")[-1] if "/" in rng else "?", st))
    return 0


if __name__ == "__main__":
    sys.exit(main())
