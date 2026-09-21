# Opus 指示書 §238a 派生表 nar_run_facts+便+検算(2026-09-21)

設計= docs/proposal_s238_run_facts_20260921.md(必読)。規則= docs/opus_rules.md。⛔本番 DB に書かない・重い SQL を流さない(集計は Actions 内か手元)。報告は HANDOFF 7 行×200 字。

## 作るもの(nar-jobs・枝 s238a)
1. `pipeline/sql/run_facts_20260921.sql`= 表 nar_run_facts(設計の列・主キー race_date,track,race_no,umaban・anon 読取可・RLS は既存表に倣う)。適用は Fable(鍵)。
2. `pipeline/facts.py`= 1 関数群。入力= nar_races(corners・distance・going・weather)・nar_runs・nar_own_runs/nar_paper_runs/nar_kb_runs(前半 3F・優先順 own>paper>kb>est)・nar_odds_ticks(発走直前の単勝)。出力= 派生行。通過順の解析は cloud/tenkai.py:183 corner_ranks と ai_feat_20260908.sql の規則を**1 つに統合**し、単体テストに 3 か所の既知の入出力例を入れる。脚質= tenkai.py の style_of と同じ規則(直近 5 走・365 日窓・閾値 .2/.4/.7)を as-of で(その日より前の走だけ)。
3. `cloud/run_facts.py`= 日次便。既定= 当日と前日ぶん(upsert)。`--from YYYY-MM-DD --to` で遡り。REST で読み・upsert は load_nar_official.upsert に倣う。workflow は nar-refresh.yml の最後(結果が確定した後)に 1 手順追加(手順名に「: 」禁止)。
4. `tests/run_facts_check.py`= 検算。12 か月の対象で 派生表 vs (a) tenkai.py の corner_ranks/style (b) ai_feat の corner/style 列 (c) js/data.js cornerRanks(node で呼ぶ・統合ビューア origin/master の js/data.js を写して使う)の一致率を出す。一致 100% でなければ差の例 10 件と理由を docs/notes_s238a_check.md に。
5. **写しの置換は次段(238a2)**= 今回は置換しない。派生表と検算が通ってから。

## 合格条件
- 2025-09〜2026-09 の遡りが Actions 内で 90 分以内(実測を報告)。
- 検算 (a)(b)(c) 一致 100% か、差の理由が全部 notes に書かれている。
- 欠けは NULL(0 で埋めない)。first3f_src が全行に入る(est は §224f の推定を入れる場合のみ)。
- 本番には SQL も便も当てない(Fable が鍵で当てる)。
