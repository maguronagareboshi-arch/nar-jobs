-- 通信量 F1(2026-10-30): その日の 3 表(レース・出走・払戻)の「版」= 更新時刻の最大と行数を 1 本で返す窓口。
--   便 cloud/day_bundle.py は束を作る前にこれを読んで束に入れ、サイト(nar-viewer js/data.js dayBundle)は
--   DB の今の版と束の版が同じときだけ束を使う(違えば今までどおり DB を読む= 古い束は画面に出ない)。
--   返すのは時刻と行数だけ(中身は出さない)。書く便(load_nar_official.upsert_all・official_alt・si5_store)は
--   触った行の updated_at を毎回付けるので、書けば版が変わる。行が消えたときのために行数も入れる。
-- ⛔10/30 から public の新しいものは自動で API に出ない= grant を同じ所に書く。
-- 流し方: Supabase の SQL Editor にこのファイルの中身を貼って Run(何度流しても同じ)。
create or replace function public.day_ver(p_date date)
returns json
language sql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
  select json_build_object(
    'races', (select json_build_array(max(r.updated_at), count(*)) from public.nar_races r where r.race_date = p_date),
    'runs',  (select json_build_array(max(u.updated_at), count(*)) from public.nar_runs u where u.race_date = p_date),
    -- 払戻の索引は (track, race_date, race_no)= その日の場で絞る
    'pay',   (select json_build_array(max(p.updated_at), count(*)) from public.nar_race_payouts p
               where p.race_date = p_date
                 and p.track in (select distinct r2.track from public.nar_races r2 where r2.race_date = p_date)));
$$;

revoke all on function public.day_ver(date) from public;
grant execute on function public.day_ver(date) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
