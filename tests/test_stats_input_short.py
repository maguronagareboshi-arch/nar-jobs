# -*- coding: utf-8 -*-
"""stats_local._input_short の単体テスト(11/19 推定行数のずれで写しが正しいのに止まった件)。"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "stats_local", os.path.join(HERE, "..", "pipeline", "stats_local", "stats_local.py"))
stats_local = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats_local)


def _boom():
    raise RuntimeError("x")


class InputShortTest(unittest.TestCase):
    def test_enough_by_estimate_does_not_count(self):
        self.assertIsNone(stats_local._input_short("t", 1000, 1005, _boom))

    def test_estimate_off_but_exact_ok_passes(self):
        # 11/19 の実例: 写し 63,890・推定 70,337・実数 63,890
        self.assertIsNone(stats_local._input_short("auction_sales", 63890, 70337, lambda: 63890))

    def test_really_short_stops(self):
        m = stats_local._input_short("t", 500, 1000, lambda: 1000)
        self.assertIn("実数 1000", m)

    def test_count_fails_stops(self):
        self.assertIn("数えられず", stats_local._input_short("t", 500, 1000, _boom))
        self.assertIn("数えられず", stats_local._input_short("t", 500, 1000, lambda: None))


if __name__ == "__main__":
    unittest.main()
