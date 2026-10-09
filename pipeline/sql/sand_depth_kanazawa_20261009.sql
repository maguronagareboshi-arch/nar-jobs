-- 2026-10-09 金沢の砂厚(作業簡略図の列ごと)を nar_sand_depth に入れられるようにする。⛔未適用(本体/ユーザーが手動で)
--   金沢= 1m おきでなく「ならし作業の列(内から 6 列)」の値で、幅のある値(13~14㎝)がある。
--   vals= 下限・vals_hi= 上限(幅の無い値は同じ)。offsets= 列の番号 1..6(⛔m ではない)。section= '全周'。
--   既存 3 場の行は vals_hi が null のまま= 読み手は変わらない。冪等。
begin;
alter table public.nar_sand_depth add column if not exists vals_hi numeric[];   -- 上限(金沢)。無ければ null
alter table public.nar_sand_depth drop constraint if exists nar_sand_depth_track_ck;
alter table public.nar_sand_depth add constraint nar_sand_depth_track_ck
  check (track in ('高知', '名古屋', '笠松', '金沢'));
alter table public.nar_sand_depth drop constraint if exists nar_sand_depth_hi_ck;
alter table public.nar_sand_depth add constraint nar_sand_depth_hi_ck
  check (vals_hi is null or (vals is not null and cardinality(vals_hi) = cardinality(vals)));
comment on column public.nar_sand_depth.offsets is '内柵からの距離 m(高知・名古屋・笠松)/ 金沢は列の番号 1..6(内から)';
comment on column public.nar_sand_depth.vals_hi is '砂厚の上限 cm(金沢の 13~14㎝ の 14)。幅の無い値は vals と同じ・他場は null';
commit;
