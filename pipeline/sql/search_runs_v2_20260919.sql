-- §220 複合検索 v2(2026-09-19)= 出走馬の条件を **4 つまで**(配列 p_kinds/p_names・かつ/または)。§213 の nar_search_runs(2 条件)と同じ作り(条件ごとの UNION ALL・trgm GIN)。
-- 5 つ目以降は無視。空の条件は数えない。旧 nar_search_runs は viewer が v2 に切り替わったあとで落とす。
create or replace function public.nar_search_runs_v2(
  p_tracks text[] default null, p_min int default null, p_max int default null,
  p_from date default null, p_to date default null, p_kw text default null,
  p_kinds text[] default null, p_names text[] default null,
  p_mode text default 'all', p_limit int default 300)
returns table(track text, race_date date, race_no int, race_name text, distance_m int, field_size int,
              going text, condition text, race_kind text, hits jsonb)
language plpgsql stable security invoker set search_path to 'public', 'pg_temp' as $$
declare
  v_n int := 0;
  i int;
begin
  -- 5 つ目以降は落とす・空の名前や知らない種類は数えない(その k の枝は 0 行)
  p_kinds := (select coalesce(array_agg(x order by o), '{}') from unnest(coalesce(p_kinds, '{}')) with ordinality t(x, o) where o <= 4);
  p_names := (select coalesce(array_agg(x order by o), '{}') from unnest(coalesce(p_names, '{}')) with ordinality t(x, o) where o <= 4);
  for i in 1..4 loop
    if nullif(btrim(coalesce(p_names[i],'')),'') is not null and lower(coalesce(p_kinds[i],'')) in ('jockey','trainer','sire','owner') then
      v_n := v_n + 1;
    else
      p_kinds[i] := null; p_names[i] := null;
    end if;
  end loop;
  if v_n = 0 then return; end if;
  return query
  with m as (
    select 1 as k, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.jockey as who
      from nar_runs r
     where lower(coalesce(p_kinds[1],'')) = 'jockey' and r.jockey ilike '%' || btrim(p_names[1]) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 1, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.trainer
      from nar_runs r
     where lower(coalesce(p_kinds[1],'')) = 'trainer' and r.trainer ilike '%' || btrim(p_names[1]) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 1, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note,
           case when lower(coalesce(p_kinds[1],'')) = 'sire' then h.sire else h.owner end
      from nar_horses h join nar_runs r on r.horse_name = h.horse_name
     where lower(coalesce(p_kinds[1],'')) in ('sire','owner')
       and ((lower(coalesce(p_kinds[1],'')) = 'sire' and h.sire ilike '%' || btrim(p_names[1]) || '%') or (lower(coalesce(p_kinds[1],'')) = 'owner' and h.owner ilike '%' || btrim(p_names[1]) || '%'))
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 2 as k, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.jockey as who
      from nar_runs r
     where lower(coalesce(p_kinds[2],'')) = 'jockey' and r.jockey ilike '%' || btrim(p_names[2]) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 2, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.trainer
      from nar_runs r
     where lower(coalesce(p_kinds[2],'')) = 'trainer' and r.trainer ilike '%' || btrim(p_names[2]) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 2, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note,
           case when lower(coalesce(p_kinds[2],'')) = 'sire' then h.sire else h.owner end
      from nar_horses h join nar_runs r on r.horse_name = h.horse_name
     where lower(coalesce(p_kinds[2],'')) in ('sire','owner')
       and ((lower(coalesce(p_kinds[2],'')) = 'sire' and h.sire ilike '%' || btrim(p_names[2]) || '%') or (lower(coalesce(p_kinds[2],'')) = 'owner' and h.owner ilike '%' || btrim(p_names[2]) || '%'))
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 3 as k, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.jockey as who
      from nar_runs r
     where lower(coalesce(p_kinds[3],'')) = 'jockey' and r.jockey ilike '%' || btrim(p_names[3]) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 3, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.trainer
      from nar_runs r
     where lower(coalesce(p_kinds[3],'')) = 'trainer' and r.trainer ilike '%' || btrim(p_names[3]) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 3, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note,
           case when lower(coalesce(p_kinds[3],'')) = 'sire' then h.sire else h.owner end
      from nar_horses h join nar_runs r on r.horse_name = h.horse_name
     where lower(coalesce(p_kinds[3],'')) in ('sire','owner')
       and ((lower(coalesce(p_kinds[3],'')) = 'sire' and h.sire ilike '%' || btrim(p_names[3]) || '%') or (lower(coalesce(p_kinds[3],'')) = 'owner' and h.owner ilike '%' || btrim(p_names[3]) || '%'))
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 4 as k, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.jockey as who
      from nar_runs r
     where lower(coalesce(p_kinds[4],'')) = 'jockey' and r.jockey ilike '%' || btrim(p_names[4]) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 4, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.trainer
      from nar_runs r
     where lower(coalesce(p_kinds[4],'')) = 'trainer' and r.trainer ilike '%' || btrim(p_names[4]) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 4, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note,
           case when lower(coalesce(p_kinds[4],'')) = 'sire' then h.sire else h.owner end
      from nar_horses h join nar_runs r on r.horse_name = h.horse_name
     where lower(coalesce(p_kinds[4],'')) in ('sire','owner')
       and ((lower(coalesce(p_kinds[4],'')) = 'sire' and h.sire ilike '%' || btrim(p_names[4]) || '%') or (lower(coalesce(p_kinds[4],'')) = 'owner' and h.owner ilike '%' || btrim(p_names[4]) || '%'))
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
  ), g as (
    select m.track, m.race_date, m.race_no, count(distinct m.k) nk,
           jsonb_agg(jsonb_build_object('k', m.k, 'no', m.runner_number, 'horse', m.horse_name, 'finish', m.finish,
                                        'note', m.finish_note, 'who', m.who) order by m.k, m.runner_number) hits
      from m group by m.track, m.race_date, m.race_no
  )
  select ra.track, ra.race_date, ra.race_no, ra.race_name, ra.distance_m, ra.field_size, ra.going, ra.condition, ra.race_kind, g.hits
    from g join nar_races ra on ra.track = g.track and ra.race_date = g.race_date and ra.race_no = g.race_no
   where (p_mode <> 'all' or g.nk = v_n)
     and (p_min is null or ra.distance_m >= p_min) and (p_max is null or ra.distance_m <= p_max)
     and (p_kw is null or ra.race_name ilike '%' || p_kw || '%')
   order by ra.race_date desc, ra.race_no asc
   limit greatest(1, least(coalesce(p_limit, 300), 300));
end
$$;
grant execute on function public.nar_search_runs_v2(text[], int, int, date, date, text, text[], text[], text, int) to anon, authenticated;
