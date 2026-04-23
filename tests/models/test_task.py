import unittest

from models.task import Task, TaskTime


class TestTaskTime(unittest.TestCase):
    def test_to_str_start_only(self):
        self.assertEqual(TaskTime(start='9:00').to_str(), '9:00')

    def test_to_str_with_end(self):
        self.assertEqual(TaskTime(start='9:00', end='10:00').to_str(), '9:00-10:00')


class TestTaskToLine(unittest.TestCase):
    def _task(self, **kwargs):
        defaults = dict(title='Do thing', status='todo', time=None, line_number=1, indent='')
        return Task(**{**defaults, **kwargs})

    def test_simple_todo(self):
        task = self._task(title='Do thing', status='todo')
        self.assertEqual(task.to_line(), '- [ ] Do thing')

    def test_done_status(self):
        task = self._task(status='done')
        self.assertEqual(task.to_line(), '- [x] Do thing')

    def test_in_progress_status(self):
        task = self._task(status='in progress')
        self.assertEqual(task.to_line(), '- […] Do thing')

    def test_failed_status(self):
        task = self._task(status='failed')
        self.assertEqual(task.to_line(), '- [–] Do thing')

    def test_started_status(self):
        task = self._task(status='started')
        self.assertEqual(task.to_line(), '- [~] Do thing')

    def test_unknown_status(self):
        task = self._task(status='unknown')
        self.assertEqual(task.to_line(), '- [?] Do thing')

    def test_with_start_time(self):
        task = self._task(time=TaskTime(start='9:00'))
        self.assertEqual(task.to_line(), '- [ ] 9:00 Do thing')

    def test_with_time_range(self):
        task = self._task(time=TaskTime(start='9:00', end='10:00'))
        self.assertEqual(task.to_line(), '- [ ] 9:00-10:00 Do thing')

    def test_with_indent(self):
        task = self._task(indent='  ')
        self.assertEqual(task.to_line(), '  - [ ] Do thing')

    def test_with_indent_and_time(self):
        task = self._task(indent='\t', time=TaskTime(start='8:30', end='9:00'))
        self.assertEqual(task.to_line(), '\t- [ ] 8:30-9:00 Do thing')


if __name__ == '__main__':
    unittest.main()
