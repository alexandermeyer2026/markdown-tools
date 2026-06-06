import asyncio
import contextlib
import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import pytest

from models import Task, TaskTime, minutes_to_time
from os_utils import FileFinder, resolve_date
from tools.journal_tools.planner import WeekState, DayCache
from tools.journal_tools.planner.app import PlannerApp
from tools.journal_tools.planner.daily import save as planner_save, has_changes as planner_has_changes
from tools.journal_tools.planner.day_screen import DayGrid
from tools.journal_tools.planner.save_dialog import SaveDialog
from tools.journal_tools.planner.task_form_screen import TaskFormScreen, TaskFormResult
from tools.journal_tools.planner.week_screen import WeekGrid
from tools.journal_tools.planner.utils import task_to_lines
from tools.journal_tools.planner.weekly import cache_has_changes

JOURNAL_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'journal')
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'planner')


@pytest.mark.integration
class TestSave(unittest.TestCase):
    CONTENT = (
        "# Journal\n"
        "\n"
        "- [ ] 9:00-10:00 Meeting\n"
        "- [ ] Buy milk\n"
    )

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        self.tmp.write(self.CONTENT)
        self.tmp.close()
        self.path = self.tmp.name
        self.directory = os.path.dirname(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        backup_dir = os.path.join(self.directory, '.backups')
        if os.path.exists(backup_dir):
            for f in os.listdir(backup_dir):
                os.unlink(os.path.join(backup_dir, f))
            os.rmdir(backup_dir)

    def _read(self):
        with open(self.path, encoding='utf-8') as f:
            return f.read()

    def test_unchanged_task_not_touched(self):
        task = Task(title='Meeting', status='todo',
                    time=TaskTime(start='9:00', end='10:00'), line_number=3, indent='')
        planner_save(self.path, self.directory, [task], [],
                          {3: task.to_line()}, [])
        self.assertEqual(self._read(), self.CONTENT)

    def test_task_with_unknown_line_number_not_written(self):
        task = Task(title='Ghost', status='done', time=None, line_number=99, indent='')
        planner_save(self.path, self.directory, [task], [], {}, [])
        self.assertEqual(self._read(), self.CONTENT)

    def test_backup_created(self):
        planner_save(self.path, self.directory, [], [], {}, [])
        backup_dir = os.path.join(self.directory, '.backups')
        self.assertTrue(os.path.exists(backup_dir))
        self.assertEqual(len(os.listdir(backup_dir)), 1)

    def test_atomic_write_leaves_no_tmp(self):
        planner_save(self.path, self.directory, [], [], {}, [])
        self.assertFalse(os.path.exists(self.path + '.tmp'))

    def test_delete_root_task(self):
        from parser.task_parser import TaskParser
        tasks = TaskParser.parse_file(self.path)
        meeting = tasks[0]
        buy = tasks[1]
        original_lines = {t.line_number: t.to_line() for t in tasks}
        planner_save(self.path, self.directory, [meeting], [], original_lines, [], [buy])
        result = self._read()
        self.assertIn('Meeting', result)
        self.assertNotIn('Buy milk', result)

    def test_delete_root_task_with_subtasks(self):
        content = (
            "- [ ] Buy milk\n"
            "  - [ ] Bread\n"
            "  - [ ] Eggs\n"
            "- [ ] Call dentist\n"
        )
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(content)
        from parser.task_parser import TaskParser
        tasks = TaskParser.parse_file(self.path)
        buy, bread, eggs, dentist = tasks
        original_lines = {t.line_number: t.to_line() for t in tasks}
        planner_save(self.path, self.directory, [], [dentist], original_lines, [], [buy])
        result = self._read()
        self.assertNotIn('Buy milk', result)
        self.assertNotIn('Bread', result)
        self.assertNotIn('Eggs', result)
        self.assertIn('Call dentist', result)

    def test_delete_subtask(self):
        content = (
            "- [ ] Buy milk\n"
            "  - [ ] Bread\n"
            "  - [ ] Eggs\n"
            "- [ ] Call dentist\n"
        )
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(content)
        from parser.task_parser import TaskParser
        tasks = TaskParser.parse_file(self.path)
        buy, bread, eggs, dentist = tasks
        original_lines = {t.line_number: t.to_line() for t in tasks}
        buy.children.remove(bread)
        planner_save(self.path, self.directory, [], [buy], original_lines, [], [bread])
        result = self._read()
        self.assertIn('Buy milk', result)
        self.assertNotIn('Bread', result)
        self.assertIn('Eggs', result)
        self.assertIn('Call dentist', result)

    def test_new_task_with_body_written_to_file(self):
        new_task = Task(title='Dentist', status='todo', time=None, line_number=-1, indent='',
                        body='Bring insurance card')
        planner_save(self.path, self.directory, [], [], {}, [new_task])
        result = self._read()
        self.assertIn('- [ ] Dentist\n', result)
        self.assertIn('    Bring insurance card\n', result)
        lines = result.splitlines()
        task_idx = next(i for i, l in enumerate(lines) if 'Dentist' in l)
        self.assertEqual(lines[task_idx + 1], '    Bring insurance card')

    def test_new_task_multiline_body_written(self):
        new_task = Task(title='Plan', status='todo', time=None, line_number=-1, indent='',
                        body='Line one\nLine two')
        planner_save(self.path, self.directory, [], [], {}, [new_task])
        result = self._read()
        self.assertIn('    Line one\n', result)
        self.assertIn('    Line two\n', result)

    def test_edit_task_body_updates_file(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task A\n    Old notes\n- [ ] Task B\n")
        from parser.task_parser import TaskParser
        tasks = TaskParser.parse_file(self.path)
        task_a, task_b = tasks[0], tasks[1]
        original_lines = {t.line_number: t.to_line() for t in tasks}
        original_bodies = {t.line_number: t.body for t in tasks}
        task_a.body = 'New notes'
        planner_save(self.path, self.directory, [], [task_a, task_b],
                     original_lines, [], original_bodies=original_bodies)
        result = self._read()
        self.assertNotIn('Old notes', result)
        self.assertIn('New notes', result)
        self.assertIn('Task A', result)
        self.assertIn('Task B', result)

    def test_clearing_task_body_removes_lines(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task A\n    Some notes\n- [ ] Task B\n")
        from parser.task_parser import TaskParser
        tasks = TaskParser.parse_file(self.path)
        task_a, task_b = tasks[0], tasks[1]
        original_lines = {t.line_number: t.to_line() for t in tasks}
        original_bodies = {t.line_number: t.body for t in tasks}
        task_a.body = None
        planner_save(self.path, self.directory, [], [task_a, task_b],
                     original_lines, [], original_bodies=original_bodies)
        result = self._read()
        self.assertNotIn('Some notes', result)
        self.assertIn('Task A', result)
        self.assertIn('Task B', result)

    def test_new_task_on_file_with_trailing_blank_has_single_gap(self):
        # File ending with a trailing blank line must not produce a double blank gap
        # before the new task. sort_timed_tasks only fixes this when >=2 timed tasks
        # exist; with an untimed file the bug survives unfixed.
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Buy milk\n\n")
        new_task = Task(title='Call dentist', status='todo', time=None, line_number=-1, indent='')
        planner_save(self.path, self.directory, [], [], {}, [new_task])
        self.assertEqual(self._read(), "- [ ] Buy milk\n\n- [ ] Call dentist\n")


class TestHasChanges(unittest.TestCase):
    CONTENT = (
        "# Journal\n"
        "\n"
        "- [ ] Buy milk\n"
        "  - [ ] Sub task\n"
    )

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        self.tmp.write(self.CONTENT)
        self.tmp.close()
        self.path = self.tmp.name
        from parser.task_parser import TaskParser
        self.tasks = TaskParser.parse_file(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_subtask_status_change_detected(self):
        parent = self.tasks[0]
        child  = self.tasks[1]
        original_lines = {t.line_number: t.to_line() for t in self.tasks}
        self.assertFalse(planner_has_changes([parent], [], original_lines, []))
        child.status = 'done'
        self.assertTrue(planner_has_changes([parent], [], original_lines, []))

    def test_deleted_task_detected(self):
        parent = self.tasks[0]
        original_lines = {t.line_number: t.to_line() for t in self.tasks}
        self.assertFalse(planner_has_changes([parent], [], original_lines, []))
        self.assertTrue(planner_has_changes([parent], [], original_lines, [], [parent]))

    def test_body_change_detected(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task\n    Some notes\n")
        from parser.task_parser import TaskParser
        tasks = TaskParser.parse_file(self.path)
        task = tasks[0]
        original_lines = {t.line_number: t.to_line() for t in tasks}
        original_bodies = {t.line_number: t.body for t in tasks}
        self.assertFalse(planner_has_changes([task], [], original_lines, [], original_bodies=original_bodies))
        task.body = 'Changed notes'
        self.assertTrue(planner_has_changes([task], [], original_lines, [], original_bodies=original_bodies))

    def test_body_cleared_detected(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task\n    Some notes\n")
        from parser.task_parser import TaskParser
        tasks = TaskParser.parse_file(self.path)
        task = tasks[0]
        original_lines = {t.line_number: t.to_line() for t in tasks}
        original_bodies = {t.line_number: t.body for t in tasks}
        task.body = None
        self.assertTrue(planner_has_changes([task], [], original_lines, [], original_bodies=original_bodies))

    def test_body_unchanged_not_detected(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task\n    Some notes\n")
        from parser.task_parser import TaskParser
        tasks = TaskParser.parse_file(self.path)
        task = tasks[0]
        original_lines = {t.line_number: t.to_line() for t in tasks}
        original_bodies = {t.line_number: t.body for t in tasks}
        self.assertFalse(planner_has_changes([task], [], original_lines, [], original_bodies=original_bodies))


class TestWeekCacheChanges(unittest.TestCase):

    def _make_cache(self, tasks):
        tl = [t for t in tasks if t.parent is None]
        return {
            '2024-01-15': DayCache(
                file_path=None,
                all_tasks=tasks,
                task_list=tl,
                original_task_list=list(tl),
                original_lines={t.line_number: t.to_line() for t in tasks if t.line_number > 0},
            )
        }

    def test_no_changes_returns_false(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='',
                      children=[child])
        child.parent = parent
        cache = self._make_cache([parent, child])
        self.assertFalse(cache_has_changes(cache))

    def test_parent_status_change_detected(self):
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        cache = self._make_cache([parent])
        parent.status = 'done'
        self.assertTrue(cache_has_changes(cache))

    def test_subtask_status_change_detected(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='',
                      children=[child])
        child.parent = parent
        cache = self._make_cache([parent, child])
        child.status = 'done'
        self.assertTrue(cache_has_changes(cache))


class TestTaskToLines(unittest.TestCase):
    def test_simple_todo(self):
        task = Task(title='Buy milk', status='todo', time=None, line_number=1, indent='')
        self.assertEqual(task_to_lines(task), ['- [ ] Buy milk\n'])

    def test_done_task(self):
        task = Task(title='Buy milk', status='done', time=None, line_number=1, indent='')
        self.assertEqual(task_to_lines(task), ['- [x] Buy milk\n'])

    def test_timed_task(self):
        task = Task(title='Meeting', status='todo',
                    time=TaskTime(start='9:00', end='10:00'), line_number=1, indent='')
        self.assertEqual(task_to_lines(task), ['- [ ] 9:00-10:00 Meeting\n'])

    def test_with_child(self):
        child = Task(title='Sub', status='done', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='',
                      children=[child])
        child.parent = parent
        self.assertEqual(task_to_lines(parent), ['- [ ] Parent\n', '  - [x] Sub\n'])

    def test_deeply_nested(self):
        grandchild = Task(title='Leaf', status='todo', time=None, line_number=3, indent='    ')
        child = Task(title='Mid', status='todo', time=None, line_number=2, indent='  ',
                     children=[grandchild])
        parent = Task(title='Root', status='todo', time=None, line_number=1, indent='',
                      children=[child])
        grandchild.parent = child
        child.parent = parent
        self.assertEqual(task_to_lines(parent),
                         ['- [ ] Root\n', '  - [ ] Mid\n', '    - [ ] Leaf\n'])


@pytest.mark.integration
class PlannerIntegrationTest(unittest.TestCase):

    def _run_fixture(self, fixture_name):
        fixture_dir = os.path.join(FIXTURES_DIR, fixture_name)
        with open(os.path.join(fixture_dir, 'scenario.json')) as f:
            config = json.load(f)

        args      = config['args']
        keys      = config['keys']
        do_save   = config.get('save', False)
        week_today = config.get('week_today')

        tmpdir = tempfile.mkdtemp()
        try:
            for fname in os.listdir(JOURNAL_DIR):
                shutil.copy(os.path.join(JOURNAL_DIR, fname), os.path.join(tmpdir, fname))

            asyncio.run(self._drive_app(args, keys, do_save, week_today, tmpdir))

            expected_dir = os.path.join(fixture_dir, 'expected')
            for fname in sorted(os.listdir(expected_dir)):
                with open(os.path.join(expected_dir, fname)) as f:
                    expected = f.read()
                with open(os.path.join(tmpdir, fname)) as f:
                    actual = f.read()
                self.assertEqual(actual, expected, f"Mismatch in {fname}")
        finally:
            shutil.rmtree(tmpdir)

    async def _drive_app(self, args, keys, do_save, week_today, tmpdir):
        file_path = None
        date = None
        if args:
            input_arg = args[0]
            basename = os.path.basename(input_arg)
            date = resolve_date(basename) or FileFinder.get_journal_file_date(input_arg)
            if date:
                journal_files = FileFinder.find_journal_files(tmpdir, date_from=date, date_to=date)
                if journal_files:
                    file_path = journal_files[0]

        patches = []
        if week_today:
            fixed = datetime.date.fromisoformat(week_today)
            mock_dt = MagicMock()
            mock_dt.date.today.return_value = fixed
            mock_dt.timedelta = datetime.timedelta
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            patches.append(patch('tools.journal_tools.planner.week_screen.datetime', mock_dt))

        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            app = PlannerApp(tmpdir, file_path=file_path, date=date)
            async with app.run_test() as pilot:
                await pilot.pause()
                for key in keys:
                    await pilot.press(key)
                if isinstance(app.screen, SaveDialog):
                    await pilot.click('#yes' if do_save else '#no')

    def test_sort_on_save(self):
        self._run_fixture('sort_on_save')

    def test_week_move_and_sort(self):
        self._run_fixture('week_move_and_sort')

    def test_week_cross_week_move(self):
        self._run_fixture('week_cross_week_move')

    def test_week_subtask_status(self):
        self._run_fixture('week_subtask_status')

    def test_week_carry_forward(self):
        self._run_fixture('week_carry_forward')

    def test_week_carry_and_move(self):
        self._run_fixture('week_carry_and_move')

    def test_week_carry_then_cross_week_move(self):
        self._run_fixture('week_carry_then_cross_week_move')

    def test_week_delete_two_nonadjacent(self):
        # Two deletions targeting lines 3 and 6 in the same save; verifies that
        # both use their original line numbers simultaneously (not sequentially,
        # which would shift line 6 to 5 after the first removal and hit the wrong task).
        self._run_fixture('week_delete_two_nonadjacent')

    def test_week_delete_body_text(self):
        # Task with body text (non-task line between tasks); verifies the block-range
        # algorithm includes the body line in the deletion even though it has no entry
        # in original_lines.
        self._run_fixture('week_delete_body_text')

    def test_week_delete_task(self):
        self._run_fixture('week_delete_task')

    def test_week_delete_then_status_change(self):
        self._run_fixture('week_delete_then_status_change')


class TestDayGridInteraction(unittest.TestCase):
    """Pilot-driven tests for DayScreen time-manipulation and quit logic."""

    STEP_M = 15

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        self.tmp.write("- [ ] 9:00-10:00 Meeting\n- [ ] Buy milk\n")
        self.tmp.close()
        self.path = self.tmp.name
        self.directory = os.path.dirname(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        backup_dir = os.path.join(self.directory, '.backups')
        if os.path.exists(backup_dir):
            for f in os.listdir(backup_dir):
                os.unlink(os.path.join(backup_dir, f))
            os.rmdir(backup_dir)

    def _read(self):
        with open(self.path, encoding='utf-8') as f:
            return f.read()

    async def _inspect(self, keys):
        """Press keys and return (timed_tasks, untimed_tasks) from the grid."""
        app = PlannerApp(self.directory, file_path=self.path)
        async with app.run_test() as pilot:
            for key in keys:
                await pilot.press(key)
            grid = app.screen.query_one(DayGrid)
            return list(grid._timed_tasks), list(grid._untimed_tasks)

    async def _drive_quit(self, keys, dialog_response=None):
        app = PlannerApp(self.directory, file_path=self.path)
        async with app.run_test() as pilot:
            for key in keys:
                await pilot.press(key)
            if dialog_response and isinstance(app.screen, SaveDialog):
                await pilot.click(dialog_response)

    # ── Time shifting ─────────────────────────────────────────────────────────

    def test_shift_right(self):
        timed, _ = asyncio.run(self._inspect(['l']))
        self.assertEqual(timed[0].time.start, minutes_to_time(540 + self.STEP_M))
        self.assertEqual(timed[0].time.end,   minutes_to_time(600 + self.STEP_M))

    def test_shift_left(self):
        timed, _ = asyncio.run(self._inspect(['h']))
        self.assertEqual(timed[0].time.start, minutes_to_time(540 - self.STEP_M))
        self.assertEqual(timed[0].time.end,   minutes_to_time(600 - self.STEP_M))

    def test_shift_clamps_at_zero(self):
        presses = 540 // self.STEP_M + 5
        timed, _ = asyncio.run(self._inspect(['h'] * presses))
        self.assertEqual(timed[0].time.start, '0:00')
        self.assertEqual(timed[0].time.end,   minutes_to_time(60))

    def test_extend_end_time(self):
        timed, _ = asyncio.run(self._inspect(['L']))
        self.assertEqual(timed[0].time.start, '9:00')
        self.assertEqual(timed[0].time.end,   minutes_to_time(600 + self.STEP_M))

    def test_shrink_end_time(self):
        timed, _ = asyncio.run(self._inspect(['H']))
        self.assertEqual(timed[0].time.start, '9:00')
        self.assertEqual(timed[0].time.end,   minutes_to_time(600 - self.STEP_M))

    def test_shrink_fuses_at_minimum_duration(self):
        # Meeting is 9:00-10:00 = 60 min; 4 presses shrink end to == start → fuse
        presses = 60 // self.STEP_M
        timed, _ = asyncio.run(self._inspect(['H'] * presses))
        self.assertEqual(timed[0].time.start, '9:00')
        self.assertIsNone(timed[0].time.end)

    def test_extend_creates_end_time_for_start_only_task(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] 9:00 Standup\n")
        timed, _ = asyncio.run(self._inspect(['L']))
        self.assertEqual(timed[0].time.start, '9:00')
        self.assertEqual(timed[0].time.end,   minutes_to_time(540 + self.STEP_M))

    def test_untimed_task_moves_to_noon(self):
        # j to Buy milk (untimed), l schedules it at noon
        timed, untimed = asyncio.run(self._inspect(['j', 'l']))
        timed_titles = [t.title for t in timed]
        self.assertIn('Buy milk', timed_titles)
        milk = next(t for t in timed if t.title == 'Buy milk')
        self.assertEqual(milk.time.start, '12:00')
        self.assertIsNone(milk.time.end)

    def test_extend_creates_end_time_for_untimed_task(self):
        # j to Buy milk, l schedules at noon, L adds end time
        timed, _ = asyncio.run(self._inspect(['j', 'l', 'L']))
        milk = next(t for t in timed if t.title == 'Buy milk')
        self.assertEqual(milk.time.start, '12:00')
        self.assertEqual(milk.time.end, minutes_to_time(720 + self.STEP_M))

    # ── Remove time ───────────────────────────────────────────────────────────

    def test_remove_time_moves_task_to_untimed(self):
        timed, untimed = asyncio.run(self._inspect(['r']))
        self.assertNotIn('Meeting', [t.title for t in timed])
        self.assertIn('Meeting', [t.title for t in untimed])

    def test_remove_time_on_untimed_is_noop(self):
        timed_before, untimed_before = asyncio.run(self._inspect([]))
        timed_after,  untimed_after  = asyncio.run(self._inspect(['j', 'r']))
        self.assertEqual(len(timed_after),   len(timed_before))
        self.assertEqual(len(untimed_after), len(untimed_before))

    # ── Quit paths ────────────────────────────────────────────────────────────

    def test_quit_no_changes_does_not_save(self):
        with open(self.path) as f:
            content_before = f.read()
        asyncio.run(self._drive_quit(['q']))
        with open(self.path) as f:
            self.assertEqual(f.read(), content_before)

    def test_quit_discard_does_not_save(self):
        with open(self.path) as f:
            content_before = f.read()
        asyncio.run(self._drive_quit(['l', 'q'], dialog_response='#no'))
        with open(self.path) as f:
            self.assertEqual(f.read(), content_before)

    # ── Deletion ──────────────────────────────────────────────────────────────

    def test_delete_untimed_task(self):
        # j moves cursor to Buy milk (untimed), D deletes it
        # (integration tests only cover timed deletion, so this fills the gap)
        timed, untimed = asyncio.run(self._inspect(['j', 'D']))
        self.assertEqual([t.title for t in timed], ['Meeting'])
        self.assertEqual([t.title for t in untimed], [])

    def test_delete_does_not_persist_without_save(self):
        with open(self.path) as f:
            content_before = f.read()
        asyncio.run(self._drive_quit(['D', 'q'], dialog_response='#no'))
        with open(self.path) as f:
            self.assertEqual(f.read(), content_before)

    async def _change_and_save(self, change_keys):
        """Press change_keys, save with ctrl+s + confirm, return grid snapshot."""
        app = PlannerApp(self.directory, file_path=self.path)
        async with app.run_test() as pilot:
            await pilot.pause()
            for key in change_keys:
                await pilot.press(key)
            await pilot.press('ctrl+s')
            await pilot.pause()
            if isinstance(app.screen, SaveDialog):
                await pilot.click('#yes')
                await pilot.pause()
            grid = app.screen.query_one(DayGrid)
            return grid._has_changes(), list(grid._new_tasks), list(grid._deleted_tasks)

    def test_save_clears_dirty_flag_after_status_change(self):
        # Regression: _original_lines was not reloaded after save, leaving the
        # dirty flag set so the user could keep re-saving with no visible effect.
        has_chg, _, _ = asyncio.run(self._change_and_save(['d']))
        self.assertFalse(has_chg)

    def test_save_clears_new_tasks_list_to_prevent_duplicates(self):
        # Regression: _new_tasks was not cleared after save, so a second save
        # would append the task again and produce duplicates in the file.
        from textual.widgets import Input

        async def run():
            app = PlannerApp(self.directory, file_path=self.path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('n')
                await pilot.pause()
                app.screen.query_one('#title', Input).value = 'Regression task'
                await pilot.press('ctrl+s')
                await pilot.pause()
                await pilot.press('ctrl+s')
                await pilot.pause()
                if isinstance(app.screen, SaveDialog):
                    await pilot.click('#yes')
                    await pilot.pause()
                grid = app.screen.query_one(DayGrid)
                return grid._has_changes(), list(grid._new_tasks)

        has_chg, new_tasks = asyncio.run(run())
        self.assertFalse(has_chg)
        self.assertEqual(new_tasks, [])
        with open(self.path) as f:
            self.assertEqual(f.read().count('Regression task'), 1)


    # ── Task body ─────────────────────────────────────────────────────────────

    def test_new_task_body_persisted_after_save(self):
        from textual.widgets import Input, TextArea

        async def run():
            app = PlannerApp(self.directory, file_path=self.path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('n')
                await pilot.pause()
                app.screen.query_one('#title', Input).value = 'Dentist appointment'
                app.screen.query_one('#body', TextArea).text = 'Bring insurance card'
                await pilot.press('ctrl+s')   # save form
                await pilot.pause()
                await pilot.press('ctrl+s')   # open save dialog
                await pilot.pause()
                if isinstance(app.screen, SaveDialog):
                    await pilot.click('#yes')
                    await pilot.pause()

        asyncio.run(run())
        content = self._read()
        self.assertIn('Dentist appointment', content)
        self.assertIn('Bring insurance card', content)
        lines = content.splitlines()
        task_idx = next(i for i, l in enumerate(lines) if 'Dentist appointment' in l)
        self.assertTrue(lines[task_idx + 1].startswith('    '))
        self.assertIn('Bring insurance card', lines[task_idx + 1])

    def test_edit_task_body_persisted_after_save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task A\n    Old notes\n- [ ] Buy milk\n")

        async def run():
            from textual.widgets import TextArea
            app = PlannerApp(self.directory, file_path=self.path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('enter')    # open edit form for Task A
                await pilot.pause()
                app.screen.query_one('#body', TextArea).text = 'New notes'
                await pilot.press('ctrl+s')   # save form
                await pilot.pause()
                await pilot.press('ctrl+s')   # open save dialog
                await pilot.pause()
                if isinstance(app.screen, SaveDialog):
                    await pilot.click('#yes')
                    await pilot.pause()
                grid = app.screen.query_one(DayGrid)
                return grid._has_changes()

        has_chg = asyncio.run(run())
        self.assertFalse(has_chg)
        content = self._read()
        self.assertNotIn('Old notes', content)
        self.assertIn('New notes', content)
        self.assertIn('Task A', content)
        self.assertIn('Buy milk', content)

    def test_clearing_task_body_persisted_after_save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task A\n    Old notes\n- [ ] Buy milk\n")

        async def run():
            from textual.widgets import TextArea
            app = PlannerApp(self.directory, file_path=self.path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('enter')    # open edit form for Task A
                await pilot.pause()
                app.screen.query_one('#body', TextArea).text = ''
                await pilot.press('ctrl+s')   # save form
                await pilot.pause()
                await pilot.press('ctrl+s')   # open save dialog
                await pilot.pause()
                if isinstance(app.screen, SaveDialog):
                    await pilot.click('#yes')
                    await pilot.pause()

        asyncio.run(run())
        content = self._read()
        self.assertNotIn('Old notes', content)
        self.assertIn('Task A', content)
        self.assertIn('Buy milk', content)

    def test_edit_task_body_marks_dirty(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Task A\n    Some notes\n")

        async def run():
            from textual.widgets import TextArea
            app = PlannerApp(self.directory, file_path=self.path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('enter')    # open edit form
                await pilot.pause()
                app.screen.query_one('#body', TextArea).text = 'Changed notes'
                await pilot.press('ctrl+s')   # save form (not file)
                await pilot.pause()
                grid = app.screen.query_one(DayGrid)
                return grid._has_changes()

        self.assertTrue(asyncio.run(run()))


class TestWeekGridInteraction(unittest.TestCase):
    """Pilot-driven tests for WeekScreen interaction logic."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Wednesday 2024-01-10: parent task with one subtask
        with open(os.path.join(self.tmpdir, '2024-01-10.md'), 'w') as f:
            f.write("- [ ] My task\n  - [ ] Sub\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    async def _inspect(self, keys, week_today='2024-01-10'):
        fixed = datetime.date.fromisoformat(week_today)
        mock_dt = MagicMock()
        mock_dt.date.today.return_value = fixed
        mock_dt.timedelta = datetime.timedelta
        mock_dt.date.fromisoformat = datetime.date.fromisoformat
        with patch('tools.journal_tools.planner.week_screen.datetime', mock_dt):
            app = PlannerApp(self.tmpdir)
            async with app.run_test() as pilot:
                await pilot.pause()  # let push_screen from on_mount settle
                for key in keys:
                    await pilot.press(key)
                grid = app.screen.query_one(WeekGrid)
                return grid._state, grid.cursor_col, grid.cursor_row

    def test_H_on_subtask_moves_root_to_previous_day(self):
        # 2024-01-10 is Wednesday (weekday=2); cursor starts at col=2, row=0
        # j → row=1 (Sub), H → root (My task + Sub) moves to Tuesday (col=1)
        state, col, row = asyncio.run(self._inspect(['j', 'H']))
        self.assertEqual(col, 1)
        self.assertEqual(len(state.day(1).task_list), 1)
        self.assertEqual(state.day(1).task_list[0].title, 'My task')
        self.assertEqual(len(state.day(1).task_list[0].children), 1)
        self.assertEqual(len(state.day(2).task_list), 0)

    # ── Deletion ──────────────────────────────────────────────────────────────

    def test_D_deletes_root_task(self):
        # cursor starts at col=2 (Wednesday), row=0 (My task); D removes it
        state, col, row = asyncio.run(self._inspect(['D']))
        self.assertEqual(len(state.day(2).task_list), 0)
        self.assertEqual(row, -1)  # clamped to -1 when day is empty

    def test_D_on_subtask_removes_only_subtask(self):
        # j → row=1 (Sub), D removes Sub but leaves My task
        state, col, row = asyncio.run(self._inspect(['j', 'D']))
        self.assertEqual(col, 2)
        self.assertEqual(row, 0)
        self.assertEqual(len(state.day(2).task_list), 1)
        self.assertEqual(state.day(2).task_list[0].title, 'My task')
        self.assertEqual(state.day(2).task_list[0].children, [])

    def test_D_then_status_change_on_remaining(self):
        # j → Sub, D deletes Sub, cursor clamps to row=0 (My task), i → in progress
        state, col, row = asyncio.run(self._inspect(['j', 'D', 'i']))
        self.assertEqual(state.day(2).task_list[0].status, 'in progress')
        self.assertEqual(state.day(2).task_list[0].children, [])

    def test_carry_skips_started_subtasks(self):
        # Task with a todo sub and a started sub; > should carry only the todo sub.
        with open(os.path.join(self.tmpdir, '2024-01-10.md'), 'w') as f:
            f.write("- [ ] My task\n  - [ ] Todo sub\n  - [~] Started sub\n")
        state, col, row = asyncio.run(self._inspect(['>']))
        # Started sub stays on Wednesday with the parent
        self.assertEqual([c.title for c in state.day(2).task_list[0].children], ['Started sub'])
        # Todo sub is carried to Thursday inside a new wrapper task
        thu = state.day(3).task_list
        self.assertEqual(len(thu), 1)
        self.assertEqual(thu[0].title, 'My task')
        self.assertEqual([c.title for c in thu[0].children], ['Todo sub'])


class TestTaskFormScreen(unittest.TestCase):
    """Pilot-driven tests for TaskFormScreen create/edit/cancel behaviour."""

    async def _run_form(self, task=None, interact=None):
        """Open TaskFormScreen, run interact(pilot), return list of dismissed values."""
        from textual.app import App as _App
        dismissed = []

        class _TestApp(_App):
            async def on_mount(self):
                await self.push_screen(
                    TaskFormScreen(task),
                    lambda r: dismissed.append(r),
                )

        async with _TestApp().run_test(size=(80, 40)) as pilot:
            if interact:
                await interact(pilot)
        return dismissed

    # ── Create mode ───────────────────────────────────────────────────────────

    def test_save_with_title_returns_result(self):
        from textual.widgets import Input

        async def interact(pilot):
            pilot.app.screen.query_one("#title", Input).value = "Buy coffee"
            await pilot.press("ctrl+s")

        dismissed = asyncio.run(self._run_form(interact=interact))
        self.assertEqual(len(dismissed), 1)
        r = dismissed[0]
        self.assertIsInstance(r, TaskFormResult)
        self.assertEqual(r.title, "Buy coffee")
        self.assertEqual(r.status, "todo")
        self.assertIsNone(r.time_start)
        self.assertIsNone(r.time_end)
        self.assertIsNone(r.body)

    def test_empty_title_does_not_dismiss(self):
        async def interact(pilot):
            await pilot.press("ctrl+s")

        dismissed = asyncio.run(self._run_form(interact=interact))
        self.assertEqual(dismissed, [])

    def test_save_captures_status_and_time(self):
        from textual.widgets import Input, Select

        async def interact(pilot):
            screen = pilot.app.screen
            screen.query_one("#title",      Input).value  = "Stand-up"
            screen.query_one("#status",     Select).value = "in progress"
            screen.query_one("#time_start", Input).value  = "9:00"
            screen.query_one("#time_end",   Input).value  = "9:15"
            await pilot.press("ctrl+s")

        dismissed = asyncio.run(self._run_form(interact=interact))
        r = dismissed[0]
        self.assertEqual(r.title,      "Stand-up")
        self.assertEqual(r.status,     "in progress")
        self.assertEqual(r.time_start, "9:00")
        self.assertEqual(r.time_end,   "9:15")

    def test_save_button_works(self):
        from textual.widgets import Input

        async def interact(pilot):
            pilot.app.screen.query_one("#title", Input).value = "Task"
            await pilot.click("#save")

        dismissed = asyncio.run(self._run_form(interact=interact))
        self.assertEqual(dismissed[0].title, "Task")

    # ── Cancel ────────────────────────────────────────────────────────────────

    def test_escape_dismisses_with_none(self):
        dismissed = asyncio.run(self._run_form(
            interact=lambda pilot: pilot.press("escape")
        ))
        self.assertEqual(dismissed, [None])

    def test_cancel_button_dismisses_with_none(self):
        async def interact(pilot):
            await pilot.click("#cancel")

        dismissed = asyncio.run(self._run_form(interact=interact))
        self.assertEqual(dismissed, [None])

    # ── Edit mode (pre-fill) ──────────────────────────────────────────────────

    def test_edit_mode_prefills_title_and_status(self):
        from textual.widgets import Input, Select
        task = Task(title="Old task", status="done", time=None, line_number=1, indent="")
        inspected = {}

        async def interact(pilot):
            screen = pilot.app.screen
            inspected["title"]  = screen.query_one("#title",  Input).value
            inspected["status"] = screen.query_one("#status", Select).value
            await pilot.press("escape")

        asyncio.run(self._run_form(task=task, interact=interact))
        self.assertEqual(inspected["title"],  "Old task")
        self.assertEqual(inspected["status"], "done")

    def test_edit_mode_prefills_time_fields(self):
        from textual.widgets import Input
        task = Task(title="Meeting", status="todo",
                    time=TaskTime(start="9:00", end="10:00"), line_number=1, indent="")
        inspected = {}

        async def interact(pilot):
            screen = pilot.app.screen
            inspected["time_start"] = screen.query_one("#time_start", Input).value
            inspected["time_end"]   = screen.query_one("#time_end",   Input).value
            await pilot.press("escape")

        asyncio.run(self._run_form(task=task, interact=interact))
        self.assertEqual(inspected["time_start"], "9:00")
        self.assertEqual(inspected["time_end"],   "10:00")

    # ── Body (notes) ──────────────────────────────────────────────────────────

    def test_save_captures_body(self):
        from textual.widgets import Input, TextArea

        async def interact(pilot):
            screen = pilot.app.screen
            screen.query_one('#title', Input).value = 'Task'
            screen.query_one('#body', TextArea).text = 'My notes'
            await pilot.press('ctrl+s')

        dismissed = asyncio.run(self._run_form(interact=interact))
        self.assertIsNotNone(dismissed[0])
        self.assertEqual(dismissed[0].body, 'My notes')

    def test_save_with_no_body_returns_none_body(self):
        from textual.widgets import Input

        async def interact(pilot):
            pilot.app.screen.query_one('#title', Input).value = 'Task'
            await pilot.press('ctrl+s')

        dismissed = asyncio.run(self._run_form(interact=interact))
        self.assertIsNone(dismissed[0].body)

    def test_edit_mode_prefills_body_dedented(self):
        from textual.widgets import TextArea
        task = Task(title='Task', status='todo', time=None, line_number=1, indent='',
                    body='    Indented note\n    Another line')
        inspected = {}

        async def interact(pilot):
            inspected['body'] = pilot.app.screen.query_one('#body', TextArea).text
            await pilot.press('escape')

        asyncio.run(self._run_form(task=task, interact=interact))
        self.assertIn('Indented note', inspected['body'])
        self.assertNotIn('    Indented note', inspected['body'])
        self.assertIn('Another line', inspected['body'])
