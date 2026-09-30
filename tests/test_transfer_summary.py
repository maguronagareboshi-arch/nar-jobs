# -*- coding: utf-8 -*-
"""§移籍まとめ D1・D2(2026-09-30)の単体テスト(通信・DB なし)。
  py -3.12 -X utf8 -m unittest tests.test_transfer_summary
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))

import horse_changes as hc   # noqa: E402
import trainer_roster as T   # noqa: E402

MARK = """<main><h4 class="odd_title">田 中 淳 司</h4> <table class="trainerinfo"> <tr> <td class="intablelabel">所属</td> <td>北海道</td> </tr></table>
<div class="databasesearch_header TrainerMark"> <ul class="ul_with_next"> <li class="li_with_next"> <span>現役管理馬一覧</span> </li>
<li class="li_with_next"> </li> <li class="li_with_next"> <a href="/KeibaWeb/DataRoom/TrainerMark?k_pageNum=1&amp;k_trainerLicenseNo=11309"> 次の50頭→ </a> </li> </ul> </div>
<table class="databasesearch_table TrainerMark"> <thead> <tr> <th>No.</th> <th>馬名</th> </tr> </thead> <tbody>
<tr> <td> 1</td> <td><b> <a href="/KeibaWeb/DataRoom/RaceHorseInfo?k_lineageLoginCode=30022403266&amp;k_activeCode=1" > アラッキーフェイス </a> </b></td> <td><span > セン7</span> </td> <td>2019</td> <td>キズナ</td> <td>レンデフルール</td> </tr>
<tr> <td> 2</td> <td> <a href="/KeibaWeb/DataRoom/RaceHorseInfo?k_lineageLoginCode=40041407996&amp;k_activeCode=1" > レイワエポック </a> </td> <td><span class="sex red" > 牝4</span> </td> <td>2022</td> <td>Mendelssohn</td> <td>Birdie Gold</td> </tr>
</tbody> </table>"""

LIST = """<li>検索結果:<span>612</span>件 </li> <tbody> <tr> <td> 1 </td> <td> <a href="/KeibaWeb/DataRoom/TrainerMark?k_trainerLicenseNo=40255" target="_blank"> 相　澤　　　　郁 </a> </td> <td> 現役 </td> <td> JRA </td> </tr>
<tr> <td> 2 </td> <td> <a href="/KeibaWeb/DataRoom/TrainerMark?k_trainerLicenseNo=11088" target="_blank"> 阿　井　　正　雄 </a> </td> <td> 現役 </td> <td> 船橋 </td> </tr>"""


class TestRoster(unittest.TestCase):
    def test_mark(self):
        raw, area, hs, nxt = T.parse_mark(MARK)
        self.assertEqual(T.official_name(raw), "田中淳司")
        self.assertEqual(area, "北海道")
        self.assertEqual([h["lineage_code"] for h in hs], ["30022403266", "40041407996"])
        self.assertEqual(hs[1], {"lineage_code": "40041407996", "horse_name": "レイワエポック", "sex_age": "牝4",
                                 "birth_year": 2022, "sire": "Mendelssohn", "dam": "Birdie Gold"})
        self.assertTrue(nxt.endswith("TrainerMark?k_pageNum=1&k_trainerLicenseNo=11309"))

    def test_mark_last_page(self):
        self.assertIsNone(T.parse_mark(MARK.replace("次の50頭→", ""))[3])

    def test_list(self):
        rows = T.parse_list(LIST)
        self.assertEqual([(r[0], r[3]) for r in rows], [("40255", "JRA"), ("11088", "船橋")])
        self.assertEqual(T.list_total(LIST), 612)

    def test_short_guess(self):
        self.assertEqual(T.short_guess("阿　井　　正　雄"), "阿井正")
        self.assertEqual(T.short_guess("相　澤　　　　郁"), "相澤郁")
        self.assertEqual(T.short_guess("佐　々　木　　大　輔"), "佐々大")
        self.assertIsNone(T.short_guess("名前だけ"))


def _h(lic, area, name="馬", ms=None):
    return {"license_no": lic, "area": area, "horse_name": name, "missing_since": ms}


def _got(m):
    return {r["lineage_code"]: (r["from_license"], r["to_license"], r["from_area"], r["to_area"]) for r in m}


class TestRosterMoves(unittest.TestCase):
    PREV = {"1": _h("A", "船橋", "イチ"), "2": _h("A", "船橋", "ニ"), "3": _h("B", "北海道", "サン"),
            "4": _h("C", "高知", "ヨン"), "6": _h("A", "船橋", "ロク", "2026-09-30")}
    D = "2026-10-01"

    def test_first_night_no_diff(self):
        self.assertEqual(T.diff_moves({}, {"1": _h("A", "船橋")}, self.D, {"A"}), ([], [], []))

    def test_moved_new_and_two_night_gone(self):
        cur = {"1": _h("B", "北海道", "イチ"), "3": _h("B", "北海道", "サン"), "5": _h("B", "北海道", "ゴ"),
               "4": _h("C", "高知", "ヨン")}
        m, miss, gone = T.diff_moves(self.PREV, cur, self.D, {"A", "B", "C"})
        self.assertEqual(_got(m), {"1": ("A", "B", "船橋", "北海道"),     # 別の免許番号に載った
                                   "5": (None, "B", None, "北海道"),      # 新しく載った
                                   "6": ("A", None, "船橋", None)})       # 2 夜続けて居ない= 消えた
        self.assertEqual(miss, ["2"])                                     # 1 夜目は差分なし・印だけ
        self.assertEqual(gone, ["6"])
        self.assertTrue(all(r["seen_on"] == self.D for r in m))

    def test_failed_trainer_carried_over(self):
        # A が取れなかった夜: A の名簿の馬(2・6)は持ち越し= 欠けにも消えたにもしない
        cur = {"3": _h("B", "北海道")}
        self.assertEqual(T.diff_moves(self.PREV, cur, self.D, {"B", "C"}), ([], ["4"], []))

    def test_move_from_failed_trainer_recorded(self):
        # A が取れなかった夜でも、取れた B の名簿に A の馬が載ったら移籍(from は前夜の行)
        cur = {"1": _h("B", "北海道", "イチ"), "3": _h("B", "北海道")}
        m, miss, gone = T.diff_moves(self.PREV, cur, self.D, {"B", "C"})
        self.assertEqual(_got(m), {"1": ("A", "B", "船橋", "北海道")})
        self.assertEqual((miss, gone), (["4"], []))

    def test_gone_licenses(self):
        # 一覧から居なくなった人(C)の馬は取れた扱い= 1 夜目の欠けになる
        cur = {"1": _h("A", "船橋"), "2": _h("A", "船橋"), "3": _h("B", "北海道")}
        m, miss, gone = T.diff_moves(self.PREV, cur, self.D, {"A", "B"}, {"C"})
        self.assertEqual(miss, ["4"])
        self.assertEqual((_got(m), gone), ({"6": ("A", None, "船橋", None)}, ["6"]))

    def test_new_fills_from_recent(self):
        rec = T.last_known([
            {"lineage_code": "9", "from_license": "A", "to_license": None, "from_area": "船橋", "to_area": None,
             "seen_on": "2026-09-25"},
            {"lineage_code": "8", "from_license": None, "to_license": "B", "from_area": None, "to_area": "北海道",
             "seen_on": "2026-09-20"}])
        self.assertEqual(rec, {"9": ("A", "船橋"), "8": ("B", "北海道")})
        cur = {"9": _h("B", "北海道"), "8": _h("B", "北海道"), "3": _h("B", "北海道")}
        m, _, _ = T.diff_moves({"3": _h("B", "北海道")}, cur, self.D, {"B"}, recent=rec)
        self.assertEqual(_got(m), {"9": ("A", "B", "船橋", "北海道"),    # 直近に別の免許番号= from を埋める
                                   "8": (None, "B", None, "北海道")})    # 同じ免許番号の記録= 埋めない

    def test_idempotent(self):
        # 同じ夜の打ち直し= 今夜の名簿(1 夜目の欠けは missing_since= 今日)が前夜になるので差分は 0
        prev = {"1": _h("B", "北海道"), "2": _h("B", "北海道", ms=self.D)}
        self.assertEqual(T.diff_moves(prev, {"1": _h("B", "北海道")}, self.D, {"B"}), ([], [], []))

    def test_reappear_no_diff(self):
        # 1 夜欠けて同じ所に載り直した馬は差分なし(行は upsert で missing_since= null に戻る)
        prev = {"1": _h("B", "北海道", ms="2026-09-30")}
        self.assertEqual(T.diff_moves(prev, {"1": _h("B", "北海道")}, self.D, {"B"}), ([], [], []))


class TestJraIn(unittest.TestCase):
    def test_career_switch(self):
        self.assertIn(hc.CAREER_ON, hc.jra_in_sql(True))
        self.assertNotIn("jra_career_runs", hc.jra_in_sql(False))

    def test_insert_uses_same_conflict(self):
        self.assertTrue(hc.jra_in_insert(True).rstrip().endswith(f"on conflict {hc.CONFLICT} do nothing"))
        self.assertIn("'jra_in' as kind", hc.jra_in_sql(True))

    def test_transfer_in_skips_jra(self):
        # 中央から来た転入は jra_in に寄せる(2 重にしない)
        self.assertIn("p_area <> 'JRA'", hc.DETECT_SQL)

    def test_same_day_jra_not_before(self):
        # 同じ日は地方を先に並べる= 同じ日の中央の走を「前」と数えない
        self.assertIn("order by race_date, is_jra, race_no", hc.JRA_IN_SQL)


if __name__ == "__main__":
    unittest.main()
