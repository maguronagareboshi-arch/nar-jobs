# 馬場差の直しの本番入れ手順(2026-10-26)

やること: ① 全場で、その日の馬場差を「1000m あたり × その走の距離」で引く(距離の直し)。
② 南関 4 場は、馬場差を予想 AI の日の値(走破指数と同じ D5)にそろえる。

PowerShell 5.1 に 1 行ずつ貼る(`&&` は使わない)。行頭の空白は無し。

## 1. nar-jobs を本番へ(計算の直し・予想 AI の値の書き出し)

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
gh workflow run baba-rebuild.yml --repo maguronagareboshi-arch/nar-jobs
```
数分〜数十分後に結果を見る(緑なら次へ。nar-refresh と同じ順番待ちの組なので、定時便の後に回ることがある):

```powershell
gh run list --workflow baba-rebuild.yml --limit 1 --repo maguronagareboshi-arch/nar-jobs
```

## 3. nar-viewer を本番へ(補正タイム・南関の呼び名)

```powershell
cd C:\Users\kouki\wt\nar-viewer-babadist
git fetch origin
git log --oneline HEAD..origin/master
```
↑ 何も出なければ次へ(出たら止めて Claude に聞く)。

```powershell
git push origin wip/baba-dist-20261026:master
```

## 4. 南関の予想 AI の値は自動で入る(手の作業なし)

- 次の予想 AI の便(nar-ai-v3・毎日 14:30 ごろ・書き込みあり)が、nar_meta `nankan_d5` に南関の日の値を書く。初回は全期間を書く。
- その後、30 分おきの便(baba.py)と翌朝 5:40 の便(baba_hist.py)が、南関 4 場の馬場差を毎回この値にかぶせる。確定済みの日も含む。
- それまでの南関は、サイトの計算(距離の直しつき)のまま出る。

## 確かめ(Claude に頼んでよい)

- nar_meta `nankan_d5` に日が入っている。
- 公開ファイル `cond-stats/v1/baba-hist/ooi.json` の日に `"d1"` と `"s":"ai"` がある。
- 大井のレースの「データ・分析 → 持ちタイム」で、表の上の行が「大井 1.0倍」になっている。1200m の走の馬場差は、その日の値 × 1.2 になっている。
