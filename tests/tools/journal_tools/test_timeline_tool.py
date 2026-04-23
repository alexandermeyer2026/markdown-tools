import io
import datetime
import os
import re
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest

from parser.task_parser import TaskParser
from tools.journal_tools.timeline_tool import TimelineTool


FIXTURE = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', '2024-01-15.md')
FIXTURE_DATE = datetime.date(2024, 1, 15)


def strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


class TestGetTimeSlot(unittest.TestCase):
    def test_get_time_slot(self):
        cases = [
            (0, 1.0, 0),    # 0:00
            (60, 1.0, 1),   # 1:00
            (59, 1.0, 0),   # 0:59
            (120, 0.5, 4),  # 2:00
            (121, 0.5, 4),  # 2:01
            (345, 0.5, 11), # 5:45
            (283, 0.25, 18),# 4:43
            (420, 0.25, 28),# 7:00
            (480, 0.25, 32),# 8:00
        ]
        for minutes, step_size_hours, expected in cases:
            with self.subTest(minutes=minutes, step_size_hours=step_size_hours):
                self.assertEqual(TimelineTool.get_time_slot(minutes, step_size_hours), expected)


class TestRenderScale(unittest.TestCase):
    def test_render_scale(self):
        cases = [
            (1.0, 0, 0,
                "0     6     12    18    24\n"
                "▼─────┼─────┼─────┼─────┤\n"
            ),
            (0.5, 0, 14,
                "0     3     6     9     12    15    18    21    24\n"
                "├─────┼─────┼─▼───┼─────┼─────┼─────┼─────┼─────┤\n"
            ),
            (0.25, 0, None,
                "0           3           6           9           12          15          18          21          24\n"
                "├───────────┼───────────┼───────────┼───────────┼───────────┼───────────┼───────────┼───────────┤\n"
            ),
            (1.0, 8, 20,
                "    12    18    24\n"
                "────┼─────┼─▼───┤\n"
            ),
            (0.5, 23, 11,
                " 12    15    18    21    24\n"
                "─┼─────┼─────┼─────┼─────┤\n"
            ),
            (0.25, 14, 28,
                "          6           9           12          15          18          21          24\n"
                "──────────┼───▼───────┼───────────┼───────────┼───────────┼───────────┼───────────┤\n"
            ),
        ]
        for step_size_hours, first_task_slot, now_marker_slot, expected in cases:
            with self.subTest(step_size_hours=step_size_hours, first_task_slot=first_task_slot, now_marker_slot=now_marker_slot):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    TimelineTool.render_scale(step_size_hours=step_size_hours, first_task_slot=first_task_slot, now_marker_slot=now_marker_slot)
                self.assertEqual(buf.getvalue(), expected)


@pytest.mark.integration
class TestIntegration(unittest.TestCase):
    EXPECTED_OUTPUT = (
        "    12    18    24\n"
        "────┼─────┼─────┤\n"
        "█ ✓ 8:00-9:00 Morning routine\n"
        " ██ ○ 9:00-10:30 Work on project\n"
        "  █ ✓ 10:30-11:00 Coffee break\n"
        "   █ ○ 11:00-12:00 Team meeting\n"
        "      █ ○ 14:00 Review PRs\n"
    )

    def setUp(self):
        tasks = TaskParser.parse_file(FIXTURE)
        buf = io.StringIO()
        with patch('shutil.get_terminal_size', return_value=type('T', (), {'columns': 80})()):
            with redirect_stdout(buf):
                TimelineTool.render_timeline(tasks, FIXTURE_DATE, step_size_hours=1.0)
        self.output = strip_ansi(buf.getvalue())

    def test_complete_output(self):
        self.assertEqual(self.output, self.EXPECTED_OUTPUT)

    def test_no_timed_tasks_prints_message(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            TimelineTool.render_timeline([], FIXTURE_DATE)
        self.assertIn('No timed tasks found', buf.getvalue())
