# -*- coding: utf-8 -*-
"""cloud/auction_today.py の件数の鍵(count_first_after)が画面の auctionTodayCounts と同じ数え方かを確かめる(DB なし)。"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "cloud"))
_spec = importlib.util.spec_from_file_location("auction_today", os.path.join(ROOT, "cloud", "auction_today.py"))
at = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(at)

D = "2026-10-30"


def row(sales, note=None):
    return {"track": "大井", "no": 1, "umaban": 1, "name": "A", "post_time": "15:00", "note": note, "sales": sales}


def sale(date, sold=True, source="rakuten", runs_after=0, first_after=None):
    return {"date": date, "source": source, "sold": sold, "runs_after": runs_after, "first_after": first_after}


class AuctionCountTest(unittest.TestCase):
    def test_counts(self):
        out = [
            row([sale("2026-10-01")]),                                    # 落札後 0 走= n・m
            row([sale("2026-09-01", runs_after=2, first_after=D)]),        # 落札後の最初が今日= n・m
            row([sale("2026-09-01", runs_after=2, first_after="2026-10-10")]),  # 2 走目以降= n だけ
            row([sale("2026-10-01", sold=False)]),                         # 不成立= n だけ
            row([sale("2022-10-31")]),                                     # 記録の床より前= n だけ
            row([sale(D)]),                                                # 今日の取引= n だけ
            row([sale("2026-10-01", source="hba")]),                       # セリ市場= 数えない
            row([sale("2026-10-01")], note="出走取消"),                    # 取消= 数えない
            row([sale("2026-10-01")], note="競走除外"),                    # 除外= 数えない
            row([{"date": "2026-10", "source": "rakuten", "sold": True}, sale("2026-10-01")]),  # 日付の読めない取引は先に落とす
            row([]),                                                       # 取引なし= 数えない
        ]
        self.assertEqual(at.count_first_after(out, D), {"n": 7, "m": 3})

    def test_empty(self):
        self.assertEqual(at.count_first_after([], D), {"n": 0, "m": 0})


if __name__ == "__main__":
    unittest.main()
