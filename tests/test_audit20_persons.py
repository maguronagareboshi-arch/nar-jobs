"""監査 #20: persons の突合は 1000 行で切れない(ページ送り・偽の応答。⛔通信なし)"""
import json
import os
import sys
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))

import persons  # noqa: E402


class Paging(unittest.TestCase):
    def test_reads_all_pages(self):
        names = [f"n{i:05d}" for i in range(2345)]
        seen = []

        def fake(base, key, path, method="GET", body=None):
            q = parse_qs(urlparse(path).query)
            seen.append(q["order"][0])
            lim, off = int(q["limit"][0]), int(q["offset"][0])
            return 200, json.dumps([{"name": n} for n in names[off:off + lim]])
        orig = persons.req
        persons.req = fake
        try:
            got = persons.stat_names("b", "k", "trainer")
        finally:
            persons.req = orig
        self.assertEqual(len(got), 2345)
        self.assertEqual(len(seen), 3)
        self.assertEqual(set(seen), {"name.asc"})


if __name__ == "__main__":
    unittest.main()
