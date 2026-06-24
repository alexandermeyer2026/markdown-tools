import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models import Task, TaskTime
from parser.file_model import RawLine, TaskBlock
from tools.journal_tools.cli_utils import parse_date_flags
from tools.journal_tools.ics_tool import (
    IcsTool,
    _build_ics,
    _collect_vevent_lines,
    _escape,
    _make_uid,
    _parse_time,
    _task_to_vevent_lines,
)


DATE = datetime.date(2026, 6, 21)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(title, status='todo', time=None, indent='', priority=None, tags=None):
    return Task(
        title=title, status=status, time=time,
        line_number=-1, indent=indent, priority=priority, tags=tags or [],
    )


def _make_block(title, **kwargs):
    task = _make_task(title, **kwargs)
    block = TaskBlock(task=task, header='')
    block.refresh_header()
    return block


def _write_journal(tmp_dir, date, content):
    path = os.path.join(tmp_dir, f'{date}.md')
    Path(path).write_text(content, encoding='utf-8')
    return path


def _parse_ics(content: str) -> list[dict]:
    """Parse VEVENT blocks from ICS text into dicts of property→value."""
    events = []
    current = None
    for raw_line in content.splitlines():
        line = raw_line.rstrip('\r')
        if line == 'BEGIN:VEVENT':
            current = {}
        elif line == 'END:VEVENT':
            if current is not None:
                events.append(current)
            current = None
        elif current is not None and ':' in line:
            key, _, value = line.partition(':')
            current[key] = value
    return events


# ---------------------------------------------------------------------------
# _escape
# ---------------------------------------------------------------------------

class TestEscape(unittest.TestCase):
    def test_plain_text_unchanged(self):
        self.assertEqual(_escape('hello world'), 'hello world')

    def test_backslash_escaped(self):
        self.assertEqual(_escape('a\\b'), 'a\\\\b')

    def test_comma_escaped(self):
        self.assertEqual(_escape('a,b'), 'a\\,b')

    def test_semicolon_escaped(self):
        self.assertEqual(_escape('a;b'), 'a\\;b')

    def test_newline_escaped(self):
        self.assertEqual(_escape('a\nb'), 'a\\nb')

    def test_multiple_special_chars(self):
        result = _escape('a,b;c\\d')
        self.assertIn('\\,', result)
        self.assertIn('\\;', result)
        self.assertIn('\\\\', result)


# ---------------------------------------------------------------------------
# _parse_time
# ---------------------------------------------------------------------------

class TestParseTime(unittest.TestCase):
    def test_parses_hour_and_minute(self):
        self.assertEqual(_parse_time('9:00'), datetime.time(9, 0))

    def test_parses_two_digit_hour(self):
        self.assertEqual(_parse_time('14:30'), datetime.time(14, 30))

    def test_midnight(self):
        self.assertEqual(_parse_time('0:00'), datetime.time(0, 0))


# ---------------------------------------------------------------------------
# _make_uid
# ---------------------------------------------------------------------------

class TestMakeUid(unittest.TestCase):
    def test_returns_string(self):
        self.assertIsInstance(_make_uid('2026-06-21', 0), str)

    def test_deterministic(self):
        self.assertEqual(_make_uid('2026-06-21', 0), _make_uid('2026-06-21', 0))

    def test_different_index_gives_different_uid(self):
        self.assertNotEqual(_make_uid('2026-06-21', 0), _make_uid('2026-06-21', 1))

    def test_different_date_gives_different_uid(self):
        self.assertNotEqual(_make_uid('2026-06-21', 0), _make_uid('2026-06-22', 0))


# ---------------------------------------------------------------------------
# _task_to_vevent_lines
# ---------------------------------------------------------------------------

class TestTaskToVeventLines(unittest.TestCase):
    def _vevent(self, **kwargs) -> dict:
        task = _make_task(**kwargs)
        lines = _task_to_vevent_lines(task, DATE, 0)
        return {k: v for k, v in (l.partition(':')[::2] for l in lines if ':' in l)}

    def test_begins_and_ends_correctly(self):
        task = _make_task('Task')
        lines = _task_to_vevent_lines(task, DATE, 0)
        self.assertEqual(lines[0], 'BEGIN:VEVENT')
        self.assertEqual(lines[-1], 'END:VEVENT')

    def test_summary_is_title(self):
        props = self._vevent(title='Write tests')
        self.assertEqual(props['SUMMARY'], 'Write tests')

    def test_uid_present(self):
        props = self._vevent(title='Task')
        self.assertIn('UID', props)

    def test_status_mapping(self):
        cases = [
            ('todo',        'TENTATIVE'),
            ('done',        'CONFIRMED'),
            ('in progress', 'CONFIRMED'),
            ('started',     'CONFIRMED'),
            ('failed',      'CANCELLED'),
            (None,          'TENTATIVE'),
        ]
        for status, expected in cases:
            with self.subTest(status=status):
                self.assertEqual(self._vevent(title='T', status=status)['STATUS'], expected)

    def test_priority_mapping(self):
        cases = [
            ('!!!', '1'),
            ('!!',  '5'),
            ('!',   '9'),
            (None,  '0'),
        ]
        for priority, expected in cases:
            with self.subTest(priority=priority):
                self.assertEqual(self._vevent(title='T', priority=priority)['PRIORITY'], expected)

    def test_timed_task_dtstart_has_time(self):
        task = _make_task('Meeting', time=TaskTime(start='9:00', end='10:00'))
        lines = _task_to_vevent_lines(task, DATE, 0)
        dtstart = next(l for l in lines if l.startswith('DTSTART:'))
        self.assertIn('T090000', dtstart)

    def test_timed_task_dtend_has_time(self):
        task = _make_task('Meeting', time=TaskTime(start='9:00', end='10:30'))
        lines = _task_to_vevent_lines(task, DATE, 0)
        dtend = next(l for l in lines if l.startswith('DTEND:'))
        self.assertIn('T103000', dtend)

    def test_timed_task_no_end_defaults_one_hour(self):
        task = _make_task('Standup', time=TaskTime(start='9:00'))
        lines = _task_to_vevent_lines(task, DATE, 0)
        dtend = next(l for l in lines if l.startswith('DTEND:'))
        self.assertIn('T100000', dtend)

    def test_untimed_task_uses_value_date(self):
        task = _make_task('Read')
        lines = _task_to_vevent_lines(task, DATE, 0)
        dtstart = next(l for l in lines if l.startswith('DTSTART'))
        self.assertIn('VALUE=DATE', dtstart)
        self.assertIn('20260621', dtstart)

    def test_untimed_task_dtend_is_next_day(self):
        task = _make_task('Read')
        lines = _task_to_vevent_lines(task, DATE, 0)
        dtend = next(l for l in lines if l.startswith('DTEND'))
        self.assertIn('20260622', dtend)

    def test_tags_become_categories(self):
        task = _make_task('Exercise', tags=['health', 'morning'])
        lines = _task_to_vevent_lines(task, DATE, 0)
        categories = next((l for l in lines if l.startswith('CATEGORIES')), None)
        self.assertIsNotNone(categories)
        self.assertIn('health', categories)
        self.assertIn('morning', categories)

    def test_no_tags_no_categories_line(self):
        task = _make_task('Task')
        lines = _task_to_vevent_lines(task, DATE, 0)
        self.assertFalse(any(l.startswith('CATEGORIES') for l in lines))

    def test_title_with_comma_escaped(self):
        task = _make_task('Buy milk, eggs')
        lines = _task_to_vevent_lines(task, DATE, 0)
        summary = next(l for l in lines if l.startswith('SUMMARY'))
        self.assertIn('\\,', summary)

    def test_date_reflected_in_dtstart(self):
        task = _make_task('Task')
        lines = _task_to_vevent_lines(task, datetime.date(2026, 1, 5), 0)
        dtstart = next(l for l in lines if l.startswith('DTSTART'))
        self.assertIn('20260105', dtstart)


# ---------------------------------------------------------------------------
# _collect_vevent_lines
# ---------------------------------------------------------------------------

class TestCollectVeventLines(unittest.TestCase):
    def test_flat_tasks_emitted(self):
        nodes = [_make_block('A'), _make_block('B')]
        events = _collect_vevent_lines(nodes, DATE, [0])
        self.assertEqual(len(events), 2)

    def test_nested_tasks_flattened(self):
        parent = _make_block('Parent')
        child = _make_block('Child', indent='  ')
        parent.nodes.append(child)
        events = _collect_vevent_lines([parent], DATE, [0])
        self.assertEqual(len(events), 2)
        titles = [next(l for l in e if l.startswith('SUMMARY')).split(':')[1] for e in events]
        self.assertEqual(titles, ['Parent', 'Child'])

    def test_document_order_preserved(self):
        nodes = [_make_block(f'Task {i}') for i in range(4)]
        events = _collect_vevent_lines(nodes, DATE, [0])
        titles = [next(l for l in e if l.startswith('SUMMARY')).split(':')[1] for e in events]
        self.assertEqual(titles, [f'Task {i}' for i in range(4)])

    def test_rawlines_skipped(self):
        nodes = [RawLine('# Heading\n'), _make_block('Task'), RawLine('\n')]
        events = _collect_vevent_lines(nodes, DATE, [0])
        self.assertEqual(len(events), 1)

    def test_counter_increments_across_calls(self):
        counter = [0]
        nodes = [_make_block('A'), _make_block('B')]
        _collect_vevent_lines(nodes, DATE, counter)
        self.assertEqual(counter[0], 2)

    def test_empty_nodes(self):
        self.assertEqual(_collect_vevent_lines([], DATE, [0]), [])


# ---------------------------------------------------------------------------
# _build_ics
# ---------------------------------------------------------------------------

class TestBuildIcs(unittest.TestCase):
    def test_vcalendar_wrapper(self):
        result = _build_ics([])
        self.assertIn('BEGIN:VCALENDAR', result)
        self.assertIn('END:VCALENDAR', result)

    def test_version_and_prodid(self):
        result = _build_ics([])
        self.assertIn('VERSION:2.0', result)
        self.assertIn('PRODID:', result)

    def test_calname_header(self):
        result = _build_ics([])
        self.assertIn('X-WR-CALNAME:Journal', result)

    def test_crlf_line_endings(self):
        result = _build_ics([])
        self.assertIn('\r\n', result)
        self.assertFalse('\n\n' in result.replace('\r\n', '\n'))

    def test_events_included(self):
        event = ['BEGIN:VEVENT', 'SUMMARY:Test', 'END:VEVENT']
        result = _build_ics([event])
        self.assertIn('BEGIN:VEVENT', result)
        self.assertIn('SUMMARY:Test', result)
        self.assertIn('END:VEVENT', result)

    def test_multiple_events(self):
        events = [
            ['BEGIN:VEVENT', f'SUMMARY:Task {i}', 'END:VEVENT']
            for i in range(3)
        ]
        result = _build_ics(events)
        for i in range(3):
            self.assertIn(f'SUMMARY:Task {i}', result)

    def test_ends_with_crlf(self):
        result = _build_ics([])
        self.assertTrue(result.endswith('\r\n'))


# ---------------------------------------------------------------------------
# _parse_date_flags
# ---------------------------------------------------------------------------

class TestParseDateFlags(unittest.TestCase):
    def test_no_flags(self):
        remaining, date_from, date_to = parse_date_flags(['out.ics'])
        self.assertEqual(remaining, ['out.ics'])
        self.assertIsNone(date_from)
        self.assertIsNone(date_to)

    def test_from_flag(self):
        _, date_from, _ = parse_date_flags(['--from', '2026-06-01'])
        self.assertEqual(date_from, datetime.date(2026, 6, 1))

    def test_to_flag(self):
        _, _, date_to = parse_date_flags(['--to', '2026-06-30'])
        self.assertEqual(date_to, datetime.date(2026, 6, 30))

    def test_both_flags(self):
        _, date_from, date_to = parse_date_flags(['--from', '2026-06-01', '--to', '2026-06-30'])
        self.assertEqual(date_from, datetime.date(2026, 6, 1))
        self.assertEqual(date_to, datetime.date(2026, 6, 30))

    def test_positional_preserved(self):
        remaining, _, _ = parse_date_flags(['out.ics', '--from', '2026-06-01'])
        self.assertEqual(remaining, ['out.ics'])

    def test_invalid_date_exits(self):
        with self.assertRaises(SystemExit):
            parse_date_flags(['--from', 'not-a-date'])

    def test_trailing_flag_without_value_exits(self):
        with self.assertRaises(SystemExit):
            parse_date_flags(['--to'])


# ---------------------------------------------------------------------------
# IcsTool.export
# ---------------------------------------------------------------------------

class TestIcsToolExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _export(self, args=None):
        out = os.path.join(self.tmp, 'out.ics')
        IcsTool.export((args or []) + [out], self.tmp)
        return Path(out).read_text(encoding='utf-8')

    def test_writes_valid_vcalendar(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task\n')
        content = self._export()
        self.assertIn('BEGIN:VCALENDAR', content)
        self.assertIn('END:VCALENDAR', content)

    def test_task_exported_as_vevent(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] My task\n')
        content = self._export()
        self.assertIn('BEGIN:VEVENT', content)
        self.assertIn('SUMMARY:My task', content)

    def test_timed_task_has_datetime_dtstart(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] 9:00-10:00 Meeting\n')
        content = self._export()
        self.assertIn('DTSTART:20260621T090000', content)
        self.assertIn('DTEND:20260621T100000', content)

    def test_untimed_task_has_date_only_dtstart(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Read\n')
        content = self._export()
        self.assertIn('DTSTART;VALUE=DATE:20260621', content)
        self.assertIn('DTEND;VALUE=DATE:20260622', content)

    def test_multiple_tasks_multiple_vevents(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] A\n- [ ] B\n- [ ] C\n')
        content = self._export()
        self.assertEqual(content.count('BEGIN:VEVENT'), 3)

    def test_nested_tasks_flattened(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Parent\n  - [ ] Child\n')
        content = self._export()
        self.assertEqual(content.count('BEGIN:VEVENT'), 2)
        self.assertIn('SUMMARY:Parent', content)
        self.assertIn('SUMMARY:Child', content)

    def test_multiple_files(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] A\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] B\n')
        content = self._export()
        self.assertEqual(content.count('BEGIN:VEVENT'), 2)

    def test_prose_lines_not_exported(self):
        _write_journal(self.tmp, '2026-06-21', '# Heading\n\n- [ ] Task\n')
        content = self._export()
        self.assertEqual(content.count('BEGIN:VEVENT'), 1)
        self.assertNotIn('Heading', content)

    def test_date_from_filter(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] Old\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] New\n')
        content = self._export(['--from', '2026-06-15'])
        self.assertEqual(content.count('BEGIN:VEVENT'), 1)
        self.assertIn('SUMMARY:New', content)
        self.assertNotIn('SUMMARY:Old', content)

    def test_date_to_filter(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] Old\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] New\n')
        content = self._export(['--to', '2026-06-15'])
        self.assertEqual(content.count('BEGIN:VEVENT'), 1)
        self.assertIn('SUMMARY:Old', content)

    def test_date_from_to_filter(self):
        _write_journal(self.tmp, '2026-06-01', '- [ ] A\n')
        _write_journal(self.tmp, '2026-06-10', '- [ ] B\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] C\n')
        content = self._export(['--from', '2026-06-05', '--to', '2026-06-15'])
        self.assertEqual(content.count('BEGIN:VEVENT'), 1)
        self.assertIn('SUMMARY:B', content)

    def test_empty_directory_writes_empty_calendar(self):
        content = self._export()
        self.assertIn('BEGIN:VCALENDAR', content)
        self.assertNotIn('BEGIN:VEVENT', content)

    def test_default_output_filename(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task\n')
        default_out = os.path.join(os.getcwd(), 'journal_export.ics')
        try:
            IcsTool.export([], self.tmp)
            self.assertTrue(os.path.exists(default_out))
        finally:
            if os.path.exists(default_out):
                os.remove(default_out)

    def test_crlf_line_endings_in_file(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task\n')
        out = os.path.join(self.tmp, 'out.ics')
        IcsTool.export([out], self.tmp)
        raw = Path(out).read_bytes()
        self.assertIn(b'\r\n', raw)

    def test_uid_stable_across_exports(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task\n')
        out = os.path.join(self.tmp, 'out.ics')
        IcsTool.export([out], self.tmp)
        first = _parse_ics(Path(out).read_text())
        IcsTool.export([out], self.tmp)
        second = _parse_ics(Path(out).read_text())
        self.assertEqual(first[0]['UID'], second[0]['UID'])

    def test_priority_exported(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] !!! Urgent task\n')
        content = self._export()
        self.assertIn('PRIORITY:1', content)

    def test_tags_exported_as_categories(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task\n    #work #health\n')
        content = self._export()
        self.assertIn('CATEGORIES:', content)

    def test_prints_summary(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] A\n- [ ] B\n')
        out = os.path.join(self.tmp, 'out.ics')
        with patch('builtins.print') as mock_print:
            IcsTool.export([out], self.tmp)
        output = ' '.join(str(a) for c in mock_print.call_args_list for a in c[0])
        self.assertIn('2', output)
