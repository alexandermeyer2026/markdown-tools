import datetime
import os
import shutil
import tempfile
import unittest

import pytest

from models import Task
from models.file import RawLine, TaskBlock, serialize
from tools.journal_tools.planner import DayCache
from tools.journal_tools.planner.state import PlannerState
from tools.journal_tools.planner.weekly import cache_has_changes
from parser.operations import task_to_block


@pytest.mark.integration


class TestWeekCacheChanges(unittest.TestCase):

    def _make_cache(self, blocks):
        nodes = list(blocks)
        return {'2024-01-15': DayCache(file_path=None, nodes=nodes)}

    def test_no_changes_returns_false(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        child_block = task_to_block(child)
        parent_block = task_to_block(parent, subtask_blocks=[child_block])
        cache = self._make_cache([parent_block])
        self.assertFalse(cache_has_changes(cache))

    def test_parent_status_change_detected(self):
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        parent_block = task_to_block(parent)
        cache = self._make_cache([parent_block])
        cache['2024-01-15'].set_status(parent, 'done')
        self.assertTrue(cache_has_changes(cache))

    def test_subtask_status_change_detected(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        child_block = task_to_block(child)
        parent_block = task_to_block(parent, subtask_blocks=[child_block])
        cache = self._make_cache([parent_block])
        cache['2024-01-15'].set_status(child, 'done')
        self.assertTrue(cache_has_changes(cache))

    def test_add_block_no_separator_when_no_trailing_blank(self):
        existing = task_to_block(Task(title='Existing', status='todo', time=None, line_number=1, indent=''))
        day = DayCache(file_path=None, nodes=[existing])
        new_block = task_to_block(Task(title='New', status='todo', time=None, line_number=-1, indent=''))
        day.add_block(new_block)
        self.assertEqual(serialize(day.nodes), '- [ ] Existing\n- [ ] New\n')

    def test_add_block_no_separator_when_trailing_blank_already_present(self):
        existing = task_to_block(Task(title='Existing', status='todo', time=None, line_number=1, indent=''))
        existing.nodes.append(RawLine('\n'))
        day = DayCache(file_path=None, nodes=[existing])
        new_block = task_to_block(Task(title='New', status='todo', time=None, line_number=-1, indent=''))
        day.add_block(new_block)
        self.assertEqual(serialize(day.nodes), '- [ ] Existing\n\n- [ ] New\n')


class TestPlannerState(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.date = datetime.date(2024, 3, 15)
        self.path = os.path.join(self.tmpdir, '2024-03-15.md')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task A\n    Some notes\n- [x] Task B\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_load_day_parses_tasks(self):
        state = PlannerState(self.tmpdir)
        day = state.load_day(self.date)
        self.assertEqual(len(day.task_list), 2)
        self.assertEqual(day.task_list[0].task.title, 'Task A')
        self.assertEqual(day.task_list[1].task.title, 'Task B')

    def test_load_day_is_idempotent(self):
        state = PlannerState(self.tmpdir)
        day1 = state.load_day(self.date)
        day2 = state.load_day(self.date)
        self.assertIs(day1, day2)

    def test_load_day_missing_file_returns_empty(self):
        state = PlannerState(self.tmpdir)
        day = state.load_day(datetime.date(2024, 3, 16))
        self.assertEqual(day.task_list, [])
        self.assertIsNone(day.file_path)

    def test_task_body_populated_on_load(self):
        state = PlannerState(self.tmpdir)
        day = state.load_day(self.date)
        block_a = day.task_list[0]
        raw_texts = [n.raw for n in block_a.nodes if isinstance(n, RawLine)]
        self.assertTrue(raw_texts)
        self.assertTrue(any('Some notes' in r for r in raw_texts))

    def test_reload_discards_in_memory_mutations(self):
        state = PlannerState(self.tmpdir)
        key = self.date.isoformat()
        state.load_day(self.date)
        new = Task(title='Ephemeral', status='todo', time=None, line_number=-1, indent='')
        state.days[key].add_block(task_to_block(new))
        self.assertEqual(len(state.days[key].task_list), 3)
        state.reload_day_by_key(key)
        self.assertEqual(len(state.days[key].task_list), 2)
        self.assertNotIn('Ephemeral', [b.task.title for b in state.days[key].task_list])

    def test_reload_refreshes_task_list(self):
        state = PlannerState(self.tmpdir)
        key = self.date.isoformat()
        state.load_day(self.date)
        n_before = len(state.days[key].task_list)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write("- [ ] Task C\n")
        state.reload_day_by_key(key)
        self.assertGreater(len(state.days[key].task_list), n_before)
        self.assertFalse(state.days[key].has_changes)

    def test_task_body_dedented_on_load(self):
        import textwrap
        state = PlannerState(self.tmpdir)
        day = state.load_day(self.date)
        block_a = day.task_list[0]
        body_lines = [n.raw.rstrip('\n') for n in block_a.nodes if isinstance(n, RawLine)]
        body_str = textwrap.dedent('\n'.join(body_lines)).strip()
        self.assertEqual(body_str, 'Some notes')
