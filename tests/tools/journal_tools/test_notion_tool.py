import csv
import datetime
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parser.file_model import RawLine, TaskBlock, parse, parse_lines, serialize
from models import Task, TaskTime
from tools.journal_tools.cli_utils import parse_date_flags
from tools.journal_tools.notion_tool import (
    CSV_FIELDNAMES,
    NotionTool,
    _collect_rows,
    _count_task_runs,
    _replace_task_runs,
    _row_to_task_block,
    _rows_to_nodes,
    _task_to_row,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(title, status='todo', time=None, indent='', priority=None, tags=None):
    return Task(
        title=title,
        status=status,
        time=time,
        line_number=-1,
        indent=indent,
        priority=priority,
        tags=tags or [],
    )


def _make_block(title, **kwargs):
    task = _make_task(title, **kwargs)
    block = TaskBlock(task=task, header='')
    block.refresh_header()
    return block


def _read_csv(path: str) -> list[dict]:
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _write_journal(tmp_dir: str, date: str, content: str) -> str:
    path = os.path.join(tmp_dir, f'{date}.md')
    Path(path).write_text(content, encoding='utf-8')
    return path


def _write_csv(tmp_dir: str, rows: list[dict], filename='import.csv') -> str:
    path = os.path.join(tmp_dir, filename)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# _task_to_row
# ---------------------------------------------------------------------------

class TestTaskToRow(unittest.TestCase):
    def test_basic_fields(self):
        task = _make_task('Write tests', status='done')
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Title'], 'Write tests')
        self.assertEqual(row['Status'], 'done')
        self.assertEqual(row['Date'], '2026-06-21')
        self.assertEqual(row['Depth'], 0)

    def test_time_start_and_end(self):
        task = _make_task('Meeting', time=TaskTime(start='9:00', end='10:00'))
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Time Start'], '9:00')
        self.assertEqual(row['Time End'], '10:00')

    def test_time_start_only(self):
        task = _make_task('Standup', time=TaskTime(start='9:00'))
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Time Start'], '9:00')
        self.assertEqual(row['Time End'], '')

    def test_no_time(self):
        task = _make_task('Read')
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Time Start'], '')
        self.assertEqual(row['Time End'], '')

    def test_priority(self):
        task = _make_task('Urgent', priority='!!!')
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Priority'], '!!!')

    def test_no_priority(self):
        task = _make_task('Normal')
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Priority'], '')

    def test_tags(self):
        task = _make_task('Exercise', tags=['health', 'morning'])
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Tags'], 'health,morning')

    def test_no_tags(self):
        task = _make_task('Read')
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Tags'], '')

    def test_depth_propagated(self):
        task = _make_task('Subtask', indent='  ')
        row = _task_to_row(task, '2026-06-21', 2)
        self.assertEqual(row['Depth'], 2)

    def test_none_status_becomes_empty(self):
        task = _make_task('Unknown', status=None)
        row = _task_to_row(task, '2026-06-21', 0)
        self.assertEqual(row['Status'], '')


# ---------------------------------------------------------------------------
# _collect_rows
# ---------------------------------------------------------------------------

class TestCollectRows(unittest.TestCase):
    def test_flat_tasks(self):
        nodes = [_make_block('Task A'), _make_block('Task B')]
        rows = _collect_rows(nodes, '2026-06-21')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['Title'], 'Task A')
        self.assertEqual(rows[1]['Title'], 'Task B')

    def test_all_depths_zero_for_top_level(self):
        nodes = [_make_block('Task A'), _make_block('Task B')]
        rows = _collect_rows(nodes, '2026-06-21')
        self.assertTrue(all(r['Depth'] == 0 for r in rows))

    def test_nested_tasks_have_correct_depth(self):
        parent = _make_block('Parent')
        child = _make_block('Child', indent='  ')
        parent.nodes.append(child)
        rows = _collect_rows([parent], '2026-06-21')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['Depth'], 0)
        self.assertEqual(rows[1]['Depth'], 1)

    def test_deeply_nested(self):
        grandparent = _make_block('Grandparent')
        parent = _make_block('Parent', indent='  ')
        child = _make_block('Child', indent='    ')
        parent.nodes.append(child)
        grandparent.nodes.append(parent)
        rows = _collect_rows([grandparent], '2026-06-21')
        self.assertEqual([r['Depth'] for r in rows], [0, 1, 2])
        self.assertEqual([r['Title'] for r in rows], ['Grandparent', 'Parent', 'Child'])

    def test_skips_raw_lines(self):
        nodes = [RawLine('# Heading\n'), _make_block('Task'), RawLine('\n')]
        rows = _collect_rows(nodes, '2026-06-21')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Title'], 'Task')

    def test_date_set_on_all_rows(self):
        nodes = [_make_block('A'), _make_block('B')]
        rows = _collect_rows(nodes, '2026-06-10')
        self.assertTrue(all(r['Date'] == '2026-06-10' for r in rows))

    def test_document_order_preserved(self):
        nodes = [_make_block(f'Task {i}') for i in range(5)]
        rows = _collect_rows(nodes, '2026-06-21')
        self.assertEqual([r['Title'] for r in rows], [f'Task {i}' for i in range(5)])

    def test_empty_nodes(self):
        self.assertEqual(_collect_rows([], '2026-06-21'), [])


# ---------------------------------------------------------------------------
# _row_to_task_block
# ---------------------------------------------------------------------------

class TestRowToTaskBlock(unittest.TestCase):
    def _row(self, **kwargs):
        defaults = {
            'Title': 'Task', 'Status': 'todo', 'Date': '2026-06-21',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0',
        }
        defaults.update(kwargs)
        return defaults

    def test_title_and_status(self):
        block = _row_to_task_block(self._row(Title='Write tests', Status='done'))
        self.assertEqual(block.task.title, 'Write tests')
        self.assertEqual(block.task.status, 'done')

    def test_empty_status_becomes_none(self):
        block = _row_to_task_block(self._row(Status=''))
        self.assertIsNone(block.task.status)

    def test_time_start_and_end(self):
        block = _row_to_task_block(self._row(**{'Time Start': '9:00', 'Time End': '10:00'}))
        self.assertEqual(block.task.time.start, '9:00')
        self.assertEqual(block.task.time.end, '10:00')

    def test_time_start_only(self):
        block = _row_to_task_block(self._row(**{'Time Start': '9:00', 'Time End': ''}))
        self.assertEqual(block.task.time.start, '9:00')
        self.assertIsNone(block.task.time.end)

    def test_no_time(self):
        block = _row_to_task_block(self._row(**{'Time Start': '', 'Time End': ''}))
        self.assertIsNone(block.task.time)

    def test_priority(self):
        block = _row_to_task_block(self._row(Priority='!!'))
        self.assertEqual(block.task.priority, '!!')

    def test_empty_priority_becomes_none(self):
        block = _row_to_task_block(self._row(Priority=''))
        self.assertIsNone(block.task.priority)

    def test_tags_parsed(self):
        block = _row_to_task_block(self._row(Tags='health,work'))
        self.assertEqual(block.task.tags, ['health', 'work'])

    def test_empty_tags(self):
        block = _row_to_task_block(self._row(Tags=''))
        self.assertEqual(block.task.tags, [])

    def test_tags_create_tag_node(self):
        block = _row_to_task_block(self._row(Tags='work'))
        self.assertIsNotNone(block.tag_node)
        self.assertIn('#work', block.tag_node.raw)

    def test_no_tags_no_tag_node(self):
        block = _row_to_task_block(self._row(Tags=''))
        self.assertIsNone(block.tag_node)

    def test_depth_sets_indent(self):
        from config import get_indent_step
        step = get_indent_step()
        block = _row_to_task_block(self._row(Depth='2'))
        self.assertEqual(block.task.indent, step * 2)

    def test_header_matches_task_line(self):
        block = _row_to_task_block(self._row(Title='My task', Status='todo'))
        self.assertEqual(block.header, block.task.to_line() + '\n')


# ---------------------------------------------------------------------------
# _rows_to_nodes
# ---------------------------------------------------------------------------

class TestRowsToNodes(unittest.TestCase):
    def _row(self, title, depth, status='todo'):
        return {
            'Title': title, 'Status': status, 'Date': '2026-06-21',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': str(depth),
        }

    def test_all_depth_zero_gives_flat_list(self):
        rows = [self._row('A', 0), self._row('B', 0), self._row('C', 0)]
        nodes = _rows_to_nodes(rows)
        self.assertEqual(len(nodes), 3)
        self.assertTrue(all(isinstance(n, TaskBlock) for n in nodes))

    def test_nesting_restored(self):
        rows = [self._row('Parent', 0), self._row('Child', 1), self._row('Sibling', 0)]
        nodes = _rows_to_nodes(rows)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0].task.title, 'Parent')
        self.assertEqual(len(nodes[0].nodes), 1)
        self.assertEqual(nodes[0].nodes[0].task.title, 'Child')
        self.assertEqual(nodes[1].task.title, 'Sibling')

    def test_deep_nesting(self):
        rows = [self._row('A', 0), self._row('B', 1), self._row('C', 2)]
        nodes = _rows_to_nodes(rows)
        self.assertEqual(len(nodes), 1)
        b = nodes[0].nodes[0]
        self.assertEqual(b.task.title, 'B')
        c = b.nodes[0]
        self.assertEqual(c.task.title, 'C')

    def test_multiple_children(self):
        rows = [
            self._row('Parent', 0),
            self._row('Child 1', 1),
            self._row('Child 2', 1),
        ]
        nodes = _rows_to_nodes(rows)
        self.assertEqual(len(nodes), 1)
        children = [n for n in nodes[0].nodes if isinstance(n, TaskBlock)]
        self.assertEqual(len(children), 2)

    def test_empty_rows(self):
        self.assertEqual(_rows_to_nodes([]), [])


# ---------------------------------------------------------------------------
# _replace_task_runs
# ---------------------------------------------------------------------------

class TestReplaceTaskRuns(unittest.TestCase):
    def test_replaces_tasks_preserves_rawlines(self):
        heading = RawLine('# Heading\n')
        old_task = _make_block('Old task')
        trailing = RawLine('\n')
        new_task = _make_block('New task')

        result = _replace_task_runs([heading, old_task, trailing], [new_task])
        self.assertEqual(len(result), 3)
        self.assertIs(result[0], heading)
        self.assertIs(result[1], new_task)
        self.assertIs(result[2], trailing)

    def test_no_tasks_in_file_appends_new(self):
        heading = RawLine('# Heading\n')
        new_task = _make_block('New task')
        result = _replace_task_runs([heading], [new_task])
        self.assertEqual(result, [heading, new_task])

    def test_multiple_old_tasks_all_replaced(self):
        old_a = _make_block('Old A')
        old_b = _make_block('Old B')
        new_task = _make_block('New')
        result = _replace_task_runs([old_a, old_b], [new_task])
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], new_task)

    def test_prose_between_task_runs_preserved(self):
        # First task run, prose, second task run — second run is dropped
        prose = RawLine('Some notes\n')
        task_a = _make_block('A')
        task_b = _make_block('B')
        new_task = _make_block('New')
        result = _replace_task_runs([task_a, prose, task_b], [new_task])
        self.assertIn(prose, result)
        titles = [n.task.title for n in result if isinstance(n, TaskBlock)]
        self.assertEqual(titles, ['New'])

    def test_empty_new_tasks_clears_old(self):
        old_task = _make_block('Old')
        result = _replace_task_runs([old_task], [])
        self.assertEqual(result, [])

    def test_rawlines_only_no_tasks_returns_unchanged_plus_new(self):
        lines = [RawLine('line\n'), RawLine('\n')]
        result = _replace_task_runs(lines, [])
        self.assertEqual(result, lines)


# ---------------------------------------------------------------------------
# _count_task_runs
# ---------------------------------------------------------------------------

class TestCountTaskRuns(unittest.TestCase):
    def test_no_tasks(self):
        self.assertEqual(_count_task_runs([RawLine('# Heading\n')]), 0)

    def test_single_run(self):
        nodes = [_make_block('A'), _make_block('B')]
        self.assertEqual(_count_task_runs(nodes), 1)

    def test_two_runs_separated_by_prose(self):
        nodes = [_make_block('A'), RawLine('\n'), RawLine('## Section\n'), _make_block('B')]
        self.assertEqual(_count_task_runs(nodes), 2)

    def test_prose_only(self):
        nodes = [RawLine('# H\n'), RawLine('\n')]
        self.assertEqual(_count_task_runs(nodes), 0)

    def test_contiguous_tasks_count_as_one(self):
        nodes = [_make_block('A'), _make_block('B'), _make_block('C')]
        self.assertEqual(_count_task_runs(nodes), 1)


# ---------------------------------------------------------------------------
# _parse_date_flags
# ---------------------------------------------------------------------------

class TestParseDateFlags(unittest.TestCase):
    def test_no_flags(self):
        remaining, date_from, date_to = parse_date_flags(['out.csv'])
        self.assertEqual(remaining, ['out.csv'])
        self.assertIsNone(date_from)
        self.assertIsNone(date_to)

    def test_from_flag(self):
        remaining, date_from, date_to = parse_date_flags(['--from', '2026-06-01'])
        self.assertEqual(remaining, [])
        self.assertEqual(date_from, datetime.date(2026, 6, 1))
        self.assertIsNone(date_to)

    def test_to_flag(self):
        remaining, date_from, date_to = parse_date_flags(['--to', '2026-06-30'])
        self.assertIsNone(date_from)
        self.assertEqual(date_to, datetime.date(2026, 6, 30))

    def test_from_and_to(self):
        remaining, date_from, date_to = parse_date_flags(
            ['--from', '2026-06-01', '--to', '2026-06-30']
        )
        self.assertEqual(date_from, datetime.date(2026, 6, 1))
        self.assertEqual(date_to, datetime.date(2026, 6, 30))

    def test_positional_preserved(self):
        remaining, _, _ = parse_date_flags(['out.csv', '--from', '2026-06-01'])
        self.assertEqual(remaining, ['out.csv'])

    def test_invalid_date_exits(self):
        with self.assertRaises(SystemExit):
            parse_date_flags(['--from', 'not-a-date'])

    def test_trailing_flag_without_value_exits(self):
        with self.assertRaises(SystemExit):
            parse_date_flags(['--from'])


# ---------------------------------------------------------------------------
# NotionTool.export
# ---------------------------------------------------------------------------

class TestNotionToolExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_writes_csv_with_correct_headers(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task A\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(list(rows[0].keys()), CSV_FIELDNAMES)

    def test_exports_task_title_and_status(self):
        _write_journal(self.tmp, '2026-06-21', '- [x] Done task\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(rows[0]['Title'], 'Done task')
        self.assertEqual(rows[0]['Status'], 'done')

    def test_exports_date_from_filename(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] Task\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(rows[0]['Date'], '2026-06-10')

    def test_exports_multiple_files(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] A\n')
        _write_journal(self.tmp, '2026-06-11', '- [ ] B\n- [ ] C\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(len(rows), 3)

    def test_exports_nested_tasks_with_depth(self):
        content = '- [ ] Parent\n  - [ ] Child\n'
        _write_journal(self.tmp, '2026-06-21', content)
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(rows[0]['Title'], 'Parent')
        self.assertEqual(rows[0]['Depth'], '0')
        self.assertEqual(rows[1]['Title'], 'Child')
        self.assertEqual(rows[1]['Depth'], '1')

    def test_exports_task_with_time(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] 9:00-10:00 Meeting\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(rows[0]['Time Start'], '9:00')
        self.assertEqual(rows[0]['Time End'], '10:00')

    def test_exports_task_with_priority(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] !!! Urgent\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(rows[0]['Priority'], '!!!')

    def test_skips_prose_lines(self):
        content = '# Heading\n\n- [ ] Task\n'
        _write_journal(self.tmp, '2026-06-21', content)
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(len(rows), 1)

    def test_default_output_filename(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task\n')
        default_out = os.path.join(os.getcwd(), 'notion_export.csv')
        try:
            NotionTool.export([], self.tmp)
            self.assertTrue(os.path.exists(default_out))
        finally:
            if os.path.exists(default_out):
                os.remove(default_out)

    def test_date_range_from_filter(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] Old\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] New\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out, '--from', '2026-06-15'], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Title'], 'New')

    def test_date_range_to_filter(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] Old\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] New\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out, '--to', '2026-06-15'], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Title'], 'Old')

    def test_date_range_from_to_filter(self):
        _write_journal(self.tmp, '2026-06-01', '- [ ] A\n')
        _write_journal(self.tmp, '2026-06-10', '- [ ] B\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] C\n')
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out, '--from', '2026-06-05', '--to', '2026-06-15'], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Title'], 'B')

    def test_empty_directory_writes_header_only(self):
        out = os.path.join(self.tmp, 'out.csv')
        NotionTool.export([out], self.tmp)
        rows = _read_csv(out)
        self.assertEqual(rows, [])

    def test_prints_summary(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] A\n- [ ] B\n')
        out = os.path.join(self.tmp, 'out.csv')
        with patch('builtins.print') as mock_print:
            NotionTool.export([out], self.tmp)
        output = ' '.join(str(c) for c in mock_print.call_args[0])
        self.assertIn('2', output)
        self.assertIn('1', output)


# ---------------------------------------------------------------------------
# NotionTool.import_
# ---------------------------------------------------------------------------

class TestNotionToolImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _confirm(self):
        return patch('builtins.input', return_value='y')

    def _abort(self):
        return patch('builtins.input', return_value='n')

    def test_no_args_exits(self):
        with self.assertRaises(SystemExit):
            NotionTool.import_([], self.tmp)

    def test_abort_does_not_modify_file(self):
        original = '- [ ] Original\n'
        _write_journal(self.tmp, '2026-06-21', original)
        csv_path = _write_csv(self.tmp, [{
            'Title': 'Changed', 'Status': 'done', 'Date': '2026-06-21',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0',
        }])
        with self._abort():
            NotionTool.import_([csv_path], self.tmp)
        content = Path(self.tmp, '2026-06-21.md').read_text()
        self.assertEqual(content, original)

    def test_replaces_tasks_in_file(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Old task\n')
        csv_path = _write_csv(self.tmp, [{
            'Title': 'New task', 'Status': 'todo', 'Date': '2026-06-21',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0',
        }])
        with self._confirm():
            NotionTool.import_([csv_path], self.tmp)
        content = Path(self.tmp, '2026-06-21.md').read_text()
        self.assertIn('New task', content)
        self.assertNotIn('Old task', content)

    def test_preserves_prose_lines(self):
        _write_journal(self.tmp, '2026-06-21', '# Heading\n\n- [ ] Task\n')
        csv_path = _write_csv(self.tmp, [{
            'Title': 'New task', 'Status': 'todo', 'Date': '2026-06-21',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0',
        }])
        with self._confirm():
            NotionTool.import_([csv_path], self.tmp)
        content = Path(self.tmp, '2026-06-21.md').read_text()
        self.assertIn('# Heading', content)

    def test_restores_nested_tasks(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Parent\n')
        csv_path = _write_csv(self.tmp, [
            {'Title': 'Parent', 'Status': 'todo', 'Date': '2026-06-21',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
            {'Title': 'Child', 'Status': 'todo', 'Date': '2026-06-21',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '1'},
        ])
        with self._confirm():
            NotionTool.import_([csv_path], self.tmp)
        content = Path(self.tmp, '2026-06-21.md').read_text()
        lines = content.splitlines()
        child_line = next(l for l in lines if 'Child' in l)
        self.assertTrue(child_line.startswith(' '), "Child should be indented")

    def test_skips_date_with_no_matching_file(self):
        csv_path = _write_csv(self.tmp, [{
            'Title': 'Ghost', 'Status': 'todo', 'Date': '2099-01-01',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0',
        }])
        with patch('builtins.print') as mock_print:
            NotionTool.import_([csv_path], self.tmp)
        printed = ' '.join(str(c[0][0]) for c in mock_print.call_args_list)
        self.assertIn('No matching', printed)

    def test_warning_printed_for_unknown_date(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task\n')
        csv_path = _write_csv(self.tmp, [
            {'Title': 'Known', 'Status': 'todo', 'Date': '2026-06-21',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
            {'Title': 'Unknown', 'Status': 'todo', 'Date': '2099-01-01',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
        ])
        with self._confirm(), patch('builtins.print') as mock_print:
            NotionTool.import_([csv_path], self.tmp)
        printed = ' '.join(str(c[0][0]) for c in mock_print.call_args_list)
        self.assertIn('Warning', printed)
        self.assertIn('2099-01-01', printed)

    def test_creates_backup_before_writing(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] Task\n')
        csv_path = _write_csv(self.tmp, [{
            'Title': 'New', 'Status': 'todo', 'Date': '2026-06-21',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0',
        }])
        with self._confirm():
            NotionTool.import_([csv_path], self.tmp)
        backups = list(Path(self.tmp, '.backups').glob('*2026-06-21.md'))
        self.assertEqual(len(backups), 1)

    def test_date_from_filter_excludes_earlier_rows(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] Old\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] Recent\n')
        csv_path = _write_csv(self.tmp, [
            {'Title': 'Old changed', 'Status': 'done', 'Date': '2026-06-10',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
            {'Title': 'Recent changed', 'Status': 'done', 'Date': '2026-06-21',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
        ])
        with self._confirm():
            NotionTool.import_([csv_path, '--from', '2026-06-15'], self.tmp)
        self.assertIn('Old', Path(self.tmp, '2026-06-10.md').read_text())
        self.assertIn('Recent changed', Path(self.tmp, '2026-06-21.md').read_text())

    def test_date_to_filter_excludes_later_rows(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] Old\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] Recent\n')
        csv_path = _write_csv(self.tmp, [
            {'Title': 'Old changed', 'Status': 'done', 'Date': '2026-06-10',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
            {'Title': 'Recent changed', 'Status': 'done', 'Date': '2026-06-21',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
        ])
        with self._confirm():
            NotionTool.import_([csv_path, '--to', '2026-06-15'], self.tmp)
        self.assertIn('Old changed', Path(self.tmp, '2026-06-10.md').read_text())
        self.assertIn('Recent', Path(self.tmp, '2026-06-21.md').read_text())
        self.assertNotIn('Recent changed', Path(self.tmp, '2026-06-21.md').read_text())

    def test_round_trip_preserves_tasks(self):
        original = '- [x] 9:00-10:00 ! Morning standup\n- [ ] Write report\n'
        _write_journal(self.tmp, '2026-06-21', original)
        csv_path = os.path.join(self.tmp, 'export.csv')
        NotionTool.export([csv_path], self.tmp)
        with self._confirm():
            NotionTool.import_([csv_path], self.tmp)
        result = Path(self.tmp, '2026-06-21.md').read_text()
        self.assertIn('Morning standup', result)
        self.assertIn('Write report', result)

    def test_multi_section_file_is_updated(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] A\n\n## Section 2\n\n- [ ] B\n')
        csv_path = _write_csv(self.tmp, [{
            'Title': 'New', 'Status': 'todo', 'Date': '2026-06-21',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0',
        }])
        with self._confirm(), patch('builtins.print'):
            NotionTool.import_([csv_path], self.tmp)
        self.assertIn('New', Path(self.tmp, '2026-06-21.md').read_text())

    def test_multi_section_file_prints_warning(self):
        _write_journal(self.tmp, '2026-06-21', '- [ ] A\n\n## Section 2\n\n- [ ] B\n')
        csv_path = _write_csv(self.tmp, [{
            'Title': 'New', 'Status': 'todo', 'Date': '2026-06-21',
            'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0',
        }])
        with self._confirm(), patch('builtins.print') as mock_print:
            NotionTool.import_([csv_path], self.tmp)
        printed = ' '.join(str(c[0][0]) for c in mock_print.call_args_list)
        self.assertIn('Warning', printed)
        self.assertIn('2026-06-21', printed)

    def test_import_multiple_files(self):
        _write_journal(self.tmp, '2026-06-10', '- [ ] A\n')
        _write_journal(self.tmp, '2026-06-21', '- [ ] B\n')
        csv_path = _write_csv(self.tmp, [
            {'Title': 'A new', 'Status': 'done', 'Date': '2026-06-10',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
            {'Title': 'B new', 'Status': 'done', 'Date': '2026-06-21',
             'Time Start': '', 'Time End': '', 'Priority': '', 'Tags': '', 'Depth': '0'},
        ])
        with self._confirm():
            NotionTool.import_([csv_path], self.tmp)
        self.assertIn('A new', Path(self.tmp, '2026-06-10.md').read_text())
        self.assertIn('B new', Path(self.tmp, '2026-06-21.md').read_text())
