# -*- coding: utf-8 -*-
"""danwa_para.check_para の単体試験(8 字一致・原文と同じ・字数・語・断定)と作り直しの流れ。
  python cloud/danwa/test_danwa_para.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import danwa_para as D  # noqa: E402

SRC = "前走は久々を使ってガス抜きができた。今回は上積みが見込めるし、展開ひとつで差はないはず。"
GOOD = "ひと息入れた前の一戦で気が抜けた様子。今度は良くなっていそうで、流れ次第で差は詰まりそう。"


def test_good():
    assert D.check_para(SRC, GOOD) == [], D.check_para(SRC, GOOD)


def test_same_as_source():
    w = D.check_para(SRC, SRC)
    assert '原文と同じ' in w, w


def test_8gram():
    p = "今回は上積みが見込めるので、流れひとつでいい勝負に持ち込めそうだと話していた。"
    w = D.check_para(SRC, p)
    assert any(x.startswith('8字:') for x in w), w
    # 句読点・空白を挟んでも弾く
    p2 = "今回は、上積みが 見込めるので、流れ次第でいい勝負に持ち込めそうだと話していた。"
    assert any(x.startswith('8字:') for x in D.check_para(SRC, p2))


def test_length():
    assert any(x.startswith('字数') for x in D.check_para(SRC, "良くなっていそう。"))
    long = "ひと息入れた前の一戦で気が抜けた様子で、今度は良くなっていそうで、流れ次第で差は詰まりそうだと見ていて期待も大きく、使える距離の幅もあるので今後の組み立ても楽しみになってきたという話だった。"
    assert any(x.startswith('字数') for x in D.check_para(SRC, long))
    assert D.check_para(SRC, "") == ['空'] and D.check_para(SRC, None) == ['空']


def test_words_and_strong():
    assert any(x.startswith('語:') for x in D.check_para(SRC, "調教師は" + GOOD[:40]))
    assert any(x.startswith('調教師名:') for x in D.check_para(SRC, "山田は" + GOOD[:40], trainer="山田 太郎"))
    assert any(x.startswith('断定:') for x in D.check_para(SRC, "必ず" + GOOD[:40]))


def test_retry_then_fail():
    horses = [{"umaban": 1, "comment": SRC}, {"umaban": 2, "comment": SRC}]
    calls = []

    def call(system, user):
        calls.append(user)
        # 1 回目: 1 番は合格・2 番は原文の写し / 2 回目: 2 番はまた写し
        return json.dumps({"items": [{"umaban": 1, "para": GOOD}, {"umaban": 2, "para": SRC}]}, ensure_ascii=False)
    res = D.paraphrase_race(horses, call)
    assert res[1][0] == GOOD and res[1][1] == 1
    assert res[2][0] is None and res[2][1] == D.MAX_TRIES   # 全部だめ= None(原文は入れない)
    assert D.check_para('次は1400メートルで巻き返したい', '1400メートルで改めて上位を狙う形になる。') == []  # 距離は写しに数えない
    assert D.check_para('次は1400メートルで巻き返したい', '次は1400メートルで巻き返したいと話す。')       # 前後ごと写すと外れる
    assert len(calls) == D.MAX_TRIES and '"umaban": 1' not in calls[1].split('\n')[1]  # 作り直しは外れた馬だけ


def test_redo_and_period():
    r = {"race_id": "R1", "umaban": "1", "comment": SRC}
    sh = D.src_hash(SRC)
    have = lambda m: {("R1", 1): {"src_hash": sh, "status": "ok", "model": m}}
    assert D.pick([r], have("claude-haiku-5-5"), False) == []
    assert D.pick([r], have("claude-haiku-5-5"), False, ("claude-haiku-5-5",)) == [r]
    assert D.pick([r], have("hand-20261109"), False, ("hand-", "claude-haiku-5-5")) == []   # 手は守る
    got = D.parse_items(json.dumps({"items": [{"umaban": 1, "para": "流れ次第で差は詰まりそう"}]}, ensure_ascii=False))
    assert got[1].endswith("。")


import tags as T  # noqa: E402

SICK = "休み明けで太め残り。去年は骨折明けだった。"   # 語句ルール: 休み明け・馬体が重め(+病気があれば後ろ)


def _reply(items):
    return json.dumps({"items": items}, ensure_ascii=False)


def test_tags_in_reply():
    horses = [{"umaban": 1, "comment": SRC}]
    # 一覧外の札は捨てる・並びは M の順
    res = D.paraphrase_race(horses, lambda s, u: _reply([{"umaban": 1, "para": GOOD,
                                                          "tags": ["流れ次第", "架空の札", "休み明け", "砂をかぶるのが苦手"]}]))
    assert res[1][0] == GOOD and res[1][3] == ["休み明け", "流れ次第", "砂をかぶるのが苦手"], res
    assert "砂をかぶるのが苦手" in D.SYSTEM and "揉まれると弱い" in D.SYSTEM and '"tags"' in D.SYSTEM


def test_tags_missing_falls_back_to_rule():
    horses = [{"umaban": 1, "comment": SICK}]
    res = D.paraphrase_race(horses, lambda s, u: _reply([{"umaban": 1, "para": GOOD}]))
    assert res[1][3] is None
    rule = T.merge_tags(None, SICK)
    assert rule and set(rule) == set(T.note_tags(SICK)), (rule, T.note_tags(SICK))   # 空にしない
    assert T.merge_tags([], SICK) == T.disease_tags(SICK)                              # 0 個= 病気だけ
    sick = T.disease_tags(SICK)
    assert T.merge_tags(["馬体が重め", "休み明け"], SICK) == ["休み明け", "馬体が重め"] + sick   # 病気は後ろ


def test_para_fail_keeps_tags():
    horses = [{"umaban": 1, "comment": SRC}]
    seq = [[{"umaban": 1, "para": SRC, "tags": ["休み明け"]}],          # 1 回目: 写し(不合格)・札あり
           [{"umaban": 1, "para": SRC}],                                # 2 回目: 札なし= 前の札を残す
           [{"umaban": 1, "para": SRC, "tags": ["流れ次第"]}]]          # 3 回目: 最後に取れた札
    it = iter(seq)
    res = D.paraphrase_race(horses, lambda s, u: _reply(next(it)))
    assert res[1][0] is None and res[1][3] == ["流れ次第"], res
    # 合格した回の札を使う(後の回は呼ばれない)
    seq2 = iter([[{"umaban": 1, "para": SRC, "tags": ["休み明け"]}], [{"umaban": 1, "para": GOOD, "tags": ["成長"]}]])
    res2 = D.paraphrase_race(horses, lambda s, u: _reply(next(seq2)))
    assert res2[1][0] == GOOD and res2[1][3] == ["成長"]


class _FakeDB:
    def __init__(self):
        self.src = [{"race_date": "2026-10-01", "race_id": "R1", "umaban": 1, "comment": SRC},
                    {"race_date": "2026-10-01", "race_id": "R1", "umaban": 2, "comment": SRC},
                    {"race_date": "2026-10-01", "race_id": "R1", "umaban": 3, "comment": ""}]
        self.note = [{"race_id": "R1", "umaban": 1, "tags": ["休み明け"], "para": GOOD, "model": "hand-1", "status": "ok"},
                     {"race_id": "R1", "umaban": 2, "tags": [], "para": None, "model": None, "status": "failed"},
                     {"race_id": "R1", "umaban": 3, "tags": [], "para": None, "model": None, "status": "pending"}]
        self.written = []

    def get_all(self, table, select, d0, d1, extra=""):
        rows = self.src if table == D.SRC else self.note
        cols = select.split(",")
        return [{c: r.get(c) for c in cols} for r in rows]

    def upsert(self, table, rows, on_conflict):
        assert table == D.DST
        self.written += rows


def test_tags_haiku_does_not_touch_para():
    db = _FakeDB()
    calls = []

    def call(system, user):
        calls.append(system)
        return _reply([{"umaban": 1, "tags": ["揉まれると弱い", "休み明け"]}])   # 2 番は返さない
    a = type("A", (), {"dry_run": False})()
    st = D.run_tags_haiku(a, D.dt.date(2026, 10, 1), D.dt.date(2026, 10, 1), db, call)
    assert calls == [D.TAG_SYSTEM]
    assert db.written == [{"race_id": "R1", "umaban": 1, "tags": ["休み明け", "揉まれると弱い"]}], db.written
    assert all(set(r) == {"race_id", "umaban", "tags"} for r in db.written)       # para・status・model は送らない
    assert st["target"] == 2 and st["missing"] == 1 and st["written"] == 1
    import tag_trial  # noqa: E402  試しと同じ指示・一覧
    assert tag_trial.SYSTEM == D.TAG_SYSTEM and tag_trial.LIST == T.HK_LIST and len(T.HK_LIST) == 25


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            f()
            n += 1
    print(f"ok {n}")
