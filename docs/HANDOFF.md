commit: 枝 s179c-paper-gear(master bbb47b4 から・⛔push/merge なし・⛔便は回していない)= cloud/paper_pdf.py(新規 gear_marks= ⑨相手の馬の行の末尾の B/P/S → 'B'/'P'/'S' を B→P→S の順に '+'・parse_block が最下段(枠の高さ 90% 以下)の字から row["gear"]・rows_to_write は馬具の字がある走だけ gear を足す)・cloud/paper_first3f.py(upsert は gear のある行/無い行を別の本で送る・ログに「馬具 N 走」)・tests/paper_match_test.py に 3 項(Gear)
検品: `py -3.12 -X utf8 -m unittest tests.paper_match_test` 11/11 OK= 'マリリンダンサーB S'→'B+S'/'マリリンダンサー'→None/'マリリンダンサーＢ'→'B'/'マリリンダンサーBX'→None/' S P'→'P+S'・馬具の無い走の行に gear の鍵が無い・upsert の 1 本の中の行は鍵がそろう(2 本= gear あり 2 行/なし 1 行)。git diff --check 通過・禁止語 0
通信: DB への書き込みの本数が最大 2 倍(gear あり/なしで分ける= 1 日 12R でも 2 本)。一覧・PDF・公式の表を引く本数は変わらない
回帰: 前半3F の読み取り(⑧の帯)・馬の特定・ログの他の字・yml は触っていない。既存の Identify 6 項・ListPdfs 2 項は緑のまま
変えた点: ⛔gear が None の走は行に gear を持たせない= 既存の行を null で潰さない(PostgREST の一括は 1 本目の鍵で列を決めるので、鍵のそろった本に分けた)。⑨の帯の字に信頼度 0.8 未満が 1 つでもあれば gear は読まない(low_score に "gear")。行を作る条件(前半の値がある走だけ)は変えていない= 前半が空欄の走の馬具は入らない
⚠: 本物の紙面で⑨の帯(枠の高さの 90〜100%)に相手の馬の行が収まるか・OCR が B/P/S を名前の後ろに返すかは確かめていない= SQL(gear 列)の後の `--force dates=2026-09-15` のログ「馬具 N 走」で見る(列が無いまま便が gear を送ると書き込みが 400 で落ちる= SQL を先に)
要判断: なし(push は Fable)
