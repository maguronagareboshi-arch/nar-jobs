#!/usr/bin/env python3
"""監査 #28(2026-09-23・案C): nar_odds_full_ticks の 60 日超を 1 日 1 ファイルへ書き出し→確かめ→DB から消す。

  JST の今日から 60 日より前の race_date を古い順に 1 日ずつ(1 回の実行で最大 --max-days 日)。
  1) その日の全行を PostgREST で読む(order=id・1000 行ずつ・id の keyset= 一意の順)
  2) gzip の JSONL(1 行 1 刻み・列はそのまま)にし、行数・最小/最大 id・sha256(解凍後の JSONL)を控える
  3) Supabase Storage の非公開バケット odds-archive へ上げる(無ければ作る・public=false)
     パス= nar_odds_full_ticks/YYYY/YYYY-MM-DD.jsonl.gz。既にあれば上書きせず、中身(sha256)が同じかだけ見る
  4) 上げたファイルを取り直して解凍し、行数・id の集合・sha256 が DB と一致したときだけ
     その日の行を id の範囲で小分け(1 回 5,000 行以下)に DELETE。一致しなければ消さずに rc 1
  5) nar_meta key 'odds_archive:v1' に {日付: {rows, bytes, sha256, path, deleted, at}} を足す

  py -3.12 -X utf8 cloud/odds_archive.py --env pipeline/.env.nar --dry-run --date 2026-09-10
  py -3.12 -X utf8 cloud/odds_archive.py --max-days 3          # 本番(nar-refresh.yml daily 朝の便)
  --dry-run= 読んで書き出して上げて確かめるが、消さない・nar_meta にも書かない。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。⛔鍵はログに出さない。
終了コード: 0 成功(対象日なしを含む)/ 1 どれか 1 日でも失敗(全滅を成功扱いしない= 監査 #19)/ 2 前提が無い

戻し方(ファイル → 一時表 → insert):
  1. Storage から nar_odds_full_ticks/YYYY/YYYY-MM-DD.jsonl.gz を落として解凍(gzip -dc … > d.jsonl)
  2. psql: create temp table t(j jsonb); \\copy t(j) from 'd.jsonl' with (format csv, quote e'\\x01', delimiter e'\\x02')
  3. insert into public.nar_odds_full_ticks select (jsonb_populate_record(null::public.nar_odds_full_ticks, j)).* from t
     on conflict (id) do nothing;
  4. select count(*) from public.nar_odds_full_ticks where race_date = 'YYYY-MM-DD' で nar_meta の rows と一致を見る
  5. 必要なら setval で id の連番を max(id) 以上に(通常は不要= 古い id を戻すだけ)
"""
import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TABLE = "nar_odds_full_ticks"
BUCKET = "odds-archive"
META_KEY = "odds_archive:v1"
KEEP_DAYS = 60
PAGE = 1000
DEL_CHUNK = 5000
JST = dt.timezone(dt.timedelta(hours=9))
UA = "nar-jobs odds_archive/1"


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ---------- 純粋関数(tests/test_audit28_odds_archive.py) ----------

def jst_today(now=None):
    """JST の今日。now は aware datetime(省略時は現在)。UTC 15:00 以降は JST の翌日。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(JST).date()


def cutoff_date(today, keep_days=KEEP_DAYS):
    """この日より前(<)の race_date が対象。旧 SQL の race_date < current_date - 60 と同じ境目。"""
    return today - dt.timedelta(days=keep_days)


def pick_dates(dates, today, max_days, keep_days=KEEP_DAYS):
    """候補日から対象日を古い順に最大 max_days 日。dates は date か 'YYYY-MM-DD'。"""
    cut = cutoff_date(today, keep_days)
    ds = sorted({d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10]) for d in dates})
    return [d for d in ds if d < cut][:max(0, int(max_days))]


def archive_path(d):
    return "%s/%04d/%s.jsonl.gz" % (TABLE, d.year, d.isoformat())


def to_jsonl(rows):
    """1 行 1 刻み・列はそのまま。解凍後のバイト列を返す(sha256 はこれに取る)。"""
    return b"".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n" for r in rows)


def gz(raw):
    """mtime=0 で固定= 同じ中身なら同じ gzip。"""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as f:
        f.write(raw)
    return buf.getvalue()


def summarize(raw):
    """解凍後の JSONL から 行数・id の集合・sha256。"""
    ids = []
    for line in raw.splitlines():
        if line.strip():
            ids.append(int(json.loads(line)["id"]))
    return {"rows": len(ids), "ids": ids, "sha256": hashlib.sha256(raw).hexdigest()}


def verify(expect, gz_bytes):
    """上げ直したファイル(gzip)が DB から読んだもの(expect= summarize の結果)と一致するか。(ok, 理由)。"""
    try:
        got = summarize(gzip.decompress(gz_bytes))
    except Exception as e:
        return False, "解凍/読み取りに失敗 %s" % type(e).__name__
    if got["rows"] != expect["rows"]:
        return False, "行数 %d≠%d" % (got["rows"], expect["rows"])
    if len(set(got["ids"])) != len(got["ids"]):
        return False, "id が重複"
    if set(got["ids"]) != set(expect["ids"]):
        return False, "id の集合が違う"
    if got["sha256"] != expect["sha256"]:
        return False, "sha256 が違う"
    return True, "一致"


def chunk_ranges(ids, size=DEL_CHUNK):
    """昇順に並べた id を size 行以下の (lo, hi) 範囲に分ける(両端を含む)。"""
    s = sorted(ids)
    return [(s[i], s[min(i + size, len(s)) - 1]) for i in range(0, len(s), size)]


# ---------- 通信 ----------

def req(base, key, path, method="GET", body=None, headers=None, timeout=180):
    h = {"apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA}
    if headers:
        h.update(headers)
    r = urllib.request.Request(base + path, method=method, data=body, headers=h)
    with urllib.request.urlopen(r, timeout=timeout) as x:
        return x.status, x.read(), dict(x.headers)


def next_date(base, key, after, cut):
    """after より後・cut より前の最も古い race_date(無ければ None)。race_date の索引で 1 行だけ読む。"""
    q = "select=race_date&race_date=lt.%s&order=race_date.asc,id.asc&limit=1" % cut.isoformat()
    if after:
        q += "&race_date=gt.%s" % after.isoformat()
    _st, body, _h = req(base, key, "/rest/v1/%s?%s" % (TABLE, q))
    rows = json.loads(body or b"[]")
    return dt.date.fromisoformat(rows[0]["race_date"][:10]) if rows else None


def read_day(base, key, d):
    rows, last = [], None
    while True:
        q = "select=*&race_date=eq.%s&order=id.asc&limit=%d" % (d.isoformat(), PAGE)
        if last is not None:
            q += "&id=gt.%d" % last
        _st, body, _h = req(base, key, "/rest/v1/%s?%s" % (TABLE, q))
        page = json.loads(body or b"[]")
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        last = int(page[-1]["id"])


def ensure_bucket(base, key):
    try:
        req(base, key, "/storage/v1/bucket/%s" % BUCKET)
        return
    except urllib.error.HTTPError as e:
        if e.code not in (400, 404):
            raise
    body = json.dumps({"id": BUCKET, "name": BUCKET, "public": False}).encode("utf-8")
    req(base, key, "/storage/v1/bucket", "POST", body, {"Content-Type": "application/json"})
    log("バケット %s を作った(非公開)" % BUCKET)


def download(base, key, path):
    """無ければ None。"""
    try:
        _st, body, _h = req(base, key, "/storage/v1/object/%s/%s" % (BUCKET, path))
        return body
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        raise


def upload(base, key, path, data):
    req(base, key, "/storage/v1/object/%s/%s" % (BUCKET, path), "POST", data,
        {"Content-Type": "application/gzip", "x-upsert": "false"}, timeout=300)


def delete_day(base, key, d, ids):
    total = 0
    for lo, hi in chunk_ranges(ids):
        q = "race_date=eq.%s&id=gte.%d&id=lte.%d" % (d.isoformat(), lo, hi)
        _st, _b, h = req(base, key, "/rest/v1/%s?%s" % (TABLE, q), "DELETE",
                         headers={"Prefer": "return=minimal,count=exact"})
        cr = h.get("Content-Range") or h.get("content-range") or ""
        n = cr.rsplit("/", 1)[-1] if "/" in cr else ""
        total += int(n) if n.isdigit() else 0
    return total


def meta_get(base, key):
    _st, body, _h = req(base, key, "/rest/v1/nar_meta?select=value&key=eq.%s" % urllib.parse.quote(META_KEY))
    rows = json.loads(body or b"[]")
    return (rows[0].get("value") or {}) if rows else {}


def meta_put(base, key, value):
    body = json.dumps([{"key": META_KEY, "value": value, "updated_at": dt.datetime.now(JST).isoformat()}],
                      ensure_ascii=False).encode("utf-8")
    req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST", body,
        {"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})


def archive_one(base, key, d, dry_run):
    """1 日ぶん。成功で控え(dict)、失敗で例外 or None。"""
    t0 = time.time()
    rows = read_day(base, key, d)
    if not rows:
        log("  %s: 行なし" % d); return None
    raw = to_jsonl(rows)
    exp = summarize(raw)
    data = gz(raw)
    path = archive_path(d)
    log("  %s: 読んだ %d 行 id %d〜%d・gzip %d bytes・sha256 %s…(%.0fs)" % (
        d, exp["rows"], min(exp["ids"]), max(exp["ids"]), len(data), exp["sha256"][:12], time.time() - t0))
    have = download(base, key, path)
    if have is None:
        upload(base, key, path, data)
        log("  %s: 上げた %s/%s" % (d, BUCKET, path))
    else:
        log("  %s: 既にある(上書きしない)= 中身を照合" % d)
    back = download(base, key, path)
    if back is None:
        log("  %s: ❌ 取り直せない= 消さない" % d); return None
    ok, why = verify(exp, back)
    if not ok:
        log("  %s: ❌ 照合 %s= 消さない" % (d, why)); return None
    log("  %s: 照合 一致(行数 %d・id 集合・sha256)・取り直し %d bytes" % (d, exp["rows"], len(back)))
    deleted = 0
    if dry_run:
        log("  %s: --dry-run= 消さない" % d)
    else:
        deleted = delete_day(base, key, d, exp["ids"])
        if deleted != exp["rows"]:
            log("  %s: ❌ 消した %d≠%d 行" % (d, deleted, exp["rows"])); return None
        log("  %s: 消した %d 行" % (d, deleted))
    log("  %s: 所要 %.1fs" % (d, time.time() - t0))
    return {"rows": exp["rows"], "bytes": len(back), "sha256": exp["sha256"], "path": "%s/%s" % (BUCKET, path),
            "deleted": deleted, "at": dt.datetime.now(JST).isoformat(timespec="seconds")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--dry-run", action="store_true", help="読んで書き出して上げて確かめるが消さない(nar_meta にも書かない)")
    ap.add_argument("--date", help="YYYY-MM-DD の 1 日だけ(60 日超でなければ断る)")
    ap.add_argument("--max-days", type=int, default=3)
    a = ap.parse_args(argv)
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が要る"); return 2
    today = jst_today()
    cut = cutoff_date(today)
    try:
        if a.date:
            d = dt.date.fromisoformat(a.date)
            # --dry-run は消さない= 60 日以内の日でも書き出しと照合だけ試せる(本番の消去は 60 日超だけ)
            if not a.dry_run and not pick_dates([d], today, 1):
                log("%s は 60 日超でない(境目 %s より前だけ)" % (d, cut)); return 1
            dates = [d]
        else:
            dates, after = [], None
            while len(dates) < a.max_days:
                after = next_date(base, key, after, cut)
                if after is None:
                    break
                dates.append(after)
        log("odds archive: 今日(JST) %s・境目 %s・対象 %s%s" % (
            today, cut, ",".join(map(str, dates)) or "なし", "(dry-run)" if a.dry_run else ""))
        if not dates:
            return 0
        ensure_bucket(base, key)
    except Exception as e:
        log("❌ 前段で失敗 %s: %s" % (type(e).__name__, str(e)[:160])); return 1
    done, fail = {}, 0
    for d in dates:
        try:
            r = archive_one(base, key, d, a.dry_run)
        except Exception as e:
            log("  %s: ❌ %s: %s" % (d, type(e).__name__, str(e)[:160])); r = None
        if r is None:
            fail += 1
        else:
            done[d.isoformat()] = r
    if done and not a.dry_run:
        try:
            m = meta_get(base, key)
            m.update(done)
            meta_put(base, key, m)
            log("nar_meta/%s に %d 日を足した" % (META_KEY, len(done)))
        except Exception as e:
            log("❌ nar_meta に書けない %s: %s" % (type(e).__name__, str(e)[:160])); fail += 1
    log("完了 %d 日・失敗 %d 日" % (len(done), fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
