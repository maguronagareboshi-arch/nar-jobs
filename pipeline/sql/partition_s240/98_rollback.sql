-- §240 / 巻き戻し(⛔流す前に「今どこで止まったか」を決める。段によって手が違う)
-- 設計= docs/proposal_s240_partition_20260922.md ・手順= docs/notes_s240_migration.md
-- ⛔この中の文は**表ごとに 1 つの段だけ**を選んで流す。上から順に全部流すものではない。
-- ⛔どの段でも、巻き戻したあとは `notify pgrst, 'reload schema';` を最後に 1 回流す。
--
-- 下の例は nar_runs で書いている。ほかの 4 表は表名を置き換える(区画名も同じ規則)。
--   <表> = nar_race_votes / nar_race_payouts / nar_races / nar_runs / nar_run_facts

-- =====================================================================
-- 段 A) §1 の途中/直後(親と区画を作っただけ・まだ 1 行も写していない)
--   → 親をまるごと落とすだけ。旧表は 1 行も触っていないので 5 秒で元通り。
-- =====================================================================
begin;
drop table if exists public.nar_runs_p cascade;   -- 区画 5 つも一緒に消える
commit;
-- ⛔`cascade` は「親に付いた区画・索引・ポリシー」を消すだけ。旧表 nar_runs には届かない
--   (まだ attach していないため)。attach 済みなら段 C を見る。

-- =====================================================================
-- 段 B) §2 の途中/直後(親へ写した・旧表はまだ無傷= 行が二重にある状態)
--   → これも親を落とすだけ。⛔旧表が正本のまま残っているので情報は消えない。
-- =====================================================================
begin;
drop table if exists public.nar_runs_p cascade;
commit;
-- そのあと必ず: select count(*) from public.nar_runs;  ← 00_baseline_counts.sql の控えと一致すること

-- =====================================================================
-- 段 C) §3 の途中(旧表から delete を始めた・まだ attach していない)
--   → ⛔ここが一番危ない段。旧表に無い行は「親にだけある」。親から旧表へ戻してから親を落とす。
--   ⛔順番を逆にすると(親を先に落とすと)消えた行が本当に消える。
-- =====================================================================
-- C-1 まず何行ずつあるか見る(⛔読みだけ)
select (select count(*) from public.nar_runs   where race_date >= '2022-11-01') as old_move,
       (select count(*) from public.nar_runs_p)                                 as new_rows;

-- C-2 旧表に付けた check を外す(check があると 2022-11 以降を戻せない)
begin;
set local lock_timeout = '10s';
alter table public.nar_runs drop constraint if exists nar_runs_archive_ck;
commit;

-- C-3 親にあって旧表に無い行を戻す(年ごと・1 年 1 トランザクション)
--   ⛔`on conflict do nothing` = 旧表に残っている行は上書きしない(delete の途中で止まった年は
--   両方に同じ行があるため)。
begin;
set local statement_timeout = '30min';
insert into public.nar_runs select * from public.nar_runs_p
 where race_date >= '2022-11-01' and race_date < '2023-01-01'
on conflict (track, race_date, race_no, runner_number) do nothing;
commit;
-- 以下 2023 / 2024 / 2025 / 2026 / 2027 以降も同じ形で 1 年ずつ(⛔範囲だけ書き換えて流す)

-- C-4 突き合わせ(⛔控えと一致してから C-5)
select count(*) from public.nar_runs;

-- C-5 親を落とす
begin;
drop table if exists public.nar_runs_p cascade;
commit;
vacuum (analyze) public.nar_runs;

-- =====================================================================
-- 段 D) §3-5 の attach 済み・§4 の rename はまだ
--   → detach してから親を落とす。detach したあと旧表は元の名前(nar_runs)のまま単独の表に戻る。
-- =====================================================================
begin;
set local lock_timeout = '10s';
alter table public.nar_runs_p detach partition public.nar_runs;
commit;
-- ⛔detach で旧表の索引は親から切り離される(索引そのものは残る)。
-- そのあと 段 C-2 〜 C-5 を同じ順で流す(check を外す → 行を戻す → 親を落とす)。

-- =====================================================================
-- 段 E) §4 の rename 直後(⛔ここは一番楽= 名前を戻すだけ・数ミリ秒)
--   画面が変なら、まずこれを流して元の姿に戻す。データは 1 行も動かさない。
-- =====================================================================
begin;
set local lock_timeout = '5s';
alter table public.nar_runs               rename to nar_runs_p;
alter table public.nar_runs_archive_part  rename to nar_runs;
commit;
notify pgrst, 'reload schema';
-- ⛔この時点では 2022-11 以降の行が親(nar_runs_p)側にしか無い= 旧表に戻しただけでは
--   今年のデータが**見えない**。だから段 E は「画面の様子を見るための一時的な退避」で、
--   直したうえで §4 をもう一度流すか、段 D → 段 C で完全に戻すかを決める。
--   ⛔「段 E で止めたまま朝を迎える」はしない(今年の行が見えない状態で客が来る)。

-- =====================================================================
-- 段 F) §5 の grant/policy だけ間に合っていない(行は全部そろっている)
--   → 巻き戻さない。50_… の §5 を流し直す(何度流しても同じ結果になるよう
--   `create policy` は先に drop してから)。
-- =====================================================================
begin;
drop policy if exists nar_runs_part_read on public.nar_runs_2026;
create policy nar_runs_part_read on public.nar_runs_2026
  for select to anon, authenticated using (true);
grant select on public.nar_runs_2026 to anon, authenticated;
commit;
notify pgrst, 'reload schema';

-- =====================================================================
-- 最後に(どの段でも)
-- =====================================================================
notify pgrst, 'reload schema';
-- そのあと 99_verify.sql の 2) と 5) を流して、行数と匿名キーでの読みを確かめる。
