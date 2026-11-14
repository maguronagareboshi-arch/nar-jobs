import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import viewer_cap_watch as w  # noqa: E402


def test_below_half_is_ok():
    counts = {t: cap // 2 - 1 for t, cap in w.CAPS.items()}
    assert w.judge(counts) == []


def test_half_or_more_is_red():
    counts = {t: 0 for t in w.CAPS}
    counts["nar_viewer_notes"] = 10000
    bad = w.judge(counts)
    assert len(bad) == 1 and "nar_viewer_notes" in bad[0] and "10000/20000" in bad[0]


def test_unreadable_is_red():
    counts = {t: 0 for t in w.CAPS}
    counts["nar_push_subs"] = "HTTPError: 401"
    bad = w.judge(counts)
    assert len(bad) == 1 and "読めない" in bad[0]


def test_caps_match_sql():
    # nar-viewer pipeline/sql/nar_viewer_cap_20261114.sql の trigger の引数と同じ 7 表
    assert w.CAPS == {
        "nar_viewer_notes": 20000, "nar_viewer_horses": 30000, "nar_viewer_people": 10000,
        "nar_viewer_reviews": 30000, "nar_push_subs": 5000, "nar_viewer_handover": 2000,
        "nar_viewer_claim_tries": 2000,
    }
