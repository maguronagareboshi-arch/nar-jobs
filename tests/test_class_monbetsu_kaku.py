# -*- coding: utf-8 -*-
"""§203 cloud/class_monbetsu.py の kaku= 番組賞金 → 要領 第5 格付区分・付ける条件(⛔推定しない)。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
try:
    import class_monbetsu as M  # noqa: E402
except ImportError as e:        # pipeline/ の部品が無い環境
    raise unittest.SkipTest(f"class_monbetsu が読めない {e}")

FY = M.KAKUZUKE_FY


class T(unittest.TestCase):
    def test_kaku_of_edges(self):
        self.assertEqual(M.kaku_of(1_200_000), "Ｃ３")       # 120 万ちょうど= 下の級
        self.assertEqual(M.kaku_of(1_200_001), "Ｃ２")       # 120.0001 万
        self.assertEqual(M.kaku_of(8_000_000), "Ａ２")
        self.assertEqual(M.kaku_of(8_010_000), "Ａ１")
        self.assertEqual(M.kaku_of(0), "Ｃ４")
        self.assertIsNone(M.kaku_of(None))

    def test_kaku_for(self):
        f = M.kaku_for
        self.assertEqual(f({"cls": "Ｂ３－２～Ｃ３－１", "prize": 1_450_000}, FY), ("Ｃ２", None))   # 範囲
        self.assertEqual(f({"cls": "Ｃ３－２ Ｃ４－１", "prize": 700_000}, FY), ("Ｃ４", None))    # 並記
        self.assertEqual(f({"cls": "Ｃ４－３", "prize": 380_000}, FY), ("Ｃ４", None))              # 単独
        self.assertEqual(f({"cls": "オープン", "prize": 9_000_000}, FY), (None, "語"))
        self.assertEqual(f({"cls": "３歳２００万円以下", "prize": 1_000_000}, FY), (None, "語"))
        self.assertEqual(f({"cls": None, "grp": "ＪＲＡ認定", "prize": 500_000}, FY), (None, "級なし"))
        self.assertEqual(f({"cls": "Ｃ４－３", "from": "ＪＲＡ"}, FY), (None, "賞金なし"))
        self.assertEqual(f({"cls": "Ｃ４－３", "prize": 1_450_000}, FY), (None, "矛盾"))          # 紙面が優先
        self.assertEqual(f({"cls": "Ｃ４－３", "prize": 380_000}, FY, nisai=True), (None, "2歳"))
        self.assertEqual(f({"cls": "Ｃ４－３", "prize": 380_000}, FY + 1), (None, "年度違い"))    # 古い表を当てない

    def test_attach_kaku(self):
        horses = {"甲": {"cls": "Ｃ４－３", "prize": 380_000}, "乙": {"cls": "Ｃ４－３", "prize": 1_450_000},
                  "丙": {"cls": "新馬", "prize": 0}}
        drop = []
        n = M.attach_kaku(horses, FY, set(), drop, 12)
        self.assertEqual((horses["甲"].get("kaku"), "kaku" in horses["乙"], "kaku" in horses["丙"]), ("Ｃ４", False, False))
        self.assertEqual((n["付けた"], n["矛盾"], n["語"]), (1, 1, 1))
        self.assertEqual(len(drop), 1)                                                            # 矛盾は隠さない


if __name__ == "__main__":
    unittest.main()
