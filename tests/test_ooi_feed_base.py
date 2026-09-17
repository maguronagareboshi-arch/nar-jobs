# -*- coding: utf-8 -*-
"""§195b 大井の入口= 当サイトの中継(OOI_FEED_BASE)。⛔通信なし= URL の組み立てだけ見る。

  py -3.12 -m unittest tests.test_ooi_feed_base -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import health_org_ooi as ooi                                       # noqa: E402


class FeedBase(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("OOI_FEED_BASE", None)

    def tearDown(self):
        os.environ.pop("OOI_FEED_BASE", None)
        if self._saved is not None:
            os.environ["OOI_FEED_BASE"] = self._saved

    # 1) 既定は当サイトの中継(⛔先方を直に読まない= ランナーの IP は 403)
    def test_default_is_relay(self):
        self.assertEqual(ooi.FEED_BASE_DEFAULT, "https://nar.yukochi.com/feed/ooi")
        self.assertEqual(ooi.feed_base(), "https://nar.yukochi.com/feed/ooi")
        self.assertEqual(ooi.feed_url(1), "https://nar.yukochi.com/feed/ooi?paged=1")
        self.assertEqual(ooi.feed_url(8), "https://nar.yukochi.com/feed/ooi?paged=8")

    # 2) 環境変数で上書きできる(手元から先方を直に読むとき)
    def test_env_override(self):
        os.environ["OOI_FEED_BASE"] = "https://example.test/relay"
        self.assertEqual(ooi.feed_url(3), "https://example.test/relay?paged=3")
        # 根に query があれば & で継ぐ(先方の RSS をそのまま指せる)
        os.environ["OOI_FEED_BASE"] = "https://example.test/news/feed/?s=%E5%87%BA%E6%9D%A5%E4%BA%8B"
        self.assertEqual(ooi.feed_url(2),
                         "https://example.test/news/feed/?s=%E5%87%BA%E6%9D%A5%E4%BA%8B&paged=2")

    # 3) 空・空白だけの環境変数は「未設定」と同じ(⛔黙って空の URL を叩かない)
    def test_blank_env_falls_back(self):
        for blank in ("", "   ", "\t"):
            os.environ["OOI_FEED_BASE"] = blank
            self.assertEqual(ooi.feed_base(), ooi.FEED_BASE_DEFAULT)

    # 4) 引数で根を渡せる(テスト用・環境変数より強い)
    def test_base_argument_wins(self):
        os.environ["OOI_FEED_BASE"] = "https://example.test/env"
        self.assertEqual(ooi.feed_url(5, "https://example.test/arg"),
                         "https://example.test/arg?paged=5")

    # 5) 便が読むのは 1〜MAX_PAGES の 8 本だけ・すべて別の URL
    def test_eight_pages(self):
        self.assertEqual(ooi.MAX_PAGES, 8)
        urls = [ooi.feed_url(n) for n in range(1, ooi.MAX_PAGES + 1)]
        self.assertEqual(len(set(urls)), 8)
        for n, u in zip(range(1, 9), urls):
            self.assertTrue(u.endswith("?paged=%d" % n), u)

    # 6) 頁送りが本当に feed_url を通る(⛔昔の FEED 定数が残っていないこと)
    def test_list_documents_uses_feed_url(self):
        os.environ["OOI_FEED_BASE"] = "https://example.test/relay"
        seen = []

        def fetch(url):
            seen.append(url)
            return ""                       # 空= 頁は読めない。⛔通信しない

        ooi.list_documents(fetch, "2026-01-01", "2026-12-31")
        self.assertEqual(len(seen), 16, "8 頁 × 引き直し 1 回でない")
        self.assertEqual(sorted(set(seen)),
                         sorted("https://example.test/relay?paged=%d" % n for n in range(1, 9)))
        self.assertFalse(hasattr(ooi, "FEED"), "古い FEED 定数が残っている")

    # 7) ⛔名乗りも本文の読み方も変えていない(§110 の契約)
    def test_parser_untouched(self):
        self.assertEqual(ooi.SOURCE_KIND, "ooi_official")
        self.assertEqual(ooi.PARSER_VERSION, "org-ooi-1.0")
        self.assertEqual(ooi.TRACK, "大井")
        got = ooi.parse("≪出走取消≫<br>第7競走 8号馬 テストノハナ<br>疾病(左前挫跖)<br>")
        self.assertEqual(len(got["rows"]), 1)
        self.assertEqual(got["rows"][0]["status"], "出走取消")
        self.assertEqual(got["rows"][0]["detail"], "疾病(左前挫跖)")


if __name__ == "__main__":
    unittest.main()
