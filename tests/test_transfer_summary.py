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


def _h(lic, area, name="馬"):
    return {"license_no": lic, "area": area, "horse_name": name}


class TestRosterMoves(unittest.TestCase):
    PREV = {"1": _h("A", "船橋", "イチ"), "2": _h("A", "船橋", "ニ"), "3": _h("B", "北海道", "サン"),
            "4": _h("C", "高知", "ヨン")}

    def test_first_night_no_diff(self):
        self.assertEqual(T.diff_moves({}, {"1": _h("A", "船橋")}, "2026-10-01", {"A"}), [])

    def test_moved_new_gone(self):
        cur = {"1": _h("B", "北海道", "イチ"), "3": _h("B", "北海道", "サン"), "5": _h("B", "北海道", "ゴ"),
               "4": _h("C", "高知", "ヨン")}
        m = T.diff_moves(self.PREV, cur, "2026-10-01", {"A", "B", "C"})
        got = {r["lineage_code"]: (r["from_license"], r["to_license"], r["from_area"], r["to_area"]) for r in m}
        self.assertEqual(got, {"1": ("A", "B", "船橋", "北海道"),     # 別の免許番号に載った
                               "2": ("A", None, "船橋", None),        # 消えた
                               "5": (None, "B", None, "北海道")})     # 新しく載った
        self.assertTrue(all(r["seen_on"] == "2026-10-01" for r in m))

    def test_gone_only_for_fetched(self):
        # 取れなかった人(C)の馬は「消えた」にしない。一覧から居なくなった人(gone_licenses)は消えた
        cur = {"1": _h("A", "船橋"), "2": _h("A", "船橋"), "3": _h("B", "北海道")}
        self.assertEqual(T.diff_moves(self.PREV, cur, "d", {"A", "B"}), [])
        m = T.diff_moves(self.PREV, cur, "d", {"A", "B"}, {"C"})
        self.assertEqual([(r["lineage_code"], r["to_license"]) for r in m], [("4", None)])

    def test_idempotent(self):
        # 同じ夜の打ち直し= 今夜の名簿が前夜になるので差分は 0
        cur = {"1": _h("B", "北海道", "イチ"), "3": _h("B", "北海道", "サン")}
        self.assertEqual(T.diff_moves(cur, dict(cur), "d", {"B"}), [])


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
