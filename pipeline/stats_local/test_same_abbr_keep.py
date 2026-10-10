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


if __name__ == '__main__':
    unittest.main()
