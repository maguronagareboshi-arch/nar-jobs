r"""§119(2026-09-06 Fable) data/kb_all/runs_{日}.json → 新DB(nar-official) nar_kb_runs へ upsert。

  py -3 -u scraper/push_kb_runs.py --since 20260101          # 遡り(ファイルがある日ぶん全部)
  py -3 -u scraper/push_kb_runs.py --since 20260830          # 毎日の段(直近 1 週間)
  py -3 -u scraper/push_kb_runs.py --date 20260904 --dry-run # 1 日だけ・書かない

- 入れる場= KB_PUBLIC の 6 場だけ(門別・大井・船橋・川崎・浦和・園田)。他の 9 場は出どころに
  馬装具・前半3F が無い(#497 実測)ので行を送らない。
- 中身が 1 つも無い行(馬具・前半3F・平均ハロン・ペース・決め手・発走状況・ブリンカ 全部 null)は送らない。
- 鍵= C:\Users\kouki\OneDrive\デスクトップ\s77-w1\pipeline\.env.nar の SUPABASE_URL / SUPABASE_SERVICE_KEY
  (⛔os.environ には入れない・印字しない)。
- PK (track, race_date, race_no, umaban) で merge-duplicates。updated_at は DB 側の now()。
"""
import argparse
import os
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ["KB_DATA_DIR"]) if os.environ.get("KB_DATA_DIR") else HERE.parent / "data"   # cloud
OUT = DATA / "kb_all"
NAR_ENV = Path(r"C:\Users\kouki\OneDrive\デスクトップ\s77-w1\pipeline\.env.nar")
KB_PUBLIC = ("門別", "大井", "船橋", "川崎", "浦和", "園田")
PAYLOAD = ("blinker", "gear", "first3f", "avg_f", "pace", "kimete", "start_note")
COLS = ("track", "race_date", "race_no", "umaban", "horse_name", "kb_race_id") + PAYLOAD
CHUNK = 500


def log(msg):
    print(msg, flush=True)


def read_env(path):
    # cloud(2026-09-29): 鍵は secrets→環境変数 SUPABASE_URL / SUPABASE_SERVICE_KEY(⛔印字しない)
    if os.environ.get("SUPABASE_URL"):
        return {"SUPABASE_URL": os.environ["SUPABASE_URL"],
                "SUPABASE_SERVICE_KEY": os.environ.get("SUPABASE_SERVICE_KEY", "")}
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def rows_of(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in obj.get("runs", []):
        if r.get("track") not in KB_PUBLIC:
            continue
        if all(r.get(k) in (None, "") for k in PAYLOAD):
            continue
        if not r.get("umaban") or not r.get("race_no"):
            continue
        d = str(r["race_date"])
        row = {k: r.get(k) for k in COLS}
        row["race_date"] = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        out.append(row)
    return out


# cloud(2026-09-29): 空で上書きしない。競馬ブックの頁は前半3F などが取るたびに伏せ字になったり
#   ならなかったりする。PC は runs_*.json を便ごとに足し合わせて(None で上書きしない)守っていたが、
#   cloud は毎回まっさらなので、送る前に本番の既存行を読んで、空の列は既存の値を残す。
KEEP_COLS = ("horse_name", "kb_race_id") + PAYLOAD


def _empty(v):
    return v is None or v == ""


def keep_existing(rows, existing):
    """rows を直に直す。existing= {(track, race_date, race_no, umaban): 既存行}。→ {列: 残した数}"""
    kept = {}
    for r in rows:
        ex = existing.get((r["track"], str(r["race_date"]), int(r["race_no"]), int(r["umaban"])))
        if not ex:
            continue
        for k in KEEP_COLS:
            if _empty(r.get(k)) and not _empty(ex.get(k)):
                r[k] = ex[k]
                kept[k] = kept.get(k, 0) + 1
    return kept


def read_existing(base, key, race_date):
    """nar_kb_runs のその日の 6 場の行(読むだけ)→ {(track, race_date, race_no, umaban): 行}"""
    import urllib.parse
    out, off = {}, 0
    tracks = ",".join(f'"{t}"' for t in KB_PUBLIC)
    while True:
        q = urllib.parse.urlencode({
            "select": ",".join(COLS), "race_date": f"eq.{race_date}", "track": f"in.({tracks})",
            "order": "track,race_no,umaban", "limit": "1000", "offset": str(off)})
        req = urllib.request.Request(base.rstrip("/") + "/rest/v1/nar_kb_runs?" + q,
                                     headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            got = json.loads(resp.read().decode("utf-8"))
        for e in got:
            out[(e["track"], str(e["race_date"]), int(e["race_no"]), int(e["umaban"]))] = e
        if len(got) < 1000:
            return out
        off += 1000


def upsert(base, key, rows):
    url = base.rstrip("/") + "/rest/v1/nar_kb_runs?on_conflict=track,race_date,race_no,umaban"
    for i in range(0, len(rows), CHUNK):
        body = json.dumps(rows[i:i + CHUNK], ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 201, 204):
                raise RuntimeError(f"HTTP {resp.status}")


def main():
    ap = argparse.ArgumentParser(description="§119 nar_kb_runs 投入")
    ap.add_argument("--date", help="YYYYMMDD(1 日だけ)")
    ap.add_argument("--since", help="YYYYMMDD(この日以降のファイル全部)")
    ap.add_argument("--dry-run", action="store_true", help="数えるだけ・書かない")
    args = ap.parse_args()
    if not args.date and not args.since:
        ap.error("--date か --since のどちらかが要ります")
    files = sorted(OUT.glob("runs_*.json"))
    if args.date:
        files = [f for f in files if f.stem == f"runs_{args.date}"]
    else:
        files = [f for f in files if f.stem[5:] >= args.since]
    if not files:
        log("対象ファイル無し")
        return 0
    env = read_env(NAR_ENV)
    base, key = env["SUPABASE_URL"], env.get("SUPABASE_SERVICE_KEY", "")
    if not key and not args.dry_run:
        log("✗ SUPABASE_SERVICE_KEY が無い")
        return 1
    total = kept_all = 0
    for f in files:
        rows = rows_of(f)
        by = {}
        for r in rows:
            by[r["track"]] = by.get(r["track"], 0) + 1
        if not rows:
            log(f"{f.stem[5:]}: 送る行なし")
            continue
        # cloud(2026-09-29): 送る前に既存行を読み、空で既存に値がある列は既存を残す(鍵が無ければ読まない)
        kept = {}
        if key:
            kept = keep_existing(rows, read_existing(base, key, rows[0]["race_date"]))
        kept_all += sum(kept.values())
        if not args.dry_run:
            upsert(base, key, rows)
        total += len(rows)
        log(f"{f.stem[5:]}: {len(rows)} 行 {by}・既存を残した値 {sum(kept.values())} {kept}"
            f"{'(dry-run)' if args.dry_run else ''}")
    log(f"おわり: {len(files)} ファイル {total} 行・既存を残した値 {kept_all}"
        f"{'(dry-run・書いていない)' if args.dry_run else ' 投入'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
