# -*- coding: utf-8 -*-
"""10/2 金沢・名古屋の能検の映像= 題の読み・既存日の付け直し(上書きしない・2 回目も残る)。⛔通信なし。
py -3.12 -m unittest tests.test_noken_kn_video -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import noken_public as nk                                          # noqa: E402

U = "https://www.youtube.com/watch?v="


class NagoyaTitle(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(nk.nagoya_title_dates("金シャチけいば情報(第7回能力審査)R7 0618")[0], "2025-06-18")
        self.assertEqual(nk.nagoya_title_dates("金シャチけいば情報(第18回能力審査)Ｒ6 11 14")[0], "2024-11-14")
        self.assertEqual(nk.nagoya_title_dates("金シャチけいば情報(第14回能力審査) R08 10 02")[0], "2026-10-02")
        self.assertEqual(nk.nagoya_title_dates("金シャチけいば情報(第7回能力審査)R4.6.10")[0], "2022-06-10")
        self.assertEqual(nk.nagoya_title_dates("金シャチけいば情報(第24回能力審査)R6 01 31"),
                         ("2024-01-31", "2025-01-31"))

    def test_fiscal_and_0425(self):
        items = [("5MWmuvKUYOA", "金シャチけいば情報(第24回能力審査)R6 01 31"),
                 ("VGD-Rzn-YMA", "金シャチけいば情報(第22回能力審査)Ｒ7 01 03"),
                 ("z0atXWei-dY", "金シャチけいば情報(第3回能力審査)R7 4 25"),
                 ("RLcVIGCgeoU", "金シャチ競馬情報(第3回能力審査)R6 4 25"),
                 ("ILLwlX7gioU", "金シャチけいば情報あすの展望R8 10 02")]
        vids, weak = nk.nagoya_from_titles(items)
        self.assertEqual(vids["2025-01-31"], U + "5MWmuvKUYOA")
        self.assertEqual(vids["2025-01-03"], U + "VGD-Rzn-YMA")     # 暦どおりが先
        self.assertEqual(vids["2025-04-25"], U + "z0atXWei-dY")
        self.assertNotIn("2026-10-02", vids)                         # 能力審査でない動画
        self.assertEqual(weak["2025-01-31"], "2024-01-31")


class FillVideos(unittest.TestCase):
    def test_fill_keep_and_again(self):
        days = [{"date": "2026-09-23", "src_id": "a", "video": U + "OLD"},
                {"date": "2026-09-07", "src_id": "b"}, {"date": "2026-08-22", "src_id": "c"}]
        vids = {"2026-09-23": U + "NEW", "2026-09-07": U + "X"}
        self.assertEqual(nk.fill_day_videos(days, vids), 1)
        self.assertEqual(days[0]["video"], U + "OLD")                 # 上書きしない
        self.assertEqual(days[1]["video"], U + "X")
        self.assertNotIn("video", days[2])
        again = nk.merge_days(days, [{"date": "2026-10-01", "src_id": "d"}], lambda d: d["src_id"])
        self.assertEqual(nk.fill_day_videos(again, {}), 0)             # 一覧が読めなくても消えない
        self.assertEqual([d.get("video") for d in again][1:3], [U + "OLD", U + "X"])

    def test_weak_skipped_when_calendar_day_exists(self):
        days = [{"date": "2025-01-31"}, {"date": "2024-01-31"}]
        self.assertEqual(nk.fill_day_videos(days, {"2025-01-31": U + "W"}, {"2025-01-31": "2024-01-31"}), 0)


if __name__ == "__main__":
    unittest.main()
