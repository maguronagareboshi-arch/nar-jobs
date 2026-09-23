-- 監査 #21 案 乙(2026-09-23): 同名表 nar_meta 'horse_homonyms'(馬名の配列)を全期間から作る。
-- ⛔本番 DB で手元から流さない= Actions 便 horse-homonyms.yml が psql で流す(nar_runs 全表を 1 回走査)。
-- 「同名」= 同じ馬名で生年が 2 つ以上、かつ生年の群どうしの走った期間(最初〜最後の開催日)が重ならない群が 2 つ以上
--   (同じ馬名の登録は同時期に 2 頭いない= 重なる群は馬齢の書き誤りで割れた同じ馬として畳む)。
--   ただし「一方がばんえい(帯広)・他方が平地」「両群とも生年月日があって値が違う」なら重なっても束ねない(viewer と同じ)。生年= 生年月日の年、無ければ 開催年 − 馬齢(日本の馬齢は 1/1 加算)。
-- nar_meta 'horse_homonym_merge'(手で持つ束ね表・無ければ空)= {"<馬名>": [[2019, 2020], ...]} の内側 1 つを同じ馬として畳む。
-- psql -v apply=true のときだけ nar_meta へ書く(既定は数を出すだけ)。
\set ON_ERROR_STOP 1
\if :{?apply}
\else
\set apply false
\endif
\timing on
set statement_timeout = 0;

create temp table s21_years as
select horse_name,
       coalesce(extract(year from birth_date)::int, extract(year from race_date)::int - age) as by,
       coalesce(track like '帯広%', false) as banei,
       min(race_date) as first_d, max(race_date) as last_d,
       min(birth_date) as bd_min, max(birth_date) as bd_max
from public.nar_runs
where horse_name is not null and (birth_date is not null or age > 0)
group by 1, 2, 3;

-- 群= (馬名, 束ねたあとの生年, ばんえいか)。群が 2 つ以上の馬名だけ残す(以下は数千行の小さい表)
create temp table s21_groups as
with mg as (
  select coalesce((select value from public.nar_meta where key = 'horse_homonym_merge'), '{}'::jsonb) as v
), g as (
  select y.horse_name, y.banei, y.first_d, y.last_d, y.bd_min, y.bd_max,
         coalesce((select min(e::int)
                   from jsonb_array_elements(case when jsonb_typeof(mg.v -> y.horse_name) = 'array'
                                                  then mg.v -> y.horse_name else '[]'::jsonb end) grp
                   cross join lateral jsonb_array_elements_text(case when jsonb_typeof(grp) = 'array'
                                                                     then grp else '[]'::jsonb end) e
                   where grp @> to_jsonb(y.by)), y.by) as grp_year
  from s21_years y cross join mg
  where y.by is not null
), gy as (
  select horse_name, grp_year, banei, min(first_d) as first_d, max(last_d) as last_d,
         min(bd_min) as bd_min, max(bd_max) as bd_max, count(*) over (partition by horse_name) as n
  from g group by horse_name, grp_year, banei
)
select row_number() over () as id, horse_name, grp_year, banei, first_d, last_d, bd_min, bd_max
from gy where n >= 2;

-- 同じ馬とみなす辺: 走った期間が重なる(同じ馬名の登録は同時期に 2 頭いない= 馬齢の書き誤りで割れた)。
-- ただし束ねない: 一方がばんえい(帯広)・他方が平地 / 両群とも生年月日があって値が違う
--   (viewer dry-run: オトコギ・シンドラー・タカラシップはばんえいと平地で同時期に走る別馬)
create temp table s21_edges as
select a.id as a, b.id as b
from s21_groups a join s21_groups b
  on a.horse_name = b.horse_name and a.id <> b.id and a.banei = b.banei
 and a.first_d <= b.last_d and b.first_d <= a.last_d
 and not (a.bd_min is not null and b.bd_min is not null
          and (a.bd_min, a.bd_max) is distinct from (b.bd_min, b.bd_max));

-- 辺でつながる群を 1 頭にまとめ、別の馬が 2 頭以上の馬名= 同名
create temp table s21_homonyms as
with recursive r(id, root) as (
  select id, id from s21_groups
  union
  select e.b, r.root from r join s21_edges e on e.a = r.id
), comp as (
  select id, min(root) as root from r group by id
)
select g.horse_name from comp c join s21_groups g using (id)
group by g.horse_name having count(distinct c.root) >= 2;

select count(*) as homonym_names from s21_homonyms;
select horse_name from s21_homonyms order by horse_name limit 20;

\if :apply
insert into public.nar_meta (key, value, updated_at)
select 'horse_homonyms', coalesce(jsonb_agg(horse_name order by horse_name), '[]'::jsonb), now()
from s21_homonyms
on conflict (key) do update set value = excluded.value, updated_at = excluded.updated_at;
select jsonb_array_length(value) as written from public.nar_meta where key = 'horse_homonyms';
\else
\echo 'dry-run: nar_meta へは書かない(confirm に apply と打つと書く)'
\endif
