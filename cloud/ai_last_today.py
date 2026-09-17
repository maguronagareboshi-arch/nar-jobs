#!/usr/bin/env python3
"""§202 直前便(nar-ai-last.yml)の周の中で、公式の当日 ZIP を 1 回取り、**手元(ジョブ内 Postgres)**の当日行に
体重と馬場を重ねるための TSV を書く。

  python -X utf8 cloud/ai_last_today.py --date 2026-09-17 --out today
  → today/official_horses.tsv(track, race_date, race_no, runner_number, body_weight, body_weight_change)
    today/official_races.tsv (track, race_date, race_no, going, post_time)
    (取りに行かない回・失敗した回も**空の TSV**を書く= yml の \\copy がそのまま通る)

⛔本番には書かない(本番の体重は今までどおり refresh.py の役)。重ねる update は yml の psql が手元にだけ流す。
⛔取り方は refresh.py と同じ部品(nar_official_csv.download_url/download_archive/normalize_archive)= 新しい URL を作らない。
⛔公式に負荷をかけない= 「発走まで 15〜90 分で、体重が全頭(取消・除外を除く)そろっていないレース」が手元にあるときだけ取る。
⛔失敗(ZIP でない・タイムアウト)はログして 0 で終わる= 周を止めない(DB の値のまま予測する)。
"""
import argparse
import datetime as dt
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

JST = dt.timezone(dt.timedelta(hours=9))
WIN_LO, WIN_HI = 15, 90            # 発走まで何分の間のレースを待つか(15 分前= 印の締切)
H_COLS = ("track", "race_date", "race_no", "runner_number", "body_weight", "body_weight_change")
R_COLS = ("track", "race_date", "race_no", "going", "post_time")


def post_at(day, post_time):
    """'1550'(本番 nar_races・公式 CSV の書き方)/'15:50' → その日の JST の時刻。読めなければ None"""
    import re
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})", str(post_time or "").strip())
    if not m:
        return None
    try:
        return dt.datetime.combine(dt.date.fromisoformat(str(day)[:10]), dt.time(int(m.group(1)), int(m.group(2))), JST)
    except (ValueError, TypeError):
        return None


def waiting_races(races, runs, now, lo=WIN_LO, hi=WIN_HI):
    """races= [{track, race_date, race_no, post_time}]・runs= [{track, race_date, race_no, body_weight, finish_note}]
    → 発走まで lo〜hi 分で、取消・除外でない走に体重の無い走があるレースの鍵 [(track, race_no)]"""
    missing = set()
    for r in runs:
        if r.get("body_weight") is None and not str(r.get("finish_note") or "").strip():
            missing.add((r["track"], int(r["race_no"])))
    out = []
    for r in races:
        at = post_at(r.get("race_date"), r.get("post_time"))
        key = (r["track"], int(r["race_no"]))
        if at is None or key not in missing:
            continue
        mins = (at - now).total_seconds() / 60
        if lo <= mins <= hi:
            out.append(key)
    return sorted(out)


def overlay_rows(horses, day, local_null):
    """公式の当日の馬の行 → 重ねる行(体重がある行だけ= NULL で上書きしない)と、手元に無かった走の鍵。
    local_null= 手元で体重が空の走の鍵 {(track, race_no, runner_number)}"""
    rows, new = [], []
    for h in horses:
        if str(h.get("race_date") or "")[:10] != day or h.get("body_weight") is None:
            continue
        key = (h["track"], int(h["race_no"]), int(h["runner_number"]))
        rows.append({"track": h["track"], "race_date": day, "race_no": key[1], "runner_number": key[2],
                     "body_weight": int(h["body_weight"]),
                     "body_weight_change": "" if h.get("body_weight_change") is None else int(h["body_weight_change"])})
        if key in local_null:
            new.append(key)
    return rows, new


def race_rows(races, day):
    """馬場か発走時刻のある当日のレースだけ(空の馬場で上書きしないのは yml の update の where)"""
    return [{"track": r["track"], "race_date": day, "race_no": int(r["race_no"]),
             "going": r.get("going") or "", "post_time": r.get("post_time") or ""}
            for r in races if str(r.get("race_date") or "")[:10] == day and (r.get("going") or r.get("post_time"))]


def write_tsv(path, cols, rows):
    """psql の \\copy(text 形式)で読める TSV。空の値は空文字(going/post_time)・体重増減の空は \\N"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        for r in rows:
            vals = []
            for c in cols:
                v = r.get(c)
                vals.append("\\N" if (v == "" and c == "body_weight_change") else str(v).replace("\t", " ").replace("\n", " "))
            f.write("\t".join(vals) + "\n")


def local_state(day):
    import pg8000.native
    con = pg8000.native.Connection(user=os.environ.get("PGUSER", "postgres"), host=os.environ.get("PGHOST", "localhost"),
                                   port=int(os.environ.get("PGPORT", "5432")), database=os.environ.get("PGDATABASE", "postgres"),
                                   password=os.environ.get("LOCAL_PGPASSWORD") or os.environ.get("PGPASSWORD"))
    try:
        races = [dict(zip(("track", "race_date", "race_no", "post_time"), r)) for r in con.run(
            "select track, race_date::text, race_no, post_time from public.nar_races where race_date = cast(:d as date)", d=day)]
        runs = [dict(zip(("track", "race_date", "race_no", "runner_number", "body_weight", "finish_note"), r)) for r in con.run(
            "select track, race_date::text, race_no, runner_number, body_weight, finish_note from public.nar_runs "
            "where race_date = cast(:d as date)", d=day)]
    finally:
        con.close()
    return races, runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", default="today")
    ap.add_argument("--now", default=None, help="JST の 'YYYY-MM-DD HH:MM'(検算用)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    hp, rp = out / "official_horses.tsv", out / "official_races.tsv"
    write_tsv(hp, H_COLS, [])
    write_tsv(rp, R_COLS, [])
    now = dt.datetime.fromisoformat(a.now).replace(tzinfo=JST) if a.now else dt.datetime.now(JST)
    try:
        races, runs = local_state(a.date)
    except Exception as e:                                   # noqa: BLE001
        print(f"official today: skip(手元の表が読めない {type(e).__name__})", flush=True)
        return 0
    wait = waiting_races(races, runs, now)
    if not wait:
        print("official today: skip(待ちのレース無し)", flush=True)
        return 0
    try:
        from nar_official_csv import download_archive, download_url, normalize_archive
        url = download_url("race", scope="daily", race_date=a.date)
        payload, final_url = download_archive(url, timeout=60)
        doc = normalize_archive(payload, kind="race", scope="daily", source_url=final_url,
                                observed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    except Exception as e:                                   # noqa: BLE001
        print(f"official today: 取得失敗 {type(e).__name__}: {str(e)[:120]}(待ち {len(wait)} レース・DB の値のまま)", flush=True)
        return 0
    local_null = {(r["track"], int(r["race_no"]), int(r["runner_number"])) for r in runs
                  if r.get("body_weight") is None and not str(r.get("finish_note") or "").strip()}
    rows, new = overlay_rows(doc.get("horses") or [], a.date, local_null)
    write_tsv(hp, H_COLS, rows)
    write_tsv(rp, R_COLS, race_rows(doc.get("races") or [], a.date))
    names = sorted({f"{t}{n}R" for t, n, _ in new})
    print(f"official today: 体重あり {len(rows)} 走・DB に無かった {len(new)} 走({' '.join(names) or 'なし'})"
          f"・待ち {len(wait)} レース({' '.join(f'{t}{n}R' for t, n in wait)})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
