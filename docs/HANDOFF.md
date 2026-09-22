commit: e4fdca7..0b0ab4d(枝 s240・7 コミット= 土台 / 表ごと 5 本 / 検算と巻き戻し・push なし)
検品: ⛔本番 DB には一切触っていない(SQL も REST も無し)。手元は `py -3.12 tests/test_partition_s240_sql.py` が ALL PASS(8 ファイル)= begin と commit の数・vacuum がトランザクションの外・$$ の閉じ・区画の範囲が隙間なく続く・attach が minvalue→2022-11-01・rename 2 本・statement_timeout・notify pgrst。実物との一致は各ファイルの §0 を流して人が確かめる。
通信: +0(表を増やしていない。読む先も今までと同じ 5 表)
回帰: SQL と覚書と検査だけ= 画面・便のコードは 1 行も触っていない。既存の読み手(js/data.js の約 35 本・Actions の \copy・nar_search_runs / _v2)は表名が変わらないので変更 0。
変えた点: `pipeline/sql/partition_s240/` に 8 本(00 控え / 10 votes / 20 payouts / 30 races / 40 runs / 50 run_facts / 98 巻き戻し / 99 検算)。各表 §0 実物の確認 → §1 親と区画 6 → §2 年ごとの写し → §3 delete と check と attach → §4 rename → §5 grant と vacuum。ほか `docs/notes_s240_migration.md`(夜に当てる順・所要・止めどころ)・`tests/test_partition_s240_sql.py`・設計書の写し。
⚠: `nar_race_payouts` の create table が手元のどこにも無く、列(payouts / source_snapshot_hash / updated_at)は `load_nar_official.py` の conv_payout からの**推定**= §0-1 の結果と違ったら `20_…` の §1 を直してから流す。残りの注意点(索引名の付け方・区画の RLS が抜けると匿名キーで 0 行・2028 の区画が無い)は notes_s240_migration.md §5。
要判断: ①当てる順と夜の時間割(全部で 2.5〜3 時間・小さい 3 表だけで止めてもよい)②`nar_runs_race_idx` の drop は今回やらず別の回に回した ③`nar_run_facts` の読み手 0 の列を落とすかは未着手(ユーザー判断のまま)④`docs/opus_rules.md` は写しただけで commit していない(公開リポに本体名・メールを書かない規則のため)。
