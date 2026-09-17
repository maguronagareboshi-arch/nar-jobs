# §202 直前便(nar-ai-last)の回りの見直し(Opus・nar-jobs) 2026-09-17

## 出どころ(実測 9/16)
直前の印(timing=last)が書けたのは 48 レース中 34(9/12〜9/17 は 9〜44/日)。落ちる仕組みは 3 つで、どれも「体重が DB に着くまで」と「1 周の長さ」の位相の問題= 模型や規則の問題ではない。
1. 体重は nar-refresh(cron :07/:37 + pg_cron :05/:25/:45 の dispatch)が公式 CSV から本番 nar_runs に入れる= 最長 30 分遅れ。
2. 直前便の 1 周は 15 分おき(:01/:16/:31/:46)で、周の頭に本番から当日分を \copy して特徴量を作り直す→ **1 周 220 秒**。印を書くのは周の**終わり**なので、:31 に始めた周は :35 に書く= 発走 15 分前の締切(DB トリガー nar_ai_marks_guard)を跨いで捨てられる(9/16 名古屋4R 発走 15:50・締切 15:35・:31 の周で捨て)。
3. 合わせて「公式が体重を出してから印が書けるまで」が最悪 30+15+4= 49 分。公式の発表が発走の 45〜60 分前なので、位相しだいで落ちる。

## 変える所(全部 nar-jobs・⛔本番 DB への書き手は増やさない)
**A. 新規 `cloud/ai_last_today.py`**= 公式の当日 ZIP を 1 回取って、**手元(ジョブ内 Postgres)の**当日行に体重と馬場を重ねる。
- 取り方は refresh.py と同じ部品を呼ぶ= `nar_official_csv.download_url('race', scope='daily', race_date=DAY)` → `download_archive` → `normalize_archive(kind='race', scope='daily', ...)`。⛔新しい取り方・新しい URL を作らない。
- 出力= `today/official_horses.tsv`(track, race_date, race_no, runner_number, body_weight, body_weight_change)と `today/official_races.tsv`(track, race_date, race_no, going, post_time)。体重が無い行は出さない(NULL で上書きしない)。
- yml の周の中で、本番からの \copy の**後**に `psql` で `create temp table` → `\copy` → `update public.nar_runs u set body_weight=o.body_weight, body_weight_change=o.body_weight_change from tmp o where (u.track,u.race_date,u.race_no,u.runner_number)=(o.track,o.race_date,o.race_no,o.runner_number) and u.body_weight is null` と `update public.nar_races ... set going=o.going where o.going<>'' and coalesce(r.going,'')=''`。⛔手元だけ・本番には書かない(本番の体重は今までどおり refresh.py の役)。
- ログ 1 行= 「official today: 体重あり N 走・DB に無かった M 走(レース名)」= M が価値の証拠。
- 取りに行く条件(公式に負荷をかけない)= 当日のレースのうち **発走まで 15〜90 分で体重が全頭そろっていない**レースが手元にあるときだけ取る。無ければ「official today: skip(待ちのレース無し)」で飛ばす。
- 失敗(ZIP でない・タイムアウト)はログして**周を止めない**(DB の値のまま予測する)。
**B. yml `nar-ai-last.yml`**
- 周の間隔 15 分 → **5 分**(`SLEEP=$(( 300 - (NOW - T0) ))`・見出しの字も「every 5 minutes」)。1 周 220 秒なので空きは 80 秒。`timeout-minutes` 358 のまま(09:00〜14:55 / 15:00〜20:55 は不変)。
- 周の順= 本番 \copy → **A(公式 ZIP を手元に重ねる)** → refresh_nar_ai_feat → predict → write。
- `on.schedule` の 2 本(`0 0` / `0 6`)を**外す**= 起動は pg_cron の dispatch(09:08 / 15:08 JST・write=yes・once=no)だけにする。理由= GitHub の schedule は 3 時間遅れて 12:23 に始まり、concurrency で dispatch と押し合い(9/15・9/16 に 15:08 の dispatch が cancelled)。⛔`WRITE`/`ONCE` の既定は dispatch の inputs から(schedule 分岐は消してよい)。
- ⛔手順名に「: 」を書かない(#yml 規則)。
**C. tests(≤ 60 行)**= A の「DB に無い体重だけ重ねる」「NULL で上書きしない」「取りに行く条件(発走まで 15〜90 分で未そろい)」を純関数で。

## 効果の見込み(実測で確かめる)
公式の発表 → 印まで最悪 5+4= 9 分。発走の 24 分前までに体重が出ていれば書ける(今は 49 分前)。狙い= 直前の印 34/48 → 45 以上/48。

## 合格
1. 手押し `gh workflow run nar-ai-last.yml -f write=no -f once=yes` が緑・ログに「official today: …」の行と「round 1 took ≈220 s」。
2. 翌日の 15:08 の便(pg_cron)で `nar_ai_marks timing='last'` の本数を Fable が数える(SQL は Fable)。
3. `gh run list -w nar-ai-last.yml` に yml 名の失敗 run が無い(yml を触ったら必ず見る)。

## 触らないもの
pipeline/ai/base_v1.py(印の規則・締切 15 分)・pipeline/sql/ai_feat_*.sql・refresh.py・本番のトリガー・pg_cron。枝 s202-ai-last(nar-jobs master から)・commit のみ・push しない。
## 報告
HANDOFF 7 行(手押し run の URL と「official today」の行を貼る)。
