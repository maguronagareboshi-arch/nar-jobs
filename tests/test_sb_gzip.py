# -*- coding: utf-8 -*-
"""cloud/sb_gzip.py= GET の受け取りを gzip で(11/6 送信量対策)。手元の偽の口(http.server)で
gzip の応答・素の応答・空の応答・Content-Range 付き・POST は頼まない・HTTPError の本文も解凍、を確かめる。
  py -3.12 -X utf8 tests/test_sb_gzip.py"""
import gzip
import http.server
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cloud'))
import sb_gzip  # noqa: E402

BODY = json.dumps([{'race_id': i, 'name': '馬' * (i % 7), 'x': None} for i in range(500)], ensure_ascii=False).encode('utf-8')
SEEN = []


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, gz, extra=None):
        ae = self.headers.get('Accept-Encoding') or ''
        SEEN.append((self.command, self.path, ae))
        if gz and 'gzip' in ae and body:
            body = gzip.compress(body)
            enc = True
        else:
            enc = False
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        if enc:
            self.send_header('Content-Encoding', 'gzip')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/gz':
            self._send(200, BODY, True)
        elif self.path == '/plain':
            self._send(200, BODY, False)
        elif self.path == '/empty':
            self._send(200, b'', True)
        elif self.path == '/range':
            self._send(200, BODY, True, {'Content-Range': '0-499/12345'})
        elif self.path == '/err':
            self._send(400, b'{"message":"bad"}', True)
        else:
            self._send(404, b'', False)

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(n)
        self._send(201, b'', True)


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        cls.base = 'http://127.0.0.1:%d' % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def r(self, p, **kw):
        return urllib.request.Request(self.base + p, headers={'apikey': 'x'}, **kw)

    def test_gzip(self):
        SEEN.clear()
        st, hd, body = sb_gzip.open_read(self.r('/gz'), 10)
        self.assertEqual((st, body), (200, BODY))
        self.assertEqual(hd.get('Content-Encoding'), 'gzip')
        self.assertEqual(SEEN[-1][2], 'gzip')

    def test_plain(self):
        self.assertEqual(sb_gzip.read(self.r('/plain'), 10), BODY)

    def test_empty(self):
        self.assertEqual(sb_gzip.read(self.r('/empty'), 10), b'')

    def test_range(self):
        st, hd, body = sb_gzip.open_read(self.r('/range'), 10)
        self.assertEqual(body, BODY)
        self.assertEqual(hd['Content-Range'].split('/')[-1], '12345')

    def test_post_not_asked(self):
        SEEN.clear()
        st, hd, body = sb_gzip.open_read(self.r('/w', data=b'[]', method='POST'), 10)
        self.assertEqual((st, body), (201, b''))
        self.assertNotIn('gzip', SEEN[-1][2])  # http.client の既定は identity

    def test_http_error_decoded(self):
        with self.assertRaises(urllib.error.HTTPError) as c:
            sb_gzip.read(self.r('/err'), 10)
        self.assertEqual(c.exception.code, 400)
        self.assertEqual(c.exception.read(), b'{"message":"bad"}')

    def test_404_plain(self):
        with self.assertRaises(urllib.error.HTTPError) as c:
            sb_gzip.read(self.r('/nope'), 10)
        self.assertEqual(c.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
