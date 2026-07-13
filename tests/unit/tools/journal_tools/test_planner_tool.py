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
from tools.journal_tools.planner.weekly import cache_has_changes, save_cache
from models.file import TaskBlock


@pytest.mark.integration


class TestWeekCacheChanges(unittest.TestCase):

    def _make_cache(self, blocks):
        nodes = list(blocks)
        return {'2024-01-15': DayCache(file_path=None, nodes=nodes)}

    def test_no_changes_returns_false(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        child_block = TaskBlock.from_task(child)
        parent_block = TaskBlock.from_task(parent, subtask_blocks=[child_block])
        cache = self._make_cache([parent_block])
        self.assertFalse(cache_has_changes(cache))

    def test_parent_status_change_detected(self):
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        parent_block = TaskBlock.from_task(parent)
        cache = self._make_cache([parent_block])
        cache['2024-01-15'].set_status(parent, 'done')
        self.assertTrue(cache_has_changes(cache))

    def test_subtask_status_change_detected(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        child_block = TaskBlock.from_task(child)
        parent_block = TaskBlock.from_task(parent, subtask_blocks=[child_block])
        cache = self._make_cache([parent_block])
        cache['2024-01-15'].set_status(child, 'done')
        self.assertTrue(cache_has_changes(cache))

    def test_set_priority_change_detected(self):
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        parent_block = TaskBlock.from_task(parent)
        cache = self._make_cache([parent_block])
        cache['2024-01-15'].set_priority(parent, '!!')
        self.assertTrue(cache_has_changes(cache))
        self.assertEqual(serialize(cache['2024-01-15'].nodes), '- [ ] !! Parent\n')

    def test_set_priority_none_is_noop(self):
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        parent_block = TaskBlock.from_task(parent)
        cache = self._make_cache([parent_block])
        cache['2024-01-15'].set_priority(parent, None)
        self.assertFalse(cache_has_changes(cache))

    def test_add_block_no_separator_when_no_trailing_blank(self):
        existing = TaskBlock.from_task(Task(title='Existing', status='todo', time=None, line_number=1, indent=''))
        day = DayCache(file_path=None, nodes=[existing])
        new_block = TaskBlock.from_task(Task(title='New', status='todo', time=None, line_number=-1, indent=''))
        day.add_block(new_block)
        self.assertEqual(serialize(day.nodes), '- [ ] Existing\n- [ ] New\n')

    def test_add_block_no_separator_when_trailing_blank_already_present(self):
        existing = TaskBlock.from_task(Task(title='Existing', status='todo', time=None, line_number=1, indent=''))
        existing.nodes.append(RawLine('\n'))
        day = DayCache(file_path=None, nodes=[existing])
        new_block = TaskBlock.from_task(Task(title='New', status='todo', time=None, line_number=-1, indent=''))
        day.add_block(new_block)
        self.assertEqual(serialize(day.nodes), '- [ ] Existing\n\n- [ ] New\n')


class TestSaveCache(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_transit_day_does_not_create_file(self):
        task = Task(title='Errand', status='todo', time=None, line_number=1, indent='')
        block = TaskBlock.from_task(task)

        transit = DayCache(file_path=None, nodes=[])
        transit.add_block(block)
        transit.remove_block(block)

        self.assertTrue(transit.has_changes)
        self.assertEqual(transit.nodes, [])

        save_cache({'2024-01-03': transit}, self.tmpdir)

        self.assertEqual(os.listdir(self.tmpdir), [])


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
        state.days[key].add_block(TaskBlock.from_task(new))
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

    def test_reopen_refreshes_clean_day_from_disk(self):
        """A cached day with no unsaved edits must reflect the current file when
        reopened — the dashboard/week/day views share one cache, so a stale clean
        snapshot would otherwise overwrite a newer file (heading loss) on save."""
        state = PlannerState(self.tmpdir)
        state.load_day(self.date)  # caches a clean snapshot
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("# Heading\n\n- [ ] Task A\n- [x] Task B\n- [ ] Task C\n")
        day = state.load_day(self.date)  # reopen → refresh from disk
        self.assertIn('Task C', [b.task.title for b in day.task_list])
        self.assertEqual(serialize(day.nodes).splitlines()[0], '# Heading')

    def test_reopen_preserves_unsaved_edits_over_disk_change(self):
        """A cached day WITH unsaved edits is never refreshed — edits must not be
        silently discarded even if the file changed underneath."""
        state = PlannerState(self.tmpdir)
        key = self.date.isoformat()
        state.load_day(self.date)
        ephemeral = Task(title='Ephemeral', status='todo', time=None, line_number=-1, indent='')
        state.days[key].add_block(TaskBlock.from_task(ephemeral))  # unsaved edit
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Totally different\n")
        day = state.load_day(self.date)
        self.assertIn('Ephemeral', [b.task.title for b in day.task_list])
        self.assertTrue(day.has_changes)

    def test_reopen_adopts_file_created_after_empty_cache(self):
        """A day first cached as empty (no file) must adopt a file created later,
        e.g. the week view caches a missing day before it exists on disk."""
        state = PlannerState(self.tmpdir)
        future = datetime.date(2024, 3, 16)
        day1 = state.load_day(future)
        self.assertIsNone(day1.file_path)
        newpath = os.path.join(self.tmpdir, '2024-03-16.md')
        with open(newpath, 'w', encoding='utf-8') as f:
            f.write("# New Day\n\n- [ ] Fresh task\n")
        day2 = state.load_day(future)
        self.assertEqual(day2.file_path, newpath)
        self.assertEqual([b.task.title for b in day2.task_list], ['Fresh task'])

    def test_task_body_dedented_on_load(self):
        import textwrap
        state = PlannerState(self.tmpdir)
        day = state.load_day(self.date)
        block_a = day.task_list[0]
        body_lines = [n.raw.rstrip('\n') for n in block_a.nodes if isinstance(n, RawLine)]
        body_str = textwrap.dedent('\n'.join(body_lines)).strip()
        self.assertEqual(body_str, 'Some notes')


class TestNextPriority(unittest.TestCase):
    def test_rotation_cycles_and_wraps(self):
        from tools.journal_tools.planner.utils import next_priority
        self.assertEqual(next_priority(None), '!')
        self.assertEqual(next_priority('!'), '!!')
        self.assertEqual(next_priority('!!'), '!!!')
        self.assertEqual(next_priority('!!!'), None)

    def test_unknown_value_restarts_cycle(self):
        from tools.journal_tools.planner.utils import next_priority
        self.assertEqual(next_priority('bogus'), '!')
