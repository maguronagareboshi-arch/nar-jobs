# -*- coding: utf-8 -*-
"""送信量の目安の見張り(2026-11-05・Supabase の送信量が 10 月に 414GB/枠 250GB で超過した再発防止)。

  python3 cloud/egress_watch.py            … 数えて nar_meta 'egress_watch' へ upsert・急増なら終了コード 1
  python3 cloud/egress_watch.py --dry-run  … 数えるだけ(書かない)

⛔目安。送った量(GB)は管理 API が無いと読めないので、pg_stat_statements の累計の差で代わりに数える:
  anon= 閲覧者の REST の回数・svc= 便の REST の回数(service_role)・pg= 便の直結(postgres)が返した行数。
  累計は統計の消去・入れ替えで減ることがある= 差が負なら数えない。REST は 1 回 1 行と数えられるので回数だけ見る。
決まり: 約 1 時間ごとに累計を控え(30 時間ぶん)、20 時間以上前の控えとの差を 24 時間に直して「1 日の量」とする。
  JST の日ごとに 1 つ残し(14 日ぶん)、その日の量が前の日々(3 日以上)の中央値の WARN_RATIO 倍を超えたら警告。
読むのは pg_stat_statements の集計 1 本だけ(軽い)。書くのは nar_meta 1 行だけ。
"""
import datetime as dt
import json
import os
import statistics
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beat  # noqa: E402

PG_HOST = "aws-0-ap-northeast-1.pooler.supabase.com"
PG_USER = "postgres.qgsnsdjvzzeazbazjlwa"
META_KEY = "egress_watch"
WARN_RATIO = float(os.environ.get("EGRESS_WARN_RATIO", "1.5"))
KEYS = ("anon", "svc", "pg")
LABEL = {"anon": "閲覧者の取得回数", "svc": "便の取得回数", "pg": "便の直結の行数"}

SQL = """
select json_build_object(
  'anon', coalesce(sum(s.calls) filter (where r.rolname = 'anon'), 0)::bigint,
  'svc',  coalesce(sum(s.calls) filter (where r.rolname = 'service_role'), 0)::bigint,
  'pg',   coalesce(sum(s.rows)  filter (where r.rolname = 'postgres'), 0)::bigint)::text
from extensions.pg_stat_statements s join pg_roles r on r.oid = s.userid;
"""


def read_now():
    out = subprocess.run(
        ["psql", "-h", PG_HOST, "-p", "5432", "-U", PG_USER, "-d", "postgres",
         "-v", "ON_ERROR_STOP=1", "-X", "-A", "-t", "-c", SQL],
        check=True, capture_output=True, text=True, timeout=120)
    return json.loads(out.stdout.strip())


def read_prev():
    got = beat._req(f"nar_meta?select=value&key=eq.{META_KEY}")
    return (got[0]["value"] if got else None) or {}


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


def step(prev, cur, now):
    """prev= 前回の value・cur= 今の累計・now= 今(aware)。→ (新しい value, 警告の配列)"""
    snaps = [s for s in (prev.get("snaps") or [])
             if (now - dt.datetime.fromisoformat(s["at"])).total_seconds() <= 30 * 3600]
    if not snaps or (now - dt.datetime.fromisoformat(snaps[-1]["at"])).total_seconds() >= 50 * 60:
        snaps.append({"at": now.isoformat(), **{k: int(cur[k]) for k in KEYS}})
    days = list(prev.get("days") or [])
    today = now.astimezone(beat.JST).date().isoformat()
    old = [s for s in snaps if (now - dt.datetime.fromisoformat(s["at"])).total_seconds() >= 20 * 3600]
    day = None
    if old:
        base = old[-1]
        hours = (now - dt.datetime.fromisoformat(base["at"])).total_seconds() / 3600
        day = {"date": today}
        for k in KEYS:
            d = int(cur[k]) - int(base[k])
            day[k] = round(d * 24 / hours) if d >= 0 else None      # 負= 統計の消去・入れ替え= 数えない
        days = [x for x in days if x["date"] != today] + [day]
    days = days[-14:]
    warn = []
    if day:
        past = [x for x in days if x["date"] != today]
        for k in KEYS:
            hist = [x[k] for x in past if x.get(k)]
            if day.get(k) and len(hist) >= 3:
                med = statistics.median(hist)
                if med and day[k] > med * WARN_RATIO:
                    warn.append(f"{LABEL[k]}が 1 日 {day[k]:,}(ふだん {int(med):,} の {day[k] / med:.1f} 倍)")
    return {"at": now.isoformat(), "snaps": snaps, "days": days, "warn": warn}, warn


def main(argv):
    now = dt.datetime.now(dt.timezone.utc)
    cur = read_now()
    v, warn = step(read_prev(), cur, now)
    print("今の累計:", json.dumps(cur))
    for x in v["days"][-7:]:
        print("  ", x["date"], "  ".join(f"{LABEL[k]} {x.get(k)}" for k in KEYS))
    if "--dry-run" not in argv:
        upsert(v)
    for w in warn:
        print("::warning::" + w)
    return 1 if warn else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
