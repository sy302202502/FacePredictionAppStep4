"""
万馬券チャレンジ（high_dividend_selector.py）の netkeiba 読み取りの決まりを確かめるテスト。
DB・ネットには繋がない（どちらも差し替える）。

  cd python && python3 -m unittest tests.test_high_dividend_selector
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import high_dividend_selector as hd   # noqa: E402


class FakeResp:
    def __init__(self, text='', status=200, data=None):
        self.text = text
        self.status_code = status
        self.encoding = 'utf-8'
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError('not json')
        return self._data


def odds_json(n):
    return {'status': 'middle',
            'data': {'odds': {'1': {f'{i:02d}': [f'{2.5 + i}', '', str(i)] for i in range(1, n + 1)}}}}


class ReaderTest(unittest.TestCase):
    def setUp(self):
        # 枠は7回まで（DB の代わりに数える）
        self.used = 0
        def reserve(conn, day):
            if self.used >= hd.DAILY_REQUEST_CAP:
                return False
            self.used += 1
            return True
        patcher = mock.patch.object(hd, 'reserve_request', side_effect=reserve)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(hd.time, 'sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def reader(self, responses):
        r = hd.Reader(conn=None)
        r.session = mock.Mock()
        r.session.get.side_effect = responses
        return r

    def test_1日の上限を超えて読まない(self):
        r = self.reader([FakeResp('ok')] * 20)
        for _ in range(hd.DAILY_REQUEST_CAP):
            r.get('u')
        with self.assertRaises(hd.Blocked):
            r.get('u')
        self.assertEqual(r.session.get.call_count, hd.DAILY_REQUEST_CAP)

    def test_断られたら止まる(self):
        for status in (403, 429, 503):
            r = self.reader([FakeResp('', status)])
            with self.assertRaises(hd.Blocked):
                r.get('u')

    def test_オッズAPIのlimitで止まる(self):
        for resp in (FakeResp('{"status":"limit","reason":"user update limit"}', data={'status': 'limit'}),
                     FakeResp('{"status":"error","reason":"user update limit"}', data={'status': 'error'}),
                     FakeResp('<html>user update limit</html>')):
            r = self.reader([resp])
            with self.assertRaises(hd.Blocked):
                hd.fetch_win_odds(r, '202604040210')

    def test_想定外の応答で止まる(self):
        r = self.reader([FakeResp('<html>maintenance</html>')])
        with self.assertRaises(hd.Blocked):
            hd.fetch_win_odds(r, '202604040210')

    def test_Cookie取得ページの制限で止まる(self):
        r = self.reader([FakeResp('<html>user update limit</html>')])
        with self.assertRaises(hd.Blocked):
            r.get('u', limit_text='update limit')

    def test_オッズは低い順で取消を除く(self):
        data = odds_json(3)
        data['data']['odds']['1']['04'] = ['0.0', '', '0']   # 取消
        r = self.reader([FakeResp('{"status":"middle"}', data=data)])
        odds = hd.fetch_win_odds(r, '202604040210')
        self.assertEqual([h['umaban'] for h in odds], [1, 2, 3])


class CoverageTest(unittest.TestCase):
    def test_頭数に対してオッズが足りないレースは使わない(self):
        odds = [{'umaban': i, 'odds': 3.0 + i, 'popularity': i} for i in range(1, 6)]
        self.assertFalse(hd.enough_odds(odds, 18))
        self.assertTrue(hd.enough_odds(odds * 3, 15))
        self.assertTrue(hd.enough_odds(odds, 0))     # 頭数不明
        self.assertFalse(hd.enough_odds(None, 10))


class EnsurePredictionTest(unittest.TestCase):
    """途中まで作られた予想を作り直す"""
    def setUp(self):
        self.ran = []
        self.state = {'heads': 10, 'stats': 4, 'face': False}
        def counts(conn, race_id):
            return self.state['heads'], self.state['stats']
        def run(script, args, desc):
            self.ran.append((script, args))
            if script == 'entry_fetcher.py':
                self.state['heads'] = 16
            if script == 'stats_predictor.py':
                self.state['stats'] = self.state['heads']
            if script == 'face_analyzer_local.py':
                self.state['face'] = True
            return True, []
        lock = mock.Mock()
        for target, name, value in ((hd, 'prediction_counts', counts), (hd, 'wait_pipeline_lock', lambda: lock),
                                    (hd, 'wait_sync', lambda: True), (hd.wp, 'run_script', run),
                                    (hd.wp, 'update_image_paths', mock.Mock()),
                                    (hd.wp, 'face_analysis_done', lambda c, r: self.state['face'])):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_頭数の足りない出馬表と一部だけの統計予想を作り直す(self):
        race = {'race_id': '202604040210', 'race_name': '飛翼特別', 'race_date': '2026-10-18'}
        self.assertTrue(hd.ensure_prediction(None, race, 16))
        self.assertEqual([s for s, _ in self.ran], ['entry_fetcher.py', 'stats_predictor.py', 'face_analyzer_local.py'])
        self.assertIn('--update', self.ran[1][1])   # 顔面データを残して全馬を計算し直す


class MainFlowTest(unittest.TestCase):
    """main の分岐で netkeiba を読まないこと"""
    def setUp(self):
        for name, value in (('single_run', mock.Mock()), ('get_conn', mock.Mock()),
                            ('ensure_table', mock.Mock()), ('wait_odds_job', mock.Mock())):
            p = mock.patch.object(hd, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.reader_cls = mock.patch.object(hd, 'Reader', side_effect=AssertionError('netkeiba を読んだ'))
        self.reader_cls.start()
        self.addCleanup(self.reader_cls.stop)

    def run_main(self, *args):
        with mock.patch.object(sys, 'argv', ['x', '--date', '20261018', *args]):
            return hd.main()

    def test_retry_onlyは選定が無ければ何もしない(self):
        with mock.patch.object(hd, 'selected_on', return_value=None):
            self.assertEqual(self.run_main('--retry-only'), 0)

    def test_retry_onlyは予想作成だけやり直す(self):
        row = (1, '202604040210', '飛翼特別', None, False, '新潟', '理由', '[]', 18)
        with mock.patch.object(hd, 'selected_on', return_value=row), \
             mock.patch.object(hd, 'retry_prediction', return_value=0) as retry:
            self.assertEqual(self.run_main('--retry-only'), 0)
            retry.assert_called_once()

    def test_選定済みの日は読まない(self):
        row = (1, '202604040210', '飛翼特別', None, True, '新潟', '理由', '[]', 18)
        with mock.patch.object(hd, 'selected_on', return_value=row):
            self.assertEqual(self.run_main(), 0)
            self.assertEqual(self.run_main('--dry-run'), 0)

    def test_予想しているレースが無い日は読まない(self):
        with mock.patch.object(hd, 'selected_on', return_value=None), \
             mock.patch.object(hd, 'odds_from_db', return_value=[]):
            self.assertEqual(self.run_main(), 0)

    def test_二重起動は何もしない(self):
        with mock.patch.object(hd, 'single_run', return_value=None):
            self.assertEqual(self.run_main(), 0)


if __name__ == '__main__':
    unittest.main()
