# -*- coding: utf-8 -*-
"""監査 A7(2026-09-24) 集計 6 本(venue_stats / person_stats / ai_record / race_level / graded / big_payouts)を
Actions 内の Postgres で計算し、本番との差分だけを戻す台本。便は .github/workflows/nar-stats.yml。

  python3 pipeline/stats_local/stats_local.py dump [--asof ISO]   ①④ 本番から入力表・出力表・推定行数を写す(⛔読むだけ)
  python3 pipeline/stats_local/stats_local.py load                ② 手元に入れて analyze
  python3 pipeline/stats_local/stats_local.py run                 ③ 集計 SQL 6 本を**そのまま**手元で流す
  python3 pipeline/stats_local/stats_local.py diff                ⑤ 表ごとに 同じ/変わった/手元だけ/本番だけ をログへ
  python3 pipeline/stats_local/stats_local.py apply [--allow-large]  差分を REST で本番へ(安全柵に掛かれば何も書かない)

⛔標準ライブラリだけ・psql を子プロセスで呼ぶ。
⛔本番への接続は dump(読むだけ・default_transaction_read_only)と apply(REST の upsert/delete)だけ。
⛔ログに秘密・入力の生データを出さない(出すのは行数と見本の鍵だけ)。
環境変数:
  本番 psql= PROD_PGPASSWORD(他は下の定数)/ 本番 REST= SUPABASE_URL・SUPABASE_SERVICE_KEY
  手元 psql= PGHOST・PGPORT・PGUSER・PGDATABASE・PGPASSWORD(便の env)
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DUMP = os.path.join(ROOT, "dump")
PROD = dict(host="aws-0-ap-northeast-1.pooler.supabase.com", port="5432",
            user="postgres.qgsnsdjvzzeazbazjlwa", db="postgres")

# 入力表= 本番から写す列(⛔schema.sql の並びと同じ)と、手元で付ける主キー/索引
INPUTS = {
    "nar_runs": ("track, race_date, race_no, runner_number, gate, horse_name, jockey, trainer, finish, finish_note, "
                 "time_sec, popularity, last3f, updated_at",
                 "alter table public.nar_runs add primary key (track, race_date, race_no, runner_number)"),
    "nar_races": ("track, race_date, race_no, post_time, race_name, surface, distance_m, going, field_size, "
                  "prize_yen, race_kind, updated_at",
                  "alter table public.nar_races add primary key (track, race_date, race_no)"),
    "nar_race_payouts": ("track, race_date, race_no, payouts, updated_at",
                         "alter table public.nar_race_payouts add primary key (track, race_date, race_no)"),
    "nar_horses": ("horse_name, sire, broodmare_sire, owner, updated_at",
                   "alter table public.nar_horses add primary key (horse_name)"),
    "nar_ai_marks": ("model, track, race_date, race_no, timing, marks, computed_at, updated_at",
                     "create index on public.nar_ai_marks (track, race_date, race_no)"),
}

# 出力表= (主キー, 比べる列の式)。updated_at は now() なので比べない。
# ⛔nar_jockey_track_stats.as_of(集計した日)も比べない= 毎日全行が「変わった」になるため(要判断: 画面は as_of を表示に使う)
OUTPUTS = {
    "nar_venue_stats": (["track", "period"], ["stats"]),
    "nar_person_stats": (["kind", "name", "track", "period"], ["stats"]),
    "nar_pair_stats": (["key"], ["kind", "a", "b", "stats"]),
    "nar_jockey_track_stats": (["kind", "track", "period", "a", "b"], ["stats"]),
    "nar_ai_record": (["model", "track", "timing"], ["stats"]),
    "nar_race_level": (["track", "race_date", "race_no"], ["stats"]),
    "nar_graded": (["track", "race_date", "race_no"],
                   ["race_name", "race_kind", "distance_m", "post_time", "field_size", "prize1_yen",
                    "winner_horse", "winner_jockey", "winner_pop"]),
    # big_payouts の 'built'(作った時刻)は比べない
    "nar_meta": (["key"], ["value - 'built'"]),
}
OUT_COLS = {
    "nar_venue_stats": "track, period, stats, updated_at",
    "nar_person_stats": "kind, name, track, period, stats, updated_at",
    "nar_pair_stats": "key, kind, a, b, stats, updated_at",
    "nar_jockey_track_stats": "kind, track, period, a, b, stats, as_of, updated_at",
    "nar_ai_record": "model, track, timing, stats, updated_at",
    "nar_race_level": "track, race_date, race_no, stats, updated_at",
    "nar_graded": ("track, race_date, race_no, race_name, race_kind, distance_m, post_time, field_size, prize1_yen, "
                   "winner_horse, winner_jockey, winner_pop, updated_at"),
    "nar_meta": "key, value, updated_at",
}
OUT_WHERE = {"nar_meta": "where key = 'big_payouts'"}
SQLS = ["venue_stats", "person_stats", "ai_record", "race_level", "graded", "big_payouts"]

INPUT_MIN_RATIO = 0.99   # 入力が本番の推定行数のこれ未満なら apply しない
CHANGE_MAX_RATIO = 0.30  # 1 表で(変わった+消す)が本番行数のこれを超えたら apply しない(--allow-large で許す)
BATCH = 500


def log(*a):
    print(*a, flush=True)


def psql_local(sql, fetch=False):
    cmd = ["psql", "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-At"] if fetch else []) + ["-c", sql]
    r = subprocess.run(cmd, check=True, capture_output=fetch, text=True, encoding="utf-8")
    return r.stdout if fetch else None


def psql_local_file(path):
    subprocess.run(["psql", "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", path], check=True)


def rows(sql):
    out = psql_local(sql, fetch=True)
    return [ln.split("|") for ln in out.splitlines() if ln != ""]


# ------------------------------------------------------------------ ①④ 本番から写す(⛔読むだけ)
def cmd_dump(asof):
    if asof and not re.fullmatch(r"[0-9T:.+\- Z]{10,40}", asof):
        raise SystemExit("asof の形がおかしい: ISO 時刻だけ")
    os.makedirs(DUMP, exist_ok=True)
    lines = ["set default_transaction_read_only = on;", "set statement_timeout = '10min';", "begin read only;"]
    for t, (cols, _) in INPUTS.items():
        # 時刻合わせ= updated_at <= asof の行だけ(5 表とも updated_at あり)
        w = f" where updated_at <= '{asof}'::timestamptz" if asof else ""
        lines.append(f"\\copy (select {cols} from public.{t}{w}) to '{DUMP}/in_{t}.tsv'")
    for t, cols in OUT_COLS.items():
        lines.append(f"\\copy (select {cols} from public.{t} {OUT_WHERE.get(t, '')}) to '{DUMP}/out_{t}.tsv'")
    names = ",".join(f"'{t}'" for t in list(INPUTS) + list(OUTPUTS))
    lines.append(
        "\\copy (select c.relname, (case when c.relkind = 'p' then (select coalesce(sum(greatest(ch.reltuples, 0)), 0) "
        "from pg_inherits i join pg_class ch on ch.oid = i.inhrelid where i.inhparent = c.oid) "
        f"else greatest(c.reltuples, 0) end)::bigint from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        f"where n.nspname = 'public' and c.relname in ({names})) to '{DUMP}/prod_est.tsv'")
    lines.append("commit;")
    script = "\n".join(lines) + "\n"
    env = dict(os.environ, PGPASSWORD=os.environ["PROD_PGPASSWORD"], PGSSLMODE="require")
    for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE"):
        env.pop(k, None)
    t0 = time.time()
    subprocess.run(["psql", "-h", PROD["host"], "-p", PROD["port"], "-U", PROD["user"], "-d", PROD["db"],
                    "-v", "ON_ERROR_STOP=1", "-X", "-q"], input=script, text=True, encoding="utf-8",
                   env=env, check=True)
    log(f"dump 済み {time.time() - t0:.0f} 秒 asof={asof or '(なし)'}")
    for f in sorted(os.listdir(DUMP)):
        log(f"  {f}  {os.path.getsize(os.path.join(DUMP, f)) / 1e6:.1f} MB")


# ------------------------------------------------------------------ ② 手元に入れる
def cmd_load():
    t0 = time.time()
    psql_local_file(os.path.join(ROOT, "pipeline/stats_local/schema.sql"))
    for t in INPUTS:
        psql_local(f"\\copy public.{t} from '{DUMP}/in_{t}.tsv'")
    for t, (_, ddl) in INPUTS.items():
        psql_local(ddl)
    psql_local("analyze")
    for t in INPUTS:
        log(f"  {t}: {rows(f'select count(*) from public.{t}')[0][0]} 行")
    log(f"load 済み {time.time() - t0:.0f} 秒")


# ------------------------------------------------------------------ ③ 集計 SQL をそのまま流す
def cmd_run():
    for s in SQLS:
        t0 = time.time()
        r = subprocess.run(["psql", "-v", "ON_ERROR_STOP=1", "-X", "-f", os.path.join(ROOT, f"pipeline/sql/{s}.sql")],
                           capture_output=True, text=True, encoding="utf-8")
        tail = "\n".join(r.stdout.splitlines()[-12:])
        log(f"::group::{s}.sql {time.time() - t0:.0f} 秒 rc={r.returncode}\n{tail}\n{r.stderr[-2000:]}\n::endgroup::")
        log(f"{s}.sql {time.time() - t0:.1f} 秒")
        if r.returncode != 0:
            raise SystemExit(f"{s}.sql が失敗")


# ------------------------------------------------------------------ ⑤ 差分
def _load_prod_outputs():
    for t in OUTPUTS:
        psql_local(f"drop table if exists prod.{t}")
        psql_local(f"create table prod.{t} (like public.{t})")
        psql_local(f"\\copy prod.{t} ({OUT_COLS[t]}) from '{DUMP}/out_{t}.tsv'")


def _diff_table(t):
    keys, cmp = OUTPUTS[t]
    k0 = keys[0]
    eq = " and ".join(f"(l.{c}) is not distinct from (p.{c})" if " " not in c else
                      f"(l.{c.split(' ')[0]} {c.split(' ', 1)[1]}) is not distinct from (p.{c.split(' ')[0]} {c.split(' ', 1)[1]})"
                      for c in cmp)
    canon = " and ".join(
        (f"public.stats_canon(l.{c}) is not distinct from public.stats_canon(p.{c})" if c in ("stats", "value")
         else f"(l.{c}) is not distinct from (p.{c})") if " " not in c else
        f"public.stats_canon(l.{c.split(' ')[0]} {c.split(' ', 1)[1]}) is not distinct from "
        f"public.stats_canon(p.{c.split(' ')[0]} {c.split(' ', 1)[1]})"
        for c in cmp)
    kl = ", ".join(f"coalesce(l.{k}, p.{k}) as {k}" for k in keys)
    psql_local(f"drop table if exists prod.diff_{t}")
    psql_local(
        f"create table prod.diff_{t} as select {kl}, case when p.{k0} is null then 'local_only' "
        f"when l.{k0} is null then 'prod_only' when {eq} then 'same' when {canon} then 'order_only' "
        f"else 'changed' end as st from public.{t} l full join prod.{t} p using ({', '.join(keys)})")


def cmd_diff():
    _load_prod_outputs()
    summary = {}
    log("表 | 手元 | 本番 | 同じ | 変わった(うち順だけ) | 手元だけ | 本番だけ | (変わった+消す)/本番")
    for t, (keys, _) in OUTPUTS.items():
        _diff_table(t)
        c = dict((a, int(b)) for a, b in rows(f"select st, count(*) from prod.diff_{t} group by st"))
        nl = int(rows(f"select count(*) from public.{t}")[0][0])
        npd = int(rows(f"select count(*) from prod.{t}")[0][0])
        ch = c.get("changed", 0) + c.get("order_only", 0)
        ratio = (ch + c.get("prod_only", 0)) / npd if npd else (1.0 if nl else 0.0)
        summary[t] = dict(local=nl, prod=npd, same=c.get("same", 0), changed=ch, order_only=c.get("order_only", 0),
                          local_only=c.get("local_only", 0), prod_only=c.get("prod_only", 0), ratio=ratio)
        log(f"{t} | {nl} | {npd} | {c.get('same', 0)} | {ch}({c.get('order_only', 0)}) | {c.get('local_only', 0)} | "
            f"{c.get('prod_only', 0)} | {ratio:.1%}")
        ks = " || '/' || ".join(f"coalesce({k}::text, '')" for k in keys)
        for st in ("changed", "order_only", "local_only", "prod_only"):
            if c.get(st):
                sm = [r[0] for r in rows(f"select {ks} from prod.diff_{t} where st = '{st}' order by 1 limit 5")]
                log(f"    見本 {st}: {sm}")
        # 変わった行で、stats / value の上の段の鍵ごとに何件違うか(原因の当たりを付ける)
        col = "value" if t == "nar_meta" else ("stats" if "stats" in OUTPUTS[t][1] else None)
        if col and c.get("changed"):
            jk = " and ".join(f"l.{k} = d.{k}" for k in keys)
            pk = " and ".join(f"p.{k} = d.{k}" for k in keys)
            got = rows(
                f"select k, count(*) from prod.diff_{t} d join public.{t} l on {jk} join prod.{t} p on {pk}, "
                f"lateral (select k from jsonb_object_keys(l.{col} || p.{col}) k) kk "
                f"where d.st = 'changed' and jsonb_typeof(l.{col}) = 'object' and jsonb_typeof(p.{col}) = 'object' "
                f"and (l.{col} -> k) is distinct from (p.{col} -> k) group by k order by 2 desc limit 12")
            log(f"    違う鍵: {[(a, int(b)) for a, b in got]}")
    with open(os.path.join(DUMP, "diff_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False)
    return summary


# ------------------------------------------------------------------ apply(REST)
def _rest(method, path, body=None, prefer=None):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    for i in range(4):
        try:
            req = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, method=method, headers=h)
            with urllib.request.urlopen(req, timeout=120) as r:
                r.read()
            return
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == 3:
                raise RuntimeError(f"REST {method} {path.split('?')[0]} → {e.code} {e.read()[:300]!r}")
        except urllib.error.URLError:
            if i == 3:
                raise
        time.sleep(5 * (i + 1))


def _q(v):
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def cmd_apply(allow_large):
    summary = cmd_diff()
    est = dict((a, int(b)) for a, b in (ln.split("\t") for ln in open(os.path.join(DUMP, "prod_est.tsv"), encoding="utf-8")
                                         if ln.strip()))
    stop = []
    for t in INPUTS:
        n = int(rows(f"select count(*) from public.{t}")[0][0])
        if n < INPUT_MIN_RATIO * est.get(t, 0):
            stop.append(f"入力 {t} {n} 行 < 本番の推定 {est.get(t)} の {INPUT_MIN_RATIO:.0%}")
    for t, s in summary.items():
        if s["ratio"] > CHANGE_MAX_RATIO and not allow_large:
            stop.append(f"{t} の(変わった+消す)が {s['ratio']:.1%} > {CHANGE_MAX_RATIO:.0%}")
    if stop:
        for m in stop:
            log("安全柵: " + m)
        raise SystemExit("安全柵に掛かった= 本番には何も書いていない")
    for t, (keys, _) in OUTPUTS.items():
        s = summary[t]
        jk = " and ".join(f"l.{k} = d.{k}" for k in keys)
        up = [json.loads(ln) for ln in psql_local(
            f"select row_to_json(l) from public.{t} l join prod.diff_{t} d on {jk} "
            f"where d.st in ('changed', 'order_only', 'local_only')", fetch=True).splitlines() if ln]
        for i in range(0, len(up), BATCH):
            _rest("POST", f"{t}?on_conflict={','.join(keys)}", up[i:i + BATCH],
                  prefer="resolution=merge-duplicates,return=minimal")
        gone = rows(f"select {', '.join(f'{k}::text' for k in keys)} from prod.diff_{t} where st = 'prod_only'")
        for i in range(0, len(gone), 50):
            part = gone[i:i + 50]
            if len(keys) == 1:
                flt = f"{keys[0]}=in.({','.join(_q(r[0]) for r in part)})"
            else:
                ors = ",".join("and(" + ",".join(f"{k}.eq.{_q(v)}" for k, v in zip(keys, r)) + ")" for r in part)
                flt = "or=(" + ors + ")"
            _rest("DELETE", f"{t}?" + urllib.parse.quote(flt, safe="=&"), prefer="return=minimal")
        log(f"apply {t}: upsert {len(up)} 行 / 消す {len(gone)} 行(見込み {s['changed'] + s['local_only']} / {s['prod_only']})")


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    c = argv[0]
    if c == "dump":
        asof = argv[argv.index("--asof") + 1] if "--asof" in argv else ""
        cmd_dump(asof.strip())
    elif c == "load":
        cmd_load()
    elif c == "run":
        cmd_run()
    elif c == "diff":
        cmd_diff()
    elif c == "apply":
        cmd_apply("--allow-large" in argv)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
