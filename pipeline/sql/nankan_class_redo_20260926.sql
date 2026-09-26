-- §294b 南関の過去の級の直し= 点の履歴の級(kaku_ran)を入れ直し → 降級の目安(nar_demotion_race の南関・過去)を消して入れ直す
-- ⛔本番 DB。手動モードで、上から 1 つずつ。条文= nar-site/RULES-nankan-class-20260926.md
--
-- 手順
--   0. この枝(s294b-nankan-class)を master に入れる(cloud/nankan_hist.py・cloud/demotion_race.py)
--   1. 下の (1) を流す(kaku_src に 'calc' を足す)
--   2. 点の履歴を全頭で入れ直す(級だけ変わる。official の行は同じ点で書く):
--        python cloud/nankan_hist.py --env <.env.nar> --all             # dry-run: 行 約 4.7 万・級の決め方 race/calc/carry/None の数を見る
--        python cloud/nankan_hist.py --env <.env.nar> --all --apply
--   3. 下の (2) で件数を控える → (3) で南関の過去の行を消す(凍結の trigger は update だけ= delete は通る)
--   4. 埋め戻し(便 demotion-race-backfill.yml を from=2025-09-26 to=<昨日> kinds=nankan apply=true で手押し、または手元で):
--        python cloud/demotion_race.py --from 2025-09-26 --to 2026-09-25 --kinds nankan --apply
--      ⛔今日以降の行は毎日の便が書く= 触らない(--to は昨日まで)
--   5. 下の (2) をもう一度= 場ごとの行数が 3 と同じ・目安ありの数が dry-run と同じ(下の表)
--
-- dry-run(2026-09-26・材料= 本番の読み取りだけ・点の履歴は新しい決め方で作った CSV)
--   場        行      目安あり(今)  目安あり(新)
--   ooi       13,787  1,505         1,866
--   kawasaki   8,372    980         1,034
--   funabashi  7,893    714           848
--   urawa      7,422    930           992

-- (1) 級の出どころに calc(算定日の点から計算)を足す
alter table public.nar_nankan_point_hist drop constraint if exists nar_nankan_point_hist_kaku_src_check;
alter table public.nar_nankan_point_hist add constraint nar_nankan_point_hist_kaku_src_check
  check (kaku_src is null or kaku_src in ('race', 'calc', 'carry'));
comment on column public.nar_nankan_point_hist.kaku_src is
  '§294b race= 単一級の条件(選抜・特選を含む)/calc= 算定日の点×格付基準表/carry= 同じ半期の前の開催の値';

-- (2) 件数(前後で見る)
select venue, count(*) as rows, count(v) as with_v
from public.nar_demotion_race
where kind = 'nankan' and race_date < (now() at time zone 'Asia/Tokyo')::date
group by venue order by venue;

-- (3) 南関の過去の行を消す
delete from public.nar_demotion_race
where kind = 'nankan' and race_date < (now() at time zone 'Asia/Tokyo')::date;
