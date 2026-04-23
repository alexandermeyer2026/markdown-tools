import datetime
import io
import os
import re
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from parser.task_parser import TaskParser
from tools.journal_tools.timeline_tool import TimelineTool

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', '2024-01-15.md')
FIXTURE_DATE = datetime.date(2024, 1, 15)

EXPECTED_OUTPUT = (
    "    12    18    24\n"
    "────┼─────┼─────┤\n"
    "█ ✓ 8:00-9:00 Morning routine\n"
    " ██ ○ 9:00-10:30 Work on project\n"
    "  █ ✓ 10:30-11:00 Coffee break\n"
    "   █ ○ 11:00-12:00 Team meeting\n"
    "      █ ○ 14:00 Review PRs\n"
)


def strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


class TestTimelineToolIntegration(unittest.TestCase):
    def setUp(self):
        tasks = TaskParser.parse_file(FIXTURE)
        buf = io.StringIO()
        with patch('shutil.get_terminal_size', return_value=type('T', (), {'columns': 80})()):
            with redirect_stdout(buf):
                TimelineTool.render_timeline(tasks, FIXTURE_DATE, step_size_hours=1.0)
        self.output = strip_ansi(buf.getvalue())

    def test_complete_output(self):
        self.assertEqual(self.output, EXPECTED_OUTPUT)


class TestTimelineToolNoTasks(unittest.TestCase):
    def test_no_timed_tasks_prints_message(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            TimelineTool.render_timeline([], FIXTURE_DATE)
        self.assertIn('No timed tasks found', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
