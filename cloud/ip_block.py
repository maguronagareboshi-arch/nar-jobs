"""持ち出し止めの見回り(2026-11-11)。

通信記録(Supabase edge_logs)から、直前の時間帯に 1 時間 THRESHOLD 回以上読んだ IP を数え、
出入り禁止名簿(private.nar_block_ip)へ載せる。入口で断るのは DB の nar_pre_request(別に付ける)。

env: SUPABASE_URL / SUPABASE_SERVICE_KEY / SUPABASE_ACCESS_TOKEN(ログを読むだけの鍵)
     HOURS(見る時間・既定 1・最大 24) / THRESHOLD(既定 5000) / DRY_RUN(1= 名簿に書かず表を出すだけ)
     DC_THRESHOLD(借りたコンピューターの線・既定 300) / DC_DRY(1= 借りたコンピューターの分は表だけ・既定 1)
11/11 追: 断った回(429)は数えない= 名簿に載っている間は載せ直さない。期限が切れて戻ってきたら 7 日。
"""
import ipaddress
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# 止めない相手(検索・広告の巡回)。自分の便は service_role なので数えから外れる。
EXEMPT_NETS = [ipaddress.ip_network(n) for n in (
    '66.249.64.0/19',    # Googlebot
    '74.125.0.0/16',     # Mediapartners-Google(AdSense)など
    '64.233.160.0/19', '66.102.0.0/20', '72.14.192.0/18', '209.85.128.0/17',  # Google の巡回
    '157.55.39.0/24', '207.46.13.0/24', '40.77.167.0/24',  # bingbot
)]
# 借りたコンピューター(データセンター)の回線名。Cloudflare(WARP= 人の iPhone)・Apple(プライベートリレー)は人なので入れない。
DC_ORG_RE = ('google llc|amazon|microsoft|tencent|alibaba|oracle|digitalocean|ovh|hetzner|linode|akamai|vultr|choopa|'
             'contabo|sakura internet|gmo internet|xserver|idc frontier|huawei cloud|scaleway|leaseweb|m247|datacamp|'
             'hostinger|ionos|kagoya|byteplus|bytedance|zenlayer|psychz|quadranet|colocrossing')
EXEMPT_UA = ('Mediapartners-Google', 'AdsBot-Google', 'Google-InspectionTool')


def exempt(ip: str, ua: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if any(a in n for n in EXEMPT_NETS):
        return True
    return any(k in (ua or '') for k in EXEMPT_UA) and ip.startswith(('66.249.', '74.125.'))


def main() -> int:
    url = os.environ['SUPABASE_URL'].rstrip('/')
    key = os.environ['SUPABASE_SERVICE_KEY']
    pat = os.environ['SUPABASE_ACCESS_TOKEN']
    hours = max(1, min(24, int(os.environ.get('HOURS') or 1)))
    thr = int(os.environ.get('THRESHOLD') or 5000)
    dry = os.environ.get('DRY_RUN') == '1'
    dc_thr = int(os.environ.get('DC_THRESHOLD') or 300)
    dc_dry = os.environ.get('DC_DRY', '1') != '0'
    ref = urllib.parse.urlparse(url).hostname.split('.')[0]

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=hours)
    sql = (
        "select ip, max(n) as max_h, sum(n) as total, any(org) as org, any(ua) as ua from ("
        " select log_attributes['request.headers.cf_connecting_ip'] as ip, toStartOfHour(timestamp) as h, countIf(log_attributes['response.status_code'] != '429') as n,"
        " any(log_attributes['request.cf.asOrganization']) as org,"
        " any(substring(log_attributes['request.headers.user_agent'],1,120)) as ua"
        " from logs where source='edge_logs'"
        " and log_attributes['request.sb.jwt.apikey.payload.role']!='service_role'"
        " group by ip,h) group by ip"
        f" having max_h >= {thr} or (max_h >= {dc_thr} and match(lower(org), '{DC_ORG_RE}'))"
        " order by max_h desc limit 300"
    )
    q = urllib.parse.urlencode({'sql': sql,
                                'iso_timestamp_start': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'iso_timestamp_end': end.strftime('%Y-%m-%dT%H:%M:%SZ')})
    req = urllib.request.Request(
        f'https://api.supabase.com/v1/projects/{ref}/analytics/endpoints/logs?{q}',
        headers={'Authorization': f'Bearer {pat}', 'User-Agent': 'nar-jobs/1.0'})
    body = json.loads(urllib.request.urlopen(req, timeout=60).read())
    if body.get('error'):
        print('ログの取得に失敗:', body['error'], file=sys.stderr)
        return 1
    rows = body.get('result') or []

    hit, skip, dc_only = [], [], []
    for r in rows:
        if exempt(r.get('ip') or '', r.get('ua') or ''):
            skip.append(r)
        elif int(r['max_h']) < thr:          # 借りたコンピューターの線だけ超えた
            (dc_only if dc_dry else hit).append(r)
        else:
            hit.append(r)

    print(f'窓 {start:%m/%d %H}時〜{end:%H}時(UTC)・線 {thr}/時・該当 {len(hit)}・除外 {len(skip)}'
          f'・借りたコンピューター {dc_thr}/時 {"(表だけ)" if dc_dry else ""}')
    print('| IP | 1時間最大 | 合計 | 回線 | 端末 |')
    print('|---|---|---|---|---|')
    for r in hit + dc_only + skip:
        mark = '' if r in hit else ('(借・表だけ)' if r in dc_only else '(除外)')
        print(f"| {r['ip']}{mark} | {r['max_h']} | {r['total']} | {r.get('org') or ''} | {(r.get('ua') or '')[:50]} |")

    if dry or not hit:
        return 0
    p = json.dumps([{'ip': r['ip'], 'hits': int(r['max_h']), 'org': r.get('org'), 'ua': r.get('ua')} for r in hit])
    req = urllib.request.Request(
        f'{url}/rest/v1/rpc/nar_block_upsert', data=json.dumps({'p': json.loads(p)}).encode(), method='POST',
        headers={'apikey': key, 'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    n = urllib.request.urlopen(req, timeout=30).read().decode()
    print(f'名簿に載せた: {n}')
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a', encoding='utf8') as f:
            ips = ' '.join(r['ip'] + '(' + (r.get('org') or '')[:20].replace(' ', '_') + ')' for r in hit)
            f.write(f'listed={n}\nips={ips}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
