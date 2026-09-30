-- §移籍まとめ D2(2026-09-30)。公式 keiba.go.jp の現役管理馬一覧(cloud/trainer_roster.py が毎日書く)。
-- ⛔本番への適用は本体が手動モードで(下請けは流していない)。

create table if not exists nar_trainers (
  license_no   text primary key,            -- 公式の免許番号(k_trainerLicenseNo)
  trainer_name text not null,               -- 正式名(字間の空白を落とした形。例 阿井正雄)
  area         text not null,               -- 公式の所属(船橋・北海道・ばんえい …= nar_runs.trainer_area と同じ言葉)
  short_guess  text,                        -- 名前から作った 3 文字の候補(姓[:2]+名[:3-len])。確定ではない
  short_name   text,                        -- nar_runs.trainer と突き合わせて確定した略称。決まらない人は null
  updated_at   timestamptz not null default now()
);
create index if not exists nar_trainers_area_short on nar_trainers (area, short_name);

create table if not exists nar_trainer_roster (
  lineage_code text primary key,            -- 公式の馬の番号(k_lineageLoginCode)。1 頭は 1 厩舎
  license_no   text not null,
  trainer_name text not null,
  area         text not null,
  horse_name   text not null,
  sex_age      text,                        -- 例 牡4・セン7
  birth_year   integer,
  sire         text,
  dam          text,
  fetched_on   date not null,               -- この日の一覧に載っていた
  missing_since date                        -- D3: 取れた人の一覧に初めて居なかった夜。2 夜続けば行を消す(載り直せば null)
);
alter table nar_trainer_roster add column if not exists missing_since date;
create index if not exists nar_trainer_roster_license on nar_trainer_roster (license_no);
create index if not exists nar_trainer_roster_horse on nar_trainer_roster (horse_name, birth_year);

alter table nar_trainers enable row level security;
alter table nar_trainer_roster enable row level security;
drop policy if exists nar_trainers_read on nar_trainers;
create policy nar_trainers_read on nar_trainers for select using (true);
drop policy if exists nar_trainer_roster_read on nar_trainer_roster;
create policy nar_trainer_roster_read on nar_trainer_roster for select using (true);

-- §移籍まとめ D3(9/30): 名簿の差分(cloud/trainer_roster.py が書き換え前に前夜と比べて追記)。
--   別の免許番号に載った= from/to とも値・新しく載った= from が null・消えた= to が null。
--   ⛔過去は遡れない(取り始めの日から)。初回の夜は出さない。1 頭 1 日 1 行= 打ち直しは重複を無視(冪等)。
--   取れなかった人は持ち越し・差分を出さない/新しく載ったは直近 14 日の記録で from を埋める/消えたは 2 夜続けて居ないときだけ。
create table if not exists nar_roster_moves (
  lineage_code text not null,               -- 公式の馬の番号(k_lineageLoginCode)
  horse_name   text not null,
  from_license text,                        -- 前夜の免許番号(新しく載ったときは null)
  to_license   text,                        -- 今夜の免許番号(消えたときは null)
  from_area    text,
  to_area      text,
  seen_on      date not null,               -- 差分を見つけた日(JST)
  primary key (lineage_code, seen_on)
);
create index if not exists nar_roster_moves_seen on nar_roster_moves (seen_on);
create index if not exists nar_roster_moves_to_area on nar_roster_moves (to_area, seen_on);
alter table nar_roster_moves enable row level security;
drop policy if exists nar_roster_moves_read on nar_roster_moves;
create policy nar_roster_moves_read on nar_roster_moves for select using (true);

-- 略称の確定(便が毎日 rpc で呼ぶ)。当て推量しない:
--   ① 名前から作った候補 short_guess が、同じ地区の他の人と重ならない
--   ② その人の在厩馬の「最後の地方の走」の調教師(nar_runs.trainer・同じ地区)で最も多いものが候補と一致
--   両方を満たす人だけ short_name を入れ、ほかは null に戻す。戻り値= 確定した人数。
create or replace function nar_trainers_match_short() returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  with last_run as (
    select t.license_no, r.trainer
    from nar_trainer_roster t
    join lateral (select r.trainer, r.trainer_area from nar_runs r
                   where r.horse_name = t.horse_name and extract(year from r.birth_date) = t.birth_year
                     and r.trainer_area is distinct from 'JRA'
                   order by r.race_date desc, r.race_no desc limit 1) r on r.trainer_area = t.area
  ), top as (
    select distinct on (license_no) license_no, trainer
    from (select license_no, trainer, count(*) c from last_run group by 1, 2) x
    order by license_no, c desc, trainer
  ), ok as (
    select tr.license_no, tr.short_guess
    from nar_trainers tr join top using (license_no)
    where tr.short_guess is not null and top.trainer = tr.short_guess
      and not exists (select 1 from nar_trainers o
                       where o.area = tr.area and o.short_guess = tr.short_guess and o.license_no <> tr.license_no)
  )
  update nar_trainers tr set short_name = ok.short_guess
  from nar_trainers t2 left join ok using (license_no)
  where t2.license_no = tr.license_no and tr.short_name is distinct from ok.short_guess;
  select count(*) into n from nar_trainers where short_name is not null;
  return n;
end $$;
revoke all on function nar_trainers_match_short() from public, anon, authenticated;

-- 便の行(/update-times の行は nar-viewer 側で足す)
-- insert into nar_job_heartbeat (job) values ('trainer_roster') on conflict do nothing;  -- nar_beat が初回に作るなら不要
