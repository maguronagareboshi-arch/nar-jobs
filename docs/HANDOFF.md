commit: 10410e9・ae6ae8f・311e37f・6423014+設計の回答 ca71af9・89f66be・c99dad7 枝 s239a(origin/master 57588fc から)。⛔push なし・本番への書き込み 0・DDL 未適用・service key は読んでいない。
作った物: DDL pipeline/sql/karte_facts_20260922.sql(nar_karte_facts 42 列= 指示書の列+late_runs/style_counts/gap_days/best_finish)。数え方 pipeline/karte.py・便 cloud/karte_facts.py(--date/--track/--apply/--late-table)。
便: 手動 karte-facts.yml(date/track/mode dry|apply・late_table)。nar-refresh の karte facts 段= 朝 9:30 前と 17:00 以降。17:00 以降は先に run_facts.py --apply --from 明日 --to 明日 → karte_facts。
前提: 明日の nar_run_facts は着順・通過・上がり・オッズが空の行。当日と翌日の run facts 段(今日と前日を毎便 upsert)が結果の入った値で同じ行を上書きする。脚質は過去走だけで決まるので変わらない。
検品: tests/test_karte.py 32 本緑(run_facts が出走前の行を焼ける 1 本込み)・unittest 164 本中 失敗 2= test_ooi_raw_read(既知)・selftest karte 28/28・facts 48/48。
浦和 9/22 1R: 198/264 一致。出遅れ・出遅れた走・使われ方・間隔・大井・相手関係・調子・ベストの着順は 12 頭一致。違い= 割合表まだ・脚質と回数・モック側の数え方(取りやめ/取消・併走の括弧・通算・全場)。
次の一手: push(ユーザー)→ 設計側が DDL を流す → karte-facts を late_table=true・mode=apply で 1 回(割合表)→ 以後 nar-refresh。239b/239c(viewer)は nar_karte_facts を 1 レース 1 読み。
