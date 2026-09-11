-- §147 C 高配当ランキング(2026-09-11)。直近 7 日(JST の昨日まで)の公式の払戻を券種ごとに高い順 10 件、
--   nar_meta 'big_payouts' に 1 行で置く。⛔当サイトは選んでいない= 公式の払戻の数字をそのまま並べるだけ。
--   形= {built, since, until, kinds:{trifecta:[{d,track,no,c,y,p}…], trio, exacta, quinella, win}}(p= 人気。無ければ null)
-- 朝の便(nar-refresh の psql 段)で毎日流す。冪等(全面作り直し)。所要 1 秒級(7 日ぶん・払戻の行だけ)。
begin;
create temp table tmp_bp as
select rp.track, rp.race_date, rp.race_no, e.v->>'t' as t, e.v->>'c' as c, (e.v->>'y')::int as y,
       case when e.v ? 'p' and (e.v->>'p') ~ '^[0-9]+$' then (e.v->>'p')::int end as p
from public.nar_race_payouts rp
cross join lateral jsonb_array_elements(rp.payouts) as e(v)
where rp.race_date between ((now() at time zone 'Asia/Tokyo')::date - 7) and ((now() at time zone 'Asia/Tokyo')::date - 1)
  and e.v->>'t' in ('trifecta', 'trio', 'exacta', 'quinella', 'win')
  and (e.v->>'y') ~ '^[0-9]+$';

insert into public.nar_meta (key, value, updated_at)
select 'big_payouts',
  jsonb_build_object(
    'built', to_char(now() at time zone 'Asia/Tokyo', 'YYYY-MM-DD"T"HH24:MI:SS+09:00'),
    'since', to_char((now() at time zone 'Asia/Tokyo')::date - 7, 'YYYY-MM-DD'),
    'until', to_char((now() at time zone 'Asia/Tokyo')::date - 1, 'YYYY-MM-DD'),
    'kinds', coalesce((
      select jsonb_object_agg(t, items) from (
        select t, jsonb_agg(jsonb_build_object('d', race_date, 'track', track, 'no', race_no, 'c', c, 'y', y, 'p', p)
                            order by y desc, race_date desc, track, race_no) as items
        from (
          select *, row_number() over (partition by t order by y desc, race_date desc, track, race_no) as rn
          from tmp_bp
        ) r
        where rn <= 10
        group by t
      ) k
    ), '{}'::jsonb)
  ),
  now()
on conflict (key) do update set value = excluded.value, updated_at = excluded.updated_at;

select 'big_payouts' as key, count(*) as rows_7d, max(y) as max_y from tmp_bp;
commit;
