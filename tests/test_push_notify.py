# -*- coding: utf-8 -*-
"""§291 cloud/push_notify.py の対象抽出(pick)= 馬 id の解き方・A/C の条件・初回の洪水よけ・上限。DB 不要。"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import push_notify as P  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 26, 6, 0, tzinfo=UTC)              # JST 15:00
SUB_AT = "2026-09-26T03:00:00+00:00"                          # 購読の作成= JST 12:00
DEV = "11111111-1111-1111-1111-111111111111"


def sub(a=True, c=True, dev=DEV, at=SUB_AT, ep="https://push.example/1"):
    return {"endpoint": ep, "device_id": dev, "want_a": a, "want_c": c, "created_at": at}


def run(name, date, no, up, finish=None, note=None, track="大井", birth=None):
    return {"track": track, "race_date": date, "race_no": no, "horse_name": name, "birth_date": birth,
            "finish": finish, "finish_note": note, "updated_at": up}


class T(unittest.TestCase):
    def test_horse_id(self):
        self.assertEqual(P.parse_horse_id("nar:アイウ"), ("アイウ", None, None))
        self.assertEqual(P.parse_horse_id("nary:2021:アイウ"), ("アイウ", 2021, None))
        self.assertEqual(P.parse_horse_id("narb:2021-04-01:アイウ"), ("アイウ", None, "2021-04-01"))
        self.assertIsNone(P.parse_horse_id("kochi:12345678901"))
        self.assertIsNone(P.parse_horse_id("kb:123"))

    def test_a_only_new_future(self):
        horses = [{"device_id": DEV, "horse_id": "nar:アイウ"}]
        runs = [run("アイウ", "2026-09-27", 5, "2026-09-26T05:00:00+00:00"),                 # 明日・購読後= A
                run("アイウ", "2026-09-28", 3, "2026-09-26T02:00:00+00:00"),                 # 購読前の取り込み= 送らない
                run("アイウ", "2026-09-27", 9, "2026-09-26T05:00:00+00:00", note="出走取消"),  # 取消= 送らない
                run("エオ", "2026-09-27", 1, "2026-09-26T05:00:00+00:00")]                   # 別の馬
        got = P.pick([sub()], horses, runs, NOW)
        self.assertEqual([(x["kind"], x["race_id"]) for x in got], [("A", "ooi/2026-09-27/5")])
        self.assertEqual(P.message(got[0])["url"], "/race/ooi/2026-09-27/5")

    def test_c_window_and_want(self):
        horses = [{"device_id": DEV, "horse_id": "nar:アイウ"}]
        runs = [run("アイウ", "2026-09-26", 4, "2026-09-26T05:30:00+00:00", finish=2),   # 30 分前に確定= C
                run("アイウ", "2026-09-26", 1, "2026-09-26T02:30:00+00:00", finish=1)]   # 購読前= 送らない
        got = P.pick([sub()], horses, runs, NOW)
        self.assertEqual([(x["kind"], x["race_no"], x["finish"]) for x in got], [("C", 4, 2)])
        self.assertEqual(P.pick([sub(c=False)], horses, runs, NOW), [])
        late = NOW + dt.timedelta(hours=4)                                               # 3 時間を過ぎた
        self.assertEqual(P.pick([sub()], horses, runs, late), [])

    def test_birth_year_and_unknown_device(self):
        horses = [{"device_id": DEV, "horse_id": "nary:2021:アイウ"},
                  {"device_id": "22222222-2222-2222-2222-222222222222", "horse_id": "nar:アイウ"}]   # 購読の無い端末
        runs = [run("アイウ", "2026-09-27", 5, "2026-09-26T05:00:00+00:00", birth="2021-03-01"),
                run("アイウ", "2026-09-27", 6, "2026-09-26T05:00:00+00:00", birth="2019-03-01", track="川崎")]
        got = P.pick([sub()], horses, runs, NOW)
        self.assertEqual([x["race_id"] for x in got], ["ooi/2026-09-27/5"])

    def test_cap_per_device(self):
        horses = [{"device_id": DEV, "horse_id": "nar:ア%d" % i} for i in range(15)]
        runs = [run("ア%d" % i, "2026-09-27", 1 + i % 12, "2026-09-26T05:00:00+00:00", track="船橋" if i < 12 else "浦和")
                for i in range(15)]
        self.assertEqual(len(P.pick([sub()], horses, runs, NOW)), P.PER_DEVICE_MAX)


if __name__ == "__main__":
    unittest.main()
