-- §240 表を年で区切る(宣言的パーティション)/ 3 表目 = nar_races
--   レース(1 レース 1 行)
-- 設計= docs/proposal_s240_partition_20260922.md ・規則= docs/opus_rules.md
-- 書いたのは Opus 実装(2026-09-22)。⛔本番 DB には一切触っていない。
--   下の DDL は手元のコードから**読み取った写し**= 本番の実物と違う可能性がある。
--   ⛔必ず §0 を先に流して答え合わせをしてから §1 へ進む。
-- 出どころ= pipeline/sql/ai_feat_local_schema.sql の 2)(⛔本番の pg_attribute を attnum の順で写したもの・2026-09-08 実測) + nankan_hist_20260917.sql の `add column nankan jsonb`
-- 行の見込み= 1 年 約 1.5 万行(全体 約 15 万行)
-- なぜこの順番か= 小さい表の 3 つ目。ここまで通ったら大きい 2 表へ進む。
-- 流す人= 鍵を持つ担当(検品役)。⛔1 ステップ 1 トランザクション。
--   ⛔始める前に便を止める(nar-refresh / nar-ai-feat / nar-ai-last / run-facts-backfill /
--   rakuten_backfill / pg_cron)。§2 で写した行に §3 の delete が後から当たるため、
--   1 表ぶんの §1〜§4 が終わるまで書き手を入れない。
-- ⚠ この表だけの注意:
--   ⛔`nankan` は 2026-09-17 に後から足した列= 並びは一番後ろのはず。§0-1 で位置を確かめる。
--   ⛔`source` は not null・check は race_no(1..12)だけ(§238b で本番を見た結果・2026-09-21)。
--
-- 今の形と思っているもの(⛔§0-1 が正):
--   create table public.nar_races (
--     track                text         not null,
--     race_date            date         not null,
--     race_no              integer      not null,
--     post_time            text         ,
--     race_name            text         ,
--     surface              text         ,
--     direction            text         ,
--     distance_m           integer      ,
--     weather              text         ,
--     going                text         ,
--     field_size           integer      ,
--     condition            text         ,
--     prize_yen            jsonb        ,
--     race_last4f          numeric      ,
--     race_last3f          numeric      ,
--     furlongs             jsonb        ,
--     corners              jsonb        ,
--     source               text         not null,
--     source_snapshot_hash text         ,
--     updated_at           timestamptz  not null,
--     race_kind            text         ,
--     cancelled            text         ,
--     cancel_note          text         ,
--     nankan               jsonb        ,
--     primary key (track, race_date, race_no));
--   constraint nar_races_race_no_ck check (race_no between 1 and 12)
--   → PK に race_date が入っている= 区画キーにできる(設計の前提 (a) を満たす)


-- =====================================================================
-- §0 当てる前に本番で確かめる(⛔読みだけ。ここで違いが出たら §1 の DDL を直す)
-- =====================================================================
-- 0-1 列と型と並び。期待= 24 列・上の写しと同じ順。
select ordinal_position, column_name, data_type, is_nullable, column_default
  from information_schema.columns
 where table_schema = 'public' and table_name = 'nar_races'
 order by ordinal_position;

-- 0-2 索引。期待= nar_races_pkey だけの見込み(§0-2 で確かめる)。
select indexname, indexdef
  from pg_indexes where schemaname = 'public' and tablename = 'nar_races' order by indexname;

-- 0-3 制約。期待= PK と check(race_no_ck)。⛔知らない制約が出たら §1 に写す。
select conname, contype, pg_get_constraintdef(oid) as def
  from pg_constraint where conrelid = 'public.nar_races'::regclass order by conname;

-- 0-4 RLS と policy。期待= relrowsecurity = true・policy は読みだけ 1 本の見込み。
select relkind, relrowsecurity, relforcerowsecurity, reltuples::bigint as est_rows
  from pg_class where oid = 'public.nar_races'::regclass;
select policyname, permissive, roles, cmd, qual, with_check
  from pg_policies where schemaname = 'public' and tablename = 'nar_races' order by policyname;

-- 0-5 grant。期待= anon / authenticated に SELECT・service_role に読み書き。
select grantee, privilege_type from information_schema.role_table_grants
 where table_schema = 'public' and table_name = 'nar_races' order by grantee, privilege_type;

-- 0-6 trigger。期待= 0 行。⛔1 行でも出たら §1 に写して親へ付け直してから進む。
select tgname, pg_get_triggerdef(oid) from pg_trigger
 where tgrelid = 'public.nar_races'::regclass and not tgisinternal;

-- 0-7 この表を指している外部キー。期待= 0 行。
--   ⛔1 行でも出たら止めて報告(参照される側を差し替えるので手順が増える)。
select c.relname as referencing_table, k.conname, pg_get_constraintdef(k.oid) as def
  from pg_constraint k join pg_class c on c.oid = k.conrelid
 where k.contype = 'f' and k.confrelid = 'public.nar_races'::regclass;

-- 0-8 この表から出ている外部キー。期待= 0 行(⛔パーティションの子は FK を持てるが、
--   attach のときに親へ写す手間が増えるので数を見ておく)。
select conname, pg_get_constraintdef(oid) from pg_constraint
 where conrelid = 'public.nar_races'::regclass and contype = 'f';

-- 0-9 この表に依存する view / matview。期待= 0 行。
--   ⛔rename は view の向き先を**旧表に残す**。1 行でも出たら §4 の前に view を作り直す手順を足す。
--   (手元で洗った結果= nar_sales_daily は nar_sales の view で無関係。nar_search_runs /
--    nar_search_runs_v2 は plpgsql の中で表名を書いているだけ= 実行時に名前で引くので影響なし。)
select distinct dependent.relname, dependent.relkind
  from pg_depend d
  join pg_rewrite r on r.oid = d.objid
  join pg_class dependent on dependent.oid = r.ev_class
 where d.refobjid = 'public.nar_races'::regclass and d.classid = 'pg_rewrite'::regclass
   and dependent.relname <> 'nar_races';

-- 0-10 移行前の行数の控え(⛔00_baseline_counts.sql でまとめて取ってもよい。99_verify.sql で使う)。
select count(*) as rows_all,
       count(*) filter (where race_date <  '2022-11-01') as rows_archive,
       count(*) filter (where race_date >= '2022-11-01') as rows_move,
       min(race_date) as d_min, max(race_date) as d_max
  from public.nar_races;


-- =====================================================================
-- §1 親表 nar_races_p と区画を作る(1 トランザクション)
--   ⛔索引・制約の**名前**は旧表とぶつからないよう `_p_` を挟む。理由= §4 の rename の後も
--   旧表の索引名(nar_races_pkey など)はそのまま残るため、同じ名前を先に使うと §1 が落ちる。
--   PK 制約の名前は create table が自動で `nar_races_p_pkey` にする= 衝突しない。
-- =====================================================================
begin;
set local lock_timeout = '10s';

create table public.nar_races_p (
  track                text         not null,
  race_date            date         not null,
  race_no              integer      not null,
  post_time            text         ,
  race_name            text         ,
  surface              text         ,
  direction            text         ,
  distance_m           integer      ,
  weather              text         ,
  going                text         ,
  field_size           integer      ,
  condition            text         ,
  prize_yen            jsonb        ,
  race_last4f          numeric      ,
  race_last3f          numeric      ,
  furlongs             jsonb        ,
  corners              jsonb        ,
  source               text         not null,
  source_snapshot_hash text         ,
  updated_at           timestamptz  not null,
  race_kind            text         ,
  cancelled            text         ,
  cancel_note          text         ,
  nankan               jsonb        ,
  constraint nar_races_p_race_no_ck check (race_no between 1 and 12),
  primary key (track, race_date, race_no)
) partition by range (race_date);

-- 〜2022-11-01 の区画は**作らない**= §3 で旧表をそのまま attach するために空けておく。
create table public.nar_races_2022_11_2023 partition of public.nar_races_p
  for values from ('2022-11-01') to ('2024-01-01');
create table public.nar_races_2024 partition of public.nar_races_p
  for values from ('2024-01-01') to ('2025-01-01');
create table public.nar_races_2025 partition of public.nar_races_p
  for values from ('2025-01-01') to ('2026-01-01');
create table public.nar_races_2026 partition of public.nar_races_p
  for values from ('2026-01-01') to ('2027-01-01');
create table public.nar_races_2027 partition of public.nar_races_p
  for values from ('2027-01-01') to ('2028-01-01');


alter table public.nar_races_p enable row level security;
create policy nar_races_read on public.nar_races_p
  for select to anon, authenticated using (true);
grant select on public.nar_races_p to anon, authenticated;
-- ⛔書き手(便)は service_role で入る。Supabase の既定で service_role は RLS を素通りするが、
--   grant は要る= 旧表と同じものを付ける。§0-5 の結果と見比べて足りない行を足す。
grant select, insert, update, delete on public.nar_races_p to service_role;

comment on table public.nar_races_p is
  'NAR 公式のレース。§240 で race_date の年ごとに区切った親表';

commit;


-- =====================================================================
-- §2 2022-11-01 以降を親へ写す(⛔1 刻み 1 トランザクション・1 回 25 万行以下)
--   1 年 約 1.5 万行(全体 約 15 万行)
-- =====================================================================

-- 2-0 列の並びが親と旧表で同じことを機械で確かめる(⛔違えばここで止まる)。
--   `select *` は位置で入るので、並びが 1 つずれると値が別の列に入る。
do $$
declare v_old text; v_new text;
begin
  select string_agg(column_name || ' ' || data_type, ',' order by ordinal_position) into v_old
    from information_schema.columns where table_schema='public' and table_name='nar_races';
  select string_agg(column_name || ' ' || data_type, ',' order by ordinal_position) into v_new
    from information_schema.columns where table_schema='public' and table_name='nar_races_p';
  if v_old is distinct from v_new then
    raise exception '列が違う。旧= % / 親= %', v_old, v_new;
  end if;
end $$;

-- 2-1 2022-11 〜 2023-12
begin;
set local statement_timeout = '30min';
insert into public.nar_races_p
select * from public.nar_races
 where race_date >= '2022-11-01' and race_date < '2024-01-01';
commit;

-- 2-2 2024
begin;
set local statement_timeout = '30min';
insert into public.nar_races_p
select * from public.nar_races
 where race_date >= '2024-01-01' and race_date < '2025-01-01';
commit;

-- 2-3 2025
begin;
set local statement_timeout = '30min';
insert into public.nar_races_p
select * from public.nar_races
 where race_date >= '2025-01-01' and race_date < '2026-01-01';
commit;

-- 2-4 2026(今年)
begin;
set local statement_timeout = '30min';
insert into public.nar_races_p
select * from public.nar_races
 where race_date >= '2026-01-01' and race_date < '2027-01-01';
commit;

-- 2-5 2027 以降
begin;
set local statement_timeout = '30min';
insert into public.nar_races_p
select * from public.nar_races
 where race_date >= '2027-01-01';
commit;

-- 2-6 突き合わせ(⛔合わなければ §3 へ進まない)
select (select count(*) from public.nar_races where race_date >= '2022-11-01') as old_move,
       (select count(*) from public.nar_races_p) as new_rows;


-- =====================================================================
-- §3 旧表から 2022-11-01 以降を消し、check を付けて archive 区画として attach
-- =====================================================================

-- 3-1 delete(刻みごと・1 刻み 1 トランザクション)
--   2022-11 〜 2023-12
begin;
set local statement_timeout = '30min';
delete from public.nar_races where race_date >= '2022-11-01' and race_date < '2024-01-01';
commit;

--   2024
begin;
set local statement_timeout = '30min';
delete from public.nar_races where race_date >= '2024-01-01' and race_date < '2025-01-01';
commit;

--   2025
begin;
set local statement_timeout = '30min';
delete from public.nar_races where race_date >= '2025-01-01' and race_date < '2026-01-01';
commit;

--   2026(今年)
begin;
set local statement_timeout = '30min';
delete from public.nar_races where race_date >= '2026-01-01' and race_date < '2027-01-01';
commit;

--   2027 以降
begin;
set local statement_timeout = '30min';
delete from public.nar_races where race_date >= '2027-01-01';
commit;

-- 3-2 delete で空いた場所を返す(⛔vacuum はトランザクションの中では流せない。
--   ⛔vacuum full は使わない= 表と同じ大きさの場所を新しく要求し、排他ロックで画面が止まる)
vacuum (analyze) public.nar_races;

-- 3-3 archive の check を not valid で付ける(短い排他・既存行は見ない= 数ミリ秒)
begin;
set local lock_timeout = '10s';
alter table public.nar_races
  add constraint nar_races_archive_ck check (race_date < '2022-11-01') not valid;
commit;

-- 3-4 validate(⛔読みだけの走査。SHARE UPDATE EXCLUSIVE なので select は止まらない)
begin;
set local statement_timeout = '30min';
alter table public.nar_races validate constraint nar_races_archive_ck;
commit;

-- 3-5 attach(check があるので全行走査は起きない。⛔親に一瞬 ACCESS EXCLUSIVE がかかる)
--   ⛔attach のとき、親の索引ごとに「同じ定義の索引」を旧表から探して繋ぐ。無ければ**その場で作る**
--   (= 旧表の行数ぶん待つ)。§1 で定義を揃えてあるので、繋ぐだけで終わるはず。
begin;
set local lock_timeout = '10s';
set local statement_timeout = '30min';
alter table public.nar_races_p
  attach partition public.nar_races for values from (minvalue) to ('2022-11-01');
commit;

-- 3-6 確認= 区画が 6 つ・親の索引がすべて indisvalid
select relid::regclass as part, level from pg_partition_tree('public.nar_races_p');
select i.indexrelid::regclass as idx, i.indisvalid
  from pg_index i where i.indrelid = 'public.nar_races_p'::regclass;


-- =====================================================================
-- §4 名前の入れ替え(⛔ここだけ短い排他。区画の名前はそのまま)
--   旧表 nar_races → nar_races_archive_part(親の下の archive 区画のまま)
--   親   nar_races_p → nar_races(画面・便・PostgREST の URL は変わらない)
--   ⛔lock_timeout を短くして、長い select の後ろに並んで全部を待たせないようにする。
--   落ちたら数分後にもう一度流すだけでよい(この 2 行は同じトランザクションの中で不可分)。
-- =====================================================================
begin;
set local lock_timeout = '5s';
alter table public.nar_races   rename to nar_races_archive_part;
alter table public.nar_races_p rename to nar_races;
commit;

-- PostgREST にスキーマを読み直させる(⛔commit の後・トランザクションの外)
notify pgrst, 'reload schema';


-- =====================================================================
-- §5 区画ごとの grant / RLS と vacuum analyze
--   ⛔親越しの select では権限は親だけを見る= この grant は「区画を直接引くとき」の保険。
--   ⛔RLS は**区画のポリシーも効く**。区画に RLS を有効にしてポリシーを置かないと、親越しの
--   select が 0 行になり得る。だから有効化とポリシーは必ず一組で流す。
--   (archive 区画= 旧表は元から RLS 有効+読みポリシー付きなので、そのままでよい)
-- =====================================================================
begin;
alter table public.nar_races_2022_11_2023 enable row level security;
create policy nar_races_part_read on public.nar_races_2022_11_2023
  for select to anon, authenticated using (true);
grant select on public.nar_races_2022_11_2023 to anon, authenticated;
grant select, insert, update, delete on public.nar_races_2022_11_2023 to service_role;

alter table public.nar_races_2024 enable row level security;
create policy nar_races_part_read on public.nar_races_2024
  for select to anon, authenticated using (true);
grant select on public.nar_races_2024 to anon, authenticated;
grant select, insert, update, delete on public.nar_races_2024 to service_role;

alter table public.nar_races_2025 enable row level security;
create policy nar_races_part_read on public.nar_races_2025
  for select to anon, authenticated using (true);
grant select on public.nar_races_2025 to anon, authenticated;
grant select, insert, update, delete on public.nar_races_2025 to service_role;

alter table public.nar_races_2026 enable row level security;
create policy nar_races_part_read on public.nar_races_2026
  for select to anon, authenticated using (true);
grant select on public.nar_races_2026 to anon, authenticated;
grant select, insert, update, delete on public.nar_races_2026 to service_role;

alter table public.nar_races_2027 enable row level security;
create policy nar_races_part_read on public.nar_races_2027
  for select to anon, authenticated using (true);
grant select on public.nar_races_2027 to anon, authenticated;
grant select, insert, update, delete on public.nar_races_2027 to service_role;

commit;

-- ⛔vacuum はトランザクションの外・区画ごとに 1 本ずつ
vacuum (analyze) public.nar_races_2022_11_2023;
vacuum (analyze) public.nar_races_2024;
vacuum (analyze) public.nar_races_2025;
vacuum (analyze) public.nar_races_2026;
vacuum (analyze) public.nar_races_2027;
vacuum (analyze) public.nar_races_archive_part;
analyze public.nar_races;

-- 最後に PostgREST をもう一度(区画を足したときは不要だが、害はない)
notify pgrst, 'reload schema';
