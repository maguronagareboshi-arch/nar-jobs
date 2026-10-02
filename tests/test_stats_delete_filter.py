# -*- coding: utf-8 -*-
"""stats_local._delete_filter の単体テスト(鍵の値に "|" があっても割れないこと・2026-10-02 消し残り)。"""
import importlib.util
import os
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "stats_local", os.path.join(HERE, "..", "pipeline", "stats_local", "stats_local.py"))
stats_local = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats_local)


class DeleteFilterTest(unittest.TestCase):
    def test_pipe_in_value_kept_whole(self):
        f = urllib.parse.unquote(stats_local._delete_filter(["kind", "a", "b"], [["sv", "Blue Point", "門別|d1000"]]))
        self.assertEqual(f, 'or=(and(kind.eq."sv",a.eq."Blue Point",b.eq."門別|d1000"))')

    def test_single_key_in(self):
        f = urllib.parse.unquote(stats_local._delete_filter(["key"], [["x|y"], ['q"z']]))
        self.assertEqual(f, 'key=in.("x|y","q\\"z")')

    def test_wrong_arity_stops(self):
        with self.assertRaises(SystemExit):
            stats_local._delete_filter(["kind", "a", "b"], [["sv", "Blue Point", "門別", "d1000"]])


if __name__ == "__main__":
    unittest.main()
