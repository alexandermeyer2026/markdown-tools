import datetime
import math
import os
import re
import shutil

from models import Task
from os_utils import FileFinder
from parser import TaskParser


class TimelineTool:
    @staticmethod
    def run(args, directory='.'):
        if not args:
            print("Usage: main.py journal timeline <today|yesterday|tomorrow|YYYY-MM-DD|file>")
            return
        input_file = args[0]
        basename = os.path.basename(input_file)

        if basename.lower() == 'today':
            date = datetime.date.today()
        elif basename.lower() == 'tomorrow':
            date = datetime.date.today() + datetime.timedelta(days=1)
        elif basename.lower() == 'yesterday':
            date = datetime.date.today() - datetime.timedelta(days=1)
        else:
            date = FileFinder.get_journal_file_date(input_file)

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
        TimelineTool.render_timeline(tasks, date=date, step_size_hours=0.25)

    @staticmethod
    def get_minutes(time_str: str) -> int:
        if not time_str:
            return
        m = re.match(r'(\d{1,2}):(\d{2})', time_str)
        if not m:
            raise ValueError(f"Invalid time string: {time_str}")
        hours = int(m.group(1))
        minutes = int(m.group(2))
        return hours * 60 + minutes

    @staticmethod
    def get_time_slot(minutes: int, step_size_hours: float) -> int:
        # slot is 0-based index of the time slot (e. g. 0)
        return math.floor(minutes / 60 / step_size_hours)

    @staticmethod
    def truncate(string: str, max_len: int) -> str:
        if len(string) > max_len:
            return string[:max_len-3] + "..."
        return string

    @staticmethod
    def validate_step_size(step_size_hours: float) -> None:
        STEP_SIZES = [0.25, 0.5, 1]
        if step_size_hours not in STEP_SIZES:
            raise ValueError(
                f"Invalid step size: {step_size_hours}"
                f" (valid sizes: {STEP_SIZES})"
            )

    @staticmethod
    def render_scale(step_size_hours: float, first_task_slot: int, now_marker_slot: int) -> None:
        timeline_width = int(24 / step_size_hours)
        marker_time_step = 6 * step_size_hours
        markers = [h for h in range(24) if h % marker_time_step == 0]
        marker_width = timeline_width // len(markers)
        hours = ''
        scale = ''
        for marker in markers:
            hours += str(marker).ljust(marker_width)
            scale += '┼' + '─' * (marker_width - 1)
        scale = '├' + scale[1:] + '┤'
        if now_marker_slot is not None:
            scale = scale[:now_marker_slot] + '▼' + scale[now_marker_slot+1:]
        hours = hours + '24'
        print(hours[first_task_slot:])
        print(scale[first_task_slot:])

    @staticmethod
    def render_task(task: Task, step_size_hours: float, terminal_width: int, first_task_slot: int, now_marker_slot: int) -> str:
        STATUS_ICONS = {
            'todo': '○',
            'in progress': '◐',
            'done': '✓',
            'failed': '✗'
        }
        STATUS_COLORS = {
            'todo': '\x1b[90m',  # gray
            'in progress': '\x1b[34m',  # blue
            'done': '\x1b[32m',  # green
            'failed': '\x1b[31m'  # red
        }

        start_minutes = TimelineTool.get_minutes(task.time.start)
        start_slot = end_slot = TimelineTool.get_time_slot(start_minutes, step_size_hours)
        if task.time.end:
            end_minutes = TimelineTool.get_minutes(task.time.end)
            end_slot = TimelineTool.get_time_slot(end_minutes-1, step_size_hours)  # Make sure 8:00-10:00 is 2 slots, not 3

        line = ' ' * start_slot
        bar = '█' * max(end_slot - start_slot + 1, 1)

        if (now_marker_slot is not None and start_slot <= now_marker_slot <= end_slot) and task.status == 'todo':
            line += bar
        elif task.status not in STATUS_COLORS:
            line += '\x1b[90m' + bar + '\x1b[0m'
        else:
            line += STATUS_COLORS[task.status] + bar + '\x1b[0m'

        task_icon = STATUS_ICONS.get(task.status, '?')
        line += ' ' + task_icon
        line += ' ' + task.time.to_str()
        line += ' ' + '\033[1m' + task.title + '\033[0m'
        line = line[first_task_slot:]

        return line

    @staticmethod
    def render_tasks(timed_tasks: list[Task], step_size_hours: float, terminal_width: int, first_task_slot: int, now_marker_slot: int) -> None:
        for task in timed_tasks:
            line = TimelineTool.render_task(task, step_size_hours, terminal_width, first_task_slot, now_marker_slot)
            print(line)

    @staticmethod
    def render_timeline(tasks: list[Task], date: datetime.date, step_size_hours: float = 1) -> None:

        TimelineTool.validate_step_size(step_size_hours)

        try:
            terminal_width = shutil.get_terminal_size().columns
        except (OSError, AttributeError):
            terminal_width = 80

        timed_tasks = [x for x in tasks if x.time and x.time.start]
        timed_tasks.sort(key=lambda x: TimelineTool.get_minutes(x.time.start))

        if not timed_tasks:
            print("No timed tasks found")
            return

        first_task = timed_tasks[0]
        first_task_minutes = TimelineTool.get_minutes(first_task.time.start)
        first_task_slot = TimelineTool.get_time_slot(first_task_minutes, step_size_hours)

        now_marker_slot = None
        if date == datetime.date.today():
            current_hour = datetime.datetime.now().hour
            current_minutes = current_hour * 60 + datetime.datetime.now().minute
            now_marker_slot = TimelineTool.get_time_slot(current_minutes, step_size_hours)

        TimelineTool.render_scale(step_size_hours, first_task_slot, now_marker_slot)
        TimelineTool.render_tasks(timed_tasks, step_size_hours, terminal_width, first_task_slot, now_marker_slot)
