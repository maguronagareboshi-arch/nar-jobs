-- §240 / 0 番目 = 移行前の控え(⛔読みだけ。一番最初に 1 回だけ流して、結果を手元に貼っておく)
-- 設計= docs/proposal_s240_partition_20260922.md ・手順= docs/notes_s240_migration.md
-- なぜ要るか= 99_verify.sql は「移行前と行数が同じか」で合否を出す。控えが無いと検算できない。
-- ⛔便(nar-refresh / nar-ai-feat / nar-ai-last / run-facts-backfill / rakuten_backfill / pg_cron)を
--   止めた**あと**に流す。止める前に取ると、写している間に行が増えて数が合わなくなる。

-- 0-1 5 表の行数(全体 / archive 側 / 移す側)と日付の幅。⛔この 5 行を控える。
select 'nar_race_votes' as tbl, count(*) as rows_all,
       count(*) filter (where race_date <  '2022-11-01') as rows_archive,
       count(*) filter (where race_date >= '2022-11-01') as rows_move,
       min(race_date) as d_min, max(race_date) as d_max
  from public.nar_race_votes
union all
select 'nar_race_payouts', count(*),
       count(*) filter (where race_date <  '2022-11-01'),
       count(*) filter (where race_date >= '2022-11-01'),
       min(race_date), max(race_date)
  from public.nar_race_payouts
union all
select 'nar_races', count(*),
       count(*) filter (where race_date <  '2022-11-01'),
       count(*) filter (where race_date >= '2022-11-01'),
       min(race_date), max(race_date)
  from public.nar_races
union all
select 'nar_runs', count(*),
       count(*) filter (where race_date <  '2022-11-01'),
       count(*) filter (where race_date >= '2022-11-01'),
       min(race_date), max(race_date)
  from public.nar_runs
union all
select 'nar_run_facts', count(*),
       count(*) filter (where race_date <  '2022-11-01'),
       count(*) filter (where race_date >= '2022-11-01'),
       min(race_date), max(race_date)
  from public.nar_run_facts
 order by 1;
-- ⚠ count(*) は 5 表で全行を読む(nar_runs 129 万・nar_run_facts 145.7 万)。
--   Small(2GB)で 1 表 数秒〜十数秒の見込み。⛔画面が混む時間には流さない。

-- 0-2 年ごとの行数(②の insert / ③の delete が 1 回 25 万行を超えないかの確認)。
select 'nar_runs' as tbl, extract(year from race_date)::int as y, count(*)
  from public.nar_runs where race_date >= '2022-11-01' group by 1, 2
union all
select 'nar_run_facts', extract(year from race_date)::int, count(*)
  from public.nar_run_facts where race_date >= '2022-11-01' group by 1, 2
 order by 1, 2;
-- 期待= どの年も 25 万行未満。⛔超える年があったら、その表の §2/§3 をその年だけ半期に割る。

-- 0-3 表の大きさ(移行の前後で比べる。区切っただけでは小さくならないが、delete のあとの
--   archive 区画は膨らむ= vacuum で戻るはず)。
select c.relname, pg_size_pretty(pg_total_relation_size(c.oid)) as total,
       pg_size_pretty(pg_relation_size(c.oid)) as heap
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public'
   and c.relname in ('nar_race_votes', 'nar_race_payouts', 'nar_races', 'nar_runs', 'nar_run_facts')
 order by pg_total_relation_size(c.oid) desc;

-- 0-4 空き容量の見込み(⛔止めどころ)。§2 は消す前に写すので、一時的に「移す側の大きさ」だけ増える。
--   nar_runs 685MB のうち 2022-11 以降が 約半分= +350MB。nar_run_facts も同じくらい。
--   ⛔ディスクの空きが 2 表ぶん(約 1GB)無ければ、nar_runs を終わらせて vacuum してから
--   nar_run_facts に入る(同時に進めない)。
select pg_size_pretty(sum(pg_total_relation_size(c.oid))) as public_total
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind in ('r', 'p', 'm');
