import os
import tempfile
import unittest

import pytest

from config import get_indent_step
from models.task import Task, TaskTime
from models.file import (
    RawLine, TaskBlock, parse, parse_lines, serialize, insert_task,
    move_block_in_nodes, shift_tab_task, tab_task,
)

STEP = get_indent_step()


# ── Helpers ───────────────────────────────────────────────────────────────────

def write_temp(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    f.write(content)
    f.close()
    return f.name


def roundtrip(content: str) -> str:
    path = write_temp(content)
    try:
        return serialize(parse(path))
    finally:
        os.unlink(path)


def parse_str(content: str) -> list:
    path = write_temp(content)
    try:
        return parse(path)
    finally:
        os.unlink(path)


def _flat_tasks(nodes) -> list[Task]:
    result = []
    for node in nodes:
        if isinstance(node, TaskBlock):
            result.append(node.task)
            result.extend(_flat_tasks(node.nodes))
    return result


def _parse_tasks(content: str) -> list[Task]:
    return _flat_tasks(parse_str(content))


def _block(line: str) -> TaskBlock:
    return parse_str(line if line.endswith('\n') else line + '\n')[0]


# ── Round-trip ────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestRoundTrip(unittest.TestCase):

    def test_empty_file(self):
        self.assertEqual(roundtrip(''), '')

    def test_single_task(self):
        c = '- [ ] Task\n'
        self.assertEqual(roundtrip(c), c)

    def test_task_with_body(self):
        c = '- [ ] Task\n  Note\n'
        self.assertEqual(roundtrip(c), c)

    def test_two_tasks_blank_separator(self):
        c = '- [ ] Task A\n\n- [ ] Task B\n'
        self.assertEqual(roundtrip(c), c)

    def test_subtask(self):
        c = '- [ ] Parent\n  - [ ] Child\n'
        self.assertEqual(roundtrip(c), c)

    def test_interleaved_notes_and_subtasks(self):
        c = (
            '- [ ] Parent\n'
            '  First note\n'
            '  - [ ] Child 1\n'
            '  Middle note\n'
            '  - [ ] Child 2\n'
            '  Last note\n'
        )
        self.assertEqual(roundtrip(c), c)

    def test_prose_before_tasks(self):
        c = '# Heading\n\n- [ ] Task\n'
        self.assertEqual(roundtrip(c), c)

    def test_blank_line_within_body(self):
        c = '- [ ] Task\n  Note 1\n\n  Note 2\n'
        self.assertEqual(roundtrip(c), c)

    def test_trailing_blank_line(self):
        c = '- [ ] Task\n\n'
        self.assertEqual(roundtrip(c), c)

    def test_poorly_formatted_indentation(self):
        c = (
            '- [ ] Parent\n'
            '    Parent note\n'
            '  - [ ] Child 1\n'
            '    Child 1 note\n'
            '      Child 1 note\n'
            ' - [ ] Child 2\n'
            '  - [ ] Grandchild\n'
        )
        self.assertEqual(roundtrip(c), c)

    def test_timed_task(self):
        c = '- [ ] 10:00-11:00 Meeting\n'
        self.assertEqual(roundtrip(c), c)

    def test_fixture_files(self):
        cases = [
            ("two tasks trailing blank",          "- [ ] 10:00 Morning meeting\n- [ ] 09:00 Standup\n\n"),
            ("single task",                       "- [ ] 12:00 Tuesday task\n"),
            ("task with body notes",              "- [ ] 09:00 Task A\n  Some notes\n- [ ] 10:00 Task B\n"),
            ("no trailing newline",               "- [ ] 10:00 Morning meeting\n- [ ] 09:00 Standup"),
            ("header and mixed-status tasks",     "# Journal 2024-01-15\n\n- [x] 8:00-9:00 Morning routine\n- [ ] 9:00-10:30 Work on project\n- [x] 10:30-11:00: Coffee break\n- [ ] 11:00-12:00: Team meeting\n- [ ] 14:00 Review PRs\n"),
            ("task with subtasks",                "- [ ] My task\n  - [ ] Sub task A\n  - [ ] Sub task B\n"),
            ("task with one subtask",             "- [ ] Weekend task\n  - [ ] Todo item\n"),
            ("mixed subtask status trailing blank","- [ ] My task\n  - [x] Sub task A\n  - [ ] Sub task B\n\n"),
            ("subtask blank separator",           "- [ ] My task\n  - [ ] Sub task B\n\n- [ ] Other task\n"),
            ("subtask with body notes",           "- [ ] My task\n  - [x] Done sub\n  - [ ] Todo sub\n      Todo sub notes\n"),
        ]
        for name, content in cases:
            with self.subTest(name):
                self.assertEqual(roundtrip(content), content)


# ── Structure ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestStructure(unittest.TestCase):

    def test_single_task_is_taskblock(self):
        nodes = parse_str('- [ ] Task\n')
        self.assertEqual(len(nodes), 1)
        self.assertIsInstance(nodes[0], TaskBlock)

    def test_task_title(self):
        nodes = parse_str('- [ ] My title\n')
        self.assertEqual(nodes[0].task.title, 'My title')

    def test_task_status(self):
        nodes = parse_str('- [x] Done\n')
        self.assertEqual(nodes[0].task.status, 'done')

    def test_task_indent(self):
        nodes = parse_str('- [ ] Parent\n  - [ ] Child\n')
        self.assertEqual(nodes[0].task.indent, '')
        self.assertEqual(nodes[0].nodes[0].task.indent, '  ')

    def test_header_exact(self):
        nodes = parse_str('- [x] Done task\n')
        self.assertEqual(nodes[0].header, '- [x] Done task\n')

    def test_body_rawline_exact(self):
        nodes = parse_str('- [ ] Task\n  Note\n')
        self.assertIsInstance(nodes[0].nodes[0], RawLine)
        self.assertEqual(nodes[0].nodes[0].raw, '  Note\n')

    def test_subtask_nested(self):
        nodes = parse_str('- [ ] Parent\n  - [ ] Child\n')
        self.assertIsInstance(nodes[0].nodes[0], TaskBlock)
        self.assertEqual(nodes[0].nodes[0].task.title, 'Child')

    def test_interleaved_order(self):
        nodes = parse_str(
            '- [ ] Parent\n'
            '  First\n'
            '  - [ ] Child\n'
            '  Last\n'
        )
        parent = nodes[0]
        self.assertIsInstance(parent.nodes[0], RawLine)
        self.assertIsInstance(parent.nodes[1], TaskBlock)
        self.assertIsInstance(parent.nodes[2], RawLine)

    def test_blank_between_tasks_in_first_body(self):
        nodes = parse_str('- [ ] A\n\n- [ ] B\n')
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[0], TaskBlock)
        self.assertEqual(nodes[0].task.title, 'A')
        self.assertEqual(len(nodes[0].nodes), 1)
        self.assertIsInstance(nodes[0].nodes[0], RawLine)
        self.assertEqual(nodes[0].nodes[0].raw, '\n')
        self.assertIsInstance(nodes[1], TaskBlock)
        self.assertEqual(nodes[1].task.title, 'B')

    def test_top_level_prose_rawline(self):
        nodes = parse_str('# Heading\n\n- [ ] Task\n')
        self.assertIsInstance(nodes[0], RawLine)
        self.assertEqual(nodes[0].raw, '# Heading\n')
        self.assertIsInstance(nodes[1], RawLine)
        self.assertEqual(nodes[1].raw, '\n')
        self.assertIsInstance(nodes[2], TaskBlock)

    def test_empty_file_empty_list(self):
        nodes = parse_str('')
        self.assertEqual(nodes, [])

    def test_timed_task_parsed(self):
        nodes = parse_str('- [ ] 09:00-10:00 Meeting\n')
        t = nodes[0].task
        self.assertEqual(t.title, 'Meeting')
        self.assertIsNotNone(t.time)
        self.assertEqual(t.time.start, '09:00')
        self.assertEqual(t.time.end, '10:00')

    def test_recursive_nesting(self):
        nodes = parse_str('- [ ] Top\n  - [ ] Mid\n    - [ ] Leaf\n')
        top = nodes[0]
        mid = [n for n in top.nodes if isinstance(n, TaskBlock)][0]
        leaf = [n for n in mid.nodes if isinstance(n, TaskBlock)][0]
        self.assertEqual(top.task.title, 'Top')
        self.assertEqual(mid.task.title, 'Mid')
        self.assertEqual(leaf.task.title, 'Leaf')


# ── Parsing: status and fields ────────────────────────────────────────────────

class TestParseStatus(unittest.TestCase):

    def test_all_status_chars(self):
        cases = [
            ('- [ ] Task', 'todo'),
            ('- [x] Task', 'done'),
            ('- [X] Task', 'done'),
            ('- […] Task', 'in progress'),
            ('- [–] Task', 'failed'),
            ('- [~] Task', 'started'),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(_block(line).task.status, expected)

    def test_non_task_line_skipped(self):
        self.assertEqual(_parse_tasks('Just a regular line\n'), [])


class TestParseFields(unittest.TestCase):

    def test_title_extracted(self):
        self.assertEqual(_block('- [ ] Buy milk').task.title, 'Buy milk')

    def test_time_start_only(self):
        t = _block('- [ ] 9:00 Meeting').task
        self.assertEqual(t.time.start, '9:00')
        self.assertIsNone(t.time.end)

    def test_time_range(self):
        t = _block('- [ ] 9:00-10:30 Meeting').task
        self.assertEqual(t.time.start, '9:00')
        self.assertEqual(t.time.end, '10:30')

    def test_colon_separator_stripped(self):
        t = _block('- [ ] 9:00: Meeting').task
        self.assertEqual(t.time.start, '9:00')
        self.assertEqual(t.title, 'Meeting')

    def test_no_time(self):
        self.assertIsNone(_block('- [ ] No time task').task.time)

    def test_indent_two_spaces(self):
        self.assertEqual(_block('  - [ ] Indented task').task.indent, '  ')

    def test_indent_four_spaces(self):
        self.assertEqual(_block('    - [ ] Deeply indented').task.indent, '    ')

    def test_line_number(self):
        tasks = _parse_tasks('Header\n- [ ] Task on line 2\n')
        self.assertEqual(tasks[0].line_number, 2)

    def test_multiple_tasks(self):
        tasks = _parse_tasks('- [ ] First\n- [x] Second\n- […] Third\n')
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0].title, 'First')
        self.assertEqual(tasks[1].status, 'done')
        self.assertEqual(tasks[2].status, 'in progress')

    def test_tags_parsed(self):
        tasks = _parse_tasks('- [ ] Task\n  #household #freetime\n')
        self.assertEqual(tasks[0].tags, ['household', 'freetime'])

    def test_no_tags_empty(self):
        self.assertEqual(_block('- [ ] Task').task.tags, [])


# ── Priority ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestPriority(unittest.TestCase):

    def test_high_priority_parsed(self):
        nodes = parse_str('- [ ] !!! Buy groceries\n')
        self.assertEqual(nodes[0].task.priority, '!!!')
        self.assertEqual(nodes[0].task.title, 'Buy groceries')

    def test_medium_priority_parsed(self):
        nodes = parse_str('- [ ] !! Task\n')
        self.assertEqual(nodes[0].task.priority, '!!')

    def test_low_priority_parsed(self):
        nodes = parse_str('- [ ] ! Task\n')
        self.assertEqual(nodes[0].task.priority, '!')

    def test_priority_with_time(self):
        nodes = parse_str('- [ ] 10:00 !! Pick up Mike\n')
        t = nodes[0].task
        self.assertEqual(t.priority, '!!')
        self.assertEqual(t.title, 'Pick up Mike')
        self.assertEqual(t.time.start, '10:00')

    def test_priority_with_time_range(self):
        nodes = parse_str('- [ ] 13:00-14:00 !!! Meeting\n')
        t = nodes[0].task
        self.assertEqual(t.priority, '!!!')
        self.assertEqual(t.title, 'Meeting')

    def test_no_priority_is_none(self):
        nodes = parse_str('- [ ] Buy milk\n')
        self.assertIsNone(nodes[0].task.priority)

    def test_priority_roundtrip(self):
        for line in [
            '- [ ] !!! Buy groceries\n',
            '- [ ] 10:00 !! Pick up Mike\n',
            '- [ ] 13:00-14:00 !!! Meeting\n',
            '- [ ] Buy milk\n',
        ]:
            self.assertEqual(roundtrip(line), line)

    def test_set_status_preserves_priority(self):
        nodes = parse_str('- [ ] !!! Buy groceries\n')
        nodes[0].set_status('done')
        self.assertEqual(nodes[0].header, '- [x] !!! Buy groceries\n')


# ── Tags ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTags(unittest.TestCase):

    def test_tag_line_populates_tags(self):
        nodes = parse_str('- [ ] Task\n  #household\n')
        self.assertEqual(nodes[0].task.tags, ['household'])

    def test_multiple_tags(self):
        nodes = parse_str('- [ ] Task\n  #Job-Search #freetime\n')
        self.assertEqual(nodes[0].task.tags, ['Job-Search', 'freetime'])

    def test_tag_node_reference_set(self):
        nodes = parse_str('- [ ] Task\n  #household\n')
        block = nodes[0]
        self.assertIsNotNone(block.tag_node)
        self.assertIs(block.tag_node, block.nodes[0])

    def test_no_tag_line_empty_tags(self):
        nodes = parse_str('- [ ] Task\n  Some notes\n')
        self.assertEqual(nodes[0].task.tags, [])
        self.assertIsNone(nodes[0].tag_node)

    def test_tag_line_roundtrip(self):
        c = '- [ ] Task\n  #household #freetime\n'
        self.assertEqual(roundtrip(c), c)

    def test_tag_line_with_body_notes_roundtrip(self):
        c = '- [ ] Task\n  Some notes\n  #household\n'
        self.assertEqual(roundtrip(c), c)

    def test_prose_with_hash_not_treated_as_tag_line(self):
        nodes = parse_str('- [ ] Task\n  blocked by #3\n')
        self.assertEqual(nodes[0].task.tags, [])

    def test_refresh_tags_updates_existing_tag_line(self):
        nodes = parse_str('- [ ] Task\n  #household\n')
        block = nodes[0]
        block.task.tags = ['household', 'freetime']
        block.refresh_tags()
        self.assertEqual(serialize(nodes), '- [ ] Task\n  #household #freetime\n')

    def test_refresh_tags_inserts_new_tag_line(self):
        nodes = parse_str('- [ ] Task\n  Some notes\n')
        block = nodes[0]
        block.task.tags = ['household']
        block.refresh_tags()
        self.assertEqual(serialize(nodes), '- [ ] Task\n  Some notes\n  #household\n')

    def test_refresh_tags_removes_tag_line_when_empty(self):
        nodes = parse_str('- [ ] Task\n  #household\n')
        block = nodes[0]
        block.task.tags = []
        block.refresh_tags()
        self.assertEqual(serialize(nodes), '- [ ] Task\n')

    def test_priority_and_tags_combined(self):
        c = '- [ ] !!! Buy groceries\n  #household\n'
        nodes = parse_str(c)
        t = nodes[0].task
        self.assertEqual(t.priority, '!!!')
        self.assertEqual(t.title, 'Buy groceries')
        self.assertEqual(t.tags, ['household'])
        self.assertEqual(roundtrip(c), c)

    def test_subtask_tags_independent(self):
        nodes = parse_str('- [ ] Parent\n  - [ ] Child\n    #household\n')
        parent = nodes[0]
        child = parent.nodes[0]
        self.assertEqual(parent.task.tags, [])
        self.assertEqual(child.task.tags, ['household'])


# ── FieldRange ────────────────────────────────────────────────────────────────

class TestFieldRanges(unittest.TestCase):

    def _sliced(self, block: TaskBlock, range_attr: str) -> str | None:
        r = getattr(block, range_attr)
        if r is None:
            return None
        return block.header.rstrip('\n')[r.start:r.end]

    def test_checkbox_range_todo(self):
        self.assertEqual(self._sliced(_block('- [ ] Buy milk'), 'checkbox_range'), ' ')

    def test_checkbox_range_done(self):
        self.assertEqual(self._sliced(_block('- [x] Buy milk'), 'checkbox_range'), 'x')

    def test_title_range_simple(self):
        self.assertEqual(self._sliced(_block('- [ ] Buy milk'), 'title_range'), 'Buy milk')

    def test_time_range_present(self):
        self.assertEqual(self._sliced(_block('- [ ] 09:00-10:00 Meeting'), 'time_range'), '09:00-10:00 ')

    def test_time_range_absent(self):
        self.assertIsNone(_block('- [ ] Buy milk').time_range)

    def test_title_range_after_time(self):
        self.assertEqual(self._sliced(_block('- [ ] 09:00-10:00 Meeting'), 'title_range'), 'Meeting')

    def test_priority_range_present(self):
        self.assertEqual(self._sliced(_block('- [ ] !!! Buy groceries'), 'priority_range'), '!!!')

    def test_priority_range_absent(self):
        self.assertIsNone(_block('- [ ] Buy milk').priority_range)

    def test_title_range_after_priority(self):
        self.assertEqual(self._sliced(_block('- [ ] !!! Buy groceries'), 'title_range'), 'Buy groceries')

    def test_time_and_priority(self):
        b = _block('- [ ] 10:00 !! Pick up Mike')
        self.assertEqual(self._sliced(b, 'time_range'), '10:00 ')
        self.assertEqual(self._sliced(b, 'priority_range'), '!!')
        self.assertEqual(self._sliced(b, 'title_range'), 'Pick up Mike')

    def test_indented_task_ranges(self):
        b = _block('  - [x] !!! Buy groceries')
        self.assertEqual(self._sliced(b, 'checkbox_range'), 'x')
        self.assertEqual(self._sliced(b, 'priority_range'), '!!!')
        self.assertEqual(self._sliced(b, 'title_range'), 'Buy groceries')

    def test_colon_separator_included_in_time_range(self):
        b = _block('- [ ] 9:00: Meeting')
        self.assertEqual(self._sliced(b, 'time_range'), '9:00: ')
        self.assertEqual(self._sliced(b, 'title_range'), 'Meeting')

    def test_ranges_cover_full_header(self):
        line = '- [ ] 09:00-10:00 !!! Meeting'
        b = _block(line)
        for attr in ('checkbox_range', 'time_range', 'priority_range', 'title_range'):
            r = getattr(b, attr)
            if r is not None:
                self.assertGreaterEqual(r.start, 0)
                self.assertLessEqual(r.end, len(line))
                self.assertLessEqual(r.start, r.end)


# ── set_status ────────────────────────────────────────────────────────────────

class TestSetStatus(unittest.TestCase):

    def test_marks_done(self):
        b = _block('- [ ] Buy milk')
        b.set_status('done')
        self.assertEqual(b.header, '- [x] Buy milk\n')

    def test_marks_todo(self):
        b = _block('- [x] Buy milk')
        b.set_status('todo')
        self.assertEqual(b.header, '- [ ] Buy milk\n')

    def test_updates_task_status(self):
        b = _block('- [ ] Buy milk')
        b.set_status('done')
        self.assertEqual(b.task.status, 'done')

    def test_preserves_time_and_title(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        b.set_status('done')
        self.assertEqual(b.header, '- [x] 09:00-10:00 Meeting\n')

    def test_preserves_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        b.set_status('done')
        self.assertEqual(b.header, '- [x] !!! Buy groceries\n')

    def test_checkbox_range_updated(self):
        b = _block('- [ ] Buy milk')
        b.set_status('done')
        self.assertEqual(b.header[b.checkbox_range.start:b.checkbox_range.end], 'x')


# ── set_time ──────────────────────────────────────────────────────────────────

class TestSetTime(unittest.TestCase):

    def test_replaces_existing_time(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        b.set_time(TaskTime(start='11:00', end='12:00'))
        self.assertEqual(b.header, '- [ ] 11:00-12:00 Meeting\n')

    def test_removes_time(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        b.set_time(None)
        self.assertEqual(b.header, '- [ ] Meeting\n')

    def test_inserts_time_where_none_existed(self):
        b = _block('- [ ] Meeting')
        b.set_time(TaskTime(start='09:00', end='10:00'))
        self.assertEqual(b.header, '- [ ] 09:00-10:00 Meeting\n')

    def test_inserts_time_before_priority(self):
        b = _block('- [ ] !!! Meeting')
        b.set_time(TaskTime(start='09:00'))
        self.assertEqual(b.header, '- [ ] 09:00 !!! Meeting\n')

    def test_updates_task_time(self):
        b = _block('- [ ] 09:00 Meeting')
        new_time = TaskTime(start='11:00')
        b.set_time(new_time)
        self.assertEqual(b.task.time, new_time)

    def test_clears_task_time(self):
        b = _block('- [ ] 09:00 Meeting')
        b.set_time(None)
        self.assertIsNone(b.task.time)

    def test_time_range_updated(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        b.set_time(TaskTime(start='11:00', end='12:00'))
        sliced = b.header.rstrip('\n')[b.time_range.start:b.time_range.end]
        self.assertEqual(sliced, '11:00-12:00 ')

    def test_time_range_none_after_removal(self):
        b = _block('- [ ] 09:00 Meeting')
        b.set_time(None)
        self.assertIsNone(b.time_range)

    def test_no_op_when_both_none(self):
        b = _block('- [ ] Meeting')
        original = b.header
        b.set_time(None)
        self.assertEqual(b.header, original)


# ── set_title ─────────────────────────────────────────────────────────────────

class TestSetTitle(unittest.TestCase):

    def test_replaces_title(self):
        b = _block('- [ ] Buy milk')
        b.set_title('Buy oat milk')
        self.assertEqual(b.header, '- [ ] Buy oat milk\n')

    def test_updates_task_title(self):
        b = _block('- [ ] Buy milk')
        b.set_title('Buy oat milk')
        self.assertEqual(b.task.title, 'Buy oat milk')

    def test_preserves_time(self):
        b = _block('- [ ] 09:00 Meeting')
        b.set_title('Standup')
        self.assertEqual(b.header, '- [ ] 09:00 Standup\n')

    def test_preserves_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        b.set_title('Buy milk')
        self.assertEqual(b.header, '- [ ] !!! Buy milk\n')

    def test_title_range_updated(self):
        b = _block('- [ ] Buy milk')
        b.set_title('Buy oat milk')
        sliced = b.header.rstrip('\n')[b.title_range.start:b.title_range.end]
        self.assertEqual(sliced, 'Buy oat milk')


# ── set_priority ──────────────────────────────────────────────────────────────

class TestSetPriority(unittest.TestCase):

    def test_replaces_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        b.set_priority('!!')
        self.assertEqual(b.header, '- [ ] !! Buy groceries\n')

    def test_removes_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        b.set_priority(None)
        self.assertEqual(b.header, '- [ ] Buy groceries\n')

    def test_inserts_priority(self):
        b = _block('- [ ] Buy groceries')
        b.set_priority('!!!')
        self.assertEqual(b.header, '- [ ] !!! Buy groceries\n')

    def test_updates_task_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        b.set_priority('!!')
        self.assertEqual(b.task.priority, '!!')

    def test_clears_task_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        b.set_priority(None)
        self.assertIsNone(b.task.priority)

    def test_preserves_time(self):
        b = _block('- [ ] 10:00 !!! Meeting')
        b.set_priority('!!')
        self.assertEqual(b.header, '- [ ] 10:00 !! Meeting\n')

    def test_removes_priority_with_time(self):
        b = _block('- [ ] 10:00 !!! Meeting')
        b.set_priority(None)
        self.assertEqual(b.header, '- [ ] 10:00 Meeting\n')

    def test_no_op_when_both_none(self):
        b = _block('- [ ] Buy groceries')
        original = b.header
        b.set_priority(None)
        self.assertEqual(b.header, original)

    def test_priority_range_updated(self):
        b = _block('- [ ] !!! Buy groceries')
        b.set_priority('!!')
        sliced = b.header.rstrip('\n')[b.priority_range.start:b.priority_range.end]
        self.assertEqual(sliced, '!!')

    def test_priority_range_none_after_removal(self):
        b = _block('- [ ] !!! Buy groceries')
        b.set_priority(None)
        self.assertIsNone(b.priority_range)


# ── insert_task ───────────────────────────────────────────────────────────────

class TestInsertTask(unittest.TestCase):

    def _task(self, title='New task', status='todo', time=None, indent=''):
        return Task(title=title, status=status, time=time, line_number=-1, indent=indent)

    def test_top_level_appended_without_preceding_blank(self):
        nodes = [_block('- [ ] Existing')]
        insert_task(nodes, self._task('New'))
        self.assertEqual(serialize(nodes), '- [ ] Existing\n- [ ] New\n\n')

    def test_top_level_appended_with_preceding_blank(self):
        b = _block('- [ ] Existing')
        b.nodes.append(RawLine('\n'))
        nodes = [b]
        insert_task(nodes, self._task('New'))
        self.assertEqual(serialize(nodes), '- [ ] Existing\n\n- [ ] New\n\n')

    def test_top_level_trailing_blank(self):
        nodes = []
        insert_task(nodes, self._task())
        self.assertEqual(serialize(nodes), '- [ ] New task\n\n')

    def test_subtask_no_blank_lines(self):
        nodes = []
        insert_task(nodes, self._task('Child', indent='  '))
        self.assertEqual(serialize(nodes), '  - [ ] Child\n')

    def test_subtask_no_blank_after_preceding_content(self):
        nodes = [_block('- [ ] Parent')]
        insert_task(nodes, self._task('Child', indent='  '))
        self.assertEqual(serialize(nodes), '- [ ] Parent\n  - [ ] Child\n')

    def test_returns_taskblock(self):
        self.assertIsInstance(insert_task([], self._task()), TaskBlock)

    def test_returned_block_has_correct_header(self):
        block = insert_task([], self._task('Buy milk'))
        self.assertEqual(block.header, '- [ ] Buy milk\n')

    def test_field_ranges_populated(self):
        block = insert_task([], self._task('Buy milk'))
        self.assertIsNotNone(block.checkbox_range)
        self.assertIsNotNone(block.title_range)
        self.assertEqual(block.header[block.title_range.start:block.title_range.end], 'Buy milk')

    def test_insert_task_with_time(self):
        task = self._task('Meeting', time=TaskTime(start='09:00', end='10:00'))
        block = insert_task([], task)
        self.assertEqual(block.header, '- [ ] 09:00-10:00 Meeting\n')
        self.assertIsNotNone(block.time_range)


# ── Helpers for hierarchy / reorder tests ────────────────────────────────────

def _make_task(title: str, indent: str = '', timed: bool = False) -> Task:
    time = TaskTime(start='9:00') if timed else None
    return Task(title=title, status='todo', time=time, line_number=-1, indent=indent)


def _make_block(task: Task, children: list | None = None) -> TaskBlock:
    return TaskBlock(task=task, header=task.to_line() + '\n', nodes=list(children or []))


# ── tab_task ──────────────────────────────────────────────────────────────────

class TestTabTask(unittest.TestCase):

    def test_no_preceding_sibling_returns_false(self):
        t = _make_task('A')
        nodes = [_make_block(t)]
        self.assertFalse(tab_task(nodes, t))

    def test_preceding_rawline_only_returns_false(self):
        t = _make_task('A')
        nodes = [RawLine('\n'), _make_block(t)]
        self.assertFalse(tab_task(nodes, t))

    def test_task_not_found_returns_false(self):
        nodes = [_make_block(_make_task('X'))]
        self.assertFalse(tab_task(nodes, _make_task('Missing')))

    def test_moves_block_into_preceding_sibling(self):
        a, b = _make_task('A'), _make_task('B')
        a_block, b_block = _make_block(a), _make_block(b)
        nodes = [a_block, b_block]
        self.assertTrue(tab_task(nodes, b))
        self.assertEqual(nodes, [a_block])
        self.assertIn(b_block, a_block.nodes)

    def test_updates_task_indent(self):
        a, b = _make_task('A'), _make_task('B')
        nodes = [_make_block(a), _make_block(b)]
        tab_task(nodes, b)
        self.assertEqual(b.indent, a.indent + STEP)

    def test_updates_header_after_tab(self):
        a, b = _make_task('A'), _make_task('B')
        a_block = _make_block(a)
        b_block = _make_block(b)
        nodes = [a_block, b_block]
        tab_task(nodes, b)
        self.assertIn(STEP, b_block.header)

    def test_recursively_updates_child_indent(self):
        a = _make_task('A')
        b = _make_task('B')
        c = _make_task('C', indent=STEP)
        b_block = _make_block(b, children=[_make_block(c)])
        nodes = [_make_block(a), b_block]
        tab_task(nodes, b)
        self.assertEqual(b.indent, STEP)
        self.assertEqual(c.indent, STEP * 2)

    def test_updates_body_rawline_indent(self):
        a, b = _make_task('A'), _make_task('B')
        b_block = _make_block(b)
        b_block.nodes.append(RawLine(STEP + 'Body line\n'))
        nodes = [_make_block(a), b_block]
        tab_task(nodes, b)
        raw = b_block.nodes[0].raw
        self.assertTrue(raw.startswith(STEP * 2), repr(raw))
        self.assertIn('Body line', raw)

    def test_preceding_sibling_with_rawline_separator(self):
        a, b = _make_task('A'), _make_task('B')
        a_block, b_block = _make_block(a), _make_block(b)
        nodes = [a_block, RawLine('\n'), b_block]
        self.assertTrue(tab_task(nodes, b))
        self.assertIn(b_block, a_block.nodes)

    def test_tab_twice_gives_nested_children(self):
        a, b, c = _make_task('A'), _make_task('B'), _make_task('C')
        a_block, b_block, c_block = _make_block(a), _make_block(b), _make_block(c)
        nodes = [a_block, b_block, c_block]
        tab_task(nodes, b)   # nodes=[a_block, c_block]; a_block.nodes=[b_block]
        tab_task(nodes, c)   # nodes=[a_block];          a_block.nodes=[b_block, c_block]
        self.assertEqual(nodes, [a_block])
        child_blocks = [n for n in a_block.nodes if isinstance(n, TaskBlock)]
        self.assertIn(b_block, child_blocks)
        self.assertIn(c_block, child_blocks)


# ── shift_tab_task ────────────────────────────────────────────────────────────

class TestShiftTabTask(unittest.TestCase):

    def test_top_level_task_returns_false(self):
        t = _make_task('A')
        nodes = [_make_block(t)]
        self.assertFalse(shift_tab_task(nodes, t))

    def test_task_not_found_returns_false(self):
        nodes = [_make_block(_make_task('A'))]
        self.assertFalse(shift_tab_task(nodes, _make_task('Missing')))

    def test_promotes_subtask_after_parent(self):
        parent = _make_task('Parent')
        child = _make_task('Child', indent=STEP)
        child_block = _make_block(child)
        parent_block = _make_block(parent, children=[child_block])
        nodes = [parent_block]
        self.assertTrue(shift_tab_task(nodes, child))
        self.assertEqual(nodes, [parent_block, child_block])
        self.assertNotIn(child_block, parent_block.nodes)

    def test_updates_indent_to_match_parent_level(self):
        parent = _make_task('Parent')
        child = _make_task('Child', indent=STEP)
        parent_block = _make_block(parent, children=[_make_block(child)])
        nodes = [parent_block]
        shift_tab_task(nodes, child)
        self.assertEqual(child.indent, parent.indent)

    def test_recursively_updates_grandchild_indent(self):
        parent = _make_task('Parent')
        child = _make_task('Child', indent=STEP)
        grandchild = _make_task('GC', indent=STEP * 2)
        child_block = _make_block(child, children=[_make_block(grandchild)])
        parent_block = _make_block(parent, children=[child_block])
        nodes = [parent_block]
        shift_tab_task(nodes, child)
        self.assertEqual(child.indent, '')
        self.assertEqual(grandchild.indent, STEP)

    def test_later_siblings_stay_in_parent(self):
        parent = _make_task('Parent')
        c1, c2 = _make_task('C1', indent=STEP), _make_task('C2', indent=STEP)
        c1_block, c2_block = _make_block(c1), _make_block(c2)
        parent_block = _make_block(parent, children=[c1_block, c2_block])
        nodes = [parent_block]
        shift_tab_task(nodes, c1)
        self.assertIn(c2_block, parent_block.nodes)
        self.assertEqual(nodes, [parent_block, c1_block])

    def test_tab_then_shift_tab_round_trips_position(self):
        a, b = _make_task('A'), _make_task('B')
        a_block, b_block = _make_block(a), _make_block(b)
        nodes = [a_block, b_block]
        tab_task(nodes, b)
        shift_tab_task(nodes, b)
        self.assertEqual(nodes, [a_block, b_block])
        self.assertEqual(b.indent, '')

    def test_tab_then_shift_tab_round_trips_body(self):
        a, b = _make_task('A'), _make_task('B')
        b_block = _make_block(b)
        b_block.nodes.append(RawLine(STEP + 'Note\n'))
        nodes = [_make_block(a), b_block]
        tab_task(nodes, b)
        shift_tab_task(nodes, b)
        raw = b_block.nodes[0].raw
        self.assertTrue(raw.startswith(STEP + 'Note'), repr(raw))


# ── move_block_in_nodes ───────────────────────────────────────────────────────

class TestMoveBlockInNodes(unittest.TestCase):

    def test_timed_task_not_moved(self):
        t = _make_task('A', timed=True)
        nodes = [_make_block(t), _make_block(_make_task('B'))]
        self.assertFalse(move_block_in_nodes(nodes, t, 1))

    def test_task_not_found_returns_false(self):
        nodes = [_make_block(_make_task('A'))]
        self.assertFalse(move_block_in_nodes(nodes, _make_task('X'), 1))

    def test_move_down(self):
        a, b = _make_task('A'), _make_task('B')
        a_block, b_block = _make_block(a), _make_block(b)
        nodes = [a_block, b_block]
        self.assertTrue(move_block_in_nodes(nodes, a, 1))
        self.assertEqual(nodes, [b_block, a_block])

    def test_move_up(self):
        a, b = _make_task('A'), _make_task('B')
        a_block, b_block = _make_block(a), _make_block(b)
        nodes = [a_block, b_block]
        self.assertTrue(move_block_in_nodes(nodes, b, -1))
        self.assertEqual(nodes, [b_block, a_block])

    def test_move_down_at_last_returns_false(self):
        a, b = _make_task('A'), _make_task('B')
        nodes = [_make_block(a), _make_block(b)]
        self.assertFalse(move_block_in_nodes(nodes, b, 1))

    def test_move_up_at_first_returns_false(self):
        a, b = _make_task('A'), _make_task('B')
        nodes = [_make_block(a), _make_block(b)]
        self.assertFalse(move_block_in_nodes(nodes, a, -1))

    def test_move_down_skips_timed_sibling(self):
        a = _make_task('A')
        t = _make_task('T', timed=True)
        b = _make_task('B')
        a_block, t_block, b_block = _make_block(a), _make_block(t), _make_block(b)
        nodes = [a_block, t_block, b_block]
        self.assertTrue(move_block_in_nodes(nodes, a, 1))
        self.assertEqual(nodes, [b_block, t_block, a_block])

    def test_move_preserves_rawline_separators(self):
        a, b = _make_task('A'), _make_task('B')
        a_block, b_block = _make_block(a), _make_block(b)
        sep = RawLine('\n')
        nodes = [a_block, sep, b_block]
        move_block_in_nodes(nodes, a, 1)
        self.assertEqual(nodes[1], sep)

    def test_works_on_subtask_within_parent(self):
        parent = _make_task('Parent')
        c1, c2 = _make_task('C1', indent=STEP), _make_task('C2', indent=STEP)
        c1_block, c2_block = _make_block(c1), _make_block(c2)
        parent_block = _make_block(parent, children=[c1_block, c2_block])
        nodes = [parent_block]
        self.assertTrue(move_block_in_nodes(nodes, c1, 1))
        self.assertEqual(parent_block.nodes, [c2_block, c1_block])

    def test_only_untimed_counted_as_swap_target(self):
        t1 = _make_task('T1', timed=True)
        t2 = _make_task('T2', timed=True)
        u = _make_task('U')
        nodes = [_make_block(t1), _make_block(u), _make_block(t2)]
        self.assertFalse(move_block_in_nodes(nodes, u, 1))
        self.assertFalse(move_block_in_nodes(nodes, u, -1))


if __name__ == '__main__':
    unittest.main()
