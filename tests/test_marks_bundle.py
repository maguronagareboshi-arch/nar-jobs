# -*- coding: utf-8 -*-
"""通信量 F3 cloud/marks_bundle.py: 置き場の名前・select がサイト(js/data.js marksBundleName・日ごとの読み)と同じか"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))
import marks_bundle as mb  # noqa: E402

KEYS = ["runners", "factors", "p", "p_win", "p3", "n", "cal"]
D = "2026-10-30"


class FakeRest:
    """版の窓口・印の表・置き場(一覧・上げ・消し)だけの偽物。vers = marks_ver の答えの順(尽きたら最後のまま)"""
    def __init__(self, vers, rows):
        self.vers, self.rows, self.files, self.calls = list(vers), rows, {}, []

    def rpc(self, name, args, query="", accept="application/json"):
        self.calls.append(("rpc", name))
        return json.dumps(self.vers.pop(0) if len(self.vers) > 1 else self.vers[0]).encode()

    def get(self, q):
        self.calls.append(("get", q))
        return [dict(r) for r in self.rows[re.search(r"model=eq\.([^&]+)", q).group(1)]]

    def req(self, path, method="GET", body=None, headers=None, timeout=60):
        self.calls.append((method, path))
        if path.startswith("/storage/v1/object/list/"):
            pre = json.loads(body)["prefix"]
            return json.dumps([{"name": n} for n in sorted({k[len(pre):].split("/")[0] for k in self.files if k.startswith(pre)})]).encode()
        if method == "POST" and path.startswith("/storage/v1/object/cond-stats/"):
            assert headers["Cache-Control"] == mb.CACHE
            self.files[path[len("/storage/v1/object/cond-stats/"):]] = body
            return b"{}"
        if method == "DELETE":
            for p in json.loads(body)["prefixes"]:
                self.files.pop(p, None)
            return b"{}"
        raise AssertionError(path)


def rows3():
    return {"base-v1": [{"track": "園田", "race_no": 1, "timing": "morning"}],
            "v3-9": [{"track": "大井", "race_no": 1, "timing": "last"}],
            "v3n-1": [{"track": "園田", "race_no": 1, "timing": "last"}, {"track": "園田", "race_no": 1, "timing": "morning"}]}


def test_once_uploads_only_changed_models():
    ver = {"base-v1": ["2026-10-30T00:00:01+00:00", 1, 10], "v3-9": ["2026-10-30T00:00:02+00:00", 1, 11],
           "v3n-1": ["2026-10-30T00:00:03+00:00", 2, 12]}
    rows = rows3()
    r, seen = FakeRest([ver], rows), {}
    assert mb.once(r, [D], None, seen)
    assert sorted(r.files) == sorted("marks/v1/%s/%s/%s" % (D, m, mb.name_of(v)) for m, v in ver.items())
    doc = json.loads(r.files["marks/v1/%s/v3n-1/%s" % (D, mb.name_of(ver["v3n-1"]))])
    assert doc["model"] == "v3n-1" and doc["ver"] == ver["v3n-1"] and doc["q"] == mb.SEL_TAJO and doc["date"] == D
    assert [x["timing"] for x in doc["rows"]] == ["last", "morning"]
    # 同じ版の次の回は置き場も DB も読まない(版の窓口だけ)
    r.calls.clear()
    mb.once(r, [D], None, seen)
    assert r.calls == [("rpc", "marks_ver")]
    # v3-9 だけ書かれた: v3-9 だけ読み直して上げる・古い版は新しい KEEP 本だけ残す
    for i in range(3):
        ver["v3-9"] = ["2026-10-30T00:01:0%d+00:00" % i, 1, 20 + i]
        r.calls.clear()
        r.vers = [ver]
        mb.once(r, [D], None, seen)
        assert [c[1] for c in r.calls if c[0] == "get"][0].startswith("nar_ai_marks?model=eq.v3-9&")
        assert len([c for c in r.calls if c[0] == "get"]) == 1
    v39 = sorted(k for k in r.files if "/v3-9/" in k)
    assert len(v39) == mb.KEEP and ("marks/v1/%s/v3-9/%s" % (D, mb.name_of(ver["v3-9"]))) in v39
    # 置き場に同じ名前があれば(別の便が上げた)読まない
    r2 = FakeRest([ver], rows)
    r2.files = dict(r.files)
    mb.once(r2, [D], None, {})
    assert not [c for c in r2.calls if c[0] == "get"]


def test_moved_while_reading_is_not_uploaded():
    v1 = {"base-v1": ["2026-10-30T00:00:01+00:00", 1, 10]}
    v2 = {"base-v1": ["2026-10-30T00:00:09+00:00", 1, 30]}
    r, seen = FakeRest([v1, v2], rows3()), {}
    mb.once(r, [D], None, seen)
    assert r.files == {} and seen == {}   # 読む間に版が変わった= 上げない・次の回にやり直す
    r = FakeRest([{"base-v1": ["2026-10-30T00:00:01+00:00", 2, 10]}], rows3())
    mb.once(r, [D], None, {})
    assert r.files == {}   # 行数が版と合わない= 上げない


def test_prune_days_keeps_today():
    r = FakeRest([{}], rows3())
    r.files = {"marks/v1/2026-10-29/v3-9/1-1-1.json": b"{}", "marks/v1/2026-10-29/base-v1/1-2-1.json": b"{}",
               "marks/v1/2026-10-30/v3-9/1-3-1.json": b"{}"}
    mb.prune_days(r, D)
    assert list(r.files) == ["marks/v1/2026-10-30/v3-9/1-3-1.json"]


def test_name_like_site():
    # サイトの tests/marks_bundle_test.mjs と同じ答え
    assert mb.name_of(["2026-10-29T22:13:51+00:00", 35, 3457923]) == "35-3457923-202610292213510000.json"
    assert mb.name_of([None, 35, 3457923]) == "35-3457923-.json"


def test_age_order():
    names = ["3-10-202610300100000000.json", "3-12-202610300200000000.json", "4-11-202610300200000000.json", "x.json"]
    assert sorted(names, key=mb.age_of)[-mb.KEEP:] == ["4-11-202610300200000000.json", "3-12-202610300200000000.json"]


def test_site_strings():
    # ⛔サイト js/data.js の MARK_META_KEYS・MARK_META_SEL・日ごとの読みの select と同じ文字(違えばサイトは束を使わない)
    assert mb.MM == ",".join("mm_%s:meta-%%3E%s" % (k, k) for k in KEYS)
    assert mb.SEL_DAY == "track,race_no,timing,marks,%s,computed_at" % mb.MM
    assert mb.SEL_TAJO == "track,race_date,race_no,timing,marks,%s,computed_at,tj_sc:meta-%%3Escratched,tj_dr:meta-%%3Edirect" % mb.MM
    sql = (Path(__file__).resolve().parents[1] / "sql" / "marks_ver.sql").read_text(encoding="utf-8")
    assert "m.model in ('base-v1', 'v3n-1', 'v3-9')" in sql and set(mb.MODELS) == {"base-v1", "v3-9", "v3n-1"}
    site = Path(__file__).resolve().parents[2] / "nar-viewer-egress" / "js" / "data.js"
    if not site.exists():
        return   # 便の repo だけのとき(CI)は照合しない
    text = site.read_text(encoding="utf-8")
    assert "export const MARK_META_KEYS = [%s];" % ", ".join("'%s'" % k for k in KEYS) in text
    assert "const MARK_META_SEL = MARK_META_KEYS.map((k) => `mm_${k}:${enc(`meta->${k}`)}`).join(',');" in text
    assert text.count("const sel = `track,race_no,timing,marks,${MARK_META_SEL},computed_at`;") == 2
    assert "const sel = `track,${select},tj_sc:${enc('meta->scratched')},tj_dr:${enc('meta->direct')}`;" in text
    assert text.count("`race_date,race_no,timing,marks,${MARK_META_SEL},computed_at`, date)") == 2
    assert "`${v[1]}-${v[2]}-${String(v[0] ?? '').replace(/\\D/g, '')}.json`" in text
    assert "/storage/v1/object/public/cond-stats/marks/v1/" in text
