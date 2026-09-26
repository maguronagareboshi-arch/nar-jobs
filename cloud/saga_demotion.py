# -*- coding: utf-8 -*-
"""§288 佐賀の「降級の目安」(翌1月の減額の見込み)を表 nar_saga_demotion へ書く(便 nar-refresh.yml の朝の class calc の後)。

  式= 令和8年度 番組編成要領 第4-1(3)③(ロ)(ハ)(ニ)= 6歳になった時点で2歳時・7歳で3歳時・8歳で4歳時の収得賞金を全額減額。
      番組賞金と年齢ごとの額は cloud/class_calc.py の saga_state をそのまま呼ぶ(朝の class calc と同じ値・lag も同じ)。
      検証= nar-site/BACKTEST-demotion-saga-20260926.md(2026年1月: 下がった 14 頭を全部当てた・空振り 4)。
  行= 翌1月に減額がある在籍馬の全部(級が下がらない馬も入れる。下がるか= cls_after と cls_now を比べる)。
      6〜8歳に 8月の減額は無い= after は value − cut だけ。転入前(在籍でない)の馬は出さない。
  計算した日(calc_date)ごとに行を残す(過去のレースの画面= レースの日より前の最新の calc_date)。同じ日は上書き。

  python cloud/saga_demotion.py --dry-run [--out x.csv]   # DB を読む→CSV と級ごとの行数だけ(書かない)
  python cloud/saga_demotion.py --apply                   # upsert→heartbeat 'saga_demotion'
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(ドライランは読める鍵なら何でもよい)。終了コード: 0 正常 / 1 投入失敗 / 2 読み・計算の失敗
"""
import argparse
import collections
import csv
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import class_calc as cc  # noqa: E402

TABLE = "nar_saga_demotion"
BEAT_JOB = "saga_demotion"
ORDER = ["Ａ１", "Ａ２", "Ｂ", "Ｃ１", "Ｃ２"]
COLS = ["code", "horse_name", "calc_date", "cls_now", "cls_calc", "value", "cut", "after", "cls_after", "need",
        "cut_age", "age_next", "target"]


def log(*a):
    print(*a, flush=True)


def lows(lines):
    """級 → 下限(円・以上)。Ｃ２ は 0。"""
    out = {}
    for cls, lo_excl, _hi in lines:
        out[cls] = lo_excl + 1000 if lo_excl else 0
    return out


def forecast(lines, rows, births, entered, races, today, lag):
    lo = lows(lines)
    target = dt.date(today.year + 1, 1, 1)
    out, why = [], collections.Counter()
    for r in rows:
        runs = r.get("runs") or []
        local = [x for x in runs if not x.get("jra") and x.get("fin") is not None]
        last_tr = local[0].get("tr") if local else None
        if last_tr != "佐賀" and r.get("horse_name") not in entered:      # class_calc main_saga --apply と同じ馬
            why["最後が佐賀でない"] += 1
            continue
        b = cc._date(births.get(r["code"]))
        if not b:
            why["生年なし"] += 1
            continue
        age_next = target.year - b.year
        if age_next not in (6, 7, 8):
            why["翌1月に6〜8歳でない"] += 1
            continue
        value, by_age, resident, _lab = cc.saga_state(runs, b, today, lag, races)
        if not resident:
            why["在籍でない(転入前・転出中)"] += 1
            continue
        cut_age = age_next - 4
        cut = cc._thou(by_age.get(cut_age, 0))
        if cut <= 0:
            why["減額 0"] += 1
            continue
        after = max(0, value - cut)
        cls_calc = cc.classify(lines, value)
        saga = [x for x in runs if x.get("tr") == "佐賀"]
        off = cc.norm_cls(saga[0].get("cls")) if saga else ""
        cls_now = off if off in ORDER else cls_calc
        cls_after = cc.classify(lines, after)
        need = None if cls_now == "Ｃ２" else lo[cls_now] - after
        out.append(dict(code=str(r["code"]), horse_name=r.get("horse_name") or "", calc_date=today.isoformat(),
                        cls_now=cls_now, cls_calc=cls_calc, value=int(value), cut=int(cut), after=int(after),
                        cls_after=cls_after, need=need, cut_age=cut_age, age_next=age_next, target=target.isoformat()))
    return out, why


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in COLS})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", help="CSV の出力先")
    ap.add_argument("--today", help="計算する日(試し用 YYYY-MM-DD)")
    ap.add_argument("--node", help="node の場所(線の表 class.js を読む)")
    a = ap.parse_args()
    apply_ = a.apply and not a.dry_run
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(cc.JST).date()

    def say(ok, note):
        if apply_:
            import beat as B
            B.beat(BEAT_JOB, ok, note)
        log(f"heartbeat {BEAT_JOB} {'ok' if ok else 'fail'} {note}" + ("" if apply_ else "(ドライラン= 書かない)"))

    try:
        if not (url and key):
            raise ValueError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        consts = cc.load_consts(a.node)
        lines = cc.saga_lines(next(s for s in consts["SYSTEMS"] if s["id"] == "saga"))
        rows, births, entered, races = cc.fetch_saga(url, key, today - dt.timedelta(days=365))
        if not rows:
            raise ValueError("佐賀の台帳が 0 頭")
        out, why = forecast(lines, rows, births, entered, races, today, cc.SAGA_LAG)
    except Exception as e:
        log(f"::error::読み・計算に失敗: {type(e).__name__}: {e}")
        say(False, f"計算失敗 {str(e)[:80]}")
        return 2
    down = [r for r in out if ORDER.index(r["cls_after"]) > ORDER.index(r["cls_now"])]
    log(f"読んだ馬 {len(rows)}・計算した日 {today}・翌1月に減額がある馬 {len(out)}・うち級が下がる見込み {len(down)}")
    log("除いた数: " + " ".join(f"{k}={v}" for k, v in why.most_common()))
    for c in ORDER:
        n = sum(1 for r in out if r["cls_now"] == c)
        d = sum(1 for r in down if r["cls_now"] == c)
        log(f"  {c}: 減額あり {n}・下がる見込み {d}")
    path = a.out or f"saga_demotion_{today.isoformat()}.csv"
    write_csv(path, out)
    log(f"CSV= {path}")

    def store_race(write):
        # §294 出走表がある今日以降のレースの馬ごとに残す(表 nar_demotion_race)。⛔落ちても便は止めない
        import demotion_race as DR
        by = {r["horse_name"]: r for r in out}
        mt = DR.saga_meta(today)
        DR.store_live(url, key, "saga", lambda trk, n: by.get(n), lambda trk: mt, write=write)

    if not apply_:
        store_race(False)
        return 0
    if not out:
        log("::error::減額がある馬が 0= 書かずに止める")
        say(False, "見込み 0 行")
        return 2
    try:
        for i in range(0, len(out), 500):
            st, msg = cc.upsert(url, key, TABLE, "code,calc_date", out[i:i + 500])
            if st >= 300:
                raise RuntimeError(f"upsert {st} {msg}")
    except Exception as e:
        log(f"::error::投入失敗: {e}")
        say(False, "投入失敗")
        return 1
    store_race(True)
    say(True, f"減額あり {len(out)}・下がる見込み {len(down)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
