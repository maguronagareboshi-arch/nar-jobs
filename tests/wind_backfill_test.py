# -*- coding: utf-8 -*-
"""wind_backfill.parse_page の試験: 気象庁から取った実ページ(2026-10-26 高知= s1・羽田= a1)を読む。

  python3 tests/wind_backfill_test.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cloud"))
from wind_backfill import parse_page, DIR_CODE  # noqa: E402

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
check("jma10min_s_kochi_20261026.html", {"00:10": {"dir": DIR_CODE["北西"], "speed": 2.2, "temp": 21.9}})
check("jma10min_a_haneda_20261026.html", {"00:10": {"dir": DIR_CODE["東北東"], "speed": 3.5, "temp": 21.2},
                                         "01:10": {"dir": DIR_CODE["東"], "speed": 5.3, "temp": 21.2}})
print("all ok")
