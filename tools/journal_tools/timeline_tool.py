import datetime
import os
import shutil

from models import Task
from os_utils import FileFinder, resolve_date
from parser import TaskParser
from tools.journal_tools.rendering import (
    STATUS_ICONS, STATUS_COLORS, GRAY, RESET,
    get_minutes, get_time_slot, scale_lines, subtask_rows,
)

_STEP_SIZES = [0.25, 0.5, 1]


class TimelineTool:

    @staticmethod
    def run(args, directory='.'):
        if not args:
            print("Usage: main.py journal timeline <today|yesterday|tomorrow|YYYY-MM-DD|file>")
            return
        input_file = args[0]
        basename = os.path.basename(input_file)

        date = resolve_date(basename) or FileFinder.get_journal_file_date(input_file)

        if date:
            directory = os.path.dirname(input_file) or directory
            if journal_files := FileFinder.find_journal_files(
                directory,
                date_from=date,
                date_to=date
            ):
                input_file = journal_files[0]
            else:
                print(f"No journal files for {date} found")
                return
        else:
            if not os.path.exists(input_file):
                print(f"File {input_file} does not exist")
                return

        tasks = TaskParser.parse_file(input_file)
        TimelineTool.render_timeline(tasks, date=date)

    @staticmethod
    def render_scale(step_size_hours: float, first_task_slot: int, now_marker_slot: int) -> None:
        hours_line, scale_line = scale_lines(step_size_hours, first_task_slot, now_marker_slot)
        print(hours_line)
        print(scale_line)

    @staticmethod
    def _step_size_for_width(first_task_minutes: int, width: int) -> float:
        for step in _STEP_SIZES:
            first_slot = get_time_slot(first_task_minutes, step)
            if int(24 / step) - first_slot <= width:
                return step
        return _STEP_SIZES[-1]

    @staticmethod
    def render_task(task: Task, step_size_hours: float, first_task_slot: int, now_marker_slot: int) -> str:
        start_minutes = get_minutes(task.time.start)
        start_slot = end_slot = get_time_slot(start_minutes, step_size_hours)
        if task.time.end:
            end_minutes = get_minutes(task.time.end)
            end_slot = get_time_slot(end_minutes - 1, step_size_hours)

        line = ' ' * start_slot
        bar = '█' * max(end_slot - start_slot + 1, 1)

        if (now_marker_slot is not None and start_slot <= now_marker_slot <= end_slot) and task.status == 'todo':
            line += bar
        elif task.status not in STATUS_COLORS:
            line += GRAY + bar + RESET
        else:
            line += STATUS_COLORS[task.status] + bar + RESET

        line += ' ' + STATUS_ICONS.get(task.status, '?')
        line += ' ' + task.time.to_str()
        line += ' \033[1m' + task.title + '\033[0m'
        line = line[first_task_slot:]

        return line

    @staticmethod
    def _icon_col(task: Task, step_size_hours: float, first_task_slot: int) -> int:
        start_slot = get_time_slot(get_minutes(task.time.start), step_size_hours)
        end_slot = start_slot
        if task.time.end:
            end_slot = get_time_slot(get_minutes(task.time.end) - 1, step_size_hours)
        bar_width = max(end_slot - start_slot + 1, 1)
        return (start_slot - first_task_slot) + bar_width + 1

    @staticmethod
    def render_timeline_lines(tasks: list[Task], date: datetime.date, width: int) -> list[str]:
        timed_tasks = [x for x in tasks if x.time and x.time.start and x.parent is None]
        timed_tasks.sort(key=lambda x: get_minutes(x.time.start))

        if not timed_tasks:
            return ["No timed tasks found"]

        first_task_minutes = get_minutes(timed_tasks[0].time.start)
        step = TimelineTool._step_size_for_width(first_task_minutes, width)
        first_task_slot = get_time_slot(first_task_minutes, step)

        now_marker_slot = None
        if date == datetime.date.today():
            now = datetime.datetime.now()
            now_marker_slot = get_time_slot(now.hour * 60 + now.minute, step)

        hours_line, scale_line = scale_lines(step, first_task_slot, now_marker_slot)
        lines = [hours_line, scale_line]
        for task in timed_tasks:
            lines.append(TimelineTool.render_task(task, step, first_task_slot, now_marker_slot))
            lines.extend(subtask_rows(task, left_pad=TimelineTool._icon_col(task, step, first_task_slot)))

        return lines

    @staticmethod
    def render_timeline(tasks: list[Task], date: datetime.date) -> None:
        try:
            width = shutil.get_terminal_size().columns
        except (OSError, AttributeError):
            width = 80
        for line in TimelineTool.render_timeline_lines(tasks, date, width):
            print(line)
