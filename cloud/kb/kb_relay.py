# -*- coding: utf-8 -*-
"""競馬ブックの頁を Supabase の東京の関数 kb-relay 経由で読む(2026-11-08)。

競馬ブックは 2026-11-07 夜から海外の接続を断る(GitHub の便は米国 = 403・東京からは 200)。
install(session) は、まず競馬ブックを直接 1 回読み、403 なら *.keibabook.co.jp への要求だけを中継に回す。
直接読めるとき(PC・断りが解けた後)は何もしない。ログイン・Cookie・転送の扱いは requests のまま。

  鍵 = KB_RELAY_KEY か SUPABASE_SERVICE_KEY(service_role)。中継の場所 = KB_RELAY_URL(既定は nar-official)。
  KB_RELAY=0 で使わない・KB_RELAY=1 で直接の確かめを飛ばして必ず使う。
"""
import base64
import http.client
import io
import os
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3 import HTTPResponse
from urllib3._collections import HTTPHeaderDict

RELAY_URL = os.environ.get('KB_RELAY_URL', 'https://qgsnsdjvzzeazbazjlwa.supabase.co/functions/v1/kb-relay')
HOSTS = ('https://p.keibabook.co.jp', 'https://kessai.keibabook.co.jp', 'https://s.keibabook.co.jp',
         'https://www.keibabook.co.jp')


class _Orig:  # requests の Cookie の取り出しが見る _original_response.msg の代わり
    def __init__(self, msg):
        self.msg = msg

    def isclosed(self):
        return True

    def close(self):
        pass


class RelayAdapter(HTTPAdapter):
    def __init__(self, key, url=RELAY_URL):
        super().__init__()
        self.key, self.url = key, url

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        body = request.body
        if isinstance(body, str):
            body = body.encode('utf-8')
        t = timeout if isinstance(timeout, (int, float)) else 60
        r = requests.post(self.url, json={
            'method': request.method, 'url': request.url, 'headers': dict(request.headers),
            'body_b64': base64.b64encode(body).decode() if body else None,
        }, headers={'Authorization': 'Bearer ' + self.key, 'apikey': self.key, 'x-region': 'ap-northeast-1'},
            timeout=max(t, 60))
        if r.status_code != 200:
            raise requests.ConnectionError(f'kb-relay {r.status_code}: {r.text[:200]}', request=request)
        j = r.json()
        hd, msg = HTTPHeaderDict(), http.client.HTTPMessage()
        for k, v in j['headers']:
            hd.add(k, v)
            msg[k] = v  # 同じ名前を重ねて足す(set-cookie が複数)
        raw = HTTPResponse(body=io.BytesIO(base64.b64decode(j['body_b64'])), headers=hd, status=j['status'],
                           preload_content=False, decode_content=False, original_response=_Orig(msg))
        return self.build_response(request, raw)


def install(session, log=lambda *a: print('[kb_relay]', *a, file=sys.stderr)):
    mode = os.environ.get('KB_RELAY', 'auto')
    if mode == '0':
        return False
    key = os.environ.get('KB_RELAY_KEY') or os.environ.get('SUPABASE_SERVICE_KEY') or ''
    if not key:
        return False
    if mode != '1':
        try:
            st = requests.get(HOSTS[0] + '/', headers={'User-Agent': session.headers.get('User-Agent', '')},
                              timeout=20).status_code
        except requests.RequestException as e:
            st = repr(e)
        if st != 403:
            return False
        log('競馬ブックが直接は 403 = 東京の中継で読む')
    ad = RelayAdapter(key)
    for h in HOSTS:
        session.mount(h, ad)
    return True
