import unittest

from models.task import Task, TaskTime


class TestTime(unittest.TestCase):
    def test_to_str_start_only(self):
        self.assertEqual(TaskTime(start='9:00').to_str(), '9:00')

    def test_to_str_with_end(self):
        self.assertEqual(TaskTime(start='9:00', end='10:00').to_str(), '9:00-10:00')


class TestToLine(unittest.TestCase):
    def _task(self, **kwargs):
        defaults = dict(title='Do thing', status='todo', time=None, line_number=1, indent='')
        return Task(**{**defaults, **kwargs})

    def test_status_to_line(self):
        cases = [
            ('todo',        '- [ ] Do thing'),
            ('done',        '- [x] Do thing'),
            ('in progress', '- […] Do thing'),
            ('failed',      '- [–] Do thing'),
            ('started',     '- [~] Do thing'),
            ('unknown',     '- [?] Do thing'),
        ]
        for status, expected in cases:
            with self.subTest(status=status):
                self.assertEqual(self._task(status=status).to_line(), expected)

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

    def test_priority_to_line(self):
        cases = [
            ('!',   '- [ ] ! Do thing'),
            ('!!',  '- [ ] !! Do thing'),
            ('!!!', '- [ ] !!! Do thing'),
            (None,  '- [ ] Do thing'),
        ]
        for priority, expected in cases:
            with self.subTest(priority=priority):
                self.assertEqual(self._task(priority=priority).to_line(), expected)

    def test_priority_with_time(self):
        task = self._task(time=TaskTime(start='10:00'), priority='!!')
        self.assertEqual(task.to_line(), '- [ ] 10:00 !! Do thing')


if __name__ == '__main__':
    unittest.main()
