#!/usr/bin/env python3
"""監査 #28(2026-09-23・案C)+§258(2026-09-23): オッズの刻みの 60 日超を 1 日 1 ファイルへ書き出し→確かめ→DB を減らす。

  2 表を順に(1 回の上限 --max-days は表ごと):
  - nar_odds_full_ticks(全 6 券種): 書き出し→照合→その日の行を全部消す。記録 nar_meta 'odds_archive:v1'(監査 #28 の形のまま)
  - nar_odds_ticks(単複 2 分刻み・§258): 書き出し→照合→1 レース 9 点だけ残して他を消す
    (残す規則は pipeline/sql/odds_ticks_retention.sql と同じ= keep_ids()。発走時刻が無いレースは初回と最終だけ)。
    記録 nar_meta 'odds_archive:nar_odds_ticks:v1'= {日付: {rows, kept, bytes, sha256, path, deleted, at}}。
    間引いた後も日付は DB に残るので、対象日は「この記録の最後の日より後」から古い順に選ぶ(失敗した日で止まる= 飛ばさない)。
    ⛔§258 から 05:33 便の odds_ticks_retention.sql は止めた(書き出す前に間引く経路を残さない)。

  JST の今日から 60 日より前の race_date を古い順に 1 日ずつ(1 回の実行で最大 --max-days 日)。
  1) その日の全行を PostgREST で読む(order=id・1000 行ずつ・id の keyset= 一意の順)
  2) gzip の JSONL(1 行 1 刻み・列はそのまま)にし、行数・最小/最大 id・sha256(解凍後の JSONL)を控える
  3) Supabase Storage の非公開バケット odds-archive へ上げる(無ければ作る・public=false)
     パス= <表名>/YYYY/YYYY-MM-DD.jsonl.gz。既にあれば上書きせず、中身(sha256)が同じかだけ見る
  4) 上げたファイルを取り直して解凍し、行数・id の集合・sha256 が DB と一致したときだけ
     その日の行を id の範囲で小分け(1 回 5,000 行以下)に DELETE。一致しなければ消さずに rc 1
  5) nar_meta key 'odds_archive:v1' に {日付: {rows, bytes, sha256, path, deleted, at}} を足す

  py -3.12 -X utf8 cloud/odds_archive.py --env pipeline/.env.nar --dry-run --date 2026-09-22 [--table ticks|full|all]
  py -3.12 -X utf8 cloud/odds_archive.py --max-days 3          # 本番(nar-refresh.yml daily 朝の便・2 表を順に)
  --dry-run= 60 日以内の日でも読んで書き出して上げて落として照合までやるが、消さない・nar_meta にも書かない。
    上げる先は odds-archive/_test/<表名>/… にして、最後に消す(本番のパスには触らない)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。⛔鍵はログに出さない。
終了コード: 0 成功(対象日なしを含む)/ 1 どれか 1 日でも失敗(全滅を成功扱いしない= 監査 #19)/ 2 前提が無い

戻し方(ファイル → 一時表 → insert):
  1. Storage から nar_odds_full_ticks/YYYY/YYYY-MM-DD.jsonl.gz を落として解凍(gzip -dc … > d.jsonl)
  2. psql: create temp table t(j jsonb); \\copy t(j) from 'd.jsonl' with (format csv, quote e'\\x01', delimiter e'\\x02')
  3. insert into public.nar_odds_full_ticks select (jsonb_populate_record(null::public.nar_odds_full_ticks, j)).* from t
     on conflict (id) do nothing;
  4. select count(*) from public.nar_odds_full_ticks where race_date = 'YYYY-MM-DD' で nar_meta の rows と一致を見る
  5. 必要なら setval で id の連番を max(id) 以上に(通常は不要= 古い id を戻すだけ)
  nar_odds_ticks も同じ手順で表名を置き換える(残した 9 点は on conflict (id) do nothing で重ならない)。
  4 の突き合わせは nar_meta 'odds_archive:nar_odds_ticks:v1' の rows(書き出した行数= 戻した後の行数)。
"""
import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TABLE = "nar_odds_full_ticks"
TICKS = "nar_odds_ticks"
BUCKET = "odds-archive"
META_KEY = "odds_archive:v1"
# 表ごとの設定。mode= all(その日を全部消す)/ thin9(9 点だけ残す)。meta= nar_meta の key(表ごとに別)
TABLES = {
    TABLE: {"mode": "all", "meta": META_KEY},
    TICKS: {"mode": "thin9", "meta": "odds_archive:%s:v1" % TICKS},
}
TABLE_ALIAS = {"full": [TABLE], "ticks": [TICKS], "all": [TABLE, TICKS]}
TEST_PREFIX = "_test/"
KEEP_MINS = (240, 120, 60, 30, 20, 10, 5)
IN_CHUNK = 300
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


def archive_path(d, table=TABLE, test=False):
    return "%s%s/%04d/%s.jsonl.gz" % (TEST_PREFIX if test else "", table, d.year, d.isoformat())


def _hm(s):
    """'HH:MM' / 'HH:MM:SS' → 分(SQL の split_part(t,':',1)*60 + split_part(t,':',2) と同じ)。"""
    p = str(s).split(":")
    return int(p[0]) * 60 + int(p[1])


def before_min(post_time, t):
    """発走(HHMM)の何分前か。post_time が数字 4 桁でなければ None(SQL の post_time ~ 数字 4 桁 と同じ)。"""
    pt = "" if post_time is None else str(post_time)
    if not re.fullmatch(r"[0-9]{4}", pt):
        return None
    return int(pt[:2]) * 60 + int(pt[2:]) - _hm(t)


def _f_desc(f):
    """order by f desc の順位(Postgres の desc は NULL が先頭)。大きいほど先。"""
    return 2 if f is None else (1 if f else 0)


def keep_ids(rows, post_times):
    """odds_ticks_retention.sql と同じ規則で残す id の集合。
    rows= nar_odds_ticks の行(id,track,race_date,race_no,t,f)。post_times= {(track, race_no): 'HHMM'}(その日の nar_races)。
    1 レースごとに 初回(t,id 昇順の先頭)/ 最終(f desc, t desc, id desc の先頭)/
    発走 240・120・60・30・20・10・5 分前に最も近い点(同点は id の小さい方)。発走時刻が無いレースは初回と最終だけ。"""
    races = {}
    for r in rows:
        races.setdefault((r["track"], str(r["race_date"])[:10], int(r["race_no"])), []).append(r)
    keep = set()
    for (track, _d, no), rs in races.items():
        first = min(rs, key=lambda r: (str(r["t"]), int(r["id"])))
        last = max(rs, key=lambda r: (_f_desc(r.get("f")), str(r["t"]), int(r["id"])))
        keep.add(int(first["id"]))
        keep.add(int(last["id"]))
        pt = post_times.get((track, no))
        bm = [(before_min(pt, r["t"]), int(r["id"])) for r in rs]
        bm = [(b, i) for b, i in bm if b is not None]
        for m in KEEP_MINS:
            if bm:
                keep.add(min(bm, key=lambda x: (abs(x[0] - m), x[1]))[1])
    return keep


def in_chunks(ids, size=IN_CHUNK):
    s = sorted(ids)
    return [s[i:i + size] for i in range(0, len(s), size)]


def next_after(meta_value):
    """thin9 の表の続きの起点= 記録の最後の日(無ければ None= 一番古い日から)。"""
    ds = [k for k in (meta_value or {}) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(k))]
    return dt.date.fromisoformat(max(ds)) if ds else None


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


def next_date(base, key, after, cut, table=TABLE):
    """after より後・cut より前の最も古い race_date(無ければ None)。race_date の索引で 1 行だけ読む。"""
    q = "select=race_date&race_date=lt.%s&order=race_date.asc,id.asc&limit=1" % cut.isoformat()
    if after:
        q += "&race_date=gt.%s" % after.isoformat()
    _st, body, _h = req(base, key, "/rest/v1/%s?%s" % (table, q))
    rows = json.loads(body or b"[]")
    return dt.date.fromisoformat(rows[0]["race_date"][:10]) if rows else None


def read_day(base, key, d, table=TABLE, select="*"):
    rows, last = [], None
    while True:
        q = "select=%s&race_date=eq.%s&order=id.asc&limit=%d" % (select, d.isoformat(), PAGE)
        if last is not None:
            q += "&id=gt.%d" % last
        _st, body, _h = req(base, key, "/rest/v1/%s?%s" % (table, q))
        page = json.loads(body or b"[]")
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        last = int(page[-1]["id"])


def read_post_times(base, key, d):
    """その日の nar_races の発走時刻 {(track, race_no): 'HHMM'}。"""
    _st, body, _h = req(base, key, "/rest/v1/nar_races?select=track,race_no,post_time&race_date=eq.%s&limit=5000"
                        % d.isoformat())
    return {(r["track"], int(r["race_no"])): r.get("post_time") for r in json.loads(body or b"[]")}


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


def upload(base, key, path, data, upsert=False):
    req(base, key, "/storage/v1/object/%s/%s" % (BUCKET, path), "POST", data,
        {"Content-Type": "application/gzip", "x-upsert": "true" if upsert else "false"}, timeout=300)


def remove_object(base, key, path):
    """試しのファイル(_test/ の下だけ)を消す。"""
    if not path.startswith(TEST_PREFIX):
        raise ValueError("_test/ の外は消さない: %s" % path)
    body = json.dumps({"prefixes": [path]}).encode("utf-8")
    req(base, key, "/storage/v1/object/%s" % BUCKET, "DELETE", body, {"Content-Type": "application/json"})


def _count(h):
    cr = h.get("Content-Range") or h.get("content-range") or ""
    n = cr.rsplit("/", 1)[-1] if "/" in cr else ""
    return int(n) if n.isdigit() else 0


def delete_day(base, key, d, ids, table=TABLE):
    total = 0
    for lo, hi in chunk_ranges(ids):
        q = "race_date=eq.%s&id=gte.%d&id=lte.%d" % (d.isoformat(), lo, hi)
        _st, _b, h = req(base, key, "/rest/v1/%s?%s" % (table, q), "DELETE",
                         headers={"Prefer": "return=minimal,count=exact"})
        total += _count(h)
    return total


def delete_ids(base, key, d, ids, table):
    """id を名指しで消す(9 点を残すので範囲では消せない)。1 回 IN_CHUNK 件。"""
    total = 0
    for ch in in_chunks(ids):
        q = "race_date=eq.%s&id=in.(%s)" % (d.isoformat(), ",".join(str(i) for i in ch))
        _st, _b, h = req(base, key, "/rest/v1/%s?%s" % (table, q), "DELETE",
                         headers={"Prefer": "return=minimal,count=exact"})
        total += _count(h)
    return total


def meta_get(base, key, meta_key=META_KEY):
    _st, body, _h = req(base, key, "/rest/v1/nar_meta?select=value&key=eq.%s" % urllib.parse.quote(meta_key))
    rows = json.loads(body or b"[]")
    return (rows[0].get("value") or {}) if rows else {}


def meta_put(base, key, value, meta_key=META_KEY):
    body = json.dumps([{"key": meta_key, "value": value, "updated_at": dt.datetime.now(JST).isoformat()}],
                      ensure_ascii=False).encode("utf-8")
    req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST", body,
        {"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})


def already_thinned(exp_db, file_gz):
    """前回 書き出し+間引きまで済んで記録だけ落ちた日か: DB の今の id ⊂ ファイルの id で、DB の方が少ない。(ok, 理由)。"""
    try:
        f = summarize(gzip.decompress(file_gz))
    except Exception as e:
        return False, "解凍に失敗 %s" % type(e).__name__
    if not set(exp_db["ids"]) <= set(f["ids"]):
        return False, "DB にファイルに無い id がある"
    if len(exp_db["ids"]) >= len(f["ids"]):
        return False, "行数 %d≠%d" % (f["rows"], exp_db["rows"])
    return True, "DB %d 行 ⊂ ファイル %d 行" % (exp_db["rows"], f["rows"])


def archive_one(base, key, d, dry_run, table=TABLE):
    """1 表 1 日ぶん。成功で控え(dict)、失敗で例外 or None。"""
    t0 = time.time()
    mode = TABLES[table]["mode"]
    tag = "%s %s" % (table, d)
    rows = read_day(base, key, d, table)
    if not rows:
        log("  %s: 行なし" % tag); return None
    raw = to_jsonl(rows)
    exp = summarize(raw)
    data = gz(raw)
    path = archive_path(d, table, test=dry_run)
    keep = keep_ids(rows, read_post_times(base, key, d)) if mode == "thin9" else None
    log("  %s: 読んだ %d 行 id %d〜%d・gzip %d bytes・sha256 %s…%s(%.0fs)" % (
        tag, exp["rows"], min(exp["ids"]), max(exp["ids"]), len(data), exp["sha256"][:12],
        "・残す %d 点" % len(keep) if keep is not None else "", time.time() - t0))
    have = None
    if dry_run:
        upload(base, key, path, data, upsert=True)
        log("  %s: 上げた(試し) %s/%s" % (tag, BUCKET, path))
    else:
        have = download(base, key, path)
        if have is None:
            upload(base, key, path, data)
            log("  %s: 上げた %s/%s" % (tag, BUCKET, path))
        else:
            log("  %s: 既にある(上書きしない)= 中身を照合" % tag)
    try:
        back = download(base, key, path)
        if back is None:
            log("  %s: ❌ 取り直せない= 消さない" % tag); return None
        ok, why = verify(exp, back)
        if not ok and mode == "thin9" and have is not None:
            ok2, why2 = already_thinned(exp, back)
            if ok2:
                fs = summarize(gzip.decompress(back))
                log("  %s: 既に間引き済み(%s)= 記録だけ足す" % (tag, why2))
                return {"rows": fs["rows"], "kept": exp["rows"], "bytes": len(back), "sha256": fs["sha256"],
                        "path": "%s/%s" % (BUCKET, path), "deleted": 0,
                        "at": dt.datetime.now(JST).isoformat(timespec="seconds")}
        if not ok:
            log("  %s: ❌ 照合 %s= 消さない" % (tag, why)); return None
        log("  %s: 照合 一致(行数 %d・id 集合・sha256)・取り直し %d bytes" % (tag, exp["rows"], len(back)))
    finally:
        if dry_run:
            try:
                remove_object(base, key, path)
                log("  %s: 試しのファイルを消した %s/%s" % (tag, BUCKET, path))
            except Exception as e:
                log("  %s: ⚠試しのファイルを消せない %s: %s" % (tag, type(e).__name__, str(e)[:120]))
    drop = [i for i in exp["ids"] if keep is None or i not in keep]
    deleted = 0
    if dry_run:
        log("  %s: --dry-run= 消さない(本番なら %d 行を消す)" % (tag, len(drop)))
    elif mode == "all":
        deleted = delete_day(base, key, d, exp["ids"], table)
        if deleted != exp["rows"]:
            log("  %s: ❌ 消した %d≠%d 行" % (tag, deleted, exp["rows"])); return None
        log("  %s: 消した %d 行" % (tag, deleted))
    else:
        deleted = delete_ids(base, key, d, drop, table) if drop else 0
        left = {int(r["id"]) for r in read_day(base, key, d, table, select="id")}
        if deleted != len(drop) or left != keep:
            log("  %s: ❌ 間引き 消した %d/%d 行・残り %d 点(期待 %d)" % (tag, deleted, len(drop), len(left), len(keep)))
            return None
        log("  %s: 間引いた %d 行・残り %d 点" % (tag, deleted, len(left)))
    log("  %s: 所要 %.1fs" % (tag, time.time() - t0))
    r = {"rows": exp["rows"], "bytes": len(back), "sha256": exp["sha256"], "path": "%s/%s" % (BUCKET, path),
         "deleted": deleted, "at": dt.datetime.now(JST).isoformat(timespec="seconds")}
    if keep is not None:
        r["kept"] = len(keep)
    return r


def run_table(base, key, table, a, today, cut):
    """1 表ぶん。(done, fail)。"""
    meta_key = TABLES[table]["meta"]
    thin = TABLES[table]["mode"] == "thin9"
    if a.date:
        d = dt.date.fromisoformat(a.date)
        # --dry-run は消さない= 60 日以内の日でも書き出しと照合だけ試せる(本番の消去は 60 日超だけ)
        if not a.dry_run and not pick_dates([d], today, 1):
            log("%s: %s は 60 日超でない(境目 %s より前だけ)" % (table, d, cut)); return {}, 1
        dates = [d]
    else:
        # thin9 は間引いた後も日付が DB に残る= 記録の最後の日より後から(all は消えるので頭から)
        after = next_after(meta_get(base, key, meta_key)) if thin else None
        dates = []
        while len(dates) < a.max_days:
            after = next_date(base, key, after, cut, table)
            if after is None:
                break
            dates.append(after)
    log("odds archive %s: 今日(JST) %s・境目 %s・対象 %s%s" % (
        table, today, cut, ",".join(map(str, dates)) or "なし", "(dry-run)" if a.dry_run else ""))
    done, fail = {}, 0
    for d in dates:
        try:
            r = archive_one(base, key, d, a.dry_run, table)
        except Exception as e:
            log("  %s %s: ❌ %s: %s" % (table, d, type(e).__name__, str(e)[:160])); r = None
        if r is None:
            fail += 1
            if thin:
                log("  %s: 失敗した日で止める(記録の続きを飛ばさない= 次回この日から)" % table); break
        else:
            done[d.isoformat()] = r
    if done and not a.dry_run:
        try:
            m = meta_get(base, key, meta_key)
            m.update(done)
            meta_put(base, key, m, meta_key)
            log("nar_meta/%s に %d 日を足した" % (meta_key, len(done)))
        except Exception as e:
            log("❌ nar_meta に書けない %s: %s" % (type(e).__name__, str(e)[:160])); fail += 1
    return done, fail


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--dry-run", action="store_true",
                    help="読んで書き出して _test/ に上げて照合するが消さない(nar_meta にも書かない・試しのファイルは最後に消す)")
    ap.add_argument("--date", help="YYYY-MM-DD の 1 日だけ(--dry-run 無しなら 60 日超でなければ断る)")
    ap.add_argument("--table", choices=sorted(TABLE_ALIAS), default="all", help="full / ticks / all(既定= 2 表を順に)")
    ap.add_argument("--max-days", type=int, default=3, help="1 回の上限日数(表ごと)")
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
        ensure_bucket(base, key)
    except Exception as e:
        log("❌ 前段で失敗 %s: %s" % (type(e).__name__, str(e)[:160])); return 1
    ndone, fail = 0, 0
    for table in TABLE_ALIAS[a.table]:
        try:
            done, f = run_table(base, key, table, a, today, cut)
        except Exception as e:
            log("❌ %s 前段で失敗 %s: %s" % (table, type(e).__name__, str(e)[:160])); done, f = {}, 1
        ndone += len(done)
        fail += f
    log("完了 %d 日・失敗 %d 日" % (ndone, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
