"""cloud/day_trend_norm.py が js/day-trend.js(nar-viewer)と同じ計算かの照合(1 日ぶん)。
実行: python tests/test_day_trend_norm.py  ⛔通信なし。
期待値= nar-viewer の computeDayTrend に同じ材料(tests/fixtures/day_trend_norm_fixture.json)を入れて出した値
(2026-10-22・posGap.front.mean − back.mean / gateGap.inner.mean − outer.mean)。
材料= 取消・除外・競走中止(着差の欄)・人気の同値・2 周のコーナー名・最後が 3 角のレース・枠の欠け・7 頭立て・着順なしのレース。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cloud"))
import day_trend_norm as m  # noqa: E402

fx = json.load(open(os.path.join(ROOT, "tests", "fixtures", "day_trend_norm_fixture.json"), encoding="utf-8"))
_, per = m.build(fx["races"], fx["runs"])
d = per["urawa"]["2026-10-15"]
assert d["pos_races"] == 5 and d["gate_races"] == 4, d
assert abs(d["pos"] - (-1.7000000000000002)) < 1e-9, d
assert abs(d["gate"] - (-2.0769230769230766)) < 1e-9, d
# 3 レース未満の日は値なし
two = [r for r in fx["races"] if r["race_no"] in (1, 2)]
_, per2 = m.build(two, fx["runs"])
assert per2["urawa"]["2026-10-15"]["pos"] is None
# 分位(直線補間)と日数の下限
assert m.quant([1, 2, 3, 4, 5], 0.1) == 1.4 and m.quant([1, 2, 3, 4, 5], 0.5) == 3
assert m.summarize([0.0] * (m.MIN_DAYS - 1)) is None
s = m.summarize([i / 10 for i in range(30)])
assert s == {"med": 1.45, "lo": 0.29, "hi": 2.61, "n": 30}, s
print("ok day_trend_norm")
