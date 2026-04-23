import io
import datetime
import unittest
from contextlib import redirect_stdout

from tools.journal_tools.timeline_tool import TimelineTool


class TestTimelineTool(unittest.TestCase):
    def test_get_time_slot(self):
        # slots are 0-based index, e. g. 1st hour (0:xx) is 0
        cases = [
            (0, 1.0, 0),  # 0:00
            (60, 1.0, 1),  # 1:00
            (59, 1.0, 0),  # 0:59
            (120, 0.5, 4),  # 2:00
            (121, 0.5, 4),  # 2:01
            (345, 0.5, 11),  # 5:45
            (283, 0.25, 18),  # 4:43
            (420, 0.25, 28),  # 7:00
            (480, 0.25, 32),  # 8:00
        ]
        for minutes, step_size_hours, expected in cases:
            with self.subTest(minutes=minutes, step_size_hours=step_size_hours):
                self.assertEqual(TimelineTool.get_time_slot(minutes, step_size_hours), expected)

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
