# 馬場差の距離の直し(d1/g1)の本番入れ手順(2026-10-26)

PowerShell 5.1 に 1 行ずつ貼る(`&&` は使わない)。行頭の空白は無し。

## 1. nar-jobs を本番へ(計算の直し)

```powershell
cd C:\Users\kouki\wt\nar-jobs-babadist
git fetch origin
git log --oneline HEAD..origin/master
```
↑ 何も出なければ次へ(出たら止めて Claude に聞く)。

```powershell
git push origin wip/baba-dist-20261026:master
```

## 2. 作り直し便を 1 回(確定済みの日にも d1/g1 を付ける)

```powershell
gh workflow run baba-rebuild.yml --repo (git remote get-url origin)
```
数分後に結果を見る(緑なら次へ。nar-refresh と同じ順番待ちの組なので、定時便の後に回ることがある):

```powershell
gh run list --workflow baba-rebuild.yml --limit 1 --repo (git remote get-url origin)
```

## 3. nar-viewer を本番へ(補正タイムの直し)

```powershell
cd C:\Users\kouki\wt\nar-viewer-babadist
git fetch origin
git log --oneline HEAD..origin/master
```
↑ 何も出なければ次へ(出たら止めて Claude に聞く)。

```powershell
git push origin wip/baba-dist-20261026:master
```

## 確かめ(どちらも Claude に頼んでよい)

- 公開ファイル `cond-stats/v1/baba-hist/ooi.json` の日に `"d1"` が付いている。
- 大井のレースの「データ・分析 → 持ちタイム」で、表の上の行が「大井 0.7倍」、1200m の走の馬場差がその日の d1 × 1.2 になっている。
- 順番を入れ替えても壊れない: d1 の無い日は、画面が今までの d × 倍率に戻る。
