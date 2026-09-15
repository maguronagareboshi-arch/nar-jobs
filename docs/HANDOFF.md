commit: 枝 s181-auction-today(master d280e95 から・⛔push なし・⛔--apply は流していない)= 新規 cloud/auction_today.py(107 行・noken_debuts.py の req/rows/log/load_env を import して使う)・.github/workflows/nar-refresh.yml の noken debuts の段の run に 1 行(`python cloud/auction_today.py --apply || echo …(続行)`= 失敗しても便は止めない・手順名は変えていない)
検品: 手元 `--dry-run`(2026-09-15 13:53 JST・匿名キー)= レース 60・出走 639 行・取引のある出走 373 行・**一番新しい取引がセリ市場でない出走 221**= 手元の /auction が同じ時刻に出していた「初出走 17 頭+畳んだ 204 頭」= 221 と一致。発走時刻なし 0・note あり 44(取消/除外などの字)
通信: 1 回= nar_races 1 本+nar_runs 1〜2 本(1000 行ごとに続き)+auction_sales 80 頭ずつ(今日は 8 本)+書き込み 1 本。30 分ごと(nar-refresh の回数)・公開リポなので分数は無料枠の外
回帰: 既存の便は noken debuts の段に 1 行足しただけ(noken_debuts.py の中身は触っていない・後ろの行が失敗しても echo で続行)
変えた点: value= {built, date, rows:[{track, no, umaban, name, post_time(HH:MM), note, sales:[{date, source, item_id, price, sold, category, url, runs_after, first_after}] 新しい順}]}。rows は取引が 1 件以上ある出走だけ・同じ出走(track, no, umaban)は 1 行。⛔初出走・除外・頭数の判定は書かない(画面の 1 か所)。note= finish_note(無ければ margin)の字そのまま。開催が無い日も rows=[] を書く・読み取りに失敗したら書かない(前の値が残る)。--dry-run は SUPABASE_ANON_KEY でも動く(--apply は SUPABASE_SERVICE_KEY 必須)
⚠: 一度だけ手元の読み取りが HTTPError で失敗して「書かない」で終わった(再実行 2 回は成功= 一時的とみている・原因の status は取れていない)。便の上では 30 分後に取り直す
次: 検品役が枝を読む → ユーザーが push → Fable が dispatch で --apply 1 回 → REST で nar_meta 'auction_today' の rows を確認 → viewer の枝 s181-auction-entry
