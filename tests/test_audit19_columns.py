"""監査 #19: 公式 CSV の必須列が消えたら ArchiveColumnsError(ValueError にしない= refresh.py が「開催なし」で流さない)。⛔通信なし"""
import csv
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))

import nar_official_csv as noc  # noqa: E402


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, (head, rows) in files.items():
            s = io.StringIO()
            w = csv.writer(s)
            w.writerow(head)
            w.writerows(rows)
            z.writestr(name, s.getvalue().encode("utf-8"))
    return buf.getvalue()


# 2026-10-10 監査 #4 で必須に足した列(1〜5着賞金(円)・馬体重・負担重量・タイム)も並べる
RACE_HEAD = ["競馬場", "競走年月日", "レース番号", "発走時刻", "距離"] + [f"{i}着賞金(円)" for i in range(1, 6)]
HORSE_HEAD = ["競馬場", "競走年月日", "レース番号", "馬番", "馬名", "着順", "人気", "生年月日", "馬体重", "負担重量", "タイム"]


class Columns(unittest.TestCase):
    def test_ok(self):
        z = _zip({"x_racelist.csv": (RACE_HEAD, [["浦和", "2026/09/23", "1", "10:00", "1400", "1000000", "400000", "200000", "100000", "50000"]]),
                  "x_horselist.csv": (HORSE_HEAD, [["浦和", "2026/09/23", "1", "1", "A", "1", "1", "2022/04/01", "452", "56.0", "1:28.5"]])})
        doc = noc.normalize_archive(z, kind="race", scope="daily", source_url="u", observed_at="t")
        self.assertEqual(len(doc["horses"]), 1)

    def test_renamed_column_raises(self):
        head = [c if c != "着順" else "確定着順" for c in HORSE_HEAD]
        z = _zip({"x_racelist.csv": (RACE_HEAD, [["浦和", "2026/09/23", "1", "10:00", "1400", "1000000", "400000", "200000", "100000", "50000"]]),
                  "x_horselist.csv": (head, [["浦和", "2026/09/23", "1", "1", "A", "1", "1", "2022/04/01", "452", "56.0", "1:28.5"]])})
        with self.assertRaises(noc.ArchiveColumnsError) as cm:
            noc.normalize_archive(z, kind="race", scope="daily", source_url="u", observed_at="t")
        self.assertNotIsInstance(cm.exception, ValueError)   # 「開催なし」扱いにされない

    def test_empty_file_not_checked(self):
        z = _zip({"x_racelist.csv": (RACE_HEAD, [["浦和", "2026/09/23", "1", "10:00", "1400", "1000000", "400000", "200000", "100000", "50000"]]),
                  "x_payback.csv": (["何か"], [])})
        noc.normalize_archive(z, kind="race", scope="daily", source_url="u", observed_at="t")


if __name__ == "__main__":
    unittest.main()
