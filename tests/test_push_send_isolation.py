# -*- coding: utf-8 -*-
"""§302 send_all= 壊れた鍵の購読 1 件で残りの送信先が止まらない・timeout を渡す。通信なし(webpush を差し替え)。"""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import push_notify as P  # noqa: E402


class FakeWPE(Exception):
    pass


class Rest:
    def __init__(self):
        self.calls = []

    def req(self, path, method="GET", body=None, prefer=None):
        self.calls.append((method, path.split("?")[0]))
        return body if path.startswith("nar_push_sent?") else []   # claim は常に初回扱い


def sub(dev, ep, p256dh="GOODKEY"):
    return {"device_id": dev, "endpoint": ep, "p256dh": p256dh, "auth": "AUTH", "want_a": True, "want_c": True}


def target(dev):
    return {"device_id": dev, "horse_id": "nar:テスト", "race_id": "ooi/2026-09-28/1", "kind": "A", "name": "テスト",
            "track": "大井", "race_date": "2026-09-28", "race_no": 1, "finish": None}


class T(unittest.TestCase):
    def test_bad_key_does_not_stop_others(self):
        sent_to, timeouts = [], []

        def webpush(subscription_info, timeout=None, **kw):
            timeouts.append(timeout)
            if subscription_info["keys"]["p256dh"] == "=":
                raise ValueError("Could not deserialize key data")
            sent_to.append(subscription_info["endpoint"])

        fake = types.ModuleType("pywebpush")
        fake.webpush, fake.WebPushException = webpush, FakeWPE
        old = sys.modules.get("pywebpush")
        sys.modules["pywebpush"] = fake
        try:
            rest = Rest()
            subs = [sub("bad", "https://push.example/bad", "="), sub("g1", "https://push.example/g1"),
                    sub("g2", "https://push.example/g2")]
            got = P.send_all(rest, subs, [target("bad"), target("g1"), target("g2")], "VAPID", "https://yukochi.com")
        finally:
            if old is None:
                sys.modules.pop("pywebpush", None)
            else:
                sys.modules["pywebpush"] = old
        self.assertEqual(got, (2, 0, 1, 0))                         # sent, skipped, failed, gone
        self.assertEqual(sent_to, ["https://push.example/g1", "https://push.example/g2"])
        self.assertEqual(timeouts, [P.PUSH_TIMEOUT] * 3)
        self.assertFalse(any(t == "nar_push_subs" for _, t in rest.calls))   # 壊れた購読の DB は触らない


if __name__ == "__main__":
    unittest.main()
