-- §280(2026-09-25) 新馬戦の馬柱の「傾向カード」用の集計。設計書 nar-site/DESIGN_s280_shinba_cols_20260925.md §1〜§3。
-- ⛔Actions の中の手元 Postgres でだけ流す(stats_local.py shinba)。本番へは diff/apply が差分だけ戻す。
-- 入力= nar_runs(age, birth_date 込み)・nar_races・nar_race_payouts・nar_horses(dam, breeder 込み)・auction_sales・
--        noken_meta / noken_recs(能検索引を python で行に開いた表)。
-- 出力= nar_shinba_stats(kind, a, b, stats, as_of)。stats は件数だけ {n, w1, w2, w3, pay}(dm だけ sib を足す)。率は画面で割る。
-- 窓= 前日までの 3 年。n<5 の行は作らない(dm だけ n≥1= 設計書 §2-2)。a・b の「無し」は ''・全体は a='*'。
set statement_timeout = '30min';

create table if not exists public.nar_shinba_stats (
  kind       text not null,
  a          text not null,
  b          text not null,
  stats      jsonb not null,
  as_of      date not null default current_date,
  updated_at timestamptz not null default now(),
  primary key (kind, a, b)
);

-- ---------------------------------------------------------------- 帯(⛔境目はここ 1 か所・画面の SHINBA_BANDS と同じ値)
create or replace function pg_temp.band_dist(m int) returns text language sql immutable as $$
  select case when m is null or m <= 0 then null when m <= 1000 then '〜1000' when m <= 1200 then '1100〜1200'
              when m <= 1400 then '1300〜1400' else '1500〜' end $$;
-- 能検 日全体順位(dr/dn)。dn<4 の池は帯にしない
create or replace function pg_temp.band_day(r int, n int) returns text language sql immutable as $$
  select case when r is null or n is null or n < 4 then null when r = 1 then '1位'
              when r::numeric / n <= 0.3 then '上位3割' when r::numeric / n <= 0.7 then '中位' else '下位' end $$;
-- 上がり・テン1F の検査レース内順位(ar/n・t1r/n)
create or replace function pg_temp.band_race(r int, n int) returns text language sql immutable as $$
  select case when r is null or n is null or n < 1 then null when r = 1 then '1位'
              when r::numeric / n <= 0.3 then '上位3割' else 'その他' end $$;
-- 最後の能検→初戦の日数
create or replace function pg_temp.band_week(days int) returns text language sql immutable as $$
  select case when days is null or days < 0 then null when days <= 14 then '〜2週' when days <= 28 then '3〜4週'
              when days <= 56 then '5〜8週' else '9週〜' end $$;
-- 能検の回数(初戦より前の索引の記録の数・再検査・不合格も数える= R12)
create or replace function pg_temp.band_cnt(c bigint) returns text language sql immutable as $$
  select case when c is null or c < 1 then null when c = 1 then '1' when c = 2 then '2' else '3+' end $$;
-- 落札価格(表の値そのまま・円)
create or replace function pg_temp.band_price(p int) returns text language sql immutable as $$
  select case when p is null or p <= 0 then null when p < 1000000 then '〜100万' when p < 3000000 then '100〜300万'
              when p < 6000000 then '300〜600万' else '600万〜' end $$;
create or replace function pg_temp.auc_group(src text) returns text language sql immutable as $$
  select case when src in ('rakuten', 'sat') then 'オークション' when src in ('jrha', 'hba') then 'セリ' end $$;

-- ---------------------------------------------------------------- 窓
-- w_from= 3 年前・nk_from= 索引の端(built の 3 年前)+180 日(R6: これより前の初戦は能検が索引から切れている)
drop table if exists tmp_sw;
create temp table tmp_sw as
select (current_date - interval '3 years')::date as w_from,
       (select ((value->>'built')::date - interval '3 years')::date + 180
          from public.noken_meta where key = 'noken_index') as nk_from;

-- ---------------------------------------------------------------- 「走った」行(person_stats.sql と同じ定義・同じ単勝払戻の式)
drop table if exists tmp_sr;
create temp table tmp_sr as
select u.track, u.race_date, u.race_no, u.runner_number, u.horse_name, u.birth_date, u.age, u.jockey, u.trainer,
       u.finish, u.popularity, r.race_name, r.distance_m,
       case when u.finish = 1 then coalesce((
         select (p->>'y')::int from jsonb_array_elements(rp.payouts) p
         where p->>'t' = 'win' and p->>'c' = u.runner_number::text limit 1), 0) else 0 end as win_pay
from public.nar_runs u
join public.nar_races r on r.track = u.track and r.race_date = u.race_date and r.race_no = u.race_no
left join public.nar_race_payouts rp on rp.track = u.track and rp.race_date = u.race_date and rp.race_no = u.race_no
where (u.finish > 0 or u.finish_note in ('競走中止', '失格')) and u.race_date < current_date
  and u.horse_name is not null and u.horse_name <> '';

-- D= 2 歳の地方初戦(馬=(馬名, 生年月日)の最初の「走った」行・その行が 2 歳・窓の中)
drop table if exists tmp_d;
create temp table tmp_d as
select f.* from (
  select distinct on (horse_name, birth_date) * from tmp_sr order by horse_name, birth_date, race_date, race_no
) f
where f.age = 2 and f.race_date >= (select w_from from tmp_sw);
create index on tmp_d (horse_name);

-- S= 新馬戦の出走(判定語は viewer の SHINBA_WORDS と同じ「新馬」「初出走」)
drop table if exists tmp_s;
create temp table tmp_s as
select * from tmp_sr
where race_date >= (select w_from from tmp_sw) and (race_name like '%新馬%' or race_name like '%初出走%');

-- D∩能検= 初戦より前の索引の記録がある馬(初戦日 ≥ 索引の端+180 日だけ)。能検の値は初戦直前の 1 件
drop table if exists tmp_dn;
create temp table tmp_dn as
select d.*, k.d as nk_d, k.date as nk_date, k.n as nk_n, k.dr, k.dn, k.ar, k.t1r, k.j as nk_j, c.cnt as nk_cnt
from tmp_d d
cross join lateral (select count(*) as cnt from public.noken_recs k
                    where k.horse_name = d.horse_name and k.date < d.race_date) c
cross join lateral (select * from public.noken_recs k
                    where k.horse_name = d.horse_name and k.date < d.race_date
                    order by k.date desc, k.d limit 1) k
where c.cnt > 0 and d.race_date >= (select nk_from from tmp_sw);

-- ---------------------------------------------------------------- 縦持ち(kind, a, b, 着, 単勝払戻)
drop table if exists tmp_kv;
create temp table tmp_kv (kind text, a text, b text, finish int, win_pay int);

-- sd 父×距離帯 / bd 母父×距離帯 / st 父×場(D)
insert into tmp_kv
select 'sd', h.sire, pg_temp.band_dist(d.distance_m), d.finish, d.win_pay
from tmp_d d join public.nar_horses h on h.horse_name = d.horse_name;
insert into tmp_kv
select 'bd', h.broodmare_sire, pg_temp.band_dist(d.distance_m), d.finish, d.win_pay
from tmp_d d join public.nar_horses h on h.horse_name = d.horse_name;
insert into tmp_kv
select 'st', h.sire, d.track, d.finish, d.win_pay
from tmp_d d join public.nar_horses h on h.horse_name = d.horse_name;

-- td 厩舎の新馬戦 / br 生産牧場 / jk 騎手×場の新馬戦(S)
insert into tmp_kv select 'td', s.trainer, '', s.finish, s.win_pay from tmp_s s;
insert into tmp_kv
select 'br', h.breeder, '', s.finish, s.win_pay
from tmp_s s join public.nar_horses h on h.horse_name = s.horse_name;
insert into tmp_kv select 'jk', s.jockey, s.track, s.finish, s.win_pay from tmp_s s;

-- nj 能検の騎手→初戦の騎手(同じ= same / 替わった= chg)。a= 調教師と '*'。索引に j の無い馬は数えない
insert into tmp_kv
select 'nj', v.a, case when regexp_replace(coalesce(x.jockey, ''), '\s', '', 'g') = x.nk_j then 'same' else 'chg' end,
       x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.trainer), ('*')) v(a)
where x.nk_j is not null and x.nk_j <> '' and x.jockey is not null and x.jockey <> '';

-- nr 日全体順位帯 / nw 週数帯 / nc 回数 / ka 上がり順位帯 / kt テン1F 順位帯。a= 地区と '*'
insert into tmp_kv
select 'nr', v.a, pg_temp.band_day(x.dr, x.dn), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*')) v(a);
insert into tmp_kv
select 'nw', v.a, pg_temp.band_week(x.race_date - x.nk_date), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*')) v(a);
insert into tmp_kv
select 'nc', v.a, pg_temp.band_cnt(x.nk_cnt), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*')) v(a);
insert into tmp_kv
select 'ka', v.a, pg_temp.band_race(x.ar, x.nk_n), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*')) v(a);
insert into tmp_kv
select 'kt', v.a, pg_temp.band_race(x.t1r, x.nk_n), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*')) v(a);

-- au 落札価格帯(初戦より前の最後の落札・生年月日は両方あるときだけ合わせる= R5)。a= オークション / セリ と '*'
insert into tmp_kv
select 'au', v.a, pg_temp.band_price(s.price), d.finish, d.win_pay
from tmp_d d
cross join lateral (select * from public.auction_sales s
                    where s.horse_name = d.horse_name and s.sold and s.price is not null
                      and s.auction_date < d.race_date
                      and (s.birth_date is null or d.birth_date is null or s.birth_date = d.birth_date)
                    order by s.auction_date desc limit 1) s
cross join lateral (values (pg_temp.auc_group(s.source)), ('*')) v(a);

-- dm 兄姉の初戦(D・a= 母)。sib= 新しい順に最大 5 頭 {h 馬名, d 初戦日, t 場, f 着(中止・失格は null), p 人気}
drop table if exists tmp_dm;
create temp table tmp_dm as
select h.dam, d.*, row_number() over (partition by h.dam order by d.race_date desc, d.horse_name) as rn
from tmp_d d join public.nar_horses h on h.horse_name = d.horse_name
where h.dam is not null and h.dam <> '';

-- ---------------------------------------------------------------- 書き込み(消して入れ直すまでを 1 トランザクション)
begin;
delete from public.nar_shinba_stats;

insert into public.nar_shinba_stats (kind, a, b, stats, as_of, updated_at)
select kind, a, b,
       jsonb_build_object('n', count(*), 'w1', count(*) filter (where finish = 1),
                          'w2', count(*) filter (where finish = 2), 'w3', count(*) filter (where finish = 3),
                          'pay', coalesce(sum(win_pay), 0)),
       current_date, now()
from tmp_kv
where a is not null and a <> '' and b is not null
group by kind, a, b
having count(*) >= 5;

insert into public.nar_shinba_stats (kind, a, b, stats, as_of, updated_at)
select 'dm', dam, '',
       jsonb_build_object('n', count(*), 'w1', count(*) filter (where finish = 1),
                          'w2', count(*) filter (where finish = 2), 'w3', count(*) filter (where finish = 3),
                          'pay', coalesce(sum(win_pay), 0),
                          'sib', jsonb_agg(jsonb_build_object('h', horse_name, 'd', race_date, 't', track,
                                                              'f', nullif(finish, 0), 'p', popularity)
                                           order by race_date desc, horse_name) filter (where rn <= 5)),
       current_date, now()
from tmp_dm
group by dam;

commit;

select kind, count(*) as rows, sum((stats->>'n')::int) as runs from public.nar_shinba_stats group by kind order by kind;
