-- §280(2026-09-25) 新馬戦の馬柱の「傾向カード」用の集計。設計書 nar-site/DESIGN_s280_shinba_cols_20260925.md §1〜§3。
-- ⛔Actions の中の手元 Postgres でだけ流す(stats_local.py shinba)。本番へは diff/apply が差分だけ戻す。
-- 入力= nar_runs(age, birth_date 込み)・nar_races・nar_race_payouts・nar_kd_pedigree(KDSCOPE の血統・(馬名, 生年月日) で引く)・
--        nar_horses(dam, breeder 込み・KD に無い馬だけ馬名で落とす)・
--        noken_meta / noken_recs(能検索引を python で行に開いた表)。
-- 出力= nar_shinba_stats(kind, a, b, stats, as_of)。stats は件数だけ {n, w1, w2, w3, pay}(dm だけ sib を足す)。率は画面で割る。
-- 母集団= sd/bd/st/sv/bv は 2 歳の走ぜんぶ(tmp_d2・9/25 ユーザー決定)・td/br/jk は新馬戦(tmp_s)・他は 2 歳の初戦(tmp_d)。
-- b の鍵は viewer の data.js SHINBA_BANDS と同じ字(検査で一致を見る)。
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
  select case when m is null or m <= 0 then null when m <= 1000 then 'd1000' when m <= 1200 then 'd1200'
              when m <= 1400 then 'd1400' else 'd1500' end $$;
-- 能検 日全体順位(dr/dn)。dn<4 の池は帯にしない
create or replace function pg_temp.band_day(r int, n int) returns text language sql immutable as $$
  select case when r is null or n is null or n < 4 then null when r = 1 then 'r1'
              when r::numeric / n <= 0.3 then 'top30' when r::numeric / n <= 0.7 then 'mid' else 'low' end $$;
-- §304c 能検の時計(案 C)の百分位 0〜1(小さいほど速い)。1 位帯は作らない(研究と同じ)。⛔画面 data.js の NOKEN_PCT_BANDS と同じ境目
create or replace function pg_temp.band_pct(q numeric) returns text language sql immutable as $$
  select case when q is null then null when q <= 0.3 then 'top30' when q <= 0.7 then 'mid' else 'low' end $$;
-- 上がり・テン1F の検査レース内順位(ar/n・t1r/n)
-- 上がり・テン1F の順位そのもの(10/2 ユーザー了承)= 1位 / 2位 / 3位以下。⛔viewer の SHINBA_BANDS.lapRank3 と同じ字。
--   旧 ka/kt(上位3割の帯)は 10/2 に消した(画面は ka3/kt3 だけ読む)
create or replace function pg_temp.band_rank3(r int) returns text language sql immutable as $$
  select case when r is null or r < 1 then null when r = 1 then 'r1' when r = 2 then 'r2' else 'r3' end $$;
-- 最後の能検→初戦の日数
create or replace function pg_temp.band_week(days int) returns text language sql immutable as $$
  select case when days is null or days < 0 then null when days <= 14 then 'w2' when days <= 28 then 'w4'
              when days <= 56 then 'w8' else 'w9' end $$;
-- 能検の回数(初戦より前の索引の記録の数・再検査・不合格も数える= R12)
create or replace function pg_temp.band_cnt(c bigint) returns text language sql immutable as $$
  select case when c is null or c < 1 then null when c = 1 then '1' when c = 2 then '2' else '3+' end $$;

-- ---------------------------------------------------------------- 窓
-- w_from= 3 年前・nk_from= 索引の端(built の 3 年前)+180 日(R6: これより前の初戦は能検が索引から切れている)
drop table if exists tmp_sw;
create temp table tmp_sw as
select (current_date - interval '3 years')::date as w_from,
       -- §304c 場で数える sv・bv・td・jk の既定の窓= 5 年(10/2 ユーザー「豪州の砂以外は 3 年か 5 年」)。豪州の砂の場は tmp_sand の日から
       (current_date - interval '5 years')::date as sv_from,
       (select ((value->>'built')::date - interval '3 years')::date + 180
          from public.noken_meta where key = 'noken_index') as nk_from;
-- (10/2 ユーザー決定) 場ごとの数え始め= 豪州産の砂に変えた後(変えた入れ替えの後の最初の開催日・出どころは viewer の data/sand-history.json)。
--   船橋 2022/10/29〜11/27 宮城産山砂→豪州産陸砂・大井 2023/10/8〜21 豪州アルバニー産(10/29 から)・門別 2023/3/30 豪州産珪砂(4/19 開幕)・
--   名古屋 2025/8/18 再開 豪州アルバニー産・園田 2020/4/3〜6 六ケ所村→豪州アルバニー産(2024・2025 は豪州産どうしの入れ替え)。
--   使う所= 場で数える sv・bv(父/母父×場×距離帯)・td(厩舎の新馬戦)・jk(騎手×場の新馬戦)・能検の比べ表の 'v:' 行。表に無い場は sv_from(5 年)。
--   画面の見出しの字は 'win' の行(a= 場)から読む。⛔場を足すときはここに 1 行(track は nar_runs の字)
drop table if exists tmp_sand;
create temp table tmp_sand (track text primary key, from_date date not null, why text not null);
insert into tmp_sand values
  ('船橋', '2022-11-28', '豪州産の砂'), ('大井', '2023-10-29', '豪州産の砂'), ('門別', '2023-04-19', '豪州産の砂'),
  ('名古屋', '2025-08-18', '豪州産の砂'), ('園田', '2020-04-07', '豪州産の砂');

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

-- D2= 2 歳の走ぜんぶ(窓の中の age=2 の「走った」行・9/25 ユーザー決定)。sd/bd/st の母集団
drop table if exists tmp_d2;
create temp table tmp_d2 as
select horse_name, birth_date, race_date, age, distance_m, track, finish, win_pay from tmp_sr   -- 生年月日・日付・齢= ped_key 用(10/2)
where age = 2 and race_date >= (select w_from from tmp_sw);
create index on tmp_d2 (horse_name);
-- D2v= sv/bv の母集団(2 歳の走ぜんぶ・窓は場ごとの数え始め tmp_sand、無い場は tmp_sw.sv_from)
drop table if exists tmp_d2v;
create temp table tmp_d2v as
select horse_name, birth_date, race_date, age, distance_m, track, finish, win_pay from tmp_sr
where age = 2 and race_date >= coalesce((select x.from_date from tmp_sand x where x.track = tmp_sr.track), (select sv_from from tmp_sw));
create index on tmp_d2v (horse_name);

-- 血統(10/2・案 c)= 走の鍵 pk で nar_kd_pedigree を引き、無い項目は nar_horses(馬名だけの鍵)へ落とす。
--   pk= 生年月日がある走は 'YYYY-MM-DD'(KD の (馬名, 生年月日)・同じ組が 2 頭なら NU を先・ketto の小さい方)。
--       無い古い走(2022-11 より前)は 'y' || 生年(= 走った年 − 馬齢・馬齢は 1/1 に加算)。KD で (馬名, 生年) が 1 頭に決まるときだけ結ぶ。
--       どちらも無ければ ''(= nar_horses だけ)。⛔tmp_d / tmp_d2 / tmp_s / dm は同じ pg_temp.ped_key で結ぶ
create or replace function pg_temp.ped_key(bd date, rd date, age int) returns text language sql immutable as $$
  select case when bd is not null then bd::text
              when rd is not null and age is not null then 'y' || (extract(year from rd)::int - age)::text
              else '' end $$;
drop table if exists tmp_ped;
create temp table tmp_ped as
-- (10/2) 窓で絞らない= 兄姉 dm は 2014 年からの初戦を使う(tmp_dall)
with k as (select distinct horse_name, pg_temp.ped_key(birth_date, race_date, age) as pk
           from tmp_sr),
kd as (select distinct on (horse_name, birth_date) * from public.nar_kd_pedigree
       where birth_date is not null
       order by horse_name, birth_date, (src = 'NU') desc, ketto),
ky as (select horse_name, 'y' || extract(year from birth_date)::int::text as pk,
              min(sire) as sire, min(broodmare_sire) as broodmare_sire, min(dam) as dam, min(breeder) as breeder
       from public.nar_kd_pedigree where birth_date is not null
       group by 1, 2 having count(*) = 1)
select k.horse_name, k.pk,
       coalesce(nullif(kd.sire, ''), nullif(ky.sire, ''), h.sire) as sire,
       coalesce(nullif(kd.broodmare_sire, ''), nullif(ky.broodmare_sire, ''), h.broodmare_sire) as broodmare_sire,
       coalesce(nullif(kd.dam, ''), nullif(ky.dam, ''), h.dam) as dam,
       coalesce(nullif(kd.breeder, ''), nullif(ky.breeder, ''), h.breeder) as breeder
from k
left join kd on kd.horse_name = k.horse_name and kd.birth_date::text = k.pk
left join ky on ky.horse_name = k.horse_name and ky.pk = k.pk
left join public.nar_horses h on h.horse_name = k.horse_name;
create index on tmp_ped (horse_name, pk);

-- Dall= 兄姉 dm 用の 2 歳の地方初戦(10/2・窓なし= nar_runs の端 2014-01 から)。
--   馬= (馬名, 生年)。生年= 生年月日の年、無い古い走は 走った年 − 馬齢(2022-11 の前後で鍵の形が変わっても同じ馬を 2 頭にしない)。
--   血統はその初戦の行の ped_key で tmp_ped を引く(古い初戦は KD の (馬名, 生年) が 1 頭のときだけ・無ければ nar_horses)
drop table if exists tmp_dall;
create temp table tmp_dall as
select f.* from (
  select distinct on (horse_name, coalesce(extract(year from birth_date)::int, extract(year from race_date)::int - age)) *
  from tmp_sr where age is not null or birth_date is not null
  order by horse_name, coalesce(extract(year from birth_date)::int, extract(year from race_date)::int - age), race_date, race_no
) f
where f.age = 2;

-- S= 新馬戦の出走(判定語は viewer の SHINBA_WORDS と同じ「新馬」「初出走」)
drop table if exists tmp_s;
create temp table tmp_s as
select * from tmp_sr
where race_date >= (select w_from from tmp_sw) and (race_name like '%新馬%' or race_name like '%初出走%');
-- Sj= td(厩舎の新馬戦)・jk(騎手×場の新馬戦)の母集団= 場ごとの数え始め(tmp_sand)・無い場は sv_from(5 年)(10/2)
drop table if exists tmp_sj;
create temp table tmp_sj as
select * from tmp_sr
where race_date >= coalesce((select x.from_date from tmp_sand x where x.track = tmp_sr.track), (select sv_from from tmp_sw))
  and (race_name like '%新馬%' or race_name like '%初出走%');

-- D∩能検= 初戦より前の索引の記録がある馬(初戦日 ≥ 索引の端+180 日だけ)。能検の値は初戦直前の 1 件
drop table if exists tmp_dn;
create temp table tmp_dn as
select d.*, k.d as nk_d, k.date as nk_date, k.n as nk_n, k.dr, k.dn, k.ar, k.t1r, k.j as nk_j, c.cnt as nk_cnt,
       k.p as nk_p, k.dm as nk_dm, k.ag as nk_ag, k.sec as nk_sec
from tmp_d d
cross join lateral (select count(*) as cnt from public.noken_recs k
                    where k.horse_name = d.horse_name and k.date < d.race_date) c
cross join lateral (select * from public.noken_recs k
                    where k.horse_name = d.horse_name and k.date < d.race_date
                    order by k.date desc, k.d limit 1) k
where c.cnt > 0 and d.race_date >= (select nk_from from tmp_sw);

-- §304c(10/2 ユーザー決定) 能検の時計 案 C= 同じ池(地区×場×距離×齢帯)の、その能検日より前 365 日の時計の中での百分位。
--   各日の時計は「その日の中央値−窓の中央値」を n/(n+k) 倍だけ引いて補正(縮み推定・k=11.1・頭数が少ない日は 0 に寄せる)。
--   本人の時計も同じく本人の日で補正。窓の頭数 20 未満は帯なし。⛔窓は能検日より前だけ(未来を入れない)。
--   定義は nar-site/research/noken-time-measure/measure.py の C と同じ。⛔画面 data.js nokenTimePct と同じ k・境目
drop table if exists tmp_nu;
create temp table tmp_nu as   -- 一意の記録(別名キーで同じ記録が複数の馬名に入るので重複を除く)
select distinct d, p, date, r, sec, j, w, dm, ag from public.noken_recs where sec is not null;
drop table if exists tmp_nday;
create temp table tmp_nday as
select d, p, dm, ag, date, count(*) as n, percentile_cont(0.5) within group (order by sec)::numeric as med
from tmp_nu group by d, p, dm, ag, date;
drop table if exists tmp_ntg;
create temp table tmp_ntg as   -- 求める (池, 能検日) と窓の中央値・頭数
select t.*, w.m, w.cnt
from (select distinct nk_d as d, nk_p as p, nk_dm as dm, nk_ag as ag, nk_date as date from tmp_dn where nk_sec is not null) t
cross join lateral (
  select percentile_cont(0.5) within group (order by u.sec)::numeric as m, count(*) as cnt from tmp_nu u
  where u.d is not distinct from t.d and u.p is not distinct from t.p and u.dm is not distinct from t.dm
    and u.ag is not distinct from t.ag and u.date >= t.date - 365 and u.date < t.date) w;
drop table if exists tmp_nq;
create temp table tmp_nq as   -- 初戦の行(馬名, 生年月日)ごとの百分位
select x.horse_name, x.birth_date, (
  select (count(*) filter (where a.v < s2.v) + 0.5 * count(*) filter (where a.v = s2.v)) / count(*)
  from (select u.sec - (dy.med - g.m) * dy.n / (dy.n + 11.1) as v
        from tmp_nu u join tmp_nday dy
          on dy.d is not distinct from u.d and dy.p is not distinct from u.p and dy.dm is not distinct from u.dm
         and dy.ag is not distinct from u.ag and dy.date = u.date
        where u.d is not distinct from g.d and u.p is not distinct from g.p and u.dm is not distinct from g.dm
          and u.ag is not distinct from g.ag and u.date >= g.date - 365 and u.date < g.date) a) as q
from tmp_dn x
join tmp_ntg g on g.d is not distinct from x.nk_d and g.p is not distinct from x.nk_p and g.dm is not distinct from x.nk_dm
              and g.ag is not distinct from x.nk_ag and g.date = x.nk_date and g.cnt >= 20
join tmp_nday td on td.d is not distinct from x.nk_d and td.p is not distinct from x.nk_p and td.dm is not distinct from x.nk_dm
              and td.ag is not distinct from x.nk_ag and td.date = x.nk_date
cross join lateral (select x.nk_sec - (td.med - g.m) * td.n / (td.n + 11.1) as v) s2
where x.nk_sec is not null;

-- ---------------------------------------------------------------- 縦持ち(kind, a, b, 着, 単勝払戻)
drop table if exists tmp_kv;
create temp table tmp_kv (kind text, a text, b text, finish int, win_pay int);

-- sd 父×距離帯 / bd 母父×距離帯 / st 父×場(D2= 2 歳の走ぜんぶ)
insert into tmp_kv
select 'sd', h.sire, pg_temp.band_dist(d.distance_m), d.finish, d.win_pay
from tmp_d2 d join tmp_ped h on h.horse_name = d.horse_name and h.pk = pg_temp.ped_key(d.birth_date, d.race_date, d.age);
insert into tmp_kv
select 'bd', h.broodmare_sire, pg_temp.band_dist(d.distance_m), d.finish, d.win_pay
from tmp_d2 d join tmp_ped h on h.horse_name = d.horse_name and h.pk = pg_temp.ped_key(d.birth_date, d.race_date, d.age);
insert into tmp_kv
select 'st', h.sire, d.track, d.finish, d.win_pay
from tmp_d2 d join tmp_ped h on h.horse_name = d.horse_name and h.pk = pg_temp.ped_key(d.birth_date, d.race_date, d.age);
-- §304(10/2) sv 父×場×距離帯 / bv 母父×場×距離帯(D2)。b= 場|距離帯(例 'funabashi|d1000')。帯が無い走は作らない
insert into tmp_kv
select 'sv', h.sire, d.track || '|' || pg_temp.band_dist(d.distance_m), d.finish, d.win_pay
from tmp_d2v d join tmp_ped h on h.horse_name = d.horse_name and h.pk = pg_temp.ped_key(d.birth_date, d.race_date, d.age)
where pg_temp.band_dist(d.distance_m) is not null;
insert into tmp_kv
select 'bv', h.broodmare_sire, d.track || '|' || pg_temp.band_dist(d.distance_m), d.finish, d.win_pay
from tmp_d2v d join tmp_ped h on h.horse_name = d.horse_name and h.pk = pg_temp.ped_key(d.birth_date, d.race_date, d.age)
where pg_temp.band_dist(d.distance_m) is not null;

-- td 厩舎の新馬戦 / br 生産牧場 / jk 騎手×場の新馬戦(S)
insert into tmp_kv select 'td', s.trainer, '', s.finish, s.win_pay from tmp_sj s;   -- 厩舎は地元の場で走る= 場の数え始めに合わせる(10/2)
insert into tmp_kv
select 'br', h.breeder, '', s.finish, s.win_pay
from tmp_s s join tmp_ped h on h.horse_name = s.horse_name and h.pk = pg_temp.ped_key(s.birth_date, s.race_date, s.age);
insert into tmp_kv select 'jk', s.jockey, s.track, s.finish, s.win_pay from tmp_sj s;

-- nj 能検の騎手→初戦の騎手(同じ= same / 替わった= chg)。a= 調教師と '*'。索引に j の無い馬は数えない
-- §304c(10/2 ユーザー指示) nj/nq/nw/ka/kt/nc に a='v:'||初出走の場 を足す(画面の比べ表・カードはこの場で数える)。接頭辞= 調教師名・地区との字の衝突よけ
insert into tmp_kv
select 'nj', v.a, case when regexp_replace(coalesce(x.jockey, ''), '\s', '', 'g') = x.nk_j then 'same' else 'chg' end,
       x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.trainer), ('*'), (case when x.race_date >= coalesce((select z.from_date from tmp_sand z where z.track = x.track), x.race_date) then 'v:' || x.track end)) v(a)
where x.nk_j is not null and x.nk_j <> '' and x.jockey is not null and x.jockey <> '';

-- nr 日全体順位帯 / nw 週数帯 / nc 回数 / ka3 上がり順位 / kt3 テン1F 順位。a= 地区と '*'
insert into tmp_kv
select 'nr', v.a, pg_temp.band_day(x.dr, x.dn), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*')) v(a);
-- §304c nq 能検の時計 案 C の帯(top30/mid/low)。a= 地区と '*'。⛔nr は残す
insert into tmp_kv
select 'nq', v.a, pg_temp.band_pct(q.q), x.finish, x.win_pay
from tmp_dn x join tmp_nq q on q.horse_name = x.horse_name and q.birth_date is not distinct from x.birth_date
cross join lateral (values (x.nk_d), ('*'), (case when x.race_date >= coalesce((select z.from_date from tmp_sand z where z.track = x.track), x.race_date) then 'v:' || x.track end)) v(a);
-- (10/2 ユーザー決定) nw だけ・兵庫だけ= 能検の記録の始まり+180 日より前の初出走を外す(記録より前に能検を受けた馬が入らず「9週〜」が少なく出るため)。
--   外すのは a= 'hyogo'・'v:園田'・'v:姫路' の行だけ。'*' とほかの地区・ほかの kind は変えない。画面の見出しは 'win' 行の nw_from/nw_label
drop table if exists tmp_nwh;
create temp table tmp_nwh as
select (min(k.date) + 180)::date as d from public.noken_recs k where k.d = 'hyogo';
insert into tmp_kv
select 'nw', v.a, pg_temp.band_week(x.race_date - x.nk_date), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*'), (case when x.race_date >= coalesce((select z.from_date from tmp_sand z where z.track = x.track), x.race_date) then 'v:' || x.track end)) v(a)
where not (coalesce(v.a, '') in ('hyogo', 'v:園田', 'v:姫路') and x.race_date < coalesce((select d from tmp_nwh), x.race_date));
insert into tmp_kv
select 'nc', v.a, pg_temp.band_cnt(x.nk_cnt), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*'), (case when x.race_date >= coalesce((select z.from_date from tmp_sand z where z.track = x.track), x.race_date) then 'v:' || x.track end)) v(a);
-- ka3 上がりの順位 / kt3 テン1F の順位(1位/2位/3位以下・10/2)。§304d au(落札価格帯)は 10/2 ユーザー決定で消した(落札額は馬柱のセール枠)
insert into tmp_kv
select 'ka3', v.a, pg_temp.band_rank3(x.ar), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*'), (case when x.race_date >= coalesce((select z.from_date from tmp_sand z where z.track = x.track), x.race_date) then 'v:' || x.track end)) v(a);
insert into tmp_kv
select 'kt3', v.a, pg_temp.band_rank3(x.t1r), x.finish, x.win_pay
from tmp_dn x cross join lateral (values (x.nk_d), ('*'), (case when x.race_date >= coalesce((select z.from_date from tmp_sand z where z.track = x.track), x.race_date) then 'v:' || x.track end)) v(a);

-- dm 兄姉の初戦(Dall・a= 母)。sib= 新しい順に最大 5 頭 {h 馬名, d 初戦日, t 場, f 着(中止・失格は null), p 人気}
drop table if exists tmp_dm;
create temp table tmp_dm as
select h.dam, d.*, row_number() over (partition by h.dam order by d.race_date desc, d.horse_name) as rn
from tmp_dall d join tmp_ped h on h.horse_name = d.horse_name and h.pk = pg_temp.ped_key(d.birth_date, d.race_date, d.age)
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


-- 場ごとの数え始め(画面の見出し用・10/2)。stats= {from, label= 父・母父・厩舎・騎手の行の見出し, nk_from, nk_label= 能検の比べ表の見出し}
insert into public.nar_shinba_stats (kind, a, b, stats, as_of, updated_at)
select 'win', t.track, '',
       jsonb_build_object(
         'from', f.d,
         'label', case when s.track is not null then '豪州産の砂に変わった' || to_char(f.d, 'YYYY"年"FMMM"月から"') else '前日までの5年' end,
         'nk_from', coalesce(case when s.track is not null and s.from_date > g.d then s.from_date end, g.d),
         'nk_label', case when g.d is null then '能検の記録なし'
                          when s.track is not null and s.from_date > g.d then '豪州産の砂に変わった' || to_char(s.from_date, 'YYYY"年"FMMM"月から"')
                          else to_char(g.d, 'YYYY"年"FMMM"月から"') end)
       -- nw(能検から今回まで)だけの始まり= 兵庫の場だけ(10/2)。ほかの場は足さない(画面は nk_label のまま)
       || case when t.track in ('園田', '姫路') and h.d is not null
               then jsonb_build_object('nw_from', h.d, 'nw_label', to_char(h.d, 'YYYY"年"FMMM"月から"'))
               else '{}'::jsonb end,
       current_date, now()
from (select distinct track from tmp_sr) t
left join tmp_sand s on s.track = t.track
cross join tmp_sw w
cross join tmp_nwh h
cross join lateral (select coalesce(s.from_date, w.sv_from) as d) f
-- g= その場の地区の能検の記録の一番古い日(地区ごとに始まりが違う= 船橋・川崎・浦和は 2026-01 から・10/2)。
--   ⛔その場で初出走した馬の能検の日の最小にしない= 他地区で能検を受けた少数の馬で古い日に引っぱられる(船橋が 2024-07 になった)
cross join lateral (select min(k.date) as d from public.noken_recs k
                    where k.d = case t.track when '船橋' then 'funabashi' when '大井' then 'ooi' when '川崎' then 'kawasaki' when '浦和' then 'urawa'
                                  when '門別' then 'monbetsu' when '園田' then 'hyogo' when '姫路' then 'hyogo' when '名古屋' then 'nagoya'
                                  when '笠松' then 'kasamatsu' when '金沢' then 'kanazawa' when '高知' then 'kochi' when '佐賀' then 'saga'
                                  when '盛岡' then 'iwate' when '水沢' then 'iwate' when '帯広ば' then 'banei' end) g;

commit;

select kind, count(*) as rows, sum((stats->>'n')::int) as runs from public.nar_shinba_stats group by kind order by kind;
