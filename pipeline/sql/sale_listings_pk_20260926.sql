-- 2026-09-26 sale_listings の主キーに jbis_horse_id を足す(未実行・本体が流す)。
-- 理由: 2014 北海道オータムセール(market_code 11B4)で上場番号 1〜272 が 2 頭ずつ(272 組 544 行)。
--   2 頭は age_class・開催日・市場名まで同じで、区分や部で分けられる列が無い(JBIS のページも表 1 枚)。
--   jbis_horse_id は全 90,940 行で空が 0 = これを足せば一意になる。
-- 流した後: cloud/sale_listings.py の upsert の on_conflict を "sale_year,market_code,hip_no,jbis_horse_id" に変え、
--   手元の sale_listings_linked_v2.csv から 11B4 の 544 行を upsert する。
-- 表は 9 万行・索引の作り直しだけ= 軽い。
begin;
alter table public.sale_listings alter column jbis_horse_id set not null;
alter table public.sale_listings drop constraint sale_listings_pkey;
alter table public.sale_listings add primary key (sale_year, market_code, hip_no, jbis_horse_id);
commit;
