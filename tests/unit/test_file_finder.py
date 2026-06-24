import datetime
import os
import tempfile
import unittest

from os_utils.file_finder import FileFinder


def make_files(directory: str, names: list[str]) -> None:
    for name in names:
        open(os.path.join(directory, name), 'w').close()


class TestGetJournalFileDate(unittest.TestCase):
    def test_valid_path(self):
        date = FileFinder.get_journal_file_date('/journal/2025-01-15.md')
        self.assertEqual(date, datetime.date(2025, 1, 15))

    def test_valid_path_in_subdir(self):
        date = FileFinder.get_journal_file_date('/some/dir/2024-12-31.md')
        self.assertEqual(date, datetime.date(2024, 12, 31))

    def test_no_date_raises(self):
        with self.assertRaises(ValueError):
            FileFinder.get_journal_file_date('/journal/notes.md')

    def test_invalid_date_raises(self):
        with self.assertRaises(ValueError):
            FileFinder.get_journal_file_date('/journal/2025-13-01.md')


class TestFindJournalFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_finds_md_files(self):
        make_files(self.tmp, ['2025-01-01.md', '2025-01-02.md'])
        results = FileFinder.find_journal_files(self.tmp)
        self.assertEqual(len(results), 2)

    def test_ignores_non_date_files(self):
        make_files(self.tmp, ['2025-01-01.md', 'notes.md', 'README.txt'])
        results = FileFinder.find_journal_files(self.tmp)
        self.assertEqual(len(results), 1)

    def test_sorted_by_date(self):
        make_files(self.tmp, ['2025-01-03.md', '2025-01-01.md', '2025-01-02.md'])
        results = FileFinder.find_journal_files(self.tmp)
        dates = [FileFinder.get_journal_file_date(f) for f in results]
        self.assertEqual(dates, sorted(dates))

    def test_date_from_filter(self):
        make_files(self.tmp, ['2025-01-01.md', '2025-01-05.md', '2025-01-10.md'])
        results = FileFinder.find_journal_files(self.tmp, date_from=datetime.date(2025, 1, 5))
        dates = [FileFinder.get_journal_file_date(f) for f in results]
        self.assertTrue(all(d >= datetime.date(2025, 1, 5) for d in dates))
        self.assertEqual(len(results), 2)

    def test_date_to_filter(self):
        make_files(self.tmp, ['2025-01-01.md', '2025-01-05.md', '2025-01-10.md'])
        results = FileFinder.find_journal_files(self.tmp, date_to=datetime.date(2025, 1, 5))
        dates = [FileFinder.get_journal_file_date(f) for f in results]
        self.assertTrue(all(d <= datetime.date(2025, 1, 5) for d in dates))
        self.assertEqual(len(results), 2)

    def test_date_range_filter(self):
        make_files(self.tmp, ['2025-01-01.md', '2025-01-05.md', '2025-01-10.md'])
        results = FileFinder.find_journal_files(
            self.tmp,
            date_from=datetime.date(2025, 1, 2),
            date_to=datetime.date(2025, 1, 9),
        )
        self.assertEqual(len(results), 1)
        self.assertIn('2025-01-05.md', results[0])

    def test_empty_directory(self):
        results = FileFinder.find_journal_files(self.tmp)
        self.assertEqual(results, [])

    def test_ignores_hidden_directories(self):
        hidden = os.path.join(self.tmp, '.backups')
        os.makedirs(hidden)
        make_files(hidden, ['2025-01-01.md'])
        results = FileFinder.find_journal_files(self.tmp)
        self.assertEqual(results, [])
