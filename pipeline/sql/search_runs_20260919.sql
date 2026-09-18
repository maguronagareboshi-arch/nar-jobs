-- §213 複合検索(2026-09-19)= レース検索に「出走馬の条件」(騎手/調教師/父/馬主・2 つまで・かつ/または)を重ねる。
-- 返り= 当たったレース(場・日・R・レース名・距離・頭数・馬場・条件・種別)+ hits(当たった行の配列)。
-- クラスの絞り(searchClass)は viewer 側で race_name/condition/race_kind に当てる(今の searchRaces と同じ規則)。
-- 父・馬主は nar_horses(馬名で結合)。名前は部分一致(ILIKE)。上限 p_limit(既定 300・日付の新しい順)。
create or replace function public.nar_search_runs(
  p_tracks text[] default null,        -- 公式の場名(null= 全場)
  p_min int default null, p_max int default null,   -- 距離の帯
  p_from date default null, p_to date default null, -- 期間(両端含む)
  p_kw text default null,              -- レース名の部分一致
  p_kind1 text default null, p_name1 text default null,
  p_kind2 text default null, p_name2 text default null,
  p_mode text default 'all',           -- 'all'= 両方が出た / 'any'= どちらか
  p_limit int default 300)
returns table(track text, race_date date, race_no int, race_name text, distance_m int, field_size int,
              going text, condition text, race_kind text, hits jsonb)
language sql stable security invoker set search_path to 'public', 'pg_temp' as $$
with c as (
  select * from (values (1, lower(coalesce(p_kind1,'')), nullif(btrim(coalesce(p_name1,'')), '')),
                        (2, lower(coalesce(p_kind2,'')), nullif(btrim(coalesce(p_name2,'')), ''))) v(k, kind, name)
  where name is not null and kind in ('jockey','trainer','sire','owner')
), ncond as (select count(*) n from c),
m as (
  select c.k, r.track, r.race_date, r.race_no, r.runner_number, r.horse_name, r.finish, r.finish_note,
         case c.kind when 'jockey' then r.jockey when 'trainer' then r.trainer when 'sire' then h.sire else h.owner end as who
    from c
    join nar_runs r on (p_from is null or r.race_date >= p_from) and (p_to is null or r.race_date <= p_to)
                   and (p_tracks is null or r.track = any(p_tracks))
    left join nar_horses h on (c.kind in ('sire','owner') and h.horse_name = r.horse_name)
   where (c.kind = 'jockey'  and r.jockey  ilike '%' || c.name || '%')
      or (c.kind = 'trainer' and r.trainer ilike '%' || c.name || '%')
      or (c.kind = 'sire'    and h.sire    ilike '%' || c.name || '%')
      or (c.kind = 'owner'   and h.owner   ilike '%' || c.name || '%')
), g as (
  select track, race_date, race_no, count(distinct k) nk,
         jsonb_agg(jsonb_build_object('k', k, 'no', runner_number, 'horse', horse_name, 'finish', finish,
                                      'note', finish_note, 'who', who) order by k, runner_number) hits
    from m group by track, race_date, race_no
)
select ra.track, ra.race_date, ra.race_no, ra.race_name, ra.distance_m, ra.field_size, ra.going, ra.condition, ra.race_kind, g.hits
  from g join nar_races ra using (track, race_date, race_no)
 where (select n from ncond) > 0
   and (p_mode <> 'all' or g.nk = (select n from ncond))
   and (p_min is null or ra.distance_m >= p_min) and (p_max is null or ra.distance_m <= p_max)
   and (p_kw is null or ra.race_name ilike '%' || p_kw || '%')
 order by ra.race_date desc, ra.race_no asc
 limit greatest(1, least(coalesce(p_limit, 300), 300));
$$;
grant execute on function public.nar_search_runs(text[], int, int, date, date, text, text, text, text, text, text, int) to anon, authenticated;
