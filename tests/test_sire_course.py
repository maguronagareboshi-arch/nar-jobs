# -*- coding: utf-8 -*-
"""§18 父の成績(nar_sire_course・2026-10-10)の登録と SQL の約束ごとを確かめる(DB なし)。"""
import importlib.util
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
_spec = importlib.util.spec_from_file_location(
    "stats_local", os.path.join(ROOT, "pipeline", "stats_local", "stats_local.py"))
stats_local = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats_local)


def _read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


class SireCourseTest(unittest.TestCase):
    def test_registered(self):
        self.assertIn("sire_course", stats_local.SQLS)
        keys, cmp = stats_local.OUTPUTS["nar_sire_course"]
        self.assertEqual(keys, ["track", "race_date", "race_no", "umaban", "going"])
        cols = [c.strip() for c in stats_local.OUT_COLS["nar_sire_course"].split(",")]
        for c in keys + cmp:
            self.assertIn(c, cols)

    def test_columns_match_prod_ddl(self):
        """手元の器(sire_course.sql)と本番の器(sire_course_table_20261010.sql)の列と主キーが同じ"""
        def cols(sql):
            body = sql[sql.index("create table if not exists public.nar_sire_course"):]
            body = body[:body.index(");")]
            body = re.sub(r"--[^\n]*", "", body)
            names = re.findall(r"\b([a-z_0-9]+)\s+(?:text|date|int|timestamptz)\b", body)
            pk = re.search(r"primary key \(([^)]*)\)", body).group(1)
            return names, pk
        a = cols(_read("pipeline/sql/sire_course.sql"))
        b = cols(_read("pipeline/sql/sire_course_table_20261010.sql"))
        self.assertEqual(a, b)
        self.assertEqual([c.strip() for c in a[1].split(",")], stats_local.OUTPUTS["nar_sire_course"][0])
        self.assertEqual(a[0], [c.strip() for c in stats_local.OUT_COLS["nar_sire_course"].split(",")])

    def test_window_is_strictly_before_race_day(self):
        sql = _read("pipeline/sql/sire_course.sql")
        self.assertIn("c.race_date < t.race_date", sql)
        self.assertIn("c.race_date < (t.race_date - interval '10 years')::date", sql)
        self.assertNotRegex(sql, r"c\.race_date <= t\.race_date")
        self.assertIn("date '2025-10-10'", sql)            # 埋め戻し 1 年
        self.assertIn("track not like '帯広%'", sql)       # ばんえい除外
        self.assertIn("('競走中止', '中止', '失格')", sql)          # 「走った」の定義

    def test_prod_ddl_has_rls_and_anon_select(self):
        sql = _read("pipeline/sql/sire_course_table_20261010.sql")
        self.assertIn("enable row level security", sql)
        self.assertIn("grant select on public.nar_sire_course to anon, authenticated", sql)


if __name__ == "__main__":
    unittest.main()
