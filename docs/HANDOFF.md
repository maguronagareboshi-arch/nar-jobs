commit: なし(下調べだけ・⛔実装なし・⛔push なし)。master(854098c)の作業木に新規 docs/run_failures_20260915.md と、この HANDOFF.md の上書きを置いた(未 commit)
検品: `gh run list` で JST 9/9 以降の success でない run= 47 本(auction-archive 11・horse-health 8・nar-refresh 18・nar-ai-last 5・nar-watchdog 4・nar-ai-feat 1= 依頼の本数と一致)を全部 `gh run view --json jobs` と `--log` で読み、1 run 1 行の表にした。分類= ① 3・② 4・③ 37・④ 1・実行中/待ち 2(nar-ai-last 09-15 12:27 実行中・15:08 待ち)
通信: gh の読み取りだけ(一覧 1 本+run ごとに 2 本)。ログは scratchpad に落として読んだ(URL・社名・鍵は表に写していない)
回帰: コード・yml・DB は触っていない
変えた点: ③の中身= **auction-archive 10 本は今も続く**(解析の版が上がって attention=871・理由 parser_changed_use_reparse → bad に数えて exit 1)/horse-health 8 本は同じ形で 9/12 11:07 以降止んだ/nar-refresh 12 本= 高知の自己修復 8(撤去済み)・門別の級別表のリンク無し 2(9/13 以降通過)・daily の HTTP 404 を rc=2 にする 2/AI 便 3 本= 本番の列追加で COPY の列ずれ(fd36163 で修正済み)/watchdog 4 本= 9/11 の当日オッズのティック 0 が 2・**高知の前半3F が 9/12・9/13 に 0 頭が 2(今も続く)**
⚠: 見立てが推測を含むもの= ①の 3 本は job 0 本・ログ 0 行で「待ちの run が次の run に置き換わった」は run の形(待ち時間と group)からの判断。watchdog の高知の前半3F は「計測は当日動いている(ran が新しい)のに nar_own_runs が 0」= 書き先の確認が要る(未確認)。9/11 のオッズのティック 0 は公開リポ側の run を見ていない
要判断: auction-archive の取り直し(手押しで --source auction --reparse を 1 回)をするか、parser_changed_use_reparse を exit の数から外すか(どちらも本番の DB に書く= Fable)。高知の前半3F 0 頭(9/12・9/13)は手元 PC の確認が要る
