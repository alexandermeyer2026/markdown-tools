import datetime
import unittest

from os_utils.date_resolver import resolve_date


class TestResolveDate(unittest.TestCase):
    def test_today(self):
        self.assertEqual(resolve_date('today'), datetime.date.today())

    def test_yesterday(self):
        self.assertEqual(resolve_date('yesterday'),
                         datetime.date.today() - datetime.timedelta(days=1))

    def test_tomorrow(self):
        self.assertEqual(resolve_date('tomorrow'),
                         datetime.date.today() + datetime.timedelta(days=1))

    def test_case_insensitive(self):
        today = datetime.date.today()
        self.assertEqual(resolve_date('TODAY'), today)
        self.assertEqual(resolve_date('Yesterday'),
                         today - datetime.timedelta(days=1))
        self.assertEqual(resolve_date('TOMORROW'),
                         today + datetime.timedelta(days=1))

    def test_iso_date(self):
        self.assertEqual(resolve_date('2024-01-15'), datetime.date(2024, 1, 15))

    def test_iso_date_another(self):
        self.assertEqual(resolve_date('2000-12-31'), datetime.date(2000, 12, 31))

    def test_unrecognised_word_returns_none(self):
        self.assertIsNone(resolve_date('week'))
        self.assertIsNone(resolve_date('next monday'))
        self.assertIsNone(resolve_date('monday'))

    def test_wrong_date_format_returns_none(self):
        self.assertIsNone(resolve_date('15-01-2024'))
        self.assertIsNone(resolve_date('2024/01/15'))

    def test_empty_string_returns_none(self):
        self.assertIsNone(resolve_date(''))
