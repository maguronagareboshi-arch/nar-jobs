# -*- coding: utf-8 -*-
"""§271 風の保存: 点の読み取り(品質 0 以外は null・窓の絞り)。標準ライブラリだけ・通信ゼロ。

  py -3.12 -m unittest tests.test_wind_store
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))

import wind_store as ws  # noqa: E402


class WindPoints(unittest.TestCase):
    def test_quality_not_zero_is_null(self):
        rows = {
            "20260924150000": {"wind": [3.2, 0], "windDirection": [5, 0], "temp": [22.1, 0]},
            "20260924151000": {"wind": [4.0, 1], "windDirection": [0, 0], "temp": [22.0, 8]},
            "20260924152000": {"wind": [None, 0], "windDirection": [17, 0]},
            "20260923235000": {"wind": [1.0, 0], "windDirection": [3, 0], "temp": [20.0, 0]},  # 前日= 捨てる
        }
        got = ws.points_of_file(rows, "20260924")
        self.assertEqual([p["t"] for p in got], ["15:00", "15:10", "15:20"])
        self.assertEqual(got[0], {"t": "15:00", "dir": 5, "speed": 3.2, "temp": 22.1})
        self.assertEqual(got[1], {"t": "15:10", "dir": None, "speed": None, "temp": None})
        self.assertEqual(got[2], {"t": "15:20", "dir": None, "speed": None, "temp": None})

    def test_window(self):
        lo, hi = ws.window_of(["15:05", "20:50", "16:40"])
        self.assertEqual((lo, hi), ("14:35", "20:50"))
        self.assertEqual(ws.hours_of(lo, hi), [12, 15, 18])
        pts = [{"t": t} for t in ("14:30", "14:40", "20:50", "21:00")]
        self.assertEqual([p["t"] for p in ws.in_window(pts, lo, hi)], ["14:40", "20:50"])


if __name__ == "__main__":
    unittest.main()
