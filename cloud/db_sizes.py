# -*- coding: utf-8 -*-
"""本番 DB の大きさを 1 日 1 回記録する(監査 D10・2026-09-24)。

  python3 cloud/db_sizes.py            … catalog を読んで nar_meta 'db_sizes' へ upsert・heartbeat 'db_size' を書く
  python3 cloud/db_sizes.py --dry-run  … 読むだけ(書かない)

読むのは catalog だけ(pg_database_size・pg_total_relation_size・pg_class.reltuples)= 軽い。
パーティションの親表は pg_inherits で子の区画を合計する。
書くのは nar_meta 1 行('db_sizes')と nar_job_heartbeat 1 行('db_size')だけ。
環境変数: PGPASSWORD(NAR_DB_PASSWORD)/SUPABASE_URL/SUPABASE_SERVICE_KEY。
閾値は下の定数(env で上書き可)。⛔仮置き= ディスクの総量が分かったら直す。
終了コード: 0= 記録できた(warn があっても 0。赤にするのは nar-watchdog)・1= 記録できなかった。
"""
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beat  # noqa: E402

GB = 1024 ** 3
MB = 1024 ** 2
WARN_DB_GB = float(os.environ.get("DB_SIZE_WARN_DB_GB", "5.0"))                 # DB 全体
WARN_GROWTH_MB = float(os.environ.get("DB_SIZE_WARN_GROWTH_MB", "150"))         # 1 日の伸び
WARN_ODDS_FULL_TICKS_GB = float(os.environ.get("DB_SIZE_WARN_ODDS_FULL_TICKS_GB", "1.0"))  # nar_odds_full_ticks

PG_HOST = "aws-0-ap-northeast-1.pooler.supabase.com"
PG_USER = "postgres.qgsnsdjvzzeazbazjlwa"
META_KEY = "db_sizes"
JOB = "db_size"

SQL = """
with recursive tree as (
  select c.oid as root, c.oid as rel from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relispartition
  union all
  select t.root, i.inhrelid from tree t join pg_inherits i on i.inhparent = t.rel
), agg as (
  select root, sum(pg_total_relation_size(rel))::bigint as bytes,
         sum(greatest(c.reltuples, 0))::bigint as rows
  from tree join pg_class c on c.oid = tree.rel group by root
)
select json_build_object('db_bytes', pg_database_size(current_database()),
  'tables', (select json_agg(x) from (select r.relname as name, a.bytes, a.rows
             from agg a join pg_class r on r.oid = a.root order by a.bytes desc limit 20) x))::text;
"""


def read_catalog():
    out = subprocess.run(
        ["psql", "-h", PG_HOST, "-p", "5432", "-U", PG_USER, "-d", "postgres",
         "-v", "ON_ERROR_STOP=1", "-X", "-A", "-t", "-c", SQL],
        check=True, capture_output=True, text=True, timeout=120)
    return json.loads(out.stdout.strip())


def read_prev():
    try:
        got = beat._req(f"nar_meta?select=value&key=eq.{META_KEY}")
        return (got[0]["value"] if got else None) or None
    except Exception as e:                          # noqa: BLE001
        print(f"⚠前回の {META_KEY} が読めない(伸びは出さない): {type(e).__name__}", flush=True)
        return None


def upsert(value):
    url, key = beat._env()
    body = json.dumps([{"key": META_KEY, "value": value,
                        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}],
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{url}/rest/v1/nar_meta?on_conflict=key", data=body, method="POST",
                                 headers={"apikey": key, "Authorization": "Bearer " + key,
                                          "Content-Type": "application/json",
                                          "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def build(cat, prev, now):
    db = int(cat["db_bytes"])
    tables = [{"name": t["name"], "bytes": int(t["bytes"]), "rows": int(t["rows"])} for t in cat.get("tables") or []]
    growth = None
    if prev and prev.get("at") and prev.get("db_bytes") is not None:
        pt = dt.datetime.fromisoformat(str(prev["at"]).replace("Z", "+00:00"))
        days = (now - pt).total_seconds() / 86400
        if days >= 0.5:                              # 半日未満の間隔では伸びを出さない(誤差が大きい)
            growth = int((db - int(prev["db_bytes"])) / days)
        elif prev.get("growth_per_day") is not None:
            growth = int(prev["growth_per_day"])      # 同じ日の取り直し= 前回の値を持ち越す
    warn = []
    if db > WARN_DB_GB * GB:
        warn.append(f"DB 全体 {db / GB:.2f}GB が {WARN_DB_GB}GB を越えた")
    if growth is not None and growth > WARN_GROWTH_MB * MB:
        warn.append(f"1 日の伸び {growth / MB:.0f}MB が {WARN_GROWTH_MB:.0f}MB を越えた")
    oft = next((t for t in tables if t["name"] == "nar_odds_full_ticks"), None)
    if oft and oft["bytes"] > WARN_ODDS_FULL_TICKS_GB * GB:
        warn.append(f"nar_odds_full_ticks {oft['bytes'] / GB:.2f}GB が {WARN_ODDS_FULL_TICKS_GB}GB を越えた")
    return {"at": now.isoformat(), "db_bytes": db, "tables": tables,
            "growth_per_day": growth, "warn": warn,
            "limits": {"db_gb": WARN_DB_GB, "growth_mb": WARN_GROWTH_MB,
                       "odds_full_ticks_gb": WARN_ODDS_FULL_TICKS_GB}}


def note_of(v):
    g = v["growth_per_day"]
    gs = "" if g is None else f"({'+' if g >= 0 else '-'}{abs(g) / MB:.0f}MB/日)"
    s = f"{v['db_bytes'] / GB:.2f}GB{gs}"
    return s + (f" 注意 {len(v['warn'])} 件" if v["warn"] else "")


def main(argv):
    dry = "--dry-run" in argv
    now = dt.datetime.now(dt.timezone.utc)
    try:
        cat = read_catalog()
    except Exception as e:                          # noqa: BLE001
        msg = f"catalog が読めない: {type(e).__name__}: {str(getattr(e, 'stderr', '') or e)[:160]}"
        print("::error::" + msg, flush=True)
        if not dry:
            beat.beat(JOB, False, msg[:120])
        return 1
    v = build(cat, read_prev(), now)
    print(f"DB {v['db_bytes'] / GB:.2f}GB 伸び {v['growth_per_day']} B/日", flush=True)
    for t in v["tables"][:10]:
        print(f"  {t['name']:28s} {t['bytes'] / MB:8.0f}MB {t['rows']:>10d} 行", flush=True)
    for w in v["warn"]:
        print("::warning::" + w, flush=True)
    if dry:
        return 0
    try:
        upsert(v)
    except Exception as e:                          # noqa: BLE001
        print(f"::error::nar_meta {META_KEY} が書けない: {type(e).__name__}: {str(e)[:120]}", flush=True)
        beat.beat(JOB, False, "nar_meta に書けない")
        return 1
    beat.beat(JOB, True, note_of(v))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:                            # noqa: BLE001
            pass
    sys.exit(main(sys.argv[1:]))
