"""
レース当日の結果ページ（race.netkeiba.com）の読み取りを確かめるテスト。DB・ネットには繋がない。

  cd python && python3 -m unittest tests.test_result_quick
"""
import os
import sys
import unittest

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import result_auto_fetcher as rf   # noqa: E402


def horse_row(rank, waku, num, hid):
    return (f'<tr><td>{rank}</td><td>{waku}</td><td>{num}</td>'
            f'<td><a href="https://db.netkeiba.com/horse/{hid}">馬{num}</a></td></tr>')


def pay_row(name, result, payout, ninki):
    return (f'<tr><th>{name}</th><td class="Result">{result}</td>'
            f'<td class="Payout">{payout}</td><td class="Ninki">{ninki}</td></tr>')


def page(rows, pays):
    return BeautifulSoup(
        '<table class="RaceTable01 RaceCommon_Table"><tr><th>着順</th></tr>' + ''.join(rows) + '</table>'
        '<table class="Payout_Detail_Table">' + ''.join(pays) + '</table>', 'lxml')


FULL_PAYS = [
    pay_row('単勝', '<span>15</span>', '970円', '5人気'),
    pay_row('複勝', '<span>15</span><span>1</span><span>13</span>', '330円<br>670円<br>680円', '4人気<br>9人気<br>8人気'),
    pay_row('馬連', '<span>1</span><span>15</span>', '13,120円', '42人気'),
    pay_row('ワイド', '<span>1</span><span>15</span><span>13</span><span>15</span><span>1</span><span>13</span>',
            '3,580円<br>2,710円<br>5,880円', '40人気<br>32人気<br>66人気'),
    pay_row('馬単', '<span>15</span><span>1</span>', '23,110円', '74人気'),
    pay_row('3連複', '<span>1</span><span>13</span><span>15</span>', '76,460円', '195人気'),
    pay_row('3連単', '<span>15</span><span>1</span><span>13</span>', '441,750円', '1,089人気'),
]


class ParseQuickResultTest(unittest.TestCase):
    def test_着順と馬番と払戻を読む(self):
        soup = page([horse_row(1, 8, 15, '2022100994'), horse_row(2, 1, 1, '2022100623'),
                     horse_row(3, 7, 13, '2022105022'), horse_row('中止', 2, 3, '2021100001'),
                     horse_row('取消', 3, 5, '2021100002')], FULL_PAYS)
        q = rf.parse_quick_result(soup)
        self.assertEqual(q['results'], {'2022100994': 1, '2022100623': 2, '2022105022': 3})
        self.assertEqual(q['numbers']['2021100001'], 3)       # 着順の無い馬も馬番は取る
        pays = {(b, c): p for b, c, p, _ in q['payouts']}
        self.assertEqual(pays[('単勝', '15')], 970)
        self.assertEqual(pays[('複勝', '13')], 680)
        self.assertEqual(pays[('ワイド', '13-15')], 2710)      # 順序の無い券種は小さい順にそろえる
        self.assertEqual(pays[('馬単', '15-1')], 23110)        # 順序のある券種はそのまま
        self.assertEqual(pays[('三連複', '1-13-15')], 76460)   # 「3連複」は DB の呼び名「三連複」に直す
        self.assertEqual(pays[('三連単', '15-1-13')], 441750)

    def test_組番と払戻の数が合わない行は使わない(self):
        soup = page([horse_row(1, 1, 1, '2022100001')],
                    [pay_row('ワイド', '<span>1</span><span>2</span><span>3</span>', '300円<br>400円', '1人気')])
        self.assertEqual(rf.parse_quick_result(soup)['payouts'], [])

    def test_結果表が無ければ_None(self):
        self.assertIsNone(rf.parse_quick_result(BeautifulSoup('<html></html>', 'lxml')))


if __name__ == '__main__':
    unittest.main()
