# -*- coding: utf-8 -*-
"""二重送信よけ= 同じ device_id の送り先が複数なら created_at が一番新しい 1 本だけ(DB・通信なし)。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import push_notify as P  # noqa: E402


def sub(dev, ep, at, a=True, c=True):
    return {"device_id": dev, "endpoint": ep, "created_at": at, "want_a": a, "want_c": c}


class T(unittest.TestCase):
    def test_two_keep_newest(self):
        old = sub("d1", "https://push.example/old", "2026-09-01T00:00:00+00:00")
        new = sub("d1", "https://push.example/new", "2026-10-03T00:00:00+00:00", c=False)
        self.assertEqual(P.latest_per_device([old, new]), [new])
        self.assertEqual(P.latest_per_device([new, old]), [new])

    def test_single_unchanged(self):
        s = sub("d1", "https://push.example/1", "2026-09-01T00:00:00Z")
        self.assertEqual(P.latest_per_device([s]), [s])

    def test_devices_not_mixed(self):
        a1 = sub("d1", "https://push.example/a1", "2026-09-01T00:00:00Z")
        a2 = sub("d1", "https://push.example/a2", "2026-10-01T00:00:00Z")
        b1 = sub("d2", "https://push.example/b1", "2026-08-01T00:00:00Z")
        self.assertEqual(P.latest_per_device([a1, b1, a2]), [b1, a2])

    def test_same_time_one_by_endpoint(self):
        x = sub("d1", "https://push.example/x", "2026-10-01T00:00:00Z")
        y = sub("d1", "https://push.example/y", "2026-10-01T00:00:00Z")
        self.assertEqual(P.latest_per_device([y, x]), [y])
        self.assertEqual(P.latest_per_device([x, y]), [y])


if __name__ == "__main__":
    unittest.main()
