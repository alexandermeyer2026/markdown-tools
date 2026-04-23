import os
import tempfile
import unittest

from parser.task_parser import TaskParser
from os_utils.file_writer import FileWriter


def write_temp(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    f.write(content)
    f.close()
    return f.name


def read_file(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestCutTask(unittest.TestCase):

    def _cut(self, content: str, task_index: int):
        path = write_temp(content)
        try:
            tasks = TaskParser.parse_file(path)
            block = FileWriter.cut_task(path, tasks[task_index], tasks)
            remaining = read_file(path)
        finally:
            os.unlink(path)
        return block, remaining

    def test_single_task_block_returned(self):
        block, _ = self._cut('- [ ] Task A\n', 0)
        self.assertEqual(block, ['- [ ] Task A\n'])

    def test_single_task_file_emptied(self):
        _, remaining = self._cut('- [ ] Task A\n', 0)
        self.assertEqual(remaining, '')

    def test_first_of_two_tasks(self):
        block, remaining = self._cut('- [ ] Task A\n- [ ] Task B\n', 0)
        self.assertEqual(block, ['- [ ] Task A\n'])
        self.assertEqual(remaining, '- [ ] Task B\n')

    def test_last_of_two_tasks(self):
        block, remaining = self._cut('- [ ] Task A\n- [ ] Task B\n', 1)
        self.assertEqual(block, ['- [ ] Task B\n'])
        self.assertEqual(remaining, '- [ ] Task A\n')

    def test_middle_task(self):
        content = '- [ ] A\n- [ ] B\n- [ ] C\n'
        block, remaining = self._cut(content, 1)
        self.assertEqual(block, ['- [ ] B\n'])
        self.assertEqual(remaining, '- [ ] A\n- [ ] C\n')

    def test_task_with_body(self):
        content = '- [ ] Task A\n  Body line\n- [ ] Task B\n'
        block, remaining = self._cut(content, 0)
        self.assertEqual(block, ['- [ ] Task A\n', '  Body line\n'])
        self.assertEqual(remaining, '- [ ] Task B\n')

    def test_task_with_subtasks(self):
        content = '- [ ] Parent\n  - [ ] Child\n- [ ] Other\n'
        block, remaining = self._cut(content, 0)
        self.assertEqual(block, ['- [ ] Parent\n', '  - [ ] Child\n'])
        self.assertEqual(remaining, '- [ ] Other\n')

    def test_task_with_body_and_subtasks(self):
        content = (
            '- [ ] Parent\n'
            '  A note\n'
            '  - [ ] Child\n'
            '    Child note\n'
            '- [ ] Sibling\n'
        )
        block, remaining = self._cut(content, 0)
        self.assertEqual(block, [
            '- [ ] Parent\n',
            '  A note\n',
            '  - [ ] Child\n',
            '    Child note\n',
        ])
        self.assertEqual(remaining, '- [ ] Sibling\n')

    def test_non_task_content_before_is_untouched(self):
        content = '# Heading\n- [ ] Task A\n- [ ] Task B\n'
        block, remaining = self._cut(content, 0)
        self.assertEqual(block, ['- [ ] Task A\n'])
        self.assertEqual(remaining, '# Heading\n- [ ] Task B\n')

    def test_non_task_content_after_last_task_is_untouched(self):
        content = '- [ ] Task A\n- [ ] Task B\nSome trailing note\n'
        block, remaining = self._cut(content, 1)
        self.assertEqual(block, ['- [ ] Task B\n', 'Some trailing note\n'])
        self.assertEqual(remaining, '- [ ] Task A\n')

    def test_cut_subtask_only(self):
        content = '- [ ] Parent\n  - [ ] Child 1\n  - [ ] Child 2\n'
        path = write_temp(content)
        try:
            tasks = TaskParser.parse_file(path)
            child1 = next(t for t in tasks if t.title == 'Child 1')
            block = FileWriter.cut_task(path, child1, tasks)
            remaining = read_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(block, ['  - [ ] Child 1\n'])
        self.assertEqual(remaining, '- [ ] Parent\n  - [ ] Child 2\n')


class TestPasteTask(unittest.TestCase):

    def test_appends_to_file(self):
        path = write_temp('- [ ] Existing\n')
        try:
            FileWriter.paste_task(path, ['- [ ] New\n'])
            self.assertEqual(read_file(path), '- [ ] Existing\n- [ ] New\n')
        finally:
            os.unlink(path)

    def test_appends_multiline_block(self):
        path = write_temp('- [ ] Existing\n')
        try:
            FileWriter.paste_task(path, ['- [ ] Parent\n', '  - [ ] Child\n'])
            self.assertEqual(read_file(path), '- [ ] Existing\n- [ ] Parent\n  - [ ] Child\n')
        finally:
            os.unlink(path)

    def test_file_without_trailing_newline(self):
        path = write_temp('- [ ] Existing')
        try:
            FileWriter.paste_task(path, ['- [ ] New\n'])
            self.assertEqual(read_file(path), '- [ ] Existing\n- [ ] New\n')
        finally:
            os.unlink(path)

    def test_paste_to_empty_file(self):
        path = write_temp('')
        try:
            FileWriter.paste_task(path, ['- [ ] New\n'])
            self.assertEqual(read_file(path), '- [ ] New\n')
        finally:
            os.unlink(path)


class TestMoveTask(unittest.TestCase):

    def test_task_leaves_source(self):
        src = write_temp('- [ ] Task A\n- [ ] Task B\n')
        dst = write_temp('- [ ] Task C\n')
        try:
            tasks = TaskParser.parse_file(src)
            task_a = next(t for t in tasks if t.title == 'Task A')
            FileWriter.move_task(src, dst, task_a, tasks)
            self.assertEqual(read_file(src), '- [ ] Task B\n')
        finally:
            os.unlink(src)
            os.unlink(dst)

    def test_task_arrives_at_destination(self):
        src = write_temp('- [ ] Task A\n- [ ] Task B\n')
        dst = write_temp('- [ ] Task C\n')
        try:
            tasks = TaskParser.parse_file(src)
            task_a = next(t for t in tasks if t.title == 'Task A')
            FileWriter.move_task(src, dst, task_a, tasks)
            self.assertEqual(read_file(dst), '- [ ] Task C\n- [ ] Task A\n')
        finally:
            os.unlink(src)
            os.unlink(dst)

    def test_move_preserves_block(self):
        src = write_temp('- [ ] Parent\n  - [ ] Child\n')
        dst = write_temp('- [ ] Other\n')
        try:
            tasks = TaskParser.parse_file(src)
            parent = next(t for t in tasks if t.title == 'Parent')
            FileWriter.move_task(src, dst, parent, tasks)
            self.assertIn('- [ ] Parent\n', read_file(dst))
            self.assertIn('  - [ ] Child\n', read_file(dst))
            self.assertEqual(read_file(src), '')
        finally:
            os.unlink(src)
            os.unlink(dst)


class TestSortTimedTasks(unittest.TestCase):

    def _sort(self, content: str) -> str:
        path = write_temp(content)
        try:
            tasks = TaskParser.parse_file(path)
            timed = [t for t in tasks if t.time is not None]
            FileWriter.sort_timed_tasks(path, timed, tasks)
            return read_file(path)
        finally:
            os.unlink(path)

    def test_two_tasks_out_of_order(self):
        content = '- [ ] 10:00 B\n- [ ] 09:00 A\n'
        self.assertEqual(self._sort(content), '- [ ] 09:00 A\n- [ ] 10:00 B\n')

    def test_already_sorted_unchanged(self):
        content = '- [ ] 09:00 A\n- [ ] 10:00 B\n'
        self.assertEqual(self._sort(content), content)

    def test_three_tasks_sorted(self):
        content = '- [ ] 11:00 C\n- [ ] 09:00 A\n- [ ] 10:00 B\n'
        self.assertEqual(self._sort(content), '- [ ] 09:00 A\n- [ ] 10:00 B\n- [ ] 11:00 C\n')

    def test_heading_before_tasks_preserved(self):
        content = '# Morning\n- [ ] 11:00 Late\n- [ ] 09:00 Early\n'
        self.assertEqual(self._sort(content), '# Morning\n- [ ] 09:00 Early\n- [ ] 11:00 Late\n')

    def test_untimed_task_between_timed_stays_in_place(self):
        content = '- [ ] 11:00 C\n- [ ] No time\n- [ ] 09:00 A\n'
        result = self._sort(content)
        self.assertEqual(result, '- [ ] 09:00 A\n- [ ] No time\n- [ ] 11:00 C\n')

    def test_sort_by_minutes_not_lexicographic(self):
        content = '- [ ] 10:00 B\n- [ ] 9:45 A\n'
        self.assertEqual(self._sort(content), '- [ ] 9:45 A\n- [ ] 10:00 B\n')

    def test_task_with_subtasks_sorted_as_block(self):
        content = (
            '- [ ] 10:00 B\n'
            '  - [ ] Sub-B\n'
            '- [ ] 09:00 A\n'
            '  - [ ] Sub-A\n'
        )
        expected = (
            '- [ ] 09:00 A\n'
            '  - [ ] Sub-A\n'
            '- [ ] 10:00 B\n'
            '  - [ ] Sub-B\n'
        )
        self.assertEqual(self._sort(content), expected)

    def test_timed_subtasks_sorted_within_parent(self):
        content = (
            '- [ ] Parent A\n'
            '  - [ ] 11:00 Late\n'
            '  - [ ] 09:00 Early\n'
            '- [ ] Parent B\n'
            '  - [ ] 08:00 First\n'
        )
        expected = (
            '- [ ] Parent A\n'
            '  - [ ] 09:00 Early\n'
            '  - [ ] 11:00 Late\n'
            '- [ ] Parent B\n'
            '  - [ ] 08:00 First\n'
        )
        self.assertEqual(self._sort(content), expected)

    def test_timed_tasks_from_different_parents_do_not_cross_sort(self):
        content = (
            '- [ ] Parent A\n'
            '  - [ ] 11:00 A-Late\n'
            '- [ ] Parent B\n'
            '  - [ ] 09:00 B-Early\n'
        )
        self.assertEqual(self._sort(content), content)

class TestReindentBlock(unittest.TestCase):

    def test_strips_indent(self):
        block = ['  - [ ] Child\n', '    Body\n']
        result = FileWriter.reindent_block(block, '  ', '')
        self.assertEqual(result, ['- [ ] Child\n', '  Body\n'])

    def test_adds_indent(self):
        block = ['- [ ] Task\n', '  Body\n']
        result = FileWriter.reindent_block(block, '', '  ')
        self.assertEqual(result, ['  - [ ] Task\n', '    Body\n'])

    def test_lines_without_prefix_unchanged(self):
        block = ['- [ ] Task\n', 'no indent here\n']
        result = FileWriter.reindent_block(block, '  ', '')
        self.assertEqual(result[1], 'no indent here\n')

    def test_empty_block(self):
        self.assertEqual(FileWriter.reindent_block([], '  ', ''), [])


if __name__ == '__main__':
    unittest.main()
