-- 10/26 同走馬のその後に枠色の馬番= 当時の枠(gate)の列を足し、nx の各走に umaban(runner_number)と gate を足す。
-- ⛔本番の形(SECURITY DEFINER・search_path public, pg_temp・実行は anon/authenticated/service_role だけ= PUBLIC なし)を保つ。
-- 返す列が増える= create or replace では変えられない→ 1 つのトランザクションで drop→create→権限(関数が無い瞬間を作らない)。
-- 古い画面は増えた列・キーを読まないだけ(名前で拾う)= 先に入れても壊れない。
begin;
drop function public.nar_next_runs3(text, date, integer, date);
create function public.nar_next_runs3(p_track text, p_date date, p_no integer, p_before date default null)
returns table (
  umaban smallint, horse_name text, birth_date date, finish integer, finish_note text, matched boolean, nx jsonb, gate smallint
)
language sql stable security definer
set search_path = public, pg_temp
as $$
  select b.runner_number::smallint, b.horse_name, b.birth_date, b.finish, b.finish_note, (b.birth_date is not null) as matched,
         coalesce((
           select jsonb_agg(jsonb_build_object(
                    'track', x.track, 'date', x.race_date, 'no', x.race_no, 'finish', x.finish, 'finish_note', x.finish_note,
                    'popularity', x.popularity, 'race_name', r.race_name, 'race_kind', r.race_kind, 'distance_m', r.distance_m,
                    'going', r.going, 'field_size', r.field_size, 'umaban', x.runner_number, 'gate', x.gate) order by x.race_date, x.race_no)
           from (
             select y.track, y.race_date, y.race_no, y.finish, y.finish_note, y.popularity, y.runner_number, y.gate
             from public.nar_runs y
             where b.birth_date is not null
               and y.horse_name = b.horse_name and y.birth_date = b.birth_date
               and y.race_date > p_date
               and (p_before is null or y.race_date < p_before)
               and coalesce(y.finish_note, '') !~ '取消|除外'
             order by y.race_date, y.race_no
             limit 3
           ) x
           left join public.nar_races r on r.track = x.track and r.race_date = x.race_date and r.race_no = x.race_no
         ), '[]'::jsonb) as nx,
         b.gate::smallint
  from public.nar_runs b
  where b.track = p_track and b.race_date = p_date and b.race_no = p_no
  order by coalesce(b.finish, 99), b.runner_number;
$$;
revoke all on function public.nar_next_runs3(text, date, integer, date) from public;
grant execute on function public.nar_next_runs3(text, date, integer, date) to anon, authenticated, service_role;
commit;
