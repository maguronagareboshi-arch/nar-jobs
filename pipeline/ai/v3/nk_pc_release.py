# -*- coding: utf-8 -*-
"""能力試験の頁を PC で読み、暗号化してリリース v3-nk-html に置く(2026-11-02・公式サイトが GitHub の機械に 403 を返すため)。

  py -3.12 -X utf8 pipeline/ai/v3/nk_pc_release.py            # 読む → 包む → 置く
  py -3.12 -X utf8 pipeline/ai/v3/nk_pc_release.py --no-upload  # 読む → 包むだけ(確かめ用)

- 読む = nk_fetch.fetch を 2026-08-22〜昨日・1 本・0.5 秒おき(t7e_forecast.nk_fetch と同じ範囲・作法)。
- 包む = nk_html の 2026-08-22 以降の HTML と、同じ期間の 404 の記録(_404_pc.txt にまとめる)を tar.gz にし、
  ~/.v3_asset_key で openssl enc -aes-256-cbc -pbkdf2(便の固定ファイルと同じ形)。
- 置く = gh release upload v3-nk-html --clobber(無ければ作る)。便は能力試験の段の前にこれを開ける。
"""
import io
import os
import subprocess
import sys
import tarfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nk_fetch as nf  # noqa: E402

D0 = date(2026, 8, 22)
TAG = 'v3-nk-html'
ASSET = 'v3_nk_html.tar.gz.enc'
REPO = 'maguronagareboshi-arch/nar-jobs'
KEYF = Path.home() / '.v3_asset_key'


def pack(out):
    s0 = f'{D0:%Y%m%d}'
    html = sorted(p for p in nf.HD.glob('*.html') if p.stem >= s0)
    n404 = set()
    for f in nf.HD.glob('_404*.txt'):
        n404 |= {k for k in f.read_text(encoding='utf-8').split() if k >= s0}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for p in html:
            t.add(p, arcname=p.name)
        b = ('\n'.join(sorted(n404)) + '\n').encode('utf-8')
        ti = tarfile.TarInfo('_404_pc.txt'); ti.size = len(b)
        t.addfile(ti, io.BytesIO(b))
    key = KEYF.read_text(encoding='utf-8').strip()
    r = subprocess.run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-pass', 'env:V3_ASSET_KEY', '-out', str(out)],
                       input=buf.getvalue(), env={**os.environ, 'V3_ASSET_KEY': key}, capture_output=True)
    if r.returncode:
        raise SystemExit('⛔ 暗号化に失敗 ' + r.stderr.decode(errors='replace'))
    last = html[-1].stem if html else '-'
    print(f'包んだ: HTML {len(html)}・404 {len(n404)}・最後の頁 {last}・{out.stat().st_size:,} バイト', flush=True)


def upload(out):
    gh = ['gh', '-R', REPO, 'release']
    if subprocess.run(gh + ['view', TAG], capture_output=True).returncode:
        subprocess.run(gh + ['create', TAG, '--prerelease', '--title', 'v3 nk html (PC)',
                             '--notes', '能力試験の頁(PC で読んだもの・暗号化)'], check=True)
    subprocess.run(gh + ['upload', TAG, str(out), '--clobber'], check=True)
    print('置いた:', TAG, ASSET, flush=True)


def main():
    nf.D0, nf.D1 = D0, date.today() - timedelta(days=1)
    nf.fetch(None, 0.5)
    out = nf.V3 / ASSET
    pack(out)
    if '--no-upload' not in sys.argv:
        upload(out)


if __name__ == '__main__':
    main()
