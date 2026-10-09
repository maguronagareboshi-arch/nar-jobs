# -*- coding: utf-8 -*-
"""2026-10-10 監査(取り込みの列・単位の読み違い)の中 A 組 6 本の番人。
  nar_official_csv(#4)・kochi_results(#5)・odds(#6)・odds_full(#7)・hyogo_roster(#13)・convene(#14)。
  壊れた表で鳴り、正しい表では通ることを固定する(材料は実物の形をまねた小さな表)。"""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "cloud"))
import convene as V  # noqa: E402
import hyogo_roster as H  # noqa: E402
import kochi_results as K  # noqa: E402
import nar_official_csv as C  # noqa: E402
import odds as O  # noqa: E402
import odds_full as F  # noqa: E402


# ---------------------------------------------------------------- #4 nar_official_csv
RACE_HEAD = ["競馬場", "競走年月日", "レース番号", "発走時刻", "距離"] + [f"{i}着賞金(円)" for i in range(1, 6)]
HORSE_HEAD = ["競馬場", "競走年月日", "レース番号", "馬番", "馬名", "着順", "人気", "生年月日", "馬体重", "負担重量", "タイム"]


class NarOfficialCsv(unittest.TestCase):
    def files(self, race_head=RACE_HEAD, horse_head=HORSE_HEAD):
        return {"x_racelist.csv": [dict.fromkeys(race_head, "1")], "x_horselist.csv": [dict.fromkeys(horse_head, "1")]}

    def test_columns_ok(self):
        C.check_columns(self.files())

    def test_missing_prize_column(self):
        with self.assertRaises(C.ArchiveColumnsError):
            C.check_columns(self.files(race_head=[h for h in RACE_HEAD if h != "3着賞金(円)"]))

    def test_missing_body_weight(self):
        for col in ("馬体重", "負担重量", "タイム"):
            with self.assertRaises(C.ArchiveColumnsError, msg=col):
                C.check_columns(self.files(horse_head=[h for h in HORSE_HEAD if h != col]))

    def test_prize_values(self):
        row = {"1着賞金(円)": "1,000,000", "2着賞金(円)": "", "3着賞金(円)": "-"}
        self.assertEqual(C._prize(row, 1), 1000000)
        self.assertEqual(C._prize(row, 2), 0)
        self.assertEqual(C._prize(row, 3), 0)
        self.assertEqual(C._prize(row, 4), 0)       # 列が無い(None)も今まで通り 0。列の欠けは check_columns が止める

    def test_prize_unreadable_not_zero(self):
        with self.assertRaises(C.ArchiveColumnsError):
            C._prize({"1着賞金(円)": "百万"}, 1)


# ---------------------------------------------------------------- #5 kochi_results
KOCHI_HEAD = ["着順", "枠", "馬番", "馬名", "所属", "性齢", "負担", "騎手", "調教師", "馬体重", "タイム", "着差",
              "上がり", "コーナー", "人気", "単勝"]


def kochi_row(n, weight="452(+2)", time_="1:28.5", extra=False):
    cells = [str(n), "1", str(n), f"馬{n}", "高知", "牡3", "56.0", "騎手", "調教師", weight, time_, "1",
             "38.9", "1-1", str(n), "2.5"]
    if extra:
        cells.append("x")
    return cells


def kochi_html(rows, head=KOCHI_HEAD):
    def tr(cs, tag):
        return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cs) + "</tr>"
    return "<table>" + tr(head, "th") + "".join(tr(r, "td") for r in rows) + "</table>"


class KochiResults(unittest.TestCase):
    def test_ok(self):
        p = K.parse_mark_table(kochi_html([kochi_row(1), kochi_row(2, weight="－", time_=""),
                                           kochi_row(3, time_="58.3")]))
        self.assertEqual(len(p["horses"]), 3)

    def test_cell_count_mismatch(self):
        with self.assertRaises(K.KochiGuard):
            K.parse_mark_table(kochi_html([kochi_row(1), kochi_row(2, extra=True)]))

    def test_bad_shapes(self):
        rows = [kochi_row(1, weight="56.0"), kochi_row(2, weight="1:28.5"), kochi_row(3, time_="452"), kochi_row(4)]
        with self.assertRaises(K.KochiGuard):
            K.parse_mark_table(kochi_html(rows))

    def test_one_bad_is_warning_only(self):
        p = K.parse_mark_table(kochi_html([kochi_row(1, weight="999(+2)"), kochi_row(2)]))
        self.assertEqual(len(p["horses"]), 2)


# ---------------------------------------------------------------- #6 odds
def odds_page(rows, thead=True):
    head = ('<thead><tr><th>枠</th><th>馬番</th><th>馬名</th><th>単勝</th><th colspan="2">複勝</th></tr></thead>'
            if thead else "")
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<h4 class="odd_title">単勝・複勝（最終）</h4><table class="odd_popular_table_02">{head}'
            f"<tbody>{body}</tbody></table>")


class Odds(unittest.TestCase):
    ROWS = [["1", "1", "A", "2.5", "1.1", "1.5"], ["2", "2", "B", "12.0", "2.0", "3.4"], ["3", "3", "C", "取消", "", ""]]

    def test_ok(self):
        runners, fin = O.parse_odds(odds_page(self.ROWS))
        self.assertTrue(fin)
        self.assertEqual([r["w"] for r in runners], [2.5, 12.0, None])

    def test_no_header_is_not_read_by_position(self):
        with self.assertRaises(O.OddsGuard):
            O.parse_odds(odds_page(self.ROWS, thead=False))

    def test_win_below_one(self):
        rows = [r[:] for r in self.ROWS]
        rows[0][3] = "0.5"
        with self.assertRaises(O.OddsGuard):
            O.parse_odds(odds_page(rows))

    def test_place_low_above_high(self):
        rows = [r[:] for r in self.ROWS]
        rows[1][4], rows[1][5] = "3.4", "2.0"
        with self.assertRaises(O.OddsGuard):
            O.parse_odds(odds_page(rows))


# ---------------------------------------------------------------- #7 odds_full
class OddsFull(unittest.TestCase):
    GOOD = [((1, 2), 3.1, 1), ((1, 3), 5.0, 2), ((2, 3), 5.0, 2), ((1, 4), 9.9, 4), ((3, 4), 0.0, 5)]

    def test_ok(self):
        self.assertEqual(F.ranking_bad(self.GOOD), "")

    def test_swapped_columns(self):
        swapped = [(c, float(r), int(o)) for c, o, r in self.GOOD[:4]]
        self.assertNotEqual(F.ranking_bad(swapped), "")

    def test_not_monotonic(self):
        bad = [((1, 2), 3.1, 1), ((1, 3), 2.0, 2), ((2, 3), 6.0, 3)]
        self.assertIn("減る", F.ranking_bad(bad))


# ---------------------------------------------------------------- #13 hyogo_roster
def hyogo_html(sections):
    out = ["<p>令和8年度 兵庫県競馬組合営 10月2週※自場馬</p><table>"]
    for sec, head, rows in sections:
        out.append(f"<tr><th>{sec}</th></tr>")
        if head:
            out.append("<tr>" + "".join(f"<td>{c}</td>" for c in head) + "</tr>")
        for r in rows:
            out.append("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    return "".join(out) + "</table>"


H2 = ["※", "馬名", "性", "齢", "賞金", "格", "調教師", "備考"]
HA = ["※", "馬名", "性", "齢", "ポイント", "格", "調教師", "備考"]


def hrow(name, val):
    return ["", name, "牡", "3", val, "A1", "調教師", ""]


class HyogoRoster(unittest.TestCase):
    def test_ok(self):
        label, ws, rows = H.parse(hyogo_html([("2歳単独", H2, [hrow("イ", "12,650,000")]),
                                              ("3歳以上Ａ１", HA, [hrow("ロ", "1,050"), hrow("ハ", "0")])]))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["prize_yen"], 12650000)
        self.assertEqual(rows[1]["points"], 1050)

    def test_header_word_swapped(self):
        with self.assertRaises(H.HyogoGuard):
            H.parse(hyogo_html([("2歳単独", HA, [hrow("イ", "100")])]))

    def test_no_header(self):
        with self.assertRaises(H.HyogoGuard):
            H.parse(hyogo_html([("3歳以上Ａ１", None, [hrow("ロ", "100")])]))

    def test_out_of_range(self):
        rows = [hrow("ロ", "12,650,000"), hrow("ハ", "3,000"), hrow("ニ", "abc")]
        with self.assertRaises(H.HyogoGuard):
            H.parse(hyogo_html([("3歳以上Ａ１", HA, rows)]))


# ---------------------------------------------------------------- #14 convene
def conv_html(ndays, venue_cells=None, head=None, ncols=31):
    def tr(cs):
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cs) + "</tr>"
    days = head or ([str(d) for d in range(1, ndays + 1)] + [""] * (ncols - ndays))
    rows = [[""] + days + [""], ["", *["月"] * ncols, ""]]
    marks = venue_cells or (["☆"] + [""] * (ncols - 1))
    rows.append(["高知", *marks, "高知"])
    return '<div id="monthlySchedule"><table>' + "".join(tr(r) for r in rows) + "</table></div>"


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Convene(unittest.TestCase):
    def run_month(self, html, y=2026, m=9):
        with mock.patch.object(V.urllib.request, "urlopen", lambda *a, **k: FakeResp(html.encode("utf-8"))):
            return V.fetch_month(y, m)

    def test_ok_30_day_month_with_31_columns(self):
        days, _ = self.run_month(conv_html(30))
        self.assertEqual(sorted(days), [1])

    def test_venue_row_short(self):
        with self.assertRaises(V.ConveneGuard):
            self.run_month(conv_html(30, venue_cells=["☆"] + [""] * 29))

    def test_header_shifted(self):
        with self.assertRaises(V.ConveneGuard):
            self.run_month(conv_html(30, head=[""] + [str(d) for d in range(1, 31)]))

    def test_mark_after_month_end(self):
        with self.assertRaises(V.ConveneGuard):
            self.run_month(conv_html(30, venue_cells=[""] * 30 + ["☆"]))


if __name__ == "__main__":
    unittest.main()
