# -*- coding: utf-8 -*-
"""wind_backfill.parse_page の試験: 気象庁から取った実ページ(2026-10-26 高知・帯広= s1・羽田= a1)を読む。
降水量(precip)と取り直し、毎晩の便 wind_store.points_of_file の precipitation10m も見る。

  python3 tests/wind_backfill_test.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cloud"))
import urllib.error  # noqa: E402
import wind_backfill  # noqa: E402
from wind_backfill import parse_page, DIR_CODE, _precip  # noqa: E402
from wind_store import points_of_file  # noqa: E402

FX = ROOT / "tests" / "fixtures"


def check(name, want):
    pts = parse_page((FX / name).read_text(encoding="utf-8"))
    assert len(pts) == 143, (name, len(pts))           # 00:10〜23:50(24:00 は翌日なので落とす)
    assert pts[0]["t"] == "00:10" and pts[-1]["t"] == "23:50", name
    for t, exp in want.items():
        got = next(p for p in pts if p["t"] == t)
        assert got == dict(exp, t=t), (name, t, got, exp)
    assert all(p["dir"] is None or 1 <= p["dir"] <= 16 for p in pts)
    print(f"ok {name} {len(pts)} 点")


# 期待値はページの表を目で見て写したもの
check("jma10min_s_kochi_20261026.html", {"00:10": {"dir": DIR_CODE["北西"], "speed": 2.2, "temp": 21.9, "precip": 0.0}})
check("jma10min_a_haneda_20261026.html", {"00:10": {"dir": DIR_CODE["東北東"], "speed": 3.5, "temp": 21.2, "precip": 0.0},
                                         "01:10": {"dir": DIR_CODE["東"], "speed": 5.3, "temp": 21.2, "precip": 0.0}})


def check_precip(name, n_zero, n_pos, total, want):
    """降水量: 0(「--」と 0.0)の数・正の数・合計・決まった時刻の値。実ページに null の値は無い。"""
    pts = parse_page((FX / name).read_text(encoding="utf-8"))
    vals = [p["precip"] for p in pts]
    assert sum(v == 0 for v in vals) == n_zero, (name, "zero", sum(v == 0 for v in vals))
    assert sum(v is not None and v > 0 for v in vals) == n_pos, (name, "pos")
    assert all(v is not None for v in vals), name
    assert round(sum(vals), 1) == total, (name, round(sum(vals), 1))
    for t, v in want.items():
        assert next(p for p in pts if p["t"] == t)["precip"] == v, (name, t)
    print(f"ok {name} 降水量 0={n_zero} 正={n_pos} 計 {total}mm")


# 数は表の降水量の列を数えたもの(24:00 の行は除く)。高知は「--」29 行+「0.0」73 行= 0 が 102
check_precip("jma10min_s_kochi_20261026.html", 102, 41, 30.5, {"05:50": 0.5, "06:20": 0.5, "03:00": 0.0})
check_precip("jma10min_a_haneda_20261026.html", 89, 54, 28.5, {"03:00": 0.5, "05:50": 0.0})
check_precip("jma10min_s_obihiro_20261026.html", 143, 0, 0.0, {"12:00": 0.0})   # 全部「--」= 降水なし

# セル 1 つの規則: 品質記号つき・///・×・空は null、「--」は 0
for cell, exp in [("--", 0.0), ("0.0", 0.0), ("1.5", 1.5), ("0.5 )", None), ("0.5]", None), ("///", None),
                  ("×", None), ("", None), ("#", None)]:
    assert _precip(cell) == exp, (cell, _precip(cell))
print("ok 降水量のセル規則")

# 毎晩の便: bosai の点データ(<yyyymmddHHMMSS>: {要素: [値, 品質]})の形。品質 0 だけ採用
bosai = {
    "20261026120000": {"temp": [21.9, 0], "precipitation10m": [0.5, 0], "wind": [2.2, 0], "windDirection": [14, 0]},
    "20261026121000": {"temp": [21.8, 0], "precipitation10m": [0.0, 0], "wind": [2.0, 0], "windDirection": [13, 0]},
    "20261026122000": {"temp": [21.8, 0], "precipitation10m": [1.0, 1], "wind": [1.9, 0], "windDirection": [13, 0]},
    "20261026123000": {"temp": [21.7, 0], "precipitation10m": [None, 5], "wind": [1.8, 0], "windDirection": [12, 0]},
    "20261026124000": {"temp": [21.7, 0], "wind": [1.8, 0], "windDirection": [12, 0]},
    "20261027000000": {"temp": [20.0, 0], "precipitation10m": [2.0, 0], "wind": [1.0, 0], "windDirection": [1, 0]},
}
pts = points_of_file(bosai, "20261026")
assert [p["t"] for p in pts] == ["12:00", "12:10", "12:20", "12:30", "12:40"], pts
assert [p["precip"] for p in pts] == [0.5, 0.0, None, None, None], [p["precip"] for p in pts]
assert pts[0] == {"t": "12:00", "dir": 14, "speed": 2.2, "temp": 21.9, "precip": 0.5}, pts[0]
print("ok bosai precipitation10m")

# 取り直し: 503 → 接続失敗 → 成功(待ちは 5, 15)。404 は取り直さない
calls, waits = [], []


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return "ok".encode("utf-8")


def _fake(seq):
    def f(req, timeout=30):
        calls.append(req.full_url)
        e = seq.pop(0)
        if e is None:
            return _Resp()
        raise e
    return f


orig = wind_backfill.urllib.request.urlopen
try:
    wind_backfill.urllib.request.urlopen = _fake([urllib.error.HTTPError("u", 503, "x", {}, None),
                                                  urllib.error.URLError("refused"), None])
    assert wind_backfill.fetch_page("74182", "2026-10-26", sleeper=waits.append) == "ok"
    assert waits == [5, 15] and len(calls) == 3, (waits, calls)
    waits.clear()
    wind_backfill.urllib.request.urlopen = _fake([urllib.error.HTTPError("u", 429, "x", {}, None)] * 4)
    try:
        wind_backfill.fetch_page("74182", "2026-10-26", sleeper=waits.append)
        raise AssertionError("4 回目の失敗で上げるはず")
    except urllib.error.HTTPError:
        pass
    assert waits == [5, 15, 45], waits
    waits.clear()
    wind_backfill.urllib.request.urlopen = _fake([urllib.error.HTTPError("u", 404, "x", {}, None)])
    try:
        wind_backfill.fetch_page("74182", "2026-10-26", sleeper=waits.append)
        raise AssertionError("404 は上げるはず")
    except urllib.error.HTTPError:
        pass
    assert waits == [], waits
finally:
    wind_backfill.urllib.request.urlopen = orig
print("ok 取り直し")
print("all ok")
