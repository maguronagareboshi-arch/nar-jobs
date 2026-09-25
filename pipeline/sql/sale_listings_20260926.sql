-- 2026-09-26 枝 horse-sales: セール(市場取引)の上場記録。1 行= 上場 1 回(落札/主取り/欠場)。
-- 出典= JBIS-Search の市場取引(HBA 5 市場・八戸・セレクト・千葉・九州・ブリーズアップ・ミックス・ジェイエス 等・2003〜)。
--   ユーザーが JBIS・HBA・JRHA の掲載許可を取得済み。購買者名は持たない。
-- 書き手= cloud/sale_listings.py(初回は手元で load --apply・以後は便 sale-listings.yml が毎週)。
-- 読み手= viewer(anon の select だけ)。馬のページの札= 落札/主取り/欠場/市場の上場記録なし(「庭先」と断定しない)。
-- 既存の auction_sales(楽天・SAT・hba・jrha の落札だけ)とは別の器。hba/jrha の落札は両方に載る(どちらを出すかは未決)。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
create table if not exists public.sale_listings (
  sale_year          integer not null,           -- 開催年
  market_code        text    not null,           -- JBIS の市場コード(例 11B4= 北海道オータムセール 1 歳)
  hip_no             integer not null,           -- 上場番号
  market_name        text    not null,           -- 例 '北海道オータムセール'
  breed              text,                       -- 'サラブレッド' / 'アラブ'
  age_class          text,                       -- '当歳' '１歳' '２歳' '繁殖牝馬' など(出典の字のまま)
  sale_start         date,                       -- 開催の初日
  sale_end           date,                       -- 開催の最終日
  sale_date          date,                       -- その馬の上場日(HBA 名簿があるときだけ)
  horse_name         text,                       -- 馬名(繁殖牝馬の市場だけ。子馬の市場は名前が付く前= null)
  dam                text,                       -- 母名(出典の字のまま・(IRE) など付き)
  dam_norm           text,                       -- 母名(NFKC・末尾の国名を外す)= ひも付けの鍵
  sire               text,
  sex                text,                       -- 牡/牝/セ
  color              text,
  birth_year         integer,                    -- 開催年 - 年齢(繁殖牝馬の市場は出典の生年)
  birth_date         date,                       -- 生年月日(HBA 名簿があるときだけ)
  breeder            text,                       -- 生産者(今の出典には無い= 空。後で別の出典から)
  seller             text,                       -- 販売申込者(出典の字のまま)
  result             text check (result in ('落札', '主取り', '欠場')),
  price_yen_tax_incl integer,                    -- 落札額(円・税込= JBIS の表示のまま)。主取り・欠場は null
  jbis_horse_id      text,                       -- JBIS の馬 id(血統登録番号ではない)
  horse_code         text,                       -- 当サイトの馬(nar_horse_profiles.code)。結べないときは null
  link_method        text,                       -- 'dam+sex+birth_date' / 'dam+sex+birth_year' / 'multi'(候補 2 頭以上= 結ばない)/ null
  source_url         text,
  fetched_at         timestamptz not null default now(),
  primary key (sale_year, market_code, hip_no)
);
create index if not exists sale_listings_horse on public.sale_listings (horse_code) where horse_code is not null;
create index if not exists sale_listings_dam on public.sale_listings (dam_norm, birth_year);
create index if not exists sale_listings_unlinked on public.sale_listings (birth_year) where horse_code is null;
alter table public.sale_listings enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'sale_listings' and policyname = 'sale_listings_read') then
    create policy sale_listings_read on public.sale_listings for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.sale_listings from anon, authenticated;
grant select on public.sale_listings to anon, authenticated;
