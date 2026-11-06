# -*- coding: utf-8 -*-
"""stats_local の出力キャッシュ(11/6 送信量)の単体テスト= 使ってよい時だけ使い、少しでも怪しければ本番を丸ごと読む。"""
import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "stats_local", os.path.join(HERE, "..", "pipeline", "stats_local", "stats_local.py"))
SL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SL)


class OutCacheTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="oc_")
        self.now = time.time()
        self.counts = {t: [100 + i, 1762400000.123456] for i, t in enumerate(SL.OUT_COLS)}

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _write(self, **over):
        meta = dict(SL._out_cache_meta_expect(), clean=True, counts=self.counts, saved_at=self.now,
                    full_read_at=self.now - 86400)
        meta.update(over)
        # JSON を通す(本物と同じく辞書・リストは JSON から戻る)
        with open(os.path.join(self.d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        for t in SL.OUT_COLS:
            open(os.path.join(self.d, f"out_{t}.tsv"), "w").close()

    def usable(self, asof="", missing=()):
        return SL._out_cache_usable(self.d, asof, list(missing), self.now)

    def test_ok(self):
        self._write()
        meta, why = self.usable()
        self.assertIsNotNone(meta, why)

    def test_no_cache(self):
        self.assertIsNone(self.usable()[0])

    def test_asof_or_missing_table(self):
        self._write()
        self.assertIsNone(self.usable(asof="2026-11-01T00:00:00Z")[0])
        self.assertIsNone(self.usable(missing=["nar_bms_course"])[0])

    def test_dirty(self):
        SL.cmd_dirty_cache(self.d)
        self.assertIsNone(self.usable()[0])
        self.assertEqual(os.listdir(self.d), ["meta.json"])

    def test_cols_changed(self):
        cols = dict(SL.OUT_COLS)
        cols["nar_graded"] += ", x"
        self._write(cols=cols)
        self.assertIsNone(self.usable()[0])
        self._write(ver=SL.OUT_CACHE_VER + 1)
        self.assertIsNone(self.usable()[0])

    def test_too_old(self):
        self._write(full_read_at=self.now - (SL.OUT_CACHE_MAX_DAYS + 0.1) * 86400)
        self.assertIsNone(self.usable()[0])

    def test_file_missing(self):
        self._write()
        os.remove(os.path.join(self.d, "out_nar_meta.tsv"))
        self.assertIsNone(self.usable()[0])

    def test_bad_counts(self):
        c = dict(self.counts)
        c.pop("nar_meta")
        self._write(counts=c)
        self.assertIsNone(self.usable()[0])

    def test_mismatch(self):
        self._write()
        meta, _ = self.usable()
        prod = {t: list(v) for t, v in self.counts.items()}
        self.assertEqual(SL._out_cache_mismatch(meta, prod), [])
        prod["nar_ob_year"][0] += 1                      # 行数が違う
        prod["nar_graded"][1] += 5                       # キャッシュの後に書かれた行
        prod["nar_meta"][1] -= 3600                      # 古いのはよい
        del prod["nar_venue_stats"]                      # 数えられなかった
        self.assertEqual(sorted(SL._out_cache_mismatch(meta, prod)),
                         sorted(["nar_ob_year", "nar_graded", "nar_venue_stats"]))

    def test_parse_counts(self):
        got = SL._parse_counts(["nar_meta\t1\t1762400000.5\n", "\n", "nar_graded\t1835\t0\n"])
        self.assertEqual(got, {"nar_meta": [1, 1762400000.5], "nar_graded": [1835, 0.0]})

    def test_count_sql_covers_all(self):
        sql = SL._out_count_sql()
        for t in SL.OUT_COLS:
            self.assertIn(f"from public.{t} ", sql)
        self.assertIn("where key = 'big_payouts'", sql)


if __name__ == "__main__":
    unittest.main()
