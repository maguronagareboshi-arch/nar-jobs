# -*- coding: utf-8 -*-
"""§195c 大井の入口= 表 `nar_fetch_raw` の読み。⛔通信なし= 表の行を手で与える。

  py -3.12 -m unittest tests.test_ooi_raw_read -v

前は §195b の中継(OOI_FEED_BASE)を見ていた。§195c で取るのは Worker の役になったので、
ここで見るのは「置かれた行のどれを採るか」と「採った本文を今までどおり読めるか」の 2 つ。
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import health_org_ooi as ooi                                       # noqa: E402

NOW = dt.datetime(2026, 9, 17, 6, 0, tzinfo=dt.timezone.utc)

# 1 頁ぶんの最小の RSS(⛔原本は置かない= 形が分かる断片だけ・馬名は作り物)
FEED = """<rss><channel>
<item><title>第8回開催5日目(9/15)の出来事</title>
<link>https://example.test/news/1</link>
<pubDate>Tue, 15 Sep 2026 12:00:00 +0900</pubDate>
<content:encoded><![CDATA[<strong>≪出走取消≫</strong><br>
<strong>第7競走 8号馬 テストノハナ</strong><br>疾病(左前挫跖)<br>]]></content:encoded>
</item></channel></rss>"""


def row(key, *, status=200, body=FEED, ago_days=0.0):
    return {"key": key, "status": status, "body": body,
            "fetched_at": (NOW - dt.timedelta(days=ago_days)).isoformat()}


class FreshPages(unittest.TestCase):
    # 1) 採るのは status 200 かつ本文があり 3 日以内の頁だけ
    def test_only_fresh_200(self):
        pages, dropped = ooi.fresh_pages([
            row("paged=1"),
            row("paged=2", ago_days=2.9),
            row("paged=3", ago_days=3.1),                 # 古い
            row("paged=4", status=403, body=None),        # 取れていない
            row("paged=5", status=-1, body=None),         # 2MB 超の印
            row("paged=6", status=200, body=""),          # 本文が空
            row("paged=7", status=0, body=None),          # 通信が切れた
        ], now=NOW)
        self.assertEqual(sorted(pages), ["paged=1", "paged=2"])
        self.assertEqual(dropped, [
            "paged=3 3.1 日前(古い)", "paged=4 status=403", "paged=5 status=-1",
            "paged=6 status=200", "paged=7 status=0"])

    # 2) 時刻の書き方(Z・小数秒・tz なし・+09:00)を読める / 読めない時刻は捨てる
    def test_timestamp_forms(self):
        for stamp in ("2026-09-17T05:00:00Z", "2026-09-17T05:00:00.123456+00:00",
                      "2026-09-17T05:00:00", "2026-09-17T14:00:00+09:00"):
            got = {"key": "paged=1", "status": 200, "body": FEED, "fetched_at": stamp}
            pages, dropped = ooi.fresh_pages([got], now=NOW)
            self.assertEqual(list(pages), ["paged=1"], stamp)
            self.assertEqual(dropped, [], stamp)
        pages, dropped = ooi.fresh_pages([{"key": "paged=1", "status": 200, "body": FEED,
                                           "fetched_at": "きのう"}], now=NOW)
        self.assertEqual(pages, {})
        self.assertEqual(dropped, ["paged=1 取った時刻が読めない"])

    # 3) 空・鍵の無い行は黙って飛ばす(⛔落ちない)
    def test_junk_rows(self):
        self.assertEqual(ooi.fresh_pages(None, now=NOW), ({}, []))
        self.assertEqual(ooi.fresh_pages([None, {}, {"key": ""}], now=NOW), ({}, []))

    # 4) ⛔捨てた理由に置き場を書かない
    def test_no_url_in_reason(self):
        _, dropped = ooi.fresh_pages([row("paged=1", status=403, body=None)], now=NOW)
        self.assertEqual(dropped, ["paged=1 status=403"])
        for why in dropped:
            self.assertNotIn("http", why)
            self.assertNotIn("keiba", why)


class ListDocuments(unittest.TestCase):
    # 5) 表の行から今までどおり読める(⛔fetch は 1 回も呼ばれない)
    def test_reads_from_table(self):
        called = []
        got = ooi.list_documents(lambda u: called.append(u), "2026-09-01", "2026-09-30",
                                 rows=[row("paged=1")])
        self.assertEqual(called, [], "⛔先方へ行っている")
        self.assertEqual(len(got), 1)
        date, link, body = got[0]
        self.assertEqual(date, "2026-09-15")
        self.assertEqual(link, "https://example.test/news/1")
        parsed = ooi.parse(body)
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["status"], "出走取消")
        self.assertEqual(parsed["rows"][0]["detail"], "疾病(左前挫跖)")

    # 6) 1 頁も使えなければ例外= 便の段が赤くなる(⛔0 件で緑のままにしない)
    def test_raises_when_nothing_usable(self):
        for rows in ([], [row("paged=1", status=403, body=None)], [row("paged=1", ago_days=9)]):
            with self.assertRaises(RuntimeError) as ctx:
                ooi.list_documents(lambda u: None, "2026-09-01", "2026-09-30", rows=rows)
            self.assertIn("nar_fetch_raw", str(ctx.exception))

    # 7) 8 頁のうち一部だけ使えても、あるぶんは読む
    def test_partial(self):
        got = ooi.list_documents(lambda u: None, "2026-09-01", "2026-09-30",
                                 rows=[row("paged=1", status=403, body=None), row("paged=2")])
        self.assertEqual([d[0] for d in got], ["2026-09-15"])


class Contract(unittest.TestCase):
    # 8) ⛔§195b の中継は消えている・読み解きと名乗りは無傷
    def test_relay_gone_and_parser_untouched(self):
        for name in ("FEED", "FEED_BASE_DEFAULT", "feed_base", "feed_url", "_page"):
            self.assertFalse(hasattr(ooi, name), "§195b の %s が残っている" % name)
        self.assertEqual(ooi.RAW_TABLE, "nar_fetch_raw")
        self.assertEqual(ooi.RAW_FRESH_DAYS, 3)
        self.assertEqual(ooi.MAX_PAGES, 8)
        self.assertEqual(ooi.SOURCE_KIND, "ooi_official")
        self.assertEqual(ooi.PARSER_VERSION, "org-ooi-1.0")
        self.assertEqual(ooi.TRACK, "大井")

    # 9) 鍵が無ければ読みに行かない(⛔黙って空を返さない)
    def test_read_raw_needs_keys(self):
        saved = {k: os.environ.pop(k, None) for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")}
        try:
            with self.assertRaises(RuntimeError) as ctx:
                ooi.read_raw()
            self.assertIn("SUPABASE_URL", str(ctx.exception))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
