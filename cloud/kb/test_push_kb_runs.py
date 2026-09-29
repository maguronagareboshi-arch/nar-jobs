# -*- coding: utf-8 -*-
"""cloud/kb/push_kb_runs.keep_existing の固定テスト(空で既存の値を上書きしない)。
  python cloud/kb/test_push_kb_runs.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from push_kb_runs import keep_existing  # noqa: E402

K = ("浦和", "2026-09-22", 1, 3)


def row(**kw):
    r = {"track": "浦和", "race_date": "2026-09-22", "race_no": 1, "umaban": 3, "horse_name": "テスト",
         "kb_race_id": "x", "blinker": None, "gear": None, "first3f": None, "avg_f": None,
         "pace": None, "kimete": None, "start_note": None}
    r.update(kw)
    return r


class KeepExisting(unittest.TestCase):
    def test_empty_new_keeps_existing(self):
        new = row(gear="", first3f=None, kimete="逃げ")
        ex = row(gear="ブリンカー", first3f=36.1, start_note="出遅れ", kimete="差し")
        kept = keep_existing([new], {K: ex})
        self.assertEqual(new["first3f"], 36.1)
        self.assertEqual(new["gear"], "ブリンカー")
        self.assertEqual(new["start_note"], "出遅れ")
        self.assertEqual(new["kimete"], "逃げ")          # 新に値あり= 新で上書き
        self.assertEqual(kept, {"gear": 1, "first3f": 1, "start_note": 1})

    def test_new_value_overwrites(self):
        new = row(first3f=35.0, gear="チークピーシーズ")
        ex = row(first3f=36.1, gear="ブリンカー")
        kept = keep_existing([new], {K: ex})
        self.assertEqual((new["first3f"], new["gear"]), (35.0, "チークピーシーズ"))
        self.assertEqual(kept, {})

    def test_no_existing_row(self):
        new = row(first3f=None)
        self.assertEqual(keep_existing([new], {}), {})
        self.assertIsNone(new["first3f"])


if __name__ == "__main__":
    unittest.main()
