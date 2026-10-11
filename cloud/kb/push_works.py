# -*- coding: utf-8 -*-
"""南関 4 場の調教(nar_kb_works)と厩舎の話(nar_kb_danwa)を競馬ブックの頁から読んで本番 DB へ(2026-10-11)。

  python cloud/kb/push_works.py --dates 20261011,20261012 [--push]

PC の daily_update.py の「{場} 今日/明日の出馬表」(fetch.py day ... --what ...,cyokyo,danwa --push)の調教と談話だけを
クラウドで回す。--push なし = 読んで件数を出すだけ。頁がまだ出ていないレース(0 頭)は送らない。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fetch  # noqa: E402
import supabase_push  # noqa: E402

TRACKS = ['大井', '船橋', '川崎', '浦和']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dates', required=True, help='YYYYMMDD のカンマ区切り')
    ap.add_argument('--tracks', default=','.join(TRACKS))
    ap.add_argument('--push', action='store_true')
    a = ap.parse_args()
    args = argparse.Namespace(no_login=False, refresh=True, push=a.push, what=['cyokyo', 'danwa'], track=None)
    client, logged_in = fetch.make_client(args)
    for d in [x.strip() for x in a.dates.split(',') if x.strip()]:
        for t in a.tracks.split(','):
            args.track = t
            fetch.cmd_day(client, d, args, logged_in=logged_in)
    print('送った行(--push のときだけ数える):', supabase_push.COUNT, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
