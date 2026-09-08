-- §77 W4(2026-09-04): nar_odds_ticks の保持。60 日を過ぎたレースは 1 レース 6 点だけ残す(冪等・monthly 05:33 便で psql)。
--   残す 6 点= 初回 / 発走 30 分前・20 分前・10 分前・5 分前 に最も近い点 / 最終(f=true があればそれ・無ければ最後の点)。
--   ⛔60 日以内は全点(2 分刻み・約 20 点/レース)。画面(odds-series.js の節目表 初回/30分前/10分前/最終)は薄めた後も同じ点を引ける。
--   ⛔発走時刻(nar_races.post_time HHMM)が無いレースは「初回・最終」以外を決められないので、初回と最終だけ残す。
-- 適用: psql … -f pipeline/sql/odds_ticks_retention.sql(nar-refresh.yml monthly の venue stats と同じ段)
\set ON_ERROR_STOP on
with old as (
  select t.id, t.track, t.race_date, t.race_no, t.t, t.f,
         case when r.post_time ~ '^\d{4}$'
              then (substr(r.post_time,1,2)::int*60 + substr(r.post_time,3,2)::int)
                   - (split_part(t.t,':',1)::int*60 + split_part(t.t,':',2)::int)
              else null end as before_min,
         row_number() over (partition by t.track, t.race_date, t.race_no order by t.t asc, t.id asc) as rn_first,
         row_number() over (partition by t.track, t.race_date, t.race_no order by t.f desc, t.t desc, t.id desc) as rn_last
  from public.nar_odds_ticks t
  left join public.nar_races r using (track, race_date, race_no)
  where t.race_date < current_date - 60
),
near as (
  select id from (
    select o.id, m.m, row_number() over (partition by o.track, o.race_date, o.race_no, m.m order by abs(o.before_min - m.m), o.id) as rk
    from old o cross join (values (30),(20),(10),(5)) as m(m)
    where o.before_min is not null
  ) x where rk = 1
),
keep as (
  select id from old where rn_first = 1 or rn_last = 1
  union select id from near
),
del as (
  delete from public.nar_odds_ticks t using old o
  where t.id = o.id and o.id not in (select id from keep)
  returning t.id
)
select count(*) as deleted_ticks from del;
