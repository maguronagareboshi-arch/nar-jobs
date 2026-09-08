# -*- coding: utf-8 -*-
"""統合ビューア cloud: PC に依存しない当日更新(GitHub Actions の定期実行から呼ぶ)。

公式ZIP(keiba.go.jp DataDownload)をメモリ上で正規化し、nar-official(Supabase)へ直接 upsert する。
ローカル保存はしない(PC 側の pipeline/nar_refresh.py と同じ判定・同じ投入関数を使うので結果は同じ)。
  python cloud/refresh.py --mode daily     # 今日の日次ZIP(当日の出馬表+確定済みの結果・払戻)。20分おき想定
  python cloud/refresh.py --mode monthly   # 当月(+月初3日は前月)の月次ZIP(先の日程の出馬表+過去日の確定結果)。1日1回
  python cloud/refresh.py --mode both
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(GitHub Secrets)。ローカル試験は --env pipeline/.env.nar
終了コード: 0 成功(開催なしで投入なしも 0) / 1 投入失敗 / 2 取得失敗(次回の実行に任せる)
"""
import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "pipeline"))
from nar_official_csv import digest_bytes, download_archive, download_url, normalize_archive  # noqa: E402
from load_nar_official import build_dedup, load_env, summarize, upsert_all  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))


def log(msg):
    print(f"[{dt.datetime.now(JST):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def fetch_doc(scope, **kw):
    url = download_url("race", scope=scope, **kw)
    observed = dt.datetime.now(dt.timezone.utc).isoformat()
    payload, final_url = download_archive(url)
    doc = normalize_archive(payload, kind="race", scope=scope, source_url=final_url, observed_at=observed)
    return doc, digest_bytes(payload)[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "monthly", "both"], default="daily")
    ap.add_argument("--env", help="ローカル試験用 .env(既定は環境変数)")
    ap.add_argument("--dry-run", action="store_true", help="取得・集計だけして投入しない")
    ap.add_argument("--months", help="遡り: '2026-06,2026-07' のように月次 ZIP だけを取り直す(daily は付けない・2026-09-04 減量記号の修理で新設)")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    url = os.environ.get("SUPABASE_URL", "").rstrip("/"); key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 1

    today = dt.datetime.now(JST).date()
    # monthly は当日の途中結果を含まない(出馬表だけ)。monthly 単独で走らせると DB にある当日の結果を
    # 出馬表だけの行で戻してしまうので、monthly のときも必ず daily を一緒に取り、観測順+「結果ありを
    # 結果なしで上書きしない」判定(build_dedup)を当日分に効かせる。
    targets = [("daily", {"race_date": today.isoformat()})]
    if args.months:
        targets = [("monthly", {"year": int(m[:4]), "month": int(m[5:7])}) for m in args.months.split(",") if m.strip()]
    elif args.mode in ("monthly", "both"):
        targets.append(("monthly", {"year": today.year, "month": today.month}))
        if today.day <= 3:                                   # 月初は前月の確定分も拾う
            prev = today.replace(day=1) - dt.timedelta(days=1)
            targets.append(("monthly", {"year": prev.year, "month": prev.month}))
        if today.day >= 25:                                  # 月末は翌月の出馬表も試す(公式が無ければ静かに諦める)
            nxt = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            targets.append(("monthly-next", {"year": nxt.year, "month": nxt.month}))

    docs = []; failed = 0
    for scope, kw in targets:
        optional = scope == "monthly-next"
        scope = "monthly" if optional else scope
        try:
            doc, h = fetch_doc(scope, **kw)
        except ValueError as e:                              # ZIP でない応答(開催なしの日 or エラーページ)
            if scope == "daily":
                log(f"daily {kw['race_date']}: 公式が ZIP を返さない({e}) → 開催なしとみなして投入なし"); continue
            if optional:
                log(f"翌月 {kw}: まだ公式に無い({e})"); continue
            failed += 1; log(f"取得失敗 {scope} {kw}: {e}"); continue
        except Exception as e:                               # ネットワーク断など。次回の実行で取り直す
            failed += 1; log(f"取得失敗 {scope} {kw}: {type(e).__name__}: {str(e)[:200]}"); continue
        races = doc.get("races") or []
        dates = sorted({r.get("race_date") for r in races if r.get("race_date")})
        if scope == "daily" and today.isoformat() not in dates:
            log(f"daily {kw['race_date']}: 当日のレースが無い(中身 {dates[:1]}..{dates[-1:]}) → 投入なし"); continue
        fin = sum(1 for x in (doc.get("horses") or []) if str(x.get("finish") or "").strip())
        log(f"{scope} {kw}: 取得 {h} races={len(races)} 結果あり走={fin} 払戻={len(doc.get('payouts') or [])} "
            f"期間={dates[0] if dates else '-'}..{dates[-1] if dates else '-'}")
        docs.append((doc.get("source_observed_at") or "", f"{scope}:{h}", doc))

    if not docs:
        log("投入なし"); return 2 if failed else 0
    dedup, stats = build_dedup(docs)
    if stats["kept_stale"]:
        log(f"(結果なしの行で上書きしなかった件数: {stats['kept_stale']:,})")
    for line in summarize(dedup, stats).splitlines():
        log(line)
    if args.dry_run:
        log("dry-run: 投入しない"); return 0
    log(f"投入先: {url}")
    rc = upsert_all(url, key, dedup, batch=1000, log=log)
    return 1 if rc else (2 if failed else 0)


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)
