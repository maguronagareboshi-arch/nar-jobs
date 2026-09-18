# §212 能検の --backfill は既存の日を捨てない(合流する)(Opus・nar-jobs) 2026-09-19

## 出どころ
大井の能検が 13 日 → 3 日に減っていた(ユーザー 9/19 発見)。cloud/noken_public.py の main(3190 付近)= `if args.backfill: merged = new_days else: merged = stored["days"] + new_days`= **総当たりの結果で置き換える**ので、公式サイトが GitHub からの取得を拒んだ 9/9(§195d の時期)の総当たりで 3 日しか取れず、10 日分が消えた。9/19 に手元から総当たりし直して 14 日に戻した(nar_meta ooi_noken・noken_index も作り直し)。

## 変える所(cloud/noken_public.py だけ)
**A.** `--backfill` でも `merged = stored["days"] + new_days`(同じ鍵の日は**新しい方**= 今の day_key の重複除去どおり)。⛔既存の日を消す道を無くす。日を消したいときは新しい `--replace` 旗(明示)だけ= 既定は合流。
**B.** 取れた日数が既存より少ないとき(`len(new_days) < len(stored["days"])`)は log に 1 行「⚠ 取れた日 n < 既存 m= 合流して書く(消さない)」。
**C.** tests(≤ 25 行)= 既存 13 日+新 3 日(重なり 3)→ 13 日/`--replace` のときだけ 3 日。
## 合格
`py -3.12 -X utf8 -m unittest discover -s tests -q` 緑。`--venue ooi --dry-run --out`(手元)= 叩いた日/試験のあった日のログのあとに合流の行。
## 触らないもの
収集の中身・他の場・DB。枝 s212-noken-merge(nar-jobs master から)・commit のみ・push しない。
## 報告
HANDOFF 7 行。
