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

-- ◎から○▲△へ流した馬券(馬連・馬単・三連単)の成績(2026-09-10 追加)。
-- 買い方はこれだけ= ◎を軸に相手3頭へ流す・1組100円。⛔点数は規則で3点/6点に固定せず、
-- **実際に買えた組の数**で持つ(印が少ないレースはその分だけ減る)。
-- ⛔取消・除外は tmp_ai_res の時点で落ちているので、その馬を含む組は自動的に買わない。
-- ⛔◎が取消・除外ならそのレースは1点も買わない(hon が無い= 行ごと落とす)。

-- ① レース単位に ◎(hon)と相手(○▲△)をまとめる
drop table if exists tmp_ai_hd;
create temp table tmp_ai_hd as
select model, track, race_date, race_no, timing,
       min(num) filter (where mark = '◎') as hon,
       coalesce(array_agg(num order by num) filter (where mark in ('○', '▲', '△')), '{}'::int[]) as aite
from tmp_ai_res
group by 1, 2, 3, 4, 5;
delete from tmp_ai_hd where hon is null;

-- ② 払戻をレースごとに1回だけ開く(この3券種だけ)。
--    ⛔組番は string_to_array で**数の配列**にして比べる= 文字列の並びを仮定しない。
--    ⚠数字と '-' 以外の組番(将来増えた書き方)はキャストで落ちるので、正規表現で先に外す
drop table if exists tmp_ai_pay;
create temp table tmp_ai_pay as
select h.track, h.race_date, h.race_no, e.v->>'t' as t,
       string_to_array(e.v->>'c', '-')::int[] as c, (e.v->>'y')::int as y
from (select distinct track, race_date, race_no from tmp_ai_hd) h
join public.nar_race_payouts rp on (rp.track, rp.race_date, rp.race_no) = (h.track, h.race_date, h.race_no)
cross join lateral jsonb_array_elements(rp.payouts) as e(v)
where e.v->>'t' in ('quinella', 'exacta', 'trifecta')
  and e.v->>'c' ~ '^[0-9]+(-[0-9]+)*$';
create index on tmp_ai_pay (track, race_date, race_no, t);

-- ③ レースごとの 点数 / 払戻 / 的中(0-1)。同着で2組当たれば払戻は両方足す(的中はレース単位なので1)
drop table if exists tmp_ai_ex;
create temp table tmp_ai_ex as
select h.model, h.track, h.race_date, h.race_no, h.timing,
       cardinality(h.aite) as um_pts, coalesce(um.y, 0) as um_pay, (um.n > 0)::int as um_hit,
       cardinality(h.aite) as ut_pts, coalesce(ut.y, 0) as ut_pay, (ut.n > 0)::int as ut_hit,
       cardinality(h.aite) * (cardinality(h.aite) - 1) as st_pts,
       coalesce(st.y, 0) as st_pay, (st.n > 0)::int as st_hit
from tmp_ai_hd h
-- 馬連 ◎−相手(順不同)= 長さ2で ◎と相手の両方を含む
left join lateral (
  select count(*) n, sum(p.y) y from tmp_ai_pay p
  where p.track = h.track and p.race_date = h.race_date and p.race_no = h.race_no and p.t = 'quinella'
    and array_length(p.c, 1) = 2
    and exists (select 1 from unnest(h.aite) x where x <> h.hon and p.c @> array[h.hon, x])) um on true
-- 馬単 ◎→相手(◎が1着)
left join lateral (
  select count(*) n, sum(p.y) y from tmp_ai_pay p
  where p.track = h.track and p.race_date = h.race_date and p.race_no = h.race_no and p.t = 'exacta'
    and exists (select 1 from unnest(h.aite) x where p.c = array[h.hon, x])) ut on true
-- 三連単 ◎→相手→別の相手(◎が1着固定・2/3着は相手の並べ方)
left join lateral (
  select count(*) n, sum(p.y) y from tmp_ai_pay p
  where p.track = h.track and p.race_date = h.race_date and p.race_no = h.race_no and p.t = 'trifecta'
    and exists (select 1 from unnest(h.aite) x, unnest(h.aite) z
                where z <> x and p.c = array[h.hon, x, z])) st on true;

-- 場別と 'all' を同じ形で集計できるよう縦に重ねる
drop table if exists tmp_ai_u;
create temp table tmp_ai_u as
select * from tmp_ai_res
union all
select model, 'all', race_date, race_no, timing, num, mark, finish, popularity, tan_pay, fuku_pay from tmp_ai_res;
create index on tmp_ai_u (model, track, timing);

drop table if exists tmp_ai_exu;
create temp table tmp_ai_exu as
select * from tmp_ai_ex
union all
select model, 'all', race_date, race_no, timing,
       um_pts, um_pay, um_hit, ut_pts, ut_pay, ut_hit, st_pts, st_pay, st_hit from tmp_ai_ex;
create index on tmp_ai_exu (model, track, timing);

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

-- 流し馬券の3券種をまとめて1つの JSON に。
-- n= 1点でも買えたレース数・pts= 買った組の合計・hit= 当たったレース数・
-- rate= 的中率(%)・ret= 100円あたりの戻り(tanRet と同じ読み方)。
-- ⛔レース数0の券種も鍵は残す(n:0。画面側が節を出すかを見るため)
create or replace function pg_temp.ai_exotic(p_model text, p_track text, p_timing text)
returns jsonb language sql as $$
  select jsonb_build_object(
    'umaren', jsonb_build_object(
      'n', count(*) filter (where um_pts > 0), 'pts', coalesce(sum(um_pts), 0),
      'hit', coalesce(sum(um_hit), 0),
      'rate', round(100.0 * sum(um_hit) / nullif(count(*) filter (where um_pts > 0), 0), 1),
      'ret', round(1.0 * sum(um_pay) / nullif(sum(um_pts), 0), 0)),
    'umatan', jsonb_build_object(
      'n', count(*) filter (where ut_pts > 0), 'pts', coalesce(sum(ut_pts), 0),
      'hit', coalesce(sum(ut_hit), 0),
      'rate', round(100.0 * sum(ut_hit) / nullif(count(*) filter (where ut_pts > 0), 0), 1),
      'ret', round(1.0 * sum(ut_pay) / nullif(sum(ut_pts), 0), 0)),
    'sanrentan', jsonb_build_object(
      'n', count(*) filter (where st_pts > 0), 'pts', coalesce(sum(st_pts), 0),
      'hit', coalesce(sum(st_hit), 0),
      'rate', round(100.0 * sum(st_hit) / nullif(count(*) filter (where st_pts > 0), 0), 1),
      'ret', round(1.0 * sum(st_pay) / nullif(sum(st_pts), 0), 0)))
  from tmp_ai_exu where model = p_model and track = p_track and timing = p_timing
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
            group by 1 order by 1 desc limit 30) dy),
    'exotic', pg_temp.ai_exotic(g.model, g.track, g.timing)
  ), now()
from (select distinct model, track, timing from tmp_ai_u) g;

select model, timing, count(*) as rows,
       sum((stats->'exotic'->'umaren'->>'n')::int) as exotic_n
from public.nar_ai_record group by 1, 2 order by 1, 2;
