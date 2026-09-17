# -*- coding: utf-8 -*-
"""§196b tools/nankan_recon.py の純関数(手元の下調べ道具・DB と通信に触らない)。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import nankan_recon as R  # noqa: E402


class T(unittest.TestCase):
    def test_grade_half_and_age(self):
        # 下半期 4 歳 B1 は 1800 以上(原文 L581〜L583)
        self.assertEqual(R.grade(1800, 4, "2026-09-14"), "B1")
        self.assertEqual(R.grade(1799, 4, "2026-09-14"), "B2")
        # 上半期 3 歳の C1・C2 は表が空欄= C3
        self.assertEqual(R.grade(600, 3, "2026-03-01"), "C3")
        self.assertEqual(R.grade(700, 3, "2026-03-01"), "B3")
        self.assertIsNone(R.grade(100, 2, "2026-09-01"))
        self.assertIsNone(R.grade(None, 4, "2026-09-01"))

    def test_race_classes(self):
        self.assertEqual(R.race_classes("オーガスト賞Ａ２二Ｂ１二選抜特別"), ["A2", "B1"])
        self.assertEqual(R.race_classes("Ｃ３五 六"), ["C3"])
        self.assertEqual(R.race_classes("３歳八 九"), [])

    def test_earned_table(self):
        tab, src = R.earned_table({"race_kind": "特別", "race_name": "播磨坂賞Ｂ３二選抜特別", "condition": "一般", "race_date": "2026-03-25"})
        self.assertEqual((tab, src), ((240, 96, 60, 36, 24), "ok"))     # 公式ページ「1着240P 2着96P…」と同じ
        tab, src = R.earned_table({"race_kind": "普通", "race_name": "３歳八 九", "condition": "３歳", "race_date": "2025-02-18"})
        self.assertEqual(tab[0], 220)                                    # 3 歳 普通(1〜6 月)
        tab, src = R.earned_table({"race_kind": "普通", "race_name": "３歳七 八", "condition": "３歳", "race_date": "2025-07-15"})
        self.assertEqual(tab[3], 24)                                     # 3 歳 普通(7〜12 月)の 4 着
        tab, src = R.earned_table({"race_kind": "重賞", "race_name": "第６２回 東京記念３上オープン重賞", "condition": "3歳以上", "race_date": "2025-09-17"})
        self.assertEqual((tab, src), (None, "重賞の格が名前に無い"))      # ⛔ S の格は決めない
        tab, src = R.earned_table({"race_kind": "重賞", "race_name": "第４９回 京浜盃JpnII３歳選定馬重賞", "condition": "３歳", "race_date": "2026-03-25"})
        self.assertEqual(tab[0], 1800)

    def test_parse_result(self):
        h = ("<p>発走時刻 20:50 播磨坂賞 Ｂ３(二) 選抜特別 詳細 サラブレッド系 一般 別定 （特別競走） 賞金 1着3,800,000円</p>"
             "<p>番組ポイント ポイント 1着240P 2着96P 3着60P 4着36P 5着24P</p>")
        r = R.parse_result(h)
        self.assertEqual(r["pts"], (240, 96, 60, 36, 24))
        self.assertEqual(r["kind"], "特別")
        self.assertEqual(r["classes"], ["B3"])

    def test_raceid_from_meetings(self):
        # 大井: 2026-03-23〜27 が年度内 19 回目、2026-04-13〜 が新年度 1 回目(馬ページのリンクと同じ形)
        races = {}
        blocks = [["2026-03-%02d" % d for d in range(23, 28)], ["2026-04-%02d" % d for d in range(13, 18)]]
        for i in range(18):
            blocks.insert(0, ["2025-%02d-%02d" % (4 + i // 2, 1 + (i % 2) * 15)])
        for b in blocks:
            for d in b:
                races[("大井", d, 12)] = {"cancelled": ""}
        mtg, idx = R.meetings(races)
        self.assertEqual(R.raceid("大井", "2026-03-25", 12, idx), "2026032520190312")
        self.assertEqual(R.raceid("大井", "2026-04-14", 10, idx), "2026041420010210")
        self.assertIsNone(R.raceid("大井", "2026-05-01", 1, idx))


if __name__ == "__main__":
    unittest.main()
