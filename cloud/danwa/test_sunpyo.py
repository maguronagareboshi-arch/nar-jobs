# -*- coding: utf-8 -*-
"""sunpyo.py の単体試験(禁止語・見込みの言葉の検査・skip の条件・送る列)。
  python cloud/danwa/test_sunpyo.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sunpyo as P  # noqa: E402
import sunpyo_trial as S  # noqa: E402

SRC = "前走は久々を使ってガス抜きができた。今回は上積みが見込めるし、展開ひとつで差はないはず。"
GOOD = ("夏は『使って良くなる』の話どおり2着と3着に走ったが、秋に『状態は良い』と言われた2戦はともに8着だった。"
        "今回はひと叩きして上向きという話で、前走からの変わり身が見どころ。")


def test_good():
    assert S.check(GOOD, [SRC]) == [], S.check(GOOD, [SRC])


def test_ban_words():
    for w in ["調教師", "厩舎", "ブリンカー", "重賞", "斤量", "C1"]:
        why = S.check(GOOD[:-12] + w + "の話で変わり身。", [SRC])
        assert any(x.startswith("語:") for x in why), (w, why)


def test_outlook_words():
    for w in ["上位", "勝機", "好勝負", "チャンス"]:
        why = S.check(GOOD[:-12] + w + "がありそうな見込み。", [SRC])
        assert any(x.startswith("見込み:") for x in why), (w, why)


def test_strong_and_copy_and_length():
    why = S.check(GOOD[:-12] + "必ず変わり身を見せる。", [SRC])
    assert any(x.startswith("断定:") for x in why), why
    why = S.check("前走は" + "今回は上積みが見込めるし、展開ひとつで差はないはず" * 2 + "。", [SRC])
    assert "8字" in why, why
    assert any(x.startswith("字数") for x in S.check("短い。", [SRC]))
    assert S.check("", [SRC]) == ["空"]


def test_skip_reason():
    past2 = [{"para": "a"}, {"para": "b"}]
    assert P.skip_reason({"para": "今回の話"}, past2) is None
    assert P.skip_reason({"para": "今回の話"}, past2[:1]) == "前の話不足"
    assert P.skip_reason({"para": "今回の話"}, []) == "前の話不足"
    assert P.skip_reason({"para": "  "}, past2) == "当日の話なし"
    assert P.skip_reason(None, past2) == "当日の話なし"


class FakeDB:
    def __init__(self, note, past):
        self.note, self.past, self.written = note, past, []

    def get_all(self, table, select, d0, d1, extra=""):
        return self.note if table == "nar_danwa_note" else [
            {"race_id": r["race_id"], "umaban": r["umaban"], "horse_name": "テスト"} for r in self.note]

    def get(self, path):
        if path.startswith("nar_danwa_note?"):
            for hid, rows in self.past.items():
                if f"horse_id=eq.{hid}&" in path:
                    return rows
            return []
        if path.startswith("nar_kb_danwa?"):
            return [{"race_id": "R0", "umaban": 1, "track": "川崎", "comment": SRC}]
        return []

    def upsert(self, table, rows, on_conflict):
        self.written += rows


def fake_client(text):
    def create(**kw):
        return types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=10, output_tokens=5),
                                     stop_reason="end_turn", content=[types.SimpleNamespace(text=text)])
    return types.SimpleNamespace(messages=types.SimpleNamespace(create=create))


def _note():
    return [{"race_id": "R1", "umaban": 1, "race_date": "2026-11-12", "horse_id": "H1", "para": "今回の話", "sunpyo": None},
            {"race_id": "R1", "umaban": 2, "race_date": "2026-11-12", "horse_id": "H2", "para": "今回の話", "sunpyo": None},
            {"race_id": "R1", "umaban": 3, "race_date": "2026-11-12", "horse_id": None, "para": "今回の話", "sunpyo": None},
            {"race_id": "R1", "umaban": 4, "race_date": "2026-11-12", "horse_id": "H1", "para": "今回の話", "sunpyo": "既にある。"}]


def _past():
    two = [{"race_id": "R0", "umaban": 1, "race_date": "2026-10-01", "para": "前の話", "tags": []},
           {"race_id": "R0", "umaban": 1, "race_date": "2026-09-01", "para": "前の話", "tags": []}]
    return {"H1": two, "H2": two[:1]}


def _args(redo=False):
    return types.SimpleNamespace(date_from="2026-11-12", date_to="2026-11-12", redo=redo, dry_run=False, limit=None)


def test_run_ok_skip_and_columns():
    db = FakeDB(_note(), _past())
    st = P.run(_args(), {}, cl=fake_client('{"sunpyo":"%s"}' % GOOD), db=db)
    assert st["target"] == 3, st                                      # sunpyo がある行は除く
    by = {r["umaban"]: r for r in db.written}
    assert by[1]["sunpyo_status"] == "ok" and by[1]["sunpyo"] == GOOD
    assert by[2]["sunpyo_status"] == "skip" and by[2]["sunpyo"] is None   # 前の話 1 件
    assert by[3]["sunpyo_status"] == "skip"                                # horse_id 無し
    assert all(set(r) == {"race_id", "umaban", "sunpyo", "sunpyo_status", "sunpyo_at"} for r in db.written)
    assert st["low_in"] == 10 and st["low_out"] == 5


def test_run_failed_after_one_retry():
    db = FakeDB(_note()[:1], _past())
    calls = []
    cl = fake_client('{"sunpyo":"%s"}' % (GOOD[:-12] + "上位争いの見込み。"))
    orig = cl.messages.create
    cl.messages.create = lambda **kw: (calls.append(1), orig(**kw))[1]
    P.run(_args(), {}, cl=cl, db=db)
    assert len(calls) == 2                                            # 1 回目 + 作り直し 1 回
    assert db.written[0]["sunpyo_status"] == "failed" and db.written[0]["sunpyo"] is None


def test_redo_includes_existing():
    db = FakeDB(_note(), _past())
    st = P.run(_args(redo=True), {}, cl=fake_client('{"sunpyo":"%s"}' % GOOD), db=db)
    assert st["target"] == 4


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            f()
            n += 1
    print(f"ok {n}")
