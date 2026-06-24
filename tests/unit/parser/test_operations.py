from __future__ import annotations

import os
import tempfile
import unittest

from models.task import Task, TaskTime
from models.file import RawLine, TaskBlock, parse, serialize, insert_task


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

    # ── scenario 1: top-level task appended to previous content ───────────────

    def test_top_level_appended_without_preceding_blank(self):
        # preceding block has no trailing blank → new task appended directly after
        b = _block('- [ ] Existing')
        nodes = [b]
        insert_task(nodes, self._task('New'))
        self.assertEqual(serialize(nodes), '- [ ] Existing\n- [ ] New\n\n')

    def test_top_level_appended_with_preceding_blank(self):
        # preceding block already ends with a blank → separator is preserved as-is
        b = _block('- [ ] Existing')
        b.nodes.append(RawLine('\n'))
        nodes = [b]
        insert_task(nodes, self._task('New'))
        self.assertEqual(serialize(nodes), '- [ ] Existing\n\n- [ ] New\n\n')

    # ── scenario 2: top-level task has trailing blank line ────────────────────

    def test_top_level_trailing_blank(self):
        nodes = []
        insert_task(nodes, self._task())
        self.assertEqual(serialize(nodes), '- [ ] New task\n\n')

    # ── scenario 3: subtask gets no leading or trailing blank line ─────────────

    def test_subtask_no_blank_lines(self):
        nodes = []
        insert_task(nodes, self._task('Child', indent='  '))
        self.assertEqual(serialize(nodes), '  - [ ] Child\n')

    def test_subtask_no_blank_after_preceding_content(self):
        b = _block('- [ ] Parent')
        nodes = [b]
        insert_task(nodes, self._task('Child', indent='  '))
        self.assertEqual(serialize(nodes), '- [ ] Parent\n  - [ ] Child\n')

    # ── return value and field ranges ─────────────────────────────────────────

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


if __name__ == '__main__':
    unittest.main()
