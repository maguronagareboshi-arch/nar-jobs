-- 2026-10-13 nar_runs に騎手の免許番号を足す(同じ略称の 2 人= 山本聡 31220 山本聡紀 / 31139 山本聡哉 を見分ける)。
-- ⛔用意だけ。本番で流すのはユーザー(手動モード)。nar_runs は §240 で区切った親表= 親に足せば子にも入る。
-- 入れ方: 出馬表ページ(cloud/nextday_card.py)の騎手リンク RiderMark?k_riderLicenseNo=N。
--   月次/日次ZIP の CSV には無い= 送らない(null で上書きしない)。DDL 前は load_nar_official が列ごと外して送る。
-- 画面: nar-viewer は select=* で読む(列を並べた select は無い)= 追加の手直しなし。
-- 列を並べた \copy(nar-ai-last.yml・nankan-copy.yml)は列名つきの select なので壊れない。

alter table public.nar_runs add column if not exists jockey_license text;

-- 閲覧用の view / RPC で nar_runs の列を列挙して返すものは無い(pipeline/sql を grep・2026-10-13)= 直す SQL なし。

-- ── 埋め戻し(案・まだ流さない)──────────────────────────────────────────
-- 案 1: 同じ略称が 1 人だけの騎手は nar_persons から 1 本の update で埋める。
--   ⚠nar_persons は現役だけ(k_genneki_flag=1)= 引退騎手は埋まらない。区切った表なので月ごとに分けて流す。
-- update public.nar_runs r set jockey_license = p.license_no
--   from (select name_short, min(license_no) license_no from public.nar_persons
--         where kind = 'jockey' and area <> 'JRA' group by name_short having count(*) = 1) p
--  where r.jockey = p.name_short and r.jockey_license is null
--    and r.race_date >= '2026-10-01' and r.race_date < '2026-11-01';
-- 案 2: 略称が 2 人以上(山本聡・藤田凌など)は過去の成績ページ RaceMarkTable を取り直し、
--   騎手リンクの k_riderLicenseNo を馬番で突き合わせて入れる(該当レースだけ= 件数は少ない)。
-- 案 3: 中央の騎手(交流)は nar_persons の area='JRA' が略称で重なるときがある= 案 2 と同じく取り直しに回す。
