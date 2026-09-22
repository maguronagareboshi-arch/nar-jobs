-- §240 / 巻き戻し(⛔流す前に「今どこで止まったか」を決める。段によって手が違う)
-- 設計= docs/proposal_s240_partition_20260922.md ・手順= docs/notes_s240_migration.md
-- ⛔新しい順(2026-09-22 に入れ替え)= §1 → §2 → §4'(差分+rename+notify を 1 トランザクション)
--   → §3'(archive_part の delete → check → validate → attach)→ §5。
--   この順だと「今年のデータが画面から消える窓」が無い。巻き戻しの段も下の A〜G に書き直した。
-- ⛔この中の文は**表ごとに 1 つの段だけ**を選んで流す。上から順に全部流すものではない。
-- ⛔どの段でも、最後に `notify pgrst, 'reload schema';` を 1 回流す。
--
-- 下の例は nar_runs で書いている。ほかの 4 表は表名を置き換える(区画名も同じ規則)。
--   <表> = nar_race_votes / nar_race_payouts / nar_races / nar_runs / nar_run_facts

-- =====================================================================
-- 段 A) §1 の途中/直後(親と区画を作っただけ・まだ 1 行も写していない)
--   → 親をまるごと落とすだけ。旧表は 1 行も触っていないので 5 秒で元通り。画面は無事。
-- =====================================================================
begin;
drop table if exists public.nar_runs_p cascade;   -- 区画 8 つも一緒に消える
commit;
-- ⛔`cascade` は「親に付いた区画・索引・ポリシー」を消すだけ。旧表 nar_runs には届かない
--   (まだ attach していないため)。

-- =====================================================================
-- 段 B) §2 の途中/直後(親へ写した・旧表はまだ無傷= 行が二重にある状態)
--   → これも親を落とすだけ。⛔旧表が正本のまま残っているので情報は消えない。画面は無事。
-- =====================================================================
begin;
drop table if exists public.nar_runs_p cascade;
commit;
-- そのあと必ず: select count(*) from public.nar_runs;  ← 00_baseline_counts.sql の控えと一致すること

-- =====================================================================
-- 段 C) §4' が落ちた(差分の取り直し・rename・notify は 1 トランザクション)
--   → ⛔何もしなくてよい。トランザクションごと巻き戻っている= 段 B と同じ状態。
--   確認だけして、直してからもう一度 §4' を流すか、段 B で親を落とす。
-- =====================================================================
select to_regclass('public.nar_runs')               as tbl,          -- 期待= 旧表(まだ普通の表)
       to_regclass('public.nar_runs_p')             as parent,       -- 期待= 親(まだ _p のまま)
       to_regclass('public.nar_runs_archive_part')  as archive;      -- 期待= null(rename されていない)
select relkind from pg_class where oid = 'public.nar_runs'::regclass;  -- 期待= 'r'(親なら 'p')

-- =====================================================================
-- 段 D) §4' の直後・§3' はまだ(⛔一番楽で一番安全= 名前を戻すだけ・数ミリ秒)
--   この時点では旧表(= nar_runs_archive_part)が**全期間の正本**のまま残っている
--   (§3' の delete をまだ流していないため)。名前を戻せば移行前と完全に同じ姿になる。
--   画面が変なら、まずこれを流す。データは 1 行も動かさない。
-- =====================================================================
begin;
set local lock_timeout = '5s';
alter table public.nar_runs               rename to nar_runs_p;
alter table public.nar_runs_archive_part  rename to nar_runs;
commit;
notify pgrst, 'reload schema';
-- そのあと: select count(*) from public.nar_runs;  ← 控えと一致(全期間そろっている)
-- 親を残しておけば直して §4' をもう一度流せる。捨てるなら 段 B を流す。
--
-- ⛔**nar_races のときだけ**= 名前を戻したあと、依存 view `nar_sales_hourly` を**旧表に**結び直す。
--   §4'(ii-b) で親に向けてあるので、そのままだと view が `nar_races_p`(中身が今年だけ)を指したまま。
--   30_nar_races.sql の (ii-b) の `create or replace view` をもう一度そのまま流せばよい
--   (名前 `nar_races` が旧表に戻っているので、同じ SQL で旧表に結び直る)。そのあと notify pgrst。

-- =====================================================================
-- 段 E) §3' の delete を始めてしまった(archive_part から 2022-11 以降が減っている)
--   → ⛔**巻き戻すより attach を急ぐ方が安全**。理由= 今年の行は親にそろっていて画面は動いている。
--   足りないのは 2022-10 以前が見えないことだけ= 3'-3 → 3'-4 → 3'-5 を続けて流せば戻る。
--   ⛔どうしても移行前の姿へ戻すなら E-1 から順に。
-- =====================================================================
-- E-0 まず状況を見る(⛔読みだけ)
select (select count(*) from public.nar_runs_archive_part where race_date >= '2022-11-01') as left_in_archive,
       (select count(*) from public.nar_runs)                                              as parent_rows;

-- E-1 名前を戻す(画面を旧表へ向け直す。⛔この瞬間から今年の行が見えなくなるので、
--   E-3 まで続けて流す。⛔夜以外にはやらない)
begin;
set local lock_timeout = '5s';
alter table public.nar_runs               rename to nar_runs_p;
alter table public.nar_runs_archive_part  rename to nar_runs;
commit;
notify pgrst, 'reload schema';

-- E-2 旧表に付けた check を外す(あると 2022-11 以降を戻せない。まだ付けていなければ空振りする)
begin;
set local lock_timeout = '10s';
alter table public.nar_runs drop constraint if exists nar_runs_archive_ck;
commit;

-- E-3 親にあって旧表に無い行を戻す(年ごと・1 年 1 トランザクション)
--   ⛔`on conflict do nothing` = 旧表に残っている行は上書きしない(delete の途中で止まった年は
--   両方に同じ行があるため)。
begin;
set local statement_timeout = '30min';
insert into public.nar_runs select * from public.nar_runs_p
 where race_date >= '2022-11-01' and race_date < '2023-01-01'
on conflict (track, race_date, race_no, runner_number) do nothing;
commit;
-- 以下 2023 / 2024 / 2025 / 2026 / 2027 以降も同じ形で 1 年ずつ(⛔範囲だけ書き換えて流す)

-- E-4 突き合わせ(⛔控えと一致してから E-5)
select count(*) from public.nar_runs;

-- E-5 親を落とす
begin;
drop table if exists public.nar_runs_p cascade;
commit;
vacuum (analyze) public.nar_runs;
notify pgrst, 'reload schema';

-- =====================================================================
-- 段 F) §3'-5 の attach まで終わった(= 移行は完成している)。あとから問題が出たとき
--   → detach → 名前を戻す → 親から旧表へ戻す。⛔一番手数が多い。
--   ⛔まず「本当に戻す必要があるか」を考える。区画の剪定が効かないだけなら §5 と analyze の
--   やり直しで直ることが多い(段 G)。
-- =====================================================================
-- F-1 archive 区画を切り離す(旧表が単独の表に戻る。名前は nar_runs_archive_part のまま)
begin;
set local lock_timeout = '10s';
alter table public.nar_runs detach partition public.nar_runs_archive_part;
commit;
-- ⛔detach で旧表の索引は親から切り離される(索引そのものは残る)。

-- F-2 そのあと 段 E-1 〜 E-5 を同じ順で流す(名前を戻す → check を外す → 行を戻す → 親を落とす)。
-- ⛔nar_races のときは E-1 の直後に `create or replace view public.nar_sales_hourly …`(30_ の (ii-b))を
--   もう一度流して view を旧表へ結び直す。⛔忘れると「今年の売得の時間帯別」が空のままになる。

-- =====================================================================
-- 段 G) §5 の grant/policy だけ間に合っていない(行は全部そろっている)
--   → 巻き戻さない。その表の §5 を流し直す(何度流しても同じ結果になるよう先に drop する)。
--   ⛔症状= 匿名キーで 0 行・画面が空。99_verify.sql の 5) で出る。
-- =====================================================================
begin;
drop policy if exists nar_runs_part_read on public.nar_runs_2026;
create policy nar_runs_part_read on public.nar_runs_2026
  for select to anon, authenticated using (true);
grant select on public.nar_runs_2026 to anon, authenticated;
commit;
notify pgrst, 'reload schema';
-- ⛔区画 8 つ + archive のぶんを同じ形で流す(その表の §5 をそのまま使ってよい)。

-- =====================================================================
-- 最後に(どの段でも)
-- =====================================================================
notify pgrst, 'reload schema';
-- そのあと 99_verify.sql の 2) と 5) を流して、行数と匿名キーでの読みを確かめる。
