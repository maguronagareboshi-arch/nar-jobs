# -*- coding: utf-8 -*-
"""§237 馬体重増減の**減った回**を当て直す(手元だけ・既定はドライラン)。

公式 CSV の正規化が負の数を捨てていたため、本番 nar_runs.body_weight_change に負の行が 1 つも無かった。
cloud/nar_official_csv.py を直した後の正規化で**生 ZIP を読み直し**、負の行だけを当てる。

  py -3.12 -X utf8 cloud/fix_weight_change.py                      # ドライラン(年別・場別の内訳だけ)
  py -3.12 -X utf8 cloud/fix_weight_change.py --since 202501       # その月以降の ZIP だけ
  py -3.12 -X utf8 cloud/fix_weight_change.py --apply              # 本番へ upsert(⛔内訳を見てから)
  py -3.12 -X utf8 cloud/fix_weight_change.py --dump cloud/onetime/weight_change_minus.csv.gz   # 負の行を書き出す(通信 0)
  py -3.12 -X utf8 cloud/fix_weight_change.py --from-file cloud/onetime/weight_change_minus.csv.gz --apply  # 生 ZIP なしで当てる(Actions 用)

- 入力= 他場\\data\\nar_official_csv\\raw の生 ZIP(⛔読むだけ・絶対に書かない)・通信は本番 DB だけ。
- 送るのは **主キー 4 列 + body_weight_change** だけ(⛔他の列は送らない= 既存の値を上書きしない)。
- 送る前に nar_runs にその行があるか確かめ、**無い鍵は送らない**(⛔新しい行を作らない)。何度流しても同じ(冪等)。
- 鍵は環境変数か --env の .env(SUPABASE_URL / SUPABASE_SERVICE_KEY)。⛔鍵はログに出さない。
  ⚠nar の本番は pipeline の .env.nar(2026-09-20 実測= 他場 の .env は古いプロジェクトを指していた)。
終了コード: 0 正常 / 1 投入失敗 / 2 前提が無い
"""
import argparse
import collections
import csv
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from nar_official_csv import normalize_archive          # noqa: E402(同じ正規化を使う= 規則を 2 か所に書かない)

RAW_DIR = Path.home() / "OneDrive" / "デスクトップ" / "他場" / "data" / "nar_official_csv" / "raw"
ENV_PATH = Path.home() / "OneDrive" / "デスクトップ" / "他場" / ".env"
RAW_FILE_RE = re.compile(r"\d{6}(\d{2})?_race_[0-9a-f]{16}\.zip")
KEYS = ("track", "race_date", "race_no", "runner_number")
BATCH = 500
UA = "nar-jobs/1.0"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def log(msg):
    print(msg, flush=True)


def load_env(path=None):
    # ⚠環境変数で渡されていればファイルは読まない(⛔鍵をリポジトリに置かない)
    if not path and os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        return
    p = Path(path) if path else ENV_PATH
    if not p.exists():
        raise SystemExit(f".env が無い: {p}")
    for raw in p.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def req(url, key, path, method="GET", body=None):
    r = urllib.request.Request(url + path, data=body, method=method, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(r, timeout=90) as x:
                return x.status, x.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt == 0:
                time.sleep(3); continue
            return e.code, e.read().decode("utf-8")[:300]
        except Exception as e:  # noqa: BLE001
            if attempt == 0:
                time.sleep(3); continue
            return 0, str(e)


def minus_rows(files):
    """生 ZIP → 増減が負の行だけ {(鍵): 値}。⛔同じ鍵が複数の ZIP にあれば**新しいファイル**の値を採る"""
    out = {}
    for f in files:
        stamp = f.name.split("_", 1)[0]
        try:
            doc = normalize_archive(f.read_bytes(), kind="race", scope=("monthly" if len(stamp) == 6 else "daily"),
                                    source_url=f.as_uri(), observed_at=dt.datetime.fromtimestamp(
                                        f.stat().st_mtime, dt.timezone.utc).isoformat())
        except (OSError, ValueError) as e:  # noqa: BLE001
            log("  ! 読めないので飛ばす: %s (%s)" % (f.name, type(e).__name__)); continue
        n = 0
        for row in doc.get("horses") or []:
            v = row.get("body_weight_change")
            if v is None or v >= 0:
                continue
            k = (row["track"], row["race_date"], int(row["race_no"]), int(row["runner_number"]))
            if not k[0] or not k[1] or not k[2] or not k[3]:
                continue
            out[k] = int(v)
            n += 1
        log("  %s 負の行 %d(ここまで %d)" % (f.name[:8], n, len(out)))
    return out


def dump_rows(rows, path):
    """負の行を csv.gz に書き出す(鍵 4 列+増減だけ)。生 ZIP の無い所(GitHub Actions)で使うため。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(KEYS) + ["body_weight_change"])
        for k, v in sorted(rows.items()):
            w.writerow(list(k) + [v])
    return p.stat().st_size


def read_rows(path):
    """--dump で書いた csv.gz を読む。⛔負の行だけ(0 や正が混ざっていたら捨てる= 既存の値を壊さない)。"""
    out = {}
    with gzip.open(Path(path), "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                v = int(row["body_weight_change"])
                k = (row["track"], row["race_date"], int(row["race_no"]), int(row["runner_number"]))
            except (KeyError, TypeError, ValueError):
                continue
            if v >= 0 or not k[0] or not k[1]:
                continue
            out[k] = v
    return out


def summarize(rows, nulls=None):
    by_year, by_track = collections.Counter(), collections.Counter()
    ny, nt = collections.Counter(), collections.Counter()
    for (track, date, _no, _u) in rows:
        by_year[date[:4]] += 1
        by_track[track] += 1
        if nulls is not None and (track, date, _no, _u) in nulls:
            ny[date[:4]] += 1
            nt[track] += 1
    lines = ["  年別(負の行 / うち今 null):"]
    for y in sorted(by_year):
        lines.append("    %s  %6d / %6d" % (y, by_year[y], ny[y]))
    lines.append("  場別(負の行 / うち今 null):")
    for t in sorted(by_track, key=lambda x: -by_track[x]):
        lines.append("    %-6s %6d / %6d" % (t, by_track[t], nt[t]))
    return "\n".join(lines)


def existing(url, key, keys):
    """本番にある鍵と、そのうち今 body_weight_change が null の鍵。⛔無い鍵は送らない(新しい行を作らない)。

    ⛔鍵ごとに問い合わせない(数万件で千本の要求になる)= **月ごとに 1000 行ずつ**引いて手元で突き合わせる。
    """
    need = set(keys)
    months = sorted({d[:7] for (_t, d, _no, _u) in need})
    have, nulls = set(), set()
    for ym in months:
        y, m = int(ym[:4]), int(ym[5:])
        last = (dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1)).isoformat()
        off, got = 0, 0
        while True:
            st, body = req(url, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,body_weight_change"
                           "&race_date=gte.%s-01&race_date=lte.%s&order=race_date.asc,track.asc,race_no.asc,"
                           "runner_number.asc&limit=1000&offset=%d" % (ym, last, off))
            if st != 200:
                log("   ! %s を照合できない(HTTP %s)" % (ym, st)); break
            rows = json.loads(body)
            for r in rows:
                k = (r["track"], r["race_date"], int(r["race_no"]), int(r["runner_number"]))
                if k not in need:
                    continue
                have.add(k)
                if r.get("body_weight_change") is None:
                    nulls.add(k)
            got += len(rows)
            if len(rows) < 1000:
                break
            off += 1000
        log("  照合 %s 本番 %d 行(当てる鍵 %d)" % (ym, got, sum(1 for k in need if k[1][:7] == ym)))
    return have, nulls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="本番へ書く(既定はドライラン)")
    ap.add_argument("--since", help="YYYYMM。この月以降の ZIP だけ")
    ap.add_argument("--env", help="接続先 .env(既定: 他場\\.env)")
    ap.add_argument("--raw", help="生 ZIP の置き場(既定: 他場\\data\\nar_official_csv\\raw)")
    ap.add_argument("--dump", help="負の行を csv.gz に書き出して終わる(通信 0)")
    ap.add_argument("--from-file", dest="from_file", help="生 ZIP でなく --dump の csv.gz を読む(Actions 用)")
    a = ap.parse_args()
    if a.from_file:
        rows = read_rows(a.from_file)
        log("控えの csv.gz から 負の行 %d(%s)" % (len(rows), a.from_file))
        if not rows:
            log("⛔負の行が 1 つも無い= 控えが空。止める"); return 2
        return apply_rows(rows, a)
    raw_dir = Path(a.raw) if a.raw else RAW_DIR
    files = [f for f in sorted(raw_dir.glob("*_race_*.zip")) if RAW_FILE_RE.fullmatch(f.name)]
    if a.since:
        files = [f for f in files if f.name[:6] >= a.since]
    if not files:
        log("生 ZIP が無い: %s" % raw_dir); return 2
    log("生 ZIP %d 本(%s 〜 %s)を読み直す" % (len(files), files[0].name[:8], files[-1].name[:8]))
    rows = minus_rows(files)
    log("増減が負の行 %d" % len(rows))
    if not rows:
        log("⛔負の行が 1 つも無い= 正規化の直しが効いていない。止める"); return 2
    if a.dump:
        size = dump_rows(rows, a.dump)
        log("控えを書いた %s(%d 行・%.1f MB)。⛔鍵は要らない(通信 0)" % (a.dump, len(rows), size / 1048576))
        return 0
    return apply_rows(rows, a)


def apply_rows(rows, a):
    """本番にある行だけ、鍵 4 列+増減を upsert する(既定はドライラン)。"""
    load_env(a.env)
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
    have, nulls = existing(url, key, rows.keys())
    log("本番にある行 %d(送らない= %d)" % (len(have), len(rows) - len(have)))
    log(summarize({k: v for k, v in rows.items() if k in have}, nulls))
    if not a.apply:
        log("ドライラン(書き込みなし)。内訳を見てから --apply を付けること。"); return 0

    send = [dict(zip(KEYS, k), body_weight_change=v) for k, v in sorted(rows.items()) if k in have]
    log("upsert する行 %d(鍵 4 列+増減だけ)" % len(send))
    for i in range(0, len(send), BATCH):
        st, msg = req(url, key, "/rest/v1/nar_runs?on_conflict=" + ",".join(KEYS), "POST",
                      json.dumps(send[i:i + BATCH], ensure_ascii=False).encode("utf-8"))
        if st not in (200, 201, 204):
            log("   投入 %s %s" % (st, msg)); return 1
    log("   nar_runs 更新 %d 行" % len(send))
    return 0


if __name__ == "__main__":
    sys.exit(main())
