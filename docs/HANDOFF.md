commit: 10410e9・ae6ae8f・311e37f・6423014+設計の回答 ca71af9・89f66be・c99dad7 枝 s239a(origin/master 57588fc から)。⛔push なし・本番への書き込み 0・DDL 未適用・service key は読んでいない。
作った物: DDL pipeline/sql/karte_facts_20260922.sql(nar_karte_facts 42 列= 指示書の列+late_runs/style_counts/gap_days/best_finish)。数え方 pipeline/karte.py・便 cloud/karte_facts.py。
便: 手動 karte-facts.yml(date/track/mode dry|apply・late_table)。nar-refresh の karte facts 段= 朝 9:30 前と 17:00 以降。17:00 以降は先に run_facts.py --apply --from 明日 --to 明日 → karte_facts。
前提: 明日の nar_run_facts は着順・通過・上がり・オッズが空の行。当日と翌日の run facts 段(今日と前日を毎便 upsert)が結果の入った値で同じ行を上書きする。脚質は過去走だけで決まるので変わらない。
検品: tests/test_karte.py 32 本緑(run_facts が出走前の行を焼ける 1 本込み)・unittest 164 本中 失敗 2= test_ooi_raw_read(既知)・selftest karte 28/28・facts 48/48。
浦和 9/22 1R: 198/264 一致。出遅れ・出遅れた走・使われ方・間隔・大井・相手関係・調子・ベストの着順は 12 頭一致。違い= 割合表まだ・脚質と回数・モック側の数え方(取りやめ/取消・併走の括弧・通算・全場)。
次の一手: push(ユーザー)→ 設計側が DDL を流す → karte-facts を late_table=true・mode=apply で 1 回(割合表)→ 以後 nar-refresh。239b/239c(viewer)は nar_karte_facts を 1 レース 1 読み。

commit: 7acc513 (枝 s238c2 / origin/master から・push なし)
検品: 通信なしの検算のみ= `py -3.12 -m unittest discover -s tests -p "test_coverage_matrix.py"` 19 本 ALL PASS・`cloud/coverage_matrix.py --selftest` OK。⛔本番 DB には触っていない(読みも書きもしていない)
通信: +0(表は増やしていない。読む先は今までと同じ nar_races/nar_runs/nar_run_facts/nar_race_payouts/nar_race_votes/nar_meta)
回帰: 触ったのは網羅表の便だけ / 他の便への影響= なし(coverage_matrix.py と その tests しか変えていない)
変えた点: cloud/coverage_matrix.py= ①年が終わるごとに coverage:v1:YYYY と索引を upsert(落ちても焼けた年は残る・書けなかった年は索引に載せない)②読みは 6 回出直す(10/20/40/60/90/120 秒・待ち 120 秒)③止まると「続きは --from YYYY-MM」と出る / tests= 検算 13→19 本
⚠: 9/21 の run 35670543476 は 2015-11 まで数えた結果を全部捨てて rc=2・本番 nar_meta に coverage:v1* が 1 行も無い= **2014-01 からやり直しが要る**。同時刻に票数の遡り 10 本が本番へ書いていたのが重さの元なので、⛔網羅表と票数の遡りを同時に流さない
要判断: push の可否(公開リポはユーザー)。流し直しは coverage-backfill を from=2014-01 to=2026-09 mode=apply で 1 本・票数の便が止まっている時間に
