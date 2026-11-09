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
    long = "ひと息入れた前の一戦で気が抜けた様子で、今度は良くなっていそうで、流れ次第で差は詰まりそうだと見ていて期待も大きい。"
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
    assert res[2][0] is None and res[2][1] == 2      # 2 回だめ= None(原文は入れない)
    assert len(calls) == 2 and '"umaban": 1' not in calls[1].split('\n')[1]  # 作り直しは外れた馬だけ


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            f()
            n += 1
    print(f"ok {n}")
