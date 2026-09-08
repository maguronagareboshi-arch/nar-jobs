-- 競馬場ごとの「データルーム」集計(2026-08-23 新設)。
-- 公式データ(nar_races / nar_runs / nar_horses / nar_race_payouts)から、場×期間ごとに 1 行の JSON を作る。
-- 毎日 1 回(月次更新の後)psql で流す。何度流しても同じ結果(全面作り直し)。所要 数十秒。
-- 期間 = 'all'(2022-11〜) / 当年 / 前年。
-- §62 B7-1: 出走数は**取消・除外だけ**を除く(**競走中止・失格は「走った」として数える**= didRun と同じ)。
-- 単勝回収率 = その馬が1着のときの単勝払戻(100円あたり)の合計 ÷ (出走数×100)。

set statement_timeout = '30min';

create table if not exists public.nar_venue_stats (
  track      text not null,
  period     text not null,          -- 'all' | 'YYYY'
  stats      jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (track, period)
);
alter table public.nar_venue_stats enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_venue_stats' and policyname = 'nar_venue_stats_read') then
    create policy nar_venue_stats_read on public.nar_venue_stats for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_venue_stats to anon, authenticated;

-- 1 走 = 1 行の作業表(出走した馬だけ・単勝払戻を 1 着馬に付ける)
drop table if exists tmp_runs;
create temp table tmp_runs as
select r.track, r.race_date, r.race_no, r.distance_m, r.going, r.surface, r.race_name,
       extract(year from r.race_date)::int as yr,
       u.runner_number, u.gate, u.horse_name, u.jockey, u.trainer, u.finish, u.time_sec, u.popularity, u.last3f,
       h.sire,
       case when u.finish = 1 then coalesce((
         select (p->>'y')::int from jsonb_array_elements(rp.payouts) p
         where p->>'t' = 'win' and p->>'c' = u.runner_number::text limit 1), 0) else 0 end as win_pay
from public.nar_runs u
join public.nar_races r on r.track = u.track and r.race_date = u.race_date and r.race_no = u.race_no
left join public.nar_horses h on h.horse_name = u.horse_name
left join public.nar_race_payouts rp on rp.track = u.track and rp.race_date = u.race_date and rp.race_no = u.race_no
-- §62 B7-1 「走った」= 着順あり or 競走中止・失格(js/data.js の didRun / RAN_NOTES と同じ規則)。
-- ⛔定義はサイト全体で1つ(#262 と同じ病気を3つ目に残さない)。
-- ⛔「競走取止め」(レース不成立)は**走っていない**ので入れない= それは margin 列にあり finish_note には無い(#267)
where (u.finish > 0 or u.finish_note in ('競走中止', '失格')) and r.race_date <= current_date;
create index on tmp_runs (track, yr);
create index on tmp_runs (track, race_date, race_no);

-- レースごとの「1番人気が勝ったか」(払戻集計で使う。走ごとの表を毎レース走査しないため)
drop table if exists tmp_fav;
create temp table tmp_fav as
select track, race_date, race_no, bool_or(popularity = 1 and finish = 1) as fav_won
from tmp_runs group by 1, 2, 3;
create index on tmp_fav (track, race_date, race_no);

-- 期間の定義
drop table if exists tmp_periods;
create temp table tmp_periods as
select 'all'::text as period, 1900 as y_from, 2999 as y_to
union all select extract(year from current_date)::int::text, extract(year from current_date)::int, extract(year from current_date)::int
union all select (extract(year from current_date)::int - 1)::text, extract(year from current_date)::int - 1, extract(year from current_date)::int - 1;

-- 集計本体
create or replace function pg_temp.rank_block(p_track text, p_from int, p_to int, p_key text, p_min int)
returns jsonb language sql as $$
  with g as (
    select case p_key when 'jockey' then jockey when 'trainer' then trainer when 'sire' then sire
                      when 'gate' then gate::text when 'popularity' then least(popularity, 10)::text end as k,
           count(*) as n,
           count(*) filter (where finish = 1) as w1,
           count(*) filter (where finish = 2) as w2,
           count(*) filter (where finish = 3) as w3,
           sum(win_pay) as pay
    from tmp_runs where track = p_track and yr between p_from and p_to
    group by 1
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'name', k, 'n', n, 'w1', w1, 'w2', w2, 'w3', w3,
           'win', round(100.0 * w1 / n, 1), 'top2', round(100.0 * (w1 + w2) / n, 1), 'top3', round(100.0 * (w1 + w2 + w3) / n, 1),
           'roi', round(100.0 * pay / (n * 100.0), 0))
         order by (case when p_key in ('gate', 'popularity') then (k)::numeric else null end), w1 desc, n desc), '[]'::jsonb)
  from g where k is not null and k <> '' and n >= p_min
$$;

delete from public.nar_venue_stats;
insert into public.nar_venue_stats (track, period, stats, updated_at)
select t.track, p.period,
  jsonb_build_object(
    'races', (select count(distinct (race_date, race_no)) from tmp_runs x where x.track = t.track and x.yr between p.y_from and p.y_to),
    'runs', (select count(*) from tmp_runs x where x.track = t.track and x.yr between p.y_from and p.y_to),
    'from', (select min(race_date) from tmp_runs x where x.track = t.track and x.yr between p.y_from and p.y_to),
    'to', (select max(race_date) from tmp_runs x where x.track = t.track and x.yr between p.y_from and p.y_to),
    'jockeys', (select jsonb_path_query_array(pg_temp.rank_block(t.track, p.y_from, p.y_to, 'jockey', 10), '$[0 to 29]')),
    'trainers', (select jsonb_path_query_array(pg_temp.rank_block(t.track, p.y_from, p.y_to, 'trainer', 10), '$[0 to 29]')),
    'sires', (select jsonb_path_query_array(pg_temp.rank_block(t.track, p.y_from, p.y_to, 'sire', 10), '$[0 to 19]')),
    'gates', pg_temp.rank_block(t.track, p.y_from, p.y_to, 'gate', 1),
    'popularity', pg_temp.rank_block(t.track, p.y_from, p.y_to, 'popularity', 1),
    -- §39.3: record_going(期間内最速時の馬場)と alltime(期間タブに関わらず全期間のレコード+馬場)を追加(2026-08-27)
    'distances', (
      select coalesce(jsonb_agg(jsonb_build_object('distance', d.distance_m, 'races', d.races, 'avg_win', d.avg_win,
                 'record', d.rec, 'record_horse', d.rec_horse, 'record_date', d.rec_date, 'record_going', d.rec_going,
                 'alltime', (select jsonb_build_object('record', min(a.time_sec),
                               'horse', (array_agg(a.horse_name order by a.time_sec))[1],
                               'date',  (array_agg(a.race_date  order by a.time_sec))[1],
                               'going', (array_agg(a.going      order by a.time_sec))[1])
                             from tmp_runs a where a.track = t.track and a.distance_m = d.distance_m
                               and a.finish = 1 and a.time_sec is not null)
               ) order by d.distance_m), '[]'::jsonb)
      from (
        select distance_m, count(*) as races, round(avg(time_sec)::numeric, 1) as avg_win, min(time_sec) as rec,
               (array_agg(horse_name order by time_sec))[1] as rec_horse, (array_agg(race_date order by time_sec))[1] as rec_date,
               (array_agg(going order by time_sec))[1] as rec_going
        from tmp_runs x where x.track = t.track and x.yr between p.y_from and p.y_to and finish = 1 and time_sec is not null and distance_m is not null
        group by distance_m having count(*) >= 5
      ) d),
    -- §39.2: 距離×種牡馬(上位10・出走5以上)と 距離×枠番。チップ切替は取得済みJSON内=通信増ゼロ
    'sires_by_distance', (
      select coalesce(jsonb_agg(jsonb_build_object('distance', distance_m, 'sires', sires) order by distance_m), '[]'::jsonb)
      from (
        select distance_m,
               jsonb_agg(jsonb_build_object('name', sire, 'n', n, 'w1', w1,
                 'win', round(100.0 * w1 / n, 1), 'top3', round(100.0 * w123 / n, 1),
                 'roi', round(100.0 * pay / (n * 100.0), 0)) order by w1 desc, n desc) filter (where rn <= 10) as sires
        from (
          select distance_m, sire, count(*) as n,
                 count(*) filter (where finish = 1) as w1,
                 count(*) filter (where finish <= 3) as w123,
                 sum(win_pay) as pay,
                 row_number() over (partition by distance_m
                                    order by count(*) filter (where finish = 1) desc, count(*) desc) as rn
          from tmp_runs x
          where x.track = t.track and x.yr between p.y_from and p.y_to
            and sire is not null and sire <> '' and distance_m is not null
          group by distance_m, sire having count(*) >= 5
        ) s group by distance_m
      ) sd where sires is not null),
    'gates_by_distance', (
      select coalesce(jsonb_agg(jsonb_build_object('distance', distance_m, 'gates', gates) order by distance_m), '[]'::jsonb)
      from (
        select distance_m,
               jsonb_agg(jsonb_build_object('gate', gate, 'n', n, 'w1', w1,
                 'win', round(100.0 * w1 / n, 1), 'top3', round(100.0 * w123 / n, 1),
                 'roi', round(100.0 * pay / (n * 100.0), 0)) order by gate) as gates
        from (
          select distance_m, gate, count(*) as n,
                 count(*) filter (where finish = 1) as w1,
                 count(*) filter (where finish <= 3) as w123,
                 sum(win_pay) as pay
          from tmp_runs x
          where x.track = t.track and x.yr between p.y_from and p.y_to
            and gate is not null and distance_m is not null
          group by distance_m, gate having count(*) >= 5
        ) g group by distance_m
      ) gd2),
    -- §30: 馬場状態×距離の勝ち時計(平均と最速)。「不良の1400mはどれくらい速い?」に答える(ユーザー要望 2026-08-26)
    'going_distance', (
      select coalesce(jsonb_agg(jsonb_build_object('going', going, 'distance', distance_m, 'races', races,
                                                   'avg_win', avg_win, 'best', best) order by distance_m, going), '[]'::jsonb)
      from (
        select going, distance_m, count(*) as races, round(avg(time_sec)::numeric, 1) as avg_win, min(time_sec) as best
        from tmp_runs x where x.track = t.track and x.yr between p.y_from and p.y_to
          and finish = 1 and time_sec is not null and distance_m is not null and going is not null and going <> ''
        group by going, distance_m having count(*) >= 5
      ) gd),
    'going', (
      select coalesce(jsonb_agg(jsonb_build_object('going', going, 'races', races, 'fav_win', fav_win) order by races desc), '[]'::jsonb)
      from (
        select going, count(distinct (race_date, race_no)) as races,
               round(100.0 * count(*) filter (where popularity = 1 and finish = 1) / nullif(count(*) filter (where popularity = 1), 0), 1) as fav_win
        from tmp_runs x where x.track = t.track and x.yr between p.y_from and p.y_to and going is not null and going <> ''
        group by going
      ) g),
    'payouts', (
      select jsonb_build_object(
        'win_avg', round(avg(win_y)), 'trifecta_avg', round(avg(tri_y)), 'trifecta_max', max(tri_y),
        'manbaken_rate', round(100.0 * count(*) filter (where tri_y >= 10000) / nullif(count(*) filter (where tri_y is not null), 0), 1),
        'fav_win_rate', round(100.0 * count(*) filter (where fav_won) / nullif(count(*), 0), 1))
      from (
        select rp.track, rp.race_date, rp.race_no,
               (select min((q->>'y')::int) from jsonb_array_elements(rp.payouts) q where q->>'t' = 'win') as win_y,
               (select max((q->>'y')::int) from jsonb_array_elements(rp.payouts) q where q->>'t' = 'trifecta') as tri_y,
               coalesce(f.fav_won, false) as fav_won
        from public.nar_race_payouts rp
        left join tmp_fav f on f.track = rp.track and f.race_date = rp.race_date and f.race_no = rp.race_no
        where rp.track = t.track and extract(year from rp.race_date)::int between p.y_from and p.y_to
      ) pz),
    'records', (
      select jsonb_build_object(
        'max_win', (select jsonb_build_object('y', win_y, 'date', race_date, 'no', race_no) from (
           select rp.race_date, rp.race_no, (select max((q->>'y')::int) from jsonb_array_elements(rp.payouts) q where q->>'t' = 'win') as win_y
           from public.nar_race_payouts rp where rp.track = t.track and extract(year from rp.race_date)::int between p.y_from and p.y_to) w
           where win_y is not null order by win_y desc limit 1),
        'max_trifecta', (select jsonb_build_object('y', tri_y, 'date', race_date, 'no', race_no) from (
           select rp.race_date, rp.race_no, (select max((q->>'y')::int) from jsonb_array_elements(rp.payouts) q where q->>'t' = 'trifecta') as tri_y
           from public.nar_race_payouts rp where rp.track = t.track and extract(year from rp.race_date)::int between p.y_from and p.y_to) w
           where tri_y is not null order by tri_y desc limit 1))),
    'schedule', (
      select jsonb_build_object(
        'next', (select coalesce(jsonb_agg(d order by d), '[]'::jsonb) from (select distinct race_date as d from public.nar_races x where x.track = t.track and x.race_date >= current_date order by 1 limit 20) s),
        'recent', (select coalesce(jsonb_agg(d order by d desc), '[]'::jsonb) from (select distinct race_date as d from public.nar_races x where x.track = t.track and x.race_date < current_date order by 1 desc limit 10) s))
    )
  ) as stats, now()
from (select distinct track from public.nar_races) t
cross join tmp_periods p;

select track, period, pg_size_pretty(octet_length(stats::text)::bigint) as size,
       stats->>'races' as races, jsonb_array_length(stats->'jockeys') as jockeys
from public.nar_venue_stats order by track, period;
