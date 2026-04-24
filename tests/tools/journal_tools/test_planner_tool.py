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
from tools.journal_tools.planner_tool import PlannerTool

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
