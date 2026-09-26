# -*- coding: utf-8 -*-
"""§196b 第 2 段 cloud/nankan_hist.py の純関数= 開催の区切り・official/recon の切替・carry・null の伝播。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import nankan_hist as H  # noqa: E402


def it(d, mend, pts, kaku=None, remote=False, no=1):
    return {"d": d, "mend": mend, "pts": pts, "kaku": kaku, "remote": remote, "no": no}


class T(unittest.TestCase):
    def test_meetings(self):
        # 休みの日を挟んでも 1 開催(間 4 日以内)・次の開催は別・4 月で回を数え直す
        idx = H.meetings({"川崎": {"2025-08-21", "2025-08-22", "2025-08-25", "2025-08-26", "2025-09-08",
                                  "2026-03-30", "2026-03-31", "2026-04-01"}})
        self.assertEqual(idx[("川崎", "2025-08-26")][:2], ("2025-08-26", "2025-08-21"))
        self.assertEqual(idx[("川崎", "2025-08-26")][3], 4)                   # 26 日は 4 日目(馬ページの raceid と同じ)
        self.assertEqual(idx[("川崎", "2025-09-08")][0], "2025-09-08")
        self.assertEqual(idx[("川崎", "2026-04-01")][1:3], ("2026-04-01", 1))  # 新年度の 1 回目
        self.assertEqual(idx[("川崎", "2026-03-31")][0], "2026-03-31")

    def test_official_and_recon(self):
        # いま 500(asof 9/15)。9/12 開催で +100・8/20 開催で +50= 8/20 の後は 400・9/12 の後が主催者の値
        rows = H.hist_rows("1", 500, "2026-09-15", [it("2026-08-18", "2026-08-20", 50), it("2026-09-10", "2026-09-12", 100)])
        self.assertEqual([(r["meet_end"], r["points"], r["src"]) for r in rows],
                         [("2026-08-20", 400, "recon"), ("2026-09-12", 500, "official")])
        # 反映前の開催(最終日 >= asof)= いまの値に足す
        rows = H.hist_rows("1", 500, "2026-09-15", [it("2026-09-14", "2026-09-18", 60)])
        self.assertEqual((rows[0]["points"], rows[0]["src"]), (560, "recon"))
        # 反映済みの遠征が後ろにあれば、主催者の値は開催の直後の値ではない= recon
        rows = H.hist_rows("1", 500, "2026-09-15", [it("2026-09-10", "2026-09-12", 100), it("2026-09-13", "2026-09-13", 30.4, remote=True)])
        self.assertEqual((rows[0]["points"], rows[0]["src"]), (470, "recon"))  # 469.6 を四捨五入

    def test_anchor_rows_are_kept(self):
        # 既にある official の行(8/20= 420)は点を変えず(同じ値で書く= 級だけ入れ直す)、それより古い開催はその行から引く
        items = [it("2026-07-01", "2026-07-03", 20), it("2026-08-18", "2026-08-20", 50), it("2026-09-10", "2026-09-12", 100)]
        rows = H.hist_rows("1", 500, "2026-09-15", items, anchors={"2026-08-20": 420})
        self.assertEqual([(r["meet_end"], r["points"], r["src"]) for r in rows],
                         [("2026-07-03", 370, "recon"), ("2026-08-20", 420, "official"), ("2026-09-12", 500, "official")])

    def test_null_propagates_to_older(self):
        # 決められない走(8/20)より古い開催は null・新しい側は値あり
        items = [it("2026-07-01", "2026-07-03", 20), it("2026-08-18", "2026-08-20", None), it("2026-09-10", "2026-09-12", 100)]
        rows = H.hist_rows("1", 500, "2026-09-15", items)
        self.assertEqual([r["points"] for r in rows], [None, 400, 500])

    def test_carry(self):
        items = [it("2026-07-01", "2026-07-03", 0), it("2026-08-18", "2026-08-20", 0, kaku="C2"),
                 it("2026-09-10", "2026-09-12", 0), it("2026-09-11", "2026-09-12", 0, no=2)]
        rows = H.hist_rows("1", 0, "2026-09-15", items)
        self.assertEqual([(r["kaku_ran"], r["kaku_src"]) for r in rows], [(None, None), ("C2", "race"), ("C2", "carry")])
        self.assertEqual(rows[2]["last_run"], "2026-09-11")

    def test_carry_not_across_half(self):
        # §294b 5/28 の C1 は 7/1 の見直しをまたいで引き継がない(点が無ければ null)
        items = [it("2026-05-28", "2026-05-29", 0, kaku="C1"), it("2026-07-16", "2026-07-17", 0),
                 it("2026-06-10", "2026-06-12", 0)]
        rows = H.hist_rows("1", None, "2026-09-15", items)
        self.assertEqual([(r["meet_end"], r["kaku_ran"], r["kaku_src"]) for r in rows],
                         [("2026-05-29", "C1", "race"), ("2026-06-12", "C1", "carry"), ("2026-07-17", None, None)])

    def test_calc_from_santei(self):
        # §294b 混合戦= 算定日の点 × 算定日の半期の基準表 × 馬齢。2021 年生= 2026 年 5 歳
        items = [it("2026-05-01", "2026-05-02", 0), dict(it("2026-08-10", "2026-08-12", 0), santei="2026-07-20"),
                 dict(it("2026-03-10", "2026-03-12", 0), santei="2026-02-20")]
        rows = H.hist_rows("2021100001", 750, "2026-09-15", items, birth_year=2021)
        got = {r["meet_end"]: (r["kaku_ran"], r["kaku_src"]) for r in rows}
        self.assertEqual(got["2026-03-12"], ("C1", "calc"))    # 上半期 5 歳 C1 の線 700 <= 750
        self.assertEqual(got["2026-08-12"], ("C2", "calc"))    # 下半期 5 歳 C1 の線 800 > 750= C2
        self.assertEqual(got["2026-05-02"], ("C1", "carry"))   # 同じ半期の前の値
        self.assertEqual(H.kaku_by_points(900, "2026-08-01", 2023), "B3")  # 3 歳 下半期 B3 の線 800
        self.assertIsNone(H.kaku_by_points(300, "2026-08-01", 2023))        # 3 歳の C2 は 10 月から(12(2))= 未格付
        self.assertEqual(H.kaku_by_points(300, "2026-10-05", 2023), "C2")
        self.assertEqual(H.kaku_by_points(750, "2025-12-25", 2021, "2026-01-01"), "C1")  # 1/1 の開催= 上半期の表・5 歳
        self.assertEqual(H.kaku_by_points(0, "2026-08-01", 2020), "C3")

    def test_santei_index(self):
        idx = H.meetings({"川崎": {"2026-09-07", "2026-09-08"}, "大井": {"2026-08-31", "2026-09-04"},
                          "船橋": {"2026-08-24", "2026-08-28"}, "浦和": {"2026-08-17"}})
        s = H.santei_index(idx)
        self.assertEqual(s[("川崎", "2026-09-08")], "2026-08-28")   # 前々開催の最終日(川崎 第 7 回の番組と同じ)
        self.assertIsNone(s[("浦和", "2026-08-17")])

    def test_kaku_of_race(self):
        self.assertEqual(H.kaku_of_race("Ｃ３(二)", "普通"), "C3")
        self.assertIsNone(H.kaku_of_race("オーガスト賞Ａ２二Ｂ１二選抜特別", "特別"))   # 混合
        self.assertEqual(H.kaku_of_race("こと座特別Ｃ１二三四選抜特別", "特別"), "C1")  # §294b 単一級の選抜= その級
        self.assertEqual(H.kaku_of_race("特選Ｃ２選抜牝馬", "普通"), "C2")             # §294b 浦和 9/25 7R
        self.assertIsNone(H.kaku_of_race("エトワール賞Ａ２下選定馬", "特別"))            # 選定= 格上編成あり
        self.assertIsNone(H.kaku_of_race("Ｃ１イＣ２ア選抜馬", "特別"))                  # 混合の選抜
        self.assertIsNone(H.kaku_of_race("日吉オープンＡ１下", "特別"))                  # オープン
        self.assertIsNone(H.kaku_of_race("３歳八 九", "普通"))

    def test_run_points(self):
        race = {"race_kind": "特別", "race_name": "Ｂ３二選抜特別", "condition": "一般", "race_date": "2026-03-25"}
        self.assertEqual(H.run_points({"fin": 2}, race, 1), (96, "ok"))
        self.assertEqual(H.run_points({"fin": 2}, race, 2)[0], (96 + 60) / 2)          # 同着は等分
        off = dict(race, nankan={"pts": [9, 8, 7, 6, 5]})
        self.assertEqual(H.run_points({"fin": 3}, off, 1), (7, "公式"))                 # 結果ページの値を優先
        sg = {"race_kind": "重賞", "race_name": "東京記念３上オープン重賞", "condition": "3歳以上", "race_date": "2025-09-17"}
        self.assertEqual(H.run_points({"fin": 1}, sg, 1)[0], None)                     # S 格で pts なし= 決めない
        self.assertEqual(H.run_points({"fin": 1}, dict(sg, nankan={"pts": [3100, 1085, 620, 310, 155]}), 1)[0], 3100)
        self.assertEqual(H.run_points({"fin": None, "note": "競走中止"}, race, 1), (0, "中止=0"))
        self.assertEqual(H.run_points({"fin": None, "note": ""}, race, 1), (None, "着順なし"))
        self.assertEqual(H.run_points({"fin": 9}, sg, 1), (0, "ok"))

    def test_cancelled_race(self):
        race = {"race_kind": "普通", "race_name": "Ｃ２(一)", "condition": "一般", "race_date": "2026-03-25"}
        self.assertEqual(H.run_points({"fin": None, "note": ""}, dict(race, cancelled="refund"), 1), (0, "取り止め"))
        self.assertEqual(H.run_points({"fin": None, "note": ""}, dict(race, cancelled=""), 1), (None, "着順なし"))

    def test_disqualified(self):
        race = {"race_kind": "普通", "race_name": "Ｃ２(一)", "condition": "一般", "race_date": "2026-03-25"}
        self.assertEqual(H.run_points({"fin": None, "note": "失格"}, race, 1), (0, "失格=0"))


if __name__ == "__main__":
    unittest.main()
