# -*- coding: utf-8 -*-
"""§196b 南関 公式 Q&A(番組)の原文を 1 回だけ取って、タグを除いた本文を保存する(手元・DB に触らない)。

  py -3.12 -X utf8 tools/nankan_rules_fetch.py            # data/cache_nankan/qanda_program.html と .txt を作る(あれば読まない)
  py -3.12 -X utf8 tools/nankan_rules_fetch.py --grep 昇級  # 保存した本文から語を含む段落を出す

⛔ 要約はしない= docs/s196b_rules.md の引用はこの .txt の字をそのまま写す。cp932 で読む。
"""
import argparse
import html
import re
import sys
import time
import urllib.request
from pathlib import Path

URL = "https://www.nankankeiba.com/info/qanda/program.html"
HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / "data" / "cache_nankan"
sys.path.insert(0, str(HERE.parent / "cloud"))


def ua():
    # 日次の便(cloud/nankan_points.py)と同じ UA を使う(⛔ここで新しく作らない)
    try:
        import nankan_points
        return nankan_points.UA
    except Exception:  # noqa: BLE001
        return "nar-jobs-recon/1.0"


def to_text(raw):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d|dt|dd|table)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = html.unescape(s)
    lines = [re.sub(r"[ \t　]+", " ", x).strip() for x in s.splitlines()]
    return "\n".join(x for x in lines if x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep", action="append", default=[])
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    hp, tp = CACHE / "qanda_program.html", CACHE / "qanda_program.txt"
    if not hp.exists():
        t0 = time.time()
        req = urllib.request.Request(URL, headers={"User-Agent": ua()})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            print("GET", URL, r.status, len(body), "bytes", round(time.time() - t0, 2), "s")
        hp.write_bytes(body)
    raw = hp.read_bytes().decode("cp932", errors="replace")
    txt = to_text(raw)
    tp.write_text(txt, encoding="utf-8")
    print("本文", len(txt), "字 →", tp)
    for w in a.grep:
        print("====", w)
        for i, ln in enumerate(txt.splitlines(), 1):
            if w in ln:
                print("%5d: %s" % (i, ln))


if __name__ == "__main__":
    main()
