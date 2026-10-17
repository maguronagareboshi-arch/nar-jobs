# -*- coding: utf-8 -*-
"""制裁の X 用画像(cloud/penalty_image.py)の文字の作り方。通信なし。

  py -3.12 -m unittest tests.test_penalty_image -v

行は本物(fixtures/penalty_rows_v3.json= nar_penalties の 2026-10-11〜15 の 16 行)。⛔作り物の文は使わない。
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "cloud"))
import penalty_image as pi                                         # noqa: E402

with open(os.path.join(HERE, "fixtures", "penalty_rows_v3.json"), encoding="utf-8") as f:
    ROWS = json.load(f)


def row(name, kind):
    return next(r for r in ROWS if r["person_name"] == name and r["kind"] == kind
                and (name != "望月洵輝" or r["track"] == "名古屋"))


class FullName(unittest.TestCase):
    def test_names(self):
        self.assertEqual(pi.full_name(row("望月洵輝", "騎乗停止")), "望月洵輝")      # ◯◯騎手は
        self.assertEqual(pi.full_name(row("小牧太", "騎乗停止")), "小牧太")          # 騎手◯◯は
        self.assertEqual(pi.full_name(row("南部楓馬", "騎乗停止")), "南部楓馬")
        self.assertEqual(pi.full_name(row("田中道夫", "戒告")), "田中道夫")          # 調教師◯◯は
        self.assertEqual(pi.full_name(row("田中守", "戒告")), "田中守")
        self.assertEqual(pi.full_name(row("佐々木由則", "戒告")), "佐々木由則")      # 「は」なし= person_name
        self.assertEqual(pi.full_name(row("チョウカンセイ", "出走停止")), "チョウカンセイ")

    def test_moriota_no_ha(self):
        r = next(r for r in ROWS if r["person_name"] == "望月洵輝" and r["track"] == "盛岡")
        self.assertEqual(pi.full_name(r), "望月洵輝")


class KindLabel(unittest.TestCase):
    def test_days(self):
        self.assertEqual(pi.kind_label(row("望月洵輝", "騎乗停止")), "騎乗停止 4日間")    # suspension_days の数
        self.assertEqual(pi.kind_label(row("小牧太", "騎乗停止")), "騎乗停止 2日間")
        self.assertEqual(pi.kind_label(row("ディオニス", "出走停止")), "出走停止 30日間")  # N日間
        self.assertEqual(pi.kind_label(row("アカリボーイ", "出走停止")), "出走停止 30日間")

    def test_no_days_written(self):
        self.assertEqual(pi.kind_label(row("チョウカンセイ", "出走停止")), "出走停止")   # 「30日(」は日間でない
        self.assertEqual(pi.kind_label(row("アルティーノ", "出走停止")), "出走停止")
        self.assertEqual(pi.kind_label(row("田中道夫", "戒告")), "戒告")                 # 賞典停止の日数は付けない
        self.assertEqual(pi.kind_label(row("シバノパージャン", "再検査")), "再検査")


class Period(unittest.TestCase):
    def test_period(self):
        self.assertEqual(pi.period_text(row("望月洵輝", "騎乗停止")), "停止 10/19・10/21・10/22・10/23")
        self.assertEqual(pi.period_text(row("ウィウィルウィン", "出走停止")), "11/3 まで出走できない")
        self.assertEqual(pi.period_text(row("田中道夫", "戒告")), "賞典停止 10/15・10/16")
        self.assertEqual(pi.period_text(row("佐々木由則", "戒告")), "賞典停止 10/12〜10/13")
        self.assertEqual(pi.period_text(row("ディオニス", "出走停止")), "停止 10/13〜11/11")
        self.assertIsNone(pi.period_text(row("シバノパージャン", "再検査")))

    def test_when_and_cause(self):
        t = pi.lines(row("望月洵輝", "騎乗停止"))
        self.assertEqual(t["when"], "2026年10月15日(木) 名古屋 1R")                     # horse_name なし
        self.assertEqual(pi.lines(row("小牧太", "騎乗停止"))["when"], "2026年10月15日(木) 園田 3R・オーヴァルウィン")
        self.assertEqual(pi.lines(row("アソノリキ", "再検査"))["when"], "2026年10月11日(日) 帯広 10R")
        self.assertEqual(pi.lines(row("ウィウィルウィン", "出走停止"))["cause"], "理由 鼻出血")
        self.assertEqual(pi.lines(row("アソノリキ", "再検査"))["role"], "馬")

    def test_months(self):
        self.assertEqual(list(pi.months("2026-01-20", "2026-03-05")),
                         [("2026-01-20", "2026-01-31"), ("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-05")])


if __name__ == "__main__":
    unittest.main()
