# -*- coding: utf-8 -*-
"""枠連・枠単の払戻の埋め戻し(2026-09-24)。

2022-11〜 の nar_race_payouts に wakuren/wakutan が 1 件も無かった(正規化 normalize_payouts が
payback.csv の枠複・枠単を拾っていなかった)。公式の月次 ZIP を取り直して正規化し、
**DB にある配列へ枠の要素を足すだけ**(既存の要素は消さない・変えない)。
  python cloud/waku_backfill.py --months 2022-11,2022-12            # ドライラン(件数だけ)
  python cloud/waku_backfill.py --months 2023-01,2023-02 --apply    # 書き込み
- 既に wakuren/wakutan が入っている行は触らない(何度流しても同じ)。
- DB に行が無いレースは作らない(数だけ出す)。
- 枠以外の要素が DB と ZIP で食い違う行も数えて出す(書くのは枠の追記だけなので DB 側の値は変わらない)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(GitHub Secrets)。
終了コード: 0 成功 / 1 投入失敗 / 2 取得失敗
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "pipeline"))
from nar_official_csv import download_archive, download_url, normalize_archive  # noqa: E402
from load_nar_official import RUN_TS, UA, build_dedup, upsert  # noqa: E402

WAKU = ("wakuren", "wakutan")
PAGE = 1000
BATCH = 500


def log(msg):
    print(f"[{dt.datetime.now(dt.timezone(dt.timedelta(hours=9))):%H:%M:%S}] {msg}", flush=True)


def month_range(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    start = dt.date(y, m, 1)
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return y, m, start.isoformat(), end.isoformat()


def zip_payouts(y, m):
    """月次 ZIP → {(場, 日, R): [{t,c,y,p}, ...]}(取り込みと同じ正規化・同じ畳み方)"""
    payload, final_url = download_archive(download_url("race", scope="monthly", year=y, month=m))
    doc = normalize_archive(payload, kind="race", scope="monthly", source_url=final_url,
                            observed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    dedup, _ = build_dedup([(doc.get("source_observed_at") or "", "monthly", doc)])
    return {k: r["payouts"] for k, r in dedup["payouts"].items()}


def db_payouts(url, key, start, end):
    """DB の {(場, 日, R): payouts}。⛔offset は一意の並び(主キー)で"""
    out = {}; offset = 0
    while True:
        q = urllib.parse.urlencode([("select", "track,race_date,race_no,payouts"),
                                    ("race_date", f"gte.{start}"), ("race_date", f"lt.{end}"),
                                    ("order", "track.asc,race_date.asc,race_no.asc"),
                                    ("limit", str(PAGE)), ("offset", str(offset))])
        req = urllib.request.Request(f"{url}/rest/v1/nar_race_payouts?{q}",
                                     headers={"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read().decode("utf-8"))
        for row in rows:
            out[(row["track"], row["race_date"], int(row["race_no"]))] = row.get("payouts") or []
        if len(rows) < PAGE:
            return out
        offset += PAGE


def _sig(items):
    return sorted(json.dumps({"t": p.get("t"), "c": str(p.get("c")), "y": p.get("y"), "p": p.get("p")},
                             sort_keys=True) for p in items)


def merge(db_list, zip_list):
    """DB の配列に ZIP の枠の要素を足した配列。足すものが無い/既にあるときは None。"""
    if any(p.get("t") in WAKU for p in db_list):
        return None
    add = [p for p in zip_list if p.get("t") in WAKU]
    if not add:
        return None
    return sorted(list(db_list) + add, key=lambda p: (str(p.get("t")), str(p.get("c"))))


def plan_month(db, zp):
    """(書く行, 数の要約)。書く行は枠を足した行だけ。"""
    rows = []; st = {"db": len(db), "zip": len(zp), "add": 0, "already": 0, "no_db_row": 0, "other_diff": 0,
                     "wakuren": 0, "wakutan": 0}
    for k, zl in zp.items():
        if not any(p.get("t") in WAKU for p in zl):
            continue
        if k not in db:
            st["no_db_row"] += 1; continue
        dl = db[k]
        if _sig([p for p in dl if p.get("t") not in WAKU]) != _sig([p for p in zl if p.get("t") not in WAKU]):
            st["other_diff"] += 1
        new = merge(dl, zl)
        if new is None:
            st["already"] += 1; continue
        for p in new:
            if p.get("t") in WAKU:
                st[p["t"]] += 1
        st["add"] += 1
        rows.append({"track": k[0], "race_date": k[1], "race_no": k[2], "payouts": new, "updated_at": RUN_TS})
    return rows, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", required=True, help="'2022-11,2022-12' のように月をカンマで")
    ap.add_argument("--apply", action="store_true", help="書き込む(既定はドライラン)")
    args = ap.parse_args()
    url = os.environ.get("SUPABASE_URL", "").rstrip("/"); key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 1
    total = {}; failed = 0
    for ym in [m.strip() for m in args.months.split(",") if m.strip()]:
        y, m, start, end = month_range(ym)
        try:
            zp = zip_payouts(y, m)
        except Exception as e:
            failed += 1; log(f"{ym}: 取得失敗 {type(e).__name__}: {str(e)[:200]}"); continue
        rows, st = plan_month(db_payouts(url, key, start, end), zp)
        log(f"{ym}: " + " ".join(f"{k}={v}" for k, v in st.items()))
        for k, v in st.items():
            total[k] = total.get(k, 0) + v
        if not args.apply:
            continue
        for i in range(0, len(rows), BATCH):
            code, err = upsert(url, key, "nar_race_payouts", "track,race_date,race_no", rows[i:i + BATCH])
            if code >= 300 or code == 0:
                log(f"{ym}: 投入失敗 {code} {err}"); return 1
        log(f"{ym}: 書いた {len(rows):,} 行")
    log("合計: " + " ".join(f"{k}={v}" for k, v in total.items()) + ("" if args.apply else "(ドライラン)"))
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
