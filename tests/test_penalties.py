# -*- coding: utf-8 -*-
"""§111 制裁の読み取り(cloud/penalties.py の純関数)の固定テスト。通信なし。

  py -3.12 -m unittest tests.penalties_test -v

⛔原本(PDF)は置かない= 実測で分かった**書き方**だけを、作り物の名前で再現する。
⛔実在の人名・馬名は使わない(名簿も作り物)。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import penalties as pen                                            # noqa: E402

# その日その場の名簿(nar_runs の略称)。⛔作り物
NAMES = {"jockey": {"試験騎", "別人騎"}, "trainer": {"試験調"}}

# 実測の 3 通りの語順(役が先 / 名前が先 / 馬名のあとに役)。PDF は字が空白で割れるので、
# 1 字ずつ空けた形でも同じに読めることを確かめる
BLOCK_ROLE_FIRST = "制 裁 【 制 裁 】 騎 手 試 験 騎 男 は 7 番 テ ス ト 号 に 騎 乗 し た と こ ろ 、" \
    " 内 斜 行 し た た め 戒 告 さ れ た 。\nコ ー ナ ー 通 過 順 1 - 2 - 3"
BLOCK_NAME_FIRST = "制裁(調教師処分)試験調子調教師はテスト号を出走させようとしたところ、" \
    "競走調教が十分でなかったため戒告された。\nハロンタイム12.1-12.3"
BLOCK_AFTER_HORSE = "制裁8番テスト号の騎手試験騎男は、騎乗法に適切を欠いたため戒告となった。\n上がり3F:36.7"
# 馬の話= 人がいないので読まない
BLOCK_HORSE = "制裁11番テスト号は、競走中鼻出血を発症したため出走制限となった。30日\nコーナー通過順5,8"
# 期間つき(騎乗停止)
BLOCK_RANGE = "制裁「騎手試験騎男は、テスト号に騎乗したところ、扶助操作に適切を欠いたため、" \
    "令和8年8月21日から令和8年9月7日までの実効2日間騎乗停止した。」\n通過順1-2"

# ---- §111b(2026 の 334 行を見て出た 5 点)。⛔どれも実測の**書き方**だけを作り物で再現
# #1 前の文の括弧書きが「)」「」の形で次の文の頭に付く(大井)
BLOCK_DECOR = "制裁≪保安措置≫「9号馬テスト号は、発走の調教が十分でないと認められ、" \
    "令和8年9月1日から令和8年11月29日までの90日間出走を停止された。" \
    "(枠内起立大転倒馬負傷競走除外)」\n" \
    "「調教師試験調男は、テスト号を出走させたところ、発走の調教が十分でなく、" \
    "競馬の公正を害したので戒告された。」\nコーナー通過順1角(1,11)"
# #3 頁またぎ= 脚注と頁番号が挟まり、続きに「制裁」のラベルが再掲される(高知・名古屋)
BLOCK_PAGE_BREAK = "制裁騎手試験騎男は7番テスト号に騎乗したところ、発走後、むちの使用に" \
    "関するガイドラインに抵触したた\n2026/01/12 09:30作 成\n40/ 40\n" \
    "制裁め、戒告。\nコーナー通過順1コーナー5,9"
# #4 「制裁」の次の見出しが「変更後の騎乗変更」(船橋)= ここで止める
BLOCK_CHANGE = "制裁調教師試験調男は、テスト号を出走させようとしたところ、届け出を怠ったことは、" \
    "競馬の公正を害したため戒告した。\n" \
    "変更後の騎乗変更「テスト号の騎手試験騎男は負傷のため別人騎男に騎乗変更となった。」\n" \
    "コーナー通過順2角8,7"
# #5 調教師の戒告に付く「賞典を停止」も期間の列に入る(川崎・水沢・盛岡)
BLOCK_SHOTEN = "制裁【制裁】調教師試験調男は、テスト号を出走させたところ、競走調教が十分でなく、" \
    "競馬の公正を害したので戒告され、令和8年8月21日から令和8年9月7日までの実効2日間" \
    "賞典を停止された。\nコーナー通過順1角3,8"


class BlockTest(unittest.TestCase):
    def test_block_ends_at_next_head(self):
        got = pen.penalty_blocks(BLOCK_ROLE_FIRST)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].endswith("戒告された。"), got[0])
        self.assertNotIn("コーナー", got[0])

    def test_wrapped_line_is_joined(self):
        text = "制裁騎手試験騎男は、内斜行したため戒告さ\nれた。\n上がり3F:36.7"
        got = pen.penalty_blocks(text)
        self.assertEqual(got, ["騎手試験騎男は、内斜行したため戒告された。"])

    def test_no_penalty_row(self):
        self.assertEqual(pen.penalty_blocks("売得金1,000円\nコーナー通過順1-2"), [])


class SentenceTest(unittest.TestCase):
    def test_only_the_penalty_label_is_dropped(self):
        # §111b #1 先頭の【制裁】は飾りなので落とす。⛔【出走停止】は中身なので残す
        got = pen.sentences("【制裁】騎手Aは戒告された。【出走停止】2番テスト号は停止された。")
        self.assertEqual(len(got), 2)
        self.assertTrue(got[0].startswith("騎手A"), got[0])
        self.assertTrue(got[1].startswith("【出走停止】"), got[1])

    def test_quotes_are_dropped(self):
        # §111b #1 「」だけの文は消える・先頭の「」は落とす
        got = pen.sentences("「騎手Aは戒告された。」「騎手Bは注意された。」")
        self.assertEqual(got, ["騎手Aは戒告された。", "騎手Bは注意された。"])

    def test_previous_parenthesis_is_returned_not_dropped(self):
        # §111b #1 「(…)」「」で始まる文の括弧書きは**前の文**のもの= 捨てずに戻す
        got = pen.sentences("「9号馬は出走を停止された。(枠内起立)」「調教師Aは戒告された。」")
        self.assertEqual(got, ["9号馬は出走を停止された。(枠内起立)", "調教師Aは戒告された。"])


class KindTest(unittest.TestCase):
    def test_priority(self):
        self.assertEqual(pen.kind_of("…2日間騎乗停止した。"), "騎乗停止")
        self.assertEqual(pen.kind_of("…戒告され、賞典を停止された。"), "戒告")
        self.assertEqual(pen.kind_of("…過怠金1万円を課された。"), "過怠金")
        self.assertEqual(pen.kind_of("…注意された。"), "注意")
        self.assertEqual(pen.kind_of("…出走できない。"), "その他")


class Fix111bTest(unittest.TestCase):
    """§111b で直した 5 点。⛔1 点 1 本。"""
    NAMES = {"jockey": {"試験騎", "別人騎"}, "trainer": {"試験調"}}

    def read(self, text):
        return pen.read_penalties("川崎", "2026-08-21", [(7, text)], self.NAMES,
                                  "https://www.keiba.go.jp/seisekipdf/20260821/21/x.pdf", "a" * 64)

    def test_1_decoration_is_dropped_and_parenthesis_returned(self):
        rows, _stats = self.read(BLOCK_DECOR)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["detail"].startswith("調教師試験調男は"), rows[0]["detail"])
        self.assertNotIn("」", rows[0]["detail"])
        # 前の文(馬の話)へ戻した括弧書きは、人の行ではないので出ないが、捨ててもいない
        got = pen.sentences(pen.penalty_blocks(BLOCK_DECOR)[0])
        self.assertTrue(got[0].endswith("(枠内起立大転倒馬負傷競走除外)"), got[0])

    def test_2_stop_riding_wording_is_a_suspension(self):
        self.assertEqual(pen.kind_of("…2日間騎乗を停止された。"), "騎乗停止")
        self.assertEqual(pen.kind_of("…10日間騎乗を停止(2月26日、27日)された。"), "騎乗停止")
        # ⛔「賞典を停止」は別物= 戒告のまま
        self.assertEqual(pen.kind_of("…戒告され、2日間賞典を停止された。"), "戒告")

    def test_3_page_footer_is_dropped_and_sentence_is_joined(self):
        blocks = pen.penalty_blocks(BLOCK_PAGE_BREAK)
        self.assertEqual(len(blocks), 1, blocks)
        self.assertNotIn("作成", blocks[0])
        self.assertTrue(blocks[0].endswith("戒告。"), blocks[0])
        rows, _stats = self.read(BLOCK_PAGE_BREAK)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "戒告")

    def test_4_ride_change_is_a_new_row_head(self):
        blocks = pen.penalty_blocks(BLOCK_CHANGE)
        self.assertEqual(len(blocks), 1, blocks)
        self.assertNotIn("騎乗変更", blocks[0])
        rows, _stats = self.read(BLOCK_CHANGE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person_kind"], "trainer")
        self.assertEqual(rows[0]["kind"], "戒告")

    def test_5_prize_suspension_uses_the_same_columns(self):
        rows, _stats = self.read(BLOCK_SHOTEN)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "戒告")      # ⛔賞典停止は戒告のまま
        self.assertTrue(rows[0]["prize_suspended"])   # 2026-10-17 印は prize_suspended
        self.assertEqual(rows[0]["suspension_from"], "2026-08-21")
        self.assertEqual(rows[0]["suspension_through"], "2026-09-07")
        self.assertTrue(rows[0]["detail"].startswith("調教師試験調男は"), rows[0]["detail"])


class SuspensionTest(unittest.TestCase):
    def test_range_is_read(self):
        self.assertEqual(pen.suspension("令和8年8月21日から令和8年9月7日までの実効2日間"),
                         ("2026-08-21", "2026-09-07"))

    def test_list_form_is_not_guessed(self):
        # ⛔「9月1日、2日の2日間」は範囲ではない= 推測しない
        self.assertEqual(pen.suspension("令和8年9月1日、2日の2日間騎乗停止した。"), (None, None))

    def test_broken_date(self):
        self.assertEqual(pen.suspension("令和8年13月45日から令和8年99月1日まで"), (None, None))


class PersonTest(unittest.TestCase):
    def test_role_first(self):
        self.assertEqual(pen.find_person("騎手試験騎男は、内斜行したため戒告された。", NAMES),
                         ("jockey", "試験騎"))

    def test_name_first(self):
        self.assertEqual(pen.find_person("試験調子調教師はテスト号を出走させた。", NAMES),
                         ("trainer", "試験調"))

    def test_after_horse_name(self):
        self.assertEqual(pen.find_person("8番テスト号の騎手試験騎男は、戒告となった。", NAMES),
                         ("jockey", "試験騎"))

    def test_role_word_without_name_is_not_a_person(self):
        # ⛔「騎手が落馬」= 人名ではない(名簿に無い)ので出さない
        self.assertIsNone(pen.find_person("4号馬テスト号は、騎手が落馬したため除外した。", NAMES))

    def test_two_people_is_not_guessed(self):
        self.assertIsNone(pen.find_person("騎手試験騎男と騎手別人騎男は戒告された。", NAMES))

    def test_abbreviation_is_not_always_contiguous(self):
        # ⛔実測: 佐々木功→佐々功・渋谷信博→渋谷博 のように、略称は本名の**連続した一部ではない**
        names = {"jockey": set(), "trainer": {"試々調"}}
        self.assertEqual(pen.find_person("調教師試々験調はテスト号を出走させた。", names),
                         ("trainer", "試々調"))
        # ⛔離れすぎているものは当てない(別人に当たる)
        self.assertIsNone(pen.find_person("調教師試々あいうえおかき調はテスト号を出走させた。", names))


class ReadTest(unittest.TestCase):
    URL = "https://www.keiba.go.jp/seisekipdf/20260821/21/20260821_kawasaki.pdf"
    HASH = "a" * 64

    def read(self, text, race_no=7):
        return pen.read_penalties("川崎", "2026-08-21", [(race_no, text)], NAMES, self.URL, self.HASH)

    def test_three_orders_all_read(self):
        for text in (BLOCK_ROLE_FIRST, BLOCK_NAME_FIRST, BLOCK_AFTER_HORSE):
            rows, _stats = self.read(text)
            self.assertEqual(len(rows), 1, text[:20])
            self.assertEqual(rows[0]["kind"], "戒告")
            self.assertEqual(rows[0]["race_no"], 7)
            self.assertEqual(rows[0]["track"], "川崎")
            self.assertEqual(len(rows[0]["penalty_id"]), 64)

    def test_horse_row_is_counted_not_written(self):
        # 2026-10-17 馬への措置は行にする。ただし名簿に馬が居なければ出さない(数えるだけ)
        rows, stats = self.read(BLOCK_HORSE)
        self.assertEqual(rows, [])
        # 「…出走制限となった。」は馬の措置(名簿に居ない)= horse_unmatched・「30日」は措置の語なし= no_person
        self.assertEqual(stats["horse_unmatched"], 1)
        self.assertEqual(stats["no_person"], 1)

    def test_suspension_columns(self):
        rows, _stats = self.read(BLOCK_RANGE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "騎乗停止")
        self.assertEqual(rows[0]["suspension_from"], "2026-08-21")
        self.assertEqual(rows[0]["suspension_through"], "2026-09-07")

    def test_race_no_out_of_range_is_null(self):
        rows, _stats = self.read(BLOCK_AFTER_HORSE, race_no=None)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["race_no"])

    def test_same_row_twice_has_same_id(self):
        a, _ = self.read(BLOCK_ROLE_FIRST)
        b, _ = self.read(BLOCK_ROLE_FIRST)
        self.assertEqual(a[0]["penalty_id"], b[0]["penalty_id"])

    def test_detail_is_capped(self):
        long_text = "制裁騎手試験騎男は、" + ("あ" * 500) + "ため戒告された。\n通過順1"
        rows, _stats = self.read(long_text)
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(rows[0]["detail"]), pen.DETAIL_MAX)


# ---- §111c 本文の馬番 → その日の名簿の馬名。⛔実在の馬名は使わない(名簿も作り物)
# 名簿に無い馬番(5番)の形。⛔埋めずに空のまま出す
BLOCK_UNKNOWN_UMABAN = "制裁騎手試験騎男は5番テスト号に騎乗したところ、内斜行したため戒告された。\n通過順1"
NAMES_H = {"jockey": {"試験騎", "別人騎"}, "trainer": {"試験調"},
           "horse": {(7, 7): "テストイチゴウ", (7, 8): "テストニゴウ", (7, 1): "テストサンゴウ"}}


class UmabanTest(unittest.TestCase):
    """⛔書いてある形だけを読む(推測しない)。実測 2026-09-12 の 347 行で出た 3 通り。"""

    def test_three_shapes(self):
        self.assertEqual(pen.umaban_of("騎手試験騎男は7番テスト号に騎乗したところ、内斜行し"), 7)
        self.assertEqual(pen.umaban_of("2番テスト号の騎手試験騎男は、注意義務違反。"), 2)
        self.assertEqual(pen.umaban_of("(調教師の処分)試験調男調教師は、第1号馬テスト号を出走させ"), 1)
        self.assertEqual(pen.umaban_of("1号馬騎乗試験騎男騎手は、外斜行し"), 1)

    def test_zenkaku(self):
        self.assertEqual(pen.umaban_of("調教師試験調男は９番テスト号を出走させたところ"), 9)

    def test_first_number_wins(self):
        # ⚠実測では 1 文に番号が 2 つ出る行は 0 件。出たときは**最初の 1 つ**
        self.assertEqual(pen.umaban_of("騎手試験騎男は7番テスト号に騎乗し、第2障害上で転倒し"), 7)

    def test_not_a_umaban(self):
        # 「N日間」「令和N年M月D日」は馬番ではない= うしろが「番」「号馬」のときだけ読む
        self.assertIsNone(pen.umaban_of("騎手試験騎男は、令和8年9月6日、7日の2日間賞典を停止する。"))
        # 馬名だけで番号が無い行(実測 347 行中 126 行)は**そのまま空**
        self.assertIsNone(pen.umaban_of("調教師試験調男はテスト号を出走させたところ"))
        self.assertIsNone(pen.umaban_of(""))
        self.assertIsNone(pen.umaban_of(None))

    def test_out_of_range(self):
        self.assertIsNone(pen.umaban_of("0番テスト号は"))
        self.assertIsNone(pen.umaban_of("19番テスト号は"))


class HorseNameTest(unittest.TestCase):
    URL = "https://www.keiba.go.jp/seisekipdf/20260821/21/20260821_kawasaki.pdf"
    HASH = "a" * 64

    def read(self, text, names=NAMES_H, race_no=7):
        return pen.read_penalties("川崎", "2026-08-21", [(race_no, text)], names, self.URL, self.HASH)

    def test_name_comes_from_roster_not_from_text(self):
        # 本文は「7番テスト号」だが、入るのは**名簿の側の馬名**
        rows, stats = self.read(BLOCK_ROLE_FIRST)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["horse_name"], "テストイチゴウ")
        self.assertEqual(stats["horse_named"], 1)

    def test_after_horse_shape(self):
        rows, _stats = self.read(BLOCK_AFTER_HORSE)          # 「8番テスト号の騎手…」
        self.assertEqual(rows[0]["horse_name"], "テストニゴウ")

    def test_unknown_umaban_stays_empty(self):
        # 名簿にない馬番は埋めない(⛔取り違えより無表示)
        rows, stats = self.read(BLOCK_UNKNOWN_UMABAN)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["horse_name"])
        self.assertEqual(stats["horse_named"], 0)

    def test_no_umaban_stays_empty(self):
        rows, _stats = self.read(BLOCK_NAME_FIRST)           # 番号の無い形
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["horse_name"])

    def test_roster_without_horses_still_works(self):
        # 馬の名簿が無くても落ちない(古い呼び方)
        rows, _stats = self.read(BLOCK_ROLE_FIRST, names=NAMES)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["horse_name"])

    def test_id_does_not_move(self):
        # ⛔penalty_id の材料に馬名は入れない= 既にある行の id は動かない
        a, _ = self.read(BLOCK_ROLE_FIRST, names=NAMES_H)
        b, _ = self.read(BLOCK_ROLE_FIRST, names=NAMES)
        self.assertEqual(a[0]["penalty_id"], b[0]["penalty_id"])


if __name__ == "__main__":
    unittest.main()
