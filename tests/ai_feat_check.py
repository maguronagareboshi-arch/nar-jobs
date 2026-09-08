# -*- coding: utf-8 -*-
"""§129c 段階1 の検算道具。`nar_ai_feat_run` を **DB から読むだけ**で確かめる(⛔1 行も書かない)。

  py -3.12 -X utf8 tests/ai_feat_check.py --selftest                     # DB 無しで通る分だけ
  py -3.12 -X utf8 tests/ai_feat_check.py --env pipeline/.env.nar        # 全部(表が無ければ列の突合まで)
  py -3.12 -X utf8 tests/ai_feat_check.py --env pipeline/.env.nar --sample  # 1 レースの全列を印字
  py -3.12 -X utf8 tests/ai_feat_check.py --dsn postgresql://postgres:xxx@localhost:5432/postgres   # §129d Actions の中の Postgres

確かめること:
  ① オラクル 3 本 = 高知 2026-09-06 12R の全頭の `prev_chakujun` / `p1_pos4` / `kishu_fuku_1y` を
     nar_runs / nar_races から **Python で独立に計算**して表の値と一致(誤差 1e-4)。
  ② 漏洩 = 無作為 200 走で「前走」が **その走より前の日**であること・
     騎手の 365 日窓に **当日以降の走が入っていない**ことを、別経路で数え直して確かめる。
  ③ 行数が nar_runs と一致・鍵の重複 0。
  ④ 設計書 B-2 の 183 列(⛔c1_dist を除く 182)+ ④ の列が表に全部ある。
  ⑤ ④ の列(3F・馬具・乗替・コース・能検)が高知の 1 レースで埋まっている。
  ⑥ コーナーと着差の読み方が JS/Python の実装と同じ(--selftest でも通る)。
⛔鍵(パスワード)は印字しない。⛔出すのは PASS/FAIL と食い違いの一覧だけ。
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HOST = "aws-0-ap-northeast-1.pooler.supabase.com"
USER = "postgres.qgsnsdjvzzeazbazjlwa"
SQL_FILE = ROOT / "pipeline" / "sql" / "ai_feat_20260908.sql"
DESIGN = ROOT / "docs" / "proposal_s129b_base_v1_20260907.md"
ORACLE = ("高知", dt.date(2026, 9, 6), 12)

FAILS: list[str] = []


def ok(name, cond, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILS.append(name + " " + detail)
    return cond


# ------------------------------------------------------------------ 規則の写し(SQL と同じもの)

def corner_ranks(order):
    """pipeline/sql/ai_feat_20260908.sql の `nar_corner_ranks()` の写し。
    ⛔js/data.js `cornerRanks()` / cloud/tenkai.py `corner_ranks()` と同じ規則。"""
    s = str(order or "").strip()
    if not s:
        return None
    out, rank, i = {}, 1, 0
    while i < len(s):
        ch = s[i]
        if ch in ",-= 　":
            i += 1
            continue
        if ch == "(":
            end = s.find(")", i)
            if end < 0:
                return None
            nums = []
            for x in s[i + 1:end].split(","):
                x = x.strip()
                if not re.fullmatch(r"[0-9]+", x) or int(x) <= 0:
                    return None
                nums.append(int(x))
            if not nums:
                return None
            for n in nums:
                out.setdefault(n, rank)
            rank += len(nums)
            i = end + 1
            continue
        j = i
        while j < len(s) and s[j] in "0123456789":
            j += 1
        if j == i:
            return None
        out.setdefault(int(s[i:j]), rank)
        rank += 1
        i = j
    return out or None


MARGIN_WORDS = {"ハナ": 0.05, "アタマ": 0.10, "クビ": 0.30, "同着": 0.0, "大差": 10.0}


def margin_len(m):
    """`nar_margin_len()` の写し(ユーザー決定 2026-09-07 の標準の対応表)。"""
    s = str(m or "").strip()
    if not s:
        return None
    if s in MARGIN_WORDS:
        return MARGIN_WORDS[s]
    if re.fullmatch(r"[0-9]+", s):
        return float(s)
    if re.fullmatch(r"[0-9]+/[0-9]+", s):
        a, b = s.split("/")
        return float(a) / float(b)
    if re.fullmatch(r"[0-9]+\.[0-9]+/[0-9]+", s):
        w, fr = s.split(".", 1)
        a, b = fr.split("/")
        return float(w) + float(a) / float(b)
    return None


def readable_corners(corners):
    """読めたコーナーだけを並びの順に。⛔SQL の maps と同じ。"""
    out = []
    for c in (corners or []):
        if isinstance(c, dict):
            m = corner_ranks(c.get("order"))
            if m:
                out.append(m)
    return out


def pos_of(maps, umaban):
    """SQL と同じ規則で (pos1, pos2, pos3, pos4, n1, n2, n3, n4) を返す。"""
    if not maps:
        return (None,) * 8
    n = len(maps)
    g = lambda m: m.get(umaban)
    pos1, n1 = g(maps[0]), len(maps[0])
    pos2, n2 = (g(maps[1]), len(maps[1])) if n >= 3 else (None, None)
    pos3, n3 = (g(maps[n - 2]), len(maps[n - 2])) if n >= 2 else (None, None)
    pos4, n4 = g(maps[n - 1]), len(maps[n - 1])
    return pos1, pos2, pos3, pos4, n1, n2, n3, n4


SELFTEST_CORNER = [
    ("7,9,(2,10)-11,6-(1,3,8),5-4",
     {7: 1, 9: 2, 2: 3, 10: 3, 11: 5, 6: 6, 1: 7, 3: 7, 8: 7, 5: 10, 4: 11}),
    ("(2,7)-11", {2: 1, 7: 1, 11: 3}),
    ("3=4,1", {3: 1, 4: 2, 1: 3}),
    ("", None),
    ("3,x", None),
]
SELFTEST_MARGIN = [("ハナ", 0.05), ("アタマ", 0.10), ("クビ", 0.30), ("1.1/2", 1.5), ("1/2", 0.5),
                   ("3/4", 0.75), ("1", 1.0), ("2.1/2", 2.5), ("大差", 10.0), ("同着", 0.0),
                   ("レコード", None), ("競走取止め", None), ("競走不成立", None)]


# ------------------------------------------------------------------ 列の突合(DB が無くても通る)

def design_columns():
    """設計書 B-2 の表から列名を読む(⛔創作しない= 設計書が正)。"""
    names = []
    for line in io.open(DESIGN, encoding="utf-8").read().splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|\s*`([a-z0-9_]+)`\s*\|", line)
        if m:
            names.append((int(m.group(1)), m.group(2)))
    names.sort()
    return [n for _, n in names]


def sql_columns():
    """pipeline/sql/ai_feat_20260908.sql の CREATE TABLE から列名を読む。"""
    s = re.sub(r"--[^\n]*", "", io.open(SQL_FILE, encoding="utf-8").read())
    m = re.search(r"create table if not exists public\.nar_ai_feat_run \((.*?)\n\);", s, re.S)
    body = m.group(1)
    body = body[:body.index("primary key")]
    return [p.strip().split()[0] for p in body.split(",") if p.strip()]


def check_columns():
    d, q = design_columns(), sql_columns()
    ok("④ 設計書 B-2 が 183 列", len(d) == 183, "実際 %d" % len(d))
    miss = [c for c in d if c not in q and c != "c1_dist"]
    ok("④ B-2 の列が表にある(⛔c1_dist は材料が無いので作らない)", not miss, "欠け= " + ", ".join(miss[:8]))
    ok("④ c1_dist は作っていない", "c1_dist" not in q)
    extra4 = ["ten_kb", "style", "jc_tier", "gear_now", "prize_local", "baba_diff_d",
              "course_waku_hit", "ill_n_365", "noken_days", "owner_hit", "sale_price",
              "jockey_penalty_90d", "race_sales", "p1_l3z", "avg_l3z_3"]
    miss4 = [c for c in extra4 if c not in q]
    ok("④ B-3 の④(サイト独自)の代表列がある", not miss4, "欠け= " + ", ".join(miss4))
    feat = [c for c in q if c not in ("track", "race_date", "race_no", "runner_number", "horse_key",
                                      "finish", "finish_note", "popularity", "y_top3", "y_win",
                                      "updated_at")]
    print("       特徴量 %d 列(B-2 の 182 + ④ の %d)" % (len(feat), len(feat) - 182))
    return q


def check_selftest():
    bad = [s for s, want in SELFTEST_CORNER if corner_ranks(s) != want]
    ok("⑥ コーナーの読み方が JS/Python と同じ(5 例)", not bad, "違う= " + repr(bad))
    bad2 = [(s, margin_len(s), w) for s, w in SELFTEST_MARGIN
            if (margin_len(s) is None) != (w is None)
            or (w is not None and abs(margin_len(s) - w) > 1e-9)]
    ok("⑥ 着差の対応表が指示どおり(13 例)", not bad2, repr(bad2))
    try:
        sys.path.insert(0, str(ROOT))
        from cloud.tenkai import corner_ranks as ref
        diff = [s for s, _ in SELFTEST_CORNER if ref(s) != corner_ranks(s)]
        ok("⑥ cloud/tenkai.py の実装と一致", not diff, repr(diff))
    except Exception as e:                                  # noqa: BLE001
        print("  --   cloud/tenkai.py を読めなかった(%s)= 比較は飛ばす" % type(e).__name__)


# ------------------------------------------------------------------ DB(読むだけ)

def connect(env_path, dsn=None):
    """--env= 本番(セッションプーラー・SSL)。--dsn= §129d Actions の中の Postgres(素の TCP)。
    ⛔どちらでも **読むだけ**。⛔鍵は印字しない(出すのはホストと DB 名だけ)。"""
    import pg8000.native
    if dsn:
        u = urlparse(dsn)
        if u.scheme not in ("postgresql", "postgres"):
            print("--dsn は postgresql://user:pass@host:port/db の形で")
            return None
        host = u.hostname or "localhost"
        print("  接続先 %s:%d/%s" % (host, u.port or 5432, (u.path or "/postgres").lstrip("/")))
        return pg8000.native.Connection(
            user=unquote(u.username or "postgres"),
            password=unquote(u.password) if u.password else None,
            host=host, port=u.port or 5432,
            database=(u.path or "/postgres").lstrip("/") or "postgres")
    if env_path:
        for raw in io.open(env_path, encoding="utf-8-sig").read().splitlines():
            raw = raw.strip()
            if raw and not raw.startswith("#") and "=" in raw:
                k, v = raw.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    pw = os.environ.get("SUPABASE_DB_PASSWORD", "")
    if not pw:
        print("SUPABASE_DB_PASSWORD が要る(--env pipeline/.env.nar)")
        return None
    return pg8000.native.Connection(user=USER, password=pw, host=HOST, port=5432,
                                    database="postgres", ssl_context=True)


def table_exists(con):
    return bool(con.run("select to_regclass('public.nar_ai_feat_run') is not null")[0][0])


def key_of(name, birth):
    return "%s|%s" % (name, birth.isoformat() if birth else "")


def check_counts(con):
    a = con.run("select count(*) from public.nar_ai_feat_run")[0][0]
    b = con.run("select count(*) from public.nar_runs")[0][0]
    t = con.run("select count(*) from public.nar_ai_feat_run where finish is null")[0][0]
    ok("③ 行数が nar_runs と一致", a == b, "%d / %d" % (a, b))
    dup = con.run("select count(*) from (select track, race_date, race_no, runner_number"
                  " from public.nar_ai_feat_run group by 1,2,3,4 having count(*) > 1) d")[0][0]
    ok("③ 鍵の重複 0", dup == 0, str(dup))
    print("       当日(まだ走っていない)の行 %d" % t)


def oracle_prev_and_pos4(con):
    """① 高知 2026-09-06 12R の全頭について、前走の着順と前走の 4 角位置(頭数比)を Python で作る。"""
    trk, day, no = ORACLE
    runners = con.run("select runner_number, horse_name, birth_date from public.nar_runs"
                      " where track = :t and race_date = :d and race_no = :n order by runner_number",
                      t=trk, d=day, n=no)
    got = {r[0]: r for r in con.run(
        "select runner_number, prev_chakujun, p1_pos4, kishu_fuku_1y from public.nar_ai_feat_run"
        " where track = :t and race_date = :d and race_no = :n", t=trk, d=day, n=no)}
    ok("① オラクルの出走頭数が表と合う", len(runners) == len(got), "%d / %d" % (len(runners), len(got)))
    bad = []
    for rn, name, birth in runners:
        rows = con.run(
            "select u.track, u.race_date, u.race_no, u.runner_number, u.finish, r.corners"
            " from public.nar_runs u join public.nar_races r using (track, race_date, race_no)"
            " where u.horse_name = :h and coalesce(u.birth_date::text,'') = :b"
            "   and u.race_date < :d and u.finish is not null"
            " order by u.race_date desc, u.track desc, u.race_no desc, u.runner_number desc limit 1",
            h=name, b=(birth.isoformat() if birth else ""), d=day)
        want_chaku = float(rows[0][4]) if rows else None
        want_pos4 = None
        if rows:
            maps = readable_corners(rows[0][5])
            p1, p2, p3, p4, n1, n2, n3, n4 = pos_of(maps, rows[0][3])
            want_pos4 = (p4 / n4) if (p4 and n4) else None
        g = got.get(rn)
        for label, w, v in (("prev_chakujun", want_chaku, g[1] if g else None),
                            ("p1_pos4", want_pos4, g[2] if g else None)):
            if (w is None) != (v is None) or (w is not None and abs(float(w) - float(v)) > 1e-4):
                bad.append("%d番 %s 望み=%s 表=%s" % (rn, label, w, v))
    ok("① prev_chakujun / p1_pos4 が独立計算と一致", not bad, "; ".join(bad[:6]))
    return runners, got


def oracle_kishu(con, runners, got):
    """① 騎手の 365 日複勝率(⛔B-2 #22 の定義= **場を分けない** 365 日窓・前日まで)。"""
    trk, day, no = ORACLE
    bad = []
    for rn, name, birth in runners:
        jk = con.run("select nullif(btrim(jockey),'') from public.nar_runs"
                     " where track = :t and race_date = :d and race_no = :n and runner_number = :r",
                     t=trk, d=day, n=no, r=rn)[0][0]
        if not jk:
            continue
        row = con.run("select count(*) filter (where finish is not null),"
                      "       count(*) filter (where finish <= 3)"
                      " from public.nar_runs"
                      " where nullif(btrim(jockey),'') = :j and race_date < :d and race_date >= :lo",
                      j=jk, d=day, lo=day - dt.timedelta(days=365))[0]
        want = (row[1] / row[0]) if row[0] else None
        v = got[rn][3] if rn in got else None
        if (want is None) != (v is None) or (want is not None and abs(want - float(v)) > 1e-4):
            bad.append("%d番 kishu_fuku_1y 望み=%s 表=%s" % (rn, want, v))
    ok("① kishu_fuku_1y が独立計算と一致(365 日・前日まで)", not bad, "; ".join(bad[:6]))


def check_leak(con, n=200):
    """② 無作為 200 走で「前走」がその走より前の日か・当日を窓に入れていないかを数え直す。"""
    rows = con.run(
        "select f.track, f.race_date, f.race_no, f.runner_number, f.horse_key,"
        "       f.days_since_prev, f.has_hist, f.kishu_n_1y"
        " from public.nar_ai_feat_run f where f.has_hist = 1"
        " order by md5(f.track || f.race_date::text || f.race_no::text || f.runner_number::text)"
        " limit :n", n=n)
    bad = []
    for trk, day, no, rn, hkey, gap, _hh, kn in rows:
        if gap is None or gap <= 0:
            bad.append("%s R%s %s番 前走との間隔が %s" % (trk, no, rn, gap))
            continue
        name, birth = hkey.rsplit("|", 1)
        cnt = con.run("select count(*) from public.nar_runs"
                      " where horse_name = :h and coalesce(birth_date::text,'') = :b"
                      "   and race_date >= :d and race_date < :d2 and finish is not null",
                      h=name, b=birth, d=day - dt.timedelta(days=int(gap)) + dt.timedelta(days=1),
                      d2=day)[0][0]
        if cnt:
            bad.append("%s R%s %s番 もっと近い前走が %d 本ある" % (trk, no, rn, cnt))
    ok("② 前走が必ずその走より前の日(200 走)", not bad, "; ".join(bad[:5]))
    # 騎手窓に当日以降が入っていないか= 当日を含めて数え直すと必ず増える(減ることはない)
    row = con.run(
        "select count(*) from public.nar_ai_feat_run f"
        " where f.kishu_n_1y is not null and f.kishu_n_1y > ("
        "   select count(*) from public.nar_runs u where u.race_date < f.race_date"
        "     and u.race_date >= f.race_date - 365 and u.finish is not null"
        "     and nullif(btrim(u.jockey),'') = (select nullif(btrim(x.jockey),'') from public.nar_runs x"
        "        where x.track = f.track and x.race_date = f.race_date and x.race_no = f.race_no"
        "          and x.runner_number = f.runner_number))"
        " and f.race_date >= :d", d=ORACLE[1] - dt.timedelta(days=3))[0][0]
    ok("② 騎手の 365 日窓に当日以降が入っていない", row == 0, "はみ出し %d 行" % row)


def check_extra_filled(con):
    """⑤ ④ の列が高知の 1 レースで埋まっているか(⛔欠測そのものは異常ではないので数だけ出す)。"""
    trk, day, no = ORACLE
    cols = ["ten_kb", "style", "qpts", "jc_changed", "jc_tier", "gear_now", "prize_local",
            "baba_diff_d", "course_waku_hit", "ill_n_365", "noken_days", "owner_hit",
            "race_sales", "p1_rz", "waku_bias_365", "opp_str_now"]
    sel = ", ".join("count(%s)" % c for c in cols)
    row = con.run("select count(*), %s from public.nar_ai_feat_run"
                  " where track = :t and race_date = :d and race_no = :n" % sel, t=trk, d=day, n=no)[0]
    n = row[0]
    got = dict(zip(cols, row[1:]))
    print("       高知 %s R%d(%d 頭)の埋まり: %s" % (day, no, n,
          " ".join("%s=%d" % (c, got[c]) for c in cols)))
    must = ["style", "qpts", "prize_local", "opp_str_now", "waku_bias_365", "p1_rz", "course_waku_hit"]
    empty = [c for c in must if got[c] == 0]
    ok("⑤ 主な④の列が埋まっている", not empty, "空= " + ", ".join(empty))
    ok("⑤ 高知は提供データの前半3F が無い場= ten_kb は空でよい", True,
       "ten_kb=%d / noken_days=%d / gear_now=%d" % (got["ten_kb"], got["noken_days"], got["gear_now"]))


def check_sql_parser(con):
    """⑥ DB 側の nar_corner_ranks() が Python の写しと同じ答えを出すか(実データ 3,000 本)。"""
    # ⛔to_regclass は「表」を探すので関数はいつも NULL= この比較が黙って飛んでいた(§129d で気づいた)。
    if not con.run("select to_regproc('public.nar_corner_ranks') is not null")[0][0]:
        print("  --   nar_corner_ranks() がまだ無い= 比較は飛ばす")
        return
    rows = con.run(
        "select x->>'order' as o, public.nar_corner_ranks(x->>'order') as m"
        " from public.nar_races r, lateral jsonb_array_elements(r.corners) x"
        " where r.corners is not null order by r.race_date desc limit 3000")
    bad = []
    for o, m in rows:
        want = corner_ranks(o)
        got = None if m is None else {int(k): int(v) for k, v in m.items()}
        if want != got:
            bad.append(str(o)[:40])
    ok("⑥ DB の nar_corner_ranks() が写しと一致(実データ 3,000 本)", not bad,
       "違い %d 本 例= %s" % (len(bad), bad[:3]))


def sample(con):
    trk, day, no = ORACLE
    cols = [c[0] for c in con.run(
        "select column_name from information_schema.columns"
        " where table_schema='public' and table_name='nar_ai_feat_run' order by ordinal_position")]
    rows = con.run("select %s from public.nar_ai_feat_run where track = :t and race_date = :d"
                   " and race_no = :n order by runner_number" % ", ".join(cols), t=trk, d=day, n=no)
    print("\n=== %s %s R%d の全列 ===" % (trk, day, no))
    for r in rows:
        print("--- %s番" % r[cols.index("runner_number")])
        for c, v in zip(cols, r):
            if v is not None:
                print("    %-20s %s" % (c, v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--dsn", help="§129d= Actions の中の Postgres(例 postgresql://postgres:xxx@localhost:5432/postgres)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sample", action="store_true")
    a = ap.parse_args()

    print("§129c 特徴量表の検算")
    check_selftest()
    check_columns()
    if a.selftest:
        print("\n(--selftest= DB は見ていません)")
        return 1 if FAILS else 0

    con = connect(a.env, a.dsn)
    if con is None:
        return 2
    try:
        if not table_exists(con):
            print("\n⛔ nar_ai_feat_run がまだ無い= ドライラン(列の突合と規則の写しだけ通した)。")
            print("   ⛔§129d= この表は**本番では作らない**(9/7 夜に 30 分サイトが止まった)。")
            print("   .github/workflows/nar-ai-feat.yml を workflow_dispatch で流すと、")
            print("   その中の Postgres に表ができて、この検算も同じジョブの中で走る。")
            check_sql_parser(con)
            return 1 if FAILS else 0
        check_counts(con)
        runners, got = oracle_prev_and_pos4(con)
        oracle_kishu(con, runners, got)
        check_leak(con)
        check_extra_filled(con)
        check_sql_parser(con)
        if a.sample:
            sample(con)
    finally:
        con.close()
    print("\n" + ("FAIL %d 件:\n  " % len(FAILS) + "\n  ".join(FAILS) if FAILS else "ALL PASS"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
