-- §54.5-c オークション後に何走したか(2026-09-02 ユーザー指摘「閲覧者が欲しいのは転入初戦の情報が薄い中でのオークションでの評価」)。
-- auction_sales に runs_after(落札日より後・今日より前の出走数)と first_after(その最初の日)を持たせ、
-- 画面は runs_after = 0 の馬(=オークション後の初出走)を主役にする。何度も走った馬は脇役。
-- 何度流しても同じ(冪等)。auction.yml の投入の直後と毎朝(load-only)に psql で流す。
-- ⛔「今日」は JST で切る(DB は UTC)。今日の出馬表の行(race_date = 今日)は「走った」に数えない。
-- ⛔出走= finish が入っている行だけ(取消・除外の行は finish が空)。競走中止/失格は finish 無しになることがあり
--   少し少なめに数える(§52 の「走った」より狭い)= 初出走の判定が甘くなる方向ではない(走った馬を初出走と言わない)。

alter table public.auction_sales add column if not exists runs_after  integer;
alter table public.auction_sales add column if not exists first_after date;

with jst as (select (now() at time zone 'Asia/Tokyo')::date as today),
cnt as (
  select s.source, s.item_id,
         count(r.race_date)          as n,
         min(r.race_date)            as first
  from public.auction_sales s
  cross join jst
  left join public.nar_runs r
    on r.horse_name = s.horse_name
   and r.race_date > s.auction_date
   and r.race_date < jst.today
   and r.finish is not null
  where s.horse_name is not null
  group by s.source, s.item_id
)
update public.auction_sales s
   set runs_after = cnt.n, first_after = cnt.first, updated_at = now()
  from cnt
 where cnt.source = s.source and cnt.item_id = s.item_id
   and (s.runs_after is distinct from cnt.n or s.first_after is distinct from cnt.first);

-- 馬名の無い行(幼駒・繁殖)は数えない= null のまま
select count(*) filter (where runs_after = 0) as first_start_pending,
       count(*) filter (where runs_after > 0) as raced_after,
       count(*) filter (where runs_after is null) as unnamed
from public.auction_sales;
