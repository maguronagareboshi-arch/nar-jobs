-- nar_horses の first_date・last_date・runs と nar_horse_profiles の first_seen・last_seen を nar_runs から数え直す(2026-10-17)。
--   8/23 の分離で一度だけ SQL で埋め、以後どの便も書いていなかった(8/27 で止まり・新馬 1,033 頭は空)。
--   ⛔nar_horses の列は変えない(AI 便の \copy が列を名指し)。値だけ直す。updated_at は触らない(属性の更新時刻のまま)。
--   数え方= 8/23 と同じ「その馬名の nar_runs の行を全部」(取消・除外も 1)。ただし JST 今日より先の出馬表は数えない。
--   profiles は (馬名, 生年) を nar_runs.birth_date で結ぶ。
--   対象= 直近 :days 日に走った馬 ＋ 馬名の hash で :parts 組に分けた :part 番の馬
--         (朝の便が日替わりで 1 組ずつ回す= 古い走りを後から足したときも :parts 日で行き渡る)。
--   psql -v days=3 -v parts=30 -v part=<0..parts-1> -v apply=1 -f pipeline/sql/horse_dates.sql
--   apply=0 は数えるだけ(最後に rollback)。
\set ON_ERROR_STOP on
begin;
set local statement_timeout = '180s';

create temp table tmp_hd_names on commit drop as
select distinct horse_name from public.nar_runs
 where race_date >= (now() at time zone 'Asia/Tokyo')::date - :days
   and race_date <= (now() at time zone 'Asia/Tokyo')::date
union
select horse_name from public.nar_horses
 where ((hashtext(horse_name)::bigint % :parts) + :parts) % :parts = :part;

create temp table tmp_hd on commit drop as
select n.horse_name, x.f, x.l, x.c
from tmp_hd_names n
cross join lateral (
  select min(r.race_date) as f, max(r.race_date) as l, count(*)::int as c
  from public.nar_runs r
  where r.horse_name = n.horse_name and r.race_date <= (now() at time zone 'Asia/Tokyo')::date
) x
where x.c > 0;

create temp table tmp_hp on commit drop as
select p.horse_name, p.birth_date, x.f, x.l
from public.nar_horse_profiles p
join tmp_hd_names n on n.horse_name = p.horse_name
cross join lateral (
  select min(r.race_date) as f, max(r.race_date) as l
  from public.nar_runs r
  where r.horse_name = p.horse_name and r.birth_date = p.birth_date
    and r.race_date <= (now() at time zone 'Asia/Tokyo')::date
) x
where x.l is not null;

with u as (
  update public.nar_horses h set first_date = t.f, last_date = t.l, runs = t.c
  from tmp_hd t
  where h.horse_name = t.horse_name
    and (h.first_date, h.last_date, h.runs) is distinct from (t.f, t.l, t.c)
  returning 1
), v as (
  update public.nar_horse_profiles p set first_seen = t.f, last_seen = t.l
  from tmp_hp t
  where p.horse_name = t.horse_name and p.birth_date = t.birth_date
    and (p.first_seen, p.last_seen) is distinct from (t.f, t.l)
  returning 1
)
select :part as part, (select count(*) from tmp_hd_names) as names,
       (select count(*) from u) as horses_changed, (select count(*) from v) as profiles_changed;

\if :apply
commit;
\else
rollback;
\endif
