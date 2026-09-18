commit: 枝 s212-noken-merge(nar-jobs・origin/master 6d65a0e の上・設計 docs/opus_s212_noken_backfill_merge_20260919.md・⛔push/merge/deploy なし・⛔収集の中身・他の場・DB・yml は触っていない)= **cloud/noken_public.py だけ**= 新規 `merge_days(stored, new, day_key, backfill, replace)`(日付降順・同じ鍵は 1 日)に main の合流を切り出し/**A** `--backfill` でも既存の日と合流(⛔既存の日を消す道は新しい旗 `--replace` だけ= 既定は合流)/**B** 取れた日 < 既存 のとき log「⚠ 取れた日 n < 既存 m= 合流して書く(消さない)」(--replace のときは出さない)/**C** tests/test_noken_merge.py(3 本・31 行)= 既存 13+新 3(重なり 3)→ 13 日・重なりは新しく取った方/--replace → 3 日/差分(旗なし)→ 14 日で不変
検品: `unittest discover` **109/109 緑**・git diff --check 通過/`--venue ooi --dry-run --out`(手元・鍵なし)= 「叩いた日 23 / 試験のあった日 3 / 取得失敗 0」→「ooi: 新規 3 日 / 合計 3 日」(鍵が無いので既存 0 日= 合流の行は出ない)/**既存 13 日を手で与えた試し**(sb_get_meta と collect を差し替え・通信なし・dry-run)= `--backfill` →「⚠ 取れた日 3 < 既存 13= 合流して書く(消さない)」「新規 3 日 / 合計 13 日」・`--backfill --replace` →「新規 3 日 / 合計 3 日」
通信: +0
回帰: 旗なし(毎日の便)の合流は今までと同じ(既存を先に置く)・頭出し(offsets)は元から合流= 不変・全場とも同じ main を通るので他の場の --backfill も合流になる(下の変えた点)
変えた点: `--backfill` の合流は**取り直した方を先に置く**(`new + stored`)= 設計の式 `stored + new` だと日付の並べ替えが安定なので**同じ鍵は古い方が残る**(設計の「同じ鍵は新しい方」と合わない)。旗なしは `stored + new` のまま
⚠: 全場の --backfill が合流になる= 公式で取り消された日・間違えて入った日を消すときは `--replace` を明示する(取れた日だけになる= 取得が拒まれている時期に流すと 9/9 と同じく減る)
要判断: なし
