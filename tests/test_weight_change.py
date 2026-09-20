# -*- coding: utf-8 -*-
"""§237 馬体重増減の負の値。⛔通信なし。

  py -3.12 -X utf8 -m unittest discover -s tests -p "test_*.py"
"""
import sys
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "cloud",):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fix_weight_change as fx                                   # noqa: E402
from nar_official_csv import _number, normalize_horses           # noqa: E402


class NumberSign(unittest.TestCase):
    def test_weight_change_keeps_minus(self):
        for text in ("-4", "−4", "－4", "‐4"):      # 半角・数学・全角・ハイフンのマイナス
            self.assertEqual(_number(text, integer=True, allow_negative=True), -4, text)

    def test_other_columns_still_drop_minus(self):
        # 上がり3F・賞金・距離の守りは今までどおり(負は None)
        self.assertIsNone(_number("-37.2"))
        self.assertIsNone(_number("-1200", integer=True))
        self.assertIsNone(_number("−37.2"))

    def test_zero_blank_and_words_unchanged(self):
        self.assertEqual(_number("+0", integer=True, allow_negative=True), 0)
        self.assertEqual(_number("0", integer=True, allow_negative=True), 0)
        for text in ("±0", "", "-", "取消", "除外"):
            self.assertIsNone(_number(text, integer=True, allow_negative=True), text)

    def test_normalize_horses_row(self):
        row = {"競馬場": "門別", "競走年月日": "20260903", "レース番号": "1", "馬番": "5",
               "馬体重": "420", "馬体重増減": "-4", "上がり3F": "39.0"}
        got = normalize_horses([row])[0]
        self.assertEqual(got["body_weight_change"], -4)
        self.assertEqual(got["body_weight"], 420)


class SendShape(unittest.TestCase):
    def test_only_keys_and_change_are_sent(self):
        rows = {("門別", "2026-09-03", 1, 5): -4, ("門別", "2026-09-03", 1, 6): -2}
        have = {("門別", "2026-09-03", 1, 5)}                      # 6 番は本番に行が無い
        send = [dict(zip(fx.KEYS, k), body_weight_change=v) for k, v in sorted(rows.items()) if k in have]
        self.assertEqual(len(send), 1, "本番に無い鍵を送っている")
        self.assertEqual(sorted(send[0]), sorted(["track", "race_date", "race_no", "runner_number", "body_weight_change"]))
        self.assertEqual(send[0]["body_weight_change"], -4)

    def test_summary_counts_year_and_track(self):
        rows = {("門別", "2026-09-03", 1, 5): -4, ("大井", "2025-05-01", 2, 3): -6}
        text = fx.summarize(rows, {("門別", "2026-09-03", 1, 5)})
        self.assertIn("2026", text)
        self.assertIn("門別", text)
        self.assertIn("大井", text)


class DumpAndRead(unittest.TestCase):
    """§237b 控え(csv.gz)の書き出し/読み込み= 生 ZIP の無い GitHub Actions で当てるための道。"""

    def test_round_trip_keeps_only_minus(self):
        import tempfile
        rows = {("門別", "2026-09-03", 1, 5): -4, ("大井", "2025-05-01", 2, 3): -6}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.csv.gz")
            fx.dump_rows(rows, path)
            back = fx.read_rows(path)
        self.assertEqual(back, rows, "書いて読んだら同じにならない")

    def test_read_drops_zero_and_plus(self):
        import gzip, csv, tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "y.csv.gz")
            with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(list(fx.KEYS) + ["body_weight_change"])
                w.writerow(["門別", "2026-09-03", 1, 5, -4])
                w.writerow(["門別", "2026-09-03", 1, 6, 0])       # ⛔0 は当てない
                w.writerow(["門別", "2026-09-03", 1, 7, 2])       # ⛔正は当てない(既存の値を壊さない)
                w.writerow(["", "2026-09-03", 1, 8, -2])          # ⛔場の無い行は捨てる
            back = fx.read_rows(path)
        self.assertEqual(back, {("門別", "2026-09-03", 1, 5): -4})


if __name__ == "__main__":
    unittest.main()
