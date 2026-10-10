# -*- coding: utf-8 -*-
"""2026-10-03 監査の直し: 購買者名の実体参照・高知の厩舎の話のレース番号ずれ。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))
import sale_results  # noqa: E402
import kochi_comments  # noqa: E402


class SaleTxt(unittest.TestCase):
    def test_unescape(self):
        self.assertEqual(sale_results._txt("K&#039;S International"), "K'S International")
        self.assertEqual(sale_results._txt("<td>Mick&amp;Breeding</td>"), "Mick&Breeding")


class KochiRaceNo(unittest.TestCase):
    def _page(self, body):
        return f'<div id="the-content"><p>{body}</p></div>'

    def test_body_race_no(self):
        page = self._page("2026年9月26日　第6競走<br>2番　ブロードグリン　新庄騎手<br>よく走った")
        self.assertEqual(kochi_comments.race_no_of(page, 7), 6)

    def test_zenkaku_digit(self):
        self.assertEqual(kochi_comments.race_no_of(self._page("第１１競走"), 3), 11)

    def test_fallback_url_no(self):
        page = self._page("2番　ブロードグリン　新庄騎手<br>よく走った")
        self.assertEqual(kochi_comments.race_no_of(page, 7), 7)
        self.assertEqual(kochi_comments.race_no_of("<html></html>", 5), 5)


class KochiMatchRaces(unittest.TestCase):
    """2026-09-26: 6R の記事が 7R の URL に載り、本文に「第N競走」が無い= 出走馬の組で載せ先を決める。"""
    BY = {6: {2: "ブロードグリン", 3: "サンブル"}, 7: {2: "クラウンクーロン", 3: "ツウキンカイソク"}}

    def _p(self, *pairs):
        return [{"umaban": u, "horse_name": n} for u, n in pairs]

    def test_all_match_other_race(self):
        self.assertEqual(kochi_comments.matching_races(self._p((2, "ブロードグリン"), (3, "サンブル")), self.BY), [6])

    def test_partial_match_is_none(self):
        self.assertEqual(kochi_comments.matching_races(self._p((2, "ブロードグリン"), (3, "ツウキンカイソク")), self.BY), [])

    def test_empty(self):
        self.assertEqual(kochi_comments.matching_races([], self.BY), [])


if __name__ == "__main__":
    unittest.main()
