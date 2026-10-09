# -*- coding: utf-8 -*-
"""2026-10-10 監査(取り込みの読み違い)の中の B 組の番人。
  noken_public(門別以外)・tokai_demotion・paper_pdf・kb/parsers(能力表)・kb/jra_runs・sale_listings。
  壊れた入力で鳴り、正しい入力では通ることを固定する。⛔ネット・DB なし。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "cloud"))
sys.path.insert(0, str(ROOT / "cloud" / "kb"))
import jra_runs as J  # noqa: E402
import noken_public as N  # noqa: E402
import paper_pdf as PP  # noqa: E402
import parsers as KP  # noqa: E402
import sale_listings as SL  # noqa: E402
import tokai_demotion as T  # noqa: E402


def nk_day(rows, dist=1000):
    return {"date": "2026-10-01", "races": [{"no": 1, "dist": dist, "rows": rows}]}


GOOD = [{"name": f"ウマ{i}", "time": "1.03.2", "weight": "455", "kin": "54"} for i in range(6)]


class NokenOthers(unittest.TestCase):
    def test_good_day_passes(self):
        N.NOKEN_GUARD.clear()
        self.assertEqual(len(N.noken_day_guard("iwate", [nk_day([dict(r) for r in GOOD])])), 1)
        self.assertEqual(N.NOKEN_GUARD, [])

    def test_weight_in_kin_column_stops_day(self):
        rows = [dict(r) for r in GOOD]
        for r in rows[:3]:
            r["kin"] = "482.0"                # 高知 2023-10-28 の形= 馬体重が負担重量の欄に
        N.NOKEN_GUARD.clear()
        self.assertEqual(N.noken_day_guard("kochi", [nk_day(rows)]), [])
        self.assertEqual(len(N.NOKEN_GUARD), 1)

    def test_one_or_two_bad_rows_only_warn(self):
        rows = [dict(r) for r in GOOD]
        rows[0]["weight"] = "54"
        N.NOKEN_GUARD.clear()
        self.assertEqual(len(N.noken_day_guard("saga", [nk_day(rows)])), 1)
        self.assertEqual(N.NOKEN_GUARD, [])

    def test_time_out_of_range_for_distance(self):
        self.assertTrue(N.noken_row_bad({"time": "54.0"}, 1000))       # 1000m で 54 秒は速すぎ
        self.assertFalse(N.noken_row_bad({"time": "1.03.2"}, 1000))
        self.assertFalse(N.noken_row_bad({"time": "タイムオーバー"}, 1000))   # 数字でない= 見ない

    def test_banei_ranges(self):
        self.assertFalse(N.noken_row_bad({"weight": "1020", "kin": "600", "time": "2:05.3"}, None, banei=True))
        self.assertTrue(N.noken_row_bad({"weight": "480"}, None, banei=True))

    def test_cell_count_mismatch_marked_and_removed(self):
        keys = ["umaban", "name", "weight", "time"]
        row = N.row_of(["1", "ウマ", "455"], keys)
        self.assertIn(N.GUARD_MARK, row)
        self.assertNotIn(N.GUARD_MARK, N.row_of(["1", "ウマ", "455", "1.03.2"], keys))
        rows = [N.row_of(["1", f"ウマ{i}", "455"], keys) for i in range(3)]
        N.NOKEN_GUARD.clear()
        day = nk_day(rows)
        self.assertEqual(N.noken_day_guard("hyogo", [day]), [])
        self.assertFalse(any(N.GUARD_MARK in r for r in rows))   # 印は消してある


def tk_rows(trk, date, ps):
    return [{"trk": trk, "date": date, "name": f"ウマ{i}", "P": p, "rc": "G", "meet": None} for i, p in enumerate(ps)]


class Tokai(unittest.TestCase):
    def test_review_075_passes(self):
        a = tk_rows("KS", "2026-09-01", [4000] * 20)
        b = tk_rows("KS", "2026-10-01", [3000] * 20)          # 見直し= 0.75 倍
        self.assertEqual(T.tokai_guard(a + b), [])

    def test_halved_p_stops(self):
        a = tk_rows("NG", "2026-09-01", [4000] * 20)
        b = tk_rows("NG", "2026-10-01", [400] * 20)           # 桁が落ちた= 読み違い
        self.assertTrue(T.tokai_guard(a + b))

    def test_p_range(self):
        self.assertTrue(T.tokai_guard(tk_rows("NG", "2026-10-01", [123456] * 3 + [2000] * 10)))
        self.assertEqual(T.tokai_guard(tk_rows("NG", "2026-10-01", [-1, 0, 18858])), [])

    def test_drop_count(self):
        st = {}
        T._stat_add(st, "ウマイ 牡 3 1,505 地辺幸一 ウマロ 牝 4 1,520 戸部尚実", T.CAND_NG, T.HN)
        T._stat_add(st, "牝 3 700 本名信行", T.CAND_NG, T.HN)   # 馬名が別の行に割れた= 落ちる
        self.assertEqual((st["hit"], st["cand"]), (2, 3))
        self.assertEqual(T.tokai_drops([("x", {"cand": 100, "hit": 70})]), ["x 読めずに落とした行 30/100"])
        self.assertEqual(T.tokai_drops([("x", {"cand": 400, "hit": 395})]), [])


def jbis_html(head, rows):
    leaves = "".join(f"<div>{x}</div>" for x in head)
    for r in rows:
        leaves += "".join(f"<div>{x}</div>" for x in r)
    return f'<div class="data-7__inner">{leaves}</div><a class="to-top">'


FOAL = [["1", "チチ", "ハハ", "牡", "鹿毛", "4,180,000円", "誰か", "牧場"],
        ["2", "チチ", "ハハ2", "牝", "栗毛", "-", "主取り", "牧場"]]


class SaleListings(unittest.TestCase):
    def test_good_page(self):
        recs, bad = SL.parse_sale(jbis_html(SL.HEAD_FOAL, FOAL))
        self.assertEqual((len(recs), bad), (2, 0))
        self.assertEqual(SL.sale_guard(recs)[1], [])

    def test_header_changed(self):
        head = list(SL.HEAD_FOAL)
        head[5], head[6] = head[6], head[5]
        with self.assertRaises(SL.SaleGuard):
            SL.parse_sale(jbis_html(head, FOAL))

    def test_mare_header(self):
        rows = [["1", "ハハ", "2015", "チチ", "ハハハ", "タネ", "440,000円", "誰か", "牧場"]]
        recs, _ = SL.parse_sale(jbis_html(SL.HEAD_MARE, rows))
        self.assertEqual(len(recs), 1)

    def test_price(self):
        self.assertEqual(SL.price_bad("451,000,000円"), "")
        self.assertTrue(SL.price_bad("4,180"))          # 単位が無い
        self.assertTrue(SL.price_bad("50,000円"))
        recs = [{"hip": i, "price_txt": "418万"} for i in range(5)]
        with self.assertRaises(SL.SaleGuard):
            SL.sale_guard(recs)


class Paper(unittest.TestCase):
    def test_last3f_match(self):
        d = {"track": "盛岡", "race_date": "2026-09-01", "race_no": 3, "runner_number": 1, "last3f": 38.2}
        self.assertEqual(PP.last3f_mismatch({"first3f": 36.5, "last3f": 38.2}, d), "")
        self.assertTrue(PP.last3f_mismatch({"first3f": 38.2, "last3f": 36.5}, d))   # 左右の入れ替わり
        self.assertTrue(PP.last3f_mismatch({"first3f": 38.2, "last3f": None}, d))
        self.assertEqual(PP.last3f_mismatch({"first3f": 36.5, "last3f": 38.2}, dict(d, last3f=None)), "")

    def test_rows_to_write_drops_run(self):
        d = {"track": "盛岡", "race_date": "2026-09-01", "race_no": 3, "runner_number": 1, "last3f": 38.2}
        runs = [{"first3f": 38.2, "last3f": 36.5}, {"first3f": 36.5, "last3f": 38.2}]
        PP.PAPER_GUARD.clear()
        out = PP.rows_to_write("ウマ", runs, {0: d, 1: d}, {("盛岡", "2026-09-01", 3): 1400},
                               {"ref": "x.pdf", "page": 1, "col": 1})
        self.assertEqual([r["first3f"] for r in out], [36.5])
        self.assertEqual(len(PP.PAPER_GUARD), 1)


def nouryoku_html(shift=False, kin="54"):
    run = f"1福① 4.11 未勝 16頭 1 1400ダ1.30.5 騎手 {kin} M 36.1-38.2 8 8 8 11 アイテ 3.5 486 1枠1人"
    rows = ""
    for u in (1, 2):
        ped = f'<td><span class="kbamei"><a href="/db/uma/00{u}/">ウマ{u}</a></span></td>'
        tds = ["<td>1</td>", f"<td>{u}</td>", "<td></td>", "<td>1.2.3.4</td>", ped, "<td>厩舎</td>", "<td>1 2 3</td>"]
        tds += [f"<td>{run}</td>"] * 5
        if shift:
            tds.insert(3, "<td>x</td>")
        rows += "<tr>" + "".join(tds) + "</tr>"
    return f'<table class="nouryoku_html_table">{rows}</table>'


class Nouryoku(unittest.TestCase):
    def test_good(self):
        got = KP.parse_nouryoku(nouryoku_html())
        self.assertEqual(len(got["horses"]), 2)
        self.assertEqual(len(got["horses"][0]["runs"]), 5)

    def test_shift(self):
        with self.assertRaises(KP.NouryokuGuard):
            KP.parse_nouryoku(nouryoku_html(shift=True))

    def test_kin_out_of_range(self):
        with self.assertRaises(KP.NouryokuGuard):
            KP.parse_nouryoku(nouryoku_html(kin="99"))


class JraRuns(unittest.TestCase):
    def test_ranges(self):
        ok = {"surface": "芝", "first3f": 35.1, "last3f": 34.2, "last4f": 46.9, "race_last3f": 35.0,
              "body_weight": 480, "carried_weight": 57.0}
        self.assertEqual(J.jra_run_bad(ok), "")
        self.assertTrue(J.jra_run_bad(dict(ok, last3f=12.3)))
        self.assertTrue(J.jra_run_bad(dict(ok, last4f=35.0, race_last3f=46.9)))     # 4F と 3F の入れ替わり
        self.assertTrue(J.jra_run_bad(dict(ok, body_weight=57)))
        self.assertEqual(J.jra_run_bad(dict(ok, surface="障", first3f=None, last3f=41.5)), "")


if __name__ == "__main__":
    unittest.main()
