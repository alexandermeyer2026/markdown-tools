import os
import tempfile
import unittest
from unittest.mock import patch

import pytest

from parser.task_parser import TaskParser
from tools.journal_tools.catch_up_tool import CatchUpTool


FIXTURE = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'journal', '2024-01-15.md')

with open(FIXTURE, encoding='utf-8') as f:
    ORIGINAL = f.read()


@pytest.mark.integration
class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        self.tmp.write(ORIGINAL)
        self.tmp.close()
        self.path = self.tmp.name
        self.directory = os.path.dirname(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def _open_tasks(self):
        tasks = TaskParser.parse_file(self.path)
        return [t for t in tasks if t.status in ('todo', 'in progress')]

    def _read(self):
        with open(self.path, encoding='utf-8') as f:
            return f.read()

    def _run(self, inputs):
        with patch('builtins.input', side_effect=inputs):
            CatchUpTool.interactive_cleanup(self.directory, self.path, self._open_tasks())

    def test_mark_all_done(self):
        self._run(['d', 'd', 'd', 'y'])
        self.assertEqual(self._read(), (
            "# Journal 2024-01-15\n"
            "\n"
            "- [x] 8:00-9:00 Morning routine\n"
            "- [x] 9:00-10:30 Work on project\n"
            "- [x] 10:30-11:00: Coffee break\n"
            "- [x] 11:00-12:00 Team meeting\n"
            "- [x] 14:00 Review PRs\n"
        ))

    def test_skip_all_leaves_file_unchanged(self):
        self._run(['s', 's', 's'])
        self.assertEqual(self._read(), ORIGINAL)

    def test_mark_first_done_skip_rest(self):
        self._run(['d', 's', 's', 'y'])
        self.assertEqual(self._read(), (
            "# Journal 2024-01-15\n"
            "\n"
            "- [x] 8:00-9:00 Morning routine\n"
            "- [x] 9:00-10:30 Work on project\n"
            "- [x] 10:30-11:00: Coffee break\n"
            "- [ ] 11:00-12:00: Team meeting\n"
            "- [ ] 14:00 Review PRs\n"
        ))

    def test_mark_first_failed(self):
        self._run(['f', 's', 's', 'y'])
        self.assertEqual(self._read(), (
            "# Journal 2024-01-15\n"
            "\n"
            "- [x] 8:00-9:00 Morning routine\n"
            "- [–] 9:00-10:30 Work on project\n"
            "- [x] 10:30-11:00: Coffee break\n"
            "- [ ] 11:00-12:00: Team meeting\n"
            "- [ ] 14:00 Review PRs\n"
        ))

    def test_quit_discard_leaves_file_unchanged(self):
        self._run(['d', 'q', 'n'])
        self.assertEqual(self._read(), ORIGINAL)

    def test_quit_save_applies_partial_changes(self):
        self._run(['d', 'q', 'y'])
        self.assertEqual(self._read(), (
            "# Journal 2024-01-15\n"
            "\n"
            "- [x] 8:00-9:00 Morning routine\n"
            "- [x] 9:00-10:30 Work on project\n"
            "- [x] 10:30-11:00: Coffee break\n"
            "- [ ] 11:00-12:00: Team meeting\n"
            "- [ ] 14:00 Review PRs\n"
        ))

    def test_confirm_discard_leaves_file_unchanged(self):
        self._run(['d', 'd', 'd', 'n'])
        self.assertEqual(self._read(), ORIGINAL)

    def test_colon_separator_normalized_on_write(self):
        self._run(['s', 'd', 's', 'y'])
        content = self._read()
        self.assertIn('- [x] 11:00-12:00 Team meeting\n', content)
        self.assertNotIn('11:00-12:00:', content)
