-- 監査 #21 案 乙(2026-09-23): 同名表 nar_meta 'horse_homonyms'(馬名の配列)を全期間から作る。
-- ⛔本番 DB で手元から流さない= Actions 便 horse-homonyms.yml が psql で流す(nar_runs 全表を 1 回走査)。
-- 「同名」= 同じ馬名で生年が 2 つ以上、かつ生年の群どうしの走った期間(最初〜最後の開催日)が重ならない群が 2 つ以上
--   (同じ馬名の登録は同時期に 2 頭いない= 重なる群は馬齢の書き誤りで割れた同じ馬として畳む)。生年= 生年月日の年、無ければ 開催年 − 馬齢(日本の馬齢は 1/1 加算)。
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
       min(race_date) as first_d, max(race_date) as last_d
from public.nar_runs
where horse_name is not null and (birth_date is not null or age > 0)
group by 1, 2;

create temp table s21_homonyms as
with mg as (
  select coalesce((select value from public.nar_meta where key = 'horse_homonym_merge'), '{}'::jsonb) as v
), g as (
  select y.horse_name, y.first_d, y.last_d,
         coalesce((select min(e::int)
                   from jsonb_array_elements(case when jsonb_typeof(mg.v -> y.horse_name) = 'array'
                                                  then mg.v -> y.horse_name else '[]'::jsonb end) grp
                   cross join lateral jsonb_array_elements_text(case when jsonb_typeof(grp) = 'array'
                                                                     then grp else '[]'::jsonb end) e
                   where grp @> to_jsonb(y.by)), y.by) as grp_year
  from s21_years y cross join mg
  where y.by is not null
)
), gy as (                                   -- 束ねたあとの群ごとの期間
  select horse_name, grp_year, min(first_d) as first_d, max(last_d) as last_d
  from g group by horse_name, grp_year
), c as (                                    -- 開始順に並べ、前の群までの最後より後に始まる群= 新しい馬
  select horse_name, first_d,
         max(last_d) over (partition by horse_name order by first_d, last_d
                           rows between unbounded preceding and 1 preceding) as prev_end
  from gy
)
select horse_name from c group by horse_name
having 1 + count(*) filter (where prev_end is not null and first_d > prev_end) >= 2;

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
