# -*- coding: utf-8 -*-
"""§193c b オークション出典の分類 v2(13 器)。⛔通信も DB も無い。

  py -3.12 -X utf8 -m unittest tests.test_auction_groups

文は §193b の棚卸し(docs/auction_disease_inventory_20260916.md)に出た言い回しから。
⛔馬名・出品者・置き場の字は書かない(医療の部分だけ)。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud"))
import horse_health as hh  # noqa: E402


def groups(text):
    return [g for g, _w in hh._auction_terms(text)]


def details(*lines):
    return hh._auction_details(list(lines))


# 分類ごとの代表文 2 つ(⛔棚卸しに出た語だけ)
CASES = {
    "bone_joint": ["2021年3月24日の追い切り中に右前第三中手骨の骨折を発症。",
                   "なお現在、右前脚管骨内側に骨瘤が見受けられます。"],
    "tendon_ligament": ["ところが、年明けに屈腱炎が判明して長期休養に。",
                        "2022年8月、左前繋靭帯炎を発症。"],
    "hoof": ["なお現在、左前蹄に蟻洞がみられます。",
             "2023年5月5日の競走にて、左後肢挫跖のため出走取消となっています。"],
    "muscle_back": ["ただ、その一戦後に全身筋肉痛の症状が出ており、休養が必要な状態です。",
                    "レース後はトモに筋肉疲労が強く出ており、現状ではコンスタントに使えません。"],
    "respiratory": ["2023年1月に喉頭片麻痺の診断を受け手術を行いました。",
                    "2歳時よりDDSPと思われるノドの異音があります。"],
    "epistaxis": ["なお、本馬は前走のレース中に鼻出血を発症しています。",
                  "2023年6月25日の調教にて、鼻出血(2回目)を発症しています。"],
    "cardiac": ["2022年7月16日の競走中に心房細動を発症しています。",
                "先日のレース後には除細動の処置を施しました。"],
    "digestive": ["・2024年7月 疝痛発症",
                  "2017年8月5日に結腸左背方変位を整復する開腹手術を実施しています。"],
    "eye": ["また、左眼に白濁があります。",
            "2022年6月に左目の白濁で点眼治療。"],
    "skin_wound": ["なお現在、全身に皮膚病がみられます。",
                   "レースでは右後肢管外側に外傷を負いました。"],
    "fever_infection": ["2024年7月9日の競走にて、熱発のため出走取消となっています。",
                        "2021年9月19日の競走にて、感冒のため出走取消となっています。"],
    "castration": ["2019年3月9日(3歳時)に去勢手術を実施しています。",
                   "25年5月15日に去勢"],
    "symptom": ["23年8月25日に左後肢跛行のため出走取消",
                "・左前肢球節に腫脹有り"],
}

# 打ち消し= 病名の側が否定されている形(⛔事象にしない)
NEGATED = [
    "骨折等の問題はありませんでした。",
    "内視鏡検査の結果、喉頭片麻痺の症状は認められませんでした。",
    "さく癖がありますが、疝痛を発症したことはありません。",
    "鼻出血はこちらに来てからは一度も発症していません。",
    "跛行することはありませんが、歩様がややツクツクしています。",
    "筋肉などに疲れは出やすいものの、骨折などはこれまでありません。",
]
# ⛔「発症したが今は問題ない」= 事象として残す(§193b 3-3)
STILL_EVENT = [
    ("2月7日の競馬で心房細動を発症してしまいましたが、その後は問題なくレースを使えています。", "cardiac"),
    ("現在、両前脚管骨内側に骨瘤を発症していますが、痛み・熱感はありません。", "bone_joint"),
]
# 事象にも判定待ちにもしない
SILENT = [
    "現在は接着装蹄にしています。",
    "遠方への輸送の場合、健康維持のため輸送熱予防の注射をお願いしています。",
]


class AuctionGroups(unittest.TestCase):
    def test_each_group_two_sentences(self):
        for group, texts in CASES.items():
            for text in texts:
                self.assertIn(group, groups(text), "%s に入らない: %s" % (group, text))

    def test_negated_condition_is_not_an_event(self):
        for text in NEGATED:
            self.assertEqual(groups(text), [], "打ち消しの文を事象にした: %s" % text)

    def test_onset_with_good_aftermath_is_still_an_event(self):
        for text, group in STILL_EVENT:
            self.assertIn(group, groups(text), "「発症したが今は問題ない」を捨てた: %s" % text)

    def test_shoeing_and_vaccine_make_nothing(self):
        for text in SILENT:
            out, review = details(text)
            self.assertEqual(out, [], "事象にした: %s" % text)
            self.assertEqual(review, [], "判定待ちにした: %s" % text)

    def test_exam_only_and_notice_make_nothing(self):
        for text in ("レントゲン検査を実施しました。",
                     "鼻出血を含めて記載事項に関するクレーム、キャンセルには応じられません。"):
            out, review = details(text)
            self.assertEqual((out, review), ([], []), text)

    def test_symptom_only_when_nothing_else(self):
        self.assertEqual(groups("2024年12月14日の競走中に左前肢跛行を発症したため競走を中止しました。"),
                         ["symptom"])
        # 病名があるときは症状だけの分類に入れない
        self.assertNotIn("symptom", groups("右前脚に浅屈腱炎を発症し、跛行が見られます。"))

    def test_marks_and_term(self):
        out, _ = details("レース後に歩様が乱れて競走能力喪失と診断され、引退しました。")
        self.assertEqual(len(out), 1)
        _detail, group, _happened, term, lost = out[0]
        self.assertEqual((group, term, lost), ("symptom", "歩様が乱れ", True))
        out2, _ = details("2019年3月9日(3歳時)に去勢手術を実施しています。")
        self.assertEqual((out2[0][1], out2[0][3], out2[0][4]), ("castration", "去勢", False))

    def test_one_sentence_two_groups(self):
        got = groups("右前脚に浅屈腱炎、左前脚に骨瘤を発症しています。")
        self.assertEqual(sorted(got), ["bone_joint", "tendon_ligament"])

    def test_organizer_rules_untouched(self):
        # ⛔主催者出典の語表(GROUP_RULES / _groups)は 1 字も変えていない
        self.assertEqual(hh._groups("鼻出血を発症"), ["epistaxis"])
        self.assertEqual(hh._groups("右前肢跛行のため競走中止"), ["musculoskeletal"])
        self.assertEqual(hh._groups("疾病(感冒)のため出走取消"), ["disease"])
        self.assertEqual([n for n, _ in hh.GROUP_RULES],
                         ["epistaxis", "cardiac", "musculoskeletal", "accident", "disease"])


if __name__ == "__main__":
    unittest.main()
