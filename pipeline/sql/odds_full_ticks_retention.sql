-- §132 全券種 全点の保持(2026-09-08・Fable)。単複の odds_ticks_retention.sql と同じ規則:
--   60 日は全点。それより古いレースは 6 点(最初・最終・発走 30/20/10/5 分前に一番近い回)だけ残す。
-- ⚠残す 6 点×7 券種でも 1 レース約 80 KB= 年 1.3 GB 弱。減らすなら values の行を削る(ユーザー判断・#533)。
-- 適用: psql … -f pipeline/sql/odds_full_ticks_retention.sql(nar-jobs nar-refresh.yml monthly・単複の保持の直後)
\set ON_ERROR_STOP on
with old as (
  select t.id, t.track, t.race_date, t.race_no, t.kind, t.observed_at, t.f,
         case when r.post_time ~ '^\d{4}$'
              then (substr(r.post_time,1,2)::int*60 + substr(r.post_time,3,2)::int)
                   - (extract(hour from t.observed_at at time zone 'Asia/Tokyo')::int*60
                      + extract(minute from t.observed_at at time zone 'Asia/Tokyo')::int)
              else null end as before_min,
         row_number() over (partition by t.track, t.race_date, t.race_no, t.kind order by t.observed_at asc, t.id asc) as rn_first,
         row_number() over (partition by t.track, t.race_date, t.race_no, t.kind order by t.f desc, t.observed_at desc, t.id desc) as rn_last
  from public.nar_odds_full_ticks t
  left join public.nar_races r using (track, race_date, race_no)
  where t.race_date < current_date - 60
),
near as (
  select id from (
    select o.id, m.m, row_number() over (partition by o.track, o.race_date, o.race_no, o.kind, m.m order by abs(o.before_min - m.m), o.id) as rk
    from old o cross join (values (30),(20),(10),(5)) as m(m)
    where o.before_min is not null
  ) x where rk = 1
),
keep as (
  select id from old where rn_first = 1 or rn_last = 1
  union select id from near
),
del as (
  delete from public.nar_odds_full_ticks t using old o
  where t.id = o.id and o.id not in (select id from keep)
  returning t.id
)
select count(*) as deleted_full_ticks from del;
