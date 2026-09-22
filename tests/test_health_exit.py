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
        # 2026-09-22 の監査= changed・review は「人が見る待ち」なので exit 1 に効かせない(数は出す)
        hh.count_skip_reason(stats, "changed_waiting_review")
        self.assertEqual(stats["changed"], 1, "changed の数は今までどおり数える")
        self.assertEqual(hh.exit_count(stats), 0, "changed で exit 1 にした")

    def test_exit_count_combinations(self):
        """数の組み合わせ 4 例= 効くのは not_ready・error・attention だけ。"""
        base = {"review": 0, "changed": 0, "not_ready": 0, "error": 0, "attention": 0,
                "review_waiting": 0, "reparse_waiting": 0}
        # ① 何も無い= 0
        self.assertEqual(hh.exit_count(dict(base)), 0)
        # ② review 3 + changed 5 だけ= 0(前は 8 で毎日赤だった)
        self.assertEqual(hh.exit_count(dict(base, review=3, changed=5)), 0)
        # ③ error 2 + not_ready 1 + attention 4 = 7
        self.assertEqual(hh.exit_count(dict(base, error=2, not_ready=1, attention=4)), 7)
        # ④ 混ざり= review/changed/待ちは数えず error 1 + attention 2 = 3
        self.assertEqual(
            hh.exit_count(dict(base, review=9, changed=9, review_waiting=9, reparse_waiting=9,
                               error=1, attention=2)), 3)


if __name__ == "__main__":
    unittest.main()
