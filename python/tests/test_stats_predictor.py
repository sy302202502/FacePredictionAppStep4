"""
統計予想（stats_predictor.py）の成績の読み方を確かめるテスト。DB・ネットには繋がない。

  cd python && python3 -m unittest tests.test_stats_predictor
"""
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import stats_predictor as sp   # noqa: E402


def row(day, rank, name='テスト特別', horses=16, dist='芝1600', cond='良'):
    """成績表の1行（netkeiba の列の並び。使う列だけ中身を入れる）"""
    cols = [''] * 28
    cols[0] = day
    cols[1] = '5東京1'
    cols[4] = name
    cols[6] = str(horses)
    cols[9] = '5.0'
    cols[10] = '2'
    cols[11] = str(rank)
    cols[14] = dist
    cols[16] = cond
    cols[25] = '3-3-2-2'
    return '<tr>' + ''.join(f'<td>{c}</td>' for c in cols) + '</tr>'


def page(*rows):
    return ('<html><body><table class="db_h_race_results"><tr><th>日付</th></tr>'
            + ''.join(rows) + '</table></body></html>')


class ParseHorseResultsTest(unittest.TestCase):
    def test_今回のレースの日より前の走だけを数える(self):
        html = page(row('2026/11/22', 1),    # 今回より後の走
                    row('2026/11/08', 1),    # 今回のレース自身
                    row('2026/10/11', 5),
                    row('2026/09/06', 3))
        got = sp.parse_horse_results(html, before=date(2026, 11, 8))
        self.assertEqual([r['date'] for r in got], ['2026/10/11', '2026/09/06'])
        self.assertEqual([r['rank'] for r in got], [5, 3])

    def test_日付を指定しなければ全部を数える(self):
        html = page(row('2026/11/08', 1), row('2026/10/11', 5))
        self.assertEqual(len(sp.parse_horse_results(html)), 2)

    def test_日付の読めない行は_日付指定のとき使わない(self):
        html = page(row('', 1), row('2026/10/11', 5))
        self.assertEqual(len(sp.parse_horse_results(html, before=date(2026, 11, 8))), 1)
        self.assertEqual(len(sp.parse_horse_results(html)), 2)

    def test_取消と除外は数えず_中止は最下位(self):
        html = page(row('2026/10/11', '取'), row('2026/09/06', '除'),
                    row('2026/08/02', '中', horses=14), row('2026/07/05', '3(降)'))
        got = sp.parse_horse_results(html, before=date(2026, 11, 8))
        self.assertEqual([r['rank'] for r in got], [14, 3])

    def test_成績表の無いページは空(self):
        self.assertEqual(sp.parse_horse_results('<html><body>no table</body></html>'), [])

    def test_直近20走まで(self):
        html = page(*[row(f'2025/{m:02d}/{d:02d}', 2) for m in range(1, 13) for d in (5, 20)])
        self.assertEqual(len(sp.parse_horse_results(html, before=date(2026, 11, 8))), 20)


class FetchHorseResultsTest(unittest.TestCase):
    def test_読めなかったときは_None(self):
        with mock.patch.object(sp, 'fetch_with_retry', side_effect=RuntimeError('timeout')):
            self.assertIsNone(sp.fetch_horse_results('2020100001', 'テスト'))

    def test_デビュー前の馬は空のリスト(self):
        resp = mock.Mock()
        with mock.patch.object(sp, 'fetch_with_retry', return_value=resp), \
             mock.patch.object(sp, 'decode_netkeiba', return_value='<html></html>'):
            self.assertEqual(sp.fetch_horse_results('2024100001', 'テスト'), [])


class BaselineTest(unittest.TestCase):
    def test_成績の無い馬の点は_horse_id_の有無で変わらない(self):
        a, _, _ = sp.calc_score([], 1600, '芝')
        b, _, _ = sp.calc_score([], 1600, '芝', blood=(None, None))
        self.assertEqual(a, b)
        self.assertLess(a, 40.0)   # 旧実装は horse_id なしだけ一律40点で、成績なしの馬より有利だった


if __name__ == '__main__':
    unittest.main()


def run(rank, horses, name):
    return {'rank': rank, 'horses': horses, 'race_name': name}


class RecentFormTest(unittest.TestCase):
    def test_クラスの読み取り(self):
        self.assertEqual(sp.class_level('太秦S(OP)'), 4)
        self.assertEqual(sp.class_level('天皇賞(秋)(GI)'), 6.4)
        self.assertEqual(sp.class_level('3歳以上2勝クラス'), 2)
        self.assertEqual(sp.class_level('2歳未勝利'), 0)
        self.assertIsNone(sp.class_level('中山グランドジャンプ(JGI)'))   # 障害は補正しない
        self.assertIsNone(sp.class_level('C1'))

    def test_今回のクラスは出走馬の前走の中央値(self):
        res = [[run(1, 16, '○○特別(2勝クラス)')], [run(3, 16, '3歳以上2勝クラス')],
               [run(5, 16, '△△S(3勝クラス)')], []]
        self.assertEqual(sp.race_class_level(res), 2)
        self.assertIsNone(sp.race_class_level([[], []]))

    def test_同じ着順でも多頭数のほうが高い(self):
        small = sp.recent_form_pt([run(5, 6, '2勝クラス')] * 5, 2)
        big = sp.recent_form_pt([run(5, 18, '2勝クラス')] * 5, 2)
        self.assertGreater(big, small)

    def test_上のクラスで走った着順は割り引いて良く見る(self):
        same = sp.recent_form_pt([run(6, 16, '3歳以上2勝クラス')] * 5, 2)
        upper = sp.recent_form_pt([run(6, 16, '○○S(GIII)')] * 5, 2)
        lower = sp.recent_form_pt([run(6, 16, '3歳以上1勝クラス')] * 5, 2)
        self.assertGreater(upper, same)
        self.assertGreater(same, lower)

    def test_1戦1勝だけでは満点にしない(self):
        one = sp.recent_form_pt([run(1, 16, '2歳新馬')], 0)
        five = sp.recent_form_pt([run(1, 16, '2歳新馬')] * 5, 0)
        self.assertLess(one, five)
        self.assertLess(five, 27.0)
        self.assertGreater(one, 13.0)   # それでも中立よりは上

    def test_点は4点台から27点の間(self):
        worst = sp.recent_form_pt([run(18, 18, '2歳未勝利')] * 5, 6.4)
        best = sp.recent_form_pt([run(1, 18, '○○(GI)')] * 5, 0)
        self.assertGreaterEqual(worst, 4.3)
        self.assertLessEqual(best, 27.0)
