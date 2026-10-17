# -*- coding: utf-8 -*-
"""2026-10-17 馬への措置・賞典停止の印・飛び日付・期間の文の戻し(cloud/penalties.py)の試験。通信なし。

  py -3.12 -m unittest tests.penalties_horse_measures_test -v

⛔文は作り物にしない= 成績 PDF(keiba.go.jp)の制裁欄の生の行を tests/fixtures/penalties_pdf_20261017.json に写した。
  名古屋 10/14・10/15、園田 10/15、盛岡 10/12、高知 10/11、帯広 10/11。
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "cloud"))
import penalties as pen                                            # noqa: E402

FX = json.load(open(os.path.join(HERE, "fixtures", "penalties_pdf_20261017.json"), encoding="utf-8"))


def read_day(track, race_date):
    for d in FX["days"]:
        if d["track"] == track and d["race_date"] == race_date:
            r = d["roster"]
            names = {"jockey": {pen.tight(x) for x in r["jockey"]},
                     "trainer": {pen.tight(x) for x in r["trainer"]},
                     "horse": {(a, b): pen.tight(c) for a, b, c in r["horse"]}}
            segs = [(no, text) for no, text in d["segments"]]
            return pen.read_penalties(track, race_date, segs, names, d["source_url"], "a" * 64)
    raise KeyError((track, race_date))


def pick(rows, person_kind, name):
    got = [r for r in rows if r["person_kind"] == person_kind and r["person_name"] == name]
    assert len(got) == 1, (person_kind, name, [(r["person_kind"], r["person_name"]) for r in rows])
    return got[0]


class FixtureShapeTest(unittest.TestCase):
    def test_days_and_rows(self):
        want = {("名古屋", "2026-10-14"): 4, ("名古屋", "2026-10-15"): 1, ("園田", "2026-10-15"): 5,
                ("盛岡", "2026-10-12"): 3, ("高知", "2026-10-11"): 2, ("帯広ば", "2026-10-11"): 1}
        for (track, day), n in want.items():
            rows, _stats = read_day(track, day)
            self.assertEqual(len(rows), n, (track, day, [(r["person_kind"], r["person_name"]) for r in rows]))
            for r in rows:
                self.assertEqual(r["parser_version"], pen.PARSER_VERSION)
                self.assertIsInstance(r["prize_suspended"], bool)
                if r["suspension_from"] and r["suspension_through"]:
                    self.assertLessEqual(r["suspension_from"], r["suspension_through"])

    def test_detail_tail_has_no_page_head(self):
        # 頁の頭(開催回の見出し「2026年度第14回…第2日目10月14日(水曜日)」)が detail の末尾に付かない
        want_tail = {("名古屋", 3): "令和8年11月3日まで出走できない。", ("名古屋", 7): "令和8年11月3日まで出走できない。",
                     ("名古屋", 10): "令和8年11月3日まで出走できない。", ("帯広ば", 10): "能力再検査を指示された。",
                     ("園田", 4): "調教再検査となった。"}
        for d in FX["days"]:
            rows, _ = read_day(d["track"], d["race_date"])
            for r in rows:
                self.assertNotIn("年度第", r["detail"], r["detail"])
                self.assertNotIn("曜日)", r["detail"], r["detail"])
                # 「。」か、期間・理由の括弧書き「)」で終わる(⛔括弧書きの末尾は消さない)
                self.assertTrue(r["detail"].endswith(("。", ")")), r["detail"])
                tail = want_tail.get((d["track"], r["race_no"]))
                if tail and r["person_kind"] == "horse":
                    self.assertTrue(r["detail"].endswith(tail), r["detail"])
        # 園田の括弧書きの期間は末尾に残る
        rows, _ = read_day("園田", "2026-10-15")
        self.assertTrue(pick(rows, "horse", "チョウカンセイ")["detail"].endswith("30日(令和8年10月16日~11月14日)"))

    def test_doubled_page_head_is_dropped(self):
        # 「競競走走成成績績表表2026/10/1509:30作成」(太字で字が 2 重)は頁の飾り
        for d in FX["days"]:
            for _no, text in d["segments"]:
                for block in pen.penalty_blocks(text):
                    self.assertNotIn("作成", block, (d["track"], d["race_date"]))


class NagoyaTest(unittest.TestCase):
    def test_time_over_and_epistaxis_before_umaban(self):
        rows, _ = read_day("名古屋", "2026-10-14")
        want = {"アルティーノ": (3, "タイムオーバー"), "グラスベリー": (6, "馬体故障による競走中止"),
                "ユイノチョウシンキ": (7, "タイムオーバー"), "ウィウィルウィン": (10, "鼻出血")}
        for name, (race_no, cause) in want.items():
            r = pick(rows, "horse", name)
            self.assertEqual(r["race_no"], race_no)
            self.assertEqual(r["horse_name"], name)
            self.assertEqual(r["kind"], "出走停止")
            self.assertEqual(r["cause"], cause)
            self.assertIsNone(r["suspension_from"])            # 「11月3日まで」= 終わりだけ書いてある
            self.assertEqual(r["suspension_through"], "2026-11-03")
            self.assertIsNone(r["suspension_days"])
            self.assertFalse(r["prize_suspended"])

    def test_scattered_days(self):
        rows, _ = read_day("名古屋", "2026-10-15")
        r = pick(rows, "jockey", "望月洵輝")
        self.assertEqual(r["kind"], "騎乗停止")
        self.assertEqual(r["suspension_days"], ["2026-10-19", "2026-10-21", "2026-10-22", "2026-10-23"])
        self.assertEqual((r["suspension_from"], r["suspension_through"]), ("2026-10-19", "2026-10-23"))
        self.assertIsNone(r["cause"])


class SonodaTest(unittest.TestCase):
    def setUp(self):
        self.rows, self.stats = read_day("園田", "2026-10-15")

    def test_period_after_the_sentence_goes_back(self):
        for name in ("小牧太", "南部楓馬"):
            r = pick(self.rows, "jockey", name)
            self.assertEqual(r["kind"], "騎乗停止")
            self.assertEqual(r["suspension_days"], ["2026-10-21", "2026-10-22"])
            self.assertTrue(r["detail"].endswith("2日(令和8年10月21日、22日)"), r["detail"])

    def test_trainer_sentence_no_longer_starts_with_the_jockey_period(self):
        r = pick(self.rows, "trainer", "田中道夫")
        self.assertTrue(r["detail"].startswith("1番チョウカンセイ号の調教師田中道夫"), r["detail"])
        self.assertEqual(r["kind"], "戒告")
        self.assertTrue(r["prize_suspended"])
        self.assertEqual(r["suspension_days"], ["2026-10-15", "2026-10-16"])

    def test_horse_rows(self):
        r = pick(self.rows, "horse", "チョウカンセイ")
        self.assertEqual(r["kind"], "出走停止")
        self.assertEqual((r["suspension_from"], r["suspension_through"]), ("2026-10-16", "2026-11-14"))
        self.assertIsNone(r["cause"])                          # 理由の語が原文に無い= 推測しない
        r = pick(self.rows, "horse", "シバノパージャン")
        self.assertEqual(r["kind"], "再検査")
        self.assertEqual(r["cause"], "枠内駐立不良")
        self.assertIsNone(r["suspension_through"])


class MoriokaTest(unittest.TestCase):
    def test_prize_and_horse(self):
        rows, _ = read_day("盛岡", "2026-10-12")
        r = pick(rows, "trainer", "佐々木由則")
        self.assertEqual(r["kind"], "戒告")
        self.assertTrue(r["prize_suspended"])
        self.assertEqual((r["suspension_from"], r["suspension_through"]), ("2026-10-12", "2026-10-13"))
        r = pick(rows, "horse", "ディオニス")
        self.assertEqual(r["kind"], "出走停止")
        self.assertEqual(r["cause"], "発走調教不十分")
        self.assertEqual((r["suspension_from"], r["suspension_through"]), ("2026-10-13", "2026-11-11"))
        r = pick(rows, "jockey", "望月洵輝")
        self.assertFalse(r["prize_suspended"])


class KochiTest(unittest.TestCase):
    def test_prize_period_in_the_next_sentence(self):
        rows, _ = read_day("高知", "2026-10-11")
        r = pick(rows, "trainer", "田中守")
        self.assertEqual(r["kind"], "戒告")
        self.assertTrue(r["prize_suspended"])
        self.assertEqual((r["suspension_from"], r["suspension_through"]), ("2026-10-11", "2026-10-17"))
        r = pick(rows, "horse", "アカリボーイ")
        self.assertEqual(r["kind"], "出走停止")
        self.assertEqual(r["cause"], "発走調教不十分")
        self.assertEqual((r["suspension_from"], r["suspension_through"]), (None, "2026-11-10"))


class ObihiroTest(unittest.TestCase):
    def test_ability_recheck(self):
        rows, _ = read_day("帯広ば", "2026-10-11")
        r = pick(rows, "horse", "アソノリキ")
        self.assertEqual(r["kind"], "再検査")
        self.assertEqual(r["race_no"], 10)
        self.assertIsNone(r["cause"])
        self.assertIsNone(r["suspension_through"])


class PeriodsTest(unittest.TestCase):
    def test_shapes(self):
        p = pen.periods
        self.assertEqual(p("令和8年8月21日から令和8年9月7日までの実効2日間", "2026-08-21"),
                         ("2026-08-21", "2026-09-07", None))
        self.assertEqual(p("令和8年9月1日、2日の2日間騎乗停止した。", "2026-08-30"),
                         ("2026-09-01", "2026-09-02", ["2026-09-01", "2026-09-02"]))
        # 年の書いてない日は開催日の年。12 月の開催の 1 月は翌年
        self.assertEqual(p("2日間(12月30日、1月2日)騎乗を停止", "2026-12-27"),
                         ("2026-12-30", "2027-01-02", ["2026-12-30", "2027-01-02"]))
        self.assertEqual(p("令和8年13月45日から令和8年99月1日まで", "2026-08-21"), (None, None, None))
        self.assertEqual(p("戒告された。", "2026-08-21"), (None, None, None))

    def test_id_includes_person_kind(self):
        rows, _ = read_day("名古屋", "2026-10-14")
        self.assertEqual(len({r["penalty_id"] for r in rows}), len(rows))


if __name__ == "__main__":
    unittest.main()


class RideHorseTest(unittest.TestCase):
    """2026-10-17 本文に馬番が無い人の行は、名簿(nar_runs)の側からその人の馬を 1 頭だけのときに入れる。"""
    def test_roster_ride(self):
        class C:
            def get(self, path):
                return [{"jockey": "望月洵", "trainer": "藤ケ崎", "race_no": 1, "runner_number": 3, "horse_name": "スラッシュコード"},
                        {"jockey": "加藤聡", "trainer": "藤ケ崎", "race_no": 1, "runner_number": 5, "horse_name": "ローレルアイビー"}]
        names = pen.roster(C(), "名古屋", "2026-10-15")
        self.assertEqual(pen.ride_horse(names, "jockey", 1, "望月洵"), "スラッシュコード")
        self.assertIsNone(pen.ride_horse(names, "trainer", 1, "藤ケ崎"))   # 2 頭= 決めない
        self.assertIsNone(pen.ride_horse(names, "jockey", 2, "望月洵"))
