# -*- coding: utf-8 -*-
"""2026-09-24 枠連・枠単の払戻(2022-11〜 に 1 件も無かった)。⛔通信なし。

  py -3.12 -X utf8 -m unittest discover -s tests -p "test_*.py"
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "cloud", ROOT / "pipeline"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import waku_backfill as wb                                              # noqa: E402
from nar_official_csv import canonical_combination, normalize_payouts, race_cancel_marks  # noqa: E402


def payback_row(**kw):
    row = {"競馬場": "大井", "競走年月日": "20260902", "レース番号": "5",
           "単勝組番": "3", "単勝払戻金（円）": "450", "単勝人気": "2"}
    row.update(kw)
    return row


class Normalize(unittest.TestCase):
    def test_bracket_pairs_are_kept(self):
        out = normalize_payouts([payback_row(**{
            "枠複組番1": "7", "枠複組番2": "3", "枠複払戻金（円）": "1640", "枠複人気": "7",
            "枠単組番1": "7", "枠単組番2": "3", "枠単払戻金（円）": "3210", "枠単人気": "12"})],
            source_url="x", source_hash="h")
        got = {(p["ticket_type"], p["combination"], p["official_payout_per_100"], p["popularity"]) for p in out}
        self.assertIn(("wakuren", "3-7", 1640, 7), got)        # 枠連は順序なし= 昇順
        self.assertIn(("wakutan", "7-3", 3210, 12), got)       # 枠単は順序あり
        self.assertIn(("win", "3", 450, 2), got)

    def test_same_bracket_zorome(self):
        # 同じ枠の 2 頭で決まる(5-5)= 枠の 2 種だけは同番を許す
        out = normalize_payouts([payback_row(**{
            "枠複組番1": "5", "枠複組番2": "5", "枠複払戻金（円）": "2250", "枠複人気": "9",
            "枠単組番1": "5", "枠単組番2": "5", "枠単払戻金（円）": "4480", "枠単人気": "15"})],
            source_url="x", source_hash="h")
        got = {(p["ticket_type"], p["combination"]) for p in out}
        self.assertIn(("wakuren", "5-5"), got)
        self.assertIn(("wakutan", "5-5"), got)

    def test_horse_pairs_still_reject_same_number(self):
        for t in ("quinella", "exacta", "wide"):
            with self.assertRaises(ValueError):
                canonical_combination(t, ["5", "5"])
        with self.assertRaises(ValueError):
            canonical_combination("trio", ["1", "1", "2"])

    def test_no_bracket_columns_no_rows(self):
        # 枠連を売らない回(頭数が少ない)・枠単を売らない場= 列が空なら行を作らない
        out = normalize_payouts([payback_row()], source_url="x", source_hash="h")
        self.assertEqual({p["ticket_type"] for p in out}, {"win"})

    def test_cancel_mark_sees_bracket_combo(self):
        # 枠の組番だけがある行も「売れて確定」= 取り止めの印は付けない
        row = {"競馬場": "大井", "競走年月日": "20260902", "レース番号": "5",
               "枠複組番1": "1", "枠複組番2": "2", "枠複払戻金（円）": "100"}
        self.assertEqual(race_cancel_marks([row], []), {("大井", "2026-09-02", 5): None})


class Backfill(unittest.TestCase):
    DB = [{"t": "win", "c": "3", "y": 450, "p": 2}, {"t": "quinella", "c": "3-7", "y": 900, "p": 3}]
    ZIP = DB + [{"t": "wakuren", "c": "3-7", "y": 1640, "p": 7}, {"t": "wakutan", "c": "7-3", "y": 3210, "p": 12}]

    def test_merge_only_adds_bracket(self):
        new = wb.merge(self.DB, self.ZIP)
        self.assertEqual([p["t"] for p in new], ["quinella", "wakuren", "wakutan", "win"])
        for p in self.DB:
            self.assertIn(p, new)                                # 既存の要素は消さない

    def test_merge_keeps_db_values_when_zip_differs(self):
        z = [{"t": "win", "c": "3", "y": 999, "p": 1}, {"t": "wakuren", "c": "3-7", "y": 1640, "p": 7}]
        new = wb.merge(self.DB, z)
        self.assertIn({"t": "win", "c": "3", "y": 450, "p": 2}, new)     # DB の値のまま
        self.assertNotIn({"t": "win", "c": "3", "y": 999, "p": 1}, new)

    def test_merge_is_idempotent(self):
        self.assertIsNone(wb.merge(wb.merge(self.DB, self.ZIP), self.ZIP))
        self.assertIsNone(wb.merge(self.DB, self.DB))           # 足すものが無い

    def test_plan_counts(self):
        k1, k2, k3 = ("大井", "2026-09-02", 5), ("大井", "2026-09-02", 6), ("大井", "2026-09-02", 7)
        db = {k1: self.DB, k3: self.DB}
        zp = {k1: self.ZIP, k2: self.ZIP, k3: self.DB}
        rows, st = wb.plan_month(db, zp)
        self.assertEqual([(r["track"], r["race_date"], r["race_no"]) for r in rows], [k1])
        self.assertEqual((st["add"], st["no_db_row"], st["other_diff"], st["wakuren"], st["wakutan"]), (1, 1, 0, 1, 1))
        self.assertEqual(set(rows[0]), {"track", "race_date", "race_no", "payouts", "updated_at"})  # 他の列は送らない


if __name__ == "__main__":
    unittest.main()
