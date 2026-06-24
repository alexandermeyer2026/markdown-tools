import unittest

from models import Task, TaskTime
from models.file import RawLine, TaskBlock
from tools.journal_tools.rendering import (
    GRAY, RESET, STATUS_COLORS, STATUS_ICONS,
    ansi_truncate_pad, body_rows, get_time_slot, scale_lines, subtask_rows,
)


class TestGetTimeSlot(unittest.TestCase):
    def test_zero_minutes(self):
        self.assertEqual(get_time_slot(0, 0.25), 0)

    def test_exact_slot_boundary(self):
        # 60 min / 0.25 hr step = slot 4
        self.assertEqual(get_time_slot(60, 0.25), 4)

    def test_just_before_boundary(self):
        # 74 min → floor(74/60/0.25) = floor(4.93) = 4
        self.assertEqual(get_time_slot(74, 0.25), 4)

    def test_on_next_boundary(self):
        # 75 min → floor(75/60/0.25) = floor(5.0) = 5
        self.assertEqual(get_time_slot(75, 0.25), 5)

    def test_nine_am(self):
        self.assertEqual(get_time_slot(540, 0.25), 36)

    def test_hourly_step(self):
        self.assertEqual(get_time_slot(60, 1.0), 1)
        self.assertEqual(get_time_slot(0, 1.0), 0)


class TestAnsiTruncatePad(unittest.TestCase):
    def test_short_text_is_padded(self):
        self.assertEqual(ansi_truncate_pad('hi', 5), 'hi' + RESET + '   ')

    def test_exact_width_no_padding(self):
        self.assertEqual(ansi_truncate_pad('hello', 5), 'hello' + RESET)

    def test_long_text_is_truncated(self):
        self.assertEqual(ansi_truncate_pad('hello world', 5), 'hello' + RESET)

    def test_ansi_codes_pass_through_and_dont_count(self):
        # ANSI bold prefix doesn't count toward visible width
        self.assertEqual(ansi_truncate_pad('\x1b[1mhi', 5), '\x1b[1mhi' + RESET + '   ')

    def test_ansi_truncates_at_visible_width(self):
        self.assertEqual(ansi_truncate_pad('\x1b[1mhello world', 5), '\x1b[1mhello' + RESET)

    def test_empty_string(self):
        self.assertEqual(ansi_truncate_pad('', 3), RESET + '   ')


class TestScaleLines(unittest.TestCase):
    def test_returns_tuple_of_two_strings(self):
        result = scale_lines(1.0, 0, None)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        hours, scale = result
        self.assertIsInstance(hours, str)
        self.assertIsInstance(scale, str)

    def test_scale_starts_and_ends_with_box_chars(self):
        _, scale = scale_lines(1.0, 0, None)
        self.assertEqual(scale[0], '├')
        self.assertEqual(scale[-1], '┤')

    def test_hours_contains_expected_markers(self):
        hours, _ = scale_lines(1.0, 0, None)
        self.assertIn('0', hours)
        self.assertIn('6', hours)
        self.assertIn('12', hours)
        self.assertIn('18', hours)
        self.assertIn('24', hours)

    def test_now_slot_inserts_marker(self):
        _, scale = scale_lines(1.0, 0, 4)
        self.assertEqual(scale[4], '▼')

    def test_no_now_slot_has_no_marker(self):
        _, scale = scale_lines(1.0, 0, None)
        self.assertNotIn('▼', scale)

    def test_first_slot_trims_both_strings(self):
        hours_full, scale_full = scale_lines(1.0, 0, None)
        hours_trim, scale_trim = scale_lines(1.0, 4, None)
        self.assertEqual(len(hours_trim), len(hours_full) - 4)
        self.assertEqual(len(scale_trim), len(scale_full) - 4)


def _make_block(task: Task, children: list | None = None) -> TaskBlock:
    nodes = [n for n in (children or [])]
    return TaskBlock(task=task, header=task.to_line() + '\n', nodes=nodes)


class TestBodyRows(unittest.TestCase):
    def _task(self) -> Task:
        return Task(title='Task', status='todo', time=None, line_number=1, indent='')

    def test_no_body_returns_empty(self):
        block = _make_block(self._task())
        self.assertEqual(body_rows(block), [])

    def test_body_text_rendered(self):
        note = RawLine('  Some note\n')
        block = TaskBlock(task=self._task(), header='- [ ] Task\n', nodes=[note])
        rows = body_rows(block)
        self.assertEqual(len(rows), 1)
        self.assertIn('Some note', rows[0])

    def test_tag_line_excluded_from_body(self):
        note = RawLine('  Some note\n')
        tag = RawLine('  #household\n')
        task = self._task()
        task.tags = ['household']
        block = TaskBlock(task=task, header='- [ ] Task\n', nodes=[note, tag], tag_node=tag)
        rows = body_rows(block)
        self.assertEqual(len(rows), 1)
        self.assertIn('Some note', rows[0])
        self.assertNotIn('#household', rows[0])

    def test_only_tag_line_returns_empty(self):
        tag = RawLine('  #household\n')
        task = self._task()
        task.tags = ['household']
        block = TaskBlock(task=task, header='- [ ] Task\n', nodes=[tag], tag_node=tag)
        self.assertEqual(body_rows(block), [])

    def test_blank_only_body_returns_empty(self):
        block = TaskBlock(task=self._task(), header='- [ ] Task\n', nodes=[RawLine('\n')])
        self.assertEqual(body_rows(block), [])


class TestSubtaskRows(unittest.TestCase):
    def _child_task(self, title='Sub', status='todo', indent='  ') -> Task:
        return Task(title=title, status=status, time=None, line_number=2, indent=indent)

    def _parent_task(self) -> Task:
        return Task(title='Parent', status='todo', time=None, line_number=1, indent='')

    def test_no_children_returns_empty(self):
        parent_block = _make_block(self._parent_task())
        self.assertEqual(subtask_rows(parent_block), [])

    def test_single_child_produces_one_row(self):
        child = self._child_task(status='done')
        child_block = _make_block(child)
        parent_block = _make_block(self._parent_task(), children=[child_block])
        rows = subtask_rows(parent_block)
        self.assertEqual(len(rows), 1)

    def test_unselected_child_contains_icon_and_title(self):
        child = self._child_task(title='Buy milk', status='done')
        child_block = _make_block(child)
        parent_block = _make_block(self._parent_task(), children=[child_block])
        row = subtask_rows(parent_block)[0]
        self.assertIn(STATUS_ICONS['done'], row)
        self.assertIn('Buy milk', row)
        self.assertIn(STATUS_COLORS['done'], row)
        self.assertNotIn('\x1b[7m', row)

    def test_selected_child_has_reverse_highlight(self):
        child = self._child_task(title='Buy milk', status='todo')
        child_block = _make_block(child)
        parent_block = _make_block(self._parent_task(), children=[child_block])
        row = subtask_rows(parent_block, selected_task=child)[0]
        self.assertIn('\x1b[7m', row)
        self.assertIn('> ', row)
        self.assertIn('Buy milk', row)

    def test_nested_children_all_returned(self):
        grandchild = Task(title='Leaf', status='todo', time=None, line_number=3, indent='    ')
        grandchild_block = _make_block(grandchild)
        child = self._child_task(title='Mid')
        child_block = _make_block(child, children=[grandchild_block])
        parent_block = _make_block(self._parent_task(), children=[child_block])
        rows = subtask_rows(parent_block)
        self.assertEqual(len(rows), 2)
        self.assertIn('Mid', rows[0])
        self.assertIn('Leaf', rows[1])
