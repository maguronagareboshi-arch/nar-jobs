commit: b698ee0・08bc5df・b3bc2e3 枝 s238e(origin/master 5321691 から)。設計 viewer-master docs/opus_s238e_facts_gap_20260922.md。⛔push なし・本番への書き込み 0・鍵は読んでいない(通信する確認はしていない)。
変えた所: facts.horse_key(名前,生年月日,age,レース日)= 生年月日が無い行だけ「名前|生年」(レース年−age)・新 birth_year_of・build_row が age を渡す。run_facts.py= 新 match_key(名前,生年)で fetch_past_positions/build_window を照合・nar_runs の select に age。src は今のまま。
ドライラン: --apply 無しは窓ごとに本番 nar_run_facts を読むだけ(主キー順ページング)で差を log= 本番に有/無/本番にだけ有・style 違い(空→値/値→空/別の値)・horse_key 埋まる(うち本番で空)・style/c1 埋まる率。最後に「差の合計」1 行。
便: run-facts-backfill.yml に入力 mode(choice dry/apply・既定 dry)。apply のときだけ --apply を付ける。手順名は変えていない(「: 」なし)。nar-refresh の日次(--apply)は同じ関数を通るだけ。
検品(手元・通信なし): facts selftest 48/48(鍵 9 例・生年 7 例を追加)。新 tests/test_facts_horse_key.py 14 本= 楽天 2022-10→公式 2022-11 がつながり逃げ/同名で生年違いはつながない/名前だけは鍵も脚質も空/dry は upsert を呼ばない。unittest 132 本中 失敗 2= test_ooi_raw_read(前からの既知)。
⚠ 楽天期は今まで鍵が全部空= 過去走を 1 本も引いていなかった→今回から全馬ぶん引く。④ 2014-01〜2022-10 を 1 便で流すと 106 か月×約 40 秒+upsert 約 2,576 本で timeout 120 分を超える見込み→ 3 便に割る(2014-01〜2016-12/2017-01〜2019-12/2020-01〜2022-10)。
次の一手: push(ユーザー)→ 設計側が起動の順 ①〜⑥(① dry 2025-09 で style 違う 0)。同じ馬でも楽天期は「名前|2019」・公式期は「名前|2019-04-01」と鍵の字面が 2 通り= 238a2 で画面は (名前, 生年) でつなぐ。
