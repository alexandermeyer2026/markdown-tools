import os
import tempfile
import unittest
from unittest.mock import patch

import pytest

from models.task import Task, TaskTime
from parser.task_parser import TaskParser
from tools.journal_tools.planner_tool import PlannerTool


class TestGetMinutes(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(PlannerTool.get_minutes('9:00'), 540)

    def test_midnight(self):
        self.assertEqual(PlannerTool.get_minutes('0:00'), 0)

    def test_half_hour(self):
        self.assertEqual(PlannerTool.get_minutes('9:30'), 570)

    def test_end_of_day(self):
        self.assertEqual(PlannerTool.get_minutes('23:30'), 1410)


class TestMinutesToTime(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(PlannerTool.minutes_to_time(540), '9:00')

    def test_midnight(self):
        self.assertEqual(PlannerTool.minutes_to_time(0), '0:00')

    def test_half_hour(self):
        self.assertEqual(PlannerTool.minutes_to_time(570), '9:30')

    def test_clamps_below_zero(self):
        self.assertEqual(PlannerTool.minutes_to_time(-1), '0:00')

    def test_midnight_end(self):
        self.assertEqual(PlannerTool.minutes_to_time(24 * 60), '24:00')


class TestHasChanges(unittest.TestCase):
    def _task(self, **kwargs):
        defaults = dict(title='Task', status='todo', time=None, line_number=1, indent='')
        return Task(**{**defaults, **kwargs})

    def test_no_changes(self):
        task = self._task(title='Buy milk')
        self.assertFalse(PlannerTool._has_changes([task], [], {1: task.to_line()}, []))

    def test_modified_task(self):
        task = self._task(title='Buy milk', time=TaskTime(start='9:00'))
        self.assertTrue(PlannerTool._has_changes([task], [], {1: '- [ ] Buy milk'}, []))

    def test_new_task(self):
        new = self._task(line_number=-1)
        self.assertTrue(PlannerTool._has_changes([], [], {}, [new]))

    def test_unknown_line_number(self):
        task = self._task(line_number=99)
        self.assertFalse(PlannerTool._has_changes([task], [], {}, []))


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

    def test_modified_task_written(self):
        task = Task(title='Meeting', status='done',
                    time=TaskTime(start='9:00', end='10:00'), line_number=3, indent='')
        PlannerTool._save(self.path, self.directory, [task], [],
                          {3: '- [ ] 9:00-10:00 Meeting'}, [])
        self.assertIn('- [x] 9:00-10:00 Meeting', self._read())

    def test_unchanged_task_not_touched(self):
        task = Task(title='Meeting', status='todo',
                    time=TaskTime(start='9:00', end='10:00'), line_number=3, indent='')
        PlannerTool._save(self.path, self.directory, [task], [],
                          {3: task.to_line()}, [])
        self.assertEqual(self._read(), self.CONTENT)

    def test_new_task_appended(self):
        new = Task(title='Call dentist', status='todo', time=None, line_number=-1, indent='')
        PlannerTool._save(self.path, self.directory, [], [], {}, [new])
        lines = self._read().splitlines()
        self.assertEqual(lines[-1], '- [ ] Call dentist')

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
        self.assertEqual(task.time.start, PlannerTool.minutes_to_time(540 + self.STEP_M))
        self.assertEqual(task.time.end,   PlannerTool.minutes_to_time(600 + self.STEP_M))

    def test_shift_left(self):
        result = self._run(['h', 'q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, PlannerTool.minutes_to_time(540 - self.STEP_M))
        self.assertEqual(task.time.end,   PlannerTool.minutes_to_time(600 - self.STEP_M))

    def test_shift_clamps_at_zero(self):
        presses = 540 // self.STEP_M + 5  # enough to reach 0:00 from 9:00
        keys = ['h'] * presses + ['q']
        result = self._run(keys, inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, '0:00')
        self.assertEqual(task.time.end, PlannerTool.minutes_to_time(60))  # duration preserved

    def test_extend_end_time(self):
        result = self._run(['L', 'q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.time.end, PlannerTool.minutes_to_time(600 + self.STEP_M))

    def test_shrink_end_time(self):
        result = self._run(['H', 'q'], inputs=['y'])
        task = result['timed'][0]
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.time.end, PlannerTool.minutes_to_time(600 - self.STEP_M))

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
        self.assertEqual(milk.time.end, PlannerTool.minutes_to_time(720 + self.STEP_M))

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
        self.assertEqual(task.time.start, PlannerTool.minutes_to_time(540 + self.STEP_M))

    def test_new_task_added_to_untimed(self):
        result = self._run(['n', 'q'], inputs=['Call dentist', 'y'])
        untimed_titles = [t.title for t in result['untimed']]
        self.assertIn('Call dentist', untimed_titles)

    def test_new_task_empty_title_ignored(self):
        result = self._run(['n', 'q'], inputs=['', 'q'])
        self.assertEqual(result, {})
