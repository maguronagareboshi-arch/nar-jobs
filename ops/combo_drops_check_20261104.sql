-- ops: public.combo_drops の照合用(2026-11-05)。関数を作る前に、同じ本体を 11/4 全場で手で流す。
-- ⛔読み取りだけ。本体は ops/combo_drops_fn.sql の「ここから下」〜「ここまで」と同じ(変えるときは両方)。
-- 期待値(仕様): 28R・58 組(三連複 11・三連単 11・馬連 10・馬単 13・ワイド 13)。
--   ※ 組の数は「組ごとに最も下がった 1 回だけ残す」後の数(Python 側の処理と同じ dedupe を下でやる)。
--   ※ 「59R 中」の 59 は Python 側の races_all(nar_races の cancelled が null のレース数)で見る。

with params as (
  select date '2026-11-04' as d, null::text[] as trs
),
-- ↓↓↓ ここから下は ops/combo_drops_fn.sql と同じ
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
lg as (
  -- 2026-11-05 自己結合は 2 分で時間切れ→窓関数で 1 つ前の刻みを見る(11/4 で 28R・58 組を確認)
  select ex.*, lag(i) over w as pi, lag(o) over w as po, lag(r) over w as pr, lag(observed_at) over w as pt
    from ex
  window w as (partition by track, race_no, kind, c order by i)
),
pairs as (
  select track, race_no, kind, pt as t0, observed_at as t1, fin, has_final,
         c, po as o0, pr as r0, o as o1, r as r1
    from lg
   where pi = i - 1 and po > 0 and o > 0 and r <= 5
     and o <= po * 0.5 + 1e-9
)
select count(distinct (track, race_no)) as n_races,
       count(*) as n_combos,
       count(*) filter (where kind = 'sanrenpuku') as sanrenpuku,
       count(*) filter (where kind = 'sanrentan') as sanrentan,
       count(*) filter (where kind = 'umaren') as umaren,
       count(*) filter (where kind = 'umatan') as umatan,
       count(*) filter (where kind = 'wide') as wide
  from best;
