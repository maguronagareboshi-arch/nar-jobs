# -*- coding: utf-8 -*-
"""§170 段 2 A 楽天の確定オッズの読み方の検算。標準ライブラリだけ・**通信ゼロ**。

  py -3.12 -m unittest discover -s tests -p "test_rakuten_odds*.py"

確かめるのは=
  ①組番「4→1→9」を (4, 1, 9) に分ける(「-」や空白が混ざっても数字だけ)
  ②「順位・組番・オッズ」の表(人気順)から組と odds を読む・2 つ目の表(高配当順)は読まない・odds の無い組は入れない
  ③ページの日付と出走頭数(出馬表の見出しの数)を読む・日付が 0000/00/00 のページは None
  ④RACEID は 18 桁(場コードの後の 0 は 6 個)・表に無い場は None
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'ai'))

from rakuten_odds_hist import parse_rank_table, race_id, split_combo  # noqa: E402

# 保存した船橋 2025-10-01 1R(三連単)のページの形をそのまま短くした断片(頭数 3・組 3 つ+取消の組)
PAGE = """<html><head><title>船橋競馬場 オッズ(三連単) | 2025/10/01 1R ：楽天競馬</title></head><body>
<table cellspacing="0" aria-label="出馬表" class="dataTable"><thead><tr><th>1</th><th>2</th><th>3</th></tr></thead></table>
<table cellspacing="0" class="dataTable"><thead><tr><th>順位</th><th>組番</th><th>オッズ</th></tr></thead><tbody>
<tr><td>1</td><td><span>4</span>→<span>1</span>→<span>9</span></td><td><span class="hot">12.3</span></td></tr>
<tr><td>2</td><td>4→9→1</td><td>15.0</td></tr>
<tr><td>3</td><td>6 - 9 - 3</td><td>168.1</td></tr>
<tr><td>-</td><td>2→1→9</td><td>---</td></tr>
</tbody></table>
<table cellspacing="0" class="dataTable"><thead><tr><th>順位</th><th>組番</th><th>オッズ</th></tr></thead><tbody>
<tr><td>1</td><td>6→9→3</td><td>999.9</td></tr>
</tbody></table></body></html>"""


class Rakuten(unittest.TestCase):
    def test_split_combo(self):
        self.assertEqual(split_combo('4→1→9'), (4, 1, 9))
        self.assertEqual(split_combo('<span>10</span>→<span>1</span>'), (10, 1))
        self.assertEqual(split_combo('6 - 9 - 3'), (6, 9, 3))

    def test_parse_rank_table(self):
        combos, day, heads = parse_rank_table(PAGE, 3)
        self.assertEqual(combos, {(4, 1, 9): 12.3, (4, 9, 1): 15.0, (6, 9, 3): 168.1},
                         '人気順の表だけ・odds の無い組は入れない')
        self.assertEqual(day, '2025/10/01')
        self.assertEqual(heads, 3)
        # 馬単の組(2 頭)を 3 頭で読もうとしたら入れない
        self.assertEqual(parse_rank_table(PAGE, 2)[0], {})

    def test_bad_page(self):
        bad = PAGE.replace('2025/10/01', '0000/00/00')
        self.assertIsNone(parse_rank_table(bad, 3)[1], '日付の無いページを取れたことにしている')

    def test_race_id(self):
        self.assertEqual(race_id('船橋', '2025-10-01', 1), '202510011900000001')
        self.assertEqual(race_id('大井', '2026-03-09', 1), '202603092000000001')
        self.assertEqual(race_id('帯広ば', '2026-01-02', 12), '202601020300000012')
        self.assertEqual(len(race_id('高知', '2026-08-02', 9)), 18)
        self.assertIsNone(race_id('ばんえい', '2026-01-02', 1))


if __name__ == '__main__':
    unittest.main()
