-- §240 表を年で区切る(宣言的パーティション)/ 5 表目 = nar_run_facts
--   派生表(通過順・脚質・前半3F・発走直前の単勝)
-- 設計= docs/proposal_s240_partition_20260922.md ・規則= docs/opus_rules.md
-- 書いたのは Opus 実装(2026-09-22)。⛔本番 DB には一切触っていない。
--   下の DDL は手元のコードから**読み取った写し**= 本番の実物と違う可能性がある。
--   ⛔必ず §0 を先に流して答え合わせをしてから §1 へ進む。
-- 出どころ= pipeline/sql/run_facts_20260921.sql(§238a でこの形のまま本番に流した create table)
-- 行の見込み= 1 年 約 19 万行(全体 約 145.7 万行・2014〜)
-- なぜこの順番か= 大きい表の 2 つ目(約 145.7 万行・681MB)。⛔一番最後。
-- 流す人= 鍵を持つ担当(検品役)。⛔1 ステップ 1 トランザクション。
-- ⛔流す順は §1 → §2 → **§4'** → **§3'** → §5(2026-09-22 に入れ替えた)。
--   前の版は「§3 delete → §4 rename」の順で、その間 15〜25 分ぶん、旧表を見ている画面から
--   **今年のデータが消える**窓があった。入れ替えた今は、先に名前を入れ替えて画面を親へ向ける=
--   今年の行は最初からそろっていて、一時的に見えないのは **2022-10 以前だけ**(数分〜十数分)。
--   ⛔始める前に便を止める(nar-refresh / nar-ai-feat / nar-ai-last / run-facts-backfill /
--   rakuten_backfill / pg_cron)。⛔止めていていい範囲は **§1 から §4' まで**。
--   §4' が終われば書き手は親へ入る= §3' は便を動かしたまま流してよい。
-- ⚠ この表だけの注意:
--   ⛔この表は PK が (race_date, track, race_no, umaban)= 区画キーが**先頭**。ほかの 4 表と並びが違う。
--   ⛔check 制約が 3 本ある= 親に同じものを付ける(名前は `_p_` を挟む)。
--
-- 今の形と思っているもの(⛔§0-1 が正):
--   create table public.nar_run_facts (
--     race_date      date         not null,
--     track          text         not null,
--     race_no        int          not null,
--     umaban         int          not null,
--     horse_key      text         ,
--     horse_name     text         ,
--     c1             int          ,
--     n1             int          ,
--     c2             int          ,
--     n2             int          ,
--     c3             int          ,
--     n3             int          ,
--     c4             int          ,
--     n4             int          ,
--     style          text         ,
--     style_p        numeric      ,
--     style_n        int          ,
--     first3f        numeric      ,
--     first3f_src    text         ,
--     last3f         numeric      ,
--     win_odds_close numeric      ,
--     src            text         not null,
--     computed_at    timestamptz  not null,
--     primary key (race_date, track, race_no, umaban));
--   create index nar_run_facts_date_idx on public.nar_run_facts (race_date desc, track);
--   create index nar_run_facts_horse_idx on public.nar_run_facts (horse_key, race_date desc);
--   constraint nar_run_facts_first3f_src_ck check (first3f_src is null or first3f_src in ('own', 'paper', 'kb', 'est'))
--   constraint nar_run_facts_first3f_pair_ck check ((first3f is null) = (first3f_src is null))
--   constraint nar_run_facts_style_ck check (style is null or style in ('逃げ', '先行', '差し', '追込'))
--   → PK に race_date が入っている= 区画キーにできる(設計の前提 (a) を満たす)


-- =====================================================================
-- §0 当てる前に本番で確かめる(⛔読みだけ。ここで違いが出たら §1 の DDL を直す)
-- =====================================================================
-- 0-1 列と型と並び。期待= 23 列・上の写しと同じ順。
select ordinal_position, column_name, data_type, is_nullable, column_default
  from information_schema.columns
 where table_schema = 'public' and table_name = 'nar_run_facts'
 order by ordinal_position;

-- 0-2 索引。期待= nar_run_facts_pkey・nar_run_facts_date_idx・nar_run_facts_horse_idx の 3 本。
select indexname, indexdef
  from pg_indexes where schemaname = 'public' and tablename = 'nar_run_facts' order by indexname;

-- 0-3 制約。期待= PK と check(first3f_src_ck, first3f_pair_ck, style_ck)。⛔知らない制約が出たら §1 に写す。
select conname, contype, pg_get_constraintdef(oid) as def
  from pg_constraint where conrelid = 'public.nar_run_facts'::regclass order by conname;

-- 0-4 RLS と policy。期待= relrowsecurity = true・policy は nar_run_facts_read 1 本(select / {anon,authenticated} / true)。
select relkind, relrowsecurity, relforcerowsecurity, reltuples::bigint as est_rows
  from pg_class where oid = 'public.nar_run_facts'::regclass;
select policyname, permissive, roles, cmd, qual, with_check
  from pg_policies where schemaname = 'public' and tablename = 'nar_run_facts' order by policyname;

-- 0-5 grant。期待= anon / authenticated に SELECT・service_role に読み書き。
select grantee, privilege_type from information_schema.role_table_grants
 where table_schema = 'public' and table_name = 'nar_run_facts' order by grantee, privilege_type;

-- 0-6 trigger。期待= 0 行。⛔1 行でも出たら §1 に写して親へ付け直してから進む。
select tgname, pg_get_triggerdef(oid) from pg_trigger
 where tgrelid = 'public.nar_run_facts'::regclass and not tgisinternal;

-- 0-7 この表を指している外部キー。期待= 0 行。
--   ⛔1 行でも出たら止めて報告(参照される側を差し替えるので手順が増える)。
select c.relname as referencing_table, k.conname, pg_get_constraintdef(k.oid) as def
  from pg_constraint k join pg_class c on c.oid = k.conrelid
 where k.contype = 'f' and k.confrelid = 'public.nar_run_facts'::regclass;

-- 0-8 この表から出ている外部キー。期待= 0 行(⛔パーティションの子は FK を持てるが、
--   attach のときに親へ写す手間が増えるので数を見ておく)。
select conname, pg_get_constraintdef(oid) from pg_constraint
 where conrelid = 'public.nar_run_facts'::regclass and contype = 'f';

-- 0-9 この表に依存する view / matview。期待= 0 行。
--   ⛔rename は view の向き先を**旧表に残す**。1 行でも出たら §4 の前に view を作り直す手順を足す。
--   (手元で洗った結果= nar_sales_daily は nar_sales の view で無関係。nar_search_runs /
--    nar_search_runs_v2 は plpgsql の中で表名を書いているだけ= 実行時に名前で引くので影響なし。)
select distinct dependent.relname, dependent.relkind
  from pg_depend d
  join pg_rewrite r on r.oid = d.objid
  join pg_class dependent on dependent.oid = r.ev_class
 where d.refobjid = 'public.nar_run_facts'::regclass and d.classid = 'pg_rewrite'::regclass
   and dependent.relname <> 'nar_run_facts';

-- 0-10 移行前の行数の控え(⛔00_baseline_counts.sql でまとめて取ってもよい。99_verify.sql で使う)。
select count(*) as rows_all,
       count(*) filter (where race_date <  '2022-11-01') as rows_archive,
       count(*) filter (where race_date >= '2022-11-01') as rows_move,
       min(race_date) as d_min, max(race_date) as d_max
  from public.nar_run_facts;


-- =====================================================================
-- §1 親表 nar_run_facts_p と区画を作る(1 トランザクション)
--   ⛔索引・制約の**名前**は旧表とぶつからないよう `_p_` を挟む。理由= §4' の rename の後も
--   旧表の索引名(nar_run_facts_pkey など)はそのまま残るため、同じ名前を先に使うと §1 が落ちる。
--   PK 制約の名前は create table が自動で `nar_run_facts_p_pkey` にする= 衝突しない。
-- =====================================================================
begin;
set local lock_timeout = '10s';

create table public.nar_run_facts_p (
  race_date      date         not null,
  track          text         not null,
  race_no        int          not null,
  umaban         int          not null,
  horse_key      text         ,
  horse_name     text         ,
  c1             int          ,
  n1             int          ,
  c2             int          ,
  n2             int          ,
  c3             int          ,
  n3             int          ,
  c4             int          ,
  n4             int          ,
  style          text         ,
  style_p        numeric      ,
  style_n        int          ,
  first3f        numeric      ,
  first3f_src    text         ,
  last3f         numeric      ,
  win_odds_close numeric      ,
  src            text         not null,
  computed_at    timestamptz  not null,
  constraint nar_run_facts_p_first3f_src_ck check (first3f_src is null or first3f_src in ('own', 'paper', 'kb', 'est')),
  constraint nar_run_facts_p_first3f_pair_ck check ((first3f is null) = (first3f_src is null)),
  constraint nar_run_facts_p_style_ck check (style is null or style in ('逃げ', '先行', '差し', '追込')),
  primary key (race_date, track, race_no, umaban)
) partition by range (race_date);

-- 〜2022-11-01 の区画は**作らない**= §3' で旧表をそのまま attach するために空けておく。
-- ⛔2030 まで先に作る(毎年 12 月に足す手作業を減らすため。区画の無い日付を upsert すると便が落ちる)。
create table public.nar_run_facts_2022_11_2023 partition of public.nar_run_facts_p
  for values from ('2022-11-01') to ('2024-01-01');
create table public.nar_run_facts_2024 partition of public.nar_run_facts_p
  for values from ('2024-01-01') to ('2025-01-01');
create table public.nar_run_facts_2025 partition of public.nar_run_facts_p
  for values from ('2025-01-01') to ('2026-01-01');
create table public.nar_run_facts_2026 partition of public.nar_run_facts_p
  for values from ('2026-01-01') to ('2027-01-01');
create table public.nar_run_facts_2027 partition of public.nar_run_facts_p
  for values from ('2027-01-01') to ('2028-01-01');
create table public.nar_run_facts_2028 partition of public.nar_run_facts_p
  for values from ('2028-01-01') to ('2029-01-01');
create table public.nar_run_facts_2029 partition of public.nar_run_facts_p
  for values from ('2029-01-01') to ('2030-01-01');
create table public.nar_run_facts_2030 partition of public.nar_run_facts_p
  for values from ('2030-01-01') to ('2031-01-01');

-- 親に索引(区画ごとに自動で作られる)。⛔旧表と**同じ定義**にしておくと §3 の attach で
--   旧表の索引がそのまま繋がる(作り直しが起きない)。名前だけ変える。
create index nar_run_facts_p_date_idx on public.nar_run_facts_p (race_date desc, track);
create index nar_run_facts_p_horse_idx on public.nar_run_facts_p (horse_key, race_date desc);

alter table public.nar_run_facts_p enable row level security;
create policy nar_run_facts_read on public.nar_run_facts_p
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_p to anon, authenticated;
-- ⛔書き手(便)は service_role で入る。Supabase の既定で service_role は RLS を素通りするが、
--   grant は要る= 旧表と同じものを付ける。§0-5 の結果と見比べて足りない行を足す。
grant select, insert, update, delete on public.nar_run_facts_p to service_role;

comment on table public.nar_run_facts_p is
  '§238a 1 頭 1 行の派生表。通過順の順位・脚質(発走前 as-of)・前半3F(出どころ付き)・発走直前の単勝。書き手は cloud/run_facts.py。§240 で race_date の年ごとに区切った親表';

commit;


-- =====================================================================
-- §2 2022-11-01 以降を親へ写す(⛔1 刻み 1 トランザクション・1 回 25 万行以下)
--   1 年 約 19 万行(全体 約 145.7 万行・2014〜)
-- =====================================================================

-- 2-0 列の並びが親と旧表で同じことを機械で確かめる(⛔違えばここで止まる)。
--   `select *` は位置で入るので、並びが 1 つずれると値が別の列に入る。
do $$
declare v_old text; v_new text;
begin
  select string_agg(column_name || ' ' || data_type, ',' order by ordinal_position) into v_old
    from information_schema.columns where table_schema='public' and table_name='nar_run_facts';
  select string_agg(column_name || ' ' || data_type, ',' order by ordinal_position) into v_new
    from information_schema.columns where table_schema='public' and table_name='nar_run_facts_p';
  if v_old is distinct from v_new then
    raise exception '列が違う。旧= % / 親= %', v_old, v_new;
  end if;
end $$;

-- 2-1 2022-11 〜 2022-12
begin;
set local statement_timeout = '30min';
insert into public.nar_run_facts_p
select * from public.nar_run_facts
 where race_date >= '2022-11-01' and race_date < '2023-01-01';
commit;

-- 2-2 2023
begin;
set local statement_timeout = '30min';
insert into public.nar_run_facts_p
select * from public.nar_run_facts
 where race_date >= '2023-01-01' and race_date < '2024-01-01';
commit;

-- 2-3 2024
begin;
set local statement_timeout = '30min';
insert into public.nar_run_facts_p
select * from public.nar_run_facts
 where race_date >= '2024-01-01' and race_date < '2025-01-01';
commit;

-- 2-4 2025
begin;
set local statement_timeout = '30min';
insert into public.nar_run_facts_p
select * from public.nar_run_facts
 where race_date >= '2025-01-01' and race_date < '2026-01-01';
commit;

-- 2-5 2026(今年)
begin;
set local statement_timeout = '30min';
insert into public.nar_run_facts_p
select * from public.nar_run_facts
 where race_date >= '2026-01-01' and race_date < '2027-01-01';
commit;

-- 2-6 2027 以降
begin;
set local statement_timeout = '30min';
insert into public.nar_run_facts_p
select * from public.nar_run_facts
 where race_date >= '2027-01-01';
commit;

-- 2-7 突き合わせ(⛔合わなければ §4' へ進まない)
select (select count(*) from public.nar_run_facts where race_date >= '2022-11-01') as old_move,
       (select count(*) from public.nar_run_facts_p) as new_rows;


-- =====================================================================
-- §4' 差分の取り直し → 名前の入れ替え → PostgREST(⛔**全部で 1 トランザクション**)
--   ここを 1 つにする理由= 途中で切れると「親に今年の行が無いのに画面は親を見る」状態が残る。
--   (i) §2 の写しの後に便が書いた行を拾う(2026-09-15 以降だけを見る)
--   (ii) 旧表 nar_run_facts → nar_run_facts_archive_part / 親 nar_run_facts_p → nar_run_facts
--   (iii) notify pgrst(⛔commit のときに配られる= トランザクションの中で書いてよい)
--   ⛔この commit の直後から画面は親を見る= **今年の行はそろっている**。
--   一時的に見えないのは 2022-10 以前だけ(§3' の attach で戻る・数分〜十数分)。
--   ⛔lock_timeout を短くして、長い select の後ろに並んで全部を待たせない。落ちても
--   トランザクションごと巻き戻るだけ= 数分後にもう一度流せばよい。
-- =====================================================================
begin;
set local lock_timeout = '5s';
set local statement_timeout = '10min';

-- (i) 差分の取り直し。⛔`computed_at >= …` で絞ってもよいが、日付で絞る方が索引が効く。
--     便を止めてから §2 を流し終えるまでの間に書かれた行を、上書きで拾う。
insert into public.nar_run_facts_p
select * from public.nar_run_facts where race_date >= '2026-09-15'
on conflict (race_date, track, race_no, umaban) do update set
  horse_key = excluded.horse_key,
  horse_name = excluded.horse_name,
  c1 = excluded.c1,
  n1 = excluded.n1,
  c2 = excluded.c2,
  n2 = excluded.n2,
  c3 = excluded.c3,
  n3 = excluded.n3,
  c4 = excluded.c4,
  n4 = excluded.n4,
  style = excluded.style,
  style_p = excluded.style_p,
  style_n = excluded.style_n,
  first3f = excluded.first3f,
  first3f_src = excluded.first3f_src,
  last3f = excluded.last3f,
  win_odds_close = excluded.win_odds_close,
  src = excluded.src,
  computed_at = excluded.computed_at;

-- (ii) 名前の入れ替え(区画の名前はそのまま)
alter table public.nar_run_facts   rename to nar_run_facts_archive_part;
alter table public.nar_run_facts_p rename to nar_run_facts;

-- (iii) PostgREST にスキーマを読み直させる
notify pgrst, 'reload schema';

commit;

-- ⛔ここで画面を 1 本開いて見る(当日のレース画面)。今年の行が出ていれば先へ進む。
--   出ていなければ 98_rollback.sql の 段 E(rename を戻すだけ)。
select count(*) as today_rows from public.nar_run_facts where race_date = current_date;
select tableoid::regclass as part, count(*) from public.nar_run_facts group by 1 order by 1;
-- 期待= 区画は 8 個(archive はまだ付いていない)・当日の行が 0 でない。

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
  from public.nar_run_facts_archive_part;
-- 期待= to_delete が §2 で写した行数と同じ(+ §4'(i) で拾った差分のぶん)

-- 3'-1 delete(刻みごと・1 刻み 1 トランザクション)
--   ⛔消す行は親にコピー済み= 情報は落ちない。⛔不安なら 3'-0 の数を先に控える。
--   2022-11 〜 2022-12
begin;
set local statement_timeout = '30min';
delete from public.nar_run_facts_archive_part where race_date >= '2022-11-01' and race_date < '2023-01-01';
commit;

--   2023
begin;
set local statement_timeout = '30min';
delete from public.nar_run_facts_archive_part where race_date >= '2023-01-01' and race_date < '2024-01-01';
commit;

--   2024
begin;
set local statement_timeout = '30min';
delete from public.nar_run_facts_archive_part where race_date >= '2024-01-01' and race_date < '2025-01-01';
commit;

--   2025
begin;
set local statement_timeout = '30min';
delete from public.nar_run_facts_archive_part where race_date >= '2025-01-01' and race_date < '2026-01-01';
commit;

--   2026(今年)
begin;
set local statement_timeout = '30min';
delete from public.nar_run_facts_archive_part where race_date >= '2026-01-01' and race_date < '2027-01-01';
commit;

--   2027 以降
begin;
set local statement_timeout = '30min';
delete from public.nar_run_facts_archive_part where race_date >= '2027-01-01';
commit;

-- 3'-2 delete で空いた場所を返す(⛔vacuum はトランザクションの中では流せない。
--   ⛔vacuum full は使わない= 表と同じ大きさの場所を新しく要求し、排他ロックで画面が止まる)
vacuum (analyze) public.nar_run_facts_archive_part;

-- 3'-3 archive の check を not valid で付ける(短い排他・既存行は見ない= 数ミリ秒)
begin;
set local lock_timeout = '10s';
alter table public.nar_run_facts_archive_part
  add constraint nar_run_facts_archive_ck check (race_date < '2022-11-01') not valid;
commit;

-- 3'-4 validate(⛔読みだけの走査。SHARE UPDATE EXCLUSIVE なので select は止まらない)
begin;
set local statement_timeout = '30min';
alter table public.nar_run_facts_archive_part validate constraint nar_run_facts_archive_ck;
commit;

-- 3'-5 attach(check があるので全行走査は起きない。⛔親に一瞬 ACCESS EXCLUSIVE がかかる)
--   ⛔attach のとき、親の索引ごとに「同じ定義の索引」を attach 先から探して繋ぐ。無ければ
--   **その場で作る**(= 行数ぶん待つ)。§1 で定義を揃えてあるので、繋ぐだけで終わるはず。
--   ⛔長引くようなら止めて 98_rollback.sql の 段 D' を読む(古い年が見えない時間が伸びるだけで、
--   今年の行は見えているので画面は動いている)。
begin;
set local lock_timeout = '10s';
set local statement_timeout = '30min';
alter table public.nar_run_facts
  attach partition public.nar_run_facts_archive_part for values from (minvalue) to ('2022-11-01');
commit;

-- 3'-6 確認= 区画が 9 つ(親の下に archive を含む)・親の索引がすべて indisvalid
select relid::regclass as part, level from pg_partition_tree('public.nar_run_facts');
select i.indexrelid::regclass as idx, i.indisvalid
  from pg_index i where i.indrelid = 'public.nar_run_facts'::regclass;
-- ⛔ここで遡りの便(rakuten_backfill)を戻してよい。


-- =====================================================================
-- §5 区画ごとの grant / RLS と vacuum analyze
--   ⛔親越しの select では権限は親だけを見る= この grant は「区画を直接引くとき」の保険。
--   ⛔RLS は**区画のポリシーも効く**。区画に RLS を有効にしてポリシーを置かないと、親越しの
--   select が 0 行になり得る。だから有効化とポリシーは必ず一組で流す。
--   (archive 区画= 旧表は元から RLS 有効+読みポリシー付きなので、そのままでよい)
-- =====================================================================
begin;
alter table public.nar_run_facts_2022_11_2023 enable row level security;
create policy nar_run_facts_part_read on public.nar_run_facts_2022_11_2023
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_2022_11_2023 to anon, authenticated;
grant select, insert, update, delete on public.nar_run_facts_2022_11_2023 to service_role;

alter table public.nar_run_facts_2024 enable row level security;
create policy nar_run_facts_part_read on public.nar_run_facts_2024
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_2024 to anon, authenticated;
grant select, insert, update, delete on public.nar_run_facts_2024 to service_role;

alter table public.nar_run_facts_2025 enable row level security;
create policy nar_run_facts_part_read on public.nar_run_facts_2025
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_2025 to anon, authenticated;
grant select, insert, update, delete on public.nar_run_facts_2025 to service_role;

alter table public.nar_run_facts_2026 enable row level security;
create policy nar_run_facts_part_read on public.nar_run_facts_2026
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_2026 to anon, authenticated;
grant select, insert, update, delete on public.nar_run_facts_2026 to service_role;

alter table public.nar_run_facts_2027 enable row level security;
create policy nar_run_facts_part_read on public.nar_run_facts_2027
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_2027 to anon, authenticated;
grant select, insert, update, delete on public.nar_run_facts_2027 to service_role;

alter table public.nar_run_facts_2028 enable row level security;
create policy nar_run_facts_part_read on public.nar_run_facts_2028
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_2028 to anon, authenticated;
grant select, insert, update, delete on public.nar_run_facts_2028 to service_role;

alter table public.nar_run_facts_2029 enable row level security;
create policy nar_run_facts_part_read on public.nar_run_facts_2029
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_2029 to anon, authenticated;
grant select, insert, update, delete on public.nar_run_facts_2029 to service_role;

alter table public.nar_run_facts_2030 enable row level security;
create policy nar_run_facts_part_read on public.nar_run_facts_2030
  for select to anon, authenticated using (true);
grant select on public.nar_run_facts_2030 to anon, authenticated;
grant select, insert, update, delete on public.nar_run_facts_2030 to service_role;

commit;

-- ⛔vacuum はトランザクションの外・区画ごとに 1 本ずつ
vacuum (analyze) public.nar_run_facts_2022_11_2023;
vacuum (analyze) public.nar_run_facts_2024;
vacuum (analyze) public.nar_run_facts_2025;
vacuum (analyze) public.nar_run_facts_2026;
vacuum (analyze) public.nar_run_facts_2027;
vacuum (analyze) public.nar_run_facts_2028;
vacuum (analyze) public.nar_run_facts_2029;
vacuum (analyze) public.nar_run_facts_2030;
vacuum (analyze) public.nar_run_facts_archive_part;
analyze public.nar_run_facts;

-- 最後に PostgREST をもう一度(区画を足したときは不要だが、害はない)
notify pgrst, 'reload schema';
