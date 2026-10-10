# -*- coding: utf-8 -*-
"""same_abbr_keep の本人判定(コードで決める・10/10)の単体テスト。py -3.12 -m unittest pipeline/stats_local/test_same_abbr_keep.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import same_abbr_keep as k  # noqa: E402

BY = {'加藤和宏': {'05610', '01077'}, '水野貴史': {'05002'}}
BIRTH = {'05610': '19531113', '01077': '19560304', '05002': '19700101'}


class OwnerCodeTest(unittest.TestCase):
    def test_same_name_two_codes_split_by_birth(self):
        self.assertEqual(k.owner_codes('加藤和宏', '1953-11-13', BY, BIRTH), {'05610'})
        self.assertEqual(k.owner_codes('加藤和宏', '1956-03-04', BY, BIRTH), {'01077'})

    def test_same_name_without_birth_has_no_code(self):
        self.assertEqual(k.owner_codes('加藤和宏', None, BY, BIRTH), set())
        self.assertEqual(k.owner_codes('加藤和宏', '1960-01-01', BY, BIRTH), set())

    def test_single_code_needs_no_birth(self):
        self.assertEqual(k.owner_codes('水野 貴史', None, BY, BIRTH), {'05002'})

    def test_no_owner(self):
        self.assertEqual(k.owner_codes(None, '1953-11-13', BY, BIRTH), set())


class JudgeTest(unittest.TestCase):
    def test_other_person_same_name_is_not_keep(self):
        codes = k.owner_codes('加藤和宏', '1953-11-13', BY, BIRTH)
        self.assertEqual(k.judge('01077', codes, True), '別人')
        self.assertEqual(k.judge('05610', codes, True), 'keep')

    def test_other_cases(self):
        self.assertEqual(k.judge(None, {'05610'}, True), 'KD無し')
        self.assertEqual(k.judge('05610', set(), False), '本人なし')
        self.assertEqual(k.judge('05610', set(), True), '本人コード無し')


class MultiOwnerTest(unittest.TestCase):
    """村上慎= 名簿に地方 2 人(ばんえい 慎一/北海道 慎康)。KD に慎一のコードだけ(10/10)。"""
    BY2 = dict(BY, **{'村上慎一': {'00777'}})

    def test_one_with_code_one_without(self):
        cs = k.multi_owner_codes([('村上慎一', '1971-06-24'), ('村上慎康', '1986-08-08')], self.BY2, BIRTH)
        self.assertEqual(cs, {'00777'})
        self.assertEqual(k.judge('00777', cs, True), 'keep')
        self.assertEqual(k.judge('09999', cs, True), '別人')

    def test_nobody_has_code(self):
        self.assertEqual(k.multi_owner_codes([('甲野太郎', None), ('乙野次郎', None)], self.BY2, BIRTH), set())

    def test_same_name_unresolved_blocks(self):
        # 加藤和宏の生年月日が合わない(コードは有るが本人が決まらない)なら混ざる恐れ→決めない
        self.assertEqual(k.multi_owner_codes([('村上慎一', None), ('加藤和宏', '1960-01-01')], self.BY2, BIRTH), set())

    def test_overlap_blocks(self):
        by = {'甲': {'1'}, '乙': {'1'}}
        self.assertEqual(k.multi_owner_codes([('甲', None), ('乙', None)], by, {}), set())


if __name__ == '__main__':
    unittest.main()
