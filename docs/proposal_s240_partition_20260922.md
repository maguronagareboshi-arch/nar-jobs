# §240 表を年で区切る(宣言的パーティション)— 設計 2026-09-22

## なぜ
9/21 に 10 年分(nar_runs +129 万行・nar_run_facts 190 万行)を入れたら、本番(当時 NANO 0.5GB・9/22 Small 2GB へ)の RAM に よく読む表(nar_runs 685MB+nar_run_facts 681MB)が乗らず IO 待ちでサイトと便が詰まった。ユーザー「なるべく課金したくない」→ 無料の根本策= 毎日の便と通常画面が触る行を「今年・去年」だけに戻す。データは捨てない。
教訓= [[feedback-capacity-check-before-bulk-load-20260922]]。

## 方式= Postgres の宣言的パーティション(race_date で年ごと)
- 対象 5 表= nar_races / nar_runs / nar_run_facts / nar_race_payouts / nar_race_votes。5 表とも **PK に race_date が入っている**ので PK を変えずに区切れる。
- 表名・列・PostgREST の URL は不変= **画面・便・AI の読み手/書き手のコード変更 0**(Opus 下調べ 9/22: 読み手 約 35 本は日付指定・日付なしは馬名系 4 本+全期間の便 6 本)。
- 区画= 〜2022-10(archive 1 区画)・2022-11〜2023・2024・2025・2026・2027(先に作る)。ON CONFLICT の upsert は PK に区画キーがあるので今のまま動く。
- 効果= 日付指定の問い合わせは区画の剪定でその年だけ読む。毎日の upsert は今年の区画だけ。古い年はアクセスされない限りメモリに乗らない。

## 移行の手順(1 表ずつ・夜間・他セッションの本番作業は停止・1 本ずつ)
1. 新しい親表 `nar_runs_p`(partition by range (race_date))+ 区画 2022_11_2023 / 2024 / 2025 / 2026 / 2027 を作る(索引は親に付ける= 各区画に自動)。
2. 2022-11 以降の行(約 61 万行)を `insert … select` で親へ写す(年ごとに分けて・1 回 10〜20 万行)。
3. 旧表から 2022-11 以降を delete → 旧表に `check (race_date < '2022-11-01')` を付ける(既存行の走査= 読みだけ)→ `attach partition … for values from (minvalue) to ('2022-11-01')`。
4. 短い排他ロックで `rename`(旧親→ `_old` 名は残さない= 旧表は archive 区画として親の下に入る)→ PostgREST に `notify pgrst,'reload schema'`。
5. RLS/grant/policy を親に写す(区画は親の設定を継承しない= 5 表とも anon select を親と区画に付ける)。`vacuum analyze` を区画ごとに。
6. 検算= 5 表とも 行数(移行前後)・当日の便(nar-refresh)成功・画面 3 本(レース/馬ページ/データの範囲)の応答 100ms 台・`explain` で日付指定が 1 区画だけ読むこと。
- IO の見込み= 写すのは 61 万行×5 表(全コピーの 1/3)。旧表の check 制約の走査は読みだけ。

## あわせて縮める(読み手 0 の列と重複索引)
- nar_run_facts= horse_name(nar_runs と重複)・horse_key・n1..n4・style_p・style_n・last3f は読み手 0 → ⛔列を落とすかは **ユーザー判断**(規則: 列を落とす決定は先にユーザーへ)。落とさない場合もそのまま区切れる。
- nar_runs の索引 `nar_runs_race_idx`(PK と同じ列集合)= 区切った後は不要の見込み → drop 候補。
- 馬名で全期間を引く 3 本(馬ページ・馬名検索・能検)は全区画を見る= 次段で派生表の鍵に寄せる(§238a2)。

## 合格条件
- 5 表の行数が移行前後で一致・nar-refresh / nar-ai-feat / run_facts / votes-daily が成功。
- トップ・レース・馬ページの DB 読みが平均 100ms 以下(Small で)。
- `explain (analyze)` で race_date 指定の問い合わせが 1 区画だけ。

## 費用の対策(同時に)
- 旧 DB(kochikeiba-viewer・月 約 $10)を一時停止= 読み手 0 の確認後(Opus 9/22)。Small(+$5)を相殺。
