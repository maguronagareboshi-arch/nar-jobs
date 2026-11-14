"""date.today() を新しく増やさない(2026-11-14 総合レビュー #8)。⛔通信なし= ファイルの字だけを見る。
Actions の機械は UTC なので、date.today() は JST の 0〜9 時台に前日になる。日付は cloud/jst.py の jst_today() を使う。
下の許可リストは 11/14 時点で残っている所(#8 の 9 か所の外・直していない)。直したら数を減らす。増やすときは理由を書く。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAT = re.compile(r"date\.today\(\)")
ALLOW = {
    "cloud/jst.py": 2,                       # 説明文の中の字だけ
    "cloud/baba_trend.py": 1,                # 444 行 hi(#8 の挙げた 381-382 の外)
    "cloud/kb/fetch_jra_runs.py": 1,
    "cloud/kb/fetch_kb_noken_hyogo.py": 1,
    "cloud/kb/probe_kb_noken_hyogo.py": 1,
    "pipeline/ai/kochi/k0_dl.py": 2,         # 89 行(キャッシュの記録日)・99 行(月の範囲の端)
    "pipeline/ai/v3/nk_pc_release.py": 1,
    "pipeline/ai/v3/t7e_forecast.py": 1,
}


def _counts():
    got = {}
    for top in ("cloud", "pipeline"):
        for p in (ROOT / top).rglob("*.py"):
            n = len(PAT.findall(p.read_text(encoding="utf-8", errors="replace")))
            if n:
                got[p.relative_to(ROOT).as_posix()] = n
    return got


def test_no_new_date_today():
    got = _counts()
    over = {f: n for f, n in got.items() if n > ALLOW.get(f, 0)}
    assert over == {}, "date.today() が増えた(cloud/jst.py の jst_today() を使う): " + str(over)


def test_jst_today_is_jst():
    import sys
    sys.path.insert(0, str(ROOT / "cloud"))
    import datetime as dt
    from jst import jst_now, jst_today
    utc = dt.timezone.utc
    assert jst_today(dt.datetime(2026, 11, 14, 14, 59, tzinfo=utc)) == dt.date(2026, 11, 14)
    assert jst_today(dt.datetime(2026, 11, 14, 15, 0, tzinfo=utc)) == dt.date(2026, 11, 15)
    assert jst_now(dt.datetime(2026, 11, 14, 0, 0, tzinfo=utc)).hour == 9
