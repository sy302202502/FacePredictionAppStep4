"""
出馬表の同期（entry_fetcher.py）の判定を確かめるテスト。DB・ネットには繋がない。

  cd python && python3 -m unittest tests.test_entry_fetcher
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import entry_fetcher as ef   # noqa: E402


def field(n, start=1, names=None):
    return [{'horse_name': (names[i] if names else f'馬{i + 1}'), 'horse_number': start + i} for i in range(n)]


class IsFinalFieldTest(unittest.TestCase):
    def test_特別登録52頭から確定16頭は信用する(self):
        db = {f'馬{i + 1}' for i in range(52)}
        self.assertTrue(ef.is_final_field(field(16), db))

    def test_馬番がまだ無い表は信用しない(self):
        db = {f'馬{i + 1}' for i in range(52)}
        entries = [{'horse_name': f'馬{i + 1}', 'horse_number': None} for i in range(16)]
        self.assertFalse(ef.is_final_field(entries, db))

    def test_途中までしか読めなかった表は信用しない(self):
        db = {f'馬{i + 1}' for i in range(16)}
        self.assertFalse(ef.is_final_field(field(4), db))            # 頭数が少なすぎる
        self.assertFalse(ef.is_final_field(field(6, start=3), db))   # 馬番が1から始まらない
        broken = field(8)
        broken[3]['horse_number'] = 12                               # 馬番が飛んでいる
        self.assertFalse(ef.is_final_field(broken, db))

    def test_別のレースの表は信用しない(self):
        db = {f'馬{i + 1}' for i in range(30)}
        other = field(16, names=[f'別の馬{i}' for i in range(16)])
        self.assertFalse(ef.is_final_field(other, db))

    def test_19頭以上は信用しない(self):
        db = {f'馬{i + 1}' for i in range(52)}
        self.assertFalse(ef.is_final_field(field(19), db))


if __name__ == '__main__':
    unittest.main()
