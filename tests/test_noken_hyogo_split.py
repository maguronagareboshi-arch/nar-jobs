# -*- coding: utf-8 -*-
"""10/12 兵庫のレース割り: 提供データの騎手を足す・板(boards)だけの日も組の番号が付く。
⛔通信なし。py -3.12 -m unittest tests.test_noken_hyogo_split -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import noken_public as nk                                          # noqa: E402


def official():
    return {"date": "2026-06-08", "races": [
        {"kind": "能力検査", "dist": 820, "rows": [{"name": "アアア"}, {"name": "イイイ"}]},
        {"kind": "自主参加", "dist": 1400, "rows": [{"name": "ウウウ", "jockey": "公式"}]},
    ]}


class HyogoSplit(unittest.TestCase):
    def test_jockey_from_split(self):
        day = official()
        sp = {"races": [{"no": 1, "rows": [{"name": "アアア", "jockey": "甲"},
                                           {"name": "ウウウ", "jockey": "乙"}]}]}
        nk.hyogo_split_day(day, sp)
        rows = {r["name"]: r for g in day["races"] for r in g["rows"]}
        self.assertEqual(rows["アアア"].get("jockey"), "甲")
        self.assertEqual(rows["ウウウ"].get("jockey"), "公式")     # 公式にある値は上書きしない
        self.assertIsNone(rows["イイイ"].get("jockey"))

    def test_boards_only_day(self):
        day = official()
        sp = {"date": "2026-06-08", "races": [],
              "boards": [{"no": 1, "names": ["イイイ", "ウウウ"]}, {"no": 2, "names": ["アアア"]}]}
        st = nk.hyogo_split_day(day, sp)
        self.assertEqual(st["unknown"], 0)
        self.assertEqual([(r["no"], [x["name"] for x in r["rows"]]) for r in day["races"]],
                         [(1, ["イイイ", "ウウウ"]), (2, ["アアア"])])


if __name__ == "__main__":
    unittest.main()
