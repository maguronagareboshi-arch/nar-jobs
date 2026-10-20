"""名古屋の公式編成馬一覧の値の差し替え(tokai_official.apply_official)。ネットに出ない部分だけ試す"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))
import class_calc as cc
import tokai_official as T

lines = [("Ａ", 4_500_000, 10**9), ("Ｂ", 2_500_000, 4_500_000), ("Ｃ", 0, 2_500_000)]
lines = [("Ａ", 4_499_999, 10**9), ("Ｂ", 2_499_999, 4_499_999), ("Ｃ", -1, 2_499_999)]

# 一般格: 公式の値で級と次の線を作り直す
c = {"value": 2_503_000, "cls": "Ｂ", "next": {"cls": "Ａ", "need": 4_500_000, "gap": 1_997_000}, "src": "calc"}
n = T.apply_official(c, 2427, lines, cc.classify, cc.next_line, "(t)")
assert n["value"] == 2_427_000 and n["cls"] == "Ｃ" and n["src"] == "official" and n["calc_value"] == 2_503_000, n
assert n["next"]["cls"] == "Ｂ" and n["next"]["gap"] == n["next"]["need"] - 2_427_000, n
assert c["value"] == 2_503_000                                  # 元は変えない

# 3歳格: 級はそのまま・gap だけ公式の値で引き直す
c3 = {"value": 560_000, "cls": "３歳", "next": {"cls": "一般格", "need": 4_400_000, "gap": 3_840_000}}
n3 = T.apply_official(c3, 570, lines, cc.classify, cc.next_line)
assert n3["cls"] == "３歳" and n3["next"]["gap"] == 4_400_000 - 570_000, n3

# 同名・同齢で値が違う馬は外す(fetch_official の規則を parse 結果で確認)
seen, bad = {}, set()
for name, age, prize in [("ア", 3, 100), ("ア", 3, 200), ("イ", 4, 300)]:
    k = (name, age)
    if k in seen and seen[k] != prize:
        bad.add(k)
    seen[k] = prize
assert bad == {("ア", 3)}
print("ok")
