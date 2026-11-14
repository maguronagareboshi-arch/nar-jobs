"""JST の今日・今(2026-11-14 総合レビュー #8)。Actions の機械は UTC なので、素の date.today() / datetime.now() は
JST の 0〜9 時台に前日になる。日付として使う所はここを通す(所要時間の計測の now() はそのままでよい)。
試験= tests/test_jst_today_guard.py(cloud/ と pipeline/ で date.today() が新しく増えたら落ちる)。"""
import datetime as dt

JST = dt.timezone(dt.timedelta(hours=9))


def jst_now(now=None):
    """JST の今(aware)。now は aware datetime(試験用・省略時は現在)。"""
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(JST)


def jst_today(now=None):
    """JST の今日(date)。UTC 15:00 以降は JST の翌日。"""
    return jst_now(now).date()
