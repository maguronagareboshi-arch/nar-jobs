# -*- coding: utf-8 -*-
"""§186 日次の取得で公式が HTTP 404 を返したら「開催なし・投入なし rc 0」(ZIP でない応答と同じ)。通信ゼロ。

  py -3.12 -m unittest tests.test_refresh_404
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))

import refresh  # noqa: E402


class FakeHTTPError(Exception):
    """requests.HTTPError の形だけ(応答の status_code を持つ)"""

    def __init__(self, code):
        super().__init__("%d Client Error" % code)
        self.response = type("R", (), {"status_code": code})()


class Daily404(unittest.TestCase):
    def _main(self, code):
        def boom(scope, **kw):
            raise FakeHTTPError(code)
        env = {"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x"}
        with mock.patch.object(refresh, "fetch_doc", boom), mock.patch.dict(os.environ, env), \
                mock.patch.object(sys, "argv", ["refresh.py", "--mode", "daily"]):
            return refresh.main()

    def test_daily_404_is_no_race_day(self):
        # 2026-09-10 21:05・09-11 17:45 の手押し= daily が 404 → 取得失敗 rc=2 だった
        self.assertEqual(self._main(404), 0)
        # 404 以外(500 など)は今までどおり取得失敗= rc 2(次回に任せる)
        self.assertEqual(self._main(500), 2)
        self.assertTrue(refresh.not_found(FakeHTTPError(404)))
        self.assertFalse(refresh.not_found(ValueError("not a zip")))


if __name__ == "__main__":
    unittest.main()
