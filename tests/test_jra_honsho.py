# -*- coding: utf-8 -*-
"""2026-10-17 中央の走の本賞金(付加賞抜き)への差し替え・台帳に無い中央の走の補い(class_calc.jra_honsho_merge)と
競馬ブック成績頁の賞金表の読み取り(kb/jra_race_prize.parse)。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cloud"))
sys.path.insert(0, str(ROOT / "cloud" / "kb"))
import class_calc as C  # noqa: E402
import jra_race_prize as P  # noqa: E402

HON = [10_700_000, 4_300_000, 2_700_000, 1_600_000, 1_070_000]


def led(d, fin, prize, jra=True):
    return {"d": d, "tr": "Ｊ新潟" if jra else "浦和", "fin": fin, "prize": prize, "jra": jra, "name": "わらび賞３歳１勝クラス"}


def jr(d, fin, honsho=HON, place="新潟"):
    return {"race_date": d, "place": place, "race_no": 9, "finish": fin, "race_name": "わらび賞 1勝クラス",
            "field_size": 14, "honsho": honsho}


class Merge(unittest.TestCase):
    def test_replace_with_honsho(self):
        out = C.jra_honsho_merge([led("2024-04-27", 3, 2_747_000)], [jr("2024-04-27", 3)])
        self.assertEqual(out[0]["prize"], 2_700_000)

    def test_keep_when_no_honsho(self):
        out = C.jra_honsho_merge([led("2024-04-27", 3, 2_747_000)], [jr("2024-04-27", 3, honsho=None)])
        self.assertEqual(out[0]["prize"], 2_747_000)

    def test_local_run_untouched(self):
        out = C.jra_honsho_merge([led("2024-04-27", 3, 500_000, jra=False)], [jr("2024-04-27", 3)])
        self.assertEqual(out[0]["prize"], 500_000)

    def test_add_missing_runs(self):
        # テイエムプレミラン: 浦和の後に中央へ戻った走が台帳に無い
        out = C.jra_honsho_merge([led("2026-05-26", 7, 0, jra=False)],
                                 [jr("2026-08-29", 3, place="中京"), jr("2026-06-14", 4, place="阪神"), jr("2026-07-10", 9, honsho=None)])
        self.assertEqual([r["d"] for r in out], ["2026-08-29", "2026-07-10", "2026-06-14", "2026-05-26"])
        self.assertEqual([r["prize"] for r in out], [2_700_000, 0, 1_600_000, 0])
        self.assertTrue(all(r["jra"] for r in out[:3]))
        self.assertEqual(out[0]["tr"], "Ｊ中京")

    def test_skip_missing_top5_without_honsho(self):
        out = C.jra_honsho_merge([], [jr("2026-08-29", 2, honsho=None)])
        self.assertEqual(out, [])

    def test_input_not_mutated(self):
        src = [led("2024-04-27", 3, 2_747_000)]
        C.jra_honsho_merge(src, [jr("2024-04-27", 3)])
        self.assertEqual(src[0]["prize"], 2_747_000)


class Parse(unittest.TestCase):
    def test_table(self):
        h = ('<table class="syokin"><tr><th>賞金</th><td>&#9312;<span>1,070.0万</span></td><td>&#9313;<span>430.0万</span></td></tr>'
             '<tr><td></td><td>&#9314;<span>270.0万</span></td><td>&#9315;<span>160.0万</span></td><td>&#9316;<span>107.0万</span></td></tr></table>')
        self.assertEqual(P.parse(h), HON)

    def test_no_table(self):
        self.assertIsNone(P.parse("<html></html>"))

class ShutokuTest(unittest.TestCase):
    """2026-10-20 高知= 付加賞抜き・同着は等分(shutoku_of)。福ちゃん 10/11 号 ヒビキ 1111万。"""
    OP = [22_000_000, 8_800_000, 5_500_000, 3_300_000, 2_200_000]      # 越後Ｓ
    NI = [15_500_000, 6_200_000, 3_900_000, 2_300_000, 1_550_000]      # 鴨川特別

    def test_fuka_only(self):                  # 台帳 ≥ 本賞金= 付加賞ぶんを除く
        self.assertEqual(C.shutoku_of(18_750_000, [18_400_000, 7_400_000, 4_600_000, 2_800_000, 1_840_000], 1), 18_400_000)
        self.assertEqual(C.shutoku_of(11_076_000, [27_000_000, 11_000_000, 6_800_000, 4_100_000, 2_700_000], 2), 11_000_000)

    def test_dead_heat(self):                  # 同着= 等分
        self.assertEqual(C.shutoku_of(4_423_000, self.OP, 3), 4_400_000)   # 3着同着 2 頭
        self.assertEqual(C.shutoku_of(775_000, self.NI, 5), 775_000)       # 5着同着 2 頭 (155万+0)/2

    def test_no_table(self):
        self.assertIsNone(C.shutoku_of(100, None, 3))
        self.assertIsNone(C.shutoku_of(100, [1, 2], 3))

    def test_merge_flag(self):
        runs = [led("2025-05-04", 3, 4_423_000)]
        out = C.jra_honsho_merge(runs, [jr("2025-05-04", 3, self.OP)], True)
        self.assertEqual(out[0]["prize"], 4_400_000)
        out = C.jra_honsho_merge(runs, [jr("2025-05-04", 3, self.OP)])
        self.assertEqual(out[0]["prize"], 5_500_000)   # 佐賀は従来どおり本賞金


if __name__ == "__main__":
    unittest.main()
