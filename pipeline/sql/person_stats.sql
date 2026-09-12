-- 騎手・調教師ページ用の集計(2026-08-24 新設・DESIGN §14)。
-- 公式データ(nar_runs / nar_races / nar_race_payouts)から、(種別, 名前, 場, 期間) ごとに 1 行の JSON を作る。
-- 名前は公式データの略称(例 '山本聡')。場='all' の行には 場別内訳・距離別・直近30走 も入れる。
-- 毎日 1 回(venue_stats.sql の後)psql で流す。全面作り直し・冪等。所要 1 分前後。
set statement_timeout = '30min';

create table if not exists public.nar_person_stats (
  kind       text not null,             -- 'jockey' | 'trainer' | 'sire' | 'bms'(§105)
  name       text not null,             -- 公式の略称
  track      text not null,             -- 'all' | 公式場名('帯広ば' 含む)
  period     text not null,             -- 'all' | 'YYYY'
  stats      jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (kind, name, track, period)
);
create index if not exists nar_person_stats_name_idx on public.nar_person_stats (kind, name text_pattern_ops) where track = 'all' and period = 'all';
alter table public.nar_person_stats enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_person_stats' and policyname = 'nar_person_stats_read') then
    create policy nar_person_stats_read on public.nar_person_stats for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_person_stats to anon, authenticated;

-- 1 走 = 1 行の作業表(出走した馬だけ・単勝払戻を 1 着に付ける)
drop table if exists tmp_pr;
create temp table tmp_pr as
select r.track, r.race_date, r.race_no, r.distance_m, r.race_name, r.going,
       extract(year from r.race_date)::int as yr,
       u.runner_number, u.horse_name, u.jockey, u.trainer, u.finish, u.finish_note, u.popularity, u.time_sec,
       case when u.finish = 1 then coalesce((
         select (p->>'y')::int from jsonb_array_elements(rp.payouts) p
         where p->>'t' = 'win' and p->>'c' = u.runner_number::text limit 1), 0) else 0 end as win_pay,
       -- §156 F2 複勝払戻(3着内の馬に付ける・複回収用)。⛔無い回は 0
       case when u.finish between 1 and 3 then coalesce((
         select (p->>'y')::int from jsonb_array_elements(rp.payouts) p
         where p->>'t' = 'place' and p->>'c' = u.runner_number::text limit 1), 0) else 0 end as place_pay
from public.nar_runs u
join public.nar_races r on r.track = u.track and r.race_date = u.race_date and r.race_no = u.race_no
left join public.nar_race_payouts rp on rp.track = u.track and rp.race_date = u.race_date and rp.race_no = u.race_no
-- §62 B7-1 「走った」= 着順あり or 競走中止・失格(js/data.js の didRun / RAN_NOTES と同じ規則)。
-- ⛔定義はサイト全体で1つ(#262 と同じ病気を3つ目に残さない)。
-- ⛔「競走取止め」(レース不成立)は**走っていない**ので入れない= それは margin 列にあり finish_note には無い(#267)
where (u.finish > 0 or u.finish_note in ('競走中止', '失格')) and r.race_date <= current_date;
create index on tmp_pr (jockey, yr);
create index on tmp_pr (trainer, yr);

-- 種別ごとに名前列を揃えた縦持ち(名前が空の行は捨てる)。
-- §27.3: 種牡馬('sire')も足す(産駒名で nar_horses と照合。同名異馬の混入はあり得るが希少)
drop table if exists tmp_pp;
create temp table tmp_pp as
select 'jockey'::text as kind, jockey as name, * from tmp_pr where jockey is not null and jockey <> ''
union all
select 'trainer', trainer, * from tmp_pr where trainer is not null and trainer <> ''
union all
select 'sire', h.sire, t.* from tmp_pr t join public.nar_horses h on h.horse_name = t.horse_name
 where h.sire is not null and h.sire <> ''
union all
-- §105: 母父('bms')も同じ形で。⛔産駒名で照合するのは種牡馬と同じ(同名異馬の混入はあり得るが希少)
select 'bms', h.broodmare_sire, t.* from tmp_pr t join public.nar_horses h on h.horse_name = t.horse_name
 where h.broodmare_sire is not null and h.broodmare_sire <> '';
create index on tmp_pp (kind, name, yr);

drop table if exists tmp_periods;
create temp table tmp_periods as
select 'all'::text as period, 1900 as y_from, 2999 as y_to
union all select extract(year from current_date)::int::text, extract(year from current_date)::int, extract(year from current_date)::int
union all select (extract(year from current_date)::int - 1)::text, extract(year from current_date)::int - 1, extract(year from current_date)::int - 1;

-- 成績の基本形(n, w1, w2, w3, win, top2, top3, roi)
create or replace function pg_temp.basic(p_kind text, p_name text, p_track text, p_from int, p_to int)
returns jsonb language sql as $$
  select jsonb_build_object(
    'n', count(*), 'w1', count(*) filter (where finish = 1), 'w2', count(*) filter (where finish = 2), 'w3', count(*) filter (where finish = 3),
    'win', round(100.0 * count(*) filter (where finish = 1) / nullif(count(*), 0), 1),
    'top2', round(100.0 * count(*) filter (where finish <= 2) / nullif(count(*), 0), 1),
    'top3', round(100.0 * count(*) filter (where finish <= 3) / nullif(count(*), 0), 1),
    'roi', round(100.0 * sum(win_pay) / nullif(count(*) * 100.0, 0), 0),
    'roi3', round(100.0 * sum(place_pay) / nullif(count(*) * 100.0, 0), 0),
    'from', min(race_date), 'to', max(race_date))
  from tmp_pp where kind = p_kind and name = p_name and yr between p_from and p_to and (p_track = 'all' or track = p_track)
$$;

-- #520(2026-09-07) 消して入れ直すまでを 1 トランザクションに(途中で job が止まっても空/半端な表を残さない)
begin;
delete from public.nar_person_stats;

-- (a) 場別の行(出走 10 以上の組だけ)。種牡馬・母父は場別を作らない(§27.3/§105: 'all' だけ)
insert into public.nar_person_stats (kind, name, track, period, stats, updated_at)
select g.kind, g.name, g.track, p.period, pg_temp.basic(g.kind, g.name, g.track, p.y_from, p.y_to), now()
from (select kind, name, track, yr from tmp_pp where kind not in ('sire', 'bms') group by 1, 2, 3, 4) g
join tmp_periods p on g.yr between p.y_from and p.y_to
group by g.kind, g.name, g.track, p.period, p.y_from, p.y_to
having count(*) > 0 and (select count(*) from tmp_pp x where x.kind = g.kind and x.name = g.name and x.track = g.track and x.yr between p.y_from and p.y_to) >= 10;

-- (b) 全場合計の行(出走 10 以上)。場別内訳・距離別・直近30走 付き
insert into public.nar_person_stats (kind, name, track, period, stats, updated_at)
select g.kind, g.name, 'all', p.period,
  pg_temp.basic(g.kind, g.name, 'all', p.y_from, p.y_to)
  || jsonb_build_object(
    'by_track', (
      select coalesce(jsonb_agg(jsonb_build_object('track', track, 'n', n, 'w1', w1, 'win', round(100.0 * w1 / n, 1), 'top3', round(100.0 * t3 / n, 1)) order by n desc), '[]'::jsonb)
      from (select track, count(*) n, count(*) filter (where finish = 1) w1, count(*) filter (where finish <= 3) t3
            from tmp_pp x where x.kind = g.kind and x.name = g.name and x.yr between p.y_from and p.y_to group by track) t),
    'by_distance', (
      select coalesce(jsonb_agg(jsonb_build_object('distance', distance_m, 'n', n, 'w1', w1, 'win', round(100.0 * w1 / n, 1), 'top3', round(100.0 * t3 / n, 1)) order by distance_m), '[]'::jsonb)
      from (select distance_m, count(*) n, count(*) filter (where finish = 1) w1, count(*) filter (where finish <= 3) t3
            from tmp_pp x where x.kind = g.kind and x.name = g.name and x.yr between p.y_from and p.y_to and distance_m is not null group by distance_m having count(*) >= 5) d),
    'recent', case when p.period = 'all' then (
      -- §62 B7-2 直近30走も didRun と同じ規則(中止・失格も出す)。⛔`note` を渡して画面が理由を書けるように
      select coalesce(jsonb_agg(jsonb_build_object('d', race_date, 'track', track, 'no', race_no,
               'horse', horse_name, 'fin', finish, 'note', finish_note, 'pop', popularity,
               'dist', distance_m, 'race', race_name) order by race_date desc, race_no desc), '[]'::jsonb)
      from (select * from tmp_pp x where x.kind = g.kind and x.name = g.name
            order by race_date desc, race_no desc limit 30) r) else null end,
    'main_track', (select track from tmp_pp x where x.kind = g.kind and x.name = g.name and x.yr between p.y_from and p.y_to group by track order by count(*) desc limit 1)
  ), now()
from (select kind, name from tmp_pp where kind not in ('sire', 'bms') group by 1, 2) g
cross join tmp_periods p
where (select count(*) from tmp_pp x where x.kind = g.kind and x.name = g.name and x.yr between p.y_from and p.y_to) >= 10;

-- (c) §27.3/§105 種牡馬(父)と母父: 全国('all')のみ・基本形+場別内訳+距離別。
--     ⛔recent は産駒に意味が無いので付けない。産駒出走 30 以上の名前だけ。
--     ⛔距離別の副問合せは (b) 騎手・調教師と**同じ形**(5 走以上の距離だけ)
insert into public.nar_person_stats (kind, name, track, period, stats, updated_at)
select g.kind, g.name, 'all', p.period,
  pg_temp.basic(g.kind, g.name, 'all', p.y_from, p.y_to)
  || jsonb_build_object(
    'by_track', (
      select coalesce(jsonb_agg(jsonb_build_object('track', track, 'n', n, 'w1', w1, 'win', round(100.0 * w1 / n, 1), 'top3', round(100.0 * t3 / n, 1)) order by n desc), '[]'::jsonb)
      from (select track, count(*) n, count(*) filter (where finish = 1) w1, count(*) filter (where finish <= 3) t3
            from tmp_pp x where x.kind = g.kind and x.name = g.name and x.yr between p.y_from and p.y_to group by track) t),
    'by_distance', (
      select coalesce(jsonb_agg(jsonb_build_object('distance', distance_m, 'n', n, 'w1', w1, 'win', round(100.0 * w1 / n, 1), 'top3', round(100.0 * t3 / n, 1)) order by distance_m), '[]'::jsonb)
      from (select distance_m, count(*) n, count(*) filter (where finish = 1) w1, count(*) filter (where finish <= 3) t3
            from tmp_pp x where x.kind = g.kind and x.name = g.name and x.yr between p.y_from and p.y_to and distance_m is not null group by distance_m having count(*) >= 5) d),
    -- §156 F3 馬場別(良/稍重/重/不良 の 4 つだけ・帯広の水分率や空は入れない・5 走以上)
    'by_going', (
      select coalesce(jsonb_agg(jsonb_build_object('going', going, 'n', n, 'w1', w1, 'win', round(100.0 * w1 / n, 1), 'top3', round(100.0 * t3 / n, 1)) order by array_position(array['良','稍重','重','不良'], going)), '[]'::jsonb)
      from (select going, count(*) n, count(*) filter (where finish = 1) w1, count(*) filter (where finish <= 3) t3
            from tmp_pp x where x.kind = g.kind and x.name = g.name and x.yr between p.y_from and p.y_to and going in ('良','稍重','重','不良') group by going having count(*) >= 5) gg)
  ), now()
from (select kind, name from tmp_pp where kind in ('sire', 'bms') group by 1, 2) g
cross join tmp_periods p
where (select count(*) from tmp_pp x where x.kind = g.kind and x.name = g.name and x.yr between p.y_from and p.y_to) >= 30;

commit;
select kind, count(*) as rows, pg_size_pretty(sum(octet_length(stats::text))::bigint) as json_size from public.nar_person_stats group by kind;
select pg_size_pretty(pg_total_relation_size('public.nar_person_stats')) as table_size;

-- ---------------------------------------------------------------- §156 F2 組み合わせ(騎手×調教師/馬主/父)
-- 上の tmp_pr を使うので**この場所(同じ psql)で**続けて作る。⛔別ファイルにすると temp 表が消える

create table if not exists public.nar_pair_stats (
  key        text primary key,          -- kind|騎手|相手
  kind       text not null,             -- 'jt'(騎手×調教師) | 'jo'(騎手×馬主) | 'js'(騎手×父)
  a          text not null,             -- 騎手(公式の略称)
  b          text not null,             -- 相手(調教師の略称 / 馬主名 / 父名)
  stats      jsonb not null,            -- {n,w1,w2,w3,win,top2,top3,roi,roi3,from,to}
  updated_at timestamptz not null default now()
);
alter table public.nar_pair_stats enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_pair_stats' and policyname = 'nar_pair_stats_read') then
    create policy nar_pair_stats_read on public.nar_pair_stats for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_pair_stats to anon, authenticated;

drop table if exists tmp_pairs;
create temp table tmp_pairs as
select 'jt'::text as kind, t.jockey as a, t.trainer as b, t.* from tmp_pr t
 where t.jockey is not null and t.jockey <> '' and t.trainer is not null and t.trainer <> ''
union all
select 'jo', t.jockey, h.owner, t.* from tmp_pr t join public.nar_horses h on h.horse_name = t.horse_name
 where t.jockey is not null and t.jockey <> '' and h.owner is not null and h.owner <> ''
union all
select 'js', t.jockey, h.sire, t.* from tmp_pr t join public.nar_horses h on h.horse_name = t.horse_name
 where t.jockey is not null and t.jockey <> '' and h.sire is not null and h.sire <> '';

begin;
delete from public.nar_pair_stats;
insert into public.nar_pair_stats (key, kind, a, b, stats, updated_at)
select kind || '|' || a || '|' || b, kind, a, b,
  jsonb_build_object(
    'n', count(*), 'w1', count(*) filter (where finish = 1), 'w2', count(*) filter (where finish = 2), 'w3', count(*) filter (where finish = 3),
    'win', round(100.0 * count(*) filter (where finish = 1) / nullif(count(*), 0), 1),
    'top2', round(100.0 * count(*) filter (where finish <= 2) / nullif(count(*), 0), 1),
    'top3', round(100.0 * count(*) filter (where finish <= 3) / nullif(count(*), 0), 1),
    'roi', round(100.0 * sum(win_pay) / nullif(count(*) * 100.0, 0), 0),
    'roi3', round(100.0 * sum(place_pay) / nullif(count(*) * 100.0, 0), 0),
    'from', min(race_date), 'to', max(race_date)),
  now()
from tmp_pairs
group by kind, a, b
having count(*) >= 5;
commit;
select kind, count(*) as rows from public.nar_pair_stats group by kind order by kind;
select pg_size_pretty(pg_total_relation_size('public.nar_pair_stats')) as table_size;
