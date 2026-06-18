import tempfile
import os
import unittest

import pytest

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

    def test_colon_separator_stripped_from_time_range(self):
        task = self._parse_first('- [ ] 9:00-12:00: Brunch\n')
        self.assertEqual(task.time.end, '12:00')
        self.assertEqual(task.title, 'Brunch')

    def test_colon_separator_stripped_from_start_time(self):
        task = self._parse_first('- [ ] 9:00: Meeting\n')
        self.assertEqual(task.time.start, '9:00')
        self.assertEqual(task.title, 'Meeting')


def _parse_block(content: str) -> list[Task]:
    path = write_temp(content)
    try:
        return TaskParser.parse_file(path)
    finally:
        os.unlink(path)


@pytest.mark.integration
class TestTaskBody(unittest.TestCase):
    def test_single_body_line(self):
        tasks = _parse_block(
            '- [ ] Task\n'
            '  Some note\n'
        )
        self.assertEqual(tasks[0].body, '  Some note')

    def test_multiline_body(self):
        tasks = _parse_block(
            '- [ ] Task\n'
            '  First note\n'
            '  Second note\n'
        )
        self.assertEqual(tasks[0].body, '  First note\n  Second note')

    def test_no_body_when_no_indented_lines(self):
        tasks = _parse_block('- [ ] Task\n')
        self.assertIsNone(tasks[0].body)

    def test_body_does_not_bleed_into_next_sibling(self):
        tasks = _parse_block(
            '- [ ] First\n'
            '  Body of first\n'
            '- [ ] Second\n'
        )
        self.assertEqual(tasks[0].body, '  Body of first')
        self.assertIsNone(tasks[1].body)

    def test_non_indented_line_is_not_body(self):
        tasks = _parse_block(
            '- [ ] Task\n'
            'Not indented\n'
        )
        self.assertIsNone(tasks[0].body)


@pytest.mark.integration
class TestSubtaskRelationships(unittest.TestCase):
    def test_top_level_task_has_no_parent(self):
        tasks = _parse_block('- [ ] Top level\n')
        self.assertIsNone(tasks[0].parent)

    def test_top_level_task_has_empty_children(self):
        tasks = _parse_block('- [ ] Top level\n')
        self.assertEqual(tasks[0].children, [])

    def test_subtask_parent_set(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '  - [ ] Child\n'
        )
        parent, child = tasks
        self.assertIs(child.parent, parent)

    def test_subtask_appears_in_parent_children(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '  - [ ] Child\n'
        )
        parent, child = tasks
        self.assertIn(child, parent.children)

    def test_sibling_subtasks_share_parent(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '  - [ ] Child 1\n'
            '  - [ ] Child 2\n'
        )
        parent, child1, child2 = tasks
        self.assertIs(child1.parent, parent)
        self.assertIs(child2.parent, parent)
        self.assertEqual(parent.children, [child1, child2])

    def test_recursive_nesting(self):
        tasks = _parse_block(
            '- [ ] Top\n'
            '  - [ ] Mid\n'
            '    - [ ] Leaf\n'
        )
        top, mid, leaf = tasks
        self.assertIsNone(top.parent)
        self.assertIs(mid.parent, top)
        self.assertIs(leaf.parent, mid)

    def test_grandchild_accessible_via_children(self):
        tasks = _parse_block(
            '- [ ] Top\n'
            '  - [ ] Mid\n'
            '    - [ ] Leaf\n'
        )
        top, mid, leaf = tasks
        self.assertIs(top.children[0].children[0], leaf)


@pytest.mark.integration
class TestInterleavedBodyAndSubtasks(unittest.TestCase):
    def test_body_before_subtask(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '  A note\n'
            '  - [ ] Child\n'
        )
        parent, child = tasks
        self.assertEqual(parent.body, '  A note')
        self.assertIs(child.parent, parent)

    def test_body_after_subtask(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '  - [ ] Child\n'
            '  A trailing note\n'
        )
        parent, child = tasks
        self.assertEqual(parent.body, '  A trailing note')

    def test_body_interleaved_between_subtasks(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '  First note\n'
            '  - [ ] Child 1\n'
            '  Middle note\n'
            '  - [ ] Child 2\n'
            '  Last note\n'
        )
        parent, child1, child2 = tasks
        self.assertEqual(parent.body, '  First note\n  Middle note\n  Last note')
        self.assertEqual(parent.children, [child1, child2])

    def test_subtask_with_own_body(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '  - [ ] Child\n'
            '    Child note\n'
        )
        parent, child = tasks
        self.assertIsNone(parent.body)
        self.assertEqual(child.body, '    Child note')

    def test_subtask_with_body_and_grandchild(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '  - [ ] Child\n'
            '    Child note\n'
            '    - [ ] Grandchild\n'
        )
        parent, child, grandchild = tasks
        self.assertEqual(child.body, '    Child note')
        self.assertIs(grandchild.parent, child)

    def test_complex_nested_block(self):
        tasks = _parse_block(
            '- [ ] Top\n'
            '  Top note\n'
            '  - [ ] Mid\n'
            '    Mid note\n'
            '    - [ ] Leaf\n'
            '  Another top note\n'
        )
        top, mid, leaf = tasks
        self.assertEqual(top.body, '  Top note\n  Another top note')
        self.assertEqual(mid.body, '    Mid note')
        self.assertIsNone(leaf.body)
        self.assertIs(mid.parent, top)
        self.assertIs(leaf.parent, mid)

    def test_poorly_formatted_block(self):
        tasks = _parse_block(
            '- [ ] Parent\n'
            '    Parent note\n'
            '  - [ ] Child 1\n'
            '    Child 1 note\n'
            '      Child 1 note\n'
            ' - [ ] Child 2\n'
            '  - [ ] Grandchild\n'
        )
        parent, child1, child2, grandchild = tasks
        self.assertEqual(parent.body, '    Parent note')
        self.assertEqual(parent.children, [child1, child2])
        self.assertEqual(child1.body, '    Child 1 note\n      Child 1 note')
        self.assertEqual(child2.children, [grandchild])
        self.assertIs(grandchild.parent, child2)


if __name__ == '__main__':
    unittest.main()
