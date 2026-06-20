import os
import tempfile
import unittest

import pytest

from parser.file_model import RawLine, TaskBlock, parse, parse_lines, serialize


def write_temp(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    f.write(content)
    f.close()
    return f.name


def roundtrip(content: str) -> str:
    path = write_temp(content)
    try:
        return serialize(parse(path))
    finally:
        os.unlink(path)


def parse_str(content: str) -> list:
    path = write_temp(content)
    try:
        return parse(path)
    finally:
        os.unlink(path)


# ── Round-trip ────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestRoundTrip(unittest.TestCase):

    def test_empty_file(self):
        self.assertEqual(roundtrip(''), '')

    def test_single_task(self):
        c = '- [ ] Task\n'
        self.assertEqual(roundtrip(c), c)

    def test_task_with_body(self):
        c = '- [ ] Task\n  Note\n'
        self.assertEqual(roundtrip(c), c)

    def test_two_tasks_blank_separator(self):
        c = '- [ ] Task A\n\n- [ ] Task B\n'
        self.assertEqual(roundtrip(c), c)

    def test_subtask(self):
        c = '- [ ] Parent\n  - [ ] Child\n'
        self.assertEqual(roundtrip(c), c)

    def test_interleaved_notes_and_subtasks(self):
        c = (
            '- [ ] Parent\n'
            '  First note\n'
            '  - [ ] Child 1\n'
            '  Middle note\n'
            '  - [ ] Child 2\n'
            '  Last note\n'
        )
        self.assertEqual(roundtrip(c), c)

    def test_prose_before_tasks(self):
        c = '# Heading\n\n- [ ] Task\n'
        self.assertEqual(roundtrip(c), c)

    def test_blank_line_within_body(self):
        c = '- [ ] Task\n  Note 1\n\n  Note 2\n'
        self.assertEqual(roundtrip(c), c)

    def test_trailing_blank_line(self):
        c = '- [ ] Task\n\n'
        self.assertEqual(roundtrip(c), c)

    def test_poorly_formatted_indentation(self):
        c = (
            '- [ ] Parent\n'
            '    Parent note\n'
            '  - [ ] Child 1\n'
            '    Child 1 note\n'
            '      Child 1 note\n'
            ' - [ ] Child 2\n'
            '  - [ ] Grandchild\n'
        )
        self.assertEqual(roundtrip(c), c)

    def test_timed_task(self):
        c = '- [ ] 10:00-11:00 Meeting\n'
        self.assertEqual(roundtrip(c), c)

    def test_fixture_files(self):
        fixtures = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'journal')
        for fname in sorted(os.listdir(fixtures)):
            if not fname.endswith('.md'):
                continue
            path = os.path.join(fixtures, fname)
            with open(path, 'r', encoding='utf-8') as f:
                original = f.read()
            self.assertEqual(serialize(parse(path)), original, f'round-trip failed: {fname}')


# ── Structure ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestStructure(unittest.TestCase):

    def test_single_task_is_taskblock(self):
        nodes = parse_str('- [ ] Task\n')
        self.assertEqual(len(nodes), 1)
        self.assertIsInstance(nodes[0], TaskBlock)

    def test_task_title(self):
        nodes = parse_str('- [ ] My title\n')
        self.assertEqual(nodes[0].task.title, 'My title')

    def test_task_status(self):
        nodes = parse_str('- [x] Done\n')
        self.assertEqual(nodes[0].task.status, 'done')

    def test_task_indent(self):
        nodes = parse_str('- [ ] Parent\n  - [ ] Child\n')
        self.assertEqual(nodes[0].task.indent, '')
        self.assertEqual(nodes[0].nodes[0].task.indent, '  ')

    def test_header_exact(self):
        nodes = parse_str('- [x] Done task\n')
        self.assertEqual(nodes[0].header, '- [x] Done task\n')

    def test_body_rawline_exact(self):
        nodes = parse_str('- [ ] Task\n  Note\n')
        self.assertIsInstance(nodes[0].nodes[0], RawLine)
        self.assertEqual(nodes[0].nodes[0].raw, '  Note\n')

    def test_subtask_nested(self):
        nodes = parse_str('- [ ] Parent\n  - [ ] Child\n')
        self.assertIsInstance(nodes[0].nodes[0], TaskBlock)
        self.assertEqual(nodes[0].nodes[0].task.title, 'Child')

    def test_interleaved_order(self):
        nodes = parse_str(
            '- [ ] Parent\n'
            '  First\n'
            '  - [ ] Child\n'
            '  Last\n'
        )
        parent = nodes[0]
        self.assertIsInstance(parent.nodes[0], RawLine)
        self.assertIsInstance(parent.nodes[1], TaskBlock)
        self.assertIsInstance(parent.nodes[2], RawLine)

    def test_blank_between_tasks_in_first_body(self):
        nodes = parse_str('- [ ] A\n\n- [ ] B\n')
        # blank belongs to the preceding task's nodes, not the top-level list
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[0], TaskBlock)
        self.assertEqual(nodes[0].task.title, 'A')
        self.assertEqual(len(nodes[0].nodes), 1)
        self.assertIsInstance(nodes[0].nodes[0], RawLine)
        self.assertEqual(nodes[0].nodes[0].raw, '\n')
        self.assertIsInstance(nodes[1], TaskBlock)
        self.assertEqual(nodes[1].task.title, 'B')

    def test_top_level_prose_rawline(self):
        nodes = parse_str('# Heading\n\n- [ ] Task\n')
        self.assertIsInstance(nodes[0], RawLine)
        self.assertEqual(nodes[0].raw, '# Heading\n')
        self.assertIsInstance(nodes[1], RawLine)
        self.assertEqual(nodes[1].raw, '\n')
        self.assertIsInstance(nodes[2], TaskBlock)

    def test_empty_file_empty_list(self):
        nodes = parse_str('')
        self.assertEqual(nodes, [])

    def test_timed_task_parsed(self):
        nodes = parse_str('- [ ] 09:00-10:00 Meeting\n')
        t = nodes[0].task
        self.assertEqual(t.title, 'Meeting')
        self.assertIsNotNone(t.time)
        self.assertEqual(t.time.start, '09:00')
        self.assertEqual(t.time.end, '10:00')


# ── refresh_header ────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestRefreshHeader(unittest.TestCase):

    def test_refresh_updates_header(self):
        nodes = parse_str('- [ ] Task\n')
        block = nodes[0]
        block.task.status = 'done'
        block.refresh_header()
        self.assertEqual(block.header, '- [x] Task\n')

    def test_serialize_after_refresh(self):
        nodes = parse_str('- [ ] Task\n')
        nodes[0].task.status = 'done'
        nodes[0].refresh_header()
        self.assertEqual(serialize(nodes), '- [x] Task\n')

    def test_refresh_preserves_body(self):
        nodes = parse_str('- [ ] Task\n  Note\n')
        nodes[0].task.status = 'done'
        nodes[0].refresh_header()
        self.assertEqual(serialize(nodes), '- [x] Task\n  Note\n')

    def test_unmodified_header_unchanged(self):
        original = '- [ ] Task\n'
        nodes = parse_str(original)
        # no refresh_header called — header must still be the original line
        self.assertEqual(nodes[0].header, original)


# ── Priority ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestPriority(unittest.TestCase):

    def test_high_priority_parsed(self):
        nodes = parse_str('- [ ] !!! Buy groceries\n')
        self.assertEqual(nodes[0].task.priority, '!!!')
        self.assertEqual(nodes[0].task.title, 'Buy groceries')

    def test_medium_priority_parsed(self):
        nodes = parse_str('- [ ] !! Task\n')
        self.assertEqual(nodes[0].task.priority, '!!')

    def test_low_priority_parsed(self):
        nodes = parse_str('- [ ] ! Task\n')
        self.assertEqual(nodes[0].task.priority, '!')

    def test_priority_with_time(self):
        nodes = parse_str('- [ ] 10:00 !! Pick up Mike\n')
        t = nodes[0].task
        self.assertEqual(t.priority, '!!')
        self.assertEqual(t.title, 'Pick up Mike')
        self.assertEqual(t.time.start, '10:00')

    def test_priority_with_time_range(self):
        nodes = parse_str('- [ ] 13:00-14:00 !!! Meeting\n')
        t = nodes[0].task
        self.assertEqual(t.priority, '!!!')
        self.assertEqual(t.title, 'Meeting')

    def test_no_priority_is_none(self):
        nodes = parse_str('- [ ] Buy milk\n')
        self.assertIsNone(nodes[0].task.priority)

    def test_priority_roundtrip(self):
        for line in [
            '- [ ] !!! Buy groceries\n',
            '- [ ] 10:00 !! Pick up Mike\n',
            '- [ ] 13:00-14:00 !!! Meeting\n',
            '- [ ] Buy milk\n',
        ]:
            self.assertEqual(roundtrip(line), line)

    def test_refresh_header_preserves_priority(self):
        nodes = parse_str('- [ ] !!! Buy groceries\n')
        nodes[0].task.status = 'done'
        nodes[0].refresh_header()
        self.assertEqual(nodes[0].header, '- [x] !!! Buy groceries\n')


# ── Tags ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTags(unittest.TestCase):

    def test_tag_line_populates_tags(self):
        nodes = parse_str('- [ ] Task\n  #household\n')
        self.assertEqual(nodes[0].task.tags, ['household'])

    def test_multiple_tags(self):
        nodes = parse_str('- [ ] Task\n  #Job-Search #freetime\n')
        self.assertEqual(nodes[0].task.tags, ['Job-Search', 'freetime'])

    def test_tag_node_reference_set(self):
        nodes = parse_str('- [ ] Task\n  #household\n')
        block = nodes[0]
        self.assertIsNotNone(block.tag_node)
        self.assertIs(block.tag_node, block.nodes[0])

    def test_no_tag_line_empty_tags(self):
        nodes = parse_str('- [ ] Task\n  Some notes\n')
        self.assertEqual(nodes[0].task.tags, [])
        self.assertIsNone(nodes[0].tag_node)

    def test_tag_line_roundtrip(self):
        c = '- [ ] Task\n  #household #freetime\n'
        self.assertEqual(roundtrip(c), c)

    def test_tag_line_with_body_notes_roundtrip(self):
        c = '- [ ] Task\n  Some notes\n  #household\n'
        self.assertEqual(roundtrip(c), c)

    def test_prose_with_hash_not_treated_as_tag_line(self):
        nodes = parse_str('- [ ] Task\n  blocked by #3\n')
        self.assertEqual(nodes[0].task.tags, [])

    def test_refresh_tags_updates_existing_tag_line(self):
        nodes = parse_str('- [ ] Task\n  #household\n')
        block = nodes[0]
        block.task.tags = ['household', 'freetime']
        block.refresh_tags()
        self.assertEqual(serialize(nodes), '- [ ] Task\n  #household #freetime\n')

    def test_refresh_tags_inserts_new_tag_line(self):
        nodes = parse_str('- [ ] Task\n  Some notes\n')
        block = nodes[0]
        block.task.tags = ['household']
        block.refresh_tags()
        self.assertEqual(serialize(nodes), '- [ ] Task\n  Some notes\n  #household\n')

    def test_refresh_tags_removes_tag_line_when_empty(self):
        nodes = parse_str('- [ ] Task\n  #household\n')
        block = nodes[0]
        block.task.tags = []
        block.refresh_tags()
        self.assertEqual(serialize(nodes), '- [ ] Task\n')

    def test_priority_and_tags_combined(self):
        c = '- [ ] !!! Buy groceries\n  #household\n'
        nodes = parse_str(c)
        t = nodes[0].task
        self.assertEqual(t.priority, '!!!')
        self.assertEqual(t.title, 'Buy groceries')
        self.assertEqual(t.tags, ['household'])
        self.assertEqual(roundtrip(c), c)

    def test_subtask_tags_independent(self):
        nodes = parse_str('- [ ] Parent\n  - [ ] Child\n    #household\n')
        parent = nodes[0]
        child = parent.nodes[0]
        self.assertEqual(parent.task.tags, [])
        self.assertEqual(child.task.tags, ['household'])


if __name__ == '__main__':
    unittest.main()
