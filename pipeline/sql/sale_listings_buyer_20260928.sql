-- 2026-09-28 §302: sale_listings に購買者(落札の行だけ・JBIS の字のまま)。ユーザー決定「埋め直す」。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等。メタデータだけ(書き換えなし・一瞬)。
-- ⛔この列が無いまま枝を master に入れると週次便 sale-listings.yml の upsert が落ちる= 先にこれを流す。
alter table public.sale_listings add column if not exists buyer text;
