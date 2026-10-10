# -*- coding: utf-8 -*-
"""§54.3-bc: 移籍・在籍変化の収集(2026-08-29)。1本で3種類を nar_horse_changes へ追記する。

  transfer_in(転入)  = nar_runs の trainer_area が直前走と違う      → 遡れる
  stable_change(転厩)= 同じ地区で trainer が変わった               → 遡れる
  jra_in(中央→地方)= 中央(nar_jra_runs+nar_runs の trainer_area='JRA')の走のあと、地方の走が来た日   → 遡れる
                        (§移籍まとめ D1・2026-09-30。下の JRA_IN_SQL の注記)
  owner_change(馬主) = nar_horses.owner の日次スナップショット差分  → ⛔遡れない(owner は最新値の上書きで
                        履歴が無い)= **今日から録り始めるだけ**。過去の馬主変更は取り戻せない

⛔検出は DB 側の1文(window 関数)でやる= 出力は1日約9件なのに入力が17万行(実測 400日=173,613行/2,070ms)
  あり、REST で引いてブラウザや Python で数えると 1000行上限(#8)に真正面から当たる。
⛔鍵は (horse_name, birth_date)= 同名で生年が違う馬が34名。⛔null の trainer/trainer_area は変化と数えない。
⛔冪等= 一意索引 + on conflict do nothing(同じ日を2回流しても増えない)。

  py -3.12 -X utf8 cloud/horse_changes.py --env pipeline/.env.nar                # ドライラン(検出件数だけ・書かない)
  py -3.12 -X utf8 cloud/horse_changes.py --env pipeline/.env.nar --apply        # 実弾(既定=直近7日+馬主差分)
  py -3.12 -X utf8 cloud/horse_changes.py --env pipeline/.env.nar --since 2025-08-29 --apply   # 遡り(1年から)
環境変数: SUPABASE_DB_PASSWORD(pipeline/.env.nar / GitHub Secrets NAR_DB_PASSWORD)
終了コード: 0 正常 / 1 失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import sys

import pg8000.native

JST = dt.timezone(dt.timedelta(hours=9))
HOST = "aws-0-ap-northeast-1.pooler.supabase.com"
USER = "postgres.qgsnsdjvzzeazbazjlwa"

# 一意索引の式と1字も違えないこと(on conflict が索引を見つけられなくなる)
CONFLICT = "(horse_name, coalesce(birth_date, date '0001-01-01'), race_date, kind)"

# 転入・転厩の検出(直前走との比較)。⛔null は「変化」と数えない(欠測を移籍と言わない)
DETECT_SQL = f"""
with r as (
  select horse_name, birth_date, race_date, trainer, trainer_area,
         lag(trainer_area) over w as p_area,
         lag(trainer)      over w as p_trainer,
         lag(race_date)    over w as p_date
  from nar_runs
  where birth_date is not null
  window w as (partition by horse_name, birth_date order by race_date, race_no)
)
select horse_name, birth_date, race_date,
       case when trainer_area <> p_area then 'transfer_in' else 'stable_change' end as kind,
       case when trainer_area <> p_area then p_area else p_trainer end as from_value,
       case when trainer_area <> p_area then trainer_area else trainer end as to_value
from r
where p_date is not null
  and race_date >= :since
  and ((trainer_area is not null and p_area is not null and trainer_area <> p_area
        and p_area <> 'JRA')   -- 中央から来た転入は jra_in に寄せる(下の注記)
    or (trainer_area is not null and p_area is not null and trainer_area = p_area
        and trainer is not null and p_trainer is not null and trainer <> p_trainer))
"""

# §移籍まとめ D1(2026-09-30): 中央→地方の転入 kind='jra_in'(from_value='中央'・to_value=地方の trainer_area)。
#   race_date= 中央の走のあと、地方で初めて走った日。再転入(地方→中央→地方)は戻った日に数える
#   = 中央と地方の走を 1 本に並べ、直前の走が中央だった地方の走を全部拾う(窓関数 1 回)。
#   中央の走= ①nar_jra_runs(競馬ブック・鍵 kb_horse_id→nar_jra_horses の 馬名+生年月日。生年月日が空の馬は
#   馬名+生年で nar_runs に 1 頭だけ当たるときに使う) ②nar_runs の trainer_area='JRA'(地方の交流に中央所属で出た走)。
#   ⛔②を入れるのは nar_jra_horses に行の無い「確実な取り漏れ」(下調べ 15 頭)を拾うため。
#   ⛔寄せ方: 旧 transfer_in の from_value='JRA'(②で中央から来た馬)は②で必ず jra_in にも出る= 2 重になるので、
#     上の DETECT_SQL で p_area='JRA' を transfer_in から外し jra_in に寄せた。既存の行の片付けは sql/transfer_jra_in.sql。
#   ⛔交流の除外: nar_jra_horses.jra_career_runs(競馬ブック公開頁の「中央在籍 N戦」)が 0 の馬の①は数えない
#     (地方所属のまま中央の交流に出ただけ)。列がまだ無い/値が空の馬は除外できない= そのまま数える。
JRA_IN_SQL = """
with jh as (
  select h.kb_horse_id, h.horse_name,
         coalesce(h.birth_date,
                  (select min(r.birth_date) from nar_runs r
                    where r.horse_name = h.horse_name and extract(year from r.birth_date) = h.birth_year
                   having count(distinct r.birth_date) = 1)) as birth_date
  from nar_jra_horses h
  where {career}
),
keys as (   -- 中央の走がある馬だけに絞る(nar_runs 全体の窓関数を避ける)
  select horse_name, birth_date from jh where birth_date is not null
  union
  select horse_name, birth_date from nar_runs where trainer_area = 'JRA' and birth_date is not null
),
ev as (      -- 中央と地方の走を 1 本の時系列に(is_jra=1 が中央)
  select jh.horse_name, jh.birth_date, j.race_date, 0 as race_no, 1 as is_jra, null::text as trainer_area
  from nar_jra_runs j join jh using (kb_horse_id)
  where jh.birth_date is not null
  union all
  select r.horse_name, r.birth_date, r.race_date, r.race_no,
         case when r.trainer_area = 'JRA' then 1 else 0 end, r.trainer_area
  from nar_runs r join keys k on k.horse_name = r.horse_name and k.birth_date = r.birth_date
  where r.trainer_area is not null
),
s as (       -- 同じ日は地方を先に並べる(同じ日の中央の走を「前」と数えない)
  select ev.*, lag(is_jra) over (partition by horse_name, birth_date order by race_date, is_jra, race_no) as p_jra
  from ev
)
select horse_name, birth_date, race_date, 'jra_in' as kind, '中央' as from_value, trainer_area as to_value
from s
where is_jra = 0 and p_jra = 1 and race_date >= :since
"""
CAREER_ON = "coalesce(h.jra_career_runs, 1) > 0"   # 中央在籍 0 戦= 交流だけ= 外す(空は外さない)
#   案 F(10/4): KDSCOPE の仮の馬(kb_horse_id=kd*)も jra_career_runs(KD の中央在籍走数)を持つので同じ規則で外れる(0 は 337 頭)
CAREER_OFF = "true"                                # 列がまだ無い(sql/transfer_jra_in.sql の適用前)


def jra_in_sql(has_career):
    return JRA_IN_SQL.format(career=CAREER_ON if has_career else CAREER_OFF)


def jra_in_insert(has_career):
    return ("insert into nar_horse_changes (horse_name, birth_date, race_date, kind, from_value, to_value)\n"
            + jra_in_sql(has_career) + f"\non conflict {CONFLICT} do nothing")


# 10/10(うやむや #25 ②A): 同じ馬・同じ日に jra_in があれば transfer_in は消す(1 回だけ並べる)。
#   KDSCOPE の仮の馬(kd)は中央の走が nar_runs に無いので、DETECT_SQL の p_area='JRA' 除外が効かず
#   「前の地方の場→今の場」の transfer_in も出る= 中央から来た移籍が 2 回並ぶ。10/10 に遡りで 115 件消した。
DEDUPE_TRANSFER_SQL = """
delete from nar_horse_changes t
where t.kind = 'transfer_in' and t.race_date >= :since
  and exists (select 1 from nar_horse_changes j
              where j.kind = 'jra_in' and j.horse_name = t.horse_name
                and j.birth_date is not distinct from t.birth_date and j.race_date = t.race_date)
"""

HAS_CAREER_SQL = ("select count(*) from information_schema.columns where table_schema = 'public' "
                  "and table_name = 'nar_jra_horses' and column_name = 'jra_career_runs'")

INSERT_SQL = ("insert into nar_horse_changes (horse_name, birth_date, race_date, kind, from_value, to_value)\n"
              + DETECT_SQL +
              f"\non conflict {CONFLICT} do nothing")

# 馬主: ①state に居ない馬を写す(初出現は「変更」ではない) ②差分を changes へ ③state を追いつかせる
OWNER_SEED = """
insert into nar_owner_state (horse_name, owner)
select horse_name, owner from nar_horses
where owner is not null and owner <> ''
on conflict (horse_name) do nothing
"""
OWNER_DIFF = f"""
insert into nar_horse_changes (horse_name, birth_date, race_date, kind, from_value, to_value)
select h.horse_name,
       (select r.birth_date from nar_runs r
         where r.horse_name = h.horse_name and r.birth_date is not null
         order by r.race_date desc limit 1),
       :today, 'owner_change', s.owner, h.owner
from nar_horses h
join nar_owner_state s using (horse_name)
where h.owner is not null and h.owner <> '' and h.owner <> s.owner
on conflict {CONFLICT} do nothing
"""
OWNER_SYNC = """
update nar_owner_state s set owner = h.owner, updated_at = now()
from nar_horses h
where h.horse_name = s.horse_name and h.owner is not null and h.owner <> '' and h.owner <> s.owner
"""


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--since", help="転入・転厩の検出窓の始まり(YYYY-MM-DD)。既定=7日前(日次)・遡りは1年から")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    pw = os.environ.get("SUPABASE_DB_PASSWORD", "")
    if not pw:
        log("SUPABASE_DB_PASSWORD が要る"); return 1
    today = dt.datetime.now(JST).date()
    since = a.since or str(today - dt.timedelta(days=7))

    con = pg8000.native.Connection(user=USER, password=pw, host=HOST, port=5432,
                                   database="postgres", ssl_context=True)
    try:
        rows = con.run("select count(*), kind from (" + DETECT_SQL + ") x group by kind", since=since)
        found = {k: n for n, k in rows}
        has_career = con.run(HAS_CAREER_SQL)[0][0] > 0
        n_jra = con.run("select count(*) from (" + jra_in_sql(has_career) + ") x", since=since)[0][0]
        log(f"検出({since}〜): 転入 {found.get('transfer_in', 0)}件 / 転厩 {found.get('stable_change', 0)}件"
            f" / 中央から {n_jra}件(交流の除外 {'あり' if has_career else 'なし= 列 jra_career_runs が未作成'})")
        if not a.apply:
            log("ドライラン(--apply で書く)")
            return 0
        con.run(INSERT_SQL, since=since)
        con.run(jra_in_insert(has_career), since=since)
        con.run(DEDUPE_TRANSFER_SQL, since=since)
        n1 = con.run("select count(*) from nar_horse_changes where kind <> 'owner_change'")[0][0]

        seeded_before = con.run("select count(*) from nar_owner_state")[0][0]
        con.run(OWNER_SEED)
        seeded_after = con.run("select count(*) from nar_owner_state")[0][0]
        if seeded_before == 0:
            log(f"馬主スナップショット初期化: {seeded_after:,}頭(初回=差分なし・ここから録り始める)")
        con.run(OWNER_DIFF, today=str(today))
        changed = con.run("select count(*) from nar_horse_changes where kind = 'owner_change' and race_date = :d",
                          d=str(today))[0][0]
        con.run(OWNER_SYNC)
        log(f"追記後: 転入+転厩 計{n1:,}行 / 馬主変更 本日{changed}件(状態 {seeded_after:,}頭)")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
