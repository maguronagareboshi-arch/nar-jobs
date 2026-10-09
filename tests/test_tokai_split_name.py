# -*- coding: utf-8 -*-
"""東海の降級 名古屋の一覧= 馬名が列の境目のすぐ左にあり性齢と別の帯に割れていた件(2026-10-10)。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "cloud"))
import tokai_demotion as T  # noqa: E402

W = 1190.4  # 名古屋の一覧の幅。既定の境目= 326 / 593 / 861


def wd(text, x0, top):
    return {"text": text, "x0": x0, "top": top}


def horse(name, x, top, sex="牝", age="3", p="1,750", tr="今津勝之"):
    """名古屋の 1 頭= 馬名・性・齢・P・調教師(x は実物の 2026-7-3 の並び)。"""
    out = [] if name is None else [wd(name, x, top)]
    return out + [wd(sex, x + 91, top), wd(age, x + 108, top), wd(p, x + 132, top), wd(tr, x + 154, top)]


def read(ws):
    bounds = T.ng_bounds(ws, W)
    bands = [[] for _ in range(4)]
    for w in ws:
        bands[sum(1 for x in bounds if w["x0"] >= x)].append(w)
    got = []
    for b in bands:
        for _, rw in T.rows_of(b):
            s = " ".join(w["text"] for w in rw)
            got += [(h.group(1), int(h.group(4).replace(",", ""))) for h in T.HN.finditer(s)]
    return got


class SplitName(unittest.TestCase):
    def test_name_left_of_bound_read_as_one(self):
        # 4 列目の馬名が 858(既定の境目 861 の 3 左)= 直す前は馬名だけ 3 列目の帯に入り 0 頭
        ws = horse("ミズイロ", 373, 120, sex="牡", age="4", p="1,603", tr="川西毅") \
            + horse("キャメロン", 858, 120) + horse("ノーチェ", 858, 130, p="1,900", tr="宇都英樹")
        self.assertEqual(sorted(read(ws)), [("キャメロン", 1750), ("ノーチェ", 1900), ("ミズイロ", 1603)])
        self.assertEqual(T.ng_bounds(ws, W)[2], 857)

    def test_first_column_at_325(self):
        # 2 列目の馬名が 325(既定の境目 326 の 1 左)= 第 10 回の形
        ws = horse("ジャスミン", 325, 140, p="700", tr="宮本茂") + horse("サマーナ", 604, 140, p="873", tr="森山英")
        self.assertEqual(sorted(read(ws)), [("サマーナ", 873), ("ジャスミン", 700)])

    def test_default_bounds_when_no_name_near(self):
        ws = horse("ミズイロ", 373, 120) + horse("カルテ", 616, 120) + horse("ノーチェ", 870, 120)
        bw = (W - 120) / 4
        self.assertEqual(T.ng_bounds(ws, W), [58 + bw, 58 + bw * 2, 58 + bw * 3])
        self.assertEqual(len(read(ws)), 3)

    def test_do_not_join_other_horse(self):
        # 性齢の行に馬名が無い(馬名が別の行にある)= つながない。馬名だけの行・調教師の無い行も読まない
        ws = [wd("ヨソノウマ", 858, 100)] + horse(None, 858, 120) \
            + [wd("ハシリ", 858, 140), wd("牝", 949, 140), wd("3", 966, 140), wd("1,750", 990, 140)]
        self.assertEqual(read(ws), [])

    def test_double_circle_mark(self):
        self.assertEqual(read(horse("◎グレースシャルマン", 373, 120, age="4", p="1,886")), [("グレースシャルマン", 1886)])


if __name__ == "__main__":
    unittest.main()
