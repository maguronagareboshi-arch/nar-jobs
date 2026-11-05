-- ops: 組の急落(締め切り前の大口)の判定を DB の中でやる関数(2026-11-05・仕様 nar-site SPEC_combo_drop_20261105.md)
--
-- ⛔このファイルは「作っただけ」= まだ本番で流していない。流すのはユーザー(手動モード)。
-- ⛔読み取りだけ。security definer は使わない(呼び手の権限で読む)。
-- 送信量対策: 組のオッズ(1 日約 17MB)を手元へ引かず、拾った組の行だけ返す。
--
-- 判定(仕様どおり)
--   券種= sanrentan / sanrenpuku / umatan / umaren / wide(wakuren は人気順が無いので使わない)。
--   combos の要素: 3 連系 [a,b,c,odds,rank]・2 連系 [a,b,odds,rank]・wide [a,b,lo,rank,hi](lo を使う)。
--   fin= そのレース×券種の f=true の刻みの observed_at(最後のもの)。無ければ nar_races.post_time(JST 'HHMM'・
--        odds_drop.py と同じ発走時刻)。fin−10 分以上の f=false の刻みを observed_at 順に並べ、隣どうしを比べる。
--   拾う= 前>0・後>0・後 ≤ 前×0.5(+1e-9)・後の人気 ≤ 5。
--   組ごとに最も下がった 1 回だけ残す処理・t0/t1/left/focus は Python(cloud/odds_drop.py --combo)側。
--
-- 返り値(1 行= 隣どうしの刻みの組 1 つ)
--   track text, race_no int, kind text, t0 timestamptz(前の刻み), t1 timestamptz(後の刻み),
--   fin timestamptz, has_final boolean(f=true の刻みがあるか), c int[](馬番),
--   o0 numeric, r0 int, o1 numeric, r1 int, ofin numeric(同じ組の最終オッズ・無ければ null)
--
-- 照合: ops/combo_drops_check_20261104.sql(同じ本体を 11/4 で手で流す・28R・58 組になるはず)。
-- 流し方: psql で -f このファイル。冪等(create or replace)。

create or replace function public.combo_drops(p_date date, p_tracks text[] default null)
returns table (
  track text, race_no int, kind text, t0 timestamptz, t1 timestamptz, fin timestamptz, has_final boolean,
  c int[], o0 numeric, r0 int, o1 numeric, r1 int, ofin numeric)
language sql
stable
set search_path = public
as $$
with params as (
  select p_date as d, p_tracks as trs
),
-- ↓↓↓ ここから下は ops/combo_drops_check_20261104.sql と同じ(変えるときは両方)
tk as (
  select t.track, t.race_no, t.kind, t.observed_at, t.f, t.combos
    from public.nar_odds_full_ticks t, params p
   where t.race_date = p.d
     and t.kind in ('sanrentan', 'sanrenpuku', 'umatan', 'umaren', 'wide')
     and (p.trs is null or t.track = any (p.trs))
     and jsonb_typeof(t.combos) = 'array'
),
fin_tick as (
  select distinct on (track, race_no, kind) track, race_no, kind, observed_at as fin_at, combos
    from tk
   where f
   order by track, race_no, kind, observed_at desc
),
post as (
  select r.track, r.race_no,
         ((p.d + make_time(substr(r.post_time, 1, 2)::int, substr(r.post_time, 3, 2)::int, 0))
            at time zone 'Asia/Tokyo') as post_at
    from public.nar_races r, params p
   where r.race_date = p.d
     and r.cancelled is null
     and r.post_time ~ '^([01][0-9]|2[0-3])[0-5][0-9]$'
),
win as (
  select k.track, k.race_no, k.kind, coalesce(ft.fin_at, po.post_at) as fin, (ft.fin_at is not null) as has_final
    from (select distinct track, race_no, kind from tk) k
    left join fin_tick ft using (track, race_no, kind)
    left join post po using (track, race_no)
),
seq as (
  select tk.track, tk.race_no, tk.kind, tk.observed_at, tk.combos, w.fin, w.has_final,
         row_number() over (partition by tk.track, tk.race_no, tk.kind order by tk.observed_at) as i
    from tk
    join win w using (track, race_no, kind)
   where not tk.f
     and w.fin is not null
     and tk.observed_at >= w.fin - interval '10 minutes'
),
ex as (
  select s.track, s.race_no, s.kind, s.i, s.observed_at, s.fin, s.has_final,
         case when z.oi = 3 then array[(x.v->>0)::int, (x.v->>1)::int, (x.v->>2)::int]
              else array[(x.v->>0)::int, (x.v->>1)::int] end as c,
         case when y.os ~ '^[0-9]+(\.[0-9]+)?$' then y.os::numeric end as o,
         case when y.rs ~ '^[0-9]+$' then y.rs::int end as r
    from seq s
    cross join lateral (select case when s.kind in ('sanrentan', 'sanrenpuku') then 3 else 2 end as oi) z
    cross join lateral jsonb_array_elements(s.combos) x(v)
    cross join lateral (select x.v->>z.oi as os, x.v->>(z.oi + 1) as rs) y
   where x.v->>0 ~ '^[0-9]+$' and x.v->>1 ~ '^[0-9]+$' and (z.oi = 2 or x.v->>2 ~ '^[0-9]+$')
),
fx as (
  select ft.track, ft.race_no, ft.kind,
         case when z.oi = 3 then array[(x.v->>0)::int, (x.v->>1)::int, (x.v->>2)::int]
              else array[(x.v->>0)::int, (x.v->>1)::int] end as c,
         case when (x.v->>z.oi) ~ '^[0-9]+(\.[0-9]+)?$' then (x.v->>z.oi)::numeric end as o
    from fin_tick ft
    cross join lateral (select case when ft.kind in ('sanrentan', 'sanrenpuku') then 3 else 2 end as oi) z
    cross join lateral jsonb_array_elements(ft.combos) x(v)
   where x.v->>0 ~ '^[0-9]+$' and x.v->>1 ~ '^[0-9]+$' and (z.oi = 2 or x.v->>2 ~ '^[0-9]+$')
),
pairs as (
  select a.track, a.race_no, a.kind, a.observed_at as t0, b.observed_at as t1, a.fin, a.has_final,
         a.c, a.o as o0, a.r as r0, b.o as o1, b.r as r1
    from ex a
    join (select * from ex where r <= 5 and o > 0) b
      on b.track = a.track and b.race_no = a.race_no and b.kind = a.kind and b.i = a.i + 1 and b.c = a.c
   where a.o > 0
     and b.o <= a.o * 0.5 + 1e-9
)
select p.track::text, p.race_no::int, p.kind::text, p.t0, p.t1, p.fin, p.has_final,
       p.c, p.o0, p.r0, p.o1, p.r1, f.o as ofin
  from pairs p
  left join fx f on f.track = p.track and f.race_no = p.race_no and f.kind = p.kind and f.c = p.c
 order by p.track, p.race_no, p.kind, p.t1, p.c
-- ↑↑↑ ここまで同じ
$$;

revoke all on function public.combo_drops(date, text[]) from public;
grant execute on function public.combo_drops(date, text[]) to anon, service_role;

-- 戻し方: drop function if exists public.combo_drops(date, text[]);
