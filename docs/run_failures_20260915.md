# nar-jobs の success でなかった run(2026-09-09〜09-15 JST)— 下調べ

- 読んだもの: `gh run list --created >=2026-09-08`(JST 9/9 以降に絞った)で success でなかった **47 本**。各 run を `gh run view <id> --json jobs`(落ちた手順)と `gh run view <id> --log`(`##[error]` の直前の行)で読んだ。調べた時刻 2026-09-15 15 時台。
- 分類: ①同時実行で取り消し ②通信の一時的な失敗(HTTP 5xx・timeout・接続断) ③本物の落ち(例外・データの不整合・判定が赤) ④timeout-minutes 超え。
- 集計: ① 3 本・② 4 本・③ 37 本・④ 1 本・実行中/待ち 2 本(判定しない)。

## auction-archive(11 本)

| 日時 JST | 結論 | 落ちた手順 | 分類 | 根拠 |
|---|---|---|---|---|
| 09-11 06:23 | failure | extract auction health disclosures | ③ | 集計行 review=15・review_waiting=370(error=0)→ review を bad に数えて exit 1 |
| 09-13 06:23 | failure | extract auction health disclosures | ③ | attention=871・skipped=871(各 source の理由は parser_changed_use_reparse)→ exit 1 |
| 09-13 08:05 | failure | extract auction health disclosures | ③ | 同上 attention=871 |
| 09-13 09:13 | failure | extract auction health disclosures | ③ | attention=871・review=1(unknown_auction_expression 1 件) |
| 09-13 13:45 | failure | extract auction health disclosures | ③ | attention=871・review_waiting=1 |
| 09-14 06:23 | failure | extract auction health disclosures | ② | get_import の GET で `URLError: [Errno 104] Connection reset by peer`(3 分で落ちた) |
| 09-14 08:14 | failure | extract auction health disclosures | ③ | attention=871・review=4 |
| 09-14 09:33 | failure | extract auction health disclosures | ③ | attention=871・review_waiting=5 |
| 09-14 14:17 | failure | extract auction health disclosures | ③ | attention=871・review_waiting=5 |
| 09-15 06:23 | failure | extract auction health disclosures | ③ | attention=871・review_waiting=5 |
| 09-15 08:54 | failure | extract auction health disclosures | ③ | attention=871・review_waiting=5 |

## horse-health(8 本)

| 日時 JST | 結論 | 落ちた手順 | 分類 | 根拠 |
|---|---|---|---|---|
| 09-09 10:43 | failure | import health events | ③ | nar: attention=20(各 PDF の理由 parser_changed_use_reparse)・error=0 → exit 1 |
| 09-09 15:39 | failure | import health events | ③ | nar: attention=20 |
| 09-10 10:43 | failure | import health events | ③ | nar: attention=16 |
| 09-10 15:37 | failure | import health events | ③ | nar: attention=16 |
| 09-11 10:43 | failure | import health events | ③ | nar: attention=11 |
| 09-11 15:37 | failure | import health events | ③ | nar: attention=11・review_waiting=1 |
| 09-12 10:43 | failure | import health events | ③ | nar: attention=8・review_waiting=1 |
| 09-12 11:02 | failure | import health events | ③ | nar: attention=1(09-12 11:07 以降の 7 本は success) |

※ 同じ便の後段「organizer ooi (daily)」で主催者ページが HTTP 403・errors=16 が毎回出ているが、手順は続行で run の失敗には効いていない。

## nar-refresh(18 本)

| 日時 JST | 結論 | 落ちた手順 | 分類 | 根拠 |
|---|---|---|---|---|
| 09-09 11:45 | cancelled | (job 開始前) | ① | job 0 本・ログ 0 行・20 分待って取り消し(group nar-refresh の待ちが次の run に置き換わった) |
| 09-09 13:25 | failure | kochi results (self-heal) | ② | 旧 DB への GET が `HTTPError: HTTP Error 500` |
| 09-09 15:45 | cancelled | (job 開始前) | ① | job 0 本・ログ 0 行・20 分待って取り消し |
| 09-10 05:33 | cancelled | venue stats (monthly only) | ④ | 60 分(timeout-minutes 60)で `The operation was canceled`= person_stats.sql の途中 |
| 09-10 21:05 | failure | refresh | ③ | `取得失敗 daily {'race_date': '2026-09-10'}: HTTPError: 404` → 投入なし・rc=2 |
| 09-11 05:33 | failure | monbetsu class (monthly only) | ③ | 「一覧ページに級別表PDFのリンクが1本も無い」で exit 1 |
| 09-11 07:42 | failure | monbetsu class (monthly only) | ③ | 同上(09-13・09-14 の 05:33 便は success) |
| 09-11 17:45 | failure | refresh | ③ | `取得失敗 daily {'race_date': '2026-09-11'}: HTTPError: 404` → rc=2 |
| 09-12 05:33 | failure | kochi results (self-heal) | ③ | 対象日に当日 2026/09/12 を入れ 1〜12R「結果表なし」→ `read-back 着順あり 0/126行` で exit 1 |
| 09-12 07:43 | failure | kochi results (self-heal) | ③ | 同上 read-back 0/126 |
| 09-12 09:05 | failure | kochi results (self-heal) | ③ | 同上 read-back 0/126 |
| 09-12 09:25 | failure | kochi results (self-heal) | ③ | 同上 read-back 0/126 |
| 09-12 09:45 | failure | kochi results (self-heal) | ③ | 同上 read-back 0/126 |
| 09-12 10:05 | failure | kochi results (self-heal) | ③ | 同上 read-back 0/126 |
| 09-12 10:25 | failure | kochi results (self-heal) | ③ | 同上 read-back 0/126 |
| 09-12 10:45 | failure | kochi results (self-heal) | ③ | 同上 read-back 0/126(10:49 の修正より前の最後の run) |
| 09-15 05:33 | failure | tenkai (morning + 17:07) | ② | tenkai.py rows_all の nar_runs 取得が `HTTP Error 500` |
| 09-15 09:05 | failure | noken debuts (daily + monthly) | ② | noken_debuts.py の nar_runs 取得が `HTTP Error 500` |

## nar-ai-last(5 本)

| 日時 JST | 結論 | 落ちた手順 | 分類 | 根拠 |
|---|---|---|---|---|
| 09-12 12:10 | failure | load into local postgres | ③ | `ERROR: extra data after last expected column`・`COPY nar_penalties, line 1`(本番の表に列が増えた) |
| 09-12 15:08 | failure | load into local postgres | ③ | 同上 COPY nar_penalties |
| 09-13 15:08 | cancelled | (job 開始前) | ① | job 0 本・313 分待って取り消し(12:13 の便が予測ループ中= 次の schedule に置き換わった) |
| 09-15 12:27 | in_progress | predict last every 15 minutes | — | 実行中(15 分ごとのループの途中・判定しない) |
| 09-15 15:08 | pending | (待ち) | — | 12:27 の便の後ろで待ち(判定しない) |

## nar-watchdog(4 本)

| 日時 JST | 結論 | 落ちた手順 | 分類 | 根拠 |
|---|---|---|---|---|
| 09-11 13:50 | failure | odds-live / check 2-minute odds ticks | ③ | `races today=35 near=2`・`latest tick today: None`(当日のティックが 1 本も無い) |
| 09-11 18:50 | failure | odds-live / check 2-minute odds ticks | ③ | `races today=35 near=3`・`latest tick today: None` |
| 09-14 10:37 | failure | kochi-results / check kochi first3f | ③ | `MISSING 2026-09-12: 出走 126頭なのに各馬の前半3F が 1 頭も無い`・kochi_auto_status.ran は当日 |
| 09-15 10:53 | failure | kochi-results / check kochi first3f | ③ | `MISSING 2026-09-13`(130 頭)と `2026-09-12`(126 頭)・ran は前日 |

## nar-ai-feat(1 本)

| 日時 JST | 結論 | 落ちた手順 | 分類 | 根拠 |
|---|---|---|---|---|
| 09-09 19:06 | failure | load into local postgres | ③ | `ERROR: extra data after last expected column`・`COPY nar_races, line 1`(2 分後 19:08 の手押しは success) |

## ③本物の落ち= 便ごとのまとめと直すなら(実装はしない)

| 便 | 本数 | いまも続くか | 直すなら何を変えるか(1 行) |
|---|---|---|---|
| auction-archive | 10 | **続く**(09-13 以降の抽出のある便は全部) | 解析の版が上がって 871 件が「取り直し待ち」のまま attention に数えられる= 手押しで `horse_health.py --source auction --reparse` を 1 回流して取り直す(再発よけに parser_changed_use_reparse は exit の数から外し、要約にだけ出す) |
| horse-health | 8 | 止んだ(09-12 11:07 の parser v1.1.1 以降 success) | 変えなくてよい(再発よけは auction と同じ= parser_changed_use_reparse を exit の数から外す) |
| nar-refresh(daily の 404) | 2 | 夜の手押しで出る | refresh.py は daily の HTTP 404 を「取得失敗 rc=2」にする= 404 は「ZIP でない応答」と同じ「開催なし・投入なし(rc 0)」に寄せる |
| nar-refresh(門別の級別表) | 2 | 止んだ(09-13・09-14 の月次便は success) | 一覧に PDF のリンクが無い日は警告だけで続行(exit 0・前回の表を残す)にする |
| nar-refresh(高知の自己修復) | 8 | 止んだ(0cd5d63 で当日を対象外に・97c0101 で段ごと撤去) | 変えなくてよい |
| nar-ai-last / nar-ai-feat(COPY の列ずれ) | 3 | 止んだ(fd36163 で nar_penalties の写し先に列を足した) | 再発よけ= 本番からの dump を列名を指定した `\copy (select 列…)` にし、本番の列追加で落ちないようにする |
| nar-watchdog(2 分オッズ) | 2 | 09-11 だけ | 見張りは正しく鳴った= 公開リポの 2 分便の 09-11 13〜19 時の run と、その日の nar_odds_ticks の件数を確かめる |
| nar-watchdog(高知の前半3F) | 2 | **続く** | 見張りの表を nar_own_runs に替えた 09-12 以降の日だけ 0 頭・計測は当日動いている= 手元 PC の翌朝計測が nar_own_runs に書いているか(書き先が旧 DB のままでないか)を確かめる |
