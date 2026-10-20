# -*- coding: utf-8 -*-
"""10/15 トップの帯「今日の出走馬」の件数と一覧 —— その日の出馬表×前走 1 本 → nar_meta 2 行。

  top_band             = {v:1, date, built, n:{transfer, layoff, dist, venue},
                          transfer:{jra, area, stable}}          … トップ(getTopMeta の相乗り)が読む件数だけ
  top_band:YYYY-MM-DD  = {v:1, date, built, rows:{layoff:[[HHMM, 場, R, 馬番, 馬名, 日数]],
                          dist:[[…, 前走m, 今回m, 前走の着順, 前走の人気, 移籍]], venue:[[…, 前走の場, 前走の着順, 前走の人気, 移籍]]}} … 一覧 /today/facts/:kind が読む
                          (10/20 末尾を足した: layoff=[日数, 着順, 人気, 移籍] dist=[…, 着順, 人気, 移籍]。着順・人気は数字か null・移籍= 今日が移籍後の初戦なら jra_in/transfer_in/stable_change・無ければ null。⛔夜の回(--no-transfer)は移籍の表が未着= 移籍は null になる)
新馬(noken_debuts)とオークション(auction_today)の件数は画面が既存の行から数える= ここでは書かない。
10/16 前の晩の分: 夜の回(JST 22:10)が `--date 翌日 --key top_band_next` で翌日分を別の鍵に書く(10/16 から移籍も= 先に horse_changes を夜にも流す。--no-transfer は便が止まったとき用に残す)
  (翌日の出馬表は前日までに入っている。⛔移籍の表は当日朝 05:33 の便で半分ほど足される= 実測 10/14〜16 で
   その日の行の 31〜52% が当日 06:00〜06:15 に入った→ 夜は移籍を書かない= n.transfer と transfer は null)。
  一覧 top_band:翌日 は日付つきなのでそのまま書く(朝の回が同じ鍵を上書きする)。画面は top_band が今日でなければ top_band_next を使う。

規則(画面の言葉と同じ):
  休み明け= 前走から 70 日以上 / 距離= 前走から 400m 以上の差 / 前走と別の場= 前走の場が今日の場と違う
  移籍後の初出走= nar_horse_changes のその日の行(馬ごと 1 頭・内訳は 中央から > 他地区から > 転厩 の順に 1 つ)
  ⛔取消・除外(finish_note か margin に字)は数えない。⛔前走= 同じ馬名(生年月日があれば一致)で今日より前の一番新しい走。

⛔本番 DB では REST の単純 select だけ(その日の出走+前走 1 本)。前走は 120 日の窓で引き、窓に無い馬だけ全期間で引き直す。
⛔読み取りに失敗したら書かない(前の値が残る= 画面は date が今日でなければ使わない)。
⛔古い日の top_band:* は 7 日で消す(--apply のときだけ)。

  python cloud/top_band.py --env pipeline/.env.nar                       # ドライラン(書かない・匿名キーでも動く)
  python cloud/top_band.py --env pipeline/.env.nar --date 2026-10-15     # 日を指定
  python cloud/top_band.py --apply                                       # 書く
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from noken_debuts import enc, load_env, log, req  # noqa: E402
from auction_today import all_rows  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
WINDOW_DAYS = 120
KEEP_DAYS = 7
LAYOFF_DAYS = 70
DIST_DIFF_M = 400
CHUNK = 80
CANCEL_RE = re.compile(r"(取消|除外)")


def hhmm(v):
    m = re.match(r"^(\d{1,2}):?(\d{2})$", str(v or "").strip())
    return f"{int(m.group(1)):02d}{m.group(2)}" if m else ""


def is_cancel(run):
    return bool(CANCEL_RE.search(str(run.get("finish_note") or "") + str(run.get("margin") or "")))


def pick_prev(run, cands):
    """cands= 同じ馬名の走(新しい順)。今日の行に生年月日があれば一致する走だけ(無い行も外す)。今日より前の一番新しい 1 本。"""
    bd = run.get("birth_date")
    for c in cands:
        if str(c["race_date"]) >= str(run["race_date"]):
            continue
        if bd and str(c.get("birth_date") or "") != str(bd):   # ⛔生年月日の無い古い行(2022-10 より前の同名)は別の馬とみる
            continue
        return c
    return None


def count_band(date, runs, races, prevs, prev_dist, changes):
    """件数と一覧を作る(通信なし= 試験の対象)。
    runs= その日の出走(nar_runs の行)・races= その日のレース {(場, R): {post_time, distance_m}}・
    prevs= {(場, R, 馬番): 前走の行 or None}・prev_dist= {(場, 日, R): 距離m}・changes= nar_horse_changes のその日の行。"""
    d0 = dt.date.fromisoformat(date)
    out = {"layoff": [], "dist": [], "venue": []}
    rank = {"jra_in": 0, "transfer_in": 1, "stable_change": 2}
    best = {}
    for c in changes:
        kind = str(c.get("kind") or "")
        if kind not in rank:
            continue
        hk = (str(c.get("horse_name") or ""), str(c.get("birth_date") or ""))
        if hk not in best or rank[kind] < rank[best[hk]]:
            best[hk] = kind
    live = [r for r in runs if not is_cancel(r)]
    live.sort(key=lambda r: (hhmm((races.get((r["track"], int(r["race_no"]))) or {}).get("post_time")) or "9999",
                             str(r["track"]), int(r["race_no"]), int(r["runner_number"])))
    for r in live:
        k = (str(r["track"]), int(r["race_no"]), int(r["runner_number"]))
        race = races.get(k[:2]) or {}
        head = [hhmm(race.get("post_time")), k[0], k[1], k[2], str(r.get("horse_name") or "")]
        p = prevs.get(k)
        if not p:
            continue
        days = (d0 - dt.date.fromisoformat(str(p["race_date"]))).days
        fin, pop = to_int(p.get("finish")), to_int(p.get("popularity"))
        chg = best.get((str(r.get("horse_name") or ""), str(r.get("birth_date") or "")))   # 今日が移籍後の初戦なら その種類
        if days >= LAYOFF_DAYS:
            out["layoff"].append(head + [days, fin, pop, chg])
        now_m = race.get("distance_m")
        prev_m = prev_dist.get((str(p["track"]), str(p["race_date"]), int(p["race_no"])))
        if isinstance(now_m, int) and isinstance(prev_m, int) and abs(now_m - prev_m) >= DIST_DIFF_M:
            out["dist"].append(head + [prev_m, now_m, fin, pop, chg])
        if str(p["track"]) != k[0]:
            out["venue"].append(head + [str(p["track"]), fin, pop, chg])
    tr = {"jra": 0, "area": 0, "stable": 0}
    for kind in best.values():
        tr[{"jra_in": "jra", "transfer_in": "area", "stable_change": "stable"}[kind]] += 1
    n = {"transfer": len(best), "layoff": len(out["layoff"]), "dist": len(out["dist"]), "venue": len(out["venue"])}
    return {"n": n, "transfer": tr, "rows": out}


def head_value(date, built, got, with_transfer=True):
    """件数の行(top_band / top_band_next)。夜の回は移籍を null にする(画面は「◯時すぎに数えます」を出す)。"""
    n = dict(got["n"])
    tr = dict(got["transfer"]) if with_transfer else None
    if not with_transfer:
        n["transfer"] = None
    return {"v": 1, "date": date, "built": built, "n": n, "transfer": tr}


def to_int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def quote_in(names):
    return enc(",".join('"' + n.replace('"', "") + '"' for n in names))


def fetch(base, key, date):
    races_l = all_rows(base, key, f"/rest/v1/nar_races?select=track,race_no,post_time,distance_m&race_date=eq.{date}",
                       "track.asc,race_no.asc")
    races = {(str(r["track"]), int(r["race_no"])): {"post_time": r.get("post_time"), "distance_m": to_int(r.get("distance_m"))}
             for r in races_l}
    runs = all_rows(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date,"
                               f"finish_note,margin&race_date=eq.{date}", "track.asc,race_no.asc,runner_number.asc")
    names = sorted({str(r.get("horse_name") or "") for r in runs} - {""})
    lo = str(dt.date.fromisoformat(date) - dt.timedelta(days=WINDOW_DAYS))
    cols = "track,race_date,race_no,runner_number,horse_name,birth_date,finish,popularity"

    def past(names_, lower):
        got = {}
        for i in range(0, len(names_), CHUNK):
            q = (f"/rest/v1/nar_runs?select={cols}&horse_name=in.({quote_in(names_[i:i + CHUNK])})&race_date=lt.{date}"
                 + (f"&race_date=gte.{lower}" if lower else ""))
            for x in all_rows(base, key, q, "horse_name.asc,race_date.desc,track.asc,race_no.asc,runner_number.asc"):
                got.setdefault(str(x["horse_name"]), []).append(x)
        return got

    cand = past(names, lo)
    prevs = {}
    for r in runs:
        prevs[(str(r["track"]), int(r["race_no"]), int(r["runner_number"]))] = pick_prev(r, cand.get(str(r.get("horse_name") or ""), []))
    miss = sorted({str(r.get("horse_name") or "") for r in runs
                   if prevs[(str(r["track"]), int(r["race_no"]), int(r["runner_number"]))] is None} - {""})
    if miss:                                     # 窓(120 日)に前走の無い馬だけ全期間で(新馬・長期休養の数十頭)
        cand2 = past(miss, None)
        for r in runs:
            k = (str(r["track"]), int(r["race_no"]), int(r["runner_number"]))
            if prevs[k] is None:
                prevs[k] = pick_prev(r, cand2.get(str(r.get("horse_name") or ""), []))
    pairs = sorted({(str(p["track"]), str(p["race_date"])) for p in prevs.values() if p})
    prev_dist = {}
    for i in range(0, len(pairs), 30):
        ors = ",".join(f"and(track.eq.{t},race_date.eq.{d})" for t, d in pairs[i:i + 30])
        for x in all_rows(base, key, f"/rest/v1/nar_races?select=track,race_date,race_no,distance_m&or=({enc(ors)})",
                          "track.asc,race_date.asc,race_no.asc"):
            prev_dist[(str(x["track"]), str(x["race_date"]), int(x["race_no"]))] = to_int(x.get("distance_m"))
    changes = all_rows(base, key, "/rest/v1/nar_horse_changes?select=horse_name,birth_date,kind"
                                  f"&race_date=eq.{date}&kind=in.(transfer_in,stable_change,jra_in)",
                       "horse_name.asc,birth_date.asc,kind.asc")
    log(f"{date} レース {len(races)}・出走 {len(runs)}行・馬名 {len(names)}頭・前走なし {sum(1 for p in prevs.values() if not p)}"
        f"・前走の開催 {len(pairs)}・移籍の行 {len(changes)}")
    return runs, races, prevs, prev_dist, changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--date", help="YYYY-MM-DD(既定= JST の今日)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="書かない(既定と同じ)")
    ap.add_argument("--out", help="ドライランで作った 2 行を JSON で保存するファイル")
    ap.add_argument("--key", default="top_band", choices=["top_band", "top_band_next"], help="件数の行の鍵(夜の回は top_band_next)")
    ap.add_argument("--no-transfer", action="store_true", help="移籍を書かない(夜の回= 移籍の表が当日朝に足されるため)")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    apply = a.apply and not a.dry_run
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or ("" if apply else os.environ.get("SUPABASE_ANON_KEY", ""))
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
    date = a.date or str(dt.datetime.now(JST).date())
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        log("--date は YYYY-MM-DD"); return 2
    try:
        got = count_band(date, *fetch(base, key, date))
    except Exception as e:  # ⛔読み取りに失敗したら書かない
        log(f"読み取りに失敗(書かない) {type(e).__name__}: {e}"); return 1
    built = dt.datetime.now(JST).isoformat(timespec="seconds")
    head = head_value(date, built, got, with_transfer=not a.no_transfer)
    day = {"v": 1, "date": date, "built": built, "rows": got["rows"]}
    log(f"件数 {json.dumps(got['n'], ensure_ascii=False)}・移籍の内訳 {json.dumps(got['transfer'], ensure_ascii=False)}"
        f"・一覧 {len(json.dumps(day, ensure_ascii=False).encode('utf-8'))} バイト")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({a.key: head, "top_band:" + date: day}, f, ensure_ascii=False)
    if not apply:
        log("ドライラン(--apply で書く)"); return 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": "top_band:" + date, "value": day, "updated_at": now},
                            {"key": a.key, "value": head, "updated_at": now}], ensure_ascii=False).encode("utf-8"))
    log(f"nar_meta/{a.key}・top_band:{date} 更新 {st}")
    if st not in (200, 201, 204):
        return 1
    old = str(dt.date.fromisoformat(date) - dt.timedelta(days=KEEP_DAYS))
    st2, _ = req(base, key, f"/rest/v1/nar_meta?key=like.{enc('top_band:*')}&key=lt.{enc('top_band:' + old)}", "DELETE")
    log(f"top_band:{old} より前を消した {st2}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
