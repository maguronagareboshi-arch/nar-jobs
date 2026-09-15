# -*- coding: utf-8 -*-
"""紙面の馬の特定(cloud/paper_pdf.py identify_horse / rows_to_write)。⛔ネット・DB なし。
実行: py -3.12 -X utf8 -m unittest tests.paper_match_test"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud import paper_pdf as pp  # noqa: E402
from cloud import paper_first3f as pf  # noqa: E402


def run(date, venue, fin, sec, f3=None):
    return {"date": date, "venue": venue, "finish": fin, "time_sec": sec, "first3f": f3}


def db(name, date, track, no, uma, fin, sec):
    return {"horse_name": name, "race_date": date, "track": track, "race_no": no, "runner_number": uma, "finish": fin, "time_sec": sec}


DB = [db("タイセイアダマス", "2026-09-06", "水沢", 4, 3, 2, 83.6), db("タイセイアダマス", "2026-08-11", "盛岡", 8, 2, 10, 101.3),
      db("メリア", "2026-09-01", "盛岡", 5, 11, 4, 74.5), db("ベツノウマ", "2026-07-27", "盛岡", 12, 9, 9, 100.7)]


class Identify(unittest.TestCase):
    def test_two_runs_same_name(self):
        runs = [run("2026-09-06", "水沢", 2, 83.6, 37.9), run("2026-08-11", "盛岡", 10, 101.3, 37.1), run("2026-06-01", "盛岡", 3, 90.0)]
        name, why, hits = pp.identify_horse(runs, DB)
        self.assertEqual((name, why, sorted(hits)), ("タイセイアダマス", "特定(2 走一致)", [0, 1]))

    def test_one_run_is_held(self):
        name, why, _ = pp.identify_horse([run("2026-09-01", "盛岡", 4, 74.5), run("2026-05-01", "水沢", 1, 80.0)], DB)
        self.assertEqual((name, why), (None, "一致 1 走"))

    def test_split_names_are_held(self):
        runs = [run("2026-09-06", "水沢", 2, 83.6), run("2026-08-11", "盛岡", 10, 101.3), run("2026-07-27", "盛岡", 9, 100.7)]
        name, why, _ = pp.identify_horse(runs, DB)
        self.assertIsNone(name)
        self.assertTrue(why.startswith("名が割れる"), why)

    def test_scratched_ignored_and_dead_heat_not_counted(self):
        dh = DB + [db("ドウチャク", "2026-08-11", "盛岡", 8, 5, 10, 101.3)]
        runs = [run("2026-08-03", "盛岡", None, None), run("2026-09-06", "水沢", 2, 83.6), run("2026-08-11", "盛岡", 10, 101.3)]
        name, why, _ = pp.identify_horse(runs, dh)
        self.assertEqual((name, why), (None, "一致 1 走(場・日・着順・時計が同じ 2 頭)"))

    def test_split_run_resolved_after_identified(self):
        # 盛岡 8/18 の実例= 別のレースの 7 着が同じ 1:28.3 で 2 頭。票には数えないが、特定した馬の行はその走に使う
        dh = DB + [db("タイセイアダマス", "2026-08-18", "盛岡", 3, 2, 7, 88.3), db("ホカノウマ", "2026-08-18", "盛岡", 1, 2, 7, 88.3)]
        runs = [run("2026-09-06", "水沢", 2, 83.6, 37.9), run("2026-08-18", "盛岡", 7, 88.3, 36.8), run("2026-08-11", "盛岡", 10, 101.3)]
        name, why, hits = pp.identify_horse(runs, dh)
        self.assertEqual((name, why, sorted(hits), hits[1]["race_no"]), ("タイセイアダマス", "特定(2 走一致)", [0, 1, 2], 3))

    def test_rows_split_first2f_below_1200(self):
        runs = [run("2026-09-06", "水沢", 2, 83.6, 37.9), run("2026-08-11", "盛岡", 10, 101.3, 25.5), run("2026-07-01", "盛岡", 1, 99.0, None)]
        hits = {0: DB[0], 1: DB[1], 2: DB[1]}
        dist = {("水沢", "2026-09-06", 4): 1300, ("盛岡", "2026-08-11", 8): 1000}
        rows = pp.rows_to_write("タイセイアダマス", runs, hits, dist, {"ref": "20260914_03Ra4.pdf", "page": 1, "col": 6})
        self.assertEqual([(r["track"], r["umaban"], r["first3f"], r["first2f"], r["src_ref"], r["src_pos"]) for r in rows],
                         [("水沢", 3, 37.9, None, "20260914_03Ra4.pdf", "右から6列 上から1段"),
                          ("盛岡", 2, None, 25.5, "20260914_03Ra4.pdf", "右から6列 上から2段")])
        self.assertNotIn("src_url", rows[0], "出どころの列は src_ref(ファイル名だけ)")


class ListPdfs(unittest.TestCase):
    def test_both_kinds_prefer_a4(self):
        html = ('<a href="x/20260915_01R.pdf">1R</a><a href="x/20260915_01Ra4.pdf">1R A4</a>'
                "<a href='x/20260915_10R.pdf'>10R</a><a href=\"x/20260915_02Ra4.pdf\">2R A4</a><a href=\"x/20260915_02R.pdf\">2R</a>")
        self.assertEqual(pf.pick_pdfs(html), {
            "20260915_01Ra4.pdf": ("2026-09-15", 1, "x/20260915_01Ra4.pdf"),
            "20260915_02Ra4.pdf": ("2026-09-15", 2, "x/20260915_02Ra4.pdf"),
            "20260915_10R.pdf": ("2026-09-15", 10, "x/20260915_10R.pdf")})

    def test_plain_only_day(self):
        html = '<a href="y/20260913_03R.pdf">3R</a><a href="y/20260913_12R.pdf">12R</a><a href="y/20260913_12R.html">x</a>'
        self.assertEqual(sorted(pf.pick_pdfs(html).values()), [("2026-09-13", 3, "y/20260913_03R.pdf"), ("2026-09-13", 12, "y/20260913_12R.pdf")])
        # 済みの判定は (日付, R)= a4 名で入った日の無印を取り直さない
        self.assertEqual((pf.sibling("20260914_03Ra4.pdf"), pf.sibling("20260914_03R.pdf")), ("20260914_03R.pdf", "20260914_03Ra4.pdf"))


class Gear(unittest.TestCase):
    def test_gear_marks(self):
        self.assertEqual(pp.gear_marks("マリリンダンサーB S"), "B+S")
        self.assertIsNone(pp.gear_marks("マリリンダンサー"))
        self.assertEqual(pp.gear_marks("マリリンダンサーＢ"), "B")
        self.assertIsNone(pp.gear_marks("マリリンダンサーBX"))
        self.assertEqual(pp.gear_marks("マリリンダンサー S P"), "P+S")      # 並びは B→P→S

    def test_rows_gear_only_when_present(self):
        runs = [dict(run("2026-09-06", "水沢", 2, 83.6, 37.9), gear="B+S"), run("2026-08-11", "盛岡", 10, 101.3, 37.1)]
        dist = {("水沢", "2026-09-06", 4): 1300, ("盛岡", "2026-08-11", 8): 1400}
        rows = pp.rows_to_write("タイセイアダマス", runs, {0: DB[0], 1: DB[1]}, dist, {"ref": "20260915_10R.pdf", "page": 1, "col": 1})
        self.assertEqual(rows[0]["gear"], "B+S")
        self.assertNotIn("gear", rows[1], "馬具の無い走に gear を持たせた(null で潰す)")

    def test_upsert_sends_same_keys_per_request(self):
        sent = []
        orig = pf.sb
        pf.sb = lambda path, body=None: sent.append(json.loads(body.decode("utf-8")))
        try:
            pf.upsert([{"track": "水沢", "gear": "B"}, {"track": "盛岡"}, {"track": "水沢", "gear": "S"}])
        finally:
            pf.sb = orig
        self.assertEqual([sorted({k for r in part for k in r}) == sorted(set(part[0])) for part in sent], [True, True])
        self.assertEqual([len(p) for p in sent], [2, 1])


if __name__ == "__main__":
    unittest.main()
