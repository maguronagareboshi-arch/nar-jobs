-- §198 工事 2 同走馬のその後 3 走(2026-09-17・Fable)。1 レースの出走馬それぞれの「地方の次の走」を最大 3 つ、1 頭 1 行(nx= jsonb 配列)で返す。
-- 工事 1 の nar_next_runs(次の 1 走)はそのまま残す(画面は本関数だけを呼ぶ)。
-- 同定= (horse_name, birth_date)。birth_date が無い馬は matched=false・nx=[](名前だけで結ばない)。birth_date は「今回も出走」の突き合わせ用に返す。
-- p_before があれば race_date < p_before(馬柱から開くとき= 今回のレースの日より前・同日は含めない)。
-- 取消/除外(finish_note ~ '取消|除外')の走は 3 走に数えず飛ばす(次の走を詰める)。中止/失格は出走として含める(画面側で状態を出す)。
create or replace function public.nar_next_runs3(p_track text, p_date date, p_no integer, p_before date default null)
returns table (
  umaban smallint, horse_name text, birth_date date, finish integer, finish_note text, matched boolean, nx jsonb
)
language sql stable security invoker
set search_path = public
as $$
  select b.runner_number::smallint, b.horse_name, b.birth_date, b.finish, b.finish_note, (b.birth_date is not null) as matched,
         coalesce((
           select jsonb_agg(jsonb_build_object(
                    'track', x.track, 'date', x.race_date, 'no', x.race_no, 'finish', x.finish, 'finish_note', x.finish_note,
                    'popularity', x.popularity, 'race_name', r.race_name, 'race_kind', r.race_kind, 'distance_m', r.distance_m,
                    'going', r.going, 'field_size', r.field_size) order by x.race_date, x.race_no)
           from (
             select y.track, y.race_date, y.race_no, y.finish, y.finish_note, y.popularity
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
         ), '[]'::jsonb) as nx
  from public.nar_runs b
  where b.track = p_track and b.race_date = p_date and b.race_no = p_no
  order by coalesce(b.finish, 99), b.runner_number;
$$;
grant execute on function public.nar_next_runs3(text, date, integer, date) to anon, authenticated;
