-- §240 表を年で区切る(宣言的パーティション)/ 3 表目 = nar_races
--   レース(1 レース 1 行)
-- 設計= docs/proposal_s240_partition_20260922.md ・規則= docs/opus_rules.md
-- 書いたのは Opus 実装(2026-09-22)。⛔Opus は本番 DB に一切触っていない。
--   下の DDL は **検品役が 2026-09-22 18:10 に本番を読んだ結果**に合わせてある(列・PK・check・
--   索引・RLS/policy・grant・comment・trigger・外部キー・依存 view)。
--   ⛔それでも §0 を先に流す= 読み取りから当てるまでの間に本番が変わっていないかの最後の確認。
-- 出どころ= 本番の実物(2026-09-22 18:10 に検品役が pg_indexes / pg_policies / information_schema.columns を読んだ結果)。24 列・nankan は一番後ろで一致
-- 行の見込み= 1 年 約 1.5 万行(全体 約 15 万行)
-- なぜこの順番か= 小さい表の 3 つ目。ここまで通ったら大きい 2 表へ進む。
-- 流す人= 鍵を持つ担当(検品役)。⛔1 ステップ 1 トランザクション。
-- ⛔流す順は §1 → §2 → **§4'** → **§3'** → §5(2026-09-22 に入れ替えた)。
--   前の版は「§3 delete → §4 rename」の順で、その間 15〜25 分ぶん、旧表を見ている画面から
--   **今年のデータが消える**窓があった。入れ替えた今は、先に名前を入れ替えて画面を親へ向ける=
--   今年の行は最初からそろっていて、一時的に見えないのは **2022-10 以前だけ**(数分〜十数分)。
--   ⛔始める前に便を止める(nar-refresh / nar-ai-feat / nar-ai-last / run-facts-backfill /
--   rakuten_backfill / pg_cron)。⛔止めていていい範囲は **§1 から §4' まで**。
--   §4' が終われば書き手は親へ入る= §3' は便を動かしたまま流してよい。
-- ⚠ この表だけの注意:
--   ⛔この表だけ policy が 2 本(印の書き手 marks_writer にも読みが要る)= 親と区画の両方に 2 本置く。
--   ⛔この表だけ **view `nar_sales_hourly` が依存している**(2026-09-22 実測)。view は OID で表に
--   結び付くので rename では付いてこない= §4' の中で create or replace view で親へ結び直す。
--   ⛔check は race_no(1..12)だけ・comment は無いので親にも付けない。
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
--   create index (名前は §0-2 で確認・定義は race_date desc, track) on public.nar_races (race_date desc, track);
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

-- 0-2 索引。期待= nar_races_pkey と (race_date desc, track) の 2 本。
select indexname, indexdef
  from pg_indexes where schemaname = 'public' and tablename = 'nar_races' order by indexname;

-- 0-3 制約。期待= PK と check(race_no_ck)。⛔知らない制約が出たら §1 に写す。
select conname, contype, pg_get_constraintdef(oid) as def
  from pg_constraint where conrelid = 'public.nar_races'::regclass order by conname;

-- 0-4 RLS と policy。期待= relrowsecurity = true・policy が **2 本**= nar_races_read(anon,authenticated)と nar_races_marks_writer_read(marks_writer)。
select relkind, relrowsecurity, relforcerowsecurity, reltuples::bigint as est_rows
  from pg_class where oid = 'public.nar_races'::regclass;
select policyname, permissive, roles, cmd, qual, with_check
  from pg_policies where schemaname = 'public' and tablename = 'nar_races' order by policyname;

-- 0-5 grant。期待= anon / authenticated / service_role に**全権限**(select, insert, update,
--   delete, truncate, references, trigger)。⛔読みだけに絞っているのは RLS の側= grant は広い。
--   ⛔この表だけ marks_writer にも select が付いている。
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

-- 0-9 この表に依存する view / matview。期待= **1 行= nar_sales_hourly**(⛔0 行ではない)。
--   ⛔view は OID で表に結び付く= rename しても向き先が**旧表(archive_part)に残る**。
--   期待と違う行が出たら、§4' の中(rename の後)に `create or replace view` を足す。
--   (2026-09-22 に洗った結果= nar_sales_daily は nar_sales の view で無関係。nar_search_runs /
--    nar_search_runs_v2 は plpgsql の中で表名を書いているだけ= 実行時に名前で引くので影響なし。
--    ⛔nar_sales_hourly だけが nar_races に依存している= 30_ の §4' で結び直す。)
select distinct dependent.relname, dependent.relkind
  from pg_depend d
  join pg_rewrite r on r.oid = d.objid
  join pg_class dependent on dependent.oid = r.ev_class
 where d.refobjid = 'public.nar_races'::regclass and d.classid = 'pg_rewrite'::regclass
   and dependent.relname <> 'nar_races';

-- 0-11 依存する view の今の定義と grant(⛔§4' で作り直すので、写しと一致することを確かめる)。
select pg_get_viewdef('public.nar_sales_hourly'::regclass, true);
select grantee, privilege_type from information_schema.role_table_grants
 where table_schema = 'public' and table_name = 'nar_sales_hourly' order by grantee, privilege_type;
-- 期待= 定義が §4'(ii-b) の写しと同じ・grant は anon / authenticated に SELECT。
--   ⛔定義が 1 文字でも違ったら、こちらの写しを本番の方に合わせてから §1 へ。

-- 0-10 移行前の行数の控え(⛔00_baseline_counts.sql でまとめて取ってもよい。99_verify.sql で使う)。
select count(*) as rows_all,
       count(*) filter (where race_date <  '2022-11-01') as rows_archive,
       count(*) filter (where race_date >= '2022-11-01') as rows_move,
       min(race_date) as d_min, max(race_date) as d_max
  from public.nar_races;


-- =====================================================================
-- §1 親表 nar_races_p と区画を作る(1 トランザクション)
--   ⛔索引・制約の**名前**は旧表とぶつからないよう `_p_` を挟む。理由= §4' の rename の後も
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

-- 〜2022-11-01 の区画は**作らない**= §3' で旧表をそのまま attach するために空けておく。
-- ⛔2030 まで先に作る(毎年 12 月に足す手作業を減らすため。区画の無い日付を upsert すると便が落ちる)。
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
create table public.nar_races_2028 partition of public.nar_races_p
  for values from ('2028-01-01') to ('2029-01-01');
create table public.nar_races_2029 partition of public.nar_races_p
  for values from ('2029-01-01') to ('2030-01-01');
create table public.nar_races_2030 partition of public.nar_races_p
  for values from ('2030-01-01') to ('2031-01-01');

-- 親に索引(区画ごとに自動で作られる)。⛔旧表と**同じ定義**にしておくと §3 の attach で
--   旧表の索引がそのまま繋がる(作り直しが起きない)。名前だけ変える。
create index nar_races_p_date_track_idx on public.nar_races_p (race_date desc, track);

alter table public.nar_races_p enable row level security;
create policy nar_races_read on public.nar_races_p
  for select to anon, authenticated using (true);
-- ⛔この表だけの 2 本目(2026-09-22 実測)= 印の書き手にも読みが要る。
create policy nar_races_marks_writer_read on public.nar_races_p
  for select to marks_writer using (true);
-- ⛔grant は本番と同じ「全権限」にする(2026-09-22 実測。読みだけに絞っているのは RLS の側)。
--   ⛔select だけにすると便(service_role)の書きが止まる。§0-5 の結果と見比べる。
grant all privileges on public.nar_races_p to anon, authenticated, service_role;
grant select on public.nar_races_p to marks_writer;

-- ⛔この表には comment が付いていない(2026-09-22 実測)= 親にも付けない。

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

-- 2-6 突き合わせ(⛔合わなければ §4' へ進まない)
select (select count(*) from public.nar_races where race_date >= '2022-11-01') as old_move,
       (select count(*) from public.nar_races_p) as new_rows;


-- =====================================================================
-- §4' 差分の取り直し → 名前の入れ替え → PostgREST(⛔**全部で 1 トランザクション**)
--   ここを 1 つにする理由= 途中で切れると「親に今年の行が無いのに画面は親を見る」状態が残る。
--   (i) §2 の写しの後に便が書いた行を拾う(2026-09-15 以降だけを見る)
--   (ii) 旧表 nar_races → nar_races_archive_part / 親 nar_races_p → nar_races
--   (iii) notify pgrst(⛔commit のときに配られる= トランザクションの中で書いてよい)
--   ⛔この commit の直後から画面は親を見る= **今年の行はそろっている**。
--   一時的に見えないのは 2022-10 以前だけ(§3' の attach で戻る・数分〜十数分)。
--   ⛔lock_timeout を短くして、長い select の後ろに並んで全部を待たせない。落ちても
--   トランザクションごと巻き戻るだけ= 数分後にもう一度流せばよい。
-- =====================================================================
begin;
set local lock_timeout = '5s';
set local statement_timeout = '10min';

-- (i) 差分の取り直し。⛔`updated_at >= …` で絞ってもよいが、日付で絞る方が索引が効く。
--     便を止めてから §2 を流し終えるまでの間に書かれた行を、上書きで拾う。
insert into public.nar_races_p
select * from public.nar_races where race_date >= '2026-09-15'
on conflict (track, race_date, race_no) do update set
  post_time = excluded.post_time,
  race_name = excluded.race_name,
  surface = excluded.surface,
  direction = excluded.direction,
  distance_m = excluded.distance_m,
  weather = excluded.weather,
  going = excluded.going,
  field_size = excluded.field_size,
  condition = excluded.condition,
  prize_yen = excluded.prize_yen,
  race_last4f = excluded.race_last4f,
  race_last3f = excluded.race_last3f,
  furlongs = excluded.furlongs,
  corners = excluded.corners,
  source = excluded.source,
  source_snapshot_hash = excluded.source_snapshot_hash,
  updated_at = excluded.updated_at,
  race_kind = excluded.race_kind,
  cancelled = excluded.cancelled,
  cancel_note = excluded.cancel_note,
  nankan = excluded.nankan;

-- (ii) 名前の入れ替え(区画の名前はそのまま)
alter table public.nar_races   rename to nar_races_archive_part;
alter table public.nar_races_p rename to nar_races;

-- (ii-b) ⛔nar_races に依存する view を親へ結び直す(2026-09-22 18:10 実測で発見)。
--   view は OID で表に結び付く= rename しただけでは nar_races_archive_part を指したままになり、
--   「今年の売得の時間帯別」が空になる。⛔定義は本番の pg_get_viewdef の写しそのまま(列名・型を変えない)。
create or replace view public.nar_sales_hourly as
  with r as (
    select s.track, s.race_date, s.race_no, v.net,
           substr(r_1.post_time, 1, 2)::integer * 60 + substr(r_1.post_time, 3, 2)::integer as post_min
      from nar_sales s
      join nar_races r_1 on r_1.track = s.track and r_1.race_date = s.race_date and r_1.race_no = s.race_no
      cross join lateral (
        select sum(coalesce((s.votes ->> k.k)::bigint, 0) - coalesce((s.refunds ->> k.k)::bigint, 0)) as net
          from jsonb_object_keys(s.votes) k(k)) v
     where s.race_date >= (current_date - 365) and r_1.post_time ~ '^[0-9]{4}$')
  select track, post_min / 30 * 30 as slot_min, count(*)::integer as races,
         avg(net)::bigint as avg_race_votes
    from r group by track, (post_min / 30 * 30);
-- ⛔view の grant は create or replace では消えないが、§0-11 の結果と見比べて足りなければ足す。
grant select on public.nar_sales_hourly to anon, authenticated;

-- (iii) PostgREST にスキーマを読み直させる
notify pgrst, 'reload schema';

commit;

-- ⛔ここで画面を 1 本開いて見る(当日のレース画面)。今年の行が出ていれば先へ進む。
--   出ていなければ 98_rollback.sql の 段 E(rename を戻すだけ)。
select count(*) as today_rows from public.nar_races where race_date = current_date;
select tableoid::regclass as part, count(*) from public.nar_races group by 1 order by 1;
-- 期待= 区画は 8 個(archive はまだ付いていない)・当日の行が 0 でない。

-- ⛔依存 view が親に結び直せたかの確認(⛔archive_part を指したままなら 0 行になる)。
select count(*) as hourly_rows from public.nar_sales_hourly;
select distinct refobjid::regclass as view_points_at
  from pg_depend d join pg_rewrite r on r.oid = d.objid
 where r.ev_class = 'public.nar_sales_hourly'::regclass and d.classid = 'pg_rewrite'::regclass
   and d.refclassid = 'pg_class'::regclass;
-- 期待= hourly_rows が 0 でない・向き先に nar_races(archive_part ではない)が出る。

-- ⛔便はここから動かしてよい(書き手は親へ入る)。§3' は便と並行で流せる。


-- =====================================================================
-- §3' archive_part から 2022-11-01 以降を消し、check を付けて archive 区画として attach
--   ⛔この間、2022-10 以前の行は**画面から見えない**(親にまだ付いていない)。
--   ⛔逆に、この間に 2022-10 以前の日付を upsert すると「区画が無い」で落ちる=
--   遡りの便(rakuten_backfill)だけは attach が終わるまで止めたままにする。
--   だから 3'-5 の attach まではできるだけ続けて流す(見込み= 小さい表 3 分・nar_runs 20 分)。
-- =====================================================================

-- 3'-0 今どうなっているかの確認(⛔読みだけ)
select count(*) as archive_all,
       count(*) filter (where race_date >= '2022-11-01') as to_delete
  from public.nar_races_archive_part;
-- 期待= to_delete が §2 で写した行数と同じ(+ §4'(i) で拾った差分のぶん)

-- 3'-1 delete(刻みごと・1 刻み 1 トランザクション)
--   ⛔消す行は親にコピー済み= 情報は落ちない。⛔不安なら 3'-0 の数を先に控える。
--   2022-11 〜 2023-12
begin;
set local statement_timeout = '30min';
delete from public.nar_races_archive_part where race_date >= '2022-11-01' and race_date < '2024-01-01';
commit;

--   2024
begin;
set local statement_timeout = '30min';
delete from public.nar_races_archive_part where race_date >= '2024-01-01' and race_date < '2025-01-01';
commit;

--   2025
begin;
set local statement_timeout = '30min';
delete from public.nar_races_archive_part where race_date >= '2025-01-01' and race_date < '2026-01-01';
commit;

--   2026(今年)
begin;
set local statement_timeout = '30min';
delete from public.nar_races_archive_part where race_date >= '2026-01-01' and race_date < '2027-01-01';
commit;

--   2027 以降
begin;
set local statement_timeout = '30min';
delete from public.nar_races_archive_part where race_date >= '2027-01-01';
commit;

-- 3'-2 delete で空いた場所を返す(⛔vacuum はトランザクションの中では流せない。
--   ⛔vacuum full は使わない= 表と同じ大きさの場所を新しく要求し、排他ロックで画面が止まる)
vacuum (analyze) public.nar_races_archive_part;

-- 3'-3 archive の check を not valid で付ける(短い排他・既存行は見ない= 数ミリ秒)
begin;
set local lock_timeout = '10s';
alter table public.nar_races_archive_part
  add constraint nar_races_archive_ck check (race_date < '2022-11-01') not valid;
commit;

-- 3'-4 validate(⛔読みだけの走査。SHARE UPDATE EXCLUSIVE なので select は止まらない)
begin;
set local statement_timeout = '30min';
alter table public.nar_races_archive_part validate constraint nar_races_archive_ck;
commit;

-- 3'-5 attach(check があるので全行走査は起きない。⛔親に一瞬 ACCESS EXCLUSIVE がかかる)
--   ⛔attach のとき、親の索引ごとに「同じ定義の索引」を attach 先から探して繋ぐ。無ければ
--   **その場で作る**(= 行数ぶん待つ)。§1 で定義を揃えてあるので、繋ぐだけで終わるはず。
--   ⛔長引くようなら止めて 98_rollback.sql の 段 D' を読む(古い年が見えない時間が伸びるだけで、
--   今年の行は見えているので画面は動いている)。
begin;
set local lock_timeout = '10s';
set local statement_timeout = '30min';
alter table public.nar_races
  attach partition public.nar_races_archive_part for values from (minvalue) to ('2022-11-01');
commit;

-- 3'-6 確認= 区画が 9 つ(親の下に archive を含む)・親の索引がすべて indisvalid
select relid::regclass as part, level from pg_partition_tree('public.nar_races');
select i.indexrelid::regclass as idx, i.indisvalid
  from pg_index i where i.indrelid = 'public.nar_races'::regclass;
-- ⛔ここで遡りの便(rakuten_backfill)を戻してよい。


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
create policy nar_races_marks_writer_read_part on public.nar_races_2022_11_2023
  for select to marks_writer using (true);
grant all privileges on public.nar_races_2022_11_2023 to anon, authenticated, service_role;
grant select on public.nar_races_2022_11_2023 to marks_writer;

alter table public.nar_races_2024 enable row level security;
create policy nar_races_part_read on public.nar_races_2024
  for select to anon, authenticated using (true);
create policy nar_races_marks_writer_read_part on public.nar_races_2024
  for select to marks_writer using (true);
grant all privileges on public.nar_races_2024 to anon, authenticated, service_role;
grant select on public.nar_races_2024 to marks_writer;

alter table public.nar_races_2025 enable row level security;
create policy nar_races_part_read on public.nar_races_2025
  for select to anon, authenticated using (true);
create policy nar_races_marks_writer_read_part on public.nar_races_2025
  for select to marks_writer using (true);
grant all privileges on public.nar_races_2025 to anon, authenticated, service_role;
grant select on public.nar_races_2025 to marks_writer;

alter table public.nar_races_2026 enable row level security;
create policy nar_races_part_read on public.nar_races_2026
  for select to anon, authenticated using (true);
create policy nar_races_marks_writer_read_part on public.nar_races_2026
  for select to marks_writer using (true);
grant all privileges on public.nar_races_2026 to anon, authenticated, service_role;
grant select on public.nar_races_2026 to marks_writer;

alter table public.nar_races_2027 enable row level security;
create policy nar_races_part_read on public.nar_races_2027
  for select to anon, authenticated using (true);
create policy nar_races_marks_writer_read_part on public.nar_races_2027
  for select to marks_writer using (true);
grant all privileges on public.nar_races_2027 to anon, authenticated, service_role;
grant select on public.nar_races_2027 to marks_writer;

alter table public.nar_races_2028 enable row level security;
create policy nar_races_part_read on public.nar_races_2028
  for select to anon, authenticated using (true);
create policy nar_races_marks_writer_read_part on public.nar_races_2028
  for select to marks_writer using (true);
grant all privileges on public.nar_races_2028 to anon, authenticated, service_role;
grant select on public.nar_races_2028 to marks_writer;

alter table public.nar_races_2029 enable row level security;
create policy nar_races_part_read on public.nar_races_2029
  for select to anon, authenticated using (true);
create policy nar_races_marks_writer_read_part on public.nar_races_2029
  for select to marks_writer using (true);
grant all privileges on public.nar_races_2029 to anon, authenticated, service_role;
grant select on public.nar_races_2029 to marks_writer;

alter table public.nar_races_2030 enable row level security;
create policy nar_races_part_read on public.nar_races_2030
  for select to anon, authenticated using (true);
create policy nar_races_marks_writer_read_part on public.nar_races_2030
  for select to marks_writer using (true);
grant all privileges on public.nar_races_2030 to anon, authenticated, service_role;
grant select on public.nar_races_2030 to marks_writer;

commit;

-- ⛔vacuum はトランザクションの外・区画ごとに 1 本ずつ
vacuum (analyze) public.nar_races_2022_11_2023;
vacuum (analyze) public.nar_races_2024;
vacuum (analyze) public.nar_races_2025;
vacuum (analyze) public.nar_races_2026;
vacuum (analyze) public.nar_races_2027;
vacuum (analyze) public.nar_races_2028;
vacuum (analyze) public.nar_races_2029;
vacuum (analyze) public.nar_races_2030;
vacuum (analyze) public.nar_races_archive_part;
analyze public.nar_races;

-- 最後に PostgREST をもう一度(区画を足したときは不要だが、害はない)
notify pgrst, 'reload schema';
