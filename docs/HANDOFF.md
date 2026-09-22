commit: 10410e9・ae6ae8f・311e37f 枝 s239a(origin/master 57588fc から)。指示書 viewer-master docs/opus_s239a_karte_facts_job_20260922.md。⛔push なし・本番への書き込み 0・DDL 未適用・service key は読んでいない。
作った物: DDL pipeline/sql/karte_facts_20260922.sql(nar_karte_facts・主キー 日/場/R/馬番・列は指示書どおり・RLS は run_facts と同じ)。数え方 pipeline/karte.py(純関数)・便 cloud/karte_facts.py(--date/--track/--apply/--late-table)。
便: 手動 karte-facts.yml(date/track/mode dry|apply・late_table)。nar-refresh の run facts の次に karte facts(朝 9:30 前と 17:00 以降の便・今日と明日・|| echo で続行)。
検品: tests/test_karte.py 28 本緑・unittest 160 本中 失敗 2= test_ooi_raw_read(既知)。selftest karte 23/23・facts 48/48。割合表の道筋は anon で 1 日ぶん読むだけで通した(9 本)。
浦和 9/22 1R(anon 読むだけ・9 秒): 161/216 一致。出遅れ・使われ方・大井・相手関係・調子は 12 頭全部一致。違いは割合表が未作成(次も)とモック側の数え方(取りやめ/取消を走に数える・併走の括弧を順に数える・通算・全場)。
設計側へ: ①粘り/失速の窓= 365 日(設計の表)か通算(モック)か ②pos_var は字 '3〜7' で持った ③ベストの着順・出遅れた走の位置・脚質の回数の列は無い ④明日の style は run_facts が明日を焼かない間は空。
次の一手: push(ユーザー)→ 設計側が DDL を流す → karte-facts を late_table=true・mode=apply で 1 回(割合表)→ 以後 nar-refresh。239b/239c(viewer)は nar_karte_facts を 1 レース 1 読み。
