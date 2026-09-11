# -*- coding: utf-8 -*-
"""§146 砂厚の読み手の検算。標準ライブラリだけ・**通信ゼロ**・pdfplumber も要らない。

  py -3.12 -m unittest discover -s tests -p "test_sand*.py"

種(fixture)は `tests/fixtures/` に置いた **pdfplumber が返した文字と語の座標**(JSON)。
⛔原本(PDF・HTML)は置かない。高知だけは記事の段落(公式の実文)をそのまま置く。

確かめるのは、実地で踏んだ落とし穴が全部塞がっているか=
  ①高知= 4 地点 × 15 値・補充は本文の日付・「馬場状態の変更」は拾わない・欠けた行はある分だけ
  ②名古屋= 回し方で 5 断面に分かれる・見出しの「16回」が断面に紛れない・内→外の順・
    様式が 2 通りある見出し(全角/半角・分かち書き)・断面の名前は向きで決まる
  ③文字認識= 小数点が落ちても読める(「85」→ 8.5)・検算に落ちたものは捨てる
  ④笠松= 11 地点 × 4 値 + **印字の**平均(算術平均と違ってもそのまま)・白い字を捨てる・
    天気と馬場は丸の中の字
  ⑤名古屋の整備= 同じ日は 1 行にまとめる(器が 1 日 1 行のため)・測定は二重に入れない
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud.sand_depth import (                                        # noqa: E402
    check_ocr, circled, drop_white, kasamatsu_news_items, kasamatsu_points, kochi_list_items,
    kochi_rows, nagoya_header, nagoya_maintenance, nagoya_name, nagoya_news_pdfs,
    nagoya_sections, norm_date, num_list, ocr_value, COND_WORDS, NAGOYA_NAMES, WEATHER_WORDS)

FIX = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    with open(FIX / name, encoding="utf-8") as f:
        return json.load(f)


class KochiTest(unittest.TestCase):
    """① 高知(HTML の記事)"""

    def setUp(self):
        self.m = fixture("sand_kochi_measure.json")

    def rows(self, f=None):
        o = f or self.m
        return kochi_rows(o["paras"], o["title"], o["url"])

    def test_four_sections_of_fifteen(self):
        rows = self.rows()
        self.assertEqual([r["section"] for r in rows],
                         ["1から2コーナー", "向正面（バック）", "3から4コーナー", "正面（ホーム）"])
        for r in rows:
            self.assertEqual(r["kind"], "measure")
            self.assertEqual(r["d"], "2026-08-02")
            self.assertEqual(len(r["vals"]), 15, r["section"])
            self.assertEqual(r["offsets"], [float(i + 1) for i in range(15)])
            self.assertEqual((r["cond"], r["t"]), ("良", "11時30分"))
        self.assertEqual(rows[0]["vals"][:3], [14.5, 14.0, 12.5])

    def test_refill_uses_the_date_in_the_text(self):
        # ⚠記事が出たのは翌日。入れるのは**砂を入れた日**(本文の「令和7年6月18日」)
        rows = self.rows(fixture("sand_kochi_refill.json"))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["kind"], rows[0]["d"], rows[0]["amount_t"]),
                         ("refill", "2025-06-18", 130.0))
        self.assertIsNone(rows[0]["vals"])
        self.assertIn("補充", rows[0]["note"])

    def test_change_notice_is_not_taken(self):
        o = dict(self.m, title="馬場状態の変更　第2競走以降")
        self.assertEqual(self.rows(o), [])

    def test_short_row_keeps_what_is_printed(self):
        # ⚠整備で測れない日は 15 個そろわない= **ある分だけ**入れる(⛔推測で埋めない)
        rows = kochi_rows(["2026年8月2日　11時30分 現在", "馬場状態　重",
                           "1から2コーナー\n14.5-14-12.5"], "2026年8月2日の馬場状態", "u")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["vals"], [14.5, 14.0, 12.5])
        self.assertEqual(rows[0]["offsets"], [1.0, 2.0, 3.0])
        self.assertEqual(rows[0]["cond"], "重")

    def test_list_items(self):
        html = ('<article id="post-127643" class="entry">'
                '<h2><a href="x" class="entry-title entry-title-link">2026年8月2日の馬場状態</a></h2>'
                '</article>'
                '<article id="post-125972" class="entry">'
                '<h2><a href="x" class="entry-title entry-title-link">馬場状態の変更　第2競走以降</a></h2>'
                '</article>')
        got = kochi_list_items(html)
        self.assertEqual([u for u, _ in got],
                         ["https://www.keiba.or.jp/?p=127643", "https://www.keiba.or.jp/?p=125972"])
        self.assertEqual(norm_date(got[0][1]), "2026-08-02")


class NagoyaTest(unittest.TestCase):
    """② 名古屋(PDF の文字)"""

    def setUp(self):
        self.old = fixture("sand_nagoya_old.json")     # 2025-11-06(全角・「16回」あり)
        self.new = fixture("sand_nagoya_new.json")     # 2026-09-10(赤い数字・分かち書き)

    def secs(self, f):
        return {s["name"]: s["vals"] for s in nagoya_sections(f["chars"], f["center"])}

    def test_five_sections_split_by_rotation(self):
        # ⛔画像の断面(ゴール前直線)はここには出ない= 文字が 1 字も無いため
        for f, n in ((self.old, "古い様式"), (self.new, "新しい様式")):
            got = self.secs(f)
            self.assertEqual(sorted(got), ["1コーナー", "2コーナー", "3コーナー", "4コーナー", "向正面"], n)
            self.assertNotIn(NAGOYA_NAMES["down"], got, n)

    def test_counts_are_not_always_fifteen(self):
        # ⚠15 個の決め打ちは外れる(古い様式の 1・4 コーナーは 14 点しか刷っていない)
        got = self.secs(self.old)
        self.assertEqual([len(got[k]) for k in ("1コーナー", "2コーナー", "3コーナー", "4コーナー", "向正面")],
                         [14, 15, 15, 14, 15])
        self.assertTrue(all(len(v) == 15 for v in self.secs(self.new).values()))

    def test_kai_number_does_not_leak_into_a_section(self):
        # ⚠「第 16 回」の 16 は向正面と同じ回し方(0 度)。列で切らないと断面に紛れる
        vals = self.secs(self.old)["向正面"]
        self.assertNotIn(16.0, vals)
        self.assertEqual(vals[0], 12.0)

    def test_inner_first(self):
        # 内(コース図の中心に近い端)が先頭。⛔「内がいちばん厚い」は前提にしない
        got = self.secs(self.new)
        self.assertEqual(got["向正面"][0], 12.0)
        self.assertEqual(got["向正面"][-1], 9.0)
        self.assertEqual(got["4コーナー"][0], 9.0)         # 内が最大でない実例
        self.assertEqual(max(got["4コーナー"]), 10.0)

    def test_header_both_layouts(self):
        self.assertEqual(nagoya_header(self.new["words"]),
                         {"d": "2026-09-10", "t": "13:00～14:00", "weather": "曇り", "cond": "重",
                          "title": nagoya_header(self.new["words"])["title"]})
        old = nagoya_header(self.old["words"])
        self.assertEqual((old["d"], old["t"], old["weather"], old["cond"]),
                         ("2025-11-06", "15:15～16:15", "晴", "稍重"))

    def test_names_come_from_the_direction(self):
        self.assertEqual(nagoya_name(2, -100), "向正面")
        self.assertEqual(nagoya_name(2, 100), "ゴール前直線")
        self.assertEqual(nagoya_name(80, -60), "3コーナー")
        self.assertEqual(nagoya_name(-80, -60), "2コーナー")
        self.assertEqual(nagoya_name(-80, 60), "1コーナー")
        self.assertEqual(nagoya_name(80, 60), "4コーナー")


class MaintenanceTest(unittest.TestCase):
    """⑤ 名古屋の馬場整備状況"""

    HTML = ('<tr data-href="a.pdf"><td>2026年09月11日</td><td>令和８年度第12回開催前日砂厚測定</td>'
            '<td class="pdf"></td></tr>'
            '<tr data-href="b.pdf"><td>2026年01月08日</td><td>馬場砂補充整備実施</td>'
            '<td class="pdf">３コーナー付近から２コーナー付近まで</td></tr>'
            '<tr data-href="c.pdf"><td>2026年01月08日</td><td>埒下砂掻き出し砂厚調整実施</td>'
            '<td class="pdf">全周</td></tr>')

    def test_same_day_becomes_one_row(self):
        # ⚠器の一意は「場×日×種類×地点」で、整備は地点が無い= 1 日 1 行。2 件ある日は 1 行にまとめる
        rows = nagoya_maintenance(self.HTML, "https://example.invalid/dirt")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["d"], "2026-01-08")
        self.assertEqual(rows[0]["kind"], "maintenance")
        self.assertIsNone(rows[0]["section"])
        self.assertEqual(rows[0]["note"],
                         "馬場砂補充整備実施(３コーナー付近から２コーナー付近まで)／埒下砂掻き出し砂厚調整実施(全周)")

    def test_measurement_is_left_to_the_pdf(self):
        rows = nagoya_maintenance(self.HTML, "u")
        self.assertNotIn("2026-09-11", [r["d"] for r in rows])

    def test_news_list_takes_only_sand_pdfs(self):
        html = ('<li><a href="https://x/a.pdf" target="_blank"><time>2026.09.11'
                '<span class="icnRace">レース情報</span></time><p>令和８年度第12回開催前日砂厚測定'
                '<img src="i.png"></p></a></li>'
                '<li><a href="https://x/b.html"><time>2026.09.10</time><p>騎手の記録</p></a></li>'
                '<li><a href="https://x/c.pdf"><time>2026.08.31</time><p>馬場砂補充整備実施</p></a></li>')
        self.assertEqual(nagoya_news_pdfs(html),
                         [("https://x/a.pdf", "2026-09-11", "令和８年度第12回開催前日砂厚測定")])


class OcrTest(unittest.TestCase):
    """③ 画像の断面を文字認識で読むところ"""

    def test_value_survives_a_lost_decimal_point(self):
        # 名古屋は必ず小数 1 桁で刷る= 数字だけ拾って 10 で割る
        self.assertEqual(ocr_value("8.5"), 8.5)
        self.assertEqual(ocr_value("85"), 8.5)
        self.assertEqual(ocr_value("120"), 12.0)
        self.assertEqual(ocr_value("9.0"), 9.0)
        self.assertIsNone(ocr_value(""))
        self.assertIsNone(ocr_value("8"))
        self.assertIsNone(ocr_value("6851"))

    def test_check_rejects_each_way_of_being_wrong(self):
        ok = [12.0, 11.0, 11.0, 10.0, 11.0, 11.0, 10.0, 10.0, 10.0, 10.0, 10.0, 8.0, 8.0, 8.0, 9.0]
        self.assertTrue(check_ocr(ok))
        self.assertTrue(check_ocr(ok[:14]))
        self.assertFalse(check_ocr([]), "空")
        self.assertFalse(check_ocr(ok[:9]), "少なすぎる")
        self.assertFalse(check_ocr(ok + [68.5]), "range の外")
        self.assertFalse(check_ocr(ok[:14] + [8.9]), "0.5 刻みでない")
        self.assertFalse(check_ocr(ok[:14] + [13.5]), "隣との差が大きい")


class KasamatsuTest(unittest.TestCase):
    """④ 笠松(PDF の文字)"""

    def setUp(self):
        self.f = fixture("sand_kasamatsu.json")
        self.words = drop_white(self.f["words"])
        self.curves = self.f["curves"]

    def test_eleven_points_of_four(self):
        got = {p["section"]: p for p in kasamatsu_points(self.words, self.curves)}
        self.assertEqual(len(got), 11)
        self.assertEqual(sorted(got), sorted(["ゴール"] + list("①②③④⑤⑥⑦⑧⑨⑩")))
        self.assertEqual(got["ゴール"]["vals"], [13.0, 12.0, 11.5, 10.0])
        self.assertEqual(got["ゴール"]["offsets"], [1.0, 3.0, 5.0, 7.0])
        self.assertEqual(got["⑤"]["vals"], [12.5, 11.5, 11.0, 10.5])

    def test_printed_average_is_kept_even_when_it_differs(self):
        # ⚠横に並ぶ 5 地点は整数で刷ってあり、4 つの算術平均(11.5)と合わない。**印字をそのまま**
        got = {p["section"]: p for p in kasamatsu_points(self.words, self.curves)}
        self.assertEqual(got["④"]["avg"], 12.0)
        self.assertEqual(sum(got["④"]["vals"]) / 4, 11.5)
        self.assertEqual(got["ゴール"]["avg"], 11.6)

    def test_invisible_white_numbers_break_a_point(self):
        # ⛔白い字(コースの絵の中に 12 字)を残すと ⑧ の 4 値がずれる= 実地で踏んだ落とし穴
        self.assertEqual(len(self.f["words"]) - len(self.words), 5)
        bad = {p["section"]: p for p in kasamatsu_points(self.f["words"], self.curves)}
        self.assertNotEqual(bad["⑧"]["vals"], [13.0, 12.0, 11.0, 10.0])

    def test_weather_and_cond_come_from_the_circle(self):
        # 字だけ読むと 4 つとも出てどれか分からない= 丸(曲線)の中にある字を採る
        text = [w["text"] for w in self.words]
        for w in ("晴", "曇", "雨", "雪"):
            self.assertIn(w, text)
        self.assertEqual(circled(self.words, self.curves, set(WEATHER_WORDS)), "曇")
        self.assertEqual(circled(self.words, self.curves, set(COND_WORDS)), "稍重")

    def test_news_list_takes_only_sand_articles(self):
        html = ('<li><time>2026/09/07</time><div class="news_link">'
                '<a href="/news/detail/1484">令和8年度第9回開催前砂厚測定について</a></div></li>'
                '<li><time>2026/09/10</time><div class="news_link">'
                '<a href="/news/detail/1488">令和８年度　第９回 笠松競馬開催成績</a></div></li>')
        self.assertEqual(kasamatsu_news_items(html),
                         [("https://www.kasamatsu-keiba.com/news/detail/1484", "2026-09-07",
                           "令和8年度第9回開催前砂厚測定について")])


class SmallPartsTest(unittest.TestCase):
    def test_num_list_drops_what_it_cannot_read(self):
        self.assertEqual(num_list("14.5-14-12.5"), [14.5, 14.0, 12.5])
        self.assertEqual(num_list("１４.５-14"), [14.5, 14.0])
        self.assertEqual(num_list("14.5-—-12"), [14.5, 12.0])
        self.assertEqual(num_list(""), [])

    def test_norm_date(self):
        self.assertEqual(norm_date("令和8年9月7日"), "2026-09-07")
        self.assertEqual(norm_date("令和７年度　第16回"), None)
        self.assertEqual(norm_date("2026年9月10日"), "2026-09-10")
        self.assertEqual(norm_date("2026年09月11日"), "2026-09-11")
        self.assertEqual(norm_date("2026/09/07"), "2026-09-07")
        self.assertEqual(norm_date("2026年2月30日"), None)


if __name__ == "__main__":
    unittest.main()
