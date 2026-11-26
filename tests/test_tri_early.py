# 2026-11-26 トリプル馬単の 1 本目だけ当日版の印を 45 分前から(体重が全頭そろった時だけ)。v29_gap の選びの 3 関数を確かめる
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'ai' / 'v3'))
import v29_gap as G  # noqa: E402


def races(tr, nos):
    return [{'track': tr, 'race_no': n} for n in nos]


def test_lead1():
    assert G.tri_lead1(races('浦和', range(1, 13)) + races('大井', [10, 11, 12]) + races('川崎', [11, 12])) == {'浦和': 10, '大井': 10}


def test_window():
    lead1 = {'浦和': 10}
    t = lambda m, n, k: (m, {'track': '浦和', 'race_no': n}, k, None)  # noqa: E731
    todo = [t(44, 10, 'a'), t(46, 10, 'b'), t(44, 9, 'c'), t(29, 9, 'd'), t(15, 10, 'e'), t(31, 11, 'f'), t(20, 10, 'g')]
    got = [x[2] for x in G.day_window(todo, lead1, {'g'})]
    assert got == ['a', 'd'], got   # 1 本目は 45 分前から・ほかは 30 分前から・16 分前より後と済みは無し


def test_full_weights():
    B = pd.DataFrame({'track': ['浦和'] * 3, 'race_no': [10] * 3, 'umaban': [1, 2, 3]})
    assert not G.full_weights(B, {}, '浦和', 10)
    assert not G.full_weights(B, {('浦和', 10): {1: (450, 2), 2: (470, 0)}}, '浦和', 10)
    assert G.full_weights(B, {('浦和', 10): {1: (450, 2), 2: (470, 0), 3: (480, -4)}}, '浦和', 10)
    assert not G.full_weights(B, {('浦和', 10): {1: 1, 2: 1, 3: 1}}, '浦和', 11)   # 土台の馬が無いレースは False
