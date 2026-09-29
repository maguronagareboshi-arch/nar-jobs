# -*- coding: utf-8 -*-
"""競馬ブックにクラウド(Actions)からログインできるかの 1 回きりの試し(2026-09-29)。

- ID/PW は secrets KEIBABOOK_LOGIN_ID / KEIBABOOK_PASSWORD から読む。⛔値・Cookie・頁の中身は一切表示しない。
- 見るのは: ログインの成否・成績頁 1 枚の HTTP 状態と大きさ・会員の欄(前半3F)が開いているか。
- 本番 DB には書かない。ファイルも残さない。
"""
import os
import re
import sys
import time

import requests

BASE = "https://p.keibabook.co.jp"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
RACE_ID = sys.argv[1] if len(sys.argv) > 1 else "2026091303010924"   # 浦和 9/24 1R(終わったレース)


def get(s, method, url, **kw):
    time.sleep(2.5)
    r = s.request(method, url if url.startswith("http") else BASE + url, timeout=30, **kw)
    r.encoding = "utf-8"
    return r


def main():
    lid, pw = os.environ.get("KEIBABOOK_LOGIN_ID", ""), os.environ.get("KEIBABOOK_PASSWORD", "")
    if not lid or not pw:
        print("NG secrets が入っていない")
        return 2
    s = requests.Session()
    s.headers["User-Agent"] = UA

    r = get(s, "GET", "/login/login")
    print(f"login page: HTTP {r.status_code}")
    if r.status_code != 200:
        print("NG ログイン頁に届かない(海外 IP の拒否の可能性)")
        return 1
    m = re.search(r'name="_token" value="([^"]+)"', r.text)
    if not m:
        print("NG _token が見つからない")
        return 1
    r = get(s, "POST", "/login/login", data={
        "_token": m.group(1), "referer": "", "service": "keibabook",
        "login_id": lid, "pswd": pw, "autologin": "1", "submitbutton": "ログインする"})
    print(f"login post: HTTP {r.status_code}")
    if 'name="pswd"' in r.text and "ログインする" in r.text:
        print("NG ログイン失敗(ID/PW を確かめる)")
        return 1
    m = re.search(r"window\.location\.href\s*=\s*'(https?://[^']+)'", r.text)
    r = get(s, "GET", m.group(1) if m else "https://kessai.keibabook.co.jp/mypage/index")
    logged = "ログアウト" in r.text
    print(f"sso: HTTP {r.status_code} logged_in={logged}")
    if not logged:
        print("NG SSO 後もログイン状態にならない")
        return 1

    r = get(s, "GET", f"/chihou/seiseki/{RACE_ID}")
    body = r.text
    has_col = "前半" in body
    n_time = len(re.findall(r"\b3[3-9]\.\d\b", body))
    print(f"seiseki {RACE_ID}: HTTP {r.status_code} bytes={len(body)} 前半の欄={has_col} 3F らしい数={n_time}")
    print("OK クラウドからログインして成績頁を取れた" if r.status_code == 200 else "NG 成績頁が取れない")
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
