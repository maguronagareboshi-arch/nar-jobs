# -*- coding: utf-8 -*-
"""10/12 兵庫のレース割り: 提供データの騎手を足す・板(boards)だけの日も組の番号が付く。
⛔通信なし。py -3.12 -m unittest tests.test_noken_hyogo_split -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import noken_public as nk                                          # noqa: E402


def official():
    return {"date": "2026-06-08", "races": [
        {"kind": "能力検査", "dist": 820, "rows": [{"name": "アアア"}, {"name": "イイイ"}]},
        {"kind": "自主参加", "dist": 1400, "rows": [{"name": "ウウウ", "jockey": "公式"}]},
    ]}


class HyogoSplit(unittest.TestCase):
    def test_jockey_from_split(self):
        day = official()
        sp = {"races": [{"no": 1, "rows": [{"name": "アアア", "jockey": "甲"},
                                           {"name": "ウウウ", "jockey": "乙"}]}]}
        nk.hyogo_split_day(day, sp)
        rows = {r["name"]: r for g in day["races"] for r in g["rows"]}
        self.assertEqual(rows["アアア"].get("jockey"), "甲")
        self.assertEqual(rows["ウウウ"].get("jockey"), "公式")     # 公式にある値は上書きしない
        self.assertIsNone(rows["イイイ"].get("jockey"))

    def test_boards_only_day(self):
        day = official()
        sp = {"date": "2026-06-08", "races": [],
              "boards": [{"no": 1, "names": ["イイイ", "ウウウ"]}, {"no": 2, "names": ["アアア"]}]}
        st = nk.hyogo_split_day(day, sp)
        self.assertEqual(st["unknown"], 0)
        self.assertEqual([(r["no"], [x["name"] for x in r["rows"]]) for r in day["races"]],
                         [(1, ["イイイ", "ウウウ"]), (2, ["アアア"])])

    def test_unverified_day_has_group_seq_not_no(self):
        # 10/28 板と照らせていない日= 区切りだけ。⛔no は null・組の順番 group_seq
        day = official()
        sp = {"date": "2026-06-08", "unverified": True, "races": [
            {"seq": 1, "rows": [{"name": "ウウウ"}]},
            {"seq": 2, "rows": [{"name": "アアア"}, {"name": "イイイ"}]}]}
        st = nk.hyogo_split_day(day, sp)
        self.assertEqual(st["races"], 2)
        self.assertTrue(day.get("unverified"))
        self.assertEqual([(r["no"], r.get("group_seq"), [x["name"] for x in r["rows"]]) for r in day["races"]],
                         [(None, 1, ["ウウウ"]), (None, 2, ["アアア", "イイイ"])])

    def test_unverified_unknown_row_has_no_group_seq(self):
        day = official()
        sp = {"unverified": True, "races": [{"seq": 1, "rows": [{"name": "アアア"}]}]}
        nk.hyogo_split_day(day, sp)
        self.assertEqual([(r["no"], r.get("group_seq")) for r in day["races"]], [(None, 1), (None, None)])
        self.assertEqual(day["races"][-1]["kind"], nk.UNKNOWN_KIND)


class FetchUnverified(unittest.TestCase):
    def test_unverified_day_drops_no(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud", "kb"))
        import fetch_kb_noken_hyogo as f
        day = {"date": "2026-06-08", "venue": "園田", "kb_id": "2026060837",
               "races": [{"no": 1, "rows": [{"name": "ア"}]}, {"no": 2, "rows": [{"name": "イ"}]}]}
        got = f.unverified_day(day)
        self.assertTrue(got["unverified"])
        self.assertEqual([("no" in r, r["seq"]) for r in got["races"]], [(False, 1), (False, 2)])
        self.assertNotIn("boards", got)


class PushMerge(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud", "kb"))
        import push_kb_noken_split as p
        self.p = p

    def test_merge_rules(self):
        cur = {"days": {"2026-06-01": {"boards": [1], "v": "cur"},       # 板つき
                        "2026-06-02": {"unverified": True, "v": "cur"},  # R 未確認
                        "2026-06-03": {"boards": [1], "v": "cur"}}}      # 手元に無い= 残る
        local = {"days": {"2026-06-01": {"unverified": True, "v": "loc"},  # 板つきを上書きしない
                          "2026-06-02": {"boards": [1], "v": "loc"},       # 板つきが勝つ
                          "2026-06-04": {"unverified": True, "v": "loc"}}} # 新しい日は入る
        got = self.p.merge_split(cur, local)["days"]
        self.assertEqual({k: v["v"] for k, v in got.items()},
                         {"2026-06-01": "cur", "2026-06-02": "loc", "2026-06-03": "cur", "2026-06-04": "loc"})

    def test_verified_overwrites_verified(self):
        got = self.p.merge_split({"days": {"d": {"v": 1}}}, {"days": {"d": {"v": 2}}})["days"]
        self.assertEqual(got["d"]["v"], 2)

    def test_empty_current(self):
        got = self.p.merge_split({}, {"days": {"d": {"unverified": True}}})["days"]
        self.assertEqual(list(got), ["d"])


if __name__ == "__main__":
    unittest.main()
