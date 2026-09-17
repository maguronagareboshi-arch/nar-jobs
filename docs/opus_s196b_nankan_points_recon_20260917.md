# §196b 南関 格付ポイントの過去復元(下調べ・Opus) 2026-09-17

## 出どころ
§196 で「レースより後の値は出さない」にしたら、過去のレースの格付ポイント/あと がほぼ「—」になった(nar_nankan_points は馬ごと最新値だけ)。ユーザー: 「過去にどういうポイントでどう動いたか(昇級・降級)が追えないと意味がない。研究にも使う」。
→ 過去の任意日のポイントと格を**逆算で復元**する。この文書は第 1 段(規則の確定+50 頭の検算)。表と画面は第 2 段(Fable が SQL・別文書)。

## 復元の式(2026-07-10 に旧道具で 400 頭矛盾 0 を確認済み)
- ある日 D のポイント= いまの値(nar_nankan_points.points・基準日 asof) − **asof 以降に稼いだ着内ポイントの合計**。
  ⚠ 「asof 以降」= 基準日は「最後に走った日の翌日」なので、race_date >= asof の走を引く。
- 着内ポイント= 公式の表(下)× 競走種別(nar_races.race_kind= 普通/特別/重賞/準重賞)× レースの格(nar_races.condition / race_name)× 着順 1〜5。同着は頭数で等分・失格/降着は変更後の着順。6 着以下 0。
- 他地区(JRA・他場)遠征分= 賞金 ÷ 1万(nar_horse_prize.runs の jra/他場の走・prize)。
- ある日の格= その日の直前に「格が反映された時点」の格。反映の時点は下の「要確認」で決める。

公式の着内ポイント表と半期×馬齢の格付基準は `C:\Users\kouki\.claude\projects\C--Users-kouki-OneDrive------------------3-\memory\nankan-kakuzuke-points.md` に原文採取済み(2026-07-10)。**数値はそのまま使ってよいが、規則の文は下の①〜④を原文で確認してから使う。**

## 材料(本番 DB nar-official・読みだけ・psql/REST どちらでも)
| 表 | 使う列 | 備考 |
|---|---|---|
| nar_nankan_points | code, horse_name, kaku, points, asof, birth_date, last_run | 3,761 頭(points null 420= 抹消) |
| nar_runs | track(大井/船橋/川崎/浦和), race_date, race_no, horse_name, finish, finish_note, age | 2022-11〜 14.6 万走 |
| nar_races | track, race_date, race_no, race_name, race_kind, condition, prize_yen | race_kind は 2024-01 から全件あり |
| nar_horse_prize | code, runs(jsonb: d, track, jra, cls, prize, fin…) | 遠征分の賞金 |
⚠ 馬の同定は馬名(同名馬は birth_date で切る)。⚠ 本番 DB に重い SQL を流さない= 必要な列を 1 回 \copy して手元で計算(feedback-no-heavy-compute-on-prod-db)。

## 手順
1. **規則の確定(原文パース)**= https://www.nankankeiba.com/info/qanda/program.html を cp932 で読み、タグ除去の原文から次を引用付きでメモ(docs/s196b_rules.md)。WebFetch の要約は数値が変わるので使わない。
   ① 昇級の時点= 開催ごと(開催最終日終了後に基準以上なら次開催から)か、半期だけか
   ② 降級の時点= 半期切替(1/1・7/1)だけか
   ③ 転入馬・移行時(2023 以前の賞金換算)・2 歳→3 歳の扱い・4 月以降の 3 歳 C3
   ④ 同着・失格降着・出走取消/競走中止の扱い
   原文に無い事項は「原文に無い」と書く(推定で埋めない)。
2. **逆算の道具**= tools/nankan_recon.py(手元実行・DB 書き込み無し)。入力= 上の 4 表の \copy CSV。出力= 馬×レース日の {points_before, points_after, earned, kaku_before} の CSV。
3. **検算 50 頭**= 直近 2 週間の南関の出走馬から無作為 50 頭(2024 年以前から走っている馬を 20 頭以上含める)。各馬の過去の出馬表 `https://www.nankankeiba.com/uma_shosai/{raceid}.do`(cache= data/cache_nankan/・1.8 秒間隔・cp932)に載っている**当時の格**と、復元した kaku_before を突き合わせる。レースの raceid の作り方は cloud/nankan_points.py の calendar 経由と同じ。
4. **不一致の分類**= 一致率を出す前に、不一致を全部「原因」で分ける(遠征分/同着/転入/規則①②の読み違い/走歴の欠け/その他)。⛔ 分類する前に閾値やパッチで合わせに行かない。
5. 手元で 2024-01-01 以降の**全頭**を流し、points_before < 0 になる頭数(あってはならない)と、走歴の欠けで復元できない頭数を数える。

## 合格
- s196b_rules.md に①〜④が原文引用付きである(無いものは「原文に無い」)。
- 50 頭×全レースで格の一致率と、不一致の分類表。points_before < 0 = 0 頭。
- 全頭の復元可能率(何頭中何頭が 2024-01-01 まで遡れるか)。

## 触らないもの
本番 DB への書き込み・Actions yml・cloud/*.py の既存動作・viewer。push しない(commit まで)。

## 報告
docs/HANDOFF.md 7 行(commit/検品/通信/回帰/変えた点/⚠/要判断)。通信= nankankeiba への request 数と所要。⚠筆頭= 復元できない馬の割合。要判断= 表の設計に効く発見(例: 昇級が開催ごとなら格の履歴表は開催単位)。
