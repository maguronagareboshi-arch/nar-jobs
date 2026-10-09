# -*- coding: utf-8 -*-
"""2026-10-10 監査(取り込みの列・単位の読み違い)の高 3 件の番人。
  horse_ledger(keiba.go.jp 馬ページの走歴表)・noken_public の門別(能検 PDF)・sale_results の JRHA(取引馬 DB)。
  列が 1 つ増えた・減った・見出しの語が変わった入力で止まり、正しい入力では通ることを固定する。
  材料は 2026-10-10 に取った実物の断片(tests/fixtures/parse_guard_*)。"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "cloud"))
import horse_ledger as HL  # noqa: E402
import noken_public as N  # noqa: E402
import sale_results as S  # noqa: E402

FX = ROOT / "tests" / "fixtures"
HORSE = (FX / "parse_guard_horse_mark_info.html").read_text(encoding="utf-8")
JRHA = (FX / "parse_guard_jrha.html").read_text(encoding="utf-8")
MB = json.loads((FX / "parse_guard_monbetsu_table.json").read_text(encoding="utf-8"))


def body_rows(html, f):
    """tbody の各 <tr> の中身を f で書き換える。"""
    head, rest = html.split("<tbody>", 1)
    return head + "<tbody>" + re.sub(r"(<tr[^>]*>)(.*?)(</tr>)", lambda m: m.group(1) + f(m.group(2)) + m.group(3),
                                     rest, flags=re.S)


class HorseLedgerGuard(unittest.TestCase):
    def test_correct_page_passes(self):
        h = HL.parse_horse(HORSE)
        self.assertEqual(len(h["runs"]), 4)
        self.assertTrue(all(r["prize"] is not None for r in h["runs"]))
        self.assertEqual(HL.horse_bad(h, {"n_runs": 4, "local_prize": h["local_prize"]}), [])

    def test_column_added(self):
        page = HORSE.replace("<th>体重</th>", "<th>体重</th><th>増減</th>")
        page = body_rows(page, lambda tr: tr + "<td>+2</td>")
        with self.assertRaises(HL.ParseGuard):
            HL.parse_horse(page)

    def test_column_removed(self):
        page = HORSE.replace("<th>R</th>", "")
        page = body_rows(page, lambda tr: re.sub(r"<td[^>]*>.*?</td>", "", tr, count=1, flags=re.S))
        with self.assertRaises(HL.ParseGuard):
            HL.parse_horse(page)

    def test_header_word_changed(self):
        with self.assertRaises(HL.ParseGuard):
            HL.parse_horse(HORSE.replace("<th>収得賞金</th>", "<th>本賞金</th>"))

    def test_rows_wider_than_header(self):
        with self.assertRaises(HL.ParseGuard):
            HL.parse_horse(body_rows(HORSE, lambda tr: tr + "<td>x</td>"))

    def test_value_and_previous(self):
        h = HL.parse_horse(HORSE)
        bad = copy.deepcopy(h)
        bad["runs"][0]["prize"] = None                      # 読めない賞金は 0 にしない
        self.assertTrue(HL.horse_bad(bad))
        bad = copy.deepcopy(h)
        bad["runs"][0]["bw"] = 57                           # 馬体重の欄に負担重量
        self.assertTrue(HL.horse_bad(bad))
        self.assertTrue(HL.horse_bad(h, {"n_runs": 10, "local_prize": h["local_prize"]}))   # 走歴が減る
        zero = copy.deepcopy(h)
        zero["local_prize"] = 0
        self.assertTrue(HL.horse_bad(zero, {"n_runs": 4, "local_prize": 70000}))           # 非0→0


class JrhaGuard(unittest.TestCase):
    def test_correct_table_passes(self):
        rows = S.parse_jrha(JRHA)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["price_man"], "26,000")
        keep, why = S.jrha_guard(rows, {S.jrha_item_id(r): S._int(r["price_man"]) * 10000 for r in rows})
        self.assertEqual((len(keep), why), (3, []))

    def test_column_added(self):
        h = JRHA.replace('<td class="koubai">購買者</td>', '<td class="koubai">購買者</td><td>市場</td>')
        h = h.replace('<td class="koubai">', '<td>x</td><td class="koubai">')
        with self.assertRaises(S.ParseGuard):
            S.parse_jrha(h)

    def test_column_removed(self):
        h = re.sub(r'<td class="skyusya">.*?</td>', "", JRHA, flags=re.S).replace(' colspan="2"', "")
        with self.assertRaises(S.ParseGuard):
            S.parse_jrha(h)

    def test_header_word_changed(self):
        with self.assertRaises(S.ParseGuard):
            S.parse_jrha(JRHA.replace("購買価格", "落札価格"))

    def test_rows_narrower_than_header(self):
        with self.assertRaises(S.ParseGuard):
            S.parse_jrha(re.sub(r'<td class="skyusya">.*?</td>', "", JRHA, flags=re.S))

    def test_price_range_and_empty(self):
        rows = S.parse_jrha(JRHA)
        big = [dict(rows[0], price_man="250,000")]
        self.assertEqual(len(S.jrha_guard(big)[1]), 1)
        name = [dict(rows[0], price_man="ノーザンファーム")]
        self.assertEqual(len(S.jrha_guard(name)[1]), 1)
        empty = [dict(rows[0], price_man="")]
        self.assertEqual(len(S.jrha_guard(empty)[1]), 0)                       # 前が無ければ不成立として通す
        self.assertEqual(len(S.jrha_guard(empty, {S.jrha_item_id(rows[0]): 260000000})[1]), 1)


class MonbetsuGuard(unittest.TestCase):
    def table(self):
        return copy.deepcopy(MB["table"])

    def test_correct_table_passes(self):
        rows = N.monbetsu_rows(self.table(), [])
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(r.get("time") and N.TIME_RE.match(r["time"]) for r in rows if r.get("time")))
        N.monbetsu_check([{"no": 1, "dist": 800, "rows": rows}], "test")

    def test_labeled_column_added_is_read_by_header(self):
        t = self.table()
        for r in t:
            r.insert(7, "斤量" if r is t[0] else "54.0")
        self.assertEqual(N.monbetsu_rows(t, []), N.monbetsu_rows(self.table(), []))

    def test_column_added_in_rows_only(self):
        t = self.table()
        for r in t[1:]:
            r.insert(7, "54.0")
        with self.assertRaises(N.MonbetsuGuard):
            N.monbetsu_rows(t, [])

    def test_column_removed(self):
        t = self.table()
        i = [N.re.sub(r"\s+", "", N.norm(x or "")) for x in t[0]].index("タイム")
        for r in t:
            del r[i]
        with self.assertRaises(N.MonbetsuGuard):
            N.monbetsu_rows(t, [])

    def test_header_word_changed(self):
        t = self.table()
        t[0] = [("騎手名" if N.re.sub(r"\s+", "", N.norm(x or "")) == "騎手" else x) for x in t[0]]
        with self.assertRaises(N.MonbetsuGuard):
            N.monbetsu_rows(t, [])

    def test_time_read_from_weight_column(self):
        t = self.table()
        lab = [N.re.sub(r"\s+", "", N.norm(x or "")) for x in t[0]]
        i, j = lab.index("タイム"), lab.index("重量")
        t[0][i], t[0][j] = t[0][j], t[0][i]                 # 見出しだけ入れ替わった= タイム ← 斤量
        with self.assertRaises(N.MonbetsuGuard):
            rows = N.monbetsu_rows(t, [])
            N.monbetsu_check([{"no": 1, "dist": 1000, "rows": rows}], "test")

    def test_range(self):
        rows = [{"name": f"ウマ{i}", "time": "2:30.0"} for i in range(3)]
        with self.assertRaises(N.MonbetsuGuard):
            N.monbetsu_check([{"no": 1, "dist": 800, "rows": rows}], "test")
        N.monbetsu_check([{"no": 1, "dist": 800, "rows": rows[:1]}], "test")     # 1 頭は警告だけ
        self.assertTrue(N.monbetsu_row_bad({"time": "54.0"}, 1000))
        self.assertFalse(N.monbetsu_row_bad({"time": "54.0"}, 800))
        self.assertTrue(N.monbetsu_row_bad({"weight": "田中"}, 800))


if __name__ == "__main__":
    unittest.main()
