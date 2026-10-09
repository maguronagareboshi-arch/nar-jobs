# -*- coding: utf-8 -*-
"""金沢の砂厚(作業簡略図)の読み手の検算。通信ゼロ・pdfplumber 不要。

  py -3.12 -m unittest discover -s tests -p "test_sand*.py"

種= 2026-09-30 の作業簡略図(info-38601)を pdfplumber で読んだ語と縦位置(top)をそのまま写したもの。
⛔原本(PDF)は置かない。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud.sand_depth import kanazawa_body_pdf, kanazawa_lanes, kanazawa_news_items   # noqa: E402

W0930 = [  # pdfplumber の並び(上下が入り組んでいる)= 読み手が top で並べ直す
    {"text": "作業簡略図（本馬場調整）9月30日", "x0": 40, "top": 30},
    {"text": "：レベルハロー調整方向", "x0": 60, "top": 120},
    {"text": "6", "x0": 300, "top": 200},
    {"text": "競走馬走行予想列", "x0": 200, "top": 230},
    {"text": "13~14㎝", "x0": 445, "top": 242},
    {"text": "10", "x0": 300, "top": 250},
    {"text": "11~12㎝", "x0": 445, "top": 263},
    {"text": "9月30日現在", "x0": 520, "top": 270},
    {"text": "11~12㎝", "x0": 445, "top": 281},
    {"text": "11㎝", "x0": 445, "top": 299},
    {"text": "砂厚を外から内へ調整", "x0": 200, "top": 310},
    {"text": "9㎝", "x0": 449, "top": 328},
    {"text": "7㎝", "x0": 450, "top": 342},
]


class TestKanazawa(unittest.TestCase):
    def test_lanes_0930(self):
        d, lanes = kanazawa_lanes(W0930, "2026-09-30")
        self.assertEqual(d, "2026-09-30")
        self.assertEqual(lanes, [[13, 14], [11, 12], [11, 12], [11, 11], [9, 9], [7, 7]])

    def test_order_is_by_top(self):
        d, lanes = kanazawa_lanes(list(reversed(W0930)), "2026-09-30")
        self.assertEqual(lanes[0], [13, 14])
        self.assertEqual(lanes[-1], [7, 7])

    def test_missing_value_is_rejected(self):
        ws = [w for w in W0930 if w["text"] != "9㎝"]
        self.assertEqual(kanazawa_lanes(ws, "2026-09-30"), (None, None))

    def test_date_from_title_when_no_genzai(self):
        ws = [w for w in W0930 if "現在" not in w["text"]]
        self.assertEqual(kanazawa_lanes(ws, "2026-09-30")[0], "2026-09-30")

    def test_year_rollover(self):
        ws = [dict(w, text=w["text"].replace("9月30日", "12月28日")) for w in W0930]
        self.assertEqual(kanazawa_lanes(ws, "2027-01-05")[0], "2026-12-28")

    def test_news_items(self):
        html = ('<li><a href="https://www.kanazawakeiba.com/news/info-38601/" >金沢競馬場コース情報（馬場砂厚調整）'
                '<span class="date">2026.09.30</span></a></li>'
                '<li><a href="https://www.kanazawakeiba.com/news/info-38444/" >金沢競馬場コース情報（砂の補充）'
                '<span class="date">2026.09.25</span></a></li>')
        self.assertEqual(kanazawa_news_items(html), [
            ("https://www.kanazawakeiba.com/news/info-38601/", "2026-09-30", "金沢競馬場コース情報（馬場砂厚調整）")])

    def test_body_pdf_skips_side_links(self):
        html = ('<a href="https://x/wp-content/uploads/2026/01/R8nenkan.pdf">年間</a>'
                '<div class="paper"><p>9月30日 馬場砂厚調整しました。</p>'
                '<p><a href="https://x/wp-content/uploads/2026/09/140f.pdf">作業簡略図</a></p></div>')
        self.assertEqual(kanazawa_body_pdf(html), "https://x/wp-content/uploads/2026/09/140f.pdf")


if __name__ == "__main__":
    unittest.main()
