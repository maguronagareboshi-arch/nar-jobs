# 指示書: 監査 #28 nar_odds_full_ticks の 60 日超をファイルへ書き出し→確かめ→DB から消す(2026-09-23 Opus 5.5)

作業木= C:\Users\kouki\AppData\Local\Temp\nar-jobs-hold(枝 audit-hold-jobs)。⛔枝を切り替えない・push しない・本番 DB に書かない/消さない(手元の検証は読むだけか --dry-run)。

## 今
- 表 nar_odds_full_ticks(普通の表・213MB・16 日分・1 日約 14MB)。列 id bigint(一意)・track・race_date・race_no・kind・observed_at・f・h・combos jsonb。race_date に索引あり。
- 月 1 回 nar-refresh.yml(monthly)が pipeline/sql/odds_full_ticks_retention.sql で 60 日超を 6 点だけ残して間引いている(書き出し無し)。
- 読む人: 画面は nar_odds_full(最新の板)だけ・ticks は読まない。nankan-ai の paper/record_week.py(直近 1 週)と nankan-copy.yml(写し)が読む。

## 作るもの(ユーザー決定 案C)
1. cloud/odds_archive.py: JST の今日から 60 日より前の race_date を古い順に 1 日ずつ(1 回の実行で最大 --max-days 日・既定 3)。
   - その日の全行を PostgREST で読む(order=id・limit 1000 のページ送り= 一意の順で)。gzip の JSONL(1 行 1 刻み・列はそのまま)に書く。行数・最小/最大 id・sha256 を控える。
   - 置き場= Supabase Storage の非公開バケット odds-archive(無ければ service key で作る・public=false)。パス= nar_odds_full_ticks/YYYY/YYYY-MM-DD.jsonl.gz。既にあれば上書きせず、中身が同じか(sha256)だけ見る。
   - 確かめ= 上げたファイルを取り直して解凍し、行数・id の集合・sha256 が DB から読んだものと一致したときだけ、その日の行を id の範囲で小分け(1 回 5,000 行以下)に DELETE。一致しなければ消さずに rc 1。
   - 控え= nar_meta の key 'odds_archive:v1' に {日付: {rows, bytes, sha256, path, deleted, at}} を足す(既存の nar_meta の書き方に合わせる)。
   - --dry-run(読んで書き出して上げて確かめるが消さない)・--date YYYY-MM-DD(1 日だけ)・--max-days。
   - 失敗は必ず rc≠0(監査 #19 と同じ= 全滅を成功扱いしない)。
2. nar-refresh.yml: daily の便(朝)に odds_archive.py --max-days 3 を足す(手順名に「: 」を入れない)。monthly の odds_full_ticks_retention.sql の呼び出しを外す(書き出し前に間引くと消える= 事故になる)。SQL ファイル自体は残し、先頭に「9/23 から odds_archive.py に置き換え」と書く。
3. 戻し方(docs に 5 行): ファイル → 一時表 → insert の手順。

## 確かめ
- tests/ に純粋関数(対象日の選び方・JST 境目・確かめの一致判定・小分け)の検査を足し、既存の tests と一緒に緑。
- 本番に対して `--dry-run --date 2026-09-10`(存在する古めの日)を 1 回だけ流してよい= 読む+Storage に 1 ファイル上げる+取り直し確認。消さない。行数・bytes・sha256 一致を報告。これ以外に本番へ書かない。
- 所要時間(1 日分)を測る。

## 決まり
- 読むファイル: .github/workflows/nar-refresh.yml(daily/monthly の手順だけ)・pipeline/sql/odds_full_ticks_retention.sql・pipeline/load_nar_official.py の load_env/upsert・cloud/ の nar_meta を書く既存例 1 つ(grep で探す)。鍵は .env から読み、画面やログに出さない。
- 試行錯誤しない。迷ったら止まって「要判断」で返す。
- commit(枝 audit-hold-jobs・「監査 #28: …」・末尾に Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>)。

## 報告(7 行以内・数字と所在だけ)
commit / 変えたファイル / テスト件数 / dry-run の行数・bytes・一致 / 1 日の所要 / Storage のパス / 要判断
