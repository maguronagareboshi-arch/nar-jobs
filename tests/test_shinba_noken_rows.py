# -*- coding: utf-8 -*-
"""§280 能検索引の JSON を noken_recs の行に開く関数(stats_local.noken_rows)の単体テスト。"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "stats_local", os.path.join(HERE, "..", "pipeline", "stats_local", "stats_local.py"))
stats_local = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats_local)


class NokenRowsTest(unittest.TestCase):
    def test_three_records(self):
        value = {"built": "2026-09-25", "horses": {
            "アカ": [{"d": "kochi", "date": "2026-08-01", "time": "51.5", "ok": 1, "r": 3, "n": 8,
                      "dr": 2, "dn": 20, "a": 38.8, "ar": 1, "t1": 12.7, "t1r": 2, "j": "赤岡", "w": 452}],
            "アオ": [{"d": "monbetsu", "date": "2026-05-10", "r": 1, "n": 6, "j": "石川"},
                     {"d": "monbetsu", "date": "bad-date", "w": 400}],
            "キ": [{"d": "ooi", "date": "2026-07-01", "n": 10, "t1": "12.1", "t1r": "1"}],
        }}
        got = stats_local.noken_rows(value)
        self.assertEqual(len(got), 3)   # 日付の読めない 1 件は捨てる
        self.assertEqual(got[0], ("アカ", "2026-08-01", "kochi", 3, 8, 2, 20, 1, 12.7, 2, "赤岡", 452))
        self.assertEqual(got[1], ("アオ", "2026-05-10", "monbetsu", 1, 6, None, None, None, None, None, "石川", None))
        self.assertEqual(got[2], ("キ", "2026-07-01", "ooi", None, 10, None, None, None, 12.1, 1, None, None))
        # 列の数と並び= NOKEN_KEYS(horse_name, date の後)
        self.assertEqual(len(got[0]), 2 + len(stats_local.NOKEN_KEYS))
        self.assertEqual(got[0][2 + stats_local.NOKEN_KEYS.index("w")], 452)
        self.assertEqual(got[0][2 + stats_local.NOKEN_KEYS.index("t1r")], 2)

    def test_empty(self):
        self.assertEqual(stats_local.noken_rows({}), [])
        self.assertEqual(stats_local.noken_rows(None), [])


if __name__ == "__main__":
    unittest.main()
