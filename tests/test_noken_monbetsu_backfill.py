# -*- coding: utf-8 -*-
"""10/2 門別の取り直し= 日付の選び方・古い PDF の着順/不合格の読み方。⛔通信なし。
py -3.12 -m unittest tests.test_noken_monbetsu_backfill -v"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import noken_public as nk                                          # noqa: E402


class FakePage:
    def __init__(self, words):
        self.words = words

    def extract_words(self):
        return self.words


def w(text, x0, top):
    return {"text": text, "x0": x0, "top": top}


class MonbetsuBackfill(unittest.TestCase):
    def test_dates_from_file_skip_existing_and_range(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8") as f:
            f.write("2023-10-09\t237855\n2024-05-07\t1\n20250617\n2026-05-01\nDONE\n")
        try:
            todo, n, probe = nk.monbetsu_bf_dates("2023-04-01", "2026-03-31", f.name, {"2024-05-07"})
        finally:
            os.unlink(f.name)
        self.assertFalse(probe)
        self.assertEqual(n, 3)
        self.assertEqual(todo, ["2023-10-09", "2025-06-17"])

    def test_dates_comma_and_probe(self):
        todo, n, probe = nk.monbetsu_bf_dates("2024-01-01", "2024-12-31", "2024-05-07,2024-06-01", set())
        self.assertEqual((todo, probe), (["2024-05-07", "2024-06-01"], False))
        todo, n, probe = nk.monbetsu_bf_dates("2024-01-01", "2024-01-03", None, {"2024-01-02"})
        self.assertEqual((todo, n, probe), (["2024-01-01", "2024-01-03"], 3, True))

    def test_heads_joined_order_2024(self):
        page = FakePage([w("１R", 10, 96.7), w("．．４．５．６．２．３．１", 30, 97.7), w("８００m", 120, 97.7)])
        h = nk.monbetsu_heads(page)[0]
        self.assertEqual((h["no"], h["order"], h["dist"]), (1, [4, 5, 6, 2, 3, 1], 800))

    def test_heads_split_order_2026(self):
        page = FakePage([w("１R", 10, 96.7), w("．", 30, 97.7), w("３", 40, 98.7), w("．", 50, 97.7),
                         w("１", 60, 98.7), w("８００m", 120, 97.7)])
        self.assertEqual(nk.monbetsu_heads(page)[0]["order"], [3, 1])

    def test_ok_counts_fugoukaku_note(self):
        rows = [{"time": "50.1"}, {"time": "53.1", "note": "不合格"}, {"time": "55.0", "note": "タイムオーバー"}, {}]
        drop = []
        nk.monbetsu_ok([{"rows": rows}], 1, 2, "2024-05-07", drop)
        self.assertEqual([r.get("ok") for r in rows], ["合格", "不合格", "不合格", None])
        self.assertEqual(drop, [])


if __name__ == "__main__":
    unittest.main()
