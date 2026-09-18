-- §213 複合検索(2026-09-19)= レース検索に「出走馬の条件」(騎手/調教師/父/馬主・2 つまで・かつ/または)を重ねる。
-- 返り= 当たったレース(場・日・R・レース名・距離・頭数・馬場・条件・種別)+ hits(当たった行の配列)。
-- クラスの絞り(searchClass)は viewer 側で race_name/condition/race_kind に当てる(今の searchRaces と同じ規則)。
-- 父・馬主は nar_horses(馬名で結合)。名前は部分一致(ILIKE)。上限 p_limit(既定 300・日付の新しい順)。
-- 2026-09-19 夜: anon の 3 秒で時間切れ(2.7〜4.2 秒)→ pg_trgm の GIN(jockey/trainer/sire/owner)+race_date の btree を足し、
-- 条件ごとの UNION ALL に書き直した(plpgsql)。実測= 大井 8〜9 月 和田譲×藤本現 all 138ms・全場 12 か月 父×騎手 any 174ms(暖)。
create extension if not exists pg_trgm;
create index if not exists nar_runs_date_idx on public.nar_runs (race_date desc);
create index if not exists nar_runs_jockey_trgm on public.nar_runs using gin (jockey gin_trgm_ops);
create index if not exists nar_runs_trainer_trgm on public.nar_runs using gin (trainer gin_trgm_ops);
create index if not exists nar_horses_sire_trgm on public.nar_horses using gin (sire gin_trgm_ops);
create index if not exists nar_horses_owner_trgm on public.nar_horses using gin (owner gin_trgm_ops);

create or replace function public.nar_search_runs(
  p_tracks text[] default null, p_min int default null, p_max int default null,
  p_from date default null, p_to date default null, p_kw text default null,
  p_kind1 text default null, p_name1 text default null, p_kind2 text default null, p_name2 text default null,
  p_mode text default 'all', p_limit int default 300)
returns table(track text, race_date date, race_no int, race_name text, distance_m int, field_size int,
              going text, condition text, race_kind text, hits jsonb)
language plpgsql stable security invoker set search_path to 'public', 'pg_temp' as $$
declare
  v_n int := 0;
begin
  if nullif(btrim(coalesce(p_name1,'')),'') is not null and lower(coalesce(p_kind1,'')) in ('jockey','trainer','sire','owner') then v_n := v_n + 1; end if;
  if nullif(btrim(coalesce(p_name2,'')),'') is not null and lower(coalesce(p_kind2,'')) in ('jockey','trainer','sire','owner') then v_n := v_n + 1; end if;
  if v_n = 0 then return; end if;
  return query
  with m as (
    select 1 as k, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.jockey as who
      from nar_runs r
     where lower(coalesce(p_kind1,'')) = 'jockey' and r.jockey ilike '%' || btrim(p_name1) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 1, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.trainer
      from nar_runs r
     where lower(coalesce(p_kind1,'')) = 'trainer' and r.trainer ilike '%' || btrim(p_name1) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 1, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note,
           case when lower(p_kind1) = 'sire' then h.sire else h.owner end
      from nar_horses h join nar_runs r on r.horse_name = h.horse_name
     where lower(coalesce(p_kind1,'')) in ('sire','owner')
       and ((lower(p_kind1) = 'sire' and h.sire ilike '%' || btrim(p_name1) || '%') or (lower(p_kind1) = 'owner' and h.owner ilike '%' || btrim(p_name1) || '%'))
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 2, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.jockey
      from nar_runs r
     where lower(coalesce(p_kind2,'')) = 'jockey' and r.jockey ilike '%' || btrim(p_name2) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 2, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note, r.trainer
      from nar_runs r
     where lower(coalesce(p_kind2,'')) = 'trainer' and r.trainer ilike '%' || btrim(p_name2) || '%'
       and (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
       and (p_tracks is null or r.track = any(p_tracks))
    union all
    select 2, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note,
           case when lower(p_kind2) = 'sire' then h.sire else h.owner end
      from nar_horses h join nar_runs r on r.horse_name = h.horse_name
     where lower(coalesce(p_kind2,'')) in ('sire','owner')
       and ((lower(p_kind2) = 'sire' and h.sire ilike '%' || btrim(p_name2) || '%') or (lower(p_kind2) = 'owner' and h.owner ilike '%' || btrim(p_name2) || '%'))
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
grant execute on function public.nar_search_runs(text[], int, int, date, date, text, text, text, text, text, text, int) to anon, authenticated;
