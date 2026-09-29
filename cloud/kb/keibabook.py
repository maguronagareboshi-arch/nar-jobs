# -*- coding: utf-8 -*-
"""競馬ブックWeb (p.keibabook.co.jp) クライアント。

- 認証情報は .env (KEIBABOOK_LOGIN_ID / KEIBABOOK_PASSWORD)
- Cookie を data/cookies.txt に保存して使い回す（毎回ログインしない）
- リクエスト間隔を必ず空ける（既定 2.5 秒）
- 取得済みHTMLは data/cache/ に保存し、過去レースは再取得しない
"""

import http.cookiejar
import re
import time
from pathlib import Path

import requests

BASE = "https://p.keibabook.co.jp"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class LoginError(Exception):
    pass


class KeibabookClient:
    def __init__(self, login_id=None, password=None, data_dir="data", wait_seconds=2.5):
        self.login_id = login_id
        self.password = password
        self.wait_seconds = float(wait_seconds)
        self.data_dir = Path(data_dir)
        self.cache_dir = self.data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

        self.cookie_path = self.data_dir / "cookies.txt"
        jar = http.cookiejar.MozillaCookieJar(str(self.cookie_path))
        if self.cookie_path.exists():
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
            except Exception:
                pass
        self.session.cookies = jar

        self._last_request = 0.0

    # ---- 低レベル ----

    def _throttle(self):
        gap = time.monotonic() - self._last_request
        if gap < self.wait_seconds:
            time.sleep(self.wait_seconds - gap)

    def _request(self, method, path, **kw):
        url = path if path.startswith("http") else BASE + path
        self._throttle()
        try:
            r = self.session.request(method, url, timeout=30, **kw)
        finally:
            self._last_request = time.monotonic()
        r.raise_for_status()
        r.encoding = "utf-8"
        return r

    def _save_cookies(self):
        self.session.cookies.save(ignore_discard=True, ignore_expires=True)

    # ---- ログイン ----

    def ensure_login(self):
        """保存済みCookieが生きていればそのまま使い、切れていればログインし直す。"""
        r = self._request("GET", "/mypage/top")
        if "ログアウト" in r.text:
            return "cookie"
        self.login()
        return "login"

    def login(self):
        """ログインフォームをPOSTし、SSOリダイレクトを辿って認証を完成させる。

        POST成功時の応答は kessai.keibabook.co.jp/mypage へのJSリダイレクトページで、
        これを踏まないと会員データ（前半3F等）が解放されない。
        """
        if not self.login_id or not self.password:
            raise LoginError("KEIBABOOK_LOGIN_ID / KEIBABOOK_PASSWORD が未設定です (.env を確認)")

        html = self._request("GET", "/login/login").text
        m = re.search(r'name="_token" value="([^"]+)"', html)
        if not m:
            raise LoginError("ログインページから _token を取得できませんでした（ページ構造変更の可能性）")

        payload = {
            "_token": m.group(1),
            "referer": "",
            "service": "keibabook",
            "login_id": self.login_id,
            "pswd": self.password,
            "autologin": "1",
            "submitbutton": "ログインする",
        }
        r = self._request("POST", "/login/login", data=payload)
        # 失敗時はログインフォームが再表示される（パスワード入力欄が残っている）
        if 'name="pswd"' in r.text and "ログインする" in r.text:
            raise LoginError("ログインに失敗しました。ID/パスワードを確認してください")

        # SSOステップ: 応答中のリダイレクト先（kessaiドメインのマイページ）を踏む
        m = re.search(r"window\.location\.href\s*=\s*'(https?://[^']+)'", r.text)
        sso_url = m.group(1) if m else "https://kessai.keibabook.co.jp/mypage/index"
        r = self._request("GET", sso_url)
        if "ログアウト" not in r.text:
            raise LoginError("SSO後もログイン状態になりません（会員契約の状態を確認してください）")
        self._save_cookies()
        return True

    # ---- ページ取得（キャッシュ付き） ----

    def _cache_file(self, path):
        return self.cache_dir / (path.strip("/").replace("/", "_") + ".html")

    def get(self, path, cache=True, refresh=False):
        """パスを取得してHTML文字列を返す。cache=Trueなら data/cache/ を使う。"""
        f = self._cache_file(path)
        if cache and not refresh and f.exists():
            return f.read_text(encoding="utf-8")
        html = self._request("GET", path).text
        if cache:
            f.write_text(html, encoding="utf-8")
        self._save_cookies()
        return html

    def drop_cache(self, path):
        f = self._cache_file(path)
        if f.exists():
            f.unlink()

    # ---- URLヘルパ ----

    @staticmethod
    def nittei_path(yyyymmdd):
        return f"/chihou/nittei/{yyyymmdd}"

    @staticmethod
    def seiseki_path(race_id):
        return f"/chihou/seiseki/{race_id}"

    @staticmethod
    def syutuba_path(race_id):
        return f"/chihou/syutuba/{race_id}"

    @staticmethod
    def cyokyo_path(race_id):
        return f"/chihou/cyokyo/3/0/{race_id}"

    @staticmethod
    def nouryoku_path(race_id):
        return f"/chihou/nouryoku_html/{race_id}"

    @staticmethod
    def danwa_path(race_id):
        return f"/chihou/danwa/1/{race_id}"
