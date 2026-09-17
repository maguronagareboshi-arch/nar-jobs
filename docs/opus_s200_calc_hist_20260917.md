# §200 D1 他場の計算(番組賞金・表の位置)のレース日時点を表に積む(Opus・nar-jobs) 2026-09-17

## 出どころ
§196 G で「レースより後の値は出さない」→ 過去のレースの左欄「表の位置 —」「あと —」(高知・帯広・佐賀・東海・兵庫)。南関は §196b/§199 で履歴から出せるようになった。他場の計算は **走歴(nar_horse_prize.runs)と asof だけで決まる純関数**(cloud/class_calc.py の kochi_calc / obi_calc / saga_calc / tokai / hyogo)なので、**レース日を asof にして計算し直せば過去分も復元できる**(取得なし)。

## 器(Fable が本番に作成済み・pipeline/sql/class_calc_hist_20260917.sql)
`nar_class_calc_hist`(code, prefix, asof, calc jsonb)。asof= **レース日**(当日の便が calc 列に書くときの asof(= きょう)と同じ取り方。lag は計算の中)。calc は nar_horse_prize.calc と同じ形(prefix/src/asof/basis/value/cls/next/note/hide…)。

## 変える所(cloud/class_calc.py に段を 1 つ・≤ 150 行)
- `--hist-days N`(既定 3)= 各 prefix について、直近 N 日にその場で走った(または出走予定の)馬 × その馬がその場で走った日 D(窓の中)ごとに `calc(asof=D)` を作り upsert(on_conflict= code,prefix,asof)。**同じ馬・同じ場の走の日ごとに 1 行**(走っていない日は作らない)。
- `--hist-all --since 2024-01-01`= 初回の埋め(その場の 2024-01-01 以降の走の日すべて・手押し・Fable が回す)。`--shard i/n` 可。
- 計算本体は既存の関数をそのまま呼ぶ(⛔式・線の表・lag・note の規則は触らない)。`age_at(asof)` もそのまま。転入前の note も同じ。
- 材料は既存の fetch(nar_horse_prize.runs・births・entered)を使う。走の日 D は runs の d(その prefix の場の走・jra でない)から。
- `--apply` の既存の流れ(calc 列)は不変。hist の段は `--apply` のあと(hist で失敗しても calc 列は残る)。
- tests(≤ 60 行)= 走の日ごとに 1 行・asof=D・calc 列(asof=きょう)と D=きょう の行が同じ値。

## 合格
1. オラクル= 高知の 1 頭(2026-09-13 に走った馬)で、`--hist-days 5` の D=9/13 の行の value/cls が、9/13 の便が書いた calc 列(HANDOFF に載っている値か DB の updated_at で確かめる)と一致。
2. `--hist-all` を `--out` で手元に流し、prefix ごとの行数・cls null の行数を報告(本番投入は Fable)。
3. unittest 緑・py_compile 通過。DB へは書かない。

## 触らないもの
nar_horse_prize.calc の書き方・線の表(class.js)・yml(Fable が朝の便に `--hist-days 3` を足す)・viewer(D2 は別文書)。push しない。

## 報告
HANDOFF 7 行(通信= DB の読み本数・所要)。枝 s200-calc-hist。
