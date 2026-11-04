"""egress_watch.step の試験: 1 日の量の出し方と急増の警告。"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))
import egress_watch as ew  # noqa: E402

T0 = dt.datetime(2026, 11, 1, 1, 0, tzinfo=dt.timezone.utc)


def run_days(daily):
    """daily= 日ごとの増え方(anon)。1 時間おきに step を回し、最後の (value, warn) を返す"""
    v, cur, warn = {}, {"anon": 0, "svc": 0, "pg": 0}, []
    t = T0
    for inc in daily:
        for _ in range(24):
            cur = {"anon": cur["anon"] + inc // 24, "svc": cur["svc"] + 100, "pg": cur["pg"] + 1000}
            t += dt.timedelta(hours=1)
            v, warn = ew.step(v, cur, t)
    return v, warn


class Step(unittest.TestCase):
    def test_steady_no_warn(self):
        v, warn = run_days([24000] * 6)
        self.assertEqual(warn, [])
        self.assertAlmostEqual(v["days"][-1]["anon"], 24000, delta=1500)

    def test_jump_warns(self):
        _, warn = run_days([24000] * 5 + [72000])
        self.assertTrue(any("閲覧者" in w for w in warn))

    def test_reset_is_not_counted(self):
        v, _ = run_days([24000] * 3)
        later = dt.datetime.fromisoformat(v["at"]) + dt.timedelta(hours=1)
        v2, warn = ew.step(v, {"anon": 5, "svc": 5, "pg": 5}, later)
        self.assertIsNone(v2["days"][-1]["anon"])
        self.assertEqual(warn, [])

    def test_keeps_14_days(self):
        v, _ = run_days([24000] * 20)
        self.assertLessEqual(len(v["days"]), 14)
        self.assertLessEqual(len(v["snaps"]), 31)


if __name__ == "__main__":
    unittest.main()
