import io
import datetime
import os
import re
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest

from parser.file_model import parse, populate_task_relations, all_tasks
from tools.journal_tools.rendering import get_time_slot
from tools.journal_tools.timeline_tool import TimelineTool


FIXTURE = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'journal', '2024-01-15.md')
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
                self.assertEqual(get_time_slot(minutes, step_size_hours), expected)


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


class TestStepSizeSelection(unittest.TestCase):
    def test_quarter_hour_step(self):
        self.assertEqual(TimelineTool._step_size_for_width(480, 80), 0.25)

    def test_half_hour_step(self):
        self.assertEqual(TimelineTool._step_size_for_width(480, 50), 0.5)

    def test_one_hour_step(self):
        self.assertEqual(TimelineTool._step_size_for_width(480, 20), 1.0)


@pytest.mark.integration
class TestIntegration(unittest.TestCase):
    EXPECTED_OUTPUT = (
        "    9           12          15          18          21          24\n"
        "────┼───────────┼───────────┼───────────┼───────────┼───────────┤\n"
        "████ ✓ 8:00-9:00 Morning routine\n"
        "    ██████ ○ 9:00-10:30 Work on project\n"
        "          ██ ✓ 10:30-11:00 Coffee break\n"
        "            ████ ○ 11:00-12:00 Team meeting\n"
        "                        █ ○ 14:00 Review PRs\n"
    )

    def setUp(self):
        nodes = parse(FIXTURE); populate_task_relations(nodes); tasks = all_tasks(nodes)
        buf = io.StringIO()
        with patch('shutil.get_terminal_size', return_value=type('T', (), {'columns': 80})()):
            with redirect_stdout(buf):
                TimelineTool.render_timeline(tasks, FIXTURE_DATE)
        self.output = strip_ansi(buf.getvalue())

    def test_complete_output(self):
        self.assertEqual(self.output, self.EXPECTED_OUTPUT)

    def test_no_timed_tasks_prints_message(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            TimelineTool.render_timeline([], FIXTURE_DATE)
        self.assertIn('No timed tasks found', buf.getvalue())


@pytest.mark.integration
class TestIntegrationHalfHourStep(unittest.TestCase):
    """width=50 forces step=0.5 (30-minute slots); verifies scale and bar alignment."""

    EXPECTED_OUTPUT = (
        "  9     12    15    18    21    24\n"
        "──┼─────┼─────┼─────┼─────┼─────┤\n"
        "██ ✓ 8:00-9:00 Morning routine\n"
        "  ███ ○ 9:00-10:30 Work on project\n"
        "     █ ✓ 10:30-11:00 Coffee break\n"
        "      ██ ○ 11:00-12:00 Team meeting\n"
        "            █ ○ 14:00 Review PRs\n"
    )

    def setUp(self):
        nodes = parse(FIXTURE); populate_task_relations(nodes); tasks = all_tasks(nodes)
        buf = io.StringIO()
        with patch('shutil.get_terminal_size', return_value=type('T', (), {'columns': 50})()):
            with redirect_stdout(buf):
                TimelineTool.render_timeline(tasks, FIXTURE_DATE)
        self.output = strip_ansi(buf.getvalue())

    def test_complete_output(self):
        self.assertEqual(self.output, self.EXPECTED_OUTPUT)


@pytest.mark.integration
class TestIntegrationHourStep(unittest.TestCase):
    """width=20 forces step=1.0 (hourly slots); verifies scale and bar alignment."""

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
        nodes = parse(FIXTURE); populate_task_relations(nodes); tasks = all_tasks(nodes)
        buf = io.StringIO()
        with patch('shutil.get_terminal_size', return_value=type('T', (), {'columns': 20})()):
            with redirect_stdout(buf):
                TimelineTool.render_timeline(tasks, FIXTURE_DATE)
        self.output = strip_ansi(buf.getvalue())

    def test_complete_output(self):
        self.assertEqual(self.output, self.EXPECTED_OUTPUT)
