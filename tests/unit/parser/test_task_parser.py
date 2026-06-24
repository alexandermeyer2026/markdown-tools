import tempfile
import os
import unittest

import pytest

from models.task import Task, TaskTime
from models.file import parse, TaskBlock


def write_temp(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    f.write(content)
    f.close()
    return f.name


def _flat_tasks(nodes) -> list[Task]:
    result = []
    for node in nodes:
        if isinstance(node, TaskBlock):
            result.append(node.task)
            result.extend(_flat_tasks(node.nodes))
    return result


def _parse_file(content: str) -> list[Task]:
    path = write_temp(content)
    try:
        nodes = parse(path)
        return _flat_tasks(nodes)
    finally:
        os.unlink(path)


class TestStatus(unittest.TestCase):
    def _parse(self, line: str) -> Task:
        tasks = _parse_file(line + '\n')
        self.assertEqual(len(tasks), 1)
        return tasks[0]

    def test_status_parsed(self):
        cases = [
            ('- [ ] Task', 'todo'),
            ('- [x] Task', 'done'),
            ('- [X] Task', 'done'),
            ('- […] Task', 'in progress'),
            ('- [–] Task', 'failed'),
            ('- [~] Task', 'started'),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(self._parse(line).status, expected)

    def test_non_task_line_skipped(self):
        tasks = _parse_file('Just a regular line\n')
        self.assertEqual(tasks, [])


class TestFields(unittest.TestCase):
    def _parse_first(self, content: str) -> Task:
        return _parse_file(content)[0]

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
        tasks = _parse_file(content)
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0].title, 'First')
        self.assertEqual(tasks[1].status, 'done')
        self.assertEqual(tasks[2].status, 'in progress')

    def test_colon_separator_stripped_from_time_range(self):
        task = self._parse_first('- [ ] 9:00-12:00: Brunch\n')
        self.assertEqual(task.time.end, '12:00')
        self.assertEqual(task.title, 'Brunch')

    def test_colon_separator_stripped_from_start_time(self):
        task = self._parse_first('- [ ] 9:00: Meeting\n')
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.title, 'Meeting')

    def test_priority_high(self):
        task = self._parse_first('- [ ] !!! Buy groceries\n')
        self.assertEqual(task.priority, '!!!')
        self.assertEqual(task.title, 'Buy groceries')

    def test_priority_with_time(self):
        task = self._parse_first('- [ ] 10:00 !! Pick up Mike\n')
        self.assertEqual(task.priority, '!!')
        self.assertEqual(task.title, 'Pick up Mike')
        self.assertEqual(task.time.start, '10:00')

    def test_no_priority_is_none(self):
        task = self._parse_first('- [ ] Buy milk\n')
        self.assertIsNone(task.priority)

    def test_tags_parsed(self):
        tasks = _parse_file('- [ ] Task\n  #household #freetime\n')
        self.assertEqual(tasks[0].tags, ['household', 'freetime'])

    def test_no_tags_empty(self):
        task = self._parse_first('- [ ] Task\n')
        self.assertEqual(task.tags, [])


@pytest.mark.integration
class TestNodeTree(unittest.TestCase):
    """Test that parse() builds the correct node tree (body and subtasks in block.nodes)."""

    def _parse_nodes(self, content: str) -> list:
        path = write_temp(content)
        try:
            return parse(path)
        finally:
            os.unlink(path)

    def test_body_in_raw_lines(self):
        nodes = self._parse_nodes('- [ ] Task\n  Some note\n')
        block = nodes[0]
        self.assertIsInstance(block, TaskBlock)
        raw_texts = [n.raw.strip() for n in block.nodes if not isinstance(n, TaskBlock)]
        self.assertIn('Some note', raw_texts)

    def test_subtask_in_child_block(self):
        nodes = self._parse_nodes('- [ ] Parent\n  - [ ] Child\n')
        parent_block = nodes[0]
        self.assertIsInstance(parent_block, TaskBlock)
        child_blocks = [n for n in parent_block.nodes if isinstance(n, TaskBlock)]
        self.assertEqual(len(child_blocks), 1)
        self.assertEqual(child_blocks[0].task.title, 'Child')

    def test_recursive_nesting(self):
        nodes = self._parse_nodes('- [ ] Top\n  - [ ] Mid\n    - [ ] Leaf\n')
        top = nodes[0]
        mid = [n for n in top.nodes if isinstance(n, TaskBlock)][0]
        leaf = [n for n in mid.nodes if isinstance(n, TaskBlock)][0]
        self.assertEqual(top.task.title, 'Top')
        self.assertEqual(mid.task.title, 'Mid')
        self.assertEqual(leaf.task.title, 'Leaf')


if __name__ == '__main__':
    unittest.main()
