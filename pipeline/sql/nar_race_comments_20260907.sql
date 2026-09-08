-- §120 高知のレース後コメント(主催者公式)。**1 行 = 1 レースの 1 頭**。
-- 出どころ= 高知県競馬組合の公式サイト `https://www.keiba.or.jp/?postracecomment=YYYYMMDDRR`(2024年3月から)。
-- 記事の中身は「騎手のコメントを元騎手の妹尾将充が聴き取り書き起こしたもの」= **公式の結果ではない**。
-- ⛔`nar_runs` には混ぜない(出どころが違う)。⛔本文は原文のまま入れる(言い換え・要約・切り詰めをしない)。
-- ⛔記事末尾の「この記事は、…」の 1 文は行に入れない(画面が固定の断りとして出す)。
-- ⛔`umaban` と `horse_name` が **nar_runs のその走と両方そろって一致した行だけ**入れる(cloud/kochi_comments.py)。
-- 適用= Fable(dbadmin.py)。⛔このファイルは書いただけで、Opus は流していません。

-- BEGIN §120 RACE COMMENTS
begin;

create table if not exists public.nar_race_comments (
  track       text        not null,
  race_date   date        not null,
  race_no     smallint    not null,
  umaban      smallint    not null,
  horse_name  text        not null,
  jockey      text,
  comment     text        not null,
  source_url  text        not null,
  fetched_at  timestamptz not null default now(),

  primary key (track, race_date, race_no, umaban),

  constraint nar_race_comments_track_ck
    check (btrim(track) <> ''),
  constraint nar_race_comments_race_no_ck
    check (race_no between 1 and 12),
  constraint nar_race_comments_umaban_ck
    check (umaban between 1 and 16),
  constraint nar_race_comments_horse_name_ck
    check (btrim(horse_name) <> ''),
  -- ⛔空のコメントは行にしない(未掲載は「無い」ままにする= 取り込み側が次回また見る)
  constraint nar_race_comments_comment_ck
    check (char_length(btrim(comment)) between 1 and 2000),
  constraint nar_race_comments_source_url_ck
    check (source_url like 'https://www.keiba.or.jp/%')
);

-- 引き方は 2 つだけ: ①レースページ(track+date+R・PK の頭で足りる) ②馬ページ(馬名で束ねて引く)
create index if not exists nar_race_comments_horse_idx
  on public.nar_race_comments (horse_name, race_date desc);

alter table public.nar_race_comments enable row level security;
drop policy if exists nar_race_comments_read on public.nar_race_comments;
create policy nar_race_comments_read on public.nar_race_comments
  for select to anon, authenticated using (true);
revoke all on table public.nar_race_comments from public, anon, authenticated;
grant select on public.nar_race_comments to anon, authenticated;
grant select, insert, update, delete on public.nar_race_comments to service_role;

commit;
-- END §120 RACE COMMENTS
