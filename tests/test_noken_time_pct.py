"""§304c 能検の時計 案 C(cloud/noken_index.py time_pct)の見本。
  py -3.12 -m unittest discover -s tests -p "test_noken_time_pct.py"

画面(js/data.js nokenTimePct)から 2026-10-02 に移した計算。見本は viewer tests/shinba_cols_test.mjs で使っていたものと同じ
(浦和 800m 2歳の 7/10〜7/14 に 25 頭・各日 5 頭 → 9/2 の 51.0 は 10/25 = 0.4)。
移す前に本番の索引 11,977 件で画面の計算と突き合わせ、9,340 件が完全一致・片方だけ 0 件だった。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud.noken_index import time_pct   # noqa: E402


def pool():
    return {f"池{i}": [{"date": f"2026-07-1{i % 5}", "d": "urawa", "dm": 800, "ag": 2,
                         "time": f"{50 + i * 0.1:.1f}"}] for i in range(25)}


class TimePctTest(unittest.TestCase):
    def test_sample_is_point_four(self):
        me = {"date": "2026-09-02", "d": "urawa", "dm": 800, "ag": 2, "time": "51.0"}
        horses = {"見本の馬": [me, {"date": "2026-08-10", "d": "urawa"}], **pool()}
        time_pct(horses)
        self.assertAlmostEqual(me["q"], 0.4, places=12)
        self.assertNotIn("q", horses["見本の馬"][1])            # 時計が無い= q なし

    def test_window_under_twenty_has_no_q(self):
        me = {"date": "2026-09-02", "d": "urawa", "dm": 800, "ag": 2, "time": "51.0"}
        time_pct({"見本の馬": [me]})
        self.assertNotIn("q", me)

    def test_other_pool_is_not_mixed(self):
        me = {"date": "2026-09-02", "d": "urawa", "dm": 1000, "ag": 2, "time": "51.0"}   # 距離が違う= 別の池
        time_pct({"見本の馬": [me], **pool()})
        self.assertNotIn("q", me)

    def test_alias_copies_count_once(self):
        # 別名キーで同じ記録が 2 つの馬名に入っても池では 1 回だけ数える(画面と同じ)
        horses = pool()
        horses["別名"] = [dict(horses["池0"][0])]
        me = {"date": "2026-09-02", "d": "urawa", "dm": 800, "ag": 2, "time": "51.0"}
        horses["見本の馬"] = [me]
        time_pct(horses)
        self.assertAlmostEqual(me["q"], 0.4, places=12)


if __name__ == "__main__":
    unittest.main()
