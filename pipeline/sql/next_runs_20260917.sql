-- §198 同走馬の次走(2026-09-17・Fable)。1 レースの出走馬それぞれの「地方の次の 1 走」を 1 本で返す。
-- 同定= (horse_name, birth_date)。birth_date が無い馬は matched=false(名前だけで結ばない)。
-- p_before があれば race_date < p_before(馬柱から開くとき= 今回のレースの日より前・同日は含めない)。
-- 取消/除外の判定は画面側(finish_note)で行う= 同じ規則 data.isScratched(取消|除外 だけ・中止/失格は出走)。
create or replace function public.nar_next_runs(p_track text, p_date date, p_no integer, p_before date default null)
returns table (
  umaban smallint, horse_name text, finish integer, finish_note text, matched boolean,
  nx_track text, nx_date date, nx_no integer, nx_finish integer, nx_finish_note text, nx_popularity integer,
  nx_race_name text, nx_race_kind text, nx_distance_m integer, nx_going text, nx_field_size integer
)
language sql stable security invoker
set search_path = public
as $$
  select b.runner_number::smallint, b.horse_name, b.finish, b.finish_note, (b.birth_date is not null) as matched,
         n.track, n.race_date, n.race_no, n.finish, n.finish_note, n.popularity,
         r.race_name, r.race_kind, r.distance_m::integer, r.going, r.field_size::integer
  from public.nar_runs b
  left join lateral (
    select x.track, x.race_date, x.race_no, x.finish, x.finish_note, x.popularity
    from public.nar_runs x
    where b.birth_date is not null
      and x.horse_name = b.horse_name and x.birth_date = b.birth_date
      and x.race_date > p_date
      and (p_before is null or x.race_date < p_before)
      and coalesce(x.finish_note, '') !~ '取消|除外'
    order by x.race_date, x.race_no
    limit 1
  ) n on true
  left join public.nar_races r on r.track = n.track and r.race_date = n.race_date and r.race_no = n.race_no
  where b.track = p_track and b.race_date = p_date and b.race_no = p_no
  order by coalesce(b.finish, 99), b.runner_number;
$$;
grant execute on function public.nar_next_runs(text, date, integer, date) to anon, authenticated;
