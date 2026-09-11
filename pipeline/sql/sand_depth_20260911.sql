-- §146 砂厚の履歴(2026-09-11)。高知・名古屋・笠松の主催者公式が出す「砂厚の測定表」と「砂の補充・整備」を
--   1 行ずつ残す表。⛔主催者は古い測定表を消す(名古屋= 一覧に 3 本・笠松= 最新 1 本だけ)ので、
--   当サイトが写しておかないと履歴にならない= この表が履歴そのもの。**insert だけ・書き換えない**。
-- 1 行= 1 場 × 1 日 × 1 種類 × 1 地点(section)。測定でない行(補充・整備)は section が null。
--   offsets= 内柵からの距離(m)・vals= その位置の砂厚(cm)。⛔2 つは同じ長さ(check)。
--   avg= **公式に印字された平均だけ**(笠松)。印字がなければ null= 画面側で計算する(公式の数字と当サイトの計算を混ぜない)。
-- 適用= Fable が dbadmin.py file で本番(nar)へ。冪等。閲覧者(anon)は select だけ。
begin;
create table if not exists public.nar_sand_depth (
  id          bigserial primary key,
  track       text        not null,                       -- 高知 / 名古屋 / 笠松(nar_runs.track と同じ字)
  d           date        not null,                       -- 測定日(補充・整備は実施日)
  kind        text        not null,                       -- measure / refill / maintenance
  section     text,                                       -- 地点名(公式の字のまま: 向正面 / ゴール前 / ⑤ …)。測定以外は null
  offsets     numeric[],                                  -- 内柵からの距離 m(高知・名古屋 1..15 / 笠松 1,3,5,7)
  vals        numeric[],                                  -- 砂厚 cm(offsets と同じ長さ)
  avg         numeric,                                    -- 公式に印字された平均だけ(無ければ null)
  cond        text,                                       -- 馬場状態(良/稍重/重/不良)。書いてあれば
  weather     text,                                       -- 天候。書いてあれば
  t           text,                                       -- 測定時刻(公式の字のまま「13:00〜14:00」)。書いてあれば
  note        text,                                       -- 補充・整備の内容(「クッション砂 130t を補充」「埒下砂掻き出しおよび砂厚調整(全周)」)
  amount_t    numeric,                                    -- 補充量(トン)。書いてあれば
  title       text,                                       -- 公式の見出し(そのまま)
  src         text        not null,                       -- 公式ページ(または PDF)の URL
  fetched_at  timestamptz not null default now(),
  constraint nar_sand_depth_kind_ck check (kind in ('measure', 'refill', 'maintenance')),
  constraint nar_sand_depth_track_ck check (track in ('高知', '名古屋', '笠松')),
  constraint nar_sand_depth_len_ck check (
    (offsets is null and vals is null)
    or (offsets is not null and vals is not null and cardinality(offsets) = cardinality(vals))
  ),
  constraint nar_sand_depth_measure_ck check (kind <> 'measure' or (section is not null and vals is not null))
);
-- 二重を器で止める(同じ日・同じ地点は 1 行)。section が null の行は '' として比べる
create unique index if not exists nar_sand_depth_key
  on public.nar_sand_depth (track, d, kind, coalesce(section, ''));
create index if not exists nar_sand_depth_track_d on public.nar_sand_depth (track, d desc);

alter table public.nar_sand_depth enable row level security;
drop policy if exists nar_sand_depth_read on public.nar_sand_depth;
create policy nar_sand_depth_read on public.nar_sand_depth for select to anon, authenticated using (true);
revoke all on table public.nar_sand_depth from public, anon, authenticated;
grant select on public.nar_sand_depth to anon, authenticated;
grant select, insert, update, delete on public.nar_sand_depth to service_role;
grant usage, select on sequence public.nar_sand_depth_id_seq to service_role;
commit;
