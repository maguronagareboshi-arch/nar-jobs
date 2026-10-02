# -*- coding: utf-8 -*-
"""§移籍まとめ D1(2026-09-30): 競馬ブック公開頁の「中央在籍 N戦」を nar_jra_horses.jra_career_runs に書く。

  頁= https://p.keibabook.co.jp/db/uma/{kb_horse_id}(ログイン不要・/seiseki へ転送される)。
  頭の「全成績 中央在籍 N戦(…) 地方在籍 M戦(…)」を読む。中央在籍の表示が無く地方在籍だけある馬= 0
  (地方所属のまま中央の交流に出ただけ。例 グレートスティック 0949823)。どちらも無い頁= 読めない(書かない)。
  使い道: nar-jobs cloud/horse_changes.py の jra_in が 0 の馬の中央の走を転入と数えない。
  ⛔列は nar-jobs sql/transfer_jra_in.sql で足す(適用前に --push すると 400 で落ちる)。

  py -3 -X utf8 cloud/kb/fetch_jra_career.py --horse-ids 0949823,0898443        # 既定= dry-run(印字だけ)
  py -3 -X utf8 cloud/kb/fetch_jra_career.py --pending 300 --push                # 未取得(中央の走あり)を 300 頭
cloud(2026-10-03): 他場\scraper の写し。毎日 kb-daily.yml の最後の手順で --pending 300 --push。
鍵= fetch_jra_runs.py と同じ(クラウドは環境変数 SUPABASE_URL/SUPABASE_SERVICE_KEY・手元は NAR_ENV・印字しない)。
--push のとき nar_job_heartbeat に job=jra_career で 1 行(書き方は fetch_jra_runs.Nar.heartbeat)。
"""
import argparse
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import fetch_jra_runs  # noqa: E402
from fetch_jra_runs import NAR_ENV, Nar, log  # noqa: E402

URL = "https://p.keibabook.co.jp/db/uma/{id}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
WAIT = 3.0


def parse_career(html):
    """「中央在籍 N戦」の N。表示なし+地方在籍あり= 0。どちらも無い= None(読めない)。"""
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    k = t.find("全成績")
    if k < 0:
        return None
    head = t[k:k + 200]
    m = re.search(r"中央在籍\s*([0-9,]+)\s*戦", head)
    if m:
        return int(m.group(1).replace(",", ""))
    return 0 if re.search(r"地方在籍\s*[0-9,]+\s*戦", head) else None


def fetch(hid):
    r = requests.get(URL.format(id=hid), headers={"User-Agent": UA}, timeout=40)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--horse-ids")
    ap.add_argument("--pending", type=int, help="jra_career_runs が空で中央の走がある馬を N 頭")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--wait", type=float, default=WAIT)
    a = ap.parse_args(argv)
    nar = Nar(NAR_ENV) if (a.push or a.pending) else None
    ids = [x.strip() for x in (a.horse_ids or "").split(",") if x.strip()]
    if a.pending:
        rows = nar.get("nar_jra_horses", {"select": "kb_horse_id", "jra_career_runs": "is.null",
                                          "jra_runs": "gt.0", "order": "kb_horse_id", "limit": str(a.pending)})
        ids += [r["kb_horse_id"] for r in rows or []]
    got, bad = 0, 0
    for i, hid in enumerate(ids):
        try:
            n = parse_career(fetch(hid))
        except requests.RequestException as e:
            n = None
            log(f"  ! {hid} {type(e).__name__}")
        log(f"{hid} 中央在籍 {n}")
        if n is None:
            bad += 1
        else:
            got += 1
            if a.push:
                r = nar._call("PATCH", nar.base + f"nar_jra_horses?kb_horse_id=eq.{hid}", "patch nar_jra_horses",
                              headers=dict(nar._h, Prefer="return=minimal"), json={"jra_career_runs": n})
                if r.status_code >= 300:
                    raise RuntimeError(f"patch {hid}: HTTP {r.status_code} {r.text[:200]}")
        if i < len(ids) - 1:
            time.sleep(a.wait)
    log(f"読めた {got} 頭 / 読めない {bad} 頭" + ("" if a.push else "(dry-run= 書かない)"))
    if a.push:
        fetch_jra_runs.HB_JOB = "jra_career"
        nar.heartbeat(True, f"read {got} / unreadable {bad}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
