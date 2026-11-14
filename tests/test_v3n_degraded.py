# code.md #7(2026-11-14): 朝の印の劣化の判定。欠けた段の名前だけを返す(書くのは止めない)
import os
import sys

import pytest

pytest.importorskip("pandas")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline", "ai", "kochi"))
import v3n_daily as v  # noqa: E402


def test_all_ok_is_empty():
    for src in ("own", "own-nosite", "site-diff", "site-off"):
        assert v.degraded_parts(True, True, src, True) == []


def test_each_part_named():
    assert v.degraded_parts(False, True, "own", True) == ["並び読み"]
    assert v.degraded_parts(True, False, "own", True) == ["能検"]
    assert v.degraded_parts(True, True, "site-ownfail", True) == ["自前の材料表"]
    assert v.degraded_parts(True, True, "own", False) == ["有利の直し"]
    assert v.degraded_parts(False, False, "site-ownfail", False) == ["並び読み", "能検", "自前の材料表", "有利の直し"]
