# -*- coding: utf-8 -*-
r"""§121(2026-09-07) data/fukuchan/{日付}.json → 本体(nar-official)の nar_paper_talks へ upsert。

  py -3.12 -u scraper/push_fukuchan.py --date 2026-09-05 --dry-run   # 1 日ぶん・数えるだけ
  py -3.12 -u scraper/push_fukuchan.py --date 2026-09-05             # 1 日ぶん 投入
  py -3.12 -u scraper/push_fukuchan.py --all                         # data/fukuchan/ の JSON ぜんぶ

- 鍵= nar_push.py が pipeline\.env.nar をその場で読む(⛔os.environ に入れない・⛔印字しない)。
- §157 6-3(2026-09-12): 置き場を `kochi_paper_talks` → **`nar_paper_talks`** へ移した。
  PK は (track, race_date, race_no, umaban)= 場が 1 列目に増え、`paper_date` は `race_date`、
  `source_file` は `source` に名前が変わった。updated_at は DB 側の now()。
- ⚠新しい表に **`matched` の列は無い**= 送らない。未突合は**画面で数え直す**
  (レースページが公式の出馬表にその馬番が無い枠を「未突合」と断って出す)。
  ⛔未突合の行そのものは今までどおり**送る**(こちらの都合で消さない)。ログには今までどおり数を出す。
- ⛔談話が読めなかった枠(talk=null)は**送らない**(無いものは無いまま)。
- ⛔閲覧者には出ない表(RLS で anon は select も不可)。⛔本文をログに出さない。

⚠この表は `pipeline/sql/kb_paper_20260912.sql` を先に流してから(適用済= §157 F5)。
"""
import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from nar_push import upsert as nar_upsert

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ["KB_DATA_DIR"]) if os.environ.get("KB_DATA_DIR") else HERE.parent / "data"   # cloud
OUT = DATA / "fukuchan"
TABLE = "nar_paper_talks"
TRACK = "高知"
ON_CONFLICT = "track,race_date,race_no,umaban"
COLS = ("track", "race_date", "race_no", "umaban", "horse_name", "talk", "source")


def log(msg):
    print(msg, flush=True)


def rows_of(path):
    """JSON 1 本 → 送る行。⛔談話の無い枠・馬名の無い枠は送らない。"""
    doc = json.loads(path.read_text(encoding="utf-8"))
    date = doc.get("date")
    src = doc.get("source_file") or path.name
    if not date:
        return [], 0
    out, skipped = [], 0
    for race in doc.get("races", []):
        no = race.get("race_no")
        for r in race.get("rows", []):
            talk = (r.get("talk") or "").strip()
            name = (r.get("name") or "").strip()
            if not talk or not name or no is None or r.get("umaban") is None:
                skipped += 1
                continue
            out.append({
                "track": TRACK, "race_date": date, "race_no": int(no), "umaban": int(r["umaban"]),
                "horse_name": name, "talk": talk, "source": src,
                # ⚠`matched` は表に列が無いので送らない。数えるためだけに持っておく(下のログ)
                "_matched": bool(r.get("matched")),
            })
    return out, skipped


def upsert(rows):
    """本体の nar_paper_talks へ。⛔表に無い `_matched` は落としてから送る。"""
    body = [{k: r[k] for k in COLS} for r in rows]
    return nar_upsert(TABLE, body, ON_CONFLICT)


def main():
    ap = argparse.ArgumentParser(description="§121 福ちゃん談話 → nar_paper_talks 投入")
    ap.add_argument("--date", help="YYYY-MM-DD(1 日だけ)")
    ap.add_argument("--all", action="store_true", help="data/fukuchan/ の JSON ぜんぶ")
    ap.add_argument("--dry-run", action="store_true", help="数えるだけ・書かない")
    args = ap.parse_args()
    if not args.date and not args.all:
        ap.error("--date か --all のどちらかが要ります")
    files = sorted(f for f in OUT.glob("*.json"))
    if args.date:
        files = [f for f in files if f.stem == args.date]
    if not files:
        log("対象ファイル無し")
        return 0
    total = 0
    for f in files:
        rows, skipped = rows_of(f)
        if not rows:
            log(f"{f.stem}: 送る行なし(談話の無い枠 {skipped})")
            continue
        matched = sum(1 for r in rows if r["_matched"])
        if not args.dry_run and not upsert(rows):
            log("✗ pipeline\\.env.nar に SUPABASE_URL / SUPABASE_SERVICE_KEY が要ります")
            return 1
        total += len(rows)
        log(f"{f.stem}: {len(rows)} 行(突合 {matched} / 未突合 {len(rows) - matched} / "
            f"談話なしで送らない枠 {skipped}){'(dry-run)' if args.dry_run else ''}")
    log(f"おわり: {len(files)} ファイル {total} 行"
        f"{'(dry-run・書いていない)' if args.dry_run else ' 投入'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
