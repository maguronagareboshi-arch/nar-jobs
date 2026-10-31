#!/usr/bin/env python3
"""騎手の話は当たっているか — 集計 B(検算用の別実装)。

仕様: research/kc-talk-check-20261101/SPEC.md
作り方: sqlite3 のメモリ DB に runs.csv・talks.csv を入れ、計算はすべて SQL。
Python は読み込みと CSV 出力だけ。

使い方:
  python research_kc_talk_b.py            # KC_TALK_DATA(既定 /tmp/kc_talk)→ docs/research-kc-talk/result_b.csv
  python research_kc_talk_b.py --selftest # 小さい試験データで手計算と照合
"""
import csv
import os
import sqlite3
import sys
import tempfile

KEYS = [
    # kind, 予想の向き(worse=悪くなる / better=良くなる)
    ("kyori_long", "worse"),
    ("kyori_short", "worse"),
    ("pref_long", "better"),
    ("pref_short", "better"),
    ("baba_wet", "better"),
    ("baba_dry", "better"),
    ("natsu", "worse"),
    ("kankaku", "worse"),
    ("waku_out", "better"),
    ("waku_in", "better"),
]

COLS = ["key", "units", "horses", "hit_runs", "miss_runs",
        "d_finish", "d_top3", "d_pop", "b_finish", "b_top3", "b_pop",
        "dd_finish", "dd_top3", "dd_pop", "agree", "disagree"]

RUN_INT = {"race_no", "umaban", "waku", "distance_m", "finish", "popularity", "field_size"}
RUN_COLS = ["horse_key", "track", "race_date", "race_no", "umaban", "waku", "distance_m",
            "going", "finish", "popularity", "field_size", "status"]
TALK_COLS = ["horse_key", "race_date", "race_no", "distance_m", "labels"]
TALK_INT = {"race_no", "distance_m"}

SQL = r"""
-- 1. 話の鍵(1 コメント 1 鍵 1 回)
CREATE TABLE tk_raw AS
SELECT t.horse_key, t.race_date, t.race_no, t.distance_m AS d,
       json_extract(j.value, '$.k') AS k,
       CAST(json_extract(j.value, '$.s') AS TEXT) AS s,
       json_extract(j.value, '$.v') AS v
FROM talks t,
     json_each(CASE WHEN t.labels IS NOT NULL AND json_valid(t.labels)
                    AND json_type(t.labels) = 'array' THEN t.labels ELSE '[]' END) j
WHERE json_type(j.value) = 'object';

CREATE TABLE tk_kind AS
SELECT horse_key, race_date, race_no, d,
  CASE
    WHEN k='kyori' AND s='-' AND v='long'  AND d IS NOT NULL THEN 'kyori_long'
    WHEN k='kyori' AND s='-' AND v='short' AND d IS NOT NULL THEN 'kyori_short'
    WHEN k='kyori_pref' AND s='0' AND v='long'  THEN 'pref_long'
    WHEN k='kyori_pref' AND s='0' AND v='short' THEN 'pref_short'
    WHEN k='baba' AND s='0' AND v='wet' THEN 'baba_wet'
    WHEN k='baba' AND s='0' AND v='dry' THEN 'baba_dry'
    WHEN k='natsu' AND s='-' THEN 'natsu'
    WHEN k='kankaku' AND s='-' THEN 'kankaku'
    WHEN k='waku' AND s='0' AND v='out' THEN 'waku_out'
    WHEN k='waku' AND s='0' AND v='in'  THEN 'waku_in'
  END AS kind
FROM tk_raw;

CREATE TABLE tk AS
SELECT DISTINCT horse_key, race_date, race_no, kind,
       CASE WHEN kind IN ('kyori_long','kyori_short') THEN d END AS x,
       CASE WHEN kind IN ('kyori_long','kyori_short') THEN kind || ':' || d ELSE kind END AS key
FROM tk_kind WHERE kind IS NOT NULL;
CREATE INDEX tk_i ON tk(horse_key, key, race_date);

CREATE TABLE keyset AS SELECT DISTINCT key, kind, x FROM tk;

-- 2. 対象の走 R と前走
CREATE TABLE r0 AS
SELECT rowid AS rid, horse_key, race_date, race_no, waku, distance_m AS dist, going, finish, popularity,
  (SELECT p.rowid FROM runs p
    WHERE p.horse_key = x.horse_key AND p.race_date < x.race_date
      AND p.status IN ('ok','chushi')
    ORDER BY p.race_date DESC, p.race_no DESC LIMIT 1) AS prev_rid
FROM runs x
WHERE x.track = '高知' AND x.status = 'ok' AND x.finish IS NOT NULL
  AND x.race_date BETWEEN '2024-03-01' AND '2026-10-30';

CREATE TABLE r AS
SELECT r0.*, p.race_date AS prev_date, p.distance_m AS prev_dist,
  CASE WHEN p.race_date IS NULL THEN NULL
       ELSE MAX(CAST((julianday(r0.race_date) - julianday(p.race_date)) AS INTEGER) / 7 - 1, 0) END AS weeks,
  CAST(substr(r0.race_date, 6, 2) AS INTEGER) AS mon,
  CASE WHEN r0.finish <= 3 THEN 1 ELSE 0 END AS top3,
  CASE WHEN r0.popularity IS NULL THEN NULL ELSE r0.finish - r0.popularity END AS pdiff
FROM r0 LEFT JOIN runs p ON p.rowid = r0.prev_rid;

-- 3. 走×鍵: 当たる(1)/当たらない(0)/数えない(NULL)・立っているか
CREATE TABLE rk0 AS
SELECT r.rid, r.horse_key, r.race_date, k.key, k.kind, k.x, r.finish, r.top3, r.pdiff,
  CASE k.kind
    WHEN 'kyori_long'  THEN CASE WHEN r.dist IS NULL THEN NULL WHEN r.dist >= k.x THEN 1 ELSE 0 END
    WHEN 'kyori_short' THEN CASE WHEN r.dist IS NULL THEN NULL WHEN r.dist <= k.x THEN 1 ELSE 0 END
    WHEN 'pref_long'   THEN CASE WHEN r.dist IS NULL OR r.prev_dist IS NULL THEN NULL
                                 WHEN r.dist > r.prev_dist THEN 1 ELSE 0 END
    WHEN 'pref_short'  THEN CASE WHEN r.dist IS NULL OR r.prev_dist IS NULL THEN NULL
                                 WHEN r.dist < r.prev_dist THEN 1 ELSE 0 END
    WHEN 'baba_wet'    THEN CASE WHEN r.going IN ('重','不') THEN 1 WHEN r.going = '良' THEN 0 END
    WHEN 'baba_dry'    THEN CASE WHEN r.going = '良' THEN 1 WHEN r.going IN ('重','不') THEN 0 END
    WHEN 'natsu'       THEN CASE WHEN r.mon BETWEEN 6 AND 9 THEN 1 WHEN r.mon IS NOT NULL THEN 0 END
    WHEN 'kankaku'     THEN CASE WHEN r.weeks IS NULL THEN NULL WHEN r.weeks >= 8 THEN 1 ELSE 0 END
    WHEN 'waku_out'    THEN CASE WHEN r.waku BETWEEN 7 AND 8 THEN 1 WHEN r.waku BETWEEN 1 AND 6 THEN 0 END
    WHEN 'waku_in'     THEN CASE WHEN r.waku BETWEEN 1 AND 2 THEN 1 WHEN r.waku BETWEEN 3 AND 8 THEN 0 END
  END AS hit
FROM r CROSS JOIN keyset k;

CREATE TABLE rk AS
SELECT rk0.*,
  CASE WHEN (SELECT COUNT(*) FROM (SELECT DISTINCT t.race_date, t.race_no FROM tk t
              WHERE t.horse_key = rk0.horse_key AND t.key = rk0.key
                AND t.race_date < rk0.race_date)) >= 2 THEN 1 ELSE 0 END AS standing
FROM rk0 WHERE hit IS NOT NULL;

-- 4. 単位の差(馬×鍵×立っているか)
CREATE TABLE units AS
SELECT horse_key, key, kind, x, standing,
  SUM(hit) AS nh, SUM(1 - hit) AS nm,
  AVG(CASE WHEN hit=1 THEN finish END) - AVG(CASE WHEN hit=0 THEN finish END) AS df,
  AVG(CASE WHEN hit=1 THEN top3 END)   - AVG(CASE WHEN hit=0 THEN top3 END)   AS dt,
  AVG(CASE WHEN hit=1 THEN pdiff END)  - AVG(CASE WHEN hit=0 THEN pdiff END)  AS dp
FROM rk
GROUP BY horse_key, key, kind, x, standing
HAVING SUM(hit) >= 1 AND SUM(1 - hit) >= 1;

-- 5. 土台(鍵ごと・kyori は X ごと)
CREATE TABLE base AS
SELECT key, AVG(df) AS bf, AVG(dt) AS bt, AVG(dp) AS bp
FROM units WHERE standing = 0 GROUP BY key;

-- 6. 話ありの単位に土台を付ける
CREATE TABLE tu AS
SELECT u.*, b.bf, b.bt, b.bp
FROM units u LEFT JOIN base b ON b.key = u.key
WHERE u.standing = 1;

-- 7. 鍵の種類ごとの表
CREATE TABLE result AS
SELECT kk.kind AS key, kk.ord,
  COUNT(tu.key) AS units,
  COUNT(DISTINCT tu.horse_key) AS horses,
  COALESCE(SUM(tu.nh), 0) AS hit_runs,
  COALESCE(SUM(tu.nm), 0) AS miss_runs,
  AVG(tu.df) AS d_finish, AVG(tu.dt) AS d_top3, AVG(tu.dp) AS d_pop,
  AVG(tu.bf) AS b_finish, AVG(tu.bt) AS b_top3,
  AVG(CASE WHEN tu.dp IS NOT NULL THEN tu.bp END) AS b_pop,
  AVG(tu.df - tu.bf) AS dd_finish, AVG(tu.dt - tu.bt) AS dd_top3, AVG(tu.dp - tu.bp) AS dd_pop,
  COALESCE(SUM(CASE WHEN (kk.dir='worse' AND tu.df > 0) OR (kk.dir='better' AND tu.df < 0) THEN 1 ELSE 0 END), 0) AS agree,
  COALESCE(SUM(CASE WHEN (kk.dir='worse' AND tu.df < 0) OR (kk.dir='better' AND tu.df > 0) THEN 1 ELSE 0 END), 0) AS disagree
FROM kinds kk LEFT JOIN tu ON tu.kind = kk.kind
GROUP BY kk.kind, kk.ord;
"""


def _load(con, table, path, cols, int_cols):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = []
        for row in csv.DictReader(f):
            vals = []
            for c in cols:
                v = (row.get(c) or "").strip()
                if v == "":
                    vals.append(None)
                elif c in int_cols:
                    vals.append(int(float(v)))
                else:
                    vals.append(v)
            rows.append(vals)
    con.execute(f"CREATE TABLE {table} ({', '.join(cols)})")
    con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})", rows)


def run(data_dir, out_path):
    con = sqlite3.connect(":memory:")
    _load(con, "runs", os.path.join(data_dir, "runs.csv"), RUN_COLS, RUN_INT)
    _load(con, "talks", os.path.join(data_dir, "talks.csv"), TALK_COLS, TALK_INT)
    con.execute("CREATE INDEX runs_i ON runs(horse_key, race_date)")
    con.execute("CREATE TABLE kinds (kind TEXT, dir TEXT, ord INTEGER)")
    con.executemany("INSERT INTO kinds VALUES (?,?,?)", [(k, d, i) for i, (k, d) in enumerate(KEYS)])
    con.executescript(SQL)
    cur = con.execute(f"SELECT {', '.join(COLS)} FROM result ORDER BY ord")
    out = []
    for row in cur.fetchall():
        rec = {}
        for c, v in zip(COLS, row):
            if v is None:
                rec[c] = ""
            elif isinstance(v, float):
                rec[c] = f"{v:.3f}"
            else:
                rec[c] = str(v)
        out.append(rec)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    return out


# ---------------- selftest ----------------
def _selftest():
    K = "高知"
    runs = [
        # horse, track, date, no, umaban, waku, dist, going, finish, pop, field, status
        ("A|2020-01-01", K, "2024-02-01", 1, 1, 1, 1200, "良", 10, 9, 10, "ok"),   # 期間外(R にしない)
        ("A|2020-01-01", K, "2024-03-05", 1, 1, 1, 1300, "良", 5, 3, 10, "ok"),
        ("A|2020-01-01", K, "2024-04-01", 1, 2, 2, 1300, "重", 2, 4, 10, "ok"),
        ("A|2020-01-01", K, "2024-05-01", 1, 3, 3, 1400, "良", 4, 2, 10, "ok"),   # 2 回目の話と同じ日
        ("A|2020-01-01", K, "2024-06-01", 1, 9, 7, 1400, "重", 1, 1, 10, "ok"),
        ("A|2020-01-01", K, "2024-07-01", 1, 10, 8, 1300, "稍", 3, 2, 10, "ok"),  # 稍= 数えない
        ("A|2020-01-01", K, "2024-08-01", 1, 4, 4, 1200, "良", 6, None, 10, "ok"),  # 人気空
        ("A|2020-01-01", K, "2024-08-15", 2, 4, 4, 1200, "良", None, None, 10, "torikeshi"),
        ("A|2020-01-01", K, "2024-09-01", 1, 5, 5, 1300, "不", 2, 5, 10, "ok"),
        ("B|", K, "2024-03-10", 2, 1, 1, 1300, "重", 1, 1, 10, "ok"),               # 前走なし
        ("B|", K, "2024-04-10", 2, 10, 8, 1400, "良", 3, 2, 10, "ok"),
        ("B|", "佐賀", "2024-05-10", 2, 3, 3, 1800, "良", 4, 4, 10, "ok"),           # 他場(R にしない)
        ("B|", K, "2024-07-10", 2, 3, 3, 1300, "不", 2, 6, 10, "ok"),
        ("B|", K, "2024-08-10", 3, 2, 2, 1200, "良", 8, 7, 10, "ok"),
        ("C|2019-05-05", K, "2024-03-20", 1, 8, 6, 1400, "良", 7, 6, 10, "ok"),     # R 当日のコメント
        ("C|2019-05-05", K, "2024-04-20", 1, 8, 6, 1400, "良", 5, 5, 10, "ok"),
        ("C|2019-05-05", K, "2024-05-20", 1, 1, 1, 1500, "良", 9, 8, 10, "ok"),
        ("C|2019-05-05", K, "2024-06-20", 1, 2, 2, 1300, "良", 2, 3, 10, "ok"),
    ]
    WET = '{"k":"baba","s":"0","v":"wet","e":""}'
    KL = '{"k":"kyori","s":"-","v":"long","e":""}'
    JUNK = '{"k":"kyori","s":"+","v":"long","e":""}'
    talks = [
        ("A|2020-01-01", "2024-04-01", 1, 1300, f"[{WET},{KL},{WET},{JUNK}]"),
        ("A|2020-01-01", "2024-05-01", 1, 1400, f"[{WET},{KL}]"),
        ("A|2020-01-01", "2024-06-01", 1, 1300, f"[{KL}]"),
        ("B|", "2024-07-10", 2, 1300, "[]"),
        ("C|2019-05-05", "2024-03-20", 1, 1400, f"[{KL}]"),
        ("C|2019-05-05", "2024-04-20", 1, 1400, f"[{KL}]"),
    ]
    # 手計算(SPEC どおり)
    expect = {
        "baba_wet": dict(units="1", horses="1", hit_runs="2", miss_runs="1",
                         d_finish="-4.500", d_top3="1.000", d_pop="",
                         b_finish="-3.250", b_top3="0.750", b_pop="",
                         dd_finish="-1.250", dd_top3="0.250", dd_pop="",
                         agree="1", disagree="0"),
        "kyori_long": dict(units="2", horses="2", hit_runs="3", miss_runs="2",
                           d_finish="1.750", d_top3="0.000", d_pop="2.000",
                           b_finish="-3.442", b_top3="0.558", b_pop="1.750",
                           dd_finish="5.192", dd_top3="-0.558", dd_pop="0.250",
                           agree="1", disagree="1"),
    }
    empty = dict(units="0", horses="0", hit_runs="0", miss_runs="0",
                 d_finish="", d_top3="", d_pop="", b_finish="", b_top3="", b_pop="",
                 dd_finish="", dd_top3="", dd_pop="", agree="0", disagree="0")
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "runs.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(RUN_COLS)
            for r in runs:
                w.writerow(["" if v is None else v for v in r])
        with open(os.path.join(td, "talks.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(TALK_COLS)
            for t in talks:
                w.writerow(t)
        out = run(td, os.path.join(td, "out", "result_b.csv"))
    got = {r["key"]: r for r in out}
    bad = []
    if [r["key"] for r in out] != [k for k, _ in KEYS]:
        bad.append(("rows", [r["key"] for r in out]))
    for k, _ in KEYS:
        exp = expect.get(k, empty)
        for c, v in exp.items():
            g = got.get(k, {}).get(c)
            if g != v:
                bad.append((k, c, v, g))
    if bad:
        print("SELFTEST NG")
        for b in bad:
            print(" ", b)
        sys.exit(1)
    print("SELFTEST OK (10 行・照合 %d 値)" % (len(KEYS) * 15))


def main():
    if "--selftest" in sys.argv[1:]:
        _selftest()
        return
    data_dir = os.environ.get("KC_TALK_DATA", "/tmp/kc_talk")
    out_path = os.path.join(os.getcwd(), "docs", "research-kc-talk", "result_b.csv")
    out = run(data_dir, out_path)
    print(f"wrote {out_path} ({len(out)} rows)")


if __name__ == "__main__":
    main()
