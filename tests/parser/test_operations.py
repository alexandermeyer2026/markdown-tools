from __future__ import annotations

import os
import tempfile
import unittest

from models.task import Task, TaskTime
from parser.file_model import RawLine, TaskBlock, parse, serialize
from parser.operations import insert_task, set_priority, set_status, set_time, set_title


def _block(line: str):
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    f.write(line if line.endswith('\n') else line + '\n')
    f.close()
    try:
        return parse(f.name)[0]
    finally:
        os.unlink(f.name)


# ── set_status ────────────────────────────────────────────────────────────────

class TestSetStatus(unittest.TestCase):

    def test_marks_done(self):
        b = _block('- [ ] Buy milk')
        set_status(b, 'done')
        self.assertEqual(b.header, '- [x] Buy milk\n')

    def test_marks_todo(self):
        b = _block('- [x] Buy milk')
        set_status(b, 'todo')
        self.assertEqual(b.header, '- [ ] Buy milk\n')

    def test_updates_task_status(self):
        b = _block('- [ ] Buy milk')
        set_status(b, 'done')
        self.assertEqual(b.task.status, 'done')

    def test_preserves_time_and_title(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        set_status(b, 'done')
        self.assertEqual(b.header, '- [x] 09:00-10:00 Meeting\n')

    def test_preserves_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        set_status(b, 'done')
        self.assertEqual(b.header, '- [x] !!! Buy groceries\n')

    def test_checkbox_range_updated(self):
        b = _block('- [ ] Buy milk')
        set_status(b, 'done')
        self.assertEqual(b.header[b.checkbox_range.start:b.checkbox_range.end], 'x')

    def test_roundtrip_after_status_change(self):
        b = _block('- [ ] Buy milk')
        set_status(b, 'done')
        self.assertEqual(serialize([b]), '- [x] Buy milk\n')


# ── set_time ──────────────────────────────────────────────────────────────────

class TestSetTime(unittest.TestCase):

    def test_replaces_existing_time(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        set_time(b, TaskTime(start='11:00', end='12:00'))
        self.assertEqual(b.header, '- [ ] 11:00-12:00 Meeting\n')

    def test_removes_time(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        set_time(b, None)
        self.assertEqual(b.header, '- [ ] Meeting\n')

    def test_inserts_time_where_none_existed(self):
        b = _block('- [ ] Meeting')
        set_time(b, TaskTime(start='09:00', end='10:00'))
        self.assertEqual(b.header, '- [ ] 09:00-10:00 Meeting\n')

    def test_inserts_time_before_priority(self):
        b = _block('- [ ] !!! Meeting')
        set_time(b, TaskTime(start='09:00'))
        self.assertEqual(b.header, '- [ ] 09:00 !!! Meeting\n')

    def test_updates_task_time(self):
        b = _block('- [ ] 09:00 Meeting')
        new_time = TaskTime(start='11:00')
        set_time(b, new_time)
        self.assertEqual(b.task.time, new_time)

    def test_clears_task_time(self):
        b = _block('- [ ] 09:00 Meeting')
        set_time(b, None)
        self.assertIsNone(b.task.time)

    def test_time_range_updated(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        set_time(b, TaskTime(start='11:00', end='12:00'))
        sliced = b.header.rstrip('\n')[b.time_range.start:b.time_range.end]
        self.assertEqual(sliced, '11:00-12:00 ')

    def test_time_range_none_after_removal(self):
        b = _block('- [ ] 09:00 Meeting')
        set_time(b, None)
        self.assertIsNone(b.time_range)

    def test_no_op_when_both_none(self):
        b = _block('- [ ] Meeting')
        original = b.header
        set_time(b, None)
        self.assertEqual(b.header, original)

    def test_roundtrip_after_time_change(self):
        b = _block('- [ ] 09:00-10:00 Meeting')
        set_time(b, TaskTime(start='11:00', end='12:00'))
        self.assertEqual(serialize([b]), '- [ ] 11:00-12:00 Meeting\n')


# ── set_title ─────────────────────────────────────────────────────────────────

class TestSetTitle(unittest.TestCase):

    def test_replaces_title(self):
        b = _block('- [ ] Buy milk')
        set_title(b, 'Buy oat milk')
        self.assertEqual(b.header, '- [ ] Buy oat milk\n')

    def test_updates_task_title(self):
        b = _block('- [ ] Buy milk')
        set_title(b, 'Buy oat milk')
        self.assertEqual(b.task.title, 'Buy oat milk')

    def test_preserves_time(self):
        b = _block('- [ ] 09:00 Meeting')
        set_title(b, 'Standup')
        self.assertEqual(b.header, '- [ ] 09:00 Standup\n')

    def test_preserves_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        set_title(b, 'Buy milk')
        self.assertEqual(b.header, '- [ ] !!! Buy milk\n')

    def test_title_range_updated(self):
        b = _block('- [ ] Buy milk')
        set_title(b, 'Buy oat milk')
        sliced = b.header.rstrip('\n')[b.title_range.start:b.title_range.end]
        self.assertEqual(sliced, 'Buy oat milk')

    def test_roundtrip_after_title_change(self):
        b = _block('- [ ] Buy milk')
        set_title(b, 'Buy oat milk')
        self.assertEqual(serialize([b]), '- [ ] Buy oat milk\n')


# ── set_priority ──────────────────────────────────────────────────────────────

class TestSetPriority(unittest.TestCase):

    def test_replaces_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        set_priority(b, '!!')
        self.assertEqual(b.header, '- [ ] !! Buy groceries\n')

    def test_removes_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        set_priority(b, None)
        self.assertEqual(b.header, '- [ ] Buy groceries\n')

    def test_inserts_priority(self):
        b = _block('- [ ] Buy groceries')
        set_priority(b, '!!!')
        self.assertEqual(b.header, '- [ ] !!! Buy groceries\n')

    def test_updates_task_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        set_priority(b, '!!')
        self.assertEqual(b.task.priority, '!!')

    def test_clears_task_priority(self):
        b = _block('- [ ] !!! Buy groceries')
        set_priority(b, None)
        self.assertIsNone(b.task.priority)

    def test_preserves_time(self):
        b = _block('- [ ] 10:00 !!! Meeting')
        set_priority(b, '!!')
        self.assertEqual(b.header, '- [ ] 10:00 !! Meeting\n')

    def test_removes_priority_with_time(self):
        b = _block('- [ ] 10:00 !!! Meeting')
        set_priority(b, None)
        self.assertEqual(b.header, '- [ ] 10:00 Meeting\n')

    def test_no_op_when_both_none(self):
        b = _block('- [ ] Buy groceries')
        original = b.header
        set_priority(b, None)
        self.assertEqual(b.header, original)

    def test_priority_range_updated(self):
        b = _block('- [ ] !!! Buy groceries')
        set_priority(b, '!!')
        sliced = b.header.rstrip('\n')[b.priority_range.start:b.priority_range.end]
        self.assertEqual(sliced, '!!')

    def test_priority_range_none_after_removal(self):
        b = _block('- [ ] !!! Buy groceries')
        set_priority(b, None)
        self.assertIsNone(b.priority_range)

    def test_roundtrip_after_priority_change(self):
        b = _block('- [ ] !!! Buy groceries')
        set_priority(b, None)
        self.assertEqual(serialize([b]), '- [ ] Buy groceries\n')


# ── insert_task ───────────────────────────────────────────────────────────────

class TestInsertTask(unittest.TestCase):

    def _task(self, title='New task', status='todo', time=None, indent=''):
        return Task(title=title, status=status, time=time, line_number=-1, indent=indent)

    def test_appends_to_empty_list(self):
        nodes = []
        insert_task(nodes, self._task())
        self.assertEqual(len(nodes), 1)
        self.assertIsInstance(nodes[0], TaskBlock)

    def test_no_blank_line_when_empty(self):
        nodes = []
        insert_task(nodes, self._task())
        self.assertEqual(serialize(nodes), '- [ ] New task\n')

    def test_blank_line_after_taskblock(self):
        b = _block('- [ ] Existing task')
        nodes = [b]
        insert_task(nodes, self._task('Second task'))
        self.assertEqual(serialize(nodes), '- [ ] Existing task\n\n- [ ] Second task\n')

    def test_blank_goes_into_preceding_taskblock_nodes(self):
        b = _block('- [ ] Existing task')
        nodes = [b]
        insert_task(nodes, self._task('Second task'))
        # blank line belongs to the preceding TaskBlock, not top-level
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[1], TaskBlock)
        self.assertIsInstance(b.nodes[-1], RawLine)
        self.assertEqual(b.nodes[-1].raw, '\n')

    def test_blank_line_after_rawline(self):
        nodes = [RawLine('# Heading\n')]
        insert_task(nodes, self._task())
        self.assertEqual(serialize(nodes), '# Heading\n\n- [ ] New task\n')

    def test_blank_appended_to_toplevel_after_rawline(self):
        raw = RawLine('# Heading\n')
        nodes = [raw]
        insert_task(nodes, self._task())
        self.assertEqual(len(nodes), 3)  # raw, blank, task

    def test_returns_taskblock(self):
        nodes = []
        result = insert_task(nodes, self._task())
        self.assertIsInstance(result, TaskBlock)

    def test_returned_block_has_correct_header(self):
        nodes = []
        block = insert_task(nodes, self._task('Buy milk'))
        self.assertEqual(block.header, '- [ ] Buy milk\n')

    def test_field_ranges_populated(self):
        nodes = []
        block = insert_task(nodes, self._task('Buy milk'))
        self.assertIsNotNone(block.checkbox_range)
        self.assertIsNotNone(block.title_range)
        self.assertEqual(block.header[block.title_range.start:block.title_range.end], 'Buy milk')

    def test_insert_task_with_time(self):
        nodes = []
        task = self._task('Meeting', time=TaskTime(start='09:00', end='10:00'))
        block = insert_task(nodes, task)
        self.assertEqual(block.header, '- [ ] 09:00-10:00 Meeting\n')
        self.assertIsNotNone(block.time_range)

    def test_roundtrip_two_inserts(self):
        nodes = []
        insert_task(nodes, self._task('First'))
        insert_task(nodes, self._task('Second'))
        self.assertEqual(serialize(nodes), '- [ ] First\n\n- [ ] Second\n')


if __name__ == '__main__':
    unittest.main()
