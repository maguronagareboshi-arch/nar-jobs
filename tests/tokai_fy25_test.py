"""名古屋 令和7年度(2026-04-01 より前)の転入加算・3歳一斉編入の控除率(公式の番組賞金額の履歴と突き合わせた値)"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import class_calc as cc  # noqa: E402

D = dt.date


def test_jra_add():
    assert cc.tokai_jra_add("名古屋", D(2025, 12, 18)) == 400_000
    assert cc.tokai_jra_add("名古屋", D(2026, 4, 1)) == 700_000
    assert cc.tokai_jra_add("笠松", D(2025, 12, 18)) == 700_000


def test_cut_rate():
    assert cc.tokai_cut_rate("名古屋", "jra", D(2025, 10, 4)) == 0.15
    assert cc.tokai_cut_rate("名古屋", "jra", D(2026, 10, 3)) == 0.20
    assert cc.tokai_cut_rate("名古屋", "native", D(2025, 10, 4)) == 0.50
    assert cc.tokai_cut_rate("笠松", "jra", D(2025, 10, 4)) == 0.20


def test_cut_amt():
    assert cc.tokai_cut_amt("名古屋", 593_000, 0.15) == 89_000   # 88,950 → 89,000(公式 ルナフェイズ)
    assert cc.tokai_cut_amt("笠松", 593_000, 0.15) == 88_000


if __name__ == "__main__":
    test_jra_add()
    test_cut_rate()
    test_cut_amt()
    print("ok")
