# -*- coding: utf-8 -*-
"""10/2 兵庫(園田 37・西脇 45)の能検の過去分を競馬ブックの能検ページから取り直し、nar_meta 'hyogo_noken' へ足す。

- 公式(sonoda-himeji.jp)は 2026-03-06 からしか無い。ここで足すのはそれより前(既定 2018-01-01〜2026-03-05)。
- 同じ日・同じ場が既にあれば**公式を残す**(叩かない・上書きしない)。
- 器の形は今の hyogo_noken と同じ= {date, venue, races[{no, rows[], dist}], src_id, weather?, going?}。
  行の鍵は**今の hyogo_noken の行にある鍵だけ**(無い鍵は落としてログに数を出す)。値は公式と同じ整え方(noken_public.cell/fix_time)。
  src_id は日の鍵(BY_SRC)なので一意が要る= 競馬ブックの id の**負の整数**(公式の detail id は正の整数= 重ならない)。
  ⛔これらの日は既に本当のレース単位なので、毎日の便の hyogo_split(レース割り)は触らない(noken_public.is_kb_day)。
- ⛔寸評(他社の評)は取らない。⛔頁の HTML をログ・成果物に出さない(public repo)。
- 間隔は FETCH_WAIT_SECONDS(既定 2.5 秒)。30 日ぶんごとに、その時点の本番の値を読み直して足して書く(毎日の便と重ならないように)。

  python cloud/kb/backfill_kb_noken_hyogo.py --from 2018-01-01 --to 2026-03-05 [--dry-run] [--dates 20210607,20250602]
"""
import argparse
import copy
import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from fetch import make_client                                        # noqa: E402
from fetch_kb_noken_hyogo import TRACKS, collect_day, month_days     # noqa: E402
import noken_public as NP                                            # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

META_KEY = "hyogo_noken"
CHUNK = 30
# 競馬ブックの行の鍵(ROW_KEYS)→ 足す順。⛔寸評は元から取っていない
KB_ROW_ORDER = ("name", "sexage", "time", "weight", "trainer", "ok", "kind", "fin", "umaban", "pass_order",
                "last3f", "jockey")


def log(m):
    print(m, flush=True)


def kb_src_id(kb_id):
    return -int(kb_id)


def to_day(kb_day, allowed):
    """collect_day の日 → hyogo_noken の 1 日。allowed= 今の hyogo_noken の行にある鍵。返り値= (日, 落とした鍵 Counter)"""
    dropped = Counter()
    races = []
    for r in kb_day["races"]:
        rows = []
        for x in r["rows"]:
            row = {}
            for k in KB_ROW_ORDER:
                v = NP.cell(str(x.get(k) or ""))
                if not v:
                    continue
                if k not in allowed:
                    dropped[k] += 1
                    continue
                row[k] = NP.fix_time(v) if k == "time" else v
            if row.get("name"):
                rows.append(row)
        if not rows:
            continue
        race = {"no": r["no"], "rows": rows}
        if r.get("dist"):
            race["dist"] = r["dist"]
        races.append(race)
    day = {"date": kb_day["date"], "venue": kb_day["venue"], "races": races,
           "src_id": kb_src_id(kb_day["kb_id"])}
    wx = {(r.get("weather"), r.get("going")) for r in kb_day["races"]}
    if len(wx) == 1:
        w, g = next(iter(wx))
        if w and g:
            day["weather"], day["going"] = w, g
    return day, dropped


def counts(days):
    return len(days), sum(len(r.get("rows") or []) for d in days for r in (d.get("races") or []))


def shape(days, title):
    dk, rk, wk, ty = Counter(), Counter(), Counter(), Counter()
    ex = defaultdict(list)
    for d in days:
        dk.update(d.keys())
        ty[type(d.get("src_id")).__name__] += 1
        for r in d.get("races") or []:
            rk.update(r.keys())
            for w in r.get("rows") or []:
                wk.update(w.keys())
                for k, v in w.items():
                    if k != "name" and v not in ex[k] and len(ex[k]) < 8:
                        ex[k].append(v)
    log(f"== 形 {title}: 日 {len(days)} / 日の鍵 {dict(dk)} / src_id の型 {dict(ty)}")
    log(f"   レースの鍵 {dict(rk)}")
    log(f"   行の鍵 {dict(wk)}")
    for k in sorted(ex):
        log(f"   値の例 {k}: {ex[k]}")
    vs = Counter(d.get("venue") for d in days)
    log(f"   場 {dict(vs)} / 日付 {min((d['date'] for d in days), default='-')}〜{max((d['date'] for d in days), default='-')}")


def read_stored(base, key):
    return NP.sb_get_meta(base, key, META_KEY) or {"days": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d_from", default="2018-01-01")
    ap.add_argument("--to", dest="d_to", default="2026-03-05")
    ap.add_argument("--dates", default="", help="「,」区切りの YYYYMMDD(試し= この日だけ・月の一覧は見ない)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-login", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    start, end = dt.date.fromisoformat(a.d_from), dt.date.fromisoformat(a.d_to)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2

    stored = read_stored(base, key)
    n0d, n0r = counts(stored["days"])
    log(f"書き込み前 {META_KEY}: {n0d} 日 / {n0r} 頭")
    allowed = {k for d in stored["days"] for r in (d.get("races") or []) for w in (r.get("rows") or []) for k in w}
    log(f"今の行の鍵(これだけ足す) {sorted(allowed)}")
    if "name" not in allowed:
        log("今の hyogo_noken に行が無い= 鍵が決められないので止める")
        return 2

    client, _ = make_client(a)
    targets = []
    if a.dates:
        for s in a.dates.split(","):
            s = s.strip()
            if s:
                targets += [(s, c) for c in TRACKS]
    else:
        d = start.replace(day=1)
        while d <= end:
            targets += month_days(client, d.strftime("%Y%m"), refresh=a.refresh)
            d = (d.replace(day=28) + dt.timedelta(days=7)).replace(day=1)
    targets = sorted({t for t in targets
                      if a.d_from <= "%s-%s-%s" % (t[0][:4], t[0][4:6], t[0][6:8]) <= a.d_to})
    have = {(d.get("date"), d.get("venue")) for d in stored["days"]}
    todo = [t for t in targets if ("%s-%s-%s" % (t[0][:4], t[0][4:6], t[0][6:8]), TRACKS[t[1]]) not in have]
    log(f"対象 {len(targets)} 日(園田・西脇)/ 既にある日(公式を残す){len(targets) - len(todo)} / 叩く日 {len(todo)}")

    new_all, pending, failed, empty = [], [], [], []
    dropped = Counter()
    by_year = defaultdict(lambda: [0, 0])
    rc = 0

    def flush():
        nonlocal pending, rc
        if not pending:
            return
        cur = read_stored(base, key)                 # 毎日の便が書いた分を落とさないように読み直す
        cur_have = {(d.get("date"), d.get("venue")) for d in cur["days"]}
        add = [d for d in pending if (d["date"], d["venue"]) not in cur_have]
        days = NP.merge_days(cur["days"], add, lambda d: d.get("src_id"))   # 既存を先= 同じ鍵は既存を残す
        if a.dry_run:
            log(f"(dry-run) 書くなら 新規 {len(add)} 日 / 合計 {len(days)} 日")
        else:
            status, msg = NP.upsert(base, key, "nar_meta", "key",
                                    [{"key": META_KEY, "value": {"days": days},
                                      "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}])
            if status not in (200, 201):
                log(f"投入失敗 {status} {msg}")
                rc = 1
                return
            log(f"nar_meta/{META_KEY} 更新 新規 {len(add)} 日 / 合計 {len(days)} 日")
        pending = []

    for i, (date, code) in enumerate(todo, 1):
        day = None
        for n in range(3):
            try:
                day, why = collect_day(client, date, code, refresh=a.refresh)
                break
            except Exception as e:                   # noqa: BLE001
                why = f"{type(e).__name__}"
        if day is None:
            (empty if why == "レースの表が無い" else failed).append(f"{date}{code}")
            log(f"  {date} {TRACKS[code]}: {why}")
        else:
            out, dr = to_day(day, allowed)
            dropped.update(dr)
            nd, nr = counts([out])
            if nr:
                new_all.append(out)
                pending.append(out)
                by_year[out["date"][:4]][0] += 1
                by_year[out["date"][:4]][1] += nr
                log(f"  {out['date']} {out['venue']}: {len(out['races'])}R {nr}頭")
        if i % CHUNK == 0:
            flush()
    flush()

    if new_all:
        shape(stored["days"], "今の hyogo_noken")
        shape(new_all, "足す日")
    if dropped:
        log(f"今の行に無い鍵なので落とした {dict(dropped)}")

    # 読み手の確かめ= ①毎日の便の hyogo_split(レース割り)②能検の索引の build に通す(書き込みなし)
    merged = NP.merge_days(copy.deepcopy(stored["days"]), copy.deepcopy(new_all), lambda d: d.get("src_id"))
    sim = copy.deepcopy(merged)
    n_done, _warn = NP.hyogo_split(sim, NP.load_hyogo_split(None, base, key))
    kb_ids = {d["src_id"] for d in new_all}
    touched = sum(1 for x, y in zip(merged, sim) if x.get("src_id") in kb_ids and x != y)
    log(f"読み手① hyogo_split: レース割り {n_done} 日 / 足した日で中身が変わった日 {touched}(0 のはず)")
    import noken_index as NI
    today = dt.datetime.now(NI.JST).date()
    for yrs in (3, 5):
        st = {}
        horses = NI.build({"hyogo": {"days": merged}}, {}, NI.cutoff_date(today, yrs).isoformat(), st)
        recs = [r for v in horses.values() for r in v if r["d"] == "hyogo"]
        old = sum(1 for r in recs if r["date"] < "2026-03-06")
        s = st.get("hyogo", {})
        log(f"読み手② 索引 build {yrs} 年: 兵庫 日 {s.get('days')} / 記録 {len(recs)}(うち 2026-03-06 より前 {old})"
            f" / 時計 {s.get('time')} 合否 {s.get('ok')} R番号 {s.get('r')} 上3F {s.get('a')} 体重 {s.get('w')} 騎手 {s.get('j')}"
            f" / 合否で落とした値 {s.get('dropped_ok')}")

    after = read_stored(base, key)
    n1d, n1r = counts(after["days"])
    log("年別に足した日・頭(" + ("dry-run= 書いていない" if a.dry_run else "書いた") + "): "
        + " / ".join(f"{y} {v[0]}日 {v[1]}頭" for y, v in sorted(by_year.items())))
    log(f"書き込み後 {META_KEY}: {n1d} 日 / {n1r} 頭(前 {n0d} 日 / {n0r} 頭)")
    log(f"取れなかった日 {len(failed)} {failed[:20]} / 表の無い日 {len(empty)}")
    return 1 if (rc or failed) else 0


if __name__ == "__main__":
    sys.exit(main())
