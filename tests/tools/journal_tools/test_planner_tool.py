import contextlib
import datetime
import json
import os
import shutil
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from models import Task, TaskTime, minutes_to_time
from parser.task_parser import TaskParser
from tools.journal_tools.planner_tool import PlannerTool, WeekState, DayCache

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
        PlannerTool._save(self.path, self.directory, [task], [],
                          {3: task.to_line()}, [])
        self.assertEqual(self._read(), self.CONTENT)

    def test_task_with_unknown_line_number_not_written(self):
        task = Task(title='Ghost', status='done', time=None, line_number=99, indent='')
        PlannerTool._save(self.path, self.directory, [task], [], {}, [])
        self.assertEqual(self._read(), self.CONTENT)

    def test_backup_created(self):
        PlannerTool._save(self.path, self.directory, [], [], {}, [])
        backup_dir = os.path.join(self.directory, '.backups')
        self.assertTrue(os.path.exists(backup_dir))
        self.assertEqual(len(os.listdir(backup_dir)), 1)

    def test_atomic_write_leaves_no_tmp(self):
        PlannerTool._save(self.path, self.directory, [], [], {}, [])
        self.assertFalse(os.path.exists(self.path + '.tmp'))


@pytest.mark.integration
class TestInteractivePlan(unittest.TestCase):
    CONTENT = (
        "# Journal\n"
        "\n"
        "- [ ] 9:00-10:00 Meeting\n"
        "- [ ] Buy milk\n"
    )
    STEP_M = int(PlannerTool.STEP_SIZE_HOURS * 60)

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        self.tmp.write(self.CONTENT)
        self.tmp.close()
        self.path = self.tmp.name
        self.directory = os.path.dirname(self.path)
        self.tasks = TaskParser.parse_file(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _run(self, keys, inputs=None):
        """Run interactive_plan and return args passed to _save (or {} if not called)."""
        captured = {}

        def capture_save(file_path, directory, timed, untimed, orig, new):
            captured['timed']   = list(timed)
            captured['untimed'] = list(untimed)
            captured['new']     = list(new)

        with patch.object(PlannerTool, 'read_key', side_effect=keys):
            with patch.object(PlannerTool, 'render'):
                with patch('builtins.input', side_effect=inputs or []):
                    with patch.object(PlannerTool, '_save', side_effect=capture_save):
                        PlannerTool.interactive_plan(self.directory, self.path, self.tasks)

        return captured

    def test_quit_no_changes_does_not_save(self):
        result = self._run(['q'])
        self.assertEqual(result, {})

    def test_quit_discard_does_not_save(self):
        result = self._run(['l', 'q'], inputs=['n'])
        self.assertEqual(result, {})

    def test_shift_right(self):
        result = self._run(['l', 'q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, minutes_to_time(540 + self.STEP_M))
        self.assertEqual(task.time.end,   minutes_to_time(600 + self.STEP_M))

    def test_shift_left(self):
        result = self._run(['h', 'q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, minutes_to_time(540 - self.STEP_M))
        self.assertEqual(task.time.end,   minutes_to_time(600 - self.STEP_M))

    def test_shift_clamps_at_zero(self):
        presses = 540 // self.STEP_M + 5  # enough to reach 0:00 from 9:00
        keys = ['h'] * presses + ['q']
        result = self._run(keys, inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, '0:00')
        self.assertEqual(task.time.end, minutes_to_time(60))  # duration preserved

    def test_extend_end_time(self):
        result = self._run(['L', 'q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.time.end, minutes_to_time(600 + self.STEP_M))

    def test_shrink_end_time(self):
        result = self._run(['H', 'q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.time.end, minutes_to_time(600 - self.STEP_M))

    def test_shrink_fuses_at_minimum_duration(self):
        # shrink until end == start → fuses to start-time only (task is 9:00-10:00 = 60 min)
        presses = 60 // self.STEP_M
        result = self._run(['H'] * presses + ['q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, '9:00')
        self.assertIsNone(task.time.end)

    def test_extend_creates_end_time(self):
        # j to untimed task, l to schedule at noon, L to add end time
        result = self._run(['j', 'l', 'L', 'q'], inputs=['y'])
        milk = next(t for t in result['timed'] if t.title == 'Buy milk')
        self.assertEqual(milk.time.start, '12:00')
        self.assertEqual(milk.time.end, minutes_to_time(720 + self.STEP_M))

    def test_untimed_task_moves_to_noon(self):
        result = self._run(['j', 'l', 'q'], inputs=['y'])
        timed_titles = [t.title for t in result['timed']]
        self.assertIn('Buy milk', timed_titles)
        milk = next(t for t in result['timed'] if t.title == 'Buy milk')
        self.assertEqual(milk.time.start, '12:00')

    def test_navigation_does_not_change_tasks(self):
        # j then k returns to first task; l shifts it
        result = self._run(['j', 'k', 'l', 'q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, minutes_to_time(540 + self.STEP_M))

    def test_new_task_added_to_untimed(self):
        result = self._run(['n', 'q'], inputs=['Call dentist', 'y'])
        untimed_titles = [t.title for t in result['untimed']]
        self.assertIn('Call dentist', untimed_titles)

    def test_new_task_empty_title_ignored(self):
        result = self._run(['n', 'q'], inputs=['', 'q'])
        self.assertEqual(result, {})

    def test_remove_time_moves_task_to_untimed(self):
        result = self._run(['r', 'q'], inputs=['y'])
        timed_titles   = [t.title for t in result['timed']]
        untimed_titles = [t.title for t in result['untimed']]
        self.assertNotIn('Meeting', timed_titles)
        self.assertIn('Meeting', untimed_titles)
        meeting = next(t for t in result['untimed'] if t.title == 'Meeting')
        self.assertIsNone(meeting.time)

    def test_remove_time_on_untimed_task_is_noop(self):
        result = self._run(['j', 'r', 'q'])
        self.assertEqual(result, {})


class PlannerIntegrationTest(unittest.TestCase):

    def _run_fixture(self, fixture_name):
        fixture_dir = os.path.join(FIXTURES_DIR, fixture_name)
        with open(os.path.join(fixture_dir, 'scenario.json')) as f:
            config = json.load(f)

        args = config['args']
        key_iter = iter(config['keys'])
        save_answer = 'y' if config.get('save', False) else 'n'
        week_today = config.get('week_today')

        tmpdir = tempfile.mkdtemp()
        try:
            for fname in os.listdir(JOURNAL_DIR):
                shutil.copy(os.path.join(JOURNAL_DIR, fname), os.path.join(tmpdir, fname))

            patches = [
                patch.object(PlannerTool, 'read_key', side_effect=lambda: next(key_iter)),
                patch('builtins.input', return_value=save_answer),
                patch('sys.stdout', new=StringIO()),
            ]

            if week_today:
                fixed = datetime.date.fromisoformat(week_today)
                mock_dt = MagicMock()
                mock_dt.date.today.return_value = fixed
                mock_dt.timedelta = datetime.timedelta
                mock_dt.datetime = datetime.datetime
                patches.append(patch('tools.journal_tools.planner_tool.datetime', mock_dt))

            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                PlannerTool.run(args, directory=tmpdir)

            expected_dir = os.path.join(fixture_dir, 'expected')
            for fname in sorted(os.listdir(expected_dir)):
                with open(os.path.join(expected_dir, fname)) as f:
                    expected = f.read()
                with open(os.path.join(tmpdir, fname)) as f:
                    actual = f.read()
                self.assertEqual(actual, expected, f"Mismatch in {fname}")
        finally:
            shutil.rmtree(tmpdir)

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


class TestInteractivePlanSubtasks(unittest.TestCase):
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
        self.directory = os.path.dirname(self.path)
        self.tasks = TaskParser.parse_file(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _run(self, keys, inputs=None):
        captured = {}

        def capture_save(file_path, directory, timed, untimed, orig, new):
            captured['timed']   = list(timed)
            captured['untimed'] = list(untimed)
            captured['new']     = list(new)

        with patch.object(PlannerTool, 'read_key', side_effect=keys):
            with patch.object(PlannerTool, 'render'):
                with patch('builtins.input', side_effect=inputs or []):
                    with patch.object(PlannerTool, '_save', side_effect=capture_save):
                        PlannerTool.interactive_plan(self.directory, self.path, self.tasks)

        return captured

    def test_j_navigates_into_subtask(self):
        # j moves to subtask; d changes its status; save captures the parent with updated child
        result = self._run(['j', 'd', 'q'], inputs=['y'])
        parent = result['untimed'][0]
        self.assertEqual(parent.children[0].status, 'done')

    def test_k_navigates_out_of_subtask(self):
        # j then k returns to parent; status change applies to parent, not subtask
        result = self._run(['j', 'k', 'd', 'q'], inputs=['y'])
        parent = result['untimed'][0]
        self.assertEqual(parent.status, 'done')
        self.assertEqual(parent.children[0].status, 'todo')

    def test_h_on_subtask_is_noop(self):
        # j enters subtask; h should be a no-op (no time assigned, no change recorded)
        result = self._run(['j', 'h', 'q'])
        self.assertEqual(result, {})

    def test_l_on_subtask_is_noop(self):
        result = self._run(['j', 'l', 'q'])
        self.assertEqual(result, {})

    def test_subtask_status_change_detected_as_has_changes(self):
        # Verify _has_changes picks up a subtask status mutation
        parent = self.tasks[0]
        child  = self.tasks[1]
        original_lines = {t.line_number: t.to_line() for t in self.tasks}
        self.assertFalse(PlannerTool._has_changes([parent], [], original_lines, []))
        child.status = 'done'
        self.assertTrue(PlannerTool._has_changes([parent], [], original_lines, []))


class TestInteractiveWeekNavigation(unittest.TestCase):
    MONDAY = datetime.date(2024, 1, 15)  # a known Monday

    def _make_state(self, tasks_by_col=None):
        week_days = [self.MONDAY + datetime.timedelta(days=i) for i in range(7)]
        week_tasks = tasks_by_col if tasks_by_col is not None else [[] for _ in range(7)]
        # Build a minimal cache so cross-week moves can load adjacent days
        cache = {}
        for i, day in enumerate(week_days):
            cache[day.isoformat()] = MagicMock(
                file_path=None, all_tasks=[], task_list=week_tasks[i],
                original_task_list=list(week_tasks[i]), original_lines={},
                new_tasks=[], moved_subtasks=[],
            )
        return WeekState(
            week_days=week_days,
            week_tasks=week_tasks,
            file_paths=[None] * 7,
            all_tasks_per_day=[[] for _ in range(7)],
            directory='/tmp',
            cache=cache,
        )

    def _run(self, keys, start_col=None, tasks_by_col=None, start_row=0):
        state = self._make_state(tasks_by_col=tasks_by_col)
        with patch.object(PlannerTool, 'read_key', side_effect=keys):
            with patch.object(PlannerTool, 'render_week'):
                with patch.object(PlannerTool, '_ensure_day_loaded'):
                    with patch('sys.stdout'):
                        return PlannerTool.interactive_week(state, start_col=start_col, start_row=start_row)

    def test_quit_returns_zero(self):
        self.assertEqual(self._run(['q']), (0, 0))

    def test_h_on_monday_returns_minus_one(self):
        direction, _ = self._run(['h'], start_col=0)
        self.assertEqual(direction, -1)

    def test_l_on_sunday_returns_one(self):
        direction, _ = self._run(['l'], start_col=6)
        self.assertEqual(direction, 1)

    def test_h_not_on_monday_moves_left_stays_in_week(self):
        direction, _ = self._run(['h', 'q'], start_col=2)
        self.assertEqual(direction, 0)

    def test_l_not_on_sunday_moves_right_stays_in_week(self):
        direction, _ = self._run(['l', 'q'], start_col=4)
        self.assertEqual(direction, 0)

    def test_h_on_monday_no_longer_prompts(self):
        task = Task(title='Standup', status='todo', time=None, line_number=1, indent='')
        tasks_by_col = [[task]] + [[] for _ in range(6)]
        # 'd' marks status, then 'h' on Monday navigates without prompting
        direction, _ = self._run(['d', 'h'], start_col=0, tasks_by_col=tasks_by_col)
        self.assertEqual(direction, -1)

    def test_l_on_sunday_no_longer_prompts(self):
        task = Task(title='Standup', status='todo', time=None, line_number=1, indent='')
        tasks_by_col = [[] for _ in range(6)] + [[task]]
        direction, _ = self._run(['d', 'l'], start_col=6, tasks_by_col=tasks_by_col)
        self.assertEqual(direction, 1)

    def test_default_cursor_lands_on_first_day_with_tasks(self):
        task = Task(title='Task', status='todo', time=None, line_number=1, indent='')
        tasks_by_col = [[], [], [task]] + [[] for _ in range(4)]
        # cursor should start at col 2; pressing h twice lands on col 0; one more h switches week
        direction, _ = self._run(['h', 'h', 'h'], tasks_by_col=tasks_by_col)
        self.assertEqual(direction, -1)

    def test_H_at_monday_moves_task_to_prev_week(self):
        task = Task(title='Standup', status='todo', time=None, line_number=1, indent='')
        tasks_by_col = [[task]] + [[] for _ in range(6)]
        state = self._make_state(tasks_by_col=tasks_by_col)
        prev_day = self.MONDAY - datetime.timedelta(days=1)
        prev_cache = MagicMock(file_path=None, task_list=[])
        state.cache[prev_day.isoformat()] = prev_cache

        with patch.object(PlannerTool, 'read_key', side_effect=['H', 'q']):
            with patch.object(PlannerTool, 'render_week'):
                with patch.object(PlannerTool, '_ensure_day_loaded',
                                  side_effect=lambda c, d, dr: c.__setitem__(d.isoformat(), prev_cache)):
                    with patch('sys.stdout'):
                        direction, row = PlannerTool.interactive_week(state, start_col=0)

        self.assertEqual(direction, -1)
        self.assertEqual(state.week_tasks[0], [])   # task removed from Monday
        self.assertEqual(prev_cache.task_list, [task])  # task in prev Sunday
        self.assertEqual(row, 0)                    # cursor at first (only) row

    def test_L_at_sunday_moves_task_to_next_week(self):
        task = Task(title='Standup', status='todo', time=None, line_number=1, indent='')
        tasks_by_col = [[] for _ in range(6)] + [[task]]
        state = self._make_state(tasks_by_col=tasks_by_col)
        next_day = self.MONDAY + datetime.timedelta(days=7)
        next_cache = MagicMock(file_path=None, task_list=[])
        state.cache[next_day.isoformat()] = next_cache

        with patch.object(PlannerTool, 'read_key', side_effect=['L', 'q']):
            with patch.object(PlannerTool, 'render_week'):
                with patch.object(PlannerTool, '_ensure_day_loaded',
                                  side_effect=lambda c, d, dr: c.__setitem__(d.isoformat(), next_cache)):
                    with patch('sys.stdout'):
                        direction, row = PlannerTool.interactive_week(state, start_col=6)

        self.assertEqual(direction, 1)
        self.assertEqual(state.week_tasks[6], [])   # task removed from Sunday
        self.assertEqual(next_cache.task_list, [task])  # task in next Monday
        self.assertEqual(row, 0)

    def test_j_enters_subtask_and_d_marks_it_done(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='',
                      children=[child])
        child.parent = parent
        tasks_by_col = [[parent]] + [[] for _ in range(6)]
        self._run(['j', 'd', 'q'], start_col=0, tasks_by_col=tasks_by_col)
        self.assertEqual(child.status, 'done')
        self.assertEqual(parent.status, 'todo')

    def test_H_on_subtask_moves_root_parent(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='',
                      children=[child])
        child.parent = parent
        tasks_by_col = [[] for _ in range(7)]
        tasks_by_col[1] = [parent]
        # cursor starts at row 1 (subtask); H should move the root parent
        self._run(['H', 'q'], start_col=1, tasks_by_col=tasks_by_col, start_row=1)
        self.assertEqual(tasks_by_col[0], [parent])
        self.assertEqual(tasks_by_col[1], [])

    def test_carry_forward_removes_unfinished_subtasks_from_parent(self):
        child_done = Task(title='Sub done', status='done', time=None, line_number=2, indent='  ')
        child_todo = Task(title='Sub todo', status='todo', time=None, line_number=3, indent='  ')
        parent = Task(title='My task', status='todo', time=None, line_number=1, indent='',
                      children=[child_done, child_todo])
        child_done.parent = parent
        child_todo.parent = parent
        tasks_by_col = [[parent]] + [[] for _ in range(6)]
        state = self._make_state(tasks_by_col=tasks_by_col)

        with patch.object(PlannerTool, 'read_key', side_effect=['>', 'q']):
            with patch.object(PlannerTool, 'render_week'):
                with patch.object(PlannerTool, '_ensure_day_loaded'):
                    PlannerTool.interactive_week(state, start_col=0)

        self.assertEqual(parent.children, [child_done])

    def test_carry_forward_adds_new_task_to_tomorrow(self):
        child_done = Task(title='Sub done', status='done', time=None, line_number=2, indent='  ')
        child_todo = Task(title='Sub todo', status='todo', time=None, line_number=3, indent='  ')
        parent = Task(title='My task', status='todo', time=None, line_number=1, indent='',
                      children=[child_done, child_todo])
        child_done.parent = parent
        child_todo.parent = parent
        tasks_by_col = [[parent]] + [[] for _ in range(6)]
        state = self._make_state(tasks_by_col=tasks_by_col)

        tuesday_key = (self.MONDAY + datetime.timedelta(days=1)).isoformat()

        with patch.object(PlannerTool, 'read_key', side_effect=['>', 'q']):
            with patch.object(PlannerTool, 'render_week'):
                with patch.object(PlannerTool, '_ensure_day_loaded'):
                    PlannerTool.interactive_week(state, start_col=0)

        tuesday_tasks = state.cache[tuesday_key].task_list
        self.assertEqual(len(tuesday_tasks), 1)
        new_task = tuesday_tasks[0]
        self.assertEqual(new_task.title, 'My task')
        self.assertEqual(new_task.line_number, -1)
        self.assertEqual(len(new_task.children), 1)
        self.assertIs(new_task.children[0], child_todo)

    def test_carry_forward_noop_when_all_subtasks_done(self):
        child_done = Task(title='Sub done', status='done', time=None, line_number=2, indent='  ')
        parent = Task(title='My task', status='todo', time=None, line_number=1, indent='',
                      children=[child_done])
        child_done.parent = parent
        tasks_by_col = [[parent]] + [[] for _ in range(6)]
        state = self._make_state(tasks_by_col=tasks_by_col)

        tuesday_key = (self.MONDAY + datetime.timedelta(days=1)).isoformat()

        with patch.object(PlannerTool, 'read_key', side_effect=['>', 'q']):
            with patch.object(PlannerTool, 'render_week'):
                with patch.object(PlannerTool, '_ensure_day_loaded'):
                    PlannerTool.interactive_week(state, start_col=0)

        self.assertEqual(parent.children, [child_done])
        self.assertEqual(state.cache[tuesday_key].task_list, [])


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
        self.assertFalse(PlannerTool._cache_has_changes(cache))

    def test_parent_status_change_detected(self):
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='')
        cache = self._make_cache([parent])
        parent.status = 'done'
        self.assertTrue(PlannerTool._cache_has_changes(cache))

    def test_subtask_status_change_detected(self):
        child = Task(title='Sub', status='todo', time=None, line_number=2, indent='  ')
        parent = Task(title='Parent', status='todo', time=None, line_number=1, indent='',
                      children=[child])
        child.parent = parent
        cache = self._make_cache([parent, child])
        child.status = 'done'
        self.assertTrue(PlannerTool._cache_has_changes(cache))
