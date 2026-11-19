-- auction_sales: 中身が同じ上書きは何もしない(Postgres 標準の suppress_redundant_updates_trigger)。2026-11-19 本番に適用済み。
-- 取り込みの便(cloud/auction_load.py)は毎回 全行(11/19 で 63,890 行)を upsert する= 同じ中身でも行を書き直していた。
--   累計 470 万回の update → 自動掃除のたびに推定行数がずれ、11/18・11/19 に集計便の安全柵が誤作動
--   → 予備の便が昼に月次をやり直し → 乗り替わり表の作り直しと DDL が重なって全読み込み 503(11/19 11:13〜11:17)。
-- 便は変えていない(送る量は同じ)。DB が同じ中身の行を書かないだけ。runs_after の更新(auction_after.sql)は値が変わるので通る。
-- 名前の頭の z= ほかの before update の仕掛けより後に動かす。冪等。
set lock_timeout = '5s';
do $$ begin
  if not exists (select 1 from pg_trigger where tgrelid = 'public.auction_sales'::regclass and tgname = 'z_auction_sales_skip_same') then
    create trigger z_auction_sales_skip_same before update on public.auction_sales
      for each row execute function suppress_redundant_updates_trigger();
  end if;
end $$;
