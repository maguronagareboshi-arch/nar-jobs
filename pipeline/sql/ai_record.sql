-- AI成績の夜間集計(2026-08-24 新設・DESIGN §15)。nar_ai_marks × 結果 → nar_ai_record。
-- (model, track('all'|場名), timing) ごとに成績ページ1枚ぶんの JSON を作る。全面作り直し・冪等。
-- 誠実さのルール:
--   ・computed_at >= 発走時刻 の印は集計しない(発走後の後出しを認めない)
--   ・出走取消・除外は購入から除外(競走中止・失格は「買って外れた」扱いで含める)
--   ・決着済み(1着が入っている)レースだけ集計する
set statement_timeout = '10min';

-- 印を1行1頭に展開(発走前に計算された行だけ)
drop table if exists tmp_ai_mk;
create temp table tmp_ai_mk as
select m.model, m.track, m.race_date, m.race_no, m.timing,
       (e.v->>'num')::int as num, e.v->>'mark' as mark
from public.nar_ai_marks m
join public.nar_races r on (r.track, r.race_date, r.race_no) = (m.track, m.race_date, m.race_no)
cross join lateral jsonb_array_elements(m.marks) as e(v)
where r.post_time ~ '^[0-9]{4}$'
  and m.computed_at < ((r.race_date::text || ' ' || substr(r.post_time, 1, 2) || ':' || substr(r.post_time, 3, 2))::timestamp
                       at time zone 'Asia/Tokyo');

-- 結果と払戻を付ける(決着済みレースのみ・取消/除外は落とす)
drop table if exists tmp_ai_res;
create temp table tmp_ai_res as
select k.model, k.track, k.race_date, k.race_no, k.timing, k.num, k.mark,
       u.finish, u.popularity,
       case when u.finish = 1 then coalesce((
         select (p->>'y')::int from jsonb_array_elements(rp.payouts) p
         where p->>'t' = 'win' and p->>'c' = k.num::text limit 1), 0) else 0 end as tan_pay,
       coalesce((
         select (p->>'y')::int from jsonb_array_elements(rp.payouts) p
         where p->>'t' = 'place' and p->>'c' = k.num::text limit 1), 0) as fuku_pay
from tmp_ai_mk k
join public.nar_runs u on (u.track, u.race_date, u.race_no, u.runner_number) = (k.track, k.race_date, k.race_no, k.num)
left join public.nar_race_payouts rp on (rp.track, rp.race_date, rp.race_no) = (k.track, k.race_date, k.race_no)
where coalesce(u.finish_note, '') !~ '取消|除外'
  and exists (select 1 from public.nar_runs w
              where w.track = k.track and w.race_date = k.race_date and w.race_no = k.race_no and w.finish = 1);

-- 場別と 'all' を同じ形で集計できるよう縦に重ねる
drop table if exists tmp_ai_u;
create temp table tmp_ai_u as
select * from tmp_ai_res
union all
select model, 'all', race_date, race_no, timing, num, mark, finish, popularity, tan_pay, fuku_pay from tmp_ai_res;
create index on tmp_ai_u (model, track, timing);

-- 印グループの基本形
create or replace function pg_temp.ai_basic(p_model text, p_track text, p_timing text, p_mark text)
returns jsonb language sql as $$
  select jsonb_build_object(
    'n', count(*), 'w1', count(*) filter (where finish = 1),
    'win',  round(100.0 * count(*) filter (where finish = 1) / nullif(count(*), 0), 1),
    'ren',  round(100.0 * count(*) filter (where finish <= 2) / nullif(count(*), 0), 1),
    'fuku', round(100.0 * count(*) filter (where finish <= 3) / nullif(count(*), 0), 1),
    'tanRet',  round(1.0 * sum(tan_pay)  / nullif(count(*), 0), 0),
    'fukuRet', round(1.0 * sum(fuku_pay) / nullif(count(*), 0), 0))
  from tmp_ai_u where model = p_model and track = p_track and timing = p_timing and (p_mark = '*' or mark = p_mark)
$$;

delete from public.nar_ai_record;
insert into public.nar_ai_record (model, track, timing, stats, updated_at)
select g.model, g.track, g.timing,
  jsonb_build_object(
    'n', (select count(*) from tmp_ai_u x where x.model = g.model and x.track = g.track and x.timing = g.timing and x.mark = '◎'),
    'from', (select min(race_date) from tmp_ai_u x where x.model = g.model and x.track = g.track and x.timing = g.timing),
    'to',   (select max(race_date) from tmp_ai_u x where x.model = g.model and x.track = g.track and x.timing = g.timing),
    'top', pg_temp.ai_basic(g.model, g.track, g.timing, '◎'),
    'byMark', (
      select jsonb_agg(pg_temp.ai_basic(g.model, g.track, g.timing, mk) || jsonb_build_object('mark', mk))
      from unnest(array['◎', '○', '▲', '△']) as mk),
    'popBands', (
      select coalesce(jsonb_agg(jsonb_build_object('band', band, 'n', n, 'w1', w1,
               'win', round(100.0 * w1 / n, 1), 'fuku', round(100.0 * f / n, 1), 'tanRet', round(1.0 * tp / n, 0))
               order by ord), '[]'::jsonb)
      from (select case when popularity = 1 then '1番人気' when popularity = 2 then '2番人気' when popularity = 3 then '3番人気'
                        when popularity between 4 and 6 then '4〜6番人気' else '7番人気以下' end as band,
                   min(case when popularity <= 3 then popularity when popularity <= 6 then 4 else 7 end) as ord,
                   count(*) n, count(*) filter (where finish = 1) w1, count(*) filter (where finish <= 3) f, sum(tan_pay) tp
            from tmp_ai_u x
            where x.model = g.model and x.track = g.track and x.timing = g.timing and x.mark = '◎' and popularity is not null
            group by 1) b),
    'monthly', (
      select coalesce(jsonb_agg(jsonb_build_object('ym', ym, 'n', n, 'w1', w1,
               'win', round(100.0 * w1 / n, 1), 'fuku', round(100.0 * f / n, 1),
               'tanRet', round(1.0 * tp / n, 0), 'fukuRet', round(1.0 * fp / n, 0)) order by ym), '[]'::jsonb)
      from (select to_char(race_date, 'YYYY-MM') ym, count(*) n, count(*) filter (where finish = 1) w1,
                   count(*) filter (where finish <= 3) f, sum(tan_pay) tp, sum(fuku_pay) fp
            from tmp_ai_u x
            where x.model = g.model and x.track = g.track and x.timing = g.timing and x.mark = '◎'
            group by 1) mth),
    'daily', (
      select coalesce(jsonb_agg(jsonb_build_object('d', d, 'n', n, 'w1', w1,
               'win', round(100.0 * w1 / n, 1), 'fuku', round(100.0 * f / n, 1), 'tanRet', round(1.0 * tp / n, 0))
               order by d desc), '[]'::jsonb)
      from (select race_date d, count(*) n, count(*) filter (where finish = 1) w1,
                   count(*) filter (where finish <= 3) f, sum(tan_pay) tp
            from tmp_ai_u x
            where x.model = g.model and x.track = g.track and x.timing = g.timing and x.mark = '◎'
            group by 1 order by 1 desc limit 30) dy)
  ), now()
from (select distinct model, track, timing from tmp_ai_u) g;

select model, timing, count(*) as rows from public.nar_ai_record group by 1, 2 order by 1, 2;
