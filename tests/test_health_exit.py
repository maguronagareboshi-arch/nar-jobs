# -*- coding: utf-8 -*-
"""§186 健康情報の便の exit= 取り直し待ち(parser_changed_use_reparse)は exit 1 に数えず reparse_waiting で見せる。
標準ライブラリだけ・通信ゼロ。

  py -3.12 -m unittest tests.test_health_exit
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))

import horse_health as hh  # noqa: E402


class HealthExit(unittest.TestCase):
    def test_reparse_waiting_does_not_fail(self):
        # 2026-09-13〜 auction の実測= 871 source が全部 parser_changed_use_reparse で毎回 exit 1 だった
        stats = {k: 0 for k in ("review", "changed", "error", "attention", "review_waiting", "reparse_waiting")}
        for _ in range(871):
            hh.count_skip_reason(stats, "parser_changed_use_reparse")
        hh.count_skip_reason(stats, "review_waiting_parser_or_force")
        hh.count_skip_reason(stats, "complete_after_window")
        self.assertEqual((stats["reparse_waiting"], stats["review_waiting"], stats["attention"]), (871, 1, 0))
        self.assertEqual(hh.exit_count(stats), 0, "取り直し待ち・review 待ちで exit 1 にした")
        # 本物の要確認(changed・error・新しい review)は今までどおり exit 1
        hh.count_skip_reason(stats, "changed_waiting_review")
        self.assertEqual(hh.exit_count(stats), 1)
        self.assertEqual(hh.exit_count(dict(stats, error=2, review=3)), 6)


if __name__ == "__main__":
    unittest.main()
