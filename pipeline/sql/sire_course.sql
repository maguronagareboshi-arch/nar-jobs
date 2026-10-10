-- §18 父の成績= この場×この距離×同じ馬場・そのレースの前日まで 10 年(2026-10-10)。レースごとの写し nar_sire_course を作る。
-- ⛔nar-stats(stats_local.py run)の手元 Postgres だけで流す。本番の器は sire_course_table_20261010.sql。
-- 仕様(nar-site research/sire-venue-dist-going/spec-impl.md):
--   対象= 2025-10-10 以降のレース(帯広を除く・出馬表のある日まで)。窓= race_date - 10 年 <= d < race_date・地方の走だけ。
--   「走った」= 着順あり or 競走中止・失格(person_stats.sql と同じ)。父= nar_horses.sire を馬名で結合。
--   発走前(今日以降で着順が 1 頭も無い)= 4 馬場+'*'・終わった= 実際の going+'*'(going が 4 語でなければ '*' だけ)。
--   umaban 0 = 父を問わない全馬(父の引けない走も含む)。
-- 作り方= (場, 距離, 父, 馬場, 日) の日別合計を累積し、「前日までの累積 − 10 年前の前日までの累積」を索引 2 回で引く。
set statement_timeout = '30min';

create table if not exists public.nar_sire_course (
  track text not null, race_date date not null, race_no int not null, umaban int not null, going text not null,
  sire text, n int not null, w1 int not null, w2 int not null, w3 int not null, roi int, roi3 int,
  updated_at timestamptz not null default now(),
  primary key (track, race_date, race_no, umaban, going)
);

-- 対象のレース
drop table if exists tmp_sc_race;
create temp table tmp_sc_race as
select r.track, r.race_date, r.race_no, r.distance_m, r.going,
       (r.race_date < current_date or exists (
          select 1 from public.nar_runs u where u.track = r.track and u.race_date = r.race_date and u.race_no = r.race_no
            and (u.finish > 0 or u.finish_note in ('競走中止', '失格')))) as done
from public.nar_races r
where r.race_date >= date '2025-10-10' and r.track not like '帯広%' and r.distance_m > 0;

-- 窓の中に入りうる走(対象の最古日の 10 年前から)
drop table if exists tmp_sc_run;
create temp table tmp_sc_run as
select r.track, r.distance_m, r.race_date, r.going, h.sire, u.finish,
       case when u.finish = 1 then coalesce((
         select (p->>'y')::int from jsonb_array_elements(rp.payouts) p
         where p->>'t' = 'win' and p->>'c' = u.runner_number::text limit 1), 0) else 0 end as win_pay,
       case when u.finish between 1 and 3 then coalesce((
         select (p->>'y')::int from jsonb_array_elements(rp.payouts) p
         where p->>'t' = 'place' and p->>'c' = u.runner_number::text limit 1), 0) else 0 end as place_pay
from public.nar_runs u
join public.nar_races r on r.track = u.track and r.race_date = u.race_date and r.race_no = u.race_no
left join public.nar_race_payouts rp on rp.track = u.track and rp.race_date = u.race_date and rp.race_no = u.race_no
left join public.nar_horses h on h.horse_name = u.horse_name and h.sire <> ''
where (u.finish > 0 or u.finish_note in ('競走中止', '失格'))
  and r.race_date >= (date '2025-10-10' - interval '10 years')::date and r.track not like '帯広%' and r.distance_m > 0;

-- 日別合計(父 '*'= 全馬・馬場 '*'= 馬場問わず)
drop table if exists tmp_sc_day;
create temp table tmp_sc_day as
select track, distance_m, race_date,
       case when grouping(sire) = 1 then '*' else sire end as s,
       case when grouping(going) = 1 then '*' else going end as g,
       count(*) as n, count(*) filter (where finish = 1) as w1, count(*) filter (where finish = 2) as w2,
       count(*) filter (where finish = 3) as w3, sum(win_pay) as wp, sum(place_pay) as pp
from tmp_sc_run
group by grouping sets ((track, distance_m, race_date, sire, going), (track, distance_m, race_date, sire),
                        (track, distance_m, race_date, going), (track, distance_m, race_date))
having (grouping(sire) = 1 or sire is not null) and (grouping(going) = 1 or going in ('良', '稍重', '重', '不良'));

-- 累積(1 鍵 1 日 1 行なので既定の窓枠で足りる)+ 父×場×距離×馬場×日付の索引
drop table if exists tmp_sc_cum;
create temp table tmp_sc_cum as
select track, distance_m, s, g, race_date,
       sum(n) over w as cn, sum(w1) over w as cw1, sum(w2) over w as cw2, sum(w3) over w as cw3,
       sum(wp) over w as cwp, sum(pp) over w as cpp
from tmp_sc_day
window w as (partition by track, distance_m, s, g order by race_date);
create index on tmp_sc_cum (track, distance_m, s, g, race_date);
analyze tmp_sc_cum;

-- 書く行(馬ごと+umaban 0)× 馬場
drop table if exists tmp_sc_t;
create temp table tmp_sc_t as
with gs as (
  select t.*, gg.g from tmp_sc_race t
  cross join lateral unnest(case when not t.done then array['良', '稍重', '重', '不良', '*']
                                 when t.going in ('良', '稍重', '重', '不良') then array[t.going, '*']
                                 else array['*'] end) as gg(g))
select gs.track, gs.race_date, gs.race_no, gs.distance_m, u.runner_number as umaban, h.sire as s, gs.g
from gs
join public.nar_runs u on u.track = gs.track and u.race_date = gs.race_date and u.race_no = gs.race_no
join public.nar_horses h on h.horse_name = u.horse_name and h.sire is not null and h.sire <> ''
union all
select gs.track, gs.race_date, gs.race_no, gs.distance_m, 0, '*', gs.g from gs;

truncate public.nar_sire_course;
insert into public.nar_sire_course (track, race_date, race_no, umaban, going, sire, n, w1, w2, w3, roi, roi3)
select t.track, t.race_date, t.race_no, t.umaban, t.g, t.s,
       x.n, x.w1, x.w2, x.w3,
       round(x.wp::numeric / nullif(x.n, 0))::int, round(x.pp::numeric / nullif(x.n, 0))::int
from tmp_sc_t t
left join lateral (select cn, cw1, cw2, cw3, cwp, cpp from tmp_sc_cum c
                   where c.track = t.track and c.distance_m = t.distance_m and c.s = t.s and c.g = t.g
                     and c.race_date < t.race_date order by c.race_date desc limit 1) a on true
left join lateral (select cn, cw1, cw2, cw3, cwp, cpp from tmp_sc_cum c
                   where c.track = t.track and c.distance_m = t.distance_m and c.s = t.s and c.g = t.g
                     and c.race_date < (t.race_date - interval '10 years')::date order by c.race_date desc limit 1) b on true
cross join lateral (select (coalesce(a.cn, 0) - coalesce(b.cn, 0))::int as n, (coalesce(a.cw1, 0) - coalesce(b.cw1, 0))::int as w1,
                           (coalesce(a.cw2, 0) - coalesce(b.cw2, 0))::int as w2, (coalesce(a.cw3, 0) - coalesce(b.cw3, 0))::int as w3,
                           coalesce(a.cwp, 0) - coalesce(b.cwp, 0) as wp, coalesce(a.cpp, 0) - coalesce(b.cpp, 0) as pp) x;
analyze public.nar_sire_course;

-- 検査(ログの末尾に出る): ① 抜き取り 300 行を走から直に数え直して違う行数(窓= 前日まで 10 年)
--   ② 同じ 300 行で「当日以降の走」を窓に入れたら数が変わる行数(参考・0 でなくてよい)③ 行数 ④ 見本 高知 2026-10-10 8R
select '検査 ① 直に数え直して違う行 ' || count(*) filter (where s.n <> d.n or s.w1 <> d.w1 or s.w3 <> d.w3)
       || ' / ' || count(*) || '  ② 当日以降を入れたら変わる行 ' || count(*) filter (where d.n <> d.n_incl)
from (select * from public.nar_sire_course order by md5(track || race_date || race_no || umaban || going) limit 300) s
join tmp_sc_race t using (track, race_date, race_no)
cross join lateral (
  select count(*) filter (where u.race_date < s.race_date) as n,
         count(*) filter (where u.race_date < s.race_date and u.finish = 1) as w1,
         count(*) filter (where u.race_date < s.race_date and u.finish = 3) as w3,
         count(*) as n_incl
  from tmp_sc_run u
  where u.track = s.track and u.distance_m = t.distance_m
    and u.race_date >= (s.race_date - interval '10 years')::date
    and (s.sire = '*' or u.sire = s.sire) and (s.going = '*' or u.going = s.going)) d;
select '行数 ' || count(*) || '  レース ' || count(distinct (track, race_date, race_no))
       || '  馬場5つのレース ' || (select count(*) from (select 1 from public.nar_sire_course where umaban = 0 group by track, race_date, race_no having count(*) = 5) q)
       || '  n=0 の行 ' || count(*) filter (where n = 0) || '  窓の最古 ' || min(race_date)
from public.nar_sire_course c;
select '見本 高知 2026-10-10 8R ' || going || ': ' || string_agg(umaban || ' ' || sire || ' ' || n || '/' || w1 || '/' || w2 || '/' || w3 || '/' || coalesce(roi, -1) || '/' || coalesce(roi3, -1), '  ' order by umaban)
from public.nar_sire_course where track = '高知' and race_date = date '2026-10-10' and race_no = 8 and going in ('良', '*')
group by going;
