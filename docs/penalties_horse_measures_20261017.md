# 制裁の表に馬への措置を入れる(penalties-1.3・2026-10-17)

- 器: `pipeline/sql/penalties_horse_measures_20261017.sql`(nar-viewer にも同じ中身)。horse-health.yml の段 `migrate penalties schema` が流す(⛔dry_run の便では流さない)。
- 読み手: `cloud/penalties.py` PARSER_VERSION = `penalties-1.3`。
  - 馬の行= person_kind `horse`・person_name = horse_name = 名簿の馬名・kind `出走停止` / `再検査`・理由は `cause`。
  - 賞典停止= kind はそのまま・`prize_suspended = true`。飛び日付= `suspension_days`(from/through は最初と最後)。
  - 「。」の後ろの期間だけの文(高知・園田)は前の文へ戻す。字が 2 重の頁の頭(「競競走走成成績績表表…作成」)は頁の飾りとして落とす。
- 試験: `tests/test_penalties.py`・`tests/test_penalties_horse_measures.py`(本物の PDF 文 = `tests/fixtures/penalties_pdf_20261017.json`)。

## 埋め直しで旧版の行を消す(⛔書くだけ・実行は本体が手動モードで)

detail(期間の戻し)と kind が変わると penalty_id が変わるので、新版で読み直しただけでは旧版の行が 2 重に残る。
**新版の行を入れ終えた後**に、新版で読み直した (場, 日) の旧版の行だけを消す。
新版で読み直した印は `nar_penalty_sources.parser_version = 'penalties-1.3'`(行の upsert が通った後に書かれる)。
id が新旧で同じ行は upsert で parser_version が 1.3 に上書き済みなので消えない。
新版で 0 行になった (場, 日) の旧版の行も消える(sources の行はある)。

```sql
-- :start / :end は埋め直した開催日の範囲(例 2026-01-01 / 2026-10-17)
delete from public.nar_penalties p
 using public.nar_penalty_sources s
 where s.track = p.track and s.race_date = p.race_date
   and s.parser_version = 'penalties-1.3'
   and p.parser_version <> 'penalties-1.3'
   and p.race_date between :'start'::date and :'end'::date;
```

先に件数だけ見るときは `delete` を `select count(*) from public.nar_penalties p using …` ではなく
`select count(*) from public.nar_penalties p join public.nar_penalty_sources s on s.track = p.track and s.race_date = p.race_date where …`(条件は同じ)で。
