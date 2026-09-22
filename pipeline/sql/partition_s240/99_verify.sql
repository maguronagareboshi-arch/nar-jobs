-- §240 / 検算(⛔読みだけ。1 表ぶんの §4 が終わるたびに、その表の分を流す)
-- 設計の合格条件= 行数が移行前と一致・race_date 指定が 1 区画だけを読む・便と画面が動く。
-- 控え= 00_baseline_counts.sql の 0-1 の結果。

-- =====================================================================
-- 1) 区画の木(⛔1 表ぶんが終わった直後に見る)
-- =====================================================================
select 'nar_race_votes'   as parent, relid::regclass as part, level, isleaf
  from pg_partition_tree('public.nar_race_votes')
union all select 'nar_race_payouts', relid::regclass, level, isleaf from pg_partition_tree('public.nar_race_payouts')
union all select 'nar_races',        relid::regclass, level, isleaf from pg_partition_tree('public.nar_races')
union all select 'nar_runs',         relid::regclass, level, isleaf from pg_partition_tree('public.nar_runs')
union all select 'nar_run_facts',    relid::regclass, level, isleaf from pg_partition_tree('public.nar_run_facts')
 order by 1, 3, 2;
-- 期待= 1 表につき 7 行(親 1 + 区画 6)。区画= *_archive_part / *_2022_11_2023 / *_2024 / *_2025 / *_2026 / *_2027。
-- ⛔まだ移していない表は「その表は親ではない」で 1 行(level 0)だけ返る= それが正しい。

-- =====================================================================
-- 2) 行数(⛔移行前の控えと突き合わせる。1 行でも違ったら 98_rollback.sql)
-- =====================================================================
select 'nar_race_votes' as tbl, count(*) as rows_all,
       count(*) filter (where race_date <  '2022-11-01') as rows_archive,
       count(*) filter (where race_date >= '2022-11-01') as rows_move
  from public.nar_race_votes
union all select 'nar_race_payouts', count(*),
       count(*) filter (where race_date < '2022-11-01'), count(*) filter (where race_date >= '2022-11-01')
  from public.nar_race_payouts
union all select 'nar_races', count(*),
       count(*) filter (where race_date < '2022-11-01'), count(*) filter (where race_date >= '2022-11-01')
  from public.nar_races
union all select 'nar_runs', count(*),
       count(*) filter (where race_date < '2022-11-01'), count(*) filter (where race_date >= '2022-11-01')
  from public.nar_runs
union all select 'nar_run_facts', count(*),
       count(*) filter (where race_date < '2022-11-01'), count(*) filter (where race_date >= '2022-11-01')
  from public.nar_run_facts
 order by 1;

-- 2-b 区画ごとの行数(どこに入ったかを見る。⛔archive に 2022-11 以降が 1 行でもあれば check が嘘)
select tableoid::regclass as part, count(*) as rows, min(race_date) as d_min, max(race_date) as d_max
  from public.nar_runs group by 1 order by 3;
select tableoid::regclass as part, count(*) as rows, min(race_date) as d_min, max(race_date) as d_max
  from public.nar_run_facts group by 1 order by 3;
-- 期待= *_archive_part の d_max が 2022-10-31 以下・*_2026 の d_min が 2026-01-01 以上。

-- =====================================================================
-- 3) 区画の剪定(⛔合格条件の本体)= 日付で引くと 1 区画だけを読む
-- =====================================================================
-- 3-1 レース画面と同じ引き方(当日・場)。⛔期待= Seq/Index Scan が nar_runs_2026 の 1 つだけ。
--     「Subplans Removed」または「Partitions: 1」相当の形になっているかを目で見る。
explain (analyze, buffers, verbose off)
select * from public.nar_runs where race_date = '2026-09-22';

-- 3-2 同じものを nar_run_facts でも
explain (analyze, buffers)
select * from public.nar_run_facts where race_date = '2026-09-22';

-- 3-3 馬ページ(⛔日付が無い= 全区画を読む。これは**想定どおり**。§238a2 で派生表の鍵へ寄せる)
--     期待= 6 区画とも nar_runs_*_horse_idx の Index Scan(Seq Scan が出たら索引が繋がっていない)。
explain (analyze, buffers)
select * from public.nar_runs where horse_name = 'サンライズホープ'
 order by race_date desc, race_no desc limit 300;

-- 3-4 期間で切った馬名(画面が実際に使う形。⛔ここは区画が減るはず)
explain (analyze, buffers)
select * from public.nar_runs
 where horse_name = 'サンライズホープ' and race_date >= '2025-01-01'
 order by race_date desc limit 300;

-- =====================================================================
-- 4) 索引と制約が全部そろっているか
-- =====================================================================
-- 4-1 親の索引が indisvalid(⛔false があると使われない)
select i.indrelid::regclass as tbl, i.indexrelid::regclass as idx, i.indisvalid, i.indisunique
  from pg_index i
 where i.indrelid in ('public.nar_race_votes'::regclass, 'public.nar_race_payouts'::regclass,
                      'public.nar_races'::regclass, 'public.nar_runs'::regclass,
                      'public.nar_run_facts'::regclass)
 order by 1, 2;

-- 4-2 区画にも同じ本数の索引が付いているか(親 1 本 = 区画ごと 1 本)
select c.relname as part, count(*) as idx_n
  from pg_class c join pg_index i on i.indrelid = c.oid
 where c.oid in (select relid from pg_partition_tree('public.nar_runs') where isleaf)
 group by 1 order by 1;
-- 期待= どの区画も同じ本数。⛔archive 区画だけ多いのは元からある nar_runs_race_idx のぶん(想定どおり)。

-- 4-3 RLS と policy(⛔親と区画の両方に要る。抜けると親越しの select が 0 行になり得る)
select c.relname, c.relrowsecurity,
       (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relname like 'nar_run%' and c.relkind in ('r', 'p')
 order by 1;

-- =====================================================================
-- 5) 匿名キーで実際に読めるか(⛔ここが本番の画面と同じ道)
-- =====================================================================
set role anon;
select count(*) from public.nar_runs where race_date = '2026-09-22';
select count(*) from public.nar_runs where race_date = '2016-05-01';   -- archive 区画
select count(*) from public.nar_run_facts where race_date = '2026-09-22';
select count(*) from public.nar_races where race_date = '2026-09-22';
select count(*) from public.nar_race_payouts where race_date = '2026-09-22';
select count(*) from public.nar_race_votes where race_date = '2016-05-01';
reset role;
-- 期待= どれも 0 でない(archive 側も読める)。⛔0 なら 4-3 の policy/grant が抜けている。

-- =====================================================================
-- 6) upsert(PostgREST の on_conflict)が親で動くか
--    ⛔書き込みなので**ユーザーの「はい」が要る**。流すなら 1 行だけ・そのあと必ず消す。
-- =====================================================================
-- begin;
-- insert into public.nar_races (track, race_date, race_no, source, updated_at)
-- values ('__test__', '2026-12-31', 1, 's240_test', now())
-- on conflict (track, race_date, race_no) do update set updated_at = excluded.updated_at;
-- select track, race_date, race_no, tableoid::regclass from public.nar_races where track = '__test__';
-- -- 期待= nar_races_2026 に入る・2 回流しても 1 行のまま
-- delete from public.nar_races where track = '__test__';
-- commit;
