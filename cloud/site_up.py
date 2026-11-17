# -*- coding: utf-8 -*-
"""yukochi.com が開けるかの点検(site-up.yml から 10 分ごと・2026-11-17)。

  python3 cloud/site_up.py            … トップ(?nocount=1)と画面の部品 1 つ(js か css)を取る。開けなければ exit 1
  python3 cloud/site_up.py --issue    … 上に加え、今回も前回(site-up の 1 つ前の run)も失敗なら緊急の issue(site)。開ければ閉じる

海外の確認画面(WAF)は見出し x-nar-sweep = 秘密 SWEEP_PASS で外す(自サイトへの要求にだけ付ける)。
前回の結果= Actions の 1 つ前の run の結論(失敗した run は最後の手順で赤にしてある)。
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emergency_issue as ei  # noqa: E402

TOP = "https://yukochi.com/?nocount=1"
HOST = "yukochi.com"


def _get(url):
    h = {"User-Agent": "nar-jobs-site-up/1.0"}
    p = os.environ.get("SWEEP_PASS", "").strip()
    if p and urllib.parse.urlparse(url).hostname == HOST:
        h["x-nar-sweep"] = p
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        return r.status, r.read()


def check():
    """→ (ok, 説明)。"""
    try:
        st, html = _get(TOP)
    except Exception as e:   # noqa: BLE001
        return False, f"トップが開けない({type(e).__name__} {str(e)[:120]})"
    text = html.decode("utf-8", "replace")
    if st != 200 or "<html" not in text.lower():
        return False, f"トップの応答が変(status {st}・{len(html)} バイト)"
    part = None
    for m in re.finditer(r'(?:src|href)="([^"]+\.(?:js|css))(?:\?[^"]*)?"', text):
        u = urllib.parse.urljoin(TOP, m.group(1))
        if urllib.parse.urlparse(u).hostname == HOST:
            part = u
            break
    if not part:
        return False, "トップに画面の部品(js/css)が見つからない"
    try:
        st, b = _get(part)
    except Exception as e:   # noqa: BLE001
        return False, f"画面の部品 {part} が取れない({type(e).__name__} {str(e)[:120]})"
    if st != 200 or len(b) < 100:
        return False, f"画面の部品 {part} の応答が変(status {st}・{len(b)} バイト)"
    return True, f"トップ {len(html)} バイト・部品 {part} {len(b)} バイト"


def prev_failed():
    """site-up.yml の 1 つ前の(この run を除く・終わった)run が failure か。読めなければ False(= 鳴らさない側)。"""
    try:
        me = str(os.environ.get("GITHUB_RUN_ID", ""))
        got = ei._api("GET", "actions/workflows/site-up.yml/runs?status=completed&per_page=5") or {}
        runs = [r for r in got.get("workflow_runs") or [] if str(r.get("id")) != me]
        return bool(runs) and runs[0].get("conclusion") == "failure"
    except Exception as e:   # noqa: BLE001
        print(f"::warning::前回の結果が読めない= 今回は鳴らさない({type(e).__name__})")
        return False


def main():
    ok, msg = check()
    print(("開けた: " if ok else "開けない: ") + msg, flush=True)
    if "--issue" in sys.argv[1:]:
        dry = "--dry-run" in sys.argv[1:]
        try:
            if ok:
                ei.resolve("site", dry)
            elif prev_failed():
                title, what, impact = ei.TEXT["site"]
                ei.raise_issue("site", title, what, impact, dry=dry)
            else:
                print("1 回目の失敗= 次の点検も失敗なら緊急にする")
        except Exception as e:   # noqa: BLE001
            print(f"::warning::緊急の issue の処理が失敗: {type(e).__name__} {str(e)[:200]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
