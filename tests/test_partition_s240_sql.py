# -*- coding: utf-8 -*-
"""§240 パーティション移行 SQL の形だけの検査(⛔手元に PostgreSQL は無いので実行はしない)。
見るのは形だけ:
  1) begin と commit の数が合っている(1 ステップ 1 トランザクションの崩れを拾う)
  2) vacuum がトランザクションの中に入っていない(⛔中で流すと必ず落ちる)
  3) `$$ ... $$`(do ブロック)が閉じている・最後が ; で終わっている
  4) 親に作る索引の名前が旧表の索引名とぶつかっていない(`_p_` が入っている)
  5) 区画の範囲が 2022-11-01 〜 2031-01-01 まで隙間なく続いている(2030 まで)
  6) archive の attach が `_archive_part` を (minvalue) → 2022-11-01
  7) 差分+rename 2 本+notify が同じトランザクション・delete は rename より後で相手が _archive_part
  8) insert/delete の刻みに statement_timeout が付いている
  9) notify pgrst がある
 10) grant all privileges がある(本番は anon/authenticated/service_role に全権限)
 11) nar_races だけ= 依存 view nar_sales_hourly を rename の後・同じトランザクションで作り直している
⛔見ていないもの= 本番の実物との一致(それは各ファイルの §0 を流して人が確かめる)。
使い方: py -3.12 tests/test_partition_s240_sql.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_DIR = os.path.join(ROOT, "pipeline", "sql", "partition_s240")
TABLES = ["nar_race_votes", "nar_race_payouts", "nar_races", "nar_runs", "nar_run_facts"]
MIGRATIONS = ["10_nar_race_votes.sql", "20_nar_race_payouts.sql", "30_nar_races.sql",
              "40_nar_runs.sql", "50_nar_run_facts.sql"]
OTHERS = ["00_baseline_counts.sql", "98_rollback.sql", "99_verify.sql"]

errors = []


def fail(fn, msg):
    errors.append("%s: %s" % (fn, msg))


def strip_noise(sql):
    """行コメントと '…' の中身を空白に潰す(begin/commit や ; を数えるため)。
    ⛔$$ … $$ は潰さない(do ブロックの中の begin/end は別に数える)。"""
    out = []
    for line in sql.split("\n"):
        line = re.sub(r"--.*$", "", line)
        line = re.sub(r"'(?:[^']|'')*'", "''", line)
        out.append(line)
    return "\n".join(out)


def split_dollar(sql):
    """$$ … $$ の中と外に分ける。返り= (外だけを繋いだ文字列, 中の個数, 閉じているか)"""
    parts = sql.split("$$")
    outside = "".join(parts[0::2])
    return outside, len(parts) // 2, (len(parts) % 2 == 1)


def check_one(fn, path, is_migration):
    sql = io.open(path, encoding="utf-8").read()
    # 行コメントだけ落としたもの(日付などの文字列を残す= 5) 以降の検査に使う)
    nocomment = "\n".join(re.sub(r"--.*$", "", ln) for ln in sql.split("\n"))
    nocomment, _, _ = split_dollar(nocomment)
    body = strip_noise(sql)
    outside, n_blocks, closed = split_dollar(body)
    if not closed:
        fail(fn, "$$ が閉じていない(do ブロックの数= %d)" % n_blocks)

    # 1) begin / commit の数(⛔$$ の外だけ数える)
    n_begin = len(re.findall(r"(?mi)^\s*begin\s*;", outside))
    n_commit = len(re.findall(r"(?mi)^\s*commit\s*;", outside))
    if n_begin != n_commit:
        fail(fn, "begin %d 個 / commit %d 個(数が合わない)" % (n_begin, n_commit))
    if re.search(r"(?mi)^\s*rollback\s*;", outside):
        fail(fn, "rollback が書いてある(⛔流す手順に混ぜない)")

    # 2) vacuum がトランザクションの中に無いこと
    depth = 0
    for i, line in enumerate(outside.split("\n"), start=1):
        s = line.strip().lower()
        if re.match(r"^begin\s*;", s):
            depth += 1
        elif re.match(r"^commit\s*;", s):
            depth -= 1
            if depth < 0:
                fail(fn, "%d 行目: commit が begin より多い" % i)
                depth = 0
        elif s.startswith("vacuum") and depth > 0:
            fail(fn, "%d 行目: vacuum がトランザクションの中にある" % i)
    if depth != 0:
        fail(fn, "閉じていない begin が %d 個" % depth)

    # 3) 最後の文が ; で終わっている
    tail = outside.rstrip()
    if tail and not tail.endswith(";"):
        fail(fn, "最後の文が ; で終わっていない")

    if not is_migration:
        return

    # 4) 親に作る索引名が `_p_` を含む(旧表の索引名との衝突よけ)
    for m in re.finditer(r"(?i)create\s+index\s+(?:if\s+not\s+exists\s+)?([a-z0-9_]+)\s+on\s+public\.([a-z0-9_]+)",
                         outside):
        idx, tbl = m.group(1), m.group(2)
        if tbl.endswith("_p") and "_p_" not in idx:
            fail(fn, "親の索引名に `_p_` が無い= 旧表の索引名とぶつかる恐れ: %s" % idx)

    # 5) 区画の範囲が 2022-11-01 から 2031-01-01 まで隙間なく続いていること(2030 まで先に作る)
    ranges = re.findall(r"for\s+values\s+from\s+\('(\d{4}-\d{2}-\d{2})'\)\s+to\s+\('(\d{4}-\d{2}-\d{2})'\)", nocomment)
    if len(ranges) != 8:
        fail(fn, "区画の範囲が 8 つでない(%d 個)" % len(ranges))
    else:
        if ranges[0][0] != "2022-11-01":
            fail(fn, "最初の区画が 2022-11-01 から始まっていない: %s" % ranges[0][0])
        for a, b in zip(ranges, ranges[1:]):
            if a[1] != b[0]:
                fail(fn, "区画に隙間か重なり: %s → %s" % (a[1], b[0]))
        if ranges[-1][1] != "2031-01-01":
            fail(fn, "最後の区画が 2031-01-01 で終わっていない: %s" % ranges[-1][1])

    # 6) archive の attach は `<表>_archive_part` を (minvalue) to ('2022-11-01') で付ける
    #    ⛔新しい順では rename が先= attach するのは `_archive_part` に改名された側。
    m = re.search(r"attach\s+partition\s+public\.([a-z0-9_]+)\s+for\s+values\s+from\s+\(minvalue\)\s+to\s+\('2022-11-01'\)",
                  nocomment, re.I)
    if not m:
        fail(fn, "archive 区画の attach(minvalue → 2022-11-01)が見つからない")
    elif not m.group(1).endswith("_archive_part"):
        fail(fn, "attach する先が `_archive_part` でない: %s" % m.group(1))

    # 7) §4' の 差分 + rename 2 本 + notify が**同じトランザクション**に入っていること
    ren = [mm.start() for mm in re.finditer(r"(?i)alter\s+table\s+public\.[a-z0-9_]+\s+rename\s+to", nocomment)]
    if len(ren) < 2:
        fail(fn, "rename が 2 本そろっていない")
    else:
        b = nocomment.rfind("begin;", 0, ren[0])
        c = nocomment.find("commit;", ren[-1])
        if b < 0 or c < 0:
            fail(fn, "rename がトランザクションの中に入っていない")
        elif "notify pgrst" not in nocomment[b:c].lower():
            fail(fn, "notify pgrst が rename と同じトランザクションの中に無い")
        elif "insert into" not in nocomment[b:ren[0]].lower():
            fail(fn, "§4'(i) の差分の取り直しが rename と同じトランザクションの中に無い")

        # 7-b ⛔順序= rename(§4')が最初の delete(§3')より前にあること
        d = re.search(r"(?im)^\s*delete\s+from\s+public\.([a-z0-9_]+)", nocomment)
        if d and d.start() < ren[0]:
            fail(fn, "delete が rename より先にある(旧い順= 今年のデータが消える窓ができる)")
        if d and not d.group(1).endswith("_archive_part"):
            fail(fn, "delete の相手が `_archive_part` でない(§3' は改名後の表を掃除する): %s" % d.group(1))

    # 8) statement_timeout が insert / delete のステップに入っている
    if nocomment.lower().count("set local statement_timeout = '30min'") < 4:
        fail(fn, "set local statement_timeout = '30min' が 4 回未満(insert/delete の刻みに付いていない)")

    # 9) PostgREST の読み直し
    if "notify pgrst" not in nocomment.lower():
        fail(fn, "notify pgrst, 'reload schema' が無い")

    # 10) grant は本番と同じ「全権限」(⛔select だけにすると便の書きが止まる)
    if "grant all privileges" not in nocomment.lower():
        fail(fn, "grant all privileges が無い(本番は anon/authenticated/service_role に全権限)")

    # 11) nar_races だけ= 依存 view `nar_sales_hourly` を §4' の rename の**後**・同じ
    #     トランザクションの中で create or replace view している(⛔view は OID で結び付くため)
    if fn.startswith("30_"):
        v = nocomment.lower().find("create or replace view public.nar_sales_hourly")
        ren2 = [mm.start() for mm in
                re.finditer(r"(?i)alter\s+table\s+public\.[a-z0-9_]+\s+rename\s+to", nocomment)]
        c2 = nocomment.find("commit;", ren2[-1]) if ren2 else -1
        if v < 0:
            fail(fn, "依存 view nar_sales_hourly の create or replace view が無い")
        elif not ren2 or v < ren2[-1]:
            fail(fn, "view の作り直しが rename より先にある(⛔rename の後でないと親に結び直せない)")
        elif c2 < 0 or v > c2:
            fail(fn, "view の作り直しが rename と同じトランザクションの中に無い")
        if "marks_writer" not in nocomment:
            fail(fn, "nar_races だけの 2 本目の policy / grant(marks_writer)が無い")
    elif "nar_sales_hourly" in nocomment:
        fail(fn, "nar_races 以外のファイルに nar_sales_hourly が書かれている")


def main():
    if not os.path.isdir(SQL_DIR):
        print("NG: %s が無い" % SQL_DIR)
        return 1
    for fn in MIGRATIONS + OTHERS:
        path = os.path.join(SQL_DIR, fn)
        if not os.path.exists(path):
            fail(fn, "ファイルが無い")
            continue
        check_one(fn, path, fn in MIGRATIONS)

    # 表ごとに 1 ファイル・番号の順
    for t, fn in zip(TABLES, MIGRATIONS):
        if not fn.endswith(t + ".sql"):
            fail(fn, "表とファイル名が対応していない(%s)" % t)

    if errors:
        print("NG (%d 件)" % len(errors))
        for e in errors:
            print("  -", e)
        return 1
    print("ALL PASS (%d ファイル)" % (len(MIGRATIONS) + len(OTHERS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
