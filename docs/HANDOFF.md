commit: 7acc513 (枝 s238c2 / origin/master から・push なし)
検品: 通信なしの検算のみ= `py -3.12 -m unittest discover -s tests -p "test_coverage_matrix.py"` 19 本 ALL PASS・`cloud/coverage_matrix.py --selftest` OK。⛔本番 DB には触っていない(読みも書きもしていない)
通信: +0(表は増やしていない。読む先は今までと同じ nar_races/nar_runs/nar_run_facts/nar_race_payouts/nar_race_votes/nar_meta)
回帰: 触ったのは網羅表の便だけ / 他の便への影響= なし(coverage_matrix.py と その tests しか変えていない)
変えた点: cloud/coverage_matrix.py= ①年が終わるごとに coverage:v1:YYYY と索引を upsert(落ちても焼けた年は残る・書けなかった年は索引に載せない)②読みは 6 回出直す(10/20/40/60/90/120 秒・待ち 120 秒)③止まると「続きは --from YYYY-MM」と出る / tests= 検算 13→19 本
⚠: 9/21 の run 35670543476 は 2015-11 まで数えた結果を全部捨てて rc=2・本番 nar_meta に coverage:v1* が 1 行も無い= **2014-01 からやり直しが要る**。同時刻に票数の遡り 10 本が本番へ書いていたのが重さの元なので、⛔網羅表と票数の遡りを同時に流さない
要判断: push の可否(公開リポはユーザー)。流し直しは coverage-backfill を from=2014-01 to=2026-09 mode=apply で 1 本・票数の便が止まっている時間に
