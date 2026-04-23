import tempfile
import os
import unittest

from models.task import Task, TaskTime
from parser.task_parser import TaskParser


def write_temp(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    f.write(content)
    f.close()
    return f.name


class TestStatus(unittest.TestCase):
    def _parse(self, line: str) -> Task:
        path = write_temp(line + '\n')
        try:
            tasks = TaskParser.parse_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(tasks), 1)
        return tasks[0]

    def test_todo_space(self):
        self.assertEqual(self._parse('- [ ] Task').status, 'todo')

    def test_done_lowercase(self):
        self.assertEqual(self._parse('- [x] Task').status, 'done')

    def test_done_uppercase(self):
        self.assertEqual(self._parse('- [X] Task').status, 'done')

    def test_in_progress(self):
        self.assertEqual(self._parse('- […] Task').status, 'in progress')

    def test_failed_dash(self):
        self.assertEqual(self._parse('- [–] Task').status, 'failed')

    def test_started(self):
        self.assertEqual(self._parse('- [~] Task').status, 'started')

    def test_non_task_line_skipped(self):
        path = write_temp('Just a regular line\n')
        try:
            tasks = TaskParser.parse_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(tasks, [])


class TestFields(unittest.TestCase):
    def _parse_first(self, content: str) -> Task:
        path = write_temp(content)
        try:
            tasks = TaskParser.parse_file(path)
        finally:
            os.unlink(path)
        return tasks[0]

    def test_title_extracted(self):
        task = self._parse_first('- [ ] Buy milk\n')
        self.assertEqual(task.title, 'Buy milk')

    def test_title_without_time(self):
        task = self._parse_first('- [x] Write report\n')
        self.assertEqual(task.title, 'Write report')

    def test_time_start_only(self):
        task = self._parse_first('- [ ] 9:00 Meeting\n')
        self.assertIsNotNone(task.time)
        self.assertEqual(task.time.start, '9:00')
        self.assertIsNone(task.time.end)

    def test_time_start_with_colon_separator(self):
        task = self._parse_first('- [ ] 9:00: Meeting\n')
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.title, 'Meeting')

    def test_time_range(self):
        task = self._parse_first('- [ ] 9:00-10:30 Meeting\n')
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.time.end, '10:30')

    def test_time_range_with_colon_separator(self):
        task = self._parse_first('- [ ] 9:00-12:00: Brunch\n')
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.time.end, '12:00')
        self.assertEqual(task.title, 'Brunch')

    def test_no_time(self):
        task = self._parse_first('- [ ] No time task\n')
        self.assertIsNone(task.time)

    def test_indent_two_spaces(self):
        task = self._parse_first('  - [ ] Indented task\n')
        self.assertEqual(task.indent, '  ')

    def test_indent_four_spaces(self):
        task = self._parse_first('    - [ ] Deeply indented\n')
        self.assertEqual(task.indent, '    ')

    def test_indent_tab(self):
        task = self._parse_first('\t- [ ] Tab indented\n')
        self.assertEqual(task.indent, '\t')

    def test_line_number(self):
        content = 'Header\n- [ ] Task on line 2\n'
        task = self._parse_first(content)
        self.assertEqual(task.line_number, 2)

    def test_returns_task_instances(self):
        task = self._parse_first('- [ ] Something\n')
        self.assertIsInstance(task, Task)

    def test_multiple_tasks(self):
        content = '- [ ] First\n- [x] Second\n- […] Third\n'
        path = write_temp(content)
        try:
            tasks = TaskParser.parse_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0].title, 'First')
        self.assertEqual(tasks[1].status, 'done')
        self.assertEqual(tasks[2].status, 'in progress')


class TestRoundtrip(unittest.TestCase):
    """Parsed task serializes back to a line equivalent to the original."""

    def _roundtrip(self, line: str) -> str:
        path = write_temp(line + '\n')
        try:
            tasks = TaskParser.parse_file(path)
        finally:
            os.unlink(path)
        return tasks[0].to_line()

    def test_simple_todo(self):
        self.assertEqual(self._roundtrip('- [ ] Do thing'), '- [ ] Do thing')

    def test_done_with_time_range(self):
        self.assertEqual(
            self._roundtrip('- [x] 9:00-10:00 Meeting'),
            '- [x] 9:00-10:00 Meeting',
        )

    def test_indented_two_spaces(self):
        self.assertEqual(self._roundtrip('  - [ ] Sub-task'), '  - [ ] Sub-task')

    def test_indented_four_spaces(self):
        self.assertEqual(self._roundtrip('    - [ ] Sub-task'), '    - [ ] Sub-task')

    def test_indented_tab(self):
        self.assertEqual(self._roundtrip('\t- [ ] Sub-task'), '\t- [ ] Sub-task')

    def test_colon_separator_normalized(self):
        # The colon after the time is stripped on parse; to_line() omits it
        self.assertEqual(self._roundtrip('- [ ] 9:00-12:00: Brunch'), '- [ ] 9:00-12:00 Brunch')

    def test_colon_separator_start_time_normalized(self):
        self.assertEqual(self._roundtrip('- [ ] 9:00: Meeting'), '- [ ] 9:00 Meeting')


if __name__ == '__main__':
    unittest.main()
