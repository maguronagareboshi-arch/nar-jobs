"""レース画面の値は発走前の出来事だけで作る(今日の走・今日以後の結果を含む一覧を入れない)。ネットに出ない部分だけ試す"""
import datetime as dt
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))
import class_calc as cc
import tokai_official as T

D = dt.date
today = D(2026, 10, 21)

# 今日の走は「前の走」に入らない(last_tr・兵庫の隠す判定の前走)
runs = [{"d": "2026-10-21", "tr": "園田", "fin": 1}, {"d": "2026-10-14", "tr": "姫路", "fin": 5}, {"tr": "園田", "fin": 2}]
prior = [x for x in runs if cc.before_day(x, today)]
assert [x["d"] for x in prior] == ["2026-10-14"], prior

# 一覧の締め= 初日の 3 日以上前に終わった直近の開催の最終日+1
old = dict(cc.TOKAI_BLOCKS)
cc.TOKAI_BLOCKS.clear()
cc.TOKAI_BLOCKS["笠松"] = [(D(2026, 10, 6), D(2026, 10, 9)), (D(2026, 10, 20), D(2026, 10, 23))]
cc.TOKAI_BLOCKS["名古屋"] = [(D(2026, 10, 13), D(2026, 10, 16)), (D(2026, 10, 20), D(2026, 10, 23))]
assert cc.list_cut("笠松", D(2026, 10, 20), 3) == D(2026, 10, 10)
# 開催中(10/21)に今の回の一覧= 当てる
assert cc.official_usable("笠松", D(2026, 10, 20), today)
# 開催中(10/21)に次の回(11/3 初日= 10/23 までの結果込み)の一覧= 当てない
assert not cc.official_usable("笠松", D(2026, 11, 3), today)
# 名古屋: 10/27 初日の一覧(10/23 までの結果込み)は 10/21 には当てない・10/27 には当てる
assert not cc.official_usable("名古屋", D(2026, 10, 27), today)
assert cc.official_usable("名古屋", D(2026, 10, 27), D(2026, 10, 27))
# 初日や開催が分からなければ当てない
assert not cc.official_usable("笠松", None, today)
cc.TOKAI_BLOCKS.clear()
cc.TOKAI_BLOCKS.update(old)

# 名古屋の次開催の見出しから初日を読む
h = "<h3>第15回名古屋競馬編成馬一覧（2026.10.27～30）</h3>"
assert T.next_program_first_day(h) == D(2026, 10, 27)
assert T.next_program_first_day("<p>なし</p>") is None
print("ok")
