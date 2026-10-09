# -*- coding: utf-8 -*-
"""東海の降級 笠松の一覧= P の前の印(× 補欠 # 9R)・級の 1 字・「R」の馬名・級の札の数え方(2026-10-10)。"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "cloud"))
import tokai_demotion as T  # noqa: E402


def read(s):
    return [(h.group(2), int(h.group(5)), "".join(re.findall(r"×|補欠|#", h.group(4) or ""))) for h in T.HK.finditer(s)]


class KsMarks(unittest.TestCase):
    def test_marks_skipped_p_taken(self):
        self.assertEqual(read("ウィングコマンダー 4R ×1800 後藤佑 57"), [("ウィングコマンダー", 1800, "×")])
        self.assertEqual(read("スティールアクター 12R補欠#12688 角田輝 58"), [("スティールアクター", 12688, "補欠#")])
        self.assertEqual(read("ジャスパーノワール 5R×12R補欠# 4875 角田輝 57"), [("ジャスパーノワール", 4875, "×補欠#")])
        self.assertEqual(read("ゴールドレーン 補欠 # 3170 塚田隆 55"), [("ゴールドレーン", 3170, "補欠#")])
        self.assertEqual(read("コンストラクション 3R # 860 加藤幸"), [("コンストラクション", 860, "#")])
        self.assertEqual(read("チュッカ 722 栗本陽"), [("チュッカ", 722, "")])

    def test_r_not_a_name(self):
        # 直す前は「9R」の R を馬名にして P 1192 の馬「R」を作っていた
        self.assertEqual(read("イエローガーデン 10R #9R # 1192 後藤佑 55"), [("イエローガーデン", 1192, "##")])

    def test_class_letter_between_name_and_p(self):
        self.assertEqual(read("ヨサリ B 4456 笹野博 57"), [("ヨサリ", 4456, "")])

    def test_no_p_no_row(self):
        # 中央・他場の馬(P なし)と馬名だけの行は読まない
        self.assertEqual(read("モーブプリエール 補欠 # 鈴木慎 55"), [])
        self.assertEqual(read("ハシリ 12R補欠#"), [])

    def test_class_labels_not_counted(self):
        self.assertEqual(len(T.CAND_KS.findall("C19 800")), 0)
        self.assertEqual(len(T.CAND_KS.findall("2R⇔1R 10R")), 0)
        self.assertEqual(len(T.CAND_KS.findall("ウィングコマンダー 4R ×1800 後藤佑")), 1)


if __name__ == "__main__":
    unittest.main()
