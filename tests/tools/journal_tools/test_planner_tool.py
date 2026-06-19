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
from parser.file_model import RawLine, TaskBlock, serialize
from tools.journal_tools.planner import WeekState, DayCache
from tools.journal_tools.planner.app import PlannerApp
from tools.journal_tools.planner.state import PlannerState
from tools.journal_tools.planner.day_screen import DayGrid
from tools.journal_tools.planner.save_dialog import SaveDialog
from tools.journal_tools.planner.task_form_screen import TaskFormScreen, TaskFormResult
from tools.journal_tools.planner.week_screen import WeekGrid
from tools.journal_tools.planner.weekly import (
    append_block, cache_has_changes, remove_block, sort_timed_nodes, task_to_block,
)

JOURNAL_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'journal')
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'planner')


@pytest.mark.integration


class TestWeekCacheChanges(unittest.TestCase):

    def _make_cache(self, blocks):
        nodes = list(blocks)
        return {
            '2024-01-15': DayCache(
                file_path=None,
                nodes=nodes,
                original_content=serialize(nodes),
            )
        }

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
        parent.status = 'done'
        cache['2024-01-15'].find_block(parent).refresh_header()
        self.assertTrue(cache_has_changes(cache))

    def test_subtask_status_change_detected(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        child_block = task_to_block(child)
        parent_block = task_to_block(parent, subtask_blocks=[child_block])
        cache = self._make_cache([parent_block])
        child.status = 'done'
        cache['2024-01-15'].find_block(child).refresh_header()
        self.assertTrue(cache_has_changes(cache))


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
        state.days[key].nodes.append(task_to_block(new))
        self.assertEqual(len(state.days[key].task_list), 3)
        state.reload_day_by_key(key)
        self.assertEqual(len(state.days[key].task_list), 2)
        self.assertNotIn('Ephemeral', [b.task.title for b in state.days[key].task_list])

    def test_reload_refreshes_original_content(self):
        state = PlannerState(self.tmpdir)
        key = self.date.isoformat()
        state.load_day(self.date)
        len_before = len(state.days[key].original_content)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write("- [ ] Task C\n")
        state.reload_day_by_key(key)
        self.assertGreater(len(state.days[key].original_content), len_before)

    def test_task_body_dedented_on_load(self):
        # File has "    Some notes" (raw indented); block.nodes RawLines must dedent
        # so TaskFormScreen shows unindented text and round-trip doesn't mark dirty.
        import textwrap
        state = PlannerState(self.tmpdir)
        day = state.load_day(self.date)
        block_a = day.task_list[0]
        body_lines = [n.raw.rstrip('\n') for n in block_a.nodes if isinstance(n, RawLine)]
        body_str = textwrap.dedent('\n'.join(body_lines)).strip()
        self.assertEqual(body_str, 'Some notes')



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

    def test_week_carry_subtask_notes(self):
        # Regression: body text on a carried subtask was dropped from the destination
        # and left as orphaned lines in the source.
        self._run_fixture('week_carry_subtask_notes')

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

    def test_week_new_task(self):
        # New task added via 'n' in week view is written to disk on save
        self._run_fixture('week_new_task')

    def test_week_status_change_saved(self):
        # Status change made in week view is written to disk on save
        self._run_fixture('week_status_change_saved')


@pytest.mark.integration
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
        self.assertEqual(timed[0].task.time.start, minutes_to_time(540 + self.STEP_M))
        self.assertEqual(timed[0].task.time.end,   minutes_to_time(600 + self.STEP_M))

    def test_shift_left(self):
        timed, _ = asyncio.run(self._inspect(['h']))
        self.assertEqual(timed[0].task.time.start, minutes_to_time(540 - self.STEP_M))
        self.assertEqual(timed[0].task.time.end,   minutes_to_time(600 - self.STEP_M))

    def test_shift_clamps_at_zero(self):
        presses = 540 // self.STEP_M + 5
        timed, _ = asyncio.run(self._inspect(['h'] * presses))
        self.assertEqual(timed[0].task.time.start, '0:00')
        self.assertEqual(timed[0].task.time.end,   minutes_to_time(60))

    def test_extend_end_time(self):
        timed, _ = asyncio.run(self._inspect(['L']))
        self.assertEqual(timed[0].task.time.start, '9:00')
        self.assertEqual(timed[0].task.time.end,   minutes_to_time(600 + self.STEP_M))

    def test_shrink_end_time(self):
        timed, _ = asyncio.run(self._inspect(['H']))
        self.assertEqual(timed[0].task.time.start, '9:00')
        self.assertEqual(timed[0].task.time.end,   minutes_to_time(600 - self.STEP_M))

    def test_shrink_fuses_at_minimum_duration(self):
        # Meeting is 9:00-10:00 = 60 min; 4 presses shrink end to == start → fuse
        presses = 60 // self.STEP_M
        timed, _ = asyncio.run(self._inspect(['H'] * presses))
        self.assertEqual(timed[0].task.time.start, '9:00')
        self.assertIsNone(timed[0].task.time.end)

    def test_extend_creates_end_time_for_start_only_task(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] 9:00 Standup\n")
        timed, _ = asyncio.run(self._inspect(['L']))
        self.assertEqual(timed[0].task.time.start, '9:00')
        self.assertEqual(timed[0].task.time.end,   minutes_to_time(540 + self.STEP_M))

    def test_untimed_task_moves_to_noon(self):
        # j to Buy milk (untimed), l schedules it at noon
        timed, untimed = asyncio.run(self._inspect(['j', 'l']))
        timed_titles = [b.task.title for b in timed]
        self.assertIn('Buy milk', timed_titles)
        milk = next(b for b in timed if b.task.title == 'Buy milk')
        self.assertEqual(milk.task.time.start, '12:00')
        self.assertIsNone(milk.task.time.end)

    def test_extend_creates_end_time_for_untimed_task(self):
        # j to Buy milk, l schedules at noon, L adds end time
        timed, _ = asyncio.run(self._inspect(['j', 'l', 'L']))
        milk = next(b for b in timed if b.task.title == 'Buy milk')
        self.assertEqual(milk.task.time.start, '12:00')
        self.assertEqual(milk.task.time.end, minutes_to_time(720 + self.STEP_M))

    # ── Remove time ───────────────────────────────────────────────────────────

    def test_remove_time_moves_task_to_untimed(self):
        timed, untimed = asyncio.run(self._inspect(['r']))
        self.assertNotIn('Meeting', [b.task.title for b in timed])
        self.assertIn('Meeting', [b.task.title for b in untimed])

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
        self.assertEqual([b.task.title for b in timed], ['Meeting'])
        self.assertEqual([b.task.title for b in untimed], [])

    def test_delete_does_not_persist_without_save(self):
        with open(self.path) as f:
            content_before = f.read()
        asyncio.run(self._drive_quit(['D', 'q'], dialog_response='#no'))
        with open(self.path) as f:
            self.assertEqual(f.read(), content_before)

    async def _change_and_save(self, change_keys):
        """Press change_keys, save with ctrl+s + confirm, return has_changes flag."""
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
            return grid._has_changes()

    def test_save_clears_dirty_flag_after_status_change(self):
        has_chg = asyncio.run(self._change_and_save(['d']))
        self.assertFalse(has_chg)

    def test_save_no_duplicate_on_second_save(self):
        # Regression: with the old line-number model, _new_tasks was not cleared
        # after save, so a second save would append the task again.
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
                return grid._has_changes()

        has_chg = asyncio.run(run())
        self.assertFalse(has_chg)
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

    def test_edit_task_title_persisted_after_save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("- [ ] Original title\n- [ ] Task B\n")

        async def run():
            from textual.widgets import Input
            app = PlannerApp(self.directory, file_path=self.path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press('enter')
                await pilot.pause()
                app.screen.query_one('#title', Input).value = 'Updated title'
                await pilot.press('ctrl+s')
                await pilot.pause()
                await pilot.press('ctrl+s')
                await pilot.pause()
                if isinstance(app.screen, SaveDialog):
                    await pilot.click('#yes')
                    await pilot.pause()

        asyncio.run(run())
        content = self._read()
        self.assertIn('Updated title', content)
        self.assertNotIn('Original title', content)
        self.assertIn('Task B', content)

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
        self.assertEqual(state.day(1).task_list[0].task.title, 'My task')
        child_blocks = [n for n in state.day(1).task_list[0].nodes if isinstance(n, TaskBlock)]
        self.assertEqual(len(child_blocks), 1)
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
        self.assertEqual(state.day(2).task_list[0].task.title, 'My task')
        self.assertEqual([n for n in state.day(2).task_list[0].nodes if isinstance(n, TaskBlock)], [])

    def test_D_then_status_change_on_remaining(self):
        # j → Sub, D deletes Sub, cursor clamps to row=0 (My task), i → in progress
        state, col, row = asyncio.run(self._inspect(['j', 'D', 'i']))
        self.assertEqual(state.day(2).task_list[0].task.status, 'in progress')
        self.assertEqual([n for n in state.day(2).task_list[0].nodes if isinstance(n, TaskBlock)], [])

    def test_carry_skips_started_subtasks(self):
        # Task with a todo sub and a started sub; > should carry only the todo sub.
        with open(os.path.join(self.tmpdir, '2024-01-10.md'), 'w') as f:
            f.write("- [ ] My task\n  - [ ] Todo sub\n  - [~] Started sub\n")
        state, col, row = asyncio.run(self._inspect(['>']))
        # Started sub stays on Wednesday with the parent
        wed_children = [n for n in state.day(2).task_list[0].nodes if isinstance(n, TaskBlock)]
        self.assertEqual([b.task.title for b in wed_children], ['Started sub'])
        # Todo sub is carried to Thursday inside a new wrapper task
        thu = state.day(3).task_list
        self.assertEqual(len(thu), 1)
        self.assertEqual(thu[0].task.title, 'My task')
        thu_children = [n for n in thu[0].nodes if isinstance(n, TaskBlock)]
        self.assertEqual([b.task.title for b in thu_children], ['Todo sub'])

    def test_carry_preserves_subtask_body_in_memory(self):
        # Subtask with body text; body should be present on the carried child in memory.
        with open(os.path.join(self.tmpdir, '2024-01-10.md'), 'w') as f:
            f.write("- [ ] My task\n  - [ ] Sub\n      Sub notes\n")
        state, col, row = asyncio.run(self._inspect(['>']))
        thu = state.day(3).task_list
        self.assertEqual(len(thu), 1)
        thu_children = [n for n in thu[0].nodes if isinstance(n, TaskBlock)]
        self.assertEqual(len(thu_children), 1)
        sub_raw = ''.join(n.raw for n in thu_children[0].nodes if isinstance(n, RawLine))
        self.assertIn('Sub notes', sub_raw)



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
        block = task_to_block(task)
        inspected = {}

        async def interact(pilot):
            screen = pilot.app.screen
            inspected["title"]  = screen.query_one("#title",  Input).value
            inspected["status"] = screen.query_one("#status", Select).value
            await pilot.press("escape")

        asyncio.run(self._run_form(task=block, interact=interact))
        self.assertEqual(inspected["title"],  "Old task")
        self.assertEqual(inspected["status"], "done")

    def test_edit_mode_prefills_time_fields(self):
        from textual.widgets import Input
        task = Task(title="Meeting", status="todo",
                    time=TaskTime(start="9:00", end="10:00"), line_number=1, indent="")
        block = task_to_block(task)
        inspected = {}

        async def interact(pilot):
            screen = pilot.app.screen
            inspected["time_start"] = screen.query_one("#time_start", Input).value
            inspected["time_end"]   = screen.query_one("#time_end",   Input).value
            await pilot.press("escape")

        asyncio.run(self._run_form(task=block, interact=interact))
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
        task = Task(title='Task', status='todo', time=None, line_number=1, indent='')
        block = TaskBlock(
            task=task,
            header=task.to_line() + '\n',
            nodes=[RawLine('    Indented note\n'), RawLine('    Another line\n')],
        )
        inspected = {}

        async def interact(pilot):
            inspected['body'] = pilot.app.screen.query_one('#body', TextArea).text
            await pilot.press('escape')

        asyncio.run(self._run_form(task=block, interact=interact))
        self.assertIn('Indented note', inspected['body'])
        self.assertNotIn('    Indented note', inspected['body'])
        self.assertIn('Another line', inspected['body'])

    # ── Subtasks ──────────────────────────────────────────────────────────────

    def test_subtask_added_to_result(self):
        from textual.widgets import Input
        from tools.journal_tools.planner.task_form_screen import SubtaskList

        async def interact(pilot):
            screen = pilot.app.screen
            screen.query_one('#title', Input).value = 'Parent'
            screen.query_one(SubtaskList).focus()
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            pilot.app.screen.query_one('#title', Input).value = 'Child'
            await pilot.press('ctrl+s')
            await pilot.pause()
            await pilot.press('ctrl+s')

        dismissed = asyncio.run(self._run_form(interact=interact))
        r = dismissed[0]
        self.assertIsNotNone(r)
        self.assertEqual(r.title, 'Parent')
        self.assertEqual(len(r.subtasks), 1)
        self.assertEqual(r.subtasks[0].task.title, 'Child')
        self.assertEqual(r.subtasks[0].task.status, 'todo')

    def test_nested_subtask_in_result(self):
        """Sub-subtask created inside a subtask's form appears in the grandchild slot."""
        from textual.widgets import Input
        from tools.journal_tools.planner.task_form_screen import SubtaskList

        async def interact(pilot):
            screen = pilot.app.screen
            screen.query_one('#title', Input).value = 'Parent'
            screen.query_one(SubtaskList).focus()
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            # child form
            pilot.app.screen.query_one('#title', Input).value = 'Child'
            pilot.app.screen.query_one(SubtaskList).focus()
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            # grandchild form
            pilot.app.screen.query_one('#title', Input).value = 'Grandchild'
            await pilot.press('ctrl+s')
            await pilot.pause()
            # back in child form
            await pilot.press('ctrl+s')
            await pilot.pause()
            # back in parent form
            await pilot.press('ctrl+s')

        dismissed = asyncio.run(self._run_form(interact=interact))
        r = dismissed[0]
        self.assertIsNotNone(r)
        self.assertEqual(len(r.subtasks), 1)
        child = r.subtasks[0]
        self.assertEqual(child.task.title, 'Child')
        child_children = [n for n in child.nodes if isinstance(n, TaskBlock)]
        self.assertEqual(len(child_children), 1)
        self.assertEqual(child_children[0].task.title, 'Grandchild')

    def test_cancel_subtask_not_added(self):
        from textual.widgets import Input
        from tools.journal_tools.planner.task_form_screen import SubtaskList

        async def interact(pilot):
            screen = pilot.app.screen
            screen.query_one('#title', Input).value = 'Parent'
            screen.query_one(SubtaskList).focus()
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            await pilot.press('ctrl+s')

        dismissed = asyncio.run(self._run_form(interact=interact))
        r = dismissed[0]
        self.assertIsNotNone(r)
        self.assertEqual(r.subtasks, [])

    def test_edit_subtask_updates_in_place(self):
        from textual.widgets import Input
        from tools.journal_tools.planner.task_form_screen import SubtaskList

        child_task = Task(title='Original', status='todo', time=None, line_number=-1, indent='  ')
        parent_task = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        child_block = task_to_block(child_task)
        parent_block = task_to_block(parent_task, subtask_blocks=[child_block])

        async def interact(pilot):
            screen = pilot.app.screen
            screen.query_one(SubtaskList).focus()
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            pilot.app.screen.query_one('#title', Input).value = 'Updated'
            await pilot.press('ctrl+s')
            await pilot.pause()
            await pilot.press('ctrl+s')

        dismissed = asyncio.run(self._run_form(task=parent_block, interact=interact))
        r = dismissed[0]
        self.assertIsNotNone(r)
        self.assertEqual(len(r.subtasks), 1)
        self.assertEqual(r.subtasks[0].task.title, 'Updated')

    def test_delete_subtask(self):
        from tools.journal_tools.planner.task_form_screen import SubtaskList

        child_task = Task(title='ToDelete', status='todo', time=None, line_number=-1, indent='  ')
        parent_task = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        child_block = task_to_block(child_task)
        parent_block = task_to_block(parent_task, subtask_blocks=[child_block])

        async def interact(pilot):
            pilot.app.screen.query_one(SubtaskList).focus()
            await pilot.pause()
            await pilot.press('D')
            await pilot.pause()
            await pilot.click('#yes')
            await pilot.pause()
            await pilot.press('ctrl+s')

        dismissed = asyncio.run(self._run_form(task=parent_block, interact=interact))
        r = dismissed[0]
        self.assertIsNotNone(r)
        self.assertEqual(r.subtasks, [])


class TestWeekGridBodySave(unittest.TestCase):
    """Pilot-driven tests for WeekScreen task note detection and save path."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(self.tmpdir, '2024-01-10.md'), 'w', encoding='utf-8') as f:
            f.write("- [ ] Task A\n    Some notes\n- [ ] Task B\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _read(self):
        with open(os.path.join(self.tmpdir, '2024-01-10.md'), encoding='utf-8') as f:
            return f.read()

    def _patch_today(self, week_today='2024-01-10'):
        fixed = datetime.date.fromisoformat(week_today)
        mock_dt = MagicMock()
        mock_dt.date.today.return_value = fixed
        mock_dt.timedelta = datetime.timedelta
        mock_dt.date.fromisoformat = datetime.date.fromisoformat
        return patch('tools.journal_tools.planner.week_screen.datetime', mock_dt)

    def test_edit_note_marks_dirty(self):
        from textual.widgets import TextArea

        async def run():
            with self._patch_today():
                app = PlannerApp(self.tmpdir)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.press('enter')
                    await pilot.pause()
                    pilot.app.screen.query_one('#body', TextArea).text = 'New notes'
                    await pilot.press('ctrl+s')
                    await pilot.pause()
                    grid = pilot.app.screen.query_one(WeekGrid)
                    return cache_has_changes(grid._planner.days)

        self.assertTrue(asyncio.run(run()))

    def test_edit_note_persisted_on_save(self):
        from textual.widgets import TextArea

        async def run():
            with self._patch_today():
                app = PlannerApp(self.tmpdir)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.press('enter')
                    await pilot.pause()
                    pilot.app.screen.query_one('#body', TextArea).text = 'New notes'
                    await pilot.press('ctrl+s')   # save form
                    await pilot.pause()
                    await pilot.press('ctrl+s')   # open save dialog
                    await pilot.pause()
                    if isinstance(pilot.app.screen, SaveDialog):
                        await pilot.click('#yes')
                        await pilot.pause()

        asyncio.run(run())
        content = self._read()
        self.assertIn('New notes', content)
        self.assertNotIn('Some notes', content)
        self.assertIn('Task A', content)

    def test_clear_note_persisted_on_save(self):
        from textual.widgets import TextArea

        async def run():
            with self._patch_today():
                app = PlannerApp(self.tmpdir)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.press('enter')
                    await pilot.pause()
                    pilot.app.screen.query_one('#body', TextArea).text = ''
                    await pilot.press('ctrl+s')   # save form
                    await pilot.pause()
                    await pilot.press('ctrl+s')   # open save dialog
                    await pilot.pause()
                    if isinstance(pilot.app.screen, SaveDialog):
                        await pilot.click('#yes')
                        await pilot.pause()

        asyncio.run(run())
        content = self._read()
        self.assertNotIn('Some notes', content)
        self.assertIn('Task A', content)
        self.assertIn('Task B', content)

    def test_unchanged_note_not_dirty(self):
        """Opening a task form and saving without changes must not mark the cache dirty."""

        async def run():
            with self._patch_today():
                app = PlannerApp(self.tmpdir)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.press('enter')
                    await pilot.pause()
                    await pilot.press('ctrl+s')   # save form with no changes
                    await pilot.pause()
                    grid = pilot.app.screen.query_one(WeekGrid)
                    return cache_has_changes(grid._planner.days)

        self.assertFalse(asyncio.run(run()))


class TestWeekSaveCacheDeleteBlanks(unittest.TestCase):
    """Unit tests for blank line preservation when deleting tasks via save_cache."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, content, date='2024-03-15'):
        path = os.path.join(self.tmpdir, f'{date}.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    def _read(self, date='2024-03-15'):
        with open(os.path.join(self.tmpdir, f'{date}.md'), encoding='utf-8') as f:
            return f.read()

    def _delete_and_save(self, state, block, date=datetime.date(2024, 3, 15)):
        from tools.journal_tools.planner.weekly import save_cache
        day = state.days[date.isoformat()]
        remove_block(day.nodes, block)
        save_cache(state.days, self.tmpdir)

    def test_delete_root_task_preserves_blank_line(self):
        self._write("- [ ] Task A\n\n- [ ] Task B\n")
        state = PlannerState(self.tmpdir)
        state.load_day(datetime.date(2024, 3, 15))
        block_a = state.days['2024-03-15'].task_list[0]
        self._delete_and_save(state, block_a)
        content = self._read()
        self.assertNotIn('Task A', content)
        self.assertIn('Task B', content)
        # blank line was between Task A and Task B; after Task A is removed it
        # becomes a leading blank — verify it was not consumed by the deletion
        self.assertTrue(content.startswith('\n'))

    def test_delete_subtask_preserves_blank_line(self):
        # Mirrors the live regression: a sub-task written by block-rewrite gets a
        # real line_number; deleting it must not consume the blank line that follows.
        self._write("- [ ] Parent\n    - [ ] Sub\n\n- [ ] Task B\n")
        state = PlannerState(self.tmpdir)
        state.load_day(datetime.date(2024, 3, 15))
        parent_block = state.days['2024-03-15'].task_list[0]
        sub_block = [n for n in parent_block.nodes if isinstance(n, TaskBlock)][0]
        self._delete_and_save(state, sub_block)
        content = self._read()
        self.assertNotIn('Sub', content)
        self.assertIn('Parent', content)
        self.assertIn('Task B', content)
        self.assertIn('\n\n', content)


class TestWeekSaveCacheTimedShift(unittest.TestCase):
    """Regression tests for note doubling / task disappearance after shifting
    a timed task into a day that already has timed tasks.

    Setup: Day A has two untimed tasks then a timed 10:00 task with a note.
    Day B has a single timed 11:00 task with a note.  After shifting task A
    to day B, sort_timed_nodes reorders the blocks; a second save_cache call
    must be a no-op (no corruption, no false dirty flag)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Day A: two padding tasks push "Task A" to line 3, body to line 4
        with open(os.path.join(self.tmpdir, '2024-01-09.md'), 'w', encoding='utf-8') as f:
            f.write("- [ ] Task X\n- [ ] Task Y\n- [ ] 10:00 Task A\n  Note for A\n")
        # Day B: single timed task at line 1 with note at line 2
        with open(os.path.join(self.tmpdir, '2024-01-10.md'), 'w', encoding='utf-8') as f:
            f.write("- [ ] 11:00 Task B\n  Note for B\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _read(self, date):
        with open(os.path.join(self.tmpdir, f'{date}.md'), encoding='utf-8') as f:
            return f.read()

    def _shift_and_save(self):
        from tools.journal_tools.planner.weekly import save_cache
        state = PlannerState(self.tmpdir)
        date_a = datetime.date(2024, 1, 9)
        date_b = datetime.date(2024, 1, 10)
        state.load_day(date_a)
        state.load_day(date_b)
        cache_a = state.days[date_a.isoformat()]
        cache_b = state.days[date_b.isoformat()]
        block_a = cache_a.task_list[2]  # TaskBlock for 10:00 Task A
        remove_block(cache_a.nodes, block_a)
        append_block(cache_b.nodes, block_a)
        if block_a.task.time:
            sort_timed_nodes(cache_b.nodes)
        save_cache(state.days, self.tmpdir)
        return state, save_cache

    def test_no_spurious_dirty_flag_after_timed_shift(self):
        """cache_has_changes must be False right after the first save_cache."""
        state, _ = self._shift_and_save()
        self.assertFalse(cache_has_changes(state.days))

    def test_no_data_corruption_on_resave_after_timed_shift(self):
        """Calling save_cache a second time must not double the note or remove task B."""
        state, save_cache = self._shift_and_save()
        save_cache(state.days, self.tmpdir)  # second call — must be a no-op
        content = self._read('2024-01-10')
        self.assertEqual(content.count('Note for A'), 1, "note must not be doubled")
        self.assertIn('Task B', content, "Task B must not disappear")
        self.assertIn('Note for B', content, "Task B's note must not disappear")
