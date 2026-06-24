import os
import tempfile
import unittest

from tools.journal_tools.time_machine_tool import (
    _extract_ts,
    _fmt_ts,
    _diff,
    _read,
)


class TestExtractTs(unittest.TestCase):
    def test_extracts_datetime_with_microseconds(self):
        self.assertEqual(
            _extract_ts('2024-01-15T09:30:00.123456_notes.md'),
            '2024-01-15T09:30:00.123456',
        )

    def test_extracts_datetime_without_microseconds(self):
        self.assertEqual(
            _extract_ts('2024-01-15T09:30:00_notes.md'),
            '2024-01-15T09:30:00',
        )

    def test_no_match_returns_full_name(self):
        self.assertEqual(_extract_ts('notimestamp.md'), 'notimestamp.md')


class TestFmtTs(unittest.TestCase):
    def test_formats_with_microseconds(self):
        self.assertEqual(_fmt_ts('2024-01-15T09:30:00.123456'), '2024-01-15  09:30:00')

    def test_formats_without_microseconds(self):
        self.assertEqual(_fmt_ts('2024-01-15T09:30:00'), '2024-01-15  09:30:00')

    def test_unrecognised_string_returned_as_is(self):
        self.assertEqual(_fmt_ts('garbage'), 'garbage')


class TestRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        self.tmp.write('line one\nline two\n')
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_reads_lines(self):
        self.assertEqual(_read(self.tmp.name), ['line one\n', 'line two\n'])

    def test_missing_file_returns_error_line(self):
        result = _read('/nonexistent/path.md')
        self.assertEqual(len(result), 1)
        self.assertIn('error', result[0])


class TestDiff(unittest.TestCase):
    def test_produces_unified_diff(self):
        current  = ['hello\n', 'world\n']
        selected = ['hello\n', 'earth\n']
        result   = _diff(current, selected)
        self.assertTrue(any('-world' in l for l in result))
        self.assertTrue(any('+earth' in l for l in result))

    def test_identical_files_produce_no_diff(self):
        lines = ['same\n', 'content\n']
        self.assertEqual(_diff(lines, lines), [])
