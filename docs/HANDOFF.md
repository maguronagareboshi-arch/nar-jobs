commit: 56408ba・eab7d21 枝 s238c(origin/master 57588fc から)。設計= docs/proposal_s238c_coverage_20260922.md §1。⛔push なし・本番への書き込み 0・鍵は読んでいない(読みは公開 anon キーだけ)。

作った物= cloud/coverage_matrix.py(網羅表)/ tests/test_coverage_matrix.py 13 本 ALL PASS / nar-refresh.yml に手順「coverage matrix (morning only)」(派生表の後・朝だけ・|| echo で続行)/ coverage-backfill.yml(from・to・mode)。

数え方= 月ごとに nar_races/runs/run_facts/race_payouts/race_votes を列を絞って REST で読み手元で数える(⛔group by 禁止)。項目 10= finish time last3f weight c1 style first3f odds_close payout votes。母数は payout/votes がレース数・他は出走数。

出力= nar_meta 'coverage:v1'(索引= built/years/venues/cols/keys)+ 'coverage:v1:YYYY'(年ごとの cells)。⛔年で割ったのは 200KB を超えないため(1 か月 3.2KB・1 年 40KB 前後)。既定は直近 2 か月だけ数え直し、全期間は backfill で。

検品(--dry 2026-08)= 13 場 1,278 レース 12,733 出走・通信 31 回 12 秒。答え合わせ= 同じ窓の REST 件数 1,278 と一致。枡の例 ooi 2026-08= races72 runs839・finish98.9 time98.9 last3f98.9 weight99.4 c1 99.2 style87.6 first3f99.0 odds_close0.0 payout100.0 votes0.0。

kochi 2026-08 は first3f 29.8・odds_close 0.0・votes 0.0= 欠けが 0% として出る(⛔空欄で誤魔化さない)。母数 0 の項目だけ null。全期間 150 か月は 1 か月 12 秒として約 30 分・通信 約 4,600 回の見込み。

⚠指示書の cloud/coverage.py は既に §118「データの状態」(nar_meta 'coverage'・nar-refresh が毎朝呼ぶ)が使っていたので潰さず coverage_matrix.py にした。要判断= ①この名前でよいか ②初回 backfill を mode=apply で 2014-01〜当月に流すか。
