# -*- coding: utf-8 -*-
"""ob_alias の切れた生産者名(案 A・10/3)の単体テスト。py -3.12 -m unittest pipeline/stats_local/test_ob_alias.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ob_alias  # noqa: E402


class TruncTest(unittest.TestCase):
    def test_ten_char_correct_name_not_target(self):
        self.assertFalse(ob_alias.is_trunc("インターナショナル牧", "インターナショナル牧"))
        m, s = ob_alias.trunc_map([("インターナショナル牧", "インターナショナル牧")])
        self.assertEqual(m, {})

    def test_ten_char_cut(self):
        self.assertTrue(ob_alias.is_trunc("ダーレー・ジャパン・", "ダーレー・ジャパン・ファーム"))

    def test_other_lengths_not_target(self):
        self.assertFalse(ob_alias.is_trunc("ダーレー・ジャパ", "ダーレー・ジャパン・ファーム"))  # 8 字
        self.assertFalse(ob_alias.is_trunc("ABCDEFGHIJKL", "ABCDEFGHIJKLMN"))  # 12 字

    def test_not_prefix_not_target(self):
        self.assertFalse(ob_alias.is_trunc("ダーレー・ジャパン・", "社台ファーム有限会社ほげ"))

    def test_spaces_removed(self):
        m, _ = ob_alias.trunc_map([("Aaron&Mari", "Aaron & Marie Jones LLC")])
        self.assertEqual(m, {"Aaron&Mari": "Aaron&MarieJonesLLC"})
        raw = "ＡｎｎＭｕｄｇｅＢａｃｋｅｒ／Ｓｍｉ"  # 18 字(20 字切れ)
        m, _ = ob_alias.trunc_map([(raw, "Ann Mudge Backer/Smitten Farm")])
        self.assertEqual(m, {raw: "AnnMudgeBacker/SmittenFarm"})

    def test_split_excluded(self):
        pairs = [("Arrowfield", "Arrowfield Group Pty Ltd"), ("Arrowfield", "Arrowfield Pastoral Pty Ltd")]
        m, s = ob_alias.trunc_map(pairs)
        self.assertEqual(m, {})
        self.assertEqual(s, ["Arrowfield"])

    def test_build_canonical_is_full_and_redirect(self):
        rows = [("breeder", "Aaron&Mari", 5, 3)]
        trunc = {"Aaron&Mari": "Aaron&MarieJonesLLC"}
        old, _ = ob_alias.build(rows, [])
        new, _ = ob_alias.build(rows, [], trunc)
        self.assertIn(("breeder", "Aaron&Mari", "Aaron&MarieJonesLLC"), new)
        self.assertIn(("breeder", "Aaron&MarieJonesLLC", "Aaron&MarieJonesLLC"), new)
        self.assertEqual(ob_alias.redirects(old, new), [])  # 旧代表 Aaron&Mari は alias に既にある

    def test_redirect_for_fullwidth_old_canonical(self):
        raw = "ＡｎｎＭｕｄｇｅＢａｃｋｅｒ／Ｓｍｉ"
        rows = [("breeder", raw, 2, 1)]
        old, _ = ob_alias.build(rows, [])
        new, _ = ob_alias.build(rows, [], {raw: "AnnMudgeBacker/SmittenFarm"})
        self.assertEqual(ob_alias.redirects(old, new),
                         [("breeder", "AnnMudgeBacker/Smi", "AnnMudgeBacker/SmittenFarm")])

    def test_existing_full_page_merges(self):
        rows = [("breeder", "BloomingFa", 10, 5), ("breeder", "BloomingFarm", 3, 1)]
        new, _ = ob_alias.build(rows, [], {"BloomingFa": "BloomingFarm"})
        self.assertEqual({c for _, _, c in new}, {"BloomingFarm"})


if __name__ == "__main__":
    unittest.main()
