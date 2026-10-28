-- 場ごとの直線の向き(nar-viewer js/weather-venues.js の値を写したもの・2026-10-28)
-- bearing= 直線を走る向き(北 0°・時計回り)。左右両回りの大井は右回りの直線(bearing)を使う(wind-core relativeLabel と同じ)。
-- leftward= wind-core runsLeftward(turn が right か straight)= 図で ← に走る場。風の成分の計算には使わない(表示用)。
-- track= nar_races.track(帯広は「帯広ば」・cloud/wind_store.py venue_of と同じ対応)。venue= nar_wind_obs.venue。
create table if not exists nar_venue_straight (
  venue    text primary key,
  track    text not null unique,
  bearing  numeric not null,
  leftward boolean not null
);
insert into nar_venue_straight (venue, track, bearing, leftward) values
  ('obihiro','帯広ば',265,true),
  ('monbetsu','門別',120,true),
  ('morioka','盛岡',225,false),
  ('mizusawa','水沢',325,true),
  ('urawa','浦和',130,false),
  ('funabashi','船橋',265,false),
  ('ooi','大井',60,true),
  ('kawasaki','川崎',265,false),
  ('kanazawa','金沢',0,true),
  ('kasamatsu','笠松',45,true),
  ('nagoya','名古屋',80,true),
  ('sonoda','園田',270,true),
  ('himeji','姫路',265,true),
  ('kochi','高知',55,true),
  ('saga','佐賀',35,true)
on conflict (venue) do update set track=excluded.track, bearing=excluded.bearing, leftward=excluded.leftward;
