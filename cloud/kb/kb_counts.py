# -*- coding: utf-8 -*-
"""runs_{日}.json(fetch_kb_all.py の出力)を 日×場 の件数だけにまとめる(2026-09-29 cloud 移行の照合用)。

  python cloud/kb/kb_counts.py DIR [--since YYYYMMDD]
出力は件数だけ(⛔馬名・中身は出さない= public repo のログに載るため)。
  日 場 行 馬具あり 発走状況あり 出遅れ 前半3Fあり 送る行(push_kb_runs と同じ絞り)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from push_kb_runs import KB_PUBLIC, rows_of  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def counts(d, since=""):
    out = {}
    for f in sorted(Path(d).glob("runs_*.json")):
        day = f.stem[5:]
        if since and day < since:
            continue
        runs = json.loads(f.read_text(encoding="utf-8")).get("runs", [])
        send = {}
        for r in rows_of(f):
            send[r["track"]] = send.get(r["track"], 0) + 1
        for r in runs:
            t = r.get("track")
            if t not in KB_PUBLIC:
                continue
            c = out.setdefault((day, t), [0, 0, 0, 0, 0, 0])
            c[0] += 1
            c[1] += 1 if r.get("gear") else 0
            c[2] += 1 if r.get("start_note") else 0
            c[3] += 1 if "出遅" in (r.get("start_note") or "") else 0
            c[4] += 1 if r.get("first3f") is not None else 0
        for t, n in send.items():
            out.setdefault((day, t), [0, 0, 0, 0, 0, 0])[5] = n
    return out


def main():
    d = sys.argv[1]
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else ""
    print("日\t場\t行\t馬具あり\t発走状況あり\t出遅れ\t前半3Fあり\t送る行")
    for (day, t), c in sorted(counts(d, since).items()):
        print("\t".join([day, t] + [str(x) for x in c]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
