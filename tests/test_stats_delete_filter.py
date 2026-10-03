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

    # 2026-10-03 名前の & で割れた件= サーバーと同じ割り方(parse_qsl)で 1 組に収まること
    VALS = ["Aaron&Mari", "A=B", "1+1", "100%", "#1", "(株)ノルマンディー,X", 'q"z', "a\\b", "Blue Point", "門別|d1000"]

    def _split(self, q):
        return urllib.parse.parse_qsl(q, keep_blank_values=True, strict_parsing=True)

    def test_special_chars_single_key_in(self):
        q = stats_local._delete_filter(["key"], [[v] for v in self.VALS])
        pairs = self._split(q)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], "key")
        self.assertEqual(pairs[0][1], "in.(" + ",".join(stats_local._q(v) for v in self.VALS) + ")")

    def test_special_chars_four_keys_or(self):
        keys = ["kind", "a", "b", "c"]
        part = [["sv", v, v + "x", "z" + v] for v in self.VALS]
        q = stats_local._delete_filter(keys, part)
        pairs = self._split(q)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], "or")
        want = "(" + ",".join("and(" + ",".join(f"{k}.eq.{stats_local._q(v)}" for k, v in zip(keys, r)) + ")"
                              for r in part) + ")"
        self.assertEqual(pairs[0][1], want)

    def test_wrong_arity_stops(self):
        with self.assertRaises(SystemExit):
            stats_local._delete_filter(["kind", "a", "b"], [["sv", "Blue Point", "門別", "d1000"]])


if __name__ == "__main__":
    unittest.main()
