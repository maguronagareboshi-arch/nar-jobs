-- 通信量 F3(2026-10-30): その日の AI の印(nar_ai_marks)の「版」を model ごとに返す窓口。
--   版 = [computed_at の最大, 行数, xmin の最大]。印を書く便(base_v1.write_marks)は computed_at を秒までしか付けず、
--   updated_at は上書きで変わらない(トリガーが付けない)= 書けば必ず変わる xmin(行の版番号)も入れる。
--   便 cloud/marks_bundle.py は版から置き場の名前(marks/v1/<日>/<model>/<行数>-<xmin>-<時刻の数字>.json)を作って上げ、
--   サイト(nar-viewer js/data.js marksFromBundle)は DB の今の版から同じ名前を作って読む= 古い束は読みようがない。
--   返すのはサイトが日ごとに読む 3 つの model だけ(影の model の名前を出さない)。増やすときはサイトの MARKS_BUNDLE_SEL も。
--   返すのは時刻・行数・版番号だけ(中身は出さない)。
-- ⛔10/30 から public の新しいものは自動で API に出ない= grant を同じ所に書く。
-- 流し方: Supabase の SQL Editor にこのファイルの中身を貼って Run(何度流しても同じ)。
create or replace function public.marks_ver(p_date date)
returns json
language sql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
  select coalesce(json_object_agg(t.model, json_build_array(t.mx, t.n, t.xm) order by t.model), '{}'::json)
  from (select m.model, max(m.computed_at) as mx, count(*) as n, max(m.xmin::text::bigint) as xm
          from public.nar_ai_marks m
         where m.race_date = p_date
           and m.model in ('base-v1', 'v3n-1', 'v3-9')
         group by m.model) t;
$$;

revoke all on function public.marks_ver(date) from public;
grant execute on function public.marks_ver(date) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
