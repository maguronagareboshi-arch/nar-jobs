# -*- coding: utf-8 -*-
"""B2 cloud/push_notify.py の☆の騎手・調教師(P/R)と重賞の日(G)= まとめ文・照合・二重送りよけ・取消除外・表が無いときの退避。DB 不要。"""
import datetime as dt
import io
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import push_notify as P  # noqa: E402

UTC = dt.timezone.utc
NOW_P = dt.datetime(2026, 10, 17, 11, 7, tzinfo=UTC)     # JST 20:07
NOW_G = dt.datetime(2026, 10, 18, 0, 7, tzinfo=UTC)      # JST 09:07
NOW_R = dt.datetime(2026, 10, 18, 13, 37, tzinfo=UTC)    # JST 22:37
DEV = "11111111-1111-1111-1111-111111111111"


def sub(p=True, g=False, a=True, c=True, dev=DEV):
    return {"endpoint": "https://push.example/" + dev[:4], "device_id": dev, "want_a": a, "want_c": c,
            "want_p": p, "want_g": g, "created_at": "2026-10-01T00:00:00+00:00"}


def person(name, kind="jockey", venues=None, any_venue=False, dev=DEV):
    return {"device_id": dev, "kind": kind, "name": name, "venues": venues or [], "any_venue": any_venue}


def run(no, jockey, trainer="胡本友", date="2026-10-18", track="高知", finish=None, note=None, num=1):
    return {"track": track, "race_date": date, "race_no": no, "runner_number": num, "horse_name": "馬%d" % no,
            "jockey": jockey, "trainer": trainer, "finish": finish, "finish_note": note}


class Match(unittest.TestCase):
    def test_venues_and_any_venue(self):
        r_kochi, r_saga = run(1, "赤岡修"), run(2, "赤岡修", track="佐賀")
        self.assertTrue(P.person_hit(person("赤岡修", venues=["kochi"]), r_kochi))
        self.assertFalse(P.person_hit(person("赤岡修", venues=["kochi"]), r_saga))       # 場が違う同名
        self.assertTrue(P.person_hit(person("赤岡修", venues=[]), r_saga))               # venues 空= どこでも
        self.assertTrue(P.person_hit(person("赤岡修", venues=["kochi"], any_venue=True), r_saga))
        self.assertFalse(P.person_hit(person("赤岡修", kind="trainer"), r_kochi))         # 騎手の名前は調教師に当てない
        self.assertTrue(P.person_hit(person("胡本友", kind="trainer", venues=["kochi"]), r_kochi))
        self.assertTrue(P.person_hit(person("ア", venues=["obihiro"]), run(1, "ア", track="帯広ば")))


class Bodies(unittest.TestCase):
    def test_p_summary_and_scratch(self):
        ppl = [person("赤岡修", venues=["kochi"]), person("打越勇", kind="trainer", venues=["kochi"]), person("居ない", venues=["kochi"])]
        runs = [run(1, "赤岡修"), run(2, "赤岡修"), run(3, "赤岡修", note="出走取消"),       # 取消は数えない
                run(4, "別人", trainer="打越勇"), run(5, "別人", trainer="打越勇", note="競走除外"),
                run(6, "赤岡修", date="2026-10-19")]                                     # 別の日
        got = P.pick_people([sub()], ppl, runs, None, NOW_P, {"P"})
        self.assertEqual(len(got), 1)
        x = got[0]
        self.assertEqual(x["body"], "明日の出番: 赤岡修(高知)2鞍・打越勇(高知)1鞍")
        self.assertEqual((x["kind"], x["horse_id"], x["race_id"], x["url"]), ("P", "p:2026-10-18", "2026-10-18", "/mymarks"))
        self.assertEqual(P.message(x)["tag"], "P:2026-10-18")

    def test_p_none_when_no_rides(self):
        self.assertEqual(P.pick_people([sub()], [person("赤岡修")], [run(1, "赤岡修", date="2026-10-19")], None, NOW_P, {"P"}), [])

    def test_r_counts(self):
        ppl = [person("赤岡修", venues=["kochi"]), person("打越勇", kind="trainer"), person("吉原寛")]
        runs = [run(1, "赤岡修", finish=1), run(2, "赤岡修", finish=1), run(3, "赤岡修", finish=2),
                run(4, "赤岡修", finish=5), run(5, "赤岡修", note="出走取消"),
                run(6, "別人", trainer="打越勇", finish=3), run(7, "別人", trainer="打越勇"),         # 未確定 1
                run(8, "吉原寛", finish=6, track="佐賀")]
        got = P.pick_people([sub()], ppl, runs, None, NOW_R, {"R"})
        self.assertEqual(got[0]["body"], "今日の結果: 赤岡修 1着2回・2着1回(4鞍)・打越勇 3着1回(確定1/2鞍)・吉原寛 3着以内なし(1鞍)")
        self.assertEqual(got[0]["horse_id"], "r:2026-10-18")

    def test_g(self):
        races = [{"track": "園田", "race_no": 11, "race_name": "第５回 園田オータム", "race_kind": "重賞", "post_time": "2010"},
                 {"track": "高知", "race_no": 10, "race_name": "黒潮盃", "race_kind": "重賞", "post_time": "1540"}]
        got = P.pick_people([sub(g=True), sub(g=False, dev="22222222-0000")], [], [], races, NOW_G, {"G"})
        self.assertEqual([x["device_id"] for x in got], [DEV])                              # want_g の人だけ
        self.assertEqual(got[0]["body"], "今日の重賞: 高知 黒潮盃 15:40・園田 園田オータム 20:10")
        self.assertEqual((got[0]["url"], got[0]["horse_id"]), ("/graded/week", "g:2026-10-18"))
        self.assertEqual(P.pick_people([sub(g=True)], [], [], [], NOW_G, {"G"}), [])         # 重賞なし= 送らない

    def test_want_p_off(self):
        self.assertEqual(P.pick_people([sub(p=False)], [person("赤岡修")], [run(1, "赤岡修")], None, NOW_P, {"P"}), [])


class Slots(unittest.TestCase):
    def test_slot_kinds(self):
        self.assertEqual(P.slot_kinds("auto", NOW_P), ({"P"}, {"A", "C"}))
        self.assertEqual(P.slot_kinds("auto", NOW_P + dt.timedelta(minutes=30)), ({"P"}, {"A", "C"}))
        self.assertEqual(P.slot_kinds("auto", NOW_G), ({"G"}, {"A", "C"}))
        self.assertEqual(P.slot_kinds("auto", NOW_G + dt.timedelta(hours=3)), (set(), {"A", "C"}))
        self.assertEqual(P.slot_kinds("night", NOW_R), ({"R"}, {"C"}))


class FakeRest:
    """表・列が無い本番を真似る(400/404)。sent は nar_push_sent の鍵。"""
    def __init__(self, missing_cols=False, missing_table=False, kind_check_old=False):
        self.missing_cols, self.missing_table, self.kind_check_old = missing_cols, missing_table, kind_check_old
        self.sent, self.calls = set(), []

    def err(self, code):
        return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"{}"))

    def get(self, table, **q):
        self.calls.append(table)
        if table == "nar_push_subs":
            if "want_p" in q["select"] and self.missing_cols:
                raise self.err(400)
            return [sub(p=True, g=True)] if "want_p" in q["select"] else [{k: v for k, v in sub().items() if k not in ("want_p", "want_g")}]
        if table == "nar_viewer_people":
            if self.missing_table:
                raise self.err(404)
            return [person("赤岡修")]
        if table == "nar_runs":
            return [run(1, "赤岡修")]
        if table == "nar_races":
            return []
        return []

    def req(self, path, method="GET", body=None, prefer=None):
        if path.startswith("nar_push_sent?on_conflict"):
            r = body[0]
            if self.kind_check_old and r["kind"] not in ("A", "C"):
                raise self.err(400)
            k = tuple(r[c] for c in ("device_id", "horse_id", "race_id", "kind"))
            if k in self.sent:
                return []
            self.sent.add(k)
            return [r]
        return None


class Fallback(unittest.TestCase):
    def test_missing_cols_skips_people(self):
        rest = FakeRest(missing_cols=True)
        subs = P.load_subs(rest)
        self.assertNotIn("want_p", subs[0])
        people, pruns, graded = P.load_people(rest, subs, NOW_P, {"P"})
        self.assertIsNone(people)
        self.assertEqual(P.pick_people(subs, people, pruns, graded, NOW_P, {"P"}), [])

    def test_missing_table_skips_people(self):
        rest = FakeRest(missing_table=True)
        subs = P.load_subs(rest)
        people, pruns, graded = P.load_people(rest, subs, NOW_P, {"P"})
        self.assertIsNone(people)
        self.assertNotIn("nar_runs", rest.calls)

    def test_tables_present(self):
        rest = FakeRest()
        subs = P.load_subs(rest)
        people, pruns, graded = P.load_people(rest, subs, NOW_P, {"P"})
        got = P.pick_people(subs, people, pruns, graded, NOW_P, {"P"})
        self.assertEqual([x["body"] for x in got], ["明日の出番: 赤岡修(高知)1鞍"])

    def test_dedupe_claim_once_per_day(self):
        rest = FakeRest()
        x = {"device_id": DEV, "horse_id": "p:2026-10-18", "race_id": "2026-10-18", "kind": "P"}
        self.assertTrue(P.claim(rest, x))
        self.assertFalse(P.claim(rest, dict(x)))                      # 20:37 の回= 送らない
        self.assertTrue(P.claim(rest, dict(x, horse_id="r:2026-10-18", kind="R")))

    def test_kind_check_old_does_not_send(self):
        rest = FakeRest(kind_check_old=True)
        self.assertFalse(P.claim(rest, {"device_id": DEV, "horse_id": "g:2026-10-18", "race_id": "2026-10-18", "kind": "G"}))
        self.assertTrue(P.claim(rest, {"device_id": DEV, "horse_id": "nar:ア", "race_id": "kochi/2026-10-18/1", "kind": "A"}))


if __name__ == "__main__":
    unittest.main()
