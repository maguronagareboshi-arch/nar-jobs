# -*- coding: utf-8 -*-
"""10/10 父・母父 × 競馬場(person_stats.sql の (d))の約束ごとを確かめる(DB なし)。"""
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _sql():
    with open(os.path.join(ROOT, "pipeline", "sql", "person_stats.sql"), encoding="utf-8") as f:
        return f.read()


def _block(sql, start, end):
    i = sql.index(start)
    return sql[i:sql.index(end, i)]


class SireVenueTest(unittest.TestCase):
    def setUp(self):
        sql = _sql()
        self.a = _block(sql, "-- (a)", "-- (b)")
        self.c = _block(sql, "-- (c)", "-- (d)")
        self.d = _block(sql, "-- (d)", "commit;")

    def test_a_still_excludes_sire_bms(self):
        self.assertIn("kind not in ('sire', 'bms')", self.a)
        self.assertIn(">= 10", self.a)

    def test_c_is_all_track_only(self):
        self.assertRegex(self.c, r"select g\.kind, g\.name, 'all', p\.period")
        self.assertIn("'by_track'", self.c)
        self.assertIn(">= 30", self.c)

    def test_d_rows_are_per_venue(self):
        d = self.d
        self.assertIn("insert into public.nar_person_stats", d)
        self.assertIn("select g.kind, g.name, g.track, g.period", d)
        self.assertIn("pg_temp.basic(g.kind, g.name, g.track, g.y_from, g.y_to)", d)
        self.assertIn("where x.kind in ('sire', 'bms')", d)
        self.assertRegex(d, r"having count\(\*\) >= 30\) g;")
        self.assertNotIn("'by_track'", d)
        self.assertNotIn("'recent'", d)
        # 距離別・馬場別はその場の中だけ(副問合せ 2 つとも track で絞る)
        self.assertIn("'by_distance'", d)
        self.assertIn("'by_going'", d)
        self.assertEqual(d.count("x.track = g.track"), 2)
        # (c) と同じ閾値・同じ馬場 4 種
        self.assertEqual(d.count("having count(*) >= 5"), 2)
        self.assertIn("going in ('良','稍重','重','不良')", d)
        # ばんえいを外していない((c) の by_track と同じ扱い)
        self.assertNotRegex(d, r"帯広%")

    def test_d_inside_same_transaction(self):
        sql = _sql()
        i_delete = sql.index("delete from public.nar_person_stats;")
        i_d = sql.index("-- (d)")
        i_commit = sql.index("commit;", i_delete)
        self.assertTrue(i_delete < i_d < i_commit)


if __name__ == "__main__":
    unittest.main()
