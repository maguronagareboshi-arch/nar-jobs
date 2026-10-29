# -*- coding: utf-8 -*-
"""2026-10-30 直前の便の生存の見張り(cloud/live_watch.py)と回し直しの入口(guard)の検査。⛔通信も DB も無し。

10/29 12:29 JST に nar-ai-last・v3-gap-live が GitHub 側で消え、fail も書けずに 2.5 時間抜けた。
確かめること:
  ① 開催中・発走前のレースがあるのに生存が 30 分より古い → 赤。引き継ぎの時間・見始め前・レースが残っていない → 赤にしない
  ② 南関の便は南関のレースだけ・他場の便は南関と帯広以外だけを数える。取消は数えない
  ③ 今日回し直しがあった(live_guard)→ 赤・昨日なら赤にしない
  ④ 2 本の便に guard の入力・入口の job・別の列(concurrency)があり、ふだんの起動(guard なし)は今までどおり走る
  ⑤ 見る時間の表が SQL(private.nar_live_guard)と同じ
"""
import datetime as dt
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cloud"))
import live_watch as L  # noqa: E402

DAY = dt.date(2026, 10, 29)


def at(hhmm):
    return dt.datetime.combine(DAY, dt.time(int(hhmm[:2]), int(hhmm[2:])), tzinfo=L.JST)


def iso(hhmm):
    return at(hhmm).isoformat()


RACES = [{"track": "大井", "post_time": t, "cancelled": None} for t in ("1430", "1502", "1535", "1607", "2050")] + \
        [{"track": "名古屋", "post_time": t, "cancelled": None} for t in ("1220", "1325", "1400", "1835")] + \
        [{"track": "帯広", "post_time": "2045", "cancelled": None},
         {"track": "園田", "post_time": "1340", "cancelled": "refund"}]


class LiveBad(unittest.TestCase):
    def test_1029_stale_both(self):
        got = {"ai_last": {"last_ok": iso("1227")}, "v3_gap_live": {"last_ok": iso("1225")}}
        bad = L.live_bad(got, RACES, at("1325"))
        self.assertEqual(len(bad), 2, bad)
        self.assertIn("ai_last", bad[0])
        self.assertIn("v3_gap_live", bad[1])

    def test_fresh_is_green(self):
        got = {"ai_last": {"last_ok": iso("1320")}, "v3_gap_live": {"last_ok": iso("1305")}}
        self.assertEqual(L.live_bad(got, RACES, at("1325")), [])

    def test_handoff_and_before_start(self):
        got = {"ai_last": {"last_ok": iso("0900")}, "v3_gap_live": {"last_ok": iso("0900")}}
        self.assertEqual(L.live_bad(got, RACES, at("0930")), [])          # どちらも見始め前
        bad = L.live_bad(got, RACES, at("1500"))                          # ai_last は引き継ぎ・v3_gap_live は見る
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("v3_gap_live", bad[0])
        bad = L.live_bad(got, RACES, at("1550"))                          # v3_gap_live は引き継ぎ・ai_last は見る
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("ai_last", bad[0])

    def test_no_races_left(self):
        got = {"ai_last": {"last_ok": iso("1200")}, "v3_gap_live": {"last_ok": iso("1200")}}
        # 名古屋の最後 18:35 は 18:25 では 15 分より近い・大井 20:50 は残る・帯広は数えない
        bad = L.live_bad(got, RACES, at("1825"))
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("v3_gap_live", bad[0])
        self.assertEqual(L.live_bad(got, RACES, at("2040")), [])

    def test_left_counts(self):
        self.assertEqual(L.left_races(RACES, DAY, at("1300"), True), 5)
        self.assertEqual(L.left_races(RACES, DAY, at("1300"), False), 3)   # 名古屋 13:25・14:00・18:35(取消の園田と帯広は外す)

    def test_unreadable_races_skip_stale_check(self):
        got = {"ai_last": {"last_ok": iso("0900")}}
        self.assertEqual(L.live_bad(got, None, at("1325")), [])

    def test_guard_today_is_red(self):
        got = {"ai_last": {"last_ok": iso("1320")}, "v3_gap_live": {"last_ok": iso("1320")},
               "live_guard": {"last_try": iso("1245"), "note": "ai_last を回し直す"}}
        bad = L.live_bad(got, RACES, at("1325"))
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("回し直し", bad[0])
        got["live_guard"]["last_try"] = (at("1245") - dt.timedelta(days=1)).isoformat()
        self.assertEqual(L.live_bad(got, RACES, at("1325")), [])


class GuardWorkflows(unittest.TestCase):
    def test_guard_job(self):
        for wf, job in (("nar-ai-last.yml", "last"), ("v3-gap-live.yml", "live")):
            y = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
            self.assertIn("      guard:\n", y, wf)                                  # 入力
            self.assertRegex(y, r"group: .*\$\{\{ github\.event\.inputs\.guard == 'yes' && '-guard' \|\| '' \}\}", wf)
            self.assertIn(f"bash ops/live_guard_check.sh {wf}", y, wf)
            self.assertIn(f"  {job}:\n    needs: guard\n    if: ${{{{ !cancelled() && (github.event.inputs.guard != 'yes' || needs.guard.outputs.go == 'yes') }}}}", y, wf)
            self.assertIn("  guard:\n    if: github.event.inputs.guard == 'yes'", y, wf)

    def test_sql_matches_table(self):
        sql = (ROOT / "pipeline" / "sql" / "live_guard_20261030.sql").read_text(encoding="utf-8")
        for job, (h0, hf, ht, nk) in L.LIVE.items():
            self.assertRegex(sql, rf"\('{job}',\s+'[a-z0-9-]+\.yml', {h0},\s+{hf}, {ht}, {'true' if nk else 'false'}\)", job)
        self.assertIn("interval '15 minutes'", sql)
        self.assertTrue(re.search(r"cron\.schedule\('nar-live-guard', '\*/5 0-12 \* \* \*'", sql))


if __name__ == "__main__":
    unittest.main()
