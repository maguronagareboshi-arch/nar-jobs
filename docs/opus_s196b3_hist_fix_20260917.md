# §196b 工事 B 履歴の「着順なし」= 中止レースは 0 点(Opus・nar-jobs) 2026-09-17

## 出どころ
第 2 段の初回投入(本番 45,536 行)で points null 2,188 行。原因の「着順なし 275 走」を Fable が本番で数え直した結果=
**着順の無い走は、①取り止めになったレース(nar_races.cancelled が空でない・302 走)か ②競走中止(finish_note)しか無い**
(2024 年以降・南関 4 場・取消/除外を除く・過去日で「着順なし・注記なし・取り止めでない」走は 0)。
= 「結果の欠け」ではなく、取り止めレースを「決められない」にしている。取り直しは要らない。

## 変える所(cloud/nankan_hist.py だけ・≤ 30 行)
1. `run_points`: finish が None で注記が無く、**そのレースの nar_races.cancelled が空でない**なら `0, "取り止め"`(走っていない)。
   注記が「失格」「降着」を含む= 失格は原文どおり 0 点扱い(第 1 段 s196b_rules.md ④ L234)。それ以外の「着順なし」は今のまま None。
2. nar_races の読み(REST・`--from-csv` 両方)に `cancelled` を足す(REST の select と CSV の列)。
3. `--help` が落ちる(argparse の help 文に `%` があると書式で落ちる)= `%%` にする。
4. tests/test_nankan_hist.py に 2 項(取り止め= 0・失格= 0)。
⛔ hist_rows の official の起点・kaku の規則・表の列は触らない。DB へは書かない(--all の投入は Fable)。

## 合格
- `python -m unittest discover -s tests -p "test_nankan*.py"` 緑・`--help` が出る。
- `--from-csv`(第 1 段の CSV・data/recon)で `--all --out` を流し、**決められない走の内訳に「着順なし」が残らない**(残るなら例を 5 つ HANDOFF に)。points null の行数(前 2,188)を報告。

## 報告
HANDOFF 7 行。枝 s196b-fix・commit まで・push しない。
