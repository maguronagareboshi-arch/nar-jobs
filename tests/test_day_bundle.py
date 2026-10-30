# -*- coding: utf-8 -*-
"""通信量 F1 cloud/day_bundle.py: select の並べ方がサイト(js/data.js runsCsvQuery)と同じか・束の q がサイトの文字と同じか"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))
import day_bundle as db  # noqa: E402


def test_csv_query_sorts_like_site():
    assert db.csv_query("select=" + db.FIN_SEL) == "select=finish,finish_note,margin,race_no,track"
    assert db.csv_query(db.TOP3_Q) == "select=*&finish=lte.3"
    assert db.csv_query("select=b,a&limit=5") == "select=a,b&limit=5"


def test_site_strings():
    # ⛔サイト js/data.js の NAR_RACE_COLS・DAY_FIN_SEL・DAY_TOP3_Q・DAY_PAY_SEL と同じ文字(違えばサイトは束を使わない)
    site = Path(__file__).resolve().parents[2] / "nar-viewer-egress" / "js" / "data.js"
    if not site.exists():
        return   # 便の repo だけのとき(CI)は照合しない
    text = site.read_text(encoding="utf-8")
    assert "const NAR_RACE_COLS = '%s';" % db.RACE_COLS in text
    assert "const DAY_FIN_SEL = '%s';" % db.FIN_SEL in text
    assert "const DAY_TOP3_Q = '%s';" % db.TOP3_Q in text
    assert "const DAY_PAY_SEL = '%s';" % db.PAY_SEL in text
